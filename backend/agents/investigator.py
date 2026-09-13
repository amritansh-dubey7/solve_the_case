"""
Investigator Agent for "Solve the Case".

Loop (per the fixed spec):
  1. Form an initial theory (LLM call naming a suspect_id + rough
     hypothesis) using the graph + case summary.
  2. Retrieve evidence via hybrid_search using a query derived from the
     theory.
  3. Evaluate whether evidence is sufficient (require a minimum number of
     *verified* supporting citations covering motive/means/opportunity;
     unverified documents may be noted but must not count toward
     sufficiency).
  4. If insufficient, reformulate the query (target the missing motive/
     means/opportunity gap) and retry. Hard cap: 3 retries total.
  5. Return an InvestigationResult.

Design notes / assumptions (not fully pinned down by the fixed spec, so
documented here explicitly):

- Sufficiency rule: at least one VERIFIED citation covering each of
  motive, means, and opportunity (REQUIRED_CATEGORIES below). Unverified
  (verified: false) evidence is still surfaced in the citations list and
  in reasoning_trace as an "unverified lead", but never counts toward
  meeting a category and never overrides a verified fact per rule #1 in
  the fixed spec's NON-NEGOTIABLE RULES.
- suspect_id format: this implementation uses the graph's entity_id for
  the accused person (e.g. "elena_rodriguez") when the graph has person
  entities to constrain the LLM's choice to, since that's the only
  grounded identifier space available at this phase. If the graph is
  still empty (no /ingest run with a real API key yet), the theory LLM
  call names a suspect based on a person mentioned in the retrieved case
  evidence instead, and slugs their name the same way llm_client's
  extraction prompt does. NOTE: this will not automatically match
  whatever key convention ground_truth.json uses internally (that file is
  backend-only and untouched here) — reconciling the two is Phase 6's
  problem (/submit_verdict), not this phase's.
- Every citation returned is guaranteed to reference a document_id that
  was actually returned by hybrid_search during this same investigation
  run (tracked via `_seen_document_ids` below) — citations referencing
  anything else are dropped, per NON-NEGOTIABLE RULE #2.
"""

import json
import logging
import os

import networkx as nx

import llm_client
from ingestion import GRAPH_OUTPUT_PATH
from retrieval import hybrid_search
from schemas import Citation, InvestigationResult

logger = logging.getLogger(__name__)

REQUIRED_CATEGORIES = ("motive", "means", "opportunity")
MAX_RETRIES = 3
RETRIEVAL_K = 8
CASE_OVERVIEW_QUERY = "murder victim suspect motive means opportunity evidence"
CASE_OVERVIEW_K = 10
MAX_GRAPH_PERSON_ENTITIES = 30


def _load_graph() -> nx.MultiDiGraph:
    """Load the entity graph saved by ingestion.py, or an empty graph if it
    doesn't exist yet / hasn't been populated by a real /ingest run."""
    if not os.path.exists(GRAPH_OUTPUT_PATH):
        return nx.MultiDiGraph()
    with open(GRAPH_OUTPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    try:
        return nx.node_link_graph(data, edges="edges")
    except TypeError:
        # older networkx versions don't take the `edges` kwarg
        return nx.node_link_graph(data)


def _graph_person_candidates(graph: nx.MultiDiGraph) -> list[str]:
    """Return entity_ids of nodes typed 'person' in the graph, capped."""
    person_ids = [
        node_id
        for node_id, attrs in graph.nodes(data=True)
        if attrs.get("type") == "person"
    ]
    return person_ids[:MAX_GRAPH_PERSON_ENTITIES]


def _graph_summary(graph: nx.MultiDiGraph) -> str:
    """Render a compact text summary of person entities + their
    relationships, for grounding the theory-forming LLM call."""
    if graph.number_of_nodes() == 0:
        return ""

    lines = []
    person_ids = _graph_person_candidates(graph)
    for node_id in person_ids:
        attrs = graph.nodes[node_id]
        aliases = attrs.get("aliases") or []
        alias_text = f" (aka {', '.join(aliases)})" if aliases else ""
        lines.append(f"- {node_id}: {attrs.get('name', node_id)}{alias_text}")

    edge_lines = []
    for source, target, attrs in graph.edges(data=True):
        if source in person_ids or target in person_ids:
            edge_lines.append(
                f"- {source} -[{attrs.get('relation', '?')}]-> {target} "
                f"(doc {attrs.get('document_id', '?')}, verified={attrs.get('verified', False)})"
            )

    summary = "PERSON ENTITIES:\n" + ("\n".join(lines) if lines else "(none)")
    summary += "\n\nRELEVANT RELATIONSHIPS:\n" + ("\n".join(edge_lines[:40]) if edge_lines else "(none)")
    return summary


def _case_overview() -> tuple[str, set[str]]:
    """
    Pull a broad set of top hybrid_search hits as an initial case overview
    for theory-forming. Returns (overview_text, document_ids_seen).
    """
    results = hybrid_search(CASE_OVERVIEW_QUERY, CASE_OVERVIEW_K)
    lines = [
        f"[{r['document_id']}] (verified={r['verified']}): {r['text'][:400]}"
        for r in results
    ]
    return "\n".join(lines), {r["document_id"] for r in results}


def _fallback_query(suspect_id: str, missing: list[str]) -> str:
    """Deterministic query fallback if a judge/theory LLM call fails
    outright (e.g. no API key configured) — keeps the loop from crashing."""
    if missing:
        return f"{suspect_id} {' '.join(missing)}"
    return suspect_id


def run_investigation() -> InvestigationResult:
    """
    Run the full Investigator loop and return a validated InvestigationResult.
    """
    reasoning_trace: list[str] = []
    seen_document_ids: set[str] = set()

    graph = _load_graph()
    graph_summary = _graph_summary(graph)
    candidate_suspects = _graph_person_candidates(graph)

    case_overview, overview_doc_ids = _case_overview()
    seen_document_ids |= overview_doc_ids
    reasoning_trace.append(
        f"Pulled case overview via hybrid_search({CASE_OVERVIEW_QUERY!r}, k={CASE_OVERVIEW_K}); "
        f"{len(overview_doc_ids)} documents surfaced."
    )

    theory_response = llm_client.call_llm_theory(case_overview, graph_summary, candidate_suspects or None)
    if theory_response is None:
        reasoning_trace.append(
            "call_llm_theory failed (no/invalid LLM response) — cannot form a theory. "
            "Returning a low-confidence, unresolved result."
        )
        return InvestigationResult(
            theory="Unable to form a theory: the LLM call failed. Check ANTHROPIC_API_KEY in .env.",
            suspect_id="unknown",
            confidence=0.0,
            citations=[],
            needs_more_evidence=True,
            retries_used=0,
            reasoning_trace=reasoning_trace,
        )

    suspect_id = theory_response["suspect_id"]
    theory = theory_response["theory"]
    query = theory_response["initial_query"]
    reasoning_trace.append(
        f"Initial theory formed: suspect_id={suspect_id!r} ({theory_response.get('suspect_name', '?')}). "
        f"Theory: {theory}"
    )
    reasoning_trace.append(f"Initial search query: {query!r}")

    citations: list[Citation] = []
    citation_keys_seen: set[tuple[str, str]] = set()  # (document_id, claim) dedup
    covered_categories: set[str] = set()
    used_unverified = False
    retries_used = 0

    while True:
        raw_results = hybrid_search(query, RETRIEVAL_K)
        seen_document_ids |= {r["document_id"] for r in raw_results}
        reasoning_trace.append(
            f"[Round {retries_used}] hybrid_search({query!r}, k={RETRIEVAL_K}) -> "
            f"{len(raw_results)} candidates."
        )

        judgement = llm_client.call_llm_judge_evidence(
            theory, suspect_id, raw_results, sorted(covered_categories)
        )

        if judgement is None:
            reasoning_trace.append(
                "[Round {}] call_llm_judge_evidence failed — treating this round's "
                "evidence as untagged and stopping retries early.".format(retries_used)
            )
            break

        verified_by_doc_id = {r["document_id"]: r["verified"] for r in raw_results}
        for tag in judgement.get("tagged", []):
            doc_id = tag.get("document_id")
            category = tag.get("category")
            claim = tag.get("claim", "")
            if doc_id not in verified_by_doc_id:
                # Guard against the judge inventing a document_id that
                # wasn't actually in this round's candidates.
                reasoning_trace.append(
                    f"[Round {retries_used}] Dropped a tagged citation referencing "
                    f"unretrieved document_id={doc_id!r}."
                )
                continue
            if category not in REQUIRED_CATEGORIES:
                continue

            verified = verified_by_doc_id[doc_id]
            key = (doc_id, claim)
            if key not in citation_keys_seen:
                citation_keys_seen.add(key)
                citations.append(Citation(document_id=doc_id, claim=claim, verified=verified))
                if verified:
                    covered_categories.add(category)
                else:
                    used_unverified = True
                    reasoning_trace.append(
                        f"[Round {retries_used}] Noted UNVERIFIED lead for '{category}': "
                        f"document_id={doc_id} — not counted toward sufficiency."
                    )

        sufficient = set(REQUIRED_CATEGORIES).issubset(covered_categories)
        reasoning_trace.append(
            f"[Round {retries_used}] Verified categories covered so far: "
            f"{sorted(covered_categories) or 'none'}. Sufficient: {sufficient}."
        )

        if sufficient:
            break
        if retries_used >= MAX_RETRIES:
            reasoning_trace.append(
                f"Hit hard cap of {MAX_RETRIES} retries without covering all of "
                f"{REQUIRED_CATEGORIES} with verified evidence."
            )
            break

        missing = judgement.get("missing_categories") or sorted(set(REQUIRED_CATEGORIES) - covered_categories)
        next_query = judgement.get("next_query") or _fallback_query(suspect_id, missing)
        reasoning_trace.append(
            f"[Round {retries_used}] Insufficient. Missing: {missing}. "
            f"Reformulated query: {next_query!r}."
        )
        query = next_query
        retries_used += 1

    # Final safety net for NON-NEGOTIABLE RULE #2: every returned citation
    # must reference a document_id actually retrieved in this run.
    citations = [c for c in citations if c.document_id in seen_document_ids]

    needs_more_evidence = not set(REQUIRED_CATEGORIES).issubset(covered_categories)

    confidence = 0.9
    confidence -= 0.1 * retries_used
    if needs_more_evidence:
        confidence -= 0.25
    if used_unverified:
        confidence -= 0.15
        reasoning_trace.append("Confidence lowered because unverified evidence was encountered/used as a lead.")
    confidence = max(0.05, min(0.95, round(confidence, 2)))

    reasoning_trace.append(
        f"Final: suspect_id={suspect_id}, confidence={confidence}, "
        f"retries_used={retries_used}, needs_more_evidence={needs_more_evidence}, "
        f"citations={len(citations)}."
    )

    return InvestigationResult(
        theory=theory,
        suspect_id=suspect_id,
        confidence=confidence,
        citations=citations,
        needs_more_evidence=needs_more_evidence,
        retries_used=retries_used,
        reasoning_trace=reasoning_trace,
    )

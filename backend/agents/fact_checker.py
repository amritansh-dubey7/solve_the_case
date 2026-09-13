"""
Fact-Checker Agent for "Solve the Case".

Given an InvestigationResult (the Investigator's theory + suspect_id +
citations), this agent runs a genuinely separate, adversarial search pass:

  1. Timeline-conflict search: negate the theory's stated timeline/sequence
     and search hybrid_search for evidence placing the suspect elsewhere,
     or events out of the order the theory assumes.
  2. Alternative-suspect search: walk the entity graph for OTHER person
     entities with motive/opportunity-shaped edges (financial disputes,
     threats, presence at the scene, etc.), independent of the suspect the
     Investigator picked, then search for supporting evidence on each.
  3. Citation-undermining search: pick a specific citation the Investigator
     used and search for documents that conflict with or contradict that
     exact claim.

None of these queries are paraphrases of the Investigator's own queries —
they are constructed by negating the theory, naming other suspects, and
targeting timeframe conflicts, per the phase's explicit adversarial
requirement.

Design notes (undocumented by the fixed spec, so pinned down here):
- Every Citation this agent returns (in `contradictions`) references a
  document_id that was actually retrieved by one of THIS agent's own
  hybrid_search calls in this run — same NON-NEGOTIABLE RULE #2 as the
  Investigator, enforced independently here since this is a separate call.
- Per NON-NEGOTIABLE RULE #1, unverified (verified: false) documents are
  never returned as `contradictions` (which would let them masquerade as
  established counter-evidence); they may only surface as free-text notes
  inside `weaknesses` (e.g. "unverified lead worth checking: ...").
- `alternative_suspects` are graph entity_ids of person entities with
  motive/opportunity-shaped edges, other than the Investigator's
  suspect_id, that survive being cross-checked against retrieval (i.e. we
  don't just list every other person node in the graph un-evidenced).
- `confidence_delta` is a signed adjustment (negative = weakens the
  Investigator's theory) derived from how many independent contradiction
  categories this pass turned up (timeline conflict / rival suspect /
  citation rebuttal), capped in [-0.9, 0.0]. This agent's job is
  adversarial, so it never returns a positive delta.
"""

import json
import logging
import os

import networkx as nx

import llm_client
from ingestion import GRAPH_OUTPUT_PATH
from retrieval import hybrid_search
from schemas import Citation, FactCheckResult, InvestigationResult

logger = logging.getLogger(__name__)

RETRIEVAL_K = 6
MAX_ALT_SUSPECT_CANDIDATES = 6
MOTIVE_OPPORTUNITY_RELATIONS = (
    "suspected_of",
    "threatened",
    "argued_with",
    "owed_money_by",
    "owes_money_to",
    "had_affair_with",
    "witnessed",
    "present_at",
    "employed_by",
    "fired_by",
    "rival_of",
)


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
        return nx.node_link_graph(data)


def _graph_alt_suspect_candidates(graph: nx.MultiDiGraph, exclude_suspect_id: str) -> list[dict]:
    """
    Walk the graph for person entities (other than exclude_suspect_id) that
    have at least one motive/opportunity-shaped edge, per
    MOTIVE_OPPORTUNITY_RELATIONS. Returns a list of
    {entity_id, name, relation, document_id, verified} — one entry per
    qualifying edge (capped), independent of anything the Investigator used.
    """
    if graph.number_of_nodes() == 0:
        return []

    candidates: list[dict] = []
    seen_entity_ids: set[str] = set()

    for source, target, attrs in graph.edges(data=True):
        relation = attrs.get("relation", "")
        if relation not in MOTIVE_OPPORTUNITY_RELATIONS:
            continue
        # Only the SOURCE of a motive/opportunity-shaped edge is a person of
        # interest (the one suspected, threatening, owing money, etc.) — the
        # target is frequently the victim themself (e.g. "elena
        # -suspected_of-> marcus", the murder victim) and must never be
        # surfaced as an "alternative suspect" against themselves.
        node_id = source
        if node_id == exclude_suspect_id:
            continue
        node_attrs = graph.nodes.get(node_id, {})
        if node_attrs.get("type") != "person":
            continue
        if node_id in seen_entity_ids:
            continue
        seen_entity_ids.add(node_id)
        candidates.append(
            {
                "entity_id": node_id,
                "name": node_attrs.get("name", node_id),
                "relation": relation,
                "document_id": attrs.get("document_id", "?"),
                "verified": attrs.get("verified", False),
            }
        )
        if len(candidates) >= MAX_ALT_SUSPECT_CANDIDATES:
            return candidates
    return candidates


def _negated_timeline_queries(theory: str, suspect_id: str) -> list[str]:
    """
    Build adversarial timeline-conflict queries by negating the theory's
    premise, rather than paraphrasing the Investigator's own search terms.
    """
    return [
        f"{suspect_id} alibi elsewhere different time",
        f"{suspect_id} seen somewhere else at time of crime",
        "timeline discrepancy contradicts sequence of events",
    ]


def _citation_undermining_query(citation: Citation) -> str:
    """
    Build a query targeting evidence that conflicts with a specific
    citation's claim — negate/contest the claim rather than re-searching it.
    """
    return f"contradicts disputes denies not true: {citation.claim}"[:300]


def _dedupe_citation(citations: list[Citation], seen_keys: set[tuple[str, str]], candidate: Citation) -> bool:
    key = (candidate.document_id, candidate.claim)
    if key in seen_keys:
        return False
    seen_keys.add(key)
    citations.append(candidate)
    return True


def run_fact_check(investigation: InvestigationResult) -> FactCheckResult:
    """
    Run the full adversarial Fact-Checker pass against an InvestigationResult
    and return a validated FactCheckResult.
    """
    seen_document_ids: set[str] = set()
    contradictions: list[Citation] = []
    contradiction_keys: set[tuple[str, str]] = set()
    weaknesses: list[str] = []
    contradiction_category_hits = 0  # timeline / alt-suspect / citation-rebuttal, each counted once

    theory = investigation.theory
    suspect_id = investigation.suspect_id

    # --- 1. Timeline-conflict search (negate the theory) ---
    timeline_hit_this_round = False
    for query in _negated_timeline_queries(theory, suspect_id):
        results = hybrid_search(query, RETRIEVAL_K)
        seen_document_ids |= {r["document_id"] for r in results}
        for r in results[:2]:  # keep only the strongest hit(s) per query, not the whole pool
            if not r["verified"]:
                weaknesses.append(
                    f"Unverified lead worth checking for a timeline conflict "
                    f"(document_id={r['document_id']}): {r['text'][:200]}"
                )
                continue
            claim = f"Possible timeline conflict: {r['text'][:250]}"
            if _dedupe_citation(contradictions, contradiction_keys, Citation(
                document_id=r["document_id"], claim=claim, verified=True,
            )):
                timeline_hit_this_round = True
    if timeline_hit_this_round:
        contradiction_category_hits += 1

    # --- 2. Alternative-suspect search (graph, independent of the theory) ---
    graph = _load_graph()
    alt_candidates = _graph_alt_suspect_candidates(graph, suspect_id)
    alternative_suspects: list[str] = []
    alt_suspect_hit = False
    for cand in alt_candidates:
        query = f"{cand['name']} motive opportunity suspect"
        results = hybrid_search(query, RETRIEVAL_K)
        seen_document_ids |= {r["document_id"] for r in results}

        # Require the candidate's own name to actually appear in the
        # matched text — otherwise a generic document (e.g. a vague news
        # article mentioning "suspect" with no names) could spuriously
        # "support" every candidate purely on keyword overlap with the
        # query terms, which isn't genuine evidence for that specific person.
        name_tokens = [t.lower() for t in cand["name"].split() if len(t) > 2]
        verified_support = [
            r for r in results
            if r["verified"] and any(tok in r["text"].lower() for tok in name_tokens)
        ][:1]
        if verified_support:
            alternative_suspects.append(cand["entity_id"])
            alt_suspect_hit = True
            r = verified_support[0]
            claim = (
                f"{cand['name']} also has a motive/opportunity link "
                f"({cand['relation']}): {r['text'][:200]}"
            )
            _dedupe_citation(contradictions, contradiction_keys, Citation(
                document_id=r["document_id"], claim=claim, verified=True,
            ))
        else:
            weaknesses.append(
                f"{cand['name']} ({cand['entity_id']}) has an unresolved "
                f"'{cand['relation']}' link in the graph (doc {cand['document_id']}, "
                f"verified={cand['verified']}) that the Investigator's theory doesn't address."
            )
    if alt_suspect_hit:
        contradiction_category_hits += 1

    # --- 3. Undermine a specific citation the Investigator used ---
    citation_rebuttal_hit = False
    target_citation = next((c for c in investigation.citations if c.verified), None)
    if target_citation is not None:
        query = _citation_undermining_query(target_citation)
        results = hybrid_search(query, RETRIEVAL_K)
        seen_document_ids |= {r["document_id"] for r in results}
        for r in results[:2]:
            if r["document_id"] == target_citation.document_id:
                continue  # not a rebuttal if it's the same document
            if not r["verified"]:
                weaknesses.append(
                    f"Unverified lead that may undermine citation on "
                    f"{target_citation.document_id!r}: {r['text'][:200]}"
                )
                continue
            claim = (
                f"Conflicts with citation on {target_citation.document_id} "
                f"({target_citation.claim[:100]}): {r['text'][:200]}"
            )
            if _dedupe_citation(contradictions, contradiction_keys, Citation(
                document_id=r["document_id"], claim=claim, verified=True,
            )):
                citation_rebuttal_hit = True
    else:
        weaknesses.append(
            "Investigator's theory had no verified citation available to "
            "target for a rebuttal search."
        )
    if citation_rebuttal_hit:
        contradiction_category_hits += 1

    # Safety net for NON-NEGOTIABLE RULE #2, enforced independently for this
    # agent's own retrieval calls (not reusing the Investigator's set).
    contradictions = [c for c in contradictions if c.document_id in seen_document_ids]

    if not weaknesses:
        weaknesses.append(
            "No specific weaknesses surfaced beyond the contradictions listed above."
        )

    confidence_delta = -0.2 * contradiction_category_hits
    confidence_delta = max(-0.9, min(0.0, round(confidence_delta, 2)))

    challenged_theory = (
        f"Adversarial review of the theory against suspect_id={suspect_id!r}: "
        f"{theory}"
    )

    return FactCheckResult(
        challenged_theory=challenged_theory,
        contradictions=contradictions,
        alternative_suspects=alternative_suspects,
        weaknesses=weaknesses,
        confidence_delta=confidence_delta,
    )

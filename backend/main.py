"""
FastAPI app for "Solve the Case".

This phase adds the two remaining fixed endpoints: POST /interrogate and
POST /submit_verdict. All six fixed endpoints now exist here:
/ingest, /search_evidence, /investigate, /fact_check, /interrogate,
/submit_verdict.
"""

import json
import os
import uuid

import llm_client
import networkx as nx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents.fact_checker import run_fact_check
from agents.investigator import run_investigation
from ingestion import CORPUS_DIR, GRAPH_OUTPUT_PATH, run_ingestion
from retrieval import hybrid_search
from schemas import Citation, FactCheckResult, InvestigationResult, VerdictRequest, VerdictResult

app = FastAPI(title="Solve the Case API")

# Allow the Vite dev server / deployed frontend (different origin) to call this API.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("FRONTEND_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

GROUND_TRUTH_PATH = os.path.join(CORPUS_DIR, "ground_truth.json")
MANIFEST_PATH = os.path.join(CORPUS_DIR, "corpus_manifest.json")

# --------------------------------------------------------------------------
# Static file serving for the Phase 7 frontend (Case Intro + Evidence Graph)
# --------------------------------------------------------------------------
# These are plain GETs for two specific, named files — not new business
# endpoints under the fixed POST list, and not a directory mount. Only
# corpus_manifest.json and graph.json are reachable this way;
# ground_truth.json is deliberately NOT served by any route, so it stays
# loadable only inside submit_verdict() below, per NON-NEGOTIABLE RULE #3.
# Flagging in case you'd rather do this differently.


@app.get("/static/case_001/corpus_manifest.json")
def get_manifest() -> FileResponse:
    if not os.path.exists(MANIFEST_PATH):
        raise HTTPException(status_code=404, detail="corpus_manifest.json not found — run /ingest first?")
    return FileResponse(MANIFEST_PATH, media_type="application/json")


@app.get("/static/case_001/graph.json")
def get_graph_file() -> FileResponse:
    if not os.path.exists(GRAPH_OUTPUT_PATH):
        raise HTTPException(status_code=404, detail="graph.json not found — run /ingest first?")
    return FileResponse(GRAPH_OUTPUT_PATH, media_type="application/json")


@app.post("/ingest")
def ingest() -> dict:
    """
    Run the ingestion pipeline (load corpus -> chunk -> extract entities/
    relationships -> build graph -> save graph.json) and return a summary.
    """
    try:
        summary = run_ingestion()
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Corpus file not found — is /corpus/case_001/ present? ({e})",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")

    return {
        "documents_processed": summary["documents_processed"],
        "entities": summary["entities"],
        "relationships": summary["relationships"],
    }


class SearchEvidenceRequest(BaseModel):
    query: str
    k: int = 5


class EvidenceResult(BaseModel):
    """Citation-shaped search result: document_id, claim/text snippet, verified."""

    document_id: str
    claim: str
    verified: bool
    score: float


class SearchEvidenceResponse(BaseModel):
    results: list[EvidenceResult]


@app.post("/search_evidence", response_model=SearchEvidenceResponse)
def search_evidence(request: SearchEvidenceRequest) -> SearchEvidenceResponse:
    """
    Run hybrid_search (BM25 + semantic, fused via RRF) against the corpus
    and return the top-k results in Citation-shaped form (document_id,
    claim/text snippet, verified) plus each result's fused score.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    if request.k < 1:
        raise HTTPException(status_code=400, detail="k must be at least 1")

    try:
        raw_results = hybrid_search(request.query, request.k)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Corpus file not found — is /corpus/case_001/ present? ({e})",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")

    results = [
        EvidenceResult(
            document_id=r["document_id"],
            claim=r["text"],
            verified=r["verified"],
            score=r["score"],
        )
        for r in raw_results
    ]
    return SearchEvidenceResponse(results=results)


@app.post("/investigate", response_model=InvestigationResult)
def investigate() -> InvestigationResult:
    """
    Run the Investigator agent's theory -> retrieve -> judge -> retry loop
    (backend/agents/investigator.py) and return the resulting
    InvestigationResult.
    """
    try:
        return run_investigation()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Investigation failed: {e}")


@app.post("/fact_check", response_model=FactCheckResult)
def fact_check(investigation: InvestigationResult) -> FactCheckResult:
    """
    Run the Fact-Checker agent's adversarial search pass
    (backend/agents/fact_checker.py) against a given InvestigationResult
    and return the resulting FactCheckResult.
    """
    try:
        return run_fact_check(investigation)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fact-check failed: {e}")


# --------------------------------------------------------------------------
# POST /interrogate
# --------------------------------------------------------------------------

INTERROGATE_K = 6

# In-memory conversation log: {(session_id, suspect_id): [{"role", "content"}]}
# Per the fixed spec, an in-memory dict is fine for this phase (no DB).
_interrogation_sessions: dict[tuple[str, str], list[dict]] = {}


class InterrogateRequest(BaseModel):
    suspect_id: str
    message: str
    session_id: str | None = None  # if omitted, a new session is started


class InterrogateResponse(BaseModel):
    session_id: str
    suspect_id: str
    reply: str
    grounding_citations: list[Citation]


def _load_graph_for_interrogation() -> nx.MultiDiGraph:
    """Load the entity graph, or an empty graph if /ingest hasn't run yet."""
    if not os.path.exists(GRAPH_OUTPUT_PATH):
        return nx.MultiDiGraph()
    with open(GRAPH_OUTPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    return nx.node_link_graph(data, edges="links")



def _suspect_name(suspect_id: str) -> str:
    """Resolve a display name for suspect_id from the graph, falling back to
    a de-slugged version of the id itself if the graph has no such node."""
    graph = _load_graph_for_interrogation()
    if suspect_id in graph.nodes:
        return graph.nodes[suspect_id].get("name", suspect_id)
    return suspect_id.replace("_", " ").title()


def _suspect_biased_documents(suspect_id: str, suspect_name: str, message: str) -> list[dict]:
    """
    Retrieve grounding evidence for an interrogation turn, biased toward the
    suspect being questioned:
      - hybrid_search on "{suspect_name} {message}" (suspect-anchored query)
      - hybrid_search on "{suspect_name}" alone, to pull in background
        material about them even if the message itself doesn't reference
        them directly
    Results are merged and de-duplicated by (document_id, text).
    """
    merged: dict[tuple[str, str], dict] = {}
    for query in (f"{suspect_name} {message}".strip(), suspect_name):
        for r in hybrid_search(query, INTERROGATE_K):
            key = (r["document_id"], r["text"])
            merged.setdefault(key, r)
    # Keep the strongest INTERROGATE_K by score across both queries.
    ranked = sorted(merged.values(), key=lambda r: r["score"], reverse=True)
    return ranked[:INTERROGATE_K]


@app.post("/interrogate", response_model=InterrogateResponse)
def interrogate(request: InterrogateRequest) -> InterrogateResponse:
    """
    Converse with a suspect in character. Grounds every reply in
    suspect-biased hybrid_search hits (never in raw LLM knowledge), logs the
    turn in an in-memory per-(session, suspect) conversation history, and
    instructs the LLM (via llm_client.call_llm_interrogate) to never assert
    a fact absent from those retrieved documents, and to treat
    verified=false documents only as rumor, never as confirmed fact.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    session_id = request.session_id or str(uuid.uuid4())
    session_key = (session_id, request.suspect_id)
    history = _interrogation_sessions.setdefault(session_key, [])

    suspect_name = _suspect_name(request.suspect_id)

    try:
        grounding_results = _suspect_biased_documents(request.suspect_id, suspect_name, request.message)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Corpus file not found — is /corpus/case_001/ present? ({e})",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Grounding search failed: {e}")

    retrieved_document_ids = {r["document_id"] for r in grounding_results}

    llm_response = llm_client.call_llm_interrogate(
        suspect_name=suspect_name,
        user_message=request.message,
        grounding_documents=grounding_results,
        conversation_history=history,
    )

    if llm_response is None:
        reply = (
            f"[{suspect_name} declines to answer right now — the LLM call failed. "
            f"Check your LLM_PROVIDER and matching API key (ANTHROPIC_API_KEY or GROQ_API_KEY) in .env.]"
        )
    else:
        reply = llm_response["reply"]

    history.append({"role": "detective", "content": request.message})
    history.append({"role": "suspect", "content": reply})

    # Grounding citations returned alongside the reply so the frontend can
    # show what evidence the persona's answer was (supposed to be) based on.
    # Per NON-NEGOTIABLE RULE #2, every citation here references a
    # document_id actually retrieved in this same call.
    grounding_citations = [
        Citation(
            document_id=r["document_id"],
            claim=r["text"][:250],
            verified=r["verified"],
        )
        for r in grounding_results
        if r["document_id"] in retrieved_document_ids
    ]

    print(reply)

    return InterrogateResponse(
        session_id=session_id,
        suspect_id=request.suspect_id,
        reply=reply,
        grounding_citations=grounding_citations,
    )


# --------------------------------------------------------------------------
# POST /submit_verdict
# --------------------------------------------------------------------------

def _load_ground_truth() -> dict:
    """
    Load ground_truth.json server-side only. Per NON-NEGOTIABLE RULE #3,
    this function's return value must never be sent to the client directly
    by any endpoint — only used internally here to compute a VerdictResult.
    """
    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _suspect_ids_match(submitted_suspect_id: str, guilty_suspect_id: str, guilty_suspect_name: str) -> bool:
    """
    Reconcile suspect_id naming conventions: the graph/Investigator use
    entity_ids slugged from a person's name (e.g. "elena_rodriguez"), while
    ground_truth.json in this corpus uses a different convention (e.g.
    "suspect_elena"). Exact match is tried first; otherwise fall back to a
    loose token-overlap check against the guilty suspect's first name and
    full name, so a reasonably-identified correct suspect isn't marked
    wrong purely over id-format mismatch.
    """
    a = submitted_suspect_id.strip().lower()
    b = guilty_suspect_id.strip().lower()
    if a == b:
        return True

    a_tokens = set(a.replace("-", "_").split("_"))
    b_tokens = set(b.replace("-", "_").split("_"))
    name_tokens = set(guilty_suspect_name.lower().split())

    # Match if the submitted id shares a meaningful name token with either
    # the ground-truth id or the guilty suspect's actual name (e.g. contains
    # "elena" or "rodriguez"), excluding the generic word "suspect".
    a_tokens.discard("suspect")
    b_tokens.discard("suspect")
    return bool(a_tokens & (b_tokens | name_tokens))


@app.post("/submit_verdict", response_model=VerdictResult)
def submit_verdict(request: VerdictRequest) -> VerdictResult:
    """
    Score a final verdict against ground_truth.json (loaded server-side
    only — never exposed to the client, per NON-NEGOTIABLE RULE #3).

    Scoring:
      - 0.6 of the score is whether suspect_id matches the guilty suspect.
      - 0.4 of the score is the fraction of supporting_citations that are
        both verified=true and reference a document_id in
        truly_probative_document_ids. Citations that are unverified, or
        that cite the known misleading_document_id, count against this
        fraction (i.e. are simply not credited) — an agent relying on the
        red-herring tip should not be rewarded for it, per
        NON-NEGOTIABLE RULE #1.
      - If supporting_citations is empty, that portion of the score is 0
        rather than undefined.
    """
    try:
        ground_truth = _load_ground_truth()
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"ground_truth.json not found — is /corpus/case_001/ present? ({e})",
        )

    guilty_suspect_id = ground_truth["guilty_suspect_id"]
    guilty_suspect_name = ground_truth.get("guilty_suspect_name", "")
    probative_doc_ids = set(ground_truth.get("truly_probative_document_ids", []))

    suspect_correct = _suspect_ids_match(request.suspect_id, guilty_suspect_id, guilty_suspect_name)

    if request.supporting_citations:
        credited = sum(
            1
            for c in request.supporting_citations
            if c.verified and c.document_id in probative_doc_ids
        )
        citation_fraction = credited / len(request.supporting_citations)
    else:
        citation_fraction = 0.0

    score = (0.6 if suspect_correct else 0.0) + 0.4 * citation_fraction
    score = round(min(1.0, max(0.0, score)), 2)

    if suspect_correct:
        explanation = (
            f"Correct suspect identified. {round(citation_fraction * 100)}% of the "
            f"supporting citations were verified and genuinely probative."
        )
    else:
        explanation = (
            f"Incorrect suspect. {round(citation_fraction * 100)}% of the supporting "
            f"citations were verified and genuinely probative, but the wrong person "
            f"was accused."
        )

    return VerdictResult(
        correct=suspect_correct,
        score=score,
        explanation=explanation,
    )

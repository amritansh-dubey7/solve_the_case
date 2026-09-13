# Technical Report — Solve the Case

## Architecture Overview

The system is a FastAPI backend (`/backend`) paired with a React/Vite frontend
(`/frontend`), talking over six fixed JSON endpoints: `/ingest`,
`/interrogate`, `/search_evidence`, `/investigate`, `/fact_check`, and
`/submit_verdict`.

`/ingest` reads the case corpus from `/corpus/case_001` (documents +
`corpus_manifest.json`), builds a `networkx.MultiDiGraph` of entities and
relationships, and writes `graph.json` to disk. Every other endpoint reads
from that graph and from the retrieval index rather than re-parsing raw
files.

Retrieval (`retrieval.py`) is hybrid: BM25 (`rank_bm25`) over paragraph-level
chunks for lexical matching, plus `sentence-transformers`
(`all-MiniLM-L6-v2`) cosine similarity for semantic matching, fused with
Reciprocal Rank Fusion (RRF). Both indexes and the embedding model are built
once per process and cached in module-level globals, not rebuilt per
request.

Two agents sit on top of retrieval. The **Investigator** (`agents/investigator.py`)
proposes a theory, retrieves evidence, judges whether it has covered the
required evidence categories, and retries (re-querying with a narrower
focus) up to a hard cap before returning an `InvestigationResult`. The
**Fact-Checker** (`agents/fact_checker.py`) takes that result and runs an
independent, adversarial pass — it does not just re-read the Investigator's
citations.

All LLM calls funnel through `backend/llm_client.py`, which reads the
provider and key from `.env` (`LLM_PROVIDER` = `anthropic` or `groq`) so
switching providers never touches endpoint or agent code.

## Corpus

`corpus/case_001` contains 18 documents restructured from a real
public-domain source — Arthur Conan Doyle's *The Boscombe Valley Mystery*
(1891; copyright expired, freely available via Project Gutenberg) —
reformatted into investigation-document form (police reports, witness
statements, inquest testimony, forensic/physical-evidence reports,
correspondence, a diary entry, and an old colonial newspaper clipping),
described in `corpus_manifest.json` with `type`, `timestamp`, `verified`,
and `source` per document. `ground_truth.json` holds the actual culprit and
supporting facts used to grade a verdict. Two documents are marked
`verified: false`: an anonymous, uncorroborated tip pointing at a fictional
vagrant, and a period newspaper clipping presuming the obvious suspect's
guilt.

**Public-domain sourcing note.** The story text itself is not reproduced
here — the 18 case documents are original restructurings, written to fit
this app's document schema (police report, witness statement, forensic
report, correspondence, etc.), of the real facts, characters, evidence, and
plot of Doyle's 1891 story. The source work is in the public domain in the
US (published well before 1928); see gutenberg.org/ebooks/1661.

## Key Design Decisions

**Why hybrid retrieval.** Witness statements and reports use inconsistent
wording for the same event (a name, a nickname, a paraphrase of an action),
so pure lexical search misses paraphrases and pure semantic search misses
exact names/times that matter for an investigation. RRF fusion combines
both rankings without needing a trained re-ranker or a vector database —
appropriate for a corpus this small (18 documents).

**How the retry loop terminates.** The Investigator tracks which required
evidence categories (e.g., motive, opportunity, physical evidence) have been
covered by verified citations after each retrieval round. It stops when
either all required categories are covered, or it hits `MAX_RETRIES = 3`
rounds — whichever comes first. `needs_more_evidence` reports whether it
stopped because it was satisfied or because it ran out of retries, and
confidence is penalized per retry used, so the score reflects how much
searching was needed, not just the final answer.

**How citation hallucination is prevented.** Every `Citation` an agent
returns is checked against the `document_id`s actually returned by
`hybrid_search` in that same call before being attached to the result; any
citation that doesn't trace back to a real retrieved chunk is dropped rather
than passed through. This is enforced structurally in both agents, not left
to the LLM's discretion.

**How Fact-Checker search differs from Investigator search.** The
Fact-Checker does not reuse the Investigator's queries. It runs three
distinct adversarial passes: (1) a timeline-conflict search that negates the
theory's stated sequence of events and looks for evidence placing the
suspect elsewhere, (2) an alternative-suspect search that walks the entity
graph for other person entities independently of the theory (not generated
by paraphrasing it), and (3) a citation-undermining search that targets one
specific citation the Investigator used and searches for material that
contradicts it. `confidence_delta` scales with how many of these three
independent categories actually produced a hit.

**Unverified documents.** Any document with `verified: false` (e.g., an
anonymous tip) is never treated as established fact by either agent — it
can only be surfaced as an explicit "unverified lead," and it cannot be used
to satisfy a required evidence category on its own.

**Ground truth isolation.** `ground_truth.json` is loaded only inside
`/submit_verdict`'s handler in `main.py`. No other endpoint reads it, and it
is not among the files served by the two static `/static/case_001/...`
routes (only `corpus_manifest.json` and `graph.json` are served that way),
so it never reaches the frontend by any path.

## Known Limitations

- The corpus is small (18 documents) and synthetic; retrieval quality at
  this scale isn't a stress test of the hybrid approach — it's chosen for
  fit, not because RRF was necessary here.
- Evidence-category coverage (used to decide `needs_more_evidence`) is a
  fixed, hand-defined list per case rather than learned or dynamically
  inferred from the corpus.
- No authentication/rate-limiting on the API; fine for a demo, not for
  multi-tenant or public production use.
- The embedding model and both indexes are rebuilt in memory on process
  restart (a few seconds for this corpus size), which is acceptable here but
  would need a persistence layer for a much larger corpus.
- LLM calls depend on whichever provider key is configured; without a valid
  key the app still runs but interrogation/investigation responses report
  that the LLM call was skipped rather than failing silently.

## Bonus Features Implemented

- Dual LLM provider support (Anthropic or Groq) behind one `llm_client.py`
  switch, so the app is usable with a free-tier key and no credit card.
- An evidence graph view in the frontend (`react-force-graph-2d`) for
  visually exploring entities and relationships from `graph.json`.
- One-click local start scripts (`start.sh` / `start.bat`) that create the
  virtualenv, install both sides, run initial ingestion, and launch both
  servers together.
- Frontend error boundaries per screen, so a failure in one tab (e.g., the
  graph view) surfaces an in-place error instead of blanking the whole app.

# Solve the Case — An Interactive Agentic RAG Investigation

An AI detective app: investigate an 1889 murder case built from a real
public-domain mystery, question suspects, search evidence, watch two AI
agents form and stress-test a theory, then submit your own verdict.

Built for the 180DC ML Team Dev Task — *Solve the Case: An Interactive
Agentic RAG Investigation*.

---

## Live demo

- **App:** `https://<your-vercel-url>.vercel.app`
- **API:** `https://solve-the-case.onrender.com` (interactive docs at `/docs`)

> Free-tier note: the backend runs on Render's free instance, which spins
> down after ~15 minutes of inactivity. The first request after a period of
> no traffic can take 30-60 seconds to wake up — this is expected, not a bug.

---

## What this is

The user investigates the death of Charles McCarthy, found beaten near
Boscombe Pool. His son James McCarthy is the obvious suspect. Two AI agents
work the case alongside the user:

- **Investigator Agent** — forms a theory, retrieves supporting evidence,
  checks whether it has covered motive/means/opportunity with *verified*
  evidence, and retries with a narrower query (up to 3 times) if not.
- **Fact-Checker Agent** — runs three independent adversarial searches
  against the Investigator's theory: a timeline-conflict check, an
  alternative-suspect check (walks the entity graph independently, not by
  paraphrasing the theory), and a check that tries to undermine one specific
  citation the Investigator relied on.

The user can interrogate suspects, search the evidence corpus, inspect a
visual evidence graph, lock in their own prediction before seeing the
agents' output, then submit a final verdict — scored on both who they
accuse and how solid (verified, relevant) their cited evidence actually is.

---

## Architecture

```
backend/        FastAPI app — retrieval, ingestion, agents, endpoints
  main.py         6 fixed endpoints (see below) + 2 static-file routes
  ingestion.py     corpus -> graph.json (networkx.MultiDiGraph)
  retrieval.py     hybrid search: BM25 + fastembed embeddings, fused via RRF
  llm_client.py    single shared LLM call path (Anthropic or Groq)
  agents/
    investigator.py   theory -> retrieve -> judge -> retry loop
    fact_checker.py    3 independent adversarial search passes
  schemas.py       Pydantic request/response models

corpus/case_001/  18 documents + corpus_manifest.json + graph.json + ground_truth.json
frontend/         React + Vite — 7-tab investigation UI
docs/
  technical_report.md   full architecture write-up (1-2 pages, as required)
```

### API endpoints

| Method | Path                | Purpose                                    |
|--------|---------------------|---------------------------------------------|
| POST   | `/ingest`            | Parse corpus, build the evidence graph      |
| POST   | `/interrogate`        | Chat with a candidate/suspect                |
| POST   | `/search_evidence`    | Hybrid (lexical + semantic) evidence search  |
| POST   | `/investigate`        | Run the Investigator agent                   |
| POST   | `/fact_check`         | Run the Fact-Checker agent                   |
| POST   | `/submit_verdict`     | Score the user's final accusation            |
| GET    | `/static/case_001/corpus_manifest.json` | Serve manifest to the frontend |
| GET    | `/static/case_001/graph.json`           | Serve graph to the frontend    |

`ground_truth.json` has **no route** — it is loaded only inside
`submit_verdict()`'s handler and never reachable any other way, so it can
never leak to the frontend or a curious user poking at the API.

### Retrieval

Hybrid search over paragraph-level (grouped in 2s) chunks:
- **Lexical**: BM25 (`rank_bm25`)
- **Semantic**: `fastembed` (`BAAI/bge-small-en-v1.5`, ONNX runtime — chosen
  over `sentence-transformers`/PyTorch specifically because it's ~100MB with
  no torch dependency, which matters for fitting inside a 512MB free-tier
  deployment)
- **Fusion**: Reciprocal Rank Fusion (RRF) — no vector database needed at
  this corpus size

### Grounding / hallucination resistance

- Every citation an agent returns is checked against documents *actually
  retrieved* in that same call before being attached to a result — a
  citation that doesn't trace back to a real retrieved chunk is dropped in
  code, not left to the model's discretion.
- Documents marked `verified: false` in the corpus can be surfaced as
  leads but can never, alone, satisfy a required evidence category
  (motive/means/opportunity) or be treated as settled fact.
- `/submit_verdict` scores citations against `ground_truth.json`'s
  `truly_probative_document_ids`, and zeroes out credit for citations that
  are unverified or not actually probative.

See `docs/technical_report.md` for the full design-decision write-up.

---

## Quickstart — run it locally

**macOS / Linux:**
```bash
./start.sh
```

**Windows:**
```
start.bat
```

Either script: creates the backend virtualenv, installs backend and
frontend dependencies (fast on repeat runs — cached), starts the backend on
`http://localhost:8000`, runs `/ingest` once automatically, starts the
frontend on `http://localhost:5173`, and opens both.

The one manual step it can't do for you: **add an API key**. The first run
creates `backend/.env` with an empty key — open it, paste in your key
(see below), and re-run the script. Without a key, the app still runs, but
interrogation/investigation replies will say the LLM call was skipped.

### Running it manually instead

```bash
# backend
cd backend
pip install -r requirements.txt
# set your key in backend/.env — see below
uvicorn main:app --reload --port 8000
curl -X POST http://localhost:8000/ingest   # build graph.json first

# frontend
cd frontend
cp .env.example .env   # VITE_API_URL=http://localhost:8000
npm install
npm run dev
```

---

## Setting up your API key — Anthropic or free Groq

The backend supports two providers via `LLM_PROVIDER` in `backend/.env`.
Every LLM call goes through one function in `llm_client.py`, so switching
providers is just editing `.env` — no code changes.

```
LLM_PROVIDER=groq
ANTHROPIC_API_KEY=
GROQ_API_KEY=
GROQ_MODEL=qwen/qwen3.6-27b
```

- **Groq (free, no credit card):** get a key at
  https://console.groq.com/keys, paste it after `GROQ_API_KEY=`.
  ⚠️ Groq's free tier has a low tokens-per-minute limit (1000 OTPM as of
  writing). `llm_client.py` retries with backoff on `429`s and
  `ingestion.py` paces calls with a short delay between chunks specifically
  to work within this — see "Known limitations" below.
- **Anthropic:** get a key at https://console.anthropic.com/settings/keys,
  paste it after `ANTHROPIC_API_KEY=`, set `LLM_PROVIDER=anthropic`.

---

## Deploying it yourself

### Backend → Render (Railway/Fly.io are equivalent)

1. Push this repo to GitHub. `.gitignore` already excludes `venv/`,
   `node_modules/`, and both `.env` files.
2. Render → **New → Web Service** → connect the repo → **Root Directory**:
   `backend`.
3. Build command: `pip install -r requirements.txt`
   Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables in Render's dashboard (never commit real
   keys): `LLM_PROVIDER`, `GROQ_API_KEY` (or `ANTHROPIC_API_KEY`),
   `GROQ_MODEL`, `FRONTEND_ORIGINS` (your frontend's URL once deployed;
   `*` works but is looser than needed in production).
5. Deploy, then call `POST /ingest` once against the live URL (via `/docs`
   or `curl`) to build `graph.json` on the server. This can take a few
   minutes on the free tier due to rate-limit pacing — that's expected.

### Frontend → Vercel (Netlify is equivalent)

1. **New Project** → import the same repo → **Root Directory**: `frontend`.
2. Build command: `npm run build` — Output directory: `dist` (Vite
   defaults, auto-detected).
3. Add environment variable `VITE_API_URL` = your Render backend URL
   (e.g. `https://solve-the-case.onrender.com`, no trailing slash).
   ⚠️ **Vite bakes env vars in at build time**, not runtime — if you add or
   fix this variable *after* a build, you must trigger a fresh deploy for
   it to take effect. Saving the variable alone does nothing to an
   already-built site.
4. Deploy.

### Verifying end-to-end

From a fresh/incognito window, open the deployed frontend and confirm: the
Case File loads, Corkboard fetches `graph.json` without a CORS error, and
submitting an interrogation/investigation/verdict round-trips successfully.

---

## Known limitations

- **Free-tier rate limits are real and visible.** Groq's free tier (1000
  output tokens/minute) means a full `/ingest` run makes many calls that
  will individually get rate-limited; the code retries and paces itself,
  but a full run can take several minutes rather than seconds. This is a
  deliberate tradeoff to keep the whole stack free to run, not a bug.
- **Free-tier Render spins down after inactivity** and re-downloads the
  ~100MB embedding model on every cold start (the free tier's disk isn't
  persistent between restarts) — expect the first request after idle time
  to be slow.
- Evidence-category coverage (motive/means/opportunity) used by the
  Investigator agent is a fixed, hand-defined list for this case, not
  learned or dynamically inferred from an arbitrary new corpus.
- No authentication/rate-limiting on the API itself — fine for a
  demo/grading context, not for public production use as-is.

---

## Dataset

18 documents in `corpus/case_001`, restructured from a real public-domain
source: Arthur Conan Doyle's *The Boscombe Valley Mystery* (1891 — public
domain, freely available via Project Gutenberg). The documents (police
reports, witness statements, inquest testimony, forensic/physical-evidence
reports, correspondence, a diary entry, and an 1867 colonial newspaper
clipping) restructure that real story's facts, characters, and evidence
into this app's investigation-document schema — original text, not the
source's literary prose, to both respect the schema and avoid reproducing
copyrighted phrasing (moot here since the source is public domain, but
good practice regardless). Each document is tagged with `type`,
`timestamp`, `verified`, and `source` in `corpus_manifest.json`.

The real culprit, per `ground_truth.json`: **John Turner**, a wealthy
neighbouring landowner Charles McCarthy had blackmailed for two decades
over a shared criminal past, who killed McCarthy rather than let him force
Turner's daughter into an unwanted marriage. James McCarthy (the obvious
suspect — seen quarrelling with his father, caught alone with the body,
initially lied about the afternoon) is cleared by physical evidence. Two
documents are deliberately marked `verified: false` — an anonymous,
uncorroborated tip about a vagrant, and a biased contemporary newspaper
clipping presuming James's guilt — to test that the agents don't treat
unverified material as established fact.

---

## AI coding tools used

Built using Claude (Anthropic) as the primary coding assistant, working in
phases from a fixed spec (tech stack, folder structure, endpoint names, and
Pydantic schemas set up front and held constant) so later phases couldn't
drift from earlier contracts: corpus/case design → ingestion & graph
construction → hybrid retrieval → Investigator agent → Fact-Checker agent
→ FastAPI endpoint layer → React frontend, each phase tested against the
fixed spec before the next began. Grading-relevant constraints — citation
grounding, unverified-evidence handling, ground-truth isolation, retry
caps — were specified explicitly up front and verified in the actual code
afterward, not assumed to be handled automatically.

---

## Bonus features implemented

- Dual LLM provider support (Anthropic or free-tier Groq) behind one
  `llm_client.py` switch — no code changes needed to swap providers.
- Evidence graph visualization in the frontend (`react-force-graph-2d`).
- One-click local start scripts (`start.sh`, `start.bat`).
- Per-screen frontend error boundaries — a failure in one tab shows an
  in-place error instead of blanking the whole app.
- Rate-limit-aware ingestion (paced calls + capped retry/backoff) so the
  app runs entirely on free-tier infrastructure end to end.

See `docs/technical_report.md` for the full architecture write-up and
`docs/TECHNICAL_REPORT_EXPLAINED.md` for a plain-English walkthrough of it.

---

## Security note

Never commit real API keys. `.gitignore` already excludes `backend/.env`
and `frontend/.env`. Set keys as environment variables in
Render's/Vercel's dashboard, never in a committed file. If a key is ever
accidentally exposed (e.g. in an uploaded zip), treat it as compromised and
rotate it immediately at the provider's dashboard.

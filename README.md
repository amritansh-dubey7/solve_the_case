# Solve the Case — Full Project (Phases 1–7)

## Run it with one click

**macOS / Linux:**
```bash
./start.sh
```

**Windows:**
```
start.bat
```

Either script: creates the backend virtualenv, installs both backend and
frontend dependencies (only the first time — fast on later runs), starts
the backend on `http://localhost:8000`, runs `/ingest` once automatically,
starts the frontend on `http://localhost:5173`, and opens both together.
On macOS/Linux, `Ctrl+C` stops both. On Windows, each runs in its own
window — close both to stop.

The one manual step either script can't do for you: **add your API key**.
The first run creates `backend/.env` with an empty `ANTHROPIC_API_KEY=` —
open that file, paste in your key, and re-run the script. Without a key,
the app still runs, but interrogation/investigation replies will say the
LLM call was skipped.

If you'd rather run each half manually (e.g. to see logs separately or
deploy them apart), see "Running it manually" near the bottom of this file.

## Setting up your API key — Anthropic or free Groq

The backend supports two providers, picked by `LLM_PROVIDER` in
`backend/.env`. Every LLM call in the codebase goes through one function
in `llm_client.py`, so switching providers is just editing `.env` — no
code changes needed.

1. Run `./start.sh` (or `start.bat`) once — it auto-creates `backend/.env`:
   ```
   LLM_PROVIDER=groq
   ANTHROPIC_API_KEY=
   GROQ_API_KEY=
   ```
2. **To use Groq (free, no credit card):** get a key at
   https://console.groq.com/keys, paste it after `GROQ_API_KEY=`, and leave
   `LLM_PROVIDER=groq`. Groq's free tier defaults to the `llama-3.3-70b-versatile`
   model (override with `GROQ_MODEL=` in `.env` if that model is ever
   retired — check https://console.groq.com/docs/models for current ones).
3. **To use Anthropic instead:** get a key at
   https://console.anthropic.com/settings/keys, paste it after
   `ANTHROPIC_API_KEY=`, and change the first line to `LLM_PROVIDER=anthropic`.
4. Save the file and restart the backend (`Ctrl+C` then `./start.sh` again —
   the frontend doesn't need restarting).

Without a valid key for whichever provider you selected, the app still
runs — interrogation and investigation replies will just say the LLM call
was skipped.

## Troubleshooting

**Backend seems stuck at "Installing backend dependencies"**
It's not stuck — `sentence-transformers` pulls in PyTorch, a ~400MB+
download, and can genuinely take several minutes on the first run
depending on your connection. `start.sh`/`start.bat` now print pip's real
progress instead of hiding it. Every run after the first is near-instant
since the packages are cached.

**Frontend shows a blank white screen**
This was a real bug in the first version of this frontend: the Corkboard
graph (`react-force-graph-2d`) was imported eagerly at the top of the app,
and if that library throws on load (it can, under React 18), it took down
the *entire* app with no visible error. Fixed now — the graph is lazy-loaded
and every screen is wrapped in an error boundary, so a problem in one tab
shows an error message in that tab instead of blanking everything. If you
still see a blank screen after updating:
1. Open the browser console (F12 → Console tab) and look for a red error —
   it'll usually name the exact file and line.
2. Confirm the backend is actually running and reachable at
   `http://localhost:8000/docs`.
3. Confirm `frontend/.env` has `VITE_API_URL=http://localhost:8000` (or
   wherever your backend actually is).

---

This is your Phase 6 backend + corpus, unmodified except for the two small,
flagged additions below, plus the new Phase 7 frontend.

```
backend/        <- your Phase 6 files, untouched except main.py (see "Changes" below)
corpus/case_001/<- your Phase 1 corpus, untouched
docs/           <- empty, as delivered (technical_report.md not due yet)
frontend/       <- new, Phase 7
```

## Changes made to `backend/main.py`

Everything else in `backend/` (schemas.py, ingestion.py, retrieval.py,
llm_client.py, agents/) is exactly as you uploaded it — unchanged. In
`main.py`, two things were added, both flagged inline as comments:

1. **Two narrow `GET` routes**, so the frontend has somewhere to fetch case
   data that had no endpoint before:
   - `GET /static/case_001/corpus_manifest.json`
   - `GET /static/case_001/graph.json`

   These are plain file reads for exactly those two files — not a directory
   mount, not a new business endpoint under the fixed POST list.
   `ground_truth.json` still has **no route at all**, so NON-NEGOTIABLE RULE
   #3 holds: it's only ever loaded inside `submit_verdict()`.

2. **CORS middleware**, so the Vite dev server (a different origin/port)
   is allowed to call the API. Configurable via `FRONTEND_ORIGINS` env var
   (comma-separated), defaults to `*`.

3. **`backend/llm_client.py` now supports two providers**, not just
   Anthropic: set `LLM_PROVIDER=anthropic` or `LLM_PROVIDER=groq` in
   `backend/.env` (Groq has a free tier). Every `call_llm_*` function still
   goes through one shared helper (`_call_llm_json`), which is the only
   place that knows about the difference between providers — nothing in
   `ingestion.py`, `agents/`, or `main.py` had to change. `requests` was
   added to `requirements.txt` for the Groq HTTP call.

No schemas, fixed endpoint names, or request/response shapes were touched.

## What I noticed in your data (informational, no code changes needed)

- `corpus/case_001/graph.json` is empty (0 nodes/0 edges) until you run
  `/ingest` against a live LLM key — `llm_client.call_llm_extract` (used by
  `ingestion.py`) needs a real API call to pull entities/relationships out
  of the corpus text. The Corkboard screen and Case Intro's suspect list
  fall back gracefully until then (Case Intro shows the hardcoded summary
  below; the Corkboard just renders an empty board with no error).
- **The corpus is now a real public-domain dataset**, not a synthetic one:
  Arthur Conan Doyle's *The Boscombe Valley Mystery* (1891, public domain —
  copyright expired decades ago; freely available via Project Gutenberg).
  The 18 documents in `corpus/case_001` are original restructurings of that
  real, public story into investigation-document form (police reports,
  witness statements, inquest testimony, forensic/physical-evidence
  reports, correspondence, a diary entry, and an old colonial newspaper
  clipping) — the underlying facts, characters, and plot are the real
  public-domain source material, reformatted to fit this app's document
  schema rather than an invented case.
- The real case, per `ground_truth.json` and the documents: Charles
  McCarthy is found beaten to death near Boscombe Pool; his son James
  McCarthy (`suspect_james`) is the obvious suspect — seen quarrelling
  violently with his father minutes before the death, caught alone with
  the body, and caught in an initial lie about having seen his father that
  afternoon. The guilty party is actually **John Turner** (`suspect_turner`),
  a wealthy neighbouring landowner Charles McCarthy had blackmailed for two
  decades over a shared criminal past in colonial Australia, who killed
  McCarthy rather than let him force Turner's daughter into a marriage she
  didn't choose. A second red herring — an anonymous, uncorroborated tip
  about a vagrant (`doc_008`) — and a biased newspaper clipping presuming
  James's guilt (`doc_007`) are both deliberately marked `verified: false`.

## Running it manually

```bash
# backend
cd backend
pip install -r requirements.txt
# set ANTHROPIC_API_KEY in a .env file (llm_client.py reads it)
uvicorn main:app --reload --port 8000
curl -X POST http://localhost:8000/ingest   # build graph.json first

# frontend
cd frontend
cp .env.example .env   # VITE_API_URL=http://localhost:8000
npm install
npm run dev
```

See `frontend/README.md` for the screen-by-screen breakdown and theme notes.

---

## ⚠️ Security note

`backend/.env` in this zip contains a **live Groq API key**. Treat it as
compromised — rotate/revoke it at https://console.groq.com/keys and put a
fresh key in your own `.env` before deploying. A `.gitignore` has been added
(`backend/.env`, `frontend/.env`, `venv/`, `node_modules/`) so this doesn't
happen again if you push to GitHub. Never commit real keys — set them as
environment variables in Render/Vercel's dashboard instead.

## Deployment (Phase 8)

**What's included here:** everything needed to deploy — `backend/Procfile`,
CORS wired to an env var, `.env`-based key handling, and a frontend that
reads the backend URL from `VITE_API_URL`. **What I can't do from this
chat:** I don't have a browser or hosting-account access, so I can't click
through Render's/Vercel's dashboards myself or hand you a live URL directly.
The steps below are exact and short — expect ~10 minutes end to end.

### Backend (Render — Railway/Fly.io are equivalent)

1. Push this repo to GitHub (the `.gitignore` above keeps `venv/`,
   `node_modules/`, and both `.env` files out of the commit).
2. On [render.com](https://render.com): **New → Web Service**, connect the
   repo, set **Root Directory** to `backend`.
3. Build command: `pip install -r requirements.txt`
   Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   (same as `backend/Procfile`, which Render/Railway auto-detect.)
4. Add environment variables in Render's dashboard (not in a committed
   file): `LLM_PROVIDER`, `GROQ_API_KEY` (or `ANTHROPIC_API_KEY`), and
   `FRONTEND_ORIGINS` set to your Vercel/Netlify URL once you have it (comma
   separate multiple origins; avoid leaving this as `*` in production).
5. Deploy, then call `POST /ingest` once against the live URL (e.g. via
   `/docs` or `curl`) to build `graph.json` on the server.

### Frontend (Vercel — Netlify is equivalent)

1. **New Project** → import the same repo → set **Root Directory** to
   `frontend`.
2. Build command: `npm run build` — output directory: `dist` (Vite
   defaults; `vercel`/`netlify` auto-detect these).
3. Add environment variable `VITE_API_URL` = your Render backend URL
   (e.g. `https://solve-the-case-api.onrender.com`).
4. Deploy.

### Verifying end-to-end

From a fresh/incognito browser window, open the deployed frontend URL and
confirm: the Case Intro loads, the Corkboard graph fetches
`/static/case_001/graph.json` from the live backend without a CORS error,
and submitting an investigation/verdict round-trips successfully. If CORS
fails, double-check `FRONTEND_ORIGINS` on the backend matches the frontend's
exact deployed origin (scheme + host, no trailing slash).

**Live URLs:** _fill in after you deploy —_
- Backend: `https://<your-backend>.onrender.com`
- Frontend: `https://<your-frontend>.vercel.app`

## Dataset

18 documents in `corpus/case_001`, restructured from a real public-domain
source: Arthur Conan Doyle's *The Boscombe Valley Mystery* (1891 — public
domain, freely available via Project Gutenberg). The documents (police
reports, witness statements, inquest testimony, forensic and physical
evidence reports, correspondence, a diary entry, and an 1867 colonial
newspaper clipping) reformat that real story's facts, characters, and
evidence into this app's investigation-document schema. Each is tagged
with `type`, `timestamp`, `verified`, and `source` in
`corpus_manifest.json`; `ground_truth.json` is used only inside
`/submit_verdict` and is never exposed elsewhere. Two documents are
deliberately marked `verified: false` — an anonymous, uncorroborated tip
about a vagrant, and a biased contemporary newspaper clipping presuming
the obvious suspect's guilt — to test that the agents don't treat
unverified material as established fact.

## AI coding tools used

This project (all phases) was built with Claude (Anthropic) as the primary
coding assistant, working phase-by-phase from a fixed spec (tech stack,
folder structure, endpoint names, and Pydantic schemas set up front and
held constant throughout) so later phases couldn't drift from earlier
contracts. Each phase's changes were flagged inline in code comments and in
this README rather than silently rewritten.

## Bonus features implemented

- Dual LLM provider support (Anthropic or Groq) behind a single
  `llm_client.py` switch — no code changes needed to swap providers.
- Evidence graph visualization in the frontend (`react-force-graph-2d`).
- One-click local start scripts (`start.sh`, `start.bat`).
- Per-screen frontend error boundaries so one broken tab doesn't blank the
  whole app.
- See `docs/technical_report.md` for the full architecture write-up.

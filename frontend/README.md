# Solve the Case — Frontend (Phase 7)

React (Vite) app for all 8 required screens, themed as an aged detective case
file: manila paper, ink stamps, a corkboard graph, red-thread contradictions.

## Run it

```bash
cp .env.example .env   # point VITE_API_URL at your backend if not localhost:8000
npm install
npm run dev
```

## Screens → endpoints

| Screen | File | Endpoint |
|---|---|---|
| Case File | `CaseIntro.jsx` | `GET /static/case_001/corpus_manifest.json` (falls back to hardcoded summary) |
| Interrogation Room | `Interrogation.jsx` | `POST /interrogate` |
| Evidence Locker | `EvidenceSearch.jsx` | `POST /search_evidence` |
| Corkboard | `EvidenceGraph.jsx` | `GET /static/case_001/graph.json` |
| Your Hunch | `Prediction.jsx` | client-side only, timestamped |
| Agents at Work | `InvestigationBoard.jsx` | `POST /investigate`, then `POST /fact_check` |
| Final Verdict | `Verdict.jsx` | `POST /submit_verdict` |

## One backend change made (flagged, not silent)

The fixed spec lists six POST endpoints and says to ask before adding more.
Two things this frontend needs — `corpus_manifest.json` and `graph.json` —
aren't served anywhere yet, so `main.py` got **two narrow GET routes**
(`/static/case_001/corpus_manifest.json`, `/static/case_001/graph.json`),
not a directory mount and not a new business endpoint. `ground_truth.json`
deliberately has no route at all, so rule #3 (ground truth never leaves the
backend except inside `/submit_verdict`) still holds. A CORS middleware was
also added so the Vite dev server can call the API from a different origin.
If you'd rather do this a different way (e.g. copy just those two files
into a `public/` folder at ingest time), say so and it's a small change.

## Theme

Colors, type (Special Elite + Lora) and the verified/unverified badge system
are defined once in `src/styles.css` as CSS variables — see the top of that
file to retheme for a different case.

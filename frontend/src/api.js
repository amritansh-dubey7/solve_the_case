// Thin wrapper around the fixed backend endpoints.
// Base URL is configurable via VITE_API_URL (defaults to same-origin proxy in dev).
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || detail
    } catch {
      /* ignore parse errors */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  ingest: () => request('/ingest', { method: 'POST' }),

  searchEvidence: (query, k = 5) =>
    request('/search_evidence', { method: 'POST', body: JSON.stringify({ query, k }) }),

  investigate: () => request('/investigate', { method: 'POST' }),

  factCheck: (investigation) =>
    request('/fact_check', { method: 'POST', body: JSON.stringify(investigation) }),

  interrogate: (suspect_id, message, session_id) =>
    request('/interrogate', {
      method: 'POST',
      body: JSON.stringify({ suspect_id, message, session_id: session_id || null }),
    }),

  submitVerdict: (suspect_id, supporting_citations) =>
    request('/submit_verdict', {
      method: 'POST',
      body: JSON.stringify({ suspect_id, supporting_citations }),
    }),

  // NOTE: these two are not in the fixed POST list above — they are plain
  // static-file GETs (not new business endpoints) that this phase needs to
  // read /corpus/case_001/corpus_manifest.json and graph.json for the Case
  // Intro and Evidence Graph screens. See the README for the one-line
  // StaticFiles mount this assumes on the backend; swap these two functions
  // for whatever your backend actually serves them at.
  getManifest: () => request('/static/case_001/corpus_manifest.json'),
  getGraph: () => request('/static/case_001/graph.json'),
}

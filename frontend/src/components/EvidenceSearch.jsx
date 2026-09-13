import { useState } from 'react'
import { api } from '../api.js'

export default function EvidenceSearch({ query, setQuery, results, setResults }) {
  // query/results now live in App so they survive tab switches instead of
  // being wiped every time this component unmounts.
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function search() {
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.searchEvidence(query.trim(), 8)
      setResults(res.results)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section>
      <div className="section-title">
        <span>Evidence Locker</span>
        <span className="stamp-small">BM25 + semantic, fused</span>
      </div>

      <div className="form-row">
        <input
          type="text"
          placeholder="Search the case documents — a name, a place, a time..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && search()}
        />
        <button className="btn btn-primary" onClick={search} disabled={loading || !query.trim()}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </div>
      {error && <p className="error-note">{error}</p>}

      {results && results.length === 0 && <p className="hint-note">Nothing turned up. Try another angle.</p>}

      {results &&
        results.map((r, i) => (
          <div key={i} className={`evidence-card ${r.verified ? 'verified' : 'unverified'}`}>
            <div className="doc-id">
              <span>{r.document_id} · score {r.score.toFixed(3)}</span>
              <span className={`badge ${r.verified ? 'badge-verified' : 'badge-unverified'}`}>
                {r.verified ? '✓ verified' : '⚠ unverified lead'}
              </span>
            </div>
            <p style={{ margin: 0 }}>{r.claim}</p>
          </div>
        ))}
    </section>
  )
}

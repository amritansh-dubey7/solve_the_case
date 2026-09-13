import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function Verdict({
  candidates,
  investigation,
  prediction,
  suspectId,
  setSuspectId,
  selectedCitationIdx,
  setSelectedCitationIdx,
  result,
  setResult,
}) {
  const list = candidates.length
    ? candidates
    : [
        { id: 'suspect_james', name: 'James McCarthy', role: 'Victim\u2019s Son' },
        { id: 'suspect_turner', name: 'John Turner', role: 'Wealthy Landowner & Neighbour' },
        { id: 'suspect_vagrant', name: 'Unidentified Vagrant', role: 'Alleged tramp, per anonymous tip' },
      ]

  // suspectId, selectedCitationIdx, and result all now live in App so an
  // in-progress (not yet submitted) verdict survives switching tabs. Only
  // seed a default suspect once, the first time this screen is opened with
  // nothing chosen yet.
  useEffect(() => {
    if (!suspectId && (prediction?.id || investigation?.suspect_id)) {
      setSuspectId(prediction?.id || investigation?.suspect_id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const availableCitations = investigation?.citations || []

  function toggleCitation(i) {
    setSelectedCitationIdx((prev) => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  async function submit() {
    if (!suspectId) return
    setLoading(true)
    setError(null)
    try {
      const supporting = availableCitations.filter((_, i) => selectedCitationIdx.has(i))
      const res = await api.submitVerdict(suspectId, supporting)
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section>
      <div className="section-title">
        <span>Final Verdict</span>
        <span className="stamp-small">no take-backs</span>
      </div>

      <p>Name your suspect and pick the citations you're standing on. This is graded once, server-side.</p>

      <strong style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem' }}>Accuse</strong>
      <div className="suspect-picker" style={{ marginTop: 8 }}>
        {list.map((c) => (
          <button
            key={c.id}
            className={`suspect-pill ${suspectId === c.id ? 'active' : ''}`}
            onClick={() => setSuspectId(c.id)}
          >
            {c.name || c.id}
          </button>
        ))}
      </div>

      <div style={{ marginTop: 18 }}>
        <strong style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem' }}>
          Supporting citations {availableCitations.length === 0 && '(none available — run the Investigator first)'}
        </strong>
        <div style={{ marginTop: 8 }}>
          {availableCitations.map((c, i) => (
            <label className="citation-toggle" key={i}>
              <input type="checkbox" checked={selectedCitationIdx.has(i)} onChange={() => toggleCitation(i)} />
              <div>
                <div className="doc-id" style={{ marginBottom: 4 }}>
                  <span>{c.document_id}</span>
                  <span className={`badge ${c.verified ? 'badge-verified' : 'badge-unverified'}`}>
                    {c.verified ? '✓ verified' : '⚠ unverified'}
                  </span>
                </div>
                <span style={{ fontSize: '0.85rem' }}>{c.claim}</span>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div style={{ textAlign: 'center', marginTop: 20 }}>
        <button className="btn btn-primary" onClick={submit} disabled={!suspectId || loading}>
          {loading ? 'Filing verdict...' : 'Submit Verdict'}
        </button>
      </div>
      {error && <p className="error-note">{error}</p>}

      {result && (
        <div className={`verdict-result ${result.correct ? 'correct' : 'incorrect'}`}>
          <p style={{ margin: 0, fontFamily: 'var(--font-display)' }}>
            {result.correct ? 'CASE CLOSED — CORRECT' : 'CASE MISFILED — INCORRECT'}
          </p>
          <div className="score-dial">{(result.score * 100).toFixed(0)}%</div>
          <p style={{ margin: 0 }}>{result.explanation}</p>
        </div>
      )}
    </section>
  )
}

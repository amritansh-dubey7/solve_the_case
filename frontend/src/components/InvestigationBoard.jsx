import { useState } from 'react'
import { api } from '../api.js'

function CitationBadge({ c }) {
  return (
    <div className={`evidence-card ${c.verified ? 'verified' : 'unverified'}`} style={{ marginBottom: 8 }}>
      <div className="doc-id">
        <span>{c.document_id}</span>
        <span className={`badge ${c.verified ? 'badge-verified' : 'badge-unverified'}`}>
          {c.verified ? '✓ verified' : '⚠ unverified'}
        </span>
      </div>
      <p style={{ margin: 0, fontSize: '0.88rem' }}>{c.claim}</p>
    </div>
  )
}

export default function InvestigationBoard({ investigation, setInvestigation, factCheck, setFactCheck, prediction }) {
  const [loadingInvestigate, setLoadingInvestigate] = useState(false)
  const [loadingFactCheck, setLoadingFactCheck] = useState(false)
  const [error, setError] = useState(null)

  async function runInvestigate() {
    setLoadingInvestigate(true)
    setError(null)
    setFactCheck(null)
    try {
      const res = await api.investigate()
      setInvestigation(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoadingInvestigate(false)
    }
  }

  async function runFactCheck() {
    if (!investigation) return
    setLoadingFactCheck(true)
    setError(null)
    try {
      const res = await api.factCheck(investigation)
      setFactCheck(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoadingFactCheck(false)
    }
  }

  return (
    <section>
      <div className="section-title">
        <span>Agents at Work</span>
        <span className="stamp-small">investigator vs. fact-checker</span>
      </div>

      {prediction && (
        <p className="hint-note" style={{ marginBottom: 14 }}>
          Your locked-in hunch was <strong>{prediction.name}</strong>, at {new Date(prediction.timestamp).toLocaleTimeString()}.
          Let's see if the agents agree.
        </p>
      )}

      <div className="select-row">
        <button className="btn btn-primary" onClick={runInvestigate} disabled={loadingInvestigate}>
          {loadingInvestigate ? 'Investigating...' : 'Run Investigator'}
        </button>
        <button className="btn btn-danger" onClick={runFactCheck} disabled={!investigation || loadingFactCheck}>
          {loadingFactCheck ? 'Cross-examining...' : 'Run Fact-Checker'}
        </button>
      </div>
      {error && <p className="error-note">{error}</p>}

      <div className="versus-grid">
        <div className="panel panel-investigator">
          <h3>🔎 The Investigator</h3>
          {!investigation && <p className="hint-note">No theory yet. Run the Investigator above.</p>}
          {investigation && (
            <>
              <p><strong>Suspect:</strong> {investigation.suspect_id}</p>
              <p>{investigation.theory}</p>
              <p style={{ marginBottom: 2 }}>
                Confidence: {(investigation.confidence * 100).toFixed(0)}%
                {investigation.needs_more_evidence && (
                  <span className="badge badge-unverified" style={{ marginLeft: 8 }}>needs more evidence</span>
                )}
              </p>
              <div className="confidence-bar-track">
                <div className="confidence-bar-fill" style={{ width: `${investigation.confidence * 100}%` }} />
              </div>
              <p className="hint-note">Retries used: {investigation.retries_used}</p>

              <div style={{ marginTop: 14 }}>
                <strong style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem' }}>Citations</strong>
                {investigation.citations.map((c, i) => (
                  <CitationBadge key={i} c={c} />
                ))}
              </div>

              <details className="reasoning-trace">
                <summary>Reasoning trace ({investigation.reasoning_trace.length} steps)</summary>
                <ol>
                  {investigation.reasoning_trace.map((step, i) => (
                    <li key={i}>{step}</li>
                  ))}
                </ol>
              </details>
            </>
          )}
        </div>

        <div className="panel panel-factchecker">
          <h3>⚖️ The Fact-Checker</h3>
          {!factCheck && (
            <p className="hint-note">
              {investigation ? 'Run the Fact-Checker above to challenge this theory.' : 'Waiting on the Investigator.'}
            </p>
          )}
          {factCheck && (
            <>
              <p>
                Confidence delta:{' '}
                <strong style={{ color: factCheck.confidence_delta < 0 ? 'var(--red-wax)' : 'var(--green-verified)' }}>
                  {factCheck.confidence_delta > 0 ? '+' : ''}
                  {(factCheck.confidence_delta * 100).toFixed(0)}%
                </strong>
              </p>

              <strong style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem' }}>Contradictions</strong>
              {factCheck.contradictions.length === 0 && <p className="hint-note">None found.</p>}
              {factCheck.contradictions.map((c, i) => (
                <CitationBadge key={i} c={c} />
              ))}

              {factCheck.alternative_suspects.length > 0 && (
                <p style={{ marginTop: 10 }}>
                  <strong style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem' }}>Alt. suspects: </strong>
                  {factCheck.alternative_suspects.join(', ')}
                </p>
              )}

              {factCheck.weaknesses.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <strong style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem' }}>Weaknesses</strong>
                  <ul>
                    {factCheck.weaknesses.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  )
}

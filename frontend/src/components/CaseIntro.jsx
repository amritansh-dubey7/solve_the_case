import { useEffect, useState } from 'react'
import { api } from '../api.js'

// Case Intro pulls its summary + candidate list from corpus_manifest.json.
// If the manifest can't be reached yet (e.g. /ingest hasn't run, or the
// static mount isn't wired up), it falls back to a short hardcoded summary
// so the screen is never empty, per the phase spec ("static, from
// corpus_manifest.json or a small hardcoded summary").
const FALLBACK_SUMMARY = {
  title: 'The Boscombe Valley Mystery',
  synopsis:
    'Charles McCarthy, tenant of Hatherley Farm, was found dying by his son James near Boscombe Pool on the afternoon of June 3rd, his skull ' +
    'battered by a heavy blow. Witnesses heard father and son quarrelling minutes before, and James — caught alone with the body, and caught in ' +
    'a lie about even having seen his father that day — is already in custody. But a second set of footprints, a torn scrap of grey cloak, and a ' +
    'dying man\u2019s garbled last word suggest someone else was at the pool that afternoon.',
  candidates: [
    { id: 'suspect_james', name: 'James McCarthy', role: 'Victim\u2019s Son' },
    { id: 'suspect_turner', name: 'John Turner', role: 'Wealthy Landowner & Neighbour' },
    { id: 'suspect_vagrant', name: 'Unidentified Vagrant', role: 'Alleged tramp, per anonymous tip' },
  ],
}

function initials(name) {
  return name.split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase()
}

export default function CaseIntro({ candidates, setCandidates }) {
  const [summary, setSummary] = useState(null)
  const [status, setStatus] = useState('loading') // loading | manifest | fallback

  useEffect(() => {
    api
      .getManifest()
      .then((manifest) => {
        // corpus_manifest.json is document metadata (document_id, type,
        // timestamp, verified, source) — it was never going to contain a
        // suspect/candidate list. This is expected, not a fetch failure,
        // so it must not be reported as "manifest unreachable".
        const list = (manifest.documents || manifest.candidates || [])
          .filter((d) => d.type === 'suspect' || d.role)
          .map((d) => ({ id: d.entity_id || d.document_id, name: d.name, role: d.role || d.type }))
        setSummary(FALLBACK_SUMMARY)
        setCandidates(list.length ? list : FALLBACK_SUMMARY.candidates)
        setStatus('manifest') // the fetch succeeded — no warning badge
      })
      .catch(() => {
        // The fetch itself failed (network error, 404, backend down) —
        // this is the only case that should warn the user.
        setSummary(FALLBACK_SUMMARY)
        setCandidates(FALLBACK_SUMMARY.candidates)
        setStatus('fallback')
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const list = candidates.length ? candidates : FALLBACK_SUMMARY.candidates

  return (
    <section>
      <div className="section-title">
        <span>The Brief</span>
        {status === 'fallback' && <span className="stamp-small">backend unreachable — showing offline copy</span>}
      </div>

      {summary ? (
        <>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', marginTop: 0 }}>
            {summary.title}
          </h2>
          <p>{summary.synopsis}</p>
        </>
      ) : (
        <p className="hint-note">Pulling the file...</p>
      )}

      <div className="section-title" style={{ marginTop: 24 }}>
        <span>Persons of Interest</span>
      </div>
      <div className="candidate-grid">
        {list.map((c) => (
          <div className="candidate-card" key={c.id}>
            <div className="avatar-ring">{initials(c.name || c.id)}</div>
            <h4>{c.name || c.id}</h4>
            <p className="role">{c.role}</p>
          </div>
        ))}
      </div>

      <p className="hint-note" style={{ marginTop: 20 }}>
        Head to the Interrogation Room to question a suspect directly, or the Evidence Locker to
        search the case documents yourself.
      </p>
    </section>
  )
}

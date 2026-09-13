import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function Interrogation({ candidates, suspectId, setSuspectId, sessions, setSessions }) {
  const list = candidates.length
    ? candidates
    : [
        { id: 'suspect_james', name: 'James McCarthy', role: 'Victim\u2019s Son' },
        { id: 'suspect_turner', name: 'John Turner', role: 'Wealthy Landowner & Neighbour' },
        { id: 'suspect_vagrant', name: 'Unidentified Vagrant', role: 'Alleged tramp, per anonymous tip' },
      ]

  // suspectId/sessions now live in App so they survive tab switches; only
  // pick a default once, the first time this screen is ever opened.
  useEffect(() => {
    if (suspectId === null) setSuspectId(list[0].id)
  }, [suspectId])
  const activeSuspectId = suspectId || list[0].id

  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)

  const current = sessions[activeSuspectId] || { session_id: null, messages: [] }

  async function send() {
    if (!draft.trim()) return
    setSending(true)
    setError(null)
    const outgoing = draft.trim()
    setDraft('')

    setSessions((prev) => ({
      ...prev,
      [activeSuspectId]: {
        ...current,
        messages: [...current.messages, { role: 'detective', content: outgoing }],
      },
    }))

    try {
      const res = await api.interrogate(activeSuspectId, outgoing, current.session_id)
      setSessions((prev) => ({
        ...prev,
        [activeSuspectId]: {
          session_id: res.session_id,
          messages: [
            ...(prev[activeSuspectId]?.messages || []),
            { role: 'suspect', content: res.reply, citations: res.grounding_citations },
          ],
        },
      }))
    } catch (e) {
      setError(e.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <section>
      <div className="section-title">
        <span>Interrogation Room</span>
        <span className="stamp-small">recorded</span>
      </div>

      <div className="suspect-picker">
        {list.map((s) => (
          <button
            key={s.id}
            className={`suspect-pill ${s.id === activeSuspectId ? 'active' : ''}`}
            onClick={() => setSuspectId(s.id)}
          >
            {s.name || s.id}
          </button>
        ))}
      </div>

      <div className="chat-window">
        {current.messages.length === 0 && (
          <p className="hint-note">The room is quiet. Ask your first question.</p>
        )}
        {current.messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role}`}>
            <span className="who">{m.role === 'detective' ? 'You' : list.find((s) => s.id === activeSuspectId)?.name || activeSuspectId}</span>
            {m.content}
            {m.citations && m.citations.length > 0 && (
              <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {m.citations.map((c, j) => (
                  <span key={j} className={`badge ${c.verified ? 'badge-verified' : 'badge-unverified'}`}>
                    {c.verified ? '✓ verified' : '⚠ unverified'} · {c.document_id}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="form-row">
        <input
          type="text"
          placeholder={`Ask ${list.find((s) => s.id === activeSuspectId)?.name || 'the suspect'} something...`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          disabled={sending}
        />
        <button className="btn btn-primary" onClick={send} disabled={sending || !draft.trim()}>
          {sending ? 'Waiting...' : 'Ask'}
        </button>
      </div>
      {error && <p className="error-note">{error}</p>}
    </section>
  )
}

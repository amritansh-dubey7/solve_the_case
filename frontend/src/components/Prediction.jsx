export default function Prediction({ candidates, prediction, setPrediction, choice, setChoice }) {
  const list = candidates.length
    ? candidates
    : [
        { id: 'suspect_james', name: 'James McCarthy', role: 'Victim\u2019s Son' },
        { id: 'suspect_turner', name: 'John Turner', role: 'Wealthy Landowner & Neighbour' },
        { id: 'suspect_vagrant', name: 'Unidentified Vagrant', role: 'Alleged tramp, per anonymous tip' },
      ]

  // choice (the not-yet-locked-in radio pick) now lives in App so it
  // survives switching tabs before you hit "Lock In".

  function lockIn() {
    if (!choice) return
    const suspect = list.find((c) => c.id === choice)
    setPrediction({ id: choice, name: suspect?.name || choice, timestamp: Date.now() })
  }

  return (
    <section>
      <div className="section-title">
        <span>Your Hunch</span>
        <span className="stamp-small">locked before the agents talk</span>
      </div>

      <p>
        Before you see what the Investigator and Fact-Checker conclude, put your own money down.
        Once locked, your guess is timestamped and can't be changed here — no peeking at the agents first.
      </p>

      <div className="candidate-grid" style={{ marginBottom: 20 }}>
        {list.map((c) => (
          <label
            key={c.id}
            className="candidate-card"
            style={{
              cursor: prediction ? 'default' : 'pointer',
              outline: choice === c.id ? '3px solid var(--brass)' : 'none',
            }}
          >
            <input
              type="radio"
              name="prediction"
              value={c.id}
              checked={choice === c.id}
              onChange={() => !prediction && setChoice(c.id)}
              disabled={!!prediction}
              style={{ display: 'none' }}
            />
            <div className="avatar-ring">{(c.name || c.id).slice(0, 2).toUpperCase()}</div>
            <h4>{c.name || c.id}</h4>
            <p className="role">{c.role}</p>
          </label>
        ))}
      </div>

      {!prediction ? (
        <div style={{ textAlign: 'center' }}>
          <button className="btn btn-primary" onClick={lockIn} disabled={!choice}>
            Lock In My Guess
          </button>
        </div>
      ) : (
        <div className="lockin-box">
          <p style={{ margin: 0 }}>You accused:</p>
          <div className="stamp">{prediction.name}</div>
          <p className="hint-note" style={{ marginTop: 10 }}>
            Locked at {new Date(prediction.timestamp).toLocaleString()}
          </p>
        </div>
      )}
    </section>
  )
}

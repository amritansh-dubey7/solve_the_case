import { Suspense, lazy, useState } from 'react'
import CaseIntro from './components/CaseIntro.jsx'
import Interrogation from './components/Interrogation.jsx'
import EvidenceSearch from './components/EvidenceSearch.jsx'
import InvestigationBoard from './components/InvestigationBoard.jsx'
import Prediction from './components/Prediction.jsx'
import Verdict from './components/Verdict.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'

// Lazy-loaded: react-force-graph-2d can throw at import time in some
// environments. Loading it lazily + behind ErrorBoundary/Suspense means a
// failure there shows an error in that one tab instead of blanking the
// whole app.
const EvidenceGraph = lazy(() => import('./components/EvidenceGraph.jsx'))

const TABS = [
  { id: 'intro', label: 'Case File' },
  { id: 'interrogate', label: 'Interrogation Room' },
  { id: 'search', label: 'Evidence Locker' },
  { id: 'graph', label: 'Corkboard' },
  { id: 'prediction', label: 'Your Hunch' },
  { id: 'board', label: 'Agents at Work' },
  { id: 'verdict', label: 'Final Verdict' },
]

export default function App() {
  const [tab, setTab] = useState('intro')
  // Shared client-side state across screens (per spec: prediction is stored
  // client-side, and the Investigator result feeds the Fact-Checker call).
  const [candidates, setCandidates] = useState([])
  const [prediction, setPrediction] = useState(null)
  const [investigation, setInvestigation] = useState(null)
  const [factCheck, setFactCheck] = useState(null)
  // Interrogation Room and Evidence Locker used to be unmounted whenever the
  // user switched tabs (they were only rendered when `tab === 'x'`), so all
  // their local useState — chat history, search query/results — got wiped
  // the moment you left the tab. Lifting that state up here, same pattern as
  // candidates/prediction/investigation above, means the tab can unmount and
  // remount freely and the conversation/search results survive.
  const [suspectId, setSuspectId] = useState(null)
  const [sessions, setSessions] = useState({}) // suspect_id -> { session_id, messages: [] }
  const [evidenceQuery, setEvidenceQuery] = useState('')
  const [evidenceResults, setEvidenceResults] = useState(null)
  // Same reasoning for the remaining screens with meaningful in-progress
  // user input: an unlocked hunch pick, and an in-progress (not yet
  // submitted) verdict selection + its result once submitted.
  const [predictionChoice, setPredictionChoice] = useState('')
  const [verdictSuspectId, setVerdictSuspectId] = useState('')
  const [verdictCitations, setVerdictCitations] = useState(new Set())
  const [verdictResult, setVerdictResult] = useState(null)

  return (
    <div className="app-shell">
      <header className="masthead">
        <p className="case-number">CASE No. 001 — CONFIDENTIAL</p>
        <h1>Solve the Case</h1>
        <p className="subtitle">Two AI agents are on it. So are you. Whoever's right, wins.</p>
      </header>

      <nav className="folder-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`folder-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="case-sheet">
        <ErrorBoundary>
          {tab === 'intro' && <CaseIntro candidates={candidates} setCandidates={setCandidates} />}
          {tab === 'interrogate' && (
            <Interrogation
              candidates={candidates}
              suspectId={suspectId}
              setSuspectId={setSuspectId}
              sessions={sessions}
              setSessions={setSessions}
            />
          )}
          {tab === 'search' && (
            <EvidenceSearch
              query={evidenceQuery}
              setQuery={setEvidenceQuery}
              results={evidenceResults}
              setResults={setEvidenceResults}
            />
          )}
          {tab === 'graph' && (
            <Suspense fallback={<p className="hint-note">Loading the corkboard...</p>}>
              <EvidenceGraph />
            </Suspense>
          )}
          {tab === 'prediction' && (
            <Prediction
              candidates={candidates}
              prediction={prediction}
              setPrediction={setPrediction}
              choice={predictionChoice}
              setChoice={setPredictionChoice}
            />
          )}
          {tab === 'board' && (
            <InvestigationBoard
              investigation={investigation}
              setInvestigation={setInvestigation}
              factCheck={factCheck}
              setFactCheck={setFactCheck}
              prediction={prediction}
            />
          )}
          {tab === 'verdict' && (
            <Verdict
              candidates={candidates}
              investigation={investigation}
              prediction={prediction}
              suspectId={verdictSuspectId}
              setSuspectId={setVerdictSuspectId}
              selectedCitationIdx={verdictCitations}
              setSelectedCitationIdx={setVerdictCitations}
              result={verdictResult}
              setResult={setVerdictResult}
            />
          )}
        </ErrorBoundary>
      </main>
    </div>
  )
}

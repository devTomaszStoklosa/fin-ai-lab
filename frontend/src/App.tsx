import { useEffect, useState } from 'react'
import { fetchHealth, fetchLlmUsage, fetchPortfolios } from './api'
import type { LlmUsage, Portfolio } from './api'
import BreakdownsEditor from './BreakdownsEditor'
import FilingsQA from './FilingsQA'
import InstrumentLinks from './InstrumentLinks'
import MarketPulse from './MarketPulse'
import ModelComparison from './ModelComparison'
import Overview from './Overview'
import PortfolioDetail from './PortfolioDetail'
import './App.css'

type View =
  | 'portfolios'
  | 'market-pulse'
  | 'model-comparison'
  | 'filings-qa'
  | 'breakdowns'
  | 'instruments'

function App() {
  const [portfolios, setPortfolios] = useState<Portfolio[] | null>(null)
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [llmUsage, setLlmUsage] = useState<LlmUsage[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [view, setView] = useState<View>('portfolios')
  // Which breakdown the editor opens on (null: its first one).
  const [editorBreakdownId, setEditorBreakdownId] = useState<string | null>(null)

  function manageBreakdowns(breakdownId: string | null) {
    setEditorBreakdownId(breakdownId)
    setView('breakdowns')
  }

  function reloadPortfolios() {
    fetchPortfolios()
      .then(setPortfolios)
      .catch((e: Error) => setError(e.message))
  }

  // The backend can still be starting up when this page loads (e.g. the
  // autostart script opens the browser as soon as the frontend answers,
  // not once the backend also does) -- a one-shot check left the pill
  // stuck on "niedostępny" forever even after the backend came up.
  // Retries until healthy, then loads everything else that depends on it.
  useEffect(() => {
    let cancelled = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    function checkHealth() {
      fetchHealth()
        .then(() => {
          if (cancelled) return
          setHealthy(true)
          fetchLlmUsage()
            .then(setLlmUsage)
            .catch(() => setLlmUsage(null))
          reloadPortfolios()
        })
        .catch(() => {
          if (cancelled) return
          setHealthy(false)
          retryTimer = setTimeout(checkHealth, 2000)
        })
    }
    checkHealth()

    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [])

  const selectedPortfolio = portfolios?.find((p) => p.id === selectedId) ?? null
  const geminiUsage = llmUsage?.find((u) => u.model === 'gemini-3.6-flash') ?? null
  const geminiLow = geminiUsage !== null && geminiUsage.rpd_limit - geminiUsage.calls_today <= 4

  return (
    <div className="page">
      <header className="topbar">
        <span className="wordmark">Portfel</span>
        <span className="tag">lokalne narzędzie</span>
        {view !== 'market-pulse' && (
          <button type="button" className="nav-link" onClick={() => setView('market-pulse')}>
            Puls rynku
          </button>
        )}
        {view !== 'model-comparison' && (
          <button type="button" className="nav-link" onClick={() => setView('model-comparison')}>
            Porównanie modeli
          </button>
        )}
        {view !== 'filings-qa' && (
          <button type="button" className="nav-link" onClick={() => setView('filings-qa')}>
            Zapytaj raport
          </button>
        )}
        <span className="spacer" />
        {geminiUsage && (
          <span className={`budget ${geminiLow ? 'budget-warn' : ''}`}>
            <span className="budget-dot" />
            Gemini: {geminiUsage.calls_today} / {geminiUsage.rpd_limit} dzisiaj
          </span>
        )}
        <span className={`health ${healthy ? 'ok' : healthy === false ? 'down' : ''}`}>
          {healthy === null ? 'sprawdzam…' : healthy ? 'backend OK' : 'backend niedostępny'}
        </span>
      </header>

      <main>
        {error && <p className="error content">{error}</p>}
        {view === 'market-pulse' ? (
          <MarketPulse
            onBack={() => setView('portfolios')}
            llmUsage={llmUsage}
            onUsageChange={setLlmUsage}
          />
        ) : view === 'model-comparison' ? (
          <ModelComparison onBack={() => setView('portfolios')} />
        ) : view === 'filings-qa' ? (
          <FilingsQA
            onBack={() => setView('portfolios')}
            llmUsage={llmUsage}
            onUsageChange={setLlmUsage}
          />
        ) : view === 'breakdowns' ? (
          <BreakdownsEditor initialId={editorBreakdownId} onBack={() => setView('portfolios')} />
        ) : view === 'instruments' ? (
          <InstrumentLinks onBack={() => setView('portfolios')} />
        ) : selectedPortfolio ? (
          <PortfolioDetail
            portfolio={selectedPortfolio}
            onBack={() => setSelectedId(null)}
            onDeleted={() => {
              setSelectedId(null)
              reloadPortfolios()
            }}
            llmUsage={llmUsage}
            onUsageChange={setLlmUsage}
            onManageBreakdowns={manageBreakdowns}
          />
        ) : (
          <Overview
            portfolios={portfolios}
            onSelect={setSelectedId}
            onCreated={reloadPortfolios}
            onManageBreakdowns={manageBreakdowns}
            onManageInstruments={() => setView('instruments')}
          />
        )}
      </main>
    </div>
  )
}

export default App

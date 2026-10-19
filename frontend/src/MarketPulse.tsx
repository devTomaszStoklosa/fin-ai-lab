import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  askMarketPulse,
  fetchLlmUsage,
  fetchMarketPulseBrief,
  fetchMarketPulseIndicators,
} from './api'
import type { LlmUsage, MarketPulseAskAnswer, MarketPulseBrief, MarketPulseIndicators } from './api'

type Props = {
  onBack: () => void
  llmUsage: LlmUsage[] | null
  onUsageChange: (usage: LlmUsage[] | null) => void
}

const REGIME_LABEL: Record<MarketPulseIndicators['regime'], string> = {
  'risk-on': 'RYZYKOWNY (RISK-ON)',
  neutral: 'NEUTRALNY',
  'risk-off': 'DEFENSYWNY (RISK-OFF)',
}

function changeClass(change: string | null): string {
  if (change === null) return 'muted'
  return Number(change) >= 0 ? 'return-gain' : 'return-loss'
}

function formatChange(change: string | null, unit: string): string {
  if (change === null) return 'bez zmian'
  const n = Number(change)
  return `${n >= 0 ? '+' : ''}${change} ${unit}`
}

function MarketPulse({ onBack, llmUsage, onUsageChange }: Props) {
  const [brief, setBrief] = useState<MarketPulseBrief | null>(null)
  const [indicators, setIndicators] = useState<MarketPulseIndicators | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<MarketPulseAskAnswer | null>(null)
  const [asking, setAsking] = useState(false)
  const [askError, setAskError] = useState<string | null>(null)

  useEffect(() => {
    fetchMarketPulseBrief()
      .then(setBrief)
      .catch((e: Error) => setLoadError(e.message))
    fetchMarketPulseIndicators()
      .then(setIndicators)
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  function handleAsk(event: FormEvent) {
    event.preventDefault()
    if (!question.trim()) return
    setAsking(true)
    setAskError(null)
    askMarketPulse(question.trim())
      .then((result) => {
        setAnswer(result)
        return fetchLlmUsage()
      })
      .then(onUsageChange)
      .catch((e: Error) => setAskError(e.message))
      .finally(() => setAsking(false))
  }

  const geminiUsage = llmUsage?.find((u) => u.model === 'gemini-3.6-flash') ?? null

  return (
    <div className="content">
      <button type="button" className="back-link" onClick={onBack}>
        ← Portfele
      </button>
      <h1>Puls rynku</h1>
      {loadError && <p className="error">{loadError}</p>}

      {indicators && (
        <>
          <div className="mp-regime-row">
            <span className="badge">Reżim: {REGIME_LABEL[indicators.regime]}</span>
            <span className="muted small">{indicators.regime_signals.join('; ')}</span>
          </div>

          <div className="metric-cards">
            {indicators.indicators.map((indicator) => (
              <div className="metric-card" key={indicator.series_id}>
                <div className="muted small">{indicator.label}</div>
                <div className="metric-value mono">
                  {indicator.value} {indicator.unit}
                </div>
                <div className={`mono small ${changeClass(indicator.change)}`}>
                  {formatChange(indicator.change, indicator.unit)}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <section className="report">
        <div className="report-header">
          <h2>Dzisiejszy brief</h2>
        </div>
        {brief ? (
          <>
            <p className="muted small">
              Wygenerowano {new Date(brief.date).toLocaleDateString('pl-PL')} · zadanie w
              Harmonogramie Zadań
            </p>
            <div className="report-content">{brief.text}</div>
          </>
        ) : (
          <p className="muted">Brak jeszcze wygenerowanego briefu.</p>
        )}
      </section>

      <section className="report mp-ask">
        <div className="report-header">
          <h2>Zapytaj o rynek</h2>
          {geminiUsage && (
            <span className="muted small">
              {geminiUsage.calls_today} z {geminiUsage.rpd_limit} dzisiejszych wywołań
            </span>
          )}
        </div>
        <form className="mp-ask-form" onSubmit={handleAsk}>
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="np. Jak wygląda ekspozycja na sektor bankowy w obecnym reżimie?"
          />
          <button type="submit" disabled={asking}>
            {asking ? 'Pytam…' : 'Zapytaj'}
          </button>
        </form>
        {askError && <p className="error">{askError}</p>}
        {answer && <div className="report-content">{answer.text}</div>}
      </section>
    </div>
  )
}

export default MarketPulse

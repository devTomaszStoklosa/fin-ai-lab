import { useEffect, useRef, useState } from 'react'
import {
  confirmCommitteeBudget,
  fetchCommitteeJob,
  fetchLlmUsage,
  startCommitteeAnalysis,
} from './api'
import type {
  CommitteeBrief,
  CommitteeJob,
  CommitteeReportResult,
  CommitteeVariant,
  ComparisonReportResult,
  LlmUsage,
} from './api'

type Props = {
  portfolioId: string
  onBack: () => void
  llmUsage: LlmUsage[] | null
  onUsageChange: (usage: LlmUsage[] | null) => void
}

const VARIANTS: {
  id: CommitteeVariant
  label: string
  calls: string
  description: string
}[] = [
  {
    id: 'single',
    label: 'Pojedynczy agent',
    calls: '~1 wywołanie',
    description: 'Szybka, tania analiza — jedna perspektywa. ~10 s.',
  },
  {
    id: 'committee',
    label: 'Komitet',
    calls: '~8 wywołań',
    description: '4 równoległe perspektywy + krytyk. ~1,5–2 min (throttling RPM).',
  },
  {
    id: 'compare',
    label: 'Porównanie',
    calls: '~15 wywołań',
    description: 'Oba warianty + sędzia LLM na ślepo. ~3 min.',
  },
]

// Estimates from the ticket/design reference, not measured per-run data --
// the real cost varies (budget confirm, cached briefs, API latency).
const VARIANT_ESTIMATED_CALLS: Record<CommitteeVariant, number> = {
  single: 1,
  committee: 8,
  compare: 15,
}

const PERSPECTIVE_LABEL: Record<CommitteeBrief['perspective'], string> = {
  fundamental: 'Fundamentalna',
  macro: 'Makro',
  sentiment: 'Sentyment',
  stress: 'Stress-test (Kwant)',
}

const PERSPECTIVE_SOURCE: Record<CommitteeBrief['perspective'], string> = {
  fundamental: 'źródło: P2 (sprawozdania)',
  macro: 'źródło: P3 (FRED, NBP)',
  sentiment: 'źródło: P4 (klasyfikator newsów)',
  stress: 'zero wywołań LLM · liczone w kodzie z wag portfela',
}

const IN_FLIGHT_STATUSES = new Set(['pending', 'running', 'awaiting_confirmation'])

function formatDuration(ms: number): string {
  const totalSeconds = Math.round(ms / 1000)
  if (totalSeconds < 60) return `${totalSeconds} s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes} min ${seconds} s`
}

function CommitteeAnalysis({ portfolioId, onBack, llmUsage, onUsageChange }: Props) {
  const [variant, setVariant] = useState<CommitteeVariant>('committee')
  const [job, setJob] = useState<CommitteeJob | null>(null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current)
    }
  }, [])

  function schedulePoll(jobId: string) {
    if (pollRef.current) clearTimeout(pollRef.current)
    pollRef.current = setTimeout(() => {
      fetchCommitteeJob(portfolioId, jobId)
        .then((updated) => {
          setJob(updated)
          if (IN_FLIGHT_STATUSES.has(updated.status)) {
            schedulePoll(jobId)
          } else {
            fetchLlmUsage().then(onUsageChange).catch(() => undefined)
          }
        })
        .catch((e: Error) => setStartError(e.message))
    }, 1500)
  }

  function handleStart(regenerate: boolean) {
    setStarting(true)
    setStartError(null)
    startCommitteeAnalysis(portfolioId, variant, regenerate)
      .then((started) => {
        setJob(started)
        if (IN_FLIGHT_STATUSES.has(started.status)) {
          schedulePoll(started.job_id)
        } else {
          fetchLlmUsage().then(onUsageChange).catch(() => undefined)
        }
      })
      .catch((e: Error) => setStartError(e.message))
      .finally(() => setStarting(false))
  }

  function handleConfirm(approve: boolean) {
    if (!job) return
    setConfirming(true)
    confirmCommitteeBudget(portfolioId, job.job_id, approve)
      .then((updated) => {
        setJob(updated)
        schedulePoll(updated.job_id)
      })
      .catch((e: Error) => setStartError(e.message))
      .finally(() => setConfirming(false))
  }

  const geminiUsage = llmUsage?.find((u) => u.model === 'gemini-3.6-flash') ?? null
  const estimatedCalls = VARIANT_ESTIMATED_CALLS[variant]
  const busy = starting || (job !== null && IN_FLIGHT_STATUSES.has(job.status))
  const elapsedMs =
    job?.finished_at && job.created_at
      ? new Date(job.finished_at).getTime() - new Date(job.created_at).getTime()
      : null

  return (
    <div className="content">
      <button type="button" className="back-link" onClick={onBack}>
        ← portfel
      </button>
      <h1>Analiza AI</h1>

      <div className="variant-grid">
        {VARIANTS.map((v) => (
          <button
            key={v.id}
            type="button"
            className={`variant-card ${variant === v.id ? 'selected' : ''}`}
            disabled={busy}
            onClick={() => setVariant(v.id)}
          >
            <div className="variant-card-head">
              <span className="serif">{v.label}</span>
              <span className="mono small muted">{v.calls}</span>
            </div>
            <div className="muted small">{v.description}</div>
          </button>
        ))}
      </div>

      <div className="committee-run-row">
        <button type="button" disabled={busy} onClick={() => handleStart(job !== null)}>
          {busy ? 'W toku…' : job ? 'Uruchom ponownie' : 'Uruchom analizę'}
        </button>
        {geminiUsage && (
          <span className="muted small">
            zużyje ok. {estimatedCalls} z {geminiUsage.rpd_limit - geminiUsage.calls_today}{' '}
            pozostałych dzisiejszych wywołań
          </span>
        )}
      </div>

      {startError && (
        <div className="banner banner-error">
          <p>{startError}</p>
        </div>
      )}

      {job && IN_FLIGHT_STATUSES.has(job.status) && job.status !== 'awaiting_confirmation' && (
        <p className="muted">Analiza w toku ({job.variant}) — może potrwać do kilku minut…</p>
      )}

      {job && job.status === 'awaiting_confirmation' && (
        <div className="banner banner-warning">
          <p>Budżet komitetu przekroczony. Kontynuować mimo to?</p>
          <div className="committee-confirm-actions">
            <button type="button" disabled={confirming} onClick={() => handleConfirm(true)}>
              Tak, kontynuuj
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={confirming}
              onClick={() => handleConfirm(false)}
            >
              Nie, przerwij
            </button>
          </div>
        </div>
      )}

      {job && job.status === 'failed' && (
        <div className="banner banner-error">
          <p>{job.error ?? 'Analiza nie powiodła się.'}</p>
        </div>
      )}

      {job && job.status === 'done' && job.result && job.variant !== 'compare' && (
        <CommitteeResultView
          result={job.result as CommitteeReportResult}
          elapsedMs={elapsedMs}
        />
      )}

      {job && job.status === 'done' && job.result && job.variant === 'compare' && (
        <CompareResultView result={job.result as ComparisonReportResult} />
      )}
    </div>
  )
}

function CommitteeResultView({
  result,
  elapsedMs,
}: {
  result: CommitteeReportResult
  elapsedMs: number | null
}) {
  const hasBriefs = result.briefs.length > 0

  return (
    <div className="committee-result">
      {!hasBriefs && (
        <section className="report">
          <div className="report-header">
            <h2>Wynik — pojedynczy agent</h2>
            <span className="muted small">
              koszt {result.cost_usd} USD{elapsedMs !== null && ` · latencja ${formatDuration(elapsedMs)}`}
            </span>
          </div>
          <div className="report-content">{result.text}</div>
        </section>
      )}

      {hasBriefs && (
        <>
          <div className="perspective-cards">
            {result.briefs.map((brief) => (
              <div className="perspective-card" key={brief.perspective}>
                <div className="serif perspective-title">
                  {PERSPECTIVE_LABEL[brief.perspective]}
                </div>
                <div className="perspective-conclusion">{brief.conclusion}</div>
                <div className="confidence-bar">
                  <div
                    className="confidence-fill"
                    style={{ width: `${Math.round(brief.confidence * 100)}%` }}
                  />
                </div>
                <div className="muted small">
                  pewność {brief.confidence.toFixed(2)} · {PERSPECTIVE_SOURCE[brief.perspective]}
                </div>
              </div>
            ))}
          </div>

          {result.disagreements.length > 0 && (
            <div className="banner banner-warning">
              <p style={{ fontWeight: 600 }}>Rozbieżność między perspektywami</p>
              {result.disagreements.map((disagreement) => (
                <p key={disagreement}>{disagreement}</p>
              ))}
            </div>
          )}

          <div className="report-disclaimer muted small">
            To opis ekspozycji i ryzyka z czterech perspektyw, nie rekomendacja inwestycyjna.
            Koszt {result.cost_usd} USD{elapsedMs !== null && ` · latencja ${formatDuration(elapsedMs)}`}.
          </div>
        </>
      )}
    </div>
  )
}

const WINNER_LABEL: Record<ComparisonReportResult['quality_winner'], string> = {
  single_agent: 'Pojedynczy agent',
  committee: 'Komitet',
  tie: 'Remis',
}

function CompareResultView({ result }: { result: ComparisonReportResult }) {
  return (
    <section className="report">
      <div className="report-header">
        <h2>Zwycięzca jakości: {WINNER_LABEL[result.quality_winner]}</h2>
        <span className="badge">sędzia LLM, na ślepo</span>
      </div>
      <p className="muted small">{result.quality_reason}</p>
      <div className="compare-variant-grid">
        <div
          className={`metric-card ${result.quality_winner === 'single_agent' ? 'variant-winner' : ''}`}
        >
          <div className="muted small">single_agent</div>
          <div className="mono metric-value">{result.single_agent.cost_usd} USD</div>
          <div className="mono muted small">{formatDuration(result.single_agent.latency_ms)}</div>
        </div>
        <div
          className={`metric-card ${result.quality_winner === 'committee' ? 'variant-winner' : ''}`}
        >
          <div className="muted small">committee</div>
          <div className="mono metric-value">{result.committee.cost_usd} USD</div>
          <div className="mono muted small">{formatDuration(result.committee.latency_ms)}</div>
        </div>
      </div>
    </section>
  )
}

export default CommitteeAnalysis

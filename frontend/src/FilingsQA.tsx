import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { askFilings, fetchFilingsIndex, fetchLlmUsage } from './api'
import type { FilingType, FilingsAnswer, FilingsIndex, IndexedCompany, LlmUsage } from './api'

type Props = {
  onBack: () => void
  llmUsage: LlmUsage[] | null
  onUsageChange: (usage: LlmUsage[] | null) => void
}

const FILING_LABEL: Record<FilingType, string> = {
  '10-K': '10-K',
  'annual-report-pl': 'roczny',
  'half-year-report-pl': 'półroczny',
  'quarterly-report-pl': 'kwartalny',
}

function filingLabel(company: IndexedCompany): string {
  return `${FILING_LABEL[company.filing_type]} ${company.fiscal_period}`
}

function FilingsQA({ onBack, llmUsage, onUsageChange }: Props) {
  const [index, setIndex] = useState<FilingsIndex | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  // null: search every indexed company.
  const [company, setCompany] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<FilingsAnswer | null>(null)
  const [asking, setAsking] = useState(false)
  const [askError, setAskError] = useState<string | null>(null)

  useEffect(() => {
    fetchFilingsIndex()
      .then((result) => {
        setIndex(result)
        // Start on the first company, like the mockup: a question then
        // doesn't have to name the company to be answered.
        setCompany(result.companies[0]?.company ?? null)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  function handleAsk(event: FormEvent) {
    event.preventDefault()
    if (!question.trim()) return
    setAsking(true)
    setAskError(null)
    askFilings(question.trim(), company)
      .then(setAnswer)
      .catch((e: Error) => setAskError(e.message))
      .finally(() => {
        setAsking(false)
        // A failed call still used a request against the daily limit.
        fetchLlmUsage()
          .then(onUsageChange)
          .catch(() => undefined)
      })
  }

  const geminiUsage = llmUsage?.find((u) => u.model === 'gemini-3.6-flash') ?? null
  const remaining = geminiUsage ? Math.max(geminiUsage.rpd_limit - geminiUsage.calls_today, 0) : null

  return (
    <div className="content content-wide">
      <button type="button" className="back-link" onClick={onBack}>
        ← Portfele
      </button>
      <h1>Zapytaj raport</h1>
      {loadError && <p className="error">{loadError}</p>}

      {index && index.companies.length === 0 && (
        <section className="report">
          <h2>Indeks raportów nie jest jeszcze zbudowany</h2>
          <p className="muted">
            Indeks buduje się poza aplikacją, żeby jedno kliknięcie nie zużyło dziennego limitu
            Gemini. Uruchom w terminalu w katalogu repozytorium:
          </p>
          <pre className="fq-command mono">uv run fin-ai-lab filings-rag build-index</pre>
          <p className="muted small">
            Spółki, których nie uda się dziś zaindeksować, dojdą przy kolejnym uruchomieniu.
          </p>
        </section>
      )}

      {index && index.companies.length > 0 && (
        <div className="fq-layout">
          <aside className="fq-companies">
            <h2>Zaindeksowane spółki</h2>
            <p className="muted small">Tylko te są przeszukiwalne — nie dowolna spółka.</p>
            <button
              type="button"
              className={`fq-chip ${company === null ? 'fq-chip-active' : ''}`}
              aria-pressed={company === null}
              onClick={() => setCompany(null)}
            >
              <span>Wszystkie spółki</span>
            </button>
            {index.companies.map((entry) => (
              <button
                type="button"
                key={entry.company}
                className={`fq-chip ${company === entry.company ? 'fq-chip-active' : ''}`}
                aria-pressed={company === entry.company}
                onClick={() => setCompany(entry.company)}
              >
                <span className="fq-chip-name">
                  <span>{entry.company}</span>
                  {entry.sections.length === 1 && (
                    <span className="muted small">{entry.sections[0]}</span>
                  )}
                </span>
                <span className="mono muted small">{filingLabel(entry)}</span>
              </button>
            ))}
            {index.built_at && (
              <p className="muted small">
                Indeks z {new Date(index.built_at).toLocaleDateString('pl-PL')}
              </p>
            )}
          </aside>

          <div className="fq-main">
            <form className="report fq-ask" onSubmit={handleAsk}>
              <div className="fq-ask-row">
                <span className="badge">{company ?? 'Wszystkie spółki'}</span>
                <input
                  type="text"
                  aria-label="Pytanie o raport"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  maxLength={500}
                  placeholder="np. Jakie ryzyka związane z AI wymienia spółka w sprawozdaniu?"
                />
                <button type="submit" disabled={asking || !question.trim()}>
                  {asking ? 'Pytam…' : 'Zapytaj'}
                </button>
              </div>
              <p className="muted small">
                1 wywołanie embeddingu + 1 wywołanie Gemini
                {geminiUsage && remaining !== null && (
                  <>
                    {' '}
                    · zostało {remaining} z {geminiUsage.rpd_limit} dzisiejszych wywołań
                  </>
                )}
                {company === null && ' · bez wybranej spółki pytanie musi ją wymienić z nazwy'}
              </p>
            </form>

            {askError && <p className="error">{askError}</p>}

            {answer && (
              <section className="report">
                <h2>Odpowiedź</h2>
                <div className={`report-content ${answer.refused ? 'muted' : ''}`}>
                  {answer.text}
                </div>
                {answer.citations.length > 0 && (
                  <div className="fq-sources">
                    <div className="fq-sources-title">Źródła</div>
                    <ol>
                      {answer.citations.map((citation, i) => (
                        <li key={i}>
                          <span className="mono fq-source-number">[{i + 1}]</span>
                          <div>
                            <div className="mono small muted">
                              {citation.company} · {FILING_LABEL[citation.filing_type]}{' '}
                              {citation.fiscal_period} · {citation.section}
                            </div>
                            <blockquote className="fq-excerpt">„{citation.excerpt}”</blockquote>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
                <div className="report-disclaimer muted small">
                  Odpowiedź opisuje treść raportu, nie jest rekomendacją inwestycyjną.
                </div>
              </section>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default FilingsQA

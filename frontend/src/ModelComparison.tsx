import { useEffect, useState } from 'react'
import { fetchComparisonReport } from './api'
import type { ComparisonReport } from './api'

type Props = {
  onBack: () => void
}

// Stable identifier used throughout P4 (comparison_report.py's SUITES,
// docs/specs/p4-news-classifier) for the model actually running in
// production -- highlighted here, not derived from the report's numbers.
const PRODUCTION_MODEL = 'few-shot'

function ModelComparison({ onBack }: Props) {
  const [report, setReport] = useState<ComparisonReport | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    fetchComparisonReport()
      .then(setReport)
      .catch((e: Error) => setLoadError(e.message))
      .finally(() => setLoaded(true))
  }, [])

  return (
    <div className="content">
      <button type="button" className="back-link" onClick={onBack}>
        ← Portfele
      </button>
      <h1>Porównanie modeli</h1>
      {loadError && <p className="error">{loadError}</p>}

      {report && (
        <>
          <div className="mp-regime-row">
            <span className="pill">Zero kosztu wyświetlenia</span>
            <span className="muted small">
              Korpus: {report.corpus_size} nagłówków
              {report.corpus_latest_headline_date &&
                ` · najnowszy nagłówek: ${new Date(
                  report.corpus_latest_headline_date,
                ).toLocaleDateString('pl-PL')}`}{' '}
              · dane z zapisanego raportu porównawczego, bez nowych wywołań LLM
            </span>
          </div>

          <div className="report" style={{ overflowX: 'auto' }}>
            <table className="positions">
              <thead>
                <tr>
                  {report.columns.map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row, index) => {
                  const isProduction = row[0] === PRODUCTION_MODEL
                  return (
                    <tr key={index} className={isProduction ? 'mp-row-highlight' : ''}>
                      {row.map((cell, cellIndex) => (
                        <td
                          key={cellIndex}
                          className={cellIndex > 0 ? 'mono' : ''}
                          style={isProduction && cellIndex === 0 ? { fontWeight: 600 } : undefined}
                        >
                          {cell}
                        </td>
                      ))}
                      <td>{isProduction && <span className="badge">Produkcyjnie</span>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {report.zero_support_notes.length > 0 && (
            <div className="report">
              <div className="report-header">
                <h2>Klasy bez wsparcia w zbiorze testowym</h2>
              </div>
              <ul className="mapping-list">
                {report.zero_support_notes.map((note, index) => (
                  <li key={index} className="muted small">
                    {note}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <section className="report">
            <div className="report-header">
              <h2>Dlaczego few-shot LLM mimo kosztu</h2>
            </div>
            <p className="report-content">
              Na tej wielkości korpusu modele trenowane od zera (TF-IDF, HerBERT, wariant
              skwantyzowany) kolabsują w praktyce do klasy większościowej — to sanity check
              pipeline'u, nie sygnał jakości. Few-shot LLM wygrywa jakościowo wyraźnie, kosztem
              czasu i pieniędzy — decyzja produkcyjna, nie domysł.
            </p>
          </section>
        </>
      )}

      {loaded && !report && !loadError && (
        <p className="muted">Brak jeszcze zapisanego raportu porównawczego.</p>
      )}
    </div>
  )
}

export default ModelComparison

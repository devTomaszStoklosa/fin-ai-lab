import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ImportFailure, UNKNOWN_FORMAT_ERROR, fetchSnapshots, importFile } from './api'
import type { Portfolio, Snapshot } from './api'
import { trimTrailingZeros } from './format'
import ProposeConfig from './ProposeConfig'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

type Props = {
  portfolio: Portfolio
  onBack: () => void
}

function PortfolioDetail({ portfolio, onBack }: Props) {
  const [snapshots, setSnapshots] = useState<Snapshot[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [valuationDate, setValuationDate] = useState(today())
  const [submitting, setSubmitting] = useState(false)
  const [importErrors, setImportErrors] = useState<string[] | null>(null)
  const [importWarnings, setImportWarnings] = useState<string[] | null>(null)
  const [showPropose, setShowPropose] = useState(false)

  function reloadSnapshots() {
    fetchSnapshots(portfolio.id)
      .then(setSnapshots)
      .catch((e: Error) => setLoadError(e.message))
  }

  useEffect(reloadSnapshots, [portfolio.id])

  // Backend returns snapshots newest-first; the detail page shows the
  // current state (the latest one), not a stack of every past import --
  // that history view belongs to portfolio-webapp-S7.
  const latestSnapshot = snapshots && snapshots.length > 0 ? snapshots[0] : null

  function handleImport(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    setSubmitting(true)
    setImportErrors(null)
    setImportWarnings(null)
    setShowPropose(false)
    importFile(portfolio.id, file, valuationDate)
      .then(({ warnings }) => {
        setImportWarnings(warnings)
        setFile(null)
        reloadSnapshots()
      })
      .catch((e: Error) => {
        if (e instanceof ImportFailure) {
          if (e.errors.length === 1 && e.errors[0] === UNKNOWN_FORMAT_ERROR) {
            setShowPropose(true)
            setImportWarnings(e.warnings)
          } else {
            setImportErrors(e.errors)
            setImportWarnings(e.warnings)
          }
        } else {
          setImportErrors([e.message])
        }
      })
      .finally(() => setSubmitting(false))
  }

  function handleProposeApproved(result: { snapshot: Snapshot; warnings: string[] }) {
    setImportWarnings(result.warnings)
    setShowPropose(false)
    setFile(null)
    reloadSnapshots()
  }

  return (
    <div className="content">
      <button type="button" className="back-link" onClick={onBack}>
        ← wszystkie portfele
      </button>

      <header className="detail-header">
        <h1>{portfolio.name}</h1>
        <div className="badges">
          {portfolio.broker && <span className="badge">{portfolio.broker.toUpperCase()}</span>}
          {portfolio.account_type && (
            <span className="badge muted-badge">{portfolio.account_type}</span>
          )}
        </div>
      </header>

      <form className="import-form" onSubmit={handleImport}>
        <h2>Importuj plik</h2>
        <label>
          Plik
          <input
            type="file"
            accept=".xlsx"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          Data wyceny
          <input
            type="date"
            value={valuationDate}
            onChange={(e) => setValuationDate(e.target.value)}
          />
        </label>
        <button type="submit" disabled={!file || submitting}>
          {submitting ? 'Importuję…' : 'Importuj'}
        </button>

        {importErrors && (
          <div className="banner banner-error">
            {importErrors.map((error) => (
              <p key={error}>{error}</p>
            ))}
          </div>
        )}
        {importWarnings && importWarnings.length > 0 && (
          <div className="banner banner-warning">
            {importWarnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        )}
      </form>

      {showPropose && file && (
        <ProposeConfig
          portfolioId={portfolio.id}
          file={file}
          valuationDate={valuationDate}
          onApproved={handleProposeApproved}
          onCancel={() => setShowPropose(false)}
        />
      )}

      <h2>Pozycje</h2>
      {loadError && <p className="error">{loadError}</p>}
      {snapshots === null ? (
        <p>Wczytywanie…</p>
      ) : latestSnapshot === null ? (
        <p className="muted">Brak pozycji — wgraj pierwszy plik powyżej.</p>
      ) : (
        <section className="snapshot">
          <div className="snapshot-meta">
            <span className="badge">{latestSnapshot.broker.toUpperCase()}</span>
            <span>wycena {latestSnapshot.valuation_date}</span>
            <span className="muted small">
              zaimportowano {new Date(latestSnapshot.imported_at).toLocaleString('pl-PL')}
            </span>
          </div>
          {latestSnapshot.positions.length === 0 ? (
            <p className="muted">Brak pozycji w tym imporcie.</p>
          ) : (
            <table className="positions">
              <thead>
                <tr>
                  <th>Instrument</th>
                  <th>ISIN / symbol</th>
                  <th>Ilość</th>
                  <th>Śr. koszt</th>
                  <th>Wartość</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {latestSnapshot.positions.map((position) => (
                  <tr key={position.id}>
                    <td>{position.instrument_name}</td>
                    <td className="muted">{position.isin ?? position.symbol ?? '—'}</td>
                    <td>{trimTrailingZeros(position.quantity)}</td>
                    <td>
                      {position.avg_cost ? trimTrailingZeros(position.avg_cost) : '—'}{' '}
                      {position.cost_currency ?? ''}
                    </td>
                    <td>
                      {position.market_value ? trimTrailingZeros(position.market_value) : '—'}{' '}
                      {position.market_currency ?? ''}
                    </td>
                    <td className="muted">{position.resolution_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  )
}

export default PortfolioDetail

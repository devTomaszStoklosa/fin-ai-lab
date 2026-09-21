import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ImportFailure, fetchSnapshots, importFile } from './api'
import type { Portfolio, Snapshot } from './api'

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

  function reloadSnapshots() {
    fetchSnapshots(portfolio.id)
      .then(setSnapshots)
      .catch((e: Error) => setLoadError(e.message))
  }

  useEffect(reloadSnapshots, [portfolio.id])

  function handleImport(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    setSubmitting(true)
    setImportErrors(null)
    setImportWarnings(null)
    importFile(portfolio.id, file, valuationDate)
      .then(({ warnings }) => {
        setImportWarnings(warnings)
        setFile(null)
        reloadSnapshots()
      })
      .catch((e: Error) => {
        if (e instanceof ImportFailure) {
          setImportErrors(e.errors)
          setImportWarnings(e.warnings)
        } else {
          setImportErrors([e.message])
        }
      })
      .finally(() => setSubmitting(false))
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

      <h2>Snapshoty</h2>
      {loadError && <p className="error">{loadError}</p>}
      {snapshots === null ? (
        <p>Wczytywanie…</p>
      ) : snapshots.length === 0 ? (
        <p className="muted">Brak importów — wgraj pierwszy plik powyżej.</p>
      ) : (
        snapshots.map((snapshot) => (
          <section className="snapshot" key={snapshot.id}>
            <div className="snapshot-meta">
              <span className="badge">{snapshot.broker.toUpperCase()}</span>
              <span>wycena {snapshot.valuation_date}</span>
              <span className="muted small">
                zaimportowano {new Date(snapshot.imported_at).toLocaleString('pl-PL')}
              </span>
            </div>
            {snapshot.positions.length === 0 ? (
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
                    <th>Klasa</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.positions.map((position) => (
                    <tr key={position.id}>
                      <td>{position.instrument_name}</td>
                      <td className="muted">{position.isin ?? position.symbol ?? '—'}</td>
                      <td>{position.quantity}</td>
                      <td>
                        {position.avg_cost ?? '—'} {position.cost_currency ?? ''}
                      </td>
                      <td>
                        {position.market_value ?? '—'} {position.market_currency ?? ''}
                      </td>
                      <td className="muted">{position.asset_class}</td>
                      <td className="muted">{position.resolution_status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        ))
      )}
    </div>
  )
}

export default PortfolioDetail

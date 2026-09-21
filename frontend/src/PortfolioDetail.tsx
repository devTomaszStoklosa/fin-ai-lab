import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  ImportFailure,
  UNKNOWN_FORMAT_ERROR,
  deletePosition,
  fetchPositions,
  fetchSnapshots,
  importFile,
} from './api'
import type { Portfolio, Position, Snapshot } from './api'
import { trimTrailingZeros } from './format'
import ManualPosition from './ManualPosition'
import ProposeConfig from './ProposeConfig'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function returnClass(returnPct: string): string {
  return Number(returnPct) >= 0 ? 'return-gain' : 'return-loss'
}

function formatReturn(returnPct: string): string {
  return Number(returnPct) >= 0 ? `+${returnPct}%` : `${returnPct}%`
}

type Props = {
  portfolio: Portfolio
  onBack: () => void
}

function PortfolioDetail({ portfolio, onBack }: Props) {
  const [snapshots, setSnapshots] = useState<Snapshot[] | null>(null)
  const [manualPositions, setManualPositions] = useState<Position[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  // 'new' adds a position; a Position edits that one; null shows neither.
  const [manualFormTarget, setManualFormTarget] = useState<Position | 'new' | null>(null)
  // Not user-editable: avg_cost/market_value already come straight from the
  // broker file's own columns, so asking the user to also pick a date here
  // (S2's own addition, never part of the design) was redundant.
  const valuationDate = today()
  const [submitting, setSubmitting] = useState(false)
  const [importErrors, setImportErrors] = useState<string[] | null>(null)
  const [importWarnings, setImportWarnings] = useState<string[] | null>(null)
  const [showPropose, setShowPropose] = useState(false)

  function reloadSnapshots() {
    fetchSnapshots(portfolio.id)
      .then(setSnapshots)
      .catch((e: Error) => setLoadError(e.message))
  }

  function reloadPositions() {
    fetchPositions(portfolio.id)
      .then(setManualPositions)
      .catch((e: Error) => setLoadError(e.message))
  }

  useEffect(reloadSnapshots, [portfolio.id])
  useEffect(reloadPositions, [portfolio.id])

  // Backend returns snapshots newest-first; the detail page shows the
  // current state (the latest one), not a stack of every past import --
  // that history view belongs to portfolio-webapp-S7.
  const latestSnapshot = snapshots && snapshots.length > 0 ? snapshots[0] : null
  // "Current" positions (AC-4) = the latest import, if any, plus every
  // manually added one -- manual positions have no snapshot of their own in
  // this view (see repository.MANUAL_BROKER on the backend).
  const displayPositions = [...(latestSnapshot?.positions ?? []), ...(manualPositions ?? [])]

  function handleManualSaved() {
    setManualFormTarget(null)
    reloadPositions()
  }

  function handleDelete(position: Position) {
    if (!window.confirm(`Usunąć pozycję „${position.instrument_name}”?`)) return
    deletePosition(portfolio.id, position.id)
      .then(reloadPositions)
      .catch((e: Error) => setLoadError(e.message))
  }

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

      <div className="detail-actions">
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

        {manualFormTarget === null && (
          <button type="button" className="btn-ghost" onClick={() => setManualFormTarget('new')}>
            Dodaj ręcznie
          </button>
        )}
      </div>

      {showPropose && file && (
        <ProposeConfig
          portfolioId={portfolio.id}
          file={file}
          valuationDate={valuationDate}
          onApproved={handleProposeApproved}
          onCancel={() => setShowPropose(false)}
        />
      )}

      {manualFormTarget !== null && (
        <ManualPosition
          portfolioId={portfolio.id}
          position={manualFormTarget === 'new' ? undefined : manualFormTarget}
          onSaved={handleManualSaved}
          onCancel={() => setManualFormTarget(null)}
        />
      )}

      <h2>Pozycje</h2>
      {loadError && <p className="error">{loadError}</p>}
      {snapshots === null || manualPositions === null ? (
        <p>Wczytywanie…</p>
      ) : displayPositions.length === 0 ? (
        <p className="muted">Brak pozycji — wgraj plik albo dodaj pozycję ręcznie powyżej.</p>
      ) : (
        <section className="snapshot">
          {latestSnapshot && (
            <div className="snapshot-meta">
              <span className="badge">{latestSnapshot.broker.toUpperCase()}</span>
              <span>wycena {latestSnapshot.valuation_date}</span>
              <span className="muted small">
                zaimportowano {new Date(latestSnapshot.imported_at).toLocaleString('pl-PL')}
              </span>
            </div>
          )}
          <table className="positions">
            <thead>
              <tr>
                <th>Instrument</th>
                <th>ISIN / symbol</th>
                <th>Ilość</th>
                <th>Śr. koszt</th>
                <th>Wartość</th>
                <th>Zwrot</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {displayPositions.map((position) => (
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
                  <td className={position.return_pct === null ? '' : returnClass(position.return_pct)}>
                    {position.return_pct === null ? '—' : formatReturn(position.return_pct)}
                  </td>
                  <td className="muted">{position.resolution_status}</td>
                  <td className="positions-actions">
                    {position.broker === 'manual' && (
                      <>
                        <button type="button" onClick={() => setManualFormTarget(position)}>
                          Edytuj
                        </button>
                        <button type="button" onClick={() => handleDelete(position)}>
                          Usuń
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}

export default PortfolioDetail

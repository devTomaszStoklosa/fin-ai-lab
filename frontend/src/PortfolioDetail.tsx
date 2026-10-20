import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  ImportFailure,
  UNKNOWN_FORMAT_ERROR,
  deletePortfolio,
  deletePosition,
  fetchMetrics,
  fetchPortfolioValuation,
  fetchPositions,
  fetchReport,
  fetchSnapshots,
  generateReport,
  importBossaFile,
  importFile,
} from './api'
import type {
  LlmUsage,
  Metrics,
  Portfolio,
  Position,
  Report,
  Snapshot,
  Valuation,
  ValuedPosition,
} from './api'
import Aggregators from './Aggregators'
import AllocationBars from './AllocationBars'
import CommitteeAnalysis from './CommitteeAnalysis'
import DividendsCard from './DividendsCard'
import { localToday } from './format'
import ManualPosition from './ManualPosition'
import ManualValuations from './ManualValuations'
import PositionsTable from './PositionsTable'
import ProposeConfig from './ProposeConfig'
import SharesCard from './SharesCard'
import ValueChart from './ValueChart'

// What an upload added beyond the positions; null when the file had neither.
function importNoticeText(
  cashOperationsAdded: number | null | undefined,
  closedLotsAdded: number | null | undefined,
): string | null {
  const parts: string[] = []
  if (cashOperationsAdded != null) {
    parts.push(`operacje gotówkowe: ${cashOperationsAdded === 0 ? 'brak nowych' : cashOperationsAdded}`)
  }
  if (closedLotsAdded != null) {
    parts.push(`zamknięte pozycje: ${closedLotsAdded === 0 ? 'brak nowych' : closedLotsAdded}`)
  }
  return parts.length > 0 ? `Nowe w pliku — ${parts.join(', ')}.` : null
}

type Props = {
  portfolio: Portfolio
  onBack: () => void
  onDeleted: () => void
  llmUsage: LlmUsage[] | null
  onUsageChange: (usage: LlmUsage[] | null) => void
  onManageBreakdowns: (breakdownId: string | null) => void
}

const NO_HIDDEN = new Set<string>()

function PortfolioDetail({
  portfolio,
  onBack,
  onDeleted,
  llmUsage,
  onUsageChange,
  onManageBreakdowns,
}: Props) {
  const [snapshots, setSnapshots] = useState<Snapshot[] | null>(null)
  const [manualPositions, setManualPositions] = useState<Position[] | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [valuation, setValuation] = useState<Valuation | null>(null)
  const [valuationRefreshing, setValuationRefreshing] = useState(false)
  // Tells the shares card that values changed (refresh, import, manual edit).
  const [sharesToken, setSharesToken] = useState(0)
  const [report, setReport] = useState<Report | null>(null)
  const [reportGenerating, setReportGenerating] = useState(false)
  const [reportError, setReportError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  // 'new' adds a position; a Position edits that one; null shows neither.
  const [manualFormTarget, setManualFormTarget] = useState<Position | 'new' | null>(null)
  // The manual position whose valuations are open (#288), by id: the stored
  // Position behind it is reloaded after every valuation.
  const [valuationsTargetId, setValuationsTargetId] = useState<string | null>(null)
  // Not user-editable: avg_cost/market_value already come straight from the
  // broker file's own columns, so asking the user to also pick a date here
  // (S2's own addition, never part of the design) was redundant.
  const valuationDate = localToday()
  const [submitting, setSubmitting] = useState(false)
  const [importErrors, setImportErrors] = useState<string[] | null>(null)
  const [importWarnings, setImportWarnings] = useState<string[] | null>(null)
  const [importNotice, setImportNotice] = useState<string | null>(null)
  const [showPropose, setShowPropose] = useState(false)
  const [showAggregators, setShowAggregators] = useState(false)
  const [showCommitteeAnalysis, setShowCommitteeAnalysis] = useState(false)
  const [deleting, setDeleting] = useState(false)

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

  function reloadMetrics() {
    fetchMetrics(portfolio.id)
      .then(setMetrics)
      .catch((e: Error) => setLoadError(e.message))
  }

  function reloadValuation() {
    fetchPortfolioValuation(portfolio.id)
      .then(setValuation)
      .catch((e: Error) => setLoadError(e.message))
  }

  // After data changed (import, manual position): the chart and the shares.
  function valuesChanged() {
    reloadValuation()
    setSharesToken((token) => token + 1)
  }

  // Bypasses today's quote cache on the backend (`refresh`), unlike a reload.
  function refreshValuation() {
    setValuationRefreshing(true)
    fetchPortfolioValuation(portfolio.id, true)
      .then(setValuation)
      .catch((e: Error) => setLoadError(e.message))
      .finally(() => {
        setValuationRefreshing(false)
        setSharesToken((token) => token + 1)
      })
  }

  function reloadReport() {
    fetchReport(portfolio.id)
      .then(setReport)
      .catch((e: Error) => setLoadError(e.message))
  }

  useEffect(reloadSnapshots, [portfolio.id])
  useEffect(reloadPositions, [portfolio.id])
  useEffect(reloadMetrics, [portfolio.id])
  useEffect(reloadReport, [portfolio.id])
  useEffect(reloadValuation, [portfolio.id])

  // Backend returns snapshots newest-first -- only the latest import's
  // date is shown now (next to the import form); positions and their value
  // come from the valuation endpoint (S10).
  const latestSnapshot = snapshots && snapshots.length > 0 ? snapshots[0] : null

  function handleManualSaved() {
    setManualFormTarget(null)
    reloadPositions()
    reloadMetrics()
    valuesChanged()
  }

  // The valued table knows a manual row by id; the edit form needs the
  // full stored Position behind it.
  function handleEdit(valued: ValuedPosition) {
    const position = manualPositions?.find((p) => p.id === valued.position_id)
    if (position) {
      setValuationsTargetId(null)
      setManualFormTarget(position)
    }
  }

  function handleValuations(valued: ValuedPosition) {
    setManualFormTarget(null)
    setValuationsTargetId(valued.position_id)
  }

  function handleValuationsChanged() {
    reloadPositions()
    reloadMetrics()
    valuesChanged()
  }

  const valuationsTarget = manualPositions?.find((p) => p.id === valuationsTargetId) ?? null

  function handleDelete(valued: ValuedPosition) {
    if (!window.confirm(`Usunąć pozycję „${valued.instrument_name}”?`)) return
    deletePosition(portfolio.id, valued.position_id)
      .then(() => {
        reloadPositions()
        reloadMetrics()
        valuesChanged()
      })
      .catch((e: Error) => setLoadError(e.message))
  }

  function handleDeletePortfolio() {
    const message =
      `Usunąć portfel „${portfolio.name}” razem z pozycjami, importami, transakcjami, ` +
      'agregatami i raportami? Tej operacji nie można cofnąć.'
    if (!window.confirm(message)) return
    setDeleting(true)
    deletePortfolio(portfolio.id)
      .then(onDeleted)
      .catch((e: Error) => {
        setDeleting(false)
        setLoadError(e.message)
      })
  }

  function handleGenerateReport(regenerate: boolean) {
    setReportGenerating(true)
    setReportError(null)
    generateReport(portfolio.id, regenerate)
      .then(setReport)
      .catch((e: Error) => setReportError(e.message))
      .finally(() => setReportGenerating(false))
  }

  function handleImport(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    setSubmitting(true)
    setImportErrors(null)
    setImportWarnings(null)
    setImportNotice(null)
    setShowPropose(false)
    const doImport =
      portfolio.broker === 'bossa'
        ? importBossaFile(portfolio.id, file, valuationDate)
        : importFile(portfolio.id, file, valuationDate)
    doImport
      .then(({ warnings, cash_operations_added, closed_lots_added }) => {
        setImportWarnings(warnings)
        setImportNotice(importNoticeText(cash_operations_added, closed_lots_added))
        setFile(null)
        reloadSnapshots()
        reloadMetrics()
        valuesChanged()
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
    reloadMetrics()
    valuesChanged()
  }

  if (showAggregators) {
    return <Aggregators portfolio={portfolio} onBack={() => setShowAggregators(false)} />
  }

  if (showCommitteeAnalysis) {
    return (
      <CommitteeAnalysis
        portfolioId={portfolio.id}
        onBack={() => setShowCommitteeAnalysis(false)}
        llmUsage={llmUsage}
        onUsageChange={onUsageChange}
      />
    )
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
        <div className="detail-header-actions">
          <button
            type="button"
            className="btn-ghost"
            onClick={() => setShowCommitteeAnalysis(true)}
          >
            Analiza AI
          </button>
          <button type="button" className="btn-ghost" onClick={() => setShowAggregators(true)}>
            Agregaty
          </button>
        </div>
      </header>

      {loadError && <p className="error">{loadError}</p>}

      {valuation === null ? (
        <section className="value-card">
          <p className="muted">Pobieram notowania i liczę historię wartości…</p>
        </section>
      ) : (
        <ValueChart
          valuation={valuation}
          title="Wartość portfela"
          multi={false}
          hidden={NO_HIDDEN}
          onToggle={() => {}}
          onRefresh={refreshValuation}
          refreshing={valuationRefreshing}
        />
      )}

      {valuation !== null && valuation.dates.length > 0 && (
        <SharesCard portfolioId={portfolio.id} reloadToken={sharesToken} onManage={onManageBreakdowns} />
      )}

      {valuation !== null && (
        <PositionsTable
          positions={valuation.positions}
          baseCurrency={valuation.base_currency}
          onEdit={handleEdit}
          onDelete={handleDelete}
          onValuations={handleValuations}
        />
      )}

      {/* Refetched with every valuation, so an import shows its dividends. */}
      {valuation !== null && (
        <DividendsCard portfolioId={portfolio.id} reloadToken={valuation.computed_at} />
      )}

      {metrics && metrics.total_value !== null && (
        <section className="metrics">
          <div className="metric-cards">
            <div className="metric-card">
              <div className="muted small">Liczba pozycji</div>
              <div className="mono metric-value">{metrics.position_count}</div>
            </div>
            <div className="metric-card">
              <div className="muted small">Koncentracja (HHI)</div>
              <div className="mono metric-value">{metrics.hhi}</div>
            </div>
            <div className="metric-card">
              <div className="muted small">Efektywna liczba pozycji</div>
              <div className="mono metric-value">{metrics.effective_positions}</div>
            </div>
            <div className="metric-card">
              <div className="muted small">Udział top-5</div>
              <div className="mono metric-value">{metrics.top5_share}%</div>
            </div>
          </div>

          <div className="allocation-grid">
            <AllocationBars
              title="Alokacja wg klasy aktywów"
              allocation={metrics.allocation_by_asset_class}
            />
            <AllocationBars title="Ekspozycja walutowa" allocation={metrics.allocation_by_currency} />
          </div>
        </section>
      )}

      {metrics && metrics.total_value !== null && (
        <section className="report">
          <div className="report-header">
            <h2>Raport AI</h2>
            <button
              type="button"
              className="btn-ghost"
              disabled={reportGenerating}
              onClick={() => handleGenerateReport(report !== null)}
            >
              {reportGenerating ? 'Generuję…' : report ? 'Odśwież' : 'Generuj raport'}
            </button>
          </div>

          {reportError && (
            <div className="banner banner-error">
              <p>{reportError}</p>
            </div>
          )}

          {report && (
            <>
              <div className="muted small">
                Wygenerowano {new Date(report.generated_at).toLocaleString('pl-PL')} · koszt{' '}
                {report.cost_usd} USD
              </div>
              <div className="report-content">{report.content_md}</div>
            </>
          )}

          {/* REQ-042: stays visible regardless of the report's own content. */}
          <div className="report-disclaimer muted small">
            To opis ekspozycji i ryzyka, nie rekomendacja inwestycyjna.
          </div>
        </section>
      )}

      <h2 className="section-title">Dane portfela</h2>
      <div className="detail-actions">
        <form className="import-form" onSubmit={handleImport}>
          <h2>Importuj plik</h2>
          {latestSnapshot && (
            <p className="muted small">
              Ostatni import: wycena {latestSnapshot.valuation_date}, wgrany{' '}
              {new Date(latestSnapshot.imported_at).toLocaleString('pl-PL')}
            </p>
          )}
          <label>
            Plik
            <input
              type="file"
              accept={portfolio.broker === 'bossa' ? '.csv' : '.xlsx'}
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
          {importNotice !== null && <p className="muted small">{importNotice}</p>}
          {importWarnings && importWarnings.length > 0 && (
            <div className="banner banner-warning">
              {importWarnings.map((warning) => (
                <p key={warning}>{warning}</p>
              ))}
            </div>
          )}
        </form>

        {manualFormTarget === null && (
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              setValuationsTargetId(null)
              setManualFormTarget('new')
            }}
          >
            Dodaj ręcznie
          </button>
        )}

        <button
          type="button"
          className="btn-ghost btn-danger"
          disabled={deleting}
          onClick={handleDeletePortfolio}
        >
          {deleting ? 'Usuwam…' : 'Usuń portfel'}
        </button>
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

      {valuationsTarget !== null && (
        <ManualValuations
          key={valuationsTarget.id}
          portfolioId={portfolio.id}
          position={valuationsTarget}
          onChanged={handleValuationsChanged}
          onClose={() => setValuationsTargetId(null)}
        />
      )}

    </div>
  )
}

export default PortfolioDetail

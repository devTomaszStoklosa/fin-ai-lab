import { useEffect, useState } from 'react'
import { deleteAggregator, fetchAggregators, fetchPositions, fetchSnapshots } from './api'
import type { Aggregator, Portfolio, Position } from './api'
import AggregatorForm from './AggregatorForm'
import { instrumentKey, pluralizePl, trimTrailingZeros } from './format'

const ASSET_CLASS_LABELS: Record<string, string> = {
  equity: 'Akcje',
  etf: 'ETF',
  bond: 'Obligacje',
  fund: 'Fundusz',
  cash: 'Gotówka',
  crypto: 'Krypto',
  derivative: 'Derywat',
  other: 'Inne',
}

type Props = {
  portfolio: Portfolio
  onBack: () => void
}

function memberCountLabel(aggregator: Aggregator): string {
  const aggCount = aggregator.member_aggregator_ids.length
  const instCount = aggregator.member_instrument_keys.length
  if (aggCount > 0 && instCount === 0) {
    return `${aggCount} ${pluralizePl(aggCount, 'agregat', 'agregaty', 'agregatów')}`
  }
  if (instCount > 0 && aggCount === 0) {
    return `${instCount} ${pluralizePl(instCount, 'instrument', 'instrumenty', 'instrumentów')}`
  }
  const total = aggCount + instCount
  if (total === 0) return 'pusty'
  return `${total} ${pluralizePl(total, 'pozycja', 'pozycje', 'pozycji')}`
}

function Aggregators({ portfolio, onBack }: Props) {
  const [aggregators, setAggregators] = useState<Aggregator[] | null>(null)
  const [positions, setPositions] = useState<Position[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [formTarget, setFormTarget] = useState<Aggregator | 'new' | null>(null)

  function reloadAggregators() {
    fetchAggregators(portfolio.id)
      .then(setAggregators)
      .catch((e: Error) => setLoadError(e.message))
  }

  function reloadPositions() {
    Promise.all([fetchSnapshots(portfolio.id), fetchPositions(portfolio.id)])
      .then(([snapshots, manual]) => {
        const latest = snapshots.length > 0 ? snapshots[0] : null
        setPositions([...(latest?.positions ?? []), ...manual])
      })
      .catch((e: Error) => setLoadError(e.message))
  }

  useEffect(reloadAggregators, [portfolio.id])
  useEffect(reloadPositions, [portfolio.id])

  function handleSaved() {
    setFormTarget(null)
    reloadAggregators()
  }

  function handleDelete(aggregator: Aggregator) {
    if (!window.confirm(`Usunąć agregat „${aggregator.name}”?`)) return
    deleteAggregator(portfolio.id, aggregator.id)
      .then(reloadAggregators)
      .catch((e: Error) => setLoadError(e.message))
  }

  const byId = new Map((aggregators ?? []).map((a) => [a.id, a]))
  const positionByKey = new Map((positions ?? []).map((p) => [instrumentKey(p), p]))
  const referenced = new Set((aggregators ?? []).flatMap((a) => a.member_aggregator_ids))
  const topLevel = (aggregators ?? []).filter((a) => !referenced.has(a.id))

  return (
    <div className="content">
      <button type="button" className="back-link" onClick={onBack}>
        ← {portfolio.name}
      </button>

      <div className="detail-header agg-header">
        <div>
          <h1>Agregaty</h1>
          <p className="muted small agg-intro">
            Grupuj dowolne instrumenty i inne agregaty, żeby zobaczyć łączną ekspozycję.
          </p>
        </div>
        {formTarget === null && (
          <button type="button" onClick={() => setFormTarget('new')}>
            + Nowy agregat
          </button>
        )}
      </div>

      {loadError && <p className="error">{loadError}</p>}

      {formTarget !== null && (
        <AggregatorForm
          portfolioId={portfolio.id}
          aggregator={formTarget === 'new' ? undefined : formTarget}
          allAggregators={aggregators ?? []}
          positions={positions ?? []}
          onSaved={handleSaved}
          onCancel={() => setFormTarget(null)}
        />
      )}

      {aggregators === null || positions === null ? (
        <p>Wczytywanie…</p>
      ) : topLevel.length === 0 ? (
        <p className="muted">Brak agregatów — dodaj pierwszy powyżej.</p>
      ) : (
        <div className="agg-list">
          {topLevel.map((aggregator) => (
            <div className="agg-card" key={aggregator.id}>
              <AggregatorNode
                aggregator={aggregator}
                byId={byId}
                positionByKey={positionByKey}
                seen={new Set()}
                onEdit={setFormTarget}
                onDelete={handleDelete}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

type NodeProps = {
  aggregator: Aggregator
  byId: Map<string, Aggregator>
  positionByKey: Map<string, Position>
  seen: Set<string>
  onEdit: (aggregator: Aggregator) => void
  onDelete: (aggregator: Aggregator) => void
}

function AggregatorNode({ aggregator, byId, positionByKey, seen, onEdit, onDelete }: NodeProps) {
  const hasChildren =
    aggregator.member_aggregator_ids.length > 0 || aggregator.member_instrument_keys.length > 0
  // Defensive only -- validate_no_cycle (REQ-062) should already keep stored
  // data cycle-free; this just stops the recursion from looping forever if
  // it somehow isn't.
  const nextSeen = new Set(seen).add(aggregator.id)

  return (
    <>
      <div className="agg-row">
        <span className="badge">Agregat</span>
        <span className="agg-name">{aggregator.name}</span>
        <span className="muted small agg-count">{memberCountLabel(aggregator)}</span>
        <span className="mono agg-value">
          {trimTrailingZeros(aggregator.value)} {aggregator.base_currency}
        </span>
        <span className="agg-row-actions">
          <button type="button" onClick={() => onEdit(aggregator)}>
            Edytuj
          </button>
          <button type="button" onClick={() => onDelete(aggregator)}>
            Usuń
          </button>
        </span>
      </div>

      {hasChildren && (
        <div className="agg-nest">
          {aggregator.member_aggregator_ids.map((childId) => {
            const child = byId.get(childId)
            if (!child || seen.has(childId)) return null
            return (
              <AggregatorNode
                key={childId}
                aggregator={child}
                byId={byId}
                positionByKey={positionByKey}
                seen={nextSeen}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            )
          })}
          {aggregator.member_instrument_keys.map((key) => {
            const position = positionByKey.get(key)
            return (
              <div className="agg-row agg-leaf" key={key}>
                <span className="badge muted-badge">
                  {position ? ASSET_CLASS_LABELS[position.asset_class] ?? position.asset_class : '?'}
                </span>
                <span className="agg-name">{position ? position.instrument_name : key}</span>
                <span className="muted small mono agg-count">
                  {position ? `${trimTrailingZeros(position.quantity)} szt` : ''}
                </span>
                <span className="mono agg-value">
                  {position?.market_value ? trimTrailingZeros(position.market_value) : '—'}{' '}
                  {position?.market_currency ?? ''}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}

export default Aggregators

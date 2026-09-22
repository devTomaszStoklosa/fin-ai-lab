import { useState } from 'react'
import type { FormEvent } from 'react'
import { createAggregator, updateAggregator } from './api'
import type { Aggregator, AggregatorCreate, Position } from './api'
import { instrumentKey } from './format'

type Props = {
  portfolioId: string
  // Present when editing an existing aggregator; absent when adding a new one.
  aggregator?: Aggregator
  allAggregators: Aggregator[]
  positions: Position[]
  onSaved: (aggregator: Aggregator) => void
  onCancel: () => void
}

function AggregatorForm({
  portfolioId,
  aggregator,
  allAggregators,
  positions,
  onSaved,
  onCancel,
}: Props) {
  const [name, setName] = useState(aggregator?.name ?? '')
  const [instrumentKeys, setInstrumentKeys] = useState<Set<string>>(
    new Set(aggregator?.member_instrument_keys ?? []),
  )
  const [aggregatorIds, setAggregatorIds] = useState<Set<string>>(
    new Set(aggregator?.member_aggregator_ids ?? []),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // An aggregate can't be a member of itself -- not offered as a choice,
  // the server would reject it anyway (REQ-062) but there's no reason to
  // show a guaranteed-invalid option.
  const availableAggregators = allAggregators.filter((a) => a.id !== aggregator?.id)

  function toggle(set: Set<string>, setSet: (s: Set<string>) => void, key: string) {
    const next = new Set(set)
    if (next.has(key)) {
      next.delete(key)
    } else {
      next.add(key)
    }
    setSet(next)
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)

    const payload: AggregatorCreate = {
      name,
      member_instrument_keys: [...instrumentKeys],
      member_aggregator_ids: [...aggregatorIds],
    }

    const request = aggregator
      ? updateAggregator(portfolioId, aggregator.id, payload)
      : createAggregator(portfolioId, payload)

    request
      .then(onSaved)
      .catch((e: Error) => setError(e.message))
      .finally(() => setSaving(false))
  }

  return (
    <form className="manual-form" onSubmit={handleSubmit}>
      <h3>{aggregator ? 'Edytuj agregat' : 'Nowy agregat'}</h3>
      <label>
        Nazwa
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>

      <label>
        Instrumenty
        <div className="agg-checklist">
          {positions.length === 0 && <span className="muted small">Brak pozycji w portfelu.</span>}
          {positions.map((position) => {
            const key = instrumentKey(position)
            return (
              <label key={key} className="agg-checkbox-row">
                <input
                  type="checkbox"
                  checked={instrumentKeys.has(key)}
                  onChange={() => toggle(instrumentKeys, setInstrumentKeys, key)}
                />
                {position.instrument_name}
              </label>
            )
          })}
        </div>
      </label>

      {availableAggregators.length > 0 && (
        <label>
          Inne agregaty
          <div className="agg-checklist">
            {availableAggregators.map((other) => (
              <label key={other.id} className="agg-checkbox-row">
                <input
                  type="checkbox"
                  checked={aggregatorIds.has(other.id)}
                  onChange={() => toggle(aggregatorIds, setAggregatorIds, other.id)}
                />
                {other.name}
              </label>
            ))}
          </div>
        </label>
      )}

      <div className="propose-actions">
        <button type="submit" disabled={saving || !name.trim()}>
          {saving ? 'Zapisuję…' : 'Zapisz'}
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel}>
          Anuluj
        </button>
      </div>
      {error && (
        <div className="banner banner-error">
          <p>{error}</p>
        </div>
      )}
    </form>
  )
}

export default AggregatorForm

import { useState } from 'react'
import type { FormEvent } from 'react'
import { createPosition, updatePosition } from './api'
import type { Position, PositionCreate } from './api'

const ASSET_CLASSES: { value: string; label: string }[] = [
  { value: 'equity', label: 'Akcje' },
  { value: 'etf', label: 'ETF' },
  { value: 'bond', label: 'Obligacje' },
  { value: 'fund', label: 'Fundusz' },
  { value: 'cash', label: 'Gotówka' },
  { value: 'crypto', label: 'Krypto' },
  { value: 'derivative', label: 'Derywat' },
  { value: 'other', label: 'Inne' },
]

type Props = {
  portfolioId: string
  // Present when editing an existing manual position; absent when adding a
  // new one -- the only real difference is that editing also exposes
  // market_value (create always values the position at cost).
  position?: Position
  onSaved: (position: Position) => void
  onCancel: () => void
}

function ManualPosition({ portfolioId, position, onSaved, onCancel }: Props) {
  const [instrumentName, setInstrumentName] = useState(position?.instrument_name ?? '')
  const [isin, setIsin] = useState(position?.isin ?? '')
  const [symbol, setSymbol] = useState(position?.symbol ?? '')
  const [assetClass, setAssetClass] = useState(position?.asset_class ?? 'equity')
  const [quantity, setQuantity] = useState(position?.quantity ?? '')
  const [avgCost, setAvgCost] = useState(position?.avg_cost ?? '')
  const [marketValue, setMarketValue] = useState(position?.market_value ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)

    const payload: PositionCreate = {
      instrument_name: instrumentName,
      isin: isin.trim() || null,
      symbol: symbol.trim() || null,
      asset_class: assetClass,
      quantity,
      avg_cost: avgCost,
    }

    const request = position
      ? updatePosition(portfolioId, position.id, { ...payload, market_value: marketValue })
      : createPosition(portfolioId, payload)

    request
      .then(onSaved)
      .catch((e: Error) => setError(e.message))
      .finally(() => setSaving(false))
  }

  return (
    <form className="manual-form" onSubmit={handleSubmit}>
      <h3>{position ? 'Edytuj pozycję' : 'Dodaj pozycję ręcznie'}</h3>
      <label>
        Instrument
        <input
          value={instrumentName}
          onChange={(e) => setInstrumentName(e.target.value)}
          required
        />
      </label>
      <label>
        ISIN (opcjonalnie)
        <input value={isin} onChange={(e) => setIsin(e.target.value)} />
      </label>
      <label>
        Symbol (opcjonalnie)
        <input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
      </label>
      <label>
        Klasa aktywów
        <select value={assetClass} onChange={(e) => setAssetClass(e.target.value)}>
          {ASSET_CLASSES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Ilość
        <input
          type="number"
          step="any"
          min="0"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
        />
      </label>
      <label>
        Śr. koszt (PLN)
        <input
          type="number"
          step="any"
          min="0"
          value={avgCost}
          onChange={(e) => setAvgCost(e.target.value)}
          required
        />
      </label>
      {position && (
        <label>
          Wartość (PLN)
          <input
            type="number"
            step="any"
            min="0"
            value={marketValue}
            onChange={(e) => setMarketValue(e.target.value)}
            required
          />
        </label>
      )}
      <div className="propose-actions">
        <button type="submit" disabled={saving}>
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

export default ManualPosition

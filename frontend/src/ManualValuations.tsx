import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { deleteManualValuation, fetchManualValuations, saveManualValuation } from './api'
import type { ManualValuation, Position } from './api'
import {
  formatCents,
  formatDate,
  formatMoney,
  formatPrice,
  localToday,
  multiplyToCents,
} from './format'

type Props = {
  portfolioId: string
  // The stored manual position: its quantity scales a valuation, its
  // valuation_date is the purchase date no valuation may precede (#288).
  position: Position
  // A valuation was added or removed: the position's value changed.
  onChanged: () => void
  onClose: () => void
}

function ManualValuations({ portfolioId, position, onChanged, onClose }: Props) {
  const [valuations, setValuations] = useState<ManualValuation[] | null>(null)
  const [valuedOn, setValuedOn] = useState(localToday())
  const [unitValue, setUnitValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function reload() {
    fetchManualValuations(portfolioId, position.id)
      .then(setValuations)
      .catch((e: Error) => setError(e.message))
  }

  useEffect(reload, [portfolioId, position.id])

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    saveManualValuation(portfolioId, position.id, valuedOn, unitValue)
      .then(() => {
        setUnitValue('')
        reload()
        onChanged()
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setSaving(false))
  }

  function handleDelete(valuation: ManualValuation) {
    if (!window.confirm(`Usunąć wycenę z ${formatDate(valuation.valued_on)}?`)) return
    setError(null)
    deleteManualValuation(portfolioId, position.id, valuation.valued_on)
      .then(() => {
        reload()
        onChanged()
      })
      .catch((e: Error) => setError(e.message))
  }

  const purchaseCents =
    position.avg_cost === null ? null : multiplyToCents(position.quantity, position.avg_cost)
  const previewCents = multiplyToCents(position.quantity, unitValue)

  return (
    <form className="manual-form valuations-form" onSubmit={handleSubmit}>
      <h3>Wyceny — {position.instrument_name}</h3>
      <p className="muted small">
        Wartość od dnia wyceny do następnej. Przed pierwszą wyceną pozycja jest warta tyle, ile
        kosztowała.
      </p>
      {valuations === null ? (
        <p className="muted small">Wczytuję…</p>
      ) : (
        <table className="positions valuations-table">
          <thead>
            <tr>
              <th>Data</th>
              <th className="num">Cena za sztukę</th>
              <th className="num">Wartość</th>
              <th aria-label="Akcje"></th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                {formatDate(position.valuation_date)}
                <div className="muted small">zakup</div>
              </td>
              <td className="num mono">
                {position.avg_cost === null ? '—' : `${formatPrice(position.avg_cost)} PLN`}
              </td>
              <td className="num mono">
                {purchaseCents === null ? '—' : `${formatCents(purchaseCents)} PLN`}
              </td>
              <td></td>
            </tr>
            {valuations.map((valuation) => (
              <tr key={valuation.valued_on}>
                <td>{formatDate(valuation.valued_on)}</td>
                <td className="num mono">{formatPrice(valuation.unit_value)} PLN</td>
                <td className="num mono">{formatMoney(valuation.value)} PLN</td>
                <td className="positions-actions">
                  <button type="button" onClick={() => handleDelete(valuation)}>
                    Usuń
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <label>
        Data wyceny
        <input
          type="date"
          min={position.valuation_date}
          max={localToday()}
          value={valuedOn}
          onChange={(e) => setValuedOn(e.target.value)}
          required
        />
      </label>
      <label>
        Cena za sztukę (PLN)
        <input
          type="number"
          step="any"
          min="0"
          value={unitValue}
          onChange={(e) => setUnitValue(e.target.value)}
          required
        />
      </label>
      <p className="muted small">
        {previewCents !== null && `Wartość pozycji: ${formatCents(previewCents)} PLN. `}
        Wycena z dnia, który już ma wycenę, zastępuje poprzednią.
      </p>
      <div className="propose-actions">
        <button type="submit" disabled={saving}>
          {saving ? 'Zapisuję…' : 'Zapisz wycenę'}
        </button>
        <button type="button" className="btn-ghost" onClick={onClose}>
          Zamknij
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

export default ManualValuations

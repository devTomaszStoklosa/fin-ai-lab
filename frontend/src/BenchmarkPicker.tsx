import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { fetchBenchmarks } from './api'
import type { BenchmarkOption } from './api'

const CUSTOM = '__custom__'

type Props = {
  ticker: string
  onChange: (ticker: string) => void
}

// What the comparison mode sets the portfolio against (#273): a built-in
// benchmark, or any Yahoo ticker typed in (the backend checks it exists).
function BenchmarkPicker({ ticker, onChange }: Props) {
  const [options, setOptions] = useState<BenchmarkOption[] | null>(null)
  const [customOpen, setCustomOpen] = useState(false)
  const [draft, setDraft] = useState('')

  useEffect(() => {
    // Without the list the picker still takes a typed ticker.
    fetchBenchmarks()
      .then(setOptions)
      .catch(() => setOptions([]))
  }, [])

  if (options === null) return null
  const known = options.some((option) => option.ticker === ticker)
  const custom = customOpen || !known

  function handleSelect(value: string) {
    if (value === CUSTOM) {
      setCustomOpen(true)
      setDraft(known ? '' : ticker)
      return
    }
    setCustomOpen(false)
    onChange(value)
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const next = draft.trim().toUpperCase()
    if (!next) return
    setCustomOpen(false)
    onChange(next)
  }

  return (
    <div className="benchmark-picker">
      <label className="benchmark-select">
        <span className="muted small">Porównaj z</span>
        <select value={custom ? CUSTOM : ticker} onChange={(e) => handleSelect(e.target.value)}>
          {options.map((option) => (
            <option key={option.id} value={option.ticker}>
              {option.label}
            </option>
          ))}
          <option value={CUSTOM}>{known ? 'Własny ticker…' : `Własny: ${ticker}`}</option>
        </select>
      </label>
      {customOpen && (
        <form className="benchmark-custom" onSubmit={handleSubmit}>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="np. CDR.WA, AAPL"
            aria-label="Ticker z Yahoo Finance"
            maxLength={20}
            autoFocus
          />
          <button type="submit" className="btn-small">
            Porównaj
          </button>
        </form>
      )}
    </div>
  )
}

export default BenchmarkPicker

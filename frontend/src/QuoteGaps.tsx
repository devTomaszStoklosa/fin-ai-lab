import { useState } from 'react'
import { QUOTE_CURRENCIES } from './api'
import type { Instrument } from './api'
import { brokerLabel } from './format'

type Props = {
  instruments: Instrument[]
  busy: boolean
  onSave: (key: string, yahooTicker: string | null, quoteCurrency: string | null) => void
}

type Draft = { ticker: string; currency: string }

// What the valuation is missing for an instrument, in the owner's words.
function missing(instrument: Instrument): string[] {
  const gaps = []
  if (!instrument.has_quotes) gaps.push('brak dziennych notowań — wartość stoi w miejscu')
  if (instrument.quote_currency === null) gaps.push('nieznana waluta notowania — kurs waluty nie zmienia wartości')
  return gaps
}

function hasOwnerData(instrument: Instrument): boolean {
  return instrument.owner_yahoo_ticker !== null || instrument.owner_quote_currency !== null
}

// #285: the owner's Yahoo symbol and listing currency for an instrument the
// import could not price. Saved entries win over what the import found and
// count right away, without a re-import.
function QuoteGaps({ instruments, busy, onSave }: Props) {
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const rows = instruments.filter(
    (i) => !i.is_manual && (missing(i).length > 0 || hasOwnerData(i)),
  )

  function draftFor(instrument: Instrument): Draft {
    return (
      drafts[instrument.key] ?? {
        ticker: instrument.owner_yahoo_ticker ?? '',
        currency: instrument.owner_quote_currency ?? '',
      }
    )
  }

  function edit(instrument: Instrument, change: Partial<Draft>) {
    setDrafts((current) => ({ ...current, [instrument.key]: { ...draftFor(instrument), ...change } }))
  }

  return (
    <section className={`value-card${busy ? ' is-refreshing' : ''}`}>
      <div className="section-head">
        <h2>Notowania do uzupełnienia</h2>
        <span className="muted small">symbol Yahoo i waluta notowania</span>
      </div>
      <p className="muted small">
        Jeśli wycena nie znalazła notowań instrumentu albo waluty, w której jest notowany, wpisz jego
        symbol z finance.yahoo.com (np. SEDG, VUAA.L) i walutę. Bez waluty wezmę ją z Yahoo. Twój wpis
        liczy się od razu i wygrywa z tym, co ustalił import.
      </p>
      {rows.length === 0 ? (
        <div className="banner banner-success">
          <p>Każdy instrument ma notowania i znaną walutę.</p>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="positions manual-links">
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Czego brakuje</th>
                <th>Symbol Yahoo · waluta</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((instrument) => {
                const draft = draftFor(instrument)
                const gaps = missing(instrument)
                const ticker = draft.ticker.trim()
                return (
                  <tr key={instrument.key}>
                    <td>
                      <div className="strong">{instrument.name}</div>
                      <div className="mono muted small">
                        {brokerLabel(instrument.broker)} · {instrument.isin ?? instrument.symbol ?? instrument.key}
                      </div>
                    </td>
                    <td className="muted small">
                      {gaps.length > 0 ? gaps.join('; ') : 'uzupełnione przez Ciebie'}
                    </td>
                    <td>
                      <div className="manual-link-controls quote-gap-controls">
                        <input
                          type="text"
                          aria-label={`Symbol Yahoo instrumentu ${instrument.name}`}
                          placeholder={instrument.yahoo_ticker ?? 'symbol Yahoo'}
                          value={draft.ticker}
                          maxLength={20}
                          disabled={busy}
                          onChange={(e) => edit(instrument, { ticker: e.target.value })}
                        />
                        <select
                          aria-label={`Waluta notowania instrumentu ${instrument.name}`}
                          value={draft.currency}
                          disabled={busy}
                          onChange={(e) => edit(instrument, { currency: e.target.value })}
                        >
                          <option value="">{ticker ? '— z Yahoo —' : '— waluta —'}</option>
                          {QUOTE_CURRENCIES.map((code) => (
                            <option key={code} value={code}>
                              {code === 'GBp' ? 'GBp (pensy)' : code}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          className="btn-small"
                          aria-label={`Zapisz notowania ${instrument.name}`}
                          disabled={busy || (!ticker && !draft.currency)}
                          onClick={() => onSave(instrument.key, ticker || null, draft.currency || null)}
                        >
                          Zapisz
                        </button>
                        {hasOwnerData(instrument) && (
                          <button
                            type="button"
                            className="btn-small btn-danger"
                            aria-label={`Usuń moje notowania ${instrument.name}`}
                            disabled={busy}
                            onClick={() => onSave(instrument.key, null, null)}
                          >
                            Usuń
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export default QuoteGaps

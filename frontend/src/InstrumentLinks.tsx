import { useEffect, useState } from 'react'
import QuoteGaps from './QuoteGaps'
import { decideInstrumentLink, detachInstrument, fetchInstruments, saveInstrumentOwnerData } from './api'
import type { Instrument, Instruments } from './api'
import { brokerLabel, formatDecimal, formatPrice, pluralizePl } from './format'

type Props = {
  onBack: () => void
}

function identifiers(instrument: Instrument): string {
  const parts = [instrument.symbol, instrument.isin]
  if (instrument.ticker) {
    parts.push(`${instrument.ticker}${instrument.exchange_code ? ` @ ${instrument.exchange_code}` : ''}`)
  }
  const shown = [...new Set(parts.filter((p): p is string => Boolean(p)))]
  return shown.length ? shown.join(' · ') : instrument.is_manual ? 'pozycja ręczna' : '—'
}

function unitValue(instrument: Instrument, currency: string): string {
  return instrument.unit_value === null ? '—' : `${formatPrice(instrument.unit_value)} ${currency}`
}

function InstrumentCard({ instrument, currency }: { instrument: Instrument; currency: string }) {
  return (
    <div className="link-side">
      <div className="badges">
        <span className="badge">{brokerLabel(instrument.broker)}</span>
        {instrument.portfolio_names.map((name) => (
          <span key={name} className="badge muted-badge">
            {name}
          </span>
        ))}
      </div>
      <div className="strong">{instrument.name}</div>
      <div className="mono muted small">{identifiers(instrument)}</div>
      <dl className="link-facts">
        <div>
          <dt className="muted small">1 szt. dziś</dt>
          <dd className="mono">{unitValue(instrument, currency)}</dd>
        </div>
        <div>
          <dt className="muted small">Ilość</dt>
          <dd className="mono">{formatDecimal(instrument.quantity)}</dd>
        </div>
      </dl>
    </div>
  )
}

// The owner's say on which instruments are one asset (S12). Pairs with the
// same FIGI are joined automatically; likely pairs wait here for a yes or
// no; anything else can be pointed at by hand.
function InstrumentLinks({ onBack }: Props) {
  const [data, setData] = useState<Instruments | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Per lone instrument: the asset picked in its "to ten sam co…" select.
  const [picked, setPicked] = useState<Record<string, string>>({})
  // Bumped on every answer from the server, so QuoteGaps drops what was typed.
  const [version, setVersion] = useState(0)

  useEffect(() => {
    fetchInstruments()
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [])

  function apply(change: Promise<Instruments>) {
    setBusy(true)
    change
      .then((result) => {
        setData(result)
        setError(null)
        setPicked({})
        setVersion((v) => v + 1)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }

  if (data === null) {
    return (
      <div className="content content-wide">
        <button type="button" className="back-link" onClick={onBack}>
          ← wróć
        </button>
        {error ? <p className="error">{error}</p> : <p className="muted">Wczytuję instrumenty…</p>}
      </div>
    )
  }

  const currency = data.base_currency
  const byKey = new Map(data.instruments.map((i) => [i.key, i]))
  const assets = new Map<string, Instrument[]>()
  for (const instrument of data.instruments) {
    assets.set(instrument.asset_key, [...(assets.get(instrument.asset_key) ?? []), instrument])
  }
  const joined = [...assets.entries()].filter(([, members]) => members.length > 1)
  const alone = data.instruments.filter((i) => (assets.get(i.asset_key) ?? []).length === 1)

  // The select's choices for one lone instrument: every other asset, those
  // held at another broker first (the likely match), then by name.
  function choicesFor(instrument: Instrument) {
    return [...assets.entries()]
      .filter(([assetKey]) => assetKey !== instrument.asset_key)
      .map(([assetKey, members]) => {
        const brokers = [...new Set(members.map((m) => brokerLabel(m.broker)))]
        const first = members[0]
        const code = first.symbol ?? first.isin ?? first.ticker
        const label = [
          first.asset_name,
          brokers.join(' + '),
          code,
          first.unit_value === null ? null : `${formatPrice(first.unit_value)} ${currency}`,
        ]
          .filter(Boolean)
          .join(' · ')
        const otherBroker = members.some((m) => m.broker !== instrument.broker)
        return { assetKey, label, otherBroker, name: first.asset_name.toLowerCase() }
      })
      .sort((a, b) => Number(b.otherBroker) - Number(a.otherBroker) || a.name.localeCompare(b.name))
  }

  return (
    <div className="content content-wide">
      <button type="button" className="back-link" onClick={onBack}>
        ← wróć
      </button>
      <header className="overview-header">
        <h1>Łączenie instrumentów</h1>
        <p className="muted">
          Ta sama spółka albo fundusz kupiony u różnych brokerów to jedno aktywo — w tabeli aktywów, w
          udziałach i w podziałach. Pary z tym samym identyfikatorem FIGI łączę sam; resztę potwierdzasz
          albo wskazujesz Ty.
        </p>
      </header>

      {error && (
        <div className="banner banner-error">
          <p>{error}</p>
        </div>
      )}

      <section className={`value-card${busy ? ' is-refreshing' : ''}`}>
        <div className="section-head">
          <h2>Do potwierdzenia</h2>
          <span className="muted small">
            {data.suggestions.length} {pluralizePl(data.suggestions.length, 'para', 'pary', 'par')}
          </span>
        </div>
        {data.suggestions.length === 0 ? (
          <div className="banner banner-success">
            <p>Nie ma par do potwierdzenia.</p>
          </div>
        ) : (
          data.suggestions.map((suggestion) => {
            const a = byKey.get(suggestion.key_a)
            const b = byKey.get(suggestion.key_b)
            if (!a || !b) return null
            return (
              <article key={`${a.key}|${b.key}`} className="link-pair">
                <div className="link-pair-sides">
                  <InstrumentCard instrument={a} currency={currency} />
                  <span className="link-pair-sign" aria-hidden="true">
                    =?
                  </span>
                  <InstrumentCard instrument={b} currency={currency} />
                </div>
                <div className="link-pair-foot">
                  <ul className="reason-list" aria-label="Dlaczego ta para">
                    {suggestion.reasons.map((reason) => (
                      <li key={reason} className="reason-chip">
                        {reason}
                      </li>
                    ))}
                  </ul>
                  <div className="link-pair-actions">
                    <button
                      type="button"
                      className="btn-small"
                      disabled={busy}
                      onClick={() => apply(decideInstrumentLink(a.key, b.key, false))}
                    >
                      To różne instrumenty
                    </button>
                    <button
                      type="button"
                      className="btn-primary"
                      disabled={busy}
                      onClick={() => apply(decideInstrumentLink(a.key, b.key, true))}
                    >
                      Połącz — to ten sam
                    </button>
                  </div>
                </div>
              </article>
            )
          })
        )}
      </section>

      <section className={`value-card${busy ? ' is-refreshing' : ''}`}>
        <div className="section-head">
          <h2>Połączone aktywa</h2>
          <span className="muted small">
            {joined.length} {pluralizePl(joined.length, 'aktywo', 'aktywa', 'aktywów')}
          </span>
        </div>
        {joined.length === 0 ? (
          <p className="muted">Jeszcze nic nie połączono.</p>
        ) : (
          joined.map(([assetKey, members]) => (
            <article key={assetKey} className="joined-asset">
              <div className="joined-asset-head">
                <span className="strong">{members[0].asset_name}</span>
                <span className="mono muted small">{assetKey}</span>
              </div>
              {members.map((member) => (
                <div key={member.key} className="joined-member">
                  <span className="badge">{brokerLabel(member.broker)}</span>
                  <span className="joined-member-name">
                    <span>{member.name}</span>
                    <span className="mono muted small">
                      {identifiers(member)} · {member.portfolio_names.join(', ')}
                    </span>
                  </span>
                  <span className="mono small">{unitValue(member, currency)}</span>
                  <span className="muted small">
                    {member.linked_by === 'figi'
                      ? 'ten sam FIGI'
                      : member.linked_by === 'owner'
                        ? 'połączone przez Ciebie'
                        : ''}
                  </span>
                  <button
                    type="button"
                    className="btn-small btn-danger"
                    disabled={busy}
                    onClick={() => apply(detachInstrument(member.key))}
                  >
                    Odłącz
                  </button>
                </div>
              ))}
            </article>
          ))
        )}
      </section>

      <section className={`value-card${busy ? ' is-refreshing' : ''}`}>
        <div className="section-head">
          <h2>Wskaż ręcznie</h2>
          <span className="muted small">instrumenty bez pary</span>
        </div>
        <p className="muted small">
          Jeśli ten sam instrument nie trafił do propozycji (np. inna nazwa u każdego brokera), wybierz jego
          odpowiednik z listy. Odłączony instrument wraca tutaj.
        </p>
        {alone.length === 0 ? (
          <p className="muted">Każdy instrument ma już swoją parę.</p>
        ) : (
          <div className="table-scroll">
            <table className="positions manual-links">
              <thead>
                <tr>
                  <th>Instrument</th>
                  <th>Broker · portfel</th>
                  <th className="num">1 szt. dziś</th>
                  <th>To ten sam instrument co…</th>
                </tr>
              </thead>
              <tbody>
                {alone.map((instrument) => {
                  const choice = picked[instrument.key] ?? ''
                  const target = choice ? assets.get(choice)?.[0] : undefined
                  return (
                    <tr key={instrument.key}>
                      <td>
                        <div className="strong">{instrument.name}</div>
                        <div className="mono muted small">{identifiers(instrument)}</div>
                      </td>
                      <td className="muted">
                        {brokerLabel(instrument.broker)} · {instrument.portfolio_names.join(', ')}
                      </td>
                      <td className="num mono">{unitValue(instrument, currency)}</td>
                      <td>
                        <div className="manual-link-controls">
                          <select
                            aria-label={`Odpowiednik instrumentu ${instrument.name}`}
                            value={choice}
                            disabled={busy}
                            onChange={(e) =>
                              setPicked((current) => ({ ...current, [instrument.key]: e.target.value }))
                            }
                          >
                            <option value="">— wybierz —</option>
                            {choicesFor(instrument).map((option) => (
                              <option key={option.assetKey} value={option.assetKey}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="btn-small"
                            aria-label={`Połącz ${instrument.name}`}
                            disabled={busy || !target}
                            onClick={() => target && apply(decideInstrumentLink(instrument.key, target.key, true))}
                          >
                            Połącz
                          </button>
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

      <QuoteGaps
        key={version}
        instruments={data.instruments}
        busy={busy}
        onSave={(key, ticker, currency) => apply(saveInstrumentOwnerData(key, ticker, currency))}
      />
    </div>
  )
}

export default InstrumentLinks

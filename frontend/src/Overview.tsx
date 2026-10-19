import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { createPortfolio, fetchAllValuation } from './api'
import type { Portfolio, Valuation } from './api'
import AssetsTable from './AssetsTable'
import DividendsCard from './DividendsCard'
import { formatCents, formatMoney, pluralizePl, toCents } from './format'
import SharesCard from './SharesCard'
import { seriesColor } from './seriesColors'
import ValueChart from './ValueChart'

type Props = {
  portfolios: Portfolio[] | null
  onSelect: (portfolioId: string) => void
  onCreated: () => void
  onManageBreakdowns: (breakdownId: string | null) => void
  onManageInstruments: () => void
}

// The start page (S10): every portfolio summed at today's quotes, the
// day-by-day value of that sum, and every asset across all of them (S12:
// one row per asset, however many accounts or brokers hold it).
function Overview({ portfolios, onSelect, onCreated, onManageBreakdowns, onManageInstruments }: Props) {
  const [valuation, setValuation] = useState<Valuation | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  // Tells the shares card that values changed (quotes refreshed).
  const [sharesToken, setSharesToken] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [broker, setBroker] = useState('xtb')
  const [accountType, setAccountType] = useState('regular')

  function load(refresh = false) {
    return fetchAllValuation(refresh)
      .then((result) => {
        setValuation(result)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }

  function reload() {
    load()
  }

  // An explicit "odśwież" bypasses today's quote cache (the backend's
  // `refresh`); a plain reload reuses it.
  function refresh() {
    setRefreshing(true)
    load(true).finally(() => {
      setRefreshing(false)
      setSharesToken((token) => token + 1)
    })
  }

  // Re-valued whenever the portfolio list changes (e.g. one just created).
  useEffect(reload, [portfolios])

  function toggle(portfolioId: string) {
    setHidden((current) => {
      const next = new Set(current)
      if (next.has(portfolioId)) next.delete(portfolioId)
      else next.add(portfolioId)
      return next
    })
  }

  function handleCreate(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    createPortfolio({ name: name.trim(), broker, account_type: accountType })
      .then(() => {
        setName('')
        setShowCreate(false)
        onCreated()
      })
      .catch((e: Error) => setError(e.message))
  }

  const series = valuation?.portfolios ?? []
  const totalCents = valuation ? toCents(valuation.total_value) : 0
  const portfolioNames = new Map(series.map((p) => [p.id, p.name]))
  const colorIndex = new Map(series.map((p, index) => [p.id, index]))

  return (
    <div className="content">
      <header className="overview-header">
        <div className="value-eyebrow">Widok zbiorczy</div>
        <h1>Wszystkie portfele</h1>
        <p className="muted">
          {portfolios === null
            ? 'Wczytywanie…'
            : `${portfolios.length} ${pluralizePl(portfolios.length, 'portfel', 'portfele', 'portfeli')} · bieżąca wycena według notowań pobranych przy wejściu`}
        </p>
      </header>

      {error && <p className="error">{error}</p>}

      {valuation !== null && valuation.link_suggestion_count > 0 && (
        <div className="banner banner-warning link-banner">
          <p>
            {valuation.link_suggestion_count}{' '}
            {pluralizePl(valuation.link_suggestion_count, 'para instrumentów', 'pary instrumentów', 'par instrumentów')}{' '}
            z różnych kont{' '}
            {pluralizePl(valuation.link_suggestion_count, 'wygląda', 'wyglądają', 'wygląda')} na to samo
            aktywo — do czasu połączenia liczą się osobno.
          </p>
          <button type="button" className="btn-small" onClick={onManageInstruments}>
            Sprawdź i połącz
          </button>
        </div>
      )}

      {valuation === null ? (
        <section className="value-card">
          <p className="muted">Pobieram notowania i liczę historię wartości…</p>
        </section>
      ) : (
        <ValueChart
          valuation={valuation}
          title="Suma wszystkich portfeli"
          multi={series.length > 1}
          hidden={hidden}
          onToggle={toggle}
          onRefresh={refresh}
          refreshing={refreshing}
        />
      )}

      {valuation !== null && valuation.dates.length > 0 && (
        <SharesCard reloadToken={sharesToken} onManage={onManageBreakdowns} />
      )}

      {portfolios !== null && portfolios.length > 0 && <DividendsCard reloadToken={portfolios} />}

      <div className="section-head">
        <h2>Twoje portfele</h2>
        <span className="muted small">udział w bieżącej sumie</span>
      </div>
      <div className="grid">
        {(portfolios ?? []).map((portfolio) => {
          const valued = series.find((p) => p.id === portfolio.id)
          const cents = valued ? toCents(valued.current_value) : null
          const share = cents !== null && totalCents > 0 ? cents / totalCents : 0
          return (
            <button
              type="button"
              className="card portfolio-card"
              key={portfolio.id}
              onClick={() => onSelect(portfolio.id)}
            >
              <div className="badges">
                {portfolio.broker && <span className="badge">{portfolio.broker.toUpperCase()}</span>}
                {portfolio.account_type && (
                  <span className="badge muted-badge">{portfolio.account_type}</span>
                )}
              </div>
              <div className="name">{portfolio.name}</div>
              <div className="card-value mono">
                {valued ? `${formatMoney(valued.current_value)} ${valuation?.base_currency}` : '—'}
              </div>
              <div className="share-track" aria-hidden="true">
                <div
                  className="share-fill"
                  style={{
                    width: `${(share * 100).toFixed(1)}%`,
                    background: seriesColor(colorIndex.get(portfolio.id) ?? 0),
                  }}
                />
              </div>
              <div className="card-meta muted small">
                <span>{(share * 100).toFixed(1).replace('.', ',')}% sumy</span>
                <span>
                  {valued
                    ? `${valued.position_count} ${pluralizePl(valued.position_count, 'pozycja', 'pozycje', 'pozycji')}`
                    : ''}
                </span>
              </div>
            </button>
          )
        })}
        <button
          type="button"
          className="card add-card"
          aria-expanded={showCreate}
          onClick={() => setShowCreate((open) => !open)}
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="M10 4v12M4 10h12" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
          </svg>
          Nowy portfel
        </button>
      </div>

      {showCreate && (
        <form className="create-form" onSubmit={handleCreate}>
          <h2>Nowy portfel</h2>
          <label>
            Nazwa
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="np. XTB — Rachunek zwykły"
            />
          </label>
          <label>
            Broker
            <select value={broker} onChange={(e) => setBroker(e.target.value)}>
              <option value="xtb">XTB</option>
              <option value="bossa">Bossa</option>
              <option value="other">inny</option>
            </select>
          </label>
          <label>
            Typ konta
            <select value={accountType} onChange={(e) => setAccountType(e.target.value)}>
              <option value="regular">zwykły</option>
              <option value="ike">IKE</option>
              <option value="ikze">IKZE</option>
              <option value="other">inny</option>
            </select>
          </label>
          <button type="submit">Dodaj portfel</button>
        </form>
      )}

      {valuation !== null && (
        <AssetsTable
          assets={valuation.assets}
          positions={valuation.positions}
          hidden={hidden}
          baseCurrency={valuation.base_currency}
          portfolioNames={portfolioNames}
          onManageInstruments={onManageInstruments}
        />
      )}

      {valuation !== null && hidden.size > 0 && (
        <p className="muted small">
          Ukryte portfele nie wliczają się do sumy, wykresu ani tabeli (widoczne:{' '}
          {formatCents(
            series.filter((p) => !hidden.has(p.id)).reduce((s, p) => s + toCents(p.current_value), 0),
          )}{' '}
          {valuation.base_currency}).
        </p>
      )}
    </div>
  )
}

export default Overview

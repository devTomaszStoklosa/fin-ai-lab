import { Fragment, useState } from 'react'
import type { Asset, ValuedPosition } from './api'
import {
  brokerLabel,
  formatCents,
  formatDecimal,
  formatMoney,
  formatPercent,
  formatPrice,
  pluralizePl,
  sumDecimals,
  toCents,
} from './format'

type Props = {
  assets: Asset[]
  positions: ValuedPosition[]
  // Portfolios switched off in the chart legend -- their positions drop out.
  hidden: Set<string>
  baseCurrency: string
  portfolioNames: Map<string, string>
  onManageInstruments: () => void
}

// What one row shows: the asset's own (backend-summed) figures when every
// position is visible, one position's figures when only one is; with some
// of several hidden only exact sums remain -- no average is recomputed here.
type Figures = Pick<
  Asset,
  | 'quantity'
  | 'avg_cost'
  | 'cost_currency'
  | 'current_price'
  | 'price_currency'
  | 'value'
  | 'return_pct'
>

function figuresFor(asset: Asset, visible: ValuedPosition[]): Figures {
  if (visible.length === asset.position_ids.length) return asset
  if (visible.length === 1) return visible[0]
  const values = visible.filter((p) => p.value !== null)
  return {
    quantity: sumDecimals(visible.map((p) => p.quantity)),
    avg_cost: null,
    cost_currency: null,
    current_price: null,
    price_currency: null,
    value: values.length ? formatCentsAsDecimal(values.reduce((s, p) => s + toCents(p.value!), 0)) : null,
    return_pct: null,
  }
}

function formatCentsAsDecimal(cents: number): string {
  const negative = cents < 0
  const absolute = Math.abs(cents)
  return `${negative ? '-' : ''}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, '0')}`
}

function price(value: string | null, currency: string | null): string {
  return value === null ? '—' : `${formatPrice(value)} ${currency ?? ''}`.trim()
}

function returnClass(returnPct: string | null): string {
  if (returnPct === null) return ''
  return returnPct.startsWith('-') ? 'return-loss' : 'return-gain'
}

// The all-portfolios list (S12): one row per asset -- the same instrument in
// several accounts, or joined across brokers, is one row; expanding it shows
// each portfolio's own position.
function AssetsTable({ assets, positions, hidden, baseCurrency, portfolioNames, onManageInstruments }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const byId = new Map(positions.map((p) => [p.position_id, p]))

  const rows = assets
    .map((asset) => {
      const members = asset.position_ids
        .map((id) => byId.get(id))
        .filter((p): p is ValuedPosition => p !== undefined)
      const visible = members.filter((p) => !hidden.has(p.portfolio_id))
      return { asset, visible, figures: figuresFor(asset, visible) }
    })
    .filter((row) => row.visible.length > 0)
  const totalCents = rows.reduce((sum, r) => sum + (r.figures.value === null ? 0 : toCents(r.figures.value)), 0)

  function toggle(key: string) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <section className="positions-card">
      <div className="positions-head">
        <h2>Aktywa</h2>
        <span className="positions-head-meta">
          <span className="muted small">
            {rows.length} {pluralizePl(rows.length, 'aktywo', 'aktywa', 'aktywów')}
          </span>
          <button type="button" className="nav-link" onClick={onManageInstruments}>
            Łączenie instrumentów
          </button>
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="muted">Brak pozycji — wgraj plik albo dodaj pozycję ręcznie.</p>
      ) : (
        <div className="table-scroll">
          <table className="positions valued-positions">
            <thead>
              <tr>
                <th>Aktywo</th>
                <th>Portfel</th>
                <th className="num">Ilość</th>
                <th className="num">Cena zakupu</th>
                <th className="num">Cena bieżąca</th>
                <th className="num">Wartość</th>
                <th className="num">Zwrot</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ asset, visible, figures }) => {
                const several = visible.length > 1
                const isOpen = several && expanded.has(asset.instrument_key)
                const brokers = [...new Set(visible.map((p) => brokerLabel(p.broker)))]
                return (
                  <Fragment key={asset.instrument_key}>
                    <tr className={isOpen ? 'asset-row is-open' : 'asset-row'}>
                      <td>
                        <div className="instrument-name">{asset.instrument_name}</div>
                        <div className="muted small">
                          {asset.symbol ?? asset.isin ?? (visible[0].is_manual ? 'ręczna' : '—')}
                          {brokers.length > 1 && ` · połączone: ${brokers.join(' + ')}`}
                        </div>
                      </td>
                      <td>
                        {several ? (
                          <button
                            type="button"
                            className="expand-toggle"
                            aria-expanded={isOpen}
                            onClick={() => toggle(asset.instrument_key)}
                          >
                            {visible.length} {pluralizePl(visible.length, 'portfel', 'portfele', 'portfeli')}
                            <span aria-hidden="true" className="chevron">
                              {isOpen ? '▴' : '▾'}
                            </span>
                          </button>
                        ) : (
                          <span className="muted">{portfolioNames.get(visible[0].portfolio_id) ?? ''}</span>
                        )}
                      </td>
                      <td className="num mono">{formatDecimal(figures.quantity)}</td>
                      <td className="num mono">{price(figures.avg_cost, figures.cost_currency)}</td>
                      <td className="num mono">{price(figures.current_price, figures.price_currency)}</td>
                      <td className="num mono strong">
                        {figures.value === null ? '—' : `${formatMoney(figures.value)} ${baseCurrency}`}
                      </td>
                      <td className={`num mono strong ${returnClass(figures.return_pct)}`}>
                        {figures.return_pct === null ? '—' : formatPercent(figures.return_pct)}
                      </td>
                    </tr>
                    {isOpen &&
                      visible.map((position) => (
                        <tr key={position.position_id} className="member-row">
                          <td>
                            <div className="member-name">
                              <span aria-hidden="true">↳ </span>
                              {position.instrument_name}
                            </div>
                            <div className="muted small">
                              {brokerLabel(position.broker)} · {position.symbol ?? position.isin ?? '—'}
                            </div>
                          </td>
                          <td className="muted">{portfolioNames.get(position.portfolio_id) ?? ''}</td>
                          <td className="num mono">{formatDecimal(position.quantity)}</td>
                          <td className="num mono">{price(position.avg_cost, position.cost_currency)}</td>
                          <td className="num mono">{price(position.current_price, position.price_currency)}</td>
                          <td className="num mono">
                            {position.value === null ? '—' : `${formatMoney(position.value)} ${baseCurrency}`}
                          </td>
                          <td className={`num mono ${returnClass(position.return_pct)}`}>
                            {position.return_pct === null ? '—' : formatPercent(position.return_pct)}
                          </td>
                        </tr>
                      ))}
                  </Fragment>
                )
              })}
            </tbody>
            <tfoot>
              <tr>
                <td>Razem</td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td className="num mono">
                  {formatCents(totalCents)} {baseCurrency}
                </td>
                <td></td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <p className="muted small table-note">
        Jedno aktywo w kilku portfelach — także u różnych brokerów, gdy są połączone — to jeden wiersz;
        rozwiń go, żeby zobaczyć pozycje. Cena zakupu i bieżąca to średnie ważone ilością, gdy wszystkie
        pozycje podają je w tej samej walucie. Zwrot to zmiana ceny względem ceny zakupu, bez prowizji i
        podatków.
      </p>
    </section>
  )
}

export default AssetsTable

import { useState } from 'react'
import type { DividendForecast, DividendHistory } from './api'
import DividendBars from './DividendBars'
import type { Bar } from './DividendBars'
import { formatDate, formatMoney, formatPrice, pluralizePl, toCents } from './format'

const MONTH_SHORT = new Intl.DateTimeFormat('pl-PL', { month: 'short', timeZone: 'UTC' })
const MONTH_LONG = new Intl.DateTimeFormat('pl-PL', { month: 'long', year: 'numeric', timeZone: 'UTC' })
// More rows than this fold behind "pokaż wszystkie" -- the largest first.
const INSTRUMENTS_SHOWN = 10

type View = 'years' | number

type Props = {
  history: DividendHistory
  // Once loaded, its total is the hatched bar after the last year.
  forecast: DividendForecast | null
}

// #265: dividends credited to the account(s), year by year and per
// instrument. Amounts come from the backend in PLN (NBP rate of each
// payment's day); this only formats and sums cents for display.
function DividendHistoryPanel({ history, forecast }: Props) {
  const [view, setView] = useState<View>('years')
  const [allInstruments, setAllInstruments] = useState(false)

  const currency = history.base_currency
  const currentYear = history.years[history.years.length - 1]?.year ?? new Date().getFullYear()
  const firstYear = history.years[0]?.year ?? currentYear
  const multiPortfolio = new Set(history.payments.map((p) => p.portfolio_id)).size > 1

  if (history.payments.length === 0) {
    return (
      <p className="muted small">
        Zaimportowane pliki nie zawierają wypłat dywidend. Dywidendy czyta import XTB (arkusz Cash
        Operations) i historia finansowa Bossy.
      </p>
    )
  }

  const selectedYear = view === 'years' ? null : (history.years.find((y) => y.year === view) ?? null)
  const estimateBar: Bar[] =
    selectedYear === null && forecast !== null
      ? [
          {
            id: 'estimate',
            label: String(forecast.year),
            title: `${forecast.year} — szacunek na konto`,
            cents: toCents(forecast.total_credited),
            estimate: true,
          },
        ]
      : []
  const bars: Bar[] =
    selectedYear === null
      ? [
          ...history.years.map((year) => ({
            id: String(year.year),
            label: String(year.year),
            title: year.year === currentYear ? `${year.year} (do dziś)` : String(year.year),
            cents: toCents(year.total),
          })),
          ...estimateBar,
        ]
      : selectedYear.months.map((total, month) => {
          const day = new Date(Date.UTC(selectedYear.year, month, 1))
          return {
            id: `${selectedYear.year}-${month}`,
            label: MONTH_SHORT.format(day).replace('.', ''),
            title: MONTH_LONG.format(day),
            cents: toCents(total),
          }
        })

  const instruments = allInstruments ? history.instruments : history.instruments.slice(0, INSTRUMENTS_SHOWN)

  return (
    <>
      <div className="metric-cards">
        <div className="metric-card">
          <div className="muted small">W {currentYear} (do dziś)</div>
          <div className="mono metric-value">
            {formatMoney(history.current_year)} {currency}
          </div>
        </div>
        <div className="metric-card">
          <div className="muted small">Ostatnie 12 miesięcy</div>
          <div className="mono metric-value">
            {formatMoney(history.last_12_months)} {currency}
          </div>
        </div>
        <div className="metric-card">
          <div className="muted small">Łącznie od {firstYear}</div>
          <div className="mono metric-value">
            {formatMoney(history.total)} {currency}
          </div>
        </div>
      </div>

      <div className="segmented" role="group" aria-label="Zakres wykresu">
        <button type="button" aria-pressed={view === 'years'} onClick={() => setView('years')}>
          Po latach
        </button>
        {[...history.years].reverse().map((year) => (
          <button key={year.year} type="button" aria-pressed={view === year.year} onClick={() => setView(year.year)}>
            {year.year}
          </button>
        ))}
      </div>

      <DividendBars
        bars={bars}
        currency={currency}
        ariaLabel={
          selectedYear === null
            ? `Dywidendy po latach, ${firstYear}–${currentYear}, w ${currency}${forecast ? `, oraz szacunek na ${forecast.year}` : ''}.`
            : `Dywidendy po miesiącach w ${selectedYear.year}, w ${currency}.`
        }
      />
      {estimateBar.length > 0 && (
        <div className="dividend-legend muted small">
          <span className="dividend-key">
            <span className="dividend-key-swatch is-paid" aria-hidden="true" />
            wypłacone
          </span>
          <span className="dividend-key">
            <span className="dividend-key-swatch" aria-hidden="true" />
            szacunek na {forecast?.year} (na konto, po podatku u źródła) — zakładka „Szacunek”
          </span>
        </div>
      )}

      <div className="table-scroll">
        <table className="positions valued-positions">
          <thead>
            <tr>
              <th>Instrument</th>
              <th className="num">Wypłaty</th>
              <th className="num">Ostatnia</th>
              <th className="num">Ostatnie 12 mies.</th>
              <th className="num">Łącznie</th>
            </tr>
          </thead>
          <tbody>
            {instruments.map((instrument) => (
              <tr key={`${instrument.instrument_key ?? 'unlinked'}:${instrument.name}`}>
                <td>
                  <span className="instrument-name">{instrument.name}</span>
                  {instrument.instrument_key === null && <span className="muted small"> · nieprzypisana</span>}
                </td>
                <td className="num mono">{instrument.payment_count}</td>
                <td className="num">{formatDate(instrument.last_paid_on)}</td>
                <td className="num mono">
                  {formatMoney(instrument.last_12_months)} {currency}
                </td>
                <td className="num mono strong">
                  {formatMoney(instrument.total)} {currency}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>Razem</td>
              <td className="num mono">{history.payments.length}</td>
              <td />
              <td className="num mono">
                {formatMoney(history.last_12_months)} {currency}
              </td>
              <td className="num mono">
                {formatMoney(history.total)} {currency}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      {history.instruments.length > INSTRUMENTS_SHOWN && (
        <button type="button" className="btn-small dividends-more" onClick={() => setAllInstruments((v) => !v)}>
          {allInstruments ? 'Pokaż największe' : `Pokaż wszystkie (${history.instruments.length})`}
        </button>
      )}

      <details className="dividend-payments">
        <summary>
          Wszystkie wypłaty ({history.payments.length}{' '}
          {pluralizePl(history.payments.length, 'wypłata', 'wypłaty', 'wypłat')})
        </summary>
        <div className="table-scroll">
          <table className="positions valued-positions">
            <thead>
              <tr>
                <th>Data</th>
                <th>Instrument</th>
                {multiPortfolio && <th>Portfel</th>}
                <th className="num">Kwota</th>
                <th className="num">Kurs NBP</th>
                <th className="num">{currency}</th>
              </tr>
            </thead>
            <tbody>
              {history.payments.map((payment, index) => (
                <tr key={`${payment.portfolio_id}:${payment.paid_on}:${payment.name}:${index}`}>
                  <td>{formatDate(payment.paid_on)}</td>
                  <td>
                    {payment.name}
                    {payment.is_correction && <span className="muted small"> · korekta</span>}
                  </td>
                  {multiPortfolio && <td className="muted">{payment.portfolio_name}</td>}
                  <td className="num mono">
                    {formatMoney(payment.amount)} {payment.currency}
                  </td>
                  <td className="num mono muted">{payment.fx_rate === null ? '—' : formatPrice(payment.fx_rate)}</td>
                  <td className="num mono">{payment.amount_base === null ? '—' : formatMoney(payment.amount_base)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      {history.warnings.length > 0 && (
        <details className="value-warnings">
          <summary>Uwagi do dywidend ({history.warnings.length})</summary>
          <ul>
            {history.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      )}

      <div className="value-footnotes muted small">
        <p>
          Kwoty, które wpłynęły na konto (po podatku pobranym przez brokera), przeliczone na {currency} kursem
          NBP z dnia wypłaty — te same, które wynik inwestycji liczy jako dywidendy. Wypłata bez rozpoznanego
          instrumentu liczy się do sum pod nazwą z wyciągu.
        </p>
        <p>To opis historii, nie rekomendacja inwestycyjna.</p>
      </div>
    </>
  )
}

export default DividendHistoryPanel

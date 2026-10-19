import type { DividendForecast, DividendForecastRow, DividendSource } from './api'
import DividendBars from './DividendBars'
import type { Bar } from './DividendBars'
import { formatCents, formatDecimal, formatMoney, formatPrice, pluralizePl, toCents } from './format'

const MONTH_SHORT = new Intl.DateTimeFormat('pl-PL', { month: 'short', timeZone: 'UTC' })
const MONTH_LONG = new Intl.DateTimeFormat('pl-PL', { month: 'long', year: 'numeric', timeZone: 'UTC' })

const SOURCE_LABEL: Record<DividendSource, string> = {
  yahoo: 'Yahoo',
  history: 'wyciąg XTB',
  none: 'brak danych',
}

// #267: the withholding rate and where it comes from, e.g. "15% · wyciąg".
function taxLabel(row: DividendForecastRow): string {
  if (row.tax_basis === 'mixed') return 'różny w portfelach'
  if (row.tax_basis === 'unknown' || row.withholding_pct === null) return 'nieznany'
  const rate = `${row.withholding_pct.replace('.0', '').replace('.', ',')}%`
  return `${rate} · ${row.tax_basis === 'statement' ? 'wyciąg' : 'reguła'}`
}

type Props = {
  forecast: DividendForecast | null
  error: string | null
}

// #266/#267: what the last 12 months' payouts would give again in the next
// calendar year, gross and after the tax withheld before payout. Every
// amount comes from the backend; this only formats.
function DividendForecastPanel({ forecast, error }: Props) {
  if (forecast === null) {
    return <p className={error ? 'error' : 'muted'}>{error ?? 'Pobieram dywidendy z Yahoo i liczę szacunek…'}</p>
  }

  const currency = forecast.base_currency
  const paying = forecast.rows.filter((row) => toCents(row.estimate) !== 0)
  const silent = forecast.rows.length - paying.length
  const hasTopUp = toCents(forecast.total_top_up) !== 0
  const bars: Bar[] = forecast.months_credited.map((total, month) => {
    const day = new Date(Date.UTC(forecast.year, month, 1))
    return {
      id: String(month),
      label: MONTH_SHORT.format(day).replace('.', ''),
      title: `${MONTH_LONG.format(day)} — szacunek na konto`,
      cents: toCents(total),
      estimate: true,
    }
  })

  return (
    <>
      <div className="metric-cards">
        <div className="metric-card">
          <div className="muted small">Brutto {forecast.year}</div>
          <div className="mono metric-value">
            {formatMoney(forecast.total)} {currency}
          </div>
        </div>
        <div className="metric-card">
          <div className="muted small">Na konto (po podatku u źródła)</div>
          <div className="mono metric-value">
            {formatMoney(forecast.total_credited)} {currency}
          </div>
          <div className="muted small">
            średnio {formatCents(Math.round(toCents(forecast.total_credited) / 12))} {currency} / mies.
          </div>
        </div>
        {hasTopUp && (
          <div className="metric-card">
            <div className="muted small">Do dopłaty w PIT (szacunek)</div>
            <div className="mono metric-value">
              {formatMoney(forecast.total_top_up)} {currency}
            </div>
          </div>
        )}
        <div className="metric-card">
          <div className="muted small">Instrumenty z dywidendą</div>
          <div className="mono metric-value">
            {paying.length} z {forecast.rows.length}
          </div>
        </div>
      </div>

      <DividendBars
        bars={bars}
        currency={currency}
        ariaLabel={`Szacunek dywidend na konto po miesiącach ${forecast.year}, w ${currency}.`}
      />

      {paying.length > 0 && (
        <div className="table-scroll">
          <table className="positions valued-positions">
            <thead>
              <tr>
                <th>Instrument</th>
                <th className="num">Sztuki</th>
                <th className="num">Na akcję (12 mies.)</th>
                <th className="num">Stopa</th>
                <th className="num">Brutto</th>
                <th className="dividend-tax">Podatek u źródła</th>
                <th className="num">Na konto</th>
                {hasTopUp && <th className="num">Dopłata w PIT</th>}
                <th>Źródło</th>
              </tr>
            </thead>
            <tbody>
              {paying.map((row) => (
                <tr key={row.instrument_key}>
                  <td className="instrument-name">{row.name}</td>
                  <td className="num mono">{formatDecimal(row.quantity)}</td>
                  <td className="num mono">
                    {row.per_share === null ? '—' : `${formatPrice(row.per_share)} ${row.per_share_currency ?? ''}`}
                  </td>
                  <td className="num mono">{row.yield_pct === null ? '—' : `${row.yield_pct.replace('.', ',')}%`}</td>
                  <td className="num mono">
                    {formatMoney(row.estimate)} {currency}
                  </td>
                  <td className="muted small dividend-tax">{taxLabel(row)}</td>
                  <td className="num mono strong">
                    {formatMoney(row.credited)} {currency}
                  </td>
                  {hasTopUp && (
                    <td className="num mono muted">
                      {toCents(row.top_up) === 0 ? '—' : `${formatMoney(row.top_up)} ${currency}`}
                    </td>
                  )}
                  <td className="muted small">
                    {SOURCE_LABEL[row.source]}
                    {row.mismatch && (
                      <span className="dividend-flag" title="Yahoo i wyciąg XTB podają różne kwoty na wypłatę">
                        {' '}
                        · rozbieżność
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td>Razem</td>
                <td />
                <td />
                <td />
                <td className="num mono">
                  {formatMoney(forecast.total)} {currency}
                </td>
                <td />
                <td className="num mono">
                  {formatMoney(forecast.total_credited)} {currency}
                </td>
                {hasTopUp && (
                  <td className="num mono">
                    {formatMoney(forecast.total_top_up)} {currency}
                  </td>
                )}
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {silent > 0 && (
        <p className="muted small">
          {silent} {pluralizePl(silent, 'instrument', 'instrumenty', 'instrumentów')} bez wypłat w ostatnich 12
          miesiącach (albo bez danych — patrz uwagi) — szacunek 0.
        </p>
      )}

      {forecast.warnings.length > 0 && (
        <details className="value-warnings">
          <summary>Uwagi do szacunku ({forecast.warnings.length})</summary>
          <ul>
            {forecast.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      )}

      <div className="value-footnotes muted small">
        <p>
          Szacunek z wypłat ostatnich 12 miesięcy przy dzisiejszej liczbie sztuk i dzisiejszych kursach walut NBP:
          każda wypłata na akcję powtarza się w tym samym miesiącu {forecast.year} (Yahoo datuje ją dniem ustalenia
          prawa, więc wypłata może przyjść miesiąc później). Stopa to wypłaty z 12 miesięcy podzielone przez ostatni
          kurs.
        </p>
        <p>
          „Na konto” to brutto minus podatek pobierany przed wypłatą: u źródła za granicą, a od polskich spółek 19% na
          koncie zwykłym i 0% na IKE i IKZE. Na koncie zwykłym, gdy podatek u źródła jest niższy niż 19%, różnicę
          dopłaca się w zeznaniu — pokazana osobno, nie odjęta. Stawka pochodzi z Twoich wyciągów, a dla spółki, która
          jeszcze nic nie wypłaciła, z reguły dla jej kraju.
        </p>
        <p>To szacunek, nie rozliczenie podatkowe. Opis, nie prognoza ani rekomendacja.</p>
      </div>
    </>
  )
}

export default DividendForecastPanel

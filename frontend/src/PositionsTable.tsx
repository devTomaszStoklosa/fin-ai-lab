import type { ValuedPosition } from './api'
import {
  formatCents,
  formatDate,
  formatDecimal,
  formatMoney,
  formatPercent,
  formatPrice,
  pluralizePl,
  toCents,
} from './format'

type Props = {
  positions: ValuedPosition[]
  baseCurrency: string
  // Only on the all-portfolios view: which portfolio a row belongs to.
  portfolioNames?: Map<string, string>
  onEdit?: (position: ValuedPosition) => void
  onDelete?: (position: ValuedPosition) => void
  // A manual position's own valuations (#288).
  onValuations?: (position: ValuedPosition) => void
}

function price(value: string | null, currency: string | null): string {
  return value === null ? '—' : `${formatPrice(value)} ${currency ?? ''}`.trim()
}

function PositionsTable({
  positions,
  baseCurrency,
  portfolioNames,
  onEdit,
  onDelete,
  onValuations,
}: Props) {
  const withActions = onEdit !== undefined || onDelete !== undefined || onValuations !== undefined
  const totalCents = positions.reduce((sum, p) => sum + (p.value === null ? 0 : toCents(p.value)), 0)

  return (
    <section className="positions-card">
      <div className="positions-head">
        <h2>Pozycje</h2>
        <span className="muted small">
          {positions.length} {pluralizePl(positions.length, 'pozycja', 'pozycje', 'pozycji')}
        </span>
      </div>
      {positions.length === 0 ? (
        <p className="muted">Brak pozycji — wgraj plik albo dodaj pozycję ręcznie.</p>
      ) : (
        <div className="table-scroll">
          <table className="positions valued-positions">
            <thead>
              <tr>
                <th>Aktywo</th>
                {portfolioNames && <th>Portfel</th>}
                <th className="num">Ilość</th>
                <th className="num">Cena zakupu</th>
                <th className="num">Cena bieżąca</th>
                <th className="num">Wartość</th>
                <th className="num">Zwrot</th>
                {withActions && <th aria-label="Akcje"></th>}
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <tr key={position.position_id}>
                  <td>
                    <div className="instrument-name">{position.instrument_name}</div>
                    <div className="muted small">
                      {position.symbol ?? position.isin ?? (position.is_manual ? 'ręczna' : '—')}
                    </div>
                  </td>
                  {portfolioNames && (
                    <td className="muted">{portfolioNames.get(position.portfolio_id) ?? ''}</td>
                  )}
                  <td className="num mono">{formatDecimal(position.quantity)}</td>
                  <td className="num mono">{price(position.avg_cost, position.cost_currency)}</td>
                  <td className="num mono">
                    {price(position.current_price, position.price_currency)}
                    {position.is_manual && (
                      <div className="muted small">
                        {position.valued_on === null
                          ? 'cena zakupu'
                          : `wycena z ${formatDate(position.valued_on)}`}
                      </div>
                    )}
                  </td>
                  <td className="num mono strong">
                    {position.value === null ? '—' : `${formatMoney(position.value)} ${baseCurrency}`}
                  </td>
                  <td
                    className={`num mono strong ${
                      position.return_pct === null
                        ? ''
                        : position.return_pct.startsWith('-')
                          ? 'return-loss'
                          : 'return-gain'
                    }`}
                  >
                    {position.return_pct === null ? '—' : formatPercent(position.return_pct)}
                  </td>
                  {withActions && (
                    <td className="positions-actions">
                      {position.is_manual && (
                        <>
                          {onValuations && (
                            <button type="button" onClick={() => onValuations(position)}>
                              Wyceny
                            </button>
                          )}
                          {onEdit && (
                            <button type="button" onClick={() => onEdit(position)}>
                              Edytuj
                            </button>
                          )}
                          {onDelete && (
                            <button type="button" onClick={() => onDelete(position)}>
                              Usuń
                            </button>
                          )}
                        </>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td>Razem</td>
                {portfolioNames && <td></td>}
                <td></td>
                <td></td>
                <td></td>
                <td className="num mono">
                  {formatCents(totalCents)} {baseCurrency}
                </td>
                <td></td>
                {withActions && <td></td>}
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <p className="muted small table-note">
        Cena bieżąca w walucie, w której broker podaje wartość pozycji (tej samej co cena zakupu).
        Zwrot to zmiana ceny względem ceny zakupu, bez prowizji i podatków. Pozycja ręczna
        ma cenę z Twojej ostatniej wyceny.
      </p>
    </section>
  )
}

export default PositionsTable

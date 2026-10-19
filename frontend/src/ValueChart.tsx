import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import type { Valuation } from './api'
import BenchmarkPicker from './BenchmarkPicker'
import CompareReadout from './CompareReadout'
import { formatCents, formatDate, formatDecimal, formatReturnUnits, toCents } from './format'
import {
  BASIS_LABEL,
  earningsBreakdown,
  NOT_COVERED_LABEL,
  percentOfBase,
  summarizeInvestment,
} from './investment'
import {
  alignBenchmark,
  portfolioReturnIndex,
  rebasedReturn,
  sameDepositsInBenchmark,
  unquotedShare,
} from './returns'
import { seriesColor } from './seriesColors'
import { useBenchmark, useStoredBenchmarkTicker } from './useBenchmark'

const RANGES = [
  { id: '1M', label: '1 mies.', days: 30 },
  { id: '3M', label: '3 mies.', days: 92 },
  { id: '6M', label: '6 mies.', days: 183 },
  { id: '1Y', label: '1 rok', days: 365 },
  { id: 'ALL', label: 'Od początku', days: null },
] as const
type RangeId = (typeof RANGES)[number]['id']
// "compare" (#273): the return in % against a benchmark, on the same range
// and day under the cursor as the value modes.
type Mode = 'line' | 'stack' | 'compare'

const HEIGHT = 300
const MARGIN = { top: 12, right: 12, bottom: 30, left: 72 }

const SHORT_DATE = new Intl.DateTimeFormat('pl-PL', { day: 'numeric', month: 'short', timeZone: 'UTC' })
const MONTH_YEAR = new Intl.DateTimeFormat('pl-PL', { month: 'short', year: '2-digit', timeZone: 'UTC' })
const TIME = new Intl.DateTimeFormat('pl-PL', { hour: '2-digit', minute: '2-digit' })

function utc(isoDate: string): Date {
  return new Date(`${isoDate}T00:00:00Z`)
}

// 1/2/2.5/5 x 10^n -- axis ticks at clean numbers.
function niceStep(rough: number): number {
  const magnitude = Math.pow(10, Math.floor(Math.log10(Math.max(rough, 1))))
  return [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((step) => step >= rough) ?? magnitude * 10
}

function useElementWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

type Props = {
  valuation: Valuation
  title: string
  // More than one portfolio: legend toggles and the "Skład" (stacked) mode.
  multi: boolean
  hidden: Set<string>
  onToggle: (portfolioId: string) => void
  onRefresh: () => void
  refreshing: boolean
}

function ValueChart({ valuation, title, multi, hidden, onToggle, onRefresh, refreshing }: Props) {
  const [range, setRange] = useState<RangeId>('ALL')
  const [mode, setMode] = useState<Mode>('line')
  const [active, setActive] = useState<number | null>(null)
  const [plotRef, width] = useElementWidth<HTMLDivElement>(848)

  const dates = valuation.dates
  const lastIndex = dates.length - 1
  const colorById = new Map(valuation.portfolios.map((p, index) => [p.id, seriesColor(index)]))
  const visible = valuation.portfolios.filter((p) => !hidden.has(p.id))
  const stack = multi && mode === 'stack'
  const compare = mode === 'compare'

  const [benchmarkTicker, setBenchmarkTicker] = useStoredBenchmarkTicker()
  const benchmarkState = useBenchmark(benchmarkTicker, dates[0] ?? null, compare)
  const benchmark = benchmarkState.benchmark
  const benchmarkLabel = benchmark?.ticker === benchmarkTicker ? benchmark.label : benchmarkTicker

  // Integer cents per day: the backend's own totals when nothing is hidden,
  // otherwise an exact sum of the visible portfolios' own series.
  const totals = useMemo(() => {
    if (hidden.size === 0) return valuation.totals.map(toCents)
    const shown = valuation.portfolios.filter((p) => !hidden.has(p.id))
    return valuation.dates.map((_, i) => shown.reduce((sum, p) => sum + toCents(p.values[i]), 0))
  }, [valuation, hidden])

  const rangeDays = RANGES.find((r) => r.id === range)?.days ?? null
  const start = rangeDays === null ? 0 : Math.max(0, lastIndex - rangeDays)
  const index = active !== null && active >= start ? active : lastIndex
  const hovering = active !== null && active >= start

  // Comparison mode: both returns from the range's first day, in hundredths
  // of a percent (null where a series has no value yet).
  const portfolioReturn = useMemo(
    () => (compare ? rebasedReturn(portfolioReturnIndex(valuation, hidden), start) : []),
    [compare, valuation, hidden, start],
  )
  const benchmarkIndex = useMemo(
    () => (compare && benchmark !== null ? alignBenchmark(benchmark, valuation.dates) : null),
    [compare, benchmark, valuation],
  )
  const benchmarkReturn = useMemo(
    () => (benchmarkIndex !== null ? rebasedReturn(benchmarkIndex, start) : valuation.dates.map(() => null)),
    [benchmarkIndex, valuation, start],
  )
  const sameDeposits = useMemo(
    () => (benchmarkIndex !== null ? sameDepositsInBenchmark(valuation, hidden, benchmarkIndex) : null),
    [benchmarkIndex, valuation, hidden],
  )

  const plotWidth = Math.max(width - MARGIN.left - MARGIN.right, 50)
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom

  const scale = useMemo(() => {
    if (compare) {
      // Around 0 (the range's start), whichever way the lines went.
      const shown = [portfolioReturn, benchmarkReturn].flatMap((series) =>
        series.slice(start).filter((v): v is number => v !== null),
      )
      const low = Math.min(0, ...shown)
      const high = Math.max(0, ...shown)
      const spread = Math.max(high - low, 100)
      const step = niceStep((spread * 1.15) / 4)
      const min = Math.floor((low - spread * 0.05) / step) * step
      const max = Math.max(min + step * 2, Math.ceil((high + spread * 0.05) / step) * step)
      return { min, max, step }
    }
    const inRange = totals.slice(start)
    const high = Math.max(...inRange, 1)
    if (stack) {
      const step = niceStep(high / 4)
      return { min: 0, max: Math.ceil(high / step) * step || step, step }
    }
    const positive = inRange.filter((v) => v > 0)
    const low = positive.length ? Math.min(...positive) : 0
    const spread = Math.max(high - low, high * 0.02, 100)
    const step = niceStep((spread * 1.15) / 4)
    const min = Math.max(0, Math.floor((low - spread * 0.05) / step) * step)
    const max = Math.max(min + step * 2, Math.ceil((high + spread * 0.05) / step) * step)
    return { min, max, step }
  }, [totals, start, stack, compare, portfolioReturn, benchmarkReturn])

  const x = (i: number) => MARGIN.left + ((i - start) / Math.max(lastIndex - start, 1)) * plotWidth
  const y = (units: number) =>
    MARGIN.top + (1 - (units - scale.min) / (scale.max - scale.min)) * plotHeight
  const path = (points: [number, number][]) =>
    points.map(([px, py], i) => `${i === 0 ? 'M' : 'L'}${px.toFixed(1)},${py.toFixed(1)}`).join('')
  // A line that breaks where the series has no value.
  const gappedPath = (values: (number | null)[]) => {
    let d = ''
    let open = false
    for (const i of indices) {
      const value = values[i]
      if (value === null) {
        open = false
        continue
      }
      d += `${open ? 'L' : 'M'}${x(i).toFixed(1)},${y(value).toFixed(1)}`
      open = true
    }
    return d
  }

  const indices = dates.map((_, i) => i).slice(start)
  const totalPath = compare ? gappedPath(portfolioReturn) : path(indices.map((i) => [x(i), y(totals[i])]))
  const benchmarkPath = compare ? gappedPath(benchmarkReturn) : ''

  const areas = stack
    ? visible.map((portfolio, k) => {
        const below = (i: number) =>
          visible.slice(0, k).reduce((sum, p) => sum + toCents(p.values[i]), 0)
        const top = indices.map((i): [number, number] => [x(i), y(below(i) + toCents(portfolio.values[i]))])
        const bottom = indices.map((i): [number, number] => [x(i), y(below(i))]).reverse()
        return { id: portfolio.id, d: `${path([...top, ...bottom])}Z`, color: colorById.get(portfolio.id) }
      })
    : []

  const yTicks: number[] = []
  for (let v = scale.min; v <= scale.max + 0.5; v += scale.step) yTicks.push(v)
  // A % tick shows as many decimals as its step needs (2.5% steps: one).
  const tickDigits = scale.step % 100 === 0 ? 0 : scale.step % 10 === 0 ? 1 : 2
  const tickLabel = (tick: number) =>
    compare ? formatReturnUnits(tick, tickDigits) : tick === 0 ? '0' : formatCents(tick, 0)
  const tickFormat = rangeDays !== null && rangeDays <= 92 ? SHORT_DATE : MONTH_YEAR
  // Fewer date labels on a narrow screen, so they never run into each other.
  const xTickSteps = width < 560 ? 2 : 4
  const xTicks = Array.from({ length: xTickSteps + 1 }, (_, k) => k)
    .map((k) => Math.round(start + ((lastIndex - start) * k) / xTickSteps))
    .filter((i, k, all) => all.indexOf(i) === k)

  // One marker per day, listing every visible portfolio's change that day.
  // Not in the comparison: a purchase or sale does not move the return.
  const changesByDate = new Map<string, string[]>()
  for (const change of compare ? [] : valuation.changes) {
    if (hidden.has(change.portfolio_id)) continue
    const sign = change.quantity_change.startsWith('-') ? '' : '+'
    const line = `${change.instrument_name}: ${sign}${formatDecimal(change.quantity_change)} szt.`
    changesByDate.set(change.date, [...(changesByDate.get(change.date) ?? []), line])
  }
  const indexByDate = new Map(dates.map((d, i) => [d, i]))
  const markers = [...changesByDate.entries()]
    .map(([date, lines]) => ({ date, index: indexByDate.get(date) ?? -1, lines }))
    .filter((marker) => marker.index >= start)

  // What the purchases are worth against what they cost (fin-ai-lab#238):
  // independent of the chart's range and of the day under the cursor.
  const investment = summarizeInvestment(visible)
  const sign = investment !== null && investment.result < 0 ? '−' : '+'

  // Visible portfolios whose imports carry no dividends: their part of the
  // return is prices only.
  const withoutDividends = visible
    .filter((p) => !p.dividends_included && p.values.some((v) => toCents(v) !== 0))
    .map((p) => p.name)
  // The comparison's headline (#273): the owner's result against the same
  // deposits in the benchmark -- only where every visible portfolio states
  // its deposits (the investment summary's own rule for its percentage).
  const depositsReadout =
    compare && investment !== null && investment.basis === 'deposits'
      ? {
          result: investment.result,
          netDeposits: investment.base,
          benchmarkResult: sameDeposits !== null ? sameDeposits.value - sameDeposits.netDeposits : null,
        }
      : null
  const capturedGain = visible.reduce((sum, p) => sum + toCents(p.history_gain), 0)
  const coverageReadout = compare
    ? {
        captured: capturedGain,
        result: investment?.result ?? capturedGain,
        unquotedShare: unquotedShare(valuation, hidden, start),
      }
    : null
  const benchmarkStartsLater =
    compare && benchmark !== null && benchmark.first_price_date > dates[start]
      ? benchmark.first_price_date
      : null

  function handlePointer(event: PointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    const px = event.clientX - bounds.left
    const ratio = (px - MARGIN.left) / plotWidth
    const i = Math.round(start + ratio * (lastIndex - start))
    setActive(Math.min(lastIndex, Math.max(start, i)))
  }

  function handleRefresh() {
    onRefresh()
    if (compare) benchmarkState.refresh()
  }

  if (dates.length === 0) {
    return (
      <section className="value-card">
        <div className="value-eyebrow">{title}</div>
        <div className="value-amount">0 {valuation.base_currency}</div>
        <p className="muted">
          Brak pozycji. Wgraj plik albo dodaj pozycję ręcznie, żeby zobaczyć wartość w czasie.
        </p>
      </section>
    )
  }

  const dimmed = refreshing || (compare && benchmarkState.loading)
  const portfolioDot = compare ? portfolioReturn[index] : totals[index]
  const benchmarkDot = compare ? benchmarkReturn[index] : null

  return (
    <section className={`value-card ${dimmed ? 'is-refreshing' : ''}`}>
      <div className="value-head">
        <div className="value-readout">
          {compare ? (
            <CompareReadout
              title={title}
              currency={valuation.base_currency}
              portfolio={portfolioReturn[index]}
              benchmark={benchmarkReturn[index]}
              benchmarkLabel={benchmarkLabel}
              from={dates[start]}
              historyStart={dates[0]}
              loading={benchmarkState.loading}
              error={benchmarkState.error}
              deposits={depositsReadout}
              coverage={coverageReadout}
            />
          ) : (
            <>
              <div className="value-eyebrow">{title}</div>
              <div className="value-amount">
                {formatCents(totals[index])} {valuation.base_currency}
              </div>
              <div className="value-delta">
                {investment !== null ? (
                  <>
                    <span className="muted">Wynik inwestycji</span>
                    <span className={`mono ${investment.result >= 0 ? 'return-gain' : 'return-loss'}`}>
                      {sign}
                      {formatCents(Math.abs(investment.result))} {valuation.base_currency} ({sign}
                      {percentOfBase(investment)}%)
                    </span>
                    <span className="muted">
                      od {formatCents(investment.base, 0)} {valuation.base_currency}{' '}
                      {BASIS_LABEL[investment.basis]}
                    </span>
                  </>
                ) : (
                  <span className="muted">Wynik inwestycji: brak danych o koszcie zakupu</span>
                )}
              </div>
              {investment !== null && earningsBreakdown(investment).length > 0 && (
                <div className="muted small">
                  W tym: {earningsBreakdown(investment).join(' · ')} {valuation.base_currency}
                </div>
              )}
              {investment !== null && investment.notCovered.length > 0 && (
                <div className="muted small">
                  Bez: {investment.notCovered.map((item) => NOT_COVERED_LABEL[item]).join(', ')} (jeszcze nie
                  importowane)
                </div>
              )}
            </>
          )}
          <div className="value-asof muted small">
            {hovering ? (
              <span>Stan na zamknięcie {formatDate(dates[index])}</span>
            ) : (
              <>
                <span className="live-dot" aria-hidden="true" />
                <span>
                  {valuation.prices_as_of
                    ? `Kursy z ${formatDate(valuation.prices_as_of)}`
                    : 'Brak kursów rynkowych'}{' '}
                  · pobrane {TIME.format(new Date(valuation.computed_at))}
                </span>
                <button type="button" className="btn-small" onClick={handleRefresh} disabled={refreshing}>
                  {refreshing ? 'Odświeżam…' : 'Odśwież notowania'}
                </button>
              </>
            )}
          </div>
        </div>

        <div className="segmented" role="group" aria-label="Zakres czasu">
          {RANGES.map((r) => (
            <button
              key={r.id}
              type="button"
              aria-pressed={range === r.id}
              onClick={() => {
                setRange(r.id)
                setActive(null)
              }}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="value-legend-row">
        {multi && (
          <div className="value-legend" role="group" aria-label="Widoczne portfele">
            {valuation.portfolios.map((portfolio) => {
              const on = !hidden.has(portfolio.id)
              return (
                <button
                  key={portfolio.id}
                  type="button"
                  className="legend-chip"
                  aria-pressed={on}
                  onClick={() => onToggle(portfolio.id)}
                >
                  <span
                    className="legend-swatch"
                    style={{ background: colorById.get(portfolio.id), opacity: on ? 1 : 0.3 }}
                  />
                  <span>{portfolio.name}</span>
                  {on && (
                    <span className="mono muted">
                      {formatCents(toCents(portfolio.values[index]), 0)}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        )}
        <div className="value-mode-controls">
          {compare && <BenchmarkPicker ticker={benchmarkTicker} onChange={setBenchmarkTicker} />}
          <div className="segmented" role="group" aria-label="Rodzaj wykresu">
            <button type="button" aria-pressed={mode === 'line'} onClick={() => setMode('line')}>
              Wartość
            </button>
            {multi && (
              <button type="button" aria-pressed={mode === 'stack'} onClick={() => setMode('stack')}>
                Skład
              </button>
            )}
            <button type="button" aria-pressed={compare} onClick={() => setMode('compare')}>
              Porównanie
            </button>
          </div>
        </div>
      </div>

      <div className="value-plot" ref={plotRef}>
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={
            compare
              ? `Zwrot w procentach: ${title} i ${benchmarkLabel}. Wybierz dzień suwakiem pod wykresem.`
              : `Dzienna wartość: ${title}. Wybierz dzień suwakiem pod wykresem.`
          }
          onPointerMove={handlePointer}
          onPointerLeave={() => setActive(null)}
        >
          {yTicks.map((tick) => (
            <g key={tick}>
              <line
                className={compare && tick === 0 ? 'grid zero-line' : 'grid'}
                x1={MARGIN.left}
                x2={width - MARGIN.right}
                y1={y(tick)}
                y2={y(tick)}
              />
              <text className="axis" x={MARGIN.left - 8} y={y(tick) + 4} textAnchor="end">
                {tickLabel(tick)}
              </text>
            </g>
          ))}
          {areas.map((area) => (
            <path key={area.id} d={area.d} fill={area.color} fillOpacity={0.85} className="stack-area" />
          ))}
          {compare && <path d={benchmarkPath} className="benchmark-line" />}
          <path d={totalPath} className="total-line" />
          {markers.map((marker) => (
            <path
              key={marker.date}
              className="change-marker"
              d={`M${x(marker.index) - 5},${HEIGHT - MARGIN.bottom - 1}L${x(marker.index) + 5},${HEIGHT - MARGIN.bottom - 1}L${x(marker.index)},${HEIGHT - MARGIN.bottom - 10}Z`}
            >
              <title>{`${formatDate(marker.date)}\n${marker.lines.join('\n')}`}</title>
            </path>
          ))}
          {hovering && (
            <line className="crosshair" x1={x(index)} x2={x(index)} y1={MARGIN.top} y2={HEIGHT - MARGIN.bottom} />
          )}
          {benchmarkDot !== null && (
            <circle className="benchmark-dot" cx={x(index)} cy={y(benchmarkDot)} r={5} />
          )}
          {portfolioDot !== null && <circle className="value-dot" cx={x(index)} cy={y(portfolioDot)} r={5} />}
          {xTicks.map((i, k) => (
            <text
              key={i}
              className="axis"
              x={x(i)}
              y={HEIGHT - 8}
              textAnchor={k === 0 ? 'start' : i === lastIndex ? 'end' : 'middle'}
            >
              {tickFormat.format(utc(dates[i]))}
            </text>
          ))}
        </svg>
        <input
          type="range"
          className="value-slider"
          min={start}
          max={lastIndex}
          value={index}
          onChange={(e) => setActive(Number(e.target.value))}
          onBlur={() => setActive(null)}
          aria-label="Wybierz dzień na wykresie"
          aria-valuetext={formatDate(dates[index])}
          style={{ marginLeft: MARGIN.left, width: plotWidth }}
        />
        <div className="value-legend-notes muted small" style={{ paddingLeft: MARGIN.left }}>
          {compare ? (
            <>
              <span className="marker-key">
                <span className="compare-swatch compare-swatch-portfolio" aria-hidden="true" />
                portfel (bez wpływu wpłat, zakupów i sprzedaży)
              </span>
              <span className="marker-key">
                <span className="compare-swatch compare-swatch-benchmark" aria-hidden="true" />
                {benchmarkLabel}
              </span>
              <span>0% = pierwszy dzień zakresu</span>
            </>
          ) : (
            <>
              <span className="marker-key">
                <svg width="10" height="9" viewBox="0 0 10 9" aria-hidden="true">
                  <path d="M0 9L10 9L5 0Z" className="change-marker" />
                </svg>
                zmiana składu (zakup lub sprzedaż)
              </span>
              <span>
                {stack
                  ? 'Oś od zera, wartości portfeli jedna na drugiej'
                  : `Oś zaczyna się od ${formatCents(scale.min, 0)} ${valuation.base_currency}, nie od zera`}
              </span>
            </>
          )}
        </div>
      </div>

      {valuation.warnings.length > 0 && (
        <details className="value-warnings">
          <summary>Uwagi do wyceny ({valuation.warnings.length})</summary>
          <ul>
            {valuation.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      )}

      <div className="value-footnotes muted small">
        {compare ? (
          <>
            {withoutDividends.length > 0 && (
              <p>
                Bez dywidend: {withoutDividends.join(', ')} — import nie zawiera operacji gotówkowych, więc
                zwrot tych portfeli to sam ruch cen.
              </p>
            )}
            {depositsReadout !== null && (
              <p>
                „Te same wpłaty”: każda wpłata kupuje {benchmarkLabel} po kursie z dnia wpłaty (w{' '}
                {valuation.base_currency}, kursem NBP), każda wypłata go sprzedaje; wynik to dzisiejsza wartość
                minus suma wpłat. W benchmarku cała wpłata pracuje od razu, a w portfelu część pieniędzy mogła
                czekać na koncie. Twój wynik to „Wynik inwestycji” z trybu „Wartość” i nie zależy od zakresu
                wykresu.
                {sameDeposits?.boughtLate
                  ? ` Wpłaty sprzed pierwszego notowania ${benchmarkLabel} albo sprzed pierwszego dnia wykresu kupują go po pierwszym dostępnym kursie.`
                  : ''}
              </p>
            )}
            {benchmarkStartsLater !== null && (
              <p>
                Notowania {benchmarkLabel} są dostępne od {formatDate(benchmarkStartsLater)} — od tego dnia
                liczy się jego zwrot.
              </p>
            )}
            <p>
              Zwrot portfela jest liczony dzień po dniu: wartość wczorajszego składu po dzisiejszych cenach
              plus dywidendy, które dziś wpłynęły na konto, wobec wczorajszej wartości. Wpłaty, wypłaty,
              zakupy i sprzedaże go nie zmieniają, dlatego da się go porównać z indeksem. Dywidendy są po
              podatku u źródła i liczą się w dniu wpłaty, choć kurs spada już w dniu ustalenia prawa — przez
              te dni zwrot jest chwilowo niższy. Pozycje ręczne i bez notowań mają stałą wartość.
            </p>
            <p>
              {benchmark?.note ? `${benchmarkLabel}: ${benchmark.note}. ` : ''}Benchmark jest przeliczony na{' '}
              {valuation.base_currency} kursem NBP z każdego dnia, tak jak portfel. Indeksy z dywidendami liczą
              je przed podatkiem, a fundusze ETF pomniejszają o swoje opłaty. Zwrot różni się od „Wyniku
              inwestycji”, który mierzy zysk w złotówkach. To opis przeszłości, nie rekomendacja
              inwestycyjna.
            </p>
          </>
        ) : (
          <>
            <p>
              Wykres: dzienne kursy zamknięcia razy liczba sztuk posiadana danego dnia, przeliczone na{' '}
              {valuation.base_currency} kursem NBP. Skok przy znaczniku ▲ to zmiana składu, nie ruch cen. W
              weekendy i święta obowiązuje kurs z poprzedniej sesji.
            </p>
            <p>
              Wynik inwestycji to wpływy ze sprzedaży plus dzisiejsza wartość otwartych pozycji minus koszt
              wszystkich zakupów (z prowizją), a dla kont z operacjami gotówkowymi (XTB, historia
              finansowa Bossy) także dywidendy, odsetki od wolnych środków i opłaty. Każda kwota jest po
              kursie NBP z dnia transakcji. Wpłaty i wypłaty gotówki nie zmieniają wyniku. Procent odnosi
              się do wpłat pomniejszonych o wypłaty, jeśli wszystkie widoczne portfele je znają; w
              pozostałych przypadkach do sumy kosztów zakupów, która liczy też środki
              reinwestowane ze sprzedaży, więc jest większa od wpłat. To opis stanu, nie rekomendacja
              inwestycyjna.
            </p>
          </>
        )}
      </div>
    </section>
  )
}

export default ValueChart

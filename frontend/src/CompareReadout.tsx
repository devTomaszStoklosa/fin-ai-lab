import { formatCents, formatDate, formatReturnUnits } from './format'

// What the owner earned against the same deposits put into the benchmark
// (money-weighted, the whole history), integer cents.
export type DepositsReadout = {
  result: number
  netDeposits: number
  benchmarkResult: number | null // null until the benchmark has loaded
}

// How much of the gain the chart's return can see (#273): the price moves
// and dividends in the daily history against the investment result, and
// the share of value held without daily quotes in the range.
export type CoverageReadout = {
  captured: number // integer cents
  result: number // integer cents
  unquotedShare: number | null
}

type Props = {
  title: string
  currency: string
  // Returns from `from` to the day shown, in hundredths of a percent.
  portfolio: number | null
  benchmark: number | null
  benchmarkLabel: string
  from: string
  historyStart: string
  loading: boolean
  error: string | null
  deposits: DepositsReadout | null
  coverage: CoverageReadout | null
}

function signedCents(cents: number, fractionDigits: 0 | 2 = 2): string {
  return `${cents < 0 ? '−' : '+'}${formatCents(Math.abs(cents), fractionDigits)}`
}

function shareOf(cents: number, base: number): string {
  return formatReturnUnits((cents / base) * 10000)
}

// Colored only when the shown value is not (rounded to) zero.
function gainClass(value: number, zeroBelow: number): string {
  if (Math.abs(value) < zeroBelow) return 'muted'
  return value > 0 ? 'return-gain' : 'return-loss'
}

// The comparison mode's readout (#273). With deposit data, the headline is
// money-weighted: the owner's result against what the same deposits would
// have earned in the benchmark. The chart's return (deposits left out) for
// the range and day shown comes under it. Descriptive only -- what
// happened, never what to do about it.
function CompareReadout({
  title,
  currency,
  portfolio,
  benchmark,
  benchmarkLabel,
  from,
  historyStart,
  loading,
  error,
  deposits,
  coverage,
}: Props) {
  const difference = portfolio !== null && benchmark !== null ? portfolio - benchmark : null
  const benchmarkStatus =
    error !== null ? (
      <span className="error">{error}</span>
    ) : loading ? (
      <span className="muted">Pobieram notowania benchmarku…</span>
    ) : null

  const chartLine = (
    <>
      <span className="compare-key">
        <span className="compare-swatch compare-swatch-portfolio" aria-hidden="true" />
        portfel {portfolio === null ? '—' : formatReturnUnits(portfolio)}
      </span>
      {benchmark !== null ? (
        <span className="compare-key">
          <span className="compare-swatch compare-swatch-benchmark" aria-hidden="true" />
          {benchmarkLabel} {formatReturnUnits(benchmark)}
        </span>
      ) : (
        !loading && error === null && <span className="muted">{benchmarkLabel}: brak notowań w tym okresie</span>
      )}
      {difference !== null && (
        <>
          <span className="muted">różnica</span>
          <span className={`mono ${gainClass(difference, 5)}`}>{formatReturnUnits(difference, 1, ' pp')}</span>
        </>
      )}
    </>
  )

  // The chart can see less than the result (part of the gain is missing
  // from the daily history) or more (#280): it values at daily closes and
  // leaves out commissions, while the result uses trade prices after them.
  const missed = coverage !== null ? coverage.result - coverage.captured : 0
  const threshold = coverage !== null ? Math.max(Math.abs(coverage.result) * 0.1, 10000) : 0
  const incomplete = coverage !== null && missed > threshold
  const exceeds = coverage !== null && -missed > threshold
  const unquotedPercent =
    coverage?.unquotedShare != null && coverage.unquotedShare >= 0.05
      ? Math.round(coverage.unquotedShare * 100)
      : null

  return (
    <>
      {deposits !== null ? (
        <>
          <div className="value-eyebrow">{title} · wynik od pierwszej wpłaty</div>
          <div className="value-amount">
            {signedCents(deposits.result)} {currency}
          </div>
          <div className="value-delta">
            <span className="muted">{shareOf(deposits.result, deposits.netDeposits)} wpłat</span>
            {benchmarkStatus ??
              (deposits.benchmarkResult !== null && (
                <>
                  <span className="compare-key">
                    <span className="compare-swatch compare-swatch-benchmark" aria-hidden="true" />
                    te same wpłaty w {benchmarkLabel}
                  </span>
                  <span className="mono">
                    {signedCents(deposits.benchmarkResult, 0)} {currency} (
                    {shareOf(deposits.benchmarkResult, deposits.netDeposits)})
                  </span>
                  <span className="muted">różnica</span>
                  <span className={`mono ${gainClass(deposits.result - deposits.benchmarkResult, 50)}`}>
                    {signedCents(deposits.result - deposits.benchmarkResult, 0)} {currency}
                  </span>
                </>
              ))}
          </div>
          <div className="value-delta small">
            <span className="muted">Na wykresie od {formatDate(from)}:</span>
            {chartLine}
          </div>
        </>
      ) : (
        <>
          <div className="value-eyebrow">
            {title} · zwrot od {formatDate(from)}
          </div>
          <div className="value-amount">{portfolio === null ? '—' : formatReturnUnits(portfolio)}</div>
          <div className="value-delta">{benchmarkStatus ?? chartLine}</div>
        </>
      )}
      {(incomplete || exceeds || unquotedPercent !== null) && coverage !== null && (
        <div className={`compare-coverage small ${incomplete ? 'is-warning' : 'muted'}`}>
          {incomplete && (
            <>
              Wykres obejmuje {formatCents(coverage.captured, 0)} z {formatCents(coverage.result, 0)}{' '}
              {currency} wyniku inwestycji (ruchy cen i dywidendy od {formatDate(historyStart)}), więc zwrot w
              % jest niepełny.{' '}
            </>
          )}
          {exceeds && (
            <>
              Wykres liczy {formatCents(coverage.captured, 0)} {currency} z ruchów cen i dywidend od{' '}
              {formatDate(historyStart)}, a wynik inwestycji to {formatCents(coverage.result, 0)} {currency}.
              Wykres wycenia po cenach zamknięcia i nie odlicza prowizji, a wynik liczy po faktycznych cenach
              transakcji i po prowizjach, dlatego zwrot w % na wykresie jest wyższy.{' '}
            </>
          )}
          {unquotedPercent !== null && (
            <>
              W tym okresie {unquotedPercent}% wartości nie ma dziennych notowań — liczy się po stałej
              cenie albo po Twoich wycenach, więc zysk lub strata pojawia się tylko w dniu wyceny.
            </>
          )}
        </div>
      )}
    </>
  )
}

export default CompareReadout

import type { Benchmark, Valuation } from './api'
import { toCents } from './format'

// fin-ai-lab#273, the chart's comparison mode: returns as growth indexes
// (1 = the first day), rebased to the chart's range. A return is a ratio,
// not money, so plain numbers are fine here; the sums under it stay exact
// integer cents.

// Growth of the visible portfolios with deposits, purchases and sales left
// out: each day, (yesterday's holdings at today's prices + dividends
// credited today) / yesterday's value. The backend's own index
// (valuation.return_index) is used as-is while nothing is hidden; this
// mirrors it for any other set, from the portfolios' own series.
export function portfolioReturnIndex(valuation: Valuation, hidden: Set<string>): number[] {
  if (hidden.size === 0) return valuation.return_index.map(Number)
  const shown = valuation.portfolios.filter((p) => !hidden.has(p.id))
  const index = valuation.dates.map(() => 1)
  for (let day = 1; day < valuation.dates.length; day++) {
    let previous = 0
    let grown = 0
    for (const portfolio of shown) {
      previous += toCents(portfolio.values[day - 1])
      grown +=
        toCents(portfolio.prior_holdings_values[day]) +
        toCents(portfolio.dividends_by_day[valuation.dates[day]] ?? '0')
    }
    index[day] = previous > 0 ? (index[day - 1] * grown) / previous : index[day - 1]
  }
  return index
}

// The benchmark on the valuation's own days: null before its first price
// (and on a day its response does not cover), so the line starts where the
// data does instead of a flat stretch it never had.
export function alignBenchmark(benchmark: Benchmark, dates: string[]): (number | null)[] {
  const byDate = new Map(benchmark.dates.map((day, i) => [day, Number(benchmark.values[i])]))
  return dates.map((day) => (day >= benchmark.first_price_date ? (byDate.get(day) ?? null) : null))
}

export type SameDeposits = {
  netDeposits: number // integer cents
  value: number // integer cents: what the same deposits would be worth today
  // Some deposits came before the benchmark's (or the chart's) first price
  // and were put in at that first price instead of their own day's.
  boughtLate: boolean
}

// "The same deposits into the benchmark" (#273): every deposit of the
// visible portfolios buys the benchmark at that day's price, every
// withdrawal sells it; what the units are worth on the last day. The
// counterpart of the investment result -- money-weighted, each deposit
// counts with its amount, unlike the return index. null without any price.
export function sameDepositsInBenchmark(
  valuation: Valuation,
  hidden: Set<string>,
  benchmark: (number | null)[],
): SameDeposits | null {
  const first = benchmark.findIndex((value) => value !== null)
  if (first < 0) return null
  const shown = valuation.portfolios.filter((p) => !hidden.has(p.id))
  let netDeposits = 0
  let units = 0
  let boughtLate = false
  let price = benchmark[first] as number
  const early = shown.reduce((sum, p) => sum + toCents(p.deposits_before_start), 0)
  if (early !== 0) {
    units += early / price
    netDeposits += early
    boughtLate = true
  }
  valuation.dates.forEach((day, i) => {
    if (i >= first && benchmark[i] !== null) price = benchmark[i] as number
    const amount = shown.reduce((sum, p) => sum + toCents(p.deposits_by_day[day] ?? '0'), 0)
    if (amount === 0) return
    units += amount / price
    netDeposits += amount
    if (i < first) boughtLate = true
  })
  return { netDeposits, value: Math.round(units * price), boughtLate }
}

// Share of the visible portfolios' value held without daily quotes over the
// days from `from` on -- the part whose return the history cannot see.
export function unquotedShare(valuation: Valuation, hidden: Set<string>, from: number): number | null {
  let unquoted = 0
  let total = 0
  for (const portfolio of valuation.portfolios) {
    if (hidden.has(portfolio.id)) continue
    for (let day = from; day < valuation.dates.length; day++) {
      unquoted += toCents(portfolio.unquoted_values[day])
      total += toCents(portfolio.values[day])
    }
  }
  return total > 0 ? unquoted / total : null
}

// Return from day `from` to each day, in hundredths of a percent -- integer-
// like units, so the chart's axis steps work as they do for cents. The first
// day at or after `from` with a value is the base (0); days before it, and
// days without a value, are null.
export function rebasedReturn(index: (number | null)[], from: number): (number | null)[] {
  const baseAt = index.findIndex((value, i) => i >= from && value !== null)
  if (baseAt < 0) return index.map(() => null)
  const base = index[baseAt] as number
  return index.map((value, i) => (i < baseAt || value === null ? null : (value / base - 1) * 10000))
}

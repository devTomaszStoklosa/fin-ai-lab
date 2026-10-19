import type { NotCovered, PortfolioSeries } from './api'
import { formatCents, toCents } from './format'

// What the percentage is relative to: the money the owner put in (deposits
// minus withdrawals), or -- where an import has no deposit data -- the cost of
// all purchases, which also counts money reinvested from sales.
export type Basis = 'deposits' | 'purchases'

export type InvestmentSummary = {
  base: number // integer cents, the percentage's denominator
  basis: Basis
  result: number // integer cents
  dividends: number // integer cents, after withholding tax
  interest: number // integer cents
  other: number // integer cents, fees and corrections
  notCovered: NotCovered[]
}

const NOT_COVERED_ORDER: NotCovered[] = ['closed_positions', 'dividends']

export const NOT_COVERED_LABEL: Record<NotCovered, string> = {
  closed_positions: 'zamknięte pozycje',
  dividends: 'dywidendy',
}

export const BASIS_LABEL: Record<Basis, string> = {
  deposits: 'wpłaconych netto',
  purchases: 'kosztu zakupów',
}

// Sums the portfolios' own investment results (integer cents, exact). A
// portfolio that holds something but has no result (missing FX rate or
// quote) makes the whole sum unknown: leaving it out would quietly report
// a number for a smaller portfolio than the one shown. Net deposits are the
// base only when every portfolio in the sum states them (and they are
// positive): dividing a sum by the deposits of some of its parts would be
// wrong.
export function summarizeInvestment(portfolios: PortfolioSeries[]): InvestmentSummary | null {
  let purchases = 0
  let netDeposits = 0
  let allHaveDeposits = true
  let result = 0
  let dividends = 0
  let interest = 0
  let other = 0
  const missing = new Set<NotCovered>()
  let counted = 0
  for (const portfolio of portfolios) {
    const { investment } = portfolio
    if (investment === null) {
      if (portfolio.position_count > 0) return null
      continue
    }
    purchases += toCents(investment.invested)
    if (investment.net_deposits === null) allHaveDeposits = false
    else netDeposits += toCents(investment.net_deposits)
    result += toCents(investment.result)
    dividends += toCents(investment.dividends)
    interest += toCents(investment.interest)
    other += toCents(investment.other)
    investment.not_covered.forEach((item) => missing.add(item))
    counted += 1
  }
  const basis: Basis = allHaveDeposits && netDeposits > 0 ? 'deposits' : 'purchases'
  const base = basis === 'deposits' ? netDeposits : purchases
  if (counted === 0 || base <= 0) return null
  return {
    base,
    basis,
    result,
    dividends,
    interest,
    other,
    notCovered: NOT_COVERED_ORDER.filter((item) => missing.has(item)),
  }
}

// The lines of "W tym: ..." -- what the account earned on the side. Zero
// lines are left out; empty when there is nothing to show.
export function earningsBreakdown(summary: InvestmentSummary): string[] {
  const lines: [string, number][] = [
    ['dywidendy', summary.dividends],
    ['odsetki', summary.interest],
    ['opłaty i korekty', summary.other],
  ]
  return lines
    .filter(([, cents]) => cents !== 0)
    .map(([label, cents]) => `${label} ${cents < 0 ? '−' : '+'}${formatCents(Math.abs(cents))}`)
}

// Tenths of a percent, Polish decimal comma: 1234 / 10000 -> "12,3".
export function percentOfBase(summary: InvestmentSummary): string {
  const tenths = Math.round((Math.abs(summary.result) * 1000) / summary.base)
  return (tenths / 10).toFixed(1).replace('.', ',')
}

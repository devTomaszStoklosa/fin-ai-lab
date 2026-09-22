// Backend stores money/quantity as DECIMAL(24,8), so values always arrive
// padded to 8 decimal places (e.g. "6.00000000") -- that precision is
// intentional at the data layer, but shouldn't leak onto the screen.
export function trimTrailingZeros(value: string): string {
  if (!value.includes('.')) return value
  return value.replace(/\.?0+$/, '')
}

// Mirrors portfolio_webapp/aggregators.py's instrument_key exactly (REQ-065)
// -- used client-side only to look up display info (name, quantity) for a
// stored member_instrument_keys entry, never to compute a value.
export function instrumentKey(position: {
  broker: string
  isin: string | null
  symbol: string | null
  instrument_name: string
}): string {
  if (position.isin) return position.isin
  if (position.symbol) return `${position.broker}:${position.symbol}`
  return `${position.broker}:${position.instrument_name}`
}

// Polish plural forms: 1 -> one, 2-4 (except 12-14) -> few, else -> many.
export function pluralizePl(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one
  const lastDigit = n % 10
  const lastTwoDigits = n % 100
  if (lastDigit >= 2 && lastDigit <= 4 && !(lastTwoDigits >= 12 && lastTwoDigits <= 14)) return few
  return many
}

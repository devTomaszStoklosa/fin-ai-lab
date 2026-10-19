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

// Money arrives as a decimal string ("51425.37") -- parsed into integer
// grosze (hundredths) by string surgery, never through a float, so a sum
// of visible portfolios (the chart's legend toggles) stays exact.
export function toCents(value: string): number {
  const negative = value.startsWith('-')
  const [whole, fraction = ''] = value.replace('-', '').split('.')
  const cents = Number(whole) * 100 + Number((fraction + '00').slice(0, 2))
  return negative ? -cents : cents
}

// Polish grouping ("51 425,37"): non-breaking space thousands, comma decimals.
export function formatCents(cents: number, fractionDigits: 0 | 2 = 2): string {
  const negative = cents < 0
  const absolute = Math.abs(cents)
  const whole = fractionDigits === 0 ? Math.round(absolute / 100) : Math.floor(absolute / 100)
  const grouped = String(whole).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  const fraction = fractionDigits === 2 ? `,${String(absolute % 100).padStart(2, '0')}` : ''
  return `${negative ? '−' : ''}${grouped}${fraction}`
}

export function formatMoney(value: string, fractionDigits: 0 | 2 = 2): string {
  return formatCents(toCents(value), fractionDigits)
}

// A price or quantity: Polish decimal comma, grouped, trailing zeros trimmed.
export function formatDecimal(value: string): string {
  const trimmed = trimTrailingZeros(value)
  const negative = trimmed.startsWith('-')
  const [whole, fraction] = trimmed.replace('-', '').split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  return `${negative ? '−' : ''}${grouped}${fraction ? `,${fraction}` : ''}`
}

export function formatPercent(value: string): string {
  const negative = value.startsWith('-')
  const body = value.replace('-', '').replace('.', ',')
  return `${negative ? '−' : '+'}${body}%`
}

// A computed return (#273) in hundredths of a percent -> "+12,3%" or, with
// unit ' pp', a difference in percentage points. Always signed; a value that
// rounds to zero shows no sign.
export function formatReturnUnits(units: number, fractionDigits = 1, unit = '%'): string {
  const rounded = Number((Math.abs(units) / 100).toFixed(fractionDigits))
  const body = new Intl.NumberFormat('pl-PL', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(rounded)
  const sign = rounded === 0 ? '' : units < 0 ? '−' : '+'
  return `${sign}${body}${unit}`
}

const DATE_LONG = new Intl.DateTimeFormat('pl-PL', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

// ISO date ("2026-09-29") -> "29 wrz 2026", read as UTC so it never shifts a day.
export function formatDate(isoDate: string): string {
  return DATE_LONG.format(new Date(`${isoDate}T00:00:00Z`))
}

// A per-unit price for display: two decimals, four below 10 (penny stocks,
// FX-like quotes) -- presentation rounding only, the backend keeps full
// precision and every sum is done there or in integer cents.
export function formatPrice(value: string): string {
  const number = Number(value)
  return new Intl.NumberFormat('pl-PL', {
    minimumFractionDigits: 2,
    maximumFractionDigits: Math.abs(number) < 10 ? 4 : 2,
  }).format(number)
}

// Exact sum of decimal strings ("1.5", "2.00000000") -- scaled to BigInt,
// never through a float, for a quantity summed over some of an asset's
// positions (the others' portfolios hidden).
export function sumDecimals(values: string[]): string {
  const scale = Math.max(0, ...values.map((v) => (v.split('.')[1] ?? '').length))
  const total = values.reduce((sum, value) => {
    const negative = value.startsWith('-')
    const [whole, fraction = ''] = value.replace('-', '').split('.')
    const scaled = BigInt(whole + fraction.padEnd(scale, '0'))
    return sum + (negative ? -scaled : scaled)
  }, 0n)
  const negative = total < 0n
  const digits = (negative ? -total : total).toString().padStart(scale + 1, '0')
  const body = scale === 0 ? digits : `${digits.slice(0, -scale)}.${digits.slice(-scale)}`
  return negative ? `-${body}` : body
}

// A non-negative decimal string as typed in a form ("9000", "10500.5").
const PLAIN_DECIMAL = /^\d+(\.\d+)?$/

// Exact a x b in integer grosze, rounded half up like the backend -- for a
// value previewed in a form before it is saved (#288). null when either
// side isn't a plain non-negative decimal.
export function multiplyToCents(a: string, b: string): number | null {
  if (!PLAIN_DECIMAL.test(a) || !PLAIN_DECIMAL.test(b)) return null
  const [aWhole, aFraction = ''] = a.split('.')
  const [bWhole, bFraction = ''] = b.split('.')
  const product = BigInt(aWhole + aFraction) * BigInt(bWhole + bFraction)
  const scale = aFraction.length + bFraction.length
  if (scale <= 2) return Number(product * 10n ** BigInt(2 - scale))
  const divisor = 10n ** BigInt(scale - 2)
  const cents = product / divisor + (2n * (product % divisor) >= divisor ? 1n : 0n)
  return Number(cents)
}

// Today on the owner's own calendar ("2026-10-18"), not UTC's.
export function localToday(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

export function brokerLabel(broker: string): string {
  if (broker === 'manual') return 'ręczna'
  if (broker === 'xtb') return 'XTB'
  return broker.charAt(0).toUpperCase() + broker.slice(1)
}

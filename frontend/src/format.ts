// Backend stores money/quantity as DECIMAL(24,8), so values always arrive
// padded to 8 decimal places (e.g. "6.00000000") -- that precision is
// intentional at the data layer, but shouldn't leak onto the screen.
export function trimTrailingZeros(value: string): string {
  if (!value.includes('.')) return value
  return value.replace(/\.?0+$/, '')
}

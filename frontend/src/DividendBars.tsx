import { useEffect, useId, useRef, useState } from 'react'
import { formatCents } from './format'

export type Bar = {
  id: string
  label: string // under the bar ("2025", "sty")
  title: string // in the tooltip ("2025", "styczeń 2026")
  cents: number
  // An estimate, not a payment: hatched instead of solid, so the difference
  // never rests on colour alone (dataviz texture fill).
  estimate?: boolean
}

const HEIGHT = 220
const MARGIN = { top: 16, right: 8, bottom: 28, left: 64 }
const MAX_BAR_WIDTH = 48
const GAP = 2 // surface gap between neighbouring bars (dataviz)
const RADIUS = 4 // rounded data end, square at the baseline
const MIN_LABEL_SLOT = 32 // px per bar below which labels would touch

// 1/2/2.5/5 x 10^n -- axis ticks at clean numbers, same steps as ValueChart.
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

// A bar from the baseline up to `top`, rounded only at its data end.
function barPath(x: number, width: number, base: number, top: number): string {
  const r = Math.min(RADIUS, width / 2, Math.abs(base - top))
  if (top >= base) return `M${x},${base}H${x + width}V${top}H${x}Z` // negative: plain
  return `M${x},${base}V${top + r}Q${x},${top} ${x + r},${top}H${x + width - r}Q${x + width},${top} ${x + width},${top + r}V${base}Z`
}

type Props = {
  bars: Bar[]
  currency: string
  ariaLabel: string
}

// One series, so no legend: the card's own heading names it. Every value
// is also in the table under the chart.
function DividendBars({ bars, currency, ariaLabel }: Props) {
  const [plotRef, width] = useElementWidth<HTMLDivElement>(640)
  const [active, setActive] = useState<string | null>(null)
  // useId's colons would need escaping inside url(#...).
  const hatchId = `dividend-hatch-${useId().replace(/:/g, '')}`

  const values = bars.map((bar) => bar.cents)
  const max = Math.max(0, ...values)
  const min = Math.min(0, ...values)
  const step = niceStep((max - min) / 4 || 100)
  const top = Math.ceil(max / step) * step || step
  const bottom = Math.floor(min / step) * step
  const ticks: number[] = []
  for (let tick = bottom; tick <= top; tick += step) ticks.push(tick)

  const plotWidth = Math.max(width - MARGIN.left - MARGIN.right, 1)
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom
  const y = (cents: number) => MARGIN.top + ((top - cents) / (top - bottom)) * plotHeight
  const slot = plotWidth / Math.max(bars.length, 1)
  const barWidth = Math.max(Math.min(slot - GAP, MAX_BAR_WIDTH), 2)
  // Twelve month labels don't fit a phone: every other one then; the
  // tooltip still names each bar.
  const labelEvery = slot < MIN_LABEL_SLOT ? 2 : 1
  const x = (index: number) => MARGIN.left + index * slot + (slot - barWidth) / 2

  const activeIndex = bars.findIndex((bar) => bar.id === active)
  const activeBar = activeIndex >= 0 ? bars[activeIndex] : null

  return (
    <div className="value-plot dividend-plot" ref={plotRef}>
      <svg width={width} height={HEIGHT} role="img" aria-label={ariaLabel}>
        <defs>
          <pattern id={hatchId} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect className="dividend-hatch-bg" width="6" height="6" />
            <line className="dividend-hatch-line" x1="0" y1="0" x2="0" y2="6" />
          </pattern>
        </defs>
        {ticks.map((tick) => (
          <g key={tick}>
            <line className="grid" x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} />
            <text className="axis" x={MARGIN.left - 8} y={y(tick) + 4} textAnchor="end">
              {tick === 0 ? '0' : formatCents(tick, 0)}
            </text>
          </g>
        ))}
        {bars.map((bar, index) => (
          <g key={bar.id}>
            <path
              className={`dividend-bar ${bar.estimate ? 'is-estimate' : ''} ${active === bar.id ? 'is-active' : ''}`}
              style={bar.estimate ? { fill: `url(#${hatchId})` } : undefined}
              d={barPath(x(index), barWidth, y(0), y(bar.cents))}
            />
            {/* Hit target: the whole column, not just the (maybe tiny) bar. */}
            <rect
              className="dividend-hit"
              x={MARGIN.left + index * slot}
              y={MARGIN.top}
              width={slot}
              height={plotHeight}
              onPointerEnter={() => setActive(bar.id)}
              onPointerLeave={() => setActive(null)}
            />
            {index % labelEvery === 0 && (
              <text className="axis" x={x(index) + barWidth / 2} y={HEIGHT - 8} textAnchor="middle">
                {bar.label}
              </text>
            )}
          </g>
        ))}
      </svg>
      {activeBar && (
        <div
          className="dividend-tooltip"
          style={{
            left: Math.min(Math.max(x(activeIndex) + barWidth / 2, 70), width - 70),
            top: Math.max(y(Math.max(activeBar.cents, 0)) - 8, 0),
          }}
        >
          <div className="muted small">{activeBar.title}</div>
          <div className="mono strong">
            {formatCents(activeBar.cents)} {currency}
          </div>
        </div>
      )}
    </div>
  )
}

export default DividendBars

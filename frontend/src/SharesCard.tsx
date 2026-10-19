import { useEffect, useState } from 'react'
import { BUILTIN_BREAKDOWNS, DEFAULT_BUILTIN_BREAKDOWN, fetchBreakdowns, fetchShares } from './api'
import type { Breakdown, ShareNode, Shares } from './api'
import { formatCents, formatDate, pluralizePl, toCents } from './format'
import { seriesColor } from './seriesColors'

// Two greys that differ in lightness, not just in name: "Bez grupy" (the
// owner still has to sort these) and "Pozostałe" (small slices folded).
const UNGROUPED_COLOR = '#8a8478'
const OTHERS_COLOR = '#c9c2b4'
// Part-to-whole reads at a glance only up to about six slices (dataviz).
const MAX_SLICES = 6

type Item = {
  id: string
  name: string
  kind: ShareNode['kind'] | 'others'
  cents: number
  color: string
  // The backend's own share of the parent (REQ-084); null for "Pozostałe",
  // which exists only on screen.
  shareOfParent: string | null
  shareOfTotal: string | null
  assetCount: number
  symbol: string | null
  portfolioName: string | null
  children: ShareNode[]
}

type Level = { id: string; name: string; cents: number; children: ShareNode[]; synthetic: boolean }

// Colour by position in the backend's definition order (groups as the owner
// ordered them, then assets by name), never by size -- a slice keeps its
// colour when values move.
function levelItems(level: Level): Item[] {
  const items = level.children
    .map(
      (node, index): Item => ({
        id: node.id,
        name: node.name,
        kind: node.kind,
        cents: toCents(node.value),
        color: node.kind === 'ungrouped' ? UNGROUPED_COLOR : seriesColor(index),
        shareOfParent: level.synthetic ? null : node.share_of_parent,
        shareOfTotal: node.share_of_total,
        assetCount: node.asset_count,
        symbol: node.symbol,
        portfolioName: node.portfolio_name,
        children: node.children,
      }),
    )
    .filter((item) => item.cents > 0)
    .sort((a, b) => b.cents - a.cents)
  if (items.length <= MAX_SLICES) return items

  const kept = items.slice(0, MAX_SLICES - 1)
  const rest = items.slice(MAX_SLICES - 1)
  const restNodes = level.children.filter((node) => rest.some((item) => item.id === node.id))
  return [
    ...kept,
    {
      id: `others:${level.id}`,
      name: `Pozostałe (${rest.length})`,
      kind: 'others',
      cents: rest.reduce((sum, item) => sum + item.cents, 0),
      color: OTHERS_COLOR,
      shareOfParent: null,
      shareOfTotal: null,
      assetCount: rest.reduce((sum, item) => sum + item.assetCount, 0),
      symbol: null,
      portfolioName: null,
      children: restNodes,
    },
  ]
}

// Display-only percentage for what exists only on screen ("Pozostałe", or
// a level inside it) -- from integer cents, one decimal like the backend's.
function percentOf(cents: number, whole: number): string {
  if (whole <= 0) return '0,0'
  return ((cents / whole) * 100).toFixed(1).replace('.', ',')
}

function formatShare(backend: string | null, cents: number, whole: number): string {
  return `${backend !== null ? backend.replace('.', ',') : percentOf(cents, whole)}%`
}

// Annular sector from angle a0 to a1 (radians, clockwise from 12 o'clock).
function sector(a0: number, a1: number, outer: number, inner: number, c = 150): string {
  if (a1 - a0 >= Math.PI * 2 - 1e-6) {
    const middle = a0 + Math.PI
    return `${sector(a0, middle, outer, inner, c)} ${sector(middle, a1, outer, inner, c)}`
  }
  const point = (r: number, a: number) =>
    `${(c + r * Math.cos(a)).toFixed(2)},${(c + r * Math.sin(a)).toFixed(2)}`
  const large = a1 - a0 > Math.PI ? 1 : 0
  return (
    `M${point(outer, a0)}A${outer},${outer} 0 ${large} 1 ${point(outer, a1)}` +
    `L${point(inner, a1)}A${inner},${inner} 0 ${large} 0 ${point(inner, a0)}Z`
  )
}

function assetKeys(node: ShareNode): string[] {
  if (node.kind === 'asset') return [node.id]
  return node.children.flatMap(assetKeys)
}

function assetsLabel(count: number): string {
  return `${count} ${pluralizePl(count, 'aktywo', 'aktywa', 'aktywów')}`
}

type Props = {
  // One portfolio, or every portfolio when left out.
  portfolioId?: string
  // Bumped by the parent whenever values may have changed (refresh, import).
  reloadToken: number
  onManage: (breakdownId: string | null) => void
}

function SharesCard({ portfolioId, reloadToken, onManage }: Props) {
  const [breakdowns, setBreakdowns] = useState<Breakdown[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [shares, setShares] = useState<Shares | null>(null)
  const [path, setPath] = useState<string[]>([])
  const [hover, setHover] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  function loadBreakdowns() {
    fetchBreakdowns()
      .then(setBreakdowns)
      .catch((e: Error) => setError(e.message))
  }
  useEffect(loadBreakdowns, [reloadToken])

  const builtIns = BUILTIN_BREAKDOWNS.filter((b) => !portfolioId || b.id !== 'builtin:portfolio')
  const known = [...builtIns.map((b) => b.id as string), ...(breakdowns ?? []).map((b) => b.id)]
  const fallback = breakdowns?.find((b) => b.is_default)?.id ?? DEFAULT_BUILTIN_BREAKDOWN
  const active = selected !== null && known.includes(selected) ? selected : fallback

  function loadShares() {
    if (breakdowns === null) return
    fetchShares(active, portfolioId)
      .then((result) => {
        setShares(result)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }
  // Not keyed on reloadToken itself: a reload refetches the breakdowns,
  // and that new list triggers this once.
  useEffect(loadShares, [active, portfolioId, breakdowns])

  function choose(breakdownId: string) {
    setSelected(breakdownId)
    setPath([])
    setHover(null)
  }

  const custom = breakdowns ?? []
  const activeCustom = custom.find((b) => b.id === active) ?? null
  const activeName =
    activeCustom?.name ?? builtIns.find((b) => b.id === active)?.name ?? shares?.breakdown_name ?? ''
  // Every breakdown's tree holds every valued asset of the scope, so the
  // loaded one tells which instrument keys any breakdown has to cover.
  const heldKeys = shares ? assetKeys(shares.root) : []
  const ungroupedIn = (b: Breakdown) => heldKeys.some((key) => !(key in b.assignments))

  const header = (
    <>
      <div className="shares-head">
        <div>
          <div className="value-eyebrow">Udziały w portfelu</div>
          <h2>Podział: {activeName}</h2>
        </div>
        <div className="shares-actions">
          {activeCustom && (
            <button type="button" className="btn-small" onClick={() => onManage(activeCustom.id)}>
              Edytuj „{activeCustom.name}”
            </button>
          )}
          <button type="button" className="nav-link" onClick={() => onManage(null)}>
            Zarządzaj podziałami
          </button>
        </div>
      </div>

      <div className="breakdown-pickers">
        <div className="breakdown-picker-row">
          <span className="muted small picker-label">Wbudowane</span>
          <div className="segmented" role="group" aria-label="Podziały wbudowane">
            {builtIns.map((b) => (
              <button key={b.id} type="button" aria-pressed={active === b.id} onClick={() => choose(b.id)}>
                {b.name}
              </button>
            ))}
          </div>
        </div>
        <div className="breakdown-picker-row">
          <span className="muted small picker-label">Twoje</span>
          {custom.length > 0 && (
            <div className="segmented" role="group" aria-label="Twoje podziały">
              {custom.map((b) => (
                <button key={b.id} type="button" aria-pressed={active === b.id} onClick={() => choose(b.id)}>
                  {b.name}
                  {ungroupedIn(b) && (
                    <span className="ungrouped-dot" title="Są aktywa bez grupy" aria-label="są aktywa bez grupy" />
                  )}
                </button>
              ))}
            </div>
          )}
          <button type="button" className="nav-link" onClick={() => onManage(null)}>
            + Nowy podział
          </button>
        </div>
      </div>
    </>
  )

  if (shares === null) {
    return (
      <section className="value-card shares-card">
        {header}
        <p className={error ? 'error' : 'muted'}>{error ?? 'Liczę udziały…'}</p>
      </section>
    )
  }

  // Walk the drill-down path; a stale step (breakdown or data changed)
  // simply stops the walk at the last level that still exists.
  const rootCents = toCents(shares.root.value)
  const trail: Level[] = [
    { id: 'root', name: shares.root.name, cents: rootCents, children: shares.root.children, synthetic: false },
  ]
  for (const id of path) {
    const current = trail[trail.length - 1]
    const next = levelItems(current).find((item) => item.id === id && item.children.length > 0)
    if (!next) break
    trail.push({
      id: next.id,
      name: next.name,
      cents: next.cents,
      children: next.children,
      synthetic: next.kind === 'others',
    })
  }
  const level = trail[trail.length - 1]
  const items = levelItems(level)
  const atRoot = trail.length === 1
  const hovered = items.find((item) => item.id === hover) ?? null
  const useBar = items.length <= 2

  function drill(item: Item) {
    if (item.children.length === 0) return
    setPath([...trail.slice(1).map((t) => t.id), item.id])
    setHover(null)
  }

  // Clockwise from 12 o'clock, largest first.
  const turn = (cents: number) => (level.cents > 0 ? (cents / level.cents) * Math.PI * 2 : 0)
  const slices = items.map((item, index) => {
    const start = -Math.PI / 2 + turn(items.slice(0, index).reduce((sum, x) => sum + x.cents, 0))
    const d = sector(start, start + turn(item.cents), hover === item.id ? 139 : 132, 84)
    return { item, d }
  })

  const focusName = hovered ? hovered.name : level.name
  const focusCents = hovered ? hovered.cents : level.cents
  const focusShare = hovered
    ? atRoot
      ? `${formatShare(hovered.shareOfTotal, hovered.cents, rootCents)} portfela`
      : `${formatShare(hovered.shareOfParent, hovered.cents, level.cents)} grupy · ${formatShare(hovered.shareOfTotal, hovered.cents, rootCents)} portfela`
    : atRoot
      ? '100%'
      : `${percentOf(level.cents, rootCents)}% portfela`

  return (
    <section className="value-card shares-card">
      {header}

      <nav className="shares-crumbs" aria-label="Poziom grupy">
        {trail.map((t, i) => (
          <span key={t.id} className="crumb">
            {i > 0 && <span aria-hidden="true" className="crumb-sep">›</span>}
            {i < trail.length - 1 ? (
              <button type="button" onClick={() => setPath(trail.slice(1, i + 1).map((x) => x.id))}>
                {t.name}
              </button>
            ) : (
              <span aria-current="page">{t.name}</span>
            )}
          </span>
        ))}
      </nav>

      {items.length === 0 ? (
        <p className="muted">Brak wycenionych pozycji w tym zakresie.</p>
      ) : (
        <div className="shares-body">
          <div className="shares-chart">
            {useBar ? (
              <div className="shares-bar-block" role="img" aria-label={items.map((i) => `${i.name} ${percentOf(i.cents, level.cents)}%`).join(', ')}>
                <div className="muted small">{focusName}</div>
                <div className="value-amount shares-bar-amount">
                  {formatCents(focusCents, 0)} {shares.base_currency}
                </div>
                <div className="muted small">{focusShare}</div>
                <div className="shares-bar">
                  {items.map((item) => (
                    <div
                      key={item.id}
                      style={{ width: `${(item.cents / level.cents) * 100}%`, background: item.color }}
                      onPointerEnter={() => setHover(item.id)}
                      onPointerLeave={() => setHover(null)}
                    />
                  ))}
                </div>
                <p className="muted small">Przy 1–2 elementach pasek zamiast koła: dwa wycinki koła trudno porównać na oko.</p>
              </div>
            ) : (
              <>
                <svg
                  viewBox="0 0 300 300"
                  width="300"
                  height="300"
                  role="img"
                  aria-label={items.map((i) => `${i.name} ${percentOf(i.cents, level.cents)}%`).join(', ')}
                >
                  {slices.map(({ item, d }) => (
                    <path
                      key={item.id}
                      d={d}
                      fill={item.color}
                      className={`share-slice ${item.children.length > 0 ? 'drillable' : ''}`}
                      onPointerEnter={() => setHover(item.id)}
                      onPointerLeave={() => setHover(null)}
                      onClick={() => drill(item)}
                    />
                  ))}
                </svg>
                <div className="shares-center">
                  <div className="muted small shares-center-name">{focusName}</div>
                  <div className="shares-center-value">{formatCents(focusCents, 0)}</div>
                  <div className="muted small">
                    {shares.base_currency} · {focusShare}
                  </div>
                </div>
              </>
            )}
          </div>

          <div className="shares-table">
            <div className="shares-row shares-row-head" aria-hidden="true">
              <span />
              <span>{items.some((i) => i.kind !== 'asset') ? 'Grupa / aktywo' : 'Aktywo'}</span>
              <span className="num">Wartość</span>
              <span className="num">{atRoot ? 'Udział' : 'Udział w grupie'}</span>
              <span className="num">Portfela</span>
              <span />
            </div>
            {items.map((item) => {
              const drillable = item.children.length > 0
              const sub =
                item.kind === 'asset'
                  ? [item.symbol, item.portfolioName].filter(Boolean).join(' · ')
                  : `${item.kind === 'ungrouped' ? 'nieprzypisane' : item.kind === 'others' ? 'najmniejsze pozycje' : 'grupa'} · ${assetsLabel(item.assetCount)}`
              const ofParent = formatShare(item.shareOfParent, item.cents, level.cents)
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`shares-row ${hover === item.id ? 'is-hover' : ''} ${drillable ? 'drillable' : ''}`}
                  onClick={() => drill(item)}
                  onPointerEnter={() => setHover(item.id)}
                  onPointerLeave={() => setHover(null)}
                  onFocus={() => setHover(item.id)}
                  onBlur={() => setHover(null)}
                  aria-label={`${item.name}, ${formatCents(item.cents, 0)} ${shares.base_currency}, ${ofParent}${drillable ? ', pokaż skład' : ''}`}
                >
                  <span className="legend-swatch" style={{ background: item.color }} />
                  <span className="shares-name">
                    <span className="strong">{item.name}</span>
                    <span className="muted small">{sub}</span>
                  </span>
                  <span className="num mono">{formatCents(item.cents, 0)} {shares.base_currency}</span>
                  <span className="num share-cell">
                    <span className="share-track-mini">
                      <span style={{ width: `${(item.cents / level.cents) * 100}%`, background: item.color }} />
                    </span>
                    <span className="mono strong">{ofParent}</span>
                  </span>
                  <span className="num mono muted">{formatShare(item.shareOfTotal, item.cents, rootCents)}</span>
                  <span aria-hidden="true" className="muted chevron">{drillable ? '›' : ''}</span>
                </button>
              )
            })}
            <div className="shares-row shares-row-total">
              <span />
              <span>Razem</span>
              <span className="num mono">{formatCents(level.cents, 0)} {shares.base_currency}</span>
              <span className="num mono">100%</span>
              <span className="num mono muted">{percentOf(level.cents, rootCents)}%</span>
              <span />
            </div>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <div className="value-footnotes muted small">
        <p>
          Kliknij grupę na kole albo w tabeli, żeby zobaczyć udziały w jej wnętrzu. Ponad sześć pozycji:
          najmniejsze łączą się w „Pozostałe”.
        </p>
        <p>
          Każdy podział jest niezależny — to samo aktywo może być w innej grupie w każdym z nich. Udziały z
          bieżącej wyceny
          {shares.prices_as_of ? ` (kursy z ${formatDate(shares.prices_as_of)})` : ''}, w{' '}
          {shares.base_currency}. Opis struktury, nie rekomendacja inwestycyjna.
        </p>
      </div>
    </section>
  )
}

export default SharesCard

import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  createBreakdown,
  createBreakdownGroup,
  deleteBreakdown,
  deleteBreakdownGroup,
  duplicateBreakdown,
  fetchBreakdowns,
  fetchShares,
  setBreakdownAssignment,
  updateBreakdown,
  updateBreakdownGroup,
} from './api'
import type { Breakdown, BreakdownGroup, ShareNode, Shares } from './api'
import { formatMoney, pluralizePl } from './format'
import { seriesColor } from './seriesColors'

const UNGROUPED_COLOR = '#8a8478'

type Props = {
  initialId: string | null
  onBack: () => void
}

// Groups in tree order (parent before its children), each with its depth --
// for indented <select> options.
function flattenGroups(groups: BreakdownGroup[]): { group: BreakdownGroup; depth: number }[] {
  const out: { group: BreakdownGroup; depth: number }[] = []
  const walk = (parentId: string | null, depth: number) => {
    groups
      .filter((g) => g.parent_id === parentId)
      .sort((a, b) => a.position - b.position)
      .forEach((group) => {
        out.push({ group, depth })
        walk(group.id, depth + 1)
      })
  }
  walk(null, 0)
  return out
}

function descendantIds(groupId: string, groups: BreakdownGroup[]): Set<string> {
  const ids = new Set<string>([groupId])
  let grew = true
  while (grew) {
    grew = false
    for (const group of groups) {
      if (group.parent_id !== null && ids.has(group.parent_id) && !ids.has(group.id)) {
        ids.add(group.id)
        grew = true
      }
    }
  }
  return ids
}

function indent(depth: number): string {
  return `${'  '.repeat(depth)}${depth > 0 ? '↳ ' : ''}`
}

function BreakdownsEditor({ initialId, onBack }: Props) {
  const [breakdowns, setBreakdowns] = useState<Breakdown[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(initialId)
  const [shares, setShares] = useState<Shares | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [newGroupName, setNewGroupName] = useState('')
  const [subgroupFor, setSubgroupFor] = useState<string | null>(null)
  const [subgroupName, setSubgroupName] = useState('')
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null)

  function reloadBreakdowns() {
    fetchBreakdowns()
      .then(setBreakdowns)
      .catch((e: Error) => setError(e.message))
  }
  useEffect(reloadBreakdowns, [])

  const selected =
    breakdowns?.find((b) => b.id === selectedId) ?? (breakdowns && breakdowns.length > 0 ? breakdowns[0] : null)

  // `selected` is the very object held in state, so it changes identity
  // exactly when the breakdown changed -- then the tree (values, "Bez
  // grupy") is refetched to follow the new groups and assignments.
  useEffect(() => {
    if (!selected) return
    fetchShares(selected.id)
      .then(setShares)
      .catch((e: Error) => setError(e.message))
  }, [selected])

  // Every change returns the whole breakdown -- swap it in, the tree follows.
  function apply(change: Promise<Breakdown>) {
    change
      .then((updated) => {
        setError(null)
        setBreakdowns((list) => (list ?? []).map((b) => (b.id === updated.id ? updated : b)))
      })
      .catch((e: Error) => setError(e.message))
  }

  function handleCreate() {
    createBreakdown('Nowy podział')
      .then((created) => {
        setBreakdowns((list) => [...(list ?? []), created])
        setSelectedId(created.id)
      })
      .catch((e: Error) => setError(e.message))
  }

  function handleDuplicate() {
    if (!selected) return
    duplicateBreakdown(selected.id)
      .then((copy) => {
        setBreakdowns((list) => [...(list ?? []), copy])
        setSelectedId(copy.id)
      })
      .catch((e: Error) => setError(e.message))
  }

  function handleDelete() {
    if (!selected) return
    if (!window.confirm(`Usunąć podział „${selected.name}” razem z jego grupami?`)) return
    deleteBreakdown(selected.id)
      .then(() => {
        setSelectedId(null)
        setShares(null)
        reloadBreakdowns()
      })
      .catch((e: Error) => setError(e.message))
  }

  function saveName(draft: string) {
    const name = draft.trim()
    if (!selected || !name || name === selected.name) return
    apply(updateBreakdown(selected.id, { name, is_default: selected.is_default }))
  }

  function toggleDefault(isDefault: boolean) {
    if (!selected) return
    // The server clears the flag on every other breakdown -- reload them all.
    updateBreakdown(selected.id, { name: selected.name, is_default: isDefault })
      .then(reloadBreakdowns)
      .catch((e: Error) => setError(e.message))
  }

  function addGroup(event: FormEvent, parentId: string | null, name: string, reset: () => void) {
    event.preventDefault()
    if (!selected || !name.trim()) return
    apply(createBreakdownGroup(selected.id, { name: name.trim(), parent_id: parentId }))
    reset()
  }

  function removeGroup(group: BreakdownGroup) {
    if (!selected) return
    const where = group.parent_id ? 'do grupy nadrzędnej' : 'do „Bez grupy”'
    if (!window.confirm(`Usunąć grupę „${group.name}”? Jej podgrupy i aktywa przejdą ${where}.`)) return
    apply(deleteBreakdownGroup(selected.id, group.id))
  }

  if (breakdowns === null) {
    return (
      <div className="content content-wide">
        <p className="muted">{error ?? 'Wczytywanie…'}</p>
      </div>
    )
  }

  const groups = selected?.groups ?? []
  const flat = flattenGroups(groups)
  const groupById = new Map(groups.map((g) => [g.id, g]))
  const others = breakdowns.filter((b) => b.id !== selected?.id)
  const groupNameIn = (b: Breakdown, key: string) =>
    b.groups.find((g) => g.id === b.assignments[key])?.name ?? 'bez grupy'
  const ungroupedNode = shares?.root.children.find((c) => c.kind === 'ungrouped') ?? null
  const topLevel = (shares?.root.children ?? []).filter((c) => Number(c.value) > 0)
  const heldCount = (node: ShareNode | null) => node?.asset_count ?? 0

  function assetSelect(key: string, current: string | null) {
    return (
      <select
        value={current ?? ''}
        onChange={(e) => selected && apply(setBreakdownAssignment(selected.id, key, e.target.value || null))}
      >
        <option value="">— bez grupy —</option>
        {flat.map(({ group, depth }) => (
          <option key={group.id} value={group.id}>
            {indent(depth)}
            {group.name}
          </option>
        ))}
      </select>
    )
  }

  function renderNode(node: ShareNode, depth: number, parentGroupId: string | null) {
    if (node.kind === 'asset') {
      const elsewhere = others.map((b) => `${b.name}: ${groupNameIn(b, node.id)}`).join(' · ')
      return (
        <div key={node.id} className="tree-row tree-asset" style={{ paddingLeft: depth * 28 }}>
          <span className="tree-asset-name">
            <span className="strong">{node.name}</span>
            <span className="muted small">
              {[node.symbol, `${node.share_of_total.replace('.', ',')}% portfela`, elsewhere].filter(Boolean).join(' · ')}
            </span>
          </span>
          <span className="mono">{formatMoney(node.value, 0)}</span>
          <label className="tree-select muted small">
            Grupa
            {assetSelect(node.id, parentGroupId)}
          </label>
        </div>
      )
    }
    if (node.kind !== 'group') return null
    const group = groupById.get(node.id)
    if (!group) return null
    const blocked = descendantIds(group.id, groups)
    return (
      <div key={node.id} className="tree-group">
        <div className="tree-row" style={{ paddingLeft: depth * 28 }}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="muted">
            <path
              d="M2 4.5A1.5 1.5 0 0 1 3.5 3h3l1.5 1.5h4.5A1.5 1.5 0 0 1 14 6v5.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 11.5z"
              stroke="currentColor"
              strokeWidth="1.3"
            />
          </svg>
          {renaming?.id === group.id ? (
            <form
              className="inline-form"
              onSubmit={(e) => {
                e.preventDefault()
                if (selected && renaming.name.trim()) {
                  apply(
                    updateBreakdownGroup(selected.id, group.id, {
                      name: renaming.name.trim(),
                      parent_id: group.parent_id,
                    }),
                  )
                }
                setRenaming(null)
              }}
            >
              <input
                aria-label="Nowa nazwa grupy"
                value={renaming.name}
                onChange={(e) => setRenaming({ id: group.id, name: e.target.value })}
                autoFocus
              />
              <button type="submit" className="btn-small">
                Zapisz
              </button>
            </form>
          ) : (
            <span className="tree-group-name">{group.name}</span>
          )}
          <span className="mono">{formatMoney(node.value, 0)}</span>
          <span className="mono muted tree-pct">{node.share_of_total.replace('.', ',')}%</span>
          <div className="tree-actions">
            <button type="button" className="btn-small" onClick={() => setSubgroupFor(group.id)}>
              + podgrupa
            </button>
            <button type="button" className="btn-small" onClick={() => setRenaming({ id: group.id, name: group.name })}>
              Zmień nazwę
            </button>
            <label className="tree-select muted small">
              W grupie
              <select
                value={group.parent_id ?? ''}
                onChange={(e) =>
                  selected &&
                  apply(
                    updateBreakdownGroup(selected.id, group.id, {
                      name: group.name,
                      parent_id: e.target.value || null,
                    }),
                  )
                }
              >
                <option value="">— najwyższy poziom —</option>
                {flat
                  .filter(({ group: g }) => !blocked.has(g.id))
                  .map(({ group: g, depth: d }) => (
                    <option key={g.id} value={g.id}>
                      {indent(d)}
                      {g.name}
                    </option>
                  ))}
              </select>
            </label>
            <button type="button" className="btn-small btn-danger" onClick={() => removeGroup(group)}>
              Usuń
            </button>
          </div>
        </div>
        {subgroupFor === group.id && (
          <form
            className="inline-form tree-row"
            style={{ paddingLeft: (depth + 1) * 28 }}
            onSubmit={(e) =>
              addGroup(e, group.id, subgroupName, () => {
                setSubgroupFor(null)
                setSubgroupName('')
              })
            }
          >
            <input
              aria-label={`Nazwa podgrupy w „${group.name}”`}
              placeholder="Nazwa podgrupy"
              value={subgroupName}
              onChange={(e) => setSubgroupName(e.target.value)}
              autoFocus
            />
            <button type="submit" className="btn-small">
              Dodaj
            </button>
            <button type="button" className="btn-small" onClick={() => setSubgroupFor(null)}>
              Anuluj
            </button>
          </form>
        )}
        {node.children.map((child) => renderNode(child, depth + 1, group.id))}
      </div>
    )
  }

  return (
    <div className="content content-wide">
      <button type="button" className="back-link" onClick={onBack}>
        ← wróć
      </button>
      <header className="overview-header">
        <h1>Podziały portfela</h1>
        <p className="muted">
          Każdy podział to osobne spojrzenie na ten sam portfel — np. według strategii, regionu albo ryzyka.
        </p>
      </header>

      {error && (
        <div className="banner banner-error">
          <p>{error}</p>
        </div>
      )}

      <div className="editor-layout">
        <nav className="breakdown-list" aria-label="Twoje podziały">
          <div className="value-eyebrow">Twoje podziały</div>
          {breakdowns.map((b) => {
            const isSelected = b.id === selected?.id
            const groupCount = b.groups.length
            return (
              <button
                key={b.id}
                type="button"
                className="breakdown-list-item"
                aria-pressed={isSelected}
                onClick={() => setSelectedId(b.id)}
              >
                <span className="breakdown-list-title">
                  <span className="strong">{b.name}</span>
                  {b.is_default && <span className="badge">domyślny</span>}
                </span>
                <span className="muted small">
                  {groupCount} {pluralizePl(groupCount, 'grupa', 'grupy', 'grup')}
                </span>
              </button>
            )
          })}
          <button type="button" className="card add-card breakdown-add" onClick={handleCreate}>
            + Nowy podział
          </button>
          <p className="muted small">
            Wbudowane (Aktywa, Klasa aktywów, Waluta notowań, Portfel) liczą się same i nie wymagają edycji.
          </p>
        </nav>

        {selected === null ? (
          <section className="value-card">
            <p className="muted">Nie masz jeszcze własnego podziału.</p>
            <button type="button" className="btn-small" onClick={handleCreate}>
              Utwórz pierwszy podział
            </button>
          </section>
        ) : (
          <div className="editor-main">
            <div className="editor-head">
              <div className="editor-head-fields">
                <label className="field-label">
                  Nazwa podziału
                  <input
                    key={selected.id}
                    className="breakdown-name-input"
                    defaultValue={selected.name}
                    onBlur={(e) => saveName(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                  />
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={selected.is_default}
                    onChange={(e) => toggleDefault(e.target.checked)}
                  />
                  Pokazuj ten podział domyślnie w udziałach
                </label>
              </div>
              <div className="editor-head-actions">
                <button type="button" className="btn-small" onClick={handleDuplicate}>
                  Duplikuj
                </button>
                <button type="button" className="btn-small btn-danger" onClick={handleDelete}>
                  Usuń
                </button>
                <button type="button" className="btn-primary" onClick={onBack}>
                  Gotowe
                </button>
              </div>
            </div>

            <div className="banner banner-info">
              <p>
                W jednym podziale każde aktywo jest w dokładnie jednej grupie, więc udziały sumują się do
                100%. W różnych podziałach to samo aktywo może być w różnych grupach. Podziały są wspólne dla
                wszystkich portfeli; grupy, które mogą się nakładać, zostają w Agregatach.
              </p>
            </div>

            {topLevel.length > 0 && (
              <section className="value-card preview-card">
                <div className="section-head">
                  <h2>Podgląd: {selected.name}</h2>
                  <span className="muted small">grupy najwyższego poziomu · wszystkie portfele</span>
                </div>
                <div className="preview-bar">
                  {topLevel.map((node) => (
                    <span
                      key={node.id}
                      style={{
                        width: `${node.share_of_parent}%`,
                        background:
                          node.kind === 'ungrouped'
                            ? UNGROUPED_COLOR
                            : seriesColor(shares?.root.children.indexOf(node) ?? 0),
                      }}
                    />
                  ))}
                </div>
                <div className="preview-legend">
                  {topLevel.map((node) => (
                    <span key={node.id}>
                      <span
                        className="legend-swatch"
                        style={{
                          background:
                            node.kind === 'ungrouped'
                              ? UNGROUPED_COLOR
                              : seriesColor(shares?.root.children.indexOf(node) ?? 0),
                        }}
                      />
                      {node.name} <span className="mono muted">{node.share_of_parent.replace('.', ',')}%</span>
                    </span>
                  ))}
                </div>
              </section>
            )}

            <div className="editor-columns">
              <section className="value-card tree-card">
                <div className="section-head">
                  <h2>Grupy</h2>
                  <span className="muted small">wartość · udział w portfelu</span>
                </div>
                {shares === null ? (
                  <p className="muted">Liczę wartości…</p>
                ) : (
                  shares.root.children.map((node) => renderNode(node, 0, null))
                )}
                <form
                  className="inline-form"
                  onSubmit={(e) => addGroup(e, null, newGroupName, () => setNewGroupName(''))}
                >
                  <input
                    aria-label="Nazwa nowej grupy"
                    placeholder="Nazwa nowej grupy"
                    value={newGroupName}
                    onChange={(e) => setNewGroupName(e.target.value)}
                  />
                  <button type="submit" className="btn-small" disabled={!newGroupName.trim()}>
                    + Dodaj grupę
                  </button>
                </form>
              </section>

              <aside className="value-card ungrouped-card">
                <div className="section-head">
                  <h2>Bez grupy</h2>
                  <span className="mono muted">{heldCount(ungroupedNode)}</span>
                </div>
                <p className="muted small">
                  Nowe aktywa z importów trafiają tutaj w każdym podziale osobno, dopóki ich nie przypiszesz.
                  Na wykresie to szary wycinek „Bez grupy”.
                </p>
                {ungroupedNode && ungroupedNode.children.length > 0 ? (
                  ungroupedNode.children.map((node) => (
                    <div key={node.id} className="ungrouped-item">
                      <span className="ungrouped-item-head">
                        <span className="strong">{node.name}</span>
                        <span className="mono">{formatMoney(node.value, 0)}</span>
                      </span>
                      <label className="field-label">
                        Przypisz do
                        {assetSelect(node.id, null)}
                      </label>
                    </div>
                  ))
                ) : (
                  <div className="banner banner-success">
                    <p>Wszystkie aktywa są przypisane.</p>
                  </div>
                )}
              </aside>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default BreakdownsEditor

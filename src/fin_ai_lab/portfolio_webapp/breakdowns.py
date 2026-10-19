"""Breakdowns ("podziały", portfolio-webapp-S11): the owner's own trees of
groups, used to show what share of a portfolio each group holds.

Unlike aggregators (S9), a breakdown is a partition: within one breakdown an
instrument sits in at most one group (the database's primary key enforces
it, REQ-081), so the shares of a level always add up to 100%. The same
instrument may sit in a different group in every breakdown.

Pure computation -- no database, no network, every amount a Decimal.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Literal
from uuid import UUID

NodeKind = Literal["root", "group", "asset", "ungrouped"]

BUILTIN_PREFIX = "builtin:"
BUILTIN_ASSET = "builtin:asset"
BUILTIN_ASSET_CLASS = "builtin:asset_class"
BUILTIN_CURRENCY = "builtin:currency"
BUILTIN_PORTFOLIO = "builtin:portfolio"
BUILTIN_NAMES = {
    BUILTIN_ASSET: "Aktywa",
    BUILTIN_ASSET_CLASS: "Klasa aktywów",
    BUILTIN_CURRENCY: "Waluta notowań",
    BUILTIN_PORTFOLIO: "Portfel",
}
# Fixed order and Polish labels, so a class keeps its place (and chart
# colour) whatever its size -- P1's canonical AssetClass values.
ASSET_CLASS_LABELS = {
    "equity": "Akcje",
    "etf": "ETF",
    "bond": "Obligacje",
    "fund": "Fundusze",
    "cash": "Gotówka",
    "crypto": "Kryptowaluty",
    "derivative": "Derywaty",
    "other": "Inne",
}
UNGROUPED_ID = "ungrouped"
UNGROUPED_NAME = "Bez grupy"


class BreakdownError(Exception):
    pass


@dataclass(frozen=True)
class Group:
    id: UUID
    name: str
    parent_id: UUID | None
    position: int


@dataclass(frozen=True)
class Breakdown:
    id: UUID
    name: str
    is_default: bool
    groups: list[Group]
    assignments: dict[str, UUID]  # instrument key -> group id


@dataclass(frozen=True)
class Holding:
    """One current position's value, as the valuation view computed it."""

    key: str  # stable instrument key (REQ-086)
    name: str
    symbol: str | None
    value: Decimal
    asset_class: str
    currency: str | None
    portfolio_id: UUID
    portfolio_name: str


@dataclass
class ShareNode:
    id: str
    name: str
    kind: NodeKind
    children: list["ShareNode"] = field(default_factory=list)
    holding: Holding | None = None

    @property
    def value(self) -> Decimal:
        if self.holding is not None:
            return self.holding.value
        return sum((child.value for child in self.children), Decimal(0))

    @property
    def asset_count(self) -> int:
        if self.holding is not None:
            return 1
        return sum(child.asset_count for child in self.children)


def validate_parent(group_id: UUID | None, parent_id: UUID | None, groups: list[Group]) -> None:
    """REQ-082: a group's parent must be in the same breakdown and must not
    be the group itself or anything below it -- otherwise the tree would
    loop. `group_id` is None for a group that doesn't exist yet."""
    if parent_id is None:
        return
    by_id = {group.id: group for group in groups}
    if parent_id not in by_id:
        raise BreakdownError("Grupa nadrzędna nie należy do tego podziału.")
    seen: set[UUID] = set()
    walk: UUID | None = parent_id
    while walk is not None and walk not in seen:
        if walk == group_id:
            raise BreakdownError("Grupy nie można umieścić w niej samej ani w jej podgrupie.")
        seen.add(walk)
        walk = by_id[walk].parent_id if walk in by_id else None


def merge_holdings(holdings: Iterable[Holding]) -> list[Holding]:
    """One holding per instrument key -- the same instrument held in two
    portfolios is one asset in a breakdown, its values summed."""
    merged: dict[str, Holding] = {}
    holders: dict[str, list[str]] = {}
    for holding in holdings:
        names = holders.setdefault(holding.key, [])
        if holding.portfolio_name not in names:
            names.append(holding.portfolio_name)
        existing = merged.get(holding.key)
        if existing is None:
            merged[holding.key] = holding
        else:
            merged[holding.key] = replace(existing, value=existing.value + holding.value)
    # Held in several portfolios: no single portfolio's name describes it.
    return [
        replace(h, portfolio_name=_portfolio_count(len(holders[key])))
        if len(holders[key]) > 1
        else h
        for key, h in merged.items()
    ]


def _portfolio_count(count: int) -> str:
    few = count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14)
    return f"{count} {'portfele' if few else 'portfeli'}"


def custom_tree(
    groups: list[Group],
    assignments: dict[str, UUID],
    holdings: list[Holding],
    *,
    root_name: str,
) -> ShareNode:
    """The breakdown's full tree over `holdings`: every group (empty ones
    too -- the editor needs them; the chart skips zero values), each
    assigned instrument under its group, and everything unassigned under a
    "Bez grupy" node. Children keep definition order (groups by position,
    then assets by name), the order a chart assigns colours by."""
    merged = merge_holdings(holdings)
    group_ids = {group.id for group in groups}
    nodes = {
        group.id: ShareNode(id=str(group.id), name=group.name, kind="group") for group in groups
    }
    root = ShareNode(id="root", name=root_name, kind="root")

    for group in sorted(groups, key=lambda g: (g.position, g.name)):
        parent = nodes.get(group.parent_id) if group.parent_id is not None else None
        (parent or root).children.append(nodes[group.id])

    ungrouped = ShareNode(id=UNGROUPED_ID, name=UNGROUPED_NAME, kind="ungrouped")
    for holding in sorted(merged, key=lambda h: h.name.lower()):
        group_id = assignments.get(holding.key)
        target = nodes[group_id] if group_id is not None and group_id in group_ids else ungrouped
        target.children.append(_asset_node(holding))
    root.children.append(ungrouped)
    return root


def builtin_tree(kind: str, holdings: list[Holding], *, root_name: str) -> ShareNode:
    """REQ-085: breakdowns computed from the data itself, no set-up."""
    root = ShareNode(id="root", name=root_name, kind="root")
    if kind == BUILTIN_ASSET:
        merged = merge_holdings(holdings)
        root.children = [_asset_node(h) for h in sorted(merged, key=lambda h: h.name.lower())]
    elif kind == BUILTIN_ASSET_CLASS:
        order = list(ASSET_CLASS_LABELS)
        classes = sorted(
            {h.asset_class for h in holdings},
            key=lambda c: order.index(c) if c in order else len(order),
        )
        root.children = [
            _builtin_group(
                f"asset_class:{c}",
                ASSET_CLASS_LABELS.get(c, c),
                [h for h in holdings if h.asset_class == c],
            )
            for c in classes
        ]
    elif kind == BUILTIN_CURRENCY:
        currencies = sorted(
            {h.currency or "?" for h in holdings}, key=lambda c: (c != "PLN", c == "?", c)
        )
        root.children = [
            _builtin_group(
                f"currency:{c}",
                c if c != "?" else "Nieznana",
                [h for h in holdings if (h.currency or "?") == c],
            )
            for c in currencies
        ]
    elif kind == BUILTIN_PORTFOLIO:
        portfolios: dict[UUID, str] = {}
        for holding in holdings:
            portfolios.setdefault(holding.portfolio_id, holding.portfolio_name)
        root.children = [
            _builtin_group(f"portfolio:{pid}", name, [h for h in holdings if h.portfolio_id == pid])
            for pid, name in portfolios.items()
        ]
    else:
        raise BreakdownError(f"Nieznany podział wbudowany: {kind}")
    return root


def share(part: Decimal, whole: Decimal) -> Decimal:
    """Percent of `whole`, unrounded; 0 when there is nothing to divide."""
    if whole == 0:
        return Decimal(0)
    return part / whole * 100


def _builtin_group(node_id: str, name: str, holdings: list[Holding]) -> ShareNode:
    merged = merge_holdings(holdings)
    return ShareNode(
        id=node_id,
        name=name,
        kind="group",
        children=[_asset_node(h) for h in sorted(merged, key=lambda h: h.name.lower())],
    )


def _asset_node(holding: Holding) -> ShareNode:
    return ShareNode(id=holding.key, name=holding.name, kind="asset", holding=holding)

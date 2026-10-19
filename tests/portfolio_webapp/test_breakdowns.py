from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from fin_ai_lab.portfolio_webapp.breakdowns import (
    BUILTIN_ASSET,
    BUILTIN_ASSET_CLASS,
    BUILTIN_CURRENCY,
    BUILTIN_PORTFOLIO,
    BreakdownError,
    Group,
    Holding,
    ShareNode,
    builtin_tree,
    custom_tree,
    merge_holdings,
    share,
    validate_parent,
)

D = Decimal
P1, P2 = uuid4(), uuid4()


def _holding(key: str, value: str, *, cls: str = "equity", ccy: str = "PLN", portfolio=P1):
    return Holding(
        key=key,
        name=key.title(),
        symbol=key.upper(),
        value=D(value),
        asset_class=cls,
        currency=ccy,
        portfolio_id=portfolio,
        portfolio_name="XTB" if portfolio == P1 else "Bossa",
    )


def _by_name(node: ShareNode) -> dict[str, ShareNode]:
    return {child.name: child for child in node.children}


# --- validate_parent (REQ-082) -------------------------------------------------


def test_group_cannot_be_moved_into_itself_or_its_descendant() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    groups = [Group(a, "A", None, 0), Group(b, "B", a, 1), Group(c, "C", b, 2)]

    with pytest.raises(BreakdownError):
        validate_parent(a, a, groups)
    with pytest.raises(BreakdownError):
        validate_parent(a, c, groups)  # C is A's grandchild
    validate_parent(c, a, groups)  # moving up is fine
    validate_parent(None, c, groups)  # a new group under C is fine


def test_parent_must_belong_to_the_same_breakdown() -> None:
    with pytest.raises(BreakdownError):
        validate_parent(None, uuid4(), [])


# --- custom tree ---------------------------------------------------------------


def test_custom_tree_nests_groups_and_puts_the_rest_in_bez_grupy() -> None:
    stocks, pl, etf, empty = uuid4(), uuid4(), uuid4(), uuid4()
    groups = [
        Group(stocks, "Akcje", None, 0),
        Group(pl, "Akcje PL", stocks, 1),
        Group(etf, "ETF", None, 2),
        Group(empty, "Pusta", None, 3),
    ]
    assignments: dict[str, UUID] = {"cdr": pl, "asml": stocks, "vwce": etf}
    holdings = [
        _holding("cdr", "100"),
        _holding("asml", "50"),
        _holding("vwce", "250"),
        _holding("gold", "100"),
    ]

    root = custom_tree(groups, assignments, holdings, root_name="Wszystkie")

    top = _by_name(root)
    # Definition order, "Bez grupy" last -- the order chart colours follow.
    assert list(top) == ["Akcje", "ETF", "Pusta", "Bez grupy"]
    assert top["Akcje"].value == D(150)
    assert [c.name for c in top["Akcje"].children] == ["Akcje PL", "Asml"]
    assert top["Pusta"].value == D(0)  # kept for the editor
    assert [c.name for c in top["Bez grupy"].children] == ["Gold"]
    assert root.value == D(500)
    assert root.asset_count == 4


def test_same_instrument_in_two_portfolios_is_one_asset() -> None:
    holdings = [_holding("vwce", "100", portfolio=P1), _holding("vwce", "60", portfolio=P2)]

    (merged,) = merge_holdings(holdings)

    assert merged.value == D(160)
    assert merged.portfolio_name == "2 portfele"  # neither portfolio's own name


def test_assignment_to_a_missing_group_falls_back_to_bez_grupy() -> None:
    root = custom_tree([], {"cdr": uuid4()}, [_holding("cdr", "10")], root_name="R")

    assert [c.name for c in root.children] == ["Bez grupy"]
    assert root.children[0].value == D(10)


# --- built-in breakdowns (REQ-085) ------------------------------------------


def test_asset_class_breakdown_uses_fixed_order_and_polish_labels() -> None:
    holdings = [
        _holding("edo", "30", cls="bond"),
        _holding("cdr", "50", cls="equity"),
        _holding("vwce", "20", cls="etf"),
    ]

    root = builtin_tree(BUILTIN_ASSET_CLASS, holdings, root_name="R")

    assert [c.name for c in root.children] == ["Akcje", "ETF", "Obligacje"]


def test_currency_breakdown_puts_pln_first() -> None:
    holdings = [
        _holding("aapl", "10", ccy="USD"),
        _holding("cdr", "10"),
        _holding("x", "1", ccy=None),
    ]

    root = builtin_tree(BUILTIN_CURRENCY, holdings, root_name="R")

    assert [c.name for c in root.children] == ["PLN", "USD", "Nieznana"]


def test_portfolio_breakdown_keeps_each_portfolio_separate() -> None:
    holdings = [_holding("vwce", "100", portfolio=P1), _holding("vwce", "60", portfolio=P2)]

    root = builtin_tree(BUILTIN_PORTFOLIO, holdings, root_name="R")

    assert [(c.name, c.value) for c in root.children] == [("XTB", D(100)), ("Bossa", D(60))]


def test_asset_breakdown_is_flat() -> None:
    root = builtin_tree(BUILTIN_ASSET, [_holding("b", "1"), _holding("a", "2")], root_name="R")

    assert [c.name for c in root.children] == ["A", "B"]
    assert all(c.kind == "asset" for c in root.children)


def test_unknown_builtin_is_an_error() -> None:
    with pytest.raises(BreakdownError):
        builtin_tree("builtin:nope", [], root_name="R")


def test_share_of_nothing_is_zero_not_a_division_error() -> None:
    assert share(D(5), D(0)) == D(0)
    assert share(D(1), D(4)) == D(25)

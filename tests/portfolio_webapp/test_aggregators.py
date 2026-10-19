from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from fin_ai_lab.portfolio_webapp.aggregators import (
    Aggregator,
    CycleError,
    instrument_key,
    resolve_value,
    top_level_ids,
    validate_no_cycle,
)
from fin_ai_lab.portfolio_xray.canonical import Position

_PORTFOLIO_ID = uuid4()


def _position(**overrides: object) -> Position:
    fields = dict(
        broker="xtb",
        account_type="regular",
        instrument_name="MSCI ACWI",
        isin=None,
        symbol=None,
        asset_class="etf",
        quantity=Decimal("1"),
        valuation_date=date(2026, 9, 15),
    )
    fields.update(overrides)
    return Position(**fields)


def _aggregator(**overrides: object) -> Aggregator:
    fields = dict(
        id=uuid4(),
        portfolio_id=_PORTFOLIO_ID,
        name="Test",
        member_instrument_keys=[],
        member_aggregator_ids=[],
    )
    fields.update(overrides)
    return Aggregator(**fields)


def test_instrument_key_prefers_isin() -> None:
    position = _position(isin="US0378331005", symbol="AAPL")
    assert instrument_key(position) == "US0378331005"


def test_instrument_key_falls_back_to_broker_symbol_without_isin() -> None:
    position = _position(isin=None, symbol="ISAC.UK")
    assert instrument_key(position) == "xtb:ISAC.UK"


def test_instrument_key_falls_back_to_instrument_name_without_isin_or_symbol() -> None:
    position = _position(isin=None, symbol=None, broker="manual", instrument_name="Gotówka")
    assert instrument_key(position) == "manual:Gotówka"


def test_resolve_value_sums_direct_instrument_members() -> None:
    aggregator = _aggregator(member_instrument_keys=["AAA", "BBB"])
    values = {"AAA": Decimal("100"), "BBB": Decimal("50")}

    assert resolve_value(aggregator, {aggregator.id: aggregator}, values) == Decimal("150")


def test_resolve_value_walks_nested_aggregators() -> None:
    child = _aggregator(member_instrument_keys=["AAA"])
    parent = _aggregator(member_instrument_keys=["BBB"], member_aggregator_ids=[child.id])
    all_by_id = {child.id: child, parent.id: parent}
    values = {"AAA": Decimal("100"), "BBB": Decimal("50")}

    assert resolve_value(parent, all_by_id, values) == Decimal("150")


def test_resolve_value_counts_shared_instrument_once() -> None:
    # Same instrument reachable directly AND through a nested aggregator --
    # REQ-061, must not be double-counted.
    child = _aggregator(member_instrument_keys=["AAA"])
    parent = _aggregator(member_instrument_keys=["AAA"], member_aggregator_ids=[child.id])
    all_by_id = {child.id: child, parent.id: parent}
    values = {"AAA": Decimal("100")}

    assert resolve_value(parent, all_by_id, values) == Decimal("100")


def test_resolve_value_ignores_instrument_with_no_stored_value() -> None:
    # An instrument that disappeared on a later re-import -- membership key
    # persists, but contributes 0, not an error.
    aggregator = _aggregator(member_instrument_keys=["GONE"])

    assert resolve_value(aggregator, {aggregator.id: aggregator}, {}) == Decimal(0)


def test_resolve_value_empty_aggregator_is_zero() -> None:
    aggregator = _aggregator()

    assert resolve_value(aggregator, {aggregator.id: aggregator}, {}) == Decimal(0)


def test_validate_no_cycle_rejects_direct_self_reference() -> None:
    target_id = uuid4()

    with pytest.raises(CycleError):
        validate_no_cycle(target_id, [target_id], {})


def test_validate_no_cycle_rejects_indirect_cycle() -> None:
    # A contains B; proposing A as a new member of B would close the loop.
    a = _aggregator()
    b = _aggregator(member_aggregator_ids=[a.id])
    all_by_id = {a.id: a, b.id: b}

    with pytest.raises(CycleError):
        validate_no_cycle(a.id, [b.id], all_by_id)


def test_validate_no_cycle_allows_unrelated_aggregator() -> None:
    a = _aggregator()
    b = _aggregator()
    all_by_id = {a.id: a, b.id: b}

    validate_no_cycle(a.id, [b.id], all_by_id)  # must not raise


def test_top_level_ids_excludes_nested_aggregators() -> None:
    child = _aggregator(name="BTC")
    parent = _aggregator(name="Kryptowaluty", member_aggregator_ids=[child.id])
    other = _aggregator(name="Spółki technologiczne")

    result = top_level_ids([child, parent, other])

    assert result == {parent.id, other.id}

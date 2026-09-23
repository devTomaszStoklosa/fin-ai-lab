from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from fin_ai_lab.portfolio_xray.canonical import Position
from fin_ai_lab.portfolio_xray.ledger import (
    BossaTransaction,
    attach_current_market_values,
    date_range,
    dedup_key,
    parse_bossa_csv,
    transactions_to_positions,
)
from portfolio_xray._fixtures import SYNTH_A_ISIN, build_synthetic_bossa_csv


def test_parse_bossa_csv_reads_every_row() -> None:
    transactions = parse_bossa_csv(build_synthetic_bossa_csv())

    assert len(transactions) == 4
    first = transactions[0]
    assert first.executed_at == datetime(2026, 1, 1, 10, 0, 0)
    assert first.instrument_name == "SYNTHA"
    assert first.isin == SYNTH_A_ISIN
    assert first.side == "buy"
    assert first.quantity == Decimal("10")
    assert first.price == Decimal("100.00")
    assert first.net_value == Decimal("1005.00")
    assert first.currency == "PLN"


def test_parse_bossa_csv_rejects_unknown_side() -> None:
    header = "data;papier;isin;ilość;-;cena;wartość;prowizja;po prowizji;waluta"
    bad_row = f"01.01.2026 10:00:00;SYNTHA;{SYNTH_A_ISIN};10;X;100,00;1000,00;5,00;1005,00;PLN"
    payload = (header + "\r\n" + bad_row + "\r\n").encode("cp1250")

    with pytest.raises(ValueError, match="Unknown transaction side"):
        parse_bossa_csv(payload)


def test_transactions_to_positions_aggregates_open_position_and_drops_closed() -> None:
    transactions = parse_bossa_csv(build_synthetic_bossa_csv())

    positions, errors = transactions_to_positions(
        transactions, account_type="regular", valuation_date=date(2026, 9, 15)
    )

    assert errors == []
    assert {p.isin for p in positions} == {SYNTH_A_ISIN}  # SYNTHB closed to zero

    synth_a = positions[0]
    assert synth_a.broker == "bossa"
    assert synth_a.quantity == Decimal("6")
    assert synth_a.avg_cost == Decimal("100.5")  # (1005 - 1005/10*4) / 6
    assert synth_a.cost_currency == "PLN"
    assert synth_a.asset_class == "other"
    assert synth_a.market_value is None


def test_transactions_to_positions_reports_oversell_as_error_not_negative_position() -> None:
    oversell = BossaTransaction(
        executed_at=datetime(2026, 1, 1, 10, 0, 0),
        instrument_name="SYNTHA",
        isin=SYNTH_A_ISIN,
        side="sell",
        quantity=Decimal("3"),
        price=Decimal("100"),
        value=Decimal("300"),
        commission=Decimal("0"),
        net_value=Decimal("300"),
        currency="PLN",
    )

    positions, errors = transactions_to_positions(
        [oversell], account_type="regular", valuation_date=date(2026, 9, 15)
    )

    assert positions == []
    assert len(errors) == 1
    assert SYNTH_A_ISIN in errors[0]


def test_dedup_key_is_stable_and_content_sensitive() -> None:
    transactions = parse_bossa_csv(build_synthetic_bossa_csv())

    assert dedup_key(transactions[0]) == dedup_key(transactions[0].model_copy())
    assert dedup_key(transactions[0]) != dedup_key(transactions[1])


def test_date_range_covers_all_transactions() -> None:
    transactions = parse_bossa_csv(build_synthetic_bossa_csv())

    assert date_range(transactions) == (date(2026, 1, 1), date(2026, 1, 5))


def test_date_range_empty_list_returns_none() -> None:
    assert date_range([]) is None


def test_attach_current_market_values_skips_position_without_ticker() -> None:
    position = Position(
        broker="bossa",
        account_type="regular",
        instrument_name="SYNTHA",
        isin=SYNTH_A_ISIN,
        symbol=None,
        asset_class="other",
        quantity=Decimal("6"),
        avg_cost=Decimal("100.5"),
        cost_currency="PLN",
        market_value=None,
        market_currency=None,
        valuation_date=date(2026, 9, 15),
    )

    updated = attach_current_market_values([position])

    assert updated[0].market_value is None


def test_attach_current_market_values_uses_latest_close(monkeypatch: pytest.MonkeyPatch) -> None:
    history = pd.Series(
        [98.0, 99.0, 101.5], index=pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"])
    )
    monkeypatch.setattr(
        "fin_ai_lab.portfolio_xray.ledger.fetch_price_history", lambda ticker: history
    )
    position = Position(
        broker="bossa",
        account_type="regular",
        instrument_name="SYNTHA",
        isin=SYNTH_A_ISIN,
        symbol=None,
        ticker="SYNA.WA",
        asset_class="other",
        quantity=Decimal("6"),
        avg_cost=Decimal("100.5"),
        cost_currency="PLN",
        market_value=None,
        market_currency=None,
        valuation_date=date(2026, 9, 15),
    )

    updated = attach_current_market_values([position])

    assert updated[0].market_value == Decimal("101.5") * Decimal("6")
    assert updated[0].market_currency == "PLN"


def test_attach_current_market_values_translates_ticker_to_yahoo_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # OpenFIGI's own ticker ("1AT") isn't Yahoo's symbol ("1AT.WA") -- issue
    # #208, verified live: fetch_price_history must be called with the
    # translated ticker, not the raw OpenFIGI one, or every Bossa position
    # keeps market_value=None even when resolved.
    history = pd.Series([60.3], index=pd.to_datetime(["2026-09-22"]))
    seen_tickers: list[str] = []

    def recording_fetcher(ticker: str):
        seen_tickers.append(ticker)
        return history

    monkeypatch.setattr("fin_ai_lab.portfolio_xray.ledger.fetch_price_history", recording_fetcher)
    position = Position(
        broker="bossa",
        account_type="regular",
        instrument_name="ATAL",
        isin="PLATAL000046",
        symbol=None,
        ticker="1AT",
        exchange_code="PW",
        asset_class="other",
        quantity=Decimal("53"),
        avg_cost=Decimal("62.79"),
        cost_currency="PLN",
        market_value=None,
        market_currency=None,
        valuation_date=date(2026, 9, 15),
    )

    updated = attach_current_market_values([position])

    assert seen_tickers == ["1AT.WA"]
    assert updated[0].market_value == Decimal("60.3") * Decimal("53")


def test_attach_current_market_values_drops_trailing_nan_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Yahoo can return NaN for the most recent day before it finalizes --
    # must use the last REAL close (101.5), not NaN (issue #193).
    history = pd.Series(
        [98.0, 99.0, 101.5, float("nan")],
        index=pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]),
    )
    monkeypatch.setattr(
        "fin_ai_lab.portfolio_xray.ledger.fetch_price_history", lambda ticker: history
    )
    position = Position(
        broker="bossa",
        account_type="regular",
        instrument_name="SYNTHA",
        isin=SYNTH_A_ISIN,
        symbol=None,
        ticker="SYNA.WA",
        asset_class="other",
        quantity=Decimal("6"),
        avg_cost=Decimal("100.5"),
        cost_currency="PLN",
        market_value=None,
        market_currency=None,
        valuation_date=date(2026, 9, 15),
    )

    updated = attach_current_market_values([position])

    assert updated[0].market_value == Decimal("101.5") * Decimal("6")


def test_attach_current_market_values_skips_when_history_is_all_nan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = pd.Series(
        [float("nan"), float("nan")], index=pd.to_datetime(["2026-09-01", "2026-09-02"])
    )
    monkeypatch.setattr(
        "fin_ai_lab.portfolio_xray.ledger.fetch_price_history", lambda ticker: history
    )
    position = Position(
        broker="bossa",
        account_type="regular",
        instrument_name="SYNTHA",
        isin=SYNTH_A_ISIN,
        symbol=None,
        ticker="SYNA.WA",
        asset_class="other",
        quantity=Decimal("6"),
        avg_cost=Decimal("100.5"),
        cost_currency="PLN",
        market_value=None,
        market_currency=None,
        valuation_date=date(2026, 9, 15),
    )

    updated = attach_current_market_values([position])

    assert updated[0].market_value is None

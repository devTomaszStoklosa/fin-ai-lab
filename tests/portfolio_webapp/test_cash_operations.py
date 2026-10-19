from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pytest

openpyxl = pytest.importorskip("openpyxl")

from portfolio_xray._fixtures import build_synthetic_xtb_workbook  # noqa: E402

from fin_ai_lab.portfolio_webapp.cash_operations import (  # noqa: E402
    CashOperationsError,
    dividend_per_share,
    extract_xtb_cash_operations,
    withholding_rate,
)

D = Decimal
DAY = datetime(2026, 1, 2, 10, 0, 0)


def _workbook(operations, **kwargs) -> bytes:
    return build_synthetic_xtb_workbook(cash_operations=operations, **kwargs)


def test_operations_are_grouped_by_kind_with_signed_amounts() -> None:
    history = extract_xtb_cash_operations(
        _workbook(
            [
                ("Stock purchase", "Atrem", DAY, -100.5, "1"),
                ("Stock sell", "Atrem", DAY, 60.25, "2"),
                ("Dividend", "Atrem", DAY, 0.72, "3"),
                ("Withholding tax", "Atrem", DAY, -0.14, "4"),
                ("Free funds interest", "", DAY, 0.08, "5"),
                ("SEC fee", "Atrem", DAY, -0.01, "6"),
            ]
        )
    )

    assert history is not None
    assert [(op.kind, op.amount, op.currency) for op in history.operations] == [
        ("purchase", D("-100.5"), "PLN"),
        ("sale", D("60.25"), "PLN"),
        ("dividend", D("0.72"), "PLN"),
        ("dividend", D("-0.14"), "PLN"),
        ("interest", D("0.08"), "PLN"),
        ("other", D("-0.01"), "PLN"),
    ]
    assert history.operations[0].op_id == "1"
    assert history.operations[0].instrument == "Atrem"


def test_deposits_and_withdrawals_are_transfers_and_the_total_row_is_ignored() -> None:
    history = extract_xtb_cash_operations(
        _workbook(
            [
                ("Deposit", "", DAY, 5000.0, "1"),
                ("Withdrawal", "", DAY, -100.0, "2"),
                ("Dividend", "Atrem", DAY, 1.0, "3"),
            ]
        )
    )

    assert history is not None
    assert [(op.op_id, op.kind, op.amount) for op in history.operations] == [
        ("1", "transfer", D("5000.0")),
        ("2", "transfer", D("-100.0")),
        ("3", "dividend", D("1.0")),
    ]
    assert history.unknown_types == []  # neither the transfers nor "Total"


def test_unknown_types_and_unreadable_rows_are_reported_not_guessed() -> None:
    history = extract_xtb_cash_operations(
        _workbook(
            [
                ("Crypto staking reward", "X", DAY, 3.0, "1"),
                ("Crypto staking reward", "X", DAY, 4.0, "2"),
                ("Dividend", "Atrem", DAY, 1.0, ""),  # no ID
                ("Dividend", "Atrem", DAY, 2.0, "4"),
            ]
        )
    )

    assert history is not None
    assert history.unknown_types == ["Crypto staking reward"]
    assert history.unreadable_rows == 1
    assert [op.op_id for op in history.operations] == ["4"]


def test_currency_comes_from_the_open_positions_summary() -> None:
    history = extract_xtb_cash_operations(
        _workbook([("Dividend", "Atrem", DAY, 1.0, "1")], account_currency="USD")
    )

    assert history is not None
    assert history.operations[0].currency == "USD"


def test_empty_cash_operations_sheet_means_no_history() -> None:
    assert extract_xtb_cash_operations(build_synthetic_xtb_workbook()) is None


def test_unknown_account_currency_is_an_error() -> None:
    with pytest.raises(CashOperationsError, match="account currency"):
        extract_xtb_cash_operations(
            _workbook([("Dividend", "Atrem", DAY, 1.0, "1")], account_currency=None)
        )


def test_ticker_and_comment_are_read_when_the_export_has_them() -> None:
    history = extract_xtb_cash_operations(
        _workbook(
            [
                ("Dividend", "Microsoft", DAY, 3.64, "1", "MSFT.US", "MSFT.US USD 0.91/ SHR"),
                ("Deposit", "", DAY, 100.0, "2"),
            ]
        )
    )

    assert history is not None
    dividend, deposit = history.operations
    assert (dividend.ticker, dividend.comment) == ("MSFT.US", "MSFT.US USD 0.91/ SHR")
    assert (deposit.ticker, deposit.comment) == (None, None)


def test_an_export_without_ticker_and_comment_columns_still_imports() -> None:
    workbook = openpyxl.Workbook()
    cash = workbook.active
    cash.title = "Cash Operations"
    cash.append(["Type", "Instrument", "Time", "Amount", "ID"])
    cash.append(["Dividend", "Atrem", DAY, 1.0, "1"])
    positions = workbook.create_sheet("Open Positions")
    positions.append(["My Trades", "Open position value", 10.0, "PLN"])
    buffer = BytesIO()
    workbook.save(buffer)

    history = extract_xtb_cash_operations(buffer.getvalue())

    assert history is not None
    (operation,) = history.operations
    assert (operation.instrument, operation.ticker, operation.comment) == ("Atrem", None, None)


def test_dividend_per_share_is_read_from_the_comment() -> None:
    assert dividend_per_share("MSFT.US USD 0.91/ SHR") == ("USD", D("0.91"))
    assert dividend_per_share("TTE.FR EUR 0.8500/ SHR") == ("EUR", D("0.8500"))


def test_tax_rows_corrections_and_empty_comments_state_no_per_share_amount() -> None:
    assert dividend_per_share("MSFT.US USD WHT 15%") is None
    assert dividend_per_share("corr ATR.PL USD 0.5700/ SHR") is None
    assert dividend_per_share(None) is None


def test_withholding_rate_is_read_from_a_tax_row_comment() -> None:
    assert withholding_rate("MSFT.US USD WHT 15%") == D("0.15")
    assert withholding_rate("DE.US USD WHT 26.375%") == D("0.26375")
    assert withholding_rate("corr ATR.PL USD WHT 19%") is None  # a correction
    assert withholding_rate("MSFT.US USD 0.91/ SHR") is None

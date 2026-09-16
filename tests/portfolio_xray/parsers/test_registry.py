from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from fin_ai_lab.portfolio_xray.parsers.signature import compute_signature

_EXPECTED_XTB_HEADERS = [
    "Product",
    "Instrument/Position",
    "Ticker",
    "Category",
    "Type",
    "Volume",
    "Value",
    "Current price",
    "Open price",
    "Open time (UTC)",
    "Stop Loss",
    "Take Profit",
    "Net Profit %",
    "Net Profit",
    "Gross Profit",
    "Margin",
    "Open Commission",
    "Swap",
    "Rollover",
]


def test_registry_finds_approved_xtb_config_by_signature() -> None:
    registry = ParserRegistry()
    signature = compute_signature(
        _EXPECTED_XTB_HEADERS, delimiter=None, encoding="utf-8", sheet_name="Open Positions"
    )

    config = registry.find_approved(signature)

    assert config is not None
    assert config.broker == "xtb"
    assert config.header_row == 9


def test_registry_returns_none_for_unknown_signature() -> None:
    registry = ParserRegistry()

    assert registry.find_approved("does-not-exist") is None

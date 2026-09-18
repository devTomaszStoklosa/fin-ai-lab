from datetime import date
from decimal import Decimal

import httpx

from fin_ai_lab.investment_committee.tools import build_tools
from fin_ai_lab.portfolio_xray.canonical import Portfolio, Position


class _FakeFxClient:
    async def mid_rate(self, currency: str, as_of):
        return Decimal(1) if currency == "PLN" else Decimal("4.0")


class _FakeFredClient:
    async def latest_observation(self, series_id: str, **kwargs):
        return None


class _FakeNbpClient:
    async def fetch_fx_rate(self, code: str, **kwargs):
        return None


def _portfolio() -> Portfolio:
    return Portfolio(
        valuation_date=date(2026, 9, 17),
        positions=[
            Position(
                broker="xtb", account_type="regular", instrument_name="Orlen",
                asset_class="equity", quantity=Decimal("10"),
                market_value=Decimal("1000"), market_currency="PLN",
                valuation_date=date(2026, 9, 17),
            ),
            Position(
                broker="xtb", account_type="regular", instrument_name="Apple",
                asset_class="equity", quantity=Decimal("5"),
                market_value=Decimal("500"), market_currency="USD",
                valuation_date=date(2026, 9, 17),
            ),
        ],
    )


def _tool(tools: list, name: str):
    return next(tool for tool in tools if tool.__name__ == name)


async def test_get_portfolio_allocation_reports_real_computed_weights() -> None:
    tools = build_tools(
        _portfolio(), _FakeFredClient(), _FakeNbpClient(), fx_client=_FakeFxClient()
    )

    result = await _tool(tools, "get_portfolio_allocation")()

    assert "HHI" in result
    assert "equity" in result


async def test_get_market_regime_reports_missing_sources_when_nothing_published(
    monkeypatch,
) -> None:
    async def fake_reference_rate():
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(
        "fin_ai_lab.market_pulse.indicators.fetch_reference_rate", fake_reference_rate
    )
    tools = build_tools(
        _portfolio(), _FakeFredClient(), _FakeNbpClient(), fx_client=_FakeFxClient()
    )

    result = await _tool(tools, "get_market_regime")()

    assert "Reżim rynku" in result
    assert "Brakujące źródła" in result


async def test_ask_about_filings_is_an_explicit_stub() -> None:
    tools = build_tools(
        _portfolio(), _FakeFredClient(), _FakeNbpClient(), fx_client=_FakeFxClient()
    )

    result = await _tool(tools, "ask_about_filings")("Jakie ryzyka ma Orlen?")

    assert "nie jest jeszcze podłączone" in result


async def test_get_news_sentiment_is_an_explicit_stub() -> None:
    tools = build_tools(
        _portfolio(), _FakeFredClient(), _FakeNbpClient(), fx_client=_FakeFxClient()
    )

    result = await _tool(tools, "get_news_sentiment")("Orlen podaje wyniki")

    assert "nie ma jeszcze wytrenowanego modelu" in result

from datetime import date
from decimal import Decimal

from fin_ai_lab.market_pulse.tools import build_tools


class _FakeFredClient:
    async def latest_observation(self, series_id: str):
        if series_id == "DGS10":
            return Decimal("4.5"), date(2026, 9, 17)
        return None


class _FakeNbpClient:
    async def fetch_fx_rate(self, code: str):
        if code == "EUR":
            return Decimal("4.36"), date(2026, 9, 17)
        return None


def _tool(tools: list, name: str):
    return next(tool for tool in tools if tool.__name__ == name)


async def test_get_fred_series_value_reports_a_found_value() -> None:
    tools = build_tools(_FakeFredClient(), _FakeNbpClient())

    result = await _tool(tools, "get_fred_series_value")("DGS10")

    assert "DGS10" in result
    assert "4.5" in result


async def test_get_fred_series_value_reports_when_nothing_published() -> None:
    tools = build_tools(_FakeFredClient(), _FakeNbpClient())

    result = await _tool(tools, "get_fred_series_value")("UNKNOWN")

    assert "No recent value" in result


async def test_get_nbp_fx_rate_reports_a_found_rate() -> None:
    tools = build_tools(_FakeFredClient(), _FakeNbpClient())

    result = await _tool(tools, "get_nbp_fx_rate")("EUR")

    assert "EUR/PLN" in result
    assert "4.36" in result


async def test_get_nbp_reference_rate_reports_the_current_rate(monkeypatch) -> None:
    async def fake_reference_rate():
        return Decimal("3.75"), date(2026, 3, 5)

    monkeypatch.setattr("fin_ai_lab.market_pulse.tools.fetch_reference_rate", fake_reference_rate)
    tools = build_tools(_FakeFredClient(), _FakeNbpClient())

    result = await _tool(tools, "get_nbp_reference_rate")()

    assert "3.75" in result

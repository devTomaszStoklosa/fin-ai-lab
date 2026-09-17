from datetime import date
from decimal import Decimal

from fin_ai_lab.market_pulse.mcp_server import build_server


class _FakeFredClient:
    async def latest_observation(self, series_id: str):
        return None


class _FakeNbpClient:
    async def fetch_fx_rate(self, code: str):
        return None


async def test_build_server_exposes_the_expected_tools() -> None:
    server = build_server(_FakeFredClient(), _FakeNbpClient())

    tools = await server.list_tools()

    tool_names = {tool.name for tool in tools}
    assert tool_names == {
        "get_fred_series_value",
        "get_nbp_fx_rate",
        "get_nbp_reference_rate",
        "get_wig20_price",
    }


async def test_wig20_tool_reports_a_found_value(monkeypatch) -> None:
    monkeypatch.setattr(
        "fin_ai_lab.market_pulse.mcp_server.fetch_wig20",
        lambda: (Decimal("2450.5"), date(2026, 9, 17)),
    )
    server = build_server(_FakeFredClient(), _FakeNbpClient())

    result = await server.call_tool("get_wig20_price", {})

    assert "2450.5" in str(result)


async def test_wig20_tool_reports_when_yahoo_has_nothing(monkeypatch) -> None:
    monkeypatch.setattr("fin_ai_lab.market_pulse.mcp_server.fetch_wig20", lambda: None)
    server = build_server(_FakeFredClient(), _FakeNbpClient())

    result = await server.call_tool("get_wig20_price", {})

    assert "No recent WIG20 value" in str(result)

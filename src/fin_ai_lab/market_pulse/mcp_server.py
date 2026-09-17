from mcp.server.mcpserver import MCPServer

from fin_ai_lab.core.config import Settings
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient
from fin_ai_lab.market_pulse.sources.yfinance_client import fetch_wig20
from fin_ai_lab.market_pulse.tools import build_tools


def build_server(fred_client: FredClient, nbp_client: NbpClient) -> MCPServer:
    """P3-S3: exposes the same data tools P3-S2's agent uses, for
    interactive use from Claude Desktop/Code, plus WIG20 — which is
    intentionally NOT in build_tools() and never reaches the automated
    brief or the AFC agent (03-design.md open question #1: no free,
    automatable WIG20 source exists, so it's interactive-only here)."""
    server = MCPServer(name="fin-ai-lab-market-pulse")

    for tool in build_tools(fred_client, nbp_client):
        server.add_tool(tool)

    async def get_wig20_price() -> str:
        """Get the latest WIG20 (Warsaw Stock Exchange blue-chip index)
        closing value, via Yahoo Finance. Interactive use only — Yahoo's
        yfinance access is unofficial and sometimes blocked, so this tool
        can fail where the other market-pulse tools don't."""
        result = fetch_wig20()
        if result is None:
            return "No recent WIG20 value available (Yahoo Finance data unavailable)."
        value, as_of = result
        return f"WIG20 = {value}, as of {as_of.isoformat()}."

    server.add_tool(get_wig20_price)
    return server


if __name__ == "__main__":
    settings = Settings()
    build_server(
        FredClient(settings.require_fred_api_key()),
        NbpClient(),
    ).run()

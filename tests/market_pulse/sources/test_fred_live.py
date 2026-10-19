import pytest

from fin_ai_lab.core.config import Settings
from fin_ai_lab.market_pulse.sources.fred import FredClient

pytestmark = pytest.mark.live


async def test_latest_observation_reads_a_real_fred_series() -> None:
    settings = Settings()
    client = FredClient(settings.require_fred_api_key())

    result = await client.latest_observation("DGS10")

    assert result is not None
    value, as_of = result
    assert value > 0
    assert as_of.year >= 2024

from decimal import Decimal

import pytest

from fin_ai_lab.core.config import Settings
from fin_ai_lab.filings_rag.ingest.sec_edgar import SecEdgarClient
from fin_ai_lab.filings_rag.xbrl.client import XbrlClient

pytestmark = pytest.mark.live


async def test_observation_reads_a_real_revenue_figure_for_microsoft() -> None:
    settings = Settings()
    sec_client = SecEdgarClient(settings.require_sec_user_agent())
    client = XbrlClient(sec_client, {"Microsoft": "789019"})

    observation = await client.observation("Microsoft", "revenue", "FY2024")

    assert observation is not None
    assert observation.unit == "USD"
    assert observation.value > Decimal("0")

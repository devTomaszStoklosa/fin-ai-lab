from decimal import Decimal
from pathlib import Path

import httpx

from fin_ai_lab.core.http.client import ThrottledHttpClient
from fin_ai_lab.filings_rag.ingest.sec_edgar import SecEdgarClient
from fin_ai_lab.filings_rag.xbrl.client import XbrlClient

_COMPANYFACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        # Same fiscal year (FY2017) reported by two filings —
                        # the later one (filed 2018) must win (REQ-032).
                        {"val": 89950000000, "fy": 2017, "fp": "FY", "filed": "2017-08-01"},
                        {"val": 90000000000, "fy": 2017, "fp": "FY", "filed": "2018-08-03"},
                    ]
                }
            },
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        # Tag changed after ASC 606 — only this tag has FY2019.
                        {"val": 125843000000, "fy": 2019, "fp": "FY", "filed": "2019-08-01"},
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {
                    "USD": [{"val": 39240000000, "fy": 2019, "fp": "FY", "filed": "2019-08-01"}]
                }
            },
        }
    }
}


def _client(tmp_path: Path) -> XbrlClient:
    def data_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_COMPANYFACTS)

    data_client = ThrottledHttpClient(
        "https://data.sec.gov",
        min_interval_s=0.0,
        provider="sec-data-test",
        cache_dir=tmp_path,
        default_headers={"User-Agent": "fin-ai-lab test test@example.com"},
        transport=httpx.MockTransport(data_handler),
    )
    sec_client = SecEdgarClient("fin-ai-lab test test@example.com", data_http_client=data_client)
    return XbrlClient(sec_client, {"Microsoft": "789019"})


async def test_observation_resolves_concept_across_tag_aliases(tmp_path: Path) -> None:
    client = _client(tmp_path)

    observation = await client.observation("Microsoft", "revenue", "FY2019")

    assert observation is not None
    assert observation.value == Decimal("125843000000")
    assert observation.unit == "USD"


async def test_observation_picks_the_most_recently_filed_when_period_repeats(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    observation = await client.observation("Microsoft", "revenue", "FY2017")

    assert observation is not None
    assert observation.value == Decimal("90000000000")
    assert observation.filed.isoformat() == "2018-08-03"


async def test_observation_filters_by_unit_when_given(tmp_path: Path) -> None:
    client = _client(tmp_path)

    observation = await client.observation("Microsoft", "revenue", "FY2019", unit="EUR")

    assert observation is None


async def test_observation_returns_none_for_unknown_concept(tmp_path: Path) -> None:
    client = _client(tmp_path)

    observation = await client.observation("Microsoft", "not_a_real_concept", "FY2019")

    assert observation is None


async def test_observation_returns_none_for_unknown_company(tmp_path: Path) -> None:
    client = _client(tmp_path)

    observation = await client.observation("Nvidia", "revenue", "FY2019")

    assert observation is None


async def test_observation_returns_none_when_period_not_reported(tmp_path: Path) -> None:
    client = _client(tmp_path)

    observation = await client.observation("Microsoft", "net_income", "FY2099")

    assert observation is None

import pytest

from fin_ai_lab.market_pulse.sources.nbp import NbpClient, fetch_reference_rate

pytestmark = pytest.mark.live


async def test_fetch_fx_rate_reads_a_real_eur_pln_rate() -> None:
    client = NbpClient()

    result = await client.fetch_fx_rate("EUR")

    assert result is not None
    value, as_of = result
    assert value > 0
    assert as_of.year >= 2024


async def test_fetch_reference_rate_reads_the_real_nbp_rate() -> None:
    value, as_of = await fetch_reference_rate()

    assert value > 0
    assert as_of.year >= 2020

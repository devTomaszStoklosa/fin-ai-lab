import pytest

from fin_ai_lab.market_pulse.sources.yfinance_client import fetch_wig20

pytestmark = pytest.mark.live


def test_fetch_wig20_returns_a_real_value(tmp_path) -> None:
    result = fetch_wig20(cache_dir=tmp_path)

    assert result is not None
    value, as_of = result
    assert value > 0
    assert as_of is not None

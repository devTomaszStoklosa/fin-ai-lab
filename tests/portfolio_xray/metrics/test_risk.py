import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from fin_ai_lab.portfolio_xray.metrics.risk import (  # noqa: E402
    MIN_TRADING_DAYS,
    compute_risk_metrics,
)

_DATES = pd.date_range("2024-01-01", periods=MIN_TRADING_DAYS, freq="D")


def _flat_series(value: float = 100.0) -> pd.Series:
    return pd.Series([value] * MIN_TRADING_DAYS, index=_DATES)


def _random_walk_series(seed: int, start: float = 100.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=0.0, scale=0.01, size=MIN_TRADING_DAYS - 1)
    prices = [start]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    return pd.Series(prices, index=_DATES)


def test_uncovered_positions_yield_zero_coverage_and_no_stats() -> None:
    metrics = compute_risk_metrics(
        price_history_by_key={"AAA": None},
        weight_by_key={"AAA": 1.0},
        total_positions=1,
    )

    assert metrics.coverage == 0.0
    assert metrics.covered_positions == 0
    assert metrics.annualized_volatility is None


def test_short_history_is_excluded_from_coverage() -> None:
    short_history = pd.Series([100.0, 101.0, 102.0])

    metrics = compute_risk_metrics(
        price_history_by_key={"AAA": short_history},
        weight_by_key={"AAA": 1.0},
        total_positions=1,
    )

    assert metrics.coverage == 0.0
    assert metrics.covered_positions == 0


def test_flat_prices_give_zero_volatility_and_drawdown() -> None:
    metrics = compute_risk_metrics(
        price_history_by_key={"AAA": _flat_series()},
        weight_by_key={"AAA": 1.0},
        total_positions=1,
    )

    assert metrics.coverage == 1.0
    assert metrics.covered_positions == 1
    assert metrics.annualized_volatility == pytest.approx(0.0, abs=1e-9)
    assert metrics.max_drawdown == pytest.approx(0.0, abs=1e-9)


def test_coverage_reflects_uncovered_weight() -> None:
    metrics = compute_risk_metrics(
        price_history_by_key={"AAA": _flat_series(), "BBB": None},
        weight_by_key={"AAA": 0.6, "BBB": 0.4},
        total_positions=2,
    )

    assert metrics.coverage == pytest.approx(0.6)
    assert metrics.covered_positions == 1
    assert metrics.total_positions == 2


def test_beta_is_one_when_portfolio_equals_benchmark() -> None:
    series = _random_walk_series(seed=42)

    metrics = compute_risk_metrics(
        price_history_by_key={"AAA": series},
        weight_by_key={"AAA": 1.0},
        total_positions=1,
        benchmark_history=series,
    )

    assert metrics.beta == pytest.approx(1.0, abs=1e-9)


def test_beta_is_none_without_benchmark() -> None:
    metrics = compute_risk_metrics(
        price_history_by_key={"AAA": _random_walk_series(seed=1)},
        weight_by_key={"AAA": 1.0},
        total_positions=1,
    )

    assert metrics.beta is None

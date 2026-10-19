import numpy as np
import pandas as pd
from pydantic import BaseModel

MIN_TRADING_DAYS = 250
TRADING_DAYS_PER_YEAR = 252


class RiskMetrics(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    coverage: float  # share of total portfolio weight with enough price history
    covered_positions: int
    total_positions: int
    annualized_volatility: float | None = None
    var_95_1d: float | None = None
    max_drawdown: float | None = None
    beta: float | None = None


def compute_risk_metrics(
    price_history_by_key: dict[str, pd.Series],
    weight_by_key: dict[str, float],
    total_positions: int,
    benchmark_history: pd.Series | None = None,
) -> RiskMetrics:
    covered_keys = [
        key
        for key, history in price_history_by_key.items()
        if history is not None and len(history) >= MIN_TRADING_DAYS
    ]
    coverage = sum(weight_by_key.get(key, 0.0) for key in covered_keys)

    if not covered_keys:
        return RiskMetrics(coverage=0.0, covered_positions=0, total_positions=total_positions)

    prices = pd.DataFrame({key: price_history_by_key[key] for key in covered_keys}).dropna()
    returns = np.log(prices / prices.shift(1)).dropna()

    # Current weights applied to past prices (REQ-043's caveat), renormalized
    # across only the covered subset so they sum to 1 for this calculation.
    raw_weights = pd.Series({key: weight_by_key.get(key, 0.0) for key in covered_keys})
    weights = raw_weights / raw_weights.sum()
    portfolio_returns = returns.mul(weights, axis=1).sum(axis=1)

    annualized_volatility = float(portfolio_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    var_95_1d = float(-np.percentile(portfolio_returns, 5))

    cumulative = (1 + portfolio_returns).cumprod()
    drawdown = (cumulative - cumulative.cummax()) / cumulative.cummax()
    max_drawdown = float(-drawdown.min())

    beta = _compute_beta(portfolio_returns, benchmark_history)

    return RiskMetrics(
        coverage=coverage,
        covered_positions=len(covered_keys),
        total_positions=total_positions,
        annualized_volatility=annualized_volatility,
        var_95_1d=var_95_1d,
        max_drawdown=max_drawdown,
        beta=beta,
    )


def _compute_beta(
    portfolio_returns: pd.Series, benchmark_history: pd.Series | None
) -> float | None:
    if benchmark_history is None or len(benchmark_history) < MIN_TRADING_DAYS:
        return None

    benchmark_returns = np.log(benchmark_history / benchmark_history.shift(1)).dropna()
    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return None
    aligned.columns = ["portfolio", "benchmark"]

    benchmark_variance = aligned["benchmark"].var()
    if benchmark_variance == 0:
        return None
    return float(aligned["portfolio"].cov(aligned["benchmark"]) / benchmark_variance)

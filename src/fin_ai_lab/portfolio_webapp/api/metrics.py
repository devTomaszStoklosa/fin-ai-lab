"""Portfolio metrics: weights, concentration and live values."""

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import (
    base_currency_value,
    current_position_rows,
    get_db,
    position_row_to_domain,
)
from fin_ai_lab.portfolio_webapp.api.defaults import BASE_CURRENCY
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.api.live_values import live_market_values
from fin_ai_lab.portfolio_webapp.schemas import MetricsOut
from fin_ai_lab.portfolio_xray.metrics.weights import compute_weights


def _as_percent(fraction: Decimal) -> Decimal:
    return (fraction * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/portfolios/{portfolio_id}/metrics", response_model=MetricsOut)
    async def get_metrics(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> MetricsOut:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        rows = current_position_rows(connection, portfolio_id)
        fx_client = deps.fx_client_factory()
        positions = [position_row_to_domain(row) for row in rows]
        live_values = await live_market_values(
            positions, deps.price_ratio_fetcher, fx_client, deps.today_provider()
        )
        positions_with_base_value = []
        for position, live_value in zip(positions, live_values, strict=True):
            if live_value is not None:
                position = position.model_copy(update={"market_value": live_value})
            positions_with_base_value.append(
                (position, await base_currency_value(position, fx_client))
            )

        try:
            weights = compute_weights(positions_with_base_value)
        except ValueError:
            # Empty portfolio, or every position values at 0 -- nothing to
            # divide by, not a server error.
            return MetricsOut(
                position_count=len(rows),
                total_value=None,
                base_currency=BASE_CURRENCY,
                hhi=None,
                effective_positions=None,
                top5_share=None,
                allocation_by_asset_class={},
                allocation_by_currency={},
            )

        total_value = sum((w.base_currency_value for w in weights.weighted_positions), Decimal(0))
        return MetricsOut(
            position_count=len(rows),
            total_value=total_value,
            base_currency=BASE_CURRENCY,
            hhi=weights.hhi.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
            effective_positions=weights.effective_positions.quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            ),
            top5_share=_as_percent(weights.top5_share),
            allocation_by_asset_class={
                key: _as_percent(value) for key, value in weights.allocation_by_asset_class.items()
            },
            allocation_by_currency={
                key: _as_percent(value) for key, value in weights.allocation_by_currency.items()
            },
        )

    return router

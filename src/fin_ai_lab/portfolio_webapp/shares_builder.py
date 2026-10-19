"""Shares of a breakdown (portfolio-webapp-S11): values the scope's current
positions exactly as the valuation view does (REQ-084 -- the pie and the
header's total always agree), then hands them to breakdowns.py's pure tree
logic and turns the result into the API's SharesOut."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import duckdb

from fin_ai_lab.portfolio_webapp.breakdowns import (
    BUILTIN_NAMES,
    Breakdown,
    Holding,
    ShareNode,
    builtin_tree,
    custom_tree,
    share,
)
from fin_ai_lab.portfolio_webapp.instruments import asset_assignments
from fin_ai_lab.portfolio_webapp.instruments_builder import load_link_state
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow
from fin_ai_lab.portfolio_webapp.schemas import ShareNodeOut, SharesOut, ValuationOut
from fin_ai_lab.portfolio_webapp.valuation import BASE_CURRENCY, fx_currency_code
from fin_ai_lab.portfolio_webapp.valuation_builder import (
    DailyClosesFetcher,
    FxSeriesClient,
    build_valuation,
)

MONEY = Decimal("0.01")
PERCENT = Decimal("0.1")
ALL_PORTFOLIOS_NAME = "Wszystkie portfele"


async def build_shares(
    connection: duckdb.DuckDBPyConnection,
    portfolio_rows: list[PortfolioRow],
    *,
    builtin: str | None,
    breakdown: Breakdown | None,
    root_name: str,
    today: date,
    closes_fetcher: DailyClosesFetcher,
    fx_client: FxSeriesClient,
) -> SharesOut:
    """Exactly one of `builtin` (a BUILTIN_NAMES key) or `breakdown`."""
    link_state = load_link_state(connection)
    # refresh=False: an explicit "odśwież" goes through the valuation
    # endpoint, which rewrites today's quote cache -- this call then reads it.
    valuation = await build_valuation(
        connection,
        portfolio_rows,
        today=today,
        refresh=False,
        closes_fetcher=closes_fetcher,
        fx_client=fx_client,
        link_state=link_state,
    )
    holdings = holdings_from_valuation(valuation)

    if breakdown is not None:
        assignments = asset_assignments(breakdown.assignments, link_state.identities)
        tree = custom_tree(breakdown.groups, assignments, holdings, root_name=root_name)
        breakdown_id, breakdown_name = str(breakdown.id), breakdown.name
    else:
        assert builtin is not None
        tree = builtin_tree(builtin, holdings, root_name=root_name)
        breakdown_id, breakdown_name = builtin, BUILTIN_NAMES[builtin]

    total = tree.value
    return SharesOut(
        breakdown_id=breakdown_id,
        breakdown_name=breakdown_name,
        base_currency=BASE_CURRENCY,
        total_value=_money(total),
        prices_as_of=valuation.prices_as_of,
        root=_to_out(tree, parent_value=total, total=total),
        warnings=valuation.warnings,
    )


def holdings_from_valuation(valuation: ValuationOut) -> list[Holding]:
    names: dict[UUID, str] = {p.id: p.name for p in valuation.portfolios}
    # Name, class and currency are the asset's (S12), not each broker's own:
    # one asset joined across brokers must land in one group of a built-in
    # breakdown, whatever each broker recorded.
    assets = {asset.instrument_key: asset for asset in valuation.assets}
    holdings = []
    for position in valuation.positions:
        # A position without any valuation is already a warning in the
        # valuation itself; a share of an unknown value would be a guess.
        if position.value is None:
            continue
        asset = assets.get(position.instrument_key)
        quote_currency = asset.quote_currency if asset is not None else position.quote_currency
        holdings.append(
            Holding(
                key=position.instrument_key,
                name=asset.instrument_name if asset is not None else position.instrument_name,
                symbol=(asset.symbol or asset.isin) if asset is not None else position.symbol,
                value=position.value,
                asset_class=asset.asset_class if asset is not None else position.asset_class,
                # Quote currency when known (a USD stock in a PLN account is
                # USD exposure), else the currency the broker recorded.
                currency=(
                    fx_currency_code(quote_currency) if quote_currency else position.price_currency
                ),
                portfolio_id=position.portfolio_id,
                portfolio_name=names.get(position.portfolio_id, ""),
            )
        )
    return holdings


def _to_out(node: ShareNode, *, parent_value: Decimal, total: Decimal) -> ShareNodeOut:
    value = node.value
    return ShareNodeOut(
        id=node.id,
        name=node.name,
        kind=node.kind,
        value=_money(value),
        share_of_parent=share(value, parent_value).quantize(PERCENT, ROUND_HALF_UP),
        share_of_total=share(value, total).quantize(PERCENT, ROUND_HALF_UP),
        asset_count=node.asset_count,
        symbol=node.holding.symbol if node.holding else None,
        portfolio_name=node.holding.portfolio_name if node.holding else None,
        children=[_to_out(child, parent_value=value, total=total) for child in node.children],
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)

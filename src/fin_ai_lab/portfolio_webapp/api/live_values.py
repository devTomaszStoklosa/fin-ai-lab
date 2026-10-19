"""Live market values of positions: today's price and FX moves since import."""

import asyncio
from collections.abc import Callable
from datetime import date as date_type
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.defaults import BASE_CURRENCY
from fin_ai_lab.portfolio_webapp.valuation import MissingFxRateError, fx_currency_code, fx_move
from fin_ai_lab.portfolio_webapp.valuation_builder import FxSeriesClient
from fin_ai_lab.portfolio_webapp.yahoo_ticker import position_yahoo_ticker
from fin_ai_lab.portfolio_xray.canonical import Position

# Margin before an import date for its NBP rate: an import made on a
# weekend or holiday is valued at the last rate published before it.
_LIVE_FX_LOOKBACK = timedelta(days=10)


async def live_market_values(
    positions: list[Position],
    price_ratio_fetcher: Callable[[str, date_type], Decimal | None],
    fx_client: FxSeriesClient,
    today: date_type,
) -> list[Decimal | None]:
    # Price ratios first, exchange rates second: NBP is only asked about the
    # currencies of positions that got a live price, once per request (#283).
    ratios = [await _live_price_ratio(position, price_ratio_fetcher) for position in positions]
    priced = [
        position for position, ratio in zip(positions, ratios, strict=True) if ratio is not None
    ]
    fx_rates = await _live_fx_rates(priced, fx_client, today)
    return [
        None if ratio is None else _live_market_value(position, ratio, fx_rates, today)
        for position, ratio in zip(positions, ratios, strict=True)
    ]


def _live_market_value(
    position: Position,
    ratio: Decimal,
    fx_rates: dict[str, dict[date_type, Decimal]],
    today: date_type,
) -> Decimal:
    # The price ratio applied to the already-stored (already-correct-
    # currency) value -- the quote's own unit is never taken as the
    # account's currency (#188). A listing quoted in another currency also
    # moves with that currency's exchange rate since the import (#283),
    # the same factor as the day-by-day valuation's.
    assert position.market_value is not None  # _live_price_ratio checked it
    value = position.market_value * ratio * _live_fx_move(position, fx_rates, today)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _live_fx_move(
    position: Position, fx_rates: dict[str, dict[date_type, Decimal]], today: date_type
) -> Decimal:
    if position.market_currency is None:
        return Decimal(1)
    try:
        return fx_move(
            position.market_currency,
            position.quote_currency,
            position.valuation_date,
            today,
            fx_rates,
        )
    except MissingFxRateError:
        # No NBP rates for the currency (see _live_fx_rates): only the
        # exchange-rate factor is left out, the price move still counts --
        # the same rule as valuation.unit_value_series.
        return Decimal(1)


async def _live_fx_rates(
    positions: list[Position], fx_client: FxSeriesClient, today: date_type
) -> dict[str, dict[date_type, Decimal]]:
    # One NBP series per currency an exchange-rate factor needs. Same call
    # as the day-by-day valuation's, so both share its on-disk cache and
    # agree on today's rate. A currency NBP has no rates for, or a failed
    # request, is simply left out.
    start_by_currency: dict[str, date_type] = {}
    for position in positions:
        start = position.valuation_date - _LIVE_FX_LOOKBACK
        for currency in _fx_move_currencies(position):
            start_by_currency[currency] = min(start_by_currency.get(currency, start), start)

    fx_rates: dict[str, dict[date_type, Decimal]] = {}
    for currency, start in start_by_currency.items():
        try:
            fx_rates[currency] = await fx_client.mid_rate_series(currency, start, today)
        except Exception:
            # NBP down, or no table A/B rate for the currency -- a live
            # value must still come back, moved by its price alone.
            continue
    return fx_rates


def _fx_move_currencies(position: Position) -> set[str]:
    if position.market_currency is None or position.quote_currency is None:
        return set()
    quote_code = fx_currency_code(position.quote_currency)
    if quote_code == position.market_currency:
        return set()
    return {quote_code, position.market_currency} - {BASE_CURRENCY}


async def _live_price_ratio(
    position: Position, price_ratio_fetcher: Callable[[str, date_type], Decimal | None]
) -> Decimal | None:
    # Ratio of latest close to the close on the position's own valuation
    # date. Manual positions are the owner's own explicit input, left
    # untouched.
    if position.broker == repository.MANUAL_BROKER:
        return None
    if position.market_value is None or position.quantity <= 0:
        return None
    yfinance_ticker = position_yahoo_ticker(
        broker=position.broker,
        symbol=position.symbol,
        ticker=position.ticker,
        exchange_code=position.exchange_code,
    )
    if yfinance_ticker is None:
        return None

    try:
        return await asyncio.to_thread(
            price_ratio_fetcher, yfinance_ticker, position.valuation_date
        )
    except Exception:
        # yfinance is unofficial and sometimes blocked (docs/DATA-SOURCES.md)
        # -- a live-refresh failure must fall back to the stored value, never
        # break the page.
        return None

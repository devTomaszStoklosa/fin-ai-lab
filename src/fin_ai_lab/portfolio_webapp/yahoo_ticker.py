"""Which Yahoo Finance symbol prices a stored position (fin-ai-lab#250).

One lookup for the value history and the live value of the positions list,
so the two can't price the same position differently.
"""

from fin_ai_lab.portfolio_webapp.lots import XTB_BROKER
from fin_ai_lab.portfolio_webapp.xtb_symbols import yahoo_symbol
from fin_ai_lab.portfolio_xray.metrics.price_history import to_yahoo_ticker


def position_yahoo_ticker(
    *, broker: str, symbol: str | None, ticker: str | None, exchange_code: str | None
) -> str | None:
    """OpenFIGI's ticker translated to Yahoo's suffix when the lookup
    resolved. Otherwise the broker's own symbol: XTB's ("GOOGL.US") is
    unknown to Yahoo until its suffix is translated too, and one with a
    suffix nobody has seen gives None (reported, never guessed)."""
    if ticker is not None:
        return to_yahoo_ticker(ticker, exchange_code)
    if symbol is None:
        return None
    if broker == XTB_BROKER:
        return yahoo_symbol(symbol)
    return symbol

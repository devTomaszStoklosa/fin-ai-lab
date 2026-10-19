from fin_ai_lab.portfolio_webapp.yahoo_ticker import position_yahoo_ticker


def test_resolved_ticker_is_translated_to_yahoo_suffix() -> None:
    assert (
        position_yahoo_ticker(broker="xtb", symbol="ISAC.UK", ticker="ISAC", exchange_code="LN")
        == "ISAC.L"
    )


def test_unresolved_xtb_symbol_is_translated_to_yahoo_form() -> None:
    # The issue's case (#250): Yahoo knows GOOGL, not GOOGL.US.
    assert (
        position_yahoo_ticker(broker="xtb", symbol="GOOGL.US", ticker=None, exchange_code=None)
        == "GOOGL"
    )


def test_unresolved_xtb_symbol_without_a_known_suffix_is_not_guessed() -> None:
    assert (
        position_yahoo_ticker(broker="xtb", symbol="SOLANA", ticker=None, exchange_code=None)
        is None
    )


def test_other_brokers_keep_their_own_symbol() -> None:
    assert (
        position_yahoo_ticker(broker="bossa", symbol="ATR", ticker=None, exchange_code=None)
        == "ATR"
    )


def test_no_symbol_and_no_ticker_gives_none() -> None:
    assert position_yahoo_ticker(broker="xtb", symbol=None, ticker=None, exchange_code=None) is None

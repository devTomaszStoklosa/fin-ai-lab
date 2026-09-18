from collections.abc import Callable
from decimal import Decimal

from fin_ai_lab.market_pulse.indicators import fetch_indicators
from fin_ai_lab.market_pulse.regime import classify_regime
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient
from fin_ai_lab.portfolio_xray.canonical import Portfolio
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient, convert_to_base_currency
from fin_ai_lab.portfolio_xray.metrics.weights import compute_weights


def build_tools(
    portfolio: Portfolio,
    fred_client: FredClient,
    nbp_client: NbpClient,
    *,
    fx_client: NbpFxClient | None = None,
) -> list[Callable]:
    """Tools for P5-S1's single-agent baseline, built the same way P3-S2's
    agent.py builds its tools — plain callables with model-facing
    docstrings, handed to the SDK's automatic function calling.

    P1 and P3 are real, zero-LLM-call tools (pure computation — REQ-004:
    the agent reads already-computed numbers, it never asks a tool to
    recompute or reclassify something an LLM would have to reason about
    twice). P2 and P4 are explicit stubs: P2's retrieval store is
    expensive to build (SEC fetch + embeddings) for one tool among many
    here, and P4 has no trained/persisted model yet — wiring either for
    real is follow-up work, not this slice's job. 02-spec.md's edge
    cases explicitly sanction this: an unready dependency is a visible
    stub, never a silent fiction."""
    fx = fx_client or NbpFxClient()

    async def get_portfolio_allocation() -> str:
        """Get this portfolio's current allocation: weight by asset
        class, by currency, by account type, plus concentration metrics
        (HHI, effective number of positions, top-5 share). Values are
        computed directly from the imported portfolio, not estimated."""
        positions_with_base_value = [
            (position, await _base_currency_value(position, portfolio, fx))
            for position in portfolio.positions
        ]
        weights = compute_weights(positions_with_base_value)
        return (
            f"Alokacja wg klasy aktywów: {_format_allocation(weights.allocation_by_asset_class)}. "
            f"Wg waluty: {_format_allocation(weights.allocation_by_currency)}. "
            f"Wg typu konta: {_format_allocation(weights.allocation_by_account_type)}. "
            f"HHI: {weights.hhi}, efektywna liczba pozycji: {weights.effective_positions}, "
            f"udział top-5: {weights.top5_share}."
        )

    async def get_market_regime() -> str:
        """Get the current US/PL market regime (risk-on/neutral/risk-off)
        and the indicator values behind it — the same deterministic
        classification market-pulse uses for its daily brief."""
        indicators, missing = await fetch_indicators(fred_client, nbp_client)
        regime = classify_regime(indicators)
        signals = "; ".join(regime.signals) if regime.signals else "brak sygnałów progowych"
        missing_note = f" Brakujące źródła: {', '.join(missing)}." if missing else ""
        return f"Reżim rynku: {regime.regime}. Sygnały: {signals}.{missing_note}"

    async def ask_about_filings(question: str) -> str:
        """Ask a question about an indexed company's SEC filing or GPW
        annual report. Not yet wired to P2's real retrieval in P5-S1 —
        returns a stub, not a fabricated answer."""
        return (
            f"Narzędzie P2 (sprawozdania) nie jest jeszcze podłączone w P5-S1 — "
            f"pytanie '{question}' nie zostało odpowiedziane."
        )

    async def get_news_sentiment(headline: str) -> str:
        """Get the sentiment/event-type classification for a Polish
        financial news headline. Not yet wired to a trained P4 model —
        returns a stub, not a guessed classification."""
        return (
            f"Narzędzie P4 (klasyfikator newsów) nie ma jeszcze wytrenowanego modelu — "
            f"nagłówek '{headline}' nie został sklasyfikowany."
        )

    return [get_portfolio_allocation, get_market_regime, ask_about_filings, get_news_sentiment]


async def _base_currency_value(position, portfolio: Portfolio, fx_client: NbpFxClient) -> Decimal:
    if position.market_value is None or position.market_currency is None:
        return Decimal(0)
    return await convert_to_base_currency(
        position.market_value, position.market_currency, portfolio.valuation_date, fx_client
    )


def _format_allocation(allocation: dict[str, Decimal]) -> str:
    return ", ".join(f"{key}: {value:.2%}" for key, value in allocation.items())

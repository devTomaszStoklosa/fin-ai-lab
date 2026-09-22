import asyncio
from collections.abc import Callable
from datetime import date

from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.identification.openfigi import Identification, OpenFigiClient
from fin_ai_lab.portfolio_xray.importer import ImportResult, deduplicate_positions, import_xlsx
from fin_ai_lab.portfolio_xray.ledger import (
    BossaTransaction,
    attach_current_market_values,
    parse_bossa_csv,
    transactions_to_positions,
)
from fin_ai_lab.portfolio_xray.metrics.price_history import to_yahoo_ticker
from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig
from fin_ai_lab.portfolio_xray.parsers.correction import (
    CorrectionLoopError,
    propose_and_validate_config,
)
from fin_ai_lab.portfolio_xray.parsers.reader import find_matching_config, read_xlsx_sheets
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from fin_ai_lab.portfolio_xray.privacy.injection import flag_suspicious_cells

# Called with (proposed config, positions it would produce) before the config
# is written to the registry; return True to accept it. Defaults to
# accepting everything, so callers that don't care (e.g. tests) don't need
# to pass one — the CLI always passes an interactive confirmation instead.
ApprovalCallback = Callable[[ParserConfig, list[Position]], bool]


async def import_file(
    file_bytes: bytes,
    *,
    valuation_date: date,
    account_type: AccountType,
    market_currency: str,
    registry: ParserRegistry,
    broker_hint: str | None = None,
    llm_client: LlmClient | None = None,
    prompt_registry: PromptRegistry | None = None,
    model: str | None = None,
    on_new_config_proposed: ApprovalCallback | None = None,
    openfigi_client: OpenFigiClient | None = None,
    broker_market: str | None = None,
    quote_currency_fetcher: Callable[[str], str | None] | None = None,
) -> ImportResult:
    sheets = read_xlsx_sheets(file_bytes)
    injection_flags = _flag_all_sheets(sheets)

    match = find_matching_config(sheets, registry)
    if match is not None:
        result = import_xlsx(
            file_bytes,
            valuation_date=valuation_date,
            account_type=account_type,
            market_currency=market_currency,
            registry=registry,
        )
        positions = await _resolve_identifications(
            result.positions, openfigi_client, broker_market, quote_currency_fetcher
        )
        return result.model_copy(
            update={"positions": positions, "warnings": result.warnings + injection_flags}
        )

    if llm_client is None or prompt_registry is None or model is None or broker_hint is None:
        return ImportResult(positions=[], errors=["Unknown file format"], warnings=injection_flags)

    try:
        config, positions = await propose_and_validate_config(
            llm_client,
            prompt_registry,
            model,
            sheets,
            broker=broker_hint,
            version=registry.next_version(broker_hint),
            account_type=account_type,
            market_currency=market_currency,
            valuation_date=valuation_date,
        )
    except CorrectionLoopError as exc:
        return ImportResult(positions=[], errors=[str(exc)], warnings=injection_flags)

    approved = on_new_config_proposed(config, positions) if on_new_config_proposed else True
    if not approved:
        return ImportResult(
            positions=[],
            errors=["New parser configuration was not approved"],
            warnings=injection_flags,
        )

    registry.save(config)
    merged, dedup_warnings = deduplicate_positions(positions)
    merged = await _resolve_identifications(
        merged, openfigi_client, broker_market, quote_currency_fetcher
    )
    return ImportResult(positions=merged, errors=[], warnings=dedup_warnings + injection_flags)


async def import_bossa_csv(
    file_bytes: bytes,
    *,
    valuation_date: date,
    account_type: AccountType,
    openfigi_client: OpenFigiClient | None = None,
    broker_market: str | None = None,
    quote_currency_fetcher: Callable[[str], str | None] | None = None,
) -> ImportResult:
    """Bossa's own path, parallel to import_file: its export is a
    transaction ledger, not a position snapshot (no registry, no LLM
    correction loop — those assume one row maps to one position), so
    positions come from replaying the whole ledger deterministically
    (ledger.py) rather than from column mapping."""
    try:
        transactions = parse_bossa_csv(file_bytes)
    except ValueError as exc:
        return ImportResult(positions=[], errors=[str(exc)], warnings=[])

    return await build_bossa_import_result(
        transactions,
        account_type=account_type,
        valuation_date=valuation_date,
        openfigi_client=openfigi_client,
        broker_market=broker_market,
        quote_currency_fetcher=quote_currency_fetcher,
    )


async def build_bossa_import_result(
    transactions: list[BossaTransaction],
    *,
    account_type: AccountType,
    valuation_date: date,
    openfigi_client: OpenFigiClient | None = None,
    broker_market: str | None = None,
    quote_currency_fetcher: Callable[[str], str | None] | None = None,
) -> ImportResult:
    """The replay -> resolve -> attach tail of import_bossa_csv, split out so
    a caller that already has a transaction list (portfolio_webapp, replaying
    the complete stored ledger across multiple imports -- 02-spec.md
    REQ-021) can reuse it without re-parsing a file each time."""
    positions, errors = transactions_to_positions(
        transactions, account_type=account_type, valuation_date=valuation_date
    )
    if errors:
        return ImportResult(positions=[], errors=errors, warnings=[])

    positions = await _resolve_identifications(
        positions, openfigi_client, broker_market, quote_currency_fetcher
    )
    positions = attach_current_market_values(positions)
    return ImportResult(positions=positions, errors=[], warnings=[])


# XTB's "Open Positions" export has no ISIN column at all -- its own ticker
# suffix ("ISAC.UK") isn't a standard exchange code either, so it needs
# translating before an OpenFIGI ticker lookup. Only markets actually
# observed in real XTB data are mapped, same "observed data only" rule as
# importer.py's CATEGORY_TO_ASSET_CLASS -- deliberately deferred fallback
# from 03-design.md, picked up for issue #192 (UK/PL) and #199 (US/NL).
# "US" is OpenFIGI's composite US code, not NYSE/NASDAQ-specific -- XTB's
# own ".US" suffix doesn't distinguish those either, so this is the right
# granularity, verified live to resolve real tickers correctly.
_XTB_SUFFIX_TO_OPENFIGI_EXCHANGE = {"UK": "LN", "PL": "PW", "US": "US", "NL": "NA"}


def _xtb_ticker_and_exchange(symbol: str) -> tuple[str, str] | None:
    base, dot, suffix = symbol.rpartition(".")
    if not dot or not base:
        return None
    exch_code = _XTB_SUFFIX_TO_OPENFIGI_EXCHANGE.get(suffix)
    return (base, exch_code) if exch_code is not None else None


async def _resolve_identifications(
    positions: list[Position],
    openfigi_client: OpenFigiClient | None,
    broker_market: str | None,
    quote_currency_fetcher: Callable[[str], str | None] | None = None,
) -> list[Position]:
    if openfigi_client is None:
        return positions

    resolved = []
    for position in positions:
        if position.isin is not None:
            currency = position.market_currency or position.cost_currency or "PLN"
            identification = await openfigi_client.resolve_by_isin(
                position.isin, currency, broker_market
            )
        elif position.broker == "xtb" and position.symbol is not None:
            split = _xtb_ticker_and_exchange(position.symbol)
            if split is None:
                resolved.append(position)
                continue
            identification = await openfigi_client.resolve_by_ticker(*split)
        else:
            resolved.append(position)
            continue

        quote_currency = await _fetch_quote_currency(identification, quote_currency_fetcher)
        resolved.append(
            position.model_copy(
                update={
                    "resolution_status": identification.status,
                    "figi": identification.figi,
                    "ticker": identification.ticker,
                    "exchange_code": identification.exchange_code,
                    "identification_rule": identification.identification_rule,
                    "quote_currency": quote_currency,
                }
            )
        )
    return resolved


async def _fetch_quote_currency(
    identification: Identification,
    quote_currency_fetcher: Callable[[str], str | None] | None,
) -> str | None:
    if quote_currency_fetcher is None or identification.ticker is None:
        return None
    yfinance_ticker = to_yahoo_ticker(identification.ticker, identification.exchange_code)
    try:
        return await asyncio.to_thread(quote_currency_fetcher, yfinance_ticker)
    except Exception:
        # yfinance is unofficial and sometimes blocked (docs/DATA-SOURCES.md)
        # -- a failed lookup must not break the import, quote_currency is
        # purely informational.
        return None


def _flag_all_sheets(sheets: dict[str, list[tuple[object, ...]]]) -> list[str]:
    flags: list[str] = []
    for sheet_name, rows in sheets.items():
        for flag in flag_suspicious_cells(rows):
            flags.append(f"{sheet_name}, {flag}")
    return flags

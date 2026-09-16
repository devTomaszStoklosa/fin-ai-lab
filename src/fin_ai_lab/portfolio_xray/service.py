from collections.abc import Callable
from datetime import date

from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.importer import ImportResult, deduplicate_positions, import_xlsx
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
        return result.model_copy(update={"warnings": result.warnings + injection_flags})

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
    return ImportResult(positions=merged, errors=[], warnings=dedup_warnings + injection_flags)


def _flag_all_sheets(sheets: dict[str, list[tuple[object, ...]]]) -> list[str]:
    flags: list[str] = []
    for sheet_name, rows in sheets.items():
        for flag in flag_suspicious_cells(rows):
            flags.append(f"{sheet_name}, {flag}")
    return flags

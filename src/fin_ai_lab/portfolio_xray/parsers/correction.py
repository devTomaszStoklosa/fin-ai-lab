from datetime import date

from pydantic import ValidationError

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.importer import build_position
from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig, ParserConfigProposal
from fin_ai_lab.portfolio_xray.parsers.reader import apply_row_filter, rows_as_dicts
from fin_ai_lab.portfolio_xray.privacy.pii import classify_pii_columns

MAX_CORRECTION_ATTEMPTS = 2
SAMPLE_ROWS_PER_SHEET = 20


class CorrectionLoopError(Exception):
    pass


def render_masked_sample(sheets: dict[str, list[tuple[object, ...]]]) -> str:
    blocks = []
    for sheet_name, rows in sheets.items():
        sample = rows[:SAMPLE_ROWS_PER_SHEET]
        masked_sample = _mask_sample_rows(sample)
        lines = [f"Sheet: {sheet_name}"]
        for row in masked_sample:
            lines.append(" | ".join("" if cell is None else str(cell) for cell in row))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _mask_sample_rows(
    rows: list[tuple[object, ...]],
) -> list[tuple[object, ...]]:
    # We don't yet know which row is the real header, so any cell in the
    # sample that itself looks like a PII column label marks its whole
    # column for masking — the label stays visible, values under it don't.
    pii_columns: set[int] = set()
    for row in rows:
        for index, cell in enumerate(row):
            if isinstance(cell, str) and classify_pii_columns([cell]):
                pii_columns.add(index)

    masked_rows = []
    for row in rows:
        masked_row = list(row)
        for index in pii_columns:
            if index >= len(masked_row):
                continue
            cell = masked_row[index]
            is_the_label_itself = isinstance(cell, str) and classify_pii_columns([cell])
            if cell not in (None, "") and not is_the_label_itself:
                masked_row[index] = "[MASKED]"
        masked_rows.append(tuple(masked_row))
    return masked_rows


async def propose_parser_config(
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    masked_sample: str,
    feedback: str = "",
) -> ParserConfigProposal:
    prompt = prompt_registry.get("propose_config", 2)
    rendered = prompt.render(sample=masked_sample, feedback=feedback)

    request = LlmRequest(
        model=model,
        messages=[{"role": "user", "text": rendered}],
        response_schema=ParserConfigProposal,
        prompt_id="propose_config",
        prompt_version=2,
    )
    result = await llm_client.complete(request)
    if not isinstance(result.parsed, ParserConfigProposal):
        raise CorrectionLoopError("Model did not return a valid configuration proposal")
    return result.parsed


async def propose_and_validate_config(
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    sheets: dict[str, list[tuple[object, ...]]],
    *,
    broker: str,
    version: int,
    account_type: AccountType,
    market_currency: str,
    valuation_date: date,
) -> tuple[ParserConfig, list[Position]]:
    masked_sample = render_masked_sample(sheets)
    feedback = ""
    errors: list[str] = []

    for _attempt in range(MAX_CORRECTION_ATTEMPTS + 1):
        proposal = await propose_parser_config(
            llm_client, prompt_registry, model, masked_sample, feedback
        )
        proposal_data = proposal.model_dump()
        proposal_data["column_mapping"] = {
            entry["file_header"]: entry["field"] for entry in proposal_data["column_mapping"]
        }
        config = ParserConfig(broker=broker, version=version, **proposal_data)

        if config.sheet_name not in sheets:
            errors = [f"Sheet '{config.sheet_name}' not found in file"]
            feedback = _feedback_text(errors, [])
            continue

        rows = rows_as_dicts(sheets[config.sheet_name], config.header_row)
        rows = apply_row_filter(rows, config.row_filter)

        positions: list[Position] = []
        errors = []
        failing_rows: list[str] = []
        for row_number, row in rows:
            try:
                position = build_position(
                    row,
                    config.column_mapping,
                    broker=broker,
                    account_type=account_type,
                    market_currency=market_currency,
                    valuation_date=valuation_date,
                )
            except ValidationError as exc:
                message = exc.errors()[0]["msg"].removeprefix("Value error, ")
                errors.append(f"{message} in row {row_number}")
                failing_rows.append(f"row {row_number}: {row}")
            else:
                positions.append(position)

        if not errors:
            return config, positions

        feedback = _feedback_text(errors, failing_rows)

    raise CorrectionLoopError(
        f"Parser configuration still invalid after {MAX_CORRECTION_ATTEMPTS} corrections: {errors}"
    )


def _feedback_text(errors: list[str], failing_rows: list[str]) -> str:
    parts = ["The previous configuration failed validation:", *errors]
    if failing_rows:
        parts += ["Rows that failed:", *failing_rows]
    return "\n".join(parts)

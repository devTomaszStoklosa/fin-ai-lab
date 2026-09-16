import asyncio
import importlib.metadata
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import get_args

import typer

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.errors import BudgetExceeded, SuiteError
from fin_ai_lab.core.evals.runner import run_suite
from fin_ai_lab.core.llm.client import GeminiLlmClient, LlmClient
from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_xray.canonical import AccountType
from fin_ai_lab.portfolio_xray.importer import import_xlsx
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry

app = typer.Typer()
portfolio_app = typer.Typer()
app.add_typer(portfolio_app, name="portfolio")

EVALS_DIR = Path("evals")


@app.command()
def version() -> None:
    typer.echo(importlib.metadata.version("fin-ai-lab"))


@app.command("eval")
def eval_command(
    suite: str,
    split: str = typer.Option("dev", "--split"),
    repeats: int | None = typer.Option(None, "--repeats"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    save_baseline: bool = typer.Option(False, "--save-baseline"),
    yes: bool = typer.Option(False, "--yes"),
    max_cost: str | None = typer.Option(None, "--max-cost"),
) -> None:
    settings = Settings()
    llm_client = _build_llm_client(settings)
    prompts = PromptRegistry()

    try:
        summary, run_dir = asyncio.run(
            run_suite(
                EVALS_DIR / suite,
                split=split,
                repeats_override=repeats,
                use_cache=not no_cache,
                save_baseline=save_baseline,
                yes=yes,
                max_cost_override=Decimal(max_cost) if max_cost else None,
                interactive=sys.stdin.isatty(),
                confirm_fn=typer.confirm,
                settings=settings,
                llm_client=llm_client,
                prompts=prompts,
            )
        )
    except (SuiteError, BudgetExceeded) as exc:
        typer.echo(f"Aborted: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Run written to {run_dir}")
    typer.echo(f"Cost: {summary.cost_usd} USD, incomplete: {summary.incomplete}")
    if summary.incomplete:
        raise typer.Exit(code=1)


@portfolio_app.command("import")
def import_positions(
    file: Path,
    valuation_date: str = typer.Option(..., "--valuation-date", help="YYYY-MM-DD"),
    account_type: str = typer.Option("regular", "--account-type"),
    market_currency: str = typer.Option("PLN", "--market-currency"),
) -> None:
    if account_type not in get_args(AccountType):
        typer.echo(f"Invalid account type '{account_type}'", err=True)
        raise typer.Exit(code=1)

    parsed_date = datetime.strptime(valuation_date, "%Y-%m-%d").date()
    registry = ParserRegistry()
    result = import_xlsx(
        file.read_bytes(),
        valuation_date=parsed_date,
        account_type=account_type,
        market_currency=market_currency,
        registry=registry,
    )

    if result.errors:
        for error in result.errors:
            typer.echo(error, err=True)
        raise typer.Exit(code=1)

    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")
    for position in result.positions:
        typer.echo(
            f"{position.symbol or position.instrument_name}: {position.quantity} "
            f"@ {position.avg_cost} {position.market_currency} "
            f"(value {position.market_value} {position.market_currency}, "
            f"{position.asset_class}, {position.resolution_status})"
        )
    typer.echo(f"{len(result.positions)} positions imported")


def _build_llm_client(settings: Settings) -> LlmClient:
    if settings.gemini_api_key:
        return GeminiLlmClient(api_key=settings.gemini_api_key)
    return FakeLlmClient({})

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
from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from fin_ai_lab.portfolio_xray.report.builder import ReportRejectedError
from fin_ai_lab.portfolio_xray.report.orchestrator import ReportGenerationError, generate_report
from fin_ai_lab.portfolio_xray.service import import_file

PORTFOLIO_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/parsers/prompts")
SECTOR_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/sectors/prompts")
REPORT_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/report/prompts")

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
    prompts.load_dir(PORTFOLIO_PROMPTS_DIR)
    prompts.load_dir(SECTOR_PROMPTS_DIR)
    prompts.load_dir(REPORT_PROMPTS_DIR)

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
    broker: str | None = typer.Option(
        None, "--broker", help="Required only if the file's format is not yet recognized."
    ),
    model: str = typer.Option("gemini-3.6-flash", "--model"),
    yes: bool = typer.Option(
        False, "--yes", help="Accept a newly proposed parser config without asking."
    ),
    broker_market: str | None = typer.Option(
        None, "--broker-market", help="Exchange code to prefer when an ISIN has several listings."
    ),
    no_identify: bool = typer.Option(
        False, "--no-identify", help="Skip OpenFIGI lookups for positions that have an ISIN."
    ),
) -> None:
    if account_type not in get_args(AccountType):
        typer.echo(f"Invalid account type '{account_type}'", err=True)
        raise typer.Exit(code=1)

    parsed_date = datetime.strptime(valuation_date, "%Y-%m-%d").date()
    settings = Settings()
    llm_client = _build_llm_client(settings)
    prompt_registry = PromptRegistry()
    prompt_registry.load_dir(PORTFOLIO_PROMPTS_DIR)
    registry = ParserRegistry()

    def approve(config: ParserConfig, positions: list[Position]) -> bool:
        return _confirm_new_config(config, positions, yes)

    result = asyncio.run(
        import_file(
            file.read_bytes(),
            valuation_date=parsed_date,
            account_type=account_type,
            market_currency=market_currency,
            registry=registry,
            broker_hint=broker,
            llm_client=llm_client,
            prompt_registry=prompt_registry,
            model=model,
            on_new_config_proposed=approve,
            openfigi_client=None if no_identify else OpenFigiClient(),
            broker_market=broker_market,
        )
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


@portfolio_app.command("report")
def report_command(
    file: Path,
    valuation_date: str = typer.Option(..., "--valuation-date", help="YYYY-MM-DD"),
    account_type: str = typer.Option("regular", "--account-type"),
    market_currency: str = typer.Option("PLN", "--market-currency"),
    broker: str | None = typer.Option(
        None, "--broker", help="Required only if the file's format is not yet recognized."
    ),
    model: str = typer.Option("gemini-3.6-flash", "--model"),
    yes: bool = typer.Option(
        False, "--yes", help="Accept a newly proposed parser config without asking."
    ),
    broker_market: str | None = typer.Option(
        None, "--broker-market", help="Exchange code to prefer when an ISIN has several listings."
    ),
    benchmark_ticker: str | None = typer.Option(
        None,
        "--benchmark-ticker",
        help="Yahoo Finance ticker for beta (REQ-031: no default benchmark is assumed).",
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Write the report to this file instead of stdout."
    ),
) -> None:
    if account_type not in get_args(AccountType):
        typer.echo(f"Invalid account type '{account_type}'", err=True)
        raise typer.Exit(code=1)

    parsed_date = datetime.strptime(valuation_date, "%Y-%m-%d").date()
    settings = Settings()
    llm_client = _build_llm_client(settings)
    prompt_registry = PromptRegistry()
    prompt_registry.load_dir(PORTFOLIO_PROMPTS_DIR)
    prompt_registry.load_dir(SECTOR_PROMPTS_DIR)
    prompt_registry.load_dir(REPORT_PROMPTS_DIR)
    registry = ParserRegistry()

    def approve(config: ParserConfig, positions: list[Position]) -> bool:
        return _confirm_new_config(config, positions, yes)

    try:
        report_text = asyncio.run(
            generate_report(
                file.read_bytes(),
                valuation_date=parsed_date,
                account_type=account_type,
                market_currency=market_currency,
                registry=registry,
                llm_client=llm_client,
                prompt_registry=prompt_registry,
                model=model,
                broker_hint=broker,
                on_new_config_proposed=approve,
                openfigi_client=OpenFigiClient(),
                broker_market=broker_market,
                benchmark_ticker=benchmark_ticker,
            )
        )
    except ReportGenerationError as exc:
        typer.echo(f"Aborted: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ReportRejectedError as exc:
        typer.echo("Report rejected: numbers not faithful to the computed metrics:", err=True)
        for mismatch in exc.mismatches:
            typer.echo(f"  {mismatch}", err=True)
        raise typer.Exit(code=1) from exc

    if output is not None:
        output.write_text(report_text, encoding="utf-8")
        typer.echo(f"Report written to {output}")
    else:
        typer.echo(report_text)


def _confirm_new_config(config: ParserConfig, positions: list[Position], yes: bool) -> bool:
    typer.echo(f"New format detected. Proposed configuration for broker '{config.broker}':")
    typer.echo(f"  sheet: {config.sheet_name}, header row: {config.header_row}")
    for file_header, field in config.column_mapping.items():
        typer.echo(f"  '{file_header}' -> {field}")
    typer.echo("First rows parsed with this configuration:")
    for position in positions[:5]:
        typer.echo(f"  {position.symbol or position.instrument_name}: {position.quantity}")
    if yes:
        return True
    return typer.confirm("Save this configuration and continue?")


def _build_llm_client(settings: Settings) -> LlmClient:
    if settings.gemini_api_key:
        return GeminiLlmClient(api_key=settings.gemini_api_key)
    return FakeLlmClient({})

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
from fin_ai_lab.market_pulse.agent import ask
from fin_ai_lab.market_pulse.alerts import check_alerts
from fin_ai_lab.market_pulse.brief import build_brief
from fin_ai_lab.market_pulse.indicators import fetch_indicators
from fin_ai_lab.market_pulse.notifications.ntfy import send_alerts
from fin_ai_lab.market_pulse.regime import classify_regime
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient
from fin_ai_lab.market_pulse.sources.news import fetch_news
from fin_ai_lab.market_pulse.state import changes_since_previous, load_previous, save_current
from fin_ai_lab.news_classifier.corpus_store import append_labeled
from fin_ai_lab.news_classifier.ingest.news_rss import collect_headlines
from fin_ai_lab.news_classifier.labeling.progress import (
    headline_key,
    load_labeled_keys,
    save_labeled_keys,
    unlabeled,
)
from fin_ai_lab.news_classifier.labeling.teacher import label_with_teacher
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
FILINGS_RAG_PROMPTS_DIR = Path("src/fin_ai_lab/filings_rag/prompts")
MARKET_PULSE_PROMPTS_DIR = Path("src/fin_ai_lab/market_pulse/prompts")
NEWS_CLASSIFIER_PROMPTS_DIR = Path("src/fin_ai_lab/news_classifier/prompts")

app = typer.Typer()
portfolio_app = typer.Typer()
app.add_typer(portfolio_app, name="portfolio")
market_pulse_app = typer.Typer()
app.add_typer(market_pulse_app, name="market-pulse")
news_classifier_app = typer.Typer()
app.add_typer(news_classifier_app, name="news-classifier")

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
    prompts.load_dir(FILINGS_RAG_PROMPTS_DIR)
    prompts.load_dir(MARKET_PULSE_PROMPTS_DIR)
    prompts.load_dir(NEWS_CLASSIFIER_PROMPTS_DIR)

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


@market_pulse_app.command("brief")
def market_pulse_brief(
    model: str = typer.Option("gemini-3.6-flash", "--model"),
    output: Path | None = typer.Option(
        None, "--output", help="Write the brief to this file instead of stdout."
    ),
) -> None:
    settings = Settings()
    llm_client = _build_llm_client(settings)
    prompt_registry = PromptRegistry()
    prompt_registry.load_dir(MARKET_PULSE_PROMPTS_DIR)

    fred_client = FredClient(settings.require_fred_api_key())
    nbp_client = NbpClient()

    async def run() -> str:
        (indicators, missing_indicator_sources), (news, missing_news_sources) = (
            await asyncio.gather(
                fetch_indicators(fred_client, nbp_client),
                fetch_news(),
            )
        )
        missing_sources = missing_indicator_sources + missing_news_sources
        previous_indicators = load_previous()
        indicators = changes_since_previous(indicators, previous_indicators)
        regime = classify_regime(indicators)
        brief = await build_brief(
            indicators, regime, missing_sources, news, llm_client, prompt_registry, model
        )

        alerts = check_alerts(indicators)
        if alerts:
            await send_alerts(alerts, settings.require_ntfy_topic())

        save_current(indicators)
        return brief.text

    text = asyncio.run(run())
    if output is not None:
        output.write_text(text, encoding="utf-8")
        typer.echo(f"Brief written to {output}")
    else:
        typer.echo(text)


@market_pulse_app.command("ask")
def market_pulse_ask(
    question: str,
    model: str = typer.Option("gemini-3.6-flash", "--model"),
) -> None:
    settings = Settings()
    llm_client = _build_llm_client(settings)
    prompt_registry = PromptRegistry()
    prompt_registry.load_dir(MARKET_PULSE_PROMPTS_DIR)

    fred_client = FredClient(settings.require_fred_api_key())
    nbp_client = NbpClient()

    answer = asyncio.run(
        ask(question, llm_client, prompt_registry, model, fred_client, nbp_client)
    )
    typer.echo(answer.text)


@news_classifier_app.command("label")
def news_classifier_label(
    max_calls: int = typer.Option(15, "--max-calls", help="Teacher calls to spend this run."),
    model: str = typer.Option("gemini-3.6-flash", "--model"),
) -> None:
    settings = Settings()
    llm_client = _build_llm_client(settings)
    prompt_registry = PromptRegistry()
    prompt_registry.load_dir(NEWS_CLASSIFIER_PROMPTS_DIR)

    async def run() -> tuple[int, list[str]]:
        headlines = await collect_headlines()
        already_labeled = load_labeled_keys()
        pending = unlabeled(headlines, already_labeled)

        labeled, errors = await label_with_teacher(
            pending, llm_client, prompt_registry, model, max_calls=max_calls
        )
        if labeled:
            append_labeled(labeled)
            already_labeled.update(headline_key(item.headline) for item in labeled)
            save_labeled_keys(already_labeled)
        return len(labeled), errors

    labeled_count, errors = asyncio.run(run())
    typer.echo(f"Labeled {labeled_count} headlines, {len(errors)} errors")
    for error in errors:
        typer.echo(f"  error: {error}", err=True)


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

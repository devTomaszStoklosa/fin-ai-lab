import asyncio
import importlib.metadata
import sys
from decimal import Decimal
from pathlib import Path

import typer

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.errors import BudgetExceeded, SuiteError
from fin_ai_lab.core.evals.runner import run_suite
from fin_ai_lab.core.llm.client import GeminiLlmClient, LlmClient
from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry

app = typer.Typer()

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


def _build_llm_client(settings: Settings) -> LlmClient:
    if settings.gemini_api_key:
        return GeminiLlmClient(api_key=settings.gemini_api_key)
    return FakeLlmClient({})

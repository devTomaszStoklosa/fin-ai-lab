import asyncio
import json
import random
import string
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.errors import BudgetExceeded, SuiteError
from fin_ai_lab.core.evals._imports import load_target
from fin_ai_lab.core.evals.cache import EvalCache, cache_key
from fin_ai_lab.core.evals.graders import build_grader
from fin_ai_lab.core.evals.loader import load_cases, load_suite
from fin_ai_lab.core.evals.models import Case, CaseResult, RunContext, RunSummary, Suite
from fin_ai_lab.core.evals.report import render_report
from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry

RUNS_DIR = Path("evals/runs")
BASELINES_DIR = Path("evals/baselines")


async def run_suite(
    suite_dir: Path,
    *,
    split: str = "dev",
    repeats_override: int | None = None,
    use_cache: bool = True,
    save_baseline: bool = False,
    yes: bool = False,
    max_cost_override: Decimal | None = None,
    interactive: bool,
    confirm_fn: Callable[[str], bool] | None = None,
    settings: Settings,
    llm_client: LlmClient,
    prompts: PromptRegistry,
    runs_dir: Path = RUNS_DIR,
    baselines_dir: Path = BASELINES_DIR,
    eval_cache: EvalCache | None = None,
) -> tuple[RunSummary, Path]:
    suite = load_suite(suite_dir, prompts=prompts)
    cases = load_cases(suite_dir, split=split)
    repeats = repeats_override or suite.repeats
    cache = eval_cache or EvalCache()
    ctx = RunContext(
        llm_client=llm_client, prompts=prompts, cache=cache, model=suite.model, effort=suite.effort
    )

    target_fn, estimate_fn = load_target(suite.target, SuiteError)

    baseline = _load_baseline(baselines_dir, suite.name)
    estimate = await _estimate_cost(suite, cases, repeats, estimate_fn, ctx, baseline)
    limit = _effective_limit(suite, settings.fin_ai_lab_max_run_cost_usd, max_cost_override)
    await _check_cost_guard(estimate, limit, yes, interactive, confirm_fn)

    run_id = _new_run_id(suite.name)
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    graders = [build_grader(spec) for spec in suite.graders]
    semaphore = asyncio.Semaphore(suite.concurrency)

    async def run_one(case: Case, repeat_index: int) -> CaseResult:
        async with semaphore:
            return await _execute_case(
                case, repeat_index, suite, target_fn, graders, ctx, cache, use_cache
            )

    tasks = [
        asyncio.ensure_future(run_one(case, repeat_index))
        for case in cases
        for repeat_index in range(repeats)
    ]

    started_at = datetime.now(UTC)
    incomplete = False
    case_results: list[CaseResult] = []

    try:
        with (run_dir / "results.jsonl").open("a", encoding="utf-8") as results_file:
            for finished in asyncio.as_completed(tasks):
                result = await finished
                case_results.append(result)
                results_file.write(result.model_dump_json() + "\n")
                results_file.flush()
    except (KeyboardInterrupt, asyncio.CancelledError):
        incomplete = True
        for task in tasks:
            task.cancel()
    finally:
        finished_at = datetime.now(UTC)
        summary = _build_summary(suite, case_results, started_at, finished_at, incomplete)
        (run_dir / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
        report_text = render_report(suite, summary, case_results, baseline)
        (run_dir / "report.md").write_text(report_text, encoding="utf-8")

    if not incomplete and save_baseline:
        _save_baseline(baselines_dir, suite.name, summary)

    return summary, run_dir


async def _execute_case(
    case: Case,
    repeat_index: int,
    suite: Suite,
    target_fn: Callable,
    graders: list,
    ctx: RunContext,
    cache: EvalCache,
    use_cache: bool,
) -> CaseResult:
    key = _target_cache_key(suite, case, repeat_index)
    started = time.monotonic()

    cached_output = cache.get("target", key) if use_cache else None
    if cached_output is not None:
        output = cached_output["output"]
        cache_hit = True
        cost_usd = Decimal(0)
    else:
        cache_hit = False
        cost_before = getattr(ctx.llm_client, "total_cost_usd", Decimal(0))
        try:
            output = await target_fn(case.input, ctx)
        except Exception as exc:
            return CaseResult(
                case_id=case.id,
                split=case.split,
                repeat_index=repeat_index,
                tags=case.tags,
                passed=False,
                grades={},
                error=f"target_error: {type(exc).__name__}: {exc}",
                cost_usd=Decimal(0),
                latency_ms=int((time.monotonic() - started) * 1000),
                cache_hit=False,
            )
        cost_after = getattr(ctx.llm_client, "total_cost_usd", Decimal(0))
        cost_usd = cost_after - cost_before
        cache.set("target", key, {"output": output})

    grades: dict = {}
    error: str | None = None
    try:
        for grader in graders:
            grades[grader.name] = await grader.grade(case, output, ctx)
    except Exception as exc:
        error = f"grader_error: {type(exc).__name__}: {exc}"

    passed = error is None and all(grade.passed for grade in grades.values())
    return CaseResult(
        case_id=case.id,
        split=case.split,
        repeat_index=repeat_index,
        tags=case.tags,
        passed=passed,
        grades=grades,
        error=error,
        cost_usd=cost_usd,
        latency_ms=int((time.monotonic() - started) * 1000),
        cache_hit=cache_hit,
    )


def _target_cache_key(suite: Suite, case: Case, repeat_index: int) -> str:
    payload = {
        "target": suite.target,
        "input": case.input,
        "prompt_versions": suite.prompt_versions,
        "model": suite.model,
        "effort": suite.effort,
        "repeat_index": repeat_index,
    }
    return cache_key(payload)


async def _estimate_cost(
    suite: Suite,
    cases: list[Case],
    repeats: int,
    estimate_fn: Callable | None,
    ctx: RunContext,
    baseline: dict | None,
) -> Decimal | None:
    if estimate_fn is not None:
        total = Decimal(0)
        for case in cases:
            for _ in range(repeats):
                total += await estimate_fn(case.input, ctx)
        return total

    if baseline is not None and baseline.get("case_count"):
        avg = Decimal(str(baseline["cost_usd"])) / Decimal(baseline["case_count"])
        return avg * len(cases) * repeats

    return None


def _effective_limit(suite: Suite, settings_limit: Decimal, override: Decimal | None) -> Decimal:
    limits = [settings_limit]
    if suite.max_cost_usd is not None:
        limits.append(suite.max_cost_usd)
    if override is not None:
        limits.append(override)
    return min(limits)


async def _check_cost_guard(
    estimate: Decimal | None,
    limit: Decimal,
    yes: bool,
    interactive: bool,
    confirm_fn: Callable[[str], bool] | None,
) -> None:
    exceeded = estimate is None or estimate > limit
    if not exceeded:
        return

    estimate_label = "unknown" if estimate is None else f"{estimate} USD"
    message = f"Estimated cost {estimate_label} exceeds limit {limit} USD"

    if yes:
        return
    if not interactive or confirm_fn is None:
        raise BudgetExceeded(message)
    if not confirm_fn(f"{message}. Continue?"):
        raise BudgetExceeded(message)


def _build_summary(
    suite: Suite,
    case_results: list[CaseResult],
    started_at: datetime,
    finished_at: datetime,
    incomplete: bool,
) -> RunSummary:
    total_cost = sum((result.cost_usd for result in case_results), Decimal(0))
    latencies = sorted(result.latency_ms for result in case_results)
    cache_hits = sum(1 for result in case_results if result.cache_hit)

    return RunSummary(
        suite=suite.name,
        dataset_version=suite.dataset_version,
        started_at=started_at,
        finished_at=finished_at,
        incomplete=incomplete,
        model=suite.model,
        effort=suite.effort,
        prompt_versions=suite.prompt_versions,
        git_commit=_current_git_commit(),
        cost_usd=total_cost,
        case_count=len(case_results),
        cache_hits=cache_hits,
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        metrics=_compute_metrics(case_results),
        cases={result.case_id: result.passed for result in case_results},
    )


def _compute_metrics(case_results: list[CaseResult]) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}

    by_grader: dict[str, list] = {}
    for result in case_results:
        for name, grade in result.grades.items():
            by_grader.setdefault(name, []).append(grade)
    for name, grades in by_grader.items():
        n = len(grades)
        metrics[f"grader:{name}"] = {
            "pass_rate": sum(1 for grade in grades if grade.passed) / n,
            "avg_score": sum(grade.score for grade in grades) / n,
            "n": float(n),
        }

    by_tag: dict[str, list[CaseResult]] = {}
    for result in case_results:
        for tag in result.tags:
            by_tag.setdefault(tag, []).append(result)
    for tag, results in by_tag.items():
        n = len(results)
        metrics[f"tag:{tag}"] = {
            "pass_rate": sum(1 for result in results if result.passed) / n,
            "n": float(n),
        }

    return metrics


def _percentile(sorted_values: list[int], pct: float) -> float:
    if not sorted_values:
        return 0.0
    rank = (len(sorted_values) - 1) * (pct / 100)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return float(sorted_values[lower])
    lower_weight = sorted_values[lower] * (upper - rank)
    upper_weight = sorted_values[upper] * (rank - lower)
    return float(lower_weight + upper_weight)


def _current_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return None


def _new_run_id(suite_name: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{timestamp}-{suffix}-{suite_name}"


def _load_baseline(baselines_dir: Path, suite_name: str) -> dict | None:
    path = baselines_dir / f"{suite_name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_baseline(baselines_dir: Path, suite_name: str, summary: RunSummary) -> None:
    baselines_dir.mkdir(parents=True, exist_ok=True)
    path = baselines_dir / f"{suite_name}.json"
    path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")

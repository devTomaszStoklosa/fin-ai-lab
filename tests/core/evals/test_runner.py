import json
import sys
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.errors import BudgetExceeded
from fin_ai_lab.core.evals.cache import EvalCache
from fin_ai_lab.core.evals.models import GraderSpec, Suite
from fin_ai_lab.core.evals.runner import _effective_limit, run_suite
from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry


@contextmanager
def _temp_module(tmp_path: Path, name: str, source: str) -> Iterator[None]:
    module_dir = tmp_path / "modules"
    module_dir.mkdir(exist_ok=True)
    (module_dir / f"{name}.py").write_text(textwrap.dedent(source), encoding="utf-8")
    sys.path.insert(0, str(module_dir))
    try:
        yield
    finally:
        sys.path.remove(str(module_dir))
        sys.modules.pop(name, None)


def _case(a: int, b: int, expected_sum: int, case_id: str = "c1") -> dict:
    return {
        "id": case_id,
        "input": {"a": a, "b": b},
        "expected": {"sum": expected_sum},
        "provenance": "synthetic",
    }


def _write_suite(suite_dir: Path, target_ref: str, cases: list[dict]) -> None:
    suite_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "name": suite_dir.name,
        "dataset_version": 1,
        "target": target_ref,
        "graders": [{"type": "numeric", "field": "sum"}],
    }
    (suite_dir / "suite.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    text = "\n".join(json.dumps(case) for case in cases) + "\n"
    (suite_dir / "cases.jsonl").write_text(text, encoding="utf-8")


def _run_kwargs(tmp_path: Path, **overrides: object) -> dict:
    kwargs = dict(
        interactive=False,
        confirm_fn=None,
        settings=Settings(),
        llm_client=FakeLlmClient({}),
        prompts=PromptRegistry(),
        runs_dir=tmp_path / "runs",
        baselines_dir=tmp_path / "baselines",
        eval_cache=EvalCache(cache_dir=tmp_path / "cache"),
    )
    kwargs.update(overrides)
    return kwargs


async def test_run_suite_executes_real_foundation_smoke_suite(tmp_path: Path) -> None:
    suite_dir = Path("evals/foundation-smoke")

    summary, run_dir = await run_suite(suite_dir, **_run_kwargs(tmp_path))

    assert summary.incomplete is False
    assert summary.case_count == 3
    assert summary.cost_usd == Decimal(0)
    assert (run_dir / "report.md").exists()


async def test_run_suite_writes_results_for_zero_cost_target(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suites" / "demo"
    with _temp_module(
        tmp_path,
        "demo_target_ok",
        """
        from decimal import Decimal

        async def target(case_input, ctx):
            return {"sum": case_input["a"] + case_input["b"]}

        async def estimate(case_input, ctx):
            return Decimal(0)
        """,
    ):
        _write_suite(suite_dir, "demo_target_ok:target", [_case(1, 2, 3)])

        summary, run_dir = await run_suite(suite_dir, **_run_kwargs(tmp_path))

    assert summary.incomplete is False
    assert (run_dir / "results.jsonl").exists()
    assert summary.metrics["grader:numeric"]["pass_rate"] == 1.0


async def test_run_suite_aborts_when_estimate_unknown_and_noninteractive(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suites" / "no-estimate"
    with _temp_module(
        tmp_path,
        "demo_target_no_estimate",
        """
        async def target(case_input, ctx):
            return {"sum": case_input["a"] + case_input["b"]}
        """,
    ):
        _write_suite(suite_dir, "demo_target_no_estimate:target", [_case(1, 2, 3)])

        with pytest.raises(BudgetExceeded):
            await run_suite(suite_dir, **_run_kwargs(tmp_path))


async def test_run_suite_records_target_exception_as_case_error(tmp_path: Path) -> None:
    suite_dir = tmp_path / "suites" / "failing"
    with _temp_module(
        tmp_path,
        "demo_target_failing",
        """
        from decimal import Decimal

        async def target(case_input, ctx):
            raise ValueError("boom")

        async def estimate(case_input, ctx):
            return Decimal(0)
        """,
    ):
        _write_suite(suite_dir, "demo_target_failing:target", [_case(1, 2, 3)])

        summary, run_dir = await run_suite(suite_dir, **_run_kwargs(tmp_path))

    assert summary.incomplete is False
    results = (run_dir / "results.jsonl").read_text(encoding="utf-8")
    assert "target_error" in results
    assert summary.cases["c1"] is False


async def test_run_suite_marks_incomplete_on_interruption(tmp_path: Path) -> None:
    # asyncio.CancelledError exercises the same abort path a real Ctrl+C
    # (KeyboardInterrupt) would, without triggering pytest's own special-cased
    # session-level handling of a literal KeyboardInterrupt.
    suite_dir = tmp_path / "suites" / "interrupted"
    with _temp_module(
        tmp_path,
        "demo_target_interrupt",
        """
        import asyncio
        from decimal import Decimal

        async def target(case_input, ctx):
            if case_input["a"] == 99:
                raise asyncio.CancelledError()
            return {"sum": case_input["a"] + case_input["b"]}

        async def estimate(case_input, ctx):
            return Decimal(0)
        """,
    ):
        _write_suite(
            suite_dir,
            "demo_target_interrupt:target",
            [_case(1, 2, 3, case_id="c1"), _case(99, 0, 99, case_id="c2")],
        )

        summary, run_dir = await run_suite(suite_dir, **_run_kwargs(tmp_path))

    assert summary.incomplete is True
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "report.md").exists()


def test_effective_limit_takes_the_lowest_of_all_configured_limits() -> None:
    suite = Suite(
        name="s",
        dataset_version=1,
        target="fin_ai_lab.core.evals.smoke_target:target",
        graders=[GraderSpec(type="numeric", field="sum")],
        max_cost_usd=Decimal("5"),
    )

    limit = _effective_limit(suite, settings_limit=Decimal("1"), override=Decimal("10"))

    assert limit == Decimal("1")


def test_effective_limit_uses_override_when_it_is_the_tightest() -> None:
    suite = Suite(
        name="s",
        dataset_version=1,
        target="fin_ai_lab.core.evals.smoke_target:target",
        graders=[GraderSpec(type="numeric", field="sum")],
        max_cost_usd=Decimal("5"),
    )

    limit = _effective_limit(suite, settings_limit=Decimal("1"), override=Decimal("0.1"))

    assert limit == Decimal("0.1")

from pathlib import Path

from fin_ai_lab.core.evals.cache import EvalCache
from fin_ai_lab.core.evals.graders.llm_judge import LlmJudgeGrader
from fin_ai_lab.core.evals.models import Case, GraderSpec, RunContext
from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry

_SPEC = GraderSpec(
    type="llm_judge",
    params={"rubric": "Oceń jakość raportu.", "model": "gemini-2.5-flash"},
)


def _case() -> Case:
    return Case(id="c1", input={}, provenance="synthetic")


def _ctx(tmp_path: Path, response: str) -> tuple[RunContext, FakeLlmClient]:
    llm_client = FakeLlmClient({"llm_judge": response})
    ctx = RunContext(
        llm_client=llm_client,
        prompts=PromptRegistry(),
        cache=EvalCache(cache_dir=tmp_path),
    )
    return ctx, llm_client


async def test_llm_judge_returns_verdict_from_llm(tmp_path: Path) -> None:
    ctx, llm_client = _ctx(tmp_path, '{"score": 0.9, "passed": true, "reason": "ok"}')
    grader = LlmJudgeGrader(_SPEC)

    result = await grader.grade(_case(), "Raport testowy.", ctx)

    assert result.passed is True
    assert result.score == 0.9
    assert len(llm_client.requests) == 1


async def test_llm_judge_reuses_cache_on_second_call_for_same_text(tmp_path: Path) -> None:
    ctx, llm_client = _ctx(tmp_path, '{"score": 0.5, "passed": false, "reason": "meh"}')
    grader = LlmJudgeGrader(_SPEC)
    case = _case()

    await grader.grade(case, "Ten sam tekst.", ctx)
    await grader.grade(case, "Ten sam tekst.", ctx)

    assert len(llm_client.requests) == 1

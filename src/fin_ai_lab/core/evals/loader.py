import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from fin_ai_lab.core.errors import PromptError, SuiteError
from fin_ai_lab.core.evals._imports import load_target
from fin_ai_lab.core.evals.models import Case, GraderSpec, Suite
from fin_ai_lab.core.llm.pricing import PRICES
from fin_ai_lab.core.prompts.registry import PromptRegistry

_VALID_SPLITS = {"dev", "test"}
_VALID_PROVENANCES = {"synthetic", "human", "rule"}
_VALID_EFFORTS = {"low", "medium", "high", "max"}


def load_suite(suite_dir: Path, prompts: PromptRegistry | None = None) -> Suite:
    raw = yaml.safe_load((suite_dir / "suite.yaml").read_text(encoding="utf-8")) or {}

    try:
        suite = Suite(
            name=raw.get("name", ""),
            dataset_version=raw.get("dataset_version"),
            target=raw.get("target", ""),
            model=raw.get("model"),
            effort=raw.get("effort"),
            prompt_versions=raw.get("prompt_versions") or {},
            graders=[GraderSpec(**grader) for grader in (raw.get("graders") or [])],
            repeats=raw.get("repeats", 1),
            concurrency=raw.get("concurrency", 4),
            max_cost_usd=raw.get("max_cost_usd"),
        )
    except ValidationError as exc:
        raise SuiteError(_first_error_message(exc)) from exc

    if suite.name != suite_dir.name:
        raise SuiteError("Suite name mismatch")
    if suite.model is not None and suite.model not in PRICES:
        raise SuiteError(f"Unknown model '{suite.model}'")
    if suite.effort is not None and suite.effort not in _VALID_EFFORTS:
        raise SuiteError(f"Invalid effort '{suite.effort}'")

    load_target(suite.target, SuiteError)
    _validate_prompt_versions(suite.prompt_versions, prompts)

    return suite


def load_cases(suite_dir: Path, split: str | None = None) -> list[Case]:
    path = suite_dir / "cases.jsonl"
    cases: list[Case] = []
    seen_ids: set[str] = set()

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SuiteError(f"Invalid JSON on line {line_number} of '{path}'") from exc

        case = _case_from_raw(raw)
        if case.id in seen_ids:
            raise SuiteError(f"Duplicate case id '{case.id}' in suite '{suite_dir.name}'")
        seen_ids.add(case.id)
        cases.append(case)

    if split is not None:
        cases = [case for case in cases if case.split == split]
    if not cases:
        raise SuiteError(f"Suite has no cases for split '{split}'")
    return cases


def _case_from_raw(raw: dict) -> Case:
    if "id" not in raw:
        raise SuiteError("Case has no id")
    if not raw.get("input"):
        raise SuiteError(f"Case '{raw['id']}' has no input")

    split = raw.get("split", "dev")
    if split not in _VALID_SPLITS:
        raise SuiteError(f"Unknown split '{split}'")

    provenance = raw.get("provenance")
    if provenance is None or not (
        provenance in _VALID_PROVENANCES or provenance.startswith("teacher:")
    ):
        raise SuiteError(f"Invalid provenance '{provenance}'")

    return Case(
        id=raw["id"],
        split=split,
        input=raw["input"],
        expected=raw.get("expected"),
        tags=raw.get("tags", []),
        provenance=provenance,
    )


def _validate_prompt_versions(
    prompt_versions: dict[str, int], prompts: PromptRegistry | None
) -> None:
    if not prompt_versions or prompts is None:
        return
    for prompt_id, version in prompt_versions.items():
        try:
            prompts.get(prompt_id, version)
        except PromptError:
            raise SuiteError(f"Prompt '{prompt_id}' has no version {version}") from None


def _first_error_message(exc: ValidationError) -> str:
    message = exc.errors()[0]["msg"]
    return message.removeprefix("Value error, ")

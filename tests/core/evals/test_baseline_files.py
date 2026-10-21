import json
from pathlib import Path

import pytest
import yaml

_BASELINES_DIR = Path("evals/baselines")
_EVALS_DIR = Path("evals")


def _case_ids(cases_path: Path) -> set[str]:
    lines = cases_path.read_text(encoding="utf-8").splitlines()
    return {json.loads(line)["id"] for line in lines if line.strip()}


@pytest.mark.parametrize(
    "baseline_path", sorted(_BASELINES_DIR.glob("*.json")), ids=lambda path: path.stem
)
def test_baseline_covers_current_cases_of_same_dataset_version(baseline_path: Path) -> None:
    # The report compares a run with its baseline whenever dataset_version
    # matches, so a cases.jsonl change without a version bump makes it compare
    # pass rates over two different question sets (issue #8).
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    suite_dir = _EVALS_DIR / baseline["suite"]
    suite = yaml.safe_load((suite_dir / "suite.yaml").read_text(encoding="utf-8"))
    cases_path = suite_dir / "cases.jsonl"

    if suite["dataset_version"] != baseline["dataset_version"]:
        pytest.skip("baseline belongs to an older dataset_version; the report skips the delta")
    if not cases_path.exists():
        pytest.skip("cases.jsonl is built locally and not present on this machine")

    assert set(baseline["cases"]) == _case_ids(cases_path), (
        f"{suite_dir / 'cases.jsonl'} changed without a dataset_version bump in "
        f"{suite_dir / 'suite.yaml'}"
    )

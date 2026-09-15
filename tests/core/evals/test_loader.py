import json
from pathlib import Path

import pytest
import yaml

from fin_ai_lab.core.errors import SuiteError
from fin_ai_lab.core.evals.loader import load_cases, load_suite

_VALID_TARGET = "fin_ai_lab.core.evals.smoke_target:target"


def _write_suite(tmp_path: Path, name: str = "demo", **overrides: object) -> Path:
    suite_dir = tmp_path / name
    suite_dir.mkdir()
    body: dict = {
        "name": name,
        "dataset_version": 1,
        "target": _VALID_TARGET,
        "graders": [{"type": "numeric", "field": "sum"}],
    }
    body.update(overrides)
    (suite_dir / "suite.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    return suite_dir


def _write_cases(suite_dir: Path, lines: list[dict]) -> None:
    text = "\n".join(json.dumps(line) for line in lines) + "\n"
    (suite_dir / "cases.jsonl").write_text(text, encoding="utf-8")


def test_load_suite_reads_valid_suite(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path)

    suite = load_suite(suite_dir)

    assert suite.name == "demo"
    assert suite.dataset_version == 1
    assert suite.repeats == 1
    assert suite.concurrency == 4


def test_load_suite_rejects_name_mismatch(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path, name="demo")
    body = yaml.safe_load((suite_dir / "suite.yaml").read_text(encoding="utf-8"))
    body["name"] = "other"
    (suite_dir / "suite.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")

    with pytest.raises(SuiteError, match="Suite name mismatch"):
        load_suite(suite_dir)


def test_load_suite_rejects_no_graders(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path, graders=[])

    with pytest.raises(SuiteError, match="Suite has no graders"):
        load_suite(suite_dir)


def test_load_suite_rejects_unknown_model(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path, model="not-a-real-model")

    with pytest.raises(SuiteError, match="Unknown model"):
        load_suite(suite_dir)


def test_load_suite_rejects_unimportable_target(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path, target="nope.no_such_module:func")

    with pytest.raises(SuiteError, match="not importable"):
        load_suite(suite_dir)


def test_load_suite_rejects_dataset_version_below_one(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path, dataset_version=0)

    with pytest.raises(SuiteError, match="dataset_version must be >= 1"):
        load_suite(suite_dir)


def test_load_suite_rejects_repeats_out_of_range(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path, repeats=99)

    with pytest.raises(SuiteError, match="repeats out of range"):
        load_suite(suite_dir)


def test_load_cases_reads_valid_cases_and_filters_by_split(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path)
    _write_cases(
        suite_dir,
        [
            {"id": "c1", "split": "dev", "input": {"a": 1}, "provenance": "synthetic"},
            {"id": "c2", "split": "test", "input": {"a": 2}, "provenance": "synthetic"},
        ],
    )

    dev_cases = load_cases(suite_dir, split="dev")

    assert [case.id for case in dev_cases] == ["c1"]


def test_load_cases_rejects_duplicate_id(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path)
    _write_cases(
        suite_dir,
        [
            {"id": "c1", "input": {"a": 1}, "provenance": "synthetic"},
            {"id": "c1", "input": {"a": 2}, "provenance": "synthetic"},
        ],
    )

    with pytest.raises(SuiteError, match="Duplicate case id"):
        load_cases(suite_dir)


def test_load_cases_rejects_unknown_split(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path)
    _write_cases(
        suite_dir, [{"id": "c1", "split": "prod", "input": {"a": 1}, "provenance": "synthetic"}]
    )

    with pytest.raises(SuiteError, match="Unknown split"):
        load_cases(suite_dir)


def test_load_cases_rejects_missing_input(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path)
    _write_cases(suite_dir, [{"id": "c1", "input": {}, "provenance": "synthetic"}])

    with pytest.raises(SuiteError, match="has no input"):
        load_cases(suite_dir)


def test_load_cases_rejects_invalid_provenance(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path)
    _write_cases(suite_dir, [{"id": "c1", "input": {"a": 1}, "provenance": "made-up"}])

    with pytest.raises(SuiteError, match="Invalid provenance"):
        load_cases(suite_dir)


def test_load_cases_rejects_empty_split(tmp_path: Path) -> None:
    suite_dir = _write_suite(tmp_path)
    _write_cases(
        suite_dir, [{"id": "c1", "split": "dev", "input": {"a": 1}, "provenance": "synthetic"}]
    )

    with pytest.raises(SuiteError, match="Suite has no cases for split 'test'"):
        load_cases(suite_dir, split="test")

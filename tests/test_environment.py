from collections.abc import Callable

import pytest


def _check_pydantic_core() -> None:
    from pydantic import BaseModel

    class Probe(BaseModel):
        value: int

    assert Probe.model_validate({"value": "42"}).value == 42


# Each entry: (dependency name, callable that imports it and performs one operation).
# Populated as slices add native dependencies (see docs/ENVIRONMENT.md).
NATIVE_DEPENDENCY_CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("pydantic-core", _check_pydantic_core),
]


def test_native_dependencies_work_on_this_cpu() -> None:
    for _name, check in NATIVE_DEPENDENCY_CHECKS:
        check()


def test_numpy_works_on_this_cpu_when_installed() -> None:
    # numpy/pandas/yfinance are the optional "portfolio" extra (P1's risk metrics),
    # not a base dependency — skip rather than fail when it's not synced.
    numpy = pytest.importorskip("numpy")

    assert numpy.array([1.0, 2.0, 3.0]).sum() == 6.0


def test_pandas_works_on_this_cpu_when_installed() -> None:
    pandas = pytest.importorskip("pandas")

    frame = pandas.DataFrame({"a": [1, 2, 3]})

    assert frame["a"].sum() == 6


def test_bm25s_works_on_this_cpu_when_installed() -> None:
    bm25s = pytest.importorskip("bm25s")

    corpus = ["the cat sat on the mat", "dogs are great pets", "the mat was red"]
    retriever = bm25s.BM25()
    retriever.index(bm25s.tokenize(corpus))
    results, _scores = retriever.retrieve(bm25s.tokenize(["red mat"]), k=1)

    assert corpus[results[0][0]] == "the mat was red"

from collections.abc import Callable


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

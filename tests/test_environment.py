from collections.abc import Callable

# Each entry: (dependency name, callable that imports it and performs one operation).
# Populated as slices add native dependencies (see docs/ENVIRONMENT.md).
NATIVE_DEPENDENCY_CHECKS: list[tuple[str, Callable[[], None]]] = []


def test_native_dependencies_work_on_this_cpu() -> None:
    for _name, check in NATIVE_DEPENDENCY_CHECKS:
        check()

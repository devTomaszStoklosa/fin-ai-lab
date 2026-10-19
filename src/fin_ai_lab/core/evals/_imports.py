import importlib
from collections.abc import Callable


def import_ref(ref: str, error_cls: type[Exception], label: str = "Target") -> object:
    module_name, _, attr_name = ref.partition(":")
    if not module_name or not attr_name:
        raise error_cls(f"{label} '{ref}' not importable")
    try:
        module = importlib.import_module(module_name)
        return getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise error_cls(f"{label} '{ref}' not importable") from exc


def load_target(ref: str, error_cls: type[Exception]) -> tuple[Callable, Callable | None]:
    module_name, _, attr_name = ref.partition(":")
    if not module_name or not attr_name:
        raise error_cls(f"Target '{ref}' not importable")
    try:
        module = importlib.import_module(module_name)
        target_fn = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise error_cls(f"Target '{ref}' not importable") from exc
    estimate_fn = getattr(module, "estimate", None)
    return target_fn, estimate_fn

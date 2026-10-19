"""docs/ARCHITECTURE.md rule 6, checked on the source instead of trusted
(#256): which project may import which, and P2-P5 only via their service.py."""

import ast
from pathlib import Path

import pytest

SRC = Path("src/fin_ai_lab")

PROJECTS = {
    "portfolio_xray",
    "filings_rag",
    "market_pulse",
    "news_classifier",
    "investment_committee",
    "portfolio_webapp",
}
# Imported by other projects only through `<project>.service`.
SERVICE_ONLY = {"filings_rag", "market_pulse", "news_classifier", "investment_committee"}
# Which other projects each package may import at all. P1's portfolio types
# and modules are shared on purpose: P5 and the web app work on the same
# portfolio data (the web app is P1's web layer).
ALLOWED = {
    "core": set(),
    "portfolio_xray": set(),
    "filings_rag": set(),
    "market_pulse": set(),
    "news_classifier": set(),
    "investment_committee": {"portfolio_xray", "filings_rag", "market_pulse", "news_classifier"},
    "portfolio_webapp": {
        "portfolio_xray",
        "filings_rag",
        "market_pulse",
        "news_classifier",
        "investment_committee",
    },
}


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    # ast.walk, not just the module body: a local import inside a function
    # (e.g. the optional "ui" extra in cli.py) is still a dependency.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def _violations(package: str) -> list[str]:
    found: list[str] = []
    for path in sorted((SRC / package).rglob("*.py")):
        for module in _imported_modules(path):
            parts = module.split(".")
            if len(parts) < 2 or parts[0] != "fin_ai_lab":
                continue
            target = parts[1]
            if target == package or target not in PROJECTS:
                continue
            if target not in ALLOWED[package]:
                found.append(f"{path}: imports {module} ({package} may not use {target})")
            elif target in SERVICE_ONLY and module != f"fin_ai_lab.{target}.service":
                found.append(f"{path}: imports {module} (use fin_ai_lab.{target}.service)")
    return found


@pytest.mark.parametrize("package", sorted(ALLOWED))
def test_package_follows_architecture_rule_6(package: str) -> None:
    assert _violations(package) == []


def test_every_service_only_project_has_a_service_module() -> None:
    for project in SERVICE_ONLY:
        assert (SRC / project / "service.py").exists(), project

from pathlib import Path

import pytest

from fin_ai_lab.core.errors import PromptError
from fin_ai_lab.core.prompts.registry import PromptRegistry


def _write(directory: Path, filename: str, content: str) -> None:
    (directory / filename).write_text(content, encoding="utf-8")


def test_load_dir_and_render(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "greet.v1.md",
        "---\ndescription: Greets someone\nvariables: [name]\n---\nHello, {{name}}!",
    )
    registry = PromptRegistry()

    registry.load_dir(tmp_path)
    prompt = registry.get("greet", 1)

    assert prompt.description == "Greets someone"
    assert prompt.render(name="Tomasz") == "Hello, Tomasz!"


def test_render_raises_on_missing_variable(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "greet.v1.md",
        "---\ndescription: Greets someone\nvariables: [name]\n---\nHello, {{name}}!",
    )
    registry = PromptRegistry()
    registry.load_dir(tmp_path)
    prompt = registry.get("greet", 1)

    with pytest.raises(PromptError, match="name"):
        prompt.render()


def test_load_dir_raises_on_duplicate_id_and_version(tmp_path: Path) -> None:
    _write(tmp_path, "greet.v1.md", "---\ndescription: A\nvariables: []\n---\nHi")
    sub = tmp_path / "sub"
    sub.mkdir()
    _write(sub, "greet.v1.md", "---\ndescription: B\nvariables: []\n---\nYo")

    registry = PromptRegistry()
    registry.load_dir(tmp_path)

    with pytest.raises(PromptError, match="Duplicate"):
        registry.load_dir(sub)


def test_get_raises_when_prompt_not_found(tmp_path: Path) -> None:
    registry = PromptRegistry()

    with pytest.raises(PromptError, match="not found"):
        registry.get("missing", 1)

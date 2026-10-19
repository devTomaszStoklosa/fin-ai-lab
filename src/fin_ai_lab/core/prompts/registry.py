import re
from pathlib import Path

import yaml
from pydantic import BaseModel

from fin_ai_lab.core.errors import PromptError

_FILENAME_RE = re.compile(r"^(?P<id>[a-z0-9_-]+)\.v(?P<version>\d+)\.md$")
_FRONTMATTER_RE = re.compile(r"\A---\n(?P<header>.*?\n)---\n(?P<body>.*)\Z", re.DOTALL)


class Prompt(BaseModel):
    id: str
    version: int
    description: str
    variables: list[str]
    template: str

    def render(self, **kwargs: str) -> str:
        missing = [name for name in self.variables if name not in kwargs]
        if missing:
            raise PromptError(
                f"Missing variable '{missing[0]}' for prompt '{self.id}' v{self.version}"
            )
        rendered = self.template
        for name in self.variables:
            rendered = rendered.replace("{{" + name + "}}", str(kwargs[name]))
        return rendered


def _parse_prompt_file(path: Path) -> Prompt:
    name_match = _FILENAME_RE.match(path.name)
    if not name_match:
        raise PromptError(f"Prompt file name '{path.name}' must match '<id>.v<N>.md'")

    text = path.read_text(encoding="utf-8")
    frontmatter_match = _FRONTMATTER_RE.match(text)
    if not frontmatter_match:
        raise PromptError(f"Prompt file '{path.name}' has no YAML frontmatter")

    header = yaml.safe_load(frontmatter_match.group("header")) or {}

    return Prompt(
        id=name_match.group("id"),
        version=int(name_match.group("version")),
        description=header.get("description", ""),
        variables=header.get("variables", []),
        template=frontmatter_match.group("body").strip("\n"),
    )


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: dict[tuple[str, int], Prompt] = {}

    def load_dir(self, directory: Path) -> None:
        for path in sorted(directory.glob("*.md")):
            prompt = _parse_prompt_file(path)
            key = (prompt.id, prompt.version)
            if key in self._prompts:
                raise PromptError(f"Duplicate prompt '{prompt.id}' version {prompt.version}")
            self._prompts[key] = prompt

    def get(self, id: str, version: int) -> Prompt:
        try:
            return self._prompts[(id, version)]
        except KeyError:
            raise PromptError(f"Prompt '{id}' version {version} not found") from None

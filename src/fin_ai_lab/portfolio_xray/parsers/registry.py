import re
from pathlib import Path

import yaml

from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig
from fin_ai_lab.portfolio_xray.parsers.signature import compute_signature

PARSERS_DIR = Path(__file__).parent


class ParserRegistry:
    def __init__(self, parsers_dir: Path = PARSERS_DIR) -> None:
        self._parsers_dir = parsers_dir
        self._by_signature: dict[str, ParserConfig] = {}
        self._configs: list[ParserConfig] = []
        for path in sorted(parsers_dir.glob("*.yaml")):
            config = ParserConfig(**yaml.safe_load(path.read_text(encoding="utf-8")))
            self._by_signature[_config_signature(config)] = config
            self._configs.append(config)

    def find_approved(self, signature: str) -> ParserConfig | None:
        return self._by_signature.get(signature)

    def next_version(self, broker: str) -> int:
        versions = [config.version for config in self._configs if config.broker == broker]
        return max(versions, default=0) + 1

    def save(self, config: ParserConfig) -> Path:
        # New file with a higher version; existing versions are never
        # overwritten, so golden-set baselines stay reproducible.
        file_name = f"{config.broker}_{_slug(config.sheet_name)}.v{config.version}.yaml"
        path = self._parsers_dir / file_name
        path.write_text(
            yaml.safe_dump(config.model_dump(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        self._by_signature[_config_signature(config)] = config
        self._configs.append(config)
        return path


def _config_signature(config: ParserConfig) -> str:
    return compute_signature(
        config.expected_headers,
        delimiter=config.delimiter,
        encoding=config.encoding,
        sheet_name=config.sheet_name,
    )


def _slug(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "sheet").lower()).strip("_")

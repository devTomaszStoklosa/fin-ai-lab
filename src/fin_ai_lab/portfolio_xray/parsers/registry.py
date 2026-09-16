from pathlib import Path

import yaml

from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig
from fin_ai_lab.portfolio_xray.parsers.signature import compute_signature

PARSERS_DIR = Path(__file__).parent


class ParserRegistry:
    def __init__(self, parsers_dir: Path = PARSERS_DIR) -> None:
        self._by_signature: dict[str, ParserConfig] = {}
        for path in sorted(parsers_dir.glob("*.yaml")):
            config = ParserConfig(**yaml.safe_load(path.read_text(encoding="utf-8")))
            self._by_signature[_config_signature(config)] = config

    def find_approved(self, signature: str) -> ParserConfig | None:
        return self._by_signature.get(signature)


def _config_signature(config: ParserConfig) -> str:
    return compute_signature(
        config.expected_headers,
        delimiter=config.delimiter,
        encoding=config.encoding,
        sheet_name=config.sheet_name,
    )

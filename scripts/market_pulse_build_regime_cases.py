"""Builds evals/p3-regime-backtest/cases.jsonl from the committed
scenarios.jsonl, filling in each indicator's historical value from FRED.

cases.jsonl is gitignored: VIXCLS is licensed for learning use only, so
the values never enter the repo (docs/DATA-SOURCES.md, docs/EVALS.md).
Needs FRED_API_KEY in .env.

Run from the repo root: `uv run python scripts/market_pulse_build_regime_cases.py`.
"""

import asyncio
import json
from pathlib import Path

from fin_ai_lab.core.config import Settings
from fin_ai_lab.market_pulse.regime_cases import build_regime_cases
from fin_ai_lab.market_pulse.sources.fred import FredClient

SUITE_DIR = Path("evals/p3-regime-backtest")


def main() -> None:
    scenarios_text = (SUITE_DIR / "scenarios.jsonl").read_text(encoding="utf-8")
    scenarios = [json.loads(line) for line in scenarios_text.splitlines() if line.strip()]
    client = FredClient(Settings().require_fred_api_key())
    cases = asyncio.run(build_regime_cases(scenarios, client))
    lines = "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n"
    (SUITE_DIR / "cases.jsonl").write_text(lines, encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {SUITE_DIR / 'cases.jsonl'}")


if __name__ == "__main__":
    main()

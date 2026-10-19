from datetime import date
from decimal import Decimal

from fin_ai_lab.filings_rag.ingest.sec_edgar import SecEdgarClient
from fin_ai_lab.filings_rag.models import XbrlObservation
from fin_ai_lab.filings_rag.xbrl.tag_aliases import TAG_ALIASES


class XbrlClient:
    """Reads reported numbers straight from SEC XBRL data — no LLM involved,
    so a number in an answer is never something the model generated
    (REQ-030, 03-design.md)."""

    def __init__(
        self,
        sec_client: SecEdgarClient,
        cik_by_company: dict[str, str],
        tag_aliases: dict[str, list[str]] = TAG_ALIASES,
    ) -> None:
        self._sec_client = sec_client
        self._cik_by_company = cik_by_company
        self._tag_aliases = tag_aliases

    async def observation(
        self, company: str, concept: str, fiscal_period: str, *, unit: str | None = None
    ) -> XbrlObservation | None:
        cik = self._cik_by_company.get(company)
        tags = self._tag_aliases.get(concept)
        if cik is None or not tags:
            return None

        facts = await self._sec_client.fetch_companyfacts(cik)
        gaap_facts = facts.get("facts", {}).get("us-gaap", {})

        candidates = [
            XbrlObservation(
                concept=concept,
                value=Decimal(str(entry["val"])),
                unit=unit_name,
                fiscal_period=fiscal_period,
                filed=date.fromisoformat(entry["filed"]),
            )
            for tag in tags
            for unit_name, entries in gaap_facts.get(tag, {}).get("units", {}).items()
            if unit is None or unit_name == unit
            for entry in entries
            if _fiscal_period_label(entry["fy"], entry["fp"]) == fiscal_period
        ]
        if not candidates:
            return None

        # REQ-032: the same period reported in more than one filing (e.g.
        # as a prior-year comparative in a later 10-K) — the most recently
        # filed one wins.
        return max(candidates, key=lambda observation: observation.filed)


def _fiscal_period_label(fiscal_year: int, fiscal_period: str) -> str:
    # Matches this repo's Chunk.fiscal_period convention (02-spec.md:
    # "FY2025", "FY2024-Q4") — SEC's own "FY"/"Q1".."Q4" fp values map to
    # "FY<year>" for the annual figure, "FY<year>-<fp>" for a quarter.
    if fiscal_period == "FY":
        return f"FY{fiscal_year}"
    return f"FY{fiscal_year}-{fiscal_period}"

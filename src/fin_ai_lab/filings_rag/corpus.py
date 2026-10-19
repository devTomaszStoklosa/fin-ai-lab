from collections.abc import Awaitable, Callable
from pathlib import Path

from fin_ai_lab.filings_rag.ingest.gpw_pdf import parse_gpw_report
from fin_ai_lab.filings_rag.ingest.sec_edgar import SecEdgarClient
from fin_ai_lab.filings_rag.models import Chunk

EMBEDDING_MODEL = "gemini-embedding-2"

# US_COMPANIES only for now — GPW (Atrem, PKN Orlen, ING BSK) join once their
# annual report PDFs are manually downloaded into data/private/gpw/
# (02-spec.md), same corpus as resolved in the P2 BA spec.
US_COMPANIES = {
    "Microsoft": "789019",
    "Amazon": "1018724",
    "Oracle": "1341439",
    "Citigroup": "831001",
    "NextEra Energy": "753308",
}

# GPW half-year reports (data/private/gpw/, gitignored real broker/IR
# downloads — 01-story.md resolved corpus, P2-S7). One narrative file per
# company: the others in each folder are audit opinions/financial
# statements without prose to retrieve. Chosen by inspecting real page
# counts/content, not guessed. No US_SECTION_FILTER applies to these (Polish
# reports have no "Item 1A Risk Factors" equivalent) — the whole narrative
# report is indexed.
GPW_COMPANIES: dict[str, Path] = {
    "Atrem": Path("data/private/gpw/Atrem/Atrem 1H2026 Sprawozdanie zarządu.pdf"),
    "ING Bank Śląski": Path(
        "data/private/gpw/ING/Sprawozdanie_Zarzadu_z_dzialalnosci_Grupy_ING_Bank_Slaski_SA_Ipol_2026_PL.pdf"
    ),
    "PKN Orlen": Path("data/private/gpw/Orlen/ORLEN_260806_2026półrocze - RAPORT IH2026.pdf"),
}
GPW_FISCAL_PERIOD = "1H2026"

# ASSUMPTION for the golden set (revisit for a real "index everything"
# command): only Risk Factors, not the full 10-K. The free tier for
# gemini-embedding-2 turned out to cap at ~100 embedded *texts* per minute
# regardless of how many API calls that's split into (verified empirically
# 2026-09-16, undocumented) — indexing all ~400 chunks per company x 5
# companies would take ~20+ minutes. One rich, real section per company is
# enough to exercise retrieval/citations/refusal meaningfully. The saved
# index (`filings-rag build-index`, #253) keeps the same scope on purpose, so
# the eval results measured on it still describe what the web app searches.
US_SECTION_FILTER = "risk factors"

ChunkLoader = Callable[[], Awaitable[list[Chunk]]]


def corpus_loaders(sec_client: SecEdgarClient) -> dict[str, ChunkLoader]:
    """One chunk loader per company in the corpus, in a fixed order (US
    first, then GPW) — what index.builder.build_index walks through. A
    loader raises if its source can't be read (e.g. a GPW PDF that isn't
    on this machine), which the builder reports as a skipped company."""
    loaders: dict[str, ChunkLoader] = {}
    for company, cik in US_COMPANIES.items():
        loaders[company] = _us_loader(sec_client, cik, company)
    for company, pdf_path in GPW_COMPANIES.items():
        loaders[company] = _gpw_loader(pdf_path, company)
    return loaders


def _us_loader(sec_client: SecEdgarClient, cik: str, company: str) -> ChunkLoader:
    async def load() -> list[Chunk]:
        all_chunks = await sec_client.ingest_10k(cik, company)
        return [chunk for chunk in all_chunks if US_SECTION_FILTER in chunk.section.lower()]

    return load


def _gpw_loader(pdf_path: Path, company: str) -> ChunkLoader:
    async def load() -> list[Chunk]:
        return parse_gpw_report(
            pdf_path, company=company, fiscal_period=GPW_FISCAL_PERIOD, period_type="half-year"
        )

    return load

from pathlib import Path
from typing import Literal

from pypdf import PdfReader

from fin_ai_lab.filings_rag.ingest.chunking import chunk_text
from fin_ai_lab.filings_rag.models import Chunk, FilingType

# GPW issuers publish quarterly, half-year, and annual reports — which one a
# given PDF is can't be reliably sniffed from its content (Polish reports
# don't use a consistent phrase or layout for this), so the caller states it
# explicitly, the same way it already states `company`/`fiscal_period`
# rather than having those guessed from the PDF.
GpwPeriodType = Literal["annual", "half-year", "quarterly"]

_FILING_TYPE_BY_PERIOD: dict[GpwPeriodType, FilingType] = {
    "annual": "annual-report-pl",
    "half-year": "half-year-report-pl",
    "quarterly": "quarterly-report-pl",
}


def parse_gpw_report(
    pdf_path: Path, *, company: str, fiscal_period: str, period_type: GpwPeriodType
) -> list[Chunk]:
    filing_type = _FILING_TYPE_BY_PERIOD[period_type]
    reader = PdfReader(pdf_path)
    page_headings = _page_headings(reader)

    chunks: list[Chunk] = []
    for page_index, page in enumerate(reader.pages):
        text = page.extract_text()
        if not text.strip():
            continue

        # TOC/heading from the PDF's own bookmarks when present, else a page
        # number — never a fabricated section name (03-design.md decision).
        section = page_headings.get(page_index, f"Strona {page_index + 1}")
        for piece_index, piece in enumerate(chunk_text(text)):
            chunks.append(
                Chunk(
                    id=f"{company}:{fiscal_period}:{section}:page{page_index + 1}:{piece_index}",
                    company=company,
                    filing_type=filing_type,
                    fiscal_period=fiscal_period,
                    section=section,
                    text=piece,
                    source_location=f"{pdf_path.name}, strona {page_index + 1}",
                    language="pl",
                )
            )
    return chunks


def _page_headings(reader: PdfReader) -> dict[int, str]:
    headings: dict[int, str] = {}
    try:
        outline = reader.outline
    except Exception:
        return headings
    _walk_outline(reader, outline, headings)
    return headings


def _walk_outline(reader: PdfReader, items: list, headings: dict[int, str]) -> None:
    for item in items:
        if isinstance(item, list):
            _walk_outline(reader, item, headings)
            continue
        try:
            page_number = reader.get_destination_page_number(item)
        except Exception:
            continue
        headings.setdefault(page_number, str(item.title))

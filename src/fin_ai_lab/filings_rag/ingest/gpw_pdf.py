from pathlib import Path

from pypdf import PdfReader

from fin_ai_lab.filings_rag.ingest.chunking import chunk_text
from fin_ai_lab.filings_rag.models import Chunk


def parse_gpw_report(pdf_path: Path, *, company: str, fiscal_period: str) -> list[Chunk]:
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
                    filing_type="annual-report-pl",
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

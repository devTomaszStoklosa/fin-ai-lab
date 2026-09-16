from pathlib import Path

from fin_ai_lab.filings_rag.ingest.gpw_pdf import _walk_outline, parse_gpw_report


def _build_minimal_pdf(pages_text: list[str]) -> bytes:
    """A hand-built, valid, minimal multi-page PDF with real extractable text
    — avoids pulling in a PDF-writing dependency (e.g. reportlab) just for
    tests, since pypdf itself can't draw text onto a blank page."""
    n = len(pages_text)
    catalog_num = 1
    pages_num = 2
    page_nums = list(range(3, 3 + n))
    content_nums = list(range(3 + n, 3 + 2 * n))
    font_num = 3 + 2 * n
    max_num = font_num

    bodies: dict[int, str] = {}
    bodies[catalog_num] = f"<< /Type /Catalog /Pages {pages_num} 0 R >>"
    kids = " ".join(f"{p} 0 R" for p in page_nums)
    bodies[pages_num] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>"
    for index, text in enumerate(pages_text):
        page_num, content_num = page_nums[index], content_nums[index]
        bodies[page_num] = (
            f"<< /Type /Page /Parent {pages_num} 0 R /MediaBox [0 0 200 200] "
            f"/Resources << /Font << /F1 {font_num} 0 R >> >> /Contents {content_num} 0 R >>"
        )
        stream = f"BT /F1 12 Tf 20 150 Td ({text}) Tj ET"
        bodies[content_num] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    bodies[font_num] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    parts = [b"%PDF-1.4\n"]
    offsets: dict[int, int] = {}
    offset = len(parts[0])
    for num in range(1, max_num + 1):
        obj_bytes = f"{num} 0 obj\n{bodies[num]}\nendobj\n".encode("latin-1")
        offsets[num] = offset
        parts.append(obj_bytes)
        offset += len(obj_bytes)

    xref_offset = offset
    xref_lines = [f"xref\n0 {max_num + 1}\n", "0000000000 65535 f \n"]
    for num in range(1, max_num + 1):
        xref_lines.append(f"{offsets[num]:010d} 00000 n \n")
    trailer = (
        f"trailer\n<< /Size {max_num + 1} /Root {catalog_num} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    )

    return b"".join(parts) + "".join(xref_lines).encode("latin-1") + trailer.encode("latin-1")


def test_parse_gpw_report_falls_back_to_page_numbers_without_bookmarks(tmp_path: Path) -> None:
    pdf_path = tmp_path / "atrem.pdf"
    pdf_path.write_bytes(_build_minimal_pdf(["Przychody wzrosly.", "Ryzyka dzialalnosci."]))

    chunks = parse_gpw_report(pdf_path, company="Atrem", fiscal_period="FY2025")

    assert [c.section for c in chunks] == ["Strona 1", "Strona 2"]
    assert chunks[0].company == "Atrem"
    assert chunks[0].filing_type == "annual-report-pl"
    assert chunks[0].fiscal_period == "FY2025"
    assert chunks[0].language == "pl"
    assert "Przychody" in chunks[0].text
    assert chunks[0].source_location == "atrem.pdf, strona 1"
    assert "Ryzyka" in chunks[1].text


def test_parse_gpw_report_skips_blank_pages(tmp_path: Path) -> None:
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(_build_minimal_pdf(["", "Tresc strony drugiej."]))

    chunks = parse_gpw_report(pdf_path, company="Atrem", fiscal_period="FY2025")

    assert len(chunks) == 1
    assert chunks[0].section == "Strona 2"


class _FakeDestination:
    def __init__(self, title: str) -> None:
        self.title = title


class _FakeReader:
    def __init__(self, page_by_destination: dict[int, int]) -> None:
        self._page_by_destination = page_by_destination

    def get_destination_page_number(self, destination: _FakeDestination) -> int:
        return self._page_by_destination[id(destination)]


def test_walk_outline_maps_page_numbers_to_titles_including_nested_items() -> None:
    intro = _FakeDestination("Wstep")
    risks = _FakeDestination("Czynniki ryzyka")
    reader = _FakeReader({id(intro): 0, id(risks): 3})
    headings: dict[int, str] = {}

    _walk_outline(reader, [intro, [risks]], headings)

    assert headings == {0: "Wstep", 3: "Czynniki ryzyka"}

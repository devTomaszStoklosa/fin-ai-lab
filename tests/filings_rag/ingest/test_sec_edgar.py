from pathlib import Path

import httpx

from fin_ai_lab.core.http.client import ThrottledHttpClient
from fin_ai_lab.filings_rag.ingest.sec_edgar import (
    SecEdgarClient,
    TenKFiling,
    extract_sections,
    filing_url,
    latest_10k,
)

_SUBMISSIONS = {
    "cik": "789019",
    "name": "MICROSOFT CORP",
    "filings": {
        "recent": {
            "accessionNumber": ["0000789019-25-000005", "0000950170-25-100235"],
            "reportDate": ["2025-06-30", "2025-06-30"],
            "form": ["4", "10-K"],
            "primaryDocument": ["form4.xml", "msft-20250630.htm"],
        }
    },
}

# A near-empty TOC entry for "Item 1A." followed by the real, longer body
# section — mirrors the real SEC EDGAR layout found in production filings.
_FILING_HTML = """
<html><body>
<div>Item 1A. Risk Factors</div>
<div>ITEM 1A. RISK FACTORS</div>
<p>Our business faces many risks including competition and regulation.</p>
<div>ITEM 1B. UNRESOLVED STAFF COMMENTS</div>
<p>None.</p>
</body></html>
"""


def test_latest_10k_picks_the_10k_entry_and_derives_fiscal_period() -> None:
    filing = latest_10k(_SUBMISSIONS)

    assert filing is not None
    assert filing.accession_number == "0000950170-25-100235"
    assert filing.primary_document == "msft-20250630.htm"
    assert filing.fiscal_period == "FY2025"


def test_latest_10k_returns_none_when_no_10k_present() -> None:
    empty_recent = {"accessionNumber": [], "reportDate": [], "form": [], "primaryDocument": []}
    submissions = {"cik": "1", "name": "X", "filings": {"recent": empty_recent}}

    assert latest_10k(submissions) is None


def test_filing_url_strips_dashes_and_leading_zeros() -> None:
    filing = TenKFiling(
        cik="0000789019",
        company="MICROSOFT CORP",
        accession_number="0000950170-25-100235",
        primary_document="msft-20250630.htm",
        fiscal_period="FY2025",
    )

    url = filing_url(filing)

    assert url == (
        "https://www.sec.gov/Archives/edgar/data/789019/"
        "000095017025100235/msft-20250630.htm"
    )


def test_extract_sections_dedupes_toc_entry_keeping_the_longer_body_text() -> None:
    sections = extract_sections(_FILING_HTML)

    labels = [label for label, _ in sections]
    assert labels == ["ITEM 1A. RISK FACTORS", "ITEM 1B. UNRESOLVED STAFF COMMENTS"]
    risk_factors_text = next(text for label, text in sections if label == "ITEM 1A. RISK FACTORS")
    assert "competition and regulation" in risk_factors_text


def test_extract_sections_falls_back_to_full_document_without_item_headers() -> None:
    sections = extract_sections("<html><body><p>No items here.</p></body></html>")

    assert len(sections) == 1
    assert sections[0][0] == "Full document"
    assert "No items here" in sections[0][1]


async def test_sec_edgar_client_ingest_10k_produces_chunks_with_citations(tmp_path: Path) -> None:
    def data_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == "fin-ai-lab test test@example.com"
        return httpx.Response(200, json=_SUBMISSIONS)

    def archives_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_FILING_HTML)

    data_client = ThrottledHttpClient(
        "https://data.sec.gov",
        min_interval_s=0.0,
        provider="sec-data-test",
        cache_dir=tmp_path,
        default_headers={"User-Agent": "fin-ai-lab test test@example.com"},
        transport=httpx.MockTransport(data_handler),
    )
    archives_client = ThrottledHttpClient(
        "https://www.sec.gov",
        min_interval_s=0.0,
        provider="sec-archives-test",
        cache_dir=tmp_path,
        default_headers={"User-Agent": "fin-ai-lab test test@example.com"},
        transport=httpx.MockTransport(archives_handler),
    )
    client = SecEdgarClient(
        "fin-ai-lab test test@example.com",
        data_http_client=data_client,
        archives_http_client=archives_client,
    )

    chunks = await client.ingest_10k("789019", "MICROSOFT CORP")

    assert len(chunks) == 2
    risk_chunk = next(c for c in chunks if c.section == "ITEM 1A. RISK FACTORS")
    assert risk_chunk.company == "MICROSOFT CORP"
    assert risk_chunk.filing_type == "10-K"
    assert risk_chunk.fiscal_period == "FY2025"
    assert risk_chunk.language == "en"
    assert risk_chunk.source_location == (
        "https://www.sec.gov/Archives/edgar/data/789019/"
        "000095017025100235/msft-20250630.htm"
    )
    assert "competition and regulation" in risk_chunk.text

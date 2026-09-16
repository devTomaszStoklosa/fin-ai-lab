import re
from html.parser import HTMLParser

from pydantic import BaseModel

from fin_ai_lab.core.http.client import ThrottledHttpClient
from fin_ai_lab.filings_rag.ingest.chunking import chunk_text
from fin_ai_lab.filings_rag.models import Chunk

SEC_ARCHIVES_BASE_URL = "https://www.sec.gov"
SEC_DATA_BASE_URL = "https://data.sec.gov"
# SEC EDGAR docs (sec.gov/os/webmaster-faq, verified 2026-09-16): max 10
# requests/second, and a declared User-Agent is required or requests 403.
DEFAULT_MIN_INTERVAL_S = 1 / 10

# SEC-mandated Item numbering (Item 1, 1A, 1B, 2, 3...) is consistent across
# nearly all 10-K filers — ASSUMPTION, revisit if the P2-S2 golden set shows
# wrong section labels for a filer that formats headers unusually.
_ITEM_HEADER_RE = re.compile(r"^\s*item\s+\d+[a-z]?\.\s*.+$", re.IGNORECASE | re.MULTILINE)
_ITEM_NUMBER_RE = re.compile(r"item\s+(\d+[a-z]?)", re.IGNORECASE)

_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"script", "style"}


class TenKFiling(BaseModel):
    cik: str
    company: str
    accession_number: str
    primary_document: str
    fiscal_period: str


def latest_10k(submissions: dict) -> TenKFiling | None:
    recent = submissions["filings"]["recent"]
    for index, form in enumerate(recent["form"]):
        if form != "10-K":
            continue
        return TenKFiling(
            cik=str(submissions["cik"]),
            company=submissions["name"],
            accession_number=recent["accessionNumber"][index],
            primary_document=recent["primaryDocument"][index],
            fiscal_period=_fiscal_period(recent["reportDate"][index]),
        )
    return None


def _fiscal_period(report_date: str) -> str:
    return f"FY{report_date[:4]}"


def filing_url(filing: TenKFiling) -> str:
    accession_no_dashes = filing.accession_number.replace("-", "")
    cik_no_leading_zeros = str(int(filing.cik))
    return (
        f"{SEC_ARCHIVES_BASE_URL}/Archives/edgar/data/"
        f"{cik_no_leading_zeros}/{accession_no_dashes}/{filing.primary_document}"
    )


def extract_sections(html: str) -> list[tuple[str, str]]:
    """Split filing text into (item_label, section_text) at 'Item N.' headers.

    A 10-K's table of contents repeats every "Item N." label near-empty
    before the real, much longer body section, and filers spell the same
    label differently between the TOC and the body (case, or a missing
    space after the period: "Item 1A. Risk Factors" vs "Item 1A.Risk
    Factors") — so entries are grouped by the item NUMBER alone (matched
    case-insensitively), not the full label text, and only the longest
    occurrence per number is kept.
    """
    text = _html_to_text(html)
    matches = list(_ITEM_HEADER_RE.finditer(text))
    if not matches:
        return [("Full document", text)]

    longest_by_number: dict[str, tuple[str, str]] = {}
    for index, match in enumerate(matches):
        label = " ".join(match.group().split())
        number_match = _ITEM_NUMBER_RE.match(label)
        if number_match is None:
            continue
        key = number_match.group(1).lower()

        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        if not section_text:
            continue

        existing = longest_by_number.get(key)
        if existing is None or len(section_text) > len(existing[1]):
            longest_by_number[key] = (label, section_text)

    return list(longest_by_number.values())


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.text()


class SecEdgarClient:
    def __init__(
        self,
        user_agent: str,
        *,
        data_http_client: ThrottledHttpClient | None = None,
        archives_http_client: ThrottledHttpClient | None = None,
    ) -> None:
        headers = {"User-Agent": user_agent}
        self._data = data_http_client or ThrottledHttpClient(
            SEC_DATA_BASE_URL,
            min_interval_s=DEFAULT_MIN_INTERVAL_S,
            provider="sec-data",
            default_headers=headers,
        )
        self._archives = archives_http_client or ThrottledHttpClient(
            SEC_ARCHIVES_BASE_URL,
            min_interval_s=DEFAULT_MIN_INTERVAL_S,
            provider="sec-archives",
            default_headers=headers,
        )

    async def fetch_submissions(self, cik: str) -> dict:
        return await self._data.get(f"/submissions/CIK{cik.zfill(10)}.json")

    async def fetch_companyfacts(self, cik: str) -> dict:
        # Raw JSON only — tag-alias resolution into XbrlObservation is P2-S5.
        return await self._data.get(f"/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json")

    async def fetch_filing_html(self, filing: TenKFiling) -> str:
        accession_no_dashes = filing.accession_number.replace("-", "")
        cik_no_leading_zeros = str(int(filing.cik))
        path = (
            f"/Archives/edgar/data/{cik_no_leading_zeros}/"
            f"{accession_no_dashes}/{filing.primary_document}"
        )
        return await self._archives.get_text(path)

    async def ingest_10k(self, cik: str, company: str) -> list[Chunk]:
        submissions = await self.fetch_submissions(cik)
        filing = latest_10k(submissions)
        if filing is None:
            return []

        html = await self.fetch_filing_html(filing)
        source_url = filing_url(filing)

        chunks: list[Chunk] = []
        for section_label, section_text in extract_sections(html):
            for piece_index, piece in enumerate(chunk_text(section_text)):
                chunks.append(
                    Chunk(
                        id=f"{company}:{filing.fiscal_period}:{section_label}:{piece_index}",
                        company=company,
                        filing_type="10-K",
                        fiscal_period=filing.fiscal_period,
                        section=section_label,
                        text=piece,
                        source_location=source_url,
                        language="en",
                    )
                )
        return chunks

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

# Second fallback (see _extract_sections_from_toc below), only tried when
# _ITEM_HEADER_RE finds nothing anywhere in the document.
_PAGE_NUMBER_RE = re.compile(r"^\d+$")
# Below this, a short alternating (title, page-number) run is more likely a
# coincidence in the prose than a real table-of-contents/cross-reference
# block — chosen well under the ~20-entry cross-reference index verified
# for Citigroup's real 10-K (CIK 831001, 2026-09-17, #38), not tuned to it.
_MIN_TOC_RUN_PAIRS = 6

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
        return _extract_sections_from_toc(text)

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


def _extract_sections_from_toc(text: str) -> list[tuple[str, str]]:
    """Second fallback, only reached when no "Item N." header exists
    anywhere in the document. Some filers (verified for Citigroup, CIK
    831001, 2026-09-17, #38) never pair an item's number with its title in
    one text run — the number lives in its own table-of-contents table
    cell, disconnected from the word "Item" entirely, and the real section
    heading in the body is a bare title with no number at all. Those
    filers do include their own cross-reference/table-of-contents block —
    a run of alternating (title, page-number) paragraphs — so its ALL-CAPS
    titles, in the order they're listed, give an independent ordering of
    the document's major sections to split on instead.

    General mechanism (detects the block structurally, doesn't hardcode
    any filer's or sector's title wording), not guaranteed to apply to
    every filer — one that has neither "Item N." headers nor this table
    still falls back to "Full document", same as before this fallback."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    toc_titles, toc_end = _find_toc_all_caps_titles(paragraphs)
    if len(toc_titles) < 2:
        return [("Full document", text)]

    title_set = set(toc_titles)
    body_positions = [
        (index, paragraph)
        for index, paragraph in enumerate(paragraphs)
        if index >= toc_end and paragraph.upper() in title_set
    ]
    if len(body_positions) < 2:
        return [("Full document", text)]

    # A title can recur (e.g. a body cross-reference to its own sub-table
    # of contents, spelled identically) — keep the longest occurrence per
    # label, same rule the primary "Item N." path uses for the same reason.
    longest_by_label: dict[str, tuple[str, str]] = {}
    for position, (para_index, label) in enumerate(body_positions):
        start = para_index + 1
        end = (
            body_positions[position + 1][0]
            if position + 1 < len(body_positions)
            else len(paragraphs)
        )
        section_text = "\n\n".join(paragraphs[start:end]).strip()
        if not section_text:
            continue

        existing = longest_by_label.get(label)
        if existing is None or len(section_text) > len(existing[1]):
            longest_by_label[label] = (label, section_text)

    return list(longest_by_label.values()) if longest_by_label else [("Full document", text)]


def _find_toc_all_caps_titles(paragraphs: list[str]) -> tuple[list[str], int]:
    """Finds the longest run of alternating (title, page-number) paragraph
    pairs and returns its ALL-CAPS titles, in order, plus the paragraph
    index right after the run ends (so body matches before it — the TOC's
    own listing — aren't mistaken for the real section content)."""
    best_run: list[str] = []
    best_run_end = 0
    index = 0
    total = len(paragraphs)
    while index < total - 1:
        run: list[str] = []
        cursor = index
        while (
            cursor + 1 < total
            and not _PAGE_NUMBER_RE.match(paragraphs[cursor])
            and _PAGE_NUMBER_RE.match(paragraphs[cursor + 1])
        ):
            run.append(paragraphs[cursor])
            cursor += 2
        if len(run) > len(best_run):
            best_run, best_run_end = run, cursor
        index = cursor + 1 if cursor > index else index + 1

    if len(best_run) < _MIN_TOC_RUN_PAIRS:
        return [], 0
    all_caps_titles = [p for p in best_run if p.isupper() and any(c.isalpha() for c in p)]
    return all_caps_titles, best_run_end


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

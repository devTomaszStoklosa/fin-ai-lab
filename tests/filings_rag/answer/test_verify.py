from fin_ai_lab.filings_rag.answer.verify import verify_citations_faithful
from fin_ai_lab.filings_rag.models import Answer, Chunk, Citation


def _chunk() -> Chunk:
    return Chunk(
        id="c1",
        company="Microsoft",
        filing_type="10-K",
        fiscal_period="FY2025",
        section="ITEM 1A. RISK FACTORS",
        text="Our business faces many risks including competition and regulation.",
        source_location="https://example.test/filing.htm",
        language="en",
    )


def test_verify_citations_faithful_accepts_a_real_excerpt() -> None:
    chunk = _chunk()
    answer = Answer(
        text="There is competition risk.",
        citations=[
            Citation(
                company="Microsoft",
                filing_type="10-K",
                fiscal_period="FY2025",
                section="ITEM 1A. RISK FACTORS",
                excerpt="risks including competition and regulation",
            )
        ],
        refused=False,
    )

    assert verify_citations_faithful(answer, {chunk.id: chunk}) == []


def test_verify_citations_faithful_rejects_a_fabricated_excerpt() -> None:
    chunk = _chunk()
    answer = Answer(
        text="There is a cybersecurity risk.",
        citations=[
            Citation(
                company="Microsoft",
                filing_type="10-K",
                fiscal_period="FY2025",
                section="ITEM 1A. RISK FACTORS",
                excerpt="major cybersecurity incidents in the past year",
            )
        ],
        refused=False,
    )

    mismatches = verify_citations_faithful(answer, {chunk.id: chunk})

    assert mismatches == ["major cybersecurity incidents in the past year"]


def test_verify_citations_faithful_rejects_when_metadata_does_not_match() -> None:
    chunk = _chunk()
    answer = Answer(
        text="There is competition risk.",
        citations=[
            Citation(
                company="Microsoft",
                filing_type="10-K",
                fiscal_period="FY2024",  # wrong period — real excerpt, wrong source
                section="ITEM 1A. RISK FACTORS",
                excerpt="risks including competition and regulation",
            )
        ],
        refused=False,
    )

    mismatches = verify_citations_faithful(answer, {chunk.id: chunk})

    assert mismatches == ["risks including competition and regulation"]


def test_verify_citations_faithful_tolerates_whitespace_differences() -> None:
    chunk = _chunk()
    answer = Answer(
        text="There is competition risk.",
        citations=[
            Citation(
                company="Microsoft",
                filing_type="10-K",
                fiscal_period="FY2025",
                section="ITEM 1A. RISK FACTORS",
                excerpt="risks   including\ncompetition and regulation",
            )
        ],
        refused=False,
    )

    assert verify_citations_faithful(answer, {chunk.id: chunk}) == []

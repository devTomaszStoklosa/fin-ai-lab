import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402

from fin_ai_lab.core.llm.client import LlmRequest, LlmResult  # noqa: E402
from fin_ai_lab.core.llm.fake import FakeEmbeddingClient, FakeLlmClient  # noqa: E402
from fin_ai_lab.filings_rag.index.persist import save_index  # noqa: E402
from fin_ai_lab.filings_rag.index.store import VectorStore  # noqa: E402
from fin_ai_lab.filings_rag.models import Chunk  # noqa: E402
from fin_ai_lab.portfolio_webapp.api import create_app  # noqa: E402

BUILT_AT = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)
MICROSOFT_EXCERPT = "Artificial intelligence may harm our reputation."


def _chunk(company: str, chunk_id: str, text: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        company=company,
        filing_type="10-K",
        fiscal_period="FY2026",
        section="ITEM 1A. RISK FACTORS",
        text=text,
        source_location="https://example.test/filing.htm",
        language="en",
    )


def _save_index(path: Path) -> None:
    store = VectorStore()
    store.add(
        [
            _chunk("Microsoft", "m1", MICROSOFT_EXCERPT),
            _chunk("Microsoft", "m2", "Datacenter capacity constraints."),
        ],
        [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
    )
    save_index(store, embedding_model="gemini-embedding-2", built_at=BUILT_AT, path=path)


def _answer_response(excerpt: str) -> str:
    return json.dumps(
        {
            "text": "Spółka opisuje ryzyko reputacyjne związane z AI.",
            "citations": [
                {
                    "company": "Microsoft",
                    "filing_type": "10-K",
                    "fiscal_period": "FY2026",
                    "section": "ITEM 1A. RISK FACTORS",
                    "excerpt": excerpt,
                }
            ],
        }
    )


def _client(
    tmp_path: Path,
    *,
    with_index: bool = True,
    llm_client: object | None = None,
    embedding_client: FakeEmbeddingClient | None = None,
    no_embedding_client: bool = False,
) -> TestClient:
    index_path = tmp_path / "index" / "index.npz"
    if with_index:
        _save_index(index_path)
    app = create_app(
        db_path=tmp_path / "test.duckdb",
        openfigi_client_factory=lambda: None,
        llm_client_factory=lambda: llm_client or FakeLlmClient({}),
        price_ratio_fetcher=lambda ticker, since: None,
        filings_index_path=index_path,
        embedding_client_factory=lambda: (
            None if no_embedding_client else embedding_client or FakeEmbeddingClient(dim=4)
        ),
    )
    return TestClient(app)


def test_companies_is_empty_without_a_saved_index(tmp_path: Path) -> None:
    with _client(tmp_path, with_index=False) as client:
        response = client.get("/api/filings-rag/companies")

    assert response.status_code == 200
    assert response.json() == {"built_at": None, "companies": []}


def test_companies_lists_what_the_saved_index_holds(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/api/filings-rag/companies")

    body = response.json()
    assert body["built_at"].startswith("2026-10-13T09:30:00")
    assert body["companies"] == [
        {
            "company": "Microsoft",
            "filing_type": "10-K",
            "fiscal_period": "FY2026",
            "language": "en",
            "sections": ["ITEM 1A. RISK FACTORS"],
            "chunk_count": 2,
        }
    ]


def test_ask_returns_the_answer_with_its_citations(tmp_path: Path) -> None:
    llm_client = FakeLlmClient({"answer": _answer_response(MICROSOFT_EXCERPT)})
    embedding_client = FakeEmbeddingClient(dim=4)

    with _client(tmp_path, llm_client=llm_client, embedding_client=embedding_client) as client:
        response = client.post(
            "/api/filings-rag/ask",
            json={"question": "Jakie ryzyka AI harm reputation?", "company": "Microsoft"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert body["refusal_reason"] is None
    assert body["citations"][0]["excerpt"] == MICROSOFT_EXCERPT
    assert len(llm_client.requests) == 1
    assert len(embedding_client.calls) == 1


def test_ask_without_a_company_refuses_a_question_naming_no_indexed_company(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/filings-rag/ask", json={"question": "What about Nvidia?"})

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert body["refusal_reason"] == "company_not_in_corpus"
    assert body["citations"] == []


def test_ask_returns_409_without_a_saved_index(tmp_path: Path) -> None:
    with _client(tmp_path, with_index=False) as client:
        response = client.post("/api/filings-rag/ask", json={"question": "Jakie ryzyka?"})

    assert response.status_code == 409
    assert "build-index" in response.json()["detail"]


def test_ask_returns_422_for_a_company_not_in_the_index(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/filings-rag/ask", json={"question": "Jakie ryzyka?", "company": "Nvidia"}
        )

    assert response.status_code == 422
    assert "Nvidia" in response.json()["detail"]


def test_ask_rejects_a_blank_question(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/filings-rag/ask", json={"question": ""})

    assert response.status_code == 422


def test_ask_returns_503_without_an_api_key(tmp_path: Path) -> None:
    with _client(tmp_path, no_embedding_client=True) as client:
        response = client.post(
            "/api/filings-rag/ask", json={"question": "Jakie ryzyka?", "company": "Microsoft"}
        )

    assert response.status_code == 503


class _UnavailableLlmClient:
    async def complete(self, request: LlmRequest) -> LlmResult:
        raise genai_errors.ServerError(
            503, {"error": {"message": "High demand", "status": "UNAVAILABLE"}}
        )


def test_ask_returns_503_when_gemini_is_unavailable(tmp_path: Path) -> None:
    with _client(tmp_path, llm_client=_UnavailableLlmClient()) as client:
        response = client.post(
            "/api/filings-rag/ask",
            json={"question": "Which AI risks harm reputation?", "company": "Microsoft"},
        )

    assert response.status_code == 503


def test_ask_returns_502_when_a_citation_is_not_in_the_source(tmp_path: Path) -> None:
    llm_client = FakeLlmClient({"answer": _answer_response("A sentence the filing never says.")})

    with _client(tmp_path, llm_client=llm_client) as client:
        response = client.post(
            "/api/filings-rag/ask",
            json={"question": "Which AI risks harm reputation?", "company": "Microsoft"},
        )

    assert response.status_code == 502

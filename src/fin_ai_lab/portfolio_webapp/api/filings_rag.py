"""Filings RAG endpoints: indexed companies and the ask-a-question tool."""

from fastapi import APIRouter, HTTPException, Request
from google.genai import errors as genai_errors

from fin_ai_lab.core.errors import ResponseValidationError
from fin_ai_lab.filings_rag.service import (
    AnswerRejectedError,
    UnknownCompanyError,
    indexed_companies,
)
from fin_ai_lab.filings_rag.service import ask as ask_filings
from fin_ai_lab.portfolio_webapp.api.common import llm_unavailable
from fin_ai_lab.portfolio_webapp.api.defaults import MODEL
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.schemas import (
    FilingsAnswerOut,
    FilingsAskRequest,
    FilingsIndexOut,
)


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/filings-rag/companies", response_model=FilingsIndexOut)
    def filings_rag_companies(request: Request) -> FilingsIndexOut:
        index = request.app.state.filings_index_cache.get()
        if index is None:
            return FilingsIndexOut(built_at=None, companies=[])
        return FilingsIndexOut(built_at=index.built_at, companies=indexed_companies(index))

    @router.post("/api/filings-rag/ask", response_model=FilingsAnswerOut)
    async def filings_rag_ask(payload: FilingsAskRequest, request: Request) -> FilingsAnswerOut:
        index = request.app.state.filings_index_cache.get()
        if index is None:
            raise HTTPException(
                status_code=409,
                detail="Indeks raportów nie jest jeszcze zbudowany -- uruchom "
                "`uv run fin-ai-lab filings-rag build-index`.",
            )
        embedding_client = deps.embedding_client_factory()
        if embedding_client is None:
            raise HTTPException(
                status_code=503, detail="Brak klucza GEMINI_API_KEY -- nie da się zadać pytania."
            )
        try:
            answer = await ask_filings(
                payload.question,
                index,
                company=payload.company,
                llm_client=deps.llm_client_factory(),
                embedding_client=embedding_client,
                prompt_registry=request.app.state.prompt_registry,
                model=MODEL,
            )
        except UnknownCompanyError as exc:
            raise HTTPException(
                status_code=422, detail=f"Spółki {exc.company} nie ma w indeksie."
            ) from exc
        except genai_errors.APIError as exc:
            raise llm_unavailable(exc) from exc
        except (AnswerRejectedError, ResponseValidationError) as exc:
            # REQ-020: a citation that isn't a verbatim excerpt of its source
            # is never shown -- the whole answer is withheld instead.
            raise HTTPException(
                status_code=502,
                detail="Model zwrócił odpowiedź, której cytatów nie dało się potwierdzić "
                "w źródle -- spróbuj ponownie albo zadaj pytanie inaczej.",
            ) from exc
        return FilingsAnswerOut(
            text=answer.text,
            refused=answer.refused,
            refusal_reason=answer.refusal_reason,
            citations=answer.citations,
        )

    return router

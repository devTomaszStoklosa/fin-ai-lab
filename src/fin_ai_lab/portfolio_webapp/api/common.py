"""Helpers shared by the routers."""

from fastapi import HTTPException
from google.genai import errors as genai_errors


def llm_unavailable(exc: genai_errors.APIError) -> HTTPException:
    # Covers both ServerError (5xx, e.g. "model overloaded") and ClientError
    # (4xx, e.g. Gemini's own rate limit) -- either way the report can't be
    # generated right now, and the raw exception must not reach the owner as
    # an opaque 500 (issue #204).
    return HTTPException(
        status_code=503,
        detail=f"Model AI chwilowo niedostępny ({exc.message}) -- spróbuj ponownie za chwilę.",
    )

"""Benchmarks to compare the value history against."""

from datetime import date as date_type

from fastapi import APIRouter, HTTPException

from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.benchmark import BENCHMARKS, normalize_ticker
from fin_ai_lab.portfolio_webapp.benchmark_builder import (
    BenchmarkNotFoundError,
    BenchmarkUnavailableError,
    build_benchmark,
)
from fin_ai_lab.portfolio_webapp.schemas import (
    BenchmarkOptionOut,
    BenchmarkOut,
)
from fin_ai_lab.portfolio_webapp.valuation import MissingFxRateError


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/benchmarks", response_model=list[BenchmarkOptionOut])
    def list_benchmarks() -> list[BenchmarkOptionOut]:
        return [
            BenchmarkOptionOut(id=b.id, label=b.label, ticker=b.ticker, note=b.note)
            for b in BENCHMARKS
        ]

    # #273: asked for only when the chart's comparison mode is open -- no
    # Yahoo lookup for a benchmark nobody looks at. `start` is the
    # valuation's first day, so both series share one day axis.
    @router.get("/api/benchmark", response_model=BenchmarkOut)
    async def get_benchmark(ticker: str, start: date_type, refresh: bool = False) -> BenchmarkOut:
        normalized = normalize_ticker(ticker)
        if normalized is None:
            raise HTTPException(
                status_code=422,
                detail="Nieprawidłowy ticker -- dozwolone litery, cyfry i znaki . ^ = -",
            )
        try:
            return await build_benchmark(
                normalized,
                start=start,
                today=deps.today_provider(),
                refresh=refresh,
                closes_fetcher=deps.benchmark_closes_fetcher,
                quote_currency_fetcher=deps.quote_currency_fetcher,
                fx_client=deps.fx_client_factory(),
            )
        except BenchmarkNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"Yahoo nie zna tickera {normalized} albo nie ma jego historii.",
            ) from None
        except BenchmarkUnavailableError:
            raise HTTPException(
                status_code=502, detail="Yahoo nie odpowiedziało -- spróbuj ponownie za chwilę."
            ) from None
        except MissingFxRateError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Brak kursu NBP dla {exc.currency} -- nie da się przeliczyć "
                f"{normalized} na PLN.",
            ) from None

    return router

from typing import Literal

from pydantic import BaseModel

from fin_ai_lab.core.http.client import ThrottledHttpClient

OPENFIGI_BASE_URL = "https://api.openfigi.com"
# Verified 2026-09-16 against api.openfigi.com/api/documentation:
# 25 requests/minute without an API key (this repo has none configured),
# 10 jobs per request. See docs/DATA-SOURCES.md.
DEFAULT_MIN_INTERVAL_S = 60 / 25

IdentificationStatus = Literal["resolved", "ambiguous", "unresolved"]


class Identification(BaseModel):
    status: IdentificationStatus
    figi: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None
    security_type: str | None = None
    identification_rule: str | None = None


class OpenFigiClient:
    def __init__(
        self, http_client: ThrottledHttpClient | None = None, api_key: str | None = None
    ) -> None:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-OPENFIGI-APIKEY"] = api_key
        self._http_client = http_client or ThrottledHttpClient(
            OPENFIGI_BASE_URL,
            min_interval_s=DEFAULT_MIN_INTERVAL_S,
            provider="openfigi",
            default_headers=headers,
        )

    async def resolve_by_isin(
        self, isin: str, currency: str, broker_market: str | None = None
    ) -> Identification:
        # OpenFIGI filters listings by currency server-side; we only decide
        # between what's left, per the "Wybór notowania" rule in 02-spec.md.
        job = {"idType": "ID_ISIN", "idValue": isin, "currency": currency}
        response = await self._http_client.post("/v3/mapping", json_body=[job])
        matches = response[0].get("data", [])

        if not matches:
            return Identification(status="unresolved")

        if len(matches) == 1:
            return _to_identification(matches[0], "resolved", "only listing in currency")

        if broker_market is not None:
            broker_matches = [match for match in matches if match.get("exchCode") == broker_market]
            if len(broker_matches) == 1:
                return _to_identification(broker_matches[0], "resolved", "broker market")

        return Identification(status="ambiguous")


def _to_identification(
    match: dict, status: IdentificationStatus, identification_rule: str
) -> Identification:
    return Identification(
        status=status,
        figi=match.get("figi"),
        ticker=match.get("ticker"),
        exchange_code=match.get("exchCode"),
        security_type=match.get("securityType"),
        identification_rule=identification_rule,
    )

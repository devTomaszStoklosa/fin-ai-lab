import asyncio
import hashlib
import json
import time
from pathlib import Path

import httpx

CACHE_DIR = Path("data/cache/http")
MAX_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ThrottledHttpClient:
    """A per-provider HTTP client: a minimum interval between requests (our
    own throttling, not reacting to 429s), retry with backoff for 429/5xx,
    and an on-disk cache keyed by the request itself — including "no result"
    responses, so a repeated lookup for the same input never pays twice."""

    def __init__(
        self,
        base_url: str,
        *,
        min_interval_s: float,
        provider: str,
        default_headers: dict[str, str] | None = None,
        cache_dir: Path = CACHE_DIR,
        timeout_s: float = 30.0,
        retry_backoff_base_s: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._min_interval_s = min_interval_s
        self._default_headers = default_headers or {}
        self._cache_dir = cache_dir / provider
        self._timeout_s = timeout_s
        self._retry_backoff_base_s = retry_backoff_base_s
        self._transport = transport
        self._last_request_at: float | None = None
        self._lock = asyncio.Lock()

    async def get(self, path: str, params: dict[str, object] | None = None) -> object:
        return await self._request("GET", path, params=params or {})

    async def post(self, path: str, json_body: object) -> object:
        return await self._request("POST", path, json_body=json_body)

    async def get_text(self, path: str, params: dict[str, object] | None = None) -> str:
        # For non-JSON responses (e.g. SEC EDGAR filing HTML) — get()/post()
        # always call response.json(), which fails on these.
        return await self._request("GET", path, params=params or {}, as_text=True)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: object = None,
        as_text: bool = False,
    ) -> object:
        cache_key = self._cache_key(method, path, params, json_body, as_text)
        cached = self._read_cache(cache_key, as_text)
        if cached is not None:
            return cached

        await self._throttle()

        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport) as client:
            response = await self._send_with_retries(client, method, url, params, json_body)

        response.raise_for_status()
        result = response.text if as_text else response.json()
        self._write_cache(cache_key, result, as_text)
        return result

    async def _send_with_retries(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        params: dict[str, object] | None,
        json_body: object,
    ) -> httpx.Response:
        response: httpx.Response | None = None
        for attempt in range(MAX_ATTEMPTS):
            response = await client.request(
                method, url, params=params, json=json_body, headers=self._default_headers
            )
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(self._retry_backoff_base_s * (2**attempt))
        return response

    async def _throttle(self) -> None:
        async with self._lock:
            if self._last_request_at is not None:
                remaining = self._min_interval_s - (time.monotonic() - self._last_request_at)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_request_at = time.monotonic()

    def _cache_key(
        self,
        method: str,
        path: str,
        params: dict[str, object] | None,
        json_body: object,
        as_text: bool = False,
    ) -> str:
        payload = {
            "method": method,
            "path": path,
            "params": params,
            "json": json_body,
            "as_text": as_text,
        }
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _read_cache(self, key: str, as_text: bool = False) -> object | None:
        suffix = "txt" if as_text else "json"
        path = self._cache_dir / f"{key}.{suffix}"
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        return text if as_text else json.loads(text)

    def _write_cache(self, key: str, value: object, as_text: bool = False) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        suffix = "txt" if as_text else "json"
        content = value if as_text else json.dumps(value)
        (self._cache_dir / f"{key}.{suffix}").write_text(content, encoding="utf-8")

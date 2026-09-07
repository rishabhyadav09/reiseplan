from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import httpx

from ..config import settings
from ..domain import PlanRequest, ProviderResult

log = logging.getLogger(__name__)


class UpstreamUnavailable(Exception):
    """The upstream could not be reached or refused. Distinct from 'no results'."""


class Provider(Protocol):
    name: str

    async def search(self, req: PlanRequest) -> ProviderResult:
        """Never raises. Signals failure via ProviderResult.degraded so the
        caller can tell 'no trains exist' from 'we could not ask'."""
        ...


_client: httpx.AsyncClient | None = None
_db_gate = asyncio.Semaphore(settings.db_max_concurrency)


def http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=settings.http_timeout_s,
            headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )
    return _client


async def close_http() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def db_get(path: str, params: dict) -> dict | list | None:
    """GET against the DB REST wrapper, throttled, with bounded retries.

    Raises UpstreamUnavailable when the upstream cannot answer. Returning None
    for both "no results" and "server is down" is what let a 503 masquerade as
    "there are no trains from Dortmund to Frankfurt".

    503 and 429 are retried with backoff because the shared instance sheds load
    in short bursts; 4xx other than 429 is a real client error and is not.
    """
    url = f"{settings.db_api_base.rstrip('/')}{path}"
    last = "unknown"

    for attempt in range(3):
        if attempt:
            await asyncio.sleep(0.4 * (2 ** (attempt - 1)))
        async with _db_gate:
            try:
                resp = await http().get(url, params=params)
            except httpx.HTTPError as exc:
                last = type(exc).__name__
                log.warning("db request failed path=%s err=%s", path, exc)
                continue

        if resp.status_code in (429, 502, 503, 504):
            last = f"HTTP {resp.status_code}"
            log.warning("db unavailable path=%s status=%s attempt=%s",
                        path, resp.status_code, attempt + 1)
            continue
        if resp.status_code >= 400:
            log.warning("db client error path=%s status=%s", path, resp.status_code)
            raise UpstreamUnavailable(f"Deutsche Bahn returned HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise UpstreamUnavailable("Deutsche Bahn returned a malformed response") from None

    raise UpstreamUnavailable(f"Deutsche Bahn unreachable after 3 attempts ({last})")

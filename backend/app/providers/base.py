from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import httpx

from ..config import settings
from ..domain import Itinerary, PlanRequest

log = logging.getLogger(__name__)


class Provider(Protocol):
    name: str

    async def search(self, req: PlanRequest) -> list[Itinerary]:
        """Return zero or more itineraries. Must never raise: a provider that
        is down should degrade the result set, not fail the request."""
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
    """GET against the DB REST wrapper, throttled and fail-soft.

    The upstream returns 429 readily. We do not retry aggressively; a missing
    rail option is far better than getting the whole deployment blocked.
    """
    url = f"{settings.db_api_base.rstrip('/')}{path}"
    async with _db_gate:
        try:
            resp = await http().get(url, params=params)
        except httpx.HTTPError as exc:
            log.warning("db request failed path=%s err=%s", path, exc)
            return None

    if resp.status_code == 429:
        log.warning("db rate limited path=%s — run your own db-vendo-client", path)
        return None
    if resp.status_code >= 400:
        log.warning("db error path=%s status=%s", path, resp.status_code)
        return None
    try:
        return resp.json()
    except ValueError:
        return None

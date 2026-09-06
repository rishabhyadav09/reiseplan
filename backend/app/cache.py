"""Cache with request coalescing.

DB's vendo/movas endpoints block aggressively and rate limit hard, so caching
is not an optimisation here, it is a requirement for the service to stay up.
Two identical searches arriving together must produce one upstream call, so
this does single-flight dedup as well as plain caching.

Redis when REDIS_URL is set, in-process dict otherwise, so `uvicorn app.main:app`
works with no infrastructure at all.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .config import settings

try:  # optional
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    Redis = None  # type: ignore[assignment]


def key_for(namespace: str, payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return f"{namespace}:{hashlib.sha256(blob.encode()).hexdigest()[:20]}"


class Cache:
    def __init__(self) -> None:
        self._local: dict[str, tuple[float, Any]] = {}
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._redis: Any = None
        if settings.redis_url and Redis is not None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        if self._redis is not None:
            raw = await self._redis.get(key)
            return json.loads(raw) if raw else None
        hit = self._local.get(key)
        if not hit:
            return None
        expires_at, value = hit
        if expires_at < time.time():
            self._local.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if self._redis is not None:
            await self._redis.set(key, json.dumps(value, default=str), ex=ttl)
        else:
            self._local[key] = (time.time() + ttl, value)

    async def get_or_set(
        self, key: str, ttl: int, producer: Callable[[], Awaitable[Any]]
    ) -> Any:
        """Cached fetch. Concurrent misses on the same key share one upstream call."""
        cached = await self.get(key)
        if cached is not None:
            return cached

        running = self._inflight.get(key)
        if running is not None:
            return await asyncio.shield(running)

        task = asyncio.create_task(producer())
        self._inflight[key] = task
        try:
            value = await task
        finally:
            self._inflight.pop(key, None)

        if value is not None:
            await self.set(key, value, ttl)
        return value

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()


cache = Cache()

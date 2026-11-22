"""The heart of the CDN edge: decide HIT, MISS or REVALIDATED for each request.

    fresh copy in cache        -> HIT          (origin not contacted at all)
    stale copy with an ETag    -> ask origin "changed?" (If-None-Match)
        origin says 304        -> REVALIDATED  (reuse body, reset its age)
        origin sends new body  -> MISS         (store the new version)
    nothing in cache           -> MISS         (fetch, store if cacheable)
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from edge.cache import Cache, CacheEntry, make_key, parse_max_age
from edge.models import CacheStatus
from edge.origin_client import OriginClient, OriginResponse
from edge.stats import Stats


@dataclass(frozen=True)
class EdgeResponse:
    status: int
    body: bytes
    headers: dict[str, str]
    cache_status: CacheStatus
    age: int  # seconds since the edge got this content from the origin


class ProxyService:
    def __init__(
        self,
        cache: Cache,
        origin: OriginClient,
        stats: Stats,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache = cache
        self.origin = origin
        self.stats = stats
        self._clock = clock

    async def get(self, path: str, query: str) -> EdgeResponse:
        """Serve a GET request and record how it went in the stats."""
        started = time.perf_counter()
        response = await self._serve(path, query)
        self.stats.record(response.cache_status, (time.perf_counter() - started) * 1000)
        return response

    async def _serve(self, path: str, query: str) -> EdgeResponse:
        key = make_key("GET", path, query)
        entry = self.cache.get(key)
        now = self._clock()

        if entry is not None and entry.is_fresh(now):
            return _from_entry(entry, CacheStatus.HIT, now)

        etag = entry.etag if entry is not None else None
        fresh = await self.origin.fetch(path, query, etag=etag)

        if fresh.status == 304 and entry is not None:
            refreshed = self._refresh(key, entry, fresh, now)
            return _from_entry(refreshed, CacheStatus.REVALIDATED, now)

        self._store_if_cacheable(key, fresh, now)
        return EdgeResponse(fresh.status, fresh.body, fresh.headers, CacheStatus.MISS, age=0)

    def _refresh(self, key: str, entry: CacheEntry, not_modified: OriginResponse, now: float) -> CacheEntry:
        """Origin confirmed our copy is current: keep the body, restart the clock."""
        max_age = parse_max_age(not_modified.headers.get("cache-control", "")) or entry.max_age
        refreshed = replace(entry, stored_at=now, max_age=max_age)
        self.cache.put(key, refreshed)
        return refreshed

    def _store_if_cacheable(self, key: str, response: OriginResponse, now: float) -> None:
        """Only successful responses that the origin allows us to keep are cached."""
        max_age = parse_max_age(response.headers.get("cache-control", ""))
        if response.status != 200 or max_age is None:
            return
        self.cache.put(key, CacheEntry(response.status, response.body, response.headers, max_age, now))


def _from_entry(entry: CacheEntry, status: CacheStatus, now: float) -> EdgeResponse:
    return EdgeResponse(entry.status, entry.body, entry.headers, status, entry.age(now))

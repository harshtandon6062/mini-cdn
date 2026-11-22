"""The edge's in-memory cache: stores origin responses, evicts with LRU.

Key   = "GET /path?query"  (two different URLs are two different entries)
Value = a CacheEntry: the response plus when it was stored and its max-age.

An entry that is past its max-age is "stale" but is NOT deleted: we keep it
so we can revalidate it with the origin using its ETag. Entries only leave
the cache when evicted (cache full) or purged by an admin.
"""

from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True)
class CacheEntry:
    status: int
    body: bytes
    headers: dict[str, str]  # only headers worth replaying (content-type, etag, ...)
    max_age: int  # seconds this entry may be served without asking the origin
    stored_at: float  # clock time when the entry was stored or last revalidated

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag")

    def age(self, now: float) -> int:
        return int(now - self.stored_at)

    def is_fresh(self, now: float) -> bool:
        return now - self.stored_at < self.max_age


def make_key(method: str, path: str, query: str) -> str:
    return f"{method} {path}?{query}"


def parse_max_age(cache_control: str) -> int | None:
    """Return how many seconds a response may be cached, or None if it must not be.

    We keep it deliberately simple: no-store/private/no-cache or a missing or
    zero max-age all mean "do not cache".
    """
    directives = [d.strip().lower() for d in cache_control.split(",")]
    if {"no-store", "private", "no-cache"} & set(directives):
        return None
    for directive in directives:
        if directive.startswith("max-age="):
            value = directive.removeprefix("max-age=")
            return int(value) if value.isdigit() and int(value) > 0 else None
    return None


class Cache:
    """A size-limited dictionary that forgets the least recently used entry first."""

    def __init__(self, max_entries: int) -> None:
        self.max_entries = max_entries
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> CacheEntry | None:
        entry = self._entries.get(key)
        if entry is not None:
            self._entries.move_to_end(key)  # mark as most recently used
        return entry

    def put(self, key: str, entry: CacheEntry) -> None:
        self._entries[key] = entry
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)  # evict the least recently used

    def purge(self, path: str | None = None) -> int:
        """Remove every entry for `path` (any query string), or everything if None."""
        if path is None:
            removed = len(self._entries)
            self._entries.clear()
            return removed
        doomed = [key for key in self._entries if _path_of(key) == path]
        for key in doomed:
            del self._entries[key]
        return len(doomed)


def _path_of(key: str) -> str:
    """'GET /a/b?x=1' -> '/a/b'"""
    return key.split(" ", 1)[1].split("?", 1)[0]

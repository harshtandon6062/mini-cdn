"""The only part of the edge that talks to the origin over the network.

It wraps one shared httpx.AsyncClient (connection pooling: TCP connections
to the origin are reused instead of re-opened for every request). Tests pass
in a fake `transport` so no real network is ever used.
"""

from dataclasses import dataclass

import httpx

# Headers the edge keeps from the origin and replays to clients.
FORWARDED_HEADERS = {"content-type", "cache-control", "etag", "last-modified"}


class OriginUnavailableError(Exception):
    """The origin could not be reached (down, timed out, connection refused)."""


@dataclass(frozen=True)
class OriginResponse:
    status: int
    body: bytes
    headers: dict[str, str]


class OriginClient:
    def __init__(
        self, base_url: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def fetch(self, path: str, query: str, etag: str | None = None) -> OriginResponse:
        """GET path?query from the origin. With an etag, asks "only send it if it changed"."""
        url = f"{path}?{query}" if query else path
        headers = {"If-None-Match": etag} if etag else {}
        try:
            response = await self._client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise OriginUnavailableError(str(exc)) from exc
        kept = {k.lower(): v for k, v in response.headers.items() if k.lower() in FORWARDED_HEADERS}
        return OriginResponse(response.status_code, response.content, kept)

    async def close(self) -> None:
        await self._client.aclose()

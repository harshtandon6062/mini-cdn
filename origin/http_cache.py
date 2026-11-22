"""HTTP caching helpers for the origin server.

The origin tells caches (browsers, our edge) two things about every response:
  * Cache-Control: how long the response may be reused without asking again.
  * ETag: a fingerprint of the content. A cache can later ask "is it still
    this fingerprint?" (If-None-Match) and get a tiny 304 instead of the body.
"""

import hashlib

from fastapi import Request, Response


def make_etag(body: bytes) -> str:
    """A strong ETag: a short hash of the body, wrapped in quotes as HTTP requires."""
    return '"' + hashlib.sha256(body).hexdigest()[:16] + '"'


def client_has_current_version(request: Request, etag: str) -> bool:
    """True if the client's If-None-Match header already lists this ETag."""
    sent = request.headers.get("if-none-match", "")
    tags = [tag.strip() for tag in sent.split(",") if tag.strip()]
    return etag in tags or "*" in tags


def cacheable_response(
    request: Request, body: bytes, media_type: str, cache_control: str
) -> Response:
    """Build a response with ETag + Cache-Control, or a 304 if the client is up to date."""
    etag = make_etag(body)
    headers = {"ETag": etag, "Cache-Control": cache_control}
    if client_has_current_version(request, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type=media_type, headers=headers)

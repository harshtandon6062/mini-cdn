"""Edge caching behaviour: HIT / MISS / REVALIDATED, no-store, keys and LRU."""

import httpx
from fastapi.testclient import TestClient

from edge.main import create_app
from tests.conftest import make_settings


def test_first_request_is_miss_then_hit(edge):
    first = edge.client.get("/page")
    second = edge.client.get("/page")

    assert first.status_code == 200 and first.headers["x-cache"] == "MISS"
    assert second.status_code == 200 and second.headers["x-cache"] == "HIT"
    assert second.content == first.content
    assert edge.origin.calls == 1  # the origin was only contacted once


def test_age_header_grows_while_cached(edge):
    edge.client.get("/page")
    edge.clock.advance(7)

    response = edge.client.get("/page")

    assert response.headers["x-cache"] == "HIT"
    assert response.headers["age"] == "7"


def test_no_store_is_never_cached(edge):
    for _ in range(3):
        response = edge.client.get("/live")
        assert response.headers["x-cache"] == "MISS"
    assert edge.origin.calls == 3


def test_errors_are_not_cached(edge):
    edge.client.get("/missing")
    response = edge.client.get("/missing")

    assert response.status_code == 404
    assert response.headers["x-cache"] == "MISS"
    assert edge.origin.calls == 2


def test_query_string_is_part_of_the_cache_key(edge):
    edge.client.get("/api/items?page=1")
    response = edge.client.get("/api/items?page=2")

    assert response.headers["x-cache"] == "MISS"
    assert edge.origin.calls == 2


def test_expired_entry_is_revalidated_with_etag(edge):
    edge.client.get("/api/items")  # MISS, max-age=10
    edge.clock.advance(11)  # now stale

    response = edge.client.get("/api/items")

    assert response.headers["x-cache"] == "REVALIDATED"
    assert response.content == b'[{"id":1}]'  # body came from the cache
    assert response.headers["age"] == "0"
    last_request = edge.origin.requests[-1]
    assert last_request.headers["if-none-match"] == '"v1"'


def test_revalidated_entry_is_fresh_again(edge):
    edge.client.get("/api/items")
    edge.clock.advance(11)
    edge.client.get("/api/items")  # REVALIDATED

    response = edge.client.get("/api/items")

    assert response.headers["x-cache"] == "HIT"
    assert edge.origin.calls == 2


def test_lru_evicts_least_recently_used_entry(make_edge):
    edge = make_edge(cache_max_entries=2)
    edge.client.get("/a")
    edge.client.get("/b")
    edge.client.get("/a")  # /a is now more recently used than /b
    edge.client.get("/c")  # cache full: evicts /b

    assert edge.client.get("/a").headers["x-cache"] == "HIT"
    assert edge.client.get("/b").headers["x-cache"] == "MISS"


def test_origin_down_returns_502():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    app = create_app(make_settings(), httpx.MockTransport(refuse))
    with TestClient(app) as client:
        assert client.get("/page").status_code == 502

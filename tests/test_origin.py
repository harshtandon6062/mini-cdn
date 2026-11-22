"""The origin's own HTTP caching behaviour: Cache-Control, ETag, 304, hashed CSS."""

import pytest
from fastapi.testclient import TestClient

from origin import content
from origin.main import app


@pytest.fixture
def origin(monkeypatch) -> TestClient:
    monkeypatch.setenv("ORIGIN_DELAY_MS", "0")
    return TestClient(app)


def test_routes_have_their_own_cache_policy(origin):
    assert origin.get("/").headers["cache-control"] == "public, max-age=30"
    assert origin.get("/api/products").headers["cache-control"] == "public, max-age=10"
    assert origin.get("/api/time").headers["cache-control"] == "no-store"


def test_matching_if_none_match_returns_304_without_body(origin):
    etag = origin.get("/api/products/1").headers["etag"]

    response = origin.get("/api/products/1", headers={"If-None-Match": etag})

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == etag


def test_stale_etag_gets_full_response(origin):
    response = origin.get("/api/products/1", headers={"If-None-Match": '"old"'})
    assert response.status_code == 200
    assert response.json()["id"] == 1


def test_hashed_css_is_immutable_and_unknown_hash_is_404(origin):
    response = origin.get(content.CSS_URL)
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]
    assert origin.get("/static/styles.deadbeef.css").status_code == 404

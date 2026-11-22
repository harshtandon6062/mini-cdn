"""Admin API: login, JWT-protected purge, and stats."""

from datetime import datetime, timedelta, timezone

import jwt

from tests.conftest import ADMIN_PASSWORD


def test_login_with_wrong_password_is_rejected(edge):
    response = edge.client.post("/admin/login", json={"username": "admin", "password": "nope"})
    assert response.status_code == 401


def test_login_returns_a_jwt(edge):
    response = edge.client.post(
        "/admin/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    body = response.json()

    assert response.status_code == 200
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60


def test_purge_requires_a_token(edge):
    assert edge.client.post("/admin/purge", json={}).status_code == 401


def test_purge_rejects_a_forged_token(edge):
    forged = jwt.encode({"sub": "admin"}, "some-other-secret-of-sufficient-length", algorithm="HS256")
    response = edge.client.post(
        "/admin/purge", json={}, headers={"Authorization": f"Bearer {forged}"}
    )
    assert response.status_code == 401


def test_purge_rejects_an_expired_token(edge):
    expired = jwt.encode(
        {"sub": "admin", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        "test-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
    )
    response = edge.client.post(
        "/admin/purge", json={}, headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401


def test_purge_one_path(edge):
    edge.client.get("/page")
    edge.client.get("/api/items?page=1")
    edge.client.get("/api/items?page=2")
    auth = {"Authorization": f"Bearer {edge.login()}"}

    response = edge.client.post("/admin/purge", json={"path": "/api/items"}, headers=auth)

    assert response.json() == {"purged": 2}  # both query-string variants removed
    assert edge.client.get("/api/items?page=1").headers["x-cache"] == "MISS"
    assert edge.client.get("/page").headers["x-cache"] == "HIT"  # untouched


def test_purge_everything(edge):
    edge.client.get("/page")
    edge.client.get("/api/items")
    auth = {"Authorization": f"Bearer {edge.login()}"}

    response = edge.client.post("/admin/purge", json={}, headers=auth)

    assert response.json() == {"purged": 2}
    assert edge.client.get("/page").headers["x-cache"] == "MISS"


def test_stats_counts_are_correct(edge):
    edge.client.get("/page")  # MISS
    edge.client.get("/page")  # HIT
    edge.client.get("/page")  # HIT
    edge.client.get("/api/items")  # MISS
    edge.clock.advance(11)
    edge.client.get("/api/items")  # REVALIDATED
    edge.client.get("/live")  # MISS (no-store)

    stats = edge.client.get("/admin/stats").json()

    assert stats["hits"] == 2
    assert stats["misses"] == 3
    assert stats["revalidations"] == 1
    assert stats["total_requests"] == 6
    assert stats["hit_ratio"] == round(2 / 6, 3)
    assert stats["cache_entries"] == 2
    assert set(stats["avg_latency_ms"]) == {"HIT", "MISS", "REVALIDATED"}

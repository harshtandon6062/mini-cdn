"""Zero-trust gateway: identity (401), policy (403, default deny), per-user rate limit, audit log.

Test users (see conftest.py): alice = engineer, bob = intern, admin = admin.
Test policy (tests/test_policy.json):
    /  and /page  -> any logged-in user (exact match)
    /api/*        -> engineer, admin    (prefix match)
    /internal/*   -> admin
"""

import logging
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from tests.conftest import JWT_SECRET


@pytest.fixture
def gateway(make_edge):
    return make_edge(zero_trust_enabled=True)


def test_no_token_is_401_and_origin_is_not_called(gateway):
    response = gateway.client.get("/page")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert gateway.origin.calls == 0


def test_expired_token_is_401(gateway):
    expired = jwt.encode(
        {"sub": "alice", "role": "engineer", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        JWT_SECRET,
        algorithm="HS256",
    )
    assert gateway.get_as("alice", "/page", token=expired).status_code == 401


def test_token_signed_with_another_secret_is_401(gateway):
    forged = jwt.encode(
        {"sub": "alice", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "attacker-secret-that-is-also-long-enough",
        algorithm="HS256",
    )
    assert gateway.get_as("alice", "/page", token=forged).status_code == 401


def test_login_returns_role(gateway):
    response = gateway.client.post("/auth/login", json={"username": "bob", "password": "user-pass"})
    assert response.status_code == 200
    assert response.json()["role"] == "intern"


def test_wrong_role_is_403(gateway):
    assert gateway.get_as("bob", "/api/items").status_code == 403


def test_unknown_path_is_403_default_deny(gateway):
    # Even admin is blocked, and the "/" rule must not act as a catch-all.
    assert gateway.get_as("admin", "/not-in-policy").status_code == 403
    assert gateway.origin.calls == 0


def test_path_traversal_is_403(gateway):
    # %2e%2e is ".." : must not sneak from /api/ into /internal/
    assert gateway.get_as("alice", "/api/%2e%2e/internal/report").status_code == 403


def test_allowed_request_is_200_then_cache_hit(gateway):
    token = gateway.login("alice")

    first = gateway.get_as("alice", "/api/items", token)
    second = gateway.get_as("alice", "/api/items", token)

    assert first.status_code == 200 and first.headers["x-cache"] == "MISS"
    assert second.status_code == 200 and second.headers["x-cache"] == "HIT"


def test_cached_response_is_not_served_to_a_role_that_is_not_allowed(gateway):
    assert gateway.get_as("alice", "/api/items").status_code == 200  # now cached

    response = gateway.get_as("bob", "/api/items")

    assert response.status_code == 403  # policy runs before the cache lookup
    assert b"id" not in response.content
    assert gateway.origin.calls == 1


def test_private_responses_are_never_cached(gateway):
    token = gateway.login("admin")
    for _ in range(2):
        response = gateway.get_as("admin", "/internal/report", token)
        assert response.status_code == 200 and response.headers["x-cache"] == "MISS"


def test_rate_limit_is_per_user(make_edge):
    gateway = make_edge(zero_trust_enabled=True, rate_limit_capacity=2, rate_limit_refill_per_second=0.01)
    alice, bob = gateway.login("alice"), gateway.login("bob")

    statuses = [gateway.get_as("alice", "/page", alice).status_code for _ in range(3)]

    assert statuses == [200, 200, 429]
    assert gateway.get_as("bob", "/page", bob).status_code == 200  # bob has his own bucket


def test_non_admin_cannot_purge(gateway):
    token = gateway.login("alice")
    response = gateway.client.post("/admin/purge", json={}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_audit_log_and_stats_record_decisions(gateway, caplog):
    caplog.set_level(logging.INFO, logger="edge.access")

    gateway.client.get("/page")  # 401
    gateway.get_as("bob", "/api/items")  # 403
    gateway.get_as("alice", "/api/items")  # allowed

    log = caplog.text
    assert "decision=DENIED_401" in log
    assert 'user=bob role=intern decision=DENIED_403 reason="rule /api/* does not allow role intern"' in log
    assert "user=alice role=engineer decision=ALLOWED" in log
    decisions = gateway.client.get("/admin/stats").json()["access_decisions"]
    assert decisions == {"ALLOWED": 1, "DENIED_401": 1, "DENIED_403": 1, "RATE_LIMITED": 0}

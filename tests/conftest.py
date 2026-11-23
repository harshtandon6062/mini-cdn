"""Shared test fixtures: a fake origin, a fake clock, and a factory for edge clients.

The fake origin is plugged in with httpx.MockTransport, so the edge's real
OriginClient code runs but no network is used. The fake clock lets tests
"wait" 60 seconds instantly.

Zero trust is OFF by default here so the plain CDN tests stay simple;
tests/test_zero_trust.py turns it on with make_edge(zero_trust_enabled=True).
"""

from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

import bcrypt
import httpx
import pytest
from fastapi.testclient import TestClient

from edge.config import Settings
from edge.main import create_app

ADMIN_PASSWORD = "correct-horse"
USER_PASSWORD = "user-pass"  # password of alice (engineer) and bob (intern)
JWT_SECRET = "test-secret-that-is-long-enough-for-hs256"

TEST_POLICY = Path(__file__).parent / "test_policy.json"
ETAG = '"v1"'

# path -> (body, Cache-Control) served by the fake origin
ORIGIN_ROUTES = {
    "/page": (b"<h1>page</h1>", "public, max-age=30"),
    "/api/items": (b'[{"id":1}]', "public, max-age=10"),
    "/live": (b'{"time":"now"}', "no-store"),
    "/a": (b"a", "max-age=60"),
    "/b": (b"b", "max-age=60"),
    "/c": (b"c", "max-age=60"),
    "/internal/report": (b'{"secret":true}', "private, max-age=60"),
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeOrigin:
    requests: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path not in ORIGIN_ROUTES:
            return httpx.Response(404, json={"detail": "Not Found"})
        body, cache_control = ORIGIN_ROUTES[request.url.path]
        headers = {"cache-control": cache_control, "etag": ETAG}
        if request.headers.get("if-none-match") == ETAG:
            return httpx.Response(304, headers=headers)
        return httpx.Response(200, content=body, headers={**headers, "content-type": "text/plain"})

    @property
    def calls(self) -> int:
        return len(self.requests)


@dataclass
class EdgeHarness:
    client: TestClient
    origin: FakeOrigin
    clock: FakeClock

    def login(self, username: str = "admin") -> str:
        password = ADMIN_PASSWORD if username == "admin" else USER_PASSWORD
        response = self.client.post("/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200
        return response.json()["access_token"]

    def get_as(self, username: str, path: str, token: str | None = None):
        """GET path with the user's Bearer token (logs in if no token given)."""
        token = token or self.login(username)
        return self.client.get(path, headers={"Authorization": f"Bearer {token}"})


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()  # fast for tests


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "origin_url": "http://origin.test",
        "jwt_secret": JWT_SECRET,
        "admin_username": "admin",
        "admin_password_hash": _hash(ADMIN_PASSWORD),
        "users": {
            "alice": {"role": "engineer", "password_hash": _hash(USER_PASSWORD)},
            "bob": {"role": "intern", "password_hash": _hash(USER_PASSWORD)},
        },
        "zero_trust_enabled": False,
        "policy_file": str(TEST_POLICY),
        "rate_limit_capacity": 1000,
        "rate_limit_refill_per_second": 1000.0,
        **overrides,
    }
    return Settings(_env_file=None, **values)


@pytest.fixture
def make_edge() -> Iterator:
    """Factory: make_edge(cache_max_entries=2) -> EdgeHarness with a running TestClient."""
    with ExitStack() as stack:

        def _make(**overrides: object) -> EdgeHarness:
            origin, clock = FakeOrigin(), FakeClock()
            app = create_app(make_settings(**overrides), httpx.MockTransport(origin.handle), clock)
            client = stack.enter_context(TestClient(app))
            return EdgeHarness(client, origin, clock)

        yield _make


@pytest.fixture
def edge(make_edge) -> EdgeHarness:
    return make_edge()

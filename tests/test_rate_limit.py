"""Token bucket rate limiting, through the HTTP API and as a unit."""

from edge.rate_limiter import RateLimiter
from tests.conftest import FakeClock


def test_burst_over_capacity_gets_429_with_retry_after(make_edge):
    edge = make_edge(rate_limit_capacity=3, rate_limit_refill_per_second=0.5)

    statuses = [edge.client.get("/page").status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]
    blocked = edge.client.get("/page")
    assert blocked.headers["retry-after"] == "2"  # 1 token at 0.5 tokens/s = 2 s
    assert edge.client.get("/admin/stats").json()["rate_limited"] == 2


def test_tokens_refill_over_time(make_edge):
    edge = make_edge(rate_limit_capacity=1, rate_limit_refill_per_second=1)
    assert edge.client.get("/page").status_code == 200
    assert edge.client.get("/page").status_code == 429

    edge.clock.advance(1)

    assert edge.client.get("/page").status_code == 200


def test_each_client_has_its_own_bucket():
    limiter = RateLimiter(capacity=1, refill_per_second=1, clock=FakeClock())

    assert limiter.check("1.1.1.1") == (True, 0.0)
    assert limiter.check("1.1.1.1")[0] is False
    assert limiter.check("2.2.2.2")[0] is True

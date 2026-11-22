"""Per-client rate limiting with the token bucket algorithm.

Each client IP has a bucket holding up to `capacity` tokens. Every request
costs one token. Tokens drip back in at `refill_per_second`. So a client can
burst up to `capacity` requests, but over time is limited to the refill rate.
When the bucket is empty we tell the client how long to wait (Retry-After).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class RateLimiter:
    def __init__(
        self, capacity: int, refill_per_second: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def check(self, client_id: str) -> tuple[bool, float]:
        """Try to spend one token. Returns (allowed, seconds_until_next_token)."""
        now = self._clock()
        bucket = self._buckets.setdefault(client_id, _Bucket(self.capacity, now))
        elapsed = now - bucket.updated_at
        bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_per_second)
        bucket.updated_at = now
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return True, 0.0
        return False, (1 - bucket.tokens) / self.refill_per_second

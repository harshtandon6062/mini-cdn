"""Counters that show how well the edge is doing (served at GET /admin/stats).

The key CDN metric is the hit ratio: the share of requests answered from the
cache without downloading anything from the origin.
"""

from edge.models import CacheStatus, StatsResponse

ACCESS_DECISIONS = ("ALLOWED", "DENIED_401", "DENIED_403", "RATE_LIMITED")


class Stats:
    def __init__(self) -> None:
        self.counts = {status: 0 for status in CacheStatus}
        self._latency_total_ms = {status: 0.0 for status in CacheStatus}
        self.rate_limited = 0
        self.decisions = {d: 0 for d in ACCESS_DECISIONS}

    def record_decision(self, decision: str) -> None:
        """Count one zero-trust access decision (ALLOWED, DENIED_401, ...)."""
        self.decisions[decision] = self.decisions.get(decision, 0) + 1

    def record(self, status: CacheStatus, latency_ms: float) -> None:
        self.counts[status] += 1
        self._latency_total_ms[status] += latency_ms

    def snapshot(self, cache_entries: int, cache_capacity: int) -> StatsResponse:
        total = sum(self.counts.values())
        hits = self.counts[CacheStatus.HIT]
        return StatsResponse(
            hits=hits,
            misses=self.counts[CacheStatus.MISS],
            revalidations=self.counts[CacheStatus.REVALIDATED],
            total_requests=total,
            hit_ratio=round(hits / total, 3) if total else 0.0,
            avg_latency_ms={s.value: self._average(s) for s in CacheStatus},
            rate_limited=self.rate_limited,
            access_decisions=dict(self.decisions),
            cache_entries=cache_entries,
            cache_capacity=cache_capacity,
        )

    def _average(self, status: CacheStatus) -> float:
        count = self.counts[status]
        return round(self._latency_total_ms[status] / count, 2) if count else 0.0

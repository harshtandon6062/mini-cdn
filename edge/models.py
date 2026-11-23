"""Pydantic models: the shapes of JSON bodies the edge accepts and returns."""

from enum import Enum

from pydantic import BaseModel, Field


class CacheStatus(str, Enum):
    """Value of the X-Cache header: how the edge answered a request."""

    HIT = "HIT"  # served from cache, origin not contacted
    MISS = "MISS"  # fetched from origin (not cached, or changed)
    REVALIDATED = "REVALIDATED"  # stale copy confirmed by origin with a 304


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_in: int = Field(description="Seconds until the token expires")


class PurgeRequest(BaseModel):
    path: str | None = Field(
        default=None, description="Path to purge, e.g. /api/products. Omit to purge everything."
    )


class PurgeResponse(BaseModel):
    purged: int


class StatsResponse(BaseModel):
    hits: int
    misses: int
    revalidations: int
    total_requests: int
    hit_ratio: float
    avg_latency_ms: dict[str, float]
    rate_limited: int
    access_decisions: dict[str, int]
    cache_entries: int
    cache_capacity: int

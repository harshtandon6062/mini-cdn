"""Admin API: log in, purge the cache, read statistics.

    POST /admin/login  -> JWT (rate limited, to slow down password guessing)
    POST /admin/purge  -> needs "Authorization: Bearer <JWT>"
    GET  /admin/stats  -> public, read-only numbers for the dashboard
"""

from fastapi import APIRouter, Depends, HTTPException

from edge.auth import AuthService
from edge.cache import Cache
from edge.dependencies import (
    enforce_rate_limit,
    get_auth_service,
    get_cache,
    get_stats,
    require_admin,
)
from edge.models import LoginRequest, PurgeRequest, PurgeResponse, StatsResponse, TokenResponse
from edge.stats import Stats

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/login", dependencies=[Depends(enforce_rate_limit)])
def login(body: LoginRequest, auth: AuthService = Depends(get_auth_service)) -> TokenResponse:
    token = auth.login(body.username, body.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return TokenResponse(access_token=token, expires_in=auth.expiry_seconds)


@router.post("/purge", dependencies=[Depends(require_admin)])
def purge(body: PurgeRequest, cache: Cache = Depends(get_cache)) -> PurgeResponse:
    return PurgeResponse(purged=cache.purge(body.path))


@router.get("/stats")
def stats(cache: Cache = Depends(get_cache), stats: Stats = Depends(get_stats)) -> StatsResponse:
    return stats.snapshot(cache_entries=len(cache), cache_capacity=cache.max_entries)

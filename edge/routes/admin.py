"""Admin API: purge the cache, read statistics. (Login lives in routes/auth.py.)

    POST /admin/purge  -> needs "Authorization: Bearer <JWT>" with role "admin"
    GET  /admin/stats  -> public, read-only numbers for the dashboard
"""

from fastapi import APIRouter, Depends

from edge.cache import Cache
from edge.dependencies import get_cache, get_stats, require_admin
from edge.models import PurgeRequest, PurgeResponse, StatsResponse
from edge.stats import Stats

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/purge", dependencies=[Depends(require_admin)])
def purge(body: PurgeRequest, cache: Cache = Depends(get_cache)) -> PurgeResponse:
    return PurgeResponse(purged=cache.purge(body.path))


@router.get("/stats")
def stats(cache: Cache = Depends(get_cache), stats: Stats = Depends(get_stats)) -> StatsResponse:
    return stats.snapshot(cache_entries=len(cache), cache_capacity=cache.max_entries)

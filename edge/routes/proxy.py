"""Catch-all route: every GET that is not /admin or /dashboard goes to the origin via the cache.

This route is thin on purpose: it only turns HTTP into a service call and
the service result back into HTTP (adding X-Cache and Age headers).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from edge.dependencies import enforce_rate_limit, get_proxy_service
from edge.origin_client import OriginUnavailableError
from edge.proxy_service import ProxyService

router = APIRouter()


@router.get("/{path:path}", dependencies=[Depends(enforce_rate_limit)])
async def proxy(
    path: str, request: Request, service: ProxyService = Depends(get_proxy_service)
) -> Response:
    try:
        result = await service.get("/" + path, request.url.query)
    except OriginUnavailableError:
        raise HTTPException(status_code=502, detail="Origin unavailable")
    headers = {**result.headers, "X-Cache": result.cache_status.value, "Age": str(result.age)}
    return Response(content=result.body, status_code=result.status, headers=headers)

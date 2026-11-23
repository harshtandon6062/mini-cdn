"""Catch-all route: every GET that is not /admin, /auth or /dashboard goes to the origin via the cache.

Zero trust order: authenticate + authorize run BEFORE the rate limit and
BEFORE the cache lookup, so cached content is never handed to someone the
policy would block. The route itself stays thin: HTTP in, service call,
HTTP out (adding X-Cache and Age headers).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from edge.dependencies import authorize, enforce_rate_limit, get_proxy_service
from edge.origin_client import OriginUnavailableError
from edge.proxy_service import ProxyService

router = APIRouter()


@router.get("/{path:path}", dependencies=[Depends(authorize), Depends(enforce_rate_limit)])
async def proxy(
    path: str, request: Request, service: ProxyService = Depends(get_proxy_service)
) -> Response:
    try:
        result = await service.get("/" + path, request.url.query)
    except OriginUnavailableError:
        raise HTTPException(status_code=502, detail="Origin unavailable")
    headers = {**result.headers, "X-Cache": result.cache_status.value, "Age": str(result.age)}
    return Response(content=result.body, status_code=result.status, headers=headers)

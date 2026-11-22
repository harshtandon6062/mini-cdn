"""Access logging: one line per request with method, path, status, cache result and time.

Example: GET /api/products -> 200 [HIT] 1.3 ms
"""

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

logger = logging.getLogger("edge.access")


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    cache_status = response.headers.get("X-Cache", "-")
    logger.info(
        "%s %s -> %d [%s] %.1f ms",
        request.method, request.url.path, response.status_code, cache_status, elapsed_ms,
    )
    return response

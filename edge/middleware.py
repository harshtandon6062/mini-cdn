"""Access + audit logging: one line per request.

Each line says what happened (method, path, status, cache result, time) and,
for zero-trust checked requests, who asked and why they were let in or not:

  GET /api/products -> 200 [HIT] 1.3 ms user=alice role=engineer decision=ALLOWED reason="rule /api/ allows role engineer"
  GET /api/products -> 403 [-] 0.4 ms user=bob role=intern decision=DENIED_403 reason="rule /api/ does not allow role intern"
"""

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

logger = logging.getLogger("edge.access")


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Time the request, then write one access/audit log line about it."""
    started = time.perf_counter()
    state = request.state  # shared with the guards in dependencies.py
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000

    identity = getattr(state, "identity", None)
    decision, reason = getattr(state, "decision", ("-", "-"))
    if decision != "-":
        request.app.state.stats.record_decision(decision)

    logger.info(
        '%s %s -> %d [%s] %.1f ms user=%s role=%s decision=%s reason="%s"',
        request.method, request.url.path, response.status_code,
        response.headers.get("X-Cache", "-"), elapsed_ms,
        identity.sub if identity else "anonymous", identity.role if identity else "-",
        decision, reason,
    )
    return response

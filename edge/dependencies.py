"""Dependency injection: how routes get their services.

Routes never create services themselves. They ask FastAPI for them with
Depends(get_xxx). The real objects are built once in main.create_app() and
stored on app.state. Tests can swap any of them with
app.dependency_overrides[get_xxx] = lambda: fake.

This file also holds two reusable "guards": rate limiting and admin auth.
"""

import math

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from edge.auth import AuthService
from edge.cache import Cache
from edge.proxy_service import ProxyService
from edge.rate_limiter import RateLimiter
from edge.stats import Stats


def get_cache(request: Request) -> Cache:
    return request.app.state.cache


def get_stats(request: Request) -> Stats:
    return request.app.state.stats


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def get_proxy_service(request: Request) -> ProxyService:
    return request.app.state.proxy


def enforce_rate_limit(
    request: Request,
    limiter: RateLimiter = Depends(get_rate_limiter),
    stats: Stats = Depends(get_stats),
) -> None:
    """Reject the request with 429 if this client IP has used up its tokens."""
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.check(client_ip)
    if not allowed:
        stats.rate_limited += 1
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(math.ceil(retry_after))},
        )


_bearer = HTTPBearer(auto_error=False)


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth_service),
) -> None:
    """Allow the request only with a valid 'Authorization: Bearer <JWT>' header."""
    if credentials is None or not auth.verify(credentials.credentials):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

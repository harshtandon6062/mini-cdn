"""Dependency injection: how routes get their services, plus the access guards.

Routes never create services themselves. They ask FastAPI for them with
Depends(get_xxx). The real objects are built once in main.create_app() and
stored on app.state. Tests can swap any of them with
app.dependency_overrides[get_xxx] = lambda: fake.

Guards, in the order a proxied request meets them (zero trust):
    authenticate  -> who are you?           (no/invalid JWT -> 401)
    authorize     -> may you reach this?    (policy says no  -> 403)
    rate limit    -> are you going too fast? (bucket empty    -> 429)
Each guard writes its decision on request.state so the audit log can print it.
"""

import math

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from edge.auth import AuthService, Identity
from edge.cache import Cache
from edge.config import Settings
from edge.policy import AccessPolicy
from edge.proxy_service import ProxyService
from edge.rate_limiter import RateLimiter
from edge.stats import Stats


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_cache(request: Request) -> Cache:
    return request.app.state.cache


def get_stats(request: Request) -> Stats:
    return request.app.state.stats


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def get_policy(request: Request) -> AccessPolicy:
    return request.app.state.policy


def get_proxy_service(request: Request) -> ProxyService:
    return request.app.state.proxy


def deny(request: Request, status: int, decision: str, reason: str, headers: dict | None = None):
    """Record a DENIED decision for the audit log and stop the request with `status`."""
    request.state.decision = (decision, reason)
    raise HTTPException(status_code=status, detail=reason, headers=headers)


_bearer = HTTPBearer(auto_error=False)


def authenticate(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> Identity | None:
    """Require a valid Bearer JWT (when zero trust is on) and return who sent it."""
    if not settings.zero_trust_enabled:
        return None
    challenge = {"WWW-Authenticate": "Bearer"}
    if credentials is None:
        deny(request, 401, "DENIED_401", "missing bearer token", challenge)
    identity = auth.verify(credentials.credentials)
    if identity is None:
        deny(request, 401, "DENIED_401", "invalid or expired token", challenge)
    request.state.identity = identity
    return identity


def authorize(
    request: Request,
    identity: Identity | None = Depends(authenticate),
    policy: AccessPolicy = Depends(get_policy),
) -> None:
    """Check the access policy for this user's role and path (default deny)."""
    if identity is None:  # zero trust is off
        return
    decision = policy.check(request.url.path, identity.role)
    if not decision.allowed:
        deny(request, 403, "DENIED_403", decision.reason)
    request.state.decision = ("ALLOWED", decision.reason)


def enforce_rate_limit(
    request: Request,
    limiter: RateLimiter = Depends(get_rate_limiter),
    stats: Stats = Depends(get_stats),
) -> None:
    """Reject with 429 if this user (or, if anonymous, this IP) has used up its tokens."""
    identity: Identity | None = getattr(request.state, "identity", None)
    client_ip = request.client.host if request.client else "unknown"
    key = f"user:{identity.sub}" if identity else f"ip:{client_ip}"
    allowed, retry_after = limiter.check(key)
    if not allowed:
        stats.rate_limited += 1
        deny(request, 429, "RATE_LIMITED", f"rate limit exceeded for {key}",
             {"Retry-After": str(math.ceil(retry_after))})


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth_service),
) -> None:
    """Allow only a valid JWT whose role is "admin" (401 if no/bad token, 403 if wrong role)."""
    identity = auth.verify(credentials.credentials) if credentials else None
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if identity.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

"""Builds the edge app: creates every service once and wires up the routes.

Run with: uvicorn edge.main:create_app --factory --port 8000

create_app() takes optional overrides (settings, a fake origin transport, a
fake clock) so tests can build a fully working edge with no network and no
real waiting.
"""

import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from edge.auth import AuthService
from edge.cache import Cache
from edge.config import Settings
from edge.middleware import log_requests
from edge.origin_client import OriginClient
from edge.proxy_service import ProxyService
from edge.rate_limiter import RateLimiter
from edge.routes import admin, dashboard, proxy
from edge.stats import Stats


def create_app(
    settings: Settings | None = None,
    origin_transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The HTTP client is opened at startup and closed at shutdown.
        origin = OriginClient(settings.origin_url, settings.origin_timeout_seconds, origin_transport)
        app.state.proxy = ProxyService(app.state.cache, origin, app.state.stats, clock)
        yield
        await origin.close()

    app = FastAPI(title="Mini CDN Edge", lifespan=lifespan)
    app.state.cache = Cache(settings.cache_max_entries)
    app.state.stats = Stats()
    app.state.rate_limiter = RateLimiter(
        settings.rate_limit_capacity, settings.rate_limit_refill_per_second, clock
    )
    app.state.auth = AuthService(
        settings.admin_username,
        settings.admin_password_hash,
        settings.jwt_secret,
        settings.jwt_expiry_minutes,
    )

    app.middleware("http")(log_requests)
    # Order matters: specific routes first, the catch-all proxy route last.
    app.include_router(admin.router)
    app.include_router(dashboard.router)
    app.mount("/dashboard/static", StaticFiles(directory=dashboard.STATIC_DIR), name="dashboard-static")
    app.include_router(proxy.router)
    return app

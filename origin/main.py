"""The origin server: the "real" website that the CDN edge sits in front of.

Every route chooses its own Cache-Control policy:
  * HTML pages      -> public, max-age=30   (change rarely)
  * JSON API        -> public, max-age=10   (change more often)
  * /api/time       -> no-store             (different on every request)
  * /internal/...   -> private              (a private app: edge must not cache it)
  * hashed CSS file -> max-age=1 year, immutable (cache busting)

An artificial delay (ORIGIN_DELAY_MS, default 300) makes the origin feel
"far away", so the speed-up from the edge cache is easy to see.
Run with: uvicorn origin.main:app --port 8001
"""

import asyncio
import json
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from origin import content
from origin.http_cache import cacheable_response

PAGE_POLICY = "public, max-age=30"
API_POLICY = "public, max-age=10"
STATIC_POLICY = "public, max-age=31536000, immutable"

app = FastAPI(title="Mini CDN Origin")


@app.middleware("http")
async def simulate_distance(request: Request, call_next):
    """Pretend the origin is on the other side of the world."""
    await asyncio.sleep(int(os.getenv("ORIGIN_DELAY_MS", "300")) / 1000)
    return await call_next(request)


def json_bytes(data: object) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode()


@app.get("/")
def home(request: Request) -> Response:
    return cacheable_response(request, content.home_page(), "text/html", PAGE_POLICY)


@app.get("/about")
def about(request: Request) -> Response:
    return cacheable_response(request, content.about_page(), "text/html", PAGE_POLICY)


@app.get("/products")
def products_html(request: Request) -> Response:
    return cacheable_response(request, content.products_page(), "text/html", PAGE_POLICY)


@app.get("/api/products")
def list_products(request: Request, category: str | None = None) -> Response:
    items = [p.model_dump() for p in content.PRODUCTS if category in (None, p.category)]
    return cacheable_response(request, json_bytes(items), "application/json", API_POLICY)


@app.get("/api/products/{product_id}")
def get_product(request: Request, product_id: int) -> Response:
    product = next((p for p in content.PRODUCTS if p.id == product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return cacheable_response(request, json_bytes(product.model_dump()), "application/json", API_POLICY)


@app.get("/internal/reports")
def internal_reports(request: Request) -> Response:
    """A private internal app: only admins may reach it through the gateway."""
    report = {"quarter": "Q4", "revenue_usd": 1_250_000, "confidential": True}
    return cacheable_response(request, json_bytes(report), "application/json", "private, max-age=60")


@app.get("/api/time")
def server_time() -> JSONResponse:
    """Personalised/live data: must never be cached by anyone."""
    now = datetime.now(timezone.utc).isoformat()
    return JSONResponse({"time": now}, headers={"Cache-Control": "no-store"})


@app.get("/static/styles.{css_hash}.css")
def stylesheet(request: Request, css_hash: str) -> Response:
    if css_hash != content.CSS_HASH:
        raise HTTPException(status_code=404, detail="Unknown stylesheet version")
    return cacheable_response(request, content.CSS_BYTES, "text/css", STATIC_POLICY)

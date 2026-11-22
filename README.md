# Mini CDN

A tiny content delivery network (CDN) edge server written in Python with FastAPI, with tests, a live dashboard and a fake "far away" website behind it.

![tests](https://github.com/harshtandon6062/mini-cdn/actions/workflows/tests.yml/badge.svg)

## 1. The pitch

Mini CDN is two small web apps. The **origin** is a normal website (HTML pages, a JSON API, a CSS file) that is slow on purpose (+300 ms), like a server on the other side of the world. The **edge** is a caching reverse proxy that sits in front of it. Users talk only to the edge. The edge keeps copies of responses in memory and answers repeat requests itself in about 1 ms instead of about 300 ms. It follows the origin's `Cache-Control` rules, checks expired copies cheaply with `ETag` / `304 Not Modified`, rate-limits abusive clients, and lets an admin purge content. That is the same basic job an Akamai edge server does. Akamai runs this on hundreds of thousands of servers placed close to users, so content is served nearby, origins get less traffic, and attacks are stopped at the edge before they reach the origin.

## 2. Architecture

```mermaid
flowchart LR
    U[Browser / curl] -->|HTTP :8000| R

    subgraph EDGE["Edge (edge/)"]
        direction TB
        M[Logging middleware] --> R[Routes<br/>proxy / admin / dashboard]
        R --> RL[RateLimiter<br/>token bucket]
        R --> AU[AuthService<br/>bcrypt + JWT]
        R --> PS[ProxyService<br/>HIT / MISS / REVALIDATED]
        PS --> C[Cache<br/>in-memory LRU]
        PS --> ST[Stats]
        PS --> OC[OriginClient<br/>httpx async]
    end

    OC -->|HTTP :8001<br/>If-None-Match| O["Origin (origin/)<br/>pages, JSON API, CSS<br/>+300 ms delay"]
```

Layers: **routes** (HTTP in/out only) → **service classes** (the logic) → nothing else. There is no database.

### Request flows

**Cache miss** (first request for `/api/products`)
1. Request reaches the edge. The logging middleware starts a timer.
2. The rate limiter takes one token from this IP's bucket (if empty: `429`).
3. `ProxyService` builds the key `GET /api/products?` and looks in the cache. Nothing there.
4. `OriginClient` fetches it from the origin (about 300 ms).
5. The origin says `Cache-Control: public, max-age=10` and `ETag: "1340…"`. Status is 200 and it is cacheable, so the edge stores it.
6. The edge replies with the body plus `X-Cache: MISS`, `Age: 0`.

**Cache hit** (same URL within 10 s)
1. Rate limit check, then cache lookup: entry found and its age (3 s) is below max-age (10 s), so it is fresh.
2. The edge replies straight from memory: `X-Cache: HIT`, `Age: 3`. The origin is never contacted. About 1–3 ms.

**Expired entry revalidated with 304** (same URL after 10 s)
1. Entry found but stale (age ≥ max-age). It has an ETag, so the edge asks the origin: `GET /api/products` with `If-None-Match: "1340…"`.
2. The content did not change, so the origin replies `304 Not Modified` with no body (tiny response).
3. The edge keeps its stored body, resets its clock (`stored_at = now`), and replies `X-Cache: REVALIDATED`, `Age: 0`.
4. If the content *had* changed, the origin would send `200` with the new body, and the edge would store it and reply `MISS`.

**Purge**
1. Admin calls `POST /admin/login` with username + password. The edge checks the password against a bcrypt hash and returns a JWT valid for 15 minutes.
2. Admin calls `POST /admin/purge` with `Authorization: Bearer <JWT>` and `{"path": "/api/products"}` (or `{}` for everything).
3. `require_admin` verifies the JWT signature and expiry (`401` if bad).
4. The cache deletes every entry for that path, including all query-string variants, and returns how many were removed. The next request is a `MISS`.

## 3. Design decisions and why

- **Reverse proxy.** Clients don't need to change anything: they call the edge as if it were the website. The origin stays simple and doesn't know a cache exists. This is exactly how a CDN is deployed: DNS points `www.shop.com` at the CDN, and the CDN points at the origin.
- **Cache key = method + path + query string** (`GET /api/products?category=books`). Different query strings can return different content, so they must be different entries. Including the method keeps the door open for caching `HEAD` later. Headers (cookies, language) are **not** in the key. That is a simplification. Real CDNs let you add them (the `Vary` header).
- **LRU eviction.** Memory is limited, so something must be thrown out. "Least recently used" keeps popular content and drops what nobody asked for lately, which fits web traffic where a few URLs get most requests. `OrderedDict` gives O(1) get, put and evict.
- **Stale entries are kept, not deleted.** An expired entry still has a body and an ETag. Keeping it lets us revalidate with a cheap 304 instead of downloading everything again.
- **ETag revalidation.** "Did it change?" costs a round trip but almost no bandwidth. For big files (images, video) that saves a lot. The origin's ETag is a hash of the content, so if the content is the same, the ETag is the same.
- **Token bucket for rate limiting.** It allows short bursts (a page loading 20 files at once) but limits the long-term rate. It needs only two numbers per client (tokens, last update), with no list of timestamps. It also tells us exactly how long to wait, which becomes `Retry-After`.
- **JWT for admin.** The password is checked once. After that the admin sends a signed token, and the edge verifies it with just the secret key: no session storage. In a real CDN with many edges, any edge could verify the token without asking a central server. Short expiry (15 min) limits the damage if a token leaks. The password is stored only as a bcrypt hash (slow on purpose, salted).
- **Dependency injection (`Depends`).** Routes ask for services (`get_cache`, `get_proxy_service`, …) instead of creating them. `create_app()` builds them once. Tests pass in a fake origin transport and a fake clock, or override any provider. No monkey-patching needed.
- **In-memory cache.** The simplest thing that works, and the fastest (no network hop). The cost: the cache is lost on restart and not shared. See weak spots.
- **App factory (`create_app`)** instead of a global `app`. Each test gets a fresh app with its own cache, so tests can't affect each other.
- **Injected clock.** Cache freshness and rate limiting read time from a `clock` function. Tests use a fake clock and "wait 11 seconds" instantly.
- **Only GET 200 responses are cached.** Errors (404, 500) are not cached so a temporary origin problem doesn't stick. POST etc. change data, so they must never be cached (the edge only proxies GET).
- **`no-store`, `private`, `no-cache`, missing or zero `max-age` → not cached.** A conservative choice: when in doubt, don't cache. (Real CDNs handle `no-cache` by always revalidating. I simplified it to "don't cache".)
- **`/admin/stats` is public, purge is protected.** Stats are read-only numbers that the dashboard polls. Purge changes state, so it needs a JWT. In production, stats would also be behind auth.
- **Login is rate limited too.** This slows down password guessing.
- **Origin down → 502 Bad Gateway.** The standard status for "the server behind me failed".
- **Python 3.11 target.** CI runs on 3.11. Local checks were run on 3.13.

## 4. HTTP concepts used

| Concept | Where | What it does here |
|---|---|---|
| `Cache-Control: max-age=N` | origin sets it, edge reads it | Pages 30 s, API 10 s. The edge serves its copy for N seconds without asking the origin. |
| `Cache-Control: no-store` | `/api/time` | "Never keep a copy." Edge always forwards to origin (`X-Cache: MISS` every time). |
| `ETag` | every origin page/API/CSS | A fingerprint (hash) of the body. Same content → same ETag. |
| `If-None-Match` | edge → origin when an entry is stale | "I have version X. Only send the body if it's different." |
| `304 Not Modified` | origin → edge | "Your copy is still good." No body, so it's tiny. The edge reuses its copy. |
| `429 Too Many Requests` | edge, rate limiter | The client used up its token bucket. |
| `Retry-After` | sent with 429 | Seconds until the client gets a new token (rounded up). |
| `Age` | edge → client | Seconds since the edge got this content from the origin. A browser subtracts it from max-age to know how much freshness is left. |
| `X-Cache` | edge → client | Not standard but common (Akamai has similar debug headers): `HIT`, `MISS` or `REVALIDATED`. |
| `401` + `WWW-Authenticate: Bearer` | purge without a valid JWT | "You need to authenticate." |
| `502 Bad Gateway` | origin unreachable | The proxy's upstream failed. |
| **Cache busting** | `/static/styles.<hash>.css` | The CSS file name contains a hash of its content and is cached for 1 year (`immutable`). When the CSS changes, the hash and URL change, so every cache fetches the new file automatically. No purge needed. An old or unknown hash gives 404. |

## 5. Weak spots and how I'd improve them

| Weak spot | Improvement |
|---|---|
| Cache is in memory: lost on restart, not shared between edge processes. | Shared cache like **Redis**, or a two-tier cache (small in-memory L1 + Redis/disk L2). |
| One edge in one place. | **Many edges** in many regions. **DNS** (geo-aware) or **anycast** routes each user to the nearest healthy edge. A mid-tier "parent" cache between edges and origin cuts origin load further. |
| No HTTPS. | **Terminate TLS at the edge** (certificates, HTTP/2 or HTTP/3), and use TLS from edge to origin too. |
| **Thundering herd**: when a popular entry expires, 1,000 simultaneous requests all go to the origin. | **Request coalescing**: the first request fetches, the others wait for its result (an `asyncio` lock or future per key). Also `stale-while-revalidate`: serve the stale copy while one background request refreshes it. |
| JWT can't be revoked before it expires. | Keep expiry short (done: 15 min). Add a **denylist** of revoked token IDs (`jti`), or use refresh tokens. |
| Rate limiter memory grows with every new IP, and limits are per edge process. | Drop idle buckets (TTL cleanup). Use Redis for shared counters across edges. |
| Client IP is `request.client.host`. Behind a load balancer every user looks the same. | Trust `X-Forwarded-For` only from known proxies. |
| Cache key ignores headers (`Vary`, cookies, `Accept-Encoding`). | Support `Vary` and normalise the key (sort query params, ignore tracking params like `utm_*`). |
| Whole bodies are held in memory, limit is by number of entries, not bytes. | Limit by total bytes. Stream large files instead of buffering them. Don't cache bodies above a size limit. |
| Edge doesn't answer the browser's own `If-None-Match` with 304. | Compare the client's `If-None-Match` with the cached ETag and send 304 directly. |
| Origin down = 502 even if we have a stale copy. | `stale-if-error`: serve the stale copy when the origin fails. |
| No compression. | gzip/brotli at the edge, keyed on `Accept-Encoding`. |
| Stats are per process, and reset on restart. | Export metrics to Prometheus/Grafana. |
| Admin purge is by exact path only. | Purge by prefix, wildcard or **cache tags** (like Akamai's Fast Purge by tag). |

## 6. File-by-file tour (read in this order)

**Origin (the website)**
1. `origin/http_cache.py` – Makes ETags (content hash) and returns `304` when the client's `If-None-Match` matches.
2. `origin/content.py` – The fake shop data, HTML page rendering, and the hashed CSS file name (cache busting).
3. `origin/main.py` – The origin routes, each with its own `Cache-Control` policy, plus the 300 ms delay middleware.

**Edge (the CDN)**

4. `edge/config.py` – All settings from environment variables. Secrets have no defaults, so the app won't start without them.
5. `edge/models.py` – Pydantic request/response models and the `CacheStatus` enum (HIT/MISS/REVALIDATED).
6. `edge/cache.py` – `CacheEntry` (body + stored time + max-age), `parse_max_age`, and the LRU `Cache` class with purge.
7. `edge/origin_client.py` – The only code that calls the origin (httpx async client, sends `If-None-Match`).
8. `edge/proxy_service.py` – **The core.** Decides HIT / MISS / REVALIDATED and what to store. Read this one carefully.
9. `edge/rate_limiter.py` – Token bucket per client IP.
10. `edge/auth.py` – bcrypt password check and JWT creation and verification.
11. `edge/stats.py` – Counters and average latency per cache status, hit ratio.
12. `edge/dependencies.py` – DI providers (`get_cache`, …) plus the two guards: `enforce_rate_limit` (429) and `require_admin` (401).
13. `edge/middleware.py` – Logs one line per request: method, path, status, X-Cache, time.
14. `edge/routes/proxy.py` – The catch-all GET route. Calls `ProxyService`, adds `X-Cache` and `Age` headers.
15. `edge/routes/admin.py` – `/admin/login`, `/admin/purge`, `/admin/stats`.
16. `edge/routes/dashboard.py` – Serves the dashboard page.
17. `edge/main.py` – `create_app()`: builds the services once and registers routes (catch-all last).
18. `edge/static/dashboard.{html,css,js}` – The dashboard: polls stats every 2 s, sends test traffic, login, purge.

**Tests and tooling**

19. `tests/conftest.py` – Fake origin (`httpx.MockTransport`), fake clock, and the `make_edge` factory.
20. `tests/test_caching.py`, `test_admin.py`, `test_rate_limit.py`, `test_origin.py` – Behaviour tests. Names read like sentences.
21. `run.sh`, `docker-compose.yml`, `Dockerfile`, `.env.example`, `scripts/hash_password.py`, `.github/workflows/tests.yml`.

## 7. Likely interview questions

1. **What is a CDN and why use one?** A network of servers close to users that keep copies of content. Faster for users (shorter distance, fewer round trips), less load and bandwidth on the origin, and a shield against traffic spikes and attacks.
2. **Walk me through a request.** Rate limit → build cache key → fresh entry? HIT. Stale with ETag? Ask origin with `If-None-Match`: 304 → REVALIDATED, 200 → MISS and store. Nothing cached? Fetch, store if allowed → MISS. Add `X-Cache` and `Age`.
3. **How does the edge decide what to cache?** Only GET, only status 200, and only if the origin's `Cache-Control` has a positive `max-age` and no `no-store`/`private`/`no-cache`. The origin is in control.
4. **What's the difference between `no-store` and `no-cache`?** `no-store`: never keep a copy. `no-cache`: you may keep it but must revalidate before every use. My edge treats both as "don't cache" (a simplification).
5. **What's an ETag and how does a 304 save work?** A fingerprint of the content. The cache sends it back in `If-None-Match`. If it matches, the origin answers 304 with no body. You still pay the round trip, but not the download.
6. **Why LRU? Alternatives?** Keeps recently popular items. Simple and O(1) with an ordered dict. Alternatives: LFU (frequency), FIFO, TTL-only, or size-aware policies. Real CDNs mix these.
7. **What happens when the cache is full?** `put` adds the entry, then removes the least recently used ones until the size is back under the limit.
8. **What is the thundering herd problem?** A hot entry expires and many requests hit the origin at once. Fix: request coalescing (one fetch per key, others wait) and stale-while-revalidate.
9. **How does the token bucket work?** Each IP has up to N tokens, refilled at R per second. Each request spends one. Empty means 429 with `Retry-After = time until one token`. Allows bursts, limits the average.
10. **Why JWT and not sessions? Downsides?** Stateless: any edge can verify it with the secret, no session store. Downside: you can't revoke it early. Mitigate with short expiry and a denylist. I also pin the algorithm (`HS256`) when decoding so `alg: none` tricks don't work.
11. **How are passwords stored?** Only a bcrypt hash in an environment variable. bcrypt is salted and slow on purpose. I always run the bcrypt check, even for a wrong username, so timing doesn't reveal valid usernames.
12. **How did you test without a real origin?** `create_app` accepts an httpx `MockTransport` (a fake origin function that counts calls) and a fake clock. Tests check headers *and* how many times the origin was called. They run in under a second and need no network.
13. **How would you scale this to many edges worldwide?** Deploy edges in many regions. Use GeoDNS or anycast to send users to the nearest one. Add a shared or parent cache tier. Make purge broadcast to all edges. Use central metrics.
14. **What's cache busting and why hash file names?** Put a content hash in the URL (`styles.c20375a7.css`) and cache it for a year. A new version gets a new URL, so there's never a stale CSS file and never a need to purge it.
15. **Why FastAPI and async?** The edge spends most of its time waiting on the network. Async lets one process handle many requests while it waits. FastAPI gives type-checked request bodies (Pydantic), DI with `Depends`, and auto-generated docs at `/docs`.

Bonus quick answers:
- *Where do TCP/DNS fit?* DNS decides which edge a user reaches. The edge reuses TCP connections to the origin (httpx connection pool), which avoids new TCP/TLS handshakes for every request.
- *How did you use AI tools?* I used Claude Code to scaffold the project. I then read every file, ran the tests, and checked HIT/MISS/REVALIDATED/429/purge by hand with curl.

## 8. How to run

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

./run.sh          # origin on :8001, edge on :8000 (creates .env from .env.example on first run)
```

- Website through the edge: http://127.0.0.1:8000/
- Dashboard: http://127.0.0.1:8000/dashboard (demo login: `admin` / `changeme`)
- API docs: http://127.0.0.1:8000/docs

Docker alternative (I couldn't run Docker in the environment where this was built, so try it once before the interview):

```bash
cp .env.example .env
docker compose up --build
```

Change the admin password:

```bash
python scripts/hash_password.py 'my-new-password'   # paste output into ADMIN_PASSWORD_HASH='...' in .env
```

Run the tests:

```bash
pytest            # 24 tests, under 1 second, no network needed
```

Handy curl commands:

```bash
curl -i localhost:8000/api/products                         # X-Cache: MISS, then HIT
curl -i localhost:8000/api/time                             # always MISS (no-store)
TOKEN=$(curl -s -X POST localhost:8000/admin/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"changeme"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -X POST localhost:8000/admin/purge -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"path":"/api/products"}'
curl localhost:8000/admin/stats
for i in $(seq 30); do curl -s -o /dev/null -w "%{http_code} " localhost:8000/about; done   # 429s appear
```

## 9. Two-minute demo script

1. **(15 s) Setup.** "The origin on 8001 is a shop with 300 ms of fake latency. The edge on 8000 is my CDN." Run `./run.sh`, open `/dashboard`.
2. **(25 s) MISS → HIT.** `curl -i localhost:8000/api/products` twice. Point at `X-Cache: MISS` (~300 ms), then `HIT` (~2 ms), and `Age`. Show the origin log printed one request only.
3. **(20 s) Revalidation.** Wait 10 s (API max-age), curl again → `REVALIDATED`. The origin log shows `304 Not Modified`: "it checked with the ETag and didn't re-download the body."
4. **(15 s) no-store.** `curl -i localhost:8000/api/time` twice → `MISS` both times: "the origin said never cache this."
5. **(20 s) Dashboard.** Click **Send test requests** twice. Show the hit ratio rising and the latency bars (HIT ~0 ms vs MISS ~300 ms).
6. **(15 s) Rate limiting.** Click **Send burst of 40** → some `429` rows with `Retry-After`. "Token bucket: 20 burst, 5 per second."
7. **(20 s) Purge.** Click **Purge path** without logging in → 401. Log in (`admin`/`changeme`), purge `/api/products` → "Purged N entries". Send test requests again → that path is `MISS`.
8. **(10 s) Tests.** Run `pytest` → 24 passed in under a second, with a fake origin and a fake clock.

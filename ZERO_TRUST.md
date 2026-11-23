# Zero-Trust Gateway: the short version

## What zero trust means

- Old model ("castle and moat"): if you're inside the company network (office or VPN), you're trusted.
- Problem: one stolen laptop or VPN password and the attacker is "inside" and can reach everything.
- **Zero trust: never trust the network, verify every request at the edge.**
  - Every request must say **who** it is (identity) and be checked against **what** they may access (policy).
  - Being on the office Wi-Fi gives you nothing.
  - Least privilege: you only reach the apps your role needs. Everything else is denied by default.

## How this maps to Akamai Enterprise Application Access (EAA)

- EAA is an **identity-aware proxy** that sits in front of private company apps (wiki, HR, Jira, internal dashboards).
- Users never connect to the app or the network directly. They connect to Akamai's edge, which:
  1. checks identity (SSO / identity provider, MFA),
  2. checks policy (is this user/group allowed to use this app?),
  3. only then forwards the request to the app (through a connector, so the app is never exposed to the internet).
- This project is that idea in miniature:

| EAA idea | This project |
|---|---|
| Akamai edge in front of apps | `edge/` (FastAPI reverse proxy) |
| Private app behind the edge | `origin/` (e.g. admin-only `/internal/reports`) |
| Identity provider + SSO login | `POST /auth/login` → JWT with `sub` + `role` |
| Per-app access policy | `policy.json` + `edge/policy.py` |
| Abuse protection at the edge | per-user token bucket rate limit |
| Audit / reporting | one audit line per request + `/admin/stats` counters |
| CDN performance | the existing cache, used only **after** access is approved |

## Request flow

```
client --> token check --> policy check --> rate limit --> cache --HIT--> response
              | 401           | 403             | 429        | MISS
              v               v                 v            v
                    audit log line (for every request)     origin
```

## The features: what, why, where

**1. Identity check (401)**
- What: every proxied request needs `Authorization: Bearer <JWT>`. Bad signature, expired, or missing → 401.
- Why: zero trust starts with "who are you?". No anonymous access to any app.
- Where:
  - `edge/auth.py`: `AuthService.login` makes the token, `AuthService.verify` checks it and returns an `Identity`.
  - `edge/dependencies.py`: `authenticate`.
  - `edge/routes/auth.py`: `login` (`POST /auth/login`).
  - Users come from config: `edge/config.py` `Settings.users` and `Settings.all_users`.

**2. Access policy, default deny (403)**
- What: `policy.json` maps paths to roles. `/api/*` → engineer, admin. `/internal/*` → admin. Pages → any logged-in user (`*`). No match or wrong role → 403.
- Why: least privilege. Default deny means a forgotten rule blocks access instead of opening it.
- Important: the policy check runs **before the cache lookup**. The cache is shared, so otherwise an intern could be served an engineer's cached `/api` response.
- Also blocks `..` path tricks (`/api/../internal/...`), so nobody can pass the `/api/*` check and land on `/internal`.
- Where:
  - `edge/policy.py`: `AccessPolicy.check` and `Rule.matches`.
  - `edge/dependencies.py`: `authorize`.
  - `edge/routes/proxy.py`: the guard order on the route.

**3. Per-user rate limit (429)**
- What: the existing token bucket is now keyed by the verified user (`user:alice`). It falls back to the IP when there's no identity (e.g. login).
- Why: a whole office can share one IP (NAT), and an attacker can switch IPs. The verified identity is the fair, stable key. One noisy user can't block others.
- Where: `edge/dependencies.py` `enforce_rate_limit`, and `edge/rate_limiter.py` `RateLimiter.check`.

**4. Audit log**
- What: one line per request with user, role, decision (`ALLOWED` / `DENIED_401` / `DENIED_403` / `RATE_LIMITED`), reason, status, cache result and time. Counters are shown in `/admin/stats` and on the dashboard.
- Why: security teams must answer "who accessed what, when, and why were they allowed or blocked?" It's needed for investigations and compliance.
- Where:
  - `edge/middleware.py`: `log_requests`.
  - Each guard records its decision with `deny()` or `request.state.decision`.
  - `edge/stats.py`: `Stats.record_decision`.

**5. Dashboard**
- Log in as alice, bob or admin, send test traffic, and watch the allowed/denied counters.
- Where: `edge/static/dashboard.*`.

**Switch:** `ZERO_TRUST_ENABLED=false` turns checks 1–3 off and gives you the plain CDN.

## Weak spots and fixes

- **One shared HS256 secret.** Anyone who holds it (every edge) could also *create* tokens.
  - Fix: asymmetric keys (RS256/ES256). The identity provider signs with its private key, and edges verify with the public key (JWKS).
  - Better: a real identity provider via **OIDC** (Okta, Entra ID), with MFA.
- **No token revocation.** A stolen or fired-user token works until `exp` (15 min).
  - Fix: a `jti` claim plus a denylist checked at the edge (Redis). Or very short access tokens plus refresh tokens.
- **No mTLS and no device posture.** We check the user, not the device.
  - Fix: client certificates (mTLS) for managed devices, and posture checks (OS patched, disk encrypted, EDR running) as part of the policy.
- **No HTTPS.** Tokens travel in clear text here.
  - Fix: TLS at the edge, always. Tokens are only safe over HTTPS.
- **In-memory rate limiter.** It's per process, so 10 edges allow 10× the limit.
  - Fix: shared counters in **Redis**, or approximate global limits.
- **Policy reload needs a restart.**
  - Fix: watch the file or fetch policy from a central control plane, versioned and audited.
- **Policy is only path + role.**
  - Fix: add HTTP method, time, location, risk score, and group membership from the identity provider.
- **Browsers don't send Bearer headers on normal page loads.**
  - Fix: after SSO login, set a secure `HttpOnly` `SameSite` session cookie (what real access portals do).
- **Audit log is plain text on stdout.**
  - Fix: JSON lines shipped to a SIEM, tamper-evident, with retention.
- **Users stored in an env var.**
  - Fix: users and groups come from the identity provider, never from the gateway.

## Likely interview questions

1. **What is zero trust, in one sentence?** Never trust the network: verify identity and permission on every request, at the gateway, and deny by default.
2. **Walk me through a request.** Token check (401) → policy check (403) → per-user rate limit (429) → cache HIT, or origin on MISS → audit line written for every outcome.
3. **Why must the policy check happen before the cache?** The cache key doesn't include the user, so a cached response could be served to anyone. Checking first means cached data only goes to people allowed to see it. A test proves bob gets 403 on a URL alice already cached.
4. **401 vs 403?** 401: unknown identity (no/invalid/expired token). 403: known identity, but not allowed.
5. **What's inside the JWT and how is it verified?** `sub` (user), `role`, `iat`, `exp`, signed with HS256. The edge checks the signature with the secret, checks `exp`, and pins the algorithm so `alg: none` tricks fail. No database lookup is needed.
6. **What would you change for production?** RS256 or an OIDC identity provider instead of a shared secret, HTTPS + mTLS, revocation with a `jti` denylist, Redis for rate limits, and central policy with hot reload.
7. **What is default deny and why does it matter?** Anything not explicitly allowed is blocked. Mistakes then fail closed (someone reports a 403) instead of open (a data leak). My demo even caught a bug where the `"/"` rule acted as a catch-all. Now `/api/*` means prefix and `/` means exactly the home page.
8. **How does this relate to Akamai EAA?** EAA is an identity-aware proxy on Akamai's edge in front of private apps. Users authenticate with the IdP, policy decides per app, and the app is never exposed directly. My gateway does the same flow in miniature, plus the CDN cache for performance.

#!/usr/bin/env bash
# Curl demo of the zero-trust gateway. Start the servers first with ./run.sh
# (ZERO_TRUST_ENABLED=true). Uses the demo users from .env.example.
set -uo pipefail
EDGE=${EDGE:-http://127.0.0.1:8000}

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
# show: print status code + the X-Cache header of a request
show() { curl -s -o /dev/null -w "HTTP %{http_code}  X-Cache: %header{x-cache}\n" "$@"; }
login() {
  curl -s -X POST "$EDGE/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}

step "1. Identity: no token -> 401"
show "$EDGE/api/products"

step "1. Identity: garbage token -> 401"
show -H "Authorization: Bearer not-a-real-token" "$EDGE/api/products"

ALICE=$(login alice alice-pass)   # role engineer
BOB=$(login bob bob-pass)         # role intern
ADMIN=$(login admin changeme)     # role admin
echo "logged in alice, bob, admin. alice's token claims:"
echo "$ALICE" | cut -d. -f2 | python3 -c 'import sys,base64,json;p=sys.stdin.read().strip();print(json.loads(base64.urlsafe_b64decode(p+"="*(-len(p)%4))))'

step "2. Policy: alice (engineer) -> /api/products allowed, twice (MISS then HIT)"
show -H "Authorization: Bearer $ALICE" "$EDGE/api/products"
show -H "Authorization: Bearer $ALICE" "$EDGE/api/products"

step "2. Policy: bob (intern) -> /api/products is 403, even though it is cached"
curl -s -w "  HTTP %{http_code}\n" -H "Authorization: Bearer $BOB" "$EDGE/api/products"

step "2. Policy: bob -> /products (any logged-in user) is allowed"
show -H "Authorization: Bearer $BOB" "$EDGE/products"

step "2. Policy: path not in policy.json -> 403 (default deny)"
curl -s -w "  HTTP %{http_code}\n" -H "Authorization: Bearer $ADMIN" "$EDGE/secret-app"

step "2. Policy: /internal/ is admin only (and 'private', so never cached)"
curl -s -w "  HTTP %{http_code}\n" -H "Authorization: Bearer $ALICE" "$EDGE/internal/reports"
show -H "Authorization: Bearer $ADMIN" "$EDGE/internal/reports"
show -H "Authorization: Bearer $ADMIN" "$EDGE/internal/reports"

step "3. Rate limit per user: 25 fast requests as bob -> 429s, but alice is unaffected"
for _ in $(seq 25); do curl -s -o /dev/null -w "%{http_code} " -H "Authorization: Bearer $BOB" "$EDGE/about"; done; echo
show -H "Authorization: Bearer $ALICE" "$EDGE/about"

step "4. Audit: decision counters (every request is also one audit line in the edge log)"
curl -s "$EDGE/admin/stats" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_decisions"])'

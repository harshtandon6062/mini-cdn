#!/usr/bin/env bash
# Start the origin (port 8001) and the edge (port 8000). Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (demo admin password: changeme)"
fi

# The edge reads .env itself, and shell variables win over it, e.g.:
#   ZERO_TRUST_ENABLED=false ./run.sh     (plain CDN mode, no tokens needed)
# The origin only needs ORIGIN_DELAY_MS: take it from the shell, else from .env.
export ORIGIN_DELAY_MS="${ORIGIN_DELAY_MS:-$(grep -E '^ORIGIN_DELAY_MS=' .env | cut -d= -f2)}"

uvicorn origin.main:app --port 8001 &
ORIGIN_PID=$!
trap 'kill $ORIGIN_PID 2>/dev/null' EXIT

echo "Origin: http://127.0.0.1:8001   Edge: http://127.0.0.1:8000   Dashboard: http://127.0.0.1:8000/dashboard"
uvicorn edge.main:create_app --factory --port 8000 --no-access-log

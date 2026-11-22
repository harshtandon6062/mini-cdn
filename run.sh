#!/usr/bin/env bash
# Start the origin (port 8001) and the edge (port 8000). Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (demo admin password: changeme)"
fi

# Export everything in .env so both servers can read it.
set -a
source .env
set +a

uvicorn origin.main:app --port 8001 &
ORIGIN_PID=$!
trap 'kill $ORIGIN_PID 2>/dev/null' EXIT

echo "Origin: http://127.0.0.1:8001   Edge: http://127.0.0.1:8000   Dashboard: http://127.0.0.1:8000/dashboard"
uvicorn edge.main:create_app --factory --port 8000 --no-access-log

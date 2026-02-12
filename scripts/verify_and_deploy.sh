#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "[verify_and_deploy] Repository: $REPO_ROOT"
echo "[verify_and_deploy] Running test suite..."

if [[ -x "./venv/bin/python" ]]; then
  ./venv/bin/python -m pytest -q tests/
else
  python3 -m pytest -q tests/
fi

echo "[verify_and_deploy] Restarting Docker services..."
docker-compose restart

echo "[verify_and_deploy] Service status:"
docker-compose ps

echo "[verify_and_deploy] Recent bot logs (last 120 lines):"
docker-compose logs --tail=120 bot

echo "[verify_and_deploy] Completed successfully."

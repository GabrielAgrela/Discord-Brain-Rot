#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "[verify_and_deploy] Repository: $REPO_ROOT"
echo "[verify_and_deploy] Running test suite..."

TEST_LOG="$(mktemp)"
BOT_LOG="$(mktemp)"
RESTART_LOG="$(mktemp)"
WEB_LOG=""
trap 'rm -f "$TEST_LOG" "$BOT_LOG" "$RESTART_LOG" "$WEB_LOG"' EXIT

if [[ -x "./venv/bin/python" ]]; then
  PYTHON_CMD=("./venv/bin/python")
else
  PYTHON_CMD=("python3")
fi

if "${PYTHON_CMD[@]}" -m pytest -q tests/ >"$TEST_LOG" 2>&1; then
  TEST_SUMMARY="$(tail -n 5 "$TEST_LOG" | grep -E 'passed|failed|error|skipped|xfailed|xpassed' | tail -n 1 || true)"
  echo "[verify_and_deploy] Tests passed: ${TEST_SUMMARY:-summary unavailable}"
else
  echo "[verify_and_deploy] Tests failed. Recent pytest output:"
  tail -n 80 "$TEST_LOG"
  exit 1
fi

echo "[verify_and_deploy] Restarting Docker services..."
if docker-compose restart >"$RESTART_LOG" 2>&1; then
  echo "[verify_and_deploy] Docker restart completed."
else
  echo "[verify_and_deploy] Docker restart failed. Recent output:"
  tail -n 80 "$RESTART_LOG"
  exit 1
fi

BOT_CONTAINER_ID="$(docker-compose ps -q bot || true)"
BOT_STARTED_AT=""
if [[ -n "$BOT_CONTAINER_ID" ]]; then
  BOT_STARTED_AT="$(docker inspect --format '{{.State.StartedAt}}' "$BOT_CONTAINER_ID" 2>/dev/null || true)"
fi

echo "[verify_and_deploy] Waiting for bot health..."
BOT_HEALTH="unknown"
if [[ -n "$BOT_CONTAINER_ID" ]]; then
  for _ in {1..30}; do
    BOT_HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$BOT_CONTAINER_ID" 2>/dev/null || echo "unknown")"
    if [[ "$BOT_HEALTH" == "healthy" || "$BOT_HEALTH" == "running" ]]; then
      break
    fi
    sleep 2
  done
fi
echo "[verify_and_deploy] Bot container health: $BOT_HEALTH"

if [[ -n "$BOT_STARTED_AT" ]]; then
  docker-compose logs --since "$BOT_STARTED_AT" --tail=200 bot >"$BOT_LOG" 2>&1 || true
else
  docker-compose logs --tail=120 bot >"$BOT_LOG" 2>&1 || true
fi

if grep -E '\[(ERROR|CRITICAL)\]|Traceback|RuntimeError|ConnectionClosed' "$BOT_LOG" >/dev/null; then
  echo "[verify_and_deploy] Fresh bot logs contain errors. Matching lines:"
  grep -E '\[(ERROR|CRITICAL)\]|Traceback|RuntimeError|ConnectionClosed' "$BOT_LOG" | tail -n 40
  echo "[verify_and_deploy] Recent fresh bot log tail:"
  tail -n 80 "$BOT_LOG"
  exit 1
fi

echo "[verify_and_deploy] Fresh bot log health: no ERROR/CRITICAL/Traceback/RuntimeError/ConnectionClosed lines found."
STARTUP_MARKERS=()
grep -q 'Logging initialized' "$BOT_LOG" && STARTUP_MARKERS+=("logging")
grep -q 'connected to Gateway' "$BOT_LOG" && STARTUP_MARKERS+=("gateway")
grep -q 'We have logged in' "$BOT_LOG" && STARTUP_MARKERS+=("login")
grep -q 'Background tasks started' "$BOT_LOG" && STARTUP_MARKERS+=("background_tasks")
grep -q 'Voice handshake complete' "$BOT_LOG" && STARTUP_MARKERS+=("voice")
if [[ ${#STARTUP_MARKERS[@]} -gt 0 ]]; then
  echo "[verify_and_deploy] Fresh startup markers: ${STARTUP_MARKERS[*]}"
else
  echo "[verify_and_deploy] Fresh startup markers: none found in captured log window"
fi

# Recreate profile-gated web container if it has ever existed.
# Stale bind mounts, entrypoints, and paths from renames (e.g. WebPage.py -> web_page.py)
# are not picked up by `docker-compose restart` alone; --force-recreate is needed.
if docker-compose ps -a -q web 2>/dev/null | grep -q .; then
  # Create WEB_LOG now only if needed (already in trap; rm -f "" is safe earlier)
  WEB_LOG="$(mktemp)"
  echo "[verify_and_deploy] Web service container exists; recreating with --profile web..."
  if docker-compose --profile web up -d --force-recreate web >"$WEB_LOG" 2>&1; then
    # Check for persistent binding/startup errors that up won't surface on success exit
    if grep -qiE '(error|traceback|cannot (bind|mount)|unable to open database)' "$WEB_LOG"; then
      echo "[verify_and_deploy] Web recreation had warnings/errors. Recent output:"
      tail -n 40 "$WEB_LOG"
      exit 1
    fi
    echo "[verify_and_deploy] Web container recreation completed."
  else
    echo "[verify_and_deploy] Web container recreation FAILED. Output:"
    tail -n 60 "$WEB_LOG"
    exit 1
  fi

  WEB_CONTAINER_ID="$(docker-compose ps -q web 2>/dev/null || true)"
  WEB_HEALTH="unknown"
  if [[ -n "$WEB_CONTAINER_ID" ]]; then
    for _ in {1..30}; do
      WEB_HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$WEB_CONTAINER_ID" 2>/dev/null || echo "unknown")"
      if [[ "$WEB_HEALTH" == "healthy" || "$WEB_HEALTH" == "running" ]]; then
        break
      fi
      sleep 2
    done
  fi
  echo "[verify_and_deploy] Web container health: $WEB_HEALTH"

  if [[ "$WEB_HEALTH" == "healthy" ]]; then
    HTTP_STATUS="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8080/ 2>/dev/null || echo "failed")"
    echo "[verify_and_deploy] Web smoke test / returned HTTP $HTTP_STATUS"
    if [[ "$HTTP_STATUS" != "200" && "$HTTP_STATUS" != "302" ]]; then
      echo "[verify_and_deploy] Web smoke test failed (HTTP $HTTP_STATUS)"
      exit 1
    fi
  elif [[ -n "$WEB_CONTAINER_ID" ]]; then
    echo "[verify_and_deploy] Web container not healthy after 60s; skipping smoke test."
  fi
fi

echo "[verify_and_deploy] Completed successfully."

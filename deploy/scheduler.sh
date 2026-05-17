#!/bin/sh
set -e

INTERVAL="${INGEST_INTERVAL_SECONDS:-86400}"
API_URL="http://api:8000/health"

echo "Starting pipeline scheduler (interval: ${INTERVAL}s)"

# Validate GITHUB_TOKEN
if [ -z "$GITHUB_TOKEN" ]; then
    echo "ERROR: GITHUB_TOKEN is not set. Pipeline cannot enrich GitHub repositories."
    echo "Set it in .env and restart."
    exit 1
fi

# Wait for API to be healthy (signals DB is ready and migrations are done)
echo "Waiting for API to be healthy..."
MAX_WAIT=120
WAITED=0
while [ "$WAITED" -lt "$MAX_WAIT" ]; do
    if curl -sf "$API_URL" > /dev/null 2>&1; then
        echo "API is healthy, starting scheduler loop."
        break
    fi
    echo "  API not ready yet, waiting... (${WAITED}s/${MAX_WAIT}s)"
    sleep 5
    WAITED=$((WAITED + 5))
done

if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    echo "WARNING: API did not become healthy within ${MAX_WAIT}s. Starting anyway."
fi

# Graceful shutdown on SIGTERM/SIGINT
trap 'echo "Received shutdown signal, exiting."; exit 0' TERM INT

while true; do
    echo "$(date -Iseconds): Running pipeline..."
    python -m pipelines.run_all || echo "$(date -Iseconds): Pipeline failed, will retry next cycle"
    echo "$(date -Iseconds): Sleeping ${INTERVAL}s..."
    sleep "$INTERVAL"
done

#!/bin/sh
set -e
while true; do
  python -m pipelines.run_pipeline || true
  sleep "${INGEST_INTERVAL_SECONDS:-86400}"
done

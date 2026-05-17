#!/bin/sh
set -e

echo "Running database migrations..."
MAX_RETRIES=5
RETRY=0
until alembic upgrade head; do
    RETRY=$((RETRY + 1))
    if [ "$RETRY" -ge "$MAX_RETRIES" ]; then
        echo "ERROR: Migration failed after $MAX_RETRIES attempts"
        exit 1
    fi
    echo "Migration attempt $RETRY failed, retrying in 3s..."
    sleep 3
done

echo "Starting application..."
exec "$@"

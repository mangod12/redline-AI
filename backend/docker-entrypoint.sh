#!/bin/sh
set -e

echo "=== Redline AI Startup ==="

# Run Alembic migrations if using PostgreSQL
if [ "${USE_SQLITE}" != "true" ]; then
    echo "Running database migrations..."
    python -m alembic upgrade head 2>&1 || {
        echo "WARNING: Alembic migration failed (tables may already exist via create_all)"
    }
fi

echo "Starting application..."
exec "$@"

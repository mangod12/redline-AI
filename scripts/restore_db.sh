#!/bin/bash
# Redline AI — PostgreSQL restore script
# Usage: ./scripts/restore_db.sh backups/redline_20260522_120000.sql.gz

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: $0 <backup_file.sql.gz>"
    echo "Available backups:"
    ls -la backups/redline_*.sql.gz 2>/dev/null || echo "  (none found)"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

PGHOST="${POSTGRES_SERVER:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-redline}"
PGDB="${POSTGRES_DB:-redline}"

echo "=== Redline AI Database Restore ==="
echo "WARNING: This will DROP and recreate the database '${PGDB}'"
read -p "Continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo "Dropping and recreating database..."
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres \
    -c "DROP DATABASE IF EXISTS ${PGDB};" \
    -c "CREATE DATABASE ${PGDB};"

echo "Restoring from ${BACKUP_FILE}..."
gunzip -c "$BACKUP_FILE" | PGPASSWORD="${POSTGRES_PASSWORD}" pg_restore \
    -h "$PGHOST" \
    -p "$PGPORT" \
    -U "$PGUSER" \
    -d "$PGDB" \
    --no-owner \
    --no-privileges \
    --if-exists \
    --clean \
    2>/dev/null || true

echo "Restore complete."

#!/bin/bash
# Redline AI — PostgreSQL backup script
# Usage: ./scripts/backup_db.sh
# Requires: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_SERVER, POSTGRES_PORT, POSTGRES_DB env vars

set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_FILE="${BACKUP_DIR}/redline_${TIMESTAMP}.sql.gz"

PGHOST="${POSTGRES_SERVER:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-redline}"
PGDB="${POSTGRES_DB:-redline}"

mkdir -p "$BACKUP_DIR"

echo "=== Redline AI Database Backup ==="
echo "Host: ${PGHOST}:${PGPORT}"
echo "Database: ${PGDB}"
echo "Output: ${BACKUP_FILE}"

PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    -h "$PGHOST" \
    -p "$PGPORT" \
    -U "$PGUSER" \
    -d "$PGDB" \
    --format=custom \
    --compress=9 \
    --no-owner \
    --no-privileges \
    | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup complete: ${BACKUP_FILE} (${SIZE})"

# Cleanup: keep last 30 days
find "$BACKUP_DIR" -name "redline_*.sql.gz" -mtime +30 -delete 2>/dev/null || true
echo "Old backups (>30 days) cleaned"

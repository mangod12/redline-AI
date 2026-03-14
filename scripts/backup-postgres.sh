#!/usr/bin/env bash
#
# Postgres backup script for Redline-AI
#
# Dumps the database running inside the docker-compose "postgres" service,
# compresses the output with gzip, and retains only the last 7 backups.
#
# Usage:
#   ./scripts/backup-postgres.sh
#
# Cron example (daily at 02:00):
#   0 2 * * * /absolute/path/to/Redline-AI/scripts/backup-postgres.sh
#
set -euo pipefail

# ── Resolve project root (parent of this script's directory) ─────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Load credentials from .env.docker.local ──────────────────────────
ENV_FILE="${PROJECT_ROOT}/.env.docker.local"
if [[ ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: ${ENV_FILE} not found. Cannot read database credentials." >&2
    exit 1
fi

# Source only the variables we need (handles KEY=VALUE, ignores comments/blanks)
while IFS='=' read -r key value; do
    # Skip blank lines and comments
    [[ -z "${key}" || "${key}" =~ ^# ]] && continue
    # Trim surrounding whitespace / quotes
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    export "${key}=${value}"
done < "${ENV_FILE}"

# Fall back to the same defaults used in docker-compose.yml
POSTGRES_USER="${POSTGRES_USER:-redline}"
POSTGRES_DB="${POSTGRES_DB:-redline}"

# ── Backup destination ───────────────────────────────────────────────
BACKUP_DIR="${PROJECT_ROOT}/backups"
mkdir -p "${BACKUP_DIR}"

TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/redline_backup_${TIMESTAMP}.sql.gz"

# ── Dump database via docker compose ─────────────────────────────────
echo "[$(date '+%F %T')] Starting Postgres backup..."

docker compose \
    --project-directory "${PROJECT_ROOT}" \
    --env-file "${ENV_FILE}" \
    exec -T postgres \
    pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner --no-acl \
    | gzip > "${BACKUP_FILE}"

if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
    echo "ERROR: pg_dump failed." >&2
    rm -f "${BACKUP_FILE}"
    exit 1
fi

FILESIZE="$(du -h "${BACKUP_FILE}" | cut -f1)"
echo "[$(date '+%F %T')] Backup saved: ${BACKUP_FILE} (${FILESIZE})"

# ── Rotate: keep only the 7 most recent backups ─────────────────────
KEEP=7
BACKUPS_SORTED=( $(ls -1t "${BACKUP_DIR}"/redline_backup_*.sql.gz 2>/dev/null) )
if (( ${#BACKUPS_SORTED[@]} > KEEP )); then
    for OLD in "${BACKUPS_SORTED[@]:${KEEP}}"; do
        echo "[$(date '+%F %T')] Removing old backup: ${OLD}"
        rm -f "${OLD}"
    done
fi

echo "[$(date '+%F %T')] Backup complete. ${#BACKUPS_SORTED[@]} backup(s) on disk (max ${KEEP})."

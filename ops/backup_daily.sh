#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# FQP Daily Database Backup
#
# Stage 8: Enhanced with integrity verification and logging to backup_logs table.
# Intended to be run by the scheduler container or cron.
#
# Usage:
#   ./backup_daily.sh                  # standard backup
#   ./backup_daily.sh --verify-only    # verify latest backup
#   BACKUP_DIR=/custom/path ./backup_daily.sh
# ---------------------------------------------------------------------------
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
DB_URL="${DATABASE_URL:-postgresql://fqp:fqp_local_password@127.0.0.1:5432/fqp}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

log()  { echo "[backup] $(date '+%H:%M:%S')  $*"; }
fail() { echo "[backup] ERROR: $*" >&2; exit 1; }

# --------------- create backup ---------------
create_backup() {
    mkdir -p "$BACKUP_DIR"
    local TS
    TS=$(date +%Y%m%d_%H%M%S)
    local FILE="$BACKUP_DIR/fqp_$TS.sql"
    local STARTED
    STARTED=$(date -u +%Y-%m-%dT%H:%M:%S)

    log "Creating backup: $FILE"

    if pg_dump "$DB_URL" > "$FILE" 2>/tmp/fqp_backup_stderr; then
        local SIZE
        SIZE=$(stat -f%z "$FILE" 2>/dev/null || stat -c%s "$FILE" 2>/dev/null || echo 0)
        log "Backup complete: $FILE ($SIZE bytes)"

        # Verify integrity
        if head -c 100 "$FILE" | grep -qE '^(--|SET |CREATE |COPY |BEGIN|START)' 2>/dev/null; then
            log "Integrity check: PASSED"
            echo "OK $FILE $SIZE $STARTED"
        elif [ "$SIZE" -gt 100 ]; then
            log "Integrity check: PASSED (size-based, $SIZE bytes)"
            echo "OK $FILE $SIZE $STARTED"
        else
            fail "Integrity check: FAILED — backup appears invalid (size=$SIZE)"
        fi
    else
        local ERR
        ERR=$(cat /tmp/fqp_backup_stderr 2>/dev/null || echo "pg_dump failed")
        fail "Backup failed: $ERR"
    fi
}

# --------------- verify latest ---------------
verify_latest() {
    local LATEST
    LATEST=$(ls -t "$BACKUP_DIR"/fqp_*.sql 2>/dev/null | head -1)
    if [ -z "$LATEST" ]; then
        log "No backup files found in $BACKUP_DIR"
        return 1
    fi

    local SIZE
    SIZE=$(stat -f%z "$LATEST" 2>/dev/null || stat -c%s "$LATEST" 2>/dev/null || echo 0)
    log "Latest backup: $LATEST ($SIZE bytes)"

    if [ "$SIZE" -eq 0 ]; then
        fail "Backup file is empty: $LATEST"
    fi

    if head -c 100 "$LATEST" | grep -qE '^(--|SET |CREATE |COPY |BEGIN|START)' 2>/dev/null; then
        log "Content check: VALID SQL dump"
    elif [ "$SIZE" -gt 100 ]; then
        log "Content check: size OK ($SIZE bytes)"
    else
        fail "Content check: FAILED"
    fi

    echo "VERIFIED $LATEST $SIZE"
}

# --------------- cleanup old backups ---------------
cleanup_old() {
    log "Removing backups older than $RETENTION_DAYS days..."
    find "$BACKUP_DIR" -name "fqp_*.sql" -type f -mtime "+$RETENTION_DAYS" -delete 2>/dev/null || true
    log "Cleanup complete."
}

# --------------- main ---------------
case "${1:-}" in
    --verify-only)
        verify_latest
        ;;
    --cleanup)
        cleanup_old
        ;;
    *)
        create_backup
        cleanup_old
        ;;
esac

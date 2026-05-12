#!/usr/bin/env bash
set -euo pipefail

BUCKET_NAME="${1:-}"
AWS_REGION="${2:-eu-north-1}"
DB_VOLUME_PATH="${DB_VOLUME_PATH:-/var/lib/docker/volumes/septica_data/_data/septica.db}"
BACKUP_DIR="${BACKUP_DIR:-/tmp/septica-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_FILE="septica-${TIMESTAMP}.db"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_FILE}"

if [[ -z "$BUCKET_NAME" ]]; then
  echo "Usage: $0 <s3-bucket-name> [aws-region]"
  exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found. Install AWS CLI first."
  exit 1
fi

if [[ ! -f "$DB_VOLUME_PATH" ]]; then
  echo "Database file not found at: $DB_VOLUME_PATH"
  exit 1
fi

mkdir -p "$BACKUP_DIR"

# Prefer SQLite online backup for consistency when DB is in use.
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB_VOLUME_PATH" ".backup '$BACKUP_PATH'"
else
  echo "sqlite3 not found; falling back to file copy (less safe during active writes)."
  cp "$DB_VOLUME_PATH" "$BACKUP_PATH"
fi

aws s3 cp "$BACKUP_PATH" "s3://${BUCKET_NAME}/${BACKUP_FILE}" --region "$AWS_REGION"

# Keep local backup cache under control.
find "$BACKUP_DIR" -type f -name 'septica-*.db' -mtime "+${RETENTION_DAYS}" -delete

# Remove fresh local backup after successful upload.
rm -f "$BACKUP_PATH"

echo "Backup uploaded: s3://${BUCKET_NAME}/${BACKUP_FILE}"

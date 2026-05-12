#!/usr/bin/env bash
set -euo pipefail

BUCKET_NAME="${1:-}"
AWS_REGION="${2:-eu-north-1}"
DB_VOLUME_PATH="${DB_VOLUME_PATH:-/var/lib/docker/volumes/septica_data/_data/septica.db}"
BACKUP_DIR="${BACKUP_DIR:-/tmp/septica-backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_FILE="septica-${TIMESTAMP}.db"

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
cp "$DB_VOLUME_PATH" "$BACKUP_DIR/$BACKUP_FILE"

aws s3 cp "$BACKUP_DIR/$BACKUP_FILE" "s3://${BUCKET_NAME}/${BACKUP_FILE}" --region "$AWS_REGION"

echo "Backup uploaded: s3://${BUCKET_NAME}/${BACKUP_FILE}"

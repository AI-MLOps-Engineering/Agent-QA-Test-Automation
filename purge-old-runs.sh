    #!/usr/bin/env bash
# purge-old-runs.sh
# Usage: ./purge-old-runs.sh [-d DAYS] [-p PATH] [--dry-run]
# Default DAYS=30, PATH=/data/artifacts/runs

set -euo pipefail

DAYS=30
RUNS_DIR="/data/artifacts/runs"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--days) DAYS="$2"; shift 2 ;;
    -p|--path) RUNS_DIR="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help)
      cat <<EOF
purge-old-runs.sh - remove run directories older than N days

Usage:
  ./purge-old-runs.sh [-d DAYS] [-p PATH] [--dry-run]

Options:
  -d, --days    Number of days (default 30)
  -p, --path    Runs root directory (default /data/artifacts/runs)
  --dry-run     Show what would be deleted without removing
EOF
      exit 0
      ;;
    *)
      echo "Unknown arg: $1"
      exit 2
      ;;
  esac
done

if [[ ! -d "$RUNS_DIR" ]]; then
  echo "Runs directory not found: $RUNS_DIR"
  exit 1
fi

echo "Searching for run directories older than $DAYS days in $RUNS_DIR ..."
if [[ "$DRY_RUN" -eq 1 ]]; then
  find "$RUNS_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +"$DAYS" -print
  echo "Dry-run mode: no deletion performed."
  exit 0
fi

# Safety: list then delete
OLD_DIRS=$(find "$RUNS_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +"$DAYS" -print)
if [[ -z "$OLD_DIRS" ]]; then
  echo "No old runs to delete."
  exit 0
fi

echo "Deleting the following directories:"
echo "$OLD_DIRS"
# delete
while IFS= read -r dir; do
  echo "Removing $dir"
  rm -rf "$dir"
done <<< "$OLD_DIRS"

echo "Purge complete."
exit 0

#!/usr/bin/env bash
# backup-notebook.sh — Back up local and Fly SQLite databases into Dropbox.
#
# Installation:
#   chmod +x scripts/backup-notebook.sh
#   cp scripts/io.developernotebook.backup.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/io.developernotebook.backup.plist
#   launchctl start io.developernotebook.backup   # one-off test
set -euo pipefail

DROPBOX="/Users/anneh/Dropbox (Personal)"
LOCAL_DB="$DROPBOX/Python/projects/developerNotebook/notebook.db"
DEV_BACKUP_DIR="$DROPBOX/_backups/dev"
PROD_BACKUP_DIR="$DROPBOX/_backups/prod"

FLY_APP="${FLY_APP:-developer-memory-garden}"
REMOTE_DB="/data/notebook.db"
RETENTION_DAYS=14

STAMP="$(date +%Y%m%d-%H%M%S)"

log() {
  local dir="$1" msg="$2"
  echo "$(date -Iseconds) $msg" >> "$dir/backup.log"
}

check_integrity() {
  local file="$1" dir="$2" label="$3"
  if sqlite3 "$file" "PRAGMA integrity_check;" | grep -q '^ok$'; then
    log "$dir" "OK $label integrity_check passed: $file"
  else
    log "$dir" "WARN $label integrity_check FAILED: $file"
  fi
}

backup_local() {
  mkdir -p "$DEV_BACKUP_DIR"

  if [[ ! -f "$LOCAL_DB" ]]; then
    log "$DEV_BACKUP_DIR" "SKIP local DB not found: $LOCAL_DB"
    return
  fi

  local dest="$DEV_BACKUP_DIR/notebook-$STAMP.db"
  sqlite3 "$LOCAL_DB" ".backup '$dest'"
  check_integrity "$dest" "$DEV_BACKUP_DIR" "local"

  find "$DEV_BACKUP_DIR" -name 'notebook-*.db' -mtime +"$RETENTION_DAYS" -delete
  log "$DEV_BACKUP_DIR" "OK local backup complete: $dest"
}

backup_fly() {
  mkdir -p "$PROD_BACKUP_DIR"

  if ! command -v fly &>/dev/null; then
    log "$PROD_BACKUP_DIR" "SKIP fly CLI not found"
    return
  fi

  local tmp
  tmp="$(mktemp /tmp/notebook-fly-XXXX.db)"
  trap 'rm -f "$tmp"' RETURN

  if ! fly ssh console -a "$FLY_APP" -C "sqlite3 '$REMOTE_DB' \".backup '/tmp/notebook-backup.db\"'" 2>>"$PROD_BACKUP_DIR/backup.log"; then
    log "$PROD_BACKUP_DIR" "SKIP fly ssh console failed (app unreachable?)"
    return
  fi

  if ! fly ssh sftp get /tmp/notebook-backup.db "$tmp" -a "$FLY_APP" 2>>"$PROD_BACKUP_DIR/backup.log"; then
    log "$PROD_BACKUP_DIR" "SKIP fly sftp get failed"
    return
  fi

  local dest="$PROD_BACKUP_DIR/notebook-$STAMP.db"
  mv "$tmp" "$dest"
  check_integrity "$dest" "$PROD_BACKUP_DIR" "fly"

  find "$PROD_BACKUP_DIR" -name 'notebook-*.db' -mtime +"$RETENTION_DAYS" -delete
  log "$PROD_BACKUP_DIR" "OK fly backup complete: $dest"
}

backup_local
backup_fly

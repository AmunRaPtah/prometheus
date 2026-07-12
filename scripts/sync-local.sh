#!/bin/bash
# Pulls/pushes prometheus's corpus state to/from OneDrive, so `entities build` can run
# locally against the real corpus. llama-swap (the local LLM this uses) only exists on
# this box -- the nightly GitHub Actions harvest has no route to it, so entity
# extraction never runs there; this script is how the real corpus gets here.
#
# Usage: scripts/sync-local.sh pull   # refresh data/ from OneDrive before a local run
#        scripts/sync-local.sh push   # push data/ (with new entity tables) back up
#
# Run sequence: sync-local.sh pull && python -m prometheus entities build && \
#               scripts/sync-local.sh push
#
# KNOWN GAP: this races the nightly GH Actions harvest (06:00 UTC), which does its own
# pull-harvest-push against the same onedrive:prometheus-state/state.tgz with no
# cross-environment locking -- avoid running this near that window. Not fixed here,
# same unsolved risk the harvest workflow already has pulling from a possibly-mid-write
# remote object.
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE="onedrive:prometheus-state/state.tgz"

case "${1:-}" in
  pull)
    TMP="data.new.$$"
    rclone copyto "$REMOTE" "state.tgz.$$" --onedrive-chunk-size 100M
    mkdir -p "$TMP"
    tar -xzf "state.tgz.$$" -C "$TMP"
    rm -f "state.tgz.$$"

    rm -rf data.old
    [ -d data ] && mv data data.old
    mv "$TMP" data
    rm -rf data.old

    echo "[prometheus-sync] $(date -u +%FT%TZ) pulled from OneDrive, warehouse: $(du -sh data/warehouse.duckdb 2>/dev/null | cut -f1)"
    ;;
  push)
    [ -d data ] || { echo "[prometheus-sync] no data/ to push" >&2; exit 1; }
    tar -czf "state.tgz.$$" -C data --exclude='*.wal' .
    rclone copyto "state.tgz.$$" "$REMOTE" --onedrive-chunk-size 100M
    rm -f "state.tgz.$$"
    echo "[prometheus-sync] $(date -u +%FT%TZ) pushed to OneDrive, warehouse: $(du -sh data/warehouse.duckdb 2>/dev/null | cut -f1)"
    ;;
  *)
    echo "usage: $0 {pull|push}" >&2
    exit 1
    ;;
esac

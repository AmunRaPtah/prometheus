#!/usr/bin/env bash
# Install (or refresh) the daily Aqueduct harvest cron job.
# Usage: scripts/install-cron.sh ["MIN HOUR"]   e.g. "17 3" = 03:17 daily (default).

set -eu
PROJECT="/root/projects/prometheus"
SCRIPT="$PROJECT/scripts/harvest.sh"
WHEN="${1:-17 3}"   # "MIN HOUR"
LINE="$WHEN * * * $SCRIPT   # prometheus-harvest"

chmod +x "$SCRIPT"

# Keep every existing line except a prior prometheus-harvest entry, then append ours.
existing="$(crontab -l 2>/dev/null | grep -v 'prometheus-harvest' || true)"
{ [ -n "$existing" ] && printf '%s\n' "$existing"; printf '%s\n' "$LINE"; } | crontab -

echo "Installed cron job:"
crontab -l | grep 'prometheus-harvest' || echo "(failed to install)"

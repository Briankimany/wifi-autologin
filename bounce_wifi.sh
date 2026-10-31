#!/usr/bin/env bash
# Bounce a NetworkManager Wi-Fi connection so the hotspot re-registers this client.
# Usage:  ./bounce_wifi.sh "<connection-name>"
#     or:  WIFI_CONNECTION="<connection-name>" ./bounce_wifi.sh
set -u
CONN="${1:-${WIFI_CONNECTION:-}}"
if [ -z "$CONN" ]; then
    echo "usage: $0 \"<nmcli-connection-name>\" (or set WIFI_CONNECTION)" >&2
    exit 2
fi
LOG=/tmp/nm_bounce.log
{
  echo "=== bounce at $(date) ==="
  nmcli connection down "$CONN"
  sleep 3
  nmcli connection up "$CONN"
  echo "BOUNCE_DONE rc=$?"
} > "$LOG" 2>&1

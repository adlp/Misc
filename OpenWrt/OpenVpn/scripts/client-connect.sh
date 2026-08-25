#!/bin/sh
MAX_CONNECTIONS=1
STATUS_FILE="/tmp/openvpn-status.log"
LOG="/tmp/openvpn-connect.log"

COUNT=$(grep "^CLIENT_LIST,${username}," "$STATUS_FILE" 2>/dev/null | wc -l)

if [ "$COUNT" -ge "$MAX_CONNECTIONS" ]; then
    echo "$(date) REFUSED: $username already has $COUNT connection(s)" >> "$LOG"
    exit 1
fi

echo "$(date) ALLOWED: $username ($COUNT active connection(s))" >> "$LOG"
exit 0

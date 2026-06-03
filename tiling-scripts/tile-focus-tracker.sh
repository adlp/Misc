#!/bin/bash
# tile-focus-tracker.sh — surveille _NET_ACTIVE_WINDOW, stocke les 2 dernières
# Lancé en background par tile-rofi-launch.sh, 1 instance par display.
# Résultat : /tmp/tiling-focus-$DISPLAY  (ligne 1 = courant, ligne 2 = précédent)

HIST_FILE="/tmp/tiling-focus-${DISPLAY//:/}"

prev=""
xprop -root -spy _NET_ACTIVE_WINDOW 2>/dev/null | while IFS= read -r line; do
    raw=$(echo "$line" | grep -oP '0x[0-9a-fA-F]+' | head -1)
    [[ -z $raw || $raw == "0x0" ]] && continue
    cur=$(printf '0x%08x' "$(( raw ))" 2>/dev/null) || continue
    [[ $cur == "$prev" ]] && continue
    printf '%s\n%s\n' "$cur" "${prev}" > "$HIST_FILE"
    prev=$cur
done

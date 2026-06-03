#!/bin/bash
# tile-lock-daemon.sh — Maintient position et taille d'une fenêtre verrouillée.
# Lancé en arrière-plan par lock_window. S'arrête quand la fenêtre est fermée.
# Args: win_id_hex target_x target_y target_w target_h

WIN_HEX=$1
WIN_DEC=$(( WIN_HEX ))
TX=$2 TY=$3 TW=$4 TH=$5

while true; do
    # Quitter si la fenêtre n'existe plus
    wmctrl -l | grep -q "^$WIN_HEX" || exit 0

    eval "$(xdotool getwindowgeometry --shell "$WIN_DEC" 2>/dev/null)"

    if [[ $X -ne $TX || $Y -ne $TY || $WIDTH -ne $TW || $HEIGHT -ne $TH ]]; then
        xdotool windowmove "$WIN_DEC" "$TX" "$TY"
        xdotool windowsize "$WIN_DEC" "$TW" "$TH"
    fi

    sleep 0.3
done

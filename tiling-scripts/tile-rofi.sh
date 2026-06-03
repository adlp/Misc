#!/bin/bash
# tile-rofi.sh — Handler rofi script-mode (niveau 1 : liste de fenêtres)
#
# Ne pas lancer directement. Appelé par rofi via tile-rofi-launch.sh.
#
# ROFI_RETV=0 : liste les fenêtres du bureau courant
# ROFI_RETV=1 : écrit ROFI_INFO (hex win_id) dans le fichier pending puis exit
#               → tile-rofi-launch.sh détecte le fichier et lance rofi niveau 2

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SELF_DIR/tiling-config.sh"

PENDING_FILE="/tmp/tiling-rofi-pending-${DISPLAY//:/}"

# ── Fenêtres ──────────────────────────────────────────────────────────────────

get_current_desktop() {
    wmctrl -d | awk '/\*/ { print $1 }'
}

list_windows() {
    local prev_win="${TILING_PREV_WIN:-}"
    local desktop
    desktop=$(get_current_desktop)

    local focused_dec focused_hex
    focused_dec=$(xdotool getactivewindow 2>/dev/null)
    focused_hex=$(printf '0x%08x' "$focused_dec" 2>/dev/null)

    # Construire l'ensemble des fenêtres verrouillées (PID files actifs)
    # Format : " 0x04000001  0x04000002 " — espaces pour index() exact dans awk
    local locked_set=" "
    if [[ -d $_LOCK_PID_DIR ]]; then
        for _pf in "$_LOCK_PID_DIR"/*.pid; do
            [[ -f $_pf ]] || continue
            kill -0 "$(cat "$_pf")" 2>/dev/null \
                && locked_set+="$(basename "$_pf" .pid) "
        done
    fi

    # wmctrl -lx : id desktop wm_class host title...
    # Ordre : 1. fenêtre active  2. fenêtre précédente  ──  3. autres
    wmctrl -lx | awk -v d="$desktop" -v foc="$focused_hex" -v prev="$prev_win" -v locked="$locked_set" '
        {
            id = $1; desk = $2; wm_cls = $3
            if (desk != d) next
            title = ""
            for (i = 5; i <= NF; i++) title = title (i > 5 ? " " : "") $i
            if (title == "" || title == "Desktop") next

            n = split(wm_cls, parts, ".")
            cls = parts[n]
            lock_icon = (index(locked, " " id " ") > 0) ? "🔒 " : "   "
            label = lock_icon "[" cls "] " title

            if (id == foc)       focused  = id "\t" label
            else if (id == prev) previous = id "\t" label
            else                 cur      = cur id "\t" label "\n"
        }
        END {
            if (focused != "")  printf "%s\n", focused
            if (previous != "") printf "%s\n", previous
            if (cur != "")
                printf "────────────────────\0nonselectable\x1ftrue\n"
            printf "%s", cur
        }
    '
}

# ── Protocole rofi script-mode ────────────────────────────────────────────────

case "${ROFI_RETV:-0}" in

  0)  # Liste des fenêtres du bureau courant
    printf '\0prompt\x1fFenêtres\n'
    list_windows | while IFS=$'\t' read -r id title; do
        printf '%s\0info\x1f%s\n' "$title" "$id"
    done
    ;;

  1)  # Fenêtre sélectionnée : mémoriser et laisser le launcher ouvrir rofi 2
    echo "$ROFI_INFO" > "$PENDING_FILE"
    ;;

esac

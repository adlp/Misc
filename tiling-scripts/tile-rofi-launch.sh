#!/bin/bash
# tile-rofi-launch.sh — Sélecteur de fenêtres + tiling en deux niveaux
#
# Niveau 1 : rofi script-mode liste les fenêtres du bureau courant
# Niveau 2 : rofi -dmenu propose Focus ou une zone de placement
#            (lancé APRÈS fermeture du niveau 1, hors contexte rofi)
#
# Assigner à un raccourci clavier XFCE :
#   Settings Manager > Keyboard > Application Shortcuts
#
# Dépendances : rofi >= 1.7, wmctrl, xrandr

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/tiling-config.sh"

HANDLER="$SCRIPT_DIR/tile-rofi.sh"
PENDING_FILE="/tmp/tiling-rofi-pending-${DISPLAY//:/}"

# Nettoyage si le script est interrompu
trap 'rm -f "$PENDING_FILE"' EXIT INT TERM

if ! command -v rofi &>/dev/null; then
    notify-send "tile-rofi" "rofi non trouvé. Installer : sudo apt install rofi" 2>/dev/null
    exit 1
fi
if ! command -v wmctrl &>/dev/null; then
    notify-send "tile-rofi" "wmctrl non trouvé. Installer : sudo apt install wmctrl" 2>/dev/null
    exit 1
fi

# ── Tracker focus : démarre si absent ────────────────────────────────────────

_TRACKER_PID_FILE="/tmp/tiling-tracker-${DISPLAY//:/}.pid"
_FOCUS_HIST="/tmp/tiling-focus-${DISPLAY//:/}"
if [[ ! -f $_TRACKER_PID_FILE ]] || ! kill -0 "$(cat "$_TRACKER_PID_FILE" 2>/dev/null)" 2>/dev/null; then
    "$SCRIPT_DIR/tile-focus-tracker.sh" &
    echo $! > "$_TRACKER_PID_FILE"
fi

# Fenêtre précédemment active (ligne 2 du fichier historique)
_prev_win=$(sed -n '2p' "$_FOCUS_HIST" 2>/dev/null)

# ── Niveau 1 : sélection de fenêtre ──────────────────────────────────────────

rm -f "$PENDING_FILE"

_win_color=$(read_config ui window-rofi-color "")
_win_theme='listview { columns: 1; }'
[[ -n $_win_color ]] && _win_theme+=" window { background-color: $_win_color; } mainbox { background-color: $_win_color; }"

TILING_PREV_WIN="$_prev_win" rofi \
    -modi "windows:${HANDLER}" \
    -show windows \
    -theme-str "$_win_theme" \
    "$@"

# ── Niveau 2 : action (hors contexte rofi) ────────────────────────────────────

[[ -f $PENDING_FILE ]] || exit 0

win_id=$(cat "$PENDING_FILE")
rm -f "$PENDING_FILE"

win_dec=$(( win_id ))

# Titre pour le prompt (wmctrl -l : id desktop host title...)
win_title=$(wmctrl -l | awk -v id="$win_id" '
    $1 == id { for (i=4; i<=NF; i++) printf (i>4?" ":"") $i; print ""; exit }
')

# État lock
if is_window_locked "$win_dec"; then
    lock_item="🔓  Déverrouiller"
    lock_indicator=" 🔒"
else
    lock_item="🔒  Verrouiller"
    lock_indicator=""
fi

# Classe WM de la fenêtre (instance.Class → partie après dernier point)
win_class=$(wmctrl -lx | awk -v id="$win_id" '
    $1 == id { n=split($3,a,"."); print a[n]; exit }
')

# Résolution du moniteur contenant la fenêtre
_mon_info=$(monitor_for_window "$win_id")
read -r _mon_name _mx _my _mon_w _mon_h <<< "$_mon_info"
res_key="${_mon_w}x${_mon_h}"

# Charger zones en tableaux parallèles (app-specific > résolution > défaut)
zone_names=()
zone_specs=()
while IFS='=' read -r name spec; do
    zone_names+=("$name")
    zone_specs+=("$spec")
done < <(load_zones "$win_class" "$res_key")

# Menu : Focus (0), Lock/Unlock (1), zones (2+)
menu_items=("▶  Focus" "$lock_item")
for name in "${zone_names[@]}"; do
    menu_items+=("⊞  $name")
done

# Couleur optionnelle du second rofi (section [ui], clé zone-rofi-color)
_zone_color=$(read_config ui zone-rofi-color "")
_zone_theme='listview { columns: 1; }'
[[ -n $_zone_color ]] && _zone_theme+=" window { background-color: $_zone_color; } mainbox { background-color: $_zone_color; }"

selected=$(printf '%s\n' "${menu_items[@]}" | \
    rofi -dmenu \
         -p "${win_title:-Fenêtre}${lock_indicator}" \
         -format i \
         -theme-str "$_zone_theme")

[[ -z $selected || ! $selected =~ ^[0-9]+$ ]] && exit 0

case $selected in
    0) focus_raise_window "$win_id" ;;
    1) is_window_locked "$win_dec" && unlock_window "$win_dec" || lock_window "$win_dec"
       focus_raise_window "$win_id" ;;
    *)
        zone_idx=$(( selected - 2 ))
        IFS=',' read -r _zx _zy _zw _zh _zflag <<< "${zone_specs[$zone_idx]}"
        apply_zone "$win_id" "${_zx},${_zy},${_zw},${_zh}"
        [[ $_zflag != "unlock" ]] && lock_window "$win_dec"
        ;;
esac

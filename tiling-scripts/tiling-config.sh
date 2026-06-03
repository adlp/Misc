#!/bin/bash
# tiling-config.sh — Config, moniteurs et application de zones
# Sourcé par tile-rofi.sh et tile-rofi-launch.sh

CONFIG_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/tiling/zones.conf"
_TILING_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_LOCK_PID_DIR="/tmp/tiling-locks-${DISPLAY//:/}"

# ── Config INI ────────────────────────────────────────────────────────────────

# Lit une valeur depuis une section [section] du fichier de config.
# Usage: read_config <section> <clé> <défaut>
read_config() {
    local section=$1 key=$2 default=$3
    if [[ ! -f $CONFIG_FILE ]]; then
        echo "$default"
        return
    fi
    local val
    val=$(awk -v sec="$section" -v k="$key" '
        /^\[/ { in_sec = ($0 == "[" sec "]") }
        in_sec && /^[[:space:]]*[^#\[]/ {
            eq = index($0, "=")
            if (eq > 0) {
                name = substr($0, 1, eq - 1)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
                if (name == k) {
                    val = substr($0, eq + 1)
                    gsub(/^[[:space:]]+/, "", val)
                    gsub(/[[:space:]]+#.*$/, "", val)
                    gsub(/[[:space:]]+$/, "", val)
                    print val
                    exit
                }
            }
        }
    ' "$CONFIG_FILE")
    echo "${val:-$default}"
}

create_default_config() {
    mkdir -p "$(dirname "$CONFIG_FILE")"
    cat > "$CONFIG_FILE" << 'EOF'
# ~/.config/tiling/zones.conf
# Rechargé à chaque lancement — aucun redémarrage nécessaire.

[zones]
# Format :  nom = x,y,largeur,hauteur
# Valeurs : pixels (ex: 960) ou pourcentages (ex: 50%)
# Les % sont relatifs au moniteur sur lequel la fenêtre se trouve.
# Ordre d'affichage dans rofi = ordre dans ce fichier.

haut-gauche  = 0%,0%,50%,50%
haut-droit   = 50%,0%,50%,50%
bas-gauche   = 0%,50%,50%,50%
bas-droit    = 50%,50%,50%,50%
gauche       = 0%,0%,50%,100%
droite       = 50%,0%,50%,100%
haut         = 0%,0%,100%,50%
bas          = 0%,50%,100%,50%
plein-ecran  = 0%,0%,100%,100%
EOF
}

# Émet les entrées "nom=x,y,w,h" d'une section nommée du fichier de config.
_emit_zone_section() {
    local sec=$1
    awk -v sec="$sec" '
        /^\[/ { in_sec = ($0 == "[" sec "]") }
        in_sec && /^[[:space:]]*[^#\[]/ {
            eq = index($0, "=")
            if (eq > 0) {
                name = substr($0, 1, eq - 1)
                spec = substr($0, eq + 1)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", spec)
                gsub(/[[:space:]]*#.*$/, "", spec)
                gsub(/[[:space:]]/, "", spec)
                if (name != "" && spec != "") print name "=" spec
            }
        }
    ' "$CONFIG_FILE"
}

# Retourne 0 si une section [sec] existe dans le fichier de config.
_has_zone_section() {
    grep -qF "[$1]" "$CONFIG_FILE"
}

# Émet des lignes "nom=x,y,w,h" dans l'ordre de priorité :
#   1. [zones:AppClass]  — zones app-spécifiques (si section existe)
#   2. [zones:WxH]       — zones résolution courante (si section existe)
#      OU [zones]        — zones par défaut (fallback si pas de section résolution)
# Args: [app_class] [résolution "WxH"]  (optionnels, retrocompatibilité sans args)
# Crée le fichier avec valeurs par défaut s'il est absent.
load_zones() {
    local app_class=${1:-} res_key=${2:-}
    [[ -f $CONFIG_FILE ]] || create_default_config

    # 1. Zones app-spécifiques en premier
    if [[ -n $app_class ]] && _has_zone_section "zones:$app_class"; then
        _emit_zone_section "zones:$app_class"
    fi

    # 2. Zones résolution si disponibles, sinon défaut
    if [[ -n $res_key ]] && _has_zone_section "zones:$res_key"; then
        _emit_zone_section "zones:$res_key"
    else
        _emit_zone_section "zones"
    fi
}

# ── Moniteurs ─────────────────────────────────────────────────────────────────

# Émet "name mx my mw mh" par moniteur connecté.
get_monitors() {
    xrandr --query | awk '
        / connected/ && match($0, /([0-9]+)x([0-9]+)\+([0-9]+)\+([0-9]+)/, a) {
            printf "%s %d %d %d %d\n", $1, a[3]+0, a[4]+0, a[1]+0, a[2]+0
        }
    '
}

# Retourne "name mx my mw mh" du moniteur contenant le point (cx,cy).
monitor_for_point() {
    local cx=$1 cy=$2 fallback=""
    while read -r name mx my mw mh; do
        [[ -z $fallback ]] && fallback="$name $mx $my $mw $mh"
        if (( cx >= mx && cx < mx+mw && cy >= my && cy < my+mh )); then
            echo "$name $mx $my $mw $mh"
            return
        fi
    done < <(get_monitors)
    echo "$fallback"
}

# Retourne "name mx my mw mh" du moniteur contenant le centre de la fenêtre.
# Arg: window_id_hex
monitor_for_window() {
    local win_id=$1
    local geo
    geo=$(wmctrl -lG | awk -v id="$win_id" '$1==id { print $3,$4,$5,$6 }')
    [[ -z $geo ]] && { get_monitors | head -1; return; }
    local wx wy ww wh
    read -r wx wy ww wh <<< "$geo"
    monitor_for_point $(( wx + ww/2 )) $(( wy + wh/2 ))
}

# ── Lock / Unlock ─────────────────────────────────────────────────────────────
# Implémentation via daemon de surveillance (tile-lock-daemon.sh).
# WM_NORMAL_HINTS / _MOTIF_WM_HINTS ignorés par xfwm4 pour les opérations souris.
# Le daemon poll toutes les 300ms et corrige position/taille si changée.
# S'arrête automatiquement quand la fenêtre est fermée.

is_window_locked() {
    local win_dec=$1
    local win_hex
    win_hex=$(printf '0x%08x' "$win_dec")
    local pid_file="$_LOCK_PID_DIR/$win_hex.pid"
    [[ -f $pid_file ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

lock_window() {
    local win_dec=$1
    local win_hex
    win_hex=$(printf '0x%08x' "$win_dec")

    # Tuer daemon existant si déjà verrouillé
    unlock_window "$win_dec"

    eval "$(xdotool getwindowgeometry --shell "$win_dec" 2>/dev/null)"
    local tx=$X ty=$Y tw=$WIDTH th=$HEIGHT

    mkdir -p "$_LOCK_PID_DIR"
    "$_TILING_SCRIPTS_DIR/tile-lock-daemon.sh" "$win_hex" "$tx" "$ty" "$tw" "$th" &
    echo $! > "$_LOCK_PID_DIR/$win_hex.pid"
}

unlock_window() {
    local win_dec=$1
    local win_hex
    win_hex=$(printf '0x%08x' "$win_dec")
    local pid_file="$_LOCK_PID_DIR/$win_hex.pid"
    if [[ -f $pid_file ]]; then
        kill "$(cat "$pid_file")" 2>/dev/null
        rm -f "$pid_file"
    fi
}

# ── Focus + raise ─────────────────────────────────────────────────────────────

# Active la fenêtre ET la remonte au premier plan.
# wmctrl -i -a envoie _NET_ACTIVE_WINDOW mais ne garantit pas le raise.
focus_raise_window() {
    local win_id=$1
    local win_dec=$(( win_id ))
    wmctrl -i -a "$win_id"
    xdotool windowraise "$win_dec"
}

# ── Application de zone ───────────────────────────────────────────────────────

resolve_px() {
    local val=$1 total=$2
    if [[ $val == *% ]]; then
        echo $(( ${val%\%} * total / 100 ))
    else
        echo "$val"
    fi
}

# Déplace et redimensionne une fenêtre vers une zone, puis lui donne le focus.
# Args: win_id_hex zone_spec(x,y,w,h)
#
# Approche itérative (max 3 passes) :
#   1. Placer le client à la position cible
#   2. Lire la position réelle du cadre extérieur (client + _NET_WM_FRAME_EXTENTS)
#   3. Calculer le delta vs zone cible, ajuster, recommencer
# Converge en 1-2 passes même si _NET_WM_FRAME_EXTENTS était incorrect.
apply_zone() {
    local win_id=$1 spec=$2
    local win_dec=$(( win_id ))

    # Moniteur contenant la fenêtre (géométrie brute xrandr)
    local mon_info
    mon_info=$(monitor_for_window "$win_id")
    local mx my mw mh
    read -r _ mx my mw mh <<< "$mon_info"

    # Work area (_NET_WORKAREA exclut panels/docks) — intersection avec moniteur
    # Corrige le décalage Y quand un panel occupe le haut de l'écran
    local wa_x=0 wa_y=0 wa_w=$mw wa_h=$mh
    local _wa
    _wa=$(xprop -root _NET_WORKAREA 2>/dev/null | grep -oP '\d+' | head -4 | tr '\n' ' ')
    read -r wa_x wa_y wa_w wa_h <<< "$_wa"
    wa_x=${wa_x:-0}; wa_y=${wa_y:-0}; wa_w=${wa_w:-$mw}; wa_h=${wa_h:-$mh}

    # Fallback : _NET_WORKAREA peut valoir 0 même avec un panel en haut (bug xfwm4/XFCE).
    # Sans correction, les apps CSD (Firefox, Signal) atterrissent DANS le panel :
    # leur contenu visible commence à gft px (~12px shadow) au lieu de panel_height.
    # Les apps non-CSD "marchent par accident" car title-bar ≈ hauteur panel.
    # Quand wa_y=0, on lit les struts des docks pour récupérer la vraie réserve du panel.
    if [[ $wa_y -eq 0 ]]; then
        local _strut_top=0
        for _wid in $(xprop -root _NET_CLIENT_LIST 2>/dev/null | grep -oP '0x[0-9a-fA-F]+'); do
            local _s
            _s=$(xprop -id "$_wid" _NET_WM_STRUT_PARTIAL 2>/dev/null | grep -oP '\d+' | head -4 | tr '\n' ' ')
            [[ -z $_s ]] && _s=$(xprop -id "$_wid" _NET_WM_STRUT 2>/dev/null | grep -oP '\d+' | head -4 | tr '\n' ' ')
            [[ -z $_s ]] && continue
            local _sl _sr _st _sb
            read -r _sl _sr _st _sb <<< "$_s"
            (( ${_st:-0} > _strut_top )) && _strut_top=${_st:-0}
        done
        (( _strut_top > 0 )) && wa_y=$_strut_top
    fi

    local emx=$(( mx > wa_x ? mx : wa_x ))
    local emy=$(( my > wa_y ? my : wa_y ))
    local emw=$(( (mx+mw < wa_x+wa_w ? mx+mw : wa_x+wa_w) - emx ))
    local emh=$(( (my+mh < wa_y+wa_h ? my+mh : wa_y+wa_h) - emy ))

    IFS=',' read -r zx zy zw zh <<< "$spec"
    local rx ry rw rh
    rx=$(( emx + $(resolve_px "$zx" "$emw") ))
    ry=$(( emy + $(resolve_px "$zy" "$emh") ))
    rw=$(resolve_px "$zw" "$emw")
    rh=$(resolve_px "$zh" "$emh")

    # Si verrouillée, suspendre le daemon pendant le déplacement
    local _was_locked=false
    is_window_locked "$win_dec" && { _was_locked=true; unlock_window "$win_dec"; }

    wmctrl -i -r "$win_id" -b remove,maximized_vert,maximized_horz 2>/dev/null
    local cx=$rx cy=$ry cw=$rw ch=$rh
    # wmctrl -e envoie _NET_MOVERESIZE_WINDOW — xfwm4 gère correctement pour toutes
    # les apps (Firefox, Signal, gvim, etc.) contrairement à xdotool windowmove
    # qui échoue sur les fenêtres reparentées (coordonnées relatives au frame parent).
    wmctrl -i -r "$win_id" -e "0,$cx,$cy,$cw,$ch"
    sleep 0.15

    local i
    for i in 1 2 3; do
        wmctrl -i -r "$win_id" -e "0,$cx,$cy,$cw,$ch"
        sleep 0.2

        eval "$(xdotool getwindowgeometry --shell "$win_dec" 2>/dev/null)"
        local act_x=$X act_y=$Y act_w=$WIDTH act_h=$HEIGHT

        # _NET_WM_FRAME_EXTENTS : cadre WM extérieur (left right top bottom)
        local fl=0 fr=0 ft=0 fb=0
        local _fe
        _fe=$(xprop -id "$win_dec" _NET_WM_FRAME_EXTENTS 2>/dev/null \
              | grep -oP '\d+' | tr '\n' ' ')
        read -r fl fr ft fb <<< "$_fe"
        fl=${fl:-0}; fr=${fr:-0}; ft=${ft:-0}; fb=${fb:-0}

        # Fallback : xfwm4 peut ajouter un cadre sans déclarer _NET_WM_FRAME_EXTENTS.
        # xwininfo retourne la position du FRAME, xdotool retourne la position du CLIENT
        # (via _NET_WM_CLIENT_WINDOW). La différence = extents réels du cadre WM.
        # Ex: frame y=-2, client y=27 → ft=29 (barre de titre cachée derrière le panel).
        if (( ft == 0 && fl == 0 && fr == 0 && fb == 0 )); then
            local _fw_x _fw_y
            read -r _fw_x _fw_y < <(xwininfo -id "$win_dec" 2>/dev/null | awk '
                /Absolute upper-left X:/ { x = $NF }
                /Absolute upper-left Y:/ { print x, $NF; exit }
            ')
            if [[ -n "$_fw_y" ]]; then
                local _dft=$(( act_y - _fw_y ))
                local _dfl=$(( act_x - _fw_x ))
                (( _dft > 0 && _dft < 200 )) && ft=$_dft
                (( _dfl > 0 && _dfl < 200 )) && fl=$_dfl
            fi
        fi

        # _GTK_FRAME_EXTENTS : marges invisibles GTK à l'intérieur du client
        # (shadow/resize handles des apps CSD comme Firefox, Signal, Thunderbird)
        local gfl=0 gfr=0 gft=0 gfb=0
        local _gfe
        _gfe=$(xprop -id "$win_dec" _GTK_FRAME_EXTENTS 2>/dev/null \
               | grep -oP '\d+' | tr '\n' ' ')
        read -r gfl gfr gft gfb <<< "$_gfe"
        gfl=${gfl:-0}; gfr=${gfr:-0}; gft=${gft:-0}; gfb=${gfb:-0}

        # Frontière visible effective :
        #   WM frame sort HORS du client → soustraire (fl, ft)
        #   GTK margin rentre DANS le client → ajouter (gfl, gft)
        local out_x=$(( act_x - fl + gfl ))
        local out_y=$(( act_y - ft + gft ))
        local out_w=$(( act_w + fl + fr - gfl - gfr ))
        local out_h=$(( act_h + ft + fb - gft - gfb ))

        local dx=$(( rx - out_x ))
        local dy=$(( ry - out_y ))
        local dw=$(( rw - out_w ))
        local dh=$(( rh - out_h ))

        [[ $dx -eq 0 && $dy -eq 0 && $dw -eq 0 && $dh -eq 0 ]] && break

        cx=$(( cx + dx ))
        cy=$(( cy + dy ))
        cw=$(( cw + dw ))
        ch=$(( ch + dh ))
    done

    focus_raise_window "$win_id"

    # Forcer la position finale : xfwm4 peut traiter _NET_MOVERESIZE_WINDOW en différé
    # pour certaines apps (Firefox, Signal, gvim). Second wmctrl après délai garantit
    # que la position convergée est bien appliquée.
    sleep 0.3
    wmctrl -i -r "$win_id" -e "0,$cx,$cy,$cw,$ch"
    # Note : le re-lock post-placement est géré par l'appelant (tile-rofi-launch.sh)
}

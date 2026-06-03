# Tiling XFCE avec wmctrl — Moitiés, Quarts et Rofi

## Prérequis

```bash
sudo apt update && sudo apt install wmctrl xdotool rofi
```

| Outil | Rôle |
|-------|------|
| `wmctrl` | Repositionne + redim fenêtres |
| `xdotool` | Détecte fenêtre active + géométrie |
| `rofi` | Sélecteur visuel fenêtres, déplacement interactif |

---

## Structure des fichiers

```
tiling-scripts/
├── tiling-config.sh          ← lib partagée : config, moniteurs, zones, lock
├── tile-rofi.sh              ← handler rofi script-mode (ne pas lancer directement)
├── tile-rofi-launch.sh       ← point d'entrée (assigner à un raccourci XFCE)
├── tile-lock-daemon.sh       ← daemon surveillance lock (lancé par lock_window)
├── tile-focus-tracker.sh     ← daemon surveillance _NET_ACTIVE_WINDOW (fenêtre précédente)
└── zones.conf.example        ← exemple de config à copier
```

---

## Installation

### 1. Copier les scripts

```bash
cp -r tiling-scripts/ ~/.local/bin/tiling
chmod +x ~/.local/bin/tiling/*.sh
```

6 fichiers installés : `tiling-config.sh`, `tile-rofi.sh`, `tile-rofi-launch.sh`, `tile-lock-daemon.sh`, `tile-focus-tracker.sh`, `zones.conf.example`.

### 2. Config zones (optionnelle)

Absent → `~/.config/tiling/zones.conf` créé auto premier lancement (4 quarts + moitiés + plein écran).

Personnaliser :
```bash
mkdir -p ~/.config/tiling
cp ~/.local/bin/tiling/zones.conf.example ~/.config/tiling/zones.conf
# Éditer à volonté — rechargé à chaque lancement, sans redémarrage
```

---

## Fichier de configuration

```
~/.config/tiling/zones.conf
```

Créé auto si absent. Trois types de sections + une section UI.

### Sections zones (hiérarchie)

| Section | Déclenchement |
|---------|---------------|
| `[zones]` | Fallback — toujours disponible |
| `[zones:1920x1080]` | Résolution du moniteur courant |
| `[zones:Firefox]` | WM class de la fenêtre sélectionnée |

**Ordre d'affichage dans rofi** :
1. `[zones:AppClass]` — affiché en premier si la section existe
2. `[zones:WxH]` — si la section existe pour la résolution courante
3. `[zones]` — fallback si aucune section résolution ne correspond

Format zone : `nom = x,y,w,h[,unlock]`
- `unlock` optionnel — place sans verrouiller. Par défaut toute zone verrouille.

```ini
[zones]
haut-gauche  = 0%,0%,50%,50%
plein-ecran  = 0%,0%,100%,100%,unlock   # pas de lock en plein écran

[zones:1920x1080]
tiers-gauche = 0,0,640,1080
tiers-milieu = 640,0,640,1080
tiers-droit  = 1280,0,640,1080
plein-ecran  = 0%,0%,100%,100%,unlock

[zones:Firefox]           # affiché en tête pour Firefox
browser-large = 0%,0%,70%,100%
```

WM class = partie après le dernier `.` dans `wmctrl -lx` (ex: `Navigator.Firefox` → `Firefox`).

% calculés runtime selon taille réelle moniteur. Multi-écran + changement résolution transparents.

### Section UI

```ini
[ui]
# Couleur de fond rofi (format CSS #rrggbb, vide = thème par défaut)
window-rofi-color = #2a1a2a   # 1er rofi (sélection fenêtre)
zone-rofi-color   = #1a2a4a   # 2e rofi (sélection zone)
```

---

## tiling-config.sh — Fonctions disponibles

Sourcé par `tile-rofi.sh` + `tile-rofi-launch.sh`.
ID fenêtre : **hex** (`0x04000001`, format wmctrl).

| Fonction | Signature | Rôle |
|----------|-----------|------|
| `read_config` | `<section> <clé> <défaut>` | Lit valeur INI |
| `create_default_config` | — | Génère `zones.conf` défaut |
| `load_zones` | `[app_class] [WxH]` | Émet `nom=x,y,w,h` — priorité app > résolution > défaut |
| `get_monitors` | — | Émet `name mx my mw mh` par moniteur connecté |
| `monitor_for_point` | `<cx> <cy>` | Moniteur contenant point (coords globales) |
| `monitor_for_window` | `<win_id_hex>` | Moniteur contenant centre fenêtre |
| `resolve_px` | `<valeur> <total>` | Convertit `50%` ou `960` en pixels |
| `focus_raise_window` | `<win_id_hex>` | `wmctrl -i -a` + `xdotool windowraise` (focus + premier plan) |
| `apply_zone` | `<win_id_hex> <x,y,w,h>` | Dé-maximise + work area + frame-adjust + move/size + focus_raise |
| `is_window_locked` | `<win_dec>` | Vérifie daemon actif (PID file + `kill -0`) |
| `lock_window` | `<win_dec>` | Lance `tile-lock-daemon.sh` background, écrit PID |
| `unlock_window` | `<win_dec>` | Kill daemon, supprime PID file |

---

## tile-rofi.sh — Fonctions internes

Appelé par rofi en script-mode. Non sourcé ailleurs.

| Fonction | Rôle |
|----------|------|
| `get_current_desktop` | Numéro bureau courant (wmctrl -d) |
| `list_windows` | Fenêtres bureau courant triées : active → séparateur → autres |

**Logique `list_windows`** :
1. Fenêtre active (`xdotool getactivewindow`) → première position
2. Fenêtre précédente (`TILING_PREV_WIN` via tracker) → deuxième position
3. Séparateur `nonselectable` rofi (si autres fenêtres existent)
4. Autres fenêtres bureau courant (ordre wmctrl)
5. Bureaux virtuels autres + sticky (desk -1) : exclus

**Format affiché** : `[Classe] titre`
Source : `wmctrl -lx`, champ `wm_class` = `instance.Class` → partie après dernier `.`
Exemples : `Navigator.Firefox` → `[Firefox]` / `xfce4-terminal.Xfce4-terminal` → `[Xfce4-terminal]`

---

## Architecture interne

```
tile-rofi-launch.sh  (point d'entrée, deux phases séquentielles)
  ├── source tiling-config.sh
  ├── démarre tile-focus-tracker.sh si absent
  │
  ├── Phase 1 — rofi script-mode  (bloquant, env TILING_PREV_WIN passé)
  │     tile-rofi.sh ROFI_RETV=0  → liste fenêtres : active → précédente → autres
  │     tile-rofi.sh ROFI_RETV=1  → écrit ROFI_INFO dans /tmp/tiling-rofi-pending-*
  │                                  rofi se ferme
  │
  └── Phase 2 — rofi -dmenu  (hors contexte rofi, après fermeture phase 1)
        lit win_id depuis pending file
        charge zones via load_zones(app_class, résolution)
        ▶  Focus        → focus_raise_window (wmctrl -i -a + xdotool windowraise)
        ⊞  <zone>       → apply_zone → auto-lock sauf flag ,unlock dans spec

tiling-config.sh  (lib partagée — sourcée par tile-rofi.sh et tile-rofi-launch.sh)
  ├── CONFIG_FILE  ~/.config/tiling/zones.conf
  ├── read_config / load_zones(app,res)      config INI, zones hiérarchiques
  ├── get_monitors / monitor_for_window      détection moniteur xrandr + work area
  ├── focus_raise_window                     wmctrl -i -a + xdotool windowraise
  ├── apply_zone <win_id_hex> <spec>         work area + boucle wmctrl-e + focus_raise
  ├── is_window_locked / lock_window         daemon PID file check / lance daemon
  └── unlock_window                          kill daemon + supprime PID file

tile-lock-daemon.sh  (lancé en background par lock_window, 1 instance par fenêtre)
  ├── poll toutes les 300ms via xdotool getwindowgeometry
  ├── corrige position/taille si déviation détectée
  └── exit propre quand wmctrl -l ne voit plus la fenêtre

tile-focus-tracker.sh  (1 instance par display, auto-démarré par tile-rofi-launch.sh)
  ├── surveille _NET_ACTIVE_WINDOW via xprop -root -spy
  ├── stocke les 2 dernières fenêtres actives dans /tmp/tiling-focus-$DISPLAY
  └── permet à tile-rofi.sh de placer la fenêtre précédente en 2e position

```

> Pourquoi deux phases ? Rofi refuse lancement depuis propre process child ("Do not launch rofi from inside rofi"). Pending file permet sortir contexte rofi avant ouvrir second rofi -dmenu.

---

## Multi-écran : comportement

- Scripts détectent moniteur contenant **centre** fenêtre active.
- Positions/dimensions calculées **relativement** ce moniteur.
- Détection xrandr chaque appel → branchement/débranchement transparent.
- Pas config par moniteur : `%` s'adaptent chaque écran.

---

## Utilisation rofi

Lancer `tile-rofi-launch.sh` (raccourci : `Super+W`) :

**Niveau 1 — Sélection de fenêtre**

```
┌──────────────────────────────────────┐
│ Fenêtres                             │
├──────────────────────────────────────┤
│ 🔒 [Firefox] Le site du poulet       │  ← fenêtre active, verrouillée
│ ────────────────────                 │  ← séparateur (non sélectionnable)
│ 🔒 [Xfce4-terminal] bash            │  ← verrouillée
│    [Thunar] /home/claudia            │  ← non verrouillée (3 espaces)
└──────────────────────────────────────┘
          Entrée ↓
```

- Fenêtre active en premier (`xdotool getactivewindow`)
- Format : `🔒 [Classe] titre` ou `   [Classe] titre` (3 espaces si non verrouillée — alignement)
- Cadenas vérifié via PID file actif dans `_LOCK_PID_DIR`
- Séparateur `nonselectable` si autres fenêtres existent
- Autres bureaux virtuels : exclus
- Sticky (desktop -1) : exclus

**Niveau 2 — Action sur fenêtre choisie** (second rofi dmenu)

```
┌──────────────────────────────────────┐
│ Firefox 🔒                           │  ← titre + indicateur lock si verrouillée
├──────────────────────────────────────┤
│ ▶  Focus                             │  ← index 0 : focus uniquement
│ 🔒  Verrouiller                      │  ← index 1 : lock/unlock (état inversé)
│ ⊞  haut-gauche                       │
│ ⊞  haut-droit                        │  ← index 2+ : zones définies dans [zones]
│ ⊞  bas-gauche                        │
│ ⊞  ...                               │
└──────────────────────────────────────┘
```

- **`▶  Focus`** → focus + remonte premier plan (`focus_raise_window`)
- **`🔒  Verrouiller`** → lance daemon surveillance + focus_raise
- **`🔓  Déverrouiller`** → kill daemon + focus_raise
- **`⊞  <zone>`** → déplace + redimensionne + focus + **auto-lock** (sauf zones avec flag `,unlock`)
- **Échap** → annule

Auto-lock : tout placement verrouille la fenêtre, sauf zones déclarées avec `,unlock` (ex: `plein-ecran = 0%,0%,100%,100%,unlock`).
Déverrouillage manuel uniquement via `🔓 Déverrouiller`.
Indicateur `🔒` : vérifie PID file + `kill -0` chaque ouverture menu.

---

## Assigner le raccourci clavier dans XFCE

Un seul raccourci nécessaire : `tile-rofi-launch.sh`.

### Via interface graphique

1. **Settings Manager > Keyboard > Application Shortcuts**
2. Clic **Add**
3. Commande : `~/.local/bin/tiling/tile-rofi-launch.sh`
4. Raccourci suggéré : `Super+W`

### Via xfconf-query

```bash
xfconf-query -c xfce4-keyboard-shortcuts \
  -p "/commands/custom/<Super>w" \
  -n -t string -s "$HOME/.local/bin/tiling/tile-rofi-launch.sh"
```

---

## Lock / Unlock de fenêtre

`WM_NORMAL_HINTS` + `_MOTIF_WM_HINTS` inefficaces : xfwm4 ignore opérations souris.

**Implémentation : daemon de surveillance** (`tile-lock-daemon.sh`).
Poll 300ms, corrige position/taille si changée, exit quand fenêtre fermée.

### Fichier : tile-lock-daemon.sh

```bash
#!/bin/bash
# Args: win_id_hex target_x target_y target_w target_h
WIN_HEX=$1 WIN_DEC=$(( WIN_HEX ))
TX=$2 TY=$3 TW=$4 TH=$5

while true; do
    wmctrl -l | grep -q "^$WIN_HEX" || exit 0   # fenêtre fermée → stop
    eval "$(xdotool getwindowgeometry --shell "$WIN_DEC" 2>/dev/null)"
    if [[ $X -ne $TX || $Y -ne $TY || $WIDTH -ne $TW || $HEIGHT -ne $TH ]]; then
        xdotool windowmove "$WIN_DEC" "$TX" "$TY"
        xdotool windowsize "$WIN_DEC" "$TW" "$TH"
    fi
    sleep 0.3
done
```

### Verrouiller

```bash
# Lire position/taille client courante
eval "$(xdotool getwindowgeometry --shell <win_dec>)"
# Lancer daemon en arrière-plan
tile-lock-daemon.sh <win_hex> $X $Y $WIDTH $HEIGHT &
echo $! > /tmp/tiling-locks-*/0x<win_hex>.pid
```

### Déverrouiller

```bash
kill $(cat /tmp/tiling-locks-*/0x<win_hex>.pid)
rm /tmp/tiling-locks-*/0x<win_hex>.pid
```

### Détecter l'état

```bash
# PID file existe ET process vivant
[[ -f $pid_file ]] && kill -0 "$(cat $pid_file)" 2>/dev/null
```

### Comportement avec apply_zone

Fenêtre verrouillée + déplacement zone :
1. Daemon suspendu (`unlock_window`)
2. `apply_zone` repositionne fenêtre
3. Daemon relancé nouvel emplacement (`lock_window`)

Lock suit fenêtre chaque changement zone.

### Limites

| Limite | Détail |
|--------|--------|
| Réactivité | Correction après 0-300ms → glissement visible bref avant correction |
| Fermeture fenêtre | Daemon exit proprement — pas de zombie |
| Persistance | Lock perdu si daemon tué manuellement ou déconnexion X |
| Multi-lock | Un daemon par fenêtre verrouillée, PID dans `/tmp/tiling-locks-$DISPLAY/` |

---

## Outils de positionnement

### Positionnement itératif

`xdotool windowmove/windowsize` opère zone client (sans décorations).
Quatre sources d'erreur corrigées :

#### Fix 1 — Work area (`_NET_WORKAREA`)

Zones depuis surface utilisable (panels exclus), pas moniteur brut.
`0%,0%` = coin haut-gauche sous panel. Corrige décalage Y systématique.

```bash
# Intersection moniteur ∩ _NET_WORKAREA
emx = max(mx, wa_x)
emy = max(my, wa_y)
emw = min(mx+mw, wa_x+wa_w) - emx
emh = min(my+mh, wa_y+wa_h) - emy
# Les % sont calculés sur (emx, emy, emw, emh) — work area du moniteur
```

Fallback : si `_NET_WORKAREA` vaut 0 (bug xfwm4), lecture des struts `_NET_WM_STRUT_PARTIAL` des fenêtres dock.

#### Fix 2 — `_NET_WM_FRAME_EXTENTS` non déclaré (xfwm4 + apps CSD)

Sur certaines configs, xfwm4 ajoute cadre décoration sans déclarer `_NET_WM_FRAME_EXTENTS`. Différence entre position retournée par `xwininfo` (position **frame**) et `xdotool getwindowgeometry` (position **client** via `_NET_WM_CLIENT_WINDOW`) révèle extents réels.

```
xwininfo -id WIN  →  frame Y = -2   (cadre xfwm4, caché derrière le panel)
xdotool ...       →  client Y = 27  (client Firefox, juste sous le panel)
ft inféré = 27 − (−2) = 29 px
```

Sans ce fix, script place client à `emy=27` avec `ft=0` supposé → frame atterrit à `y=−2`. Résultat : title bar xfwm4 cachée derrière panel, Firefox supprime propres onglets → onglets invisibles.

#### Fix 3 — `_GTK_FRAME_EXTENTS` (shadow CSD : GTK3+)

Apps GTK3+ CSD ajoutent marges invisibles intérieur client (shadow, resize handles). Non comptées dans `_NET_WM_FRAME_EXTENTS`.

```
Frontière visible effective :
  out_x = act_x − fl + gfl     (WM frame sort dehors, GTK margin rentre dedans)
  out_y = act_y − ft + gft
  out_w = act_w + fl + fr − gfl − gfr
  out_h = act_h + ft + fb − gft − gfb
```

#### Fix 4 — Boucle de mesure/correction via wmctrl (max 3 passes)

Corrige extents inconnus (état maximisé → normal, _NET_WM_FRAME_EXTENTS absent).

```
Pour chaque passe (max 3) :
  1. wmctrl -e "0,cx,cy,cw,ch"  →  _NET_MOVERESIZE_WINDOW (xfwm4 place frame à cx+fl,cy+ft)
  2. sleep 0.2s
  3. Lire position client réelle              via xdotool getwindowgeometry
  4. Lire _NET_WM_FRAME_EXTENTS (fl,fr,ft,fb) via xprop
     → Fallback : inférer ft depuis xwininfo (frame) vs xdotool (client)
  5. Lire _GTK_FRAME_EXTENTS (gfl,gfr,gft,gfb) via xprop
  6. Calculer frontière visible effective (cf. Fix 3)
  7. Delta vs zone cible → (dx, dy, dw, dh)
  8. Si delta == 0 → stop
  9. Ajuster : cx+=dx  cy+=dy  cw+=dw  ch+=dh → passe suivante
```

- Pass 1 : mesure extents réels → delta calculé (cx = rx−fl, cy = ry−ft)
- Pass 2 : wmctrl-e au cx/cy corrigé → frame atterrit à (rx,ry)
- Post-boucle : sleep 0.3 + wmctrl-e final → garantit position malgré traitement différé xfwm4

#### Limite connue — apps avec `PResizeInc` (ex: Tillix, terminaux)

`WM_NORMAL_HINTS` + `PResizeInc` contraint taille multiples cellules caractères.
`xdotool windowsize` arrondit multiple valide → taille approx.
Pas fix propre sans casser comportement app.

---

### wmctrl — état et focus

```bash
# Retirer l'état maximisé
wmctrl -i -r <hex_id> -b remove,maximized_vert,maximized_horz

# Donner le focus
wmctrl -i -a <hex_id>
```

| Flag | Signification |
|------|---------------|
| `-i` | ID hex numérique (`0x04000001`) plutôt titre |
| `-r` | Fenêtre cible (opération état) |
| `-a` | Activer (focus + raise) |
| `-b` | Modifier `_NET_WM_STATE` (maximisé, minimisé…) |

> `wmctrl -e "0,X,Y,W,H"` envoie `_NET_MOVERESIZE_WINDOW` — utilisé pour le placement (xfwm4 place le frame à X+fl,Y+ft). xdotool windowmove échouait sur fenêtres reparentées (coordonnées relatives au parent, pas root).

### xdotool — géométrie et focus

```bash
# Lire position/taille client (root-relative)
xdotool getwindowgeometry --shell <win_dec>

# Remonter au premier plan
xdotool windowraise <win_dec>
```

| Argument | Signification |
|----------|---------------|
| `<win_dec>` | ID décimal fenêtre (xdotool n'accepte pas hex) |

Conversion hex → décimal (scripts) :
```bash
win_dec=$(( win_id ))   # bash évalue 0x... nativement
```

> xdotool windowmove/windowsize non utilisés : sur fenêtres reparentées (xfwm4), coordonnées interprétées comme relatives au frame parent → placement incorrect. Remplacés par `wmctrl -e`.

---

## Dépannage

### wmctrl ne déplace pas la fenêtre

Fenêtres maximisées ignorent `-e`. Scripts retirent état maximisé auto avant positionnement :
```bash
wmctrl -i -r "$hex" -b remove,maximized_vert,maximized_horz
```
Fenêtre résiste encore (Electron, Java), essayer titre :
```bash
wmctrl -r "Nom de la fenêtre" -e 0,X,Y,W,H
```

### Décalage dû au panel XFCE

Géré auto via `_NET_WORKAREA`. Si décalage persiste (voir cas CSD ci-dessous), vérifier :
```bash
xprop -root _NET_WORKAREA
```
Valeur attendue avec panel 28px en haut : `0, 28, <largeur>, <hauteur-28>`.
Si `_NET_WORKAREA` retourne `0, 0, ...` malgré panel, fallback struts prend relais auto.

Panels en bas uniquement, ajustement manuel si nécessaire :
```ini
# Panel 28px en bas, écran 1080px — bas-gauche sans débordement :
bas-gauche = 0,540,960,512     # 1080 - 540 - 28 = 512
```

### Apps CSD décalées vers le haut (Firefox, Signal, Thunderbird)

**Symptôme** : onglets/barre de titre cachés derrière panel lors placement zone haute.

**Cause réelle** : xfwm4 ajoute cadre décoration (title bar) à ces apps **sans déclarer `_NET_WM_FRAME_EXTENTS`**. Script croit frame absent (`ft=0`), place client à `y=emy`. Mais xfwm4 place frame à `y=emy-ft` (ex: `y=-2` pour `ft=29, emy=27`), caché derrière panel. Firefox supprime propres onglets quand xfwm4 fournit title bar → onglets invisibles.

**Fix automatique** : quand `_NET_WM_FRAME_EXTENTS` absent, scripts comparent position frame (`xwininfo`) avec position client (`xdotool`) pour déduire `ft` réel. Placement via `wmctrl -e` (pas `xdotool windowmove`) + passe finale forcée post-boucle garantissent position correcte dès le premier appel.

**Diagnostic** — placer Firefox zone haute, puis :
```bash
WIN=$(wmctrl -l | grep -i firefox | head -1 | awk '{print $1}')

# Position frame (xwininfo) vs client (xdotool) — la différence = ft réel
xwininfo -id $WIN | grep "Absolute upper-left"
xdotool getwindowgeometry $WIN

# Vérifier si _NET_WM_FRAME_EXTENTS est déclaré
xprop -id $WIN _NET_WM_FRAME_EXTENTS _GTK_FRAME_EXTENTS
```

Résultat typique XFCE avec panel 27px :
- xwininfo Y = -2 (frame), xdotool Y = 27 (client) → ft inféré = 29
- Après fix : frame à Y=27, client à Y=56, onglets visibles

### rofi : ROFI_INFO non disponible

Nécessite **rofi >= 1.7**. Vérifier :
```bash
rofi -version
```
Ubuntu 22.04+ : `sudo apt install rofi` installe 1.7+.
Ubuntu 20.04 : compiler sources ou PPA.

### Moniteur non détecté

```bash
xrandr --query | grep ' connected'
```
Aucun moniteur "primary" → fallback premier connecté. Tous scripts fonctionnent sans "primary".

---

## Résultat visuel

```
┌─────────┬─────────┐
│ KP_7    │ KP_9    │
│ topleft │topright │
├─────────┼─────────┤
│ KP_1    │ KP_3    │
│ botleft │botright │
└─────────┴─────────┘
         ↕
   Super+W → rofi niveau 1 (fenêtres)
          → Entrée → rofi niveau 2 (focus ou zone)
```

Raccourcis directs (pavé num) + sélecteur rofi deux niveaux, multi-écran natif, zones configurables sans redémarrage, aucun keybinding rofi custom.
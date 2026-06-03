# Changelog — tiling-scripts

## 2026-06-03

### Suppressions

#### Timers de sélection automatique retirés
- `window-rofi-select-delay` et `zone-rofi-select-delay` supprimés — détection d'interaction clavier non fiable sous X11 (keyboard grab rofi + autorepeat des périphériques virtuels)
- Les deux rofi redeviennent entièrement manuels
- Clés retirées de `zones.conf.example`, README et du code

---

## 2026-06-02

### Ajouts

#### Flag `unlock` sur les zones
- Format étendu : `nom = x,y,w,h[,unlock]`
- Par défaut, toute zone verrouille la fenêtre après placement
- `,unlock` désactive le verrouillage pour cette zone (ex: plein-ecran, zones flottantes)
- Suppression du cas spécial `plein-ecran` codé en dur — remplacé par le flag générique

#### Validation auto du second rofi (`zone-rofi-select-delay`)
- Nouvelle clé `[ui]` : `zone-rofi-select-delay` (défaut : 2s, 0 = désactivé)
- Sans interaction après le délai, l'entrée courante est validée (Return simulé)
- Cohérent avec `window-rofi-select-delay` du premier rofi

---

## 2026-06-01

### Ajouts

#### Zones hiérarchiques
- `[zones:AppClass]` — zones spécifiques à une application (WM class), affichées en tête de liste
- `[zones:WxH]` — zones spécifiques à une résolution de moniteur
- `[zones]` reste le fallback quand aucune section résolution ne correspond
- `load_zones` accepte désormais `app_class` et `res_key` en arguments
- Helper internes `_emit_zone_section` et `_has_zone_section` dans `tiling-config.sh`

#### Couleurs rofi configurables (`[ui]` dans zones.conf)
- `window-rofi-color` — couleur de fond du 1er rofi (sélection fenêtre)
- `zone-rofi-color` — couleur de fond du 2e rofi (sélection zone)
- Fix `read_config` : le strip de commentaires utilisait `[[:space:]]*#` (supprimait les valeurs CSS `#rrggbb`) → remplacé par `[[:space:]]+#`

#### Sélection automatique de la fenêtre précédente
- `window-rofi-select-delay` — délai (secondes) avant sélection auto de la 2e entrée du 1er rofi
- Après le délai : lève la fenêtre précédente (`wmctrl -i -a`) + re-focus rofi + `Down`
- Délai configurable dans `[ui]`, défaut 0.5s

#### Tracker focus (`tile-focus-tracker.sh`)
- Nouveau daemon : surveille `_NET_ACTIVE_WINDOW` via `xprop -root -spy`
- Stocke les 2 dernières fenêtres actives dans `/tmp/tiling-focus-$DISPLAY`
- Auto-démarré par `tile-rofi-launch.sh` (1 instance par display)
- `list_windows` dans `tile-rofi.sh` : fenêtre précédente en 2e position via `TILING_PREV_WIN`

### Correctifs

#### Placement fenêtres CSD (Firefox, Signal, gvim)
- `xdotool windowmove` sur fenêtres reparentées : xfwm4 appliquait les extents en double → frame caché derrière le panel
- Fix : remplacement par `wmctrl -i -r -e "0,cx,cy,cw,ch"` (`_NET_MOVERESIZE_WINDOW`) dans la boucle de placement
- Ajout d'un sleep 0.2s par itération + re-application finale (sleep 0.3 + wmctrl-e) pour garantir la position malgré le traitement différé xfwm4

---

## v1.0 (initial)

- Placement fenêtres via rofi deux niveaux (sélection fenêtre → zone)
- Zones configurables en % ou pixels dans `~/.config/tiling/zones.conf`
- Détection multi-écran via xrandr, work area via `_NET_WORKAREA`
- Lock daemon (`tile-lock-daemon.sh`) : maintient position/taille d'une fenêtre
- Correction frame extents : `_NET_WM_FRAME_EXTENTS`, fallback xwininfo, `_GTK_FRAME_EXTENTS`
- Boucle itérative placement (max 3 passes) avec correction convergente

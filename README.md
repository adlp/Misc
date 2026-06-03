# Introduction
  * Le projet courant est en fait une multitude de petit projet distinct, qui faut traiter distinctement
  * Chaques mini projets et dans un repertoire different
  * Lorsque l'on travaille sur un mini-projet, on ne peut pas modifier un autre mini-projet directement
  * Chaques mini-porjet a son README.md
  * Chaques mini-projet a son changelog.txt
  * Chaques mini-projet a son mini resume dans le README.md ici present

# Mini-Projets
## tiling-scripts
  * Redimensionnement et placement fenêtres XFCE via rofi (deux niveaux : sélection fenêtre → zone)
  * Multi-écran, work area, lock daemon, zones configurables en % ou pixels — flag `,unlock` par zone
  * Zones hiérarchiques : `[zones]` fallback, `[zones:WxH]` par résolution, `[zones:AppClass]` par application
  * Placement via `wmctrl -e` (_NET_MOVERESIZE_WINDOW) — corrige fenêtres reparentées xfwm4 (Firefox, Signal, gvim)
  * Tracker focus daemon — fenêtre précédente en 2e position dans le sélecteur
  * Détails : README.md dans le répertoire tiling-scripts/


## Git

### gitoune
python script to push stdin data to a repo

  * push automatically a file from a server to git if it have change (put it in y'r crontab)

  `
    2 4 * * * ssh adlp-nestor cat /etc/calaos/local_config.xml | gitoune -r ssh://git@git.adlp.org:65322/adlp/TopSecret.git -f Calaos/local_config.xml -d
    `

  * to see logs about a file

  `
    ./gitoune -r git@github.com:adlp/Misc.git -f Git/gitoune -l
    `

  * to get a precise release

  `
    ./gitoune -r git@github.com:adlp/Misc.git -f Git/gitoune -G C0mM1tNumB3r
    `

  * HowTo get gitoune (do not forget to chmod +x ) :-D ?

  `
    ./gitoune -r git@github.com:adlp/Misc.git -f Git/gitoune -g >/usr/local/bin/gitoune
    `

### gitar
python script to push a tar file to a repo....

  `
ssh adlp-octopussy sysupgrade -b /tmp/backup-octopussy.tgz

scp adlp-octopussy:/tmp/backup-octopussy.tgz /tmp/backup-octopussy.tgz

./gitar -t /tmp/backup-octopussy.tgz -r ssh://git@git.adlp.org:653222/adlp/TopSecret.git -p OpenWrt/Octopussy -m "cron $(date)"
  `

## OpenWrt
### uciRuleFromName
A shell script to let me activate or desactivate a firewall rule in line...

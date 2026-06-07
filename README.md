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

### git2git_file
Script bash pour transférer un fichier d'un dépôt git à un autre en conservant l'historique des commits.

  `./git2git_file <repo_src> <fichier_src> <repo_dst> <fichier_dst>`

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

## Borg
### borgHelper
Script Python 3 d'aide à la gestion des sauvegardes BorgBackup.

  * Configuration multi-dépôts/serveurs dans un fichier INI
  * CLI et librairie Python
  * Commandes : Bkp, Prune, Report, Index, Search, FileHist, Restore, DiffBkp, Mount/UMount, DuIdx, IdxTop, IdxPurge, DiffTop...
  * Indexation SQLite incrémentale des diffs inter-archives
  * Détails : README.md dans le répertoire Borg/

## Docker
### Compose
Fichiers docker-compose pour services auto-hébergés :
  * letsencrypt
  * nextcloud
  * nginx
  * wordpress

## Halloween
### web2shell
Serveur HTTP Python minimaliste pour exécuter des commandes shell via HTTP.

## Mail
### mailqOnOneLine
Script Perl affichant la mailq Postfix en une ligne par message (from, to, sujet, date).

## Toip
### astFullLogs2DP
Script Perl d'analyse des logs Asterisk — filtrage par channel-id, extension ou channel, avec support gzip et couleurs ANSI.

## Tools
### checkssl
Script bash pour vérifier l'état d'un certificat SSL.

### cronMutt
Script Python pour gérer la sortie d'une commande cron — envoi conditionnel par mail (mutt), push Nextcloud, etc.

### sleepUntil
Script bash similaire à `at` mais bloquant : suspend le processus jusqu'à une heure précise, utilisable dans un script.

### whosshkey
Script bash similaire à `last` mais pour les clefs SSH.

## Zapiz
### zapiz.py
Framework Python (FastAPI) pour exposer des fonctions Python en API REST avec authentification OIDC ou CSV, documentation Swagger auto-générée.

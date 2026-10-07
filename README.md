# Introduction
  * Le projet courant est en fait une multitude de petits projets distincts, à traiter indépendamment
  * Chaque mini-projet est dans un répertoire différent
  * Lorsque l'on travaille sur un mini-projet, on ne peut pas modifier un autre mini-projet directement
  * Chaque mini-projet a son README.md
  * Chaque mini-projet a son changelog.txt
  * Chaque mini-projet a son mini-résumé dans le README.md ici présent

# CheatSheets
Fiches de référence rapide.
  * [CheatSheets/git.md](CheatSheets/git.md) — commandes git, flux (remotes, push/fetch/pull, upstream)
  * [CheatSheets/tmux.md](CheatSheets/tmux.md) — sélection souris vers clipboard X11

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
Script shell pour activer ou désactiver une règle de pare-feu en ligne de commande.

## Borg
### borgHelper
Script Python 3 d'aide à la gestion des sauvegardes BorgBackup.

  * Configuration multi-dépôts/serveurs dans un fichier INI
  * CLI et librairie Python
  * Commandes : Bkp, Prune, Report, Index, Search, FileHist, Restore, DiffBkp, Mount/UMount, DuIdx, IdxTop, IdxPurge, DiffTop...
  * Indexation SQLite incrémentale des diffs inter-archives
  * Détails : README.md dans le répertoire Borg/

## Ssh
### sshvault
CLI Python (sans root, `uv tool install ./Ssh`) : clés SSH dans Vaultwarden via le CLI `bw` ; `login`, `unlock`, `lock`, `status`, `sync`, `list` et `search` des éléments « SSH key » par hôte, nom ou empreinte ; `load` dans un `ssh-agent` dédié (durée de vie, `--confirm`, `--restrict`), `agent status|purge|lock|unlock|stop`, `config` (durée par défaut) ; `hosts add|remove|set|list` (hôtes d'une clé, écrits dans le coffre) et `ssh-config` (`~/.ssh/sshvault/config` généré, un bloc `Match originalhost` par clé avec l'agent dédié et sa seule clé ; `install` : ligne `Include` en tête de `~/.ssh/config`) ; chargement automatique à la connexion (`Match … exec "sshvault ensure"`, cible et chaque saut ProxyJump/ProxyCommand, une invite au plus, `config set auto-load false` pour s'en passer). Détails : README.md dans le répertoire Ssh/

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

## SignalSpam
### signal_spam_report
Script Python pour signaler en masse des mails `.eml` à signal-spam.fr (API non-officielle). Renomme en `.eml.done` chaque mail signalé avec succès.

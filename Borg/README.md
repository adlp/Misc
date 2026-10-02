# borgHelper

Script Python 3 d'aide à la gestion des sauvegardes [BorgBackup](https://www.borgbackup.org/).  
Centralise la configuration de plusieurs dépôts/serveurs dans un fichier INI et expose des commandes haut niveau.  
Utilisable comme CLI ou comme **librairie Python** — voir [LIBRARY.md](LIBRARY.md).

> Fonctionnement interne et schémas de base de données → [TECHNICAL.md](TECHNICAL.md)

---

## Prérequis

- Python 3.8+
- `borg` dans le PATH
- `prettytable` (`pip install prettytable`) — requis pour `Report` et les commandes d'index

---

## Installation

```bash
cp borgHelper /usr/local/bin/borgHelper
chmod +x /usr/local/bin/borgHelper
```

---

## Fichier de configuration

Par défaut : `~/.borghelperrc`  
Surchargeable avec `-C /autre/chemin`.

Format INI — une section par dépôt enregistré :

```ini
[mon-serveur]
BORG_REPO        = user@repo01:/mnt/borg/mon-serveur
BORG_PASSPHRASE  = motdepasse-du-repo
SER_NAME         = mon-serveur.domaine.com
SER_LOGIN        = root
GLOB_ARCH        = mon-serveur-root-*
MOUNTPOINT       = /mnt/borg/mon-serveur

# Rétention (au moins une clef requise pour Prune)
KEEP_DAILY       = 7
KEEP_WEEKLY      = 4
KEEP_MONTHLY     = 6
KEEP_YEARLY      = 2

# Backup
EXCLUDE          = --exclude /proc --exclude /sys --exclude /dev --exclude /tmp --exclude /run
# exclusions complémentaires optionnelles
EXCLUDE_NEXT     = --exclude /var/cache
# partie centrale du nom d'archive
BORG_ARCHNAME    = root
# chemins sauvegardés (1.0.163 : plusieurs, séparés par des espaces ; guillemets pour un chemin qui en contient)
#   BORG_ROOTBKP = /etc /home "/srv/mes documents"
# Chemin absent au Bkp : [WARN] (et « borgHelper_missing_roots » dans le JSON), les autres sont sauvegardés ; aucun
# présent ou valeur illisible (guillemet non fermé) : Bkp refusé (code 2, enregistré en échec) ; vide : « / ». Une valeur qui
# désigne telle quelle un chemin existant reste entière (rc d'avant : espace sans guillemets). Avec SSH_REMFO (borg
# distant) : rien de vérifié ici, la valeur passe telle quelle et le shell distant la découpe (guillemets compris).
BORG_ROOTBKP     = /

# Affichage rapport
# alerte si dernière sauvegarde > N heures (défaut 25) : serveur en erreur dans Report, et
# notification push « sauvegarde en retard » (borgHelperWWW >= 1.24.0, type Échec)
MAX_AGE_BKP      = 25
# Alertes Sentry opérationnelles (borgHelper >= 1.0.132, désactivées par défaut ; voir « Sentry » plus bas) :
#   bkp_error : sauvegarde en échec (ou bloquée au-delà du délai du watcher de borgHelperWWW)
#   overdue   : dernière sauvegarde plus vieille que MAX_AGE_BKP (détectée par borgHelperWWW, rappel à
#               chaque période supplémentaire)
# liste séparée par des virgules, ou all ; utilisable dans [DEFAULT] pour tous les serveurs
SENTRY_ALERTS    = bkp_error,overdue
# Délai au-delà duquel un Bkp démarré mais jamais fini est tenu pour interrompu (borgHelper >= 1.0.155,
# borgHelperWWW >= 1.28.4) : Status « probablement interrompu », /access bkp_running false, échec notifié par le
# watcher (définitif : la vraie fin d'un Bkp plus long n'est plus notifiée). SECONDES, ou suffixe s/m/h (12h,
# pas 12 : contrairement à MAX_AGE_BKP, un nombre seul est en secondes). [WARN] si invalide ou < 300 s.
# Défaut : variable BORGHELPERWWW_BKP_STATUS_TIMEOUT, sinon 6 h ; utilisable dans [DEFAULT] (vide dans la section du
# nick : [DEFAULT] ignoré, la variable s'applique). À poser aussi dans le rc de borgHelperWWW s'il en a un dédié.
# BKP_STATUS_TIMEOUT = 12h
# Pause des notifications push de ce serveur (borgHelperWWW >= 1.27.2), ex. pendant une maintenance :
# relu à chaque envoi, sans redémarrage ; journal seulement. Une alerte « en retard » n'est pas perdue :
# elle part à la reprise si le retard persiste. Ne touche pas Sentry (SENTRY_ALERTS).
PUSH_MUTE        = false
# nombre de sauvegardes affichées dans Report
DISPLAY_BKP      = 5

# SSH avancé (backup distant)
# BORG_REPO côté serveur sauvegardé
SSH_REPO         = repo01:/mnt/borg/mon-serveur
# tunnel inverse SSH
SSH_REMFO        = 8022:localhost:22
SSH_KEY          = /root/.ssh/id_borg

# Identifiant SQLite (optionnel — surcharge le nick dans le nom des fichiers DB)
# -> borghelperrc-mon-serveur-home-cache.db / -diff.db / -history.db
DB_NAME          = mon-serveur-home

# Désactiver l'indexation pour ce dépôt (Search/FileHist/DuIdx non disponibles)
NOIDX            = 1

# Filtres d'indexation
# Plusieurs patterns séparés par espaces sur une ligne,
# ou multiligne avec indentation (syntaxe INI standard) :
#
#   IDX_EXCLUDE = /tmp /proc /sys
#       /var/lib/docker
#       /home/*/.cache/*
#       *.pyc *.o *.log
#
# Préfixe plain : /home/, /etc  → startswith (rapide)
# Pattern glob  : *.bak, /home/*/.bash_history  → fnmatch (* matche tout y compris /)
#
# Logique : IDX_INCLUDE (liste blanche) ET IDX_EXCLUDE (liste noire) sont cumulatifs.
# Un chemin est indexé si : (aucun INCLUDE défini OU matche un INCLUDE)
#                        ET (aucun EXCLUDE défini OU ne matche aucun EXCLUDE)
# liste blanche — seuls ces chemins indexés
IDX_INCLUDE      = /etc /home /root
# liste noire (valeur multiligne : lignes de continuation indentées)
IDX_EXCLUDE      = /proc /sys /tmp /var/log
    /var/lib/docker /home/*/.cache
    *.bak *.pyc /home/*/.bash_history

# Parallélisation de l'indexation (nombre de borg diff simultanés, défaut 4)
IDX_WORKERS      = 4

# Limiter la taille de diff_index : conserver seulement les N dernières paires indexées
# Non défini = pas de limite (tout l'historique conservé)
DIFF_KEEP        = 30

# Rétention des historiques, en mois (défaut 13 : une vue annuelle complète pour repérer les motifs
# saisonniers). Défaut 13 si absent, non numérique ou < 1. S'applique à :
#  - repo_stats (taille du dépôt dans le temps) : purgé à chaque écriture (fin de Bkp/Prune réel) ;
#  - séries des graphiques (RepoHistory/ArchiveHistory, depuis 1.0.127) : bornées à cette durée à
#    l'affichage — les statistiques par archive restent en base tant que l'archive existe (Report,
#    Historique complet) ; quand elle disparaît, sa ligne de graphique est figée dans history.db et
#    reste affichée (marquée supprimée) jusqu'à cette durée (1.0.140) ;
#  - bkp_status (suivi des sauvegardes pour les notifications, depuis 1.0.127) : purgé au démarrage
#    d'une sauvegarde.
STATS_RETENTION_MONTHS = 13

# Clef explicite (keyfile mode, utile si plusieurs nicks partagent le même dépôt)
BORG_KEY_FILE    = /root/.config/borg/keys/abcdef123456

# Chemin de l'exécutable borg (défaut : 'borg' dans le PATH)
BORG_EXE                    = /usr/local/bin/borg1

# Borg divers
BORG_REMOTE_PATH            = borg1
BORG_RSH                    = ssh -p 2222
BORG_SHOW_SYSINFO           = no
BORG_RELOCATED_REPO_ACCESS_IS_OK = yes

# Autorisation par groupes (facultatif) — non interprété par borgHelper lui-même (ignoré par la CLI),
# reconnu uniquement par borgHelperWWW quand l'autorisation par groupes y est activée (voir sa propre
# section « Autorisation par groupes »). Listes de noms de groupes séparés par des virgules,
# hiérarchiques (admin ⊇ écriture ⊇ lecture — pas besoin de répéter un groupe dans les trois clefs).
# ⚠️ Un commentaire va toujours sur sa propre ligne, jamais après une valeur : configparser ne le
# coupe pas, il ferait partie du nom de groupe (qui ne correspondrait alors jamais).
# Un tier donne accès à TOUTES les sauvegardes du nick (équivalent d'un accès racine).
# GROUPS_ADMIN : Prune/DelBkp/IdxPurge/Init/Key/Login sur ce nick
GROUPS_ADMIN     = ops-admins
# GROUPS_WRITE : Bkp/Index/Restore/CacheClean (+ lecture)
GROUPS_WRITE     = ops-admins,ops-writers
# GROUPS_READ : tout le reste (+ téléchargements)
GROUPS_READ      = ops-admins,ops-writers,ops-readers

# Périmètre de chemin par groupe (facultatif). Syntaxe :
# 'groupe:/chemin/a|/chemin/b, groupe2:/chemin/c' — ':' sépare groupe et chemin(s), '|' sépare
# plusieurs chemins pour un même groupe, ',' sépare les groupes. Ces trois caractères sont donc
# réservés : un nom de groupe ou un chemin qui en contient fait échouer le chargement de la
# config avec une erreur explicite (jamais un résultat silencieusement mal découpé).
#
# Deux usages selon que le groupe a déjà un tier ci-dessus ou non :
#   - groupe AVEC tier (ops-readers) : restriction — il ne voit plus que ce chemin. Un groupe à
#     tier absent de GROUPS_PATHS garde un accès chemin illimité (ops-admins, ops-writers).
#   - groupe SANS tier (borgHelperWWW ≥ 1.20.0, accès direct) : dba-lecture et dba ne sont dans
#     aucun GROUPS_ADMIN/WRITE/READ — être cité ici leur donne directement la LECTURE de ces
#     chemins seulement (arborescence, recherche, historique), sans téléchargement.
GROUPS_PATHS     = ops-readers:/var/www/client-x, dba-lecture:/opt/backups/mysql, dba:/opt/backups/mysql

# Périmètre de RESTAURATION/téléchargement (facultatif, même syntaxe) — Restore/RestorePerms/
# DownloadFile/DownloadTar :
#   - groupe AVEC tier : absent d'ici, il reprend son entrée GROUPS_PATHS (lecture et
#     restauration identiques) ; présent (ops-readers), ce périmètre remplace le sien pour la
#     restauration seulement.
#   - groupe SANS tier : seul moyen de télécharger (aucun repli sur GROUPS_PATHS). dba peut
#     télécharger les dumps MySQL et PostgreSQL (et donc aussi parcourir /opt/backups/postgresql) ;
#     dba-lecture, absent d'ici, ne télécharge rien. Jamais POST /restore/Bkp/Prune (tier requis).
GROUPS_PATHS_RESTORE = ops-readers:/var/www/client-x/archives, dba:/opt/backups/mysql|/opt/backups/postgresql
```

Le nickname (nom de section) sert d'identifiant partout avec `-n`.

**Permissions.** `Login` crée `~/.borghelperrc` en `0600` (il contient des passphrases). Un rc existant n'est
jamais modifié, mais un avertissement (une fois, sur stderr) est émis à sa lecture si le groupe ou les autres y ont
accès. Le répertoire de cache est créé en `0700` et les bases `.db` en `0600` ; les fichiers/répertoires existants
sont laissés tels quels.

**Chiffrement des bases.** Deux clés optionnelles, globales (`[DEFAULT]`) ou par nick (la valeur du nick l'emporte) :

```ini
[DEFAULT]
# true par défaut ; false/no/off/0 pour désactiver (globalement ou pour un seul nick)
DB_ENCRYPT = true
# light | standard (défaut) | strong — coût de dérivation de la clé
DB_KDF     = standard
```

`DB_ENCRYPT=true` (défaut) : depuis 1.0.168, une base **neuve** (`diff.db`, `cache.db`) créée par `Bkp`/`Index`/`Prune`/
`Diff`/`Report` (cache de `borg info`) est chiffrée dès sa création quand la passphrase est disponible — sauf pour une base
partagée (`DB_NAME` sur ce nick, ou autre nick dont le `DB_NAME` désigne ce nick : en clair, comme avant). Base née d'une
passphrase fausse et encore sans aucun chemin : le créateur suivant, avec la bonne passphrase, lui pose une nouvelle clé ;
d'ici là (1.0.169), les lectures la voient vide (« Index vide — lancez Index »), sans `DbKeyError`.
`DbEncrypt -y`/`DbDecrypt -y` mettent aussi `cache.db` dans le mode voulu quand `diff.db` y est déjà. Une base **existante** en clair reste `plain` tant qu'on n'a pas lancé `DbEncrypt`
dessus (elle ne le devient pas toute seule — pas de migration implicite). Si une base reste `plain` alors que `DB_ENCRYPT` est actif et qu'une passphrase est disponible,
`borgHelper` avertit une fois par base (par invocation, sur stderr) et cite la commande à lancer. `DbEncrypt`/
`DbDecrypt`/`DbRekey`/`DbStatus` (voir [Commandes](#commandes)) basculent le mode d'une base réelle. La clé de
chiffrement est dérivée de `BORG_PASSPHRASE`. `DbRekey` ré-enveloppe la DEK existante avec un sel/nonce frais
(et le `DB_KDF` courant du nick, s'il a changé) — la DEK ne change pas et aucune ligne de donnée n'est touchée ; c'est
une rotation de l'enveloppe, PAS un mécanisme de changement de `BORG_PASSPHRASE` (celui-ci exigerait de connaître
simultanément l'ancienne et la nouvelle passphrase — hors périmètre de cette commande). Changer `BORG_PASSPHRASE`
dans le fichier de conf d'un nick dont la base est déjà chiffrée la rend illisible (`DbKeyError`) : ne le faites pas
sans avoir d'abord `DbDecrypt`é, et passez `DB_ENCRYPT=false` le temps du changement (sinon une base recréée entre-temps
naîtrait chiffrée avec l'ancienne passphrase). `DB_ENCRYPT=false`
pour un nick fait refuser `DbEncrypt` dessus explicitement (déchiffrer avec `DbDecrypt` reste toujours permis).
`borgHelper -c CodecSelfTest` vérifie le codec, la migration et ses refus sur des bases temporaires.

Répertoire de cache configurable via la clé `CACHE_DIR` dans la section `[DEFAULT]` — comme toute clef
INI, `GROUPS_ADMIN`/`GROUPS_WRITE`/`GROUPS_READ` supportent aussi ce repli sur `[DEFAULT]` (politique
par défaut pour tous les nicks qui ne les surchargent pas individuellement) :

```ini
[DEFAULT]
CACHE_DIR = /data/borgcache
# défaut : tout le monde peut au moins lire
GROUPS_READ = ops-readers,ops-writers,ops-admins
```

### Dépôts borg externes (1.0.142)

Un dépôt dont les archives sont créées **hors borgHelper** (autre outil, `borg create` à la main) se déclare avec
`EXTERNAL = true`. borgHelper le construit et le suit depuis le dépôt seul, par `Index` (et sa ligne cron par
tranches) ; il est listé, exploré, cherché, comparé, tracé en graphique et surveillé (`MAX_AGE_BKP`, notification
« dépassé », alerte Sentry `overdue`) comme les autres. borgHelper n'y crée jamais d'archive.

```ini
[autre-outil]
EXTERNAL         = true
# BORG_REPO : local ou ssh://, même accès borg qu'aujourd'hui
BORG_REPO        = user@repo01:/mnt/borg/autre-outil
BORG_PASSPHRASE  = motdepasse-du-repo
# GLOB_ARCH facultatif : absent = toutes les archives du dépôt
# GLOB_ARCH      = srv-*
# EXTERNAL_OPS : défaut read,restore ; parmi read, restore, prune, delete — bkp jamais permis
# EXTERNAL_OPS   = read,restore
# KEEP_* : exigé seulement si prune figure dans EXTERNAL_OPS
# KEEP_DAILY     = 7
MAX_AGE_BKP      = 25
```

- Aucune clé de Bkp n'est exigée (`SER_NAME`, `SER_LOGIN`, `BORG_ARCHNAME`, `BORG_ROOTBKP`, `EXCLUDE*`, `SSH_*`,
  `MOUNTPOINT`). Sans `MOUNTPOINT`, `Mount`/`UMount` répondent par un message (code 3), `Stats` l'indique.
- `EXTERNAL`, `EXTERNAL_OPS` et `GLOB_ARCH` se mettent dans la section du dépôt, jamais dans `[DEFAULT]` (ils
  s'appliqueraient à tous les nicks). `EXTERNAL` n'accepte que true/yes/on/1 ou false/no/off/0 (sinon code 2).
- **Opérations permises** : lecture (listes, exploration, recherche, rapports, `Index`, `Mount`, `Key`, maintenance
  des bases) toujours ; `Restore` par défaut ; `Prune` et `DelBkp` seulement si `EXTERNAL_OPS` les liste ; `Bkp`,
  `Init` et `Login` jamais. Une opération refusée sort avec le **code 4**, sans lancer borg. Avec `-n ALL`, les nicks
  où elle est refusée sont écartés (une ligne d'information), les autres continuent — un cron `Bkp -n ALL` sauvegarde
  les nicks internes un par un (depuis 1.0.167 ; voir [`Bkp`](#bkp)). Une liste explicite (`-n int,ext`) contenant un nick refusé sort avec le code 4 avant tout
  traitement, nick permis compris. `Restore -L` (liste des droits) est une lecture.
- `Prune -n ALL` ne s'arrête pas au premier nick refusé par sa configuration (`GLOB_ARCH` ou `KEEP_*` absent) :
  message, puis nick suivant.
- Mesures prises au Bkp (C/E, taille dédupliquée à la création) : absentes pour un dépôt externe (`null`, trous dans
  les graphiques) ; la taille du dépôt dans le temps vient des points relevés par `Index`.
- `Prune` d'un nick **interne** sans `GLOB_ARCH` est refusé (il porterait sur toutes les archives du dépôt, celles
  des autres hôtes comprises) ; sur un nick externe, il porte volontairement sur tout le dépôt.
- `demo.borghelperrc` contient une section `demo-externe` (commandes de remplissage en commentaire).

### Conversion depuis borgmatic (`borgmatic2borghelper`)

Script à part (`borgmatic2borghelper`, sa propre version, PyYAML requis — paquet `python3-yaml`) : lit une ou plusieurs
configurations borgmatic (format 1.7 à sections `location:`/`storage:`/`retention:`/…, ou 1.8+ à plat) et produit les
sections `.borghelperrc` correspondantes. **N'écrit jamais dans un rc existant.**

```bash
borgmatic2borghelper /etc/borgmatic/config.yaml                 # aperçu : sections rc sur stdout
borgmatic2borghelper -o ~/nouveau.borghelperrc /etc/borgmatic.d/*.yaml   # rc NEUF, 0600 ; refus si le fichier existe
borgmatic2borghelper -e -p bm- /etc/borgmatic/config.yaml       # nicks externes (EXTERNAL = true), préfixés « bm- »
borgmatic2borghelper --selftest                                 # auto-test (dossier temporaire)
```

- Un nick par dépôt (`repositories`, chaînes ou objets) : son `label`, sinon le nom du fichier sans `.yaml` ; dépôts
  suivants sans label ou nom déjà pris : `-2`, `-3`… ; `-p` préfixe les noms.
- Par défaut, nick **interne** (sauvegardé par borgHelper) : `BORG_REPO`, `BORG_PASSPHRASE` (`encryption_passphrase`),
  `BORG_RSH` (`ssh_command`), `BORG_REMOTE_PATH`, `BORG_EXE` (`local_path`), `BORG_ROOTBKP` (`source_directories`,
  guillemets si besoin), `EXCLUDE` (`exclude_patterns`, `exclude_from`, `patterns`, `patterns_from`,
  `exclude_if_present`, `exclude_caches`, `keep_exclude_tags`, `exclude_nodump`, `one_file_system`), `KEEP_HOURLY` à
  `KEEP_YEARLY`, `SER_NAME` (cette machine), `SER_LOGIN` (utilisateur courant).
- Noms d'archives : le début d'`archive_name_format` jusqu'à `{now…}` donne `BORG_ARCHNAME = ::<début>` (défaut
  borgmatic `{hostname}-{now…}` -> `::{hostname}`) et `GLOB_ARCH` (marqueurs `{hostname}` — nom court, comme borg —,
  `{fqdn}`, `{user}` résolus **sur la machine qui lance la conversion**) : les archives de borgmatic et celles de
  borgHelper restent dans le même motif. `match_archives` (`sh:` ou sans préfixe) ou `prefix` priment pour `GLOB_ARCH`.
  Les deux formats de nom se trient différemment (`…T12:00:00.123` / `…T1230…`) : à la transition, un snapshot complet
  peut être refait une fois.
- `-e` : nick **externe** (`EXTERNAL = true`, borgmatic continue de sauvegarder ; ni `BORG_ROOTBKP`, ni `EXCLUDE`).
- Tout ce qui n'a pas d'équivalent est nommé sur stderr (`[NON CONVERTI]`, avec sa section d'origine en 1.7) :
  `encryption_passcommand` (borgHelper lit `BORG_PASSPHRASE` seule), passphrase en `${VARIABLE}`, `checks`, hooks et
  commandes, `keep_within`/`keep_minutely`…, motif ou exclusion contenant un espace (`EXCLUDE` est découpé sur les
  espaces), valeur contenant `${VARIABLE}`, `{credential …}` ou commençant par `~` (développés par borgmatic, pas par
  borgHelper), valeur non textuelle (YAML : `on`, `yes`, `no`, `12:30` sont lus comme booléens ou nombres par PyYAML, pas
  par borgmatic — mettre entre guillemets), clés d'un dépôt autres que `path`/`label`, motif dans `source_directories`,
  aucune exclusion (`EXCLUDE` exigé par Bkp). Racines imbriquées : la plus haute seule (comme borgmatic). `constants:`
  est appliqué ; `!include` et dépôt contenant `${…}` refusés (code 2).
- `%` doublé dans les valeurs (le rc est lu avec interpolation). Relire le résultat avant usage : les passphrases y sont
  en clair.

### Sentry

DSN lu dans `BORGHELPERC_SENTRY_DSN`, sinon dans le fichier désigné par `BORGHELPERC_SENTRY_FILE`, sinon dans
`/usr/local/etc/borghelper-sentry` (première ligne) ; absent = Sentry désactivé. Depuis 1.0.132, Sentry ne reçoit que :

- les **erreurs logicielles** (exception non prévue, bug) — plus aucune trace de performance (auparavant une par
  invocation, donc une par clic de l'interface web) ; les erreurs de données ou de configuration (passphrase fausse,
  base altérée…) affichent un message et ne partent pas ;
- les **alertes opérationnelles** demandées par `SENTRY_ALERTS` (par serveur ou dans `[DEFAULT]`) : `bkp_error` —
  sauvegarde en échec, envoyée par borgHelper à la fin du `Bkp`, ou sauvegarde bloquée constatée par borgHelperWWW ;
  `overdue` — dernière sauvegarde plus vieille que `MAX_AGE_BKP`, constatée par le watcher de borgHelperWWW (qui doit
  donc tourner), une alerte au franchissement puis un rappel à chaque période supplémentaire, indépendamment des
  notifications push. Événements de niveau `error`, étiquetés `alert`/`nick`, regroupés par (type, serveur).

Chemins et passphrase sont masqués dans tout ce qui part (voir TECHNICAL.md, AD-15).

---

## Utilisation

```
borgHelper -c <commande> [options]
borgHelper -H <commande>    # aide détaillée d'une commande
borgHelper -h               # aide générale
borgHelper -v               # version
```

Options communes :

| Option | Description |
|--------|-------------|
| `-n <nickname>` | Dépôt cible (défaut : hostname) |
| `-n ALL` | Tous les dépôts du fichier de conf |
| `-d` | Mode debug (cumulable : `-dd`) |
| `-C <fichier>` | Fichier de conf alternatif |
| `-P <passphrase>` | Complète/supplante `BORG_PASSPHRASE` du fichier de conf pour cet appel |

Variable d'environnement `BORGHELPERC_RUNTIME_PASSPHRASE` : valeur par défaut de `-P` — préférable sur une machine partagée car invisible dans `ps aux` (contrairement à `-P`, qui apparaît en clair dans la liste des processus).

---

## Commandes

### `Stats`
Affiche l'état de montage de chaque dépôt enregistré.

```bash
borgHelper -c Stats
borgHelper -c Stats -n mon-serveur
```

---

### `Login`
Enregistre un dépôt dans `~/.borghelperrc`. Importe optionnellement une clef borg.

```bash
borgHelper -c Login -n mon-serveur -s mon-serveur.domaine.com \
           -p motdepasse -r user@repo:/mnt/borg/srv
borgHelper -c Login -n mon-serveur -p motdepasse -r /mnt/borg/local -k /root/borg.key
```

| Option | Description |
|--------|-------------|
| `-n` | Nickname (section INI) |
| `-s` | Nom du serveur (SER_NAME) |
| `-p` | Passphrase |
| `-r` | Chemin du dépôt |
| `-m` | Mountpoint (défaut : `/mnt/borg/<nick>`) |
| `-k` | Fichier de clef à importer |

---

### `Bkp`
Lance une sauvegarde selon la configuration du dépôt.  
Par défaut, indexe automatiquement la nouvelle archive dans le SQLite juste après la sauvegarde :
`borg diff` avec l'archive précédente (`diff_index`), puis snapshot incrémental (borgHelper ≥ 1.0.116 —
auparavant, les changements étaient déduits de `borg create --list`, qui prenait chaque répertoire pour
un fichier supprimé et ne voyait aucune suppression réelle, voir CHANGELOG).

```bash
borgHelper -c Bkp -n mon-serveur        # backup + indexation automatique
borgHelper -c Bkp -n mon-serveur -I     # backup seul, sans indexation
```

Nécessite : `EXCLUDE`, `SER_LOGIN`, `SER_NAME`.  
Code retour 0 si succès ou warnings, 2 si erreur borg.

Plusieurs nicks (`-n ALL`, `-n a,b` ; 1.0.167) : un Bkp après l'autre, dans l'ordre du fichier de conf pour `-n ALL`,
dans l'ordre donné pour une liste (dépôts externes écartés) ; un nick en échec n'arrête pas les suivants ; Ctrl-C arrête tout. Code retour : le pire des
nicks. Sortie : l'objet JSON de chaque nick, à la suite (même forme qu'un nick seul). Avant 1.0.167, plusieurs
nicks internes donnaient « Ce serveur est inconnu » (code 3) sans aucune sauvegarde.

> `-I` désactive toute écriture de changements/snapshot et l'appel automatique à `Index` — utile si l'indexation est gérée séparément (les statistiques de l'archive et la taille du dépôt restent enregistrées).

> **Priorité sur Index :** `Bkp` est prioritaire sur `Index` à tout moment — même si `Index` est en cours à n'importe quelle étape :
> - Si `Index` démarre alors que `Bkp` est déjà actif → annulation immédiate avant même le premier `borg diff`.
> - Si `Bkp` démarre pendant un `Index` → les `borg diff` actifs reçoivent SIGKILL, `Index` s'arrête complètement (borg info et indexsnap inclus).
> - Dans les deux cas, `Index` pose un flag de reprise (`index-pending.lock`) : `Bkp` le détecte en fin d'exécution et relance automatiquement `Index` complet.

**Sortie stdout (JSON)** — stdout ne contient que ce JSON, imprimé à la fin (après l'indexation ; ses
messages partent sur stderr). Si exit 0, le JSON borg est enrichi de deux clefs borgHelper, calculées à
partir du vrai `borg diff` de la paire (types de changement borg : `added`, `modified`, `removed`,
`added directory`, `removed directory`, `ctime`, `mode`...). Absentes si la paire n'est pas indexée
(première archive, `-I`, `NOIDX=1`, Index post-Bkp interrompu) :

**Fichiers modifiés pendant la sauvegarde / erreurs de lecture** (borgHelper ≥ 1.0.117) : `borg create`
tourne avec `--list --filter CE` — seuls deux statuts sont retenus, jamais utilisés comme un diff :
`C` (fichier modifié *pendant* sa lecture : copie possiblement incohérente — base de données, journal
actif…) et `E` (erreur de lecture : fichier non ou partiellement sauvegardé). Signalés par un `[WARN]`
récapitulatif sur stderr (100 chemins au plus, compteur exact), dans le JSON de sortie
(`borgHelper_backup_warnings`: `{changed_during_backup: {count, paths}, read_errors: {count, paths}}`),
et enregistrés par archive (`archive_stats`) : exposés par `ArchiveHistory -j` et visibles dans le
graphique « Fichiers modifiés par archive » de l'interface web. Actif aussi avec `-I`.

```json
{
  "archive": {
    "name": "mon-serveur-root-2026-06-05T020004",
    "start": "2026-06-05T02:00:04.000000",
    "duration": 42.3,
    "stats": { "nfiles": 183241, "original_size": 9871234560, "...": "..." }
  },
  "cache": { "...": "..." },
  "borgHelper_file_counts": {
    "added": 12,
    "modified": 3,
    "removed": 1
  }
}
```

En mode debug (`-d`), `borgHelper_files` s'ajoute avec la liste complète des fichiers touchés.

---

### `Prune`
Supprime les anciennes archives selon les règles `KEEP_*`.  
**Opération destructive.**

```bash
borgHelper -c Prune -n mon-serveur
borgHelper -c Prune -n ALL
```

Requiert au moins une clef `KEEP_*` dans la conf.  
Attend qu'un `Index` en cours se mette en pause (1.0.141), enchaîne automatiquement `borg compact`, invalide le cache SQLite, et retire des bases les archives disparues
(rapprochement, voir `Index`) — leurs lignes de graphique restent affichées pendant `STATS_RETENTION_MONTHS`.
Met aussi à jour le schéma de `cache.db`/`diff.db` si nécessaire avant toute opération (comme `Bkp`/`Index`)
— voir [Schéma de base de données](TECHNICAL.md#migrations-diffdb--table-de-correspondance-version--action).

---

### `Report`
Rapport sur l'état des sauvegardes — texte (prettytable) ou HTML.

```bash
borgHelper -c Report -n mon-serveur
borgHelper -c Report -n ALL
borgHelper -c Report -n ALL -l              # sortie HTML
borgHelper -c Report -n mon-serveur -N 5    # 5 dernières archives (surcharge DISPLAY_BKP)
borgHelper -c Report -n ALL -j             # sortie JSON
borgHelper -c Report -n ALL -o             # mode offline : même résumé que Report, toutes machines (même sans index), aucun appel borg
borgHelper -c Report -n ALL -o -j          # offline + JSON
borgHelper -c Report -n ALL -o -N 10       # offline + 10 dernières archives
```

Code retour 1 si un dépôt dépasse `MAX_AGE_BKP` heures depuis la dernière sauvegarde.  
Code retour 2 si un dépôt est inaccessible.

Dépôt local introuvable (disque démonté, chemin faux ; 1.0.167) : colonne `reste` = `⚠ dépôt absent`, nick en
alerte (`*** nick`, rouge en HTML), code 2 ; archives affichées en hors ligne (avant : aucune archive du nick dans
`Report -o`). Un dépôt présent mais illisible (droits) n'est jamais dit absent.

`diff.db` corrompue (1.0.171) : `Report -o` affiche le nick en erreur (`*** nick`) avec le message réel (« ⚠ DB corrompue
… »), code 2 — jamais « diff.db absent — lancez Index » ; base sans droits : « DB illisible … ne PAS supprimer le fichier ».
Plusieurs nicks : code de sortie = le pire des nicks.

Plusieurs nicks (1.0.166) : la base d'un nick tenue par un autre processus (migration, Index) est lue telle quelle,
sans message, après 2 s d'attente au plus par base (Report direct : `diff.db` et `cache.db`, soit ~4 s par nick occupé) ;
une base illisible ne donne qu'une ligne `*** nick ⚠ <message réel>` (`*** ERREUR nick` en direct ; code 2 ; 1.0.168 : par exemple
`⚠ DB corrompue : …/rc-nick-diff.db -> database disk image is malformed …`, avant `⚠ base illisible (voir message)`),
en direct comme hors ligne — les autres dépôts s'affichent toujours (liste des machines de borgHelperWWW comprise). Même attente bornée pour
`Status`.

En texte seulement (ni `-j` ni `-l`), en ligne de commande, une ligne finale signale les restes à nettoyer sur la
machine (1.0.160) : « Nettoyage possible : N entrée(s) borg de dépôts disparus (taille), … — aperçu : borgHelper -c
BorgCleanup ». Jamais dans `GET /report` (borgHelperWWW pose `BORGHELPERC_NO_CLEANUP_NOTICE`). Voir
[`BorgCleanup`](#borgcleanup).

**Variation de taille** — colonne `size_delta` : pourcentage de variation de `original_size` par rapport à l'archive précédente (`+11%`, `-5%`, `—` pour la première). `original_size` est stable dans le temps (indépendant de la déduplication inter-archives). Dans le résumé (ligne par hôte), ce delta de la dernière archive est aussi affiché entre parenthèses dans la colonne `derniere` — ex. `1.37 GB (+11%)`.

**Statistiques de mouvement** (si l'index SQLite est disponible) — colonne `modifications` :

| Contexte | `modifications` | Exemple |
|----------|----------------|---------|
| Résumé (par hôte) | `XX%nb / Y.YY GB` | `3%nb / 1.37 GB` |
| Détail (par archive) | `XX%nb / Y.YY GB` | `5%nb / 890 MB` |

Formule (identique résumé et détail) :
- `added`, `modified`, `removed` : **fichiers ordinaires** seulement (1.0.162), comme `nfiles` de borg — répertoires,
  liens, fifo et entrées `ctime`/`mtime` d'un répertoire dont le contenu change ne comptent pas ; fichiers exclus de
  l'indexation compris ; un `chmod` seul compte comme modifié (borg le signale ainsi)
- dénominateur = état précédent = `nfiles − added + removed` (100%) — égal au `nfiles` de l'archive précédente
- `XX%nb` = `100 × (modified + removed) / précédent` — % de fichiers modifiés ou supprimés. Avant 1.0.162, les
  comptes incluaient répertoires et liens : pourcentage surestimé dès qu'un répertoire changeait (mesuré : 200 %nb au
  lieu de 100 %nb)
- un fichier devenu lien, répertoire ou fifo (ou l'inverse) compte comme supprimé ou ajouté (1.0.163 : borg ne donne
  qu'un changement de `mode`, scindé à l'Index en suppression de l'ancien type et ajout du nouveau ; taille comptée 0,
  inconnue) ; paires indexées avant 1.0.163 : non comptées — `Index -F` refait les paires gardées (`DIFF_KEEP`) et le
  dernier snapshot, pas les comptes déjà figés
- limites : les exclus d'un `IdxPurge`
  antérieur à 1.0.162 peuvent compter d'anciens répertoires comme fichiers supprimés (pas de taille par ligne pour les
  distinguer). `DiffBkp`, `DiffTop` et `IdxTop` comptent, eux, des entrées (répertoires et liens compris)
- `Y.YY GB` = taille absolue lisible (`added_sz + modified_sz + removed_sz`), **pas** un pourcentage — `—` si nulle

- `—` si l'archive n'est pas encore indexée

**Version de borg** (1.0.165) — colonne `borg` du détail par archive (texte, HTML, JSON ; UI 1.20.0 : historiques court
et complet) : version du borg qui a **créé** l'archive, suivie de `/ srv X` quand le borg qui a **reçu** les données
est connu et différent (`1.2.6`, `1.2.6 / srv 1.2.4`), `—` si inconnue. borg n'enregistre aucune version (ni dans
l'archive, ni dans le dépôt, et `borg serve` ne transmet pas la sienne : mesuré, borg 1.2.6) : borgHelper la relève
lui-même **au Bkp** — archives créées hors borgHelper (dépôts externes) ou avant 1.0.165 : `—`.
- Créateur : message `borgbackup version X` de `borg create --show-version` (Bkp local comme distant `SSH_REMFO`, où
  c'est le borg de la machine sauvegardée) — aucune connexion de plus.
- Serveur, selon le mode :
  - tunnel inverse `SSH_REMFO` vers cette machine (`port:localhost:22`, `127.0.0.1`, `::1`, son nom) : le `borg serve`
    tourne ici -> `<BORG_REMOTE_PATH|borg> --version` en local ; tunnel vers une autre machine : `—` et `[WARN]` ;
  - dépôt ssh direct (`user@hôte:…`, `ssh://…`, IPv6 entre crochets) : `<BORG_RSH|ssh> [-p port] hôte
    <BORG_REMOTE_PATH|borg> --version`, avec l'environnement du borg du Bkp (sans agent ssh), entrée fermée, sans
    terminal (jamais d'invite de mot de passe), `BatchMode`/`ControlMaster=no` pour ssh, 15 s ; une clé à commande
    forcée (`command="borg serve …"` dans `authorized_keys`) lance `borg serve`, dont la réponse porte la version
    (`Borg 1.2.6: Got connection close…`, mesuré) : lue quand même ;
  - dépôt local (chemin, `file://`) : celle du créateur.
- Réponse sans numéro : `—` en silence ; échec (code d'erreur, délai, exécutable absent) : `—` et `[WARN]` ; jamais
  d'échec du Bkp ni de mesure perdue. JSON du Bkp : `borgHelper_borg_versions` `{archive, server}`.

**Mode offline** (`-o`) — rapport sans appel borg, depuis `diff.db` uniquement :
- `nfiles` et tailles par archive disponibles si `archive_stats` est peuplée (après `Bkp` ou `Index`)
- `taille` (taille dédupliquée du dépôt entier) disponible si `repo_stats` est peuplée (après `Bkp` ou `Prune` réel — dernière ligne historique, quel que soit son type)
- `reste` (espace disponible) alimenté via `df` local — non disponible pour les dépôts distants SSH
- `recuperable` toujours indisponible hors ligne (nécessite `borg prune --dry-run`)
- Combinable avec `-j`, `-l`, `-N <n>`

---

### `LstBkp`
Liste les archives disponibles — lecture base uniquement, pas d'appel `borg` (rapide).

```bash
borgHelper -c LstBkp -n mon-serveur
```

Nécessite `archive_stats` peuplée (`Bkp` ou `Index`). Sinon : "Aucune archive indexée en base".

---

### `LstBkpFls`
Liste les fichiers d'une archive — lecture base uniquement, pas d'appel `borg` (rapide).

```bash
borgHelper -c LstBkpFls -n mon-serveur
borgHelper -c LstBkpFls -n mon-serveur -b mon-serveur-root-2025-04-02T213004
borgHelper -c LstBkpFls -n mon-serveur -j   # JSON : {nick,archive,files:[chemin,...]}
```

Nécessite le snapshot de l'archive peuplé (`Indexsnap`). Sinon : "Aucun fichier indexé — lancer 'indexsnap'" (`{"error": "..."}` avec `-j`).

---

### `DiffBkp`
Différences entre deux archives — un fichier par ligne.

```bash
borgHelper -c DiffBkp -n mon-serveur                          # 2 dernières archives
borgHelper -c DiffBkp -n mon-serveur -b archive-ancienne      # vs dernière
borgHelper -c DiffBkp -n mon-serveur -b archive-1,archive-2   # entre deux précises
borgHelper -c DiffBkp -n mon-serveur -j   # JSON : {archive_old,archive_new,entries:[...],n_add,n_rem,n_mod}
```

Première colonne : `+` ajouté, `-` supprimé, `=` présent dans les deux archives (modifié, permissions, type).  
La taille est affichée en fin de ligne : taille finale pour `+`, initiale pour `-`, `avant → après` pour `=`.

```
mon-serveur-root-2026-06-04T020001 → mon-serveur-root-2026-06-05T020001
+ /etc/newfile                    42.3 KB
- /var/log/oldlog                 1.2 MB
= /etc/nginx/nginx.conf           8.5 KB → 9.1 KB
= /etc/hosts                      [C]

+ 1  - 1  = 2
```

Source : index SQLite si la paire est indexée, sinon `borg diff` + stockage automatique.

---

### `Restore`
Restaure un fichier ou une arborescence depuis une archive.

```bash
borgHelper -c Restore -n mon-serveur -b archive-id \
           -f etc/nginx/nginx.conf -w /tmp/restauration
borgHelper -c Restore -n mon-serveur -f etc/nginx/nginx.conf \
           -w /tmp/restauration          # archive auto depuis SQLite
borgHelper -c Restore -n mon-serveur -f 'etc/nginx/*.conf' \
           -w /tmp/backup.tar            # glob → tar avec arborescence
borgHelper -c Restore -n mon-serveur -f 'home/user/*.log' \
           -W /tmp/logs.tgz             # glob → tgz plat
borgHelper -c Restore -n mon-serveur -f 'etc/nginx/*.conf' -L          # liste les droits
borgHelper -c Restore -n mon-serveur -f 'home/user' -w - | tar -tvf -  # tar vers stdout
borgHelper -c Restore -n mon-serveur -f 'home/user' -w - \
           | ssh autre "tar -xf - -C /restore"                          # pipe vers hôte distant
```

| Option | Description |
|--------|-------------|
| `-b` | Nom de l'archive — si absent : dernière archive SQLite contenant `-f` |
| `-f` | Chemin exact ou glob (`*`, `?`) — glob réellement fonctionnel depuis 1.0.122 ; style shell de borg : `*` ne franchit pas `/`, `**` si (`'home/*/*.log'`, `'var/**/*.conf'`) |
| `-w <dest>` | Restauration avec sous-répertoires (répertoire ou `.tar`/`.tgz`) ; 1.0.173 : répertoire absent créé (comme `-W` ; retiré s'il reste vide après un échec de borg) ; destination vide, qui n'est pas un répertoire, non traversable, ou création impossible : `[ERREUR] destination … : …`, code 3, avant tout appel à borg (avant : trace Python). Cible `.tar` : son dossier doit exister |
| `-w -` | Tar non-compressé vers stdout (pipeable) |
| `-W <dest>` | Restauration plate — fichiers à la racine ; 1.0.173 : mêmes refus que `-w`, code 3 (avant : trace Python vers un fichier ou sans droits) |
| `-W -` | Tar plat non-compressé vers stdout |
| `-L` | Affiche droits/propriétaires sans restaurer |

> **Priorité sur Index :** `Restore` pose un lock sur le dépôt borg et attend la fin des `borg diff` actifs — même comportement que `Bkp`, même portée inter-nicks.

---

### `Mount` / `UMount`
Monte/démonte les archives via FUSE.  
**Le dépôt ne peut pas être sauvegardé tant qu'il est monté.**

```bash
borgHelper -c Mount -n mon-serveur               # toutes les archives
borgHelper -c Mount -n mon-serveur -b last       # dernière archive
borgHelper -c Mount -n mon-serveur -b archive-id
borgHelper -c UMount -n mon-serveur
```

---

### `Key`
Exporte la clef du dépôt en format papier.

```bash
borgHelper -c Key -n mon-serveur
borgHelper -c Key -n ALL
```

---

### `DelBkp`
Supprime une archive précise. **Opération destructive.**

```bash
borgHelper -c DelBkp -n mon-serveur -b archive-id
```

Opération prioritaire (1.0.142) : un `Index` en cours se met en pause, comme pour `Prune`.

L'archive supprimée quitte aussitôt les bases (rapports, historique, explorateur) : même rapprochement qu'après
`Prune` (1.0.145 ; avant, il fallait attendre le prochain `Index`). Si un autre Bkp, Restore ou Prune tourne sur le même
dépôt, ou si le rapprochement échoue (avertissement, jamais un échec de `DelBkp`), il est fait au prochain `Index`.

### Dépôt absent ou borg en échec (1.0.172)

`DiffBkp`, `Restore`, `Mount`, `Key`, `DelBkp`, `Prune` : dépôt local introuvable (disque démonté, chemin faux) ->
`<nick>: ⚠ dépôt absent (<BORG_REPO>)`, code 2, borg jamais lancé, aucune base créée (comme `Report`, 1.0.167) ; autre
échec de borg (passphrase, ssh, dépôt distant) -> `<nick>: borg <commande> a échoué : <message de borg>`, code 2 (DelBkp,
Prune, Mount : code de borg ; Restore avec `-b` : ligne de `borg extract` telle quelle ; code 1 de borg = avertissement,
Key et Mount affichent leur résultat). `DiffBkp -j` : `{"error": "…"}` seul sur stdout. `BORG_REPO` avec marqueur borg
(`{hostname}`…) : jamais dit absent (Report compris). Avant : trace Python (DiffBkp, Restore sans
`-b`, Mount `-b last`), dictionnaire brut (DelBkp, Prune, Mount), rien du tout et code 0 (Key). `Key` et `Prune` sur
plusieurs nicks : code de sortie = le pire des nicks.

---

### `Init`
Initialise un nouveau dépôt borg (chiffrement `repokey`).

```bash
borgHelper -c Init -n mon-serveur
```

---

### `Index`
Indexe les diffs entre archives consécutives dans `diff.db`.  
Incrémental — paires déjà traitées ignorées. Met à jour le snapshot de la dernière archive à la fin.

```bash
borgHelper -c Index -n mon-serveur           # diffs + snapshot
borgHelper -c Index -n ALL
borgHelper -c Index -n mon-serveur -F        # force la réindexation complète
borgHelper -c Index -n mon-serveur -S        # snapshot seul
borgHelper -c Index -n mon-serveur -S -F     # force le snapshot seul (borg list complet)
borgHelper -c Index -n mon-serveur -A <archive>  # indexe uniquement la paire terminant par <archive>
borgHelper -c Index -n ALL -t 20m            # tranche de 20 min par nick (ligne cron conseillée, horaire)
borgHelper -c Index -n mon-serveur -T diff -b 2026-09-01   # diffs seuls, archives depuis le 1er septembre
borgHelper -c Index -n mon-serveur --rebuild -t 20m        # reconstruction dans un fichier fantôme (1.0.143)
```

| Option | Description |
|--------|-------------|
| `-F` | Supprime et recalcule toutes les paires existantes (snapshot : force `borg list` complet) |
| `-S` | Snapshot seul — indexe uniquement le listing de la dernière archive |
| `-A <archive>` | Restreint l'indexation à la paire dont `archive_new` correspond à `<archive>` |
| `-t <durée>` | Tranche (1.0.141) : budget par nick — `90`, `90s`, `5m`, `1h` |
| `-T <natures>` | Tranche : parmi `stats,snap,diff` (défaut : les trois) |
| `--rebuild` | Reconstruction dans un fichier fantôme (1.0.143) : tranche qui crée ou poursuit `<diff.db>.rebuild` ; avec `-F`, repart de zéro |
| `-b` / `-B` | Tranche : période — nom d'archive, date `AAAA-MM-JJ[THH:MM:SS]` (borne haute : toute la journée incluse) ou `ALL` (sans borne) ; toute autre valeur est refusée — restreint stats et diffs |

**Index par tranches** (borgHelper ≥ 1.0.141) : `-t`, `-T`, `-b` ou `-B` (jamais avec `-F`, `-S` ou `-A`)
construisent ou complètent la base par petits morceaux, pensés pour une ligne cron. Ordre (1.0.146) : snapshot de la
dernière archive (explorable dès la première tranche), statistiques des archives (un `borg info` par archive, la plus
récente d'abord), puis diffs du plus récent au plus ancien. À l'échéance, le `borg` en cours est tué et son morceau
jeté ; les morceaux finis ne sont jamais refaits : le lancement suivant reprend. La tranche tourne en priorité basse
(`nice` 10, `ionice` idle). Choisir un budget qui couvre le `borg list` du début de chaque tranche, puis le snapshot
de la dernière archive (un `borg list` complet de l'archive la première fois : c'est la première unité, rien d'autre
n'avance tant qu'il ne tient pas dans le budget), un `borg info` ou un `borg diff` de deux archives consécutives,
sinon rien n'aboutit (un avertissement le signale). L'avancement (`partielle` / `terminée`, paires,
statistiques, snapshot) s'affiche en fin de tranche et dans `Status`. `-S` passe aussi par le verrou et la pause.

**Reconstruction dans un fichier fantôme** (borgHelper ≥ 1.0.143) : `Index --rebuild` reconstruit la base d'un nick
dans `<conf>-<nick>-diff.db.rebuild` (même `CACHE_DIR`, `0600`) pendant que l'ancienne base reste servie — CLI et
borgHelperWWW continuent de lire l'ancienne, sans changement. Il lance une première tranche (`-t` facultatif) ; ensuite,
toute tranche (`Index` avec `-t`, `-T`, `-b` ou `-B`, comme la ligne cron conseillée `Index -n ALL -t 20m`) fait d'abord l'incrémental de la base servie, puis avance le
fantôme avec le budget restant, dans le même ordre (snapshot, statistiques, diffs récents d'abord). Quand il est
complet, il remplace la base servie d'un coup, après avoir vérifié par un `borg list` que rien n'est arrivé entre-temps.
Un Bkp, Restore, Prune ou Report met la reconstruction en pause comme tout Index ; pendant la bascule, il l'annule
(base servie intacte, fantôme gardé, nouvel essai à la tranche suivante). L'Index sans option et celui de fin de Bkp ne
touchent jamais au fantôme : une ligne cron `Index` **sans option** ne fait pas avancer la reconstruction.

```bash
borgHelper -c Index -n mon-serveur --rebuild -t 20m   # démarre (ou poursuit)
# cron existant, inchangé : 0 * * * * borgHelper -c Index -n ALL -t 20m   -> poursuit puis bascule
borgHelper -c Index -n mon-serveur --rebuild -F       # jette le fantôme et repart de zéro
borgHelper -c Status -n mon-serveur                   # « Reconstruction (fantôme) en cours : 3/6 paires… »
```

- Refusé (code 3, rien créé) : moins de 2,2 × la taille de la base servie de libre (le fantôme, puis le WAL de la
  bascule), `diff.db` partagée entre plusieurs nicks par `DB_NAME` (la supprimer puis relancer `Index`), base en cours
  de `DbEncrypt`/`DbDecrypt`, base servie ou son en-tête illisible. Pendant une tranche ordinaire, le même refus laisse
  la base servie avancer et affiche « reconstruction suspendue ».
- `borg list` vide (`GLOB_ARCH` erroné, dépôt vidé) : le fantôme n'est ni avancé ni basculé.
- Tranche limitée par `-T` ou `-b/-B` (une borne autre que `ALL`) : le fantôme n'avance que dans ces limites ; il ne
  devient complet et ne bascule que lorsque le reste a été couvert (par d'autres tranches, limitées ou non). Un
  avertissement le signale (1.0.148). La ligne cron conseillée n'a pas de limite.
- Base chiffrée : le fantôme reprend l'en-tête de la base servie (même clé). Un `DbEncrypt`/`DbDecrypt`/`DbRekey`
  lancé entre deux tranches fait jeter le fantôme, qui repart de zéro.
- `IDX_EXCLUDE`/`IDX_INCLUDE` : déjà appliqués par `Index` ; la purge d'`IdxPurge` passe aussi sur le fantôme juste
  avant la bascule (lignes indexées avant un changement de motif).
- Abandonner : hors de tout `Index` en cours, supprimer `<diff.db>.rebuild` et ses `-wal`/`-shm` (jamais servis) ; un
  fantôme supprimé pendant une tranche est abandonné par celle-ci. Base servie absente : `--rebuild` la construit
  directement, sans fantôme.
- La base reconstruite ne garde que le snapshot de la dernière archive, comme un `Index` complet : les snapshots
  d'archives plus anciennes (gardés jusqu'à `IDX_SNAP_KEEP`) ne sont pas refaits. `history.db` (mesures) n'est jamais touchée.

**`DIFF_KEEP`** (corrigé en 1.0.141, pour tout Index) : seules les N paires les plus récentes sont calculées et gardées.
Avant, chaque Index recalculait les paires purgées au précédent, et la paire gardée changeait d'un Index à l'autre.

Types d'événements : `added`, `removed`, `modified`, `C` (permissions), `B` (lien cassé), `T` (type changé).

**Statistiques des graphiques** (borgHelper ≥ 1.0.114) : chaque `Index` — y compris `NOIDX=1` (les
chemins ne sont alors pas indexés) ou moins de 2 archives — met aussi à jour les données des
graphiques d'évolution de borgHelperWWW :
- statistiques des archives qui n'en ont pas encore (archives antérieures à cette fonctionnalité, ou
  créées hors borgHelper) — `borg info` n'est lancé que s'il en manque (`-F` : toutes). Pour ces
  archives, la taille dédupliquée est celle d'aujourd'hui (données propres à l'archive), pas celle
  mesurée lors de sa création ;
- un point de taille du dépôt (`op='index'`), seulement si elle a changé depuis le dernier point
  (jamais de doublon juste après un `Bkp`).

Le snapshot (`-S`) est **incrémental par défaut** : si un snapshot précédent et le diff correspondant existent, il en part, retire les chemins supprimés et relit par `borg list` chaque chemin changé (ajouté, modifié, droits, propriétaire, date, changement de type — 1.0.164 ; avant, seuls les ajouts étaient relus). Fallback vers `borg list` complet si : pas de snapshot précédent, diff absent, > 5 000 chemins changés, ou erreur borg. `-F` force le `borg list` complet.

**Un snapshot par archive, exact (1.0.164)** : chaque archive garde la taille, la date, le type, les droits et le
propriétaire qu'avaient ses fichiers — un fichier inchangé n'est stocké qu'une fois pour toutes les archives où il est
identique. Avant, une seule ligne par chemin, mise à jour à chaque snapshot : `LstBkpFls`, `Search`, `FileHist` ou
`DuIdx` sur une archive plus ancienne lisaient l'état actuel d'un chemin encore présent (ils lisent la vue par archive). La base passe au schéma 11
automatiquement (mesuré : 3 s pour un million de chemins, sans passphrase) ; les snapshots déjà faits gardent leurs valeurs partagées, seuls
les suivants sont exacts. Un borgHelper antérieur à 1.0.164 refuse ensuite la base (la supprimer et relancer `Index`
pour revenir en arrière). En base chiffrée, le snapshot incrémental perdait les fichiers ajoutés (corrigé).

**Archives supprimées hors borgHelper** (1.0.140) : chaque `Index` rapproche les bases de la liste `borg list` qu'il
obtient déjà (un `borg list` du dépôt entier en plus seulement pour un nick à `GLOB_ARCH` dont une archive manque, voir
Périmètre ci-dessous). Une archive disparue du dépôt — `borg prune`/`borg delete` bruts, `DelBkp` —
est retirée des diffs, snapshots, statistiques et mesures : `TreeHist`, `FileHist`,
`Search` et la restauration ne la proposent plus. Sa ligne de graphique est d'abord figée dans `history.db`, pour que
les graphiques par archive couvrent `STATS_RETENTION_MONTHS` (13 mois) même avec une rétention d'archives de quelques
semaines. Une liste d'archives vide (`GLOB_ARCH` erroné, dépôt vidé) ne retire rien et affiche un avertissement.
Aucune écriture quand rien n'a disparu. Le premier `Index` de 1.0.140 retire aussi, une fois, les lignes de diff
orphelines laissées par l'ancien nettoyage (archive du milieu supprimée : doublons, archive absente proposée).

**Périmètre du nick** (1.0.146) : `GLOB_ARCH` désigne les archives de la machine dans un dépôt que plusieurs machines
peuvent partager. Une archive sortie du motif mais encore présente dans le dépôt appartient à une autre machine : elle
quitte la base du nick (diffs, snapshots, statistiques ; reconstruits si l'on revient à l'ancien motif) **sans aucune
écriture dans `history.db`** — ni ligne de graphique figée, ni mesure retirée (« N archive(s) hors GLOB_ARCH (autre
machine) retirée(s) de la base — history.db inchangée »). Pour les distinguer d'une vraie disparition, un `borg list`
du dépôt entier est lancé, seulement quand une archive a quitté la liste filtrée (et jamais pour un nick sans
`GLOB_ARCH`) ; s'il échoue ou est interrompu, le rapprochement est reporté. Les lignes figées à tort avant 1.0.146
restent en place.
⚠️ Restreindre ou renommer `GLOB_ARCH` au point d'exclure des archives de **ce** nick les traite aussi en « autre
machine » : elles quittent ses rapports et ses graphiques sans y être figées, leurs mesures restent dans `history.db`
(message « connue(s) seulement par leurs mesures… GLOB_ARCH exclut-il des archives de ce nick ? », et un `borg list`
complet à chaque passe tant que le motif les exclut). Revenir à l'ancien motif les reconstruit.
`Index` ne compacte jamais `diff.db` : si le dépôt est élagué par `borg prune` hors borgHelper, lancer `IdxPurge` de
temps en temps pour rendre la place libérée (le `Prune` de borgHelper compacte lui-même).

> **Pause et reprise automatiques** (1.0.141) : si `Bkp`, `Restore`, `Prune` ou `Report` démarre pendant `Index`
> (quelle que soit l'étape : diffs, statistiques, snapshot), le `borg` en cours est tué et `Index` se met en pause en
> une seconde environ (quelques secondes si une écriture SQL est en cours) — l'opération prioritaire ne l'attend plus. Il attend la fin de l'opération (Index de fin de Bkp
> compris), puis reprend seul là où il en était : ce qui était fini est gardé, la nouvelle archive est prise en compte.
> Un seul `Index` à la fois par dépôt : un second (un cron, par exemple) s'arrête aussitôt avec « Index déjà en cours ».
> Une tranche (`-t`) compte la pause dans son budget et sort à l'échéance ; le cron suivant reprend.
> Depuis 1.0.145, les `borg diff` en cours sont arrêtés par SIGTERM (borg rend lui-même son verrou de dépôt), SIGKILL
> après 5 s seulement ; plus aucun `borg break-lock`, qui cassait aussi le verrou d'un `borg create` externe, d'un
> `borg mount` ou d'un autre hôte. L'Index attend la fin de **toutes** les opérations prioritaires du dépôt : un
> Restore qui finit pendant un Bkp ne le fait plus reprendre à côté du Bkp.

**Code de sortie** (1.0.145) : le pire rendu sur les nicks traités — `0` (fini, rien à faire, Index déjà en cours,
échéance, pause), `1` (erreur : `borg list` en échec, période `-b`/`-B` refusée…), `3` (`--rebuild` refusé). Une
ligne cron voit donc une tranche qui n'a pas pu démarrer. Un `borg diff` ou `borg info` en échec au milieu d'une passe
reste un avertissement (unité refaite au passage suivant), sans changer le code.

**Résultat du dernier Index** (1.0.149) : après chaque nick, `Index` écrit son résultat dans
`CACHE_DIR/<conf>-<nick>-index-last.json` (0600) : `outcome` (`ok`, `error`, `refused`, `busy` = « Index déjà en
cours », `deadline` = échéance atteinte pendant l'attente), `code`, heures de début et de fin (ISO avec décalage),
`via` (`http` pour un Index lancé par `POST /index`, sinon `cli`) et les dernières lignes d'erreur. Seul le dernier
passage est gardé, mais un `busy`/`deadline` reporte l'échec précédent (`last_failure`) jusqu'au prochain `ok` ;
fichier jetable. L'Index de fin de Bkp n'écrit rien. borgHelperWWW le montre (`GET /access`, badge « ⚠ Index en échec ») : un Index cron ou détaché en
échec n'est plus invisible.

---

### `Search`
Cherche par nom de fichier dans l'index des diffs et dans le snapshot.

```bash
borgHelper -c Search -f passwd -n mon-serveur
borgHelper -c Search -f '*.conf' -n ALL
borgHelper -c Search -f '/etc/nginx*' -n mon-serveur
borgHelper -c Search -f passwd -n mon-serveur -j   # JSON : {nick:[{date,archive,type,path,size_before,size_after},...]}
```

Plage : `-b <archive>` (depuis), `-B <archive>` (jusqu'à), `-b ALL` (tout), sans les deux (dernière paire).

Le motif porte sur le chemin complet ; sans `*`/`?`, sous-chaîne implicite. La comparaison ignore la casse des lettres ASCII
(`%`/`_` restent des jokers LIKE) ; résultats triés par date puis par chemin (ordre octet UTF-8).

Plusieurs nicks (1.0.167 ; même règle pour `FileHist`, `TreeHist`, `TreeFind`, `DuIdx`, `IdxTop`, `DiffTop`) : un nick
dont la base est inutilisable (passphrase fausse ou absente, base illisible, migration de chiffrement en cours, schéma
plus récent) n'arrête plus la commande — ligne `[ERREUR]` sur stderr avec le message réel, `{nick: {"error": "…"}}`
en JSON (DuIdx : totaux des autres nicks seulement, l'échec n'est que sur stderr), code 0 sinon (y compris quand
l'autre nick répond « Index vide »). Nick seul, ou tous en échec : comme avant (erreur du premier nick, code 2 pour
une base chiffrée inutilisable).

---

### `FileHist`
Historique complet des changements pour un chemin exact.

```bash
borgHelper -c FileHist -f /etc/nginx/nginx.conf -n mon-serveur
borgHelper -c FileHist -f /var/lib/postgresql -n ALL
borgHelper -c FileHist -f /etc/nginx/nginx.conf -n mon-serveur -j   # JSON : {nick:[{date,archive_before,archive_after,type,size_before,size_after},...]}
```

`-f` est une égalité exacte, sensible à la casse ; un `/` initial/final ou un `//` interne est normalisé avant comparaison
(`FileHist -f /etc/passwd` et `FileHist -f etc/passwd` trouvent la même entrée).

---

### `TreeHist`
Contenu **direct** d'un répertoire (racine entière si `-f` omis) — jamais le contenu d'un
sous-répertoire — en **un seul tableau** : le répertoire courant lui-même apparaît en `.`, puis ses
enfants immédiats. Liste **toujours l'intégralité** du contenu (dernier snapshot indexé), comme un
`ls` enrichi, y compris les entrées sans événement dans la plage demandée (présentes, inchangées) —
plus les enfants directs supprimés depuis mais toujours récupérables (voir plus bas).

Colonnes : `nom`, `genre` (répertoire / fichier / lien symbolique / fifo / socket / périph. bloc ou
caractère — type réel stocké par borg), `droits` (ls-style, ex. `drwxr-xr-x`), `propriétaire`
(`user:group (uid:gid)`, ex. `root:root (0:0)`) — **droits et propriétaire sont le dernier état connu**,
pas forcément celui de l'archive sélectionnée dans `-b`/`-B` —, type d'événement
(`added`/`modified`/`removed`/…), archive, date. `aucun événement dans la plage` si l'entrée n'a pas
bougé sur la période demandée ; genre/droits/propriétaire `inconnu (réindexer)`/`—` si l'entrée a été
snapshotée avant l'ajout de ces colonnes — réindexer (`Index -F -S`) pour les peupler.

**Un sous-répertoire affiche un événement dès qu'un changement a eu lieu n'importe où dans sa
sous-arborescence** (fichier ajouté/modifié/supprimé à n'importe quelle profondeur en dessous) — sans en
lister le détail (pas de contenu de sous-répertoire, juste les types/archives/dates distincts concernés).
Un fichier, lui, n'affiche que ses propres événements.

`added`/`removed` sur un répertoire ne concernent **que son entrée à lui** (ex. `added directory` /
`removed directory` quand il est réellement créé/supprimé). Un mouvement interne quelconque — même un
simple `added` ou `removed` d'un fichier niché en dessous — remonte en `modified` générique, jamais en
`added`/`removed` emprunté à un descendant.

Pour descendre dans un sous-répertoire, relancer `TreeHist` avec `-f` pointant dessus.

**Préfixe (`-f`) sensible à la casse et littéral** (depuis 1.0.101, aussi pour `TreeFind -f`, `DuIdx -f 'préfixe/*'`,
`IdxPurge -x préfixe`) : `-f /Etc` ne trouve pas `/etc`, et `%`/`_` n'y sont pas des jokers (un dossier `a%b` n'inclut jamais
son frère `aXYZb`). Auparavant la comparaison ignorait la casse ASCII.

**Base chiffrée — vérification limitée au niveau affiché** (depuis 1.0.121) : `TreeHist` ne décode, et donc ne
vérifie, que le répertoire listé et ses enfants directs, plus chaque chemin de toute la sous-arborescence —
l'explorateur ne paie plus le coût d'un sous-arbre entier pour afficher quelques entrées. Une altération de la
base sur un chemin plus profond n'est signalée qu'en descendant jusqu'à lui (ou par `TreeFind`/`Search`, qui
vérifient tout). Sans effet sur une base non chiffrée.

**Fichiers/répertoires supprimés** : les enfants directs supprimés depuis (mais toujours
récupérables — l'archive de dernière présence existe encore) apparaissent aussi, marqués
distinctement (colonne `type`=`supprimé`, colonne `archive`=archive à restaurer). Un répertoire
entièrement supprimé reste explorable : `TreeHist` dessus affiche son ancien contenu au lieu d'une
erreur. Un chemin réajouté depuis sa suppression réapparaît normalement, sans marque. JSON (`-j`) :
ces entrées portent `"deleted":true,"last_seen_archive":"<archive>"` en plus des clés habituelles
(`mode`/`owner` à `null` ; `genre`/`is_dir` = vrai type — répertoire, lien symbolique, fifo, périphérique — depuis
1.0.126, auparavant seuls les fichiers supprimés apparaissaient) ; les entrées non
supprimées gardent une forme JSON strictement inchangée.

**Changements entre deux sauvegardes (`-X`, depuis 1.0.133)** : seules les entrées qui ont changé **après** `-b` (exclue :
c'est l'état de départ) et **jusqu'à** `-B` (incluse) — fichier ajouté, modifié ou supprimé (type réel : fichier,
répertoire, lien, fifo…), répertoire dès qu'un changement a eu lieu n'importe où en dessous. Une entrée supprimée dans la
plage est marquée `supprimé` (JSON : `deleted`, `last_seen_archive` = archive à restaurer). Sans `-b` : depuis le début ;
sans `-B` : jusqu'à la dernière archive. Source : l'index des différences (`Index`) — une paire non indexée n'y figure pas.

```bash
borgHelper -c TreeHist -n mon-serveur                        # contenu direct de la racine
borgHelper -c TreeHist -f /etc -n mon-serveur -b srv-2026-09-01 -B srv-2026-09-27 -X   # ce qui a changé sous /etc
borgHelper -c TreeHist -f /etc -n mon-serveur -b ALL          # contenu direct de /etc, tout l'historique
borgHelper -c TreeHist -f /var/lib/docker -n ALL -b ALL
```

Plage : `-b <archive>` (depuis), `-B <archive>` (jusqu'à), `-b ALL` (tout), sans les deux (dernière
paire indexée seulement — comme `Search`). Une entrée présente mais sans événement dans cette plage
affiche `aucun événement dans la plage` plutôt que d'être omise. La détection des entrées
**supprimées** est indépendante de `-b`/`-B` — la garantie de récupérabilité ne dépend pas de la plage
consultée, elle apparaît identiquement quel que soit `-b`/`-B`.

Genre/droits/propriétaire `inconnu (réindexer)`/`—` : entrée snapshotée avant l'ajout des colonnes
`type`/`mode`/`owner`. Se répare tout seul au **prochain `Bkp`** (indexation automatique activée) :
`IndexSnap` détecte une colonne manquante et force un resnapshot complet cette fois-là (message
« type/mode/propriétaire manquant… auto-réparation »), puis revient à l'incrémental normal ensuite. Pour
forcer immédiatement sans attendre un backup : `Index -F -S`.

---

### `TreeFind`
Recherche **récursive par nom** (pas le chemin complet) sous un préfixe (racine entière si omis), dans
le **dernier snapshot connu** — comme `TreeHist`, mais récursif et filtré par motif — plus les chemins
supprimés depuis mais toujours récupérables (voir plus bas ; c'est le seul historique consulté, pas
un remplacement de `Search`).

```bash
borgHelper -c TreeFind -n mon-serveur -m '*.log'                   # toute l'arborescence
borgHelper -c TreeFind -n mon-serveur -f /var/log -m 'error*'      # sous un préfixe précis
borgHelper -c TreeFind -n mon-serveur -m backup                    # sous-chaîne implicite (sans *)
borgHelper -c TreeFind -n mon-serveur -m '*.ko' -j                 # JSON
```

Motif minimal (`-m`) : `*` = n'importe quelle suite de caractères, `.` reste **littéral** (pas de sens
spécial) ; sans `*` (ni `?`) dans le motif, sous-chaîne implicite (comme `Search`). Comparaison sur le
**nom** de l'entrée uniquement (dernier segment du chemin), **insensible à la casse** (`casefold`,
correct aussi pour les caractères accentués — `-m 'error*'` trouve `ERROR.log` comme `Error.LOG`).

Le préfixe (`-f`) est sensible à la casse et littéral (`%`/`_` n'y sont pas des jokers) ; un `/` initial/final ou un `//`
interne est normalisé avant comparaison — voir la note dans `TreeHist` ci-dessus.

Colonnes (mode texte) : `nom`, `genre`, `chemin` (complet), `droits`, `propriétaire`, `état` — dernier
état connu, même limitation que `TreeHist`. JSON (`-j`) :
`{nick:{archive,scope,pattern,matches:[{name,full_path,parent,is_dir,genre,mode,owner}]}}` — `parent`
est le répertoire contenant l'entrée, pratique pour y naviguer directement (utilisé par l'explorateur
de l'interface web).

**Fichiers/répertoires supprimés** : recherchés récursivement sous le préfixe comme les chemins
présents (même filtre de motif), et inclus dans `matches` même s'ils ne sont plus dans le dernier
snapshot — tant qu'ils restent récupérables (archive de dernière présence encore existante). Colonne
`état` en mode texte (`supprimé (<archive>)`) ; en JSON, `"deleted":true,"last_seen_archive":"<archive>"`
en plus des clés habituelles (`mode`/`owner` à `null`).

---

### `DuIdx`
Résumé `du -sh`-like depuis le SQLite.

```bash
borgHelper -c DuIdx -n mon-serveur                         # résumé global par type
borgHelper -c DuIdx -f '*' -n mon-serveur                  # détail par répertoire racine
borgHelper -c DuIdx -f 'home/*' -n mon-serveur             # détail sous home/
borgHelper -c DuIdx -f 'home/*_old' -n mon-serveur         # seulement les home/…_old (depuis 1.0.125)
borgHelper -c DuIdx -f 'home/*/.cache' -n mon-serveur      # un .cache par utilisateur (depuis 1.0.125)
borgHelper -c DuIdx -f '*.log' -n ALL                      # résumé global sur les .log
borgHelper -c DuIdx -f '*' -s présent:desc -n mon-serveur  # trié par taille présent desc
borgHelper -c DuIdx -f '*' -j -n mon-serveur               # sortie JSON
borgHelper -c DuIdx -n mon-serveur -R                      # sortie brute, une ligne JSON par chemin
```

Le préfixe (`-f 'préfixe/*'`) est sensible à la casse et littéral (`%`/`_` n'y sont pas des jokers) ; un `/`
initial/final ou un `//` interne y est normalisé avant comparaison. **Motif groupé complet** (depuis 1.0.125) : chaque
composant du motif filtre le composant de même rang du chemin (`*` et `?` ne franchissent jamais `/`) et le
regroupement se fait à la profondeur du motif — `home/*_old`, `home/*/.cache`, `var/lib/*/data/*` sont honorés.
Auparavant, tout ce qui suivait le dernier `/*` était ignoré sans prévenir (`home/*_old` agissait comme `home/*`). Le motif de nom (`-f motif` sans `/*`) reste
insensible à la casse ASCII, comme `Search`.

`-R` (Story 1.4) : mode brut, une ligne `{chemin,type,taille}` par chemin, **jamais groupée** —
distinct de `-j` qui reste le mode groupé historique (JSON `rows`/`total` par arborescence ou par
type, format inchangé). Usage interne : `borgHelperWWW` s'en sert pour filtrer par périmètre de
chemin puis regrouper lui-même sur les seules lignes en périmètre (voir « Autorisation par
groupes » plus haut) ; utile aussi en CLI pour post-traiter les données par-chemin soi-même.

---

### `IdxTop`
Top N arborescences du `diff_index` par nombre d'entrées — diagnostic d'un `diff.db` volumineux.

```bash
borgHelper -c IdxTop -n mon-serveur           # top 20, profondeur 3
borgHelper -c IdxTop -n mon-serveur -N 10     # top 10
borgHelper -c IdxTop -n mon-serveur -p 4      # profondeur 4
borgHelper -c IdxTop -n mon-serveur -j        # sortie brute, une ligne JSON par chemin
```

| Option | Description |
|--------|-------------|
| `-N <n>` | Nombre de lignes affichées (défaut : 20) |
| `-p <n>` | Profondeur de regroupement des chemins (défaut : 3) |
| `-j` | Sortie brute (Story 1.4) : une ligne `{chemin,taille}` par chemin, **sans** regroupement/top-N ni les figures Exclus/Inchangés — `-N`/`-p` sont ignorés dans ce mode. Usage interne (`borgHelperWWW` filtre par périmètre puis regroupe/classe lui-même). |

Parcours en streaming (batchs 50 000 lignes) — fonctionne sur les grosses bases sans surcharge mémoire.

Affiche également le total des entrées **exclues** par `IDX_EXCLUDE` (stockées dans `diff_excluded_stats`) :

```
Indexés : 142 350 entrées · 1.2 GB
Exclus  :  18 200 entrées · 3.4 GB (IDX_* / IdxPurge) — +5 000 · -200 · =13 000
```

Le détail `+ajoutés · -supprimés · =modifiés` est affiché sur la même ligne. Seuls les types présents sont affichés. Les fichiers inchangés ne peuvent pas être comptés (`borg diff` ne les liste pas).

Si `IDX_EXCLUDE` est vide ou qu'aucun fichier n'a été filtré, la ligne Exclus est omise.

Affiche également les fichiers **inchangés par archive** avant le tableau :

```
Inchangés par archive :
  archive-2024-01-01 : 95 000 (97%) / 98 000 fichiers
  archive-2024-01-02 : 96 200 (96%) / 100 000 fichiers
```

Calcul : `nfiles − added_total − modified_total` (indexés + exclus). `nfiles` de borg ne compte que les fichiers ordinaires (ni répertoires, ni liens, ni fifos) : seuls les types exacts `added` et `modified` (fichiers) sont retranchés, jamais les répertoires, liens ni entrées `ctime`/`mtime` d'un répertoire (1.0.156, même calcul que DiffTop ; IdxTop cumule toutes les paires qui aboutissent à l'archive, DiffTop une seule paire — valeurs égales quand une seule paire y aboutit). Le détail « Exclus » compte toutes les entrées ; « Inchangés », seulement les fichiers. Limites (mesurées sur borg 1.2.6) : borg signale `modified` (+0/−0) dès que le ctime d'un fichier change (droits, propriétaire, dates, même `touch -a`) — un tel fichier compte comme **modifié** ; un fichier à plusieurs liens physiques n'est compté qu'une fois dans `nfiles` mais chaque nom a sa ligne `added`/`modified` — « Inchangés » est alors sous-estimé (0 au plus bas) ; un lien ou un répertoire remplacé par un fichier ne donne qu'une ligne `mode` — ce nouveau fichier compte comme inchangé. Seules les archives présentes dans `archive_stats` (avec `nfiles` non nul) et dans `diff_index` ou ses exclus sont affichées.

---

### `RepoHistory` / `ArchiveHistory`
Historique brut, colonnes brutes, pour un seul nick à la fois — destiné à l'API (`borgHelperWWW`
`/repohistory`/`/archivehistory`), source des graphiques d'évolution des sauvegardes. Aucune métrique
dérivée (gain Prune, % dédup) n'est calculée ici — uniquement les valeurs telles que stockées.

```bash
borgHelper -c RepoHistory -n mon-serveur -j       # historique repo_stats (taille du dépôt), JSON brut
borgHelper -c ArchiveHistory -n mon-serveur -j    # historique archive_stats (par archive), JSON brut
```

| Option | Description |
|--------|-------------|
| `-n <nick>` | Un seul nick — jamais `nick=a,b` ni `ALL` sur plusieurs nicks configurés (rejeté, code de sortie non nul) |
| `-j` | Sortie JSON `{borghelper_version,nick,rows:[...]}` — sans `-j` : message court, pas de crash (mode texte non destiné à un usage interactif élaboré) |

`RepoHistory -j` : une ligne par événement `repo_stats` (`id`,`op` (`'bkp'|'prune'|'index'`),`unique_csize`,
`total_size`,`total_csize`,`updated_at`), ordonnées par `id` croissant.

`ArchiveHistory -j` : une ligne par archive de `archive_stats` (`archive`,`archive_date`,`duration`,
`original_size`,`compressed_size`,`deduplicated_size`,`nfiles`), ordonnées par `archive_date`.
Depuis 1.0.115, en plus : `files_added`/`files_modified`/`files_removed` — nombre de fichiers ajoutés,
modifiés et supprimés par rapport à l'archive précédente, même source que la colonne « Modifs » de `Report`
(fichiers exclus de l'indexation compris) ; fichiers ordinaires seulement depuis 1.0.162 (répertoires, liens et
entrées `ctime`/`mtime` de répertoires comptés avant) — les lignes figées d'archives déjà purgées gardent leurs
anciennes valeurs (série mixte sur ce passé) ; `null` si cette paire
d'archives n'est pas indexée (première archive, purgée par `DIFF_KEEP`, `NOIDX=1`, Index pas encore
passé). Et `changed_during_backup`/`read_errors` (1.0.117) : fichiers modifiés pendant la sauvegarde /
erreurs de lecture, relevés par le Bkp — `null` si inconnus (archive antérieure, ou statistiques
rattrapées par Index).
Depuis 1.0.165 : `borg_version` / `borg_server_version` — versions de borg relevées au Bkp (créateur de l'archive,
borg qui a reçu les données ; voir `Report`, « Version de borg ») — `null` si inconnues (archive créée hors borgHelper
ou avant 1.0.165, ligne figée).
Depuis 1.0.140 : `pruned` (booléen) sur chaque ligne. `true` = archive disparue du dépôt, ligne figée dans
`history.db` au moment de sa disparition et gardée `STATS_RETENTION_MONTHS` (graphiques sur 13 mois même avec une
rétention d'archives courte) — jamais restaurable. Pour une archive présente dont la paire précédente a été retirée
(archive précédente disparue, `DIFF_KEEP`), `files_*` reprend les comptages figés au lieu de `null`.

`diff.db` jamais indexé : `{'error':'diff.db absent pour <nick>'}`, jamais une exception (même
comportement que `IdxTop -j`).

---

### `Status`
État rapide (dernier backup connu, Bkp en cours, opération prioritaire en cours) par nick — **100%
local, jamais d'appel `borg`** (contrairement à `LstBkp`/`GetLastBkp` qui interrogent le dépôt en
direct) : rapide, fonctionne hors ligne, ne bloque jamais sur un dépôt distant injoignable.

```bash
borgHelper -c Status -n mon-serveur          # un seul nick, texte
borgHelper -c Status -n a,b                  # plusieurs nicks
borgHelper -c Status -n ALL -j               # tous les nicks configurés, JSON
```

| Option | Description |
|--------|-------------|
| `-n <nick1,nick2>` / `-n ALL` | Un ou plusieurs nicks nativement (contrairement à `RepoHistory`/`ArchiveHistory` qui rejettent le multi-nick) — c'est le cas d'usage principal de `Status` |
| `-j` | Sortie JSON — toujours une **liste**, même à un seul nick : `[{nick,last_backup,bkp_running,bkp_stale,priority_op_running,build,rebuild}, ...]` — `rebuild` (1.0.143) : état du fichier fantôme (`build_state`), `null` sans reconstruction |

En texte, en ligne de commande, une ligne finale signale les restes à nettoyer sur la machine, comme `Report`
(1.0.160 ; JSON inchangé ; jamais via borgHelperWWW) — voir [`BorgCleanup`](#borgcleanup).

Par nick :
- **Dernier backup connu** : archive + date depuis `archive_stats` (déjà indexée localement) + âge
  lisible (« il y a 3h12 ») ; « aucune archive indexée » si le nick n'a jamais été indexé. Ligne suivante (1.0.165) :
  `borg : 1.2.6` (ou `1.2.6 / srv 1.2.4`, `—`), versions relevées au Bkp de cette archive ; JSON : `last_backup`
  porte `borg_version` et `borg_server_version`.
- **Bkp en cours** : si une ligne `bkp_status` non terminée existe, « Bkp en cours depuis HH:MM
  (XhYYmin) ». Démarrée depuis plus que le délai du nick (1.0.154) : « Bkp sans fin depuis HH:MM (XhYYmin) — probablement
  interrompu (délai 6 h dépassé) », jamais « en cours » (date affichée au-delà de 24 h). Seule la dernière ligne du nick
  compte : un Bkp tué suivi d'autres Bkp n'est plus affiché (1.0.155 : effacé seulement par un Bkp plus récent réussi ;
  un Bkp vivant suivi d'un Bkp arrêté en échec par le verrou du dépôt reste « en cours »). Délai (1.0.155) : clé rc
  `BKP_STATUS_TIMEOUT` du nick ou de `[DEFAULT]` (secondes, ou `90s`/`5m`/`12h`), sinon la variable
  `BORGHELPERWWW_BKP_STATUS_TIMEOUT`, sinon 6 h — le même que `/access` et le watcher à condition qu'ils lisent le même
  rc (`-C` et `BORGHELPERWWW_CFGFILE`), ou que les deux rc portent la même clé. La variable se lit dans l'environnement
  de chaque processus : préférer la clé rc.
- **Opération prioritaire en cours** : si un autre processus tient le verrou prioritaire (`priority.lock.<pid>`) et qu'aucun Bkp en cours n'est détecté (un Bkp interrompu ne la masque pas),
  « Opération prioritaire en cours (Restore, Prune ou DelBkp) » (« Bkp peut-être toujours actif, … » si un Bkp interrompu est affiché) — **ambiguïté assumée**, `priority.lock` ne
  distingue pas laquelle le tient. Si un Bkp est aussi détecté, pas de message redondant (le
  Bkp lui-même tient ce lock).

En JSON : `last_backup` est `{archive,date}` ou `null` ; `bkp_running` est `{started_at}` ou `null` ; `bkp_stale`
(1.0.154) est `{started_at,timeout_s}` (`timeout_s` 1.0.155 : délai du nick) pour un Bkp sans fin au-delà du délai (alors `bkp_running` vaut `null`), sinon `null` ;
`priority_op_running` est un booléen brut (reflète `priority.lock`, indépendamment de `bkp_running` —
c'est au consommateur de corréler les deux, comme pour l'affichage texte). `build` (1.0.141) : état de construction
de la base, `{state:'partial'|'complete', pairs_done, pairs_total, archives_total, stats_done, snapshot, updated_at}` écrit par les
tranches d'Index ; `{state:'complete'}` pour une base jamais construite par tranches. En texte, une ligne
« Construction partielle : X/Y paires, statistiques A/B » tant qu'elle n'est pas finie ; `null` si le nick est en
erreur (champ `error`). Base chiffrée sans passphrase ou en migration (1.0.145) : `last_backup` porte l'erreur, `build`
vaut `null`, mais `bkp_running`, `rebuild` et `priority_op_running` (lisibles sans clé) restent renseignés.

---

### `IdxPurge`
Supprime rétroactivement des entrées de `diff_index`, purge les snapshots anciens et compacte le `diff.db`.

```bash
borgHelper -c IdxPurge -n mon-serveur -D              # dry-run selon IDX_EXCLUDE/IDX_INCLUDE
borgHelper -c IdxPurge -n mon-serveur                 # purge selon IDX_EXCLUDE/IDX_INCLUDE
borgHelper -c IdxPurge -n mon-serveur -x /var/log     # purge un préfixe explicite
borgHelper -c IdxPurge -n mon-serveur -x '*/node_modules/*'  # purge un glob
```

| Option | Description |
|--------|-------------|
| `-x <pattern>` | Pattern explicite : préfixe (sensible à la casse, littéral) ou glob avec `*?[` |
| `-D` | Dry-run — affiche le volume sans supprimer |

Le préfixe (`-x`, et chaque entrée non-glob de `IDX_INCLUDE`/`IDX_EXCLUDE`) est sensible à la casse et littéral
(`%`/`_` non-jokers). **Non normalisé, contrairement aux autres commandes** : un `/` initial ne cible jamais rien (les
chemins stockés n'ont jamais de `/` initial), comportement volontairement préservé pour cette commande destructive.

Sans `-x`, lit `IDX_EXCLUDE`/`IDX_INCLUDE` depuis la configuration du nick et purge tout ce qui serait exclu à l'indexation.

**Purge automatique des snapshots :** en fin d'opération, `IdxPurge` purge aussi les snapshots (`archive_snapshot`) au-delà du seuil `IDX_SNAP_KEEP`. Si `IDX_SNAP_KEEP` n'est pas défini, le seuil est calculé comme `sum(KEEP_DAILY + KEEP_WEEKLY + KEEP_MONTHLY + KEEP_YEARLY + KEEP_HOURLY)`, ou 10 si aucune règle KEEP_* n'est configurée. Le dry-run `-D` affiche également les snapshots qui seraient purgés.

Les entrées supprimées rejoignent les exclus de leur paire (`diff_excluded_stats`, nombre et taille par type de changement, 1.0.154) : `modifications` de Report, ArchiveHistory et IdxTop sont inchangés par la purge (les fichiers purgés y comptent comme exclus — seule exception, un fichier `modified` dont la taille après vaut 0 compte alors sa taille avant, comme un exclu de l'Index), une paire entièrement vidée n'est pas prise pour une paire vide à tort, et DiffTop comme IdxTop affichent encore ses exclus (« IDX_* / IdxPurge », 1.0.155 pour IdxTop : plus de « diff_index vide » s'il reste des exclus). Détail des exclus par familles, comme Report (1.0.155) : `+` tous les ajouts (fichiers, répertoires, liens…), `-` toutes les suppressions, `=` tout le reste (`modified`, `changed link`, `mode`…) — la somme vaut le total.

Après suppression, `IdxPurge` recalcule `diff_indexed_pairs.entry_count` et compacte le fichier via `VACUUM INTO` (dans le même répertoire, évite les problèmes de `/tmp` plein). Si le compactage échoue ou est reporté, les entrées sont quand même supprimées (message `[WARN] compactage impossible` ou `[WARN] compactage reporté : <raison>`) ; relancer `IdxPurge` plus tard, ou la procédure manuelle de LIBRARY.md.

Le compactage laisse la base en mode WAL (1.0.137) et ne remplace plus jamais le fichier sous les processus qui l'ont ouvert (1.0.138) : il est reporté, base intacte, si un Bkp/Restore/Prune est en cours ou démarre, si la base est modifiée pendant la copie, ou si elle reste verrouillée en écriture par un autre processus. Si une base est momentanément verrouillée par un autre processus,
borgHelper affiche `[ERREUR] DB occupée : … réessayer plus tard (ne PAS supprimer le fichier)`. Seul `[ERREUR] DB corrompue : …` invite
à supprimer le fichier pour reconstruire. Supprimée pendant qu'un Index, un Bkp ou borgHelperWWW la tenait encore ouverte,
une `diff.db` ou une `cache.db` ne peut pas être recréée tout de suite : `[ERREUR] DB : … recréée alors qu'un autre processus tenait encore
l'ancienne ouverte` (1.0.169) — attendre la fin de ce processus, puis relancer ; ne rien supprimer de plus.

> **Workflow recommandé :**  
> `IdxTop` → identifier les arborescences volumineuses → ajouter à `IDX_EXCLUDE` dans borghelperrc → `IdxPurge` (sans `-x`) pour purger l'historique existant.

---

### `DiffTop`
Top N arborescences par nombre de changements sur une paire d'archives — diagnostic rapide après un backup.

```bash
borgHelper -c DiffTop -n mon-serveur                         # top 10, profondeur 3, dernière paire indexée
borgHelper -c DiffTop -n mon-serveur -N 5                    # top 5
borgHelper -c DiffTop -n mon-serveur -p 4                    # profondeur 4
borgHelper -c DiffTop -n mon-serveur -b archive-old,archive-new  # paire explicite
borgHelper -c DiffTop -n mon-serveur -j                      # sortie brute, une ligne JSON par chemin
```

| Option | Description |
|--------|-------------|
| `-N <n>` | Nombre de lignes affichées (défaut : 10) |
| `-p <n>` | Profondeur de regroupement (défaut : 3) |
| `-b <old,new>` | Paire d'archives explicite (défaut : dernière paire indexée) |
| `-j` | Sortie brute (Story 1.4) : une ligne `{chemin,type,taille_avant,taille_apres}` par chemin, **sans** regroupement/top-N ni les figures Exclus/Inchangés — `-N`/`-p` sont ignorés dans ce mode. Usage interne (`borgHelperWWW` filtre par périmètre puis regroupe/classe lui-même). |

Colonnes : `total (nb+%)` · `+nb` · `+taille` · `-nb` · `-taille` · `=nb` · `taille`.  
Trié par total. Source : `diff_index` — aucun appel borg, résultat immédiat si la paire est indexée.

Affiche également le total des entrées **exclues** par `IDX_EXCLUDE` pour cette paire, avec détail `+ajoutés · -supprimés · =modifiés` sur la même ligne.

Affiche enfin le nombre de fichiers **inchangés**, calculé depuis les index :

```
Indexés  : 3 200 changements · 450 MB
Exclus   :   800 entrées · 1.2 GB (IDX_* / IdxPurge) — +300 · -50 · =450
Inchangés: 96 000 (97%) sur 99 500 fichiers dans archive-new
```

Calcul : `nfiles_new − added_total − modified_total` (indexés + exclus), en fichiers ordinaires comme `nfiles` : types exacts `added` et `modified` seulement (1.0.156 ; avant, les répertoires ajoutés, liens changés et entrées `ctime` de répertoires indexés étaient aussi retranchés — « Inchangés » sous-estimé, et différent d'IdxTop). Le tableau et le détail des exclus comptent toutes les entrées ; « Inchangés », seulement les fichiers. Mêmes limites qu'IdxTop (fichier dont le ctime change compté modifié, liens physiques, changement de type). Ligne omise si `archive_stats` ne contient pas `nfiles` pour l'archive cible.

---

### `DbEncrypt` / `DbDecrypt`

Chiffre (ou déchiffre) les chemins d'un `diff.db` réel, en place, table par table (`snapshot_file` puis
`diff_index` — `archive_snapshot` n'a pas de colonne `path` propre, rien à y migrer directement), par lots
transactionnels reprenables après interruption. `cache.db` est purgé et recréé directement dans le mode
cible (jamais migré ligne à ligne : c'est un cache, reconstructible par un simple appel borg).

```bash
borgHelper -c DbEncrypt -n mon-serveur -D    # dry-run : tables/lignes/espace, rien changé
borgHelper -c DbEncrypt -n mon-serveur -y    # exécution réelle
borgHelper -c DbDecrypt -n mon-serveur -D    # symétrique
borgHelper -c DbDecrypt -n mon-serveur -y
```

| Option | Description |
|--------|-------------|
| `-D` | Dry-run — rapporte les tables/lignes/espace estimé, ne change rien (1.0.171 : pas même une migration de schéma ; base ancienne lue telle quelle, « ? » pour une table pas encore créée ; base corrompue, occupée ou d'un schéma plus récent : même arrêt qu'avec `-y`. Limite : des trames WAL d'un processus tué sont reportées par SQLite à la fermeture, contenu identique) |
| `-y` | Exécute réellement (convention `IdxPurge` : ni `-D` ni `-y` → refus explicite, rien changé) |

`DbEncrypt` refuse (code de sortie non nul, rien changé) si `DB_ENCRYPT=false` pour ce nick, si une opération
est déjà en cours (`Bkp`/`Restore`/`Report`/`Index`), ou si l'espace disque libre est insuffisant. `DbDecrypt`
n'a pas ce contrôle `DB_ENCRYPT` : déchiffrer reste toujours permis. Une migration interrompue (crash, kill)
reprend automatiquement au point où elle s'est arrêtée au prochain lancement de la **même** commande sur le
même nick — la DEK n'est jamais régénérée, aucune ligne n'est perdue ni dupliquée. Avant le tout dernier
commit, un échantillon de lignes migrées est relu et son aller-retour vérifié ; le commit final n'a lieu
qu'après cette validation.

### `DbRekey`

Ré-enveloppe la DEK existante d'un `diff.db` chiffré avec une nouvelle KEK (nouveau sel, nouveau nonce, `DB_KDF`
courant du nick) — **aucune ligne de donnée n'est touchée** (opération quasi instantanée, même sur une grosse base).

```bash
borgHelper -c DbRekey -n mon-serveur -y
```

Refuse (rien changé) si la base n'est pas déjà `siv1` (rien à re-clé). Ce n'est **pas** un mécanisme de
changement de `BORG_PASSPHRASE` — voir la note sur `DbRekey` plus haut ([Chiffrement des bases](#fichier-de-configuration)).
`borgHelperWWW` ≥ 1.26.4 prend en compte un `DbRekey`, `DbEncrypt` ou `DbDecrypt` exécuté en CLI **sans
redémarrage** (il relit l'en-tête de chiffrement de la base à chaque usage). Versions antérieures : redémarrer son
process — faute de quoi, après un `DbEncrypt`, son cache de périmètre continuait d'écrire ce nick en clair.

### `history.db` : la seule base à sauvegarder (1.0.139)

Chaque nick a trois bases dans `CACHE_DIR` : `cache.db` et `diff.db` se reconstruisent depuis le dépôt borg (on peut
les supprimer), mais `<conf>-<nick>-history.db` garde ce qu'aucun appel borg ne redonne : l'historique des tailles du
dépôt (graphiques, gain de Prune), le suivi des sauvegardes (notifications) et, par archive, les compteurs C/E et la
taille dédupliquée mesurés au Bkp, et (1.0.140) les lignes de graphique figées des archives disparues. Elle est créée
automatiquement à la mise à jour (migration depuis `diff.db`).

- **La sauvegarder** : `CACHE_DIR` (par défaut `~/.cache/borghelper`) est souvent exclu des sauvegardes. Copie cohérente
  (WAL compris) : `python3 -c 'import sqlite3,sys; sqlite3.connect(sys.argv[1]).execute("VACUUM INTO ?",(sys.argv[2],))' <history.db> <copie>`.
- **Pas de retour arrière** : une `diff.db` migrée est refusée par les versions antérieures. Arrêter les anciens
  processus (Bkp, borgHelperWWW) avant la mise à jour ; pour revenir en arrière, restaurer une copie de `diff.db`
  d'avant la mise à jour (les mesures écrites depuis dans `history.db` seront ignorées par l'ancienne version).
- `history.db` est toujours en clair (aucun nom de fichier) ; `RepoHistory` la lit donc même sans passphrase.

### `DbStatus`

```bash
borgHelper -c DbStatus -n mon-serveur
borgHelper -c DbStatus -n ALL
```

Affiche le mode (`plain`/`siv1`/`migrating`) de `cache.db` et de `diff.db` pour chaque nick, puis `history.db`
(toujours `plain` : elle ne contient aucun chemin). Ne lit que
l'en-tête (`db_meta.enc_header`) : aucune passphrase n'est nécessaire pour simplement connaître le mode d'une
base chiffrée. Si une base reste `plain` alors que `DB_ENCRYPT` est actif et qu'une passphrase est
disponible, avertit (comme `_open_db`, une fois par base et par invocation) et cite la commande `DbEncrypt`.
Base inexistante, vide ou sans table : `absent` ; base corrompue, verrouillée ou sans droits : `illisible (<erreur SQLite>)`
(1.0.171, `history.db` comprise). Code de sortie 0 dans tous les cas (affichage d'état).

### `BorgCleanup`

```bash
borgHelper -c BorgCleanup                    # aperçu : rien n'est supprimé
borgHelper -c BorgCleanup -D                 # aperçu explicite (comme IdxPurge -D) ; l'emporte sur -y
borgHelper -c BorgCleanup -y                 # retire entrées borg (sécurité, cache) et fichiers régénérables
borgHelper -c BorgCleanup -y --keys --history   # retire aussi les clés et les historiques mesurés
```

Avec `-y`, confirmation lue sur l'entrée standard : « o » pour supprimer ; avec `--keys` ou `--history`, taper en plus
« oui » (perte définitive). Sans réponse (entrée fermée, cron) : rien supprimé, code 2. Question et bilan comptent en
**éléments** (1.0.162) : une entrée borg (sécurité et cache d'un même dépôt), un fichier borgHelper ; clés et historiques
à part — ex. « Supprimer 9 élément(s) » puis « 9 élément(s) retiré(s) », ou « 2 élément(s) retiré(s) (+ 2 clé(s),
1 historique(s)) ». Une entrée déjà réduite à sa clé (ou à son entrée de dépôt non chiffré) ne compte qu'avec `--keys`.

Restes laissés sur la machine (1.0.160), repérés **sans appel `borg`** et **seulement supprimés par cette commande,
avec `-y`** — jamais par `borgHelperWWW` ni l'interface :

- **borg**, dans le dossier personnel de l'utilisateur qui lance borgHelper (celui qu'utilise borg lancé par
  borgHelper, sans `HOME`) : entrées `~/.config/borg/security/<id>` et caches `~/.cache/borg/<id>` d'un dépôt
  **local** dont le chemin n'existe plus et qu'aucun `BORG_REPO` du rc ne désigne (un disque démonté configuré n'est
  jamais proposé ; un chemin inaccessible compte comme présent ; un dépôt distant, jamais). Les clés
  `~/.config/borg/keys` de ces dépôts (mode keyfile) sont listées à part : **leur suppression est irréversible** (le
  dépôt, s'il existe encore ailleurs, devient illisible) — seulement avec `--keys` ; sans `--keys`, l'entrée qui porte
  l'emplacement du dépôt est gardée avec la clé.
- **borg, ancien dépôt recréé au même chemin** (1.0.161) : entrée d'un dépôt local **présent** (configuré ou non) dont
  l'identifiant n'est plus celui du dépôt qui s'y trouve (`id` de la section `[repository]` de `<dépôt>/config`, lu sans
  borg). Listée à part dans l'aperçu (« disque en rotation ? »), **jamais dans la notice** (deux disques montés tour à
  tour au même chemin la rallumeraient à chaque rotation). Config absente, illisible, sans identifiant valide ou qui ne
  répond pas en 2 s : jamais proposée. L'identifiant est relu juste avant la suppression : ancien disque remis
  entre-temps, dépôt parti ou illisible, gardé. Un disque en rotation chiffré monté à ce chemin retrouve seul son entrée
  et son cache (borg les recrée ; coût : resynchronisation du cache) ; **sa clé (mode keyfile), si elle est retirée
  avec `--keys`, est perdue** : dépôt illisible.
- **Dépôt non chiffré** (1.0.161 ; `key-type` 2 `none`, 6 et 7 `authenticated`) : sans son entrée de sécurité, borg
  lancé sans terminal (cron) **refuse** ce dépôt s'il existe encore (« Do you want to continue? [yN] Aborting », code 2 ;
  mesuré, borg 1.2.6). L'entrée est donc gardée comme une clé : `-y` ne retire que son cache (sans effet mesuré), puis
  elle sort de la notice ; retirée seulement avec `-y --keys` et « oui ».
- **borgHelper**, dans `CACHE_DIR` : bases, `index-last.json` et verrous morts de nicks retirés du rc — seulement si
  **aucun** nick actuel ne les produit (dépôts et `DB_NAME` partagés gardés ; verrou tenu par un processus vivant
  jamais proposé, ni aucun fichier de ce nick tant que le verrou vit). `history.db` (historique mesuré, non
  régénérable) : seulement avec `--history`. rc sans nick ou illisible : rien proposé.

Chaque emplacement et chaque verrou sont revérifiés juste avant la suppression (dépôt réapparu, verrou repris :
gardés). Un chemin inaccessible, ou dont l'état ne répond pas en 2 s (montage réseau bloqué), compte comme présent.
Code 1 si une suppression échoue. `Status`, `Report` (texte, CLI) et l'interface (bandeau sur la page des serveurs)
signalent ces restes ; une entrée réduite à une clé gardée (et à ce qui porte son emplacement) n'y est plus comptée,
mais reste dans l'aperçu.

Variables d'environnement : `BORGHELPERC_CLEANUP_HOME` (autre dossier personnel à scruter ; les selftests y mettent
un dossier vide), `BORGHELPERC_NO_CLEANUP_NOTICE` (pas de notice ; posée par borgHelperWWW pour ses appels).

Limite : un autre rc dont le nom commence par celui-ci et qui partage `CACHE_DIR` verrait ses fichiers proposés — lire
l'aperçu avant `-y`.

---

### `CodecSelfTest`

```bash
borgHelper -c CodecSelfTest
borgHelper -c CodecSelfTest -f 'tranche|surveillance'   # un groupe seulement (1.0.147) : run PARTIEL
borgHelper -c CodecSelfTest -l -f fantôme               # noms des contrôles sélectionnés, rien exécuté
```

**Par groupe** (1.0.147) : `-f <motif>` n'exécute que les contrôles dont le nom correspond (expression régulière, sans
casse). Le bilan l'annonce : « run PARTIEL (filtre …, N contrôle(s) écarté(s)) : le run complet reste exigé avant
commit ». Code de sortie 2 si le motif est invalide, vide ou ne sélectionne rien, 1 si un contrôle échoue. `-l` affiche
les noms sans exécuter les contrôles (seule la préparation des bases temporaires tourne, ~2 s) — pour choisir un motif.
Les contrôles d'un même groupe partagent un dépôt de test que les précédents modifient (archives ajoutées, bases déjà
construites) : viser un groupe entier plutôt qu'un contrôle isolé, et relancer le run complet en cas d'échec — le bilan
le rappelle. Ne jamais lancer deux `CodecSelfTest` en même temps : les contrôles de minutage échouent sous charge.

**Fichiers temporaires** (1.0.151) : en fin de run (même en échec ou filtré, pas avec `-l`), les `_MEI*` (~60 Mo
chacun, dans `/tmp` ou `TMPDIR`) laissés par les borg tués pendant le run sont retirés : seulement ceux apparus pendant
le run, à l'utilisateur courant, utilisés par aucun processus et dont rien (arborescence comprise) n'a changé depuis
10 s (15 s d'attente au plus pour un plus récent). Une ligne
`/tmp/_MEI* : N orphelin(s) du run retiré(s)` le signale ; bilan et code de sortie inchangés.

**Isolation** (1.0.161) : un crochet d'audit Python relève, pendant le run et dans les borgHelper qu'il lance, les
accès aux vrais dossiers de l'utilisateur — `~/.config/borg`, `~/.cache/borg`, `~/.borghelperrc` (jamais lu par le
selftest : tout usage du `CACHE_DIR` d'un vrai rc passe par sa lecture), `~/.cache/borghelper`, dossiers `XDG_*`/`BORG_*`
de borg — par ouverture, liste, création, suppression, renommage, `chmod`/`chown`/`utime`/`truncate`, lien, base
SQLite. Le dernier contrôle, « isolation des selftests », échoue en listant ces accès (fonction et ligne) ; des témoins
(un appel voué à l'échec par évènement et par dossier, dans ce processus et dans un enfant) prouvent à chaque run que
le crochet voit tout ce qu'il doit voir. Non couverts : `stat` et `exists` (pas d'évènement d'audit), copies
`shutil` hors ouverture, borg lui-même (isolé par son wrapper, garde « vrai borg »). Run filtré (`-f`) : le contrôle ne
couvre que les contrôles lancés, et seulement s'il est lui-même sélectionné.

Auto-test du codec de chiffrement des chemins (vecteurs officiels HMAC/PBKDF2/scrypt, aller-retour, rejets
`DbCodecError`/`DbKeyError`/`DbTamperError`, versions de schéma, `DB_ENCRYPT`/`DB_KDF`, permissions) et des requêtes de
chemin : mêmes résultats sur une base `plain` et sur une base chiffrée pour `TreeHist`, `TreeFind`, `Search`, `FileHist`,
`DuIdx`, `IdxTop`, `DiffTop`, `ListBkpFiles`, `IdxPurge` et le périmètre RBAC, plans d'exécution sur les index de chemin.
Vérifie aussi l'écriture (story 3) : aller-retour `store_diff_entries`/`store_archive_snapshot` sur une base chiffrée
temporaire, `DbModeError` levée (et non avalée) quand le mode change sous une transaction ouverte, et qu'un nick jamais
indexé ne crée aucun schéma de base via les commandes de lecture (`ensure_diff_db`/`ensure_cache_db(create=False)`).
Vérifie aussi le cache `cachejsonboexlm` (story 4) : `cacheJsonBoexWithLM` sur un nick dont le `cache.db` est chiffré
— `details` chiffré au repos, hit servi sans second appel borg, ligne altérée traitée comme un cache miss (borg
rappelé) plutôt que comme une exception.
Vérifie enfin la migration (story 5) : `DbEncrypt`/`DbDecrypt` aller simple et aller-retour sur une base temporaire
(chemins et `TreeHist` identiques avant/après), interruption simulée à mi-lots puis reprise (aucune perte ni
duplication), les trois refus (`DB_ENCRYPT=false`, verrou d'opération en cours, espace disque insuffisant simulé),
`DbRekey` (DEK inchangée, enveloppe renouvelée) et son refus sur une base `plain`, et l'avertissement AD-6 émis une
fois par base.
Vérifie enfin (1.0.136), si `borg` est installé, la capture de la taille du dépôt par un Bkp puis un Prune **réels**
sur un dépôt borg jetable. Sans borg, chaque contrôle sur un vrai borg est sauté sous son propre nom (`SKIP`, compté au
bilan ; `-f` le montre, `-l` le liste).
Contrôles sur un vrai borg isolés (1.0.158) : ni le cache, ni la sécurité, ni les clés, ni la configuration borg de
l'utilisateur ne sont touchés, même avec `BORG_CACHE_DIR`, `BORG_SECURITY_DIR`, `BORG_CONFIG_DIR`, `BORG_KEYS_DIR` ou
`BORG_BASE_DIR` exportés (variables `BORG_*` retirées, dossier borg propre à chaque famille de contrôles) ; chaque
contrôle échoue s'il laisse une entrée dans le dossier borg de l'utilisateur. Les runs d'avant 1.0.158 ont pu laisser
des entrées dans `~/.config/borg/security` et `~/.cache/borg` (fichier `location` sous `/tmp/borghelper-selftest-*`) :
sans valeur, supprimables.
Travaille uniquement sur des bases temporaires : aucune vraie base ni aucun vrai rc n'est lu. Une ligne `OK`/`FAIL` par
contrôle ; code de sortie non nul au moindre échec.

---

### `PerfBench`

```bash
borgHelper -c PerfBench
borgHelper -c PerfBench -n 500000
borgHelper -c PerfBench -K
```

Génère un jeu de données synthétique réaliste (`INSERT`/`executemany` directs — jamais de vrai `borg backup`, bien trop
lent pour représenter plusieurs Go) sur des bases temporaires `plain` et chiffrée, puis chronomètre `TreeHist` (racine
et sous-répertoire profond), `TreeFind`, `Search`, `DuIdx -R`, `IdxTop`, `DiffTop`, `_find_last_archive_with_file` et
`IdxPurge -D` dans les deux modes, ainsi que le mémo de décodage (`DbCodec._memo`, passe froide vs mémoïsée). Imprime
un tableau de durées et signale toute mesure dépassant 1 s (seuil de jugement documenté dans TECHNICAL.md).

`-n <taille>` : nombre de lignes `diff_index` visé par mode (défaut 250 000, voir TECHNICAL.md pour la justification
de cet ordre de grandeur). `-K` : ajoute le coût KDF par niveau (`light`/`standard`/`strong`) et une mesure réelle
`DbEncrypt`/`DbDecrypt` — sur un jeu réduit dédié (30 000 lignes) si `-n` n'est pas donné explicitement, pour rester
rapide (« plus lent, optionnel ») ; `-n` donné explicitement (même combiné à `-K`) gouverne aussi cette mesure.

Code de sortie non nul si une mesure a levé une exception (comme `CodecSelfTest`, sinon 0 — y compris quand une
mesure dépasse le seuil de jugement, qui n'est qu'un signal imprimé, pas un échec).

Comme `CodecSelfTest`, travaille uniquement sur des bases temporaires (aucune vraie base ni vrai rc), nettoyées en fin
d'exécution même en cas d'erreur. Chiffres de référence et sites confirmés problématiques : TECHNICAL.md, section
« Mesures PerfBench ».

### `CacheInfo` / `CacheClean`

```bash
borgHelper -c CacheInfo
borgHelper -c CacheInfo -n mon-serveur
borgHelper -c CacheClean
borgHelper -c CacheClean -n mon-serveur
```

`CacheClean` vérifie le `last_modified` courant et supprime les entrées périmées ou pour des nicks absents de la conf.

---

## `borgHelperWWW` — API HTTP

`borgHelperWWW` expose borgHelper en API REST (FastAPI + Swagger). Il s'appuie sur `borgHelper` en
sous-processus (via `python3 borgHelper -C <conf> -c <commande> ...`) — pas d'appel direct aux classes
Python, donc aucun changement de comportement par rapport au CLI.

Toutes les commandes sont exposées **sauf `Mount`/`UMount`** (accès FUSE local, sans objet en HTTP).

### Prérequis

```bash
pip install fastapi uvicorn pydantic
apt install python3-aiohttp python3-requests python3-cryptography  # OPTIONNEL (notifications push,
    # spec-notifications-push) : dépendances de pywebpush, toutes dans les dépôts apt Ubuntu.
    # `cryptography` est en plus importée et utilisée directement par borgHelperWWW (sérialisation de
    # la clé publique VAPID en format X962 non compressé) — pas seulement transitive.
```

`pywebpush`/`py_vapid`/`http_ece` eux-mêmes ne sont des paquets d'aucun dépôt apt (PyPI-only) —
**vendorisés** dans `vendor/` (`spec-push-vendoring`, voir `vendor/README.md`), donc **aucun `pip
install`/venv requis pour eux** : un `git pull` suffit une fois `python3-aiohttp`/`python3-requests`/
`python3-cryptography` installés via apt ci-dessus. Absents (apt non fait) : `borgHelperWWW` démarre
et fonctionne quand même (y compris `/push/subscribe` en CRUD), seul l'envoi push réel est désactivé
(avertissement au démarrage).

`borgHelperWWW.py` (symlink vers `borgHelperWWW`, même principe que `borgHelper.py`) doit être présent
à côté du script : `uvicorn borgHelperWWW:app` importe le module par son nom et échoue sans l'extension
`.py` ("Could not import module"). Inutile pour `python3 borgHelperWWW` en exécution directe.

### Configuration

Quatre façons de configurer, cumulables — par ordre de priorité (la première présente l'emporte) :

1. **Option CLI** (`python3 borgHelperWWW ...` en exécution directe uniquement — sous
   `uvicorn borgHelperWWW:app`, uvicorn possède seul `sys.argv`)
2. **Variable d'environnement** `BORGHELPERWWW_*` (marche dans les deux modes de lancement)
3. **Fichier de conf** `BORGHELPERWWW_CONF` / `--conf` (ini, un seul fichier pour tous les réglages
   ci-dessous — voir [`borghelperwww.conf.example`](borghelperwww.conf.example) ; comble uniquement
   ce qui n'est pas déjà réglé par une option CLI ou une variable d'environnement)
4. **Section `[_borgHelperWWW]` du `.borghelperrc`** dédié à l'API (`-C`/`BORGHELPERWWW_CFGFILE`
   ci-dessous) — dernier repli, même jeu de clés que le fichier de conf ci-dessus (`groups_header`,
   `api_key`, `host`, `port`, etc., en minuscule). Permet un déploiement à **fichier unique** : pas
   besoin de `borghelperwww.conf` séparé si tout tient dans le `.borghelperrc` déjà là pour la CLI.
   Préfixe `_` **réservé** : `borgHelper` (CLI) ignore silencieusement toute section dont le nom
   commence par `_` lors de l'énumération des nicks (`-n ALL`, `Stats` sans argument...) — jamais
   traitée comme un nick réel.

⚠️ **Jamais une clé `BORGHELPERWWW_*` nue dans `[DEFAULT]`** de `.borghelperrc` (ce fichier est lu par
`borgHelper`, CLI, réglages par nick) — silencieusement ignorée par `borgHelperWWW` (aucune erreur).
Piège réel constaté : `BORGHELPERWWW_GROUPS_HEADER` ainsi posé laisse le RBAC désactivé sans le savoir
(accès total pour tout `X-API-Key` valide). `borgHelperWWW` avertit (`[WARN]` au démarrage) si une clé
`BORGHELPERWWW_*` traîne dans `[DEFAULT]` — utiliser `[_borgHelperWWW]` (clés en minuscule, sans
préfixe `BORGHELPERWWW_`, point 4 ci-dessus) à la place.

⚠️ **Un commentaire va toujours sur sa propre ligne**, jamais après une valeur sur la même ligne —
`configparser` ne le coupe jamais (piège réel constaté : une valeur `groups_header` corrompue par un
commentaire collé a fait planter toute requête RBAC). `borgHelperWWW` refuse de démarrer si
`groups_header` n'est pas un nom de header HTTP valide (RFC 7230), plutôt que de planter sur la
première requête — voir `docs/borghelperrc.example`.

| Variable d'environnement | Option CLI | Clé fichier de conf | Rôle |
|---------------------------|------------|----------------------|------|
| `BORGHELPERWWW_CONF` | `--conf` | — | Fichier de conf ini (voir ci-dessus) |
| `BORGHELPERWWW_CFGFILE` | `-C`, `--cfgfile` | `cfgfile` | **Requis** (par un des trois moyens). `.borghelperrc` dédié à l'API (distinct de celui de l'admin CLI) |
| `BORGHELPERWWW_API_KEY` | `-K`, `--api-key` | `api_key` | Clé partagée attendue dans le header `X-API-Key` — absente : **générée aléatoirement** au démarrage (voir ci-dessous) |
| `BORGHELPERWWW_BORGHELPER_BIN` | `--borghelper-bin` | `borghelper_bin` | Chemin du script `borgHelper` (défaut : à côté de `borgHelperWWW`) |
| `BORGHELPERWWW_UI_FILE` | `--ui-file` | `ui_file` | Chemin de `borgHelperWWW_ui.html` (défaut : à côté de `borgHelperWWW`) |
| `BORGHELPERWWW_TIMEOUT` | `--timeout` | `timeout` | Timeout en secondes par commande (défaut 3600 ; 0 = illimité) |
| `BORGHELPERWWW_HOST` | `--host` | `host` | Bind — adresse (défaut `127.0.0.1`) |
| `BORGHELPERWWW_PORT` | `--port` | `port` | Bind — port (défaut `8000`) |
| `BORGHELPERWWW_TRUSTED_PROXIES` | `--trusted-proxies` | `trusted_proxies` | IP/CIDR des reverse proxies de confiance, séparées par des virgules, ou `*` pour toutes (défaut `127.0.0.1`) — IP du navigateur dans le journal des requêtes, dans les deux modes de lancement (voir ci-dessous) |
| `BORGHELPERWWW_ALLOW_DESTRUCTIVE` | `--allow-destructive`, `--no-allow-destructive` | `allow_destructive` | Autorise `Prune`/`DelBkp` (destruction de sauvegardes) — **interdit par défaut** (voir ci-dessous) |
| `BORGHELPERWWW_ALLOW_DOWNLOADS` | `--allow-downloads`, `--no-downloads` | `allow_downloads` | Autorise `/download/file` et `/download/tar` (vue d'une restauration) — **autorisé par défaut** (voir ci-dessous) |
| `BORGHELPERWWW_API_PREFIX` | `--api-prefix` | `api_prefix` | Préfixe de toutes les routes API — défaut `/api` (voir ci-dessous) |
| `BORGHELPERWWW_GROUPS_HEADER` | `--groups-header` | `groups_header` | Header HTTP contenant les groupes de l'utilisateur (reverse proxy OIDC) — absent : **désactivé** (voir ci-dessous) |
| `BORGHELPERWWW_USER_HEADER` | `--user-header` | `user_header` | Header HTTP portant l'email/le nom de l'utilisateur (reverse proxy) — journalisé et enregistré avec les abonnements aux notifications (≥ 1.25.0) |
| `BORGHELPERWWW_REQUIRE_USER` | `--require-user` / `--no-require-user` | `require_user` | Refuse (403) les requêtes sans ce header, sauf `/healthz` — défaut non ; exige `user_header` |
| `BORGHELPERWWW_SCOPE_CACHE_DB` | `--scope-cache-db` | `scope_cache_db` | Chemin du fichier SQLite du cache de réponses **filtrées** par périmètre (Story 1.5) — défaut : co-localisé avec `cache.db`/`diff.db` (voir [Cache de réponses](#cache-de-réponses)) |
| `BORGHELPERWWW_BKP_WATCHER_INTERVAL` | — | — | Intervalle (secondes) d'interrogation `bkp_status` par le watcher — défaut 30 (voir `POST /bkp` asynchrone ci-dessus) |
| `BORGHELPERWWW_PUSH_DISABLED` | — | — | `1` : **suspend l'envoi** de toutes les notifications push (1.27.2) — détection et journal inchangés, `POST /push/test` en `503`, bandeau sur la page Notifications ; lu au démarrage. Par serveur et sans redémarrage : `PUSH_MUTE = true` dans le rc |
| `BORGHELPERWWW_SCHEMA_CHECK_INTERVAL` | — | — | Intervalle (secondes, défaut 3600, min. 60) du contrôle périodique des bases (1.26.6) : structure de la vue `archive_snapshot_v` de chaque serveur, remise à jour si elle diffère ; `[WARN] … redémarrer borgHelperWWW` si borgHelper a été mis à jour sur disque depuis le démarrage (rien n'est alors modifié) |
| `BORGHELPERWWW_BKP_STATUS_TIMEOUT` | — | — | Délai (secondes, ou suffixe `s`/`m`/`h` depuis 1.28.4) avant qu'une sauvegarde démarrée mais jamais terminée soit traitée comme un échec (AD-7) — défaut 21600 (6h). Lu aussi par `borgHelper -c Status` (1.0.154), dans son propre environnement : au-delà, « probablement interrompu ». La clé rc `BKP_STATUS_TIMEOUT` du nick ou de `[DEFAULT]` l'emporte (1.28.4 / 1.0.155) |
| `BORGHELPERWWW_PUSH_DB` | `--push-db` | `push_db` | Chemin du fichier SQLite **dédié** aux clés VAPID et abonnements push (Story 2a, `spec-notifications-push`, AD-6 — jamais `scopecache.db`) — défaut : co-localisé avec `cache.db`/`diff.db` (voir [Notifications push](#notifications-push)) |
| `BORGHELPERWWW_PUSH_PREFS` | `--push-prefs` | `push_prefs` | Fichier **JSON** des préférences de notification par abonné (début/fin, nicks suivis, expiration — `spec-push-ui-prefs-json`), éditable à la main — défaut : à côté de `push.db` (`<prefixe>-push-prefs.json`) |
| `BORGHELPERWWW_PUSH_DEFAULT_EXPIRY_DAYS` | — | — | Durée d'expiration par défaut (jours) d'un abonnement push quand `expires_in_days` est absent de `POST /push/subscribe` — défaut 30, repli sur 30 si valeur invalide/négative |
| `BORGHELPERWWW_PUSH_VAPID_SUB` | — | — | Contact (`vapid_claims['sub']`, ex. `mailto:...`) requis par le protocole Web Push (RFC 8292) pour l'envoi réel (Story 2b) — défaut générique `mailto:admin@example.invalid`, à définir en production. Valeur qui n'est ni `mailto:adresse` ni `https://…` : `[WARN]` au démarrage (1.26.3), les services push la refuseraient |

Le serveur refuse de démarrer si le fichier de conf `.borghelperrc` (`cfgfile`) est absent (aucun des
trois moyens ne l'a fourni). La clé API, elle, n'est **pas requise** : si absente partout,
`borgHelperWWW` en génère une aléatoirement (`secrets.token_urlsafe(32)`) et l'affiche sur **stderr** au
démarrage — pratique en dev/démo, mais cette clé est **perdue au redémarrage** (pas persistée) : pour
une clé stable, la fournir explicitement.

```bash
# Un seul fichier de conf pour tout borgHelperWWW
cp borghelperwww.conf.example /etc/borghelperwww.conf
$EDITOR /etc/borghelperwww.conf          # cfgfile, api_key, host, port, …
python3 borgHelperWWW --conf /etc/borghelperwww.conf
# ou, pour uvicorn externe / systemd (fonctionne aussi en exécution directe) :
export BORGHELPERWWW_CONF=/etc/borghelperwww.conf
uvicorn borgHelperWWW:app --host 0.0.0.0 --port 8000 --workers 2
```

#### Préfixe des routes API

Toutes les routes API métier (voir [Endpoints](#endpoints) ci-dessous) sont montées sous un préfixe
configurable — **`/api` par défaut** (`GET /lstbkp` devient `GET /api/lstbkp`, etc.). Restent
**toujours accessibles sans préfixe**, quel que soit `api_prefix` — c'est la condition pour que la page
web puisse se charger et apprendre ce préfixe avant de savoir où se trouve le reste de l'API :

- `GET /` (la page web elle-même) et ses adresses partageables `GET /serveur/…`, `/explorer/…`,
  `/historique/…`, `/notifications` (même page — voir [Interface web](#interface-web))
- `GET /version` (versions + postures de sécurité, y compris `api_prefix` — la page web lit cette
  valeur au chargement et l'utilise pour tous ses appels API ultérieurs)
- `GET /healthz` (liveness — un superviseur/orchestrateur n'a pas à connaître `api_prefix`)
- `GET /docs`, `GET /openapi.json` (natifs FastAPI — listent automatiquement les routes avec leur
  préfixe effectif)

`BORGHELPERWWW_API_PREFIX`/`--api-prefix`/`api_prefix` accepte une valeur vide ou `/` pour désactiver
le préfixe (routes à la racine, comportement d'avant l'introduction de ce réglage) :

```bash
python3 borgHelperWWW -C /etc/borghelperrc-www --api-prefix /api/v1   # préfixe personnalisé
python3 borgHelperWWW -C /etc/borghelperrc-www --api-prefix ''        # aucun préfixe
```

#### Actions destructrices et téléchargements — postures par défaut

Deux réglages de sécurité au démarrage, affichés sur **stderr** au lancement (avec leur état effectif) :

- **`Prune`/`DelBkp`** (destruction de sauvegardes — irréversible) : **interdits par défaut**
  (`BORGHELPERWWW_ALLOW_DESTRUCTIVE`/`allow_destructive` = `false`). Toute requête `POST /prune` ou
  `DELETE /delbkp` reçoit `403 Forbidden` tant que ce réglage n'est pas explicitement mis à `true`
  (`--allow-destructive`, `BORGHELPERWWW_ALLOW_DESTRUCTIVE=1`, ou `allow_destructive = true` dans le
  fichier de conf). Les autres actions de mutation (`Bkp`, `Index`, `Restore`, `Init`, `IdxPurge`,
  `CacheClean`, `Login`) ne sont **pas** concernées par ce réglage.
- **`/download/file` et `/download/tar`** (téléchargement en vue d'une restauration, streaming
  binaire direct) : **autorisés par défaut** (`BORGHELPERWWW_ALLOW_DOWNLOADS`/`allow_downloads` =
  `true`). Les désactiver (`--no-downloads`, `BORGHELPERWWW_ALLOW_DOWNLOADS=0`, ou
  `allow_downloads = false`) fait répondre `403 Forbidden` à ces deux routes — utile pour une instance
  en lecture seule (rapports/exploration uniquement, aucune extraction de données possible) tout en
  gardant `POST /restore` (écrit sur le disque du serveur borgHelperWWW, pas un téléchargement
  navigateur) inchangé par ce réglage.

Les deux réglages sont indépendants l'un de l'autre et des permissions habituelles (`X-API-Key`,
`X-Borg-Passphrase`) — ils s'y ajoutent, ils ne les remplacent pas.

**`POST /restore` n'a, à ce jour, aucun réglage d'activation/désactivation comparable** à
`BORGHELPERWWW_ALLOW_DESTRUCTIVE` ou `BORGHELPERWWW_ALLOW_DOWNLOADS` : ni l'un ni l'autre des deux
réglages ci-dessus ne le couvre (voir les deux bullets ci-dessus), et il n'existe aucun troisième
réglage dédié. Seuls `X-API-Key`, et — depuis la Story 2.1 — le périmètre de chemin par groupes
(`require_path_in_scope`, voir « Autorisation par groupes » ci-dessous) le protègent.

#### Autorisation par groupes (reverse proxy OIDC/auth_request)

Cas d'usage : un reverse proxy (nginx `auth_request`, oauth2-proxy…) authentifie l'utilisateur par
OIDC et transmet ses groupes dans un header HTTP (ex. `X-Groups: ops-admins,ops-readers`, liste
séparée par des virgules). `borgHelperWWW` peut vérifier ces groupes pour n'autoriser, **par nick**,
que les actions correspondant au niveau d'accès de l'utilisateur — **complémentaire** à `X-API-Key`
(jamais un remplacement : `X-API-Key` reste requis sur toutes les routes, que l'autorisation par
groupes soit activée ou non).

**Désactivée par défaut** — `BORGHELPERWWW_GROUPS_HEADER`/`--groups-header`/`groups_header` absent :
comportement inchangé, seule `X-API-Key` fait foi. Une fois activée (nom du header à lire, ex.
`X-Groups`) :

- Chaque nick porte trois listes de groupes dans son `.borghelperrc` — **`GROUPS_ADMIN`**,
  **`GROUPS_WRITE`**, **`GROUPS_READ`** (comma-séparées, repli sur `[DEFAULT]` comme toute autre
  clef — voir plus haut). **Hiérarchiques** : appartenir à un groupe de `GROUPS_ADMIN` donne aussi
  accès écriture et lecture sur ce nick ; `GROUPS_WRITE` donne aussi accès lecture — pas besoin de
  répéter un même groupe dans les trois listes.
- Chaque route est classée : **lecture** (`Stats`, `LstBkp`, `LstBkpFls`, `Report`, `DiffBkp`,
  `Search`, `FileHist`, `TreeHist`, `TreeFind`, `DuIdx`, `CacheInfo`, `IdxTop`, `DiffTop`,
  `Restore -L`, `/download/file`, `/download/tar`), **écriture** (`Bkp`, `Index`, `Restore`,
  `CacheClean`), **admin** (`Prune`, `DelBkp`, `IdxPurge`, `Init`, `Key`). `Login` est un cas
  particulier : accès admin requis sur le nick visé s'il existe déjà (mise à jour), ou sur la section
  `[DEFAULT]` s'il s'agit d'en créer un nouveau (aucune section propre où lire une politique).
- **Plusieurs nicks en un appel** (`nick=ALL` ou `nick=a,b,c`) : *fail-closed* — la requête entière est
  refusée (`403`, nommant le premier nick en cause) si le niveau requis manque pour **au moins un**
  des nicks visés, jamais de filtrage silencieux d'une partie de la liste.
- Header absent ou vide sur une requête donnée (alors que l'autorisation par groupes est active) :
  aucun groupe ⇒ aucun accès (`403` sur toute route porteuse d'un nick).
- **Interface web — nicks sans aucun droit invisibles** : le comportement *fail-closed* ci-dessus
  refuserait en bloc `GET /report?nick=ALL` (utilisé par la liste des serveurs) dès qu'**un seul** nick
  configuré est inaccessible à l'utilisateur — inutilisable pour un affichage multi-nick. L'interface
  web contourne ceci côté client, sans toucher à la logique *fail-closed* elle-même : elle appelle
  d'abord `GET /access` (voir [Endpoints](#endpoints)), n'envoie ensuite `GET /report` qu'avec la liste
  **explicite** des nicks où elle a un droit de lecture au moins (jamais `nick=ALL`), et affiche « Aucun
  serveur accessible avec vos droits actuels. » si cette liste est vide. Un nick sans aucun droit
  n'apparaît ainsi jamais dans la liste des serveurs ni dans la navigation rapide, exactement comme s'il
  n'existait pas pour cet utilisateur — et reste bien entendu inaccessible en accès direct (la requête
  `403` habituelle, `nick` étant explicite).
- **Badges de sécurité personnalisés** : les trois badges de l'en-tête (voir
  [Endpoints](#endpoints)) sont d'abord calculés à partir des seuls réglages globaux
  `allow_destructive`/`allow_downloads` (avant connexion), puis affinés après connexion avec le
  résultat de `/access` — **🔒 Destructions désactivées** tient compte de l'accès admin réel de
  l'utilisateur (pas seulement `allow_destructive`), **🚫 Téléchargements désactivés** de son accès à au
  moins un nick, et **⚠️ Tout autorisé** exige en plus d'être admin sur la **totalité** des nicks
  configurés — un badge ne minimise donc jamais le niveau de restriction réellement subi par
  l'utilisateur connecté.

**Périmètre de chemin par groupe (`GROUPS_PATHS` / `GROUPS_PATHS_RESTORE`, `spec-groups-paths-restore`)**
: depuis borgHelperWWW 1.18.7, le périmètre de chemin est **scindé lecture/restauration** —
`GROUPS_PATHS` régit la lecture (`Search`/`FileHist`/`TreeHist`/`TreeFind`/`DiffBkp`/`LstBkpFls`/
`DuIdx`/`IdxTop`/`DiffTop`), `GROUPS_PATHS_RESTORE` régit la restauration/téléchargement
(`Restore`/`RestorePerms`/`DownloadFile`/`DownloadTar`) — **même syntaxe exacte** pour les deux clefs.
Un groupe sans entrée dans `GROUPS_PATHS_RESTORE` reprend son entrée `GROUPS_PATHS` (repli **par
groupe**, rétro-compatible : une config qui n'utilise que `GROUPS_PATHS`, comme avant cette scission,
restreint la restauration de la même façon que la lecture). Le reste de cette section décrit
`GROUPS_PATHS` — `GROUPS_PATHS_RESTORE` suit exactement les mêmes règles, sur sa propre clef.

Navigation (borgHelperWWW ≥ 1.19.1) : dans l'arborescence de l'UI (`/treehist`), les répertoires
**parents** d'un périmètre (ex. `opt` et `opt/backups` pour `groupe:/opt/backups/mysql`) restent
affichés, marqués « accès partiel », pour pouvoir descendre jusqu'au périmètre — nom seul, sans
droits/propriétaire/historique, sans téléchargement, et sans aucun de leurs autres enfants. Les autres
commandes (Search/TreeFind/rapports/restauration) restent strictement limitées au périmètre.

**Accès direct par périmètre (borgHelperWWW ≥ 1.20.0)** — pas besoin de donner d'abord un tier
(`GROUPS_ADMIN`/`GROUPS_WRITE`/`GROUPS_READ` = accès à *tout* le nick) puis de le restreindre : un
groupe cité **uniquement** dans `GROUPS_PATHS` et/ou `GROUPS_PATHS_RESTORE` reçoit directement un accès
borné à ses chemins :

| Groupe cité dans | Lire (arborescence, Search/TreeFind, historique, Report...) | Télécharger fichier/`.tar`, consulter les droits |
|---|---|---|
| `GROUPS_PATHS` seul | ses chemins `GROUPS_PATHS` | **non** (aucun repli) |
| `GROUPS_PATHS_RESTORE` seul | ses chemins `GROUPS_PATHS_RESTORE` | ses chemins `GROUPS_PATHS_RESTORE` |
| les deux | union des deux | ses chemins `GROUPS_PATHS_RESTORE` |

Niveau équivalent à la lecture, jamais au-delà : `POST /restore` (écriture sur le disque du serveur),
`Bkp`, `Index`, `Prune`... restent réservés à `GROUPS_WRITE`/`GROUPS_ADMIN`. Comme `GROUPS_READ`, il
voit aussi la liste des archives et les stats globales du dépôt. `GET /access` renvoie `level:"read"`
et un `restore_scope` vide (`[]`) pour un groupe `GROUPS_PATHS` seul ; l'UI masque alors les boutons de
téléchargement (le serveur refuse de toute façon).

Pour un groupe qui **a** un tier, `GROUPS_PATHS` reste un raffinement orthogonal —
il ne fait jamais qu'un nick est accordé, seulement *quelle partie* de ce nick l'est. Un groupe
absent de `GROUPS_PATHS` conserve un accès chemin illimité dans la limite du tier qu'il détient
déjà (comportement rétro-compatible : c'est déjà ce qui se passe aujourd'hui pour un groupe
absent de `GROUPS_ADMIN/WRITE/READ`). Résolution strictement par nick (mêmes conventions que
`_effective_level` : lecture via `cfgread(nick)`, repli natif `[DEFAULT]`), la plus permissive
gagne : si **au moins un** des groupes correspondants de l'appelant (ceux qui lui donnent déjà un
tier sur ce nick) est absent de `GROUPS_PATHS`, le périmètre est **illimité** quels que soient ses
autres groupes ; sinon le périmètre est l'**union** des préfixes de tous ses groupes scopés
correspondants, canonicalisée (`/` final retiré, doublons éliminés, tout préfixe déjà couvert par
un préfixe plus large gardé retiré — la racine `/` absorbe alors tout le reste). Voir
[Fichier de configuration](#fichier-de-configuration) pour la syntaxe exacte de la clef.

Story 1.1 **résout et expose** ce périmètre (voir `GET /access` ci-dessous). Depuis la Story 1.3,
il est aussi **appliqué** — en filtrage a posteriori — sur six des neuf commandes de lecture
concernées : `Search`, `FileHist`, `LstBkpFls`, `DiffBkp`, `TreeHist`, `TreeFind`. Principe : dès
qu'**au moins un** nick de la requête porte un périmètre restreint, `borgHelperWWW` appelle
`borgHelper` en interne avec `-j` (même si le client n'a rien demandé de spécial), retire du JSON
obtenu les lignes/chemins hors périmètre, et répond avec ce JSON — **la réponse devient alors
JSON même sans `?json=true`** (`TreeHist`/`TreeFind`) et même si le client n'a jamais eu la
possibilité de le demander (`Search`/`FileHist`/`LstBkpFls`/`DiffBkp`, qui ne gagnent aucun
paramètre `?json=` dans cette story). `DiffBkp` recalcule en plus `n_add`/`n_rem`/`n_mod` à partir
des entrées filtrées, jamais depuis le compte non filtré. Un appelant **sans aucune restriction**
sur les nicks demandés (admin, ou autorisation par groupes désactivée) ne voit **aucun**
changement de format : texte par défaut, JSON seulement sur demande explicite là où c'était déjà
possible — exactement comme avant cette story.

Depuis la Story 1.4, `DuIdx`/`IdxTop`/`DiffTop` (agrégats disque/top-N par chemin) sont filtrés eux
aussi — mais pas par simple retrait de lignes comme les six commandes ci-dessus : ces trois
commandes **groupent/agrègent déjà** (en Python, voire en SQL pour `DuIdx`) **avant** de produire
leur JSON existant, donc filtrer ce JSON après coup serait incorrect (une frontière de périmètre
peut tomber au milieu d'un groupe déjà constitué). `borgHelper` expose donc, en plus de son mode
groupé existant, un mode **brut** ungroupé, une ligne JSON par chemin — `-R` pour `DuIdx` (dont le
`-j` existant reste le mode groupé historique, inchangé) ; `-j` pour `IdxTop`/`DiffTop`, qui
n'avaient aucun mode JSON avant cette story. Quand l'appelant est scopé, `borgHelperWWW` demande ce
mode brut, retire les lignes hors périmètre, puis **recalcule lui-même** le regroupement/tri/top-N
à partir des lignes filtrées — jamais un total/classement transmis depuis le calcul non filtré puis
partiellement masqué. `DuIdx`/`IdxTop`/`DiffTop` sont traités **mono-nick** pour le périmètre (comme
`LstBkpFls`/`DiffBkp` en Story 1.3) : `nick=ALL`/plusieurs nicks chez un appelant scopé est refusé
(`400`, aucune donnée) plutôt que de tenter un regroupement inter-nicks que cette story ne construit
pas pour ces trois commandes. Les figures « Exclus » (`IDX_EXCLUDE`) et « Inchangés par archive »
(dérivées de `nfiles`, sans colonne de chemin) sont des figures **portant sur le nick entier** — non
scopables correctement — et sont donc **omises** de la réponse pour tout appelant scopé, jamais
approximées. Une paire d'archives (`DiffTop`) sans la moindre ligne dans le périmètre renvoie un
résultat vide (`rows: []`), jamais une erreur. Un appelant sans restriction ne voit, comme pour les
six autres commandes, **aucun** changement de format.

**`Restore`/`Restore -L`/`/download/file`/`/download/tar` (Epic 2, Story 2.1) : garde PRÉ-appel,
jamais un filtrage a posteriori.** Ces quatre routes écrivent sur le disque du serveur
(`POST /restore`) ou streament des octets directement (`/download/*`, qui appellent `borg`
directement, en contournant `borgHelper`) — un filtre après coup serait déjà trop tard, l'action
ayant eu lieu avant qu'un filtre ne puisse s'appliquer. `require_path_in_scope(request, nick, path)`
réutilise telle quelle la même résolution de périmètre (`_resolve_path_scope`/`_path_in_scope`) que
les commandes ci-dessus, mais tranche AVANT tout appel `borg`/`borgHelper` : chemin hors périmètre
⇒ aucun appel n'est fait, jamais.

Sur un chemin hors périmètre, chaque route répond **exactement comme pour un chemin qui n'existe pas** —
**jamais un `403` distinct** : un `403` permettrait à l'appelant de distinguer « hors périmètre » de « n'existe pas »
par le seul code de statut, ce qui confirmerait indirectement qu'un chemin existe quelque part dans l'archive même si
l'appelant n'a pas le droit de le voir (voir [Codes retour](#codes-retour)). Depuis borgHelperWWW 1.27.5, cette réponse
n'est plus une imitation écrite à la main : la **vraie commande** est exécutée sur un **leurre** garanti inexistant (nom
aléatoire, joker conservé si le chemin en contient un), puis le leurre est remplacé par le chemin demandé dans le texte
renvoyé. Résultat identique par construction — texte, code de sortie, contenu téléchargé (vide, ou `.tar` vide),
nom de fichier, **et temps de réponse** — quelles que soient les versions de borg et de borgHelper ; rien n'est
extrait. Auparavant l'imitation avait dérivé : pour un joker, code 1 et « never matched » alors que la vraie réponse
est code 0 sans ce message, et elle était instantanée. Contrôlé par `push_selftest` sur le dépôt de démo (quatre
routes, avec et sans joker).

`GET /download/tar` sans `prefix` (export de l'archive entière) est traité comme hors périmètre pour
tout appelant dont le périmètre résolu ne couvre pas déjà l'ensemble de l'arborescence (`prefix` omis
⇒ chemin racine, `''`, comparé au périmètre comme n'importe quel autre chemin) — un export non borné
ne peut être « dans le périmètre » d'un périmètre qui ne couvre pas tout. Cas particulier : un groupe
explicitement configuré avec `GROUPS_PATHS = groupe:/` (périmètre racine) obtient légitimement
l'export complet — `/` absorbe tout par construction (`_canonicalize_scope`, Story 1.1), c'est
l'équivalent délibéré d'un accès illimité, pas un contournement. Un appelant **sans aucune
restriction** (admin, groupe absent de `GROUPS_PATHS`, ou autorisation par groupes désactivée) ne
voit **aucun** changement — export complet toujours disponible, exactement comme avant cette story.

`Bkp/Index/Prune/DelBkp/Init/Key/IdxPurge/Stats` n'ont pas de notion de sous-chemin et ne sont jamais
concernés.

⚠️ **Chemins stockés sans `/` initial, préfixes `GROUPS_PATHS` avec un `/` initial** : vérifié
contre le dépôt réel (`borg create /lib/modules` stocke des chemins d'archive `lib/modules/...`,
jamais `/lib/modules/...`), alors que `GROUPS_PATHS` s'écrit **avec** un `/` initial (exemple
Story 1.1 : `GROUPS_PATHS = ops-readers:/lib/modules/6.8.0-generic`). La fonction de comparaison
partagée (`_path_in_scope`, AD-7 — segments de chemin complets, jamais sous-chaîne) normalise ce
décalage en retirant le `/` initial des préfixes de périmètre avant de comparer — sans cette
normalisation, toute comparaison scopée échoue silencieusement et un appelant scopé n'obtient
jamais aucun résultat, pour aucun nick (trouvé en investigation d'implémentation, avant tout
déploiement — fail-closed, jamais une fuite, mais un vrai bug fonctionnel).

⚠️ **`GROUPS_PATHS` est relu, et donc revalidé, à chaque appel** — `.borghelperrc` n'est jamais mis
en cache côté config (`cfgread()` relit le fichier depuis le disque à chaque fois). Une valeur
`GROUPS_PATHS` rendue ambiguë (séparateur réservé dans un nom de groupe ou un chemin) **pendant que
le process tourne** échoue donc bruyamment dès le prochain appel qui résout un périmètre pour ce
nick — `500` non catché, jamais une réponse silencieusement dégradée. Depuis 1.20.0 (accès direct
par périmètre), **pour tout appelant** de ce nick, même sans tier : `GROUPS_PATHS` doit être lu pour
savoir s'il y figure. La
validation faite une fois au démarrage (`_validate_groups_paths_startup()`) n'est qu'un fail-fast
pour le cas courant (faute de frappe détectée avant que le service ne serve du trafic), pas le seul
point de contrôle. `GET /access` n'est donc **plus inconditionnellement `200` pour un appel
authentifié qui détient un tier sur le nick concerné** — voir sa propre description plus bas.

⚠️ Le header n'est vérifié que pour sa **valeur**, jamais pour sa **provenance** — ce mécanisme
suppose que `borgHelperWWW` n'est atteignable **que** via le reverse proxy de confiance qui pose ce
header (bind sur `127.0.0.1` + reverse proxy sur la même machine, ou pare-feu équivalent), exactement
la même hypothèse que pour `X-Forwarded-For` (voir section suivante). Un accès direct au port de
`borgHelperWWW`, en contournant le reverse proxy, permettrait de forger n'importe quelle valeur de ce
header.

`GET /version` renvoie `groups_auth_enabled` (booléen — jamais le nom du header ni les groupes eux-mêmes).

#### Derrière un reverse proxy — IP du navigateur et utilisateur dans les logs

**Journal des requêtes** (borgHelperWWW ≥ 1.25.0) : une ligne par requête sur stderr, produite par
borgHelperWWW lui-même (plus le journal d'accès d'uvicorn, désactivé en exécution directe) :

```
[req] 203.0.113.9 alice@example.org "POST /api/login?servername=x&repo=y&repo_passphrase=***" 200 213ms
       │           │                  │                                                         │   └ durée
       │           │                  └ requête — paramètres sensibles masqués (passphrase, clé, secret, token)
       │           └ utilisateur (header BORGHELPERWWW_USER_HEADER), « - » si absent/non configuré
       └ IP du navigateur
```

**IP du navigateur** : si la connexion vient d'un reverse proxy listé dans
`BORGHELPERWWW_TRUSTED_PROXIES` / `--trusted-proxies` / `trusted_proxies` (IP ou CIDR séparés par des
virgules, `*` = toutes ; défaut `127.0.0.1`, proxy sur la même machine), l'IP journalisée est lue dans
`X-Forwarded-For`, parcouru de droite à gauche en sautant les proxies de confiance : la première IP non
fiable est le navigateur (jamais la plus à gauche d'emblée, qu'un client peut forger). Une connexion qui
ne vient pas d'un proxy de confiance est journalisée avec son IP réelle, `X-Forwarded-For` ignoré.
Élargir `trusted_proxies` à l'IP réelle du reverse proxy s'il n'écoute pas sur `127.0.0.1` (conteneur,
load-balancer distant…) ; `*` à réserver aux réseaux fermés. **Même comportement dans les deux modes de
lancement** : ce réglage est lu par borgHelperWWW lui-même, y compris sous `uvicorn borgHelperWWW:app`
(avant 1.25.0 il était sans effet dans ce mode). Sous uvicorn externe, ajouter `--no-access-log` pour ne
pas doubler chaque ligne avec le journal d'uvicorn.

```bash
# reverse proxy sur un hôte distinct (10.0.0.5)
BORGHELPERWWW_TRUSTED_PROXIES=10.0.0.5 uvicorn borgHelperWWW:app --host 0.0.0.0 --port 8000 --workers 2 --no-access-log
```

**Identité de l'utilisateur** : `BORGHELPERWWW_USER_HEADER` / `--user-header` / `user_header` = nom du
header dans lequel le reverse proxy (OIDC, `auth_request`…) transmet l'email ou le nom de l'utilisateur
(ex. `X-Email`, `X-Forwarded-User`). S'il est configuré et présent, sa valeur est journalisée avec chaque
requête et enregistrée avec les abonnements aux notifications (champ `user` du fichier JSON des
préférences, mis à jour à chaque abonnement ou modification, conservé si le header manque) — pour savoir
qui reçoit quoi et accompagner les utilisateurs. Caractères de contrôle retirés, 256 caractères max.
`BORGHELPERWWW_REQUIRE_USER` / `--require-user` / `require_user = true` : **refuse (403)** toute requête
sans ce header (sauf `/healthz`, pour la supervision) ; exige `user_header` (sinon borgHelperWWW refuse
de démarrer). ⚠️ Comme `groups_header` : le reverse proxy doit être la seule voie d'accès et **écraser**
tout header de même nom envoyé par le navigateur — sinon n'importe qui peut s'attribuer une identité.
C'est une identification, pas une authentification (qui reste `X-API-Key` + groupes).

Détail de la résolution : voir [TECHNICAL.md](TECHNICAL.md), section « borgHelperWWW — IP client réelle
derrière un reverse proxy ».

- **`uvicorn borgHelperWWW:app`** : uvicorn importe le module et possède seul `sys.argv` — seules les
  variables d'environnement sont lues, pas d'options CLI possibles ici.
- **`python3 borgHelperWWW ...`** : les options CLI ci-dessus sont prioritaires sur les variables
  d'environnement déjà présentes.

### Lancement

```bash
# Via options CLI (exécution directe uniquement)
python3 borgHelperWWW -C /etc/borghelperrc-www -K "$(openssl rand -hex 32)" --host 0.0.0.0 --port 8000

# Via variables d'environnement (marche dans les deux modes)
export BORGHELPERWWW_CFGFILE=/etc/borghelperrc-www
export BORGHELPERWWW_API_KEY=$(openssl rand -hex 32)
python3 borgHelperWWW                      # dev, uvicorn intégré
# ou en prod :
uvicorn borgHelperWWW:app --host 0.0.0.0 --port 8000 --workers 2
```

Swagger interactif : `http://<host>:<port>/docs` — également accessible via un lien dans le pied de
page de l'interface web (visible sur toutes les pages, y compris la page de connexion).

### Interface web

`http://<host>:<port>/` — page unique (SPA, HTML/CSS/JS vanilla, aucune dépendance externe, servie par
`borgHelperWWW_ui.html`, obligatoirement à côté du script). Titre **borgHelperWWW**, lien vers `/`,
répété dans l'en-tête et le pied de page — visible sur toutes les pages.

1. **Connexion** : saisie de la clé `X-API-Key`. Vérifiée par un appel `Report` hors-ligne ; conservée en
   `sessionStorage` (effacée à la fermeture de l'onglet, jamais persistée sur disque). Bouton
   **Serveurs** dans l'en-tête (à côté de **Déconnexion**), visible sur toutes les pages sauf
   Connexion et Serveurs elle-même, pour revenir directement à la liste des serveurs.
2. **Serveurs** : liste des nicks avec un rapport sommaire hors-ligne (aucune passphrase requise pour
   cette liste — lecture SQLite uniquement). Ligne de **liens rapides** au-dessus de la liste (un par
   serveur) : clic → défilement direct vers la carte de ce serveur (utile quand la liste est longue).
   Nom en **rouge** (lien ET titre de la carte) si `Report` remonte une erreur pour ce serveur (`nom`
   préfixé par `***` — diff.db absent, dernière sauvegarde plus ancienne que `MAX_AGE_BKP`, ou erreur
   SQLite). Bouton **+ Nouveau serveur** pour `Login`. Pas de saisie de
   passphrase sur cette page — juste un badge indiquant si elle est déjà enregistrée pour la session ou
   non ; à renseigner sur la page du serveur concerné. Bouton **▶ Backup** sur chaque carte serveur pour
   lancer un `Bkp` immédiat (confirmation avant lancement ; utilise la passphrase de session si
   enregistrée, sinon celle du `.borghelperrc` si présente — avertissement sinon) ; la liste se
   rafraîchit automatiquement une fois terminé. Bouton **🗂 Explorer** juste à côté pour accéder
   directement à l'explorateur d'arborescence de ce serveur, sans passer par la page de détail.
   Tableau des **10 dernières sauvegardes** (durée, taille originale, Δ taille, compressée,
   dédupliquée, nb fichiers, modifications) affiché **automatiquement** sous chaque carte — `Report -o
   -N 10 -j` hors-ligne, aucune passphrase requise, chargé au rendu de la liste, aucun clic requis.
   Bouton **📜 Historique complet** juste à côté pour ouvrir la vue Historique (point 5) de ce serveur.
   Badge **🔓 base non chiffrée** (UI ≥ 1.17.0) sur la carte et la page d'un serveur dont une base (`diff.db`,
   `cache.db`) est restée en clair alors que `DB_ENCRYPT` est actif et qu'une passphrase est disponible — noms de
   fichiers en clair sur disque ; la bulle donne la commande `DbEncrypt`. Aucun badge pour une base chiffrée ni pour
   `DB_ENCRYPT=false` volontaire. Source : champ `db_plain` de `GET /access`.
   Bandeau **🧹 Nettoyage possible sur le serveur** (UI ≥ 1.19.5) quand la machine garde des restes de dépôts borg
   disparus ou de nicks retirés : nombres et tailles seulement, avec la commande `borgHelper -c BorgCleanup` —
   l'interface ne supprime rien. Source : champ `borg_cleanup` de `GET /access` (borgHelperWWW ≥ 1.28.5 ; `null` s'il
   n'y a rien, ou pour un appelant sans droit admin quand les groupes sont actifs ; recalculé au plus toutes les 5 min ;
   masqué si `/access` échoue).
3. **Détail d'un serveur** : champ **BORG_PASSPHRASE** à enregistrer pour la session (`sessionStorage`,
   par nick) — c'est ici, et seulement ici, qu'elle se saisit. Envoyée en `X-Borg-Passphrase` pour les
   actions qui en ont besoin (repérées par 🔑) ; les actions destructives (`Prune`, `DelBkp`, `Restore`,
   `IdxPurge`, `Init`) demandent une confirmation avant exécution. Le résultat brut (`exitcode`, `stdout`,
   `stderr`) s'affiche tel quel. Bouton **🗂 Explorer l'arborescence** dans le bandeau du serveur.
   En haut de cette page, de l'explorateur et de l'Historique complet (UI ≥ 1.13.4), une étiquette
   **🖥 nom du serveur** rappelle le serveur en cours ; retour à la liste par le bouton **Serveurs** de
   l'en-tête (plus de bouton « ← Serveurs » / « ← Retour au serveur »).
4. **Explorateur d'arborescence** (`TreeHist -j`) : navigation façon gestionnaire de fichiers. Colonnes
   **Droits** (ls-style, `drwxr-xr-x`…) et **Propriétaire** (`user:group (uid:gid)`) affichées pour
   chaque entrée — dernier état connu. Chaque navigation (clic sur un dossier, sur le fil d'Ariane, sur
   Explorer) affiche une **animation de chargement** le temps de la réponse ; un numéro de séquence
   protège contre l'API lente : une réponse arrivée après qu'une navigation plus récente a eu lieu est
   **ignorée** (jamais affichée), pour ne jamais montrer le contenu d'un autre répertoire ou d'un autre
   serveur que celui affiché à l'écran. Même protection sur la liste des serveurs et sur l'Historique
   complet.
   - **Fichiers/répertoires supprimés** : listés eux aussi (badge « supprimé »), tant qu'ils restent
     récupérables. Cliquer sur un fichier supprimé, ou en télécharger un depuis la recherche, ouvre la
     fenêtre de téléchargement avec l'archive de dernière présence **présélectionnée** (plutôt que
     « dernière archive », qui échouerait — le fichier n'y est plus). Un dossier entièrement supprimé
     reste explorable normalement (son ancien contenu s'affiche).
   - **Clic sur un dossier** : l'ouvre (contenu direct, comme `TreeHist -f <dossier>`).
   - **Notice « Droits et propriétaire »** sous l'explorateur (UI ≥ 1.16.1), visible dans tous les modes :
     ils montrent le dernier état connu (plus récente sauvegarde indexée contenant l'entrée), pas forcément celui de
     la sauvegarde épinglée ou comparée ; inconnus (—) pour une entrée supprimée ; droits exacts d'une sauvegarde
     donnée : téléchargement `.tar` « préserve les droits d'accès ».
   - **Affichage « Changements entre deux sauvegardes »** (UI ≥ 1.16.0) : sélecteur au-dessus de la liste, puis deux
     listes d'archives — « Depuis » (état de départ, exclue) et « Jusqu'à » (incluse). Seules les entrées ajoutées,
     modifiées ou supprimées entre les deux s'affichent (`TreeHist -X`) ; un dossier apparaît dès qu'un changement a
     eu lieu en dessous, et on y descend en restant dans ce mode. Par défaut : de l'avant-dernière à la dernière
     sauvegarde. Raccourci : bouton **🔀 Changements** de l'Historique complet (depuis la sauvegarde précédente jusqu'à
     celle-là). Téléchargement d'une entrée supprimée : archive de dernière présence présélectionnée.
   - **Clic droit sur un dossier** : télécharge un `.tar` de cette arborescence, à une archive
     choisissable dans une liste déroulante (`borg export-tar`, streamé directement au navigateur).
   - **Clic sur un fichier** : le télécharge, à une archive choisissable (streamé directement, jamais
     écrit sur le disque du serveur borgHelperWWW). Deux formats au choix : **brut** (`borg extract
     --stdout`, par défaut — contenu seul, pas de métadonnées) ou **.tar** (case à cocher « préserve les
     droits d'accès » — `borg export-tar` sur ce seul fichier, conserve mode/propriétaire/date comme dans
     l'archive borg). La liste déroulante ne propose **que les archives où ce fichier a réellement
     changé** (`added`/`modified` — `removed` exclu, `TreeHist -j -b ALL` sur son historique complet),
     pas toutes les archives du dépôt.
   - Sans archive choisie : la dernière disponible. Le `.tar` d'un dossier (clic droit), lui, propose
     toutes les archives — un instantané complet n'a pas de notion de « mouvement » à filtrer.
   - **Commande `borgHelper` équivalente** affichée systématiquement dans la fenêtre de téléchargement
     (fichier ou dossier, brut ou tar) : `Restore -n <nick> -f <chemin> -w <destination> [-b <archive>]`
     — extraction disque classique avec droits préservés (`borg extract` réel, contrairement au
     téléchargement brut navigateur) ; mise à jour en direct selon l'archive sélectionnée.
   - **Recherche** (`TreeFind -j`) : champ texte au-dessus du tableau — recherche **récursive par nom**
     à partir du répertoire actuellement affiché (motif minimal `*`/`.`, comme la commande CLI ;
     Entrée ou bouton **🔍 Rechercher** pour lancer). Résultats en liste (chemin complet, droits,
     propriétaire), chacun avec un bouton **📂 Aller au dossier** (navigue directement dans
     l'explorateur — le répertoire lui-même pour un dossier trouvé, son parent pour un fichier) et un
     bouton **⬇ Télécharger** (même fenêtre de téléchargement que ci-dessus). Bouton **✕ Revenir à
     l'explorateur** pour effacer la recherche ; toute navigation normale (dossier, fil d'Ariane)
     l'efface aussi automatiquement.
5. **Historique complet** (bouton **📜 Historique complet** sur la page Serveurs) : toutes les archives
   indexées en base pour ce serveur (`Report -o -j`, sans limite `-N`), mêmes colonnes que le tableau
   des 10 dernières, plus une colonne **Actions** par archive :
   - **🗂 Explorer** : ouvre l'explorateur d'arborescence (point 4) **épinglé sur cette archive** —
     seuls les événements propres à cette sauvegarde sont affichés (`TreeHist -b <archive> -B
     <archive>`), pas ceux des autres archives. Les colonnes droits/genre/propriétaire restent, comme
     toujours, le **dernier état connu** (pas forcément celui de cette archive précise — limitation
     documentée de `TreeHist`).
   - **🗑 Supprimer** (`DelBkp`) : supprime définitivement cette archive — confirmation, 🔑 passphrase.
   - Bouton **⚡ Lancer Prune** en haut de la vue (portée sur tout le dépôt, pas une archive précise,
     selon `KEEP_*` de la conf) — confirmation, 🔑 passphrase.
   - Au-dessus du tableau (UI ≥ 1.12.1), une carte **Évolution** avec trois graphiques Chart.js
     (chargés via `/repohistory`/`/archivehistory`) : taille du dépôt dans le temps
     (`unique_csize`/`total_size`/`total_csize`, un point par Bkp, Prune ou Index), gain Prune (delta
     calculé côté navigateur, jamais stocké), métriques par archive dans le temps
     (`original_size`/`compressed_size`/`deduplicated_size` — cliquer sur `original_size` et `compressed_size`
     dans la légende les masque et recadre l'axe sur la taille dédupliquée), et — UI ≥ 1.13.0 — deux graphiques
     par archive : **fichiers modifiés** (barres empilées ajoutés/modifiés/supprimés), **durée de
     sauvegarde** (UI 1.19.4 : le bargraphe « taille dédupliquée par archive », doublon de la courbe
     précédente, est retiré). Une archive sans valeur reste vide, jamais comptée à
     zéro. UI ≥ 1.18.0 (borgHelper ≥ 1.0.140) : les archives supprimées du dépôt restent dans ces
     graphiques par archive pendant `STATS_RETENTION_MONTHS`, atténuées, infobulle « (supprimée) ». Nick sans historique ou sans Prune :
     message à la place du graphique concerné — un `Index` complète les données manquantes.
     **Chart.js embarqué** (borgHelperWWW ≥ 1.22.0) : copie locale `vendor/chartjs/`, servie par
     borgHelperWWW sur `/static/chart.umd.min.js` — aucun accès Internet requis côté navigateur. Si
     elle est absente du déploiement (`[WARN]` au démarrage), l'UI se replie sur le CDN
     (`cdn.jsdelivr.net`) ; ni l'une ni l'autre : message à la place des graphiques, le reste de la
     page reste fonctionnel. Même empreinte d'intégrité (SRI) vérifiée dans les deux cas.

**Icône du site** (borgHelperWWW ≥ 1.22.0) : un fichier `favicon.ico` posé à côté de
`borgHelperWWW_ui.html` (sinon à côté de `borgHelperWWW`) est servi sur `/favicon.ico`, sans clé API —
pris en compte immédiatement, sans redémarrage. Absent : `404`, comme avant.

**Adresses partageables** (borgHelperWWW ≥ 1.26.0, UI ≥ 1.14.0) : l'adresse du navigateur suit la page
affichée — on peut la recharger, utiliser Précédent/Suivant, ou l'envoyer à un collègue pour lui
montrer exactement ce dont on parle.

| Adresse | Page |
|---|---|
| `/` | Liste des serveurs |
| `/serveur/<nick>` | Détail d'un serveur |
| `/explorer/<nick>` | Explorateur, racine |
| `/explorer/<nick>/<chemin…>` | Explorateur, répertoire `<chemin>` |
| `/explorer/<nick>/<chemin…>?archive=<nom>` | Explorateur épinglé sur une archive (depuis l'Historique) |
| `/explorer/<nick>/<chemin…>?depuis=<A>&jusqua=<B>` | Explorateur, changements entre deux sauvegardes (UI ≥ 1.16.0) |
| `/historique/<nick>` | Historique complet |
| `/notifications` | Réglages des notifications |

- Bouton **🔗 Copier le lien** à côté de l'étiquette du serveur (détail, explorateur, historique) :
  copie l'adresse dans le presse-papier (« ✅ Lien copié ») ; si le navigateur le refuse (page en HTTP
  hors `localhost`…), l'adresse s'affiche dans une fenêtre pour être copiée à la main.
- **Le lien ne dispense pas de se connecter** : la clé API reste par onglet. Sans session, la page de
  connexion s'affiche puis, une fois connecté, la page visée — l'adresse est conservée entre-temps.
- **Le lien n'accorde aucun droit** : ceux du destinataire s'appliquent (`GROUPS_*`, `GROUPS_PATHS`). Un
  serveur inconnu ou hors de ses droits renvoie à la liste avec le même message dans les deux cas —
  « Serveur inconnu ou inaccessible avec vos droits : `<nick>` » — sans révéler si ce serveur existe.
- Adresse inconnue (`/xyz`, `/explorer` sans serveur…) ouverte dans un navigateur : liste des serveurs,
  adresse remplacée par `/`. Un client API (curl…) reçoit toujours le `404` JSON habituel.
- **Titre de l'onglet** (UI ≥ 1.15.0) propre à chaque page, le plus précis d'abord — `🖥 <nick>`,
  `🗂 <nick>:/<chemin> [@ <archive>]`, `📜 <nick> — Historique`, `Serveurs`, `🔔 Notifications`,
  `Connexion` (suivi de « — borgHelperWWW ») : onglets, favoris et menu de Précédent/Suivant
  distinguent les pages.
- Non reflétés dans l'adresse : la recherche de l'explorateur et l'action ouverte dans la page détail.
- L'interface doit être publiée à la racine du site (pas sous un sous-chemin `https://host/borg/…`).
- Test de l'UI (Node, sans dépendance) : `node borgHelperWWW_ui_test.js` — routeur, badges, fin de Bkp, actions et
  graphiques de la page Historique (tous construits, séries de la courbe des tailles, archives supprimées atténuées,
  message sans données, bloc HTML de chaque graphique, chargements qui se croisent, rechargement, réponses en erreur,
  bibliothèque absente). À lancer après toute modification de ces parties de
  `borgHelperWWW_ui.html`. Inutile au déploiement.

Cette page HTML elle-même n'est pas protégée par `X-API-Key` (elle ne contient aucun secret — la clé et
les passphrases ne sont saisies et envoyées que depuis le navigateur, via `fetch()`) ; c'est l'API qui
reste la seule frontière de sécurité. En conséquence, servir `borgHelperWWW` derrière HTTPS est fortement
recommandé dès que le navigateur n'est pas sur `localhost` : la clé API et les passphrases transitent en
clair sur le réseau sinon.

### Authentification et passphrase

- **`X-API-Key`** (header, requis sur tous les endpoints) — protège l'accès à l'API elle-même. Sans
  cette clé, n'importe qui pourrait déclencher `Prune`/`DelBkp`/`Restore` sur les dépôts configurés.
- **`X-Borg-Passphrase`** (header, optionnel) — complète ou supplante `BORG_PASSPHRASE` du
  `.borghelperrc` pour cet appel uniquement (équivalent HTTP de `-P` / `BORGHELPERC_RUNTIME_PASSPHRASE`).
  Permet de garder le `.borghelperrc` de l'API **sans passphrase en clair** : chaque appelant fournit
  la sienne à la demande.
- **`Login`** est un cas à part : il **écrit** la passphrase fournie (`repo_passphrase`) en clair dans
  `BORGHELPERWWW_CFGFILE` (c'est son rôle : déclarer un nouveau dépôt). À réserver au provisioning.

### Endpoints

Un endpoint par commande CLI, sauf `BorgCleanup` (suppression en ligne de commande seulement) (voir [Commandes](#commandes) ci-dessus pour le détail de chaque
comportement) — `GET` pour les commandes en lecture, `POST`/`DELETE` pour celles qui modifient un état.
Toutes les routes du tableau ci-dessous sont montées sous `api_prefix` (`/api` par défaut — voir
[Configuration](#configuration)) : `GET /lstbkp` du tableau signifie concrètement
`GET /api/lstbkp` avec le préfixe par défaut.

Exception : `GET /version` n'exécute aucune commande, n'est **jamais préfixé** (comme `/`, `/healthz`,
`/docs`, `/openapi.json` — voir [Préfixe des routes API](#configuration)), et renvoie les versions de
`borgHelperWWW` (`WWW_VERSION`, constante interne), de `borgHelper` (`Version`, importée) et de
`borgHelperWWW_ui.html` (`UI_VERSION`, extraite par regex du commentaire `<!-- UI_VERSION: X.Y.Z -->`
en tête du fichier HTML), ainsi que les postures de sécurité `allow_destructive`/`allow_downloads` et
le préfixe effectif `api_prefix` — tout **chargé une fois au démarrage du processus**. Comme `/`,
volontairement **non protégé** par `X-API-Key` (aucune donnée sensible) — affiché dans le pied de page
de l'interface web (versions), et via trois badges dans l'en-tête (visibles même avant connexion) :
**🔒 Destructions désactivées** quand `allow_destructive` est à `false` (le défaut) ;
**🚫 Téléchargements désactivés** quand `allow_downloads` est à `false` (non défaut — signale un
réglage explicitement restrictif) ; **⚠️ Tout autorisé** quand `allow_destructive` **et**
`allow_downloads` sont tous les deux à `true` (aucune restriction — rappel qu'aucune protection n'est
active sur cette instance). Affichage initial, **global** (avant connexion) ; une fois connecté et si
l'autorisation par groupes est active, ces trois badges sont affinés d'après les droits personnels de
l'utilisateur — voir [Autorisation par groupes](#autorisation-par-groupes-reverse-proxy-oidcauth_request).

Quand une action est interdite côté serveur, le bouton correspondant **n'apparaît tout simplement
pas** dans l'interface web (plutôt qu'un bouton visible qui échouerait en `403`) :
`allow_destructive=false` retire **⚡ Purger les vieux backups (Prune)** et **⚡ Supprimer une archive
(DelBkp)** de la liste d'actions de la page Détail, le bouton **⚡ Lancer Prune** et les boutons
**🗑 Supprimer** par archive de la vue Historique complet ; `allow_downloads=false` retire le bouton
**⬇ Télécharger** des résultats de recherche de l'explorateur et masque le bouton de confirmation de la
fenêtre de téléchargement (remplacé par un message explicite — la fenêtre reste accessible en clic sur
un fichier/clic droit sur un dossier, mais aucun téléchargement n'y est possible).

`GET /healthz` : liveness check pour orchestrateurs/superviseurs (Kubernetes, Docker, systemd,
load-balancer…) — répond `{"status":"ok"}` (HTTP 200) dès que le processus tourne, sans toucher à
`borg`/aux bases SQLite ni exécuter `borgHelper`. Non protégé par `X-API-Key`. Vérifie uniquement que le
processus **répond** (liveness), pas que les dépôts/DB sont accessibles (pas de readiness check) — pour
ça, `GET /cacheinfo` ou `GET /lstbkp` (protégés, nécessitent la clé API).

#### Cache de réponses

Les endpoints marqués **✓** dans la colonne Cache ci-dessous ne lisent (ou n'écrivent, pour `DiffBkp`
lors de son tout premier appel sur une paire non indexée) que `cache.db`/`diff.db` — jamais l'état live
du dépôt
indépendamment de ces fichiers. `borgHelperWWW` retient leur dernière réponse en mémoire, avec une
empreinte = date de modification de tous les `cache.db`/`diff.db`/`history.db` concernés (tous les nicks connus si
le nick demandé est vide ou `ALL`). Un appel identique est servi depuis le cache **sans relancer
`borgHelper`** tant que cette empreinte n'a pas changé ; dès qu'un `Bkp`/`Index`/`Prune`/`DelBkp`/… a
modifié ces fichiers, l'empreinte change et l'appel suivant recalcule (et remet en cache) une réponse
fraîche. Cache en mémoire du processus (perdu au redémarrage), sans limite de durée mais borné à 500
entrées (purge totale au-delà, garde-fou anti-croissance illimitée). `GET /report` n'est concerné qu'en
mode `offline=true` (le mode en ligne interroge le dépôt en direct via `borg info`, non couvert par
cette empreinte). Depuis borgHelperWWW 1.28.8, seules les réponses en code 0 ou 1 (alerte tirée des bases : diff.db
absent, sauvegarde trop ancienne) sont mises en cache : un code >= 2 (« ⚠ dépôt absent », coupure ssh…) dépend d'un état
extérieur aux bases et serait resservi après remontage — il est recalculé à chaque appel.

⚠️ **Périmètre de chemin actif ⇒ jamais servi depuis `_RESPONSE_CACHE`** (Story 1.3, étendu Story
1.4) : pour `/search`, `/filehist`, `/lstbkpfls`, `/diffbkp`, `/treehist`, `/treefind`, `/duidx`,
`/idxtop`, `/difftop`, dès qu'**au moins un** nick de la requête porte un périmètre restreint
(`GROUPS_PATHS`), l'appel contourne entièrement `_RESPONSE_CACHE` — ni lu, ni écrit — et relance
`borgHelper` **sauf** hit du cache dédié décrit ci-dessous. Seul le cas entièrement non restreint
(autorisation par groupes désactivée, ou appelant sans aucun périmètre sur tous les nicks demandés)
continue d'utiliser `_RESPONSE_CACHE`, exactement comme avant ces stories.

**Cache SQLite dédié aux réponses filtrées par périmètre (Story 1.5)** : un second fichier SQLite,
distinct de `cache.db`/`diff.db` (réglage `BORGHELPERWWW_SCOPE_CACHE_DB`/`--scope-cache-db`, défaut
co-localisé avec eux — voir [Configuration](#configuration)), stocke le résultat **déjà filtré**
pour chaque `(nick, commande, paramètres, périmètre)` — une ligne **par nick réel**, même pour une
requête multi-nick (`Search`/`FileHist`/`TreeHist`/`TreeFind`) : deux nicks scopés différemment dans
la même requête ne partagent jamais une ligne. Empreinte d'invalidation capturée **avant** la
résolution du périmètre (mtimes `cache.db`/`diff.db`/`history.db` du nick **et** mtime de `.borghelperrc` lui-même
— un `GROUPS_PATHS` resserré/relâché invalide donc le cache sans attendre une nouvelle sauvegarde) ;
un appel identique est servi sans relancer `borgHelper` tant que cette empreinte n'a pas changé. Pour
les quatre routes multi-nick, un hit **partiel** (certains nicks en cache, d'autres non) relance
l'appel combiné existant pour **tous** les nicks demandés (comportement Story 1.3/1.4 inchangé) puis
rafraîchit chaque fragment ; seul un hit **complet** (tous les nicks) évite l'appel `borgHelper`.
Même garde-fou anti-croissance que `_RESPONSE_CACHE` (purge totale au-delà de 500 lignes, pas de LRU).
Fichier auto-créé au premier démarrage (`db_meta`/`schema_version`, même convention que
`cache.db`/`diff.db` — échec bruyant si la DB est corrompue ou d'un schéma plus récent que celui
attendu).

Ce cache dépend d'un correctif appliqué à `borgHelper` lui-même (Story 1.5) : `_check_set_meta()`
n'écrit désormais `db_meta` (`schema_version`/`borghelper_version`) que si la valeur stockée diffère
réellement, et `ensure_diff_db()` ne recrée la vue `archive_snapshot_v` que si elle n'existe pas déjà
— sans ces deux correctifs, `cache.db`/`diff.db` voyaient leur date de modification avancer à **chaque**
appel, même en lecture pure sans le moindre changement de données (chaque appel `borgHelper` étant un
sous-processus séparé, la fermeture de connexion SQLite déclenche un checkpoint WAL qui touche le
fichier), ce qui aurait invalidé le cache par périmètre à chaque requête et l'aurait rendu quasiment
inopérant en pratique. Comportement CLI/format de sortie de `borgHelper` inchangés par ces deux
correctifs — seule la date de modification des fichiers `.db` en bénéficie (moins d'écritures inutiles
sur disque, en plus de rendre ce cache par périmètre effectif).

**Chiffrement au repos (Story 4).** Sur un nick dont le `diff.db` est chiffré, chaque ligne du cache par
périmètre ci-dessus est chiffrée avec la DEK de ce nick (jamais celle d'un autre nick d'une requête
multi-nick) — `scopecache.db` elle-même reste un fichier non chiffré, seule la colonne du résultat
filtré l'est. Passphrase de ce nick absente/incorrecte : ni lecture ni écriture pour ses lignes (dégrade
en cache miss silencieux, jamais une erreur visible). `_RESPONSE_CACHE` inclut désormais un condensé
salé de la passphrase de la requête dans sa clé quand une passphrase est fournie (deux passphrases
différentes pour le même appel ne partagent jamais une entrée) ; sans passphrase, comportement inchangé.
Un résultat d'erreur de clé/mode de base n'est jamais mis en cache : rejoué à chaque appel plutôt que
servi comme une réponse obsolète.

| Méthode | Route | Commande CLI | Cache |
|---------|-------|--------------|:---:|
| GET | `/version` | *(aucune — spécifique à borgHelperWWW)* | |
| GET | `/healthz` | *(aucune — liveness, spécifique à borgHelperWWW)* | |
| GET | `/access` | *(aucune — spécifique à borgHelperWWW)* | |
| GET | `/stats` | Stats | |
| POST | `/login` | Login | |
| GET | `/lstbkp` | LstBkp | ✓ |
| GET | `/lstbkpfls` | LstBkpFls | ✓ |
| GET | `/report` | Report | ✓ *(offline uniquement)* |
| GET | `/diffbkp` | DiffBkp | ✓ |
| GET | `/restore/perms` | Restore -L | |
| POST | `/restore` | Restore | |
| DELETE | `/delbkp` | DelBkp ⚡ | |
| POST | `/init` | Init | |
| POST | `/bkp` | Bkp *(asynchrone — voir ci-dessous)* | |
| GET | `/key` | Key | |
| POST | `/prune` | Prune ⚡ | |
| POST | `/index` | Index *(asynchrone depuis 1.28.0 — voir ci-dessous)* | |
| GET | `/search` | Search | ✓ |
| GET | `/filehist` | FileHist | ✓ |
| GET | `/treehist` | TreeHist (`changes=true` → `-X`, changements entre `archive_from` exclue et `archive_to`, borgHelperWWW ≥ 1.27.0) | ✓ |
| GET | `/treefind` | TreeFind | ✓ |
| GET | `/duidx` | DuIdx | ✓ |
| GET | `/cacheinfo` | CacheInfo + (≥ 1.27.3) lignes du cache par périmètre `scopecache.db` par serveur, plus ancienne ligne, taille du fichier | ✓ |
| POST | `/cacheclean` | CacheClean + (≥ 1.27.3) purge des lignes de ces serveurs dans `scopecache.db` | |
| GET | `/idxtop` | IdxTop | ✓ |
| GET | `/difftop` | DiffTop | ✓ |
| GET | `/repohistory` | RepoHistory | ✓ |
| GET | `/archivehistory` | ArchiveHistory | ✓ |
| POST | `/idxpurge` | IdxPurge ⚡ | |
| POST | `/push/subscribe` | *(aucune — spécifique à borgHelperWWW, voir [Notifications push](#notifications-push))* | |
| PATCH | `/push/subscribe` | *(idem)* | |
| DELETE | `/push/subscribe` | *(idem)* | |
| GET | `/push/subscriptions` | *(idem)* | |

`DelBkp` et `Prune` (destruction de sauvegardes) reçoivent `403 Forbidden` tant que
`BORGHELPERWWW_ALLOW_DESTRUCTIVE` n'est pas activé (interdit par défaut — voir
[Configuration](#configuration)) ; `IdxPurge`, bien que marqué ⚡ (irréversible sur l'index local, pas
sur les sauvegardes elles-mêmes), n'est **pas** concerné par ce réglage.

Réponse (`CommandResult`) commune à tous les endpoints ci-dessus :

```json
{"exitcode": 0, "stdout": "...", "stderr": "..."}
```

`exitcode != 0` ⇒ HTTP 400 (le détail reste dans le corps JSON — voir [Codes retour](#codes-retour)), sauf le code 4
(opération refusée sur un dépôt externe) ⇒ **HTTP 403** (borgHelperWWW ≥ 1.28.0).

**Dépôts externes** (borgHelperWWW ≥ 1.28.0) : les routes d'action vérifient `EXTERNAL_OPS` **avant** tout borg ou
sous-processus, avec la fonction de borgHelper (`op_allowed`), et répondent `403` « dépôt externe — opération non
permise » : `POST /bkp`, `POST /init`, `POST /login` (jamais permis) ; `POST /restore`, `GET /download/file`,
`GET /download/tar` (si `restore` manque) ; `POST /prune` et `DELETE /delbkp` (si `prune`/`delete` manquent). Actif
même sans autorisation par groupes ; les groupes s'appliquent en plus. Clé API vérifiée d'abord (401, jamais un 403
qui révélerait un nick). `nick=ALL` : laissé à la CLI, qui écarte les nicks refusés comme `-n ALL` ; une liste
explicite contenant un nick refusé ⇒ 403 (comme le code 4 de la CLI).

**⚠️ `POST /index` est asynchrone** (rupture de compatibilité, depuis 1.28.0) : comme `POST /bkp`, elle détache
`borgHelper -c Index` et répond dès le lancement (`exitcode: 0` = lancé, `stdout` = message de lancement, jamais la
sortie de l'Index ; `ALL` et les listes de nicks acceptés, nick inconnu ⇒ 404). Le résultat d'un Index lancé ainsi
n'est pas remonté dans la réponse. Un Index se met en pause sans limite pendant un Bkp/Restore/Prune (borgHelper
1.0.141) : la requête synchrone restait bloquée jusqu'au délai d'expiration. L'avancement se lit dans `GET /access`
(`build`), et depuis 1.28.2 (borgHelper ≥ 1.0.149) le résultat aussi (`index_last`, `via: "http"`) : échec, refus ou
« Index déjà en cours — rien lancé ».

**⚠️ `POST /bkp` est asynchrone** (rupture de compatibilité, depuis 1.16.0) : contrairement à toutes
les autres routes ci-dessus, elle ne lance jamais `borgHelper -c Bkp` en l'attendant. Elle détache le
sous-processus (`start_new_session=True` — survit à un redémarrage de `borgHelperWWW` pendant la
sauvegarde) et répond dès son lancement confirmé, pas à la fin de la sauvegarde. `exitcode: 0` signifie
donc **« lancement réussi »**, jamais « sauvegarde réussie » — `stdout` contient un message
informatif (`"Sauvegarde démarrée pour <nick> (pid <pid>) — ..."`), jamais la sortie de `borgHelper`
lui-même. Le résultat réel (succès/échec) est capté par une table dédiée `bkp_status` (`history.db` depuis borgHelper 1.0.139,
exclusive à `Bkp`) et réclamé périodiquement par une tâche de fond (« watcher », un par worker
uvicorn) — début **et** fin de sauvegarde — qui envoie une notification push réelle à chaque
abonnement concerné (voir [Envoi réel](#envoi-réel-story-2b) sous [Notifications
push](#notifications-push)). Intervalle d'interrogation et délai avant qu'une sauvegarde bloquée
soit traitée comme un échec : `BORGHELPERWWW_BKP_WATCHER_INTERVAL` (déf. 30s) et
`BORGHELPERWWW_BKP_STATUS_TIMEOUT` (déf. 21600s = 6h), ou par nick la clé rc `BKP_STATUS_TIMEOUT` (1.28.4, prioritaire)
— voir [Configuration](#configuration).

`GET /access` : protégée par `X-API-Key` (contrairement à `/version`), mais **jamais** par
l'autorisation par groupes elle-même — son seul but est de la refléter. Renvoie, pour **chaque**
nick connu, le niveau d'accès effectif de l'appelant (`level`) **et** ses deux périmètres de chemin
résolus séparément depuis `spec-groups-paths-restore` (`read_scope`/`restore_scope` — `null` =
illimité, sinon liste de préfixes canonicalisés ; voir
[Autorisation par groupes](#autorisation-par-groupes-reverse-proxy-oidcauth_request)) :

```json
{"groups_auth_enabled": true, "nicks": {
  "demo-modules": {"level": "admin", "read_scope": null, "restore_scope": null},
  "demo-usrlocal": {"level": "read", "read_scope": ["/var/www/client-x"], "restore_scope": ["/var/www/client-x"]}
}}
```

`groups_auth_enabled: false` (autorisation par groupes désactivée) : `level:"admin"` et
`read_scope:null`/`restore_scope:null` pour chaque nick, sans cas particulier côté client.

Depuis 1.28.0, chaque nick lisible par l'appelant porte aussi (lectures locales comme `Status`, jamais borg) :

- `external` : dépôt externe (`null` si `EXTERNAL` est invalide — les actions sont alors refusées, `ops` vaut `["read"]`) ;
- `ops` : opérations permises parmi `read`, `restore`, `prune`, `delete`, `bkp`, calculées par borgHelper ; `null`
  si la configuration n'a pu être lue (l'UI ne masque alors rien, le serveur refuse toujours) ;
- `build` : état de la base servie comme `Status -j` — `{"state":"complete"}` ou `{"state":"partial","pairs_done",
  "pairs_total","archives_total","stats_done","snapshot","updated_at"}` ;
- `rebuild` : même forme pour le fichier fantôme (`{"state":"partial"}` avant sa première fin de tranche), `null` sans
  reconstruction ;
- `bkp_running` : `true` si un Bkp du nick sans fin, non suivi d'un Bkp réussi, a démarré depuis moins que son délai (clé rc `BKP_STATUS_TIMEOUT`,
  sinon `BORGHELPERWWW_BKP_STATUS_TIMEOUT`, sinon 6 h) sans finir, `false` sinon (un Bkp tué au-delà n'est plus « en
  cours » : le watcher le traite en échec ; 1.28.4 : un Bkp tué suivi d'un Bkp réussi non plus), `null` si `history.db` est
  illisible (1.28.1 ; jamais pris pour une fin de Bkp).
- `index_last` (1.28.2, borgHelper ≥ 1.0.149) : résultat du dernier `Index` de ce nick, quel que soit son lanceur
  (CLI, cron, `POST /index`) — `{"nick","started_at","finished_at","outcome","code","via","message"}` avec `outcome`
  ∈ `ok`, `error`, `refused` (code 3), `busy` (« Index déjà en cours », rien fait), `deadline` (échéance atteinte
  pendant l'attente) et `via` ∈ `cli`, `http` ; heures ISO avec décalage ; `last_failure` (même forme, sans `nick` ni
  `started_at`) sur un `busy`/`deadline` qui suit un échec ; `null` si aucun Index n'a encore écrit de résultat ou si
  le fichier est illisible. L'Index de fin de Bkp n'en écrit pas.
- `bkp_last` (1.28.3, borgHelper ≥ 1.0.152) : dernier Bkp du nick dans `history.db` — `{"run_id","started_at",
  "finished_at","result"}` (`finished_at`/`result` `null` tant qu'il tourne ; heures UTC de SQLite) ; `null` si aucun
  Bkp enregistré ou lecture impossible. L'UI s'en sert pour suivre un ▶ Backup.

Un nick sans droit n'en porte aucun. L'interface web (UI ≥ 1.19.0) s'en sert pour ses badges
(🔗 externe, ⏳ Bkp en cours, 🏗 construction partielle, ♻ reconstruction ; UI ≥ 1.19.2 : ⚠ Index en échec,
jusqu'au prochain Index réussi, avec l'heure et le message en infobulle, et ⏸ Index déjà en cours — rien lancé, pour
un `POST /index` refusé ainsi depuis moins d'une heure), pour masquer les actions interdites sur
un dépôt externe, et la relit toutes les 30 s (liste et page serveur, onglet visible) : à la fin d'un Bkp, la carte du
serveur est rechargée. Un Bkp lancé par ▶ Backup est suivi à part (UI 1.19.1) : même fini avant la première relecture,
sa carte est rechargée une fois. Depuis UI 1.19.3, ce suivi se fait par `run_id` (`bkp_last`) : la carte est rechargée
dès qu'un Bkp différent de celui connu au clic apparaît comme fini, quel que soit le temps que `backup()` a mis à
démarrer (attente de l'Index, `borg list` SSH).

⚠️ **Exception à la règle générale "toujours 200 pour un appel authentifié"** — mais **seulement
pour tout appelant** (depuis 1.20.0, accès direct par périmètre) : `GROUPS_PATHS`
étant relu à chaque appel (voir plus haut), une valeur devenue ambiguë dans `.borghelperrc`
**pendant que le process tourne** fait échouer `/access` en `500` non catché pour le(s) nick(s)
concerné(s), plutôt que de dégrader silencieusement la réponse — c'est la seule route de ce projet
où une erreur de configuration en cours d'exécution est volontairement laissée remonter telle
quelle à l'appelant.

`groups_auth_enabled=false` (autorisation par groupes désactivée) : `"admin"` pour tous les nicks —
reflète l'absence de restriction par groupes, sans forme de réponse différente à gérer côté client.
C'est sur cette route que s'appuient à la fois l'affinage des badges de sécurité de l'interface web
(après connexion) et le filtrage de la liste des serveurs (voir [Autorisation par
groupes](#autorisation-par-groupes-reverse-proxy-oidcauth_request) ci-dessus).

### Notifications push

**Depuis l'UI (Story 2c, `spec-push-ui-prefs-json`)** : bouton **🔔 Notifications** dans l'en-tête
(affiché une fois connecté, si `GET /version` indique `push_available: true` — `pywebpush`/`py_vapid`
disponibles et Service Worker déployé). La vue permet de s'abonner (le navigateur demande la
permission), de régler **host par host** trois types de notification — **début** de sauvegarde,
**succès**, **échec** (Bkp en erreur, ou bloqué au-delà du délai du nick, `BKP_STATUS_TIMEOUT`) — avec
une ligne « Tous » pour cocher une colonne entière (défaut d'un nouvel abonnement : succès + échec),
de choisir la durée (défaut serveur, 7/30/90/365 jours, ou « à vie »), d'**envoyer un test**, de
modifier ses réglages et de se désabonner (borgHelperWWW ≥ 1.21.0 / UI ≥ 1.12.0). Réglages
propres à chaque navigateur. **Exige HTTPS** (ou `localhost`) : un navigateur refuse les notifications
push sur une page non sécurisée. Service Worker : fichier statique `borgHelperWWW_sw.js` (à côté de
l'UI), servi sur `GET /sw.js` sans `X-API-Key` (un navigateur ne peut pas ajouter d'en-tête à
l'enregistrement de son propre Service Worker) — il ne fait qu'afficher la notification et, au clic
(`borgHelperWWW_sw.js` ≥ 1.3.0), ouvrir la page du serveur concerné (`/serveur/<nick>`) : un onglet
borgHelperWWW déjà ouvert y va sans se recharger (Précédent ramène à la page d'avant) et passe au
premier plan ; sinon un nouvel onglet s'ouvre (connexion d'abord, la clé API étant par onglet). Mêmes
règles qu'un lien partagé : serveur hors droits → liste + message de refus. Notification de test → `/`.

**Stockage des préférences — fichier JSON** (`BORGHELPERWWW_PUSH_PREFS`, défaut
`<prefixe>-push-prefs.json` à côté de `push.db`) : source de vérité unique des réglages de chaque
abonné, indexés par `endpoint`, **éditable à la main** et pris en compte à chaud (lu à chaque envoi) :

```json
{
  "subscriptions": {
    "https://fcm.googleapis.com/fcm/send/...": {
      "expires_at": null,
      "hosts": {
        "srv-db":  {"error": true, "start": false, "success": false},
        "srv-web": {"error": true, "start": true,  "success": true}
      },
      "scope_nicks": ["srv-db", "srv-web"],
      "updated_at": "2026-09-26 18:28:06"
    }
  },
  "version": 2
}
```

`scope_nicks` : hosts autorisés — droits de l'appelant à l'abonnement, réalignés à chaque visite de la page
Notifications (≥ 1.27.4) et nettoyés des serveurs retirés du rc par le watcher — un host
ajouté à la main dans `hosts` hors de cette liste est ignoré ; un host de la liste absent de `hosts`,
ou une valeur non booléenne, ne produit aucune notification. Une entrée à l'ancien format (≤ 1.20,
`notify_start`/`notify_end` globaux) est convertie à la lecture : début = `notify_start`, succès et
échec = `notify_end`, pour chaque host.

`expires_at` : `null` = « à vie », sinon date UTC `AAAA-MM-JJ HH:MM:SS`. Un abonnement expiré est retiré du fichier et
de `push.db` par le watcher, au plus tard une heure après son expiration (1.26.3 ; auparavant seulement ignoré à
l'envoi, jamais nettoyé). Écritures atomiques (fichier
temporaire + renommage, mode `0600`) sous verrou (`<fichier>.lock`, plusieurs workers uvicorn). Une
entrée mal formée est normalisée **fail-closed** (nicks invalides -> aucun, date illisible -> expiré,
jamais « à vie » par accident) ; un fichier **corrompu n'est jamais écrasé** : les routes `/push/*`
répondent `500` explicite et le watcher n'envoie rien (log `[watcher] push: ...`) tant qu'il n'est pas
corrigé. Au premier démarrage en 1.19.0, les préférences des abonnements existants sont migrées
automatiquement depuis `push.db` (une fois). `push.db` ne garde plus que les clés VAPID et les clés de
chiffrement de chaque navigateur (`endpoint`/`p256dh`/`auth`) ; ses anciennes colonnes de préférence
sont conservées mais plus lues.

**Stockage des clés — `push.db`** (Story 2a) : fichier dédié (jamais `scopecache.db` — voir
`BORGHELPERWWW_PUSH_DB` dans [Configuration](#configuration)), clés VAPID (EC P-256) générées **une
seule fois** au premier démarrage, jamais régénérées ensuite. Clé publique VAPID exposée sur
`GET /version` (déjà public, sans clé API) : `{"vapid_public_key": "..."}` — nécessaire côté client
pour `PushManager.subscribe({applicationServerKey})`.

Gestion par `endpoint` (la `PushSubscription` du navigateur, retrouvable via
`pushManager.getSubscription()`) plutôt que par compte : pas de couche d'authentification
supplémentaire au-delà de `X-API-Key`/groupes déjà en place.

⚠️ **`endpoint` agit comme un jeton de capacité** (même principe qu'un lien de désabonnement
classique) : les quatre routes `/push/subscribe*`/`/push/subscriptions` ne sont protégées que par
`X-API-Key` — `_check_group_access` les laisse passer sans consulter le périmètre RBAC de
l'appelant (voir la note sur `_ROUTE_LEVELS` plus haut : ces routes n'ont pas de paramètre `nick`).
Concrètement, tout détenteur d'une clé API valide qui connaît/devine un `endpoint` donné peut lire
(`GET /push/subscriptions`), modifier (`PATCH`) ou supprimer (`DELETE`) l'abonnement correspondant,
quel que soit son propre périmètre par groupes — `scope_nicks` filtre ce que l'abonnement *notifie*,
pas qui peut *gérer* l'abonnement lui-même. C'est un compromis de conception assumé (pas de couche
compte séparée, voir Design Notes du spec), pas un oubli.

```bash
# Créer/rafraîchir un abonnement — endpoint/keys.p256dh/keys.auth = forme standard PushSubscription
curl -X POST http://localhost:8000/api/push/subscribe -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{
  "endpoint": "https://push.example.com/ep1",
  "keys": {"p256dh": "...", "auth": "..."},
  "defaults": {"start": false, "success": false, "error": true},
  "hosts": {"srv-web": {"start": true, "success": true, "error": true}},
  "expires_in_days": 30
}'
```

| Paramètre | Défaut si absent | `null` explicite |
|-----------|-------------------|-------------------|
| `hosts` | `{}` — `{nick: {start, success, error}}` ; un host hors du périmètre de l'appelant est ignoré (la réponse montre les réglages effectifs) ; un champ omis prend sa valeur par défaut | — |
| `defaults` | `{"start": false, "success": true, "error": true}` — appliqué à chaque host du périmètre absent de `hosts` | — |
| `notify_start` / `notify_end` | hérités (API ≤ 1.20), utilisés seulement sans `defaults` : début / succès+échec pour tous les hosts | rejeté (`422`) en `PATCH` |
| `expires_in_days` | `BORGHELPERWWW_PUSH_DEFAULT_EXPIRY_DAYS` (déf. 30) | « à vie » (`expires_at` = `NULL`, jamais d'expiration automatique) |

`expires_in_days` est borné à `[1, 3650]` jours (`PUSH_MAX_EXPIRY_DAYS`) — une valeur hors bornes
(y compris une valeur absurde comme `999999999999`, qui ferait sinon silencieusement déborder
`datetime('now','+N days')` côté SQLite vers `NULL`, soit « à vie » par accident) retombe sur le
même défaut serveur que l'absence du champ, jamais sur « à vie ». Logique de résolution partagée
entre `POST`/`PATCH` (`_resolve_push_expiry_days`).

`scope_nicks` (périmètre RBAC de l'appelant, même mécanisme que `GET /access` : tout nick où l'appelant
a au moins un accès lecture) est calculé et **figé** à chaque appel `POST /push/subscribe` — un
ré-abonnement sur le **même** `endpoint` (`endpoint` `UNIQUE`) met à jour la ligne existante (jamais de
doublon) et **recalcule** `scope_nicks` à ce nouveau moment : une personne qui se réabonne
explicitement après un changement de ses groupes rafraîchit ainsi son périmètre sans devoir d'abord se
désabonner. Depuis 1.27.4, `POST /push/subscribe/sync?endpoint=…` (appelé par la page Notifications à chaque
visite) **réaligne** `scope_nicks` sur les droits actuels de l'appelant : hosts devenus inaccessibles retirés (plus
aucune notification), nouveaux hosts ajoutés **tout décochés** (jamais d'envoi non demandé), réglages des autres
conservés ; réponse `{added, removed}`. Les groupes n'étant connus qu'aux requêtes de l'abonné (en-tête HTTP), un
abonné qui ne revient pas garde sa liste jusqu'à l'expiration de l'abonnement. Le watcher retire en outre, toutes
les heures, les serveurs qui n'existent plus dans le rc. `PATCH /push/subscribe` modifie les préférences
(`hosts`, `expires_in_days`, jamais `scope_nicks`). Les hosts fournis voient leurs réglages
**remplacés**, les autres restent inchangés ; un host hors du périmètre de l'abonnement → `422`, rien
n'est écrit :

```bash
curl -X PATCH http://localhost:8000/api/push/subscribe -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{
  "endpoint": "https://push.example.com/ep1",
  "hosts": {"srv-db": {"start": false, "success": false, "error": true}},
  "expires_in_days": null
}'
# 404 explicite si l'endpoint est inconnu — jamais de création silencieuse (PATCH != POST)
# 409 si l'endpoint est connu de push.db mais sans entrée dans le fichier JSON (fichier supprimé/édité)
#     — se réabonner (POST) pour recréer les préférences

curl -X POST "http://localhost:8000/api/push/test?endpoint=https://push.example.com/ep1" -H "X-API-Key: $KEY"
# {"sent": true} — envoie une notification de TEST à ce seul abonnement (payload event:"test") ;
# 404 endpoint inconnu, 410 abonnement mort côté navigateur (supprimé), 502 service push en erreur,
# 503 envoi indisponible sur ce serveur (vendor/ ou paquets apt manquants — voir le [WARN] au démarrage)

curl -X DELETE "http://localhost:8000/api/push/subscribe?endpoint=https://push.example.com/ep1" -H "X-API-Key: $KEY"
# {"deleted": true} — un endpoint déjà absent renvoie {"deleted": false}, jamais un 404 bruyant
# (désabonnement explicite : « déjà absent » atteint déjà l'objectif)

curl "http://localhost:8000/api/push/subscriptions?endpoint=https://push.example.com/ep1" -H "X-API-Key: $KEY"
# {"subscriptions": [{...}]} — permet à l'UI d'afficher « vos abonnements actuels »
```

Réponse commune à `POST`/`PATCH`/`GET` (un ou plusieurs objets de cette forme) :

```json
{"id": 1, "endpoint": "...", "scope_nicks": ["demo-modules"],
 "hosts": {"demo-modules": {"start": false, "success": true, "error": true}},
 "expires_at": "2026-10-26 07:48:45", "created_at": "2026-09-26 07:48:45",
 "updated_at": "2026-09-26 07:48:45", "prefs_missing": false}
```

`prefs_missing: true` : endpoint connu de `push.db` sans entrée dans le fichier JSON — aucune
notification ne part pour lui tant qu'il ne s'est pas réabonné.

**Dépannage — « Envoyer un test » n'affiche rien** (UI ≥ 1.11.1) : cliquer **« Tester l'affichage
local »** (notification créée par le navigateur lui-même, sans serveur ni service push).

- Le test local n'apparaît pas non plus : blocage côté navigateur/système — autorisation des
  notifications pour le navigateur dans le système (GNOME/KDE, Windows, macOS), mode « Ne pas
  déranger », permission du site.
- Le test local apparaît mais pas le test serveur : acheminement. Le serveur `borgHelperWWW` doit
  joindre en HTTPS sortant le service push du navigateur (Firefox : `updates.push.services.mozilla.com`,
  Chrome : `fcm.googleapis.com`) — pare-feu/proxy (`HTTPS_PROXY` est respecté). Depuis 1.20.2, un
  service injoignable donne une erreur explicite en 10 s au lieu d'une attente sans fin. Vérifier
  depuis le serveur : `curl -sI https://updates.push.services.mozilla.com/`.

Les notifications de sauvegarde sont conservées 24 h par le service push si le navigateur est hors
ligne (TTL), puis livrées à sa reconnexion ; le test, 5 minutes.

Vérification interne dédiée : `borgHelperWWW -C ... --selftest` (voir `TECHNICAL.md` — génération
VAPID, CRUD, calcul d'expiration, clamp de `BORGHELPERWWW_PUSH_DEFAULT_EXPIRY_DAYS`, envoi push mocké,
sur des fichiers temporaires uniquement).

#### Envoi réel (Story 2b)

Le watcher `bkp_status` (voir `POST /bkp` asynchrone ci-dessus) ne se contente plus de journaliser :
à chaque réclamation CAS gagnée — **début** de sauvegarde (`started_at` écrit, aucun délai à
attendre) **et** fin (succès, échec, ou timeout AD-7) — il envoie un push réel (`pywebpush`) à chaque
abonnement non expiré dont les préférences (fichier JSON) activent, **pour ce host**, le type
correspondant : `start` pour un début, `success` pour une fin réussie, `error` pour toute autre fin
(erreur, timeout AD-7). Payload JSON (affiché par le
Service Worker) : `{"nick":..., "event":"start"|"end"|"test", "result":"success"|"error"|null,
"timestamp":...}` — `result` toujours `null` pour un début ou un test. Fin de sauvegarde
(borgHelperWWW ≥ 1.23.0 / borgHelper ≥ 1.0.118) : en plus `changed_during_backup` / `read_errors`
(fichiers modifiés pendant la sauvegarde / erreurs de lecture, voir `Bkp`) quand ils sont connus. Une
sauvegarde réussie avec avertissements s'affiche « ⚠️ Sauvegarde terminée avec avertissements — nick »
(ex. « Bkp réussi — 2 fichiers modifiés pendant la sauvegarde, 1 erreur de lecture ») ; un échec
mentionne aussi ces compteurs. Le type reste « succès » ou « échec » pour les réglages par host.

**Sauvegarde en retard** (borgHelperWWW ≥ 1.24.0) : le watcher compare à chaque passage l'âge de la
dernière archive connue de chaque serveur à son `MAX_AGE_BKP` (heures, défaut 25 — la même règle qui
marque déjà le serveur en erreur dans `Report`). Au-delà, notification de type **Échec** (réglage
« ❌ Échec / retard » par host) : « ⏰ Sauvegarde en retard — nick / Dernière sauvegarde il y a 31 h
(seuil : 25 h) », payload `{"event":"overdue","result":"error","age_hours","max_age_hours",
"last_backup","reminder"}`. Une alerte au franchissement du seuil, puis un **rappel** à chaque période
supplémentaire (2×, 3× le seuil… — « ⏰ Toujours aucune sauvegarde »), jusqu'à la prochaine archive.
Rien pendant un Bkp en cours, ni pour un serveur sans aucune archive connue. Tant que personne n'est
abonné aux échecs de ce host, l'alerte n'est pas consommée : un abonnement pris pendant le retard la
reçoit au passage suivant. Plusieurs workers uvicorn : un seul envoie (réservation atomique dans
`push.db`, table `overdue_alerts`). « Dernière archive connue » = `archive_stats` (alimentée par chaque
`Bkp` et par `Index`) : une archive créée hors borgHelper n'est vue qu'après un `Index`.

Un abonnement mort côté navigateur (le service de push répond `404`/`410`) est désabonné
automatiquement (même requête que `DELETE /push/subscribe`). Toute autre erreur (réseau, autre code
HTTP) est journalisée côté serveur (log `[watcher] push: ...`) sans désabonner ni retenter — la ligne
`bkp_status` est déjà réclamée par CAS, elle ne sera plus jamais revisitée par aucun watcher : une
erreur transitoire sur un abonnement, lors d'une réclamation par ailleurs réussie pour d'autres
abonnements, n'est donc jamais retentée pour cet événement précis (limitation assumée, pas un bug —
voir Design Notes du spec).

`vapid_claims['sub']` (contact requis par le protocole Web Push, RFC 8292, jamais affiché à la
personne abonnée) : `BORGHELPERWWW_PUSH_VAPID_SUB` (déf. `mailto:admin@example.invalid` — générique,
à définir en production).

### `/download/file` et `/download/tar` — téléchargements binaires

Seule exception au principe « tout passe par le binaire `borgHelper` en sous-processus » : un
téléchargement doit streamer des octets bruts vers le navigateur (`Content-Disposition: attachment`),
incompatible avec la réponse JSON texte de `CommandResult`. Ces deux routes lisent la conf via
`BorgRunner` (mode librairie) et appellent `borg` **directement**, sans passer par `borgHelper` :

| Méthode | Route | Paramètres | Commande borg |
|---------|-------|------------|----------------|
| GET | `/download/file` | `nick`, `path`, `bid` (optionnel, défaut dernière archive) | `borg extract --stdout` |
| GET | `/download/tar` | `nick`, `prefix` (optionnel, défaut racine), `bid` (optionnel) | `borg export-tar` |

Passphrase via `X-Borg-Passphrase` comme les autres actions marquées 🔑. Réponse : le flux binaire
directement (pas de `CommandResult`) ; en cas d'erreur avant le début du stream, `HTTPException` JSON
classique (404 nick/archive inconnu, 502 `borg list` en échec, 504 timeout, **403** si
`BORGHELPERWWW_ALLOW_DOWNLOADS` est désactivé — autorisé par défaut, voir
[Configuration](#configuration)).

Depuis la Story 2.1 : un `path`/`prefix` hors du périmètre de l'appelant (`GROUPS_PATHS`, voir
[Autorisation par groupes](#autorisation-par-groupes-reverse-proxy-oidcauth_request)) répond `200`
avec un corps vide (`/download/file`) ou un tar minimal vide (`/download/tar`), jamais un `403` —
voir le tableau de la section « Autorisation par groupes » ci-dessus pour la forme exacte et le
raisonnement (indiscernabilité d'un chemin qui n'existe simplement pas dans l'archive). Aucun appel
`borg` n'est fait dans ce cas pour le fichier/l'arborescence demandé.

### Limites connues

- Exécution synchrone : `Bkp`/`Prune`/`Index` sur un gros dépôt occupent un worker HTTP pendant toute
  leur durée — pas de file d'attente/job asynchrone. Prévoir `--workers` et un timeout côté reverse-proxy.
- Le budget d'authentification est volontairement simple (une seule clé partagée). Pour un usage
  multi-utilisateurs avec traçabilité par appelant, ajouter une couche d'auth dédiée devant l'API.
- **Interface web pas encore adaptée au filtrage par périmètre (Stories 1.3–1.4)** :
  `borgHelperWWW_ui.html` ne distingue pas encore une réponse filtrée (JSON forcé par un périmètre
  restreint) d'une réponse normale — elle continue d'afficher le JSON forcé comme si c'était la forme
  attendue, sans indiquer à l'utilisateur que le résultat a été réduit à son périmètre. Vrai pour les
  six commandes de la Story 1.3 (`Search`, `FileHist`, `LstBkpFls`, `DiffBkp`, `TreeHist`,
  `TreeFind`) comme pour les trois de la Story 1.4 (`DuIdx`, `IdxTop`, `DiffTop`, dont le JSON brut
  recalculé côté `borgHelperWWW` est tout aussi indiscernable d'une réponse normale pour l'UI). Connu,
  non traité dans ces stories (périmètre volontairement limité à l'API HTTP elle-même) — suivi séparé
  côté UI.
- **`DuIdx`/`IdxTop`/`DiffTop` filtrés par périmètre depuis la Story 1.4** : voir « Autorisation par
  groupes » ci-dessus pour le mécanisme (mode brut par-chemin + recalcul côté `borgHelperWWW`,
  traitement mono-nick, omission des figures Exclus/Inchangés non scopables pour un appelant scopé).
- **Une requête hors périmètre coûte autant qu'une vraie requête introuvable** (1.27.5 : vraie commande sur un
  leurre, voir « Autorisation par groupes ») — c'est le prix de l'indiscernabilité, temps de réponse compris : un
  appelant qui martèle ces routes génère la même charge côté dépôt borg qu'avec des chemins inexistants.

---

## Codes retour

| Code | Signification |
|------|---------------|
| 0 | Succès |
| 1 | Avertissement (rapport : sauvegarde trop ancienne) |
| 2 | Erreur borg |
| 3 | État incohérent (déjà monté, serveur inconnu, `MOUNTPOINT`/`GLOB_ARCH` absent…) |
| 4 | Opération non permise sur ce nick (dépôt externe, `EXTERNAL_OPS`) — aucun borg lancé |

---

## Exemples de crontab

```cron
# Backup quotidien à 2h — index (diff + snapshot + tailles) automatique
0 2 * * *  borgHelper -c Bkp -n mon-serveur

# Prune hebdomadaire le dimanche à 3h
0 3 * * 0  borgHelper -c Prune -n mon-serveur

# Construction / complétion / reconstruction des bases par tranches de 20 min PAR NICK, toutes les heures (ligne
# conseillée, 1.0.148) : couvre le snapshot d'un gros dépôt, première unité d'une tranche. Au-delà de 3 nicks, un
# lancement peut dépasser l'heure (jusqu'à 20 min × nombre de nicks si chacun use son budget) : le suivant saute
# seulement le nick en cours (« Index déjà en cours ») et traite les autres en parallèle — plusieurs lancements peuvent
# alors se cumuler. Pour n'en garder qu'un : flock -n /tmp/borghelper-index.lock borgHelper -c Index -n ALL -t 20m
# Remplace l'ancienne ligne conseillée `*/10 * * * * … Index -n ALL -t 1m` (avant 1.0.148).
0 * * * *  borgHelper -c Index -n ALL -t 20m

# Rapport HTML envoyé par mail
30 6 * * *  borgHelper -c Report -n ALL -l | mail -s "Borg $(date +\%F)" admin@domaine.com
```

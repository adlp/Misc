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
EXCLUDE_NEXT     = --exclude /var/cache          # exclusions complémentaires optionnelles
BORG_ARCHNAME    = root                          # partie centrale du nom d'archive
BORG_ROOTBKP     = /                             # répertoire racine sauvegardé

# Affichage rapport
MAX_AGE_BKP      = 25                            # alerte si dernière sauvegarde > N heures (défaut 25)
DISPLAY_BKP      = 5                             # nombre de sauvegardes affichées dans Report

# SSH avancé (backup distant)
SSH_REPO         = repo01:/mnt/borg/mon-serveur  # BORG_REPO côté serveur sauvegardé
SSH_REMFO        = 8022:localhost:22             # tunnel inverse SSH
SSH_KEY          = /root/.ssh/id_borg

# Identifiant SQLite (optionnel — surcharge le nick dans le nom des fichiers DB)
DB_NAME          = mon-serveur-home              # → borghelperrc-mon-serveur-home-cache.db

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
IDX_INCLUDE      = /etc /home /root              # liste blanche — seuls ces chemins indexés
IDX_EXCLUDE      = /proc /sys /tmp /var/log
    /var/lib/docker /home/*/.cache
    *.bak *.pyc /home/*/.bash_history            # liste noire

# Parallélisation de l'indexation (nombre de borg diff simultanés, défaut 4)
IDX_WORKERS      = 4

# Limiter la taille de diff_index : conserver seulement les N dernières paires indexées
# Non défini = pas de limite (tout l'historique conservé)
DIFF_KEEP        = 30

# Rétention de l'historique repo_stats (taille du dépôt dans le temps, un point par Bkp/Prune)
# en mois. Purgé à chaque écriture (fin de Bkp ou de Prune réel). Défaut 13 mois si absent,
# non numérique, ou < 1 (0 ou négatif sont ramenés au défaut de 13 mois).
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
GROUPS_ADMIN     = ops-admins                    # Prune/DelBkp/IdxPurge/Init/Key/Login sur ce nick
GROUPS_WRITE     = ops-admins,ops-writers        # Bkp/Index/Restore/CacheClean (+ lecture)
GROUPS_READ      = ops-admins,ops-writers,ops-readers  # tout le reste (+ téléchargements)

# Périmètre de chemin par groupe (facultatif, orthogonal au tier ci-dessus — ne l'étend jamais,
# ne peut que le restreindre) : un groupe absent de cette clef garde un accès chemin illimité
# dans la limite du tier qu'il détient déjà via GROUPS_ADMIN/WRITE/READ. Syntaxe :
# 'groupe:/chemin/a|/chemin/b, groupe2:/chemin/c' — ':' sépare groupe et chemin(s), '|' sépare
# plusieurs chemins pour un même groupe, ',' sépare les groupes. Ces trois caractères sont donc
# réservés : un nom de groupe ou un chemin qui en contient fait échouer le chargement de la
# config avec une erreur explicite (jamais un résultat silencieusement mal découpé).
GROUPS_PATHS     = ops-readers:/var/www/client-x
```

Le nickname (nom de section) sert d'identifiant partout avec `-n`.

**Permissions.** `Login` crée `~/.borghelperrc` en `0600` (il contient des passphrases). Un rc existant n'est
jamais modifié, mais un avertissement (une fois, sur stderr) est émis à sa lecture si le groupe ou les autres y ont
accès. Le répertoire de cache est créé en `0700` et les bases `.db` en `0600` ; les fichiers/répertoires existants
sont laissés tels quels.

**Chiffrement des bases.** Deux clés optionnelles, globales (`[DEFAULT]`) ou par nick (la valeur du nick l'emporte) :

```ini
[DEFAULT]
DB_ENCRYPT = true       # défaut. false/no/off/0 pour désactiver (globalement ou pour un seul nick)
DB_KDF     = standard   # light | standard (défaut) | strong — coût de dérivation de la clé
```

`DB_ENCRYPT=true` (défaut) ne fait rien tout seul : une base créée par `Bkp`/`Index` reste `plain` tant qu'on n'a pas
lancé `DbEncrypt` dessus (elle n'était pas chiffrée avant, elle ne le devient pas toute seule — pas de migration
implicite). Si une base reste `plain` alors que `DB_ENCRYPT` est actif et qu'une passphrase est disponible,
`borgHelper` avertit une fois par base (par invocation, sur stderr) et cite la commande à lancer. `DbEncrypt`/
`DbDecrypt`/`DbRekey`/`DbStatus` (voir [Commandes](#commandes)) basculent le mode d'une base réelle. La clé de
chiffrement est dérivée de `BORG_PASSPHRASE`. `DbRekey` ré-enveloppe la DEK existante avec un sel/nonce frais
(et le `DB_KDF` courant du nick, s'il a changé) — la DEK ne change pas et aucune ligne de donnée n'est touchée ; c'est
une rotation de l'enveloppe, PAS un mécanisme de changement de `BORG_PASSPHRASE` (celui-ci exigerait de connaître
simultanément l'ancienne et la nouvelle passphrase — hors périmètre de cette commande). Changer `BORG_PASSPHRASE`
dans le fichier de conf d'un nick dont la base est déjà chiffrée la rend illisible (`DbKeyError`) : ne le faites pas
sans avoir d'abord `DbDecrypt`é. `DB_ENCRYPT=false`
pour un nick fait refuser `DbEncrypt` dessus explicitement (déchiffrer avec `DbDecrypt` reste toujours permis).
`borgHelper -c CodecSelfTest` vérifie le codec, la migration et ses refus sur des bases temporaires.

Répertoire de cache configurable via la clé `CACHE_DIR` dans la section `[DEFAULT]` — comme toute clef
INI, `GROUPS_ADMIN`/`GROUPS_WRITE`/`GROUPS_READ` supportent aussi ce repli sur `[DEFAULT]` (politique
par défaut pour tous les nicks qui ne les surchargent pas individuellement) :

```ini
[DEFAULT]
CACHE_DIR = /data/borgcache
GROUPS_READ = ops-readers,ops-writers,ops-admins   # défaut : tout le monde peut au moins lire
```

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
Par défaut, capture les fichiers modifiés pendant le backup (`--list`) et indexe automatiquement dans le SQLite (`diff_index` + snapshot + tailles via `borg diff`).

```bash
borgHelper -c Bkp -n mon-serveur        # backup + indexation automatique
borgHelper -c Bkp -n mon-serveur -I     # backup seul, sans indexation
```

Nécessite : `EXCLUDE`, `SER_LOGIN`, `SER_NAME`.  
Code retour 0 si succès ou warnings, 2 si erreur borg.

> `-I` désactive `--list`, toute écriture SQLite et l'appel automatique à `Index` — utile si l'indexation est gérée séparément.

> **Priorité sur Index :** `Bkp` est prioritaire sur `Index` à tout moment — même si `Index` est en cours à n'importe quelle étape :
> - Si `Index` démarre alors que `Bkp` est déjà actif → annulation immédiate avant même le premier `borg diff`.
> - Si `Bkp` démarre pendant un `Index` → les `borg diff` actifs reçoivent SIGKILL, `Index` s'arrête complètement (borg info et indexsnap inclus).
> - Dans les deux cas, `Index` pose un flag de reprise (`index-pending.lock`) : `Bkp` le détecte en fin d'exécution et relance automatiquement `Index` complet.

**Sortie stdout (JSON)** — si exit 0, le JSON borg est enrichi de deux clefs borgHelper :

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
Enchaîne automatiquement `borg compact`, invalide le cache SQLite, et purge les entrées orphelines du `diff.db`.
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

**Variation de taille** — colonne `size_delta` : pourcentage de variation de `original_size` par rapport à l'archive précédente (`+11%`, `-5%`, `—` pour la première). `original_size` est stable dans le temps (indépendant de la déduplication inter-archives). Dans le résumé (ligne par hôte), ce delta de la dernière archive est aussi affiché entre parenthèses dans la colonne `derniere` — ex. `1.37 GB (+11%)`.

**Statistiques de mouvement** (si l'index SQLite est disponible) — colonne `modifications` :

| Contexte | `modifications` | Exemple |
|----------|----------------|---------|
| Résumé (par hôte) | `XX%nb / Y.YY GB` | `3%nb / 1.37 GB` |
| Détail (par archive) | `XX%nb / Y.YY GB` | `5%nb / 890 MB` |

Formule (identique résumé et détail) :
- dénominateur = état précédent = `nfiles − added + removed` (100%)
- `XX%nb` = `100 × (modified + removed) / précédent` — % de fichiers modifiés ou supprimés
- `Y.YY GB` = taille absolue lisible (`added_sz + modified_sz + removed_sz`), **pas** un pourcentage — `—` si nulle

- `—` si l'archive n'est pas encore indexée

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
| `-f` | Chemin exact ou glob (`*`, `?`) |
| `-w <dest>` | Restauration avec sous-répertoires (répertoire ou `.tar`/`.tgz`) |
| `-w -` | Tar non-compressé vers stdout (pipeable) |
| `-W <dest>` | Restauration plate — fichiers à la racine |
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
```

| Option | Description |
|--------|-------------|
| `-F` | Supprime et recalcule toutes les paires existantes (snapshot : force `borg list` complet) |
| `-S` | Snapshot seul — indexe uniquement le listing de la dernière archive |
| `-A <archive>` | Restreint l'indexation à la paire dont `archive_new` correspond à `<archive>` |

Types d'événements : `added`, `removed`, `modified`, `C` (permissions), `B` (lien cassé), `T` (type changé).

Le snapshot (`-S`) est **incrémental par défaut** : si un snapshot précédent et le diff correspondant existent, seules les entrées `added/removed/modified` sont appliquées par SQL, et `borg list` est appelé uniquement sur les fichiers ajoutés (pour leur mtime). Fallback vers `borg list` complet si : pas de snapshot précédent, diff absent, > 5 000 ajouts, ou erreur borg. `-F` force le `borg list` complet.

> **Interruptible et reprise automatique :** si `Bkp` ou `Restore` démarre pendant `Index`, l'indexation s'arrête immédiatement (diffs tués + borg info + indexsnap annulés). `Index` pose un flag de reprise ; `Bkp` le détecte à la fin de son exécution et relance automatiquement `Index` complet. Les paires déjà indexées sont sautées (incrémental).

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

**Fichiers/répertoires supprimés** : les enfants directs supprimés depuis (mais toujours
récupérables — l'archive de dernière présence existe encore) apparaissent aussi, marqués
distinctement (colonne `type`=`supprimé`, colonne `archive`=archive à restaurer). Un répertoire
entièrement supprimé reste explorable : `TreeHist` dessus affiche son ancien contenu au lieu d'une
erreur. Un chemin réajouté depuis sa suppression réapparaît normalement, sans marque. JSON (`-j`) :
ces entrées portent `"deleted":true,"last_seen_archive":"<archive>"` en plus des clés habituelles
(`mode`/`owner` à `null`, `is_dir` déduit par heuristique — voir TECHNICAL.md) ; les entrées non
supprimées gardent une forme JSON strictement inchangée.

```bash
borgHelper -c TreeHist -n mon-serveur                        # contenu direct de la racine
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
borgHelper -c DuIdx -f '*.log' -n ALL                      # résumé global sur les .log
borgHelper -c DuIdx -f '*' -s présent:desc -n mon-serveur  # trié par taille présent desc
borgHelper -c DuIdx -f '*' -j -n mon-serveur               # sortie JSON
borgHelper -c DuIdx -n mon-serveur -R                      # sortie brute, une ligne JSON par chemin
```

Le préfixe (`-f 'préfixe/*'`) est sensible à la casse et littéral (`%`/`_` n'y sont pas des jokers) ; un `/`
initial/final ou un `//` interne y est normalisé avant comparaison. Le motif de nom (`-f motif` sans `/*`) reste
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
Exclus  :  18 200 entrées · 3.4 GB (IDX_EXCLUDE) — +5 000 · -200 · =13 000
```

Le détail `+ajoutés · -supprimés · =modifiés` est affiché sur la même ligne. Seuls les types présents sont affichés. Les fichiers inchangés ne peuvent pas être comptés (`borg diff` ne les liste pas).

Si `IDX_EXCLUDE` est vide ou qu'aucun fichier n'a été filtré, la ligne Exclus est omise.

Affiche également les fichiers **inchangés par archive** avant le tableau :

```
Inchangés par archive :
  archive-2024-01-01 : 95 000 (97%) / 98 000 fichiers
  archive-2024-01-02 : 96 200 (96%) / 100 000 fichiers
```

Calcul : `nfiles − added_total − modified_total` (indexés + exclus). Seules les archives présentes dans `archive_stats` et `diff_index` sont affichées.

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

`RepoHistory -j` : une ligne par événement `repo_stats` (`id`,`op` (`'bkp'|'prune'`),`unique_csize`,
`total_size`,`total_csize`,`updated_at`), ordonnées par `id` croissant.

`ArchiveHistory -j` : une ligne par archive de `archive_stats` (`archive`,`archive_date`,`duration`,
`original_size`,`compressed_size`,`deduplicated_size`,`nfiles`), ordonnées par `archive_date`.

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
| `-j` | Sortie JSON — toujours une **liste**, même à un seul nick : `[{nick,last_backup,bkp_running,priority_op_running}, ...]` |

Par nick :
- **Dernier backup connu** : archive + date depuis `archive_stats` (déjà indexée localement) + âge
  lisible (« il y a 3h12 ») ; « aucune archive indexée » si le nick n'a jamais été indexé.
- **Bkp en cours** : si une ligne `bkp_status` non terminée existe, « Bkp en cours depuis HH:MM
  (XhYYmin) ».
- **Opération prioritaire en cours** : si `priority.lock` est tenu et qu'aucun Bkp n'est détecté,
  « Opération prioritaire en cours (Restore ou Prune) » — **ambiguïté assumée**, `priority.lock` ne
  distingue pas laquelle des deux le tient. Si un Bkp est aussi détecté, pas de message redondant (le
  Bkp lui-même tient ce lock).

En JSON : `last_backup` est `{archive,date}` ou `null` ; `bkp_running` est `{started_at}` ou `null` ;
`priority_op_running` est un booléen brut (reflète `priority.lock`, indépendamment de `bkp_running` —
c'est au consommateur de corréler les deux, comme pour l'affichage texte).

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

Après suppression, `IdxPurge` recalcule `diff_indexed_pairs.entry_count` et compacte le fichier via `VACUUM INTO` (dans le même répertoire, évite les problèmes de `/tmp` plein). Si le compactage échoue, les entrées sont quand même supprimées et la commande manuelle est affichée.

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
Exclus   :   800 entrées · 1.2 GB (IDX_EXCLUDE) — +300 · -50 · =450
Inchangés: 96 000 (97%) sur 99 500 fichiers dans archive-new
```

Calcul : `nfiles_new − added_total − modified_total` (indexés + exclus). Ligne omise si `archive_stats` ne contient pas `nfiles` pour l'archive cible.

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
| `-D` | Dry-run — rapporte les tables/lignes/espace estimé, ne change rien |
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
**Limitation connue :** `borgHelperWWW` n'a aucun moyen d'être notifié d'un `DbRekey` exécuté en CLI ; son memo
de codec par nick reste périmé jusqu'à son redémarrage.

### `DbStatus`

```bash
borgHelper -c DbStatus -n mon-serveur
borgHelper -c DbStatus -n ALL
```

Affiche le mode (`plain`/`siv1`/`migrating`) de `cache.db` et de `diff.db` pour chaque nick. Ne lit que
l'en-tête (`db_meta.enc_header`) : aucune passphrase n'est nécessaire pour simplement connaître le mode d'une
base chiffrée. Si une base reste `plain` alors que `DB_ENCRYPT` est actif et qu'une passphrase est
disponible, avertit (comme `_open_db`, une fois par base et par invocation) et cite la commande `DbEncrypt`.

---

### `CodecSelfTest`

```bash
borgHelper -c CodecSelfTest
```

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

Trois façons de configurer, cumulables — par ordre de priorité (la première présente l'emporte) :

1. **Option CLI** (`python3 borgHelperWWW ...` en exécution directe uniquement — sous
   `uvicorn borgHelperWWW:app`, uvicorn possède seul `sys.argv`)
2. **Variable d'environnement** `BORGHELPERWWW_*` (marche dans les deux modes de lancement)
3. **Fichier de conf** `BORGHELPERWWW_CONF` / `--conf` (ini, un seul fichier pour tous les réglages
   ci-dessous — voir [`borghelperwww.conf.example`](borghelperwww.conf.example) ; comble uniquement
   ce qui n'est pas déjà réglé par une option CLI ou une variable d'environnement)

⚠️ **Jamais dans `.borghelperrc`** : ce fichier (`-C`/`BORGHELPERWWW_CFGFILE` ci-dessous) est lu par
`borgHelper` (CLI, réglages par nick) — une clé `BORGHELPERWWW_*` posée dans son `[DEFAULT]` est
silencieusement ignorée par `borgHelperWWW` (aucune erreur). Piège réel constaté : `GROUPS_HEADER`
ainsi posé laisse le RBAC désactivé sans le savoir (accès total pour tout `X-API-Key` valide) —
`borgHelperWWW` avertit désormais (`[WARN]` au démarrage) si une clé `BORGHELPERWWW_*` traîne dans
`[DEFAULT]` de `.borghelperrc`.

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
| `BORGHELPERWWW_TRUSTED_PROXIES` | `--trusted-proxies` | `trusted_proxies` | IP/CIDR des reverse proxies de confiance, séparées par des virgules, ou `*` pour toutes (défaut `127.0.0.1` — voir ci-dessous) |
| `BORGHELPERWWW_ALLOW_DESTRUCTIVE` | `--allow-destructive`, `--no-allow-destructive` | `allow_destructive` | Autorise `Prune`/`DelBkp` (destruction de sauvegardes) — **interdit par défaut** (voir ci-dessous) |
| `BORGHELPERWWW_ALLOW_DOWNLOADS` | `--allow-downloads`, `--no-downloads` | `allow_downloads` | Autorise `/download/file` et `/download/tar` (vue d'une restauration) — **autorisé par défaut** (voir ci-dessous) |
| `BORGHELPERWWW_API_PREFIX` | `--api-prefix` | `api_prefix` | Préfixe de toutes les routes API — défaut `/api` (voir ci-dessous) |
| `BORGHELPERWWW_GROUPS_HEADER` | `--groups-header` | `groups_header` | Header HTTP contenant les groupes de l'utilisateur (reverse proxy OIDC) — absent : **désactivé** (voir ci-dessous) |
| `BORGHELPERWWW_SCOPE_CACHE_DB` | `--scope-cache-db` | `scope_cache_db` | Chemin du fichier SQLite du cache de réponses **filtrées** par périmètre (Story 1.5) — défaut : co-localisé avec `cache.db`/`diff.db` (voir [Cache de réponses](#cache-de-réponses)) |
| `BORGHELPERWWW_BKP_WATCHER_INTERVAL` | — | — | Intervalle (secondes) d'interrogation `bkp_status` par le watcher — défaut 30 (voir `POST /bkp` asynchrone ci-dessus) |
| `BORGHELPERWWW_BKP_STATUS_TIMEOUT` | — | — | Délai (secondes) avant qu'une sauvegarde démarrée mais jamais terminée soit traitée comme un échec (AD-7) — défaut 21600 (6h) |
| `BORGHELPERWWW_PUSH_DB` | `--push-db` | `push_db` | Chemin du fichier SQLite **dédié** aux clés VAPID et abonnements push (Story 2a, `spec-notifications-push`, AD-6 — jamais `scopecache.db`) — défaut : co-localisé avec `cache.db`/`diff.db` (voir [Notifications push](#notifications-push)) |
| `BORGHELPERWWW_PUSH_DEFAULT_EXPIRY_DAYS` | — | — | Durée d'expiration par défaut (jours) d'un abonnement push quand `expires_in_days` est absent de `POST /push/subscribe` — défaut 30, repli sur 30 si valeur invalide/négative |
| `BORGHELPERWWW_PUSH_VAPID_SUB` | — | — | Contact (`vapid_claims['sub']`, ex. `mailto:...`) requis par le protocole Web Push (RFC 8292) pour l'envoi réel (Story 2b) — défaut générique `mailto:admin@example.invalid`, à définir en production |

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

- `GET /` (la page web elle-même)
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

**Périmètre de chemin par groupe (`GROUPS_PATHS`)** : raffinement orthogonal au tier ci-dessus —
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

Sur un chemin hors périmètre, chaque route répond avec une forme SYNTHÉTIQUE qui imite exactement
sa propre réponse « chemin introuvable » (vérifiée en direct contre `demo.borghelperrc`) —
**jamais un `403` distinct** : un `403` permettrait à l'appelant de distinguer « hors périmètre »
de « n'existe pas » par le seul code de statut, ce qui confirmerait indirectement qu'un chemin
existe quelque part dans l'archive même si l'appelant n'a pas le droit de le voir (voir
[Codes retour](#codes-retour)).

| Route | Hors périmètre | Forme imitée (chemin réellement introuvable) |
|---|---|---|
| `POST /restore` | `400`, `{"exitcode":1,"stdout":"","stderr":"Include pattern '<ftor>' never matched.\n"}` (`stdout` porte `"Archive sélectionnée (dernière) : <dernière archive>\n"` si `bid` est omis) | identique |
| `GET /restore/perms` | `200`, `{"exitcode":0,"stdout":"","stderr":""}` (`stdout` porte `"Archive (dernière) : <dernière archive>\n"` si `bid` est omis) | identique |
| `GET /download/file` | `200`, corps **vide** (0 octet), `Content-Disposition` présent (nom de fichier dérivé de `path`, inchangé) | identique |
| `GET /download/tar` | `200`, tar minimal valide **vide** (`Content-Disposition` présent, nom dérivé de `prefix`/`nick`) | identique |

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
nick — `500` non catché, jamais une réponse silencieusement dégradée. **Uniquement pour les
appelants qui détiennent un tier sur ce nick** : la résolution de périmètre court-circuite avant
même de lire `GROUPS_PATHS` pour un appelant sans aucun accès à ce nick (l'erreur ne le concerne
donc jamais — il reçoit `scope:null` normalement, `200`, comme s'il n'y avait pas de problème). La
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

#### Derrière un reverse proxy — IP client réelle dans les logs

`uvicorn.run(..., proxy_headers=True, forwarded_allow_ips=...)` (exécution directe
`python3 borgHelperWWW ...`) : l'IP client des logs d'accès (`INFO: <ip>:<port> - "GET ..."`) est prise
depuis l'en-tête `X-Forwarded-For` **plutôt que** l'IP de connexion TCP brute — mais **seulement** si
cette connexion TCP brute (le reverse proxy lui-même) figure dans `BORGHELPERWWW_TRUSTED_PROXIES` /
`--trusted-proxies` (défaut `127.0.0.1`, comme uvicorn lui-même — couvre le cas le plus courant : proxy
sur la même machine). Un client qui ne passe pas par une IP de confiance ne peut donc pas usurper son IP
en forgeant lui-même ce header. Élargir avec l'IP (ou le CIDR) réel du reverse proxy si celui-ci
n'écoute pas sur `127.0.0.1` (conteneur séparé, load-balancer distant, etc.) ; `*` fait confiance à
n'importe quelle IP amont (à réserver aux réseaux internes fermés).

Avec `uvicorn borgHelperWWW:app ...` (lancement externe) : `borgHelperWWW` ne construit plus le
serveur lui-même — `BORGHELPERWWW_TRUSTED_PROXIES` (CLI, variable, ou clé `trusted_proxies` du fichier
de conf) est **sans effet** dans ce mode. C'est le mécanisme natif d'uvicorn qui s'applique
directement : `--proxy-headers` (activé par défaut) et
`--forwarded-allow-ips <ip/cidr[,ip/cidr...]|*>`, sinon la variable d'environnement **native**
`FORWARDED_ALLOW_IPS` (sans préfixe `BORGHELPERWWW_`), sinon `127.0.0.1` par défaut — même défaut que
le mode d'exécution directe, donc même comportement dans les deux modes sans réglage supplémentaire
tant que le reverse proxy tourne sur la même machine.

```bash
# reverse proxy sur un hôte distinct (10.0.0.5)
export FORWARDED_ALLOW_IPS=10.0.0.5
uvicorn borgHelperWWW:app --host 0.0.0.0 --port 8000 --workers 2
# équivalent sans variable d'environnement :
uvicorn borgHelperWWW:app --host 0.0.0.0 --port 8000 --workers 2 --forwarded-allow-ips 10.0.0.5
```

Détail de la résolution (code source uvicorn) et exemples supplémentaires : voir
[TECHNICAL.md](TECHNICAL.md), section « borgHelperWWW — IP client réelle derrière un reverse proxy ».

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
3. **Détail d'un serveur** : champ **BORG_PASSPHRASE** à enregistrer pour la session (`sessionStorage`,
   par nick) — c'est ici, et seulement ici, qu'elle se saisit. Envoyée en `X-Borg-Passphrase` pour les
   actions qui en ont besoin (repérées par 🔑) ; les actions destructives (`Prune`, `DelBkp`, `Restore`,
   `IdxPurge`, `Init`) demandent une confirmation avant exécution. Le résultat brut (`exitcode`, `stdout`,
   `stderr`) s'affiche tel quel. Bouton **🗂 Explorer l'arborescence** dans le bandeau du serveur.
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
     documentée de `TreeHist`). Le bouton retour ramène à cette vue Historique plutôt qu'à la page de
     détail.
   - **🗑 Supprimer** (`DelBkp`) : supprime définitivement cette archive — confirmation, 🔑 passphrase.
   - Bouton **⚡ Lancer Prune** en haut de la vue (portée sur tout le dépôt, pas une archive précise,
     selon `KEEP_*` de la conf) — confirmation, 🔑 passphrase.
   - Sous le tableau, une carte **Évolution** avec trois graphiques Chart.js (chargés via
     `/repohistory`/`/archivehistory`, en plus du tableau `/report` ci-dessus) : taille du dépôt dans
     le temps (`unique_csize`/`total_size`/`total_csize`, un point par Bkp/Prune), gain Prune (delta
     calculé côté navigateur, jamais stocké), et métriques par archive dans le temps
     (`original_size`/`compressed_size`/`deduplicated_size`). Nick sans historique ou sans Prune :
     message à la place du graphique concerné.
     **Dépendance réseau** : ces graphiques chargent Chart.js depuis un CDN externe
     (`cdn.jsdelivr.net`) — contrairement au reste du projet, conçu pour fonctionner entièrement
     hors-ligne/en local, cette carte **Évolution** nécessite un accès réseau sortant vers ce CDN ; si
     le CDN est inaccessible, un message d'erreur s'affiche à la place des graphiques (le reste de la
     page reste fonctionnel).

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

Un endpoint par commande CLI (voir [Commandes](#commandes) ci-dessus pour le détail de chaque
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
empreinte = date de modification de tous les `cache.db`/`diff.db` concernés (tous les nicks connus si
le nick demandé est vide ou `ALL`). Un appel identique est servi depuis le cache **sans relancer
`borgHelper`** tant que cette empreinte n'a pas changé ; dès qu'un `Bkp`/`Index`/`Prune`/`DelBkp`/… a
modifié ces fichiers, l'empreinte change et l'appel suivant recalcule (et remet en cache) une réponse
fraîche. Cache en mémoire du processus (perdu au redémarrage), sans limite de durée mais borné à 500
entrées (purge totale au-delà, garde-fou anti-croissance illimitée). `GET /report` n'est concerné qu'en
mode `offline=true` (le mode en ligne interroge le dépôt en direct via `borg info`, non couvert par
cette empreinte).

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
résolution du périmètre (mtimes `cache.db`/`diff.db` du nick **et** mtime de `.borghelperrc` lui-même
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
| POST | `/index` | Index | |
| GET | `/search` | Search | ✓ |
| GET | `/filehist` | FileHist | ✓ |
| GET | `/treehist` | TreeHist | ✓ |
| GET | `/treefind` | TreeFind | ✓ |
| GET | `/duidx` | DuIdx | ✓ |
| GET | `/cacheinfo` | CacheInfo | ✓ |
| POST | `/cacheclean` | CacheClean | |
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

`exitcode != 0` ⇒ HTTP 400 (le détail reste dans le corps JSON — voir [Codes retour](#codes-retour)).

**⚠️ `POST /bkp` est asynchrone** (rupture de compatibilité, depuis 1.16.0) : contrairement à toutes
les autres routes ci-dessus, elle ne lance jamais `borgHelper -c Bkp` en l'attendant. Elle détache le
sous-processus (`start_new_session=True` — survit à un redémarrage de `borgHelperWWW` pendant la
sauvegarde) et répond dès son lancement confirmé, pas à la fin de la sauvegarde. `exitcode: 0` signifie
donc **« lancement réussi »**, jamais « sauvegarde réussie » — `stdout` contient un message
informatif (`"Sauvegarde démarrée pour <nick> (pid <pid>) — ..."`), jamais la sortie de `borgHelper`
lui-même. Le résultat réel (succès/échec) est capté par une table dédiée `bkp_status` (`diff.db`,
exclusive à `Bkp`) et réclamé périodiquement par une tâche de fond (« watcher », un par worker
uvicorn) — début **et** fin de sauvegarde — qui envoie une notification push réelle à chaque
abonnement concerné (voir [Envoi réel](#envoi-réel-story-2b) sous [Notifications
push](#notifications-push)). Intervalle d'interrogation et délai avant qu'une sauvegarde bloquée
soit traitée comme un échec : `BORGHELPERWWW_BKP_WATCHER_INTERVAL` (déf. 30s) et
`BORGHELPERWWW_BKP_STATUS_TIMEOUT` (déf. 21600s = 6h) — voir [Configuration](#configuration).

`GET /access` : protégée par `X-API-Key` (contrairement à `/version`), mais **jamais** par
l'autorisation par groupes elle-même — son seul but est de la refléter. Renvoie, pour **chaque**
nick connu, le niveau d'accès effectif de l'appelant (`level`) **et** son périmètre de chemin
résolu (`scope` — `null` = illimité, sinon liste de préfixes canonicalisés ; voir
[Autorisation par groupes](#autorisation-par-groupes-reverse-proxy-oidcauth_request)) :

```json
{"groups_auth_enabled": true, "nicks": {
  "demo-modules": {"level": "admin", "scope": null},
  "demo-usrlocal": {"level": "read", "scope": ["/var/www/client-x"]}
}}
```

`groups_auth_enabled: false` (autorisation par groupes désactivée) : `level:"admin"` et
`scope:null` pour chaque nick, sans cas particulier côté client.

⚠️ **Exception à la règle générale "toujours 200 pour un appel authentifié"** — mais **seulement
pour un appelant qui détient un tier (lecture/écriture/admin) sur le nick concerné** : `GROUPS_PATHS`
étant relu à chaque appel (voir plus haut), une valeur devenue ambiguë dans `.borghelperrc`
**pendant que le process tourne** fait échouer `/access` en `500` non catché pour le(s) nick(s)
concerné(s), plutôt que de dégrader silencieusement la réponse — c'est la seule route de ce projet
où une erreur de configuration en cours d'exécution est volontairement laissée remonter telle
quelle à l'appelant. Un appelant sans aucun tier sur ce nick ne voit jamais cette erreur : la
résolution de périmètre s'arrête avant même de lire `GROUPS_PATHS` pour lui, et reçoit
normalement `level:"none", scope:null` en `200`.

`groups_auth_enabled=false` (autorisation par groupes désactivée) : `"admin"` pour tous les nicks —
reflète l'absence de restriction par groupes, sans forme de réponse différente à gérer côté client.
C'est sur cette route que s'appuient à la fois l'affinage des badges de sécurité de l'interface web
(après connexion) et le filtrage de la liste des serveurs (voir [Autorisation par
groupes](#autorisation-par-groupes-reverse-proxy-oidcauth_request) ci-dessus).

### Notifications push

**Story 2a de `spec-notifications-push`** — stocke/expose les abonnements push navigateur et les clés
VAPID. Fichier dédié `push.db` (jamais `scopecache.db` — voir `BORGHELPERWWW_PUSH_DB` dans
[Configuration](#configuration)), clés VAPID (EC P-256) générées **une seule fois** au premier
démarrage, jamais régénérées ensuite. Clé publique VAPID exposée sur `GET /version` (déjà public, sans
clé API) : `{"vapid_public_key": "..."}` — nécessaire côté client pour
`PushManager.subscribe({applicationServerKey})` (Story 2b).

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
  "notify_start": true, "notify_end": true,
  "expires_in_days": 30
}'
```

| Paramètre | Défaut si absent | `null` explicite |
|-----------|-------------------|-------------------|
| `notify_start` | `false` | rejeté (`422`) — pas d'état « null » significatif pour un type de notification |
| `notify_end` | `true` | rejeté (`422`) — idem |
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
désabonner. Entre deux souscriptions, `scope_nicks` n'est en revanche **jamais** recalculé
dynamiquement (AD-4) — seule `PATCH /push/subscribe` peut ensuite modifier les préférences
(`notify_start`/`notify_end`/`expires_in_days`, jamais `scope_nicks`) :

```bash
curl -X PATCH http://localhost:8000/api/push/subscribe -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{
  "endpoint": "https://push.example.com/ep1", "notify_end": false, "expires_in_days": null
}'
# 404 explicite si l'endpoint est inconnu — jamais de création silencieuse (PATCH != POST)

curl -X DELETE "http://localhost:8000/api/push/subscribe?endpoint=https://push.example.com/ep1" -H "X-API-Key: $KEY"
# {"deleted": true} — un endpoint déjà absent renvoie {"deleted": false}, jamais un 404 bruyant
# (désabonnement explicite : « déjà absent » atteint déjà l'objectif)

curl "http://localhost:8000/api/push/subscriptions?endpoint=https://push.example.com/ep1" -H "X-API-Key: $KEY"
# {"subscriptions": [{...}]} — permet à l'UI d'afficher « vos abonnements actuels »
```

Réponse commune à `POST`/`PATCH`/`GET` (un ou plusieurs objets de cette forme) :

```json
{"id": 1, "endpoint": "...", "scope_nicks": ["demo-modules"],
 "notify_start": true, "notify_end": true,
 "expires_at": "2026-10-26 07:48:45", "created_at": "2026-09-26 07:48:45"}
```

Vérification interne dédiée : `borgHelperWWW -C ... --selftest` (voir `TECHNICAL.md` — génération
VAPID, CRUD, calcul d'expiration, clamp de `BORGHELPERWWW_PUSH_DEFAULT_EXPIRY_DAYS`, envoi push mocké,
sur des fichiers temporaires uniquement).

#### Envoi réel (Story 2b)

Le watcher `bkp_status` (voir `POST /bkp` asynchrone ci-dessus) ne se contente plus de journaliser :
à chaque réclamation CAS gagnée — **début** de sauvegarde (`started_at` écrit, aucun délai à
attendre) **et** fin (succès, échec, ou timeout AD-7) — il envoie un push réel (`pywebpush`) à chaque
abonnement de `push.db` dont `scope_nicks` contient le nick concerné, non expiré, avec le type
correspondant actif (`notify_start`/`notify_end`). Payload JSON (contenu affiché par le futur Service
Worker, Story 2c) : `{"nick":..., "event":"start"|"end", "result":"success"|"error"|null,
"timestamp":...}` — `result` toujours `null` pour un événement de début.

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
- **`POST /restore`/`GET /restore/perms` hors périmètre sans `bid` déclenchent encore un `borg list
  --short` par requête** (Story 2.1, `_oos_last_archive_line`/`_latest_archive`, pour construire la
  ligne d'archive de la réponse synthétique) : moins coûteux qu'avant cette story (qui exécutait
  l'extraction/le listing complet quel que soit le périmètre), mais un appel répété reste un vrai
  sous-processus `borg` par requête, pas gratuit — un appelant hors périmètre qui martèle ces deux
  routes sans `bid` continue de générer de la charge côté dépôt borg.

---

## Codes retour

| Code | Signification |
|------|---------------|
| 0 | Succès |
| 1 | Avertissement (rapport : sauvegarde trop ancienne) |
| 2 | Erreur borg |
| 3 | État incohérent (déjà monté, serveur inconnu…) |

---

## Exemples de crontab

```cron
# Backup quotidien à 2h — index (diff + snapshot + tailles) automatique
0 2 * * *  borgHelper -c Bkp -n mon-serveur

# Prune hebdomadaire le dimanche à 3h
0 3 * * 0  borgHelper -c Prune -n mon-serveur

# Rapport HTML envoyé par mail
30 6 * * *  borgHelper -c Report -n ALL -l | mail -s "Borg $(date +\%F)" admin@domaine.com
```

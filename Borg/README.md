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

# Clef explicite (keyfile mode, utile si plusieurs nicks partagent le même dépôt)
BORG_KEY_FILE    = /root/.config/borg/keys/abcdef123456

# Chemin de l'exécutable borg (défaut : 'borg' dans le PATH)
BORG_EXE                    = /usr/local/bin/borg1

# Borg divers
BORG_REMOTE_PATH            = borg1
BORG_RSH                    = ssh -p 2222
BORG_SHOW_SYSINFO           = no
BORG_RELOCATED_REPO_ACCESS_IS_OK = yes
```

Le nickname (nom de section) sert d'identifiant partout avec `-n`.

Répertoire de cache configurable via la clé `CACHE_DIR` dans la section `[DEFAULT]` :

```ini
[DEFAULT]
CACHE_DIR = /data/borgcache
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
| Résumé (par hôte) | `XX%nb / YY%B` | `3%nb / 8%B` |
| Détail (par archive) | `XX%nb / YY%B` | `5%nb / 12%B` |

Formule (identique résumé et détail) :
- dénominateur = état précédent = `nfiles − added + removed` (100%)
- `XX%nb` = `100 × (modified + removed) / précédent` — % de fichiers modifiés ou supprimés
- `YY%B` = même calcul sur les tailles disque

- `—` si l'archive n'est pas encore indexée

**Mode offline** (`-o`) — rapport sans appel borg, depuis `diff.db` uniquement :
- `nfiles` et tailles par archive disponibles si `archive_stats` est peuplée (après `Bkp` ou `Index`)
- `taille` (taille dédupliquée du dépôt entier) disponible si `repo_stats` est peuplée (après `Bkp`)
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
```

Nécessite le snapshot de l'archive peuplé (`Indexsnap`). Sinon : "Aucun fichier indexé — lancer 'indexsnap'".

---

### `DiffBkp`
Différences entre deux archives — un fichier par ligne.

```bash
borgHelper -c DiffBkp -n mon-serveur                          # 2 dernières archives
borgHelper -c DiffBkp -n mon-serveur -b archive-ancienne      # vs dernière
borgHelper -c DiffBkp -n mon-serveur -b archive-1,archive-2   # entre deux précises
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
```

Plage : `-b <archive>` (depuis), `-B <archive>` (jusqu'à), `-b ALL` (tout), sans les deux (dernière paire).

---

### `FileHist`
Historique complet des changements pour un chemin exact.

```bash
borgHelper -c FileHist -f /etc/nginx/nginx.conf -n mon-serveur
borgHelper -c FileHist -f /var/lib/postgresql -n ALL
```

---

### `TreeHist`
Contenu **direct** d'un répertoire (racine entière si `-f` omis) — jamais le contenu d'un
sous-répertoire — en **un seul tableau** : le répertoire courant lui-même apparaît en `.`, puis ses
enfants immédiats. Liste **toujours l'intégralité** du contenu (dernier snapshot indexé), comme un
`ls` enrichi, y compris les entrées sans événement dans la plage demandée (présentes, inchangées).

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

```bash
borgHelper -c TreeHist -n mon-serveur                        # contenu direct de la racine
borgHelper -c TreeHist -f /etc -n mon-serveur -b ALL          # contenu direct de /etc, tout l'historique
borgHelper -c TreeHist -f /var/lib/docker -n ALL -b ALL
```

Plage : `-b <archive>` (depuis), `-B <archive>` (jusqu'à), `-b ALL` (tout), sans les deux (dernière
paire indexée seulement — comme `Search`). Une entrée présente mais sans événement dans cette plage
affiche `aucun événement dans la plage` plutôt que d'être omise.

Genre/droits/propriétaire `inconnu (réindexer)`/`—` : entrée snapshotée avant l'ajout des colonnes
`type`/`mode`/`owner`. Se répare tout seul au **prochain `Bkp`** (indexation automatique activée) :
`IndexSnap` détecte une colonne manquante et force un resnapshot complet cette fois-là (message
« type/mode/propriétaire manquant… auto-réparation »), puis revient à l'incrémental normal ensuite. Pour
forcer immédiatement sans attendre un backup : `Index -F -S`.

---

### `TreeFind`
Recherche **récursive par nom** (pas le chemin complet) sous un préfixe (racine entière si omis), dans
le **dernier snapshot connu** — comme `TreeHist`, mais récursif, sans historique, et filtré par motif.

```bash
borgHelper -c TreeFind -n mon-serveur -m '*.log'                   # toute l'arborescence
borgHelper -c TreeFind -n mon-serveur -f /var/log -m 'error*'      # sous un préfixe précis
borgHelper -c TreeFind -n mon-serveur -m backup                    # sous-chaîne implicite (sans *)
borgHelper -c TreeFind -n mon-serveur -m '*.ko' -j                 # JSON
```

Motif minimal (`-m`) : `*` = n'importe quelle suite de caractères, `.` reste **littéral** (pas de sens
spécial) ; sans `*` (ni `?`) dans le motif, sous-chaîne implicite (comme `Search`). Comparaison sur le
**nom** de l'entrée uniquement (dernier segment du chemin), sensible à la casse.

Colonnes (mode texte) : `nom`, `genre`, `chemin` (complet), `droits`, `propriétaire` — dernier état
connu, même limitation que `TreeHist`. JSON (`-j`) :
`{nick:{archive,scope,pattern,matches:[{name,full_path,parent,is_dir,genre,mode,owner}]}}` — `parent`
est le répertoire contenant l'entrée, pratique pour y naviguer directement (utilisé par l'explorateur
de l'interface web).

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
```

---

### `IdxTop`
Top N arborescences du `diff_index` par nombre d'entrées — diagnostic d'un `diff.db` volumineux.

```bash
borgHelper -c IdxTop -n mon-serveur           # top 20, profondeur 3
borgHelper -c IdxTop -n mon-serveur -N 10     # top 10
borgHelper -c IdxTop -n mon-serveur -p 4      # profondeur 4
```

| Option | Description |
|--------|-------------|
| `-N <n>` | Nombre de lignes affichées (défaut : 20) |
| `-p <n>` | Profondeur de regroupement des chemins (défaut : 3) |

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
| `-x <pattern>` | Pattern explicite (préfixe ou glob avec `*?[`) |
| `-D` | Dry-run — affiche le volume sans supprimer |

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
```

| Option | Description |
|--------|-------------|
| `-N <n>` | Nombre de lignes affichées (défaut : 10) |
| `-p <n>` | Profondeur de regroupement (défaut : 3) |
| `-b <old,new>` | Paire d'archives explicite (défaut : dernière paire indexée) |

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
```

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
`borgHelperWWW_ui.html`, obligatoirement à côté du script). Titre **borgHelperWWW** dans l'en-tête,
lien vers `/`, visible sur toutes les pages.

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
active sur cette instance).

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

| Méthode | Route | Commande CLI | Cache |
|---------|-------|--------------|:---:|
| GET | `/version` | *(aucune — spécifique à borgHelperWWW)* | |
| GET | `/healthz` | *(aucune — liveness, spécifique à borgHelperWWW)* | |
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
| POST | `/bkp` | Bkp | |
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
| POST | `/idxpurge` | IdxPurge ⚡ | |

`DelBkp` et `Prune` (destruction de sauvegardes) reçoivent `403 Forbidden` tant que
`BORGHELPERWWW_ALLOW_DESTRUCTIVE` n'est pas activé (interdit par défaut — voir
[Configuration](#configuration)) ; `IdxPurge`, bien que marqué ⚡ (irréversible sur l'index local, pas
sur les sauvegardes elles-mêmes), n'est **pas** concerné par ce réglage.

Réponse (`CommandResult`) commune à tous les endpoints ci-dessus :

```json
{"exitcode": 0, "stdout": "...", "stderr": "..."}
```

`exitcode != 0` ⇒ HTTP 400 (le détail reste dans le corps JSON — voir [Codes retour](#codes-retour)).

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

### Limites connues

- Exécution synchrone : `Bkp`/`Prune`/`Index` sur un gros dépôt occupent un worker HTTP pendant toute
  leur durée — pas de file d'attente/job asynchrone. Prévoir `--workers` et un timeout côté reverse-proxy.
- Le budget d'authentification est volontairement simple (une seule clé partagée). Pour un usage
  multi-utilisateurs avec traçabilité par appelant, ajouter une couche d'auth dédiée devant l'API.

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

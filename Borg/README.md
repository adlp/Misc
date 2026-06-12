# borgHelper  `v1.0.43`

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
Liste les archives disponibles.

```bash
borgHelper -c LstBkp -n mon-serveur
```

---

### `LstBkpFls`
Liste les fichiers d'une archive.

```bash
borgHelper -c LstBkpFls -n mon-serveur
borgHelper -c LstBkpFls -n mon-serveur -b mon-serveur-root-2025-04-02T213004
```

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

# borgHelper — Fonctionnement technique

Ce document décrit l'architecture interne de borgHelper : fichiers de données, schémas SQLite, indexes, et comportements internes.

→ Usage CLI : [README.md](README.md)  
→ Usage librairie : [LIBRARY.md](LIBRARY.md)

---

## Architecture

borgHelper est structuré en trois couches :

| Classe | Rôle |
|--------|------|
| `BorgHelperDB` | Toutes les opérations SQLite (cache.db + diff.db) |
| `BorgRunner` | Subprocess borg + lecture/écriture borghelperrc |
| `BorgHelper` | Services haut niveau — orchestre DB et Borg |

---

## Fichiers de données

| Fichier | Contenu |
|---------|---------|
| `~/.borghelperrc` | Configuration des dépôts (INI) |
| `~/.cache/borghelper/<conf>-<nick>-cache.db` | Cache des appels `borg info/list` (SQLite) |
| `~/.cache/borghelper/<conf>-<nick>-diff.db` | Index des diffs, snapshots et stats d'archives (SQLite) |
| `~/.cache/borghelper/<conf>-<repo_sanitisé>-priority.lock` | Lock PID posé par `Bkp`/`Restore` — signal d'interruption pour `Index` sur le même dépôt |
| `~/.cache/borghelper/<conf>-<repo_sanitisé>-index-running.lock` | Lock PID posé par `Index` pendant Phase 2 — `Bkp`/`Restore` attendent sa disparition avant `borg create`/`borg extract` |

- `<conf>` = basename sanitisé du fichier de configuration (ex : `borghelperrc` pour `~/.borghelperrc`)
- `<nick>` = identifiant du dépôt (ou valeur de `DB_NAME` si définie dans la section) — un fichier par dépôt
- Répertoire configurable via `CACHE_DIR` dans la section `[DEFAULT]` du borghelperrc

---

## Base de données `cache.db`

Cache des résultats `borg info` et `borg prune --dry-run`, invalidé automatiquement par `last_modified` du dépôt.

- Purge automatique après `DelBkp` et `Prune`
- Nettoyage manuel : `CacheClean`
- Un seul appel `borg info` par commande grâce au cache partagé (`last_modified`)

```mermaid
erDiagram
    cachejsonboexlm {
        INTEGER id PK
        TEXT nom "nick ou nick:prune"
        TEXT lastmodified "last_modified du dépôt borg"
        TEXT details "JSON sérialisé"
    }
```

Contrainte : `UNIQUE(nom, lastmodified)`.

**Entrées :**
- `nom = nick` → résultat de `borg info --json --glob-archives`
- `nom = nick:prune` → liste des archives à pruner (dry-run)

---

## Base de données `diff.db`

Index des diffs inter-archives, snapshots du dernier état, métadonnées de taille et statistiques des fichiers exclus par les filtres d'indexation.

### Comportement WAL et auto-vacuum

- `PRAGMA journal_mode=WAL` : lectures non-bloquantes pendant les écritures (important pour les diff parallèles)
- `PRAGMA auto_vacuum=INCREMENTAL` : recupération progressive des pages supprimées
- `VACUUM` explicite après `Prune` pour récupérer l'espace immédiatement

### Tables

#### `diff_index`
Stocke chaque événement de fichier entre deux archives consécutives.

- Peuplée par `Index` (via `borg diff`) et par `Bkp` (via `--list`)
- `change_type` : `added`, `removed`, `modified`, `C` (permissions/proprio), `B` (lien cassé), `T` (type changé)
- `size_before` / `size_after` : `NULL` selon le type de changement

#### `diff_indexed_pairs`
Sentinelle d'idempotence pour les diffs — une ligne par paire (archive_old, archive_new) indexée.  
Empêche de ré-indexer une paire déjà traitée. Purge des lignes orphelines par `Prune`.

#### `snapshot_file`
Dictionnaire global des chemins de fichiers avec leur taille et mtime.  
Contrainte `UNIQUE(nick, path)` — le même chemin n'est stocké qu'une seule fois par nick (déduplication).

#### `archive_snapshot`
Table mince : associe une archive à ses fichiers via `file_id → snapshot_file.id`.  
Réduit la duplication des chaînes de chemin quand le même fichier apparaît dans plusieurs archives consécutives.

#### `archive_snapshot_indexed`
Sentinelle d'idempotence pour les snapshots — une ligne par archive dont le snapshot est complet.

#### `archive_stats`
Métadonnées de taille par archive (original, compressé, dédupliqué, nfiles, durée).  
Peuplée par `Bkp` (depuis le JSON borg) et par `Index` (via `borg info --json`).  
Utilisée par `Report -o` pour produire un rapport complet sans aucun appel borg.

#### `diff_excluded_stats`
Agrégat des fichiers filtrés par `IDX_INCLUDE`/`IDX_EXCLUDE` lors de l'indexation des diffs.  
Une ligne par (nick, archive_old, archive_new, change_type) : `file_count` + `total_size`.  
Peuplée par `Index` et `Bkp` (taille non disponible pour `Bkp` car `--list` ne retourne pas les tailles).  
Permet de savoir combien de fichiers ont été intentionnellement exclus de l'index et quelle taille ils représentent.

#### `snap_excluded_stats`
Agrégat des fichiers filtrés lors de l'indexation du snapshot de la dernière archive.  
Une ligne par (nick, archive) : `file_count` + `total_size`.  
Peuplée par `IndexSnap` (`-S`) et en fin d'`Index` normal.

### Vue `archive_snapshot_v`

```sql
CREATE VIEW archive_snapshot_v AS
    SELECT s.nick, s.archive, s.archive_date, sf.path, sf.size, sf.mtime
    FROM archive_snapshot s
    JOIN snapshot_file sf ON sf.id = s.file_id;
```

Utilisée par `Search`, `FileHist`, `DuIdx`, `Restore` — expose la jointure de façon transparente.

### Schéma complet

```mermaid
erDiagram
    diff_index {
        INTEGER id PK
        TEXT nick
        TEXT archive_old
        TEXT archive_new
        TEXT archive_new_date "ISO datetime"
        TEXT change_type "added|removed|modified|C|B|T"
        TEXT path
        INTEGER size_before "NULL si added"
        INTEGER size_after "NULL si removed"
        TEXT indexed_at
    }

    diff_indexed_pairs {
        INTEGER id PK
        TEXT nick
        TEXT archive_old
        TEXT archive_new "UNIQUE(nick,archive_old,archive_new)"
        INTEGER entry_count
        TEXT indexed_at
    }

    snapshot_file {
        INTEGER id PK
        TEXT nick
        TEXT path "UNIQUE(nick, path)"
        INTEGER size
        TEXT mtime "ISO datetime"
    }

    archive_snapshot {
        TEXT nick "PK partielle"
        TEXT archive "PK partielle"
        TEXT archive_date
        INTEGER file_id FK
    }

    archive_snapshot_indexed {
        TEXT nick "UNIQUE(nick, archive)"
        TEXT archive
        INTEGER entry_count
        TEXT indexed_at
    }

    archive_stats {
        TEXT nick PK
        TEXT archive PK
        TEXT archive_date
        REAL duration
        INTEGER original_size
        INTEGER compressed_size
        INTEGER deduplicated_size
        INTEGER nfiles
    }

    diff_excluded_stats {
        TEXT nick PK
        TEXT archive_old PK
        TEXT archive_new PK
        TEXT change_type PK
        INTEGER file_count
        INTEGER total_size
    }

    snap_excluded_stats {
        TEXT nick PK
        TEXT archive PK
        INTEGER file_count
        INTEGER total_size
    }

    snapshot_file ||--o{ archive_snapshot : "file_id → id"
```

### Indexes

| Table | Index | Colonnes | Requête cible |
|-------|-------|----------|---------------|
| `diff_index` | `idx_diff_nick_path` | `(nick, path)` | Search, FileHist |
| `diff_index` | `idx_diff_nick_archive` | `(nick, archive_new)` | DiffBkp, Report |
| `diff_index` | `idx_diff_nick_newtype` | `(nick, archive_new, change_type)` | stats Report |
| `diff_index` | `idx_diff_nick_date` | `(nick, archive_new_date)` | filtres plage `-b`/`-B` |
| `diff_indexed_pairs` | `idx_pairs_nick` | `(nick)` | suppressions Prune |
| `snapshot_file` | `idx_snapfile_nick_path` | `(nick, path)` | insertion / lookup |
| `archive_snapshot` | `idx_snap_nick_archive` | `(nick, archive)` | suppressions Prune |
| `archive_stats` | `idx_astats_nick` | `(nick)` | Report -o, suppressions Prune |
| `diff_excluded_stats` | `idx_exclu_nick_arch` | `(nick, archive_new)` | consultation stats exclus |

---

## Flux d'indexation

### `Bkp` (indexation automatique)

```
set_priority_lock(nick)                                  → <nick>-priority.lock (PID)
    ↓
borg create --list --filter AMCBTd
    ↓
stderr parsé → _bkp_parse_list() → entrées de type added/modified/removed/C/B/T
    ↓
filtre IDX_INCLUDE/IDX_EXCLUDE par fichier (en RAM)
    ├── inclus  → store_diff_entries()       → diff_index + diff_indexed_pairs
    └── exclus  → store_excluded_diff_stats() → diff_excluded_stats (count seul, taille = 0)
store_archive_stats(nick, archive_new, ...)              → archive_stats
indexsnap(nick)                                          → snapshot_file + archive_snapshot
                                                            + snap_excluded_stats
    ↓
finally: clear_priority_lock(nick)                       → supprime le lock
```

### `Index` (indexation manuelle, parallèle)

```
borg list --json
    ↓
Phase 1 : déterminer les paires manquantes (diff_indexed_pairs)
          si force : purge diff_index + diff_indexed_pairs + diff_excluded_stats
    ↓
Phase 2 : ThreadPoolExecutor(IDX_WORKERS) → borg diff par paire en parallèle
          pour chaque ligne : filtre IDX_INCLUDE/IDX_EXCLUDE
          compteurs exclus accumulés en RAM jusqu'à fin du diff
    ↓
Phase 3 : insert groupé (connexion SQLite unique)
          → diff_index + diff_indexed_pairs
          → diff_excluded_stats (count + total_size par change_type)
    ↓
DIFF_KEEP : purge des paires au-delà de la limite
    ↓
borg info --json (seulement si archive_stats manquantes) → archive_stats
    ↓
indexsnap() → snapshot_file + archive_snapshot + snap_excluded_stats
```

---

## Gestion de la taille de `diff.db`

Pour les dépôts à fort volume (plusieurs GB de diff.db) :

| Levier | Paramètre | Effet |
|--------|-----------|-------|
| Purge automatique | `DIFF_KEEP = N` | Supprime les paires au-delà des N dernières après chaque Index |
| Filtre chemins | `IDX_INCLUDE` / `IDX_EXCLUDE` | Réduit le nombre d'entrées indexées ; stats des exclus dans `diff_excluded_stats` / `snap_excluded_stats` |
| Vacuum post-prune | automatique | Récupère l'espace après suppression d'archives |
| Auto-vacuum | `PRAGMA auto_vacuum=INCREMENTAL` | Récupération progressive en continu |

---

## Filtres d'indexation : patterns glob

`IDX_INCLUDE` et `IDX_EXCLUDE` supportent deux syntaxes :

| Syntaxe | Exemple | Comportement |
|---------|---------|--------------|
| Préfixe plain | `/home/`, `/etc` | `path.startswith(pattern)` — tout chemin commençant par ce préfixe |
| Pattern glob | `*.bak`, `/home/*/.bash_history` | `fnmatch(path, pattern)` — `*` matche toute séquence **y compris** `/` |

La distinction est automatique : si le pattern contient `*`, `?` ou `[`, fnmatch est utilisé ; sinon startswith.

**Exemples :**

```ini
IDX_EXCLUDE = *.bak *.tmp *.swp         # tous les .bak/.tmp/.swp dans toute arborescence
IDX_EXCLUDE = /home/*/.bash_history     # .bash_history dans tout sous-répertoire de /home/
IDX_EXCLUDE = /home/*/.cache/*          # tout le cache utilisateur
IDX_INCLUDE = /etc /home /root          # préfixes plains (pas de glob)
IDX_INCLUDE = /home/*/documents/*       # uniquement les documents des utilisateurs
```

> Note : `fnmatch` en Python traite `*` comme "n'importe quelle séquence de caractères **incluant** `/`". `/home/*/.bash_history` matche donc `/home/user/.bash_history` ET `/home/user/subdir/.bash_history`.

---

## Priorité Bkp/Restore sur Index

`Bkp` et `Restore` sont prioritaires sur `Index` — si une indexation tourne en parallèle sur le même dépôt, elle s'interrompt proprement.

### Mécanisme — lock PID

Le lock est keyed sur `BORG_REPO` (sanitisé), pas sur le nick. Tous les nicks pointant le même dépôt borg partagent donc le même fichier de lock — `Bkp` sur `nick-A` interrompt `Index` sur `nick-B` si `BORG_REPO` identique.

```
Bkp / Restore démarre
    ↓
set_priority_lock(nick)    → <repo>-priority.lock (PID)  ← signal à Index de s'arrêter
    ↓
wait_index_idle(nick)      → poll 1s jusqu'à 120s
    ├── <repo>-index-running.lock absent / PID mort → continue
    └── PID vivant → attente... (Index en cours de terminer ses diffs actifs)
    ↓
opération borg (create / extract)   ← plus de conflit de verrou borg
    ↓
finally: clear_priority_lock(nick)  → supprime priority.lock
```

```
Index Phase 2
    ↓
set_index_running_lock(nick)  → <repo>-index-running.lock (PID)
    ↓
ThreadPoolExecutor — borg diff en parallèle
    après chaque diff : check_priority_lock(nick)
    ├── absent           → continue
    ├── PID vivant       → annule futures en attente, interrupted=True
    │                      les diffs actifs terminent proprement
    └── PID mort (stale) → supprime, continue
    ↓
finally: clear_index_running_lock(nick)  → <repo>-index-running.lock supprimé
         ← Bkp/Restore débloqué ici
    ↓
Phase 3 : commit des résultats (paires annulées non commitées → reprises au prochain Index)
```

### Reprise transparente

`Index` est incrémental : `diff_indexed_pairs` garde la sentinelle de chaque paire indexée. Après interruption, relancer `Index` saute les paires déjà traitées et reprend les suivantes.

---

## Migration de schéma

`ensure_diff_db()` détecte automatiquement l'ancien schéma de `archive_snapshot` (colonne `path` directe) et migre vers le schéma déduplication (`file_id → snapshot_file`) au premier lancement après mise à jour.

---

## Sentry

Intégration optionnelle pour remonter les erreurs.  
DSN lu dans l'ordre :

1. Variable d'environnement `BORGHELPERC_SENTRY_DSN`
2. Fichier pointé par `BORGHELPERC_SENTRY_FILE`
3. Fichier `/usr/local/etc/borghelper-sentry`

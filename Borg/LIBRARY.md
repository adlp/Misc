# borgHelper — Usage comme librairie Python

borgHelper est utilisable comme module Python en plus de son interface CLI.  
L'architecture 3 couches permet d'intégrer les opérations borg dans ses propres scripts.

→ Usage CLI : [README.md](README.md)  
→ Fonctionnement interne : [TECHNICAL.md](TECHNICAL.md)

---

## Installation

`borgHelper.py` est un symlink vers `borgHelper` — placer les deux dans le même répertoire, puis ajouter ce répertoire au `PYTHONPATH` :

```bash
# Si borgHelper est dans /usr/local/bin
ln -sf /usr/local/bin/borgHelper /usr/local/bin/borgHelper.py
export PYTHONPATH=/usr/local/bin:$PYTHONPATH

# Ou en local
ln -sf borgHelper borgHelper.py
export PYTHONPATH=$(pwd):$PYTHONPATH
```

Import :

```python
from borgHelper import BorgHelper, BorgHelperDB, BorgRunner
```

---

## Les trois classes

### `BorgHelper` — couche haut niveau

Point d'entrée principal. Orchestre `BorgHelperDB` et `BorgRunner`.

```python
bh = BorgHelper(cfgfile=None, cache_dir=None)
# cfgfile  : chemin vers le borghelperrc (défaut : ~/.borghelperrc)
# cache_dir: répertoire des DB SQLite (défaut : valeur CACHE_DIR du borghelperrc ou ~/.cache/borghelper)
```

Attributs :
- `bh.db`   — instance `BorgHelperDB`
- `bh.borg` — instance `BorgRunner`

### `BorgHelperDB` — couche SQLite

Toutes les opérations sur `cache.db` et `diff.db`. Pas d'appel borg.

```python
db = BorgHelperDB(cache_dir, db_prefix, cfg_reader=None)
```

### `BorgRunner` — couche borg

Lecture du borghelperrc, exécution des commandes borg via subprocess.

```python
runner = BorgRunner(cfgfile=None)
```

---

## Exemples — `BorgHelper`

### Backup et indexation

```python
from borgHelper import BorgHelper

bh = BorgHelper('/etc/borghelperrc')

# Backup + indexation automatique
bh.backup('mon-serveur')

# Backup sans indexation
bh.backup('mon-serveur', no_index=True)

# Indexation manuelle (après backup sans -I)
bh.index('mon-serveur')

# Forcer la réindexation complète
bh.index('mon-serveur', force=True)

# Snapshot seul (sans recalculer les diffs)
bh.indexsnap('mon-serveur')
```

### Rapport

```python
# Rapport ASCII (affiche dans stdout)
bh.report('mon-serveur')

# Rapport multi-nicks
bh.report('serveur1,serveur2,serveur3')

# Rapport offline (sans appel borg, depuis diff.db)
bh.report_offline('mon-serveur')

# Rapport offline, N dernières archives
bh.report_offline('mon-serveur', maxp=5)

# Rapport HTML
bh.report('mon-serveur', htrep=True)
```

### Recherche et historique

```python
# Chercher un fichier par pattern
bh.search('mon-serveur', '*.conf')
bh.search('mon-serveur', '/etc/nginx*')

# Historique d'un chemin exact
bh.filehist('mon-serveur', '/etc/nginx/nginx.conf')

# Résumé du-like
bh.duidx('mon-serveur')                    # global
bh.duidx('mon-serveur', pattern='home/*')  # par répertoire sous home/
bh.duidx('mon-serveur', pattern='*.log', as_json=True)
```

### Prune

```python
# Prune + compact + nettoyage index
bh.prune('mon-serveur')

# Multi-nicks
for nick in bh.borg.cfgreadnicks().split(','):
    bh.prune(nick)
```

### Restauration

```python
# Restaurer vers un répertoire
bh.restore('mon-serveur', bid=None, ftor='etc/nginx/nginx.conf', where='/tmp/restore')

# Archive précise
bh.restore('mon-serveur', bid='mon-serveur-root-2026-06-05T02:00:04',
           ftor='etc/nginx/nginx.conf', where='/tmp/restore')

# Glob → tar
bh.restore('mon-serveur', bid=None, ftor='etc/nginx/*.conf', where='/tmp/nginx.tar')

# Glob → tgz plat
bh.restore('mon-serveur', bid=None, ftor='home/user/*.log',
           where='/tmp/logs.tgz', flat=True)
```

### Gestion des archives

```python
# Lister les archives disponibles
bh.list_backups('mon-serveur')

# Différence entre deux archives
bh.diffbkp('mon-serveur')                                   # 2 dernières
bh.diffbkp('mon-serveur', bidun='archive-1', bideux='archive-2')

# Supprimer une archive
bh.delbkp('mon-serveur', 'mon-serveur-root-2026-01-01T02:00:00')

# Monter / démonter
bh.mount('mon-serveur')
bh.umount('mon-serveur')
```

### Cache

```python
# Infos cache
bh.cache_info('mon-serveur')
bh.cache_info()  # tous les nicks

# Nettoyage cache
bh.cache_clean('mon-serveur')
```

---

## Exemples — accès direct aux couches

### Lire la configuration

```python
bh = BorgHelper()

# Lire la conf d'un nick
cfg = bh.borg.cfgread('mon-serveur')
print(cfg['BORG_REPO'])
print(cfg['GLOB_ARCH'])

# Lister tous les nicks
nicks = bh.borg.cfgreadnicks()
for nick in nicks.split(','):
    print(nick)
```

### Exécuter borg directement

```python
# Appel borg brut (retourne dict {stdout, stderr, exitcode})
rb = bh.borg.boex('mon-serveur', ['list', '--json'])
archives = rb['stdout'][0]['archives']
for a in archives:
    print(a['name'], a['start'])

# last_modified du dépôt
lm = bh.borg._boex_last_modified('mon-serveur')
print('Dernière modification :', lm)

# Dernières N archives
last2 = bh.borg.getlastbkp('mon-serveur', nbl=2)
print('Avant-dernière :', last2[0])
print('Dernière :', last2[1])
```

### Interroger le diff.db directement

```python
import sqlite3

bh = BorgHelper()

# Chemin du diff.db d'un nick
db_path = bh.db.get_diff_db('mon-serveur')

# Statistiques par archive
stats = bh.db._diff_stats_for_nick('mon-serveur')
for archive, s in sorted(stats.items()):
    print(f"{archive}: +{s['added']} -{s['removed']} ~{s['modified']}")

# Vérifier si une paire est indexée
indexed = bh.db.is_diff_pair_indexed('mon-serveur', 'archive-old', 'archive-new')
print('Indexé :', indexed)

# Requête SQL directe
conn = sqlite3.connect(db_path)
rows = conn.execute(
    "SELECT path, COUNT(*) as nb FROM diff_index WHERE nick=? AND change_type='added' "
    "GROUP BY path ORDER BY nb DESC LIMIT 10",
    ('mon-serveur',)
).fetchall()
for path, nb in rows:
    print(nb, path)
conn.close()
```

### Consulter les fichiers exclus des filtres d'indexation

```python
import sqlite3
from borgHelper import BorgHelper

bh = BorgHelper()

# Stats exclus du diff (par paire d'archives)
db_path = bh.db.get_diff_db('mon-serveur')
conn = sqlite3.connect(db_path)

# Vue d'ensemble : total exclus par change_type sur toutes les paires
rows = conn.execute(
    "SELECT change_type, SUM(file_count) as nb, SUM(total_size) as sz "
    "FROM diff_excluded_stats WHERE nick=? GROUP BY change_type",
    ('mon-serveur',)
).fetchall()
for ct, nb, sz in rows:
    from borgHelper import convert_octets_readable
    print(f"  exclus {ct}: {nb} fichiers, {convert_octets_readable(sz or 0)}")

# Détail par archive
rows = conn.execute(
    "SELECT archive_new, change_type, file_count, total_size "
    "FROM diff_excluded_stats WHERE nick=? ORDER BY archive_new, change_type",
    ('mon-serveur',)
).fetchall()

# Stats exclus du snapshot (dernière archive)
row = conn.execute(
    "SELECT archive, file_count, total_size FROM snap_excluded_stats WHERE nick=? "
    "ORDER BY archive DESC LIMIT 1",
    ('mon-serveur',)
).fetchone()
if row:
    arch, cnt, sz = row
    print(f"Snapshot {arch}: {cnt} fichiers exclus ({convert_octets_readable(sz or 0)})")

conn.close()
```

### Stocker des stats depuis borg info

```python
bh = BorgHelper()

# Récupérer et stocker les stats d'une archive
rb = bh.borg.boex('mon-serveur', ['info', '--json', '--glob-archives', 'mon-serveur-root-*'])
for a in rb['stdout'][0]['archives']:
    st = a.get('stats', {})
    bh.db.store_archive_stats(
        nick='mon-serveur',
        archive=a['name'],
        archive_date=a.get('start'),
        duration=a.get('duration'),
        original_size=st.get('original_size'),
        compressed_size=st.get('compressed_size'),
        deduplicated_size=st.get('deduplicated_size'),
        nfiles=st.get('nfiles'),
    )
```

---

## Intégration dans un script de supervision

```python
#!/usr/bin/env python3
"""Vérifie que tous les dépôts ont été sauvegardés dans les dernières 26 heures."""

import sys
from borgHelper import BorgHelper

bh = BorgHelper()
nicks = bh.borg.cfgreadnicks().split(',')
problems = []

for nick in nicks:
    try:
        lm = bh.borg._boex_last_modified(nick)
        from borgHelper import d2DateNSince
        info = d2DateNSince(lm)
        if info['since'] > 26:
            problems.append(f"{nick}: {info['since']:.1f}h depuis dernier backup")
    except Exception as e:
        problems.append(f"{nick}: erreur — {e}")

if problems:
    print("PROBLÈMES DÉTECTÉS:")
    for p in problems:
        print(" -", p)
    sys.exit(1)

print(f"OK — {len(nicks)} dépôt(s) à jour")
sys.exit(0)
```

---

## Référence des méthodes publiques de `BorgHelper`

| Méthode | Description |
|---------|-------------|
| `backup(nick, no_index, debug)` | Lance `borg create` + indexation |
| `prune(nick, dryrun, debug)` | `borg prune` + compact + nettoyage index |
| `index(nick, debug, db_path, force)` | Indexe les diffs, parallèle |
| `indexsnap(nick, debug, db_path, force)` | Snapshot de la dernière archive |
| `report(nicks, htrep, debug, maxp, as_json)` | Rapport avec appels borg |
| `report_offline(nicks, htrep, debug, maxp, as_json)` | Rapport depuis diff.db uniquement — même résumé que `report`, toutes machines affichées même sans index |
| `search(nick, pattern, archive_from, archive_to, debug)` | Recherche par chemin |
| `filehist(nick, path, archive_from, archive_to, debug)` | Historique d'un chemin |
| `duidx(nick, pattern, sort_by, reverse, as_json, ...)` | Résumé taille/type |
| `diffbkp(nick, bidun, bideux, debug)` | Différences entre deux archives — `+`/`-`/`=` par ligne, résumé compteurs |
| `restore(nick, bid, ftor, where, flat, debug)` | Restauration |
| `listperms(nick, bid, ftor, debug)` | Liste droits fichiers sans restaurer |
| `list_backups(nick, debug)` | Liste les archives |
| `list_files(nick, bid, debug)` | Liste fichiers d'une archive |
| `delbkp(nick, bid, debug)` | Supprime une archive |
| `mount(nick, bid, debug)` | Monte via FUSE |
| `umount(nick, debug)` | Démonte |
| `key(nicks, debug)` | Exporte la clef |
| `init_repo(nick, debug)` | Initialise un dépôt |
| `stats(nick, debug)` | État de montage |
| `cache_info(nick, debug)` | Affiche le cache |
| `cache_clean(nick, debug)` | Nettoie le cache |

### Méthodes `BorgHelperDB` utiles en lecture

| Méthode | Description |
|---------|-------------|
| `get_diff_db(nick)` | Chemin du diff.db d'un nick |
| `get_cache_db(nick)` | Chemin du cache.db d'un nick |
| `is_diff_pair_indexed(nick, a_old, a_new)` | Vérifie si une paire est indexée |
| `is_archive_snapshot_indexed(nick, archive)` | Vérifie si le snapshot est indexé |
| `_diff_stats_for_nick(nick)` | Stats de mouvement par archive (used by Report) |
| `store_excluded_diff_stats(nick, a_old, a_new, exclu, db_path)` | Stocke stats fichiers exclus d'une paire |
| `store_excluded_snap_stats(nick, archive, count, size, db_path)` | Stocke stats fichiers exclus d'un snapshot |
| `_with_lock_retry(fn, max_wait=300)` | Exécute `fn()`, retente toutes les 2 s si `OperationalError: database is locked`, jusqu'à `max_wait` secondes |
| `set_priority_lock(nick)` | Pose le lock prioritaire (écrit le PID) — appelé par `Bkp`/`Restore` |
| `clear_priority_lock(nick)` | Supprime le lock prioritaire |
| `check_priority_lock(nick)` | `True` si un processus prioritaire vivant tient le lock (stale → auto-supprimé) |
| `set_index_running_lock(nick)` | Pose le lock "Index actif" pendant Phase 2 — appelé par `Index` |
| `clear_index_running_lock(nick)` | Supprime le lock "Index actif" |
| `check_index_running(nick)` | `True` si un Index vivant tient le running lock (stale → auto-supprimé) |
| `wait_index_idle(nick, timeout=120)` | Attend jusqu'à `timeout` s que `Index` libère ses verrous borg |

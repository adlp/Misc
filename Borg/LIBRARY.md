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
from borgHelper import BorgHelper, BorgHelperDB, BorgRunner, SchemaVersionError
```

### Exception `SchemaVersionError`

Levée par `ensure_diff_db()` / `ensure_cache_db()` si la `schema_version` stockée en DB est supérieure à la constante attendue par le script (DB créée par une version plus récente). À intercepter si l'opération doit continuer sans indexation :

```python
try:
    db.ensure_diff_db(db_path)
except SchemaVersionError as e:
    print(f"[WARN] DB incompatible, indexation ignorée : {e}")
```

`ensure_diff_db(db_path, create=True, nick=None)` / `ensure_cache_db(db_path, create=True, nick=None)` — 1.0.168 :
avec `nick`, une base **neuve** (fichier sans schéma) est créée chiffrée (`siv1`, schéma et en-tête dans une même
transaction) si la config du nick a `DB_ENCRYPT` actif, une passphrase et pas de `DB_NAME` (jamais un fantôme
`.rebuild`) ; sans `nick` ou base existante : inchangé. Depuis 1.0.102, `create=False`
réserve la création (fichier, schéma, `enc_header`) aux créateurs légitimes (`Index`, `Bkp`, `indexsnap`, `DbEncrypt`) :
un appelant de lecture qui passe `create=False` sur une base absente ou sans schéma n'écrit rien sur disque et doit
lui-même gérer l'absence de table (`sqlite3.OperationalError: no such table`) comme un index vide.
1.0.166 : avec `create=False`, l'entretien d'une base existante (paliers de migration, vue, tampons de version) attend au
plus 2 s le verrou d'écriture ; s'il est tenu par un autre processus, la fonction rend la main sans erreur, sans migrer ni
tamponner (base lue telle quelle par l'appelant) et ne réessaie pas pendant 60 s pour ce `BorgHelperDB` ; seule une base
d'un schéma plus récent lève encore `SchemaVersionError`. `create=True` : inchangé (60 s).

### Exceptions du chiffrement de base

`DbKeyError` (passphrase absente ou fausse pour une base chiffrée), `DbModeError` (mode de la base changé depuis
l'ouverture, ou base `migrating` ouverte avec un rôle non-admin depuis 1.0.104), `DbTamperError` (en-tête incohérent,
ex. `enc_header` avec `path_enc='plain'`), `DbCodecError` (chemin ou blob stocké non canonique, tag/MAC invalide).
Elles **n'héritent pas de `sqlite3.Error`** : un `except sqlite3.Error` ne les avale jamais. Une base `plain` ne lève
aucune de ces erreurs (mode toujours valide, AD-2/AD-5). Depuis 1.0.104 (`DbEncrypt`/`DbDecrypt`/`DbRekey`, voir
plus bas), une base réelle peut effectivement être `siv1` — jusque-là `DB_ENCRYPT` était sans effet à l'exécution.
La clé de chiffrement est dérivée de `BORG_PASSPHRASE` : `DbRekey` ré-enveloppe la DEK avec une nouvelle KEK (même
passphrase, nouveau sel/nonce) — ce n'est pas un mécanisme de changement de `BORG_PASSPHRASE` (voir TECHNICAL.md).

`DbModeError` (depuis 1.0.102) : levée par `_write_mode_check(conn)`, appelée en tout premier par les sites qui
écrivent un chemin (`store_diff_entries`, `store_archive_snapshot`, `_indexsnap_incremental`, le bloc d'écriture
inline de `index()`) si le mode relu dans la transaction (`db_meta.enc_header`) diffère du mode constaté à l'ouverture
de la connexion (`conn.mode`). Pas un verrou d'exclusion mutuelle, une garde de cohérence contre un écrivain ouvert
avant une migration. `index()` l'intercepte spécifiquement par paire (paire reportée via `index_pending`, jamais «
borg diff échoué ») ; ailleurs elle se propage à l'appelant.

`cache_prune_dryrun`/`cacheJsonBoexWithLM` (depuis 1.0.103) : signature inchangée. Sur une base `cache.db` chiffrée,
`details` est transparemment chiffré à l'écriture et déchiffré à la lecture (`conn.codec.blob`) ; une ligne illisible
(`DbCodecError`) est absorbée en interne et traitée comme un cache miss, jamais propagée à l'appelant.

```python
from borgHelper import _open_db, DbKeyError
conn = _open_db(db_path, nick='mon-serveur', role='read')   # BhConnection ; .codec est None si la base est plain (ou mode 'empty', voir plus bas)
```

`_open_db(db_path, nick=None, role='read', passphrase=None, empty_ok=False, **kw)` est le seul point d'ouverture SQLite
(1.0.169 : avec `empty_ok=True` en lecture, une base siv1 en WAL sans aucun chemin que la passphrase n'ouvre pas est rendue
vide — `conn.mode == 'empty'`, `codec None` (ce n'est PAS une base en clair), lecture seule, instantané figé — au lieu de
`DbKeyError` ; une `DbKeyError` dont `wrong_key` est vrai signale une enveloppe qui refuse la passphrase (même type, même nom affiché) ; les `kw`,
ex. `timeout=60`, sont transmis à `sqlite3`). `db_encrypt_enabled(nick)` / `db_kdf_level(nick)` lisent `DB_ENCRYPT` /
`DB_KDF`.

Lectures de chemins (depuis 1.0.101) : les méthodes de `BorgHelper` (`treehist`, `treefind`, `search`, `filehist`, `duidx`,
`idxtop`, `difftop`, `list_files`, `diffbkp`, `idxpurge`) renvoient/impriment toujours des chemins **logiques**, que la base soit
`plain` ou chiffrée. Un préfixe de chemin est sensible à la casse et littéral (voir README, `TreeHist`). Pour lire une base
directement, ouvrir avec `_open_db(..., nick=...)` et passer par `_path_range`/`_psel_under`, `_path_stored` et `_path_decode`
plutôt que par un `LIKE` sur `path` (qui ne fonctionnerait pas sur une base chiffrée) ; les requêtes SQL manuelles ci-dessous
ne valent que pour une base `plain`.

---

## Les trois classes

### `BorgHelper` — couche haut niveau

Point d'entrée principal. Orchestre `BorgHelperDB` et `BorgRunner`.

```python
bh = BorgHelper(cfgfile=None, cache_dir=None, passphrase=None)
# cfgfile   : chemin vers le borghelperrc (défaut : ~/.borghelperrc)
# cache_dir : répertoire des DB SQLite (défaut : valeur CACHE_DIR du borghelperrc ou ~/.cache/borghelper)
# passphrase: complète/supplante BORG_PASSPHRASE du borghelperrc pour toute la durée de vie de bh
#             (utile pour ne pas persister de passphrase en clair dans un borghelperrc partagé)
```

Attributs :
- `bh.db`   — instance `BorgHelperDB`
- `bh.borg` — instance `BorgRunner`

### `BorgHelperDB` — couche SQLite

Toutes les opérations sur `cache.db` et `diff.db`. Pas d'appel borg.

```python
db = BorgHelperDB(cache_dir, db_prefix, cfg_reader=None, nicks_reader=None)
# nicks_reader (1.0.168) : callable() -> liste des nicks du rc ; sert à ne jamais chiffrer d'office une base partagée
```

### `BorgRunner` — couche borg

Lecture du borghelperrc, exécution des commandes borg via subprocess.

```python
runner = BorgRunner(cfgfile=None, passphrase=None)
```

`runner.dfRepo(nick)` : place libre (octets) du système de fichiers d'un dépôt local, `None` si distant ou illisible
(1.0.167 : sans shell, plus de `ValueError` sur un dépôt absent) ; `runner.repoLocalAbsent(nick)` : vrai si le dépôt
est local et introuvable.

Lecteurs à plusieurs nicks (`search`, `filehist`, `treehist`, `treefind`, `duidx` avec `nick='a,b'` ; 1.0.167) : un nick
dont la base est inutilisable (`DbKeyError`, `DbModeError`, `DbTamperError`, `DbCodecError`, `SchemaVersionError`,
`SystemExit` d'une base illisible) ne lève plus : `{nick: {'error': message}}` avec `as_json=True` (search, filehist,
treehist, treefind), ligne `[ERREUR]` sur stderr sinon ; `duidx` rend les totaux des autres nicks (aucune entrée
d'erreur). Nick seul ou tous en échec : la première exception est levée comme avant ; `SystemExit(130)` (Ctrl-C)
toujours relevée.

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
# backup() se termine par sys.exit(code) — SystemExit à attraper. 1.0.163 : SystemExit(2) avant tout borg si
# BORG_ROOTBKP est illisible ou si aucun de ses chemins n'existe (bkp_status 'error', alerte bkp_error)
# backup() ne prend qu'UN nick : la boucle multi-nicks (`-n ALL`, 1.0.167 : un nick après l'autre, pire code, Ctrl-C
# = sys.exit(130) relancé) est dans la CLI — un appelant Python boucle lui-même en attrapant SystemExit par nick.

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

### Chiffrement des bases (depuis 1.0.104)

```python
bh.db_encrypt('mon-serveur', dryrun=True)             # rapport seul, rien changé
bh.db_encrypt('mon-serveur', confirm=True)             # exécution réelle -> code 0 si OK, non nul sinon
bh.db_decrypt('mon-serveur', confirm=True)             # sens inverse
bh.db_rekey('mon-serveur', confirm=True)                # ré-enveloppe la DEK (refuse sur base plain)
bh.db_status('mon-serveur')                             # imprime le mode de cache.db/diff.db (stderr)
```

`db_encrypt`/`db_decrypt`/`db_rekey` retournent un entier (0 = succès, non nul = refus/erreur — voir README pour le
détail des refus) plutôt que de lever une exception pour les cas attendus (verrou, `DB_ENCRYPT=false`, espace disque,
base déjà dans le mode cible). Les erreurs de chiffrement (`DbKeyError`, `DbModeError`, `DbTamperError`,
`DbCodecError`) levées pendant la migration elle-même sont capturées et converties en message + code 2 ; une
interruption externe (kill, crash du process) laisse la base en `path_enc='migrating'`, reprise automatiquement par
un nouvel appel de la **même** méthode sur le même nick.

### Restes de dépôts disparus et de nicks retirés (depuis 1.0.160)

```python
scan = bh.cleanup_scan()                    # lecture seule : {'borg': [...], 'bh': [...]}, chemins compris
bh.cleanup_summary(scan)                    # nombres et tailles seulement (borg_entries, keys, bh_files, history…)
bh.cleanup_notice()                         # ligne de Status/Report, ou None — jamais d'exception
bh.borg_cleanup()                           # aperçu imprimé (stderr), code 0
bh.borg_cleanup(confirm=True)               # demande confirmation sur stdin, puis supprime le régénérable
bh.borg_cleanup(confirm=True, keys=True, history=True, ask=lambda prompt, want: True)   # réponse fournie par l'appelant
```

`cleanup_scan(home=None)` : dossier personnel pwd par défaut, ou `BORGHELPERC_CLEANUP_HOME`. Chaque entrée `borg` porte
`recreated` (1.0.161 : ancien dépôt recréé au même chemin — hors notice, `cleanup_summary()['recreated']`),
`current_id` (identifiant du dépôt présent, sinon `None`) et `plain` (dépôt non chiffré : entrée de sécurité gardée
comme une clé). `borg_cleanup` rend 0, 1
(suppression en échec) ou 2 (non confirmé). La notice n'est imprimée que par le CLI (`Status`, `Report` texte) ;
`status()` n'imprime rien de plus. Critères et limites : README, `BorgCleanup`.

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

# Dernières N archives (moins de N dans le dépôt : message + SystemExit(3) ; strict=False rend [] à la place)
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

# Statistiques par archive : added/removed/modified = fichiers ordinaires seuls (1.0.162, comme nfiles de borg) ;
# added_sz/removed_sz/modified_sz par familles (répertoires et liens compris) — un compte peut être 0 avec une taille > 0
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

### Consulter le statut des sauvegardes (`bkp_status`, Story 1 spec-notifications-push)

```python
from borgHelper import BorgHelper

bh = BorgHelper()

# bh.backup(nick) écrit une ligne bkp_status (history.db depuis 1.0.139, exclusif à backup()) à son
# début et à sa fin — 'success'/'error' dérivé du même code retour que sys.exit(). Lecture/réclamation
# directes via bh.db, sans passer par sqlite3 : mêmes méthodes que le watcher borgHelperWWW.
# db_path facultatif : par défaut, la history.db du nick (une lecture ne la crée jamais).
db_path = bh.db.get_history_db('mon-serveur')

# Lignes prêtes à être traitées : terminées, ou bloquées depuis plus de timeout_s secondes sans fin
# (processus tué avant sa fin normale — AD-7). Ne modifie rien (lecture seule).
pending = bh.db.list_pending_bkp_status('mon-serveur', timeout_s=21600, db_path=db_path)
for row in pending:
    # 'result' est None pour une ligne réclamée uniquement via le timeout (jamais écrit en base
    # dans ce cas) — la traiter comme un échec dans ce cas précis :
    result = row['result'] if row['finished_at'] else 'error'
    print(row['run_id'], result)

# Réclamation par comparer-et-échanger — jamais deux appelants (process/thread) ne gagnent sur la
# même ligne : True = cet appel a gagné, False = déjà réclamée ailleurs (pas une erreur).
for row in pending:
    if bh.db.claim_bkp_status('mon-serveur', row['run_id'], db_path=db_path):
        print('réclamée :', row['run_id'])

# Bkp en cours (1.0.145) : True (démarré depuis moins de timeout_s, sans fin), False (aucun, ou bloqué
# au-delà), None (history.db illisible — ne jamais le prendre pour une fin de Bkp). 1.0.155 : une ligne ouverte n'est
# effacée que par un Bkp plus récent réussi (tué puis réussi -> False ; vivant puis échec -> True) ; timeout_s < 1 s ou
# invalide : 21600, plafond 10 ans.
state = bh.db.bkp_running_state('mon-serveur', timeout_s=bh.bkp_status_timeout('mon-serveur'))

# Délai du nick (1.0.155) : clé rc BKP_STATUS_TIMEOUT (section ou [DEFAULT] ; secondes ou suffixe s/m/h), sinon
# BORGHELPERWWW_BKP_STATUS_TIMEOUT, sinon 21600 ; valeur invalide : 21600 ; [WARN] si invalide ou < 300 s ; jamais
# d'exception (nick absent, rc illisible).
timeout_s = bh.bkp_status_timeout('mon-serveur')

# Dernière ligne du nick si elle est sans fin (Status) : {'run_id','started_at'}, sinon None (1.0.154 : un Bkp tué suivi
# d'autres Bkp n'est plus rendu) ; avec timeout_s, clé 'stale' en plus — True au-delà du délai (Bkp tenu pour
# interrompu, même condition que bkp_running_state) ; timeout_s < 1 : 21600, plafonné à 10 ans.
row = bh.db.get_running_bkp_status('mon-serveur', timeout_s=21600)

# Dernier Bkp du nick (1.0.152) : {'run_id','started_at','finished_at','result'} (finished_at None s'il tourne),
# None sans ligne ou sans history.db (jamais créée) ; lève si la base est illisible.
last = bh.db.last_bkp_status('mon-serveur')
```

### Résultat du dernier Index (1.0.149)

```python
from borgHelper import BorgHelper

bh = BorgHelper()

# Écrit par le dispatch CLI `Index` après chaque nick (pas par bh.index() appelé en bibliothèque, ni par l'Index de
# fin de Bkp) : CACHE_DIR/<conf>-<nick>-index-last.json. Heures ISO avec décalage ; last_failure = échec précédent
# reporté par un busy/deadline. dict ou None (absent, illisible) — jamais d'exception, rien créé.
last = bh.db.read_index_last('mon-serveur')
fail = last if last and last['outcome'] in ('error', 'refused') else (last or {}).get('last_failure')
if fail:
    print(fail['finished_at'], fail['code'], fail['message'])

bh.db.index_last_path('mon-serveur')    # chemin du fichier
# write_index_last(nick, rec) : écriture atomique 0600 ; lève OSError (la CLI n'en fait qu'un avertissement).
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

## Accès direct à la base SQLite en ligne de commande

Le `diff.db` est un fichier SQLite standard — consultable avec `sqlite3` sans Python.

### Trouver le chemin du diff.db

```bash
# Chemin standard : ~/.cache/borghelper/<conf>-<nick>-diff.db
# <conf> = basename du borghelperrc sans extension
# Exemple pour ~/.borghelperrc et nick "mon-serveur" :
DB=~/.cache/borghelper/borghelperrc-mon-serveur-diff.db

# Ou depuis borgHelper (affiche le répertoire de cache) :
borgHelper -c CacheInfo -n mon-serveur
```

### Configuration sqlite3

```bash
sqlite3 $DB
# Dans le shell interactif :
.headers on
.mode column
.width auto
# Quitter :
.quit
```

### Requêtes utiles

**Valables uniquement sur une base `plain`.** Ces requêtes SQL manuelles (`sqlite3` en ligne de commande) lisent la
colonne `path` directement : sur une base chiffrée, `path` contient la valeur stockée (chiffrée), pas le chemin
logique — un `LIKE '%nginx%'` n'y trouverait rien, et rien n'y déchiffre le résultat. Pour une base potentiellement
chiffrée, passer par `borgHelper`/`BorgHelper` (CLI ou lib) plutôt que par ces requêtes.

```bash
# Tables disponibles
sqlite3 $DB ".tables"

# Liste des archives avec tailles
sqlite3 -header -column $DB "
SELECT archive, archive_date, nfiles,
       original_size/1048576 AS orig_MB,
       deduplicated_size/1048576 AS dedup_MB
FROM archive_stats WHERE nick='mon-serveur'
ORDER BY archive_date;"

# Paires indexées (avec compteur d'entrées)
sqlite3 -header -column $DB "
SELECT archive_old, archive_new, entry_count, indexed_at
FROM diff_indexed_pairs WHERE nick='mon-serveur'
ORDER BY indexed_at DESC LIMIT 10;"

# Historique d'un fichier spécifique
sqlite3 -header -column $DB "
SELECT archive_new_date, archive_new, change_type,
       size_before, size_after
FROM diff_index
WHERE nick='mon-serveur' AND path='/etc/nginx/nginx.conf'
ORDER BY archive_new_date;"

# Fichiers les plus souvent modifiés
sqlite3 -header -column $DB "
SELECT path, COUNT(*) AS nb
FROM diff_index
WHERE nick='mon-serveur' AND change_type='modified'
GROUP BY path ORDER BY nb DESC LIMIT 20;"

# Gros fichiers ajoutés dans la dernière archive
sqlite3 -header -column $DB "
SELECT path, size_after/1048576 AS size_MB
FROM diff_index
WHERE nick='mon-serveur' AND change_type='added'
  AND archive_new = (
    SELECT archive_new FROM diff_indexed_pairs
    WHERE nick='mon-serveur' ORDER BY indexed_at DESC LIMIT 1)
ORDER BY size_after DESC LIMIT 20;"

# Résumé +/-/= par archive (compteurs)
sqlite3 -header -column $DB "
SELECT archive_new, change_type, COUNT(*) AS nb,
       SUM(COALESCE(size_after, size_before))/1048576 AS size_MB
FROM diff_index WHERE nick='mon-serveur'
GROUP BY archive_new, change_type
ORDER BY archive_new DESC, change_type;"

# Fichiers exclus par les filtres d'indexation
sqlite3 -header -column $DB "
SELECT change_type, SUM(file_count) AS nb, SUM(total_size)/1048576 AS size_MB
FROM diff_excluded_stats WHERE nick='mon-serveur'
GROUP BY change_type;"

# Recherche dans le snapshot (dernière archive) — snapshot_file : une ligne par VERSION d'un chemin (1.0.164),
# toujours filtrer sur l'archive voulue (sans filtre : une ligne par archive et par version)
sqlite3 -header -column $DB "
SELECT sf.path, sf.size/1024 AS size_KB, sf.mtime
FROM snapshot_file sf
JOIN archive_snapshot s ON s.file_id = sf.id
WHERE s.nick='mon-serveur' AND sf.path LIKE '%nginx%'
  AND s.archive=(SELECT archive FROM archive_snapshot WHERE nick='mon-serveur' ORDER BY archive_date DESC LIMIT 1)
LIMIT 20;"
```

### Export CSV

```bash
# Exporter archive_stats en CSV
sqlite3 -header -csv $DB \
  "SELECT * FROM archive_stats WHERE nick='mon-serveur' ORDER BY archive_date;" \
  > archive_stats.csv
```

### Compactage manuel (VACUUM INTO)

Après de grosses purges (`IdxPurge`), le fichier SQLite conserve les pages libérées en interne (freelist) sans réduire sa taille sur disque. `borgHelper idxpurge` fait ce compactage automatiquement, mais si l'espace disque manquait même dans le répertoire de la base, voici la procédure manuelle.

**Principe** : `VACUUM INTO` crée une copie compacte dans le *même répertoire* (même filesystem), ce qui évite l'erreur `database or disk is full` liée à `/tmp` sur une partition séparée.

> **Important** : le nom de fichier dans `VACUUM INTO` doit être une chaîne SQL entre apostrophes — sans guillemets, SQLite l'interprèterait comme un nom de colonne et retournerait `no such column`.

```bash
# ❌ ERREUR — popo est interprété comme un nom de colonne
sqlite3 mon.db "VACUUM INTO popo"

# ✅ CORRECT — le nom de fichier est entre apostrophes SQL
sqlite3 mon.db "VACUUM INTO 'popo.db'"
```

Procédure complète :

```bash
DB=~/.cache/borghelper/borghelperrc-mon-serveur-diff.db

# 1. Créer une copie compacte dans le même répertoire
python3 -c 'import sqlite3,sys; sqlite3.connect(sys.argv[1]).execute("VACUUM INTO ?",(sys.argv[2],))' "$DB" "${DB}.compact"

# 2. Recopier la version compacte DANS la base (API backup de SQLite, sûre même si la base est ouverte),
#    puis vider le WAL et supprimer la copie
python3 -c 'import sqlite3,sys; s=sqlite3.connect(sys.argv[2]); d=sqlite3.connect(sys.argv[1],timeout=60); s.backup(d); d.execute("PRAGMA wal_checkpoint(TRUNCATE)"); d.close(); s.close()' "$DB" "${DB}.compact"
rm "${DB}.compact"

# 3. Vérifier que la taille a bien diminué
ls -lh "$DB"
```

> ⚠️ **Jamais `mv` pour remplacer une base ouverte** (borgHelperWWW, un Bkp, un Index…) : avec un `-wal` non vide, les
> connexions suivantes rejouent l'ancien WAL sur le nouveau fichier (lectures en erreur, ancien contenu réapparu), et
> les connexions déjà ouvertes continuent d'écrire dans l'ancien fichier (écritures perdues) — mesuré en 1.0.138.
> L'étape 2 passe par les verrous de SQLite, comme `_swap_db` que `borgHelper` utilise lui-même depuis 1.0.138 ; la base
> reste en mode WAL (vérifié).
> Écrire une modification entre l'étape 1 et l'étape 2 la ferait écraser : faire les deux étapes à la suite, hors Bkp.

Le fichier résultant est immédiatement utilisable par borgHelper :
- `journal_mode=WAL` et `auto_vacuum=INCREMENTAL` sont réappliqués automatiquement à la prochaine connexion borgHelper.
- Le schéma et les données sont intacts (`VACUUM INTO` est une copie compacte fidèle).
- Aucune ré-indexation nécessaire.

> **Espace requis** : `VACUUM INTO` a besoin d'environ autant d'espace que la taille *réelle* des données (sans les pages libres) — bien moins que la taille actuelle du fichier si celui-ci contient beaucoup de freelist.

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
| `backup(nick, no_index, debug)` | Lance `borg create` + indexation automatique (indexsnap + index ciblé sur la nouvelle archive) ; opération prioritaire : un `Index` externe se met en pause pendant le Bkp et reprend seul après l'Index de fin de Bkp (1.0.141) ; écrit une ligne `bkp_status` (history.db depuis 1.0.139) à son début et à sa fin (`'success'`/`'error'` dérivé de `sys.exit()` — voir `bh.db.list_pending_bkp_status`/`claim_bkp_status` ci-dessous) |
| `prune(nick, dryrun, debug)` | Opération prioritaire : attend qu'un Index se mette en pause (1.0.141), `borg prune` + compact + rapprochement (archives disparues figées puis retirées, 1.0.140) |
| `index(nick, debug, db_path, force, target_archive, set_pending, budget=None, natures=None, period=None, pause=True, snap_only=False, rebuild=False)` | Rapproche d'abord les bases de `borg list` (archives disparues retirées, 1.0.140), puis indexe. 1.0.141 : `budget` (s, > 0), `natures` (sous-ensemble non vide de `stats`,`snap`,`diff`) ou `period` (`(de, à)` : archive, date `AAAA-MM-JJ[THH:MM:SS]` ou `ALL`) → tranche (snapshot, stats, diffs du plus récent au plus ancien — ordre 1.0.146 —, reprenable, `build_state` écrit) ; `snap_only` : snapshot seul (`-S`). Tout Index prend un verrou exclusif par dépôt et se met en pause si Bkp/Restore/Prune/Report démarre, puis reprend seul — **changement de comportement** : sans budget, l'appel peut attendre sans limite la fin de l'opération prioritaire ; `pause=False` : arrêt immédiat comme avant (`index-pending` si `set_pending`, retour 1). Retour : 0 (fini, déjà en cours, échéance), 1 (erreur, période invalide, annulé) ; `ValueError` sur budget/natures invalides. N'abaisse jamais la priorité du processus appelant (seule la CLI le fait). 1.0.143 : `rebuild=True` → tranche qui crée ou poursuit le fichier fantôme `<db_path>.rebuild` (`force=True` : le jette d'abord) ; toute tranche poursuit un fantôme existant (dans ses limites `natures`/`period`, avertissement si elles restreignent, 1.0.148) et bascule quand il est complet ; retour 3 si `rebuild` est refusé (`DB_NAME` partagé, espace disque, migration de chiffrement) |
| `indexsnap(nick, debug, db_path, force, archives=None)` | Snapshot de la dernière archive — incrémental par défaut (force=True pour `borg list` complet) ; purge auto des snapshots anciens (IDX_SNAP_KEEP) ; `archives` (1.0.141) : liste `borg list` déjà obtenue ; retourne `'killed'` si son borg a été tué par une demande d'arrêt (rien d'écrit) |
| `report(nicks, htrep, debug, maxp, as_json)` | Rapport avec appels borg ; 1.0.166 : un `SystemExit` d'un nick (base illisible) devient sa ligne d'erreur (retour 2), sauf le code 130 (Ctrl-C), relancé ; 1.0.168 : `reste` = message réel de l'arrêt |
| `report_offline(nicks, htrep, debug, maxp, as_json)` | Rapport depuis diff.db uniquement — même résumé que `report`, toutes machines affichées même sans index ; 1.0.166 : même isolation par nick que `report` ; 1.0.168 : `reste` = message réel de l'arrêt |
| `idxtop(nick, depth, topn, debug, as_json)` | Top N arborescences par nb d'entrées dans diff_index — diagnostiquer un diff.db volumineux ; `as_json` (Story 1.4) : mode brut, une ligne par chemin (`{'nick','rows':[{'chemin','taille'}]}`), **sans** regroupement/top-N ni Exclus/Inchangés — `depth`/`topn` ignorés dans ce mode |
| `difftop(nick, bkp, depth, topn, debug, as_json)` | Top N arborescences par changements sur une paire d'archives — diagnostiquer les changements d'un backup ; `as_json` (Story 1.4) : mode brut, une ligne par chemin (`{'nick','archive_old','archive_new','rows':[{'chemin','type','taille_avant','taille_apres'}]}`), **sans** regroupement/top-N ni Exclus/Inchangés — `depth`/`topn` ignorés dans ce mode |
| `_swap_db(live, new, nick, abort, changed, pages, busy_limit, keep_new=False)` (fonction du module, interne) | Remplace le contenu d'une base servie par celui de `new` (API backup de SQLite) ; `'ok'`/`'abort'`/`'changed'`/`'busy'`/`'invalid'` ; `keep_new=True` (1.0.143) : `new` gardée sauf après `'ok'`/`'invalid'` |
| `idxpurge(nick, pattern=None, dryrun, debug, db_path=None)` | Purge rétroactive de diff_index + snapshots anciens + VACUUM — sans pattern : lit IDX_EXCLUDE/IDX_INCLUDE depuis la config ; `db_path` (1.0.143) : autre fichier que la base servie (fantôme avant bascule) |
| `search(nick, pattern, archive_from, archive_to, debug, as_json)` | Recherche par chemin — `as_json` : `{nick:[{date,archive,type,path,size_before,size_after},...]}` |
| `filehist(nick, path, archive_from, archive_to, debug, as_json)` | Historique d'un chemin — `as_json` : `{nick:[{date,archive_before,archive_after,type,size_before,size_after},...]}` |
| `duidx(nick, pattern, sort_by, reverse, as_json, archive_from, archive_to, debug, raw)` | Résumé taille/type ; `raw=True` (Story 1.4, distinct de `as_json` qui reste le mode groupé historique) : mode brut, une ligne par chemin (`{'pattern','rows':[{'chemin','type','taille'}]}`) |
| `diffbkp(nick, bidun, bideux, debug, db_path, as_json)` | Différences entre deux archives — `+`/`-`/`=` par ligne, résumé compteurs ; `as_json` : `{archive_old,archive_new,entries:[...],n_add,n_rem,n_mod}` |
| `restore(nick, bid, ftor, where, flat, debug)` | Restauration |
| `listperms(nick, bid, ftor, debug)` | Liste droits fichiers sans restaurer |
| `list_backups(nick, debug)` | Liste les archives |
| `list_files(nick, bid, debug, as_json)` | Liste fichiers d'une archive — `as_json` : `{nick,archive,files:[chemin,...]}` |
| `delbkp(nick, bid, debug)` | Supprime une archive : opération prioritaire (un Index se met en pause, 1.0.142), `borg delete` + compact, puis rapprochement des bases comme `prune` (1.0.145) ; termine par `sys.exit` |
| `mount(nick, bid, debug)` | Monte via FUSE |
| `umount(nick, debug)` | Démonte |
| `key(nicks, debug)` | Exporte la clef |
| `init_repo(nick, debug)` | Initialise un dépôt |
| `stats(nick, debug)` | État de montage |
| `cache_info(nick, debug)` | Affiche le cache |
| `cache_clean(nick, debug)` | Nettoie le cache |

### Dépôts externes (1.0.142)

| Fonction (module `borgHelper`) | Description |
|---------|-------------|
| `glob_args(cfg, form='list', archives=False)` | Arguments de filtre d'archives (`--glob-archives`) ; aucun si `GLOB_ARCH` absent (motif `*` avec `archives=True`, pour `borg info`) — seul lecteur de la clé |
| `is_external(cfg)` | Vrai si la section déclare `EXTERNAL = true` |
| `external_ops(cfg, nick='')` | Opérations permises sur un externe (`read` toujours, défaut `read,restore`) |
| `command_op(cmd)` | Nature d'une commande CLI : `bkp`, `restore`, `prune`, `delete` ou `read` |
| `op_allowed(cfg, op, nick='')` | Autorité unique : l'opération est-elle permise sur ce nick ? |
| `allowed_ops(cfg, nick='')`, `ALL_OPS` | (1.0.144) Opérations permises parmi `ALL_OPS` (`read`, `restore`, `prune`, `delete`, `bkp`) — `GET /access` de borgHelperWWW |
| `require_op(cfg, op, nick='')` | Lève `OpNotAllowed` si refusée (la CLI sort alors avec le code 4) |

> Les méthodes de `BorgHelper` (`backup`, `prune`, `delbkp`, `restore`…) ne vérifient pas `EXTERNAL_OPS` : le contrôle
> se fait au dispatch CLI. Un script qui les appelle directement doit appeler `require_op` lui-même.

### Méthodes `BorgHelperDB` utiles en lecture

| Méthode | Description |
|---------|-------------|
| `get_diff_db(nick)` | Chemin du diff.db d'un nick |
| `get_cache_db(nick)` | Chemin du cache.db d'un nick |
| `get_history_db(nick)` | Chemin de la history.db d'un nick (1.0.139 : mesures non régénérables, en clair, sans chemin) |
| `history_path(nick)` | Idem, après migration éventuelle de la diff.db du nick (lecteurs) ; ne crée jamais le fichier |
| `ensure_history_db(path, create=True)` | Schéma de history.db ; `create=False` : ne rien créer si absente |
| `store_archive_measure(nick, archive, archive_date, deduplicated_size, changed_during_backup, read_errors, db_path=None, borg_version=None, borg_server_version=None)` | Mesures d'une archive prises au Bkp (history.db) ; versions de borg (1.0.165, mot-clé, `None` = inconnue) |
| `get_archive_measures(nick)` | `{(archive, archive_date): {deduplicated_size, changed_during_backup, read_errors, borg_version, borg_server_version}}` (+ clé `(archive, None)` si le nom est unique) ; `{}` si aucune |
| `delete_archive_measures(nick, keep=None)` | Retire les mesures des archives absentes de `keep` (toutes si `keep` vide) |
| `freeze_archive_chart(nick, rows, db_path=None)` | 1.0.140 — fige des lignes de graphique dans `history.db.archive_chart` (dicts `archive`, `archive_date`, `gone`, champs de graphique) ; jamais une valeur non nulle écrasée par `None` ; purge au-delà de `STATS_RETENTION_MONTHS` ; lève `sqlite3.Error` |
| `get_archive_chart(nick, db_path=None)` | 1.0.140 — lignes figées dans la rétention : `[{archive, archive_date, duration, …, read_errors, gone}]` ; `[]` si aucune |
| `is_diff_pair_indexed(nick, a_old, a_new)` | Vérifie si une paire est indexée |
| `is_archive_snapshot_indexed(nick, archive)` | Vérifie si le snapshot est indexé |
| `_diff_stats_for_nick(nick, archives=None, conn=None)` | Stats de mouvement par archive (Report, ArchiveHistory, figeage) — comptes en fichiers ordinaires depuis 1.0.162, tailles par familles ; `archives` (1.0.140) restreint aux archives nouvelles données, `conn` : erreurs SQLite remontées |
| `store_excluded_diff_stats(nick, a_old, a_new, exclu, db_path)` | Stocke stats fichiers exclus d'une paire |
| `store_excluded_snap_stats(nick, archive, count, size, db_path)` | Stocke stats fichiers exclus d'un snapshot |
| `_with_lock_retry(fn, max_wait=300)` | Exécute `fn()`, retente toutes les 2 s si `OperationalError: database is locked`, jusqu'à `max_wait` secondes |
| `set_priority_lock(nick)` | Pose le lock prioritaire de CE processus (`<…>-priority.lock.<pid>`, 1.0.145) — appelé par `backup`/`restore`/`prune`/`delbkp` |
| `clear_priority_lock(nick)` | Supprime le lock prioritaire de CE processus seulement (1.0.145 : ceux des autres porteurs restent) |
| `check_priority_lock(nick)` | `True` si un AUTRE processus prioritaire vivant tient le lock (jamais le sien ; porteur mort → fichier retiré ; ancien fichier unique encore lu) |
| `set_index_running_lock(nick)` | Pose le lock "Index actif" (écrasement, non exclusif) — `Index` utilise `acquire_index_running_lock` depuis 1.0.141 |
| `acquire_index_running_lock(nick, wait=0)` | 1.0.141 — prise exclusive (un seul Index par dépôt), réentrante pour le même processus ; verrou d'un PID mort retiré ; `wait` : attente maximale en secondes |
| `release_index_running_lock(nick)` / `index_running_owned(nick)` | 1.0.141 — relâche le verrou s'il est à ce processus / vrai s'il l'est (1.0.148 : faux pour un ancien fichier portant notre PID repris) |
| `acquire_index_paused_lock(nick)` / `release_index_paused_lock(nick)` / `check_index_paused(nick)` | 1.0.141 — marqueur exclusif de l'Index en pause (un seul en attente par dépôt) |

> 1.0.148 : tous les `check_*`/`acquire_*` de verrous à PID (prioritaire, `index-running`, `index-paused`, `report-running`) comptent comme mort un PID ≤ 0, hors plage, ou **repris** (processus démarré plus de 60 s après l'écriture du fichier) ; le fichier est alors retiré ou mis de côté.
| `clear_index_running_lock(nick)` | Supprime le lock "Index actif" |
| `check_index_running(nick)` | `True` si un Index vivant tient le running lock (stale → auto-supprimé ; 1.0.148 : un verrou plus ancien de plus de 60 s que le processus qui porte son PID compte comme mort, comme pour tous les verrous à PID) |
| `wait_index_idle(nick, timeout=120)` | Attend jusqu'à `timeout` s que `Index` libère ses verrous borg |
| `set_index_pending_lock(nick)` | Pose le flag de reprise — appelé par `Index` quand interrompu par priorité (`set_pending=True`) |
| `clear_index_pending_lock(nick)` | Supprime le flag de reprise |
| `check_index_pending_lock(nick)` | `True` si un `Index` interrompu attend d'être repris |

> ⚠️ **Changement cassant (1.0.139)** : `store_archive_stats(...)` n'accepte plus `changed_during_backup=` / `read_errors=` (`TypeError`) — ces mesures passent par `store_archive_measure(...)` dans `history.db`. Les fonctions `bkp_status`/`repo_stats` (`store_bkp_status_*`, `list_pending_bkp_status*`, `claim_bkp_status*`, `bkp_running`, `bkp_running_state` (1.0.145), `get_running_bkp_status`, `store_repo_stats`, `get_repo_stats`) visent désormais la `history.db` du nick par défaut ; un `db_path` explicite doit être un chemin de `history.db`.

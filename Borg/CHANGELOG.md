# Changelog — borgHelper

## 1.0.20 — 2026-06-07

### `Report` : pourcentages cohérents — base unique = archive courante

Les colonnes `+ajouté`, `-supprimé`, `=présent` affichaient deux bases différentes :
- comptages (fichiers) → base = archive précédente
- tailles (octets)     → base = archive courante

Les deux utilisent maintenant la même base : **l'archive courante** (`nfiles` / `original_size`).

Lecture uniforme : "X% des fichiers de ce backup sont nouveaux / supprimés / inchangés".  
`ajouté% + présent% ≈ 100%` (les fichiers modifiés sont comptés dans `=présent`).

## 1.0.19 — 2026-06-07

### `DiffTop` : top N arborescences par changements sur une paire d'archives

Nouveau diagnostic ciblé sur un diff précis (par défaut : la dernière paire indexée).

```bash
borgHelper -c DiffTop -n mon-serveur          # top 10, profondeur 3, dernière paire
borgHelper -c DiffTop -n mon-serveur -N 5     # top 5
borgHelper -c DiffTop -n mon-serveur -p 4     # profondeur 4
borgHelper -c DiffTop -n mon-serveur -b archive-old,archive-new  # paire explicite
```

Colonnes : `total (nb+%)`, `+nb`, `+taille`, `-nb`, `-taille`, `=nb`, `taille`.  
Tri par total. Source : `diff_index` — aucun appel borg.

## 1.0.18 — 2026-06-07

### `IdxTop` : fix regroupement des chemins sans `/` initial

`get_prefix` ignorait la profondeur pour les chemins sans `/` initial (borg peut produire des chemins relatifs) — chaque fichier formait sa propre clé au lieu d'être regroupé. Corrigé : les chemins relatifs sont maintenant tronqués à la même profondeur que les chemins absolus.

`IdxTop` est trié par nombre d'entrées (colonne `entrées`), pas par poids.

## 1.0.17 — 2026-06-07

### `IdxPurge` : `VACUUM INTO` pour éviter l'erreur "database or disk is full"

`VACUUM` (et `PRAGMA incremental_vacuum` sur les DB en mode `auto_vacuum=NONE`) écrit son fichier temporaire dans `/tmp`, qui peut être sur une partition séparée et saturée — même si le filesystem du `diff.db` a de l'espace disponible.

`VACUUM INTO 'chemin.tmp'` crée la copie compacte dans le **même répertoire** que le `diff.db`, utilisant l'espace libre du bon filesystem. Suivi d'un `os.replace` atomique.

Si le compactage échoue malgré tout (disque vraiment plein), les entrées sont quand même supprimées et borgHelper affiche la commande manuelle à relancer quand de l'espace sera libéré :

```
[WARN] compactage impossible (...) — entrées supprimées mais espace non récupéré
[WARN] relancer manuellement : sqlite3 'diff.db' "VACUUM INTO 'diff.db.tmp'" && mv 'diff.db.tmp' 'diff.db'
```

## 1.0.16 — 2026-06-07

### `IdxPurge` : `PRAGMA incremental_vacuum` au lieu de `VACUUM`

`VACUUM` crée une copie complète du fichier avant de remplacer l'original — sur un `diff.db` de plusieurs GB, cela nécessite autant d'espace libre que la taille du fichier, et échoue avec `database or disk is full` si le disque est serré.

Remplacé par `PRAGMA incremental_vacuum` : reclaime les pages libérées en tronquant le fichier depuis la fin, sans aucune copie. Possible car `diff.db` a `PRAGMA auto_vacuum=INCREMENTAL` depuis l'origine.

L'espace est récupéré immédiatement et proportionnellement aux entrées supprimées, sans risque de remplir le disque.

## 1.0.15 — 2026-06-07

### `IdxPurge` sans `-x` : purge selon IDX_EXCLUDE/IDX_INCLUDE du borghelperrc

Sans l'option `-x`, `IdxPurge` lit directement les filtres `IDX_EXCLUDE` et `IDX_INCLUDE` de la configuration du nick et purge tout ce que ces filtres auraient exclu à l'indexation.

```bash
# Après avoir modifié IDX_EXCLUDE dans borghelperrc :
borgHelper -c IdxPurge -n mon-serveur -D   # dry-run — voir le volume
borgHelper -c IdxPurge -n mon-serveur      # purger selon la config
```

- Affiche les patterns lus depuis la config avant d'agir
- Logique identique à `_idx_path_ok` : IDX_INCLUDE whitelist d'abord, IDX_EXCLUDE blacklist ensuite
- La condition SQL est construite dynamiquement à partir des patterns (GLOB ou LIKE selon présence de `*?[`)
- `-x` reste disponible pour un pattern explicite ponctuel (comportement 1.0.14 inchangé)

## 1.0.14 — 2026-06-07

### `IdxTop` et `IdxPurge` — diagnostic et nettoyage rétroactif du diff.db

Deux nouvelles commandes pour gérer les `diff.db` devenus trop volumineux (accumulation d'entrées sur des arborescences très actives comme `/var/lib/docker`, caches, artefacts de compilation).

#### `IdxTop` — diagnostic des gros contributeurs

```bash
borgHelper -c IdxTop -n mon-serveur
borgHelper -c IdxTop -n mon-serveur -N 30 -p 4   # top 30, profondeur 4
```

- Stream de `diff_index` par batch (50 000 lignes), regroupement par préfixe en Python
- Affiche les N arborescences avec le plus d'entrées : chemin, nb entrées, taille cumulée, % du total
- Configurable : `-N` (nb résultats, défaut 20) · `-p` (profondeur répertoire, défaut 3)
- Résultat typique : identifie en quelques secondes quelle arbo représente 35 % des entrées

#### `IdxPurge` — purge rétroactive + VACUUM

```bash
borgHelper -c IdxPurge -n mon-serveur -x /var/lib/docker -D   # dry-run
borgHelper -c IdxPurge -n mon-serveur -x /var/lib/docker       # purge réelle
borgHelper -c IdxPurge -n mon-serveur -x '*.pyc'               # glob
borgHelper -c IdxPurge -n mon-serveur -x '/home/*/.cache/*'    # glob (* matche /)
```

- Préfixe plain : supprime toutes les entrées dont le chemin vaut exactement le préfixe ou commence par `préfixe/`
- Glob : utilise SQLite `GLOB` (`*` matche tout y compris `/`)
- Après suppression : recalcule `diff_indexed_pairs.entry_count` + `VACUUM` pour récupérer l'espace immédiatement
- `-D` : dry-run — affiche le volume concerné sans rien modifier

#### Workflow recommandé

```
borgHelper -c IdxTop -n mon-serveur          # identifier les arbo volumineuses
  → ajouter les arbo à IDX_EXCLUDE dans le borghelperrc
borgHelper -c IdxPurge -n mon-serveur -D -x /var/lib/docker  # vérifier
borgHelper -c IdxPurge -n mon-serveur -x /var/lib/docker     # purger
  → diff.db : 6 GB → quelques centaines de MB
```

**Patterns depth-independent :** `*` matche `/`, donc `*/.git/*` purge tous les fichiers dans n'importe quel `.git/` quelle que soit la profondeur :

```bash
borgHelper -c IdxPurge -n mon-serveur -x '*/.git/*'
borgHelper -c IdxPurge -n mon-serveur -x '*/node_modules/*'
borgHelper -c IdxPurge -n mon-serveur -x '*/__pycache__/*'
```

Même syntaxe dans `IDX_EXCLUDE` pour le futur :

```ini
IDX_EXCLUDE = */.git/* */.git
    */node_modules/* */__pycache__/*
```

## 1.0.13 — 2026-06-06

### Index : attente automatique si SQLite verrouillé

- Lors de l'indexation, si la base `diff.db` est verrouillée par un backup ou une restauration en cours sur le même dépôt, borgHelper attend automatiquement le déverrouillage au lieu d'échouer immédiatement
- Affiche `SQLite verrouillé — attente déverrouillage (max 300s)...` au premier blocage, puis retente toutes les 2 s jusqu'à 300 s
- Concerne toutes les opérations d'écriture d'indexation : `store_diff_entries`, `store_archive_stats`, `store_archive_snapshot`, `_diff_keep_purge`, `store_excluded_diff_stats`, `store_excluded_snap_stats`
- Implémenté via `_with_lock_retry(fn, max_wait=300)` dans `BorgHelperDB` — chaque méthode d'écriture ferme proprement sa connexion entre deux tentatives (pas de fuite de connexion)

## 1.0.12 — 2026-06-06

### Report `-o` : même résumé que Report, toutes machines affichées

- `report_offline` (`-o`) produit désormais le même tableau résumé que `report` : colonnes `nom`, `duree`, `depuis`, `derniere`, `taille`, `recuperable`, `reste`, `+ajouté`, `-supprimé`, `=présent` + ligne `Totaux`
- Les nicks sans index (`diff.db` absent ou `archive_stats` vide) sont affichés avec `—` au lieu d'être silencieusement ignorés — le rapport est exhaustif même pour les machines non encore indexées
- Réécrit pour utiliser `prep_report_from_db()` (partagé avec le fallback offline de `report`) + même code de rendu que `report()`
- Les champs borg-only (`taille`/unique_csize, `récupérable`, `reste`) restent vides puisqu'il n'y a aucun appel borg

## 1.0.11 — 2026-06-06

### Report : fallback base uniquement si dépôt occupé

- Si `Report` est lancé pendant un `Bkp`, `Restore` ou `Index` sur le même dépôt, borgHelper détecte le lock actif (`priority.lock` ou `index-running.lock`) et lit les données depuis la base SQLite (`archive_stats` + `diff_index`) au lieu d'appeler borg
- Affiche un message : `dépôt occupé (Bkp/Index en cours) — rapport depuis la base uniquement`
- Les champs borg-only (`taille`/unique_csize, `récupérable`/prune, `reste`/df) apparaissent vides — les autres champs (archives, tailles, diffs, durées) sont complets depuis l'index
- Compatible multi-nick : chaque nick est évalué indépendamment (mixte online/offline possible)
- Nouveau : `BorgHelperDB.check_index_running(nick)` — symétrique de `check_priority_lock`
- Nouveau : `BorgHelper.prep_report_from_db(nick, maxp)` — construit `(tcmpl, tbkps)` depuis SQLite uniquement

## 1.0.10 — 2026-06-06

### Index : SIGKILL + `borg break-lock` — arrêt garanti sans stale locks

**Problème 1.0.9 :** SIGINT demande à borg de faire son cleanup, mais ce cleanup lui-même se bloque (I/O sur FUSE, ou opération interne en attente). `ps.communicate()` attend que le process meure → tout le threadpool hang → `wait_index_idle` timeout 120s → `borg create` voit encore les locks → échec.

**Solution :**

1. **SIGKILL** (`ps.kill()`) → mort instantanée, aucun cleanup, aucune chance de bloquer
2. **Poll `running_procs`** jusqu'à vide (deadline 15 s) → les threads `_run_diff` ont exécuté `ps.communicate()` qui reap les zombies ; les PIDs ne sont plus dans la table de processus
3. **`borg break-lock <BORG_REPO>`** → borg liste ses lock files, trouve les PIDs morts → les supprime → dépôt déverrouillé
4. `clear_index_running_lock` → `wait_index_idle` retourne → `borg create` démarre sans conflit

**Pourquoi le poll PIDs avant break-lock ?** Tant qu'un process est zombie (tué mais non reap), `os.kill(pid, 0)` retourne 0 — borg croit le lock légitime et ne le supprime pas. Le poll garantit que `ps.communicate()` (appel à `waitpid`) a reapé tous les zombies avant break-lock.

- Import `signal` supprimé (inutile)
- `ps.send_signal(signal.SIGINT)` → `ps.kill()` + poll `running_procs` + `borg break-lock`

## 1.0.9 — 2026-06-06

### Index : SIGINT au lieu de SIGTERM — libération propre des locks borg

**Problème :** `ps.terminate()` envoie SIGTERM au processus `borg diff`. Sous Python, SIGTERM appelle `_exit()` au niveau C — les blocs `finally` et les `__exit__` de context managers ne s'exécutent **pas**. Borg stocke ses locks dans des fichiers applicatifs (pas des OS file locks) via des context managers `with Lock(...):`. Avec SIGTERM, ces locks ne sont jamais libérés. Résultat : `borg create` voit des stale lock files et timeout.

**Solution :** `ps.send_signal(signal.SIGINT)` à la place de `ps.terminate()`.  
SIGINT (KeyboardInterrupt en Python) est intercepté par l'interpréteur Python, qui lève `KeyboardInterrupt` dans le thread courant. Cette exception remonte normalement à travers la pile : les blocs `finally` s'exécutent, les `with Lock():` appellent leur `__exit__` → borg supprime ses fichiers de lock → `borg create` trouve le dépôt libre.

- Ajout de `signal` aux imports
- `ps.terminate()` → `ps.send_signal(signal.SIGINT)` dans `_priority_monitor`

## 1.0.8 — 2026-06-06

### Index : thread moniteur priority lock — arrêt sans attendre la fin d'un diff

**Problème :** En 1.0.7, le check priority lock était dans la boucle `as_completed`. Si tous les workers `IDX_WORKERS` étaient bloqués dans `ps.communicate()`, aucun future ne complétait → `as_completed` ne progressait pas → `terminate()` non appelé → `Bkp` attendait jusqu'à 120 s.

**Solution — thread moniteur dédié :**
- Un thread daemon `_priority_monitor` démarre dès la soumission des futures, poll le priority lock toutes les 0.5 s
- Dès détection : `interrupted_event.set()`, `cancel()` sur les futures en attente, `ps.terminate()` sur tous les `Popen` actifs via `running_procs`
- Indépendant du rythme de `as_completed` — réagit dans les 0.5 s quelle que soit la charge
- Thread arrêté proprement (`interrupted_event.set()` dans `finally`, `monitor.join(timeout=2)`)
- `interrupted` booléen remplacé par `interrupted_event.is_set()` pour cohérence

**Délai d'interruption :** ≤ 0.5 s après pose du priority lock par `Bkp`

## 1.0.7 — 2026-06-06

### Index : arrêt immédiat des `borg diff` actifs sur priority lock

- `_run_diff` gère désormais son propre `subprocess.Popen` (au lieu de `boex`) pour conserver la référence au processus
- Dict thread-safe `running_procs` stocke les `Popen` actifs pendant Phase 2
- Quand le priority lock est détecté dans la boucle `as_completed` :
  - futures en attente → `cancel()`
  - processus `borg diff` en cours → `ps.terminate()` (SIGTERM)
  - `ps.communicate()` retourne immédiatement → running lock libéré → `Bkp` débloqué en quelques secondes
- Avant : `Bkp` attendait la fin naturelle de chaque diff (potentiellement plusieurs minutes)
- Après : arrêt en quelques secondes, quelle que soit la taille des archives

## 1.0.6 — 2026-06-06

### Bkp/Restore : attente réelle de la fin des `borg diff` actifs

**Problème :** `Bkp` posait le priority lock et appelait `borg create` immédiatement. Si des `borg diff` étaient encore en cours (IDX_WORKERS threads), borg ne pouvait pas acquérir le verrou exclusif → `Failed to create/acquire the lock … (timeout)`.

**Solution — `index-running` lock :**
- `Index` pose un lock `<cache>/<prefix>-<repo>-index-running.lock` (PID) au début de Phase 2 (avant le ThreadPoolExecutor), le supprime dans un `finally` après la fin de tous les diffs
- `Bkp`/`Restore` appellent `wait_index_idle(nick)` après `set_priority_lock` : attend jusqu'à 120 s que le running lock disparaisse (polling 1 s), puis lance `borg create`/`borg extract`
- Lock périmé (PID mort) → supprimé automatiquement, pas de blocage
- Séquence complète :
  1. `Bkp` set priority lock → `Index` détecte, annule les futures en attente
  2. `Bkp` attend running lock → les diffs en cours terminent, running lock supprimé
  3. `Bkp` lance `borg create` sans conflit de verrou borg

**Nouvelles méthodes `BorgHelperDB` :** `_index_running_lock_path`, `set_index_running_lock`, `clear_index_running_lock`, `wait_index_idle`

## 1.0.5 — 2026-06-06

### Priority lock par BORG_REPO (inter-nicks)

- Correction : le lock prioritaire est maintenant keyed sur `BORG_REPO` (sanitisé) plutôt que sur le nick
- Si plusieurs nicks pointent le même dépôt borg, `Bkp` sur `nick-A` interrompt `Index` sur `nick-B`, `nick-C`, etc. (même `BORG_REPO`)
- Nicks sur des dépôts différents → locks différents → aucune interférence
- Fallback sur le nick si `BORG_REPO` non disponible (comportement inchangé pour usage standalone)

## 1.0.4 — 2026-06-06

### BORG_EXE : chemin borg configurable

- Nouvelle clé de configuration `BORG_EXE` par section (ou `[DEFAULT]`)
- Spécifie le chemin complet vers l'exécutable borg (ex : `/usr/local/bin/borg1`, `/opt/borg/bin/borg`)
- Si absent : utilise `borg` depuis le `PATH` (comportement inchangé)
- Utile si plusieurs versions de borg coexistent ou si borg n'est pas dans le PATH standard

## 1.0.3 — 2026-06-06

### DiffBkp : affichage ligne par ligne depuis l'index

- Affichage un fichier par ligne : `+ chemin`, `- chemin`, `= chemin`
  - `+` = ajouté, `-` = supprimé, `=` = modifié/permissions/type (présent dans les deux archives)
- Taille affichée en fin de ligne : taille finale pour `+`, initiale pour `-`, `avant → après` pour `=`
- Types non-`modified` (`C`, `B`, `T`) affichent le code entre crochets si pas de taille (`[C]`, `[B]`, `[T]`)
- Tri alphabétique par chemin (toutes entrées mélangées, symbol différencie)
- Ligne résumé `+ N  - N  = N` à la fin
- Source : index SQLite si la paire est indexée, sinon `borg diff` + stockage automatique (comportement inchangé)
- Suppression de la `PrettyTable` pour ce résultat

## 1.0.2 — 2026-06-06

### Priorité Bkp/Restore sur Index

**Problème :** `Index` parallèle (`IDX_WORKERS` workers `borg diff`) peut bloquer le démarrage d'un `Bkp` ou ralentir une restauration par contention sur le dépôt borg.

**Solution — lock PID :**
- `Bkp` et `Restore` posent un lock fichier (`<cache>/<prefix>-<nick>-priority.lock`, contient le PID) avant tout appel `borg`, et le retirent dans un `finally` (garanti même sur `sys.exit()`/exception)
- `Index` vérifie le lock après chaque `borg diff` complété (dans la boucle `as_completed`)
  - Si lock actif (PID vivant) → annule les futures en attente, termine proprement les diffs déjà lancés
  - Affiche le nombre de paires non indexées et la commande pour reprendre
- Lock périmé (PID mort) → supprimé automatiquement, pas de blocage
- Reprise transparente : `diff_indexed_pairs` est incrémental, les paires déjà indexées sont ignorées au prochain `Index`

**Nouvelles méthodes `BorgHelperDB` :** `set_priority_lock`, `clear_priority_lock`, `check_priority_lock`, `_priority_lock_path`

## 1.0.1 — 2026-06-06

### IDX_INCLUDE / IDX_EXCLUDE : glob complet + stats fichiers exclus

**Patterns glob dans les filtres d'indexation :**
- `_idx_path_ok` distingue maintenant explicitement patron glob (contient `*`, `?`, `[`) vs préfixe plain
- Glob → `fnmatch` : `*` matche n'importe quelle séquence y compris `/`
  - `*.bak` → filtre tous les fichiers `.bak` quel que soit le répertoire
  - `/home/*/.bash_history` → filtre tous les `.bash_history` dans toute arborescence sous `/home/`
- Préfixe plain → `startswith` (comportement inchangé)

**Stats des fichiers exclus (nouvelles tables diff.db) :**
- `diff_excluded_stats` — agrégat par paire (archive_old, archive_new) et change_type : `file_count`, `total_size`
- `snap_excluded_stats` — agrégat par archive snapshot : `file_count`, `total_size`
- Compteurs accumulés en RAM pendant chaque `borg diff` / listing snapshot, écrits en lot en fin de paire
- Peuplés par `Index`, `IndexSnap (-S)` et `Bkp` (taille non disponible pour Bkp car `--list` ne donne pas les tailles)
- Nettoyés automatiquement lors du Prune (archives supprimées) et lors du force-reindex (`-F`)
- Nouvelles méthodes `BorgHelperDB` : `store_excluded_diff_stats`, `store_excluded_snap_stats`

## 1.0.0 — 2026-06-06

### Documentation : découpage en 3 fichiers

- `README.md` — présentation, installation, config, toutes les commandes CLI, crontab, codes retour
- `TECHNICAL.md` *(nouveau)* — architecture interne, schémas ERD cache.db + diff.db, indexes, flux d'indexation, gestion taille, migration schéma, Sentry
- `LIBRARY.md` *(nouveau)* — usage des classes avec exemples complets (backup, report, search, requêtes SQL directes, script de supervision, référence méthodes)

### Refactoring : architecture 3 classes, importable comme librairie

- `BorgHelperDB` : toutes les opérations SQLite (cache.db + diff.db)
- `BorgRunner` : subprocess borg + lecture/écriture borghelperrc
- `BorgHelper` : services haut niveau, combine DB + Borg

API librairie :
```python
from borgHelper import BorgHelper
bh = BorgHelper('/path/to/.borghelperrc')
bh.backup('myserver')
bh.index('myserver')
bh.report('myserver')
```

- `if __name__ == '__main__': _cli_main()` — importable sans effets de bord
- Comportement CLI identique (optab, dispatch, exit codes inchangés)
- Méthodes publiques : `backup`, `prune`, `index`, `indexsnap`, `report`, `report_offline`, `search`, `filehist`, `duidx`, `diffbkp`, `restore`, `stats`, `key`, `mount`, `umount`, `cache_info`, `cache_clean`, etc.
- 1999 lignes (−1060 vs 0.69 : suppression inline changelog, dead code, legacy functions)
- `borgHelper.py` : symlink vers `borgHelper` — import direct `from borgHelper import BorgHelper`
- README : section usage librairie + version `v1.0.0` en en-tête

## 0.69 — 2026-06-06

### Erreurs SQLite : messages explicites

- Ajout helper `_db_connect(db_path)` : capture `OperationalError` à l'ouverture et affiche un message ciblé selon la cause :
  - répertoire parent inexistant → nom du répertoire manquant
  - permission refusée sur le répertoire → chemin concerné
  - fichier existant non lisible/inscriptible → nom du fichier
  - autre cause → message brut SQLite + chemin
- `ensure_diff_db` : ajout `try/except DatabaseError` → message de corruption avec nom du fichier + instruction de suppression
- `ensure_cache_db` : même traitement

Avant : traceback Python brut sans indication du fichier.  
Après : message d'erreur actionnable avec chemin précis et cause.

## 0.68 — 2026-06-06

### Performance — `diff.db` : réduction taille et fragmentation

- **`VACUUM` après Prune** : espace des lignes supprimées récupéré immédiatement après nettoyage
- **`PRAGMA auto_vacuum=INCREMENTAL`** : récupération incrémentale des pages vides au fil du temps
- **`DIFF_KEEP = N`** dans borghelperrc : purge automatique des N+1 paires les plus anciennes de `diff_index` après chaque `Index`

```ini
DIFF_KEEP = 30   # conserver les 30 dernières paires indexées seulement
```

---

## 0.67 — 2026-06-06

### Fix — CLI : arguments positionnels non reconnus rejetés

- `borgHelper -c bkp toto` : `toto` était silencieusement ignoré, le backup tournait avec `nick = hostname`
- Désormais : erreur explicite `"Argument(s) non reconnu(s) : toto"` + rappel d'utiliser `-n <nick>`

---

## 0.66 — 2026-06-05

### Performance — `Index` : `borg diff` parallèle + insert groupé

- **Phase 1** : détermination des paires à indexer + purge groupée en une seule transaction SQLite (si `-F`)
- **Phase 2** : appels `borg diff` en parallèle via `ThreadPoolExecutor` — `borg diff` est read-only (lock partagé)
- **Phase 3** : insert groupé en une seule connexion SQLite avec commit unique
- `IDX_WORKERS` dans borghelperrc : nombre de workers parallèles (défaut : 4)

```ini
IDX_WORKERS = 8   # pour dépôts distants rapides
IDX_WORKERS = 1   # pour forcer le séquentiel
```

---

## 0.65 — 2026-06-05

### Fix — `Index` : `borg info` pour `archive_stats` uniquement si archives manquantes

- Régression 0.64 : `borg info --json --glob-archives` appelé à chaque `Index` même si `archive_stats` était complet
- Désormais : comparaison entre les archives connues de borg et celles présentes dans `archive_stats`
- `borg info` n'est appelé que si au moins une archive manque (ou `-F` forcé)

---

## 0.64 — 2026-06-05

### Ajout — `archive_stats` dans `diff.db` : tailles d'archives persistées localement

- Nouvelle table `archive_stats(nick, archive, archive_date, duration, original_size, compressed_size, deduplicated_size, nfiles)`
- Peuplée par `Bkp` : stats issues de `borg create --json` (archive juste créée)
- Peuplée par `Index` : appel `borg info --json --glob-archives` en fin d'indexation (toutes les archives)
- Nettoyée par `Prune` : `_cleanup_index_after_prune` supprime les archives prunées
- `Report -o` : colonnes `taille` et `nfiles` disponibles sans appel borg si `archive_stats` est peuplée

---

## 0.63 — 2026-06-05

### Ajout — `Report -o` : mode offline stats-only depuis diff.db

- `-o` : rapport sans aucun appel borg — lit uniquement `diff.db`
- Colonnes : dernière archive, date, +ajouté, -supprimé, =modifié (avec tailles)
- Combinable avec `-j` (JSON), `-l` (HTML), `-N <n>` (limite archives)
- Erreur explicite si `diff.db` absent ou index vide

---

## 0.62 — 2026-06-05

### Correction — `Bkp` : `borgHelper_messages` retiré du stdout

- La sortie stderr (messages `[INFO]`/`[WARNING]`) reste dans stderr — elle n'est plus copiée dans stdout
- `borgHelper_file_counts` et `borgHelper_files` (debug) restent dans le JSON stdout si exit 0

---

## 0.61 — 2026-06-05

### Changement — `Report` : `-N <n>` remplace `-b <n>` pour surcharger `DISPLAY_BKP`

- `-b` retiré de `Report` (sémantique ambiguë — dans les autres commandes `-b` = nom d'archive)
- `-N <n>` : affiche les `n` dernières archives, surcharge `DISPLAY_BKP` de la conf
- Les deux niveaux de filtrage (`prep_report` et `filtrer_lignes`) sont maintenant cohérents

---

## 0.60 — 2026-06-05

### Fix — `Report` : `filtrer_lignes` respecte maintenant `maxp`

- `filtrer_lignes` ignorait `maxp` et utilisait toujours `DISPLAY_BKP` de la conf
- Corrigé en préparation du remplacement `-b` → `-N`

---

## doc — 2026-06-05

### Documentation — README et aide intégrée mis à jour

- Schéma relationnel Mermaid ERD : `cache.db`, `diff.db` + table `archive_stats`
- `Bkp` : exemples JSON stdout (`borgHelper_file_counts`, `borgHelper_files` debug), exit codes
- `Prune` : mention purge diff.db + `archive_stats` après suppression d'archives
- `Report` : `-N n` (remplace `-b`), `-o` mode offline + description colonnes
- `Index` : `-F`, `-S`, `IDX_WORKERS` parallélisme
- `IndexSnap` retiré — remplacé par `Index -S` dans aide et README
- Usage inline (`-H`) : toutes les commandes mises à jour (Report, Bkp, Prune, Index, Init)

---

## 0.59 — 2026-06-05

### Changement — `Index -S` remplace la commande `IndexSnap`

- Nouvelle option `-S` sur `Index` : exécute uniquement le snapshot (équivalent à l'ancienne commande `IndexSnap`)
- `-S -F` : force le recalcul du snapshot seul
- `IndexSnap` retiré du dispatch CLI (la fonction interne `cmd_indexsnap` reste utilisée par `Index` et `Bkp`)

---

## 0.58 — 2026-06-05

### Ajout — `Bkp` : stdout JSON enrichi si exit 0

- `borgHelper_messages` : liste des messages stderr filtrés (`[LEVEL] msg`), hors entrées fichiers
- `borgHelper_file_counts` : dict `{change_type: count}` — nombre de fichiers par type (added, removed, modified…)
- En mode debug (`-d`) : `borgHelper_files` — liste complète des entrées fichiers (chemin + type)
- Le stderr interactif (`[LEVEL] msg`) reste inchangé
- `newretC` calculé avant les prints pour cohérence

---

## 0.57 — 2026-06-05

### Changement — `Report` : suppression de la réindexation automatique

- Le bloc auto-repair de `prep_report` (réindexation à la volée des paires manquantes) est supprimé
- Si une paire n'est pas indexée, les stats affichent `—` sans déclencher `borg diff`
- Pour indexer, utiliser explicitement `borgHelper -c Index -n <nick>`

---

## 0.56 — 2026-06-05

### Refactor — DB : déduplication de contenu, WAL, indexes couvrants

**Schéma `diff.db` — déduplication `archive_snapshot`**

- Nouvelle table `snapshot_file(id, nick, path, size, mtime)` — états de fichiers uniques, `UNIQUE(nick, path)`
- `archive_snapshot` devient une table mince `(nick, archive, archive_date, file_id)` — référence par id
- Vue `archive_snapshot_v` — jointure transparente pour toutes les lectures (Search, FileHist, DuIdx, Restore)
- `store_archive_snapshot` : `INSERT OR REPLACE INTO snapshot_file` puis `INSERT … SELECT id` — plus de duplication de paths
- Migration automatique au premier lancement : `ensure_diff_db` détecte l'ancienne colonne `path` et migre sans intervention
- `_cleanup_snapshot_file_orphans` : supprime les `snapshot_file` orphelins après prune ou force re-index

**Indexes ajoutés**

- `diff_index` : `idx_diff_nick_newtype(nick, archive_new, change_type)` — accélère `_diff_stats_for_nick`
- `diff_index` : `idx_diff_nick_date(nick, archive_new_date)` — accélère les filtres par plage de dates
- `diff_indexed_pairs` : `idx_pairs_nick(nick)` — accélère les suppressions par nick lors du prune
- `snapshot_file` : `idx_snapfile_nick_path(nick, path)` — lookup O(log n) pour l'insertion et la recherche
- `archive_snapshot` : `idx_snap_nick_archive(nick, archive)` — accélère les suppressions par archive

**WAL mode**

- `PRAGMA journal_mode=WAL` activé dans `ensure_diff_db` et `ensure_cache_db` — lectures concurrentes sans blocage

---

## 0.55 — 2026-06-04

### Fix — `Bkp` : exit 0 si stderr contient uniquement INFO/WARNING

- Borg renvoie exit code 1 quand des avertissements se produisent pendant le backup (fichiers modifiés, droits insuffisants, etc.)
- Précédemment : cet exit 1 était propagé tel quel si aucun `ERROR` n'était trouvé
- Désormais : si aucun message de niveau `ERROR` ou `CRITICAL` n'est présent dans stderr, exit code = 0
- Seule la présence d'un `ERROR` ou `CRITICAL` déclenche exit 2

---

## 0.54 — 2026-06-04

### Ajout — `Prune` : nettoyage automatique du diff.db après prune réel

- Après `borg prune` + `compact`, `_cleanup_index_after_prune()` récupère la liste courante des archives
- Supprime de `diff_index` les entrées dont `archive_new` n'existe plus
- Supprime de `diff_indexed_pairs` les paires dont `archive_old` ou `archive_new` n'existe plus
- Supprime de `archive_snapshot` et `archive_snapshot_indexed` les archives disparues
- Affiche un résumé si des entrées ont été supprimées : `N diff, N paires, N+N snapshots`
- Pas exécuté sur dry-run ; ignoré si `NOIDX=1` ou si le diff.db n'existe pas encore

---

## 0.53.1 — 2026-06-04

### Fix — suppression du `print` debug dans `getDataFromEnvOrFile`

- `"📄 Fichier trouvé : <path>"` affiché à chaque démarrage si le fichier sentry existe
- Ligne `print(f"📄 Fichier trouvé : {path}")` supprimée

---

## 0.53 — 2026-06-04

### Ajout — `Report` : option `-j` sortie JSON

- `-j` : sortie `json.dumps({'summary': ..., 'backups': ...})` à la place des tableaux ASCII/HTML
- `summary` : dict par nick (même données que le tableau résumé, stats du dernier backup incluses)
- `backups` : dict par nick → dict par archive (toutes colonnes, stats +ajouté/-supprimé/=présent)
- Mutuellement exclusif avec `-l` (HTML) : `-j` prioritaire
- Ajout de `j` dans `optab['report']` et paramètre `as_json` dans `cmd_report()`

---

## 0.52 — 2026-06-04

### Ajout — `Report` : réindexation automatique des paires manquantes

- Lors de la génération du rapport, si une archive affiche `—` en stats et que sa paire n'est pas dans `diff_indexed_pairs`, elle est réindexée automatiquement (borg diff à la volée)
- Seules les paires non indexées sont traitées — le premier dump (sans prédécesseur) est ignoré
- Les paires déjà indexées mais vides (0 changements) restent `—` (comportement attendu)
- Message de diagnostic vers `stderr` : `réindexation auto <old> → <new>`
- Après réparation, `diff_stats` est recalculé avant d'afficher le rapport

---

## 0.51.2 — 2026-06-04

### Fix — `-F` absent de `optab` pour `index` / `indexsnap`

- `-F` non listé dans `optab['index']` et `optab['indexsnap']` → `step2F` + `usage()` appelé
- Ajout de `F` dans les deux entrées `optab`

---

## 0.51.1 — 2026-06-04

### Fix — `-F` absent de `getopt`

- `-F` n'était pas déclaré dans la chaîne `getopt` → `option -F not recognized` à l'exécution
- Ajout de `F` (sans `:`, flag sans argument) dans la chaîne getopt

---

## 0.51 — 2026-06-04

### Ajout — `Index` / `IndexSnap` : option `-F` (force réindexation)

- `-F` force la réindexation même si les paires/snapshots sont déjà présents en cache SQLite
- `cmd_index -F` : supprime les entrées `diff_index` + `diff_indexed_pairs` existantes avant de réindexer chaque paire
- `cmd_indexsnap -F` : supprime `archive_snapshot` + `archive_snapshot_indexed` de la dernière archive avant réindexation
- Utile quand l'index existe mais contient des données manquantes ou corrompues
- Propagé automatiquement : `Index -F` appelle `IndexSnap -F` en fin de traitement

---

## 0.50 — 2026-06-04

### Ajout — `Restore` : `-w -` / `-W -` → tar vers stdout

- `where == '-'` : tar non-compressé streamé vers `sys.stdout.buffer` (`mode='w|'`)
- Fonctionne avec `-w -` (arborescence) et `-W -` (plat)
- Tous les messages informatifs (archive sélectionnée, erreurs) redirigés vers stderr pour ne pas corrompre le flux binaire
- `BrokenPipeError` géré proprement (pipe fermé par le lecteur → exit 0)
- Exemple : `borgHelper -c Restore -n srv -f 'home/user' -w - | tar -tvf -`
- Exemple : `borgHelper -c Restore -n srv -f 'home/user' -w - | ssh autre "tar -xf - -C /restore"`

---

## 0.49.5 — 2026-06-04

### Ajout — `Report` : `=présent` avec taille disque et %

- `present_sz = original_size - added_sz - modified_sz` (calculé sans requête supplémentaire)
- Format : `N (P%) · SIZE (S%)` — cohérent avec `+ajouté` et `-supprimé`

---

## 0.49.4 — 2026-06-04

### Ajout — `Report` : taille disque exprimée en % dans les stats

- `_fmt_stats(s, nf, total_sz)` : nouveau paramètre `total_sz` = `original_size` de l'archive courante
- Format : `N (P%) · SIZE (S%)` — ex : `12 (3%) · 3.2 MiB (1%)`
- `=présent` : nb fichiers + % uniquement (taille des fichiers stables non stockée dans diff_index)
- Dénominateur taille : `original_size` du backup courant (disponible depuis borg info)

---

## 0.49.3 — 2026-06-04

### Ajout — `Report` : stats dans le tableau résumé + taille disque

#### Tableau résumé du haut (par serveur)
- Colonnes `+ajouté`, `-supprimé`, `=présent` ajoutées : stats du **dernier backup**
- Format : `N (P%) · SIZE` pour ajouté/supprimé, `N (P%)` pour présent
- `—` si l'index n'a pas encore été construit pour ce nick

#### Taille disque dans les stats (tous tableaux)
- `_diff_stats_for_nick` : requête étendue avec `SUM(size_after)` / `SUM(size_before)`
- added → `size_after` (taille des nouveaux fichiers)
- removed → `size_before` (taille des fichiers supprimés)
- modified → `size_after` (taille après modification)
- Format unifié via `_fmt_stats(s, nf)` : `"N (P%) · X MiB"`

---

## 0.49.2 — 2026-06-04

### Correctifs

#### `_diff_stats_for_nick` : `sqlite3.connect` manquant
- `conn=get_diff_db(nick)` retournait un chemin (string) au lieu d'une connexion
- `conn.execute(...)` → `AttributeError` → avalé par `except Exception: return {}` → stats toujours `—`
- Fix : `db_path=get_diff_db(nick)` + `conn=sqlite3.connect(db_path)`

#### `boex` : `KeyboardInterrupt` non géré
- Ctrl-C pendant `ps.communicate()` provoquait un traceback Python + message Sentry
- Fix : `try/except KeyboardInterrupt` autour de `communicate()` → `ps.kill()` + exit 130

---

## 0.49.1 — 2026-06-04

### Correctif — `Report` : colonnes stats toujours visibles en ASCII

- `prettyTabelise` auto-découvre les colonnes depuis les clés des entrées → si aucune archive n'a de stats (index absent), les colonnes n'apparaissaient pas
- Fix : toutes les vraies archives (celles avec `nfiles`) reçoivent toujours les 3 colonnes (`+ajouté`, `-supprimé`, `=présent`), avec `'—'` quand aucune donnée d'index n'est disponible
- Résultat : colonnes présentes dans ASCII et HTML, que l'index soit construit ou non

---

## 0.49 — 2026-06-04

### Ajout — `Report` : statistiques % ajoutés/supprimés/présents par backup

- Nouvelle fonction `_diff_stats_for_nick(nick)` : agrège les counts par type depuis `diff_index` pour chaque archive
- Calcul par archive : `+ajouté`, `-supprimé`, `=présent` en nb de fichiers et % relatif au total de la backup précédente
- Formule : `total_précédent = nfiles_courant - ajoutés + supprimés` (derivé de `nfiles` borg info)
- Format d'affichage : `N (P%)` — ex : `12 (3%)` / `5 (1%)` / `380 (96%)`
- Si pas d'index pour l'archive : colonnes absentes (pas d'erreur)
- Colonnes ajoutées dans les tables ASCII (prettyTabelise) et HTML (htmlTabelise)

---

## 0.48 — 2026-06-04

### Ajout — `Restore` : préservation des droits d'origine + option `-L` (liste des droits)

#### Droits d'origine dans le tar (`--numeric-owner`)
- `borg extract` appelé avec `--numeric-owner` : préserve les uid/gid numériques des fichiers extraits
- `tarfile.add()` capture `mode`, `uid`, `gid`, `mtime` via `os.lstat()` sur les fichiers extraits
- Résultat : le tar contient les droits/propriétaires exacts de l'archive d'origine (quand lancé en root)

#### Option `-L` : affichage des droits sans restauration
- `borgHelper -c Restore -n <nick> -f <chemin> -L`
- Affiche les droits des fichiers/répertoires correspondants (format `ls -la`) depuis l'archive
- Si `-b` absent : recherche via SQLite la dernière archive contenant le fichier (comme `Restore` normal)
- Sortie redirigeable vers un fichier texte : `borgHelper -c Restore -n srv -f 'home/*' -L > droits.txt`
- Implémenté via `borg list --format '{mode} {user:8} {group:8} {size:>12} {isomtime} {path}{NL}'`

---

## 0.47.2 — 2026-06-04

### Correctif — `Restore` : `OSError: No space left on device`

- `_restore_to_tar` et restauration plate (`-W`) : `OSError` attrapé autour des opérations d'écriture
- `errno 28` (ENOSPC) : message `[ERREUR] Espace disque insuffisant sur la cible : <fichier>` + exit 3
- Autres `OSError` : message d'erreur + exit 3
- Le répertoire temporaire est nettoyé proprement dans tous les cas (context manager)

---

## 0.47.1 — 2026-06-04

### Ajout — `IDX_INCLUDE` et `IDX_EXCLUDE` dans borghelperrc

- `IDX_INCLUDE = /etc /home /root` : liste blanche — seuls ces chemins sont indexés
- `IDX_EXCLUDE = /proc /sys /tmp /var/log` : liste noire — ces chemins sont exclus de l'index
- Support préfixe et glob (`*`, `?`) pour chaque entrée
- Si les deux sont définis : `IDX_INCLUDE` filtre d'abord, puis `IDX_EXCLUDE` s'applique
- Appliqué dans : `Index` (diffs), `IndexSnap` (snapshot), `Bkp` (--list parsing)

---

## 0.47 — 2026-06-04

### Ajout — `NOIDX` et détection index vide

#### `NOIDX = 1` dans borghelperrc
- Désactive toute indexation pour ce nick : `Index`, `IndexSnap`, et `Bkp` (en plus du flag `-I`)
- Message informatif quand le nick est ignoré

#### Index vide → erreur explicite
- `_is_index_empty(nick)` : vérifie si `diff_index` et `archive_snapshot` sont tous deux vides pour ce nick
- `Search`, `FileHist`, `DuIdx` : si index vide pour un nick → `[ERREUR] Index vide pour X — lancez : borgHelper -c Index -n X`
- Permet de distinguer "aucun résultat" de "index jamais initialisé"

---

## 0.46.2 — 2026-06-04

### Correctifs — `IndexError: list index out of range`

- `_boex_check_stdout` : helper commun qui lève `RuntimeError` si `boex` retourne stdout vide ou code d'erreur
- `getlastbkp` : crash si borg list échoue → RuntimeError propagée aux appelants
- `cmd_index` : borg list inaccessible → message d'erreur + return 1 (ne crash plus)
- `cmd_indexsnap` : même fix
- `cmd_diffbkp` : même fix → exit 2

---

## 0.46.1 — 2026-06-04

### Améliorations — `Restore`

- `-f` accepte les globs `*` et `?` (ex : `etc/nginx/*.conf`, `home/user*`)
  - Avec glob : `borg extract --pattern=sh:...` utilisé à la place du chemin direct
  - `_find_last_archive_with_file` utilise `LIKE` sur l'index SQLite pour les patterns
- Structure des répertoires préservée dans les tar (sous-répertoires inclus par défaut)
- `-w <dest>` : restauration avec sous-répertoires (comportement précédent)
- `-W <dest>` : restauration plate — fichiers à la racine, sans arborescence
  - Pour tar : `arcname = basename(fichier)`
  - Pour répertoire : copie plate via `shutil.copy2`
- `.tgz` existant : exit 3 avec message d'erreur (au lieu de warning + écrasement silencieux)

---

## 0.46 — 2026-06-04

### Améliorations — `Restore`

#### Sans `-b` : sélection automatique de l'archive depuis le SQLite
- `_find_last_archive_with_file` : cherche dans `archive_snapshot` puis `diff_index` la dernière archive connue contenant le chemin
- Si trouvée : utilisée et affichée ; sinon : fallback sur la dernière archive (comportement précédent)

#### `-w .tar` ou `-w .tgz` : sortie archive tar
- Extraction vers un répertoire temporaire puis création/append du tar via Python `tarfile`
- `.tar` : append si le fichier existe déjà
- `.tgz` / `.tar.gz` : recréation (gzip ne supporte pas l'append) avec warning si le fichier existe
- Répertoire temporaire nettoyé automatiquement

#### Fix
- `cmd_resto` : affichage stderr propre au lieu de `print(rb)` (dump dict brut)

---

## 0.45.2 — 2026-06-04

### Ajout — `BORG_KEY_FILE` dans borghelperrc

- `boex` passe `BORG_KEY_FILE` à borg si la clé est définie dans la section du nick
- Utile quand plusieurs nicks partagent le même dépôt physique avec chiffrement `keyfile`
- Inactif si absent de la conf (pas d'effet de bord)

---

## 0.45.1 — 2026-06-04

### Optimisation — `Report` : cache du prune dry-run + 1 seul appel borg info

- `_boex_last_modified(nick)` : extrait le point commun des deux caches
- `cache_prune_dryrun(nick, last_modified)` : met en cache le résultat de `borg prune --dry-run` (clé `{nick}:prune` dans `cachejsonboexlm`)
- `cacheJsonBoexWithLM` : accepte `last_modified=` pour éviter un appel borg info redondant
- `prep_report` : **1 seul `borg info --json`** par nick → `last_modified` partagé entre les deux caches
- Cache hit complet : 1 appel réseau au lieu de 3 (borg info + borg info --glob + prune dry-run)
- Fix : `suffix="-info.json"` retiré de l'appel `cacheJsonBoexWithLM` dans `prep_report` (TypeError latent)
- `clear_cache_nick` : purge aussi `{nick}:prune`
- `cmd_cache_clean` : purge aussi les entrées `:prune` périmées

---

## 0.45 — 2026-06-04

### Ajout — `Bkp` : indexation automatique pendant le backup

- Par défaut, `Bkp` ajoute `--list --filter AMCBTd` au `borg create`
- Après backup réussi : parse la sortie `--list` (entrées `borg.output.list`) → stocke dans `diff_index`
- Appelle ensuite `IndexSnap` pour le snapshot de la nouvelle archive
- Entrées list masquées dans l'affichage stderr (sauf debug) — évite des milliers de lignes `[INFO] A /etc/...`
- `-I` : désactive tout (pas de `--list`, pas d'indexation)
- Statuts capturés : `A`→added, `M`→modified, `C`/`B`/`T`→flags, `d`→removed
- Note : les tailles ne sont pas disponibles depuis `--list` (stockées à `None`) — `DuIdx` affichera `—` pour ces entrées

---

## 0.44.3 — 2026-06-04

### Correctifs — `Report` : gestion des erreurs borg par nick

- `cacheJsonBoexWithLM` : si `borg info` retourne un code non-nul ou stdout vide, lève `RuntimeError` avec le message d'erreur borg (fin du crash IndexError)
- `cmd_report` : attrape l'exception par nick, affiche une ligne erreur dans le tableau (rouge en HTML, `*** ERREUR` en ASCII), note exit code 2, continue les autres nicks
- Colonne `reste` contient le message d'erreur tronqué pour identification rapide

---

## 0.44.2 — 2026-06-04

### Ajout — `-B <archive>` borne de fin pour `Search`, `FileHist`, `DuIdx`

- `-B <archive>` : limite la recherche jusqu'à cet archive (inclus)
- Combinable avec `-b` : `-b X -B Y` → plage [X, Y]
- `-b ALL -B Y` → tout l'index jusqu'à Y
- Sans `-B` : comportement inchangé (jusqu'au dernier)

---

## 0.44.1 — 2026-06-04

### Correctifs — Aide `-h` / `-H`

- `-h` général : ajout `IndexSnap`, `DuIdx`, mention `-b` pour `Search`/`FileHist`
- `-H indexsnap`, `-H duidx` : nouvelles entrées détaillées
- `-H search`, `-H filehist` : mention de `-b` et du snapshot
- `-H index` : mention de l'appel automatique à `IndexSnap`

---

## 0.44 — 2026-06-04

### Ajout — Filtre plage d'archives pour `Search`, `FileHist`, `DuIdx`

- Sans `-b` : uniquement la dernière paire d'archives (archive_new = MAX)
- `-b <archive>` : depuis cet archive jusqu'au dernier (archive_new_date ≥ date de l'archive)
- `-b ALL` : tout l'index, toutes les paires
- Filtre appliqué aussi sur la clause `NOT EXISTS` du snapshot (présent)

---

## 0.43.1 — 2026-06-04

### Correctifs et améliorations — `DuIdx`

- Fix : colonne `added/modif` toujours vide (clé `'added/modif'` vs `'added'` dans le dict)
- Vue pivotée : tri par colonne avec `-s <col>[:asc|desc]` — valeurs : `chemin`, `added`, `removed`, `present`
- Sortie JSON avec `-j` — structure `{pattern, rows:[{chemin, added/modif:{nb,taille}, ...}], total}`

---

## 0.43 — 2026-06-04

### Ajout — commande `DuIdx`

- Résumé `du -sh`-like à partir du SQLite : taille totale et nombre de fichiers par type de changement
- Types : `added`, `modified`, `removed`, `C`, `B`, `T`, `présent` (stables)
- Pattern de chemin : sous-chaîne libre ou glob `*`/`?` (ex : `home/*`, `*.conf`)
- `-f` optionnel — défaut `*` (tout le dépôt)
- Ligne TOTAL en bas du tableau
- Taille : `size_after` pour added/modified, `size_before` pour removed, `size` pour présent
- Note : les entrées `diff_index` comptent les événements, pas les fichiers uniques

---

## 0.42.2 — 2026-06-04

### Ajout — `DB_NAME` dans borghelperrc

- Nouvelle clé optionnelle `DB_NAME` dans la section d'un dépôt
- Si définie, remplace le nick dans le nom des fichiers SQLite : `<conf>-<DB_NAME>-cache.db`
- Utile quand plusieurs nicks partagent le même dépôt physique
- Caractères non alphanumériques sanitisés automatiquement

---

## 0.42.1 — 2026-06-04

### Changement cassant — Un SQLite par nick

- Chaque dépôt (nick) possède désormais ses propres fichiers DB
- Nommage : `<conf>-<nick>-cache.db` et `<conf>-<nick>-diff.db`
- `get_cache_db(nick)` / `get_diff_db(nick)` remplacent les globals `cache_db_file` / `diff_db_file`
- `cmd_cache_info`, `cmd_cache_clean`, `cmd_search`, `cmd_filehist` : connexion par nick
- **Migration** : relancer `Index` et `IndexSnap` pour reconstruire les index dans les nouveaux fichiers

---

## 0.42 — 2026-06-04

### Changement cassant — Emplacement des fichiers DB

- Les deux DBs SQLite (`-cache.db` et `-diff.db`) sont maintenant dans `~/.cache/borghelper/` par défaut
- Le nom des fichiers inclut le basename sanitisé du fichier de configuration : `borghelperrc-cache.db`, `borghelperrc-diff.db`
- Configurable via la clé `CACHE_DIR` dans la section `[DEFAULT]` de `.borghelperrc`
- Exemple avec `-C /etc/borg-prod.rc` → `~/.cache/borghelper/borg-prod_rc-cache.db`
- **Migration** : les anciens `~/.borghelper-cache.db` et `~/.borghelper-diff.db` ne sont plus utilisés — relancer `Index` et `IndexSnap` pour reconstruire les index

---

## 0.41.1 — 2026-06-04

### Correctifs — `IndexSnap`

- `borg list --json ::archive` non supporté dans borg 1.x pour le contenu d'une archive → remplacé par `borg list --format '{size} {isomtime} {path}{NL}' ::archive` avec parse ligne par ligne
- Affichage du stderr borg en cas d'échec (était silencieux)

---

## 0.41 — 2026-06-04

### Ajouts — Snapshot archive + recherche de fichiers stables

#### Nouvelle table `archive_snapshot`
- Stocke le listing complet des fichiers de la dernière archive (`borg list --json ::archive`)
- Clé : `(nick, archive, path)` — incrémental, paires déjà indexées ignorées
- Champs : nick, archive, archive_date, path, size, mtime

#### Nouvelle commande `IndexSnap [-n nick/ALL]`
- Indexe le listing de la dernière archive de chaque nick
- Appelée automatiquement par `Index` à la fin de chaque indexation de diffs

#### `Search` étendu
- Résultats UNION : diff_index (changements) + archive_snapshot (fichiers présents sans historique de changement)
- Les fichiers stables depuis plus longtemps que la rétention de prune apparaissent maintenant avec le type `présent`

#### `FileHist` étendu
- Ajoute les lignes `présent` depuis archive_snapshot, triées chronologiquement avec le reste

---

## 0.40.3 — 2026-06-04

### Refactoring — `DiffBkp` sur SQLite

- `DiffBkp` utilise désormais `~/.borghelper-diff.db` au lieu d'appeler `borg diff` en direct
- Si la paire d'archives n'est pas encore indexée, le diff est calculé et stocké automatiquement à la volée
- Affichage en tableau (prettytable) : colonnes type / chemin / taille avant / taille après
- Paires indexées via `Index` : réponse instantanée, sans appel réseau

---

## 0.40.2 — 2026-06-04

### Correctifs — `cmd_bkp` : affichage et codes retour

- Suppression du double affichage : `boex()` n'imprime plus `stderr` directement — c'est `cmd_bkp` qui gère
- Stderr parsé (JSON borg) : chaque entrée affichée sous forme `[LEVELNAME] message` (lisible humain)
- Stderr fallback (strings, cas JSONDecodeError) : chaque ligne non-vide affichée telle quelle
- Code retour : si borg sort avec code ≠ 0 et qu'aucun dict `ERROR` n'est trouvé dans stderr, le code retour borg est propagé directement (couvre la branche fallback de 0.39.1)

---

## 0.40.1 — 2026-06-03

### Suppressions
- `cmd_bkp` n'écrit plus `/tmp/borgHelper-bkp-<nick>.json`
- Commande `poc` supprimée (commande debug morte qui lisait ce fichier)

---

## 0.40 — 2026-06-03

### Ajouts

#### Cache persistant (`~/.borghelper-cache.db`)
- Cache déplacé de `/tmp/borgsql.db` vers `~/.borghelper-cache.db` (persistant entre reboots)
- `purge_stale_cache` : supprime les entrées périmées dès que `last_modified` du dépôt change
- `clear_cache_nick` : vide tout le cache d'un nick — appelé automatiquement après `DelBkp` et `Prune`
- Nouvelle commande `CacheInfo [-n nick/ALL]` : affiche le contenu du cache (nick, last_modified, taille)
- Nouvelle commande `CacheClean [-n nick/ALL]` : nettoyage manuel des entrées périmées et des nicks inconnus

### Correctifs
- `cacheJsonBoexWithLM` : `return(ret[0])` → `return(details[0])` (bug : `ret` non défini)
- `cacheJsonBoexWithLM` : suppression des paramètres inutilisés `prefix` et `suffix`

---

## 0.39.1 — 2026-06-03

### Correctifs
- `boex` : `ret['stderr']=theJson` stockait la chaîne brute au lieu de la parser → `json.loads(theJson)`
- `boex` : le `except` re-encodait en JSON → crash sur tout `\` dans le texte (chemins Windows, messages borg)
- Fallback : `except json.JSONDecodeError` → split lignes brutes (cohérent avec la branche `else`)

---

## 0.39 — 2026-06-03

### Ajouts

#### Index diff — historique des changements de fichiers
- Nouvelle commande `Index [-n nick/ALL]` : indexe les diffs entre archives consécutives dans `~/.borghelper-diff.db`
- Incrémental : les paires déjà traitées sont ignorées (`diff_indexed_pairs`)
- Nouvelle commande `Search -f <pattern> [-n nick/ALL]` : recherche par nom de fichier (sous-chaîne ou glob `*`/`?`)
- Nouvelle commande `FileHist -f <chemin> [-n nick/ALL]` : historique complet d'un chemin exact
- Parsing de la sortie `borg diff` : `added`, `removed`, `modified` (avec tailles avant/après), `C`, `B`, `T`
- Tailles stockées en octets entiers, affichées via `convert_octets_readable`

#### Mount
- Sans `-b` : monte toutes les archives (`ALL`) — était la dernière archive
- `-b last` : comportement précédent (dernière archive uniquement)

---

## 0.38.2 — antérieur

- Division par zéro corrigée dans `prep_report` (cas 0 archives)

## 0.38.1

- Correctifs et amélioration de la partie Sentry

## 0.38

- Cache des appels `borg info/list` en SQLite — remplace les fichiers JSON temporaires

## 0.37

- Fichier de conf paramétrable (`-C`)

## 0.36.2

- Correction version + déplacement import Sentry

## 0.36

- Intégration Sentry (DSN via env, fichier ou `/usr/local/etc/borghelper-sentry`)

## 0.35

- Rapport HTML colorisé et limité

## 0.34

- Export de clef (`Key`)

## 0.33

- `Mount` sur la dernière archive ou archive précisée

## 0.32

- `ALL` exclut les sections sans archives

## 0.31

- Nom serveur en tête de tableau dans `Report`

## 0.30

- `BORG_ARCHNAME` commençant par `::` → nom d'archive complet

## 0.29

- `-n ALL` pour `Report` et `Prune`
- `Prune` opérationnel

## 0.27

- `Report` multi-host fonctionnel (texte + HTML)

## 0.22

- `Init` : initialisation repo local (`repokey`)

## 0.20

- `BORG_ARCHNAME` et `BORG_ROOTBKP` configurables

## 0.1

- Première version officielle

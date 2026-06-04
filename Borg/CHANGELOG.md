# Changelog — borgHelper

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

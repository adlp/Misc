# Changelog — borgHelper

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

# Changelog — borgHelper

## borgHelper 1.0.102 — chiffrement des chemins SQLite, story 3 : écriture — 2026-09-22

Fait passer chaque écriture de chemin par le codec et pose la barrière de migration (AD-11), sans chiffrer aucune base
réelle (`DbEncrypt` reste Story 5). **Aucun changement observable en `plain`** : `_path_stored`/`_write_mode_check` sont
des no-op/silencieux tant qu'aucun `enc_header` n'existe ; vérifié par `CodecSelfTest` (257/257) et par un `Bkp`/`Index`
complet sur `demo.borghelperrc`.

- **Écriture de chemin unifiée (AD-3/AD-8).** `store_diff_entries`, `store_archive_snapshot`, `_indexsnap_incremental`
  (chemins ajoutés via `borg list`) et le bloc d'écriture inline de `index()` passent désormais chaque valeur de chemin
  par `_path_stored(conn,path)` avant le paramètre SQL — les 4 sites qui écrivaient encore un chemin en clair,
  indépendamment du mode de la connexion.
- **Barrière de migration `_write_mode_check(conn)` (AD-11).** Relit `enc_header.path_enc` dans la transaction en cours
  et le compare au mode constaté à l'ouverture (`conn.mode`) ; lève `DbModeError` avant tout `INSERT`/`UPDATE`/
  `executemany` de chemin si le mode a changé depuis l'ouverture (migration passée en `migrating` entre-temps). Posée en
  tout premier dans les 4 sites ci-dessus — `_indexsnap_incremental` la pose deux fois : à l'ouverture, puis à nouveau
  juste avant la seconde phase d'écriture (fichiers ajoutés), qui suit un appel `borg list` en sous-processus capable de
  durer assez longtemps pour qu'un changement de mode survienne entre les deux. Ce n'est **pas** un verrou d'exclusion
  mutuelle (pas de `BEGIN IMMEDIATE` généralisé) — une garde de cohérence sur laquelle la Story 5 (`DbEncrypt`,
  compare-and-swap) s'appuiera sans retoucher ces sites.
- **`index()` : `DbModeError` interceptée spécifiquement, une fois par run.** Avant le `except Exception` générique
  existant : sur la première occurrence, la paire n'est ni marquée indexée ni committée, `set_index_pending_lock(nick)`
  est appelée (mécanisme `index_pending` existant, réutilisé sans être dupliqué), et un message dédié est imprimé
  (jamais « borg diff échoué »). Le mode changé étant durable pour le reste du run, un drapeau local évite de
  re-tester la barrière et d'écrire pour chaque paire restante — sans ce drapeau, chaque paire suivante émettait son
  propre `set_index_pending_lock`/message, bruyant et redondant. `Bkp` ne peut jamais échouer à cause de cette erreur :
  `index()` retourne normalement comme pour toute paire en échec.
- **`indexsnap()` : `DbModeError` interceptée spécifiquement (tentative incrémentale + fallback).** Même traitement que
  ci-dessus (message dédié, `set_index_pending_lock`, retour `1`, pas de "traceback"). Corrige un bug réel repéré en
  revue : sans cette interception, une `DbModeError` levée par `_indexsnap_incremental` remontait NON attrapée à
  travers `indexsnap()` puis l'appel `self.indexsnap(...)` en fin d'`index()` — masquée en échec générique par le
  `try/except Exception` de `backup()` (pas d'`index_pending` posé), mais une traceback brute jusqu'à l'utilisateur
  via `Index`/`Index -S` en CLI direct (aucun `try/except` englobant sur ce chemin).
- **`ensure_diff_db`/`ensure_cache_db(db_path, create=True)` (AD-12).** **Tous** les appelants de lecture — l'ensemble
  complet, pas un sous-ensemble — passent désormais `create=False` : `TreeHist`, `TreeFind`, `Search`, `DuIdx`,
  `ListBkp`, `ListBkpFiles`, `FileHist`, `DiffBkp`, `Report` en mode DB-only, `CacheInfo`
  (`BorgHelperDB.get_cache_rows`), purge/consultation de cache, recherche de dernière archive. Une base absente ou vide
  n'est plus créée par une simple lecture, qui répond « non indexé »/« index vide » comme si la base existait mais
  était vide. Seuls `Index`, `Bkp` et `indexsnap` (créateurs légitimes) gardent le défaut `create=True`.
  `list_backups`, `list_files` et `prep_report_from_db` gèrent maintenant explicitement l'absence de schéma
  (`sqlite3.OperationalError` contenant `no such table`, narrowé — pas un `except sqlite3.Error` générique qui
  confondrait une vraie corruption/erreur disque avec « jamais indexé ») comme un index vide, ferment systématiquement
  leur connexion sur ce chemin, et laissent remonter toute autre erreur — nécessaire car `_open_db` touche toujours un
  fichier 0 octet même en lecture seule (permissions à la création), donc `os.path.exists` seul ne suffit plus à
  distinguer « jamais indexé » de « base réelle » : nouvel helper `_db_has_schema(db_path)` (au moins une table,
  `timeout=60` comme `_open_db` ailleurs — un `database is locked` transitoire ne doit pas se lire comme « pas de
  schéma »), utilisé par `ensure_*_db(create=False)` et ces trois fonctions.
  `cache_prune_dryrun`, `cacheJsonBoexWithLM` (cache de sortie `boex`) et `diffbkp` restent des créateurs légitimes sur
  leur propre chemin d'écriture : elles ne créent plus la base pour un simple lookup (`create=False` au début, comme les
  autres lecteurs), mais réappellent `ensure_*_db()` (`create=True`, défaut) juste avant d'écrire un résultat en cache
  ou une paire nouvellement diffée — un miss de cache confirmé, ou une paire non indexée, écrivent toujours comme avant
  ; seul le lookup initial ne crée plus rien. `cache_prune_dryrun`/`cacheJsonBoexWithLM` n'appellent
  `purge_stale_cache(...)` (`role='write'`, touche aussi le fichier à l'ouverture) que si `_db_has_schema(db_path)` est
  déjà vrai — rien à purger, et rien à toucher, pour un cache jamais écrit.
- **`CodecSelfTest`** : aller-retour d'écriture (`store_diff_entries`/`store_archive_snapshot`) sur une base chiffrée
  temporaire ; simulation de bascule de mode pendant une transaction ouverte (`_write_mode_check` lève `DbModeError`,
  propagée sans être avalée, aucune ligne écrite) ; simulation équivalente pour `indexsnap()` (retour `1`,
  `index_pending` posé, pas de traceback) ; vérification qu'un nick jamais indexé/jamais mis en cache ne crée aucun
  schéma via l'ensemble des sites de lecture convertis (`ensure_diff_db`/`ensure_cache_db(create=False)`), y compris
  ceux qui appellent `borg` avant d'écrire (`boex` monkeypatché pour échouer immédiatement, déterministe).

## borgHelper 1.0.101 — chiffrement des chemins SQLite, story 2 : requêtes — 2026-09-22

Rend toutes les lectures de chemins indépendantes du mode (`plain`/chiffré) : préfixes et égalités passent par des
bornes/valeurs fournies par le codec, prédicats sur le nom et tris s'exécutent en Python sur des chemins décodés quand la
connexion est chiffrée (AD-8, AD-16). **Aucune base n'est chiffrée** : en `plain` les sorties et codes de sortie sont
inchangés, aux exceptions ci-dessous ; le mode chiffré est vérifié par `CodecSelfTest` sur des bases temporaires.

- **Comportements modifiés en `plain` par rapport à `a53b9fa`** (toutes les sorties `plain` étaient auparavant garanties
  identiques : les points ci-dessous sont les seules exceptions, listées explicitement ; le dernier documente au
  contraire un comportement volontairement PRÉSERVÉ malgré un changement qui aurait pu l'affecter) :
  - **Préfixe sensible à la casse (AD-16).** Un préfixe de chemin (`TreeHist -f`, `TreeFind -f`, `FileHist -f`,
    `DuIdx -f 'préfixe/*'`, `IdxPurge -x préfixe`) ne correspond plus qu'à la casse exacte : `/Etc` ne trouve plus `/etc`
    (l'ancien `LIKE` était insensible à la casse ASCII et n'utilisait pas l'index). Les préfixes sont aussi littéraux :
    `%` et `_` n'y sont plus des jokers (`DuIdx -f 'a%b/*'` ne remonte plus `aXYZb/…`, `TreeHist -f a%b` non plus).
    `Search`, `DuIdx` sans `/*` et `IdxPurge` (glob) gardent leurs prédicats de nom inchangés (`LIKE` insensible à la casse
    ASCII, `GLOB` sensible) et `FileHist` reste une égalité exacte (après normalisation, voir point suivant).
  - **Préfixe/chemin normalisé.** Un `/` initial ou final, ou un `//` interne, dans un préfixe (`TreeHist -f`,
    `TreeFind -f`, `DuIdx -f 'préfixe/*'`) ou un chemin exact (`FileHist -f`) est maintenant retiré/fusionné avant
    comparaison, dans les deux modes (`plain` comme chiffré, un seul normaliseur `_norm_lp`) : `-f /etc`, `-f etc/` et
    `-f etc` donnent désormais le même résultat, `FileHist -f /etc/passwd` trouve la même entrée que
    `FileHist -f etc/passwd`. Auparavant le comportement différait selon la présence de ces caractères (l'ancien `LIKE`
    de préfixe les traitait différemment de l'égalité de `FileHist`, elle-même sensible au moindre `/` superflu).
  - **`DuIdx` global : correction du filtre de plage d'archives.** `_duidx_collect_global` plaçait la condition de plage
    (`archive_new=?`, dernière archive par défaut) *après* le `GROUP BY` : elle devenait une expression de regroupement
    au lieu d'un filtre, si bien que toutes les entrées de diff étaient comptées, toutes archives confondues, sous un
    seul type arbitraire. La condition est maintenant placée avant le `GROUP BY` : le résumé global par type change (il
    est désormais correct). Nécessaire pour que `DuIdx` donne les mêmes résultats en `plain` et en chiffré.
  - **Ordre des lignes non contractuel.** `DuIdx -R`, `IdxTop -j` et `DiffTop -j` peuvent renvoyer leurs lignes dans un
    ordre différent (ordre d'index au lieu de l'ordre de table) : ces sorties n'ont jamais été triées, l'ordre n'était
    qu'un détail d'implémentation de l'ancien `LIKE`/balayage de table.
  - **`IdxPurge` avec un `/` initial : comportement inchangé.** Un pattern (`-x` ou une entrée `IDX_INCLUDE`/`IDX_EXCLUDE`)
    commençant par `/` ne cible toujours rien (les chemins stockés n'ont jamais de `/` initial) — vérifié explicitement
    malgré la normalisation ci-dessus, qui ne s'applique pas à `IdxPurge` (commande destructive : on préserve son
    comportement historique plutôt que de le faire bénéficier de la normalisation).
- **Index de chemin.** Un préfixe devient `path >= 'p/' AND path < 'p0'` (plus de `LIKE 'p/%'`, de
  `(path=? OR path LIKE ?)`, de `NOT LIKE 'p/%/%'` ni de `_like_escape`, supprimé) : `diff_index` et `snapshot_file`
  utilisent `idx_diff_nick_path` / `idx_snapfile_nick_path`. La vue `archive_snapshot_v` balaie toujours par
  `(nick, archive)` puis filtre le chemin (comportement inchangé, voir TECHNICAL.md).
- **`TreeHist`** : la profondeur se calcule en Python après décodage ; les enfants supprimés se cherchent par chemins
  distincts du sous-arbre puis par dernier événement des seuls enfants directs (plus de fenêtre `ROW_NUMBER` sur tout le
  sous-arbre) ; la détection des événements descendants d'un répertoire n'interprète plus `%`/`_` du nom du répertoire.
- **Tris en Python** (ordre octet UTF-8, identique à l'ancien tri SQLite) pour `ListBkpFiles`, `DiffBkp` et `Search`.
- **Chiffré uniquement** : helpers `_path_range`/`_psel_under`/`_psel_eq`/`_psel_like`/`_psel_glob`/`_path_decode`/
  `_path_stored`/`_path_sort_key`, `DbCodec.decode_path` (mémo borné à 262 144 entrées, partagé entre connexions du processus),
  `LIKE` ASCII et `GLOB` reproduits en Python (regex en cache borné), `PRAGMA case_sensitive_like=ON` sur les seules
  connexions chiffrées, `IdxPurge` : préfixe par intervalle, glob en Python, `DELETE` par `id`.
- **`CodecSelfTest`** : parité plain/chiffré sur `TreeHist`, `TreeFind` (dont supprimés), `Search`, `FileHist`, `DuIdx`,
  `IdxTop`, `DiffTop`, `ListBkpFiles`, `IdxPurge` (préfixe, glob, `IDX_INCLUDE`/`IDX_EXCLUDE`), RBAC (`_path_in_scope`),
  jeu de chemins avec `%`, `_`, casse différente, imbrication, racine, non UTF-8 ; comparaison `LIKE`/`GLOB`/tri avec
  SQLite ; plans `EXPLAIN QUERY PLAN` ; aucun `LIKE`/`GLOB`/`ORDER BY path` émis sur une connexion chiffrée.

## borgHelper 1.0.100 / borgHelperWWW 1.15.1 — chiffrement des chemins SQLite, story 1 : fondations — 2026-09-21

Première brique du chiffrement des chemins/payloads des bases SQLite (architecture : AD-1 à AD-5, AD-10,
AD-12, AD-14). **Aucune donnée n'est chiffrée ni migrée** : toutes les bases restent `plain` et se
comportent exactement comme avant (mêmes sorties, mêmes codes de sortie, mêmes requêtes SQL).

- **Ouverture unique** : `_open_db(db_path, nick=None, role='read', passphrase=None, **kw)` remplace
  `BorgHelperDB._db_connect` (méthode supprimée, remplacée par la fonction de module `_open_db`) et les 50 appels de connexion SQLite directs de `borgHelper` (plus les 3 de
  `borgHelperWWW` sur `scopecache.db`). Renvoie une `BhConnection` (sous-classe de `sqlite3.Connection`) portant
  `.codec` (`None` si `plain`), `.mode`, `.role`, `.nick`. `role` (`read|write|admin`) est validé et mémorisé, sans
  effet fonctionnel pour l'instant. `_vacuum_db` reçoit désormais le nick.
- **Codec** (stdlib seule) : `PathCodec` (SIV déterministe chaîné par segment, `HMAC-SHA256` tronqué 12 o +
  keystream `SHAKE-256`, alphabet `A-Za-z0-9.-`, décodage strict), `BlobCodec` (nonce 16 o, chiffrer puis MAC),
  enveloppe DEK/KEK (chiffrer puis MAC, le MAC couvre `path_enc`, KDF, sel, nonce et chiffré), `enc_header`
  (ligne JSON de `db_meta`, `INSERT … ON CONFLICT DO NOTHING` sous `BEGIN IMMEDIATE`). Aucun chemin de production
  ne crée encore d'`enc_header`.
- **Erreurs typées** `DbKeyError`, `DbModeError`, `DbTamperError`, `DbCodecError` (n'héritent pas de
  `sqlite3.Error`). `enc_header` présent avec `path_enc='plain'` → `DbTamperError`.
- **Versions de schéma** : chaque constante est désormais la version *maximale comprise*
  (`DIFF_DB_SCHEMA_VERSION` 4→5, `CACHE_DB_SCHEMA_VERSION` 1→2, `SCOPE_CACHE_DB_SCHEMA_VERSION` 1→2) ; la version
  *écrite* dans une base `plain` reste 4 / 1 / 1 (`*_BASE_SCHEMA_VERSION`). `_check_set_meta` ne réécrit jamais une
  base `plain` à la version maximale : un ancien binaire continue de l'ouvrir ; seule la future `DbEncrypt` écrira
  la maximale. Un binaire 1.0.99 refusera donc une future base chiffrée (version maximale) mais continue d'ouvrir les
  bases `plain`.
- **Config** : `DB_ENCRYPT` (booléen, défaut activé mais **sans aucun effet tant que `DbEncrypt` n'existe pas** ; la clé sera
  dérivée de `BORG_PASSPHRASE`, donc changer la passphrase borg exigera un `DbRekey` ; `false`/`no`/`off`/`0` pour désactiver, global `[DEFAULT]`
  ou par nick) et `DB_KDF` (`light`/`standard`/`strong`, défaut `standard`), lues via `db_encrypt_enabled(nick)` /
  `db_kdf_level(nick)`. Valeur invalide → arrêt avec message. Sans effet runtime dans cette story.
- **Permissions** : `~/.borghelperrc` créé en `0600` par `Login` ; avertissement unique sur stderr à la lecture d'un
  rc accessible au groupe/autres ; répertoire de cache créé en `0700` ; `.db` créées en `0600`. Les fichiers et
  répertoires existants ne sont pas modifiés.
- **`CodecSelfTest`** (nouvelle commande) : auto-test du codec, de l'en-tête, des versions de schéma, de la config et
  des permissions sur des bases temporaires ; `OK`/`FAIL` par contrôle, code de sortie non nul au moindre échec.
- `borgHelperWWW` : les accès à `scopecache.db` passent par `_open_db`. Un échec d'ouverture dans `_scope_cache_get`
  / `_scope_cache_put` est désormais traité comme un cache miss (comme documenté) au lieu d'un `sys.exit(1)`.

## borgHelper 1.0.99 / borgHelperWWW_ui 1.8.0 — fichiers/répertoires effacés visibles dans TreeHist/TreeFind — 2026-09-19

`TreeHist`/`TreeFind` (l'explorateur d'arborescence de `borgHelperWWW_ui.html`) ne listaient que le
contenu du DERNIER snapshot indexé (`archive_snapshot_v`) — un chemin supprimé depuis n'apparaissait
plus jamais, même s'il restait réellement récupérable depuis une archive plus ancienne encore
présente. Spec : `_bmad-output/implementation-artifacts/spec-fichiers-effaces-exploration.md`.

- `_treehist_listing()`/`_treefind_listing()` : ajoutent désormais les chemins supprimés, sourcés
  depuis `diff_index` — **jamais** `archive_snapshot_v`/`archive_snapshot`, purgés indépendamment
  selon `IDX_SNAP_KEEP` (fenêtre glissante fixe, sans rapport avec l'existence réelle des archives),
  alors qu'une ligne `diff_index` survivante référence toujours une archive encore restaurable
  (`_cleanup_index_after_prune` ne la purge qu'au prune réel de l'archive). Détection : l'événement
  `diff_index` le PLUS RÉCENT (`archive_new_date`/`id` max, via une fenêtre `ROW_NUMBER()`) d'un
  chemin candidat est `change_type='removed'` — jamais "supprimé un jour" ; un chemin réajouté depuis
  réapparaît normalement, sans marque. Un chemin déjà présent dans le dernier snapshot n'est jamais
  reconsidéré via `diff_index` (priorité systématique au snapshot courant).
- `TreeHist` : enfants DIRECTS uniquement (même granularité que l'existant), fusionnés avec les
  enfants du snapshot. `TreeFind` : recherche récursive sous le préfixe, même sémantique de motif
  que l'existant.
- Entrée supprimée : `deleted:true`, `last_seen_archive` = `archive_old` de l'événement de
  suppression (l'archive à restaurer). `is_dir` déduit par heuristique (`size_before IS NULL` sur la
  ligne `diff_index` — `diff_index` n'a pas de colonne de type, et `borg diff` n'inclut pas de taille
  pour une entrée répertoire, voir `parse_diff_line_json()`).
- `TreeHist` sur un répertoire entièrement supprimé (absent du dernier snapshot) : ne renvoie plus
  "vide ou introuvable" — ses anciens enfants directs (trouvés via `diff_index`) restent explorables.
- Forme JSON des entrées présentes strictement inchangée (pas de champ `deleted` ajouté).
- Mode texte CLI (PrettyTable) : entrées supprimées marquées distinctement (`TreeHist` : colonne
  `type`="supprimé" ; `TreeFind` : nouvelle colonne `état`) — jamais une fonctionnalité JSON-only.
- RBAC (Epic 1, `_filter_per_nick_listkey`/`_path_in_scope`) : aucune modification — les entrées
  supprimées portent `full_path` comme les entrées présentes, le filtrage existant s'applique
  automatiquement et identiquement.
- `borgHelperWWW_ui.html` : marqueur visuel "supprimé" (`badge warn`) sur les lignes concernées
  (navigation normale et résultats de recherche) ; `openDownloadDialog()` présélectionne
  `last_seen_archive` dans le sélecteur d'archive pour une entrée supprimée au lieu de "dernière
  archive" (qui échouerait, le fichier n'y est plus).
- `borgHelperWWW` (routes `/treehist`/`/treefind`) : aucun changement — le filtrage RBAC et le cache
  de réponses existants s'appliquent tels quels.
- `python3 -m py_compile borgHelper borgHelperWWW` propre. Requête `ROW_NUMBER() OVER (...)`
  vérifiée manuellement sur une base SQLite de test (isolée, supprimée après vérification).
- `borgHelper` 1.0.98 → **1.0.99**. `borgHelperWWW_ui.html` 1.7.1 → **1.8.0** (`borgHelperWWW` et son
  `WWW_VERSION` inchangés — aucune ligne de `borgHelperWWW` modifiée par cette story).

## borgHelper 1.0.98 — désactive la découverte automatique d'intégrations Sentry — 2026-09-19

`sentry_sdk.init()` (`_cli_main()`) coûtait à lui seul ~100-180ms sur *chaque* invocation CLI
(mesuré empiriquement, DSN réel de production), dominé par la découverte automatique d'une
vingtaine d'intégrations tierces sans rapport avec cet outil (frameworks web, SDK cloud comme
`boto3`). `borgHelperWWW` spawn un sous-processus borgHelper par requête HTTP — ce coût était donc
payé à chaque appel API, y compris pour des commandes qui ne lisent que du SQLite local (`LstBkp`,
`Search`, etc.).

- `sentry_sdk.init(...,auto_enabling_integrations=False)` — option officielle du SDK. Élimine la
  découverte automatique, garde toutes les intégrations par défaut actives (`excepthook`,
  `logging`, `dedupe`, `atexit`, `modules`, `argv`, `stdlib`, `threading`) — capture des exceptions
  non gérées inchangée, vérifiée directement (`'excepthook' in client.integrations` → `True` après
  le changement).
- **Écueil trouvé en revue** : une première version de ce correctif ajoutait aussi
  `default_integrations=False`, qui désactive `excepthook` avec le reste — `borgHelper` n'appelle
  jamais `capture_exception()` explicitement, donc plus aucune exception ne serait jamais remontée
  à Sentry, silencieusement. Corrigé avant commit : seul `auto_enabling_integrations=False` est
  utilisé.
- Vérifié en conditions réelles contre `demo.borghelperrc` et le DSN de production
  (`/usr/local/etc/borghelper-sentry`) : `LstBkp` (commande 100% SQLite) passe de 199-273ms à
  88-93ms sur 3 mesures répétées, avant/après. `python3 -m py_compile borgHelper` propre.
- Issu du spine `_bmad-output/planning-artifacts/architecture/architecture-Borg-2026-09-19/`
  (AD-1) — voir `SOLUTION-DESIGN.md` pour le diagnostic complet.
- `borgHelper` 1.0.97 → **1.0.98**.

## borgHelperWWW 1.15.0 — garde pré-appel Restore/téléchargements hors périmètre (Epic 2, Story 2.1) — 2026-09-19

Dernière story de l'initiative RBAC arborescence : `Restore`, `Restore -L`/`listperms`,
`/download/file`, `/download/tar` n'avaient aucune conscience du périmètre de chemin
(`GROUPS_PATHS`, Epic 1) — un appelant scopé à un sous-arbre d'un nick pouvait restaurer/télécharger
n'importe quel chemin du nick entier. Contrairement aux commandes de liste d'Epic 1 (filtrage a
posteriori, sûr car rien n'est écrit avant le filtre), ces quatre routes écrivent sur le disque du
serveur ou streament des octets directement (`/download/*` appelle `borg` en sous-processus, en
contournant `borgHelper`) — un filtre après coup serait déjà trop tard.

- Nouvelle fonction `require_path_in_scope(request, nick, path)` — validation AVANT tout appel
  `borg`/`borgHelper`, réutilise `_resolve_scopes_for_request`/`_path_in_scope` (Epic 1) telles
  quelles. Retourne un booléen (jamais une exception) : l'investigation en direct (voir Intent du
  spec 2.1) a montré que les quatre routes doivent répondre avec des **formes différentes** sur le
  cas hors périmètre pour ne jamais confirmer l'existence d'un chemin hors périmètre (FR9/AD-2) —
  un `403` uniforme (pattern `require_destructive_allowed()`/`require_downloads_allowed()` suggéré
  en planification) aurait permis de distinguer « hors périmètre » de « n'existe pas » par le seul
  code de statut.
- Chaque route synthétise donc sa propre réponse « introuvable » sur un chemin hors périmètre,
  **jamais un 403** : `POST /restore` → `400` imitant `Include pattern '<ftor>' never matched.` ;
  `GET /restore/perms` → `200` imitant l'en-tête d'archive sans ligne de permissions ; `GET
  /download/file` → `200`, corps vide ; `GET /download/tar` → `200`, tar minimal vide — voir
  README.md/TECHNICAL.md pour les formes exactes. Aucun appel `borg`/`borgHelper` portant sur le
  chemin demandé n'est fait dans ces cas (`/download/*`) ; `/restore`/`/restore/perms` peuvent
  encore appeler `borg list --short` pour nommer la dernière archive quand `bid` est omis — métadonnée
  de nick, pas du chemin protégé, déjà accessible via `/lstbkp`.
- `GET /download/tar` sans `prefix` (export de l'archive entière) est traité comme toujours hors
  périmètre pour un appelant restreint — un export non borné ne peut être « dans le périmètre »
  d'aucun appelant restreint.
- Un appelant sans restriction (admin, groupe absent de `GROUPS_PATHS`, ou autorisation par groupes
  désactivée) ne voit **aucun** changement de comportement sur ces quatre routes.

**Deux écarts trouvés entre le texte gelé de l'Intent du spec 2.1 (capturé à la rédaction du spec) et
le comportement re-vérifié en direct avant implémentation (exigé par les Design Notes du spec)** —
l'implémentation suit le comportement observé, pas le texte gelé, écarts consignés dans le Spec
Change Log du spec 2.1 : (1) `GET /restore/perms` sans `bid`, cas introuvable : la ligne d'archive
est `"Archive (dernière) : <dernière archive>"`, jamais `"Archive : <dernière archive>"` (qui ne peut apparaître que si le
chemin a été trouvé dans l'index — jamais le cas « introuvable ») ; (2) `GET /download/tar`, tar
minimal vide : 10240 octets (`RECORDSIZE` de `tarfile`, toujours bufferisé en entier même vide),
jamais 1024. Connu, non corrigé : `POST /restore` sur `borg` 1.2.6 ajoute une ligne `Warning:
"--numeric-owner" has been deprecated...` à tout `stderr` réel de `borg extract` (trouvé ou non,
dans ou hors périmètre) ; reproduite littéralement dans la réponse synthétique pour préserver
l'indiscernabilité vérifiée en direct, mais couplée à la version de `borg` installée — à
re-vérifier si `borg`/`_borg_extract_args` changent (voir TECHNICAL.md).

Vérifié en conditions réelles contre une copie scratch de `demo.borghelperrc` (nick dédié, deux
sauvegardes, `Index` exécuté, `GROUPS_ADMIN/WRITE/READ` + `GROUPS_PATHS` actifs) :
`python3 -m py_compile borgHelper borgHelperWWW` propre ; pour chacune des quatre routes, diff
byte-pour-byte (JSON field-for-field pour `/restore`/`/restore/perms`) entre (a) un appelant scopé
sur un chemin hors périmètre et (b) le même appelant sur un chemin dans son périmètre mais
réellement absent de l'archive — identiques dans les deux cas `bid` omis/fourni ; `GET /download/tar`
sans `prefix` pour un appelant restreint → même tar vide ; restauration/téléchargement réels d'un
fichier dans le périmètre → inchangés (contenu restauré/téléchargé correct) ; appelant admin
(illimité) restaurant un chemin hors du périmètre d'un autre groupe → procède normalement, aucun
changement ; `GROUPS_HEADER` désactivé → aucun changement. Scratch config et dépôts `/tmp` supprimés
après vérification.

`README.md`/`TECHNICAL.md` mis à jour (nouveau garde, formes synthétiques par route, les deux écarts
trouvés en re-vérification, la limite connue de l'avertissement `--numeric-owner`). `borgHelperWWW`
1.14.0 → **1.15.0** ; `borgHelper` inchangé par cette story.

**Corrections de revue (même story, avant premier commit)** :
- `_oos_last_archive_line` catch désormais l'`HTTPException` (404/502/504) que peut lever
  `_latest_archive()` (nick sans aucune archive, `borg list` en échec/timeout) et omet simplement la
  ligne d'archive plutôt que de la laisser se propager — sans ce correctif, un nick sans archive
  cassait la garantie d'indiscernabilité de cette story (troisième forme de réponse, ni « introuvable »
  ni « dans le périmètre »).
- Nouveau helper `_download_tar_filename(nick, prefix)` — factorise l'expression du nom de fichier
  `.tar`, partagée avant ce correctif (copiée-collée identique) entre `download_tar()` et
  `_synth_download_tar_out_of_scope`, même risque de divergence silencieuse documenté pour `_fmt_stats`
  dans AGENTS.md.
- `require_path_in_scope(request, nick, path)` : type de `path` corrigé en `Optional[str]` (`download_tar`
  l'appelle avec `prefix: Optional[str]`, déjà accepté en pratique via la normalisation de
  `_path_in_scope`, mais pas reflété par l'annotation).
- Disclosure `--numeric-owner` élargie aux libellés de ligne d'archive codés en dur (`"Archive
  sélectionnée (dernière)"`, `"Archive (dernière)"`) — même risque de dérive silencieuse si les
  prints de `borgHelper.restore()`/`listperms()` changent de formulation.
- Docs : ambiguïté `<bid>` (paramètre de requête vs archive résolue serveur) levée dans TECHNICAL.md/
  CHANGELOG.md (`<dernière archive>`, déjà correct dans README.md) ; absence de tout réglage
  d'activation pour `POST /restore` rendue explicite (README.md, section « Actions destructrices et
  téléchargements ») ; note ajoutée à « Limites connues » sur le `borg list --short` toujours déclenché
  par requête hors périmètre sans `bid`.

## borgHelper 1.0.97 + borgHelperWWW 1.14.0 — cache SQLite des réponses filtrées par périmètre (Epic 1, Story 1.5) — 2026-09-19

Cinquième et dernière brique de la consultation scopée par arborescence (Epic 1) : depuis les
Stories 1.3/1.4, tout appelant scopé (au moins un nick à périmètre restreint) contournait
entièrement `_RESPONSE_CACHE` — chaque requête, même identique et récemment servie, relançait
`borgHelper` et refiltrait de zéro (AD-5). Cette story ajoute le cache SQLite dédié que ces deux
stories laissaient volontairement de côté.

- Nouveau fichier SQLite `SCOPE_CACHE_DB` (réglage `BORGHELPERWWW_SCOPE_CACHE_DB`/`--scope-cache-db`,
  défaut co-localisé avec `cache.db`/`diff.db`), même convention `db_meta`/`schema_version` que ces
  deux bases (réutilise `_bh_paths.db._db_connect()`/`_check_set_meta()`, jamais dupliqué). Table
  `scope_cache(cache_key, fingerprint, result_json, written_at)` — une ligne par `(nick réel,
  commande, paramètres, signature de périmètre)`, jamais une clé combinée pour une requête
  multi-nick (AD-5) : deux nicks scopés différemment dans la même requête ne partagent jamais une
  ligne.
- `_capture_fingerprints(nick)` : **tout premier appel** de chacune des neuf routes, strictement
  avant la résolution du périmètre — empreinte = mtimes `cache.db`/`diff.db` du nick **et** mtime de
  `.borghelperrc` lui-même (un `GROUPS_PATHS` resserré/relâché invalide donc le cache sans attendre
  une nouvelle sauvegarde), capturée par nick réel pour qu'un backup/index sur un seul nick n'invalide
  que sa propre ligne, même à l'intérieur d'une requête multi-nick. Garde-fou TOCTOU d'AD-5 : jamais
  recapturée après l'appel `borgHelper`.
- `_scoped_cached_mono()`/`_scoped_cached_multi()` enveloppent `_run_scoped()`/`_run_scoped_raw()`
  (Stories 1.3/1.4, strictement inchangées) dans chacune des neuf endpoints — jamais à l'intérieur de
  ces deux fonctions elles-mêmes, qui restent des primitives non-cacheables. Pour les quatre routes
  multi-nick (`Search`/`FileHist`/`TreeHist`/`TreeFind`) : un hit **complet** (tous les nicks
  demandés ont une ligne fraîche) synthétise la réponse sans appeler `borgHelper` ; tout miss (même
  un seul nick) relance l'appel combiné existant exactement comme avant cette story, puis
  rafraîchit une ligne par nick à partir de ce résultat.
- Même garde-fou anti-croissance que `_RESPONSE_CACHE` (purge totale au-delà de 500 lignes, pas de
  LRU) — cohérence plutôt que sophistication.

**Deux correctifs `borgHelper` requis pour que ce cache produise un hit en pratique** (limites
`borgHelper` initialement frozen, renégociées en cours de story après deux tours d'investigation
live — voir `_bmad-output/implementation-artifacts/spec-1-5-cache-perimetre.md`, Amendments
iteration 1 et 2) :
1. `_check_set_meta()` n'écrit plus `db_meta` (`schema_version`/`borghelper_version`) que si la
   valeur stockée diffère réellement — avant, ces deux lignes étaient réécrites à **chaque** appel,
   même en lecture pure, avançant la date de modification de `cache.db`/`diff.db` à chaque fois
   (chaque appel `borgHelper` est un sous-processus séparé ; fermer sa connexion SQLite déclenche un
   checkpoint WAL qui touche le fichier).
2. `ensure_diff_db()` ne recrée plus la vue `archive_snapshot_v` (`DROP VIEW`/`CREATE VIEW`) que si
   elle n'existe pas déjà (simple contrôle d'existence contre `sqlite_master`, jamais une comparaison
   textuelle du SQL stocké) — même défaut d'écriture inconditionnelle à chaque appel, découvert en
   test live **après** le premier correctif, qui à lui seul ne suffisait pas.

Sans ces deux correctifs combinés, l'empreinte qu'un appel scopé doit retrouver inchangée pour faire
un hit était invalidée par l'appel `borgHelper` lui-même — un miss garanti à chaque fois, quelle que
soit la justesse du mécanisme de cache. Comportement CLI/format de sortie de `borgHelper` inchangés
par ces deux correctifs — seule la date de modification des fichiers `.db` en bénéficie.

Vérifié en conditions réelles contre une copie scratch de `demo.borghelperrc` (`GROUPS_ADMIN/WRITE/
READ` + `GROUPS_PATHS` actifs sur les deux nicks de démo, données déjà indexées réutilisées sans
réindexation) : `python3 -m py_compile borgHelper borgHelperWWW` propre ;
`borgHelperWWW` piloté via `fastapi.testclient.TestClient` avec `_exec_borghelper` instrumenté d'un
compteur d'appels — (1) ligne `scope_cache` écrite après un appel scopé, désérialise vers la même
forme `CommandResult` qu'une réponse live ; (2) 5 appels `LstBkpFls` scopés identiques consécutifs →
**1 seul** sous-processus `borgHelper` (0 hit avant les deux correctifs `borgHelper`, confirmé lors
de la première tentative d'implémentation — voir spec) ; (3) `Search` multi-nick avec une seule ligne
supprimée → exactement 1 appel combiné, réponse correcte et identique pour les deux nicks (chemin
hit-partiel) ; (4) appelant admin (illimité) : 2 appels identiques → 1 seul exec (hit
`_RESPONSE_CACHE` normal), **0** ligne `scope_cache` écrite (additivité confirmée) ; (5) `.borghelperrc`
touché (`os.utime`) entre deux requêtes identiques → 2e requête toujours `200`, données correctement
re-scopées (miss, pas de crash) ; (6) garde-fou de croissance : 501 lignes de remplissage insérées
directement, l'écriture suivante vide la table et n'y laisse qu'1 ligne ; (7) `db_meta` du nouveau
fichier contient `schema_version='1'`, `borghelper_version` = `borgHelper.Version` ; (8) mêmes
vérifications de stabilité (n identiques → 1 exec) répétées pour `DiffBkp`/`DuIdx`/`IdxTop`/
`DiffTop`/`FileHist`/`TreeHist`/`TreeFind` — les neuf routes couvertes. **Test explicite requis par
le spec** : deux appels `LstBkpFls` consécutifs directement en CLI (`borgHelper -C ... -c LstBkpFls
-n demo-modules -j`, hors `borgHelperWWW`) contre un nick à données existantes non modifiées → mtime
de `diff.db` identique après le 2e appel (confirmé stable sur 3 appels consécutifs) — ce test avait
échoué avec seulement le premier correctif lors de l'itération précédente ; passe désormais avec les
deux ensemble. Scratch config et tous les fichiers `story15_test_rc-*`
(cache/diff-db/scope-cache) supprimés après vérification ; l'état `Index` propre aux deux dépôts de
démo laissé en place (inchangé par cette vérification, en lecture pure).

`README.md`/`TECHNICAL.md`/`borghelperwww.conf.example` mis à jour (nouveau cache, réglage
`--scope-cache-db`/`BORGHELPERWWW_SCOPE_CACHE_DB`, règle d'invalidation, et les deux correctifs
`borgHelper`). `borgHelper` 1.0.96 → **1.0.97** ; `borgHelperWWW` 1.13.0 → **1.14.0**.

## borgHelper 1.0.96 + borgHelperWWW 1.13.0 — filtrage par périmètre sur DuIdx/IdxTop/DiffTop (Epic 1, Story 1.4) — 2026-09-19

Quatrième brique de la consultation scopée par arborescence (Epic 1) : le périmètre de chemin
étend maintenant aux trois commandes d'**agrégats** (`DuIdx`/`IdxTop`/`DiffTop`) le filtrage déjà
en place depuis Story 1.3 sur les six commandes de liste/recherche — les neuf routes liées à AD-1
sont désormais toutes couvertes.

- Ces trois commandes groupent/agrègent déjà (Python, voire SQL pour `DuIdx`) **avant** de produire
  leur JSON existant — filtrer ce JSON après coup serait incorrect (une frontière de périmètre peut
  tomber au milieu d'un groupe déjà constitué). `borgHelper` gagne donc un mode **brut**, ungroupé,
  une ligne JSON par chemin, distinct du JSON groupé existant : `-R` pour `DuIdx` (son `-j` existant
  reste le mode groupé historique, byte-identique, jamais touché) ; `-j` pour `IdxTop`/`DiffTop`,
  qui n'avaient aucun mode JSON avant cette story. `borgHelper` reste RBAC-ignorant (AD-3) : ce mode
  brut est une option de sortie générique, jamais scope/groupe-aware.
- Quand l'appelant est scopé, `borgHelperWWW` demande ce mode brut, retire les lignes hors
  périmètre, puis **recalcule lui-même** — en miroir ligne-à-ligne de l'algorithme de regroupement
  de `borgHelper` au moment de l'écriture — le regroupement/tri/top-N (`_recompute_duidx`,
  `_recompute_idxtop`, `_recompute_difftop`) : jamais un total/classement transmis depuis le calcul
  non filtré puis partiellement masqué. `topn` s'applique sur l'ensemble **complet** filtré, jamais
  sur une tranche tronquée avant filtrage.
- Les figures « Exclus » (`IDX_EXCLUDE`) et « Inchangés par archive » (dérivées de `nfiles`) sont
  des figures portant sur le **nick entier**, sans colonne de chemin — non scopables correctement —
  et sont donc **omises** pour tout appelant scopé, jamais approximées.
- `DuIdx`/`IdxTop`/`DiffTop` sont traitées **mono-nick** pour le périmètre (comme `LstBkpFls`/
  `DiffBkp` en Story 1.3) : `nick` est développé via `_nick_list()` avant résolution du périmètre
  (jamais `cfgread('ALL')` direct) ; un appelant scopé sur `nick=ALL`/plusieurs nicks est refusé
  (`400`, aucune donnée) plutôt que de tenter un regroupement inter-nicks que cette story ne
  construit pas. Une paire d'archives (`DiffTop`) sans la moindre ligne dans le périmètre renvoie un
  résultat vide (`rows: []`), jamais une erreur.
- Un appelant sans restriction (admin, ou autorisation par groupes désactivée) ne voit **aucun**
  changement : texte/JSON groupé existant byte-identique à avant cette story.
- `_RESPONSE_CACHE` étendu (Story 1.3) aux trois nouvelles routes : contourné entièrement dès qu'un
  périmètre restreint s'applique, comme pour les six commandes précédentes.
- `borgHelper` 1.0.95 → **1.0.96** ; `borgHelperWWW` 1.12.0 → **1.13.0**.

Vérifié en conditions réelles contre `demo.borghelperrc` : `python3 -m py_compile` propre ; sortie
texte de `DuIdx`/`IdxTop`/`DiffTop` et JSON groupé existant (`-j`) de `DuIdx` diffées byte-à-byte
contre la sortie d'avant cette story (seule différence : le numéro de version après le bump) ;
lignes `diff_index` synthétiques insérées temporairement sous deux préfixes noyau distincts pour
exercer un cas réel de filtrage (données réelles du dépôt de démo sans diff exploitable entre les
dernières archives indexées) — `borgHelperWWW` lancé avec `--groups-header X-Groups`, `ops-readers`
scopé sur un sous-répertoire de `demo-modules` : `DuIdx` (modes groupé et global), `IdxTop`,
`DiffTop` ne renvoient que les lignes du sous-répertoire, totaux/pourcentages recalculés
correctement depuis l'ensemble filtré (confirmé par comparaison ligne à ligne avec la réponse admin
non filtrée) ; paire d'archives sans ligne en périmètre → résultat vide, `200`, pas d'erreur ;
`nick=ALL` scopé → `400`, aucune donnée. Configuration et lignes de test entièrement retirées après
vérification (`git checkout -- demo.borghelperrc`, lignes `diff_index` supprimées).

`README.md`/`TECHNICAL.md`/`LIBRARY.md` mis à jour (mécanisme de filtrage par mode brut + recalcul,
traitement mono-nick, options CLI `-R`/`-j`, retrait du caveat « `DuIdx`/`IdxTop`/`DiffTop` non
filtrés » de Story 1.3).

**Risque signalé, non corrigé dans cette story** : `_check_group_access` ne vérifie le tier que si
`nick` figure littéralement dans la query string de la requête HTTP — un appel à `/idxtop` ou
`/difftop` **sans aucun `?nick=`** (ces deux routes ont un défaut de route `nick="ALL"`) contourne
donc la vérification de tier grossière. Angle mort **pré-existant** (présent avant cette story, non
introduit par elle — `/cacheinfo`, `/cacheclean`, `/idxpurge` partagent le même défaut `nick="ALL"`
et le même angle mort, hors périmètre de Story 1.3/1.4). `_resolve_single_scope()` de cette story ne
le comble que par accident pour un appelant scopé sur au moins un nick réel (son propre refus
multi-nick s'applique avant toute lecture) ; un appelant sans **aucun** tier sur aucun nick resterait
exposé. Non corrigé ici : modifier `_check_group_access` est hors des limites frozen du spec 1.4, et
un correctif confiné à `IdxTop`/`DiffTop` serait incohérent avec les autres routes touchées par le
même angle mort — signalé pour triage humain/architecture (voir TECHNICAL.md).

## borgHelperWWW 1.12.0 — filtrage par périmètre sur Search/FileHist/LstBkpFls/DiffBkp/TreeHist/TreeFind (Epic 1, Story 1.3) — 2026-09-18

Troisième brique de la consultation scopée par arborescence (Epic 1) : le périmètre de chemin
résolu par Story 1.1 (`GROUPS_PATHS`) est désormais **appliqué**, en filtrage a posteriori, sur les
six commandes de lecture qui renvoient des chemins ou des listes indexées par chemin —
`Search`/`FileHist`/`LstBkpFls`/`DiffBkp`/`TreeHist`/`TreeFind`. `DuIdx`/`IdxTop`/`DiffTop`
(agrégats) restent hors périmètre de cette story (Story 1.4, distincte : recalcul de totaux/top-N).

- Dès qu'**au moins un** nick de la requête porte un périmètre restreint, `borgHelperWWW` appelle
  `borgHelper` avec `-j` en interne (même si le client n'a rien demandé), retire du JSON les
  lignes/chemins hors périmètre, et répond avec ce JSON — **la réponse devient JSON même sans
  `?json=true`** (`TreeHist`/`TreeFind`), sans aucun nouveau paramètre `?json=` côté client pour
  `Search`/`FileHist`/`LstBkpFls`/`DiffBkp`. `DiffBkp` recalcule `n_add`/`n_rem`/`n_mod` depuis les
  entrées filtrées, jamais depuis le compte non filtré. Un appelant sans restriction (admin, ou
  autorisation par groupes désactivée) ne voit **aucun** changement : texte par défaut, JSON
  seulement sur demande explicite là où c'était déjà possible — byte-identical à avant cette story.
- Requête multi-nick (`Search`/`FileHist`/`TreeHist`/`TreeFind`, `nick=a,b`) : chaque nick est
  filtré contre **son propre** périmètre résolu ; un seul nick scopé force tout le corps en JSON,
  les nicks non scopés de la même requête restent non filtrés.
- Nouvelle fonction partagée `_path_in_scope(path, scope)` (AD-7 : comparaison par segments de
  chemin complets, jamais sous-chaîne) — **corrige un bug trouvé en investigation d'implémentation,
  avant tout déploiement** : les chemins stockés par `borgHelper` (`archive_snapshot_v`/
  `diff_index`, vérifié contre un dépôt réel) n'ont jamais de `/` initial, alors que les préfixes
  `GROUPS_PATHS` s'écrivent **avec** un `/` initial (convention Story 1.1) — sans normalisation de
  ce décalage, toute comparaison scopée échouait silencieusement et un appelant scopé n'obtenait
  jamais aucun résultat, pour aucun nick (fail-closed, jamais une fuite, mais un vrai bug
  fonctionnel qui serait passé inaperçu sans un test contre des chemins stockés réels).
- `_RESPONSE_CACHE` (cache mémoire existant) n'est plus utilisé (ni lu, ni écrit) pour un appel dont
  au moins un nick est scopé — reste réservé au cas entièrement non restreint, exactement comme
  avant cette story. Un cache dédié au résultat filtré (clé incluant le périmètre) est prévu pour
  Story 1.5, pas celle-ci.
- `borgHelperWWW` 1.11.0 → **1.12.0**.

Vérifié en conditions réelles contre `demo.borghelperrc` (données déjà indexées par Story 1.2) :
`borgHelperWWW` lancé avec `--groups-header X-Groups`, un groupe `ops-readers` scopé sur un sous-
répertoire de `demo-modules` (`/lib/modules/6.2.0-39-generic`, un des trois répertoires de version
noyau réellement présents dans les données indexées) — `Search`/`FileHist`/`LstBkpFls`/`DiffBkp`/
`TreeHist`/`TreeFind` ne renvoient que des chemins de ce sous-répertoire, en JSON même sans
`?json=true` ; le même groupe non scopé sur `demo-usrlocal` (multi-nick `Search`) reste non
filtré dans la même réponse ; un appelant `ops-admins` (illimité) obtient un texte byte-identique à
l'appel direct `borgHelper` (diff vide) et, sur `TreeHist`/`TreeFind` avec `?json=true`, un JSON
byte-identique à l'appel direct `borgHelper -j`. Complété par des tests unitaires en isolation
(`_path_in_scope`, `_filter_diffbkp` + recalcul des compteurs sur des entrées synthétiques
couvrant les deux répertoires, `_filter_per_nick_listkey`, `_filter_filehist`) pour les cas que les
données réelles du dépôt de démo ne couvraient pas (aucune différence entre les dernières archives
indexées). `python3 -m py_compile borgHelperWWW borgHelper` propre.

`README.md`/`TECHNICAL.md` mis à jour (mécanisme de filtrage, normalisation du `/` initial avec sa
justification, caveat de cache, limite connue côté UI qui ne distingue pas encore une réponse
filtrée).

**Correction issue de la revue (itération 1, avant commit)** : `Search`/`FileHist`/`TreeHist`/
`TreeFind` construisaient leur liste de nicks par un simple `nick.split(',')`, sans passer par
`_nick_list()` (déjà utilisé par `_check_group_access` pour exactement ce besoin) — un appelant
scopé demandant `nick=ALL` littéral voyait `cfgread('ALL')` renvoyer `None` (aucune section `ALL`
n'existe), interprété comme périmètre illimité par `_resolve_scopes_for_request`, donc `_any_scoped`
à `False` et la requête retombait entièrement non filtrée — un contournement complet du filtrage de
cette story pour ces quatre routes via `nick=ALL`, confirmé en conditions réelles avant correction
puis re-vérifié après (réponse filtrée, JSON forcé, aucun changement pour un appelant illimité).
Corrigé en remplaçant le découpage manuel par `_nick_list(nick)` dans les quatre routes.
`LstBkpFls`/`DiffBkp` (mono-nick) ne sont pas affectées : `nick=ALL` y échoue déjà proprement
(exitcode non nul, aucune donnée) côté `borgHelper`, qui ne sait pas résoudre un nick agrégé sur ces
deux commandes — vérifié, pas de correctif nécessaire. `_run_scoped()` durci en complément : un
`stdout` non-JSON malgré `-j` pour un appelant scopé renvoie désormais une erreur (fail-closed)
plutôt que de relayer tel quel une sortie potentiellement non filtrée (cas non atteignable
aujourd'hui, mais contraire au principe fail-closed affiché par cette story).

## borgHelper 1.0.95 — mode JSON sur Search, FileHist, LstBkpFls, DiffBkp (Epic 1, Story 1.2) — 2026-09-18

Deuxième brique de la consultation scopée par arborescence (Epic 1) : `Search`, `FileHist`,
`LstBkpFls` et `DiffBkp` gagnent un flag `-j`/`as_json`, sur le même modèle que `TreeHist`/
`TreeFind` — prérequis mécanique pour le filtrage par périmètre d'une story ultérieure du même
epic (rien n'est filtré ici, ce changement est CLI-only).

- `-j` sur les quatre commandes : sortie JSON structurée à la place du tableau texte habituel,
  qui reste strictement inchangé sans `-j`. `Search`/`FileHist` : `{nick:[{...},...]}`, une entrée
  par nick (comme `TreeHist`/`TreeFind`). `LstBkpFls` : `{nick,archive,files:[...]}`. `DiffBkp` :
  `{archive_old,archive_new,entries:[...],n_add,n_rem,n_mod}`.
- Toutes les sorties d'erreur de ces quatre commandes (index vide, paire non trouvée, échec
  `borg list`/`borg diff`, erreur SQLite) passent aussi par `-j` — `{"error": "..."}` sur stdout
  plutôt qu'une phrase en clair, pour ne jamais casser un consommateur qui s'attend à du JSON.
- Champs JSON en valeurs brutes (tailles en octets, pas `convert_octets_readable`) — utile pour un
  programme, contrairement au tableau texte destiné à un terminal.

Vérifié contre le dépôt `demo.borghelperrc` réel (`Init`+`Bkp` x2 en local) : sortie texte vs `-j`
comparées champ par champ pour `Search`/`FileHist`, `LstBkpFls -j` et `DiffBkp -j` (cas
différence vide et compteurs `n_add/n_rem/n_mod`) conformes ; `python3 -m py_compile` propre.

`README.md`/`LIBRARY.md` mis à jour (exemples `-j`, signatures) ; usage CLI (`-h`/`-H`) documente
le nouveau flag sur les quatre commandes.

## borgHelperWWW 1.11.0 + UI 1.7.1 — périmètre de chemin par groupe (Epic 1, Story 1.1) — 2026-09-18

Première brique de la consultation scopée par arborescence (Epic 1) : `borgHelperWWW` peut
désormais **résoudre et exposer** un périmètre de chemin par groupe, en plus du tier
admin/écriture/lecture existant — cette story ne filtre encore **aucune** réponse de commande
(prévu dans une story ultérieure du même epic) ; elle pose la fonction de résolution partagée et
l'expose via `/access`.

- Nouvelle clef `.borghelperrc` par nick **`GROUPS_PATHS`** (repli `[DEFAULT]` natif, même
  convention que `GROUPS_ADMIN/WRITE/READ`) : associe un groupe à un ou plusieurs préfixes de
  chemin (`groupe:/a|/b, groupe2:/c`). Orthogonale au tier — ne fait que le restreindre, jamais
  l'étendre ; un groupe absent de la clef garde un accès chemin illimité dans son tier.
- `_resolve_path_scope(user_groups, cfg)` (miroir de `_effective_level`) : résolution strictement
  par nick, la plus permissive gagne (un seul groupe correspondant non scopé ⇒ périmètre illimité,
  sinon union canonicalisée des préfixes de tous les groupes correspondants scopés).
  `_parse_groups_paths` rejette bruyamment (`ValueError`) tout nom de groupe/chemin contenant un
  des séparateurs réservés (`:`, `|`, `,`) — jamais un découpage silencieusement ambigu.
- `_canonicalize_scope` : dédoublonne, retire les `/` finaux, élimine les préfixes redondants —
  **corrigé pour que la racine `/` absorbe bien tout le reste** (`_canonicalize_scope(['/',
  '/var/www'])` renvoie maintenant `['/']` ; le check générique `p.startswith(kept+'/')` ne
  fonctionnait pas pour `kept=='/'`, qui devient `'//'`).
- `GET /access` : chaque nick expose désormais `{level, scope}` au lieu d'une simple chaîne de
  niveau — `scope` est `null` (illimité) ou la liste des préfixes résolus, `null` partout quand
  l'autorisation par groupes est désactivée. **Changement de forme de réponse, non rétro-compatible**
  côté client (voir correctif UI ci-dessous).
  - `_validate_groups_paths_startup()` valide `GROUPS_PATHS` de chaque nick une fois au démarrage
    (fail-fast pour la faute de config la plus courante) — mais **n'est pas le seul point
    d'application** : `.borghelperrc` étant relu à chaque appel (`cfgread()`, sans cache), une
    valeur rendue ambiguë **pendant que le process tourne** fait échouer le prochain `/access`
    concerné en `500` non catché — **uniquement pour un appelant qui détient déjà un tier sur ce
    nick** (`_resolve_path_scope` court-circuite en `None` avant de lire `GROUPS_PATHS` pour un
    appelant sans aucun accès au nick, qui reçoit donc `scope:null` en `200` normal, sans jamais
    voir l'erreur) — jamais une réponse dégradée en silence pour l'appelant concerné. Conséquence
    documentée : `/access` n'est plus inconditionnellement `200` pour un appel authentifié qui a un
    tier sur le nick concerné — son `summary=`, le README et TECHNICAL.md sont corrigés en ce sens.
- `borgHelperWWW_ui.html` — **correctif de compatibilité**, dans le même commit : `loadMyAccess()`/
  `applyBadges()`/`loadMachines()` lisaient encore `nicks[nick]` comme une chaîne brute ; corrigés
  pour lire `.level` (nouvelle forme `{level, scope}`). Restaure exactement le comportement
  existant (calcul des badges, filtrage de la liste des serveurs) — `scope` lui-même n'est pas
  encore consommé côté UI, ce sera une story ultérieure.
- `demo.borghelperrc` : exemple commenté `GROUPS_PATHS` ajouté à côté de l'exemple
  `GROUPS_ADMIN/WRITE/READ` existant.

**Toujours pas de filtrage effectif** : `Search`, `FileHist`, `TreeHist`, `TreeFind`, `LstBkpFls`,
`DiffBkp`, `DuIdx`, `IdxTop`, `DiffTop` renvoient toujours l'intégralité de ce que le tier
autorise, périmètre ou pas — le filtrage a posteriori de ces neuf commandes est une story
ultérieure du même epic. `Restore`/`Restore -L`/`/download/file`/`/download/tar` sont, eux,
couverts par un **epic séparé** (garde pré-appel, pas un filtrage a posteriori) qui réutilisera
cette même résolution de périmètre — ils ne sont ni concernés ni « oubliés » par cette liste, ils
sont hors périmètre de cet epic. `Bkp/Index/Prune/DelBkp/Init/Key/IdxPurge/Stats` n'ont aucune
notion de sous-chemin et ne sont jamais concernés, dans aucun epic.

Vérifié : `python3 -m py_compile borgHelperWWW borgHelper` (aucune erreur de syntaxe) ; les 8
scénarios de la matrice E/S de la spec (groupe scopé seul, groupe scopé + groupe non scopé,
même groupe sur deux nicks indépendants, `GROUPS_PATHS` absent, préfixes redondants, séparateur
ambigu au démarrage, `groups_auth_enabled=false`, séparateur rendu ambigu **pendant que le
process tourne** → `500` non catché puis rétabli en `200` dès la config corrigée) rejoués contre
un `.borghelperrc` de scratch via `curl` sur `/api/access`, plus `_canonicalize_scope(['/',
'/var/www']) == ['/']` vérifié directement.

## borgHelperWWW 1.10.0 + UI 1.7.0 — droits alignés sur les badges, nicks sans accès invisibles — 2026-09-18

Complète l'autorisation par groupes (1.9.0) : les badges de sécurité et la liste des serveurs
reflètent désormais les droits **personnels** de l'utilisateur connecté, pas seulement les réglages
globaux `allow_destructive`/`allow_downloads`.

- Nouvel endpoint `GET /access` : niveau effectif (`none`/`read`/`write`/`admin`) de l'appelant sur
  **chaque** nick connu, d'après ses groupes — `{'admin': ...}` partout si l'autorisation par groupes
  est désactivée. Protégé par `X-API-Key` mais spécial-casé dans `_check_group_access` (accessible
  quels que soient les groupes de l'appelant — son rôle est justement de les refléter).
- **Liste des serveurs** : un nick sans aucun droit de lecture n'apparaît plus ni dans la liste ni dans
  la navigation rapide (au lieu de faire échouer toute la liste en `403` dès qu'un seul nick configuré
  est inaccessible — comportement *fail-closed* correct pour un appel explicite `nick=a,b,c`, mais
  inadapté à `nick=ALL`). `loadMachines()` appelle `/access` en premier, puis n'envoie à `/report`
  qu'une liste explicite des nicks accessibles ; liste vide ⇒ « Aucun serveur accessible avec vos
  droits actuels. » sans appeler `/report`.
- **Badges de sécurité affinés après connexion** : 🔒 Destructions désactivées tient compte de l'accès
  admin réel (pas seulement `allow_destructive`), 🚫 Téléchargements désactivés de l'accès à au moins un
  nick, ⚠️ Tout autorisé exige en plus l'admin sur la totalité des nicks configurés.
- Piste de réécriture côté serveur de `nick=ALL` (mutation de `request.scope['query_string']` dans
  `_check_group_access`) testée et écartée : sans effet sur le paramètre `nick` déjà résolu côté
  endpoint (voir TECHNICAL.md).

Vérifié : `/access` par curl sur plusieurs profils de groupes (admin, lecteur, aucun groupe, groupes
non pertinents, fonctionnalité désactivée), simulation complète de la séquence `loadMachines()`
(`/access` puis `/report` avec liste explicite dérivée), non-régression `nick=ALL` avec l'autorisation
par groupes désactivée.

## borgHelperWWW 1.9.0 — autorisation par groupes (reverse proxy OIDC/auth_request) — 2026-09-18

Nouveau mécanisme d'autorisation **par nick et par groupes**, complémentaire à `X-API-Key` (jamais un
remplacement) — pensé pour un reverse proxy (nginx `auth_request`, oauth2-proxy…) qui authentifie par
OIDC et transmet les groupes de l'utilisateur dans un header HTTP.

**Désactivé par défaut** — `BORGHELPERWWW_GROUPS_HEADER` / `--groups-header` / clé `groups_header`
absente : comportement strictement inchangé. Une fois activé (nom du header à lire, ex. `X-Groups`,
liste de groupes séparés par des virgules) :

- Trois nouvelles clefs `.borghelperrc` par nick (repli natif sur `[DEFAULT]`, comme toute autre
  clef) : **`GROUPS_ADMIN`**, **`GROUPS_WRITE`**, **`GROUPS_READ`** — hiérarchiques (admin ⊇ écriture
  ⊇ lecture, pas besoin de répéter un groupe dans les trois listes). Reconnues uniquement par
  `borgHelperWWW` — ignorées par `borgHelper` CLI lui-même (aucun changement de code côté
  `borgHelper`, juste de nouvelles clefs de configuration documentées).
- Chaque route classée lecture/écriture/admin (`_ROUTE_LEVELS`), appliqué à toutes via un seul
  `APIRouter(dependencies=[Depends(_check_group_access)])` — aucune signature d'endpoint modifiée.
- `Login` traité à part (accès admin sur le nick visé s'il existe déjà, sinon sur `[DEFAULT]`).
- Requête multi-nick (`nick=ALL` ou `nick=a,b,c`) : *fail-closed* — toute la requête est refusée si le
  niveau manque pour ne serait-ce qu'un seul des nicks visés.
- Header absent/vide (fonctionnalité active) : aucun groupe ⇒ aucun accès.
- `GET /version` renvoie `groups_auth_enabled` (booléen seulement — jamais le nom du header ni les
  groupes).

⚠️ Le header n'est vérifié que pour sa valeur, jamais sa provenance — suppose `borgHelperWWW` non
atteignable autrement que via le reverse proxy de confiance (même hypothèse déjà documentée pour
`X-Forwarded-For`/`BORGHELPERWWW_TRUSTED_PROXIES`).

Vérifié de bout en bout sur une configuration à deux nicks/trois groupes (`ops-admins`/`writers`/
`readers` équivalents) : hiérarchie admin/écriture/lecture, isolation stricte entre nicks (accès sur
l'un n'accorde rien sur l'autre), repli `[DEFAULT]`, multi-nick fail-closed, header absent/vide
refusé, cas `Login` (nouveau nick refusé sans `GROUPS_ADMIN` en `[DEFAULT]`, nick existant accepté
pour un groupe admin dessus), et non-régression complète avec la fonctionnalité désactivée.

`borghelperwww.conf.example` et `demo.borghelperrc` mis à jour (nouvelles clés documentées/exemples
commentés).

## UI 1.6.3 — correctif : les badges de sécurité ignoraient leur état réel — 2026-09-18

**Bug corrigé** : les trois badges de sécurité (🔒 Destructions désactivées, 🚫 Téléchargements
désactivés, ⚠️ Tout autorisé) s'affichaient systématiquement, sans tenir compte de leur attribut
`hidden` — donc sans rapport avec l'état réel du serveur (`allow_destructive`/`allow_downloads`).

**Cause** : `.badge{display:inline-block;...}` (CSS auteur) l'emportait sur le comportement par défaut
du navigateur pour `[hidden]` (`display:none`, une règle de la feuille de style *user-agent*) — en CSS,
une déclaration auteur l'emporte toujours sur une déclaration *user-agent*, quelle que soit la
spécificité du sélecteur. Seule `section[hidden]` avait une règle explicite ; aucune règle générique ne
couvrait les autres éléments (ici des `<span class="badge">`).

**Correctif** : règle globale `[hidden]{display:none!important}` ajoutée en tête de la feuille de
style (remplace l'ancienne règle `section[hidden]` devenue redondante).

Vérifié dans un vrai navigateur (Chrome headless, `getComputedStyle`) : avant le correctif, les trois
badges rendent `display:inline-block` quel que soit leur `hidden` (reproduit le bug rapporté) ; après,
`hidden=true` → `display:none`, `hidden=false` → `display:inline-block`, dans tous les cas testés.

## UI 1.6.2 — même lien « borgHelperWWW » dans le pied de page — 2026-09-18

`borgHelperWWW` dans le pied de page devient aussi un lien vers `/` (même principe que le titre en
en-tête, 1.6.1). Vérifié en direct.

## UI 1.6.1 — le titre « borgHelperWWW » ramène à la page d'accueil — 2026-09-18

`<h1>borgHelperWWW</h1>` dans l'en-tête devient un lien vers `/`. Vérifié en direct.

## borgHelperWWW 1.8.0 + UI 1.6.0 — préfixe configurable des routes API (`/api` par défaut) — 2026-09-18

Toutes les routes API métier de `borgHelperWWW` sont désormais montées sous un préfixe configurable
(**`/api` par défaut**, ex. `GET /lstbkp` → `GET /api/lstbkp`) — nouveau
`BORGHELPERWWW_API_PREFIX` / `--api-prefix` / clé `api_prefix` du fichier de conf. Vide ou `/`
désactive le préfixe (comportement d'avant ce changement).

Implémenté via un `APIRouter()` regroupant toutes les routes métier (`app.include_router(router,
prefix=API_PREFIX)`) ; `/`, `/version` et `/healthz` restent **délibérément hors préfixe** (comme
`/docs`/`/openapi.json`, natifs FastAPI) — condition nécessaire pour que la page web puisse se charger
et apprendre le préfixe effectif (`GET /version` renvoie désormais aussi `api_prefix`) avant de savoir
où se trouve le reste de l'API. L'interface web lit cette valeur au chargement et l'applique à tous ses
appels API ultérieurs (`apiCall()`, `downloadViaFetch()`).

Vérifié de bout en bout : préfixe par défaut (`/lstbkp` nu → 404, `/api/lstbkp` → 200, `/version` et
`/docs` toujours accessibles nus, `/openapi.json` liste bien les chemins préfixés) ; préfixe
personnalisé (`--api-prefix /borgapi`) ; préfixe désactivé (`--api-prefix ''`) ; téléchargements
(`/download/file`) également montés sous le préfixe.

`borghelperwww.conf.example` mis à jour avec la nouvelle clé `api_prefix`.

## UI 1.5.0 — badge « Tout autorisé » (rappel) — 2026-09-18

Badge **⚠️ Tout autorisé** dans l'en-tête, visible quand `allow_destructive` **et** `allow_downloads`
sont tous les deux à `true` (aucune restriction active sur l'instance) — couleur `err` (rouge), pour
attirer l'attention sur cet état sans protection. Vérifié en direct avec `--allow-destructive`
(`allow_downloads` restant à `true` par défaut).

## UI 1.4.1 — badge « Téléchargements désactivés » — 2026-09-18

Badge **🚫 Téléchargements désactivés** dans l'en-tête (même emplacement/mécanisme que
**🔒 Destructions désactivées**), visible quand `allow_downloads` est à `false` — couleur `warn`
(plutôt que `ok` comme le badge destructions) car ce n'est pas le réglage par défaut : signale une
restriction explicitement choisie par l'administrateur. Vérifié en direct avec `--no-downloads`.

## UI 1.4.0 — masque les boutons d'actions interdites (destruction / téléchargements) — 2026-09-18

Quand `allow_destructive`/`allow_downloads` (récupérés via `GET /version` au chargement de la page)
interdisent une action, le bouton correspondant **n'apparaît plus** dans l'interface web, plutôt que
de rester visible et d'échouer en `403` au clic :

- `allow_destructive=false` : retire **Prune** et **DelBkp** de la liste d'actions de la page Détail
  (nouveau flag `requiresDestructive` sur ces deux entrées d'`ACTIONS`), le bouton **⚡ Lancer Prune**
  et les boutons **🗑 Supprimer** par archive de la vue Historique complet.
- `allow_downloads=false` : retire le bouton **⬇ Télécharger** des résultats de recherche de
  l'explorateur ; masque le bouton de confirmation de la fenêtre de téléchargement (remplacé par un
  message explicite — ouvrir la fenêtre reste possible via clic sur un fichier/clic droit sur un
  dossier, mais plus aucun téléchargement n'y est déclenchable).

Vérifié : filtrage de la liste d'actions et des boutons conditionnels simulés en isolation (logique
identique à celle du fichier), markup et `GET /version` cohérents en direct.

## borgHelperWWW 1.7.1 + UI 1.3.0 — badge « Destructions désactivées » dans l'UI — 2026-09-18

`GET /version` renvoie désormais aussi `allow_destructive` et `allow_downloads` (postures de sécurité
au démarrage, voir 1.7.0 ci-dessous). Interface web : badge **🔒 Destructions désactivées** dans
l'en-tête (visible sur toutes les pages, même avant connexion) quand `allow_destructive` est à `false`
(le défaut) — masqué quand `Prune`/`DelBkp` sont explicitement autorisés. Vérifié en direct : badge
markup présent, `allow_destructive` correctement `false` par défaut et `true` avec `--allow-destructive`.

## borgHelperWWW 1.7.0 + UI 1.2.1 — postures de sécurité par défaut (destruction / téléchargements) — 2026-09-18

Deux nouveaux réglages de sécurité au démarrage de `borgHelperWWW`, affichés sur `stderr` :

- **`BORGHELPERWWW_ALLOW_DESTRUCTIVE`** / `--allow-destructive` / `--no-allow-destructive` / clé
  `allow_destructive` du fichier de conf — **`false` par défaut**. `POST /prune` et `DELETE /delbkp`
  répondent `403 Forbidden` tant qu'il n'est pas explicitement activé. `IdxPurge` (index local, pas les
  sauvegardes elles-mêmes) n'est pas concerné.
- **`BORGHELPERWWW_ALLOW_DOWNLOADS`** / `--allow-downloads` / `--no-downloads` / clé `allow_downloads`
  du fichier de conf — **`true` par défaut**. `GET /download/file` et `GET /download/tar`
  (téléchargement de données en vue d'une restauration) répondent `403 Forbidden` si désactivé.
  `POST /restore` (écrit sur le disque du serveur borgHelperWWW, pas un téléchargement navigateur)
  n'est pas concerné.

Interface web : messages d'erreur de suppression d'archive et de Prune (vue Historique complet)
affichent désormais le détail HTTP (`r.detail`/`HTTP {status}`) au lieu d'un générique « (pas de
détail) » quand la réponse n'a pas la forme `CommandResult` habituelle (cas d'un `403` de ce nouveau
gate).

Vérifié de bout en bout : défauts (`DelBkp`/`Prune` → 403, téléchargement → 200) ; `--allow-destructive`
(`DelBkp` atteint bien le sous-processus) ; `--no-downloads` (téléchargement → 403 avec message clair) ;
mêmes réglages via le fichier de conf (`allow_destructive`/`allow_downloads`).

`borghelperwww.conf.example` mis à jour avec les deux nouvelles clés.

## borgHelperWWW 1.6.0 — endpoint `/healthz` (liveness) — 2026-09-18

Nouvel endpoint `GET /healthz` : répond `{"status":"ok"}` (HTTP 200) dès que le processus tourne, sans
accès `borg`/SQLite ni sous-processus `borgHelper` — pour sondes de liveness (Kubernetes, Docker,
systemd, load-balancer…). Non protégé par `X-API-Key`, comme `/` et `/version`. Vérifié en direct :
200 sans header d'authentification.

## borgHelperWWW 1.5.0 — fichier de conf dédié (`BORGHELPERWWW_CONF`) — 2026-09-18

Nouveau fichier de conf ini pour `borgHelperWWW` lui-même (`BORGHELPERWWW_CONF` / `--conf`), distinct
du `.borghelperrc` qu'il exécute — un seul fichier peut désormais regrouper tous ses réglages :
`cfgfile`, `api_key`, `borghelper_bin`, `ui_file`, `timeout`, `host`, `port`, `trusted_proxies`.
Priorité : option CLI > variable d'environnement déjà présente > fichier de conf > défaut — le fichier
ne comble que ce qui n'est pas déjà réglé autrement, et fonctionne dans les deux modes de lancement
(exécution directe et `uvicorn borgHelperWWW:app` externe, via la variable d'environnement).

Nouveau réglage `BORGHELPERWWW_UI_FILE` / `--ui-file` / clé `ui_file` : chemin de
`borgHelperWWW_ui.html` désormais surchargeable (jusqu'ici toujours à côté du script, sans option).

Fichier `borghelperwww.conf.example` ajouté (toutes les clés documentées, commentées par défaut).
Vérifié de bout en bout : `cfgfile`/`api_key`/`port`/`timeout` depuis le fichier → serveur démarre et
répond avec la clé du fichier sur le port du fichier ; option CLI (`--port`) prioritaire sur la même
clé dans le fichier ; `--ui-file` sert bien un fichier HTML alternatif.

## borgHelperWWW 1.4.0 — IP client réelle dans les logs derrière un reverse proxy — 2026-09-18

`uvicorn.run()` (exécution directe `python3 borgHelperWWW ...`) appelé désormais avec
`proxy_headers=True` (déjà le défaut uvicorn, rendu explicite) et `forwarded_allow_ips=` réglable via
la nouvelle option `--trusted-proxies` / variable `BORGHELPERWWW_TRUSTED_PROXIES` (défaut `127.0.0.1`,
même défaut qu'uvicorn) : les logs d'accès affichent l'IP client réelle (`X-Forwarded-For`) plutôt que
celle du reverse proxy, **uniquement** si la connexion TCP brute provient d'une IP de confiance
(sinon un client pourrait usurper son IP en forgeant lui-même ce header). Vérifié de bout en bout :
`X-Forwarded-For` spoofé depuis une IP de confiance (127.0.0.1, défaut) → apparaît dans le log ; même
en-tête depuis une IP explicitement exclue de `--trusted-proxies` → ignoré, IP réelle du client TCP
loggée. Lancement via `uvicorn borgHelperWWW:app ...` externe : options natives uvicorn
`--proxy-headers`/`--forwarded-allow-ips` (déjà fonctionnelles, aucun changement nécessaire côté code).

## borgHelperWWW 1.3.0 — clé API générée automatiquement si absente — 2026-09-18

`borgHelperWWW` ne refuse plus de démarrer faute de clé API (`-K`/`--api-key`/`BORGHELPERWWW_API_KEY`) :
il en génère une aléatoirement (`secrets.token_urlsafe(32)`) et l'affiche sur `stderr` au démarrage
(encadrée, bien visible). Clé valable pour cette exécution uniquement — perdue au redémarrage, jamais
persistée. Vérifié de bout en bout : démarrage sans clé → clé affichée → fonctionne pour l'auth → une
clé erronée reste rejetée (401) ; démarrage avec `-K` explicite → comportement inchangé, aucune
génération.

## borgHelper 1.0.94 + borgHelperWWW 1.2.0 + UI 1.2.0 — recherche récursive dans l'explorateur (TreeFind) — 2026-09-18

Nouvelle commande **`TreeFind`** : recherche **récursive par nom** (pas le chemin complet) sous un
préfixe (racine entière si omis), dans le dernier snapshot connu — comme `TreeHist`, mais récursif et
filtré par motif. Motif minimal `-m` : `*` = n'importe quelle suite de caractères, `.` reste littéral ;
sans `*` (ni `?`), sous-chaîne implicite (comme `Search`). JSON (`-j`) inclut `parent` (répertoire
contenant l'entrée) par résultat. Aucune migration de schéma — réutilise `archive_snapshot_v` tel quel.

Endpoint `GET /treefind` (mêmes paramètres, `cacheable=True`). Interface web : champ de recherche dans
l'explorateur d'arborescence, scope = répertoire actuellement affiché, récursif. Résultats en liste
avec, par entrée, un lien **📂 Aller au dossier** (navigue directement — le dossier trouvé lui-même, ou
le parent pour un fichier) et un bouton **⬇ Télécharger** réutilisant la fenêtre de téléchargement
existante (mêmes formats brut/`.tar`, même commande `borgHelper` équivalente affichée). Toute
navigation normale efface la recherche en cours.

## borgHelperWWW 1.1.0 — cache de réponses basé sur la date de modification de la base — 2026-09-18

Les endpoints qui ne lisent (ou n'écrivent, pour `DiffBkp` lors de son tout premier appel sur une paire
non indexée) que `cache.db`/`diff.db` — `LstBkp`, `LstBkpFls`, `Report -o`, `DiffBkp`, `Search`,
`FileHist`, `TreeHist`, `DuIdx`, `CacheInfo`, `IdxTop`, `DiffTop` — sont désormais mis en cache en
mémoire par `borgHelperWWW` : un appel identique (même commande, nick, paramètres) est servi depuis le
cache, **sans relancer `borgHelper`**, tant que la date de modification de tous les
`cache.db`/`diff.db` concernés n'a pas changé. Dès qu'un `Bkp`/`Index`/`Prune`/`DelBkp`/… modifie ces
fichiers, l'empreinte change et l'appel suivant recalcule une réponse fraîche — vérifié de bout en bout
(un vrai `Bkp` sur le dépôt de démo fait bien apparaître la nouvelle archive dans `LstBkp` dès l'appel
suivant). Cache borné à 500 entrées (purge totale au-delà) et perdu au redémarrage du processus.

## UI 1.1.0 — animation de chargement + protection contre les réponses tardives — 2026-09-17

**Bug corrigé** : quand un appel API était lent (explorateur d'arborescence notamment), rien
n'indiquait qu'un chargement était en cours, et si l'utilisateur naviguait entre-temps (autre dossier,
autre archive, autre serveur), la réponse tardive du **premier** appel pouvait s'afficher **après**
celle du second — montrant le contenu d'un mauvais répertoire ou d'un mauvais serveur sans que rien ne
le signale.

Corrigé par un numéro de séquence par vue (`browseLoadSeq`, `historyLoadSeq`, `machinesLoadSeq`) :
l'état demandé (nick/chemin/archive) est capturé au moment de l'appel, et une réponse qui revient après
qu'une navigation plus récente a eu lieu est silencieusement ignorée. Animation de chargement
(spinner CSS + « Chargement… ») affichée immédiatement sur : explorateur d'arborescence, liste des
serveurs, historique des 10 dernières sauvegardes par carte, Historique complet.

## borgHelperWWW 1.0.1 + UI 1.0.0 — versionnage UI, intégré à /version — 2026-09-17

`borgHelperWWW_ui.html` reçoit lui aussi son propre numéro de version (`UI_VERSION`, commentaire
`<!-- UI_VERSION: X.Y.Z -->` en tête du fichier) — à incrémenter à chaque commit qui modifie ce fichier
(même règle symétrique que `borgHelper`/`Version` et `borgHelperWWW`/`WWW_VERSION`).

`borgHelperWWW` extrait cette version par regex au démarrage (lecture de `_UI_HTML`) et l'ajoute à la
réponse de `GET /version` (`ui_version`). Pied de page : affiche désormais les trois versions
(borgHelperWWW, borgHelper, UI).

## borgHelperWWW 1.0.0 — versionnage propre + affichage dans le pied de page — 2026-09-17

`borgHelperWWW` reçoit son propre numéro de version (`WWW_VERSION`, jusqu'ici il réutilisait par erreur
`Version` de `borgHelper` pour le champ `version` de l'app FastAPI) — à incrémenter uniquement quand le
source de `borgHelperWWW` change (même règle que `borgHelper` pour son propre `Version`).

Nouvel endpoint `GET /version` (non protégé, comme `/`) renvoyant `borghelperwww_version` et
`borghelper_version`, toutes deux résolues une fois au démarrage du processus (import de `borgHelper`
pour la seconde). Pied de page de l'interface web : affiche désormais les deux versions, récupérées via
`/version` au chargement de la page (avant même la connexion).

## Interface web — navigation rapide + alerte visuelle sur la liste des serveurs — 2026-09-17

Ligne de liens rapides au-dessus de la liste des serveurs : clic sur un nom → défilement direct
(`scrollIntoView`) vers la carte de ce serveur, utile quand la liste est longue. Nom affiché en rouge
(lien ET titre de la carte) si `Report` remonte une erreur pour ce serveur — détecté via le préfixe
`***` déjà posé par `report_offline()` sur le champ `nom` (diff.db absent, dernière sauvegarde plus
ancienne que `MAX_AGE_BKP`, ou erreur SQLite). Aucun changement côté `borgHelper`.

Page élargie (`main` 1100px → 1400px) pour réduire les marges latérales vides. Tableau de l'Historique
complet : colonnes ajustées au contenu (`width:auto`) au lieu d'un étirement uniforme forcé qui créait
de grosses colonnes vides et des sauts de ligne inutiles ; cellules non-coupables (`white-space:nowrap`) ;
défilement horizontal (`overflow-x:auto`) en secours sur petit écran.

## Interface web — alignement des boutons Explorer/Supprimer (Historique complet) — 2026-09-17

Colonne Actions de la vue Historique complet : boutons **🗂 Explorer** et **🗑 Supprimer** alignés en
ligne (flexbox, espacement constant), plus de retour à la ligne intempestif.

## Interface web — vue Historique complet par serveur (Prune / DelBkp / Explorer par archive) — 2026-09-17

Le tableau des **10 dernières sauvegardes** sur chaque carte de la page Serveurs s'affiche désormais
**automatiquement** (aucun clic requis — c'était auparavant un panneau à déplier).

Nouveau bouton **📜 Historique complet** (remplace l'ancien bouton de dépli) : ouvre une nouvelle vue
listant **toutes** les archives indexées en base pour ce serveur (`Report -o -j`, sans `-N`), avec par
archive :
- **🗂 Explorer** — ouvre l'explorateur d'arborescence épinglé sur cette seule archive
  (`archive_from`/`archive_to` = l'archive choisie), pour ne voir que les événements propres à cette
  sauvegarde, sans l'historique des autres. Un bandeau d'information rappelle que droits/genre/
  propriétaire restent le dernier état connu (limitation déjà documentée de `TreeHist`).
- **🗑 Supprimer** — `DelBkp` sur cette archive (confirmation, 🔑 passphrase).

Bouton **⚡ Lancer Prune** en haut de la vue (portée sur tout le dépôt, confirmation, 🔑 passphrase).

Aucun changement côté `borgHelper` — endpoints `/report`, `/treehist`, `/delbkp`, `/prune` déjà
existants, simplement recombinés côté UI.

## Interface web — lien Swagger dans le pied de page — 2026-09-17

Lien **Swagger / API** (`/docs`) ajouté dans le pied de page de l'interface web, visible sur toutes
les pages y compris la page de connexion.

## Interface web — bouton Serveurs dans l'en-tête — 2026-09-17

Bouton **Serveurs** ajouté à côté de **Déconnexion** dans l'en-tête : retour direct à la liste des
serveurs depuis n'importe quelle page (détail, explorateur). Masqué sur la page de connexion et sur
la page Serveurs elle-même.

## Interface web — bouton Explorer sur la liste des serveurs — 2026-09-17

Bouton **🗂 Explorer** ajouté à côté du bouton **▶ Backup** sur chaque carte de la page Serveurs :
ouvre directement l'explorateur d'arborescence (`TreeHist`) du serveur concerné, sans passer par la
page de détail au préalable.

## 1.0.93 — TreeHist affiche aussi le propriétaire (user:group, uid:gid) — 2026-09-17

### Nouvelle colonne `propriétaire` sur `TreeHist`

Précision sur la demande précédente (1.0.92, droits unix) : « droits » incluait aussi
utilisateur/groupe. `TreeHist` affiche désormais le propriétaire du **dernier état connu** de chaque
entrée sous la forme `user:group (uid:gid)` (ex. `root:root (0:0)`), à côté du genre et des droits —
colonne `owner` en JSON (`-j`).

Nécessite une nouvelle colonne `snapshot_file.owner` (migration `ALTER TABLE` automatique dans
`ensure_diff_db()`, additive/rétrocompatible — `DIFF_DB_SCHEMA_VERSION` 3→4). `indexsnap()` (chemins
complet et incrémental) demande désormais `{user}`/`{group}`/`{uid}`/`{gid}` en plus de
`{mode}`/`{type}`/`{size}`/`{isomtime}` à `borg list`. L'auto-réparation d'`indexsnap()` détecte
maintenant `type IS NULL OR mode IS NULL OR owner IS NULL` — un resnapshot complet se déclenche
automatiquement au prochain `Bkp`/`Index` si l'une des trois colonnes manque. Les entrées déjà
snapshotées avant cette version affichent `—` jusqu'à réindexation.

Interface web : nouvelle colonne **Propriétaire** dans l'explorateur d'arborescence.

Vérifié par test réel : migration + auto-réparation sur la DB demo (colonnes absentes → détectées,
resnapshot complet, `owner` peuplé — `root:root (0:0)` — `schema_version` remonté à 4) ; affiché
correctement en CLI, en JSON, et sur la page web servie.

## Interface web — bouton Backup immédiat sur la liste des serveurs — 2026-09-17

Bouton **▶ Backup** sur chaque carte serveur de la page « Serveurs » : lance un `Bkp` immédiat
(`POST /bkp`) sans passer par la page détail. Confirmation avant lancement ; utilise la passphrase de
session déjà enregistrée pour ce nick si présente, sinon avertit et propose de continuer sans (comme les
actions 🔑 de la page détail). Bouton désactivé pendant l'exécution, résultat affiché (succès/erreur +
détail), liste rafraîchie automatiquement ensuite pour refléter le nouveau backup.

Vérifié par test réel : appel `POST /bkp` tel que déclenché par le bouton → exitcode 0, backup réel
effectué sur le dépôt démo.

## 1.0.92 — TreeHist affiche les droits unix — 2026-09-17

### Nouvelle colonne `droits` (mode ls-style) sur `TreeHist`

`TreeHist` affiche désormais les droits unix du **dernier état connu** de chaque fichier/répertoire
(ex. `drwxr-xr-x`, `-rwxr-xr-x`, `lrwxrwxrwx`), à côté du genre — colonne `mode` en JSON (`-j`).

Nécessite une nouvelle colonne `snapshot_file.mode` (migration `ALTER TABLE` automatique dans
`ensure_diff_db()`, additive/rétrocompatible — `DIFF_DB_SCHEMA_VERSION` 2→3). `indexsnap()` (chemins
complet et incrémental) demande désormais `{mode}` en plus de `{type}`/`{size}`/`{isomtime}` à
`borg list`. L'auto-réparation d'`indexsnap()` (1.0.89) détecte maintenant `type IS NULL OR mode IS
NULL` — un resnapshot complet se déclenche automatiquement au prochain `Bkp`/`Index` si l'une ou
l'autre colonne manque. Les entrées déjà snapshotées avant cette version affichent `—` jusqu'à
réindexation.

Interface web : nouvelle colonne **Droits** dans l'explorateur d'arborescence.

Vérifié par test réel : migration + auto-réparation sur la DB demo (`type`/`mode` absents → détectés,
resnapshot complet, colonnes peuplées, `schema_version` remonté à 3) ; droits corrects affichés pour un
répertoire, un fichier exécutable et un lien symbolique (CLI, JSON, et page web).

## Interface web — téléchargement .tar (droits préservés) + commande équivalente — 2026-09-17

### Téléchargement de fichier au format .tar

Le téléchargement brut (`borg extract --stdout`) ne transporte que le contenu, pas les métadonnées
(mode, propriétaire, date). Ajout d'une case « Format .tar (préserve les droits d'accès) » dans la
fenêtre de téléchargement d'un fichier : cochée, réutilise `/download/tar` avec ce fichier comme
`prefix` (déjà générique — fonctionnait sans changement backend, `borg export-tar` acceptant un chemin
de fichier comme de dossier). Vérifié par test réel : `tar tvf` sur un fichier ainsi téléchargé montre
mode/propriétaire/date d'origine préservés (`-rwxr-xr-x root/root ... 2023-04-22 ...`).

### Commande `borgHelper` équivalente, systématique

La fenêtre de téléchargement (fichier brut, fichier .tar, ou dossier .tar) affiche désormais toujours la
commande `borgHelper -c Restore -n <nick> -f <chemin> -w <destination> [-b <archive>]` qui produit le
même résultat en ligne de commande (extraction disque réelle, droits préservés) — mise à jour en direct
quand l'archive sélectionnée change.

## Interface web — téléchargement de fichier : archives filtrées au mouvement réel — 2026-09-17

La liste déroulante d'archives pour télécharger un fichier proposait tout l'historique du dépôt
(`/lstbkp`), sans lien avec ce fichier précis. Elle ne propose désormais que les archives où **ce
fichier** a réellement changé (`added`/`modified` — `removed` exclu, le fichier n'y existe plus).
`loadBrowse()` charge maintenant l'explorateur avec `archive_from=ALL` (historique complet par entrée,
au lieu de la dernière paire seulement) et réutilise ces événements déjà en mémoire — aucun appel API
supplémentaire pour peupler le menu. Sans mouvement indexé pour ce fichier : la dernière archive reste
proposée par défaut. Le `.tar` d'un dossier (clic droit) continue de proposer toutes les archives —
sans objet à filtrer pour un instantané complet.

Vérifié par test réel : fichier modifié 2 fois sur 3 backups → 2 archives (et seulement ces 2)
proposées ; fichier jamais retouché → 0 archive proposée avec le fichier lui-même.

## 1.0.91 + borgHelperWWW — Explorateur d'arborescence — 2026-09-17

### `borgHelper` : `TreeHist -j`

Nouveau flag `-j` sur `TreeHist` : sortie JSON `{nick:{path,archive,entries:[{name,full_path,genre,
is_dir,events}]}}` au lieu du tableau texte — même contenu, structuré pour une consommation
programmatique (utilisé par le nouvel explorateur web).

### `borgHelperWWW` : endpoints `/download/file` et `/download/tar`

Nouveaux endpoints streamant des octets bruts (`borg extract --stdout` / `borg export-tar`) directement
vers l'appelant — seule exception au principe « tout passe par le binaire borgHelper en sous-processus »,
binaire streaming incompatible avec la réponse JSON texte des autres endpoints. Conf lue via `BorgRunner`
en mode librairie, `borg` appelé directement.

### Interface web : explorateur d'arborescence

Bouton **🗂 Explorer l'arborescence** dans le bandeau du serveur. Navigation façon gestionnaire de
fichiers sur `TreeHist -j` : clic sur un dossier = l'ouvrir, clic droit sur un dossier = télécharger un
`.tar` de son contenu (à une archive choisissable), clic sur un fichier = le télécharger (à une archive
choisissable) — téléchargement direct dans le navigateur (fetch + blob + `<a download>`), jamais écrit
sur le disque du serveur borgHelperWWW.

Vérifié par test réel : navigation JSON via `/treehist`, téléchargement d'un fichier régulier
(comparaison octet-à-octet avec l'original — identique) et d'un `.tar` de ~140 Mo (contenu vérifié via
`tar tf`) — le tout via curl et via la page servie par `borgHelperWWW`.

## borgHelperWWW UI — 2026-09-17

Retiré la saisie de passphrase de la page « Serveurs » (liste) — champ input + bouton Enregistrer par
carte serveur, remplacés par un badge lecture-seule (enregistrée / non renseignée). La passphrase ne se
saisit plus que sur la page détail du serveur concerné.

## 1.0.90 — 2026-09-17

### `Prune` migre désormais la DB comme `Bkp`/`Index` — `DIFF_DB_SCHEMA_VERSION` bumpée à 2

`prune()` ne passait par aucun `ensure_diff_db()`/`ensure_cache_db()` avant d'exécuter
`_cleanup_index_after_prune()` et `clear_cache_nick()` — contrairement à `Bkp`/`Index`/`Report`, il
pouvait donc opérer sur un schéma non migré (colonne `snapshot_file.type` manquante, ancien
`archive_snapshot`). Corrigé : `prune()` appelle désormais `ensure_cache_db()`/`ensure_diff_db()` en
tout premier, et `_cleanup_index_after_prune()` le fait aussi en défense en profondeur.

`DIFF_DB_SCHEMA_VERSION` passe de 1 à 2, documentant enfin correctement les deux migrations
structurelles déjà en place (déduplication `archive_snapshot`, `snapshot_file.type`) — jusqu'ici les
deux étaient appliquées sous version 1, rendant le numéro inexploitable pour savoir si une DB était à
jour. Les migrations restent auto-détectées par introspection (`PRAGMA table_info`), pas seulement par
comparaison de version — donc rejouables sans risque. Table de correspondance version ↔ migration dans
TECHNICAL.md.

Vérifié par test réel : DB ramenée à un état pré-migration (colonne `type` supprimée, `schema_version`
forcé à 1), seul `Prune` lancé (aucun `Bkp`/`Index`) → colonne restaurée, `schema_version` remonté à 2.
Garde anti-régression (DB plus récente que le binaire) revérifiée, toujours fonctionnelle.

## 1.0.89 — 2026-09-17

### `IndexSnap` : auto-réparation du `type` manquant

Le clonage incrémental (`_indexsnap_incremental`) réutilise le `file_id` (donc le `type`) des fichiers
inchangés — un `type` manquant (migration `snapshot_file.type` ou ancien snapshot pré-1.0.86) ne se
réparait jamais tout seul via l'incrémental normal, obligeant un `Index -F -S` manuel. `indexsnap()`
détecte désormais toute entrée `type IS NULL` avant de tenter l'incrémental et, si trouvée, force un
resnapshot complet cette fois-là (message « type manquant… auto-réparation ») — les backups suivants
repassent en incrémental normal une fois tout repeuplé. Se déclenche automatiquement au prochain `Bkp`
(indexation auto activée) ou `Index`, sans intervention.

Vérifié par test réel : `type` neutralisé manuellement (simulation de données pré-1.0.86), `Bkp` normal
(sans `-F`/`-S`) lancé → détection, resnapshot complet automatique, tous les `type` repeuplés.

## 1.0.88 — 2026-09-17

### `TreeHist` : added/removed ne concernent que l'entrée elle-même

Le rollup des sous-répertoires (1.0.87) pouvait afficher `added` ou `removed` sur un répertoire alors
que seul un descendant avait été ajouté/supprimé — trompeur (laissait croire que le répertoire lui-même
avait été créé/supprimé). Désormais : `added`/`removed` ne s'affichent que si l'entrée du répertoire
**elle-même** a ce marqueur dans `diff_index` (ex. `added directory`/`removed directory`) ; tout
mouvement interne quelconque (ajout/suppression/modification d'un descendant, à n'importe quelle
profondeur) remonte en `modified` générique. Un événement propre à l'entrée (ex. `ctime`) prime sur le
synthétique `modified` pour la même archive — pas de doublon.

Vérifié par test réel : fichier ajouté 2 niveaux sous un répertoire → le répertoire affiche `modified`
(pas `added`) ; un sous-répertoire ayant à la fois son propre `ctime` et un descendant ajouté à la même
archive n'affiche que son `ctime` (pas de ligne `modified` redondante).

## 1.0.87 — 2026-09-17

### `TreeHist` : un sous-répertoire "a eu des événements" si sa sous-arborescence a changé

Un sous-répertoire n'affichait un événement que si SA PROPRE entrée avait un marqueur direct dans
`diff_index` (ex. `added directory`) — restant "aucun événement" même si un fichier profondément niché
en dessous avait changé. Désormais : un sous-répertoire (et `.`, toujours un répertoire) affiche un
événement dès qu'un changement a eu lieu n'importe où dans sa sous-arborescence (`path=<lui> OR path
LIKE '<lui>/%'`, `SELECT DISTINCT` sur type/archive/date) — sans en lister le détail, toujours pas de
contenu de sous-répertoire. Les fichiers, eux, n'affichent que leurs propres événements (inchangé).

Vérifié par test réel : fichier modifié 2 niveaux sous un sous-répertoire dont la propre entrée n'a
aucun marqueur → le sous-répertoire, son parent et `.` affichent tous `modified` grâce au rollup.

## 1.0.86 — 2026-09-17

### `TreeHist` : un seul tableau, colonne genre (répertoire/fichier/lien/…)

Fusionné en un seul tableau (au lieu de sections séparées « entrée elle-même »/« sous-répertoires »/
« fichiers ») : le répertoire courant apparaît en `.`, suivi de ses enfants immédiats. Nouvelle colonne
`genre` tirée du **type réel stocké par borg** (`{type}` de `borg list`) : `répertoire`, `fichier`,
`lien symbolique`, `fifo`, `socket`, `périph. bloc`/`caractère` — plus fiable que l'ancienne heuristique
par profondeur de chemin.

Nécessite une nouvelle colonne `snapshot_file.type` (migration `ALTER TABLE` automatique dans
`ensure_diff_db()`, additive/rétrocompatible, pas de bump `DIFF_DB_SCHEMA_VERSION`). `indexsnap()`
(chemins complet et incrémental) demande désormais `{type}` en plus de `{size}`/`{isomtime}` à
`borg list`. Les entrées déjà snapshotées avant cette version affichent `inconnu (réindexer)` jusqu'à
réindexation (`Index -F -S` ou nouveau `Bkp`).

Vérifié par test réel : répertoire, fichier régulier, lien symbolique et fifo tous correctement
identifiés ; DB pré-migration testée (dégradation propre vers `inconnu (réindexer)`, pas de crash).

## 1.0.85 — 2026-09-17

### `TreeHist` : liste toujours l'intégralité du répertoire courant

`TreeHist` n'affichait que les entrées ayant changé dans la plage demandée ; les fichiers/répertoires
présents mais inchangés (ou dont l'historique a été purgé) étaient absents. Unifié les deux anciens
modes (table plate des changements / listing de secours) en un seul : toujours l'intégralité du
répertoire courant (snapshot), chaque entrée annotée de ses propres événements dans la plage `-b`/`-B`
(défaut : dernière archive indexée, comme avant), avec `aucun événement dans la plage` pour les entrées
présentes mais inchangées sur la période — au lieu d'être simplement omises. Vérifié par test réel
(fichier modifié + fichier jamais touché dans le même répertoire, aux deux apparaissent désormais).

## 1.0.84 — 2026-09-17

### `TreeHist` : ne remonte que le contenu direct du répertoire

Corrigé : `TreeHist` listait tout le sous-arbre sous `<préfixe>` (n'importe quelle profondeur) au lieu de
son seul contenu direct. Restreint désormais à `path=<préfixe>` (l'entrée du répertoire lui-même) et à
ses enfants immédiats (`path LIKE 'préfixe/%' AND path NOT LIKE 'préfixe/%/%'`) — jamais le contenu d'un
sous-répertoire. Pour y descendre, relancer `TreeHist -f <sous-répertoire>`. Vérifié par test réel
(changements à 3 profondeurs : racine, sous-répertoire direct, sous-répertoire imbriqué).

## 1.0.83 — 2026-09-17

### `TreeHist` : bascule en listing courant si rien n'a changé

Quand la requête (répertoire + plage `-b`/`-B`) ne trouve aucune modification, `TreeHist` affiche
désormais le contenu courant du répertoire (dernier snapshot indexé) au lieu d'un message vide :
sous-répertoires avec leurs apparitions/disparitions, fichiers avec tout leur historique de
création/modification/suppression — historique par entrée toujours calculé sur tout l'index, sans
tenir compte de `-b`/`-B` (qui ne sert qu'à décider du mode d'affichage).

### Correctif `_indexsnap_incremental` : colonnes `archive_snapshot` corrompues

Repéré en marge du travail sur `TreeHist` : l'INSERT qui applique les fichiers `added` (indexation
incrémentale du snapshot, chemin par défaut) liait ses paramètres dans le mauvais ordre —
`(archive_name,archive_date,nick,nick,path)` au lieu de `(nick,archive_name,archive_date,nick,path)` —
ce qui corrompait les colonnes `nick`/`archive`/`archive_date` de `archive_snapshot` pour chaque fichier
ajouté via ce chemin. `diff_index` n'était pas affecté. Corrigé (paramètres réordonnés), vérifié par
test réel (backup incrémental avec fichier ajouté → `archive_snapshot` cohérent).

⚠️ Les lignes déjà écrites avant ce correctif restent corrompues en base — réindexer le snapshot
(`borgHelper -c Index -n <nick> -F -S`) pour les régénérer proprement.

## 1.0.82 — 2026-09-17

### Nouvelle commande `TreeHist`

Pour chaque objet sous un préfixe d'arborescence (toute l'arborescence si `-f` omis) : liste triée par
chemin des événements (`added`/`modified`/`removed`/…) et de l'archive où ils ont eu lieu. DB-only
(`diff_index`), pas d'appel borg, pas de passphrase requise — même mécanique que `Search`/`FileHist`
(`-b ALL` pour tout l'historique, sinon dernière archive indexée seulement). Reportée dans
`borgHelperWWW` (`GET /treehist`) et dans l'interface web.

Au passage, repéré (non corrigé — hors scope) un bug préexistant dans `index()` : le `threading.Event`
utilisé pour arrêter le thread moniteur de priorité est aussi lu comme indicateur d'interruption après
la boucle — il est toujours `set()` à la fin, donc `index()` affiche systématiquement "indexation
interrompue" et pose `index_pending_lock`, même en cas de succès complet. Les insertions en base ne sont
pas affectées (elles ont lieu avant ce check), seuls le message et le code de retour sont faux.

## 1.0.81 — 2026-09-17

### `borgHelperWWW` : interface web

Nouveau fichier `borgHelperWWW_ui.html` (SPA vanilla JS, servi sur `/`, aucune dépendance externe) :
connexion par clé API, liste des serveurs (rapport hors-ligne, aucune passphrase requise), passphrase
par serveur saisie et conservée en `sessionStorage` pour la session du navigateur, puis panneau
d'actions par serveur (toutes les commandes de l'API, confirmation pour les actions destructives).
Testé via curl sur chaque endpoint utilisé par la page + vérification statique du JS (syntaxe, ids DOM,
handlers) faute d'extension Chrome disponible dans cette session.

## 1.0.80 — 2026-09-17

### `borgHelperWWW` : options CLI (-C, -K, --host, --port, ...)

En exécution directe (`python3 borgHelperWWW ...`), la conf peut désormais être passée en options CLI
en plus des variables d'environnement : `-C/--cfgfile`, `-K/--api-key`, `--borghelper-bin`, `--timeout`,
`--host`, `--port` (priment sur l'environnement). Sous `uvicorn borgHelperWWW:app`, uvicorn possède
seul `sys.argv` — les variables d'environnement `BORGHELPERWWW_*` restent le seul canal dans ce mode
(inchangé). `python3 borgHelperWWW --help` pour le détail.

## demo.borghelperrc — 2026-09-17

Fichier de conf démo, 100% local (pas de SSH) : deux nicks `demo-modules` (`/lib/modules`) et
`demo-usrlocal` (`/usr/local`) sur le host courant, dépôts/cache/DB SQLite sous `/tmp/demo_borghelper`.
Testé de bout en bout (Init, Bkp, Stats, LstBkp, LstBkpFls, Report).

## 1.0.79 — 2026-09-17

### `borgHelperWWW.py` : symlink manquant pour `uvicorn borgHelperWWW:app`

`uvicorn <module>:app` importe le module par son nom via `importlib` — échoue sans extension `.py`
("Could not import module"). Ajout du symlink `borgHelperWWW.py → borgHelperWWW`, même principe que
`borgHelper.py`. Sans impact sur `python3 borgHelperWWW` (exécution directe).

## 1.0.78 — 2026-09-17

### `-P` : passphrase en paramètre + correctif `-C`

Nouveau paramètre `-P <passphrase>` (et variable d'environnement `BORGHELPERC_RUNTIME_PASSPHRASE`,
prioritaire sur `-P` uniquement par ordre de résolution — l'env est le défaut, `-P` le supplante s'il
est fourni explicitement) : complète ou supplante `BORG_PASSPHRASE` du `.borghelperrc` pour l'appel en
cours, sans le persister. Permet de garder un `.borghelperrc` sans passphrase en clair et de l'injecter
à l'exécution — cas d'usage principal : `borgHelperWWW`.

Corrigé au passage : `-C <fichier>` n'acceptait en réalité aucun argument (absent du spec `getopt`,
`-C /chemin` provoquait "Argument(s) non reconnu(s)") alors que la doc l'a toujours documenté comme
prenant un chemin. `-C` fonctionne maintenant comme documenté.

### Nouveau : `borgHelperWWW`

API HTTP (FastAPI + Swagger) au-dessus de `borgHelper`, en sous-processus (aucune modification du
comportement CLI). Toutes les commandes sauf `Mount`/`UMount`. Auth par clé partagée (`X-API-Key`),
passphrase par appel (`X-Borg-Passphrase` → `-P`). Voir [README.md](README.md#borghelperwww--api-http).

## 1.0.77 — 2026-09-17

### `LstBkp` et `LstBkpFls` : DB uniquement, plus d'appel `borg`

`list_backups` lit désormais `archive_stats` et `list_files` lit `archive_snapshot_v` (via `get_diff_db`) au lieu d'exécuter `borg list`. Réponse quasi-instantanée pour les dépôts distants, au prix de dépendre de l'indexation (`Bkp`/`Index` pour la liste d'archives, `Indexsnap` pour les fichiers) — message d'erreur explicite si rien n'est indexé.

## 1.0.76 — 2026-06-13

### Refactoring interne : consolidation du système de locks PID

Extraction de `_repo_key(nick)` (calcul de la clé repo à partir de `BORG_REPO` ou `DB_NAME`) pour éliminer la duplication dans les 3 méthodes `_*_lock_path`. Ajout de `_pid_lock_path(nick, suffix)`, `_set_pid_lock`, `_clear_pid_lock`, `_check_pid_lock` comme helpers génériques. Les 12 méthodes publiques de lock (priority, report-running, index-running) deviennent des wrappers d'une ligne. Aucun changement de comportement.

## 1.0.75 — 2026-06-13

### Report résumé : suppression de la clé `size_delta_last` du dict résumé

`size_delta_last` était visible dans la sortie JSON (`-j`) et en fallback `colnames`. Remplacé `get()` par `pop()` dans `report` et `report_offline` pour consommer la clé après usage.

## 1.0.74 — 2026-06-12

### Report résumé : `size_delta` de la dernière sauvegarde dans la colonne `derniere`

La colonne `derniere` du résumé (ligne par hôte) affiche maintenant le `size_delta` de la dernière archive entre parenthèses — ex. `1.37 GB (+11%)`. Absent si première archive. Stocké via `size_delta_last` dans `tcmpl[nick]` (non affiché séparément), appendé après `convert_octets_readable` dans `report` et `report_offline`.

## 1.0.72 — 2026-06-12

### `Index` interrompu par `bkp` : reprise automatique après le backup

Quand un `Index` externe est interrompu par un backup prioritaire, un fichier `index-pending.lock` est posé. `backup()` le détecte en fin d'exécution (après son propre `index` ciblé) et lance automatiquement un `Index` complet — sans intervention manuelle.

Deux cas couverts :
- **Early-exit** : `priority_lock` déjà actif au démarrage de `Index` → pending posé immédiatement
- **Interrupt mid-run** : `_priority_monitor` tue les diffs → pending posé après le retour de la phase diff

Les appels internes à `index()` depuis `backup()` utilisent `set_pending=False` pour ne pas déclencher de reprise récursive.

## 1.0.71 — 2026-06-12

### `Index` : priorité `bkp` étendue à toute la durée d'exécution

Deux correctifs :

1. **Early-exit au démarrage** : si `priority_lock` est posé au moment où `Index` démarre (Bkp/Restore déjà actif), l'indexation est annulée immédiatement sans lancer `borg list` ni aucun diff.

2. **Arrêt complet après interrupt** : lorsque `_priority_monitor` interrompt les diffs en cours, `index()` s'arrête aussitôt après (au lieu de continuer avec `borg info` + `indexsnap`). `bkp` peut donc reprendre sans attendre la fin de ces opérations post-diff.

## 1.0.70 — 2026-06-12

### `bkp` : indexation complète (avec tailles) automatique après backup

La commande `bkp` lance maintenant automatiquement `index()` après `indexsnap()`, ciblé sur la nouvelle archive (`-A <archive_new>`). Cela déclenche `borg diff --json-lines` pour remplir les tailles (`size_before`/`size_after`) dans `diff_index` — opération jusqu'ici nécessitant un appel manuel séparé à `Index`. Le `priority_lock` est levé avant l'appel à `index()` (le travail borg est terminé) ; le `finally` reste inoffensif (double `clear` absorbé par `OSError: pass`).

## 1.0.69 — 2026-06-12

### Report : `size_delta` remplace `dedup_delta` — basé sur `original_size`

`dedup_delta` (variation de `deduplicated_size`) remplacé par `size_delta` (variation de `original_size`). `original_size` est stable dans le temps (taille réelle des données de l'archive, indépendante de la déduplication inter-archives) — contrairement à `deduplicated_size` qui varie selon les archives voisines. La colonne est repositionnée après `original_size` dans le tableau. Le chargement de valeurs figées depuis `archive_stats` dans `prep_report` devient inutile et est supprimé.

## 1.0.68 — 2026-06-12

### Report : `dedup_delta` utilise les valeurs figées de `archive_stats`

Dans `prep_report` (rapport live), le calcul de `dedup_delta` utilisait les `deduplicated_size` retournées par `borg info` — valeurs qui varient à chaque nouveau backup (la déduplication redistribue les chunks entre archives). Corrigé : `prep_report` charge les valeurs de `archive_stats` (figées au moment de l'indexation initiale) et les utilise pour le delta. Fallback sur la valeur live si l'archive n'est pas encore dans `archive_stats`.

## 1.0.67 — 2026-06-12

### Report : colonne `dedup_delta` — variation de taille dédupliquée

Nouvelle colonne dans le tableau des sauvegardes du rapport (`Report` et `Report -o`) : `dedup_delta` affiche le pourcentage de variation de `deduplicated_size` par rapport à l'archive précédente (`+11%`, `-5%`, `—` pour la première). Calculé dans `prep_report` et `prep_report_from_db` à partir des valeurs déjà stockées dans `archive_stats`.

## 1.0.66 — 2026-06-12

### `indexsnap` incrémental via `diff_index`

Nouveau `_indexsnap_incremental` : si un snapshot précédent et un diff indexé existent, met à jour le snapshot par diff SQL au lieu d'un `borg list` complet :
- `removed` → DELETE de archive_snapshot + cleanup orphelins
- `modified` → UPDATE size dans snapshot_file (mtime conservé)
- `added` → `borg list` ciblé sur ces chemins uniquement (mtime exact)
- Fallback automatique vers `borg list` complet si : pas de snapshot précédent, diff absent, > 5000 ajouts, ou erreur borg
- `-F` force toujours le `borg list` complet

## 1.0.65 — 2026-06-12

### `indexsnap` : purge automatique des snapshots anciens

Après indexation du snapshot, `indexsnap` appelle `_snapurge_check` / `_snapurge_exec` et purge les archives au-delà de `IDX_SNAP_KEEP` (même logique que `IdxPurge`). Erreur non bloquante (`[WARN]`).

## 1.0.64 — 2026-06-10

### IdxPurge : IDX_SNAP_KEEP déduit de KEEP_* par défaut

Si `IDX_SNAP_KEEP` absent de la config, le seuil de rétention des snapshots est calculé comme `sum(KEEP_DAILY + KEEP_WEEKLY + KEEP_MONTHLY + KEEP_YEARLY + KEEP_HOURLY)`. Fallback à 10 si aucune règle KEEP_* n'est définie.

## 1.0.63 — 2026-06-10

### Refactor : purge des snapshots intégrée dans `IdxPurge`

La commande `SnapUrge` (1.0.62) est supprimée. `IdxPurge` purge désormais automatiquement les snapshots anciens en fin d'opération, via deux helpers privés `_snapurge_check` / `_snapurge_exec`. Seuil configurable : `IDX_SNAP_KEEP=10` dans borghelperrc (défaut 10). Un seul commit SQLite + un seul VACUUM pour les deux opérations. Le dry-run affiche aussi les snapshots qui seraient purgés.

## 1.0.62 — 2026-06-10

### Nouvelle commande : `SnapUrge` (remplacée par 1.0.63)

## 1.0.61 — 2026-06-10

### Bugfix : option `-A` de la commande `index` non reconnue

`-A` absent du string `getopt` (`A:` ajouté) et de `optab['index']` (`A` ajouté). L'option était parsée nulle part — `getopt` levait une erreur avant même d'atteindre le dispatch.

## 1.0.60 — 2026-06-10

### Résumé : factorisation du VACUUM SQLite

Nouvelle méthode `BorgHelper._vacuum_db(db_path, verbose)` : `VACUUM INTO` dans le même répertoire + `os.replace`, `[WARN]` non bloquant en cas d'échec. `verbose=True` (IdxPurge) affiche compactage en cours/terminé + hint manuel ; `verbose=False` (_cleanup_index_after_prune) est silencieux en cas de succès. Les deux anciens blocs dupliqués sont remplacés par un appel à cette méthode.

## 1.0.59 — 2026-06-10

### Résumé : VACUUM après prune via VACUUM INTO (évite l'erreur "disk is full")

`_cleanup_index_after_prune` utilisait `VACUUM` qui crée une copie complète en espace temporaire (`/tmp`). Sur les serveurs où `/tmp` est un `tmpfs` plus petit que `diff.db`, cela échouait avec "database or disk is full" même si la partition de données avait de l'espace. Remplacé par `VACUUM INTO db_path.vacuum_tmp` (même répertoire que la DB) + `os.replace`, identique au pattern déjà utilisé par `IdxPurge`. Échec de compactage → `[WARN]` non bloquant, les entrées purgées sont conservées.

## 1.0.58 — 2026-06-10

### Résumé : version borgHelper dans les messages d'erreur stderr

`printer()` ajoute automatiquement `[borgHelper vX.Y.Z]` en suffixe de tout message stderr contenant `[ERREUR]` ou `[WARN]`. Aucun site d'appel modifié — effet global sur tous les avertissements et erreurs.

## 1.0.57 — 2026-06-10

### Résumé : report live toujours via borg (plus de fallback DB)

`report` (sans `-o`) appelle désormais toujours `prep_report()` (borg live), y compris quand Bkp/Restore est en cours. Dans ce cas, `borg info` sera mis en attente du verrou borg plutôt que de tomber en fallback DB. `wait_index_idle` + `set_report_running_lock` stoppent l'indexation avant l'appel borg (inchangé). Alerte uniquement si borg échoue (`errcode=2`) ou si l'âge du dernier backup dépasse `MAX_AGE_BKP` ou si le dépôt est vide (`duree==-1`). La correction de `_msg` → alerte ne s'applique plus qu'à `report_offline` (`-o`), où elle est légitime.

## 1.0.56 — 2026-06-10

### Résumé : alerte systématique si aucun backup détectable (-o ou non)

`report` et `report_offline` génèrent désormais `errcode=1` + marqueur `***` / `errhost` dans deux cas : (1) `_msg` retourné par `prep_report_from_db` (diff.db absent ou aucune archive indexée) ; (2) dépôt borg vide (`c==0`, `duree==-1`) dans `prep_report` — le `depuis` affiché vaut `—` au lieu de la date de modification du repo, `duree` et `derniere` valent `—`.

## 1.0.55 — 2026-06-10

### Résumé : borg diff --json-lines + streaming stdout + insert pipeline

`borg diff` lancé avec `--json-lines` : sortie JSON structurée par ligne au lieu de texte humain. Nouveau parser `parse_diff_line_json` remplace les regex de `parse_diff_line`. `_run_diff` lit désormais le stdout de borg ligne à ligne (streaming) au lieu d'attendre `communicate()` : la mémoire pic est réduite et le parsing débute dès la première ligne. L'insert SQLite est déplacé dans la boucle `as_completed` (ancienne Phase 3 supprimée) : chaque paire est écrite en DB dès que son diff se termine, sans attendre les paires encore en cours. Même changement appliqué à `listperms`. Sur les gros dépôts, la latence entre fin du dernier diff et données disponibles en DB est quasi nulle.

## 1.0.54 — 2026-06-10

### Résumé : suppression des TODO obsolètes

Supprime les 4 commentaires TODO en tête de fichier (gestion erreurs borg, paramètres borgrc manquants, aide création borgrc, nettoyage caches) — fonctionnalités toutes implémentées.

## 1.0.53 — 2026-06-10

### Résumé : version borgHelper dans tous les stdout JSON

Tous les outputs JSON stdout incluent désormais la clé `borghelper_version` (valeur : string X.Y.Z). Concerne : `backup` (stdout borg create), `report`/`report_offline` (clé `-j`), et les commandes `DiffIndex`/`SnapIndex` en mode JSON (`-J`).

## 1.0.52 — 2026-06-10

### Résumé : réindexation ciblée sur une archive spécifique (`-A`)

Nouvelle option `-A <archive>` pour `borgHelper -c Index` : réindexe uniquement la paire dont `archive_new` correspond à l'archive donnée, sans toucher aux autres paires. Utile pour forcer la réindexation d'un backup précis (ex : `12%nb / —` qui indique des tailles manquantes). Implémenté via `target_archive=None` dans `index()`.

## 1.0.51 — 2026-06-10

### Résumé : message colspan quand archive_stats est vide

Quand `archive_stats` est vide (diff.db absent ou aucune archive indexée), le résumé affiche la commande à exécuter dans une seule cellule qui regroupe toutes les colonnes sauf `nom` — au lieu de lever une exception. En HTML : `colspan=100` sur la cellule message. En terminal : message dans la colonne `duree`. `prep_report_from_db` retourne un dict `_msg` au lieu de lever une exception ; `htmlTabelise` gère le rendu colspan.

## 1.0.50 — 2026-06-10

### Suppression colonne `moy` du résumé

La taille dédupliquée moyenne par archive est redondante avec la colonne `derniere`. Supprimée de `prep_report_from_db`, `prep_report` et de la boucle de conversion dans `report`.

## 1.0.49 — 2026-06-10

### `modifications` : espace disque en valeur absolue lisible

Remplace `YY%B` (pourcentage entier, toujours 0 avant fix des tailles) par la somme des tailles absolues des fichiers ajoutés + modifiés + supprimés, affichée en format lisible (`convert_octets_readable`). Exemple : `24%nb / 1.37 GB`. Affiche `—` si aucune donnée de taille disponible.

## 1.0.48 — 2026-06-10

### Correction `%B` toujours 0 dans le rapport

`backup()` stockait les entrées post-backup depuis `_bkp_parse_list` (tailles toutes NULL) et marquait la paire comme indexée dans `diff_indexed_pairs`. `index()` voyait la paire déjà indexée et la sautait → les tailles restaient NULL → `0%B` permanent.

Fix : ajout de `diff_pair_has_sizes()` dans `BorgHelperDB`. Dans la phase 1 de `index()`, si une paire est déjà indexée mais sans tailles (post-backup), elle est ajoutée à `pairs_to_purge` et re-indexée via `borg diff` — qui fournit les vraies tailles. Sans changement de schéma DB.

Cas particuliers : `entry_count=0` (aucun changement) et paires avec uniquement des entrées `C/B/T` (sans taille par nature) sont correctement traités comme "avec tailles" pour éviter une boucle de re-indexation.

## 1.0.47 — 2026-06-10

### Message `wait_index_idle` plus explicite

Inclut le nom du dépôt (nick) et le timeout dans le message affiché quand `report` attend la fin d'une indexation en cours.

## 1.0.46 — 2026-06-10

### `report` interrompt l'indexation en cours

`report` (sans `-o`) pose un verrou `report-running.lock` avant d'appeler borg, ce qui déclenche l'arrêt du `_priority_monitor` dans `index` (comme pour Bkp/Restore). Puis attend `wait_index_idle` (max 30 s) que les `borg diff` en cours libèrent le dépôt avant de lancer `prep_report` en live. Résultat : le rapport obtient toujours les données fraîches du backup le plus récent, même si une indexation parallèle était en cours.

Seul cas de fallback sur la DB conservé : quand un Bkp/Restore tient le `priority.lock`.

## 1.0.45 — 2026-06-09

### Parsing stderr ligne par ligne dans `boex`

Remplace le parsing en bloc (`json.loads('[' + join + ']')`) par un parsing ligne par ligne. Quand le JSON global échouait (ex. bannière SSH mélangée au JSON borg), les entrées `file_status` restaient sous forme de chaîne brute `{"type":"file_status"...}` et n'étaient pas filtrées. Désormais chaque ligne est parsée indépendamment : les lignes JSON valides deviennent des dicts (correctement filtrés), les autres restent des strings.

## 1.0.44 — 2026-06-09

### Filtrage messages DEBUG borg sur `bkp`

Supprime du stderr les messages `DEBUG` de borg (ex. `Merging into master chunks index`, `Reading cached archive chunk index`) lors d'un backup. Ces messages n'apparaissent qu'avec l'option `--debug`. Les entrées fichier par fichier (`file_status`) étaient déjà filtrées.

## 1.0.43 — 2026-06-09

### Format nom d'archive sans deux-points

`{now}` → `{now:%Y-%m-%dT%H%M%S}` : `sg210-root-2026-05-31T230006` au lieu de `sg210-root-2026-05-31T23:00:06`. Compatible avec les systèmes de fichiers qui n'acceptent pas les `:`.

## 1.0.42 — 2026-06-09

### `SchemaVersionError` : mismatch DB non bloquant pour `bkp`/`restore`

Remplace `sys.exit(1)` de `_check_set_meta` par `raise SchemaVersionError`. Pour `bkp`, l'exception est absorbée par le `except Exception` existant → warning + borg s'exécute normalement. Pour `Index`, `Report`, etc., l'exception remonte jusqu'à `__main__` et affiche un message propre avant de quitter.

## 1.0.41 — 2026-06-09

### Versionning schéma DB (`db_meta`)

Ajout table `db_meta (key, value)` dans `cache.db` et `diff.db`. Stocke `schema_version` (entier, incrémenté uniquement sur changement de schéma) et `borghelper_version` (version du script). Au démarrage : si `schema_version` DB > constante attendue → erreur + exit (DB d'une version future incompatible). Constantes actuelles : `DIFF_DB_SCHEMA_VERSION=1`, `CACHE_DB_SCHEMA_VERSION=1`.

## 1.0.40 — 2026-06-09

### `diffbkp` : cache conservé + stockage filtré corrigé

Restaure le comportement cache : si la paire est déjà indexée, lecture depuis `diff_index` (rapide, sans appel borg). Si non indexée : borg diff → filtre via `_idx_path_ok` → stockage filtré (`diff_index`) + exclus (`diff_excluded_stats`) → affichage complet (non filtré). Les paires mal indexées antérieurement nécessitent un `borgHelper -c Index -n <nick> --force`.

## 1.0.39 — 2026-06-09

### `diffbkp` : re-calcul forcé + stockage filtré + affichage complet

**Bug** : l'indexation à la volée de `diffbkp` stockait tous les fichiers sans appliquer `IDX_EXCLUDE`, polluant `diff_index`. De plus, si la paire était déjà en cache (même incorrectement), `diffbkp` lisait les données corrompues sans recalculer.

**Fix** :
- `diffbkp` force toujours un re-calcul via `borg diff` (purge préalable de la paire)
- Stockage filtré : `entries_ok` → `diff_index`, fichiers exclus → `diff_excluded_stats`
- Affichage depuis `all_entries` (non filtré) — le diff complet reste visible à l'écran
- L'utilisateur doit relancer `borgHelper -c Index -n <nick> --force` une fois pour nettoyer les paires déjà mal indexées

## 1.0.38 — 2026-06-09

### Statistiques : fichiers exclus inclus dans `modifications`

`_diff_stats_for_nick` agrège maintenant `diff_excluded_stats` (par `archive_new`) en plus de `diff_index`. Les fichiers filtrés par `IDX_EXCLUDE` (added/modified/removed) sont comptés dans le numérateur et le dénominateur de la colonne `modifications`, ce qui donne un pourcentage représentatif de l'intégralité des fichiers modifiés.

## 1.0.37 — 2026-06-09

### Index : annulation propre en base des diffs interrompus

**Bug** : quand un `borg diff` en cours était tué (`ps.kill()`), `communicate()` retournait quand même (returncode=-9), entries=[], et la paire était insérée dans `diff_indexed_pairs` avec 0 entrées — marquée "indexée" à tort, impossible à reprendre.

**Fix** : `_run_diff` retourne maintenant un flag `ok = returncode in (0,1)`. En Phase 3, les paires `ok=False` déclenchent une purge (`diff_index`, `diff_indexed_pairs`, `diff_excluded_stats`) au lieu d'un insert. Elles seront réindexées au prochain lancement.

## 1.0.36 — 2026-06-09

### Colonne `modifications` unifiée résumé + détail — suffixes `%nb` / `%B`

Colonne `modifications` étendue au détail par archive (remplace `fichiers` + `espace`). Même formule partout. Format : `"3%nb / 8%B"` — `%nb` pour le pourcentage fichiers, `%B` pour le pourcentage espace disque.

## 1.0.35 — 2026-06-09

### Résumé : colonne `modifications` (fichiers + espace)

Remplace les colonnes `fichiers`/`espace` du résumé par une seule colonne `modifications` affichant `"XX% / YY%"`.

Formule : dénominateur = état précédent (`inchangés + modifiés + supprimés`), numérateur = `modifiés + supprimés`. Première valeur = pourcentage fichiers, seconde = pourcentage espace disque.

Le détail par archive conserve `fichiers` et `espace` inchangés.

## 1.0.34 — 2026-06-09

### Erreurs SQLite : nom de fichier inclus dans le message

Tous les `printer()` et `raise Exception()` sur erreur SQLite affichent maintenant `({db_path})` en plus du message d'erreur. Plus besoin de deviner quelle base est en cause (ex. `database or disk is full`).

## 1.0.33 — 2026-06-08

### `Report` : fix `—` sur archives indexées sans changements visibles

**Bug** : quand tous les changements entre deux archives sont filtrés par `IDX_EXCLUDE`, `diff_index` reste vide pour cette paire mais `diff_indexed_pairs` la marque quand même comme indexée. Au report suivant, `_diff_stats_for_nick` ne trouvait rien dans `diff_index` → `None` → `—`.

**Fix** : `_diff_stats_for_nick` initialise maintenant un stat-zéro pour toutes les archives présentes dans `diff_indexed_pairs` avant de les surcharger avec les valeurs réelles de `diff_index`. Les archives indexées sans changements visibles affichent désormais `Pre(N/100%)+Add(0/0%)-Supp(0/0%)`.

## 1.0.32 — 2026-06-08

### `boex` : purge `_MEI*` PyInstaller sur Ctrl+C

Même nettoyage que 1.0.31 : après `ps.kill()/wait()` sur `KeyboardInterrupt` dans `boex`, les répertoires `/tmp/_MEI*` orphelins sont supprimés (via `fuser`).

## 1.0.31 — 2026-06-08

### `Index` : nettoyage des répertoires PyInstaller orphelins après SIGKILL

Quand `Bkp`/`Restore` interrompt un `Index` en cours via SIGKILL, les répertoires `/tmp/_MEI*` créés par borg (binaire PyInstaller) ne sont pas nettoyés. Le moniteur de priorité purge désormais ces répertoires orphelins après avoir attendu que les processus tués soient reap'd, en vérifiant via `fuser` qu'aucun process actif ne les utilise encore.

## 1.0.30 — 2026-06-08

### `Report -o` : colonne `taille` alimentée depuis `repo_stats`

`borg create --json` retourne `cache.stats.unique_csize` (taille dédupliquée du dépôt entier). Ce champ est désormais persisté dans une nouvelle table `repo_stats` après chaque `Bkp` réussi, et utilisé par `Report -o`.

**Nouvelle table `diff.db`** :
```sql
repo_stats (nick PK, unique_csize, total_size, total_csize, updated_at)
```

Nouveaux méthodes `BorgHelperDB` : `store_repo_stats()`, `get_repo_stats()`.

Limite : `repo_stats` n'est mis à jour qu'après `Bkp` (pas après `Prune` — `borg prune` sans `--json` ne retourne pas les stats structurées).

## 1.0.29 — 2026-06-08

### `Report -o` : colonne `reste` désormais alimentée

En mode offline (`-o`), la colonne `reste` (espace disque disponible sur le dépôt) était toujours `None`. Elle appelle maintenant `dfRepo` (simple `df` local) — disponible tant que le système de fichiers est accessible, même sans connexion borg.

Pas d'effet sur les dépôts distants (SSH) : `dfRepo` retourne `None` si `BORG_REPO` contient `:`.

## 1.0.28 — 2026-06-08

### `Report` : résumé — format `Chg(X%) Supp(Y%)`

Le tableau résumé par hôte remplace `Pre()+Add()-Supp()` par deux indicateurs orthogonaux :

| Colonne | Formule |
|---------|---------|
| `fichiers` | `Chg((added+modified)/nfiles_new) Supp(removed/nfiles_prev)` |
| `espace`   | `Chg((added_sz+modified_sz)/total_sz) Supp(removed_sz/prev_sz)` |

Avec `nfiles_prev = nfiles_new − added + removed` et `prev_sz = total_sz − added_sz + removed_sz`.

`Chg` et `Supp` ont des dénominateurs distincts et cohérents — pas de problème de somme > 100%.

## 1.0.27 — 2026-06-08

### `IdxTop` : inchangés par archive

Section `Inchangés par archive` ajoutée avant le tableau, listant pour chaque archive indexée :

```
Inchangés par archive :
  archive-2024-01-01 : 95 000 (97%) / 98 000 fichiers
  archive-2024-01-02 : 96 200 (96%) / 100 000 fichiers
```

Calcul : `nfiles` (depuis `archive_stats`) − added_total − modified_total (indexés + exclus). Seules les archives présentes dans `archive_stats` et `diff_index` sont affichées.

## 1.0.26 — 2026-06-08

### `DiffTop` : fichiers inchangés calculés depuis les index

Ligne `Inchangés` ajoutée après les exclusions :

```
Indexés  : 3 200 changements · 450 MB
Exclus   :   800 entrées · 1.2 GB (IDX_EXCLUDE) — +300 · -50 · =450
Inchangés: 96 000 (97%) sur 99 500 fichiers dans archive-new
```

Calcul : `nfiles_new` (depuis `archive_stats`) − added_total − modified_total, où les totaux incluent indexés et exclus. Ligne omise si `archive_stats` ne contient pas `nfiles` pour l'archive cible.

## 1.0.25 — 2026-06-08

### `IdxTop` / `DiffTop` : détail +/-/= des exclus sur une ligne

La ligne `Exclus` affiche désormais le détail par type de changement :

```
Exclus  : 18 200 entrées · 3.4 GB (IDX_EXCLUDE) — +5 000 · -200 · =13 000
```

Seuls les types présents sont affichés. Note : les fichiers **inchangés** ne peuvent pas être comptés car `borg diff` ne les liste pas.

## 1.0.24 — 2026-06-08

### `IdxTop` / `DiffTop` / `Index` : affichage des entrées non indexées

Les fichiers exclus par `IDX_EXCLUDE` (stockés dans `diff_excluded_stats`) sont désormais visibles :

- **`IdxTop`** — ligne `Exclus : N · taille (IDX_EXCLUDE)` après le total indexé (toutes paires confondues)
- **`DiffTop`** — idem pour la paire spécifique affichée
- **`Index` résumé final** — `, N exclus` ajouté au bilan de paires indexées

La ligne Exclus est omise si aucun fichier n'a été filtré.

## 1.0.23 — 2026-06-07

### `Report` : résumé % seuls, détail valeur+%

Affichage différencié entre résumé (tableau par hôte) et détail (tableau par archive) :

| Contexte | `fichiers` | `espace` |
|----------|-----------|---------|
| Résumé | `Pre(80%)+Add(8%)-Supp(3%)` | `Pre(85%)+Add(12%)-Supp(2%)` |
| Détail | `Pre(800/80%)+Add(80/8%)-Supp(30/3%)` | `Pre(8.5 GB/85%)+Add(1.2 GB/12%)-Supp(200 MB/2%)` |

## 1.0.22 — 2026-06-07

### `Report` : colonnes fichiers/espace au format `Pre()+Add()-Supp()`

Les trois colonnes `+ajouté`, `-supprimé`, `=présent` remplacées par deux colonnes :

- `fichiers` : `Pre(80%)+Add(8%)-Supp(3%)` — pourcentages relatifs à l'archive courante
- `espace`   : `Pre(8.5 GB)+Add(1.2 GB)-Supp(200 MB)` — tailles réelles

Format identique en résumé et en détail par archive.

## 1.0.21 — 2026-06-07

### `Report` : résumé en pourcentages seuls

Dans le tableau résumé par hôte, les colonnes `+ajouté`, `-supprimé`, `=présent` affichaient le même format verbeux que le détail par archive (`15 (8%) · 1.2 GB (12%)`).

Format résumé : `8% · 12%` — pourcentage fichiers · pourcentage taille, sans les valeurs absolues.  
Le détail par archive conserve le format complet `N (P%) · SIZE (Q%)`.

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

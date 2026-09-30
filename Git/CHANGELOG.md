# Changelog

## git2git_mirror

### 1.1.0 — 2026-09-22
- Ajout de `-s/--subdir <chemin>` : extrait un sous-repertoire du depot source (avec son historique, via git-filter-repo) et le pousse a la racine du depot destination. Permet d'exposer un sous-projet comme depot independant.

### 1.0.0 — 2026-09-22
- Creation du script : synchronisation miroir entre deux depots git (clone --mirror + push --mirror), avec option `-n/--dry-run`.

## gitconfig

### 1.6.0 — 2026-10-01
- Ajout de l'alias `tar` : `git tar <archive.tar|.tgz> <depot> <repertoire> <message>` clone `<depot>`, remplace entierement le contenu de `<repertoire>` par celui de l'archive (ajouts, modifs et suppressions), commit avec `<message>` et pousse. Equivalent inline de `gitar`, integre a `.gitconfig`. Chemin d'archive relatif au repertoire d'invocation (via `$GIT_PREFIX`, comme `addco`/`addcom`). Rien commite si l'archive ne change rien au sous-repertoire.

### 1.5.0 — 2026-09-30
- Ajout de l'alias `mirror` : equivalent simplifie de `git2git_mirror` (clone --mirror + push --mirror) integre directement dans `.gitconfig`, un seul fichier pour tout gerer git. Pas de `--subdir` (contrairement au script) : uniquement `[-n|--dry-run] <src> <dest>`. Le script `git2git_mirror` est conserve en parallele pour le cas `--subdir`.

### 1.4.0 — 2026-09-23
- `addco` et `addcom` fonctionnent désormais comme `git add` : le point de départ est le répertoire courant (retour dans `$GIT_PREFIX` avant d'agir, car les alias shell s'exécutent à la racine), pathspecs relatifs (y compris `../..`), plusieurs arguments possibles, défaut = `.`.
- `addcom` : périmètre limité au répertoire courant / aux chemins donnés (avant : tout le dépôt) ; boucle `git status | while read` remplacée par `git add -u`.

### 1.3.0 — 2026-09-22
- `[includeIf "gitdir:~/.local/"]` remplace par `[include]` inconditionnel : `~/.local/gitconfig` est maintenant charge quel que soit l'emplacement du repo (pour `[safe]` et autres reglages locaux a la machine). Git ignore silencieusement un include vers un fichier absent.
- Ajout des alias `whoami` (affiche l'identite git effective du repo courant) et `setid` (fixe interactivement `user.email`/`user.name` dans le `.git/config` local du repo courant, pour basculer pro/perso repo par repo). Git n'a pas de mecanisme natif de detection automatique via un fichier du worktree (seulement `gitdir`/`onbranch`/`remote url`) ; `setid` est le point d'entree explicite pour cet usage.

### 1.2.0 — 2026-09-22
- Fix `goto` : guillemets typographiques (“ ”) au lieu de guillemets droits (" ") cassaient completement l'alias (erreur shell). Remplaces par des guillemets droits.

### 1.1.0 — 2026-09-22
- Fix `addco` : cassait avec un chemin relatif quand invoque depuis un sous-repertoire (les alias shell `!` de git s'executent deja a la racine du depot ; `addco` prenait l'argument tel quel puis re-cd'ait vers la racine, donc `fichier.txt` pointait au mauvais endroit). Utilise maintenant `$GIT_PREFIX` (comme `ls`) pour reconstruire le chemin racine-relatif avant `diff`/`add`.

### 1.0.0 — 2026-09-22
- Depot de la version actuelle du `.gitconfig` personnel.

## git2git_file

### 1.0.0 — 2026-09-22
- Versioning initial (script existant, aucun changement fonctionnel).

## gitar

### 1.0.0 — 2026-09-22
- Versioning initial (script existant, aucun changement fonctionnel).

## gitoune

### 1.0.0 — 2026-09-22
- Versioning initial (script existant, aucun changement fonctionnel).

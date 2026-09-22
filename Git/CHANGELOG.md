# Changelog

## git2git_mirror

### 1.1.0 — 2026-09-22
- Ajout de `-s/--subdir <chemin>` : extrait un sous-repertoire du depot source (avec son historique, via git-filter-repo) et le pousse a la racine du depot destination. Permet d'exposer un sous-projet comme depot independant.

### 1.0.0 — 2026-09-22
- Creation du script : synchronisation miroir entre deux depots git (clone --mirror + push --mirror), avec option `-n/--dry-run`.

## gitconfig

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

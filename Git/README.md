# Git

Scripts utilitaires pour manipuler des depots git.

## Scripts

| Script | Version | Description |
|---|---|---|
| `git2git_file` | 1.0.0 | Transfere un fichier (avec son historique de commits) d'un depot git vers un autre |
| `git2git_mirror` | 1.1.0 | Synchronise l'integralite d'un depot git (branches, tags, refs) vers un autre, avec option `--dry-run` ; ou extrait un sous-repertoire (`--subdir`) pour l'exposer comme depot independant |
| `gitar` | 1.0.0 | Pousse une archive tar dans un depot git |
| `gitoune` | 1.0.0 | Pousse un fichier dans un depot git |
| `gitconfig` | 1.9.0 | Configuration git personnelle (`~/.gitconfig`) : alias, pager, diff tool, identite pro/perso par repo, mirroring inline (`git mirror`), depot d'archive tar (`git tar`), telechargement fichier/repertoire (`git figet`), depot d'un fichier unique (`git fiput`), historique d'un fichier distant (`git filog`) |

Voir `CHANGELOG.md` pour l'historique des versions.

## `gitar` vs `git tar`

`git tar` (alias dans `gitconfig`) remplace fonctionnellement `gitar` (script standalone) pour le cas d'usage courant : ecraser un sous-repertoire d'un depot par le contenu d'une archive, commit + push.

| | `gitar` | `git tar` |
|---|---|---|
| Langage | Python (requiert `gitpython`) | shell (alias `!` dans `.gitconfig`), requiert juste `tar`+`git` |
| Format archive | `.tar.gz` uniquement (`tarfile.open(mode='r:gz')` en dur) | `.tar`, `.tgz`, `.tar.gz`, `.tar.bz2`… — `tar xf` autodetecte |
| Args | flags nommes : `-t/--tarfile -r/--repo -p/--path -m/--message` (ordre libre) | positionnels : `archive depot repertoire message` (ordre fixe) |
| Diff ajout/suppr | vrai diff recursif (`filecmp.dircmp`) fichier par fichier, ne touche que ce qui change reellement | `rm -rf` du repertoire cible + reextraction complete, puis `git add -A` (resultat final identique, mais tout le repertoire est reecrit sur disque a chaque fois) |
| Detection "rien a faire" | compare avant d'agir, skip commit si aucun add/deleted/modified | commit puis verifie `git diff --cached --quiet`, skip si vide (meme resultat, ordre inverse) |
| Mode debug | `-D/--debug` avec log detaille par fichier | aucun |
| Chemin archive | tel que tape (pas de resolution `$GIT_PREFIX`) | resolu via `$GIT_PREFIX` — fonctionne depuis un sous-repertoire d'un autre repo invoquant (meme technique que `addco`/`addcom`) |
| Dependance externe | paquet python `git` (GitPython) installe | aucune, juste `git`+`tar` deja presents partout |
| Fichier | script standalone, 137 lignes | alias inline dans `.gitconfig`, une ligne |

## `gitoune` vs `git fiput` / `git figet`

`gitoune` multiplexe get+put d'un fichier unique derriere des flags. `git fiput` (deposer) et `git figet` (recuperer) sont deux alias separes dans `gitconfig` qui couvrent le meme besoin, plus les repertoires pour `figet`.

| | `gitoune` | `git fiput` / `git figet` |
|---|---|---|
| Langage | Python (requiert `gitpython`) | shell (alias `!` dans `.gitconfig`), requiert juste `git`+`tar` |
| Args | flags nommes : `-r -f -m -g -G -d -l` (combinables) | positionnels, un alias par sens : `fiput depot local dest message` / `figet depot chemin destination` |
| Entree/sortie fichier | contenu via **stdin/stdout**, ouvert en mode texte (`open(..., 'w')`) — risque de corruption sur binaire/encodage | copie **binaire** (`cp -a`) — fichiers binaires et encodages preserves |
| Recuperer (`get`) | `-g`/`-G <commit>` affiche le contenu sur stdout, a HEAD ou a un commit precis | `figet` ecrit vers une destination (fichier, repertoire, ou archive `.tar`/`.tgz`) ; HEAD uniquement, pas de commit specifique |
| Repertoires | non supporte, fichier unique seulement | `figet` recupere aussi un repertoire entier (copie ou archive) ; `fiput` reste fichier unique |
| Diff avant envoi | `-d` affiche le diff unifie (stdin vs contenu git) avant de decider | aucun affichage, decision via `git diff --cached --quiet` seulement |
| Historique du fichier | `-l` affiche le log du fichier dans le depot | couvert separement par `git filog <depot> <chemin>` (meme format que `git logs`) |
| Detection "rien a faire" | compare les deux contenus, exit code 2 si diff, 0 si identique | `git diff --cached --quiet` apres `add`, skip le commit si vide |
| Chemin local | tel que tape (pas de resolution `$GIT_PREFIX`) | resolu via `$GIT_PREFIX` pour `fiput` — fonctionne depuis un sous-repertoire d'un autre repo invoquant |
| Dependance externe | paquet python `git` (GitPython) installe | aucune |
| Fichier | script standalone, 165 lignes | trois alias inline dans `.gitconfig`, une ligne chacun |

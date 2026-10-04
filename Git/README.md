# Git

Scripts utilitaires pour manipuler des depots git.

## Scripts

| Script | Version | Description |
|---|---|---|
| `git2git_file` | 1.0.0 | Transfere un fichier (avec son historique de commits) d'un depot git vers un autre |
| `git2git_mirror` | 1.1.0 | Synchronise l'integralite d'un depot git (branches, tags, refs) vers un autre, avec option `--dry-run` ; ou extrait un sous-repertoire (`--subdir`) pour l'exposer comme depot independant |
| `gitar` | 1.0.0 | Pousse une archive tar dans un depot git |
| `gitoune` | 1.0.0 | Pousse un fichier dans un depot git |
| `gitconfig` | 1.15.1 | Configuration git personnelle (`~/.gitconfig`) : alias, pager, diff tool, identite pro/perso par repo, mirroring inline (`git mirror`), depot d'archive tar depuis fichier ou stdin (`git tar`), telechargement fichier/repertoire a HEAD ou a un commit precis (`git figet [-G <commit>]`), depot d'un fichier unique depuis fichier ou stdin (`git fiput`), historique d'un fichier distant (`git filog`), diff fichier local vs depot (`git fidiff [-G <commit>]`), liste des alias avec doc (`git alias`), deploiement HEAD vers des urls ssh (`git deploy`), rsync d'un chemin d'un depot vers un chemin d'un autre depot (`git syncdir`) |
| `git-deploy` | 1.3.0 | Script appele par l'alias `git deploy` : deploie le contenu commite (HEAD) de lots nommes (`[src "lot"]`) vers leurs destinations ssh/scp par type de deploiement (optionnel, defaut via `[default]`), selon un `.deploy.conf` (non tracke) pose a cote du sous-projet |
| `git2git_sync` | 1.0.0 | Script appele par l'alias `git syncdir` : synchronise (rsync --delete) un chemin (fichier/repertoire) d'un depot vers un chemin d'un autre depot, sans toucher au reste de la destination ; rejouable sans etat, id de commit non conserves |

Voir `CHANGELOG.md` pour l'historique des versions.

## `gitar` vs `git tar`

`git tar` (alias dans `gitconfig`) remplace fonctionnellement `gitar` (script standalone) pour le cas d'usage courant : ecraser un sous-repertoire d'un depot par le contenu d'une archive, commit + push.

| | `gitar` | `git tar` |
|---|---|---|
| Langage | Python (requiert `gitpython`) | shell (alias `!` dans `.gitconfig`), requiert juste `tar`+`git` |
| Format archive | `.tar.gz` uniquement (`tarfile.open(mode='r:gz')` en dur), fichier local seulement | `.tar`, `.tgz`, `.tar.gz`, `.tar.bz2`… — fichier local ou `-` (stdin, bufferise en temp car `tar` n'autodetecte pas la compression sur un pipe) |
| Args | flags nommes : `-t/--tarfile -r/--repo -p/--path -m/--message` (ordre libre) | positionnels : `archive\|- depot repertoire message` (ordre fixe) |
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
| Args | flags nommes : `-r -f -m -g -G -d -l` (combinables) | positionnels, un alias par sens : `fiput depot local dest message` / `figet [-G commit] depot chemin destination` |
| Entree/sortie fichier | contenu via **stdin/stdout**, ouvert en mode texte (`open(..., 'w')`) — risque de corruption sur binaire/encodage | `fiput` accepte un fichier local ou `-` (stdin, binaire-safe via `cat`/`cp -a`) |
| Recuperer (`get`) | `-g`/`-G <commit>` affiche le contenu sur stdout, a HEAD ou a un commit precis | `figet` ecrit vers une destination (fichier, repertoire, ou archive `.tar`/`.tgz`) ; `-G <commit>` couvre aussi un commit precis (clone complet + `checkout`, au lieu du `--depth 1` par defaut) |
| Repertoires | non supporte, fichier unique seulement | `figet` recupere aussi un repertoire entier (copie ou archive) ; `fiput` reste fichier unique |
| Diff avant envoi | `-d` affiche le diff unifie (stdin vs contenu git) avant de decider | couvert separement par `git fidiff [-G <commit>] <depot> <fichier-local> <chemin>` (`git diff --no-index`, HEAD par defaut ou commit precis) |
| Historique du fichier | `-l` affiche le log du fichier dans le depot | couvert separement par `git filog <depot> <chemin>` (meme format que `git logs`) |
| Detection "rien a faire" | compare les deux contenus, exit code 2 si diff, 0 si identique | `git diff --cached --quiet` apres `add`, skip le commit si vide |
| Chemin local | tel que tape (pas de resolution `$GIT_PREFIX`) | resolu via `$GIT_PREFIX` pour `fiput` — fonctionne depuis un sous-repertoire d'un autre repo invoquant |
| Dependance externe | paquet python `git` (GitPython) installe | aucune |
| Fichier | script standalone, 165 lignes | quatre alias inline dans `.gitconfig`, une ligne chacun |

## `git deploy` — deploiement vers des serveurs ssh

`git deploy [type-de-deploiement]` deploie le contenu **commite** (HEAD, pas la copie de travail meme si elle differe) de "lots" (groupes nommes de fichiers/repertoires) vers des destinations ssh/scp. Le type est optionnel : omis, `git deploy` utilise `[default] type=` de `.deploy.conf`.

Implemente en script standalone (`git-deploy`, appele par l'alias fin `deploy = !git-deploy`) plutot qu'en alias inline : la logique (recherche du fichier de config en remontant l'arbo, resolution des lots, boucle sur plusieurs destinations avec erreur geree une par une) est trop consequente pour un alias `!` lisible.

**Prerequis** : `git-deploy` doit etre dans le `PATH` (pas de chemin absolu dans l'alias). Ex : `ln -s ~/Projets/Misc/Git/git-deploy ~/.local/bin/git-deploy`, ou ajouter `Git/` au `PATH`.

Fonctionnement :
- Cherche un fichier `.deploy.conf` en remontant depuis le repertoire d'invocation jusqu'a la racine du depot (le premier trouve est utilise) — pose a cote du sous-projet concerne, **jamais commite** (voir `.gitignore` racine : `**/.deploy.conf`), a recreer sur chaque machine qui deploie.
- Format `.deploy.conf` a 3 etages (syntaxe `git config`) : **lot** (`[src "nom"]`, groupe nomme de sources fichier/repertoire relatives au repertoire du `.deploy.conf`) / **type de deploiement** (une section comme `[prod]`) / **cible** (cle `<lot> = dest`, repetable) :
  ```ini
  [src "outils"]
      src = gitconfig
      src = git-deploy

  [prod]
      outils = user@host1:/opt/git-tools/

  [preprod]
      outils = user@host1:/opt/git-tools/
      outils = user@host2:/opt/git-tools/

  [default]
      type = preprod
  ```
  `dest` suit la syntaxe scp classique `[user@]host:chemin` : repertoire distant ou atterrissent les membres du lot, chacun sous son propre nom (copie groupee). Un meme lot est reutilisable par plusieurs types, chacun pouvant l'envoyer vers des destinations differentes ; un lot peut aussi avoir plusieurs destinations au sein d'un meme type (cle repetee). `[default] type=` fixe le type utilise quand `git deploy` est appele sans argument — nom de section reserve (ne pas l'utiliser comme nom de type de deploiement).
- Transfert via `git archive HEAD -- <membres-du-lot> | ssh <host> 'tar x -C <chemin> --strip-components=N'` — une connexion par destination.
- Une destination en echec (host injoignable, syntaxe invalide, lot non defini) n'empeche pas les autres d'etre tentees ; code de sortie non nul si au moins une a echoue (y compris si une source du lot n'existe pas dans HEAD, detecte grace a `pipefail`).

Exemple pret a copier : `Git/.deploy.conf.example` (a copier en `.deploy.conf` puis adapter).

## `git syncdir` — rsync entre deux depots git

`git syncdir <repoSrc> <cheminSrc> <repoDst> <cheminDst> <message>` synchronise (comme `rsync --delete`) un chemin (fichier ou repertoire) du depot `<repoSrc>` vers un chemin du depot `<repoDst>`, sans toucher au reste de `<repoDst>`. Contrairement a `git mirror`/`git2git_mirror --subdir`, les id de commit ne sont pas conserves et la destination garde sa propre vie (autre contenu, autre historique) : seul le chemin cible est remplace.

Implemente en script standalone (`git2git_sync`, appele par l'alias fin `syncdir = !git2git_sync`), **prerequis** : doit etre dans le `PATH` (meme principe que `git-deploy`).

Fonctionnement :
- Clone la source (`--depth 1`, juste HEAD) et la destination (clone complet, necessaire pour pousser).
- Si `<cheminSrc>` est un repertoire : vide `<cheminDst>` puis copie le contenu de `<cheminSrc>` (`cp -a`) — equivalent a `rsync --delete`. Si c'est un fichier : copie simple vers `<cheminDst>` (cree les repertoires intermediaires).
- `git add -A` sur `<cheminDst>`, commit avec `<message>`, push. Rien n'est commite si le resultat est identique.
- **Rejouable sans etat** : chaque appel repart de l'etat HEAD courant des deux depots (pas de curseur/checkpoint a maintenir). Fonctionne que la source ait evolue, que la destination ait evolue ailleurs (hors cible), ou les deux — notre commit s'empile naturellement sur le HEAD courant de la destination au moment du clone.
- Si la destination a avance entre le clone et le push (course avec un autre processus), `git push` echoue normalement (pas de retry/rebase automatique) : relancer la commande.

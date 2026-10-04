# Changelog

## git2git_mirror

### 1.1.0 — 2026-09-22
- Ajout de `-s/--subdir <chemin>` : extrait un sous-repertoire du depot source (avec son historique, via git-filter-repo) et le pousse a la racine du depot destination. Permet d'exposer un sous-projet comme depot independant.

### 1.0.0 — 2026-09-22
- Creation du script : synchronisation miroir entre deux depots git (clone --mirror + push --mirror), avec option `-n/--dry-run`.

## gitconfig

### 1.15.1 — 2026-10-04
- `logs` et `lg` scopes desormais au repertoire courant (`-- .` ajoute en fin d'alias) : depuis un sous-repertoire, n'affichent que les commits touchant ce sous-repertoire (comme `git log` natif le ferait avec un pathspec `.`). Alias simples (non `!`), git traduit `.` relatif au repertoire d'invocation automatiquement.
- Effet de bord : un argument supplementaire passe a `git logs`/`git lg` (ex un nom de branche) devient un second pathspec plutot qu'une revision — comportement different de l'usage `git logs main` d'avant.

### 1.15.0 — 2026-10-04
- Ajout de l'alias fin `syncdir = !git2git_sync`, qui appelle le nouveau script `git2git_sync` (voir ci-dessous). `git alias` documente la nouvelle entree. `git2git_sync` doit etre dans le `PATH` (meme principe que `git-deploy`).

## git2git_sync

### 1.0.0 — 2026-10-04
- Creation : `git syncdir <repoSrc> <cheminSrc> <repoDst> <cheminDst> <message>` synchronise (rsync --delete) un chemin d'un depot vers un chemin d'un autre depot, sans toucher au reste de la destination. Id de commit non conserves (contrairement a `git mirror`). Clone source `--depth 1` + destination complete, remplace la cible (rm+cp pour un repertoire, cp simple pour un fichier), `git add -A` + commit + push, rien si identique.
- Rejouable sans etat : chaque appel repart de HEAD courant des deux depots, donc fonctionne que la source ait evolue, que la destination ait evolue ailleurs, ou les deux.
- Implemente en script standalone plutot qu'en alias inline (coherent avec `git-deploy`) : deux clones + branchement fichier/repertoire + commit/push, trop pour un alias `!` lisible.
- Testes : sync initial repertoire, evolution concurrente source (ajout+suppression) et destination (contenu non lie, preserve), idempotence, fichier unique, source introuvable, mauvais nombre d'arguments.

### 1.14.1 — 2026-10-02
- `deploy = !git-deploy` au lieu du chemin absolu `!/home/claudia/Projets/Misc/Git/git-deploy`. `git-deploy` doit desormais etre dans le `PATH` (symlink ou ajout au `PATH`) ; sinon `git deploy` echoue proprement (`cannot run git-deploy: No such file or directory`).

### 1.14.0 — 2026-10-02
- Ajout de l'alias fin `deploy = !git-deploy`, qui appelle le nouveau script `git-deploy` (voir ci-dessous). `git alias` documente la nouvelle entree.

## git-deploy

### 1.3.0 — 2026-10-03
- `git deploy` sans argument utilise desormais `[default] type=` dans `.deploy.conf` (section reservee). Erreur claire si aucun type n'est precise ni par defaut.
- `.deploy.conf.example` et README mis a jour.

### 1.2.0 — 2026-10-02
- Nouvelle refonte du format `.deploy.conf` : introduction des **lots** (`[src "nom"]`, groupe nomme et reutilisable de sources). Un type de deploiement (ex `[prod]`) reference des lots par leur nom (`<lot> = dest`, cle repetable pour plusieurs destinations), au lieu de lister directement des sources individuelles par type. Le meme lot peut etre reutilise par plusieurs types avec des destinations differentes a chaque fois. Remplace le format 1.1.0 (une sous-section `dest` par source individuelle, sans reutilisation possible).
- Transfert redevenu groupe par destination (comme en 1.0.0, mais par lot plutot que par profil entier) : `git archive` sur tous les membres du lot en une fois, `strip-components` calcule une seule fois (prefixe du sous-projet), chaque membre atterrit sous son propre nom a la racine de la destination.
- Ajout de `set -o pipefail` : une source manquante dans un lot (`git archive` qui echoue) est desormais correctement detectee comme un echec, au lieu d'etre potentiellement masquee par le code de sortie de `ssh`/`tar` cote distant.
- `.deploy.conf.example` et README mis a jour avec le nouveau format.

### 1.1.0 — 2026-10-02
- Format `.deploy.conf` passe de 2 a 3 etages : type de deploiement (section) / source (sous-section) / cible (cle `dest`, repetable), au lieu d'une liste `file` + d'une liste `url` partagee par toutes les sources. Chaque source (fichier ou repertoire) peut desormais viser une destination differente (chemin/nom different sur le serveur cible), chose impossible avec l'ancien format ou toutes les sources d'un profil allaient au meme repertoire de base sur chaque url.
- Type de la source determine via `git cat-file -t HEAD:<chemin>` : fichier -> `git show` + `cat >`, repertoire -> `git archive` + `tar x --strip-components` (calcule par source, plus par profil entier).
- `.deploy.conf.example` et README mis a jour avec le nouveau format.

### 1.0.0 — 2026-10-02
- Creation : `git deploy <profil>` deploie le contenu commite (HEAD) de fichiers/repertoires vers des urls ssh/scp, selon un profil lu dans un `.deploy.conf` (non tracke, syntaxe git config) trouve en remontant l'arbo depuis le repertoire d'invocation. Transfert via `git archive | ssh ... tar x --strip-components`. Implemente en script standalone plutot qu'en alias inline : logique jugee trop consequente (recherche de config, calcul de prefixe, boucle multi-urls avec erreur geree par url) pour rester lisible dans un alias `!`.
- `.gitignore` racine : ajout de `**/.deploy.conf`.

### 1.13.0 — 2026-10-01
- `git alias` affiche desormais le nom de chaque alias avec une courte description (au lieu du nom + definition brute). Table de description codee en dur dans l'alias (a tenir a jour manuellement a chaque ajout/suppression d'alias) ; un alias non documente s'affiche avec une description vide plutot que de planter.

### 1.12.0 — 2026-10-01
- `fiput` et `tar` acceptent `-` comme source pour lire depuis **stdin** au lieu d'un fichier local (convention `-`, comme `tar`/`curl`). `fiput - ...` : `cat > destpath` directement. `tar - ...` : stdin bufferise dans un fichier temp avant extraction — `tar` n'autodetecte pas le format de compression (gzip/bzip2) sur un flux non-seekable (pipe), seulement sur un vrai fichier, d'ou le passage par un fichier temporaire pour reutiliser le meme chemin d'extraction fiable.

### 1.11.0 — 2026-10-01
- Ajout de l'alias `fidiff` : `git fidiff [-G <commit>] <depot> <fichier-local> <chemin-dans-le-depot>` affiche le `git diff --no-index` entre un fichier local et sa version dans le depot — HEAD par defaut, ou le commit precise via `-G` (meme mecanisme que `figet -G`). Comble le manque identifie face a `gitoune -d`.

### 1.10.0 — 2026-10-01
- `figet` accepte `-G <commit>` : `git figet [-G <commit>] <depot> <chemin> <destination>`. Sans `-G`, clone `--depth 1` (HEAD uniquement, inchange). Avec `-G`, clone complet + `git checkout <commit>` pour recuperer le fichier/repertoire a cette version precise. Comble le manque identifie face a `gitoune -G`.

### 1.9.0 — 2026-10-01
- Ajout de l'alias `filog` : `git filog <depot> <chemin-dans-le-depot>` clone le depot (historique complet) et affiche `git log` filtre sur ce chemin, meme format que l'alias `logs`. Comble le manque identifie face a `gitoune -l` (historique d'un fichier distant).

### 1.8.0 — 2026-10-01
- Ajout de l'alias `fiput` : `git fiput <depot> <fichier-local> <chemin-destination> <message>` clone `<depot>`, copie `<fichier-local>` vers `<chemin-destination>` (cree les repertoires intermediaires si besoin), commit avec `<message>` et pousse. Rien commite si le contenu est identique. Chemin local relatif au repertoire d'invocation via `$GIT_PREFIX`. Equivalent fichier unique de `git tar`, remplace l'usage ponctuel de `gitoune`.

### 1.7.0 — 2026-10-01
- Ajout de l'alias `figet` : `git figet <depot> <chemin-dans-le-depot> <destination>` recupere un fichier ou un repertoire precis d'un depot (clone --depth 1 dans un temp, sans historique) et le depose en local. Fichier -> copie vers `<destination>` (ou dans `<destination>/` si c'est un repertoire existant). Repertoire -> copie locale, ou archive si `<destination>` finit en `.tar`/`.tgz`/`.tar.gz`/`.tar.bz2`/`.tbz2`.
- Limite connue : le clone recupere tout l'historique courant (HEAD) du depot, pas seulement le chemin demande — git ne permet pas de transfert partiel portable sans support serveur (partial clone/sparse-checkout, ou `git archive --remote` souvent desactive cote hebergeur). Acceptable pour des depots de taille courante (Gitea perso), a eviter sur un gros monorepo distant.

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

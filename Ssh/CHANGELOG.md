# Changelog — sshvault

## sshvault 0.4.0 — Chargement transparent à la demande — 2026-10-07

- `ssh <hôte>` charge seul la clé manquante, pour la cible comme pour chaque saut
  ProxyJump/ProxyCommand : le `ssh_config` généré reçoit, avant chaque bloc, une ligne
  `Match originalhost <motifs> exec "'<sshvault>' ensure --id <id>"` sans directive. La
  commande ne contient que le chemin absolu de sshvault (entre apostrophes, `%` doublé ;
  `'`, `"`, `\`, `${` et caractères de contrôle refusés) et l'id (UUID vérifié) : jamais
  `%h` ni `%n`. Chemin résolu : la commande lancée sous le nom `sshvault`, sinon le PATH
  (dossiers absolus) ; introuvable : code 4.
- `sshvault ensure --id ID` : chemin rapide sans `bw` ni réseau si la clé est dans
  l'agent dédié avec plus de 60 s restantes (médiane mesurée 27 à 30 ms, max 31 à 43 ms ; point
  d'entrée `sshvault.launch` qui ne charge pas la CLI dans ce cas) ; sinon, sous un verrou
  `flock` par utilisateur et après relecture de l'état, chargement comme `load` (un seul
  `bw get item`, agent démarré s'il le faut, `ssh-add -t key-ttl -` par stdin, tout ou
  rien, état enregistré ; une clé presque expirée est rechargée, avec ses `-c`/`-h`).
  `ssh -G` (parent lu dans `/proc`, à travers le shell de `$SHELL -c`) : rien demandé,
  code 0. Invite du coffre sur `/dev/tty` seulement au premier plan du terminal, sinon
  askpass, sinon échec immédiat sans `bw` ; jamais stdin, jamais SIGTTIN. Échec de
  déverrouillage mémorisé 30 s pour la connexion (`unlock-failed`) : pas de nouvelle
  invite. Silencieux en cas de succès, une ligne `sshvault: <hôte> : <cause>` sinon ;
  délai global `SSHVAULT_ENSURE_TIMEOUT` (240 s) ; Ctrl-C, SIGTERM, SIGHUP rattrapés.
- Revue : agent vérifié (démarré, OpenSSH ≥ 8.9, verrou) avant toute invite ou `bw` ;
  mémoire d'échec liée à la connexion (ssh le plus haut : pid et date de démarrage),
  écrite seulement pour un mot de passe refusé par `bw` ou une invite annulée ou sans
  réponse, effacée par `sshvault unlock` ; askpass non exécutable = pas d'askpass ;
  `--nointeraction` et `-o BatchMode=yes` du ssh : aucune invite ; `ssh -O` traité comme
  `-G`, `-P` reconnu ; ssh appelant cherché sur tous les ancêtres ; seuil de fraîcheur
  min(60 s, durée/2) ; clé changée dans le coffre détectée (`.pub` de la config) ; même
  clé dans deux éléments : reconnue pour les deux ; `auto-confirm` refusé si l'agent n'a
  pas d'askpass ; clé privée différente détectée même avec une ancienne copie, retrait
  protégé des signaux, état non écrit → clé retirée ; délai global 240 s compté depuis le
  démarrage (chemin rapide compris), invite bornée par le temps restant, résultat acquis
  protégé d'un délai ou signal tardif ; avertissements du backend affichés ; invite
  « clé pour <hôte> » ; chemin de sshvault vérifié (`--version` ≥ 0.4.0), avertissement
  s'il change ou vient d'un `.venv`.
- `config` : `auto-load` (défaut `true` ; `false` = config de la 0.3.0, sans lignes
  `ensure`), `auto-restrict` et `auto-confirm` (défaut `false` : `ssh-add -h` / `-c` au
  chargement automatique). Booléens `true`/`false`.
- L'invite du coffre (toutes commandes) et l'écho coupé pendant `ssh-add` exigent
  désormais d'être au premier plan du terminal ; en arrière-plan : askpass ou échec.
- Message « absent de known_hosts » commun à `load --restrict` et `auto-restrict`
  (« restriction -h »).
- Tests : `tests/test_ensure.py`, une ligne par ligne de la matrice : vrais `ssh` contre
  deux sshd de test (rebond A, cible B), ProxyJump et ProxyCommand, vrais
  `ssh-agent`/`ssh-add`, faux `bw` (délai simulé de 1,4 s), pty au premier plan, en
  arrière-plan, deux ssh simultanés, Ctrl-C ; latence du chemin rapide mesurée. Garde de
  fin de session : aucun processus de test restant, `~/.ssh` réel inchangé, aucun dossier
  sshvault réel créé. Intégration : `ssh` vers un sshd local via `ensure` et le vrai `bw`.

## sshvault 0.3.0 — Association clé-hôtes et ssh_config généré — 2026-10-07

- `hosts add|remove|set SÉLECTION HÔTE…` et `hosts list SÉLECTION` : modifient le seul
  champ `sshvault-hosts` de l'élément (créé s'il manque, retiré s'il devient vide ; type
  texte ou masqué gardé ; autres champs, notes, clé et `revisionDate` tels que `bw` les
  rend). Sélection d'un seul élément comme `load` (plusieurs : code 2 « préciser --id »).
  Hôtes : lettres, chiffres, `.`, `-`, `_`, `*`, `?`, en minuscules, sans doublon ; autre
  caractère → code 2, rien écrit ; `remove` d'un hôte absent → code 1.
- Écriture par `bw edit item <id>` avec l'élément encodé sur **stdin** (jamais en
  argument), puis relecture ; `edit` en échec ou bloqué : relecture de l'état du serveur
  (`sync`, `get`), rejeu **une** fois seulement si l'élément n'a pas changé, succès si
  l'écriture est passée malgré l'erreur ; sinon code 4 avec l'état relu.
- `ssh-config [--print|--check]` : `~/.ssh/sshvault/config` (un bloc par élément
  associé, trié par nom puis id, ouvert par `Match originalhost <motif>,<motif>` : nom
  tapé, sans tenir compte de la casse, pas le `HostName` ; `IdentityAgent` = socket dédié résolu, `IdentityFile` =
  `pub/<empreinte base64url>.pub`, `IdentitiesOnly yes`), chemins absolus entre
  guillemets, `%` doublé ; écriture atomique 0600/0700, rien réécrit sans changement,
  `pub/` purgé ; élément à hôte invalide ou clé publique illisible sauté avec avertissement ;
  hôte porté par deux éléments : deux blocs et avertissement. `--check` : code 1 si pas à
  jour ou `Include` absent ou pas en tête. `hosts` régénère après chaque modification.
- `ssh-config install` : `Include "<HOME>/.ssh/sshvault/config"` en première ligne de
  `~/.ssh/config` (déplacée si plus bas, idempotent), sauvegarde `config.sshvault.bak`,
  mode et propriétaire conservés, lien symbolique refusé (code 4). Jamais automatique :
  `ssh-config` et `hosts` préviennent seulement.
- Mesuré (OpenSSH 8.9p1) : `Host foo` ne s'applique pas à `ssh FOO` (d'où `Match
  originalhost`) ; `IdentityAgent` et `IdentitiesOnly` de sshvault l'emportent sur un
  `Host *` placé après l'`Include`, mais un `IdentityFile` de l'utilisateur se cumule ;
  `Include` n'y développe pas `%` (les versions récentes le font : chemin avec `%` refusé
  à `install`).
- Revue : `hosts` fait `sync` avant de lire l'élément, vérifie socket et chemins avant
  d'écrire, signale une écriture peut-être passée si interrompu, et une clé chargée avec
  `--restrict` ; `ssh-config` sous verrou `flock`, jamais bloqué par une FIFO (fichier
  non ordinaire → code 4), `~` = répertoire de passwd ; `Include` « en tête » = avant la
  première ligne utile, conditionnel (dans un bloc Host/Match) signalé et non déplacé,
  reconnu sous toutes ses formes, lignes coupées sur `\n` seulement ; sauvegarde jamais
  écrasée (`.bak.N`) ; création sans écraser un fichier apparu entre-temps ; `--check`
  aligné sur l'écriture (droits des dossiers, `pub/` inutilisable) ; motifs attrape-tout
  (`*`, `*.*`, `?*`) et motifs qui se recouvrent : avertissement. `ForwardAgent` non
  écrit : mesuré qu'il transfère l'agent dédié entier (README).
- Tests : faux `bw` avec `edit` (stdin, `revisionDate` vérifiée, pannes avant/après
  écriture, concurrence) ; validation par `ssh -G -F` et `ssh -vvv` du poste (espace et
  `%` dans les chemins) ; intégration : `hosts add`/`remove` sur le compte de test,
  `/proc/<pid>/cmdline` surveillé pendant l'appel, relecture par un autre client `bw`,
  `ssh-config` dans un HOME de test.

## sshvault 0.2.0 — Agent dédié, chargement, état et purge — 2026-10-07

- `load (MOTIF [--host|--name|--fingerprint|--id] | --all) [-t DURÉE] [--confirm] [--restrict] [--force]` :
  charge des clés du coffre dans un `ssh-agent` d'OpenSSH dédié, clé privée passée par
  le seul stdin de `ssh-add -`. Sans sélection ni `--all` : code 2. Clé déjà présente non
  rechargée (sauf `--force`) ; `--restrict` : `ssh-add -h` par hôte (littéral, en
  minuscules ; known_hosts haché mesuré compatible) de l'élément, hôte non littéral ou
  absent de `known_hosts` → code 4, rien chargé ; `--confirm` : `ssh-add -c` (avertissement
  si l'agent n'a pas d'askpass). Tout ou rien : un échec en cours retire de l'agent les
  clés apparues pendant ce `load`.
- Agent lancé par le premier `load` sur `$XDG_RUNTIME_DIR/sshvault/agent.sock` (tmpfs privé
  vérifié, chemin canonique ; repli `/run/user/<uid>` si la variable manque), OpenSSH ≥ 8.9
  vérifié ; surveillant détaché qui l'arrête quand le socket ou `XDG_RUNTIME_DIR` disparaît
  (fin de session) ; agents orphelins arrêtés au lancement suivant ; pid vérifié (ligne de
  commande et socket) avant tout signal ; agent repris si l'état est perdu ; socket mort
  nettoyé puis agent relancé ; agent tiers sur le socket refusé sans rien toucher ; verrou
  `flock` contre les `load` simultanés. L'agent de l'utilisateur n'est jamais touché.
- `sshvault lock` (coffre) ne vide pas l'agent dédié : `agent purge|lock|stop`.
- `agent status | purge | lock | unlock | stop` ; fichier d'état `agent.json` (0600, sans
  secret) réconcilié avec `ssh-add -L`.
- `config get|set|unset key-ttl` (`${XDG_CONFIG_HOME:-~/.config}/sshvault/config.json`) :
  durée de vie par défaut (1 h), `N`, `Ns`, `Nm`, `Nh`, `Nd`, de 1 s à 30 j, `0` = illimitée ;
  priorité `-t` > config > 1 h.
- Clé chiffrée par passphrase : saisie déléguée à `ssh-add`, écho du terminal coupé par
  sshvault pendant tout `ssh-add` interactif (OpenSSH 8.9 ne le coupe pas pour une clé lue
  sur stdin, mesuré) et rétabli sur refus, délai ou signal ; askpass et ssh-add tués
  ensemble au délai ; `--nointeraction` ou refus → code 3.
- Vérification « tmpfs privé » partagée (`fsutil.check_private_tmpfs`).
- Tests : vrais `ssh-agent`/`ssh-add` sur sockets de test, agent témoin à la place de
  l'agent de l'utilisateur, agents et surveillants de test vérifiés arrêtés, `load` sous
  `strace -f`, `load` simultanés, retour arrière, reprise, orphelins ;
  intégration : `load`, `agent status`, `purge`, `stop` sur le compte de test.

## sshvault 0.1.0 — Squelette et lecture du coffre via bw — 2026-10-06

- CLI `sshvault` (Python ≥ 3.10, bibliothèque standard seule) installable par
  `uv tool install` : `status`, `login [--server URL] [--apikey]`, `unlock [--ttl]`,
  `lock`, `sync`, `list [--json]`, `search MOTIF [--host|--name|--fingerprint] [--json]`,
  option globale `--nointeraction`.
- Interface `VaultBackend` et première implémentation `BwBackend` (CLI `bw` en
  sous-processus, données dédiées dans `${XDG_DATA_HOME:-~/.local/share}/sshvault/bw`,
  `--nointeraction`, délai borné, mot de passe par `--passwordenv`).
- Éléments « SSH key » (type 5) seuls ; hôtes dans le champ personnalisé
  `sshvault-hosts` (virgules, insensible à la casse).
- Distinction « non connecté », « verrouillé » (code 3) et « erreur du backend »
  (code 4) : une panne de `bw` ne déclenche pas d'invite.
- Session dans le keyring `@u` avec expiration noyau, repli fichier 0600 dans
  `$XDG_RUNTIME_DIR/sshvault/` ; session refusée par `bw` purgée.
- `sync` relancé une fois si `bw` reste bloqué (connexion TLS neuve jamais acquittée,
  mesurée) : deux essais de `SSHVAULT_BW_TIMEOUT`/2 par passage.
- Délais `SSHVAULT_BW_TIMEOUT` et `SSHVAULT_PROMPT_TIMEOUT` validés (0 < v ≤ 86400,
  sinon code 2) ; repli fichier de la session seulement sur un tmpfs privé ; texte du
  coffre nettoyé des caractères de contrôle en sortie texte ; motif vide refusé ;
  écho du terminal rétabli si `bw login` est interrompu.
- Invite `/dev/tty` ou askpass selon `SSH_ASKPASS_REQUIRE` (`man ssh`), délai borné.
- Tests : faux `bw` fidèle (messages mesurés sur le vrai bw 2026.9.1), matrice des
  entrées et cas limites ; intégration (marqueur `integration`) sur le compte de test dédié par défaut,
  éléments marqués `sshvault-test-run` et supprimés en fin de test ; mode conteneur
  Vaultwarden 1.37.4 en option.

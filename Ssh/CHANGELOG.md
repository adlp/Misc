# Changelog — sshvault

## sshvault 0.8.0 — bw par chemin configuré ou PATH — 2026-10-08

- Réglage `bw-path` : `sshvault config set bw-path /chemin/absolu/bw`. Les lignes
  `Match exec` héritent du PATH du ssh appelant (session graphique, cron), qui peut ne pas
  contenir le dossier de `bw` : le chargement automatique trouve désormais `bw` par ce
  réglage. Ordre : `SSHVAULT_BW` (tests), sinon `bw-path`, sinon `bw` du PATH ; aucune
  recherche implicite ailleurs. Lu dans le `config.json` de l'environnement de ssh
  (`XDG_CONFIG_HOME` compris), au premier appel de `bw` seulement (une commande qui ne lance
  pas `bw` ne le lit pas) ; chemin passé tel quel à `Popen`, jamais à un shell ; arguments
  et environnement de `bw` inchangés.
- Lecture : `status`, `list`, `search`, `login`, `unlock`, `lock`, `sync`, `load -t`,
  `pubkey`, `deploy`, `hosts list` et `forward list` ne lisent que `bw-path`
  (`Config.bw_path`) : un autre réglage invalide ne les gêne pas (comme en 0.7.0). `config`,
  `ensure`, `load` sans `-t`, `ssh-config`, `hosts`/`forward add|remove|set`, `import` et
  `generate` avec hôtes valident toujours tout le fichier. Fichier illisible, droits, JSON
  invalide ou `bw-path` qui n'est pas une chaîne absolue sans caractère de contrôle :
  code 2.
- `config set bw-path` refuse (code 2, `config.json` inchangé) un chemin relatif, absent,
  avec un caractère de contrôle, ou dont la cible (lien suivi, gardé tel quel) n'est pas un
  fichier ordinaire exécutable par l'utilisateur. Messages
  `bw-path refusé : « <chemin> » (<raison>)`.
- `config unset bw-path` revient au PATH ; `config get` affiche le chemin ou
  `bw-path PATH (défaut)`. Avec `SSHVAULT_BW` posé, `set` le dit prioritaire, `unset` le
  dit toujours utilisé.
- Avertissement (pas un refus, choix de l'utilisateur : dossier partagé avec son groupe)
  quand d'autres peuvent remplacer `bw` : cible finale, dossier de chaque lien de la chaîne
  (lstat, liens relatifs résolus depuis leur dossier) et tous leurs parents jusqu'à `/`
  doivent être à l'utilisateur ou à root et non modifiables par le groupe ni les autres
  (sticky bit compris), comme le `StrictModes` d'OpenSSH. Une ligne sur stderr
  `avertissement : bw-path « <chemin> » exposé à d'autres (<raisons>) : ils pourraient
  remplacer bw et recevoir le mot de passe maître ; <remède>`, à `config set` puis une fois
  par processus, aussitôt, avant le premier lancement de `bw` (avant l'invite du mot de
  passe) ; sous `ensure`, préfixée de l'hôte. Remède : `« chmod g-w,o-w … »` pour ce qui est
  à l'utilisateur sans sticky bit, sinon « déplacer bw dans un dossier à vous non
  modifiable par d'autres ». Codes de sortie et stdout inchangés.
- Refus revérifié avant chaque lancement de `bw` par le réglage : fichier supprimé
  (ENOENT, ENOTDIR : « bw introuvable »), non exécutable, répertoire, inaccessible (EACCES,
  ELOOP : « bw refusé » avec la cause) : code 4, une ligne `bw introuvable|refusé (<chemin>,
  réglage bw-path)[ : <raison>] : corriger par « sshvault config set bw-path … » ou revenir
  au PATH par « sshvault config unset bw-path »` ; le PATH n'est pas essayé.
- Lancement de `bw` (toute source) : fichier présent mais interpréteur du shebang ou
  chargeur absent → « interpréteur ou chargeur de bw introuvable » ; ENOEXEC → « bw : format
  non exécutable » ; même remède que « bw introuvable » pour la source. Messages « bw
  introuvable » : citent le chemin essayé et sa source (`SSHVAULT_BW`, `réglage bw-path`,
  ou `bw cherché dans le PATH, réglage bw-path non posé`).
- `sshvault status` : première ligne `bw : <chemin> (SSHVAULT_BW | réglage bw-path | PATH)`
  (ou `bw : bw (introuvable dans le PATH)`), affichée avant tout lancement de `bw`, donc
  même s'il manque.
- Nettoyage des caractères de contrôle partagé (`sshvault.text.clean`) par la CLI, `bw` et
  la configuration.
- Tests : matrice de la story 9 (réglage utilisé par `status`, `list` et `ensure` avec un
  PATH sans `bw` et un `bw` piège en tête du PATH jamais lancé ; sans réglage ;
  `SSHVAULT_BW` prioritaire ; chemins refusés ; fichier, dossier, dossier d'un lien ou parent
  ouvert au groupe ou aux autres (sticky compris) accepté avec avertissement à `set` et une
  fois par processus, avant le premier lancement de `bw` et l'invite ; propriétaire
  étranger ; exécutable système à root sans avertissement ; fichier disparu, non
  exécutable, répertoire, inaccessible, boucle de liens, sans shebang ou à interpréteur
  absent ; autre réglage invalide sans effet sur `status`, `load -t`, `lock` ; `ensure` avec
  `config.json` invalide ; lecture paresseuse ; `unset` ; chemin avec espace, apostrophe et
  `$(…)` sans shell) ; sous vrai `ssh b` via le rebond `a` (agent vide, PATH sans `bw`,
  piège en tête) : clés chargées par le `bw` du réglage, et réglage cassé : une ligne par
  `ensure` citant `bw-path`, connexion refusée proprement. Banc : `env_without_bw`,
  `bw_wrapper`, `safe()` (dossier sous `/run/user/<uid>`, sans parent ouvert à d'autres).

## sshvault 0.7.0 — Transfert d'agent restreint par hôte — 2026-10-08

- Champ d'élément `sshvault-forward` (motifs d'hôtes, mêmes règles que `sshvault-hosts`) et
  commande `sshvault forward add|remove|set|list SÉLECTION HÔTE…`, calquée sur `hosts`
  (écriture sur stdin, relecture, rejeu unique, autres champs inchangés ; `set_forward` du
  backend) ; le `ssh_config` est régénéré ensuite.
- `ssh_config` généré : pour chaque motif de transfert, **avant** les blocs d'identité,
  `Match originalhost <motif> exec "'<sshvault>' ensure --forward <fid> --id <uuid>…"` puis
  `Match originalhost <motif>` + `ForwardAgent "<socket résolu du sous-agent>"` (`<fid>` = 16
  premiers hex du SHA-256 du motif en minuscules ; ni `%h` ni `%n` ; ids et motif validés).
  Mesuré (8.9p1) : ce chemin gagne sur un `ForwardAgent yes` ultérieur, `ssh -A` et
  `-o ForwardAgent=yes`. Motifs littéraux d'abord, puis à joker du plus précis au moins précis,
  attrape-tout en dernier ; la ligne `Match … exec` d'un bloc exclut les motifs des blocs
  précédents (`!motif`) ; avertissements : recouvrement (le premier bloc gagne), attrape-tout,
  motif invalide, id non UUID, clé publique illisible ; sans ligne `Match exec` possible
  (`auto-load false`, aucune clé utilisable) : `ForwardAgent no`. Aucun `ForwardAgent` pour un
  hôte d'identité sans transfert.
- Sous-agents : `ssh-agent` d'OpenSSH sur `$XDG_RUNTIME_DIR/sshvault/fwd/<fid>.sock`, état
  `<fid>.json`, mêmes garanties que l'agent dédié (`Agent` paramétré par socket et état,
  fabrique `forward_agent`) : pid vérifié, surveillant (aussi pour `fwd/`), orphelins arrêtés,
  verrou `flock` sur `fwd/`, `SSH_AUTH_SOCK` = son socket.
- `sshvault ensure --forward FID --id ID…` : clés des éléments, et elles seules, chargées à la
  demande dans le sous-agent (`ssh-add -t <key-ttl> [-c] -`, clé sur stdin, jamais `-h`), tout
  ou rien, clés en trop retirées, état enregistré ; chemin rapide (sans charger la CLI) si
  toutes sont fraîches et seules ; même verrou, même invite unique et même mémoire d'échec
  que `ensure --id` ; le coffre fait foi (élément qui ne déclare plus ce motif : rien chargé).
  N'ouvre jamais l'agent dédié (état lu : verrouillé → code 3). Échec : une ligne
  `… : transfert d'agent : …`, la connexion continue.
- Saut `ssh -W` (ProxyJump, ProxyCommand) et `ssh -N` : rien n'est transféré ni chargé ;
  mesuré : `-W` impose `ExitOnForwardFailure` (même avec `-a`), un socket absent arrêtait le
  saut : un sous-agent vide est lancé au besoin (ni réglage, ni coffre, ni invite). `ssh -a`,
  `-o ForwardAgent=no` : `ensure --forward` ne fait rien. Clé du coffre différente du `.pub`
  généré : retirée, code 4, « lancer sshvault ssh-config ».
- Réglage `forward-confirm` (défaut `true`) : clés transférées chargées avec `-c`. Sans askpass
  utilisable pour le sous-agent : rien chargé (une ligne) ; sous-agent lancé sans askpass
  relancé dès qu'un ssh en a un.
- `agent status` liste les sous-agents (motif, clés, temps restant, options) ; `agent purge`
  les vide ; `agent stop` les arrête (aucun ssh-agent de sshvault restant, `fwd/` vide) ;
  `agent lock` les vide et les arrête d'abord (rechargés par le premier ssh après `unlock`) ;
  `agent lock` et `agent stop` tiennent `ensure.lock` (aucun `ensure --forward` ne relance un
  sous-agent pendant l'arrêt).
- `ssh-config` (et toute régénération) arrête les sous-agents qu'il ne référence plus, ou qui
  gardent la clé d'un élément retiré du motif. `sshvault ssh-config` seul (et `--check`)
  avertit pour chaque hôte d'identité littéral sans transfert déclaré dont `ssh -G` montre
  `forwardagent yes` (l'agent dédié entier y serait transféré) ; 30 s au total.
- `config set|unset forward-confirm` qui change la valeur : sous-agents arrêtés (rechargés au
  prochain ssh). `agent lock`/`stop`, les régénérations qui arrêtent un sous-agent et ce
  réglage tiennent `ensure.lock` (« attente d'un chargement en cours (ensure)… » s'il est
  pris). `agent status|stop|purge|lock` : code 4 si un sous-agent est en erreur. Un état
  « verrouillé » laissé par un agent dédié mort ne bloque plus le transfert. Contrôle `ssh -G`
  : chaque `ssh -G` dans sa session, groupe tué au délai ; budget `SSHVAULT_SSH_G_BUDGET`.
- `list --json` : champ `forward` ; `forward … --host` (et la sélection par défaut) couvre
  aussi les motifs de transfert.
- README : section « Transfert d'agent restreint », risques résiduels (root distant pendant
  la session, confirmation hameçonnable, pas de `-h src>dst`, `ExitOnForwardFailure`, `ssh -A`
  et motifs non vérifiables sur les hôtes d'identité).
- Tests : `tests/test_forward.py` (matrice et critères de la story ; deux sshd de test,
  `ssh a 'ssh-add -L'` ne liste que la clé transférée, confirmation par askpass, saut
  ProxyJump) ; intégration : `forward add` relu par un second client `bw`, transfert vérifié
  sur sshd local avec le vrai `bw`, `forward remove`.

## sshvault 0.6.0 — Génération d'une clé dans le coffre — 2026-10-08

- `sshvault generate --name NOM [--type ed25519|rsa] [--bits 3072|4096] [--comment TEXTE]
  [--hosts HÔTE,…] [--force]` : nouvelle clé générée par
  `ssh-keygen -q -t <type> [-b <bits>] -N "" -C <commentaire> -f <dossier>/key` dans un
  sous-dossier 0700 neuf du tmpfs privé (mêmes règles que la copie de l'import : tmpfs
  vérifié, verrou `flock`, suppression sur tous les chemins, signaux masqués pendant la
  suppression, orphelin `generate.<pid>.*` récupéré). La clé privée est relue en mémoire,
  jamais écrite par sshvault sur disque persistant (limites : swap d'un tmpfs, copies en mémoire
  du processus jusqu'à sa fin), affichée ni passée en argument ; l'élément est créé
  par le chemin de l'import (stdin, reprise sans doublon, relecture, trois champs `sshKey`).
- Ed25519 par défaut ; RSA 3072 ou 4096 (défaut 4096) ; toute autre valeur (ECDSA, DSA,
  `-sk`, `--bits 1024`, `--bits` avec Ed25519) : code 2 avant toute génération. Sans
  passphrase (le coffre chiffre déjà la clé).
- stdout ne contient que la clé publique, une ligne au format OpenSSH ; tout le reste sur
  stderr (la régénération du `ssh_config` y écrit aussi son compte rendu). Nom déjà porté par
  une clé du coffre : code 1, rien généré, sauf `--force`. Commentaire (défaut : le nom) :
  imprimable, 255 caractères au plus.
- Ordre des contrôles : usage (2), tmpfs privé (4), prérequis du `ssh_config` (4), coffre
  (3), nom (1), puis seulement la génération. Création non aboutie : code 4, le message dit
  que la clé générée est perdue (jamais écrite sur disque). Interruption : code 130, dossier
  supprimé ; pendant la création, « création peut-être passée ».
- `sshvault pubkey (SÉLECTION | --all)` : une ligne de clé publique par clé sélectionnée,
  rien d'autre sur stdout ; cache local de `bw`, aucun appel réseau ; commentaire avec
  caractère de contrôle retiré ; clé publique illisible : message, code 4.
- `sshvault deploy SÉLECTION [UTILISATEUR@]HÔTE [-p PORT] [-- OPTIONS_SSH…]` : ajoute les clés
  publiques sélectionnées à `~/.ssh/authorized_keys` de la cible par un seul `ssh` (clés sur
  stdin, commande distante fixe `exec sh -c '…'` sans donnée de l'utilisateur, `umask 077`,
  `~/.ssh` 0700 et `authorized_keys` 0600 créés au besoin, ajout seulement si type + base64
  absents, lignes commentées ignorées) ; « ajoutée » ou « déjà présente », une ligne par clé ;
  idempotent. Cible validée (lettres, chiffres, `.`, `-`, `_`, IPv6 entre crochets ; code 2
  sinon), options ssh passées en arguments séparés, sans shell local (seules des options de
  `ssh` acceptées après `--`), `--nointeraction` → `-o BatchMode=yes`. `ssh` en échec :
  code 4 avec son message. Variable `SSHVAULT_SSH`.
- `deploy`, durcissements : options qui changent le mode de `ssh` refusées (`-N -n -f -G -V
  -Q -O -W -s -M -t`, `-o RequestTTY/StdinNull/SessionType/ForkAfterAuthentication/
  RemoteCommand/LocalCommand/PermitLocalCommand/ProxyUseFdpass`) ; `-o ConnectTimeout=30`
  ajouté sauf s'il est donné ; délai global `SSHVAULT_DEPLOY_TIMEOUT` (120 s, ssh arrêté par
  TERM puis KILL, code 4) ; échec partiel : clés déjà ajoutées dites, puis code 4 ; IPv6 entre
  crochets passée sans crochets à ssh, IPv6 nue validée (`cafe:22` refusé) ; script distant :
  CRLF reconnu, « déjà présente (avec options…) », verrou `~/.ssh/.sshvault-deploy.lock`,
  `restorecon -F` si présent, aucun `!` ; type de clé hors `ssh-*`/`ecdsa-*`/`sk-*` refusé
  localement (les autres clés déployées).
- `generate` : prérequis (dossier `sshvault/` du tmpfs, chemins du `ssh_config`) vérifiés avant
  le coffre ; avertissement attrape-tout une seule fois, après le contrôle du nom ; session
  refusée à la création : « clé perdue » dit aussi ; interruption ou sortie fermée après la
  création : « clé créée : « nom » id » (et « ssh_config non régénéré » au besoin) ; `--type ""`
  refusé. Limites documentées (swap d'un tmpfs, copies en mémoire du processus).
- Intégration : purge de tous les éléments `sshvault-test-run` au début et à la fin ; `sync` et
  `delete` retentés après une panne réseau passagère.
- `private_copy` : dossier sans données (génération), préfixe et messages paramétrés ;
  `reap_stale` récupère aussi `generate.<pid>.*`. Message « élément relu différent » : « avant
  de relancer la commande » (import et generate).
- Tests : `tests/test_generate.py` (matrice de la story, sshd de test à HOME de test,
  connexion avec la clé déployée, script distant sous sh/dash/bash, argv contrôlé après coup
  contre la clé générée) ; `ArgvWatch(keep_all=True)` ; intégration : `generate` relue par
  un second client `bw`, `pubkey`, `load`, `ssh -G`.

## sshvault 0.5.0 — Import d'une clé existante — 2026-10-07

- `sshvault import FICHIER… [--name NOM] [--hosts HÔTE,…] [--force] [--decrypt]` : chaque
  fichier devient un élément « SSH key » avec `privateKey` (le fichier tel quel),
  `publicKey` et `keyFingerprint`, et ses hôtes dans `sshvault-hosts` (validés comme pour
  `hosts add`) ; `ssh_config` régénéré si des hôtes sont donnés, prérequis vérifiés avant
  d'écrire. Nom : commentaire de la clé (ou de la `.pub` voisine qui correspond), sinon nom
  du fichier ; `--name` pour un seul fichier.
- Acceptées : Ed25519 et RSA ≥ 2048 bits, formats OpenSSH, PKCS#8 (PEM ; RSA seulement avec
  OpenSSH 8.9, qui ne lit pas une Ed25519 PKCS#8) et RSA PEM PKCS#1. Refusées, code 2,
  message clair : ECDSA, DSA, `-sk`, PuTTY, SSH2, RSA trop courte, clé publique, fichier qui
  n'est pas une clé (ou partie privée incohérente avec l'en-tête), illisible, non ordinaire
  ou de plus de 64 Kio.
- PEM en clair (RSA PKCS#1, PKCS#8) : converti au format OpenSSH par
  `ssh-keygen -p -P "" -N ""` sur une copie dans le tmpfs privé (supprimée sur tous les
  chemins), original intact. PKCS#1 chiffrée : seulement avec `--decrypt`, sinon code 2 avec
  l'indication. PKCS#8 chiffrée sans `--decrypt` : gardée telle quelle (clients Bitwarden
  peut-être incapables de l'utiliser, dit à l'import). Fins de ligne CRLF stockées en LF
  (`ssh-add -` refuse le CRLF, mesuré).
- Clé publique lue dans l'en-tête OpenSSH (sans passphrase ; pour un PEM, après
  conversion), ou par `ssh-keygen -y` sur une copie pour une PKCS#8 chiffrée ; empreinte
  comme `ssh-keygen -l`. `.pub` voisine différente ou illisible : avertissement, ignorée.
- Clé à passphrase : importée **chiffrée** par défaut (avertissement : passphrase demandée
  au chargement, inutilisable par l'agent de Bitwarden Desktop). `--decrypt` : passphrase
  demandée une fois par `ssh-keygen -p -N "" -f <copie>` (terminal au premier plan ou
  askpass, jamais `-P`), copie 0600 dans un sous-dossier 0700 du tmpfs privé, lue puis
  supprimée sur tous les chemins (signaux masqués pendant la suppression ; un échec du
  nettoyage n'efface jamais l'erreur en cours ; verrou `flock` tenu sur le sous-dossier,
  orphelin d'un SIGKILL au verrou libre supprimé au suivant, même pid réutilisé). Invite :
  règles de readpass.c (askpass d'abord avec `SSH_ASKPASS_REQUIRE=force|prefer`) ; invite
  impossible décidée avant tout accès au coffre. PKCS#8 chiffrée sans `--decrypt` : une invite, pour la clé
  publique seulement. Mesuré (OpenSSH 8.9p1) : `ssh-keygen -y` relit le fichier après la
  saisie de la passphrase, un tube déjà lu est vide ; la clé publique d'une PKCS#8 chiffrée
  passe donc aussi par la copie tmpfs.
- Fichier d'origine et `.pub` jamais modifiés ni supprimés (pas d'option) ; le README
  invite à supprimer soi-même l'original, avec la mise en garde SSD/journalisation.
- Doublon (empreinte déjà dans le coffre, après `bw sync`) : code 1 avec le nom et l'id de
  l'élément existant (avec `--hosts` : la commande `hosts add --id …` à lancer) ; `--force`
  crée un second élément.
- Création par `bw create item`, élément encodé sur stdin ; relecture et comparaison des
  trois champs `sshKey` et des hôtes. Échec ou blocage : `sync`, recherche d'un nouvel
  élément à cette empreinte (les éléments déjà présents exclus, pour `--force`), rejeu une
  seule fois s'il est absent, code 4 s'il l'est toujours ; créé mais différent : code 4,
  l'id à supprimer donné. Interruption : code 130 et « création peut-être passée » (avec
  `--hosts`, clés créées nommées et `sshvault ssh-config` à lancer).
- Plusieurs fichiers : une ligne par fichier, code de sortie = le pire rencontré.
- Variables : `SSHVAULT_SSH_KEYGEN` ; `SSHVAULT_TEST_FIELD` (tests : champ ajouté aux
  éléments importés, marqueur de nettoyage de l'intégration).
- Tests : `tests/test_import.py` (vraies clés `ssh-keygen`, formats convertis, pty et
  askpass, faux `bw` capable de `create` et de ses pannes, argv de `bw`/`ssh-keygen` et
  `/proc/<pid>/cmdline` sans JSON, clé ni passphrase, aucun fichier de clé hors des
  fixtures) ; intégration : import de trois clés de test (dont une PKCS#1 convertie),
  relecture par un autre client `bw`, `load`, `ssh -G`. `ArgvWatch` déplacé dans
  `tests/bench.py` (ancêtres de pytest exclus du relevé).

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

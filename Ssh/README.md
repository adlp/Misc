# sshvault

Clés SSH dans un Vaultwarden auto-hébergé, utilisées de façon transparente par ssh.

État (0.2.0) : **lecture** du coffre via le CLI officiel `bw` (lister et chercher les
éléments « SSH key ») et **agent dédié** : chargement d'une clé du coffre dans un
`ssh-agent` d'OpenSSH propre à sshvault, sans écriture disque, avec durée de vie,
confirmation et restriction aux hôtes en option ; état, purge, verrou et arrêt de l'agent.
`ssh_config` généré, chargement à la demande, import et génération de clés viendront ensuite.

## Installation (sans root)

1. `bw`, binaire natif, dans `~/.local/bin`, empreinte vérifiée. La release ne publie
   pas de fichier `.sha256` : l'empreinte vient du champ `digest` de l'asset, publié
   par l'API GitHub de la même release.
   ```
   export VER=2026.9.1
   D=$(mktemp -d)
   curl -fL -o "$D/bw.zip" "https://github.com/bitwarden/clients/releases/download/cli-v$VER/bw-linux-$VER.zip"
   SUM=$(curl -fsS "https://api.github.com/repos/bitwarden/clients/releases/tags/cli-v$VER" \
     | python3 -c 'import json, os, sys; n = "bw-linux-%s.zip" % os.environ["VER"]; print(next(a["digest"] for a in json.load(sys.stdin)["assets"] if a["name"] == n).split(":", 1)[1])')
   echo "$SUM  $D/bw.zip" | sha256sum -c - \
     && mkdir -p ~/.local/bin \
     && unzip -o -d ~/.local/bin "$D/bw.zip" bw && chmod 700 ~/.local/bin/bw
   rm -r "$D"
   ```
   Un autre chemin se donne par `SSHVAULT_BW=/chemin/vers/bw`.
2. sshvault (Python ≥ 3.10, bibliothèque standard seule) :
   ```
   uv tool install ./Ssh        # depuis la racine de Misc ; --force pour réinstaller
   sshvault --help
   ```
   La commande est installée dans `~/.local/bin/sshvault`.

## Utilisation

```
sshvault login --server https://vault.example.org   # interactif (délégué à bw)
sshvault unlock [--ttl 900]                          # invite du mot de passe maître
sshvault list [--json]
sshvault search MOTIF [--host | --name | --fingerprint] [--json]
sshvault sync
sshvault status
sshvault lock

sshvault load (MOTIF [--host | --name | --fingerprint | --id] | --all) [-t DURÉE] [--confirm] [--restrict] [--force]
sshvault agent status | purge | lock | unlock | stop
sshvault config get [key-ttl] | set key-ttl DURÉE | unset key-ttl
```

- `list` affiche, pour chaque élément « SSH key » (type 5) : nom, empreinte, hôtes.
  `--json` ajoute l'id et la clé publique. Une clé privée n'est jamais affichée.
- `search` : `--host` motif glob (`*`, `?`, `[…]`) sur les hôtes, insensible à la
  casse ; un hôte associé écrit en glob avec `*` ou `?` (`*.lab`) couvre aussi le nom
  cherché (`x.lab`) ; `--name` sous-chaîne du nom, insensible à la casse ;
  `--fingerprint` empreinte exacte, avec ou sans `SHA256:`. Sans option : l'une des
  trois. Un motif vide est refusé (code 2).
- En sortie texte, les caractères de contrôle venus du coffre (tabulation, fin de
  ligne, séquences d'échappement) sont affichés sous la forme `\xNN` ; `--json` les
  garde tels quels.
- Option globale `--nointeraction` (avant la commande) : jamais d'invite ; un
  coffre verrouillé donne le code 3.
- Coffre verrouillé : `list`, `search`, `sync` et `load` demandent le mot de passe, puis
  gardent la session (900 s).
- Déconnexion : pas encore de commande `logout`. En attendant :
  `sshvault lock && BITWARDENCLI_APPDATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/sshvault/bw" bw logout`.

### Agent dédié

OpenSSH ≥ 8.9 requis (vérifié par `ssh -V` au démarrage de l'agent, sinon code 4) ;
testé avec 8.9p1-3ubuntu0.17 (Ubuntu 22.04). `-h`/`-H` et les messages d'`ssh-add` lus
par sshvault sont ceux de cette version.

- `load` charge dans l'agent dédié les clés choisies comme pour `search` (`--id` : id
  exact de l'élément ; `--all` : toutes les clés SSH du coffre), une ligne par clé. Sans
  sélection ni `--all` : code 2 (« préciser une sélection ou --all »). Aucune clé ne
  correspond : code 1. Deux éléments portant la même clé : un seul chargement.
  - `-t DURÉE` : durée de vie (`N`, `Ns`, `Nm`, `Nh`, `Nd`, entre 1 s et 30 j ; `0` =
    illimitée). Priorité : `-t`, puis `config key-ttl`, puis 1 h.
  - `--confirm` : `ssh-add -c`, confirmation demandée **par l'agent** à chaque usage,
    avec l'askpass de l'environnement (`DISPLAY`, `SSH_ASKPASS`) du `load` qui l'a lancé.
    Si l'agent a été lancé sans askpass utilisable, `load --confirm` l'avertit (chaque
    usage serait refusé) : `agent stop`, puis `load` depuis une session graphique.
  - `--restrict` : `ssh-add -h <hôte>` pour chaque hôte de l'élément, clés d'hôte lues
    dans `known_hosts` par `ssh-add`. Hôtes **littéraux** seulement (nom ou IPv4) : un
    motif (`*`, `?`), `user@hôte`, `a>b`, `hôte:port` ou IPv6 est refusé (code 4, rien
    chargé), comme un élément sans hôte ou un hôte absent de `known_hosts`. Les hôtes
    sont passés en minuscules : mesuré sur 8.9, `-h` trouve une entrée **hachée**
    (`ssh-keygen -H`, `HashKnownHosts yes`) seulement sous le nom en minuscules
    (`-h Bastion` échoue, `-h bastion` réussit) ; une entrée en clair est trouvée sans
    tenir compte de la casse. Défense en profondeur, pas une garantie (voir SPEC).
  - Une clé déjà présente dans l'agent n'est pas rechargée (« déjà chargée ») : un
    rechargement écraserait sa durée et ses contraintes. `--force` la recharge avec les
    nouvelles options.
  - Clé du coffre chiffrée par passphrase : `ssh-add` la demande (askpass s'il est
    permis et installé, sinon le terminal). sshvault coupe l'écho du terminal pendant
    tout `ssh-add` interactif (OpenSSH 8.9 lit la passphrase d'une clé passée sur stdin
    sans le faire, mesuré) et le rétablit sur tous les chemins (refus, délai, signal).
    Refus, annulation, délai (`SSHVAULT_PROMPT_TIMEOUT` + 10 s) ou `--nointeraction` :
    code 3.
  - Tout ou rien : sélection, hôtes de `--restrict` et clés chiffrées sous
    `--nointeraction` sont vérifiés, puis toutes les clés lues, avant le premier
    chargement ; un échec ensuite (passphrase refusée, clé privée qui ne correspond pas à
    la clé publique de l'élément, interruption) retire de l'agent les clés apparues
    pendant ce `load` (`ssh-add -d -`, clé publique sur stdin). Une clé rechargée par
    `--force` ne retrouve pas ses anciennes options. Un élément dont la clé publique est
    illisible est ignoré avec un avertissement (code 4 si rien d'autre n'est chargeable).
- La clé privée ne passe que par le stdin de `ssh-add -` : jamais en argument, dans un
  fichier, un journal ou une sortie.
- **Socket** : `$XDG_RUNTIME_DIR/sshvault/agent.sock` (chemin canonique : la même base
  écrite autrement — `/`, `/./`, lien — donne le même socket). `XDG_RUNTIME_DIR` doit
  appartenir à l'utilisateur, sans droits groupe/autres, sur tmpfs ou ramfs ; absent :
  repli sur `/run/user/<uid>` s'il passe la même vérification ; relatif, non privé, ou
  chemin du socket trop long (107 octets) : code 4. `agent status` affiche le chemin.
- **Vie de l'agent** : `ssh-agent -a <socket>` (jamais `-d`/`-D`), lancé par le premier
  `load`, avec un petit surveillant détaché (`python -m sshvault.watch`, sa propre
  session) qui l'arrête dès que le socket ou `XDG_RUNTIME_DIR` disparaît (fin de
  session : le tmpfs est vidé ; vérifié toutes les 2 s), puis s'arrête ; il s'arrête aussi
  avec l'agent. Utile car l'agent survit sinon à la déconnexion (`KillUserProcesses=no`).
  À chaque lancement, sshvault arrête aussi les agents orphelins : ssh-agent de
  l'utilisateur qui visent ce socket alors qu'il a disparu ou qu'il est servi par l'agent
  enregistré. Pas d'unité systemd. `agent stop` arrête agent et surveillant.
- `sshvault lock` verrouille le **coffre** seulement : il ne vide ni ne verrouille
  l'agent dédié (`agent purge`, `agent lock` ou `agent stop` pour cela).
- L'agent de l'utilisateur (`SSH_AUTH_SOCK` hérité) n'est jamais lu ni modifié : chaque
  `ssh-add` reçoit `SSH_AUTH_SOCK` = socket dédié.
- **Identité de l'agent** : avant tout signal, sshvault vérifie que le pid est un
  processus de l'utilisateur lancé comme `ssh-agent … -a <socket>`, et que le socket est
  celui enregistré. État perdu, illisible ou d'une version inconnue : l'unique ssh-agent
  de l'utilisateur qui vise ce socket est repris (enregistrement reconstruit, clés
  affichées `?`). Socket mort : retiré, l'agent est relancé au `load` suivant. Socket
  vivant sans tel agent : agent tiers, refus, rien touché (code 4).
- **Concurrence** : verrou `flock` sur le dossier `sshvault/` (aucun fichier créé) de
  l'examen de l'agent à son démarrage, et autour de chaque mise à jour de l'état.
- **État** : `$XDG_RUNTIME_DIR/sshvault/agent.json` (0600, aucun secret) : pid de l'agent
  et de son surveillant, askpass utilisable au lancement, verrou ; par empreinte : id et
  nom de l'élément, hôtes, heure de chargement, durée, options. Réconcilié avec
  `ssh-add -L` (à `status` et `load`) : une clé expirée ou retirée disparaît. Si l'agent
  ne montre aucune clé alors que l'état en a, les lignes non échues sont gardées et
  `status` affiche « verrouillé ? » (verrou posé hors sshvault, ou clés retirées à la main).
- `agent status` : agent, socket, pid, puis une ligne par clé (nom, empreinte, hôtes,
  temps restant, options, séparés par des tabulations ; `?` pour une clé chargée hors de
  sshvault). Agent arrêté : code 3.
- `agent purge` : `ssh-add -D` (toutes les clés, même chargées hors sshvault), état vidé
  (agent arrêté : rien à faire, code 0).
- `agent lock` / `agent unlock` : `ssh-add -x` / `-X`, mot de passe saisi par `ssh-add`
  (terminal ou askpass ; sous `--nointeraction` ou sans saisie possible : code 3). Un
  agent verrouillé ne montre aucune clé : `status` affiche celles de l'état ; `load` et
  `purge` refusent (code 3). Si l'état dit « verrouillé » mais que l'agent montre des
  clés, l'état est corrigé. `unlock` d'un agent qui montre ses clés : « déjà
  déverrouillé », code 0.
- `agent stop` : agent tué (pid vérifié), socket et état supprimés. Pid réutilisé par un
  autre processus : aucun signal, seul le socket est nettoyé.
- **Config** : `${XDG_CONFIG_HOME:-~/.config}/sshvault/config.json` (0600, dossier 0700,
  aucun secret). `config set key-ttl 2h` fixe la durée par défaut, `config get` l'affiche,
  `config unset key-ttl` revient à 1 h. Durée ou fichier invalide (JSON, valeur, droits
  autres que 0600, propriétaire) : code 2 ; écriture impossible : code 4.

### Hôtes d'une clé

Champ personnalisé `sshvault-hosts` de l'élément, texte ou masqué : liste
d'hôtes séparés par des virgules (`prod.example.org, *.lab`). Les espaces autour
sont ignorés et la comparaison est insensible à la casse. Le nom de l'élément
reste libre.

### Codes de sortie

| Code | Sens |
|---|---|
| 0 | succès |
| 1 | `search`, `load` : aucun résultat |
| 2 | usage (option ou argument invalide ; `load` sans sélection ni `--all`) ; durée invalide ; `config.json` invalide, illisible ou aux droits inattendus |
| 3 | non connecté (« lancer sshvault login »), ou coffre verrouillé : aucune invite possible, invite annulée ou sans réponse, mot de passe refusé ; agent dédié arrêté (`agent status`, `lock`, `unlock`) ou verrouillé ; passphrase d'une clé refusée ou impossible à saisir |
| 4 | erreur du backend : `bw` introuvable, en erreur, réponse illisible, délai dépassé ; magasin de session inutilisable ; agent dédié : `XDG_RUNTIME_DIR` relatif, non privé ou hors tmpfs, chemin du socket trop long, agent tiers sur le socket, OpenSSH < 8.9, `--restrict` (élément sans hôte, hôte non littéral ou absent de `known_hosts`), clé publique illisible ou différente de la clé privée, `ssh-add`/`ssh-agent` en erreur ; écriture de `config.json` impossible ; erreur interne |
| 130 | interrompu (Ctrl-C, SIGTERM, SIGHUP) |

`status` : 0 si le coffre est déverrouillé, 3 s'il est verrouillé ou non connecté,
4 si `bw` est en erreur. Un délai invalide dans l'environnement (voir Variables) donne
le code 2. Toute erreur est une ligne sur stderr, sans traceback.

## Fonctionnement

- **`bw` dédié** : sshvault lance `bw` avec
  `BITWARDENCLI_APPDATA_DIR=${XDG_DATA_HOME:-~/.local/share}/sshvault/bw`. Son
  login est donc séparé de l'usage personnel de `bw` (un `unlock` invalide les
  sessions précédentes). `bw serve` n'est jamais utilisé.
- `bw` est appelé avec `--nointeraction` (sauf `login`), un délai borné
  (`SSHVAULT_BW_TIMEOUT`, 60 s par défaut) et la session dans `BW_SESSION` de son
  seul environnement. Le mot de passe maître passe par `--passwordenv`, dans
  l'environnement du seul sous-processus : jamais en argument ni dans un fichier.
- Réseau : `list`, `search`, `unlock`, `lock` et `status` ne lisent que le cache local
  de `bw` (aucune connexion) ; seuls `sync` et `login` passent par le réseau. Une
  connexion neuve peut y rester bloquée sans fin (mesuré : ClientHello TLS jamais
  acquitté ; `bw` n'a pas de délai réseau propre). Un passage de `sync` fait donc
  deux essais de `SSHVAULT_BW_TIMEOUT`/2 chacun. S'il faut d'abord déverrouiller (pas
  de session rangée, ou session refusée par `bw`), s'y ajoutent l'invite, `bw status`
  ou un premier passage refusé, et `bw unlock` : au pire
  3 × `SSHVAULT_BW_TIMEOUT` + `SSHVAULT_PROMPT_TIMEOUT`.
- **Session** : keyring noyau `@u` (clé `user` `sshvault:session`, expiration
  posée par le noyau). Si `keyctl` échoue (session keyring non liée à `@u`, par
  exemple un tmux survivant à sa session), repli sur
  `$XDG_RUNTIME_DIR/sshvault/session` (0600), expiré à la lecture, seulement si
  `XDG_RUNTIME_DIR` appartient à l'utilisateur, sans droits groupe/autres, sur tmpfs
  ou ramfs ; sinon la session n'est pas rangée (`unlock` : code 4 ; `list` marche
  avec un avertissement). `lock` vide les deux. Une session refusée par `bw` est purgée.
- **Invite** : `/dev/tty` (pas stdin), ou le programme `SSH_ASKPASS`, selon les
  règles de `man ssh` pour `SSH_ASKPASS_REQUIRE` (`never`, `prefer`, `force`) et
  `DISPLAY`/`WAYLAND_DISPLAY`. Délai `SSHVAULT_PROMPT_TIMEOUT` (60 s par défaut).
- Fichiers créés en 0600, dossiers en 0700.

### Variables

| Variable | Rôle |
|---|---|
| `SSHVAULT_BW` | exécutable `bw` (défaut : `bw` du PATH) |
| `SSHVAULT_BW_TIMEOUT` | délai d'un appel `bw`, en secondes, 0 < v ≤ 86400 (défaut 60 ; `login` : 600) |
| `SSHVAULT_PROMPT_TIMEOUT` | délai d'une invite, en secondes, 0 < v ≤ 86400 (défaut 60) |
| `SSHVAULT_KEYRING`, `SSHVAULT_KEYCTL` | anneau et exécutable `keyctl` (tests ; défaut `@u`, `keyctl`) |
| `XDG_DATA_HOME` | base du dossier de données de `bw` (défaut `~/.local/share`) |
| `XDG_RUNTIME_DIR` | repli fichier de la session ; socket et état de l'agent dédié (tmpfs privé exigé) |
| `XDG_CONFIG_HOME` | base de `sshvault/config.json` (défaut `~/.config`) |
| `SSHVAULT_SSH_AGENT`, `SSHVAULT_SSH_ADD` | exécutables `ssh-agent` et `ssh-add` (défaut : ceux du PATH) |
| `SSHVAULT_KNOWN_HOSTS` | fichiers known_hosts passés à `ssh-add -H` pour `--restrict`, séparés par `:` (défaut : ceux d'`ssh-add`) |
| `BW_CLIENTID`, `BW_CLIENTSECRET` | clé API pour `sshvault login --apikey` (lues par `bw`) |
| `SSH_ASKPASS`, `SSH_ASKPASS_REQUIRE`, `DISPLAY`, `WAYLAND_DISPLAY` | choix de l'invite (`man ssh`) |
| `NODE_EXTRA_CA_CERTS` | transmise à `bw` (certificat auto-signé du serveur) |

## Tests

```
cd Ssh
uv run --python 3.10 pytest -q                    # faux bw, sans réseau
uv run --python 3.10 pytest -q -m integration     # vrai bw + compte de test (ou conteneur)
```

- Les tests unitaires passent par `tests/fake_bw.py`, un faux `bw` qui reproduit
  les sorties du vrai (2026.9.1). Ils tournent dans une session keyring anonyme
  neuve, avec un anneau dédié par test : le `@u` réel n'est jamais touché.
- Les tests de l'agent (`tests/test_agent.py`) utilisent les vrais `ssh-agent` et
  `ssh-add` du poste (ignorés s'ils manquent), sur des sockets de test en `/dev/shm`. `SSH_AUTH_SOCK` y pointe sur
  un agent témoin dont le contenu est revérifié inchangé après chaque test ; tout
  `ssh-agent` (et surveillant) lancé par un test est arrêté et sa disparition vérifiée. Un test passe
  `load` sous `strace -f` : seules écritures, le fichier d'état (et son temporaire).
- L'intégration (`-m integration`, `bw` par `SSHVAULT_BW` ou le PATH) a deux modes :
  - **compte de test** (défaut) : identifiants dans `~/.config/sshvault-test/account.env`
    (0600, hors git ; chemin remplaçable par `SSHVAULT_IT_ENV`) : `SSHVAULT_IT_SERVER`,
    `SSHVAULT_IT_EMAIL`, `SSHVAULT_IT_PASSWORD`, `NODE_EXTRA_CA_CERTS` en option. Jamais
    affichés ; mot de passe par `--passwordenv` ; données `bw` dans des dossiers
    temporaires supprimés à la fin. Le test crée 2 éléments SSH et 1 login marqués
    `sshvault-test-run=<uuid>`, pilote sshvault, puis supprime définitivement
    (`--permanent`) les seuls éléments de son run, même en cas d'échec, et fait `bw logout` ;
  - **conteneur** (`SSHVAULT_IT_MODE=container`) : Vaultwarden 1.37.4 sur un port libre de
    127.0.0.1, compte créé par l'API (crypto d'inscription Bitwarden, dépendance de test
    `cryptography`), conteneur supprimé à la fin.
  Ignorée si ni le fichier ni (en mode conteneur) docker ne sont disponibles.
  `SSHVAULT_IT_REPORT=<fichier>` y écrit les messages réels de `bw` mesurés, sans identifiants.
  Le test pilote `sshvault login` sous un pseudo-terminal, puis `unlock` (askpass),
  `list`, `search`, `sync`, `load` d'une clé de test dans l'agent dédié, `agent status`,
  `purge` et `stop`, une session invalidée et `lock`. `register.py` (mode
  conteneur) se lance seul par `SSHVAULT_IT_PASSWORD=… python register.py <url> <e-mail>`.

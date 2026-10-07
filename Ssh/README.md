# sshvault

Clés SSH dans un Vaultwarden auto-hébergé, utilisées de façon transparente par ssh.

État (0.1.0) : squelette de la CLI et **lecture** du coffre via le CLI officiel `bw`
(lister et chercher les éléments « SSH key »). Agent dédié, `ssh_config` généré,
chargement à la demande, import et génération de clés viendront ensuite.

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
- Coffre verrouillé : `list`, `search` et `sync` demandent le mot de passe, puis
  gardent la session (900 s).
- Déconnexion : pas encore de commande `logout`. En attendant :
  `sshvault lock && BITWARDENCLI_APPDATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/sshvault/bw" bw logout`.

### Hôtes d'une clé

Champ personnalisé `sshvault-hosts` de l'élément, texte ou masqué : liste
d'hôtes séparés par des virgules (`prod.example.org, *.lab`). Les espaces autour
sont ignorés et la comparaison est insensible à la casse. Le nom de l'élément
reste libre.

### Codes de sortie

| Code | Sens |
|---|---|
| 0 | succès |
| 1 | `search` : aucun résultat |
| 2 | usage (option ou argument invalide) |
| 3 | non connecté (« lancer sshvault login »), ou coffre verrouillé : aucune invite possible, invite annulée ou sans réponse, mot de passe refusé |
| 4 | erreur du backend : `bw` introuvable, en erreur, réponse illisible, délai dépassé ; magasin de session inutilisable ; erreur interne |
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
| `XDG_RUNTIME_DIR` | repli fichier de la session (tmpfs privé exigé) |
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
  `list`, `search`, `sync`, une session invalidée et `lock`. `register.py` (mode
  conteneur) se lance seul par `SSHVAULT_IT_PASSWORD=… python register.py <url> <e-mail>`.

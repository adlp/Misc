# sshvault

Clés SSH dans un Vaultwarden auto-hébergé, utilisées de façon transparente par ssh.

État (0.4.0) : **lecture** du coffre via le CLI officiel `bw` (lister et chercher les
éléments « SSH key »), **agent dédié** (chargement d'une clé du coffre dans un
`ssh-agent` d'OpenSSH propre à sshvault, sans écriture disque, avec durée de vie,
confirmation et restriction aux hôtes en option ; état, purge, verrou et arrêt de l'agent),
**hôtes d'une clé** modifiables depuis la CLI, **`ssh_config` généré** (chaque hôte
associé reçoit l'agent dédié et sa seule clé) et **chargement automatique** : `ssh <hôte>`
charge seul la clé manquante, pour la cible comme pour chaque saut ProxyJump/ProxyCommand,
avec au plus une invite de déverrouillage du coffre. L'import et la génération de clés
viendront ensuite.

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
   La commande est installée dans `~/.local/bin/sshvault`. Le `ssh_config` généré appelle
   ce chemin absolu (chargement automatique) : après une réinstallation ailleurs, relancer
   `sshvault ssh-config`. Mise à jour depuis la 0.3.0 : `uv tool install --force ./Ssh`
   (nouveau point d'entrée), puis `sshvault ssh-config`.

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
sshvault config get [CLÉ] | set CLÉ VALEUR | unset CLÉ   # key-ttl, auto-load, auto-restrict, auto-confirm

sshvault hosts add | remove | set  SÉLECTION [--host | --name | --fingerprint | --id] HÔTE…
sshvault hosts list SÉLECTION [--host | --name | --fingerprint | --id]
sshvault ssh-config [--print | --check]
sshvault ssh-config install

sshvault ensure --id ID          # appelé par ssh (ligne Match exec du ssh_config généré)
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
- Coffre verrouillé : `list`, `search`, `sync`, `load`, `hosts` et `ssh-config` (sauf
  `install`, qui ne lit pas le coffre) demandent le mot de passe, puis
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
  `config unset key-ttl` revient à 1 h. Clés du chargement automatique (voir plus bas) :
  `auto-load` (défaut `true`), `auto-restrict` et `auto-confirm` (défaut `false`), valeurs
  `true`/`false` (aussi `yes`/`no`, `on`/`off`, `1`/`0`). Durée, booléen ou fichier
  invalide (JSON, valeur, droits autres que 0600, propriétaire) : code 2 ; écriture
  impossible : code 4.

### Hôtes d'une clé

Champ personnalisé `sshvault-hosts` de l'élément, texte ou masqué : liste
d'hôtes séparés par des virgules (`prod.example.org, *.lab`). Les espaces autour
sont ignorés et la comparaison est insensible à la casse. Le nom de l'élément
reste libre. Il se modifie dans l'interface web ou par `sshvault hosts` :

```
sshvault hosts add  --id 1111… prod.example.org '*.lab'    # crée ou complète le champ
sshvault hosts remove 'Serveur Prod' prod.example.org      # champ retiré s'il devient vide
sshvault hosts set  --id 1111… a.example,b.example         # remplace la liste ; "" la vide
sshvault hosts list --id 1111…                             # un hôte par ligne
```

- La sélection désigne **un seul** élément, comme pour `load` (motif seul : nom, hôte
  ou empreinte ; ou `--host`, `--name`, `--fingerprint`, `--id`). Plusieurs : code 2
  (« préciser --id ») ; aucun : code 1.
- Hôte accepté : motif de ligne `Host` d'OpenSSH fait de lettres, chiffres, `.`, `-`, `_`,
  `*`, `?` ; écrit en minuscules, sans doublon. Tout autre caractère (espace, `!`, `%`,
  `"`, `@`, `:`, `/`, accent, contrôle…) : code 2, rien écrit. Une liste du coffre qui
  contient déjà un hôte invalide n'est réécrite qu'une fois cet hôte retiré (`remove`) ou
  la liste remplacée (`set`). `remove` d'un hôte absent : code 1, rien écrit.
- Écriture : `bw sync` d'abord (une modification faite dans l'interface web est vue),
  puis `bw get item`, seul le champ `sshvault-hosts` changé (créé, complété ou
  retiré ; autres champs, notes, clé et `revisionDate` gardés tels que `bw` les rend),
  puis `bw edit item <id>` avec l'élément encodé **sur stdin**, jamais en argument (argv
  est lisible par `ps`, l'élément contient la clé privée), puis relecture. `edit` passe
  par le réseau : s'il échoue ou reste bloqué (`SSHVAULT_BW_TIMEOUT`), sshvault relit
  l'état du serveur (`sync`, puis `get`) avant toute décision : écriture passée → succès ;
  élément inchangé → rejouée **une** fois ; élément modifié entre-temps (par exemple par
  l'interface web : « The client copy of this cipher is out of date ») → rien rejoué.
  Échec final : code 4, avec les hôtes relus ou « état inconnu » si la relecture échoue.
  Interrompue (Ctrl-C, SIGTERM) pendant l'écriture : code 130 et « écriture peut-être
  passée : vérifier par sshvault sync puis sshvault hosts list --id … ».
- Durée au pire d'une écriture (`SSHVAULT_BW_TIMEOUT`, 60 s par défaut, noté T) : cinq
  appels réseau (sync initial, deux `edit`, deux relectures `sync`), soit 5 × T, plus les
  lectures locales (`list`, jusqu'à trois `get`), un T chacune au plus ; s'y ajoute le
  déverrouillage si le coffre est verrouillé.
- Avant d'écrire, sshvault vérifie qu'il pourra régénérer le `ssh_config` (socket de
  l'agent, chemins) : sinon code 4 et rien écrit. Si la régénération échoue malgré tout
  après l'écriture : code 4, « hôtes écrits dans le coffre, mais ssh_config non régénéré ».
- Après une modification, le `ssh_config` généré est mis à jour. Si la clé est chargée
  dans l'agent avec `--restrict`, ses contraintes gardent les anciens hôtes : sshvault le
  signale (relancer `sshvault load --force --restrict --id …`).
- Motif sans partie littérale (`*`, `*.*`, `?*`) : accepté, avec l'avertissement « ce bloc
  prend toutes les connexions ssh et désactive ton agent habituel » (à l'écriture et à
  chaque génération).

### `ssh_config` généré

`sshvault ssh-config` lit le **cache local** de `bw` (lancer `sshvault sync` d'abord pour
voir une modification faite ailleurs) et écrit `~/.ssh/sshvault/config` (0600, dossier
0700, en-tête « ne pas éditer ») et `~/.ssh/sshvault/pub/<empreinte en base64url>.pub` (0600). Un bloc par
élément qui a des hôtes, triés par nom puis par id :

```
# Serveur Prod 11111111-1111-4111-8111-111111111111
Match originalhost prod.example.org,*.lab exec "'/home/alice/.local/bin/sshvault' ensure --id 11111111-1111-4111-8111-111111111111"
Match originalhost prod.example.org,*.lab
    IdentityAgent "/run/user/1000/sshvault/agent.sock"
    IdentityFile "/home/alice/.ssh/sshvault/pub/SHA256:70bMgv5m…_OjUbIQdVk.pub"
    IdentitiesOnly yes
```

- `IdentityAgent` est le chemin **résolu** du socket de l'agent dédié (sans
  `${XDG_RUNTIME_DIR}` : la config reste valable si la variable manque, par exemple sous
  `su` ou cron). Chemins absolus entre guillemets, `%` doublé en `%%` ; un chemin avec
  `"`, `\`, `${` ou un caractère de contrôle est refusé (code 4).
- `Match originalhost` compare le nom **tapé** (`ssh Prod.Example.ORG`, alias d'un
  `ProxyJump`), sans tenir compte de la casse, motifs glob compris ; pas le `HostName` : un
  bloc `Host prod.example.org` + `HostName 10.0.0.5` de votre config reçoit bien la clé,
  `ssh 10.0.0.5` non. (Mesuré sur OpenSSH 8.9p1 : une ligne `Host foo` ne s'applique pas
  à `ssh FOO`, d'où cette forme.)
- La ligne `Match … exec` (sans directive) charge la clé à la connexion : voir
  « Chargement automatique ». `config set auto-load false` la retire (forme de la 0.3.0).
- Jamais de `HostName`, `User`, `Port`, `ProxyJump` ni `ProxyCommand` : la topologie reste
  dans votre `~/.ssh/config`.
- Rien n'est réécrit si le contenu est identique (mtime inchangée) ; `pub/` ne garde que
  les clés des éléments associés (sshvault est le seul à y écrire). Aucune clé privée.
- `~` désigne le répertoire de passwd (là où ssh lit `~/.ssh/config`), pas `$HOME` ;
  inconnu ou `/` : code 4.
- Élément avec un hôte invalide (saisi dans l'interface web) ou une clé publique
  illisible : sauté, avec un avertissement ; le reste est généré. Hôte porté par deux
  éléments, ou motifs qui se recouvrent (`*.lab` et `x.lab`) : un bloc chacun, ssh offre
  les deux clés dans l'ordre des blocs ; avertissement.
- Verrou (`flock` sur `~/.ssh/sshvault/`) : deux régénérations simultanées ne se gênent
  pas. Un fichier non ordinaire (FIFO, dossier) à la place d'un fichier généré : code 4.
- `--print` affiche le fichier sans rien écrire ; `--check` n'écrit rien et sort en 0 si
  tout est à jour et la ligne `Include` en tête, 1 sinon. Différences sur stdout : contenu,
  fichier absent, en trop ou non ordinaire, droits autres que 0600 (fichiers) ou 0700
  (dossiers), `pub/` qui n'est pas un dossier ou illisible. Un sous-dossier de `pub/` est
  signalé (stderr) et laissé en place, comme par `ssh-config`.
- Première valeur rencontrée : `IdentityAgent` et `IdentitiesOnly` de sshvault
  l'emportent sur vos défauts (`Host *`) placés après la ligne `Include`. `IdentityFile`,
  lui, se **cumule** : un `IdentityFile` de votre config qui vise aussi cet hôte s'ajoute
  après la clé de sshvault (mesuré) ; pour n'offrir qu'une clé, ne pas en mettre pour les
  hôtes gérés par sshvault.

**ForwardAgent : attention.** Le bloc généré n'écrit pas `ForwardAgent` : votre
config décide. Mais avec `ForwardAgent yes` sur un hôte géré par sshvault, c'est
**l'agent dédié entier** (toutes les clés chargées par sshvault, pas seulement celle de
cet hôte) qui est transféré, et non votre agent habituel : `IdentityAgent` remplace
`SSH_AUTH_SOCK` pour la connexion (mesuré sur OpenSSH 8.9p1 avec un sshd de test :
`ssh-add -L` sur l'hôte distant liste les clés de l'agent dédié). Un root distant peut
s'en servir tant que la session est ouverte. Le transfert restreint par hôte viendra avec
la story 8 ; d'ici là, éviter `ForwardAgent yes` vers ces hôtes.

**Clé absente de l'agent dédié.** Le bloc n'offre que la clé de l'agent dédié
(`IdentitiesOnly yes`) : si elle n'y est pas (chargement automatique désactivé ou en
échec), ssh affiche `Load key "…/pub/SHA256:….pub": error in libcrypto` puis
`Permission denied (publickey)`. La ligne `sshvault: …` qui précède dit pourquoi ;
`sshvault load <hôte>` la charge à la main.

### Chargement automatique (`Match exec`)

Avec la config générée incluse, `ssh <hôte>` charge seul la clé de l'hôte si elle manque
dans l'agent dédié, pour la cible **et** pour chaque saut `ProxyJump`/`ProxyCommand ssh -W`
(le ssh du saut relit la config). Aucune commande préalable ; au plus une invite de
déverrouillage du coffre par connexion.

- **Comment.** Avant chaque bloc, `Match originalhost <motifs> exec "'<sshvault>' ensure
  --id <id>"` : ssh n'exécute la commande que si le nom tapé correspond, avant
  l'authentification, puis applique le bloc. La ligne ne porte aucune directive : son code
  de sortie ne change rien. Mesuré (OpenSSH 8.9p1) : un appel par saut, la cible d'abord
  puis le saut, chacun fini avant l'authentification de son saut.
- **Commande sûre.** La commande passe par le shell de l'utilisateur : elle ne contient
  que le chemin absolu de sshvault entre apostrophes (refusé s'il contient `'`, `"`, `\`,
  `${` ou un caractère de contrôle ; `%` doublé) et l'id de l'élément, un UUID vérifié.
  Jamais `%h` ni `%n` : avec un motif `*.lab`, un nom tapé contenant des métacaractères du
  shell y passerait. (Élément dont l'id n'est pas un UUID : pas de ligne, avertissement.)
- **Clé déjà là** (enregistrée par sshvault pour cet élément, ou pour un autre élément de
  même clé ; égale au `.pub` de l'élément dans la config générée ; restant plus de
  min(60 s, durée/2)) : `ensure` répond sans `bw` ni réseau, sans rien afficher. Mesuré sur
  trois séries de 20 appels : médiane 27 à 30 ms, max 31 à 43 ms, démarrage de Python compris
  (`ssh -G`, `ssh -O` et ce cas ne chargent pas la CLI). Au-dessous du seuil, la clé est
  rechargée ; clé changée dans le coffre (puis `ssh-config`) : la nouvelle est chargée.
- **Clé absente** : sous un verrou par utilisateur (`$XDG_RUNTIME_DIR/sshvault/ensure.lock`),
  état relu, agent vérifié **avant le coffre** (démarré s'il le faut, OpenSSH ≥ 8.9 ;
  verrouillé → code 3, une ligne, ni invite ni `bw`), puis comme `load` : un `bw get item`
  (cache local, ~1,4 s pour le vrai `bw`), `ssh-add -t <key-ttl> -` (clé par stdin), tout
  ou rien (une clé privée qui ne correspond pas est retirée, même si une ancienne copie
  est là), état enregistré. Mesuré avec un faux `bw` à 1,4 s par appel : `ssh B` derrière
  le rebond A, agent vide, 3,3 s (deux `bw`). Deux ssh lancés ensemble : une invite, un
  `ssh-add` par clé.
- **Options** : durée `key-ttl`, sans `-c` ni `-h`. `config set auto-restrict true` ajoute
  `ssh-add -h` (hôtes de l'élément, littéraux, dans `known_hosts` ; sinon une ligne
  d'erreur, rien chargé) ; `config set auto-confirm true` ajoute `-c` (confirmation par
  l'askpass de l'agent ; agent lancé sans askpass utilisable : une ligne d'erreur, rien
  chargé). Une clé rechargée garde les `-c`/`-h` qu'elle avait.
- **Coffre verrouillé** : invite sur le terminal si ssh est **au premier plan**
  (`tcgetpgrp == getpgrp`), jamais sur stdin (`/dev/null` sous `Match exec`) ; sinon
  (`ssh … &`, pas de terminal) l'askpass selon les règles de `man ssh` (`SSH_ASKPASS`
  exécutable, `DISPLAY`, `SSH_ASKPASS_REQUIRE`) ; sinon échec immédiat, sans appel à
  `bw`. Aucune invite sous `sshvault --nointeraction ensure` ni si un ssh de la chaîne a
  `-o BatchMode=yes` en argument (pas dans un fichier de config). Jamais d'arrêt par
  SIGTTIN. L'invite dit ce qui la déclenche (« clé pour <hôte> »). La session obtenue sert
  aux sauts suivants ; **sans magasin de session utilisable** (ni keyring, ni
  `XDG_RUNTIME_DIR` privé : avertissement « session non rangée »), chaque saut redemande.
- **Mauvais mot de passe** (refusé par `bw`, ou invite annulée ou sans réponse) : une ligne,
  et l'échec est mémorisé 30 s pour **cette connexion** (`$XDG_RUNTIME_DIR/sshvault/unlock-failed`
  : horodatage, pid et date de démarrage du ssh tapé) : les sauts suivants échouent
  aussitôt, sans invite ni `bw`, et ssh finit en `Permission denied`. Une autre connexion
  redemande. Une invite impossible n'est pas mémorisée. `sshvault unlock` ou un
  déverrouillage réussi efface la mémoire.
- **`ssh -G`, `ssh -O`** : ssh exécute aussi les `Match exec` ; `ensure` reconnaît l'option
  sur le ssh qui l'a lancé (premier `ssh` parmi ses ancêtres, lus dans `/proc`, à travers le
  shell de `$SHELL -c`) et sort aussitôt, code 0, sans rien demander ni charger.
- **Échec** : une seule ligne `sshvault: <hôte> : <cause>` sur stderr (hôte tapé, ou id de
  l'élément si le ssh appelant n'est pas trouvé), puis ssh continue et échoue proprement.
  Rien en cas de succès, sauf les avertissements du backend (une ligne chacun). Délais
  bornés : invite `SSHVAULT_PROMPT_TIMEOUT` (réduite au temps restant), `bw`
  `SSHVAULT_BW_TIMEOUT`, tout l'appel depuis son démarrage (chemin rapide et attente du
  verrou compris) `SSHVAULT_ENSURE_TIMEOUT` (240 s ; 0 < v ≤ 86400, sinon code 2). Ctrl-C,
  SIGTERM, SIGHUP : terminal rétabli, sous-processus tués, « interrompu » ; un délai ou un
  signal arrivé une fois la clé chargée ne change plus rien.
- **Chemin de sshvault** : celui de la commande qui génère la config si elle s'appelle
  `sshvault`, sinon le premier `sshvault` du PATH (dossiers absolus) qui répond
  `--version` ≥ 0.4.0. Avertissement s'il diffère de celui de la config existante, ou s'il
  est dans un environnement de projet (`.venv`).
- **Limites.** La commande suppose un shell à guillemets POSIX (apostrophes littérales) :
  testé avec bash et dash (`/bin/sh`) ; zsh et fish le sont s'ils sont installés (absents du
  poste de test). Une clé chiffrée par passphrase demande sa passphrase (terminal au
  premier plan ou askpass), sinon une ligne d'erreur. Clé changée dans le coffre sans
  `ssh-config` : l'ancienne reste offerte. Le chemin de sshvault est figé dans la config
  générée.

**Inclusion.** ssh ne lit le fichier que si `~/.ssh/config` l'inclut **en tête** (pour
chaque paramètre, la première valeur rencontrée l'emporte). « En tête » : avant la
première ligne qui n'est ni vide ni un commentaire (lignes coupées sur le seul saut de
ligne, comme ssh). `sshvault ssh-config install` insère
`Include "<répertoire personnel>/.ssh/sshvault/config"` en première ligne (vos
commentaires d'en-tête restent dessous, inchangés) :

- idempotent (ligne déjà en tête, sous toute forme : chemin réel, `~`, `~user`, relatif à
  `~/.ssh`, joker, parmi plusieurs fichiers : rien fait) ; une ligne `Include` de sshvault
  placée plus bas est déplacée en tête (une ligne qui inclut aussi d'autres fichiers est
  gardée telle quelle : ssh ignore le doublon) ;
- une ligne `Include` de sshvault **dans** un bloc `Host`/`Match` (Include conditionnel)
  n'est pas déplacée : code 4, rien modifié ; `ssh-config` et `--check` la signalent ;
- sauvegarde avant toute écriture, jamais écrasée : `~/.ssh/config.sshvault.bak`, sinon
  `.bak.1`, `.bak.2`… (0600) ; écriture atomique, mode et propriétaire conservés ; fichier
  absent : créé en 0600 (et `~/.ssh` en 0700 s'il manque), sans écraser un fichier créé
  entre-temps ;
- `~/.ssh/config` lien symbolique ou non ordinaire (FIFO, dossier) : code 4, rien
  modifié ; chemin personnel avec `%`, `$` ou un joker de glob : code 4 (`Include`
  développe les tokens dans les versions récentes d'OpenSSH, pas en 8.9).

Jamais automatique : `ssh-config` et `hosts` préviennent seulement (stderr) si la ligne
manque, est conditionnelle ou n'est pas en tête.

**Désinstaller.** Retirer la ligne `Include "…/.ssh/sshvault/config"` de `~/.ssh/config`
(ou remettre une sauvegarde `~/.ssh/config.sshvault.bak*`), puis supprimer
`~/.ssh/sshvault/` (`rm -r ~/.ssh/sshvault`) ; `sshvault agent stop` arrête l'agent dédié.

### Codes de sortie

| Code | Sens |
|---|---|
| 0 | succès |
| 1 | `search`, `load`, `hosts` : aucun résultat ; `hosts remove` : hôte absent (rien écrit) ; `ssh-config --check` : pas à jour (contenu, droits, fichier en trop ou non ordinaire), ou ligne `Include` absente, conditionnelle ou pas en tête |
| 2 | usage (option ou argument invalide ; `load` sans sélection ni `--all`) ; durée invalide ; `config.json` invalide, illisible ou aux droits inattendus ; hôte invalide ; sélection de `hosts` qui désigne plusieurs éléments |
| 3 | non connecté (« lancer sshvault login »), ou coffre verrouillé : aucune invite possible, invite annulée ou sans réponse, mot de passe refusé ; agent dédié arrêté (`agent status`, `lock`, `unlock`) ou verrouillé ; passphrase d'une clé refusée ou impossible à saisir |
| 4 | erreur du backend : `bw` introuvable, en erreur, réponse illisible, délai dépassé ; magasin de session inutilisable ; agent dédié : `XDG_RUNTIME_DIR` relatif, non privé ou hors tmpfs, chemin du socket trop long, agent tiers sur le socket, OpenSSH < 8.9, `--restrict` (élément sans hôte, hôte non littéral ou absent de `known_hosts`), clé publique illisible ou différente de la clé privée, `ssh-add`/`ssh-agent` en erreur ; écriture de `config.json` impossible ; écriture des hôtes dans le coffre non aboutie ou non vérifiée (y compris hôtes écrits mais `ssh_config` non régénéré) ; `ssh_config` généré impossible à écrire (chemin avec `"`, `\`, `${`, fichier non ordinaire, droits) ; répertoire personnel inconnu ; `ssh-config install` refusé (lien symbolique, fichier non ordinaire, `Include` conditionnel, chemin personnel avec `%`, `$` ou joker) ; erreur interne |
| 130 | interrompu (Ctrl-C, SIGTERM, SIGHUP) |

`ensure` : 0 si la clé est présente ou chargée, et pour `ssh -G` ; sinon le code de
l'erreur (3 coffre verrouillé ou agent verrouillé, 4 backend, agent, délai global…), sans
effet sur ssh.

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
  de `bw` (aucune connexion) ; seuls `sync`, `login` et l'écriture de `hosts`
  (`bw edit`, jamais relancé à l'aveugle : voir Hôtes d'une clé) passent par le réseau. Une
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
- **Invite** : `/dev/tty` (pas stdin) si le processus est au premier plan du terminal,
  ou le programme `SSH_ASKPASS`, selon les règles de `man ssh` pour
  `SSH_ASKPASS_REQUIRE` (`never`, `prefer`, `force`) et `DISPLAY`/`WAYLAND_DISPLAY`.
  Délai `SSHVAULT_PROMPT_TIMEOUT` (60 s par défaut).
- Fichiers créés en 0600, dossiers en 0700.

### Variables

| Variable | Rôle |
|---|---|
| `SSHVAULT_BW` | exécutable `bw` (défaut : `bw` du PATH) |
| `SSHVAULT_BW_TIMEOUT` | délai d'un appel `bw`, en secondes, 0 < v ≤ 86400 (défaut 60 ; `login` : 600) |
| `SSHVAULT_PROMPT_TIMEOUT` | délai d'une invite, en secondes, 0 < v ≤ 86400 (défaut 60) |
| `SSHVAULT_ENSURE_TIMEOUT` | délai global d'un `ensure` depuis son démarrage, attente du verrou comprise, en secondes, 0 < v ≤ 86400 (défaut 240) |
| `SSHVAULT_KEYRING`, `SSHVAULT_KEYCTL` | anneau et exécutable `keyctl` (tests ; défaut `@u`, `keyctl`) |
| `XDG_DATA_HOME` | base du dossier de données de `bw` (défaut `~/.local/share`) |
| `XDG_RUNTIME_DIR` | repli fichier de la session ; socket et état de l'agent dédié (tmpfs privé exigé) |
| `XDG_CONFIG_HOME` | base de `sshvault/config.json` (défaut `~/.config`) |
| `SSHVAULT_SSH_HOME` | tests seulement : répertoire personnel de `~/.ssh` (défaut : celui de passwd) |
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
- `tests/test_sshconfig.py` valide le fichier généré avec l'OpenSSH du poste :
  `ssh -G -F <config de test qui l'inclut>` (agent dédié, une seule `identityfile`,
  `identitiesonly yes`, HOME et `XDG_RUNTIME_DIR` avec espace et `%`), puis `ssh -vvv`
  arrêté avant l'authentification (`ProxyCommand true`) pour voir le `.pub` réellement
  chargé. Le faux `bw` sait faire `edit` (élément lu sur stdin, argv journalisé) et
  simuler un `edit` en échec, bloqué, passé puis bloqué, ou en concurrence.
- `tests/test_ensure.py` (chargement automatique) : vrais `ssh` contre deux sshd de test
  (A, le rebond, et B, la cible, sur 127.0.0.1, chacun n'acceptant que sa clé), en
  `ProxyJump` et en `ProxyCommand ssh -W`, vrais `ssh-agent`/`ssh-add`, faux `bw` (avec un
  délai de 1,4 s par appel pour mesurer le chargement), vrai terminal par pty (premier
  plan, arrière-plan, deux ssh simultanés, Ctrl-C). La commande `sshvault` des lignes
  `Match exec` y est une enveloppe de `python -m sshvault` du dépôt, inerte hors du banc.
  La latence du chemin rapide est mesurée (médiane et maximum de 20 appels).
- En fin de session, les tests vérifient qu'aucun de leurs processus ne reste (agent,
  surveillant, sshd, `bw`, askpass, `ensure`), que `~/.ssh` réel est inchangé et
  qu'aucun dossier sshvault réel (socket, données, config) n'a été créé.
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
  `purge` et `stop`, `hosts add`/`remove` sur les deux éléments de test (lignes de commande
  de tous les processus relevées dans `/proc` pendant l'appel : ni JSON ni clé privée ;
  relecture par un autre client `bw` après `sync` : autres champs et clé privée
  identiques), `ssh-config` dans le HOME de test (validé par `ssh -G`), une session
  invalidée et `lock` ; enfin `ssh` vers un sshd local qui n'accepte que la clé de test,
  agent dédié vide, coffre déverrouillé : la connexion passe par `ensure` et le vrai `bw`.
  `register.py` (mode
  conteneur) se lance seul par `SSHVAULT_IT_PASSWORD=… python register.py <url> <e-mail>`.

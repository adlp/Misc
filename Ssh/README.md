# sshvault

Clés SSH dans un Vaultwarden auto-hébergé, utilisées de façon transparente par ssh.

État (0.10.0) : **plusieurs comptes** Vaultwarden utilisés en même temps (alias → serveur
+ e-mail, sur un même serveur ou sur des serveurs différents ; déconnexion par `sshvault
logout`, serveur ou e-mail corrigé par `sshvault account set` ; voir « Comptes du coffre »),
**lecture** du coffre via le CLI officiel `bw` (lister et chercher les
éléments « SSH key »), **agent dédié** (chargement d'une clé du coffre dans un
`ssh-agent` d'OpenSSH propre à sshvault, sans écriture disque, avec durée de vie,
confirmation et restriction aux hôtes en option ; état, purge, verrou et arrêt de l'agent),
**hôtes d'une clé** modifiables depuis la CLI, **`ssh_config` généré** (chaque hôte
associé reçoit l'agent dédié et sa seule clé) et **chargement automatique** : `ssh <hôte>`
charge seul la clé manquante, pour la cible comme pour chaque saut ProxyJump/ProxyCommand,
avec au plus une invite de déverrouillage par compte concerné, **import** d'une clé existante dans
le coffre (`sshvault import`) et **génération** d'une clé directement dans le coffre
(`sshvault generate`, clé privée jamais écrite sur disque par sshvault, voir les limites), avec affichage
(`sshvault pubkey`) et **déploiement** de la clé publique dans `authorized_keys` d'une
cible (`sshvault deploy`), et **transfert d'agent restreint** : vers un hôte déclaré
(`sshvault forward`), seul un sous-agent qui ne contient que les clés autorisées pour cet
hôte est transféré, jamais l'agent dédié entier. `bw` est pris au chemin absolu du réglage
`bw-path` s'il est posé, sinon dans le PATH.

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
2. sshvault (Python ≥ 3.10, bibliothèque standard seule) :
   ```
   uv tool install ./Ssh        # depuis la racine de Misc ; --force pour réinstaller
   sshvault --help
   ```
   La commande est installée dans `~/.local/bin/sshvault`. Le `ssh_config` généré appelle
   ce chemin absolu (chargement automatique) : après une réinstallation ailleurs, relancer
   `sshvault ssh-config`. Mise à jour depuis la 0.3.0 : `uv tool install --force ./Ssh`
   (nouveau point d'entrée), puis `sshvault ssh-config`.
3. Chemin de `bw`. sshvault prend `bw` dans le PATH. Les lignes `Match exec` du
   `ssh_config` généré héritent du PATH du ssh appelant (session graphique, cron…), qui peut
   ne pas contenir `~/.local/bin` : le chargement automatique échoue alors (« bw
   introuvable »). Donner le chemin absolu une fois pour toutes :
   ```
   sshvault config set bw-path ~/.local/bin/bw
   sshvault status          # ligne « bw : /home/alice/.local/bin/bw (réglage bw-path) »
   ```
   Le réglage est lu dans `${XDG_CONFIG_HOME:-~/.config}/sshvault/config.json` de
   l'environnement où tourne ssh : si ssh (donc `Match exec`) voit un autre
   `XDG_CONFIG_HOME` que votre terminal, il ne voit pas ce réglage. `sshvault config unset
   bw-path` revient au PATH. `SSHVAULT_BW` (tests) reste prioritaire. Si le fichier, un
   dossier de la chaîne de liens ou un de leurs parents est modifiable par d'autres
   (`~/.local/bin` ouvert au groupe, par exemple), le réglage est accepté avec un
   avertissement (voir « Config ») : `bw` reçoit le mot de passe maître et la session.
   Le réglage est commun à tous les comptes.
4. Comptes du coffre : `sshvault account add perso --server https://vault.example.org
   --email alice@example.org`, puis `sshvault login` (voir « Comptes du coffre »).
   Mise à jour depuis la 0.8.0 : l'installation est adoptée au premier lancement ; un
   déverrouillage est à refaire, puis `sshvault ssh-config`. Voir « Changements
   incompatibles (0.9.0) » ci-dessous pour les scripts.

### Changements incompatibles (0.9.0)

- `sshvault login --server URL` n'existe plus : le serveur vient du compte
  (`sshvault account add ALIAS --server URL --email E`, puis `sshvault login`) ; `login`
  passe l'e-mail du compte à `bw`, qui ne demande plus que le mot de passe ; avec plusieurs
  comptes, `--account` est obligatoire.
- `list` et `search` en texte ont une colonne de plus, en tête : l'alias du compte
  (`alias⇥nom⇥empreinte⇥hôtes`) ; `--json` a une clé `account`. `agent status` aussi (alias
  en tête, `?` pour une clé chargée avant la 0.9.0), sous-agents de transfert compris.
- `status` affiche un groupe de lignes par compte, chacun ouvert par `alias : <alias>`
  (`(défaut)` pour un compte par défaut), séparés par une ligne vide ; sans compte :
  `comptes : aucun`, code 3. `lock` sans compte : code 3.
- Données et session par compte : `…/sshvault/accounts/<alias>/bw`, clé keyring
  `sshvault:session:<alias>`, repli `$XDG_RUNTIME_DIR/sshvault/sessions/<alias>`, mémoire
  d'échec `unlock-failed.<alias>`.
- `ssh_config` généré : commentaires `# <nom> <alias> <id>`, lignes `ensure --account
  <alias> --id <id>` et `ensure --forward <fid> --id <alias>:<id>`.
- État des agents (`agent.json`, `fwd/<fid>.json`) : champ `account`, références `also` en
  `<alias>:<id>`.
- Invite du coffre : `sshvault : mot de passe maître du coffre « <alias> » (<e-mail>) : `
  (`(<e-mail>)` absent quand bw l'a déjà dit connecté, session refusée) ; sous `ssh`, la fin
  devient `…, clé pour <hôte> : ` (sans e-mail : `… « <alias> », clé pour <hôte> : `).

## Utilisation

```
sshvault account add ALIAS --server URL --email E   # enregistre un compte (le premier : compte par défaut)
sshvault account list | remove ALIAS | default ALIAS… | rename ANCIEN NOUVEAU
sshvault account set ALIAS [--server URL] [--email E]   # corrige le compte (déconnecté, sauf registre seul faux)
sshvault login [--account ALIAS] [--apikey]         # interactif (bw login <e-mail du compte>)
sshvault logout [--account ALIAS]                   # bw logout, session oubliée, clés retirées des agents
sshvault unlock [--account ALIAS]… [--ttl 900]       # une invite par compte
sshvault list [--account ALIAS]… [--json]
sshvault search MOTIF [--host | --name | --fingerprint] [--account ALIAS]… [--json]
sshvault sync [--account ALIAS]…
sshvault status [--account ALIAS]…                   # défaut : tous les comptes
sshvault lock [--account ALIAS]…                     # défaut : tous les comptes

sshvault load (MOTIF [--host | --name | --fingerprint | --id] | --all) [-t DURÉE] [--confirm] [--restrict] [--force]
sshvault agent status | purge | lock | unlock | stop
sshvault config get [CLÉ] | set CLÉ VALEUR | unset CLÉ   # key-ttl, auto-load, auto-restrict, auto-confirm, forward-confirm, bw-path

sshvault hosts add | remove | set  SÉLECTION [--host | --name | --fingerprint | --id] HÔTE…
sshvault hosts list SÉLECTION [--host | --name | --fingerprint | --id]
sshvault forward add | remove | set  SÉLECTION [--host | --name | --fingerprint | --id] HÔTE…
sshvault forward list SÉLECTION [--host | --name | --fingerprint | --id]
sshvault ssh-config [--print | --check]
sshvault ssh-config install

sshvault import FICHIER… [--name NOM] [--hosts HÔTE,…] [--force] [--decrypt]
sshvault generate --name NOM [--type ed25519 | --type rsa [--bits 3072|4096]] [--comment TEXTE] [--hosts HÔTE,…] [--force]
sshvault pubkey (SÉLECTION [--host | --name | --fingerprint | --id] | --all)
sshvault deploy SÉLECTION [--host | --name | --fingerprint | --id] [UTILISATEUR@]HÔTE [-p PORT] [-- OPTIONS_SSH…]

sshvault ensure --account ALIAS --id ID          # appelé par ssh (ligne Match exec du ssh_config généré)
sshvault ensure --forward FID --id ALIAS:ID…     # idem, sous-agent de transfert
```

`load`, `hosts`, `forward`, `import`, `generate`, `pubkey` et `deploy` prennent aussi
`--account ALIAS` (voir « Comptes du coffre »).

- `list` affiche, pour chaque élément « SSH key » (type 5) : alias du compte (toujours en
  première colonne), nom, empreinte, hôtes, séparés par une tabulation. `--json` ajoute le
  compte (`account`), l'id et la clé publique. Une clé privée n'est jamais affichée.
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
- Coffre verrouillé : `list`, `search`, `sync`, `load`, `hosts`, `forward`, `import`, `generate`, `pubkey`,
  `deploy` et `ssh-config` (sauf
  `install`, qui ne lit pas le coffre) demandent le mot de passe, puis
  gardent la session (900 s).
- Déconnexion : `sshvault logout [--account ALIAS]` (compte gardé, voir « Comptes du
  coffre »), ou `sshvault account remove ALIAS` (oublie aussi le compte).

### Comptes du coffre

Plusieurs comptes Vaultwarden, sur un même serveur (e-mails différents) ou sur des serveurs
différents, servent en même temps. Chaque compte est désigné par un **alias** choisi par
l'utilisateur (`[a-z0-9][a-z0-9_-]{0,31}`, unique), associé à son serveur et son e-mail
(couple unique, serveur normalisé : schéma et hôte en minuscules, sans `/` final ; e-mail en
minuscules). Le registre est dans `config.json` (clés `accounts` et `default-accounts`),
modifié seulement par `sshvault account …` (pas par `config set`).

```
sshvault account add perso --server https://vault.example.org --email alice@example.org
sshvault account add boulot --server https://vault.example.org --email alice@boulot.example
sshvault account add client --server https://vault.client.example --email alice@client.example
sshvault login --account perso          # puis boulot, client : bw demande le mot de passe
sshvault ssh-config                     # 1re fois ; ensuite, login régénère la config existante
sshvault account default perso boulot   # comptes par défaut (remplace la liste)
sshvault list                           # perso et boulot
sshvault list --account client          # client seul, quels que soient les défauts
```

- **Par compte** : données de `bw` propres
  (`${XDG_DATA_HOME:-~/.local/share}/sshvault/accounts/<alias>/bw`), session propre (clé
  keyring `sshvault:session:<alias>`, repli `$XDG_RUNTIME_DIR/sshvault/sessions/<alias>`),
  mémoire d'échec de déverrouillage propre. `bw-path` reste commun ; les agents (dédié et
  sous-agents de transfert) et leurs sockets aussi : les clés de tous les comptes y vont.
- **Comptes par défaut** : un ou plusieurs, fixés par `account default` ; le premier
  compte ajouté l'est d'office ; une liste vide avec un seul compte vaut ce compte.
  `--account ALIAS` (plusieurs fois pour une lecture) les remplace pour une commande ; alias
  inconnu : code 2.
- **Lecture** (`list`, `search`, `load`, `pubkey`, `deploy`, `hosts list`, `forward list`,
  `unlock`, `sync`) : comptes par défaut, une invite au plus par compte, qui nomme l'alias.
  Un compte en erreur (verrouillé sans invite possible…) est dit en une ligne
  (`<alias> : …`), les autres sont traités ; code : le pire. Sélection qui désigne des
  éléments de plusieurs comptes : code 2, préciser `--id` et `--account`.
- **Écriture** (`import`, `generate`, `hosts`/`forward add|remove|set`) : un seul compte, le
  compte par défaut s'il est unique, sinon `--account` obligatoire (code 2, une ligne, rien
  écrit).
- **Sans `--account`** : `status` montre tous les comptes, `lock` les verrouille tous,
  `login` exige `--account` dès qu'il y a plusieurs comptes (même s'il n'y a qu'un compte par
  défaut).
- `account add` en `http://` : accepté avec un avertissement (mot de passe maître en clair) ;
  port par défaut (`:443`, `:80`) retiré de l'URL. Refusé (code 2) si `accounts/<alias>/`
  existe déjà, et (code 4) tant qu'une installation 0.8.0 attend son adoption.
- `status` avertit (une ligne) si bw est connecté à un autre e-mail ou un autre serveur que
  ceux du registre, et propose le remède : corriger le registre par un seul `sshvault account
  set ALIAS [--server …] [--email …]` (valeurs lues dans bw, citées pour le shell ; valeur
  de bw invalide : `URL` ou `E` à saisir, puis `login`), sinon reconnecter (`sshvault logout
  --account ALIAS` puis `sshvault login --account ALIAS`). Si bw est connecté au couple d'un
  autre alias, seule la reconnexion est proposée.
- `logout [--account ALIAS]` (`--account` obligatoire dès qu'il y a plusieurs comptes, code
  2 sinon ; un seul compte : visé). `bw-path` invalide : code 2, rien fait, même sans
  données de `bw`. Sous le verrou d'`ensure`, l'état du compte est d'abord lu dans bw
  (`bw status`, sans toucher à la session rangée) ; puis chaque agent (dédié et sous-agents)
  qui porte une clé possible du compte est vérifié lisible et non verrouillé, avant tout `bw
  list` — un agent verrouillé refuse même s'il n'y a qu'une promotion à faire ; puis les
  clés du compte sont retirées (une clé partagée avec un autre compte reste chargée, elle
  passe à l'autre compte ; une clé partie entre-temps compte comme retirée, sauf si l'agent
  ne liste plus rien alors que sa durée de vie n'est pas écoulée : tenu pour verrouillé,
  code 4, entrée gardée ; une clé du compte chargée pendant la commande est laissée, avec un
  avertissement), `bw logout` est lancé s'il est connecté — ou si son état est illisible —,
  et la session est oubliée, aussi quand bw a été déconnecté hors de
  sshvault. Le compte reste au registre et ses blocs restent dans le `ssh_config`
  (`ssh-config --check` les compare tels quels : à jour, même avec un seul compte ; voir
  « `ssh_config` généré »). Rien du tout à faire (non connecté, ni clé chargée, ni état
  d'agent, aucune session à coup sûr) : une ligne, code 0, rien touché (mémoire d'échec de
  déverrouillage comprise). Agent verrouillé ou en erreur : rien modifié, une ligne, code 4 ;
  si une clé a déjà été retirée, la ligne dit l'état partiel (clés retirées, agents mis à
  jour, agent en cours partiellement modifié). `bw logout` en échec : une ligne qui dit que
  les données restent connectées sous l'alias (état inconnu si bw est resté sans réponse et
  que son état ne se relit pas en 10 s, ou si `bw status` et `bw logout` échouent tous deux)
  et ce qui est fait, code 4. « session oubliée » n'est dit que si une session l'a vraiment
  été. `logout` pose un marqueur persistant `logged-out` dans le dossier du compte
  (`${XDG_DATA_HOME:-~/.local/share}/sshvault/accounts/<alias>/logged-out`, fichier
  ordinaire à côté des données de `bw` ; posé aussi quand l'état est inconnu ; il suit
  `account rename` et part avec `account remove`), retiré dès que bw est vu connecté : tout
  `bw status` qui le voit connecté (`status`, `login` même en échec « déjà connecté »,
  `account set`…) et tout déverrouillage réussi, par `unlock` comme par l'invite de `load`,
  `list` ou `ensure`. Un `ensure` sur ce compte, clé absente, échoue alors en une ligne qui
  propose `sshvault login --account ALIAS`, même sans invite possible et après un
  redémarrage ; le chemin rapide la donne sans charger la CLI quand l'agent dédié est connu
  et non verrouillé (sinon la CLI tranche). Un objet qui n'est pas un fichier ordinaire à la
  place du marqueur ne compte pas (avertissement à la pose). Rien n'est modifié dans le
  coffre.
- `account set ALIAS [--server URL] [--email E]` : au moins une option (code 2 sinon) ;
  validé comme `account add` (serveur normalisé, e-mail validé, `http://` averti, couple
  serveur + e-mail unique : code 2). Valeurs identiques aux actuelles : rien fait, code 0.
  Si bw est déjà connecté avec exactement ces serveur et e-mail (seul le registre se
  trompait) : registre corrigé seul, une ligne le dit, même avec un agent verrouillé ; ni
  déconnexion, ni clé ni bloc retiré. État de bw illisible (`bw status` en échec) : rien fait, une ligne, code de
  l'erreur (jamais de registre corrigé à l'aveugle). Sinon, sous le verrou d'`ensure` (état lu dans
  bw sans toucher à la session, puis agents vérifiés avant toute liste du coffre) : clés du compte retirées des agents (comme `logout`),
  `bw logout` si le compte est connecté (marqueur `logged-out` posé),
  session oubliée, registre mis à jour ; puis le `ssh_config` est régénéré **sans les blocs
  de ce compte** (ils visaient l'ancien compte) ; alias et comptes par défaut gardés. Une
  ligne dit de lancer `sshvault login --account ALIAS`, qui connecte au nouveau serveur ou
  e-mail et régénère les blocs. Agent verrouillé ou en erreur, `bw logout` en échec :
  registre inchangé, une ligne, code 4. Registre refusé après la déconnexion (couple pris
  entre-temps, `config.json` illisible ou non écrit) : une ligne qui dit ce qui est déjà fait,
  registre inchangé, code 2 (4 si l'écriture échoue). `bw-path` invalide : code 2, rien
  fait, même sans données de `bw`. Un `serverUrl` nul dans `bw status` vaut le serveur par
  défaut de bw (`https://vault.bitwarden.com`), pour `status` (avertissement et ligne `serveur :`) comme pour `account set`. Ni l'alias (`account rename`) ni le coffre ne changent.
- **ssh_config et chargement automatique** : toujours sur **tous** les comptes. Chaque bloc
  nomme son compte (`# <nom> <alias> <id>`, `ensure --account <alias> --id <id>`,
  `ensure --forward <fid> --id <alias>:<id>…`). À une régénération, un compte verrouillé
  sans invite possible (ou en erreur) **garde ses blocs actuels** tels quels, avec un
  avertissement ; ils ne sont jamais retirés. `ssh-config` demande le mot de passe de chaque
  compte verrouillé ; `hosts`, `forward`, `import` et `generate` lisent les autres comptes
  sans invite. Tous les comptes illisibles : `ssh-config` n'écrit rien (code 3).
- Une connexion qui touche plusieurs comptes (rebond A du compte `perso`, cible B du compte
  `boulot`) : au plus une invite par compte ; un refus sur `perso` ne bloque pas `boulot`.
- Les messages qui suggèrent une commande citent `--account <alias>` dès qu'il y a
  plusieurs comptes.
- `account remove ALIAS` : verrouille le compte (session oubliée), supprime ses données
  locales de `bw`, retire ses clés des agents (dédié et sous-agents), le retire du registre
  et régénère le `ssh_config` (ses blocs disparaissent). Rien n'est modifié dans le coffre.
  Une clé partagée avec un autre compte reste chargée (elle passe à l'autre compte). Agent
  verrouillé ou en erreur : ses clés restent, état gardé, une ligne, code 4. Clés chargées
  avant la 0.9.0 (sans compte) d'un compte verrouillé : laissées, une ligne le dit.
- `account rename ANCIEN NOUVEAU` : données, registre, comptes par défaut, session, état des
  agents et `ssh_config` suivent. La session garde sa durée restante, arrondie vers le bas à
  l'unité qu'affiche le noyau (`/proc/keys` : `59m` pour 59 min 59 s) ; repli fichier : son
  expiration telle quelle. Alias pris : code 2 ;
  destination existante ou déplacement impossible : code 4, rien changé.
- **Installation 0.8.0** (un seul compte, données dans `sshvault/bw`) : adoptée au premier
  lancement de sshvault. Le compte connecté devient un alias déduit de l'e-mail (partie
  avant `@`, en minuscules, autres caractères remplacés par `-`), ses données passent dans
  `accounts/<alias>/`, il devient compte par défaut ; une ligne le dit. L'ancienne session
  est oubliée : un déverrouillage est à refaire. Déplacement impossible : rien n'est
  modifié, code 4 pour les commandes qui touchent au coffre (`config`, `agent`, `account
  list`, `ssh-config install` se font avec un avertissement). `bw` illisible à ce moment :
  avertissement, retenté au lancement suivant ; entre-temps `ssh-config` n'écrit rien (code
  3) et `account add` est refusé. L'ancienne config générée (`ensure --id <uuid>`, sans compte) reste acceptée
  jusqu'à la régénération (`sshvault ssh-config`) : le compte est trouvé par l'id (seul
  compte ; sinon l'état de l'agent, entrée ou référence `also` qui porte un compte ; sinon
  les comptes déverrouillés, lus une fois sans invite ; sinon le seul compte connecté
  verrouillé, un compte dont `bw` est en erreur n'étant pas candidat ; introuvable : une
  ligne).
- Pas d'organisations ni de partage entre comptes, pas de copie d'élément d'un compte à
  l'autre. Même hôte porté par des clés de comptes différents : même règle qu'entre deux
  éléments d'un compte (toutes les clés offertes, avertissement).

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
- `agent status` : agent, socket, pid, puis une ligne par clé (alias du compte, toujours en
  première colonne, `?` s'il est inconnu ; nom, empreinte, hôtes, temps restant, options,
  séparés par des tabulations ; `?` pour une clé chargée hors de sshvault). Agent arrêté : code 3. Puis chaque sous-agent de transfert (voir « Transfert
  d'agent restreint ») : `transfert <motif> (<fid>) : actif, pid N, socket …` et ses clés
  (alias, nom, empreinte, temps restant, options), ou « arrêté » ; un sous-agent en erreur (agent
  tiers sur son socket) : une ligne, code 4.
- `agent purge` : `ssh-add -D` (toutes les clés, même chargées hors sshvault), état vidé
  (agent arrêté : rien à faire, code 0) ; les sous-agents de transfert sont vidés aussi.
- `agent lock` / `agent unlock` : `ssh-add -x` / `-X`, mot de passe saisi par `ssh-add`
  (terminal ou askpass ; sous `--nointeraction` ou sans saisie possible : code 3). Un
  agent verrouillé ne montre aucune clé : `status` affiche celles de l'état ; `load` et
  `purge` refusent (code 3). Si l'état dit « verrouillé » mais que l'agent montre des
  clés, l'état est corrigé. `unlock` d'un agent qui montre ses clés : « déjà
  déverrouillé », code 0.
- `agent stop` : agent tué (pid vérifié), socket et état supprimés. Pid réutilisé par un
  autre processus : aucun signal, seul le socket est nettoyé. Les sous-agents de transfert
  sont arrêtés aussi : aucun ssh-agent de sshvault ne reste, `fwd/` est vide.
- `agent lock` vide puis arrête d'abord tous les sous-agents de transfert (même si le
  verrouillage échoue ensuite) ; tant que l'agent dédié est verrouillé, `ensure --forward`
  refuse (code 3) ; le premier ssh après `agent unlock` les recharge.
- **Config** : `${XDG_CONFIG_HOME:-~/.config}/sshvault/config.json` (0600, dossier 0700,
  aucun secret). `config set key-ttl 2h` fixe la durée par défaut, `config get` l'affiche,
  `config unset key-ttl` revient à 1 h. Clés du chargement automatique (voir plus bas) :
  `auto-load` (défaut `true`), `auto-restrict` et `auto-confirm` (défaut `false`) ;
  `forward-confirm` (défaut `true`, voir « Transfert d'agent restreint ») ; valeurs
  `true`/`false` (aussi `yes`/`no`, `on`/`off`, `1`/`0`). Durée, booléen ou fichier
  invalide (JSON, valeur, droits autres que 0600, propriétaire) : code 2 ; écriture
  impossible : code 4.
- **`bw-path`** : chemin absolu de `bw` (défaut : `bw` du PATH, affiché `bw-path PATH
  (défaut)`). Ordre : `SSHVAULT_BW`, sinon `bw-path`, sinon le PATH ; aucune recherche
  ailleurs (pas même `~/.local/bin`). `sshvault status` affiche d'abord celui qui sera lancé,
  sans le lancer, donc même s'il manque : `bw : <chemin> (SSHVAULT_BW | réglage bw-path |
  PATH)`, ou `bw : bw (introuvable dans le PATH)`.
  - **Refus** : `config set bw-path` refuse (code 2, `config.json` inchangé) un chemin
    relatif, absent, qui contient un caractère de contrôle, ou dont la cible (lien
    symbolique suivi, gardé tel quel) n'est pas un fichier ordinaire exécutable par
    l'utilisateur. Revérifié avant chaque lancement : fichier disparu (« bw introuvable »),
    devenu non exécutable, inaccessible (dossier non traversable, boucle de liens : « bw
    refusé » avec la cause) : code 4, une ligne qui cite le chemin et `bw-path` avec le
    remède ; le PATH n'est **pas** essayé. Fichier présent mais impossible à lancer :
    « interpréteur ou chargeur de bw introuvable » (shebang vers un interpréteur absent) ou
    « format non exécutable » (ni ELF ni shebang), pour toute source.
  - **Avertissement** (pas un refus) : comme le `StrictModes` d'OpenSSH, sont contrôlés la
    cible finale, le dossier de chaque lien symbolique de la chaîne (liens relatifs résolus
    depuis leur dossier) et tous leurs dossiers parents jusqu'à `/`. Chacun doit être à vous
    ou à root et non modifiable par le groupe ni les autres (sticky bit compris : un dossier
    type `/tmp` compte). Sinon le réglage est **accepté** avec une ligne sur stderr, à
    `config set bw-path` puis dans chaque processus qui lance `bw` par ce réglage, une fois,
    **avant** le premier lancement de `bw` (donc avant l'invite du mot de passe maître) ;
    sous `ensure`, préfixée de l'hôte comme les autres messages, dans la sortie de ssh.
    Codes de sortie et stdout inchangés. Exemple : `avertissement : bw-path
    « /home/alice/.local/bin/bw » exposé à d'autres (dossier /home/alice/.local/bin
    modifiable par le groupe ou les autres) : ils pourraient remplacer bw et recevoir le mot
    de passe maître ; corriger par « chmod g-w,o-w /home/alice/.local/bin »`. Le `chmod`
    n'est proposé que pour ce qui est à vous sans sticky bit ; sinon (sticky, autre
    propriétaire, dossier système) : « déplacer bw dans un dossier à vous non modifiable
    par d'autres ».
  - **Lecture** : ne lisent que `bw-path` dans `config.json` (un autre réglage invalide ne
    les gêne pas) : `status`, `list`, `search`, `login`, `unlock`, `lock`, `sync`, `load -t`,
    `pubkey`, `deploy`, `hosts list`, `forward list`. Valident tout le fichier (code 2 sur
    n'importe quel réglage invalide) : `config`, `ensure`, `load` sans `-t` (`key-ttl`),
    `ssh-config`, `hosts`/`forward add|remove|set`, `import` et `generate` avec hôtes
    (régénération du `ssh_config`). Partout, un `bw-path` qui n'est pas une chaîne absolue
    sans caractère de contrôle, ou un fichier illisible (droits, JSON) : code 2. Une
    commande qui ne lance pas `bw` (`agent status`…) ne lit pas ce réglage.
  - Lu dans le `config.json` de l'environnement de ssh (`XDG_CONFIG_HOME` compris) ; le
    chemin n'est jamais passé à un shell ; `bw` reçoit les mêmes arguments et le même
    environnement qu'avant. Pris en compte au prochain appel, sans régénérer le `ssh_config`.

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

### Import d'une clé existante

```
sshvault import ~/.ssh/id_ed25519 --hosts prod.example.org,'*.lab'
sshvault import ~/.ssh/id_rsa --name "Bastion" --hosts bastion
sshvault import ~/.ssh/id_perso --decrypt          # clé à passphrase, stockée déchiffrée
```

Chaque fichier devient un élément « SSH key » du coffre, avec `privateKey` (le fichier tel
quel s'il est au format OpenSSH, sinon converti, voir plus bas), `publicKey` et
`keyFingerprint` remplis, et ses hôtes dans `sshvault-hosts`.

- **Clés acceptées** : Ed25519 et RSA d'au moins 2048 bits, au format OpenSSH, PKCS#8 (PEM,
  `BEGIN PRIVATE KEY` ou `BEGIN ENCRYPTED PRIVATE KEY`) ou RSA PEM PKCS#1 (`BEGIN RSA
  PRIVATE KEY`). PKCS#8 : RSA seulement avec l'OpenSSH 8.9 du poste, qui ne lit pas une
  Ed25519 PKCS#8 (celle qu'écrit OpenSSL : « invalid format », code 2).
- **Refusés** avec un message (code 2) : ECDSA, DSA, clés matérielles `-sk`, PuTTY, SSH2
  (RFC 4716), RSA de moins de 2048 bits, clé publique, PKCS#1 chiffrée sans `--decrypt`,
  fichier qui n'est pas une clé privée ; fichier illisible, qui n'est pas un fichier
  ordinaire (dossier, FIFO…), ou de plus de 64 Kio.
- **PEM en clair converti au format OpenSSH** (RSA PKCS#1, PKCS#8) : par
  `ssh-keygen -p -P "" -N "" -f <copie>` (passphrases vides : aucun secret en argument), sur
  une copie dans le tmpfs privé traitée comme pour `--decrypt` ci-dessous ; une ligne le
  signale. L'élément contient la clé au format OpenSSH, même empreinte.
- **RSA PKCS#1 chiffrée** : acceptée **seulement avec `--decrypt`** (stockée déchiffrée, au
  format OpenSSH) ; sinon code 2 avec cette indication.
- **Fins de ligne** : un fichier en CRLF est stocké en LF (mesuré : `ssh-add -` refuse une
  clé OpenSSH en CRLF) ; le fichier d'origine n'est pas modifié.
- **Clé publique et empreinte** : lue dans l'en-tête OpenSSH (sans passphrase, même si la
  clé est chiffrée ; pour un PEM, après conversion) ; PKCS#8 chiffrée, par `ssh-keygen -y`
  sur une copie (passphrase demandée). Empreinte `SHA256:…` comme `ssh-keygen -l`. Une `.pub`
  voisine qui ne correspond pas, ou illisible : avertissement, ignorée.
- **Nom** : le commentaire de la clé (ou celui de la `.pub` voisine qui correspond), sinon
  le nom du fichier ; `--name` le remplace (un seul fichier).
- **Hôtes** (`--hosts`, liste à virgules, répétable) : mêmes règles que `hosts add` (code
  2 si invalide, rien lu ni écrit) ; le `ssh_config` généré est ensuite régénéré. Ses
  prérequis (socket de l'agent, chemins) sont vérifiés avant d'écrire dans le coffre.
- **Doublon** : une clé dont l'empreinte est déjà dans le coffre (après `bw sync`) n'est
  pas réimportée : code 1, avec le nom et l'id de l'élément existant (avec `--hosts` : la
  commande `sshvault hosts add --id …` qui lui associe ces hôtes). `--force` crée quand même
  un second élément.
- **Clé à passphrase** : par défaut importée **telle quelle, chiffrée**. `load` et le
  chargement automatique demandent alors la passphrase à chaque chargement. Une telle clé
  n'est **pas utilisable par l'agent SSH de Bitwarden Desktop**, ni peut-être par d'autres
  clients Bitwarden (une PKCS#8 chiffrée est gardée telle quelle). Une clé PKCS#8 chiffrée
  demande sa passphrase une fois à l'import, pour calculer la clé publique seulement.
- `--decrypt` : la passphrase est demandée **une fois**, par `ssh-keygen` lui-même (terminal
  au premier plan, sinon askpass ; jamais en argument, jamais lue par sshvault), et la clé
  est stockée **déchiffrée** (au format OpenSSH). Le déchiffrement se fait par
  `ssh-keygen -p -N "" -f <copie>` sur une copie 0600 dans un sous-dossier 0700 neuf de
  `$XDG_RUNTIME_DIR/sshvault/` (tmpfs privé vérifié), lue puis supprimée sur tous les
  chemins, Ctrl-C et SIGTERM compris. L'import tient un verrou `flock` sur ce sous-dossier :
  celui d'un import tué (SIGKILL), au verrou libre, est supprimé au suivant, même si son pid
  a été réutilisé. Sans tmpfs privé, ou disque plein : code 4, rien importé. Passphrase
  refusée, annulée ou sans réponse : code 3, rien créé. Invite impossible
  (`--nointeraction`, ni terminal ni askpass) : code 3, décidé avant tout accès au coffre.
  Invite : askpass si `SSH_ASKPASS_REQUIRE` vaut `force`, ou `prefer` avec askpass permis ;
  sinon le terminal si stdin en est un ; sinon askpass permis ; sinon `/dev/tty` au premier
  plan.
- **Fichier d'origine toujours conservé** : sshvault ne modifie ni ne supprime jamais le
  fichier importé ni sa `.pub` (lecture seule ; pas d'option de suppression). Une fois
  l'import vérifié (`sshvault search --fingerprint …`, puis `load`), supprimer soi-même
  l'original si on ne veut plus de copie sur le disque. **Attention** : un effacement
  (`rm`, même `shred`) n'est pas garanti sur un SSD ou un système de fichiers journalisé
  (copies d'anciens blocs, instantanés, sauvegardes) ; une clé restée longtemps sur disque
  peut justifier d'en générer une nouvelle.
- **Écriture** : `bw sync`, puis `bw create item` avec l'élément encodé **sur stdin**
  (jamais en argument), puis relecture et comparaison des trois champs `sshKey` et des
  hôtes (code 4 si différent). Une création n'est pas idempotente : si `bw create` échoue ou
  reste bloqué (`SSHVAULT_BW_TIMEOUT`), sshvault fait `sync` puis cherche un nouvel élément
  à cette empreinte avant toute décision : trouvé → vérifié, succès ; absent → rejouée **une**
  fois ; toujours absent → code 4. Élément créé mais relu différent : code 4, rien rejoué, avec
  l'id de l'élément à supprimer avant de relancer (sinon il serait vu comme doublon ; ou
  `--force`). Interrompu pendant l'écriture : code 130 et « création peut-être passée :
  vérifier par sshvault sync puis sshvault search --fingerprint … » ; avec `--hosts`, les
  clés déjà créées sont nommées et `ssh_config` n'est pas régénéré (lancer
  `sshvault ssh-config`).
- **Plusieurs fichiers** : chacun est traité à part, une ligne par fichier
  (`importée : nom (empreinte)` sur la sortie, ou l'erreur sur stderr) ; code de sortie : le
  pire des codes rencontrés (0 < 1 < 2 < 3 < 4), y compris si le coffre échoue ensuite.

### Génération d'une clé dans le coffre

```
sshvault generate --name web --hosts web.example.org
sshvault generate --name vieux-serveur --type rsa --bits 3072 > vieux-serveur.pub
```

- La clé est générée par `ssh-keygen -q -t <type> [-b <bits>] -N "" -C <commentaire> -f
  <dossier>/key`, dans un sous-dossier 0700 neuf de `$XDG_RUNTIME_DIR/sshvault/` (tmpfs
  privé vérifié, mêmes règles que la copie de `import --decrypt` : verrou `flock`,
  suppression sur tous les chemins, Ctrl-C et SIGTERM compris, signaux masqués pendant la
  suppression, dossier d'une génération tuée supprimé à la suivante). La clé privée est relue
  en mémoire puis le dossier supprimé : sshvault ne l'écrit **jamais sur un stockage
  persistant**, ne l'affiche pas et ne la passe pas en argument (le seul « secret » en argument
  est la passphrase vide `-N ""`). Limites : un tmpfs peut être évincé vers le swap (en clair
  si le swap n'est pas chiffré), et les copies Python de la clé restent dans la mémoire du
  processus jusqu'à sa fin (Python ne garantit pas leur effacement).
- **Types** : Ed25519 par défaut ; `--type rsa` avec `--bits 3072` ou `4096` (défaut 4096).
  Toute autre valeur (`--bits 1024`, `--type ecdsa`, `dsa`, `-sk`, `--bits` avec Ed25519) :
  code 2, avant toute génération. ECDSA, DSA et `-sk` ne sont pas pris en charge par les
  clients Bitwarden.
- **Sans passphrase** : le coffre chiffre déjà la clé (utilisable par l'agent de Bitwarden
  Desktop).
- **Nom** (`--name`, obligatoire) : un nom déjà porté par une clé SSH du coffre (casse et
  blancs autour ignorés, après `bw sync`) donne le code 1, rien généré, avec le nom et l'id de
  l'élément existant ; `--force` crée quand même un élément de ce nom.
- **Commentaire** de la clé (`--comment`, défaut : le nom) : caractères imprimables
  seulement (ni tabulation, ni fin de ligne, ni contrôle), 255 au plus ; sinon code 2.
- **Sortie** : stdout ne contient **qu'une ligne**, la clé publique au format OpenSSH (à
  rediriger vers un fichier ou à déployer) ; tout le reste (compte rendu, régénération du
  `ssh_config`, avertissements) va sur stderr.
- **Création** : comme `import` (élément sur stdin, trois champs `sshKey`, reprise sans
  doublon après un échec ou un blocage de `bw create`, relecture comparée). Si la création
  n'aboutit pas (code 4), le message le dit : la clé générée n'a jamais existé ailleurs qu'en
  mémoire, elle est perdue ; relancer `generate`. Interrompu pendant la création : code 130 et
  « création peut-être passée » (vérifier par `sshvault sync` puis
  `sshvault search --fingerprint …`, clé publique par `sshvault pubkey`).
- **Hôtes** (`--hosts`) : comme `import` (validés, prérequis de la régénération vérifiés
  avant le coffre, `ssh_config` régénéré ensuite). Un motif attrape-tout (`*`) est signalé
  une seule fois, après le contrôle du nom et avant la génération.
- **Ordre** : refus d'usage (code 2) ; puis, avant tout accès au coffre, tmpfs privé et son
  dossier `sshvault/` (code 4 : `XDG_RUNTIME_DIR` relatif, non privé ou hors tmpfs, repli
  `/run/user/<uid>` inutilisable) et prérequis du `ssh_config` (chemins, socket, chemin de
  sshvault ; code 4) ; puis le coffre (code 3 verrouillé sans invite possible), le nom déjà
  pris (code 1) ; seulement ensuite la génération et la création.
- **Après la création**, une interruption ou une sortie fermée (`generate … | head -0`) laisse
  la clé dans le coffre : stderr le dit (« clé créée : « nom » id », et « ssh_config non
  régénéré : lancer « sshvault ssh-config » » si la régénération n'a pas eu lieu). Session
  refusée par `bw` pendant la création : même code que d'habitude (3), avec « clé perdue ».

### Clés publiques : affichage et déploiement

```
sshvault pubkey --host web.example.org > web.pub
sshvault deploy --id 0f2c… admin@web.example.org
sshvault deploy web web.example.org -p 2222 -- -i ~/.ssh/cle_admin -o ConnectTimeout=10
```

- `pubkey` affiche la ou les clés publiques sélectionnées (sélection comme `load`, ou
  `--all`), une ligne `type base64 [commentaire]` par clé, rien d'autre sur stdout. Elle lit
  le cache local de `bw` : aucun appel réseau (lancer `sshvault sync` d'abord si besoin).
  Deux éléments d'une même clé : une ligne. Commentaire avec caractère de contrôle : retiré
  de la ligne. Clé publique d'un élément illisible : message, code 4, les autres affichées.
- `deploy` ajoute les clés publiques sélectionnées à `~/.ssh/authorized_keys` de la cible
  par **un seul `ssh`** :
  - les clés passent sur **stdin** ; la commande distante est un script POSIX **fixe**,
    lancé par `exec sh -c '…'`, qui ne contient aucune donnée de l'utilisateur ;
  - sous `umask 077`, il crée `~/.ssh` (0700) s'il manque et `authorized_keys` (0600) ;
  - il tient un verrou (`~/.ssh/.sshvault-deploy.lock`, un dossier, 10 essais d'une seconde,
    supprimé à la sortie) autour de la vérification et de l'ajout : deux `deploy` simultanés
    ne se doublent pas. Un verrou resté d'un `deploy` tué : erreur qui le nomme ;
  - il n'ajoute une clé que si elle (type + base64) n'y est pas déjà ; les lignes commentées
    `#` ne comptent pas, les fins de ligne CRLF sont reconnues ; un fichier sans fin de ligne
    finale est complété ;
  - il lance `restorecon -F` sur `~/.ssh` et `authorized_keys` si la commande existe (SELinux ;
    échec ignoré) ;
  - il répond, par clé : « ajoutée », « déjà présente », ou « déjà présente (avec options : la
    connexion peut être restreinte) » si la clé n'y figure qu'avec des options (`command=`,
    `from=`, `restrict`, `cert-authority`, `expiry-time`…) : une ligne par clé sur stdout.
    Un second `deploy` n'ajoute rien et ne touche pas au fichier.
- Shells de connexion distants éprouvés : `sh`, `dash`, `bash` (tests pour `zsh`, `fish`,
  `tcsh`, ignorés quand ils manquent : non éprouvés sur le poste de développement). Le script
  tient sur une ligne, sans apostrophe ni `!`.
- Cible `[utilisateur@]hôte` : nom de lettres, chiffres, `.`, `-`, `_` (pas de `-` en tête),
  ou adresse IPv6 valide (au moins deux `:`), nue ou entre crochets (`[::1]`) : les crochets
  sont retirés avant `ssh` (OpenSSH 8.9 les garderait dans le nom à résoudre). Tout autre
  caractère (`;`, `$`, espace, `%`…) ou `hôte:port` est refusé (code 2) : rien ne peut être
  interprété par un shell local, ni par un `ProxyCommand` de la config ssh de l'utilisateur
  (`%h`, `%r`). `-p PORT` : 1 à 65535.
- `-- OPTIONS_SSH…` : options passées telles quelles à `ssh`, chacune en argument séparé,
  jamais par un shell ; seules des options de `ssh` (et leurs arguments) y sont acceptées,
  pas une cible ni une commande. Refusées aussi, car elles changent le mode de `ssh` : `-N`,
  `-n`, `-f`, `-G`, `-V`, `-Q`, `-O`, `-W`, `-s`, `-M`, `-t`, et `-o` `RequestTTY`,
  `StdinNull`, `SessionType`, `ForkAfterAuthentication`, `RemoteCommand`, `LocalCommand`,
  `PermitLocalCommand`, `ProxyUseFdpass` (code 2).
- `ssh` reçoit, dans l'ordre : `[-o BatchMode=yes]` (avec `--nointeraction`), les options,
  `-o ConnectTimeout=30` (sauf si les options en donnent un), `-p PORT`, `--`, la cible, la
  commande fixe. L'authentification est celle de `ssh` (agent, clés, mot de passe ou
  confirmation de la clé d'hôte sur le terminal). `SSHVAULT_SSH` remplace l'exécutable.
- Délai global `SSHVAULT_DEPLOY_TIMEOUT` (120 s par défaut, saisie comprise) : passé, `ssh`
  est arrêté (SIGTERM, puis SIGKILL) : code 4.
- `ssh` en échec (connexion, authentification, commande distante) : code 4, avec son
  message. Échec en cours de route : les clés déjà ajoutées sont dites (une ligne chacune),
  puis code 4. Le coffre n'est pas contacté par le réseau (cache local de `bw`).

### `ssh_config` généré

`sshvault ssh-config` lit le **cache local** de `bw` (lancer `sshvault sync` d'abord pour
voir une modification faite ailleurs) et écrit `~/.ssh/sshvault/config` (0600, dossier
0700, en-tête « ne pas éditer ») et `~/.ssh/sshvault/pub/<empreinte en base64url>.pub` (0600). Un bloc par
élément qui a des hôtes, de tous les comptes, triés par nom, alias puis id :

```
# Serveur Prod perso 11111111-1111-4111-8111-111111111111
Match originalhost prod.example.org,*.lab exec "'/home/alice/.local/bin/sshvault' ensure --account perso --id 11111111-1111-4111-8111-111111111111"
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
  tout est à jour et la ligne `Include` en tête, 1 sinon. Un compte **déconnecté** (bw non
  connecté, après `sshvault logout`) garde ses blocs tels quels pour la comparaison, même
  s'il est le seul compte (avertissement) ; un compte seulement verrouillé ou un `bw` en
  erreur (absent, délai, `bw-path` invalide) gardent la règle des régénérations : seul
  compte, ou tous illisibles : leur code (3 verrouillé, 4 erreur de bw, 2 `bw-path`
  invalide), jamais « à jour ». Différences sur stdout : contenu,
  fichier absent, en trop ou non ordinaire, droits autres que 0600 (fichiers) ou 0700
  (dossiers), `pub/` qui n'est pas un dossier ou illisible. Un sous-dossier de `pub/` est
  signalé (stderr) et laissé en place, comme par `ssh-config`.
- Première valeur rencontrée : `IdentityAgent` et `IdentitiesOnly` de sshvault
  l'emportent sur vos défauts (`Host *`) placés après la ligne `Include`. `IdentityFile`,
  lui, se **cumule** : un `IdentityFile` de votre config qui vise aussi cet hôte s'ajoute
  après la clé de sshvault (mesuré) ; pour n'offrir qu'une clé, ne pas en mettre pour les
  hôtes gérés par sshvault.

**ForwardAgent : attention.** Le bloc d'identité n'écrit pas `ForwardAgent` : votre
config décide. Mais avec `ForwardAgent yes` (ou `ssh -A`) sur un hôte géré par sshvault
**sans transfert déclaré**, c'est **l'agent dédié entier** (toutes les clés chargées par
sshvault, pas seulement celle de cet hôte) qui est transféré, et non votre agent habituel :
`IdentityAgent` remplace `SSH_AUTH_SOCK` pour la connexion (mesuré sur OpenSSH 8.9p1 avec un
sshd de test : `ssh-add -L` sur l'hôte distant liste les clés de l'agent dédié). Un root
distant peut s'en servir tant que la session est ouverte. Déclarer un transfert restreint
(`sshvault forward add … <hôte>`, voir plus bas) ou poser `ForwardAgent no` pour ces hôtes.
`sshvault ssh-config` (écriture et `--check` ; pas les régénérations de `hosts`, `forward`,
`import`, `generate`) avertit pour chaque hôte d'identité **littéral** sans transfert déclaré
dont `ssh -G` montre `forwardagent yes` ; un motif (`*.lab`) ne peut pas être vérifié, et
`ssh -A` tapé à la main non plus. `ssh -G` lit votre config réelle et **exécute vos propres
lignes `Match exec`** (celles de sshvault n'y font rien) ; 15 s au plus par hôte et 30 s au
total, puis « contrôle … interrompu » et les hôtes restants ne sont pas vérifiés.

**Clé absente de l'agent dédié.** Le bloc n'offre que la clé de l'agent dédié
(`IdentitiesOnly yes`) : si elle n'y est pas (chargement automatique désactivé ou en
échec), ssh affiche `Load key "…/pub/SHA256:….pub": error in libcrypto` puis
`Permission denied (publickey)`. La ligne `sshvault: …` qui précède dit pourquoi ;
`sshvault load <hôte>` la charge à la main.

### Chargement automatique (`Match exec`)

Avec la config générée incluse, `ssh <hôte>` charge seul la clé de l'hôte si elle manque
dans l'agent dédié, pour la cible **et** pour chaque saut `ProxyJump`/`ProxyCommand ssh -W`
(le ssh du saut relit la config). Aucune commande préalable ; au plus une invite de
déverrouillage par compte concerné et par connexion (l'invite nomme l'alias).

- **Comment.** Avant chaque bloc, `Match originalhost <motifs> exec "'<sshvault>' ensure
  --account <alias> --id <id>"` : ssh n'exécute la commande que si le nom tapé correspond, avant
  l'authentification, puis applique le bloc. La ligne ne porte aucune directive : son code
  de sortie ne change rien. Mesuré (OpenSSH 8.9p1) : un appel par saut, la cible d'abord
  puis le saut, chacun fini avant l'authentification de son saut.
- **Commande sûre.** La commande passe par le shell de l'utilisateur : elle ne contient
  que le chemin absolu de sshvault entre apostrophes (refusé s'il contient `'`, `"`, `\`,
  `${` ou un caractère de contrôle ; `%` doublé), l'alias du compte (vérifié) et l'id de
  l'élément, un UUID vérifié : aucune donnée tapée par l'utilisateur.
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

### Transfert d'agent restreint (`sshvault forward`)

Pour un hôte où l'on veut `ForwardAgent` (rebond d'où l'on se connecte plus loin), seul un
**sous-agent** qui ne contient que les clés autorisées pour cet hôte est transféré.

```
sshvault forward add  --id 2222… bastion '*.dmz'   # la clé de 2222… sera transférée vers ces hôtes
sshvault forward remove --id 2222… '*.dmz'
sshvault forward set  --id 2222… bastion           # remplace la liste ; "" la vide
sshvault forward list --id 2222…                   # un motif par ligne
```

- **Déclaration** : champ personnalisé `sshvault-forward` de l'élément (texte ou masqué),
  mêmes règles que `sshvault-hosts` (liste à virgules, motifs de ligne `Host`, minuscules,
  écrit sur stdin, relu, rejoué au plus une fois, autres champs inchangés) ; la commande
  `forward` est calquée sur `hosts` (sélection d'un seul élément, codes 1 et 2 identiques) et
  régénère le `ssh_config`. Un hôte de transfert n'a pas besoin d'être un hôte d'identité
  (on peut s'y authentifier avec sa propre clé).
- **Bloc généré**, par motif, **avant** les blocs d'identité (pour chaque paramètre, la
  première valeur gagne) :
  ```
  # transfert d'agent bastion 1f2e3d4c5b6a7980
  Match originalhost bastion exec "'/home/alice/.local/bin/sshvault' ensure --forward 1f2e3d4c5b6a7980 --id 2222…"
  Match originalhost bastion
      ForwardAgent "/run/user/1000/sshvault/fwd/1f2e3d4c5b6a7980.sock"
  ```
  `<fid>` = 16 premiers chiffres hexadécimaux du SHA-256 du motif en minuscules. La commande
  ne contient que le chemin vérifié de sshvault, le `fid` et des ids validés (UUID) ; ni `%h`
  ni `%n`. Mesuré (OpenSSH 8.9p1) : ce chemin l'emporte sur un `ForwardAgent yes` placé après
  la ligne `Include`, et aussi sur `ssh -A` et `-o ForwardAgent=yes`. Ordre des blocs :
  motifs littéraux, puis motifs à joker du plus au moins précis, attrape-tout en dernier ;
  deux motifs qui se recouvrent (`bastion.dmz` et `*.dmz`) : le premier bloc gagne,
  avertissement, et la ligne `Match … exec` d'un bloc exclut les motifs des blocs précédents
  (`Match originalhost *.dmz,!bastion.dmz exec …`) : les clés d'un sous-agent qui ne serait pas
  transféré ne sont ni lues ni chargées ; motif sans partie littérale (`*`) : avertissement « ce sous-agent de
  transfert sera transféré à toutes les connexions ssh ». Sans ligne `Match exec`
  (`auto-load false`, ou aucune clé utilisable pour ce motif) : `ForwardAgent no`, avec un
  avertissement (un socket jamais créé arrêterait un saut `ssh -W` par cet hôte, voir plus
  bas) ; rien n'est transféré par la config, seul un `ssh -A` tapé à la main le pourrait.
- **Sous-agent** : un `ssh-agent` d'OpenSSH par motif, mêmes règles que l'agent dédié :
  socket `$XDG_RUNTIME_DIR/sshvault/fwd/<fid>.sock` (107 octets au plus, sinon code 4), état
  `<fid>.json` à côté (0600, aucun secret), pid vérifié avant tout signal, surveillant
  détaché, orphelins arrêtés à chaque lancement de sshvault, verrou `flock` sur `fwd/`
  (jamais celui de l'agent dédié), `SSH_AUTH_SOCK` = son socket pour chaque `ssh-add`.
- **Chargement à la demande** : `ensure --forward <fid> --id …` (ligne `Match exec`) charge
  dans le sous-agent les clés des éléments, et elles seules, comme `ensure --id` : chemin
  rapide si toutes sont fraîches et qu'aucune autre n'est là ; sinon sous le même verrou
  `ensure.lock`, une seule invite de déverrouillage pour la connexion (mémoire d'échec
  partagée), `bw get item` par clé, `ssh-add -t <key-ttl> [-c] -` (clé sur stdin, jamais `-h`),
  tout ou rien, état enregistré. Le coffre fait foi : une clé dont l'élément ne déclare plus
  ce motif n'est pas chargée (config générée périmée : « lancer sshvault ssh-config »). Toute
  autre clé trouvée dans le sous-agent (élément retiré, clé changée, `ssh-add` à la main) est
  retirée. `ensure --forward` ne touche jamais l'agent dédié (son état est seulement lu :
  verrouillé par `agent lock` → refus, code 3) ; `ensure --id` ne touche jamais un sous-agent.
- **Confirmation** : `forward-confirm` (défaut `true`) charge les clés transférées avec
  `ssh-add -c` : chaque usage depuis l'hôte distant est confirmé sur le poste par l'askpass du
  sous-agent (celui de l'environnement du ssh qui l'a lancé : `DISPLAY` ou
  `SSH_ASKPASS_REQUIRE=force`, `SSH_ASKPASS` exécutable). Sans askpass utilisable, rien n'est
  chargé (une ligne, code 4) ; un sous-agent lancé sans askpass est relancé dès qu'un ssh en
  a un. `config set forward-confirm false` : sans confirmation. Tout changement de la valeur
  (`set` ou `unset`) arrête les sous-agents (« sous-agents de transfert arrêtés : rechargés au
  prochain ssh ») : aucune clé ne garde l'ancienne option ; l'agent dédié n'est pas touché.
- **Échec** (coffre verrouillé sans invite possible, `forward-confirm` sans askpass, agent
  dédié verrouillé…) : une ligne `sshvault: <hôte> : transfert d'agent : <cause>`, code ≠ 0,
  et la connexion se fait quand même : l'hôte distant voit un agent vide, ou aucun (ssh
  affiche alors `Cannot forward agent socket path …`). Clé expirée (`key-ttl`) pendant la
  session : l'hôte distant voit un agent vide ; la connexion suivante la recharge.
- **Saut ProxyJump/ProxyCommand `ssh -W`, et `ssh -N`** : aucun canal de session, donc rien
  n'est transféré et aucune clé n'est chargée ; mais `-W` impose `ExitOnForwardFailure`
  (mesuré, 8.9p1 : un socket de `ForwardAgent` absent arrête le saut aussitôt, même avec
  `-a`) : `ensure --forward` y lance au besoin un sous-agent **vide**, sans coffre, sans
  réglage lu ni invite. Ce sous-agent vide est lancé **même pendant `agent lock`** ou juste
  après `agent stop` (refuser arrêterait le saut) ; il ne reçoit aucune clé. `ssh -a` ou
  `-o ForwardAgent=no` (aussi `-oForwardAgent=no`, que passent scp et sftp) : rien n'est
  transféré, `ensure --forward` ne fait rien (code 0).
- **Retrait** : `ssh-config` (et toute régénération : `hosts`, `forward`, `import`,
  `generate`) arrête chaque sous-agent qu'il ne référence plus, ou qui garde la clé d'un
  élément retiré de ce motif (rechargé sans elle au prochain ssh), ou dont le bloc n'a plus de
  ligne `Match exec`. Clé changée dans le coffre sans `ssh-config`, pour un élément qui a aussi
  des hôtes d'identité (son `.pub` généré diffère) : rien n'est chargé pour ce motif, une ligne
  « lancer sshvault ssh-config », code 4. Un élément **seulement** transféré n'a pas de `.pub` :
  son ancienne clé reste dans le sous-agent jusqu'à `key-ttl`, puis la nouvelle est chargée.
- **Verrou** : `agent lock`, `agent stop`, les régénérations qui arrêtent un sous-agent et
  `config set forward-confirm` prennent le verrou `ensure.lock` : un `ensure` en cours finit
  d'abord (« attente d'un chargement en cours (ensure)… » sur stderr), aucun ne relance un
  sous-agent pendant l'arrêt ni avant que l'état « verrouillé » soit enregistré. Pendant que
  `agent lock` attend le mot de passe de verrouillage, les connexions ssh qui doivent charger
  une clé attendent aussi (dans leur délai `SSHVAULT_ENSURE_TIMEOUT`). Un état « verrouillé »
  laissé par un agent dédié mort ne bloque rien. Limites : `agent lock` exige l'agent dédié
  lancé (usage en transfert seul : les sous-agents sont vidés et arrêtés, mais le verrouillage
  échoue, code 3, et le ssh suivant les recharge) ; un verrou posé à la main
  (`ssh-add -x` sur l'agent dédié) n'est pas vu par `ensure --forward`, qui ne lit que l'état
  de sshvault.
- **Risques résiduels.** Pendant la session, root sur l'hôte distant peut utiliser les clés
  du sous-agent (pas les autres). `-c` aide, mais la fenêtre de confirmation d'OpenSSH ne nomme
  pas l'hôte de destination : facile à hameçonner. La contrainte `ssh-add -h src>dst` n'est
  pas posée (la clé d'hôte du saut suivant est rarement dans le `known_hosts` local) :
  reportée ; de toute façon sans garantie avant OpenSSH 10.5. Avec `ExitOnForwardFailure yes`
  dans votre config, un échec d'`ensure --forward` arrête la connexion. Un hôte d'identité sans
  transfert déclaré reste exposé à `ForwardAgent yes`/`ssh -A` (voir « ForwardAgent :
  attention »).

### Codes de sortie

| Code | Sens |
|---|---|
| 0 | succès |
| 1 | `search`, `load`, `hosts`, `forward`, `pubkey`, `deploy` : aucun résultat ; `import` : clé déjà dans le coffre (rien créé) ; `generate` : nom déjà pris, sans `--force` (rien généré) ; `hosts remove`, `forward remove` : hôte absent (rien écrit) ; `ssh-config --check` : pas à jour (contenu, droits, fichier en trop ou non ordinaire), ou ligne `Include` absente, conditionnelle ou pas en tête |
| 2 | usage (option ou argument invalide ; `load` sans sélection ni `--all`) ; comptes : alias invalide ou inconnu, alias ou couple serveur + e-mail déjà enregistré, serveur ou e-mail invalide, écriture sans `--account` quand plusieurs comptes sont possibles, `login` ou `logout` sans `--account` avec plusieurs comptes, aucun compte par défaut, `account rename` vers un alias pris, `account add` : dossier `accounts/<alias>` existant, `account set` sans `--server` ni `--email`, `account set` : registre refusé après la déconnexion (couple pris entre-temps ; ce qui est déjà fait est dit) ; `logout`, `account set` : `bw-path` invalide (rien fait) ; durée invalide ; `config.json` invalide, illisible ou aux droits inattendus ; `config set bw-path` : chemin relatif, absent, avec un caractère de contrôle, ou pas un fichier ordinaire exécutable ; `bw-path` invalide dans `config.json` ; hôte invalide ; sélection de `hosts` ou `forward` qui désigne plusieurs éléments ; `import` : fichier refusé (illisible, pas une clé privée, type ou format non accepté), `--name` avec plusieurs fichiers ; `generate` : type, bits, nom ou commentaire refusés ; `deploy` : cible, port ou options ssh invalides ou refusées ; délai `SSHVAULT_DEPLOY_TIMEOUT` invalide |
| 3 | aucun compte enregistré (`ssh-config` n'écrit alors rien, `lock` compris), non connecté (« lancer sshvault login » ; `ensure` d'un compte déconnecté par `logout` : « lancer sshvault login --account ALIAS »), ou coffre verrouillé : aucune invite possible, invite annulée ou sans réponse, mot de passe refusé ; agent dédié arrêté (`agent status`, `lock`, `unlock`) ou verrouillé (`ensure --forward` compris) ; passphrase d'une clé refusée ou impossible à saisir (`load`, `import`) |
| 4 | erreur du backend : `bw` introuvable, non exécutable, interpréteur ou chargeur absent, format non exécutable (au chemin du réglage `bw-path` compris, le PATH n'étant alors pas essayé), en erreur, réponse illisible, délai dépassé ; magasin de session inutilisable ; agent dédié : `XDG_RUNTIME_DIR` relatif, non privé ou hors tmpfs, chemin du socket trop long, agent tiers sur le socket, OpenSSH < 8.9, `--restrict` (élément sans hôte, hôte non littéral ou absent de `known_hosts`), sous-agent de transfert en erreur (`agent status`, `stop`, `purge`, `lock`), clé publique illisible ou différente de la clé privée, `ssh-add`/`ssh-agent` en erreur ; écriture de `config.json` impossible ; écriture des hôtes ou des transferts dans le coffre non aboutie ou non vérifiée (y compris écrits mais `ssh_config` non régénéré) ; `ensure --forward` : `forward-confirm` sans askpass, élément qui ne déclare plus ce transfert, chemin du socket de transfert trop long ; `import` : création non aboutie ou non vérifiée (y compris clé importée mais `ssh_config` non régénéré), copie impossible dans un tmpfs privé (`--decrypt`), `ssh-keygen` absent ou en erreur ; `generate` : tmpfs privé inutilisable, `ssh-keygen` absent ou en erreur, création non aboutie ou non vérifiée (clé perdue, dit), clé créée mais `ssh_config` non régénéré ; `pubkey` : clé publique d'un élément illisible ; `deploy` : `ssh` absent, en échec ou sans réponse (`SSHVAULT_DEPLOY_TIMEOUT`), réponse inattendue de la cible, échec partiel (clés déjà ajoutées dites, puis code 4), clé publique illisible ; `ssh_config` généré impossible à écrire (chemin avec `"`, `\`, `${`, fichier non ordinaire, droits) ; répertoire personnel inconnu ; `ssh-config install` refusé (lien symbolique, fichier non ordinaire, `Include` conditionnel, chemin personnel avec `%`, `$` ou joker) ; adoption de l'installation 0.8.0 impossible (rien modifié ; `account add` refusé tant qu'elle n'est pas faite) ; `account rename` : destination existante ou déplacement impossible (rien changé) ; `account remove` : données locales impossibles à supprimer (compte gardé), magasin de session ou agent en erreur ou verrouillé (clés laissées, état gardé) ; `logout`, `account set` : agent en erreur ou verrouillé (rien modifié, ou état partiel dit), `bw logout` en échec ou sans réponse (compte toujours connecté, ou état inconnu ; `account set` : registre inchangé), `account set` : écriture du registre impossible après la déconnexion (ce qui est déjà fait est dit) ; `ssh-config --check` : `bw` en erreur, même pour un compte déconnecté ; erreur interne |
| 130 | interrompu (Ctrl-C, SIGTERM, SIGHUP) |

`agent status`, `stop`, `purge`, `lock` : code de l'agent dédié (`status` : 0 actif, 3 arrêté),
mais 4 si un sous-agent de transfert est en erreur (agent tiers sur son socket…), chacun dit
en une ligne ; les autres sous-agents sont traités quand même.

`ensure` : 0 si la clé est présente ou chargée, et pour `ssh -G` ; sinon le code de
l'erreur (3 coffre verrouillé ou agent verrouillé, 4 backend, agent, délai global…), sans
effet sur ssh. `ensure --forward` : de même (0 aussi pour un saut `ssh -W` dont le socket
existe) ; la connexion se fait sans clé transférée.

`status` : 0 si le coffre de chaque compte affiché est déverrouillé, 3 si l'un est
verrouillé ou non connecté (ou s'il n'y a aucun compte), 4 si `bw` est en erreur.
Plusieurs comptes (lecture, `unlock`, `lock`, `sync`) : le pire des codes des comptes. Un délai invalide dans l'environnement (voir Variables) donne
le code 2. Toute erreur est une ligne sur stderr, sans traceback.

## Fonctionnement

- **`bw` dédié** : sshvault lance `bw` avec
  `BITWARDENCLI_APPDATA_DIR=${XDG_DATA_HOME:-~/.local/share}/sshvault/accounts/<alias>/bw`
  (un dossier par compte : `bw` ne connaît qu'un compte par dossier). Son
  login est donc séparé de l'usage personnel de `bw` (un `unlock` invalide les
  sessions précédentes). `bw serve` n'est jamais utilisé.
- `bw` est appelé avec `--nointeraction` (sauf `login`), un délai borné
  (`SSHVAULT_BW_TIMEOUT`, 60 s par défaut) et la session dans `BW_SESSION` de son
  seul environnement. Le mot de passe maître passe par `--passwordenv`, dans
  l'environnement du seul sous-processus : jamais en argument ni dans un fichier.
- Réseau : `list`, `search`, `unlock`, `lock` et `status` ne lisent que le cache local
  de `bw` (aucune connexion) ; seuls `sync`, `login`, l'écriture de `hosts`
  (`bw edit`, jamais relancé à l'aveugle : voir Hôtes d'une clé), `import` et `generate`
  (`bw create`, même règle : voir Import) passent par le réseau. `pubkey` et `deploy` lisent
  le cache local (`deploy` ne contacte que la cible, par `ssh`). Une
  connexion neuve peut y rester bloquée sans fin (mesuré : ClientHello TLS jamais
  acquitté ; `bw` n'a pas de délai réseau propre). Un passage de `sync` fait donc
  deux essais de `SSHVAULT_BW_TIMEOUT`/2 chacun. S'il faut d'abord déverrouiller (pas
  de session rangée, ou session refusée par `bw`), s'y ajoutent l'invite, `bw status`
  ou un premier passage refusé, et `bw unlock` : au pire
  3 × `SSHVAULT_BW_TIMEOUT` + `SSHVAULT_PROMPT_TIMEOUT`.
- **Session** (une par compte) : keyring noyau `@u` (clé `user` `sshvault:session:<alias>`,
  expiration posée par le noyau). Si `keyctl` échoue (session keyring non liée à `@u`, par
  exemple un tmux survivant à sa session), repli sur
  `$XDG_RUNTIME_DIR/sshvault/sessions/<alias>` (0600), expiré à la lecture, seulement si
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
| `SSHVAULT_BW` | exécutable `bw`, prioritaire sur le réglage `bw-path` (défaut : `bw-path`, sinon `bw` du PATH) |
| `SSHVAULT_BW_TIMEOUT` | délai d'un appel `bw`, en secondes, 0 < v ≤ 86400 (défaut 60 ; `login` : 600) |
| `SSHVAULT_PROMPT_TIMEOUT` | délai d'une invite, en secondes, 0 < v ≤ 86400 (défaut 60) |
| `SSHVAULT_ENSURE_TIMEOUT` | délai global d'un `ensure` depuis son démarrage, attente du verrou comprise, en secondes, 0 < v ≤ 86400 (défaut 240) |
| `SSHVAULT_KEYRING`, `SSHVAULT_KEYCTL` | anneau et exécutable `keyctl` (tests ; défaut `@u`, `keyctl`) |
| `XDG_DATA_HOME` | base des dossiers de données de `bw`, un par compte (défaut `~/.local/share`) |
| `XDG_RUNTIME_DIR` | repli fichier de la session ; socket et état de l'agent dédié (tmpfs privé exigé) |
| `XDG_CONFIG_HOME` | base de `sshvault/config.json` (défaut `~/.config`) |
| `SSHVAULT_SSH_HOME` | tests seulement : répertoire personnel de `~/.ssh` (défaut : celui de passwd) |
| `SSHVAULT_SSH_AGENT`, `SSHVAULT_SSH_ADD` | exécutables `ssh-agent` et `ssh-add` (défaut : ceux du PATH) |
| `SSHVAULT_SSH_KEYGEN` | exécutable `ssh-keygen` (`import`, `generate` ; défaut : celui du PATH) |
| `SSHVAULT_SSH` | exécutable `ssh` (`deploy`, contrôle `ssh -G` de `ssh-config` ; défaut : celui du PATH) |
| `SSHVAULT_SSH_G_BUDGET` | durée totale du contrôle `ssh -G` de `ssh-config`, en secondes, 0 < v ≤ 86400 (défaut 30) |
| `SSHVAULT_DEPLOY_TIMEOUT` | délai global d'un `deploy`, en secondes, 0 < v ≤ 86400 (défaut 120) |
| `SSHVAULT_TEST_FIELD` | tests seulement : `NOM=VALEUR`, champ texte ajouté aux éléments créés par `import` et `generate` (marqueur de nettoyage de l'intégration) |
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
- `tests/test_import.py` (import) : vraies clés générées par `ssh-keygen` (Ed25519, RSA
  2048/4096, `-m PKCS8`, `-m PEM` en clair et chiffrée, à passphrase ; ECDSA, DSA, RSA 1024, PuTTY, `-sk`
  construite, fichiers abîmés) ; passphrase par pty (premier plan) et askpass ; faux `bw`
  capable de `create` (élément sur stdin) et de simuler une création en échec, bloquée,
  passée puis bloquée, illisible ou altérée ; argv de `bw` et de `ssh-keygen` journalisés et
  `/proc/<pid>/cmdline` relevé pendant l'appel (ni JSON, ni clé, ni passphrase) ; fichiers
  d'origine inchangés, copie tmpfs supprimée, aucun fichier de clé privée hors des fixtures.
- `tests/test_generate.py` (`generate`, `pubkey`, `deploy`) : vrai `ssh-keygen` (enveloppé
  pour journaliser ses arguments) ; empreinte de l'élément = `ssh-keygen -l` de la ligne
  affichée, `ssh-keygen -y` de la clé privée stockée = cette ligne ; refus et ordre des
  contrôles vérifiés par l'absence d'appel à `ssh-keygen` et à `bw` ; interruptions
  (SIGINT, SIGTERM) pendant la génération et la création ; `/proc/<pid>/cmdline` relevé
  pendant l'appel et contrôlé après coup contre la clé générée. `deploy` vers un sshd de test
  sur 127.0.0.1 dont le HOME des sessions est un dossier de test (`SetEnv HOME=`), puis
  connexion avec la clé déployée chargée dans l'agent dédié ; script distant aussi éprouvé
  sous `sh`, `dash` et `bash` (`zsh`, `fish`, `tcsh` s'ils sont installés) : CRLF, clé avec
  options, verrou ; cibles et options piégées (`;`, `$()`, espaces) ; faux `ssh` : échec
  partiel, réponse incomplète, délai, SIGTERM.
- `tests/test_forward.py` (transfert restreint) : champ `sshvault-forward` lu et écrit seul,
  commande `forward`, blocs générés (ordre, commande, avertissements) validés par l'OpenSSH du
  poste (`ssh -G` : le chemin du sous-agent gagne sur `ForwardAgent yes`, `-A`,
  `-o ForwardAgent=yes`), avertissement `forwardagent yes`, `ensure --forward` avec les vrais
  `ssh-agent`/`ssh-add` (clé en trop retirée, tout ou rien, coffre qui fait foi, confirmation
  et askpass, agent dédié verrouillé, clé expirée), `agent status/purge/lock/stop`, arrêt des
  sous-agents non référencés, surveillant et orphelin ; de bout en bout, deux sshd de test
  (`PermitUserRC no`) : `ssh a 'ssh-add -L'` ne liste que la clé transférée (aussi avec
  `ssh -A`), saut ProxyJump (`-W`) sans clé chargée, confirmation demandée par l'askpass puis
  refusée (`ssh-add -T` sur l'hôte distant).
- `tests/test_accounts.py` (plusieurs comptes) : faux `bw` multi-serveurs (un coffre par
  compte, `FAKE_BW_VAULTS`, choisi au `login` par e-mail et serveur) ; registre (`account
  add/list/default/remove/rename`, refus), lecture sur les comptes par défaut et `--account`,
  écriture qui exige `--account`, `lock`/`unlock`/`status` par compte, blocs d'un compte
  verrouillé gardés à la régénération, adoption d'une installation 0.8.0 (déplacement
  impossible compris), ancienne config `ensure --id` ; `logout` (un compte, plusieurs comptes,
  clé partagée, non connecté, agent verrouillé, `bw logout` en échec, `ensure` qui propose
  `login` ensuite) et `account set` (compte connecté, puis `login` au nouveau serveur et
  e-mail, doublon, rien de neuf, refus, remède proposé par `status`) ; trois sshd de test :
  `ssh` vers un hôte de chacun de trois comptes (deux serveurs), rebond qui touche deux
  comptes (une invite par compte, refus sur l'un sans blocage de l'autre).
- Intégration à deux comptes : second compte de test, créé par l'utilisateur
  (`SSHVAULT_IT2_SERVER`, `SSHVAULT_IT2_EMAIL`, `SSHVAULT_IT2_PASSWORD` dans le fichier du
  compte de test ; en mode conteneur, inscrit par le test) ; sans eux, ce volet est sauté et
  le rapport le dit. Il couvre aussi `logout --account` du second compte puis `login`, et
  `account set` aller-retour (e-mail factice puis le vrai) suivi de `login`.
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
    (`--permanent`) les éléments de son run, même en cas d'échec, et fait `bw logout`. Au début
    et à la fin, il purge aussi tout élément marqué `sshvault-test-run` (quelle que soit la
    valeur : restes d'un run interrompu), marqueur relu avant chaque suppression ; `sync` et
    `delete` sont retentés après une panne réseau passagère (DNS, connexion) ;
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
  agent dédié vide, coffre déverrouillé : la connexion passe par `ensure` et le vrai `bw` ;
  puis `import` de trois clés de test (en clair, chiffrée avec `--decrypt` par askpass, RSA
  PEM PKCS#1 convertie),
  marquées pour le nettoyage, `/proc` relevé pendant l'appel, relecture par l'autre client
  `bw` (trois champs `sshKey`, hôtes), doublon refusé, `load` et `ssh -G` ; enfin `generate`
  avec un hôte (marquée), relue par l'autre client `bw` (`ssh-keygen -y` de la clé privée
  = la ligne affichée, même empreinte), aucune ligne de commande relevée ne contenant la clé,
  `pubkey`, `load` et `ssh -G` ; et le transfert restreint : `forward add` relu par l'autre
  client `bw`, puis `ssh` vers un sshd local avec `ForwardAgent yes` (et `ssh -A`) : l'hôte
  distant ne liste que la clé transférée (chargée par `ensure --forward` et le vrai `bw`) ;
  `forward remove` : bloc retiré, sous-agent arrêté, champ retiré.
  `register.py` (mode
  conteneur) se lance seul par `SSHVAULT_IT_PASSWORD=… python register.py <url> <e-mail>`.

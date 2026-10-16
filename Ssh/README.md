# sshvault

Clés SSH dans un Vaultwarden auto-hébergé, utilisées de façon transparente par ssh.

État (0.16.0) : **plusieurs comptes** Vaultwarden utilisés en même temps (alias → serveur
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
hôte est transféré, jamais l'agent dédié entier. `sshvault lock --unload` révoque aussitôt
les clés chargées des comptes verrouillés ; `sshvault ssh-config uninstall` retire sshvault du
`ssh_config`. **Mots de passe d'hôte** : pour une machine qui n'accepte qu'un mot de passe,
`ssh <hôte>` (cible ou saut) reçoit le mot de passe rangé dans un élément « identifiant » du
coffre, par l'askpass de sshvault (`sshvault-askpass`, voir « Mots de passe d'hôte ») ; cet
élément se crée (`sshvault password add`) et se relie à ses hôtes (`sshvault password hosts`)
depuis la CLI, mot de passe jamais en argument. `bw` est
pris au chemin absolu du réglage `bw-path` s'il est posé, sinon dans le PATH.

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
5. Mots de passe d'hôte (facultatif, voir « Mots de passe d'hôte ») : dans le shell
   (`~/.bashrc`, `~/.profile`…) :
   ```
   export SSH_ASKPASS="$HOME/.local/bin/sshvault-askpass"
   export SSH_ASKPASS_REQUIRE=force
   ```
   **Attention** : avec `force`, ssh, `ssh-add` et `ssh-keygen` envoient **toutes** leurs
   invites à cet askpass (mot de passe, passphrase, question de clé d'hôte, code à usage
   unique…). Il ne répond lui-même qu'aux invites de mot de passe des hôtes du coffre et relaie
   toutes les autres au terminal (sinon à `askpass-fallback`, sinon refus) ; un programme qui
   lit son propre terminal sans terminal (cron, session graphique sans `askpass-fallback`) voit
   donc ses invites refusées.
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
sshvault lock [--account ALIAS]… [--unload]          # défaut : tous les comptes ; --unload : clés retirées des agents

sshvault load (MOTIF [--host | --name | --fingerprint | --id] | --all) [-t DURÉE] [--confirm] [--restrict] [--force]
sshvault agent status | purge | lock | unlock | stop
sshvault config get [CLÉ] | set CLÉ VALEUR | unset CLÉ   # key-ttl, auto-load, auto-restrict, auto-confirm, forward-confirm, bw-path, askpass-fallback
sshvault password list [--account ALIAS]… [--json]       # éléments identifiant à URI ssh:// (jamais le mot de passe)
sshvault password add NOM --host [USER@]HÔTE… [--user U] [--account ALIAS] [--force]   # mot de passe : terminal ou stdin
sshvault password hosts add | set  SÉLECTION [--host | --name | --id] [USER@]HÔTE… [--account ALIAS] [--force]   # set : aussi --yes
sshvault password hosts remove SÉLECTION [--host | --name | --id] [USER@]HÔTE… [--account ALIAS] [--yes]
sshvault password hosts list SÉLECTION [--host | --name | --id] [--account ALIAS]…

sshvault hosts add | remove | set  SÉLECTION [--host | --name | --fingerprint | --id] HÔTE…
sshvault hosts list SÉLECTION [--host | --name | --fingerprint | --id]
sshvault forward add | remove | set  SÉLECTION [--host | --name | --fingerprint | --id] HÔTE…
sshvault forward list SÉLECTION [--host | --name | --fingerprint | --id]
sshvault ssh-config [--print | --check]
sshvault ssh-config install | uninstall

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
  `install` et `uninstall`, qui ne lisent pas le coffre) demandent le mot de passe, puis
  gardent la session (900 s).
- Déconnexion : `sshvault logout [--account ALIAS]` (compte gardé, voir « Comptes du
  coffre »), ou `sshvault account remove ALIAS` (oublie aussi le compte).
- `lock` verrouille le coffre (`bw lock`) et oublie la session ; les clés déjà chargées
  restent utilisables jusqu'à leur durée de vie. `lock --unload` les révoque aussitôt : sous
  le verrou d'`ensure`, compte après compte, chaque agent (dédié et sous-agents) qui porte
  une clé possible du compte est vérifié comme pour `logout`, les clés du compte en sont
  retirées (une clé partagée avec un compte non verrouillé reste chargée et passe à lui ; une
  clé partagée par deux comptes verrouillés part avec le second), puis le coffre est
  verrouillé (après le retrait : la session sert à reconnaître les clés chargées avant la
  0.9.0). Agent verrouillé ou en erreur : le coffre est verrouillé quand même (un `lock`
  n'est jamais empêché), une ligne dit les clés non retirées et la commande à relancer,
  code 4. Sans `--unload`, `lock` ne touche à aucun agent.

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
  passe à l'autre compte ; une clé partie entre-temps compte comme retirée ; un agent
  verrouillé entre les deux passes donne le code 4, entrée gardée, voir « Sonde de
  verrou » ; une clé du compte chargée pendant la commande est laissée, avec un
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
  été. Interrompu (Ctrl-C, SIGTERM, SIGHUP) pendant `bw logout` (`logout`, `account set`) :
  bw est tué, son état relu (10 s au plus ; signaux retenus le temps de la relecture et de la
  pose du marqueur), la session oubliée ; le marqueur `logged-out` est posé si bw est
  déconnecté ou si son état est inconnu ; « interrompu », code 130 (`account set` : registre
  inchangé). `logout` pose un marqueur persistant `logged-out` dans le dossier du compte
  (`${XDG_DATA_HOME:-~/.local/share}/sshvault/accounts/<alias>/logged-out`, fichier
  ordinaire à côté des données de `bw` ; posé aussi quand l'état est inconnu ; il suit
  `account rename` et part avec `account remove`), retiré dès que bw est vu connecté : tout
  `bw status` qui le voit connecté (`status`, `login` même en échec « déjà connecté »,
  `account set`…) et tout déverrouillage réussi, par `unlock` comme par l'invite de `load`,
  `list` ou `ensure`. Un `ensure` sur ce compte, clé absente, échoue alors en une ligne qui
  propose `sshvault login --account ALIAS`, même sans invite possible et après un
  redémarrage ; le chemin rapide la donne sans charger la CLI quand l'agent dédié est connu
  et non verrouillé (sinon la CLI tranche). Agent verrouillé hors de sshvault (`ssh-add -x`)
  : la ligne dit « agent verrouillé » (code 3), pas « déconnecté » (voir « Agent dédié »,
  sonde de verrou). Un objet qui n'est pas un fichier ordinaire à la
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
  - Verrou : après la lecture du coffre (invites du coffre hors verrou), `load` prend le
    verrou d'`ensure` (`ensure.lock`) pour les ajouts à l'agent, le retour arrière et
    l'écriture de l'état ; tenu par un `ensure` en cours : « attente d'un chargement en cours
    (ensure)… » sur stderr, puis `load` continue ; les clés privées déjà lues restent en
    mémoire pendant l'attente. En interactif, l'attente est sans limite (Ctrl-C l'arrête) ;
    avec `--nointeraction`, elle est bornée par `SSHVAULT_ENSURE_TIMEOUT` (240 s par défaut) :
    au-delà, « verrou d'ensure tenu : rien chargé », code 4. Sous le verrou, l'agent est relu :
    verrouillé entre-temps (`agent lock`) → rien chargé, code 3 ; clé chargée entre-temps (par
    `ensure`) → « déjà chargée », rien rechargé (sauf `--force`) ; clé « déjà chargée » au
    départ mais retirée de l'agent pendant l'attente → rechargée avec les options de la
    commande (durée, `--confirm`, `--restrict` et ses contrôles, passphrase sous le verrou),
    ligne « rechargée (retirée pendant l'attente) : … ». Pour chacune, sous le verrou : son
    compte revu (une fois par compte), puis `--restrict` (hôte non littéral ou absent de
    `known_hosts` : rien chargé, code 4), puis sa clé privée relue sans invite du coffre ;
    compte déconnecté, verrouillé, changé ou `bw` en erreur, relecture en échec (invite
    nécessaire, élément absent, erreur de bw), ou clé chiffrée avec `--nointeraction` →
    « … non rechargée : … » sur stderr, les autres clés chargées, code inchangé. (Une clé
    chiffrée à charger, lue avant le verrou, fait tout refuser avec `--nointeraction` ; une
    clé à recharger était déjà chargée au départ : la sauter rend l'état d'avant l'attente,
    sans priver les autres clés.) Si la clé retirée partage son compte avec une clé à
    charger, ce compte est revu comme celui des clés à charger : fermé pendant l'attente →
    rien chargé, code 3 (règle de la 0.12.0). Chaque compte des clés à
    charger est aussi revu, comme `status` et sans invite (toujours enregistré avec le même
    serveur et le même e-mail, `bw` connecté, coffre déverrouillé) : un `logout`, `lock`,
    `account remove`, `account rename` ou `account set` passé pendant l'attente → rien
    chargé, une ligne qui nomme le compte, code 3 ; `bw status` en erreur : code 4. Coût : un
    `bw status` par compte à chaque `load`, sous le verrou (un `ensure` concurrent attend
    pendant ce temps). Valeur invalide de `SSHVAULT_ENSURE_TIMEOUT` avec `--nointeraction` :
    code 2, avant toute lecture du coffre. La passphrase d'une clé chiffrée se tape sous ce
    verrou (les `ssh` qui doivent charger une clé attendent, dans leur délai).
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
  l'agent dédié (`agent purge`, `agent lock` ou `agent stop` pour cela) ; `lock --unload`
  en retire aussi les clés des comptes verrouillés (voir « Utilisation »).
- **Sonde de verrou** : un agent verrouillé (`ssh-add -x`, par `agent lock` ou hors de
  sshvault) ne liste aucune clé, comme un agent vide. sshvault tranche alors par `ssh-add
  -D` : il réussit sur un agent vide et déverrouillé (rien à retirer), échoue sur un agent
  verrouillé (mesuré, OpenSSH 8.9p1). `ssh-add -x`/`-X` ne servent jamais de sonde.
  - Contrôles de retrait (`logout`, `account set`, `account remove`, `lock --unload`) :
    sonde seulement si l'agent ne liste aucune clé alors que son état en attend une dont la
    durée de vie n'est pas écoulée (contrôle des agents ; clé partie entre deux passes :
    agent vide = clé partie, comptée retirée ; verrouillé = code 4, entrée gardée).
  - `ensure` d'un compte déconnecté (marqueur) : dès que l'agent dédié ne liste aucune clé,
    **quel que soit son état** (état vide compris : seul compte déconnecté, puis `ssh-add
    -x`), sonde sous le verrou d'`ensure` ; « agent verrouillé » (code 3) passe avant
    « déconnecté ». Le chemin rapide ne sonde jamais : sur ce chemin seulement, il lit
    l'agent (un `ssh-add -L`) et, s'il ne liste aucune clé, laisse la CLI trancher (agent
    jamais lancé, sans socket : il répond « déconnecté » lui-même). Coût : pour un compte
    déconnecté dont l'agent dédié tourne mais est vide, chaque `ssh` vers ses hôtes charge
    la CLI et sonde, au lieu de la réponse du chemin rapide.
  - `agent unlock`, quel que soit l'état : agent qui ne liste aucune clé, état non marqué
    verrouillé (verrou posé hors de sshvault) : verrouillé → `ssh-add -X` ; vide → « agent
    déjà déverrouillé », et les entrées d'état restantes, périmées, sont retirées. Comme
    `agent lock`, `agent unlock` tient le verrou d'`ensure` pendant la saisie du mot de
    passe : un `ssh` lancé entre-temps attend, borné par son délai
    (`SSHVAULT_ENSURE_TIMEOUT`).
  - La sonde n'est pas sans perte dans tous les cas : une clé ajoutée à l'agent à la main
    (`ssh-add`, hors du verrou d'`ensure`) à l'instant même entre la liste vide et `ssh-add
    -D` serait retirée ; une clé du coffre est rechargée par `ensure` à son prochain usage.
    `sshvault load` (0.12.0) ajoute ses clés sous ce verrou : jamais retirées ainsi.
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
  `forward-confirm` (défaut `true`, voir « Transfert d'agent restreint ») ; `askpass-fallback`
  (askpass graphique de relais, voir « Mots de passe d'hôte ») ; valeurs
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
  Dans une même commande (`load`, `list`…), la session obtenue à l'invite sert jusqu'à sa
  fin, gardée en mémoire seulement (jamais écrite) : `load` relit ainsi le compte sous le
  verrou d'`ensure` sans le dire verrouillé.
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
`Include "~/.ssh/sshvault/config"` en première ligne (vos commentaires d'en-tête restent
dessous, inchangés). ssh développe ce `~` avec `$HOME`, entre guillemets aussi (mesuré,
OpenSSH 8.9p1) : la forme `~` est écrite quand `$HOME` (normalisé) est le répertoire
personnel où sshvault écrit (celui de passwd), et sert alors telle quelle sur une autre
machine au répertoire personnel différent qui partage le fichier (config versionnée par
git) ; sinon la forme absolue `Include "<répertoire personnel>/.ssh/sshvault/config"`. Le
`~` est développé à chaque lancement d'ssh avec **son** `$HOME` : un ssh lancé avec un autre
`$HOME` (`sudo` ou `su` qui garde `HOME`, script qui le change) ne trouve pas la config
générée. Les deux formes sont reconnues partout (install, uninstall, `--check`,
avertissements) ; une ligne absolue déjà en tête n'est pas réécrite :

- idempotent (ligne déjà en tête, sous toute forme : chemin réel, `~`, `~user`, relatif à
  `~/.ssh`, joker qui couvre le fichier généré pour ssh (voir plus bas), parmi plusieurs
  fichiers : rien fait) ; une ligne `Include` de sshvault
  (dont tous les arguments désignent exactement le fichier généré) placée plus bas est
  déplacée en tête ;
- une ligne à **joker** qui couvre le fichier généré (`Include ~/.ssh/*/config`) ou **mixte**
  (`Include a.conf ~/.ssh/sshvault/config`) n'est jamais supprimée ni déplacée, qu'elle soit
  plus bas ou dans un bloc `Host`/`Match` (elle peut inclure d'autres fichiers) :
  l'`Include` exact est ajouté en tête, elle reste, et un avertissement le dit sur stderr
  (numéro de ligne du fichier réécrit), code 0 : le fichier généré est alors inclus deux
  fois, sans effet néfaste (la première valeur rencontrée gagne) ; ses lignes `Match … exec`
  sont évaluées deux fois à chaque lecture de la config : `sshvault ensure` est lancé deux
  fois, et le second trouve la clé déjà chargée quand le premier l'a chargée. Un joker
  « couvre » le fichier généré comme le glob d'ssh : composant par composant (`*`, `?`,
  `[…]` ne traversent pas `/`), un nom à point initial (`.ssh`) pris seulement par un motif
  à point initial, liens symboliques suivis ; `Include ~/.ssh/*` ou `Include
  ~/*/sshvault/config` ne l'incluent pas (mesuré, OpenSSH 8.9p1) : ce sont des lignes
  ordinaires, jamais touchées. La ligne est lue comme ssh 8.9 : arguments découpés comme
  `argv_split` (guillemets `'`/`"` retirés, `\` retiré devant `\`, un guillemet ou un espace,
  gardé ailleurs ; `#` en début de mot : commentaire ; guillemet non fermé : rien), `~` et
  chemin absolu décidés sur l'argument brut (`\/…` est relatif à `~/.ssh`), puis glob :
  `\x` = `x` littéral (`con\*fig` n'est pas un joker), `?` = un octet, `[…]` avec `!` (pas
  `^`), plages et classes POSIX (`[[:alpha:]]` ; classe inconnue, ou nom de classe avec un
  `\` : l'argument n'inclut rien), `]` cherché dans tout le reste du motif (`[` sans `]` :
  littéral ; un `[…]` qui enjambe un `/` ne prend rien), `\.` vaut un point écrit
  (`~/\.ss*/…` couvre). « Couvre » est décidé en parcourant le disque comme le glob d'ssh,
  en octets : dossiers listés (`.` et `..` compris : `~/.ssh/.*/sshvault/config` couvre),
  segments sans joker vérifiés par `lstat`, liens suivis (`~/*/sshvault/config` couvre si
  `~/lien → .ssh`), `/` final exige un dossier, `..` jamais replié à l'écrit
  (`~/.ssh/absent/../sshvault/config` ne couvre pas, `~/.ssh/*/../sshvault/config` est un
  joker qui couvre). Seuls les noms d'entrées et `lstat`/`stat` sont lus, jamais le contenu
  d'un fichier ; le fichier généré et ses dossiers parents sont tenus pour existants (install
  avant le premier `ssh-config`) ; couvre = un chemin trouvé dont le chemin réel est celui du
  fichier généré (un lien symbolique oui, un lien physique non : il garderait l'ancien
  contenu après une régénération) ; au-delà de 5000 entrées de dossier examinées (comptées au
  fil de la lecture, pour toute une lecture de `~/.ssh/config`) ou de 64 composants, réponse
  textuelle (motif comparé au chemin normal et réel) ;
- un joker **voisin**, qui n'inclut pas le fichier généré mais le couvrirait si `*`, `?` et
  `[…]` traversaient `/` (`Include ~/.ssh/*`) ou si un nom à point initial pouvait être pris
  sans son point (`Include ~/*/sshvault/config`), ou les deux (`Include ~/*`), est nommé
  dès que l'`Include` de sshvault n'est pas en tête (absent, plus bas ou conditionnel) : une
  ligne par argument voisin, motif tel qu'écrit, avec la ou les raisons (« *, ? et […] ne
  traversent pas / », « un nom à point initial (.ssh) doit être écrit avec son point », qui
  nomme chaque composant à point initial que le joker prend réellement : « (.x, .ssh) »), dans
  un bloc compris,
  ligne nettoyée (caractères de contrôle et octets non UTF-8 échappés),
  jamais sur une ligne dont un autre argument couvre déjà le fichier généré, ni quand le motif
  couvre à l'écrit mais pas sur le disque (`/` final, `absent/..`) ; sur stderr pour
  `ssh-config` et chaque régénération, ligne de diff pour `--check` (code 1), avertissement
  d'`install` quand il réécrit le fichier (pas quand il refuse), numéroté dans le fichier
  réécrit ;
- une ligne `Include` de sshvault exacte **dans** un bloc `Host`/`Match` (Include
  conditionnel) n'est pas déplacée : code 4, rien modifié ; `ssh-config` et `--check` la
  signalent (« le sortir du bloc ») ; pour une ligne à joker ou mixte dans un bloc,
  `ssh-config` et `--check` proposent `install` (« ne s'applique que dans ce bloc »), sauf si
  une ligne hors bloc, au-dessus du bloc (toute ligne après une ligne `Host`/`Match` est dans
  un bloc) mais pas en tête, désigne aussi le fichier généré : sshvault
  s'applique alors partout, l'avertissement est celui d'un `Include` qui n'est pas en tête ;
- sauvegarde avant toute écriture, jamais écrasée : `~/.ssh/config.sshvault.bak`, sinon
  `.bak.1`, `.bak.2`… (0600) ; écriture atomique, mode et propriétaire conservés ; fichier
  absent : créé en 0600 (et `~/.ssh` en 0700 s'il manque), sans écraser un fichier créé
  entre-temps ;
- `~/.ssh/config` **lien symbolique** (config versionnée par git, `~/.ssh/config →
  ~/dotfiles/ssh/config`) : le lien est suivi maillon par maillon (liens relatifs résolus
  depuis le chemin réel de leur dossier, comme le noyau) et la ligne est écrite dans sa
  **cible finale**, si elle passe les contrôles qu'ssh applique au fichier qu'il lit (un
  fichier à un autre que vous ou root, ou modifiable par le groupe ou les autres, fait
  échouer ssh : « Bad owner or permissions », lien suivi ; mesuré 8.9p1), plus ceux de
  `bw-path` pour les dossiers : cible = fichier ordinaire **à vous**, non modifiable par le
  groupe ni les autres ; dossier de chaque maillon et tous ses parents jusqu'à `/` à vous ou
  à root, non modifiables par le groupe ni les autres (sticky bit compris : un maillon sous
  `/tmp` est refusé) ; pour écrire, dossier de la cible modifiable par vous (vérifié avant
  toute sauvegarde, et seulement s'il faut écrire). Écriture atomique dans le dossier de la
  cible, mode et propriétaire conservés ; sauvegarde du contenu de la cible dans
  `~/.ssh/config.sshvault.bak*` comme d'habitude ; le lien et ses maillons ne sont jamais
  modifiés ni remplacés par un fichier ; message « lien suivi : écrit dans <cible> ».
  Contrôle échoué (lien cassé, boucle, cible non ordinaire, à un autre, droits ou dossier
  ouverts, dossier de la cible non modifiable) : code 4, rien modifié, une ligne qui nomme
  le lien, la cible (boucle : la valeur du lien), la raison et l'action à faire à la main :
  « ajouter en première ligne de <cible> : Include "~/.ssh/sshvault/config" » (boucle : «
  réparer le lien <lien> puis relancer » ; cible non ordinaire : « remplacer <cible> par un
  fichier ordinaire (ou réparer le lien) puis relancer »), suivie de « ou corriger par «
  chmod g-w,o-w <chemins> » puis relancer « sshvault ssh-config install » » quand ce chmod
  lève à lui seul toutes les raisons (ssh refuse de toute façon une cible ouverte). Contrôle
  échoué mais `Include` de sshvault déjà en tête de la cible : rien à écrire, code 0, « déjà
  en tête, rien changé » et un avertissement qui nomme le lien, la cible et la raison (aucun
  pour un dossier de la cible seulement non modifiable). Aucune option pour passer outre ;
- `~/.ssh/config` non ordinaire (FIFO, dossier) : code 4, rien modifié ; chemin personnel
  avec `%`, `$` ou un joker de glob : code 4, quelle que soit la forme écrite (`Include`
  développe les tokens dans les versions récentes d'OpenSSH, pas en 8.9 ; le glob lit
  `$HOME` comme un motif).

Jamais automatique : `ssh-config` et `hosts` préviennent seulement (stderr) si la ligne
manque, est conditionnelle ou n'est pas en tête (avec les jokers voisins).

**Désinstaller.** `sshvault ssh-config uninstall` défait `install` et ce qu'écrit la
régénération, rien d'autre, sans accès au coffre :

- les lignes `Include` qui ne désignent que `~/.ssh/sshvault/config` (sous toute forme :
  chemin réel, `~`, `~user`, relatif à `~/.ssh`), en tête, plus bas ou dans un bloc
  `Host`/`Match`, sont retirées de `~/.ssh/config` (sauvegarde `~/.ssh/config.sshvault.bak*`
  d'abord, jamais écrasée ; écriture atomique, mode et propriétaire conservés) : après
  `install` puis `uninstall`, le fichier est identique à l'original, sauf dans deux cas : un
  `~/.ssh/config` créé par `install` reste là, vide ; une ligne `Include` de sshvault
  qu'`install` a déplacée de plus bas, ou une ligne `Include` à joker qu'un `install`
  antérieur à la 0.12.0 a prise pour la sienne et retirée, n'est pas remise à sa place (elle
  est dans la sauvegarde `config.sshvault.bak*` d'`install`). Une ligne qui inclut
  aussi d'autres fichiers, ou un joker qui couvre le fichier généré, est gardée, avec un
  avertissement (son numéro de ligne) ;
- `~/.ssh/sshvault/config` est supprimé ; dans `~/.ssh/sshvault/pub/`, seuls les `*.pub`
  (fichiers ordinaires) le sont, puis le dossier s'il est vide (sinon gardé, avertissement) ;
  `~/.ssh/sshvault/` lui-même reste ;
- `~/.ssh/config` lien symbolique : même règle qu'`install`, lignes retirées de la cible
  finale (lien intact, « lien suivi : écrit dans <cible> ») ; contrôle échoué avec des lignes
  de sshvault à retirer de la cible : code 4, rien modifié (ni cible, ni config générée, ni
  `pub/`), une ligne qui nomme le lien, la cible, la raison et, pour chaque ligne
  qu'`uninstall` aurait retirée, « retirer de <cible> la ligne N : <ligne> » (et le `chmod`
  comme pour `install`, puis relancer « sshvault ssh-config uninstall » ; cible illisible :
  « retirer à la main » ; non ordinaire : « remplacer <cible> par un fichier ordinaire ») ;
  dossier de la cible non modifiable : même refus s'il y a des lignes à retirer ; contrôle
  échoué sans rien à retirer de la cible (aucune ligne de sshvault, cible absente, boucle) :
  code 0, un avertissement (lien, cible, raison), cible non touchée, et le reste est
  désinstallé (config générée, `pub/`) ;
- mêmes refus qu'`install` : `~/.ssh/config` non ordinaire, ou `~/.ssh/sshvault`, sa config
  ou `pub/` d'un type inattendu (lien…) : code 4, rien modifié ; rien d'installé : « rien à
  faire », code 0 ; `--print`/`--check` exclus (code 2).

Agents, comptes, sessions et données de `bw` sont gardés (`sshvault agent stop` arrête
l'agent dédié, `sshvault account remove` oublie un compte). Pour tout retirer : `sshvault
lock --unload` (clés retirées des agents, coffres verrouillés), `sshvault logout --account
ALIAS` pour chaque compte (`bw logout`), `sshvault agent stop`, `sshvault ssh-config
uninstall`, puis supprimer le dossier `~/.ssh/sshvault/` (vide, sauf un `pub/` gardé pour
des entrées qui ne sont pas des clés publiques), les sauvegardes `~/.ssh/config.sshvault.bak*`,
le dossier `$XDG_RUNTIME_DIR/sshvault/` (sockets, états, verrou ; vidé aussi à la fin de la
session), les données (`${XDG_DATA_HOME:-~/.local/share}/sshvault/`, dont les données de `bw`
de chaque compte sous `accounts/<alias>/bw`) et la configuration
(`${XDG_CONFIG_HOME:-~/.config}/sshvault/`), et enfin la commande `sshvault` elle-même.
Mots de passe d'hôte : **d'abord** retirer `SSH_ASKPASS` (s'il désigne `sshvault-askpass`) et
`SSH_ASKPASS_REQUIRE=force` des fichiers de démarrage du shell (`~/.bashrc`, `~/.profile`…), et
ouvrir un nouveau shell, avant de désinstaller sshvault : sinon chaque invite de ssh, `ssh-add`
et `ssh-keygen` échoue (askpass introuvable). Les enregistrements des connexions
(`$XDG_RUNTIME_DIR/sshvault/pw/`, sans secret) partent avec le dossier runtime.
Après `uninstall`, `hosts`, `forward`, `import`, `generate` et `ssh-config` recréent
`~/.ssh/sshvault/`, inerte sans la ligne `Include` (avertissement habituel) ; `sshvault
ssh-config` puis `sshvault ssh-config install` remettent tout.

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

### Mots de passe d'hôte (`sshvault password`, `sshvault-askpass`)

Pour les rares machines qui n'acceptent qu'un mot de passe (CAP-11). Le mot de passe vit dans
un élément **identifiant** du coffre (créé par `sshvault password add`, ou dans le web vault),
relié à ses hôtes par ses URI :

- `ssh://hôte`, `ssh://utilisateur@hôte`, `ssh://utilisateur@hôte:port` : `hôte` est le nom
  **tapé** (`ssh hôte`, ou le nom d'un saut ProxyJump), lettres, chiffres, `.`, `-`, `_`, sans
  motif, comparé sans tenir compte de la casse ; l'utilisateur de l'URI remplace le nom
  d'utilisateur de l'élément pour cet hôte ; le port est ignoré (la topologie reste dans
  `~/.ssh/config`). Toute autre URI de l'élément (web, autre forme) est ignorée, avec un
  avertissement (`password list`, `ssh-config`). Un élément identifiant sans URI `ssh://`
  n'est pas à sshvault (ni dans `password list`, ni dans le `ssh_config`) ; `list` et `search`
  ne montrent que les clés.
- `sshvault password list [--json]` : alias, nom, hôtes (`[utilisateur@]hôte`), jamais le mot
  de passe.
- `sshvault password add NOM --host [USER@]HÔTE… [--user U] [--account ALIAS] [--force]` crée
  l'élément : `--user` = son nom d'utilisateur (utilisateur attendu des hôtes écrits sans
  `USER@`) ; chaque `--host` (plusieurs fois, ou liste à virgules ; au moins un) donne l'URI
  `ssh://hôte` ou `ssh://USER@hôte` (utilisateur encodé), jamais de port. Hôte (lettres,
  chiffres, `.`, `-`, `_`, sans motif ni `-` en tête) et utilisateur (sans blanc, caractère de
  contrôle ni `:`) vérifiés avant tout accès au coffre (code 2). Le mot de passe n'est jamais
  un argument : stdin est un terminal → saisi deux fois, masqué (vide ou différent : message
  et nouvelle saisie, trois essais, puis code 2, rien créé ; `--nointeraction` : code 2) ;
  sinon une ligne lue sur stdin (`printf '%s\n' "$MDP" | sshvault password add …` ; fin de
  ligne finale retirée ; vide, `\r` ou `\n` à l'intérieur, pas de l'UTF-8, plus de 4096
  octets ou rien lu en `SSHVAULT_PROMPT_TIMEOUT` : code 2). Stdin terminal mais sshvault pas
  au premier plan : code 2. Deux `--host` de même paire attendue (`db` et `admin@db` avec
  `--user admin`) : une seule URI, la première. Élément écrit sur stdin de `bw create`, relu et comparé (nom, utilisateur,
  mot de passe, URI) ; `bw create` en échec ou bloqué : `sync`, puis recherche d'un nouvel
  élément identifiant de même nom et mêmes URI, rejeu une seule fois, jamais de doublon.
  Compte rendu sur stdout (`élément « NOM » créé (id …)`), jamais le mot de passe ;
  `ssh_config` régénéré. Un seul compte écrit (`--account`, sinon le compte par défaut
  unique).
- **Doublon** : un hôte et son utilisateur attendu (celui de l'URI, sinon le nom
  d'utilisateur de l'élément) déjà portés par un autre élément identifiant (de tout compte
  lisible sans invite) : code 2, l'autre élément nommé, rien écrit ; `--force` écrit quand même
  (avertissement après l'écriture relue — rien n'est annoncé si elle échoue — : le premier
  élément, par nom, compte, id, gagne). Création relue différente : le message donne la
  commande exacte de suppression (`BITWARDENCLI_APPDATA_DIR=… <bw> delete item <id>`). Un hôte sans utilisateur (ni `USER@`, ni `--user`) n'est jamais un doublon.
- `sshvault password hosts add|remove|set|list SÉLECTION [USER@]HÔTE…` : URI `ssh://` d'un
  seul élément identifiant à URI `ssh://`, choisi comme pour `hosts` (`--name`, `--id`,
  `--host` : motif glob d'hôte ; défaut : nom ou hôte ; `--id` choisit aussi un élément
  identifiant sans URI `ssh:`, par exemple après `set ""`). `list` : `[user@]hôte` attendus,
  comme `password list` (`list --id` d'un élément sans hôte : code 0, rien affiché).
  **Paire attendue** : (hôte sans tenir compte de la casse, utilisateur de l'URI, sinon nom
  d'utilisateur de l'élément), port ignoré. `add` : URI ajoutées après les URI `ssh://`
  actuelles ; paire attendue déjà présente : « déjà présent » avec l'URI qui la porte, rien
  écrit ; une paire répétée dans la commande (`add X db admin@db`, utilisateur `admin`) n'est
  écrite qu'une fois. `remove` : retire les URI de ces paires **exactes** (`remove X root@db`
  retire `ssh://root@db:22`, pas `ssh://db`) ; paire absente : code 1, rien écrit, chaque paire
  absente dite sur sa ligne ; une paire qui ne correspond que par l'utilisateur attendu nomme
  l'URI réelle et la forme à retirer (`ssh://db` porte `admin@db` par l'utilisateur de
  l'élément : retirer « db » ; `ssh://admin@db` porte `admin@db` par son utilisateur : retirer
  « admin@db »). `set` : les URI `ssh://` valides deviennent cette liste, dans l'ordre donné
  (une URI déjà là pour une paire de la liste — exacte, sinon attendue — est gardée telle
  quelle, port compris : `set X admin@db` garde `ssh://db` d'un élément d'utilisateur `admin`,
  sans perte ni question) ; `set X ""` les retire toutes. Restent tels quels : nom, notes,
  champs, dossier, favori, nouvelle demande du mot de passe maître (`reprompt`), organisation,
  collections, historique des mots de passe, nom d'utilisateur, mot de passe, TOTP, passkeys,
  autres URI (web, `ssh:` invalides) et le `match` de chaque URI gardée ; écriture relue et
  comparée sur tout cela, rejouée une fois au plus et seulement si l'élément relu n'a pas
  changé ; `ssh_config` régénéré. Avec `--force`, l'avertissement de doublon n'est dit
  qu'une fois l'écriture relue.
- `remove` et `set` qui retirent des URI : l'élément et chaque URI perdue (complète, port
  compris) sur stderr, puis « confirmer ? [o/N] » au terminal (`o`, `oui`, `y` ou `yes`, sans
  tenir compte de la casse : écrit ; toute autre réponse, délai `SSHVAULT_PROMPT_TIMEOUT` ou
  fin de saisie : code 1, rien écrit). Sans terminal ou avec `--nointeraction` : la liste, code 2, rien écrit, sauf
  `--yes`. Rien de perdu : pas de question.
- `sshvault ssh-config` ajoute, après les blocs d'identité, un bloc par élément, sans
  directive, gardé même avec `auto-load false` :
  ```
  # Routeur perso 22222222-2222-4222-8222-222222222222 mot de passe
  Match originalhost routeur exec "'/home/alice/.local/bin/sshvault' ensure --password --account perso --id 22222222-2222-4222-8222-222222222222 --host routeur"
  ```
  Même hôte et même utilisateur dans deux éléments : avertissement, le premier (nom, compte,
  id) gagne. Même hôte avec une clé et un mot de passe : les deux blocs, le serveur choisit.
  Un compte illisible à la régénération garde ses blocs tels quels.
- À la connexion, `ensure --password` (ligne `Match exec`) enregistre le ssh appelant dans
  `$XDG_RUNTIME_DIR/sshvault/pw/<pid du ssh>.json` (pid et date de début du ssh, compte,
  élément, hôte ; aucun secret ; 0600 dans un dossier 0700 ; enregistrements des ssh finis
  retirés) et déverrouille le compte s'il le faut (mêmes règles d'invite que le chargement
  automatique : une invite au plus par compte et par connexion, aucune sous `BatchMode=yes`
  ou `--nointeraction`). Rien sous `ssh -G`/`-O`. Code 0 (sauf usage, 2) : un échec est dit
  en une ligne, la connexion continue.
- ssh appelle alors `sshvault-askpass` (avec `SSH_ASKPASS_REQUIRE=force`). Il donne le mot de
  passe du coffre **seulement** si : son parent est le ssh enregistré (même pid **et** même
  date de début) ; l'invite est exactement `<utilisateur>@<h>'s password: ` (méthode
  password) ou `(<utilisateur>@<h>) Password: ` (keyboard-interactive) ; l'utilisateur est
  celui attendu pour un hôte enregistré (`ssh root@routeur` avec un élément `admin` : relais) ;
  ce mot de passe n'a pas encore été donné à ce ssh. Il est lu par `bw get item` à ce
  moment-là (session rangée ; jamais d'invite du mot de passe maître dans l'askpass : coffre
  verrouillé, une ligne, puis relais), gardé en mémoire et écrit seulement sur la sortie de
  l'askpass : jamais en argument, dans un fichier, un état ou un journal.
- Une fois par connexion **et par saut** : `ssh B` via le rebond A (ProxyJump), A et B à
  mot de passe, aboutit sans saisie ; chaque ssh (le saut `-W` est un ssh à part) a son
  enregistrement. Mot de passe refusé par le serveur : la nouvelle invite affiche « mot de
  passe du coffre refusé pour <u>@<hôte> (<nom>) » et va au terminal.
- **Relais** de toute autre invite (question de clé d'hôte, passphrase, code à usage unique,
  confirmation `-c` d'un agent avec `SSH_ASKPASS_PROMPT=confirm`) : `/dev/tty` ouvrable →
  invite au terminal (écho coupé, sauf la question de clé d'hôte) ; sinon le réglage
  `askpass-fallback` (mêmes arguments et environnement) ; sinon code 1 (ssh : mot de passe
  vide, « Host key verification failed. »).
- `askpass-fallback` : `sshvault config set askpass-fallback /usr/bin/ssh-askpass` (chemin
  absolu d'un fichier exécutable ; l'askpass de sshvault refusé ; même avertissement que
  `bw-path` s'il est modifiable par d'autres). Défaut : `/usr/bin/ssh-askpass` s'il est
  exécutable et que `DISPLAY` est défini.
- Les invites de sshvault (déverrouillage, passphrase d'une clé à `load`, `import`, mot de
  passe de verrou de l'agent) et ses enfants (`ssh-add`, `ssh-keygen`, `ssh-agent`) ne
  passent jamais par son askpass : `SSH_ASKPASS` y devient `askpass-fallback` (absent :
  retiré) et `SSH_ASKPASS_REQUIRE=force` est retiré, comme si vous ne l'aviez pas posé : le
  terminal d'abord, l'askpass graphique seulement sans terminal (`prefer` l'aurait préféré au
  terminal dès que `DISPLAY` est défini).
- Hors champ : codes à usage unique, changement d'un mot de passe expiré, enveloppe `sshpass`
  (ces invites sont relayées telles quelles).

### Codes de sortie

| Code | Sens |
|---|---|
| 0 | succès |
| 1 | `search`, `load`, `hosts`, `forward`, `pubkey`, `deploy`, `password hosts` : aucun résultat ; `password hosts remove` : paire absente, `password hosts remove`/`set` : URI à retirer non confirmées — autre réponse que `o`/`oui`/`y`/`yes`, délai ou fin de saisie — (rien écrit) ; `import` : clé déjà dans le coffre (rien créé) ; `generate` : nom déjà pris, sans `--force` (rien généré) ; `hosts remove`, `forward remove` : hôte absent (rien écrit) ; `ssh-config --check` : pas à jour (contenu, droits, fichier en trop ou non ordinaire), ou ligne `Include` absente, conditionnelle ou pas en tête |
| 2 | usage (option ou argument invalide ; `load` sans sélection ni `--all`) ; comptes : alias invalide ou inconnu, alias ou couple serveur + e-mail déjà enregistré, serveur ou e-mail invalide, écriture sans `--account` quand plusieurs comptes sont possibles, `login` ou `logout` sans `--account` avec plusieurs comptes, aucun compte par défaut, `account rename` vers un alias pris, `account add` : dossier `accounts/<alias>` existant, `account set` sans `--server` ni `--email`, `account set` : registre refusé après la déconnexion (couple pris entre-temps ; ce qui est déjà fait est dit) ; `logout`, `account set` : `bw-path` invalide (rien fait) ; durée invalide ; `config.json` invalide, illisible ou aux droits inattendus ; `config set bw-path` : chemin relatif, absent, avec un caractère de contrôle, ou pas un fichier ordinaire exécutable ; `bw-path` invalide dans `config.json` ; hôte invalide ; sélection de `hosts` ou `forward` qui désigne plusieurs éléments ; `import` : fichier refusé (illisible, pas une clé privée, type ou format non accepté), `--name` avec plusieurs fichiers ; `generate` : type, bits, nom ou commentaire refusés ; `deploy` : cible, port ou options ssh invalides ou refusées ; délai `SSHVAULT_DEPLOY_TIMEOUT` invalide ; `load --nointeraction` : `SSHVAULT_ENSURE_TIMEOUT` invalide (rien lu, rien chargé) ; `password add` : nom, hôte ou utilisateur refusé, mot de passe vide, saisies différentes ou vides trois fois, stdin de plus d'une ligne, pas de l'UTF-8, de plus de 4096 octets ou sans rien en `SSHVAULT_PROMPT_TIMEOUT`, terminal pas au premier plan, saisie au terminal avec `--nointeraction` (rien créé) ; `password add`, `password hosts add`/`set` : hôte et utilisateur déjà portés par un autre élément identifiant, sans `--force` (rien écrit) ; `password hosts remove`/`set` : URI à retirer sans terminal ou avec `--nointeraction`, sans `--yes` (rien écrit) |
| 3 | aucun compte enregistré (`ssh-config` n'écrit alors rien, `lock` compris), non connecté (« lancer sshvault login » ; `ensure` d'un compte déconnecté par `logout` : « lancer sshvault login --account ALIAS »), ou coffre verrouillé : aucune invite possible, invite annulée ou sans réponse, mot de passe refusé ; agent dédié arrêté (`agent status`, `lock`, `unlock`) ou verrouillé (`ensure --forward` compris) ; passphrase d'une clé refusée ou impossible à saisir (`load`, `import`) ; `load` : compte déconnecté, verrouillé, retiré, renommé ou modifié pendant l'attente du verrou d'`ensure` (rien chargé) ; `login` refusé par bw (mot de passe, limite de débit des connexions du serveur — réessayer dans une minute —, réseau) |
| 4 | erreur du backend : `bw` introuvable, non exécutable, interpréteur ou chargeur absent, format non exécutable (au chemin du réglage `bw-path` compris, le PATH n'étant alors pas essayé), en erreur, réponse illisible, délai dépassé ; magasin de session inutilisable ; agent dédié : `XDG_RUNTIME_DIR` relatif, non privé ou hors tmpfs, chemin du socket trop long, agent tiers sur le socket, OpenSSH < 8.9, `--restrict` (élément sans hôte, hôte non littéral ou absent de `known_hosts`), sous-agent de transfert en erreur (`agent status`, `stop`, `purge`, `lock`), clé publique illisible ou différente de la clé privée, `ssh-add`/`ssh-agent` en erreur ; écriture de `config.json` impossible ; écriture des hôtes ou des transferts dans le coffre non aboutie ou non vérifiée (y compris écrits mais `ssh_config` non régénéré) ; `password add`, `password hosts` : création ou écriture de l'élément identifiant non aboutie ou non vérifiée (y compris écrite mais `ssh_config` non régénéré) ; `ensure --forward` : `forward-confirm` sans askpass, élément qui ne déclare plus ce transfert, chemin du socket de transfert trop long ; `import` : création non aboutie ou non vérifiée (y compris clé importée mais `ssh_config` non régénéré), copie impossible dans un tmpfs privé (`--decrypt`), `ssh-keygen` absent ou en erreur ; `generate` : tmpfs privé inutilisable, `ssh-keygen` absent ou en erreur, création non aboutie ou non vérifiée (clé perdue, dit), clé créée mais `ssh_config` non régénéré ; `pubkey` : clé publique d'un élément illisible ; `deploy` : `ssh` absent, en échec ou sans réponse (`SSHVAULT_DEPLOY_TIMEOUT`), réponse inattendue de la cible, échec partiel (clés déjà ajoutées dites, puis code 4), clé publique illisible ; `ssh_config` généré impossible à écrire (chemin avec `"`, `\`, `${`, fichier non ordinaire, droits) ; répertoire personnel inconnu ; `ssh-config install` refusé (fichier non ordinaire, lien symbolique dont la cible échoue aux contrôles alors qu'il faudrait y écrire — lien cassé, boucle, cible non ordinaire, à un autre, droits ou dossier ouverts, dossier de la cible non modifiable —, `Include` exact conditionnel, chemin personnel avec `%`, `$` ou joker) ; `ssh-config uninstall` refusé (`~/.ssh/config` non ordinaire, ou lien symbolique dont il faudrait modifier la cible refusée — lignes de sshvault à retirer — ou dont la cible est illisible ou non ordinaire, `~/.ssh/sshvault`, sa config ou `pub/` d'un type inattendu : rien modifié) ; `lock --unload` : agent verrouillé ou en erreur (coffre verrouillé quand même, clés laissées) ; adoption de l'installation 0.8.0 impossible (rien modifié ; `account add` refusé tant qu'elle n'est pas faite) ; `account rename` : destination existante ou déplacement impossible (rien changé) ; `account remove` : données locales impossibles à supprimer (compte gardé), magasin de session ou agent en erreur ou verrouillé (clés laissées, état gardé) ; `logout`, `account set` : agent en erreur ou verrouillé (rien modifié, ou état partiel dit), `bw logout` en échec ou sans réponse (compte toujours connecté, ou état inconnu ; `account set` : registre inchangé), `account set` : écriture du registre impossible après la déconnexion (ce qui est déjà fait est dit) ; `ssh-config --check` : `bw` en erreur, même pour un compte déconnecté ; erreur interne ; `load` : « verrou d'ensure tenu : rien chargé » (`--nointeraction`, attente au-delà de `SSHVAULT_ENSURE_TIMEOUT`), `bw status` en erreur à la relecture d'un compte sous le verrou |
| 130 | interrompu (Ctrl-C, SIGTERM, SIGHUP) ; pendant `bw logout` (`logout`, `account set`) : état relu, marqueur `logged-out` posé si bw est déconnecté ou si son état est inconnu |

`agent status`, `stop`, `purge`, `lock` : code de l'agent dédié (`status` : 0 actif, 3 arrêté),
mais 4 si un sous-agent de transfert est en erreur (agent tiers sur son socket…), chacun dit
en une ligne ; les autres sous-agents sont traités quand même.

`ensure` : 0 si la clé est présente ou chargée, et pour `ssh -G` ; sinon le code de
l'erreur (3 coffre verrouillé, compte déconnecté ou agent verrouillé — même hors de
sshvault —, 4 backend, agent, délai global…), sans
effet sur ssh. `ensure --forward` : de même (0 aussi pour un saut `ssh -W` dont le socket
existe) ; la connexion se fait sans clé transférée. `ensure --password` : 0 (y compris coffre
verrouillé sans invite possible, dit en une ligne), sauf usage (2).

`sshvault-askpass` : 0 et la réponse sur stdout (mot de passe du coffre, ou saisie relayée au
terminal) ; code de `askpass-fallback` s'il a été lancé ; 1 sans terminal ni fallback, ou
saisie annulée.

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
| `SSHVAULT_ENSURE_TIMEOUT` | délai global d'un `ensure` depuis son démarrage, attente du verrou comprise, en secondes, 0 < v ≤ 86400 (défaut 240) ; borne aussi l'attente d'`ensure.lock` par `load --nointeraction` (interactif : sans limite) |
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
| `SSHVAULT_TEST_GUARD` | tests seulement : `warn` ramène à un avertissement la garde de fin de session sur les dossiers sshvault réels existants (défaut : échec) |
| `SSHVAULT_KNOWN_HOSTS` | fichiers known_hosts passés à `ssh-add -H` pour `--restrict`, séparés par `:` (défaut : ceux d'`ssh-add`) |
| `BW_CLIENTID`, `BW_CLIENTSECRET` | clé API pour `sshvault login --apikey` (lues par `bw`) |
| `SSH_ASKPASS`, `SSH_ASKPASS_REQUIRE`, `DISPLAY`, `WAYLAND_DISPLAY` | choix de l'invite (`man ssh`) ; `SSH_ASKPASS` = `sshvault-askpass` : remplacé par `askpass-fallback` (ou retiré) et `SSH_ASKPASS_REQUIRE=force` retiré pour les invites de sshvault et ses enfants (terminal d'abord) |
| `SSH_ASKPASS_PROMPT` | lu par `sshvault-askpass` : `confirm` (confirmation d'un agent) ou `none` : relais seul |
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
  `load` sous `strace -f` : seules écritures, le fichier d'état (et son temporaire) et le
  verrou `ensure.lock` (vide). `load` lancé pendant que `ensure.lock` est tenu : coffre lu,
  attente, rien ajouté avant la libération ; clé chargée ou agent verrouillé pendant
  l'attente ; clé « déjà chargée » retirée pendant l'attente : rechargée avec les options de
  la commande (état et `agent status`), sautée si son compte est verrouillé ou déconnecté
  (deux comptes) ou `bw status` en erreur, relecture en échec (élément supprimé, `bw get` en
  erreur), clé chiffrée avec `--nointeraction` ; `--restrict` : rechargée avec ses hôtes, clé
  sans hôte ou hôte absent de `known_hosts` (rien chargé, code 4) ; échec en cours de
  rechargement : retour arrière. Concurrence réelle : `load` qui attend derrière un vrai
  `sshvault logout --account` (bloqué dans `bw logout` par une enveloppe de `bw`) : rien
  chargé, code 3 ; derrière un vrai `sshvault ensure` (bloqué dans `bw get`) : la clé chargée
  par `ensure` est « déjà chargée », rien rechargé. Agent arrêté pendant l'attente de `load
  --confirm`, relancé sous le verrou sans askpass utilisable : avertissement affiché.
- `tests/test_sshconfig.py` valide le fichier généré avec l'OpenSSH du poste :
  `ssh -G -F <config de test qui l'inclut>` (agent dédié, une seule `identityfile`,
  `identitiesonly yes`, HOME et `XDG_RUNTIME_DIR` avec espace et `%`), puis `ssh -vvv`
  arrêté avant l'authentification (`ProxyCommand true`) pour voir le `.pub` réellement
  chargé. Le faux `bw` sait faire `edit` (élément lu sur stdin, argv journalisé) et
  simuler un `edit` en échec, bloqué, passé puis bloqué, ou en concurrence. `ssh-config
  uninstall` : `install` puis `uninstall` rendent `~/.ssh/config` identique (mode compris)
  et `ssh -G` ne montre plus l'agent dédié ; Include mixte, joker, plus bas, dans un bloc,
  lien, FIFO, `pub/` avec d'autres fichiers. `~/.ssh/config` lien symbolique (HOME de test
  sous `/run/user/<uid>`, seul dossier du poste sans parent ouvert à d'autres) : lien vers
  une config git, chaîne de liens relatifs, `..` sous un `~/.ssh` lien, déjà en tête (forme
  `~` ou absolue), install puis uninstall (cible rendue identique, lien intact à chaque
  étape) ; refus sans rien modifier (arborescence comparée) : lien cassé, boucle, FIFO, cible
  0664/0606, dossier g+w (chmod proposé), maillon sous un dossier à sticky bit, `/tmp`,
  dossier de la cible non modifiable, cible à un autre ou à root, chaîne qui ne mène pas à la
  cible, cible remplacée ou disparue entre le contrôle et l'écriture ; rien à écrire malgré un
  contrôle échoué (déjà en tête ; uninstall sans ligne, lien cassé, boucle, ligne mixte) :
  code 0 et avertissement ; `ssh -G -F` réel qui lit `Include "~/…"` avec le HOME du banc (et
  rien avec un autre HOME) ; HOME différent : forme absolue. `install` : joker ou ligne mixte
  plus bas, dans un bloc ou en tête (gardé, avertissement), exact dans un bloc (refus), puis
  `uninstall`.
  Jokers : chaque forme mesurée (`~/.ssh/*`, `~/*/sshvault/config`, `~/.ssh/*/config`,
  `~/.*/sshvault/config`, `?`, `[s]`, `[!x]`, `[.]`…) comparée à la réponse d'`ssh -G` du
  poste ; formes relatives à `~/.ssh`, jokers sous un lien symbolique ; `install`,
  `ssh-config`, `--check` et `uninstall` avec des jokers qui ne couvrent pas le fichier généré
  (plus bas, en tête, dans un bloc, parmi d'autres fichiers). Échappements, guillemets,
  classes POSIX, `[…]` (`^`, `]` et `-` littéraux, plages, `[` sans `]`, `/`),
  `\` final, guillemets au milieu d'un mot, `#`, guillemet non fermé, parcours du disque (`.*`,
  `/` final, `absent/..`, `*/..`, lien atteint par un joker, octets d'un HOME `josé`, `[…]`
  qui enjambe `/`) : chaque forme mesurée confrontée à `ssh -G` du poste ; config pas encore
  écrite, parcours borné, `~user` avec octet nul, `\/…` relatif à `~/.ssh` (test unitaire :
  un témoin `ssh -G` lirait sous le vrai `~/.ssh`) ; `~user/…` (exact, joker couvrant,
  voisin, autre utilisateur, inconnu) avec `pwd.getpwnam` remplacé dans le processus de test
  par un HOME temporaire, jamais le vrai passwd ni le vrai HOME ; découpage `argv_split` ;
  jokers voisins (une raison, deux raisons, noms des composants à point initial réellement
  pris, aucune ligne quand l'`Include` est en tête, avertissement d'avant inchangé sans voisin)
  dans `ssh-config`, `--check` et `install` ; `_dot_taken` confronté à `_match` sur toutes ces
  formes (chemin normal et réel, `/` traversé ou non), longue suite de `*` (coût compté) ;
  joker ou ligne mixte dans un bloc avec une ligne hors bloc au-dessus du bloc : « pas en
  tête » (`ssh-config`, `--check`), puis `install` (Include exact en tête, ligne du bloc
  gardée, « inclus deux fois ») et plus aucun avertissement.
- `tests/test_passwords.py` (mots de passe d'hôte) : URI `ssh://` acceptées et refusées,
  éléments identifiant du faux `bw`, `password list`, blocs à mot de passe (après les blocs
  d'identité, `auto-load false`, compte illisible gardé, `--check`, régénération par `hosts
  add` sans appel `bw` de plus), `ensure --password` sous un faux parent `ssh` (enregistrement
  0600/0700 sous son pid, aucun mot de passe lu, enregistrements morts retirés, `ssh -G` par le
  chemin rapide, usage, une seule invite pour deux hôtes, `BatchMode`), `sshvault-askpass`
  (donné une fois puis « refusé » et relais au terminal, keyboard-interactive, utilisateur
  différent, parent inconnu, question de clé d'hôte avec écho, sans terminal ni fallback,
  `askpass-fallback` avec mêmes arguments et environnement, `confirm`, coffre verrouillé,
  module léger sans `bw`), invites internes au terminal sous `SSH_ASKPASS_REQUIRE=force`
  (déverrouillage, passphrase). Bout en bout : deux serveurs SSH paramiko locaux
  (`tests/pwserver.py`, dépendance de test seulement : A par mot de passe, B par
  keyboard-interactive derrière A par ProxyJump), un vrai `ssh` et l'askpass du banc :
  `ssh B` aboutit sans saisie, argv de tous les processus relevés pendant la connexion et
  fichiers du HOME et du runtime relus (aucun mot de passe) ; mot de passe refusé puis saisi
  au terminal ; question de clé d'hôte relayée ; éléments créés par `password add` (stdin)
  puis `ssh B` via A sans saisie.
- `tests/test_password_write.py` (écriture des éléments identifiant) : `[user@]hôte` acceptés
  et refusés (jamais de port), URI gardées à leur place ou réordonnées ; `password add` par
  stdin (une ligne, refus avant tout appel `bw`) et au terminal (stdin sur le pty : deux
  saisies masquées, vide, trois paires différentes, `--nointeraction`), doublon hôte +
  utilisateur (même compte, autre compte, `--force`), échecs de `bw create` (passé puis erreur,
  bloqué, réponse illisible : rien rejoué ; erreur ou blocage une fois : rejeu unique ; erreur
  deux fois, mot de passe relu différent, rien enregistré), SIGTERM pendant `bw create` ;
  `password hosts` (list, add, « déjà présent », remove exact confirmé ou refusé au terminal,
  set sans terminal : code 2 puis `--yes`, `set ""`, doublon, sélection ambiguë) ; échecs de
  `bw edit` (passé puis erreur ou bloqué, une fois, deux fois, élément changé par un autre
  client, relu différent) ; nom, notes, champs, utilisateur, mot de passe, TOTP et autres URI
  inchangés ; aucun mot de passe en argument (`FAKE_BW_LOG`, `/proc`) ni sur une sortie.
  Intégration : `password add` (stdin), `password hosts add`, `remove` (sans puis avec
  `--yes`), `set --yes` sur le vrai Vaultwarden, élément relu par `bw get item` d'un autre
  client, supprimé en fin de run (marqueur).
- `tests/test_it_accounts.py` : lecteur du fichier des comptes de test d'intégration
  (`tests/integration/accounts.py`), sans réseau ni vrai fichier : comptes valides et alias,
  doublon, champ manquant, vide ou de type faux, clé inconnue, TOML illisible, fichier absent
  (avec ou sans `account.env`), `SSHVAULT_IT_ENV`, `SSHVAULT_IT_ACCOUNTS` (`~` développé) vers
  un chemin absent, un dossier, une FIFO, un lien cassé ou un chemin illisible, fichier par
  défaut présent mais inutilisable (échec, raison nommée) ; aucune valeur dans les messages.
- `tests/test_it_pty.py` : `pty_login` de l'intégration, sans réseau ni vrai sshvault (faux
  paquet `sshvault` par PYTHONPATH, qui laisse un petit-enfant écrire sans fin sur le terminal
  et garder la sortie standard ouverte) : reste du terminal et sortie standard lus 5 s au
  plus chacun.
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
  e-mail, doublon, rien de neuf, refus, remède proposé par `status`), `lock --unload` (deux
  comptes, clé partagée, agent verrouillé, `bw lock` en échec), sonde de verrou (agent vidé
  à la main ou pendant le retrait, verrouillé par `ssh-add -x` hors de sshvault avant
  `ensure`), `bw logout` interrompu (déconnecté, toujours connecté, état inconnu, second
  signal pendant la relecture) ; trois sshd de test :
  `ssh` vers un hôte de chacun de trois comptes (deux serveurs), rebond qui touche deux
  comptes (une invite par compte, refus sur l'un sans blocage de l'autre).
- Intégration à plusieurs comptes : tous les comptes du fichier des comptes de test (au
  moins 2, créés par l'utilisateur ; en mode conteneur, 3 inscrits par le test), alias `it`
  (1er, coffre peuplé), `it2`, `it3`… dans l'ordre du fichier ; un seul compte : ce volet est
  sauté et le rapport le dit. Login de chacun, `list`, `account default`, une clé générée et
  marquée dans chaque compte au-delà du premier (éléments marqués purgés au début et à la
  fin), `ssh-config`, `ensure` ; puis sur **chaque** compte, `it` compris, `logout --account`
  suivi de `login`, et `account set` aller-retour (e-mail factice puis le vrai) suivi de
  `login` ; enfin `lock`. Rapport et messages d'échec masqués pour tous les comptes.
- Mesure du code de `sshvault login` (opt-in) : `SSHVAULT_IT_LOGIN_REPEAT=N` lance N
  `sshvault login` (pty) suivis de `sshvault logout`, au moins 7 s entre deux essais, HOME
  temporaire, 1er compte ; le rapport donne le rc, la durée et les invites de chaque essai,
  la sortie et la fin masquée du terminal de chaque échec, et le décompte par code ; le test
  échoue si un essai rend autre chose que 0, ou si un `logout` entre deux essais échoue
  (anomalie dite ; `bw logout` à la main avant l'essai suivant, son échec arrête la série).
  Sans la variable : sauté. Mesuré le 2026-10-14 (N = 20) : 12 essais à 0, puis 6 sur 8 à
  3, refusés par la limite de débit des connexions de Vaultwarden (« Rate limit exceeded.
  Try again later. »). Les autres tests d'intégration attendent alors 60 s et réessaient
  (3 fois au plus, chaque attente dans le rapport), pour `sshvault login` comme pour le
  `bw login` du peuplement.
- En fin de session, les tests vérifient qu'aucun de leurs processus ne reste (agent,
  surveillant, sshd, `bw`, askpass, `ensure`), que `~/.ssh` réel est inchangé,
  qu'aucun dossier sshvault réel (socket, données, config) n'a été créé, et que rien n'a
  changé dans ceux qui existaient déjà (instantané récursif : mode, taille, date, inode de
  chaque chemin ; l'échec liste les chemins changés). Un usage réel de sshvault pendant les
  tests (un `ssh` qui charge une clé…) change ces dossiers : `SSHVAULT_TEST_GUARD=warn` ramène
  alors ce seul contrôle à un avertissement (`~/.ssh` modifié et dossier créé restent des
  échecs).
- L'intégration (`-m integration`, `bw` par `SSHVAULT_BW` ou le PATH) a deux modes :
  - **comptes de test** (défaut) : fichier TOML `~/.config/sshvault-test/accounts.toml`
    (0600, hors git ; chemin remplaçable par `SSHVAULT_IT_ACCOUNTS`, `~` développé : un chemin
    absent, un lien cassé, autre chose qu'un fichier ordinaire ou un chemin illisible fait
    échouer la session, chemin et raison nommés), à écrire d'après
    `tests/integration/accounts.example.toml` : un bloc `[[account]]` par compte (`server`,
    `email`, `password`), `node_extra_ca_certs` commun en option (passé à `bw` par
    `NODE_EXTRA_CA_CERTS`). Lu par `tomllib` (Python 3.11+) ou `tomli` (Python 3.10,
    dépendance de test seule). Clé inconnue, champ manquant ou vide, type faux, serveur ou
    e-mail invalide pour sshvault, doublon (serveur et e-mail normalisés comme le registre de
    sshvault : casse, `/` final, port par défaut), certificat `node_extra_ca_certs` qui n'est
    pas un fichier ordinaire lisible (`~` développé, chemin rendu absolu) ou TOML illisible
    (ligne et colonne seulement) : la session échoue, avec le numéro du compte et le nom de la
    clé, jamais une valeur. Fichier ouvert au groupe ou aux autres, ou d'un autre
    propriétaire : avertissement seul (sortie de pytest et rapport). Les messages masquent les
    valeurs de tous les comptes à la fois (la plus longue d'abord), et aussi le serveur tel
    que sshvault l'affiche (normalisé), son nom d'hôte seul et le chemin du certificat.
    Fichier par défaut absent (sans `SSHVAULT_IT_ACCOUNTS`) : intégration sautée (l'ancien
    `account.env`, s'il existe encore, est signalé : il n'est plus lu ; `SSHVAULT_IT_ENV`
    défini : échec qui nomme `SSHVAULT_IT_ACCOUNTS`) ; présent sans être un fichier ordinaire
    utilisable : échec. Valeurs jamais affichées ; mot de passe par `--passwordenv` ;
    données `bw` dans des dossiers temporaires supprimés à la fin. Le test crée 2 éléments SSH et 1 login marqués
    `sshvault-test-run=<uuid>`, pilote sshvault, puis supprime définitivement
    (`--permanent`) les éléments de son run, même en cas d'échec, et fait `bw logout`. Au début
    et à la fin, il purge aussi tout élément marqué `sshvault-test-run` (quelle que soit la
    valeur : restes d'un run interrompu), marqueur relu avant chaque suppression ; `sync` et
    `delete` sont retentés après une panne réseau passagère (DNS, connexion) ;
  - **conteneur** (`SSHVAULT_IT_MODE=container`) : Vaultwarden 1.37.4 sur un port libre de
    127.0.0.1, 3 comptes créés par l'API (crypto d'inscription Bitwarden, dépendance de test
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

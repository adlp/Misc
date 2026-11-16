# sshvault — Cheat Sheet

Aide-mémoire par cas d'usage. Référence complète : [README.md](README.md). Aide de chaque commande :
`sshvault <commande> [<sous-commande>] --help`.

sshvault range des clés SSH et des mots de passe d'hôte dans un Vaultwarden (via le CLI `bw`) et fait
utiliser ces clés par `ssh` sans rien changer à vos habitudes : `ssh <hôte>` charge seul la clé voulue
dans un agent dédié.

Option globale, **avant** la commande : `--nointeraction` = ne rien demander jamais (code 3 si une saisie
serait nécessaire).

```bash
sshvault --nointeraction list   # pas d'invite : coffre verrouillé = code 3
```


## Installation et premiers pas

```bash
uv tool install ./Ssh                 # depuis la racine de Misc ; --force pour réinstaller
sshvault --help                       # installé dans ~/.local/bin/sshvault
```

`bw` (CLI Bitwarden) doit être installé (voir README, « Installation »). Par défaut sshvault le cherche dans
le `PATH` ; le `ssh_config` généré tourne dans l'environnement de ssh, dont le `PATH` peut ne pas contenir
`~/.local/bin` : donner le chemin absolu une fois pour toutes.

```bash
sshvault config set bw-path ~/.local/bin/bw   # chemin absolu d'un exécutable
sshvault status                               # 1re ligne : « bw : <chemin> (réglage bw-path) »
sshvault config unset bw-path                 # retour au PATH
```

Premier compte, connexion, déverrouillage :

```bash
sshvault account add perso --server https://vault.example.org --email alice@example.org
sshvault login                        # interactif : bw demande le mot de passe maître
sshvault unlock                       # déverrouille, garde la session (900 s par défaut)
sshvault unlock --ttl 3600            # durée de la session, en secondes
sshvault status                       # état de chaque compte (0 = déverrouillé, 3 sinon)
sshvault lock                         # verrouille le coffre et oublie la session
```

```bash
sshvault login --apikey               # par clé API (BW_CLIENTID / BW_CLIENTSECRET dans l'environnement)
```

- Le premier compte ajouté devient le compte par défaut.
- Le mot de passe maître n'est jamais pris en argument : invite sur le terminal (ou askpass).
- `lock` ne retire pas les clés déjà chargées dans l'agent (voir « Agent » : `lock --unload`).


## Plusieurs comptes

Chaque compte a un **alias** (`[a-z0-9][a-z0-9_-]{0,31}`) lié à un serveur et un e-mail.

```bash
sshvault account add boulot --server https://vault.example.org --email alice@boulot.example
sshvault account list                       # alias, serveur, e-mail, défaut
sshvault account default perso boulot       # remplace la liste des comptes par défaut
sshvault account rename boulot travail      # données, session, agents et ssh_config suivent
sshvault account set travail --email alice@travail.example   # corrige serveur et/ou e-mail
sshvault account remove travail             # oublie le compte localement (coffre non modifié)
sshvault logout --account perso             # bw logout, session oubliée, clés retirées des agents
```

`--account ALIAS` existe sur la plupart des commandes qui lisent ou écrivent le coffre :

```bash
sshvault list                         # comptes par défaut
sshvault list --account client        # ce compte seul
sshvault list --account perso --account boulot   # lecture : plusieurs fois possible
sshvault status                       # sans --account : tous les comptes
```

- Lecture (`list`, `search`, `load`, `pubkey`, `deploy`, `sync`, `unlock`…) : comptes par défaut, ou ceux de `--account`.
- Écriture (`import`, `generate`, `hosts`, `forward`, `password add`) : **un seul** compte ; sans `--account`, le compte
  par défaut s'il est unique, sinon code 2.
- `login` et `logout` exigent `--account` dès qu'il y a plusieurs comptes.
- `account set` déconnecte le compte (clés retirées des agents, blocs retirés du `ssh_config`) : refaire
  `sshvault login --account ALIAS`.
- `account remove` ne touche pas au coffre : il supprime les données locales de `bw` du compte.


## Clés : lister, importer, générer

```bash
sshvault list                         # compte, nom, empreinte, hôtes (tabulations)
sshvault list --json                  # + id et clé publique ; jamais de clé privée
sshvault search prod                  # nom, hôte ou empreinte
sshvault search --host 'web*'         # motif glob d'hôte (insensible à la casse)
sshvault search --name bastion        # sous-chaîne du nom
sshvault search --fingerprint SHA256:…   # empreinte exacte (avec ou sans « SHA256: »)
```

Importer une clé existante (Ed25519 ou RSA ≥ 2048 bits) :

```bash
sshvault import ~/.ssh/id_ed25519 --hosts prod.example.org,'*.lab'
sshvault import ~/.ssh/id_rsa --name Bastion --hosts bastion   # --name : un seul fichier
sshvault import ~/.ssh/id_perso --decrypt     # clé à passphrase : stockée déchiffrée (passphrase demandée une fois)
sshvault import ~/.ssh/cle --force            # même si l'empreinte est déjà dans le coffre (second élément)
```

- Sans `--decrypt`, une clé à passphrase est importée **telle quelle, chiffrée** : la passphrase est redemandée à chaque
  chargement.
- Le fichier d'origine n'est jamais modifié ni supprimé : à vous de l'effacer une fois l'import vérifié.
- Empreinte déjà présente : code 1, rien créé.

Générer une clé directement dans le coffre (la clé privée n'est jamais écrite sur disque persistant) :

```bash
sshvault generate --name web --hosts web.example.org              # Ed25519 (défaut)
sshvault generate --name vieux --type rsa --bits 3072 > vieux.pub # RSA : 3072 ou 4096 (défaut 4096)
sshvault generate --name web --comment "web 2026"                 # commentaire de la clé (défaut : le nom)
```

- stdout ne contient **que** la clé publique (une ligne) ; le reste va sur stderr.
- Nom déjà pris : code 1, rien généré ; `--force` crée quand même un élément de ce nom.
- Ni ECDSA, ni DSA, ni `-sk` (code 2).

Afficher la clé publique et la déployer :

```bash
sshvault pubkey --host web.example.org > web.pub    # une ligne par clé ; lit le cache local, pas de réseau
sshvault pubkey --all                                # toutes les clés du coffre
sshvault deploy --id UUID admin@web.example.org      # ajoute la clé à ~/.ssh/authorized_keys de la cible
sshvault deploy web web.example.org -p 2222 -- -i ~/.ssh/cle_admin -o ConnectTimeout=10
```

- `deploy` fait un seul `ssh` ; idempotent : un second appel répond « déjà présente » et ne touche à rien.
- Après `--` : options passées telles quelles à `ssh` (pas de cible, ni de commande ; `-t`, `-N`, `-f`… refusés).
- Cible : `[utilisateur@]hôte` (lettres, chiffres, `.` `-` `_`, ou IPv6) ; pas de `hôte:port`, utiliser `-p`.
- `pubkey` et `deploy` lisent le cache local de `bw` : `sshvault sync` d'abord si la clé vient d'être ajoutée ailleurs.

La sélection d'une clé (`load`, `pubkey`, `deploy`, `hosts`, `forward`) se fait par motif (nom, hôte ou empreinte) ou
avec un critère explicite :

```bash
sshvault load web                     # motif : nom, hôte ou empreinte
sshvault load --host web.example.org  # glob d'hôte
sshvault load --name Bastion          # sous-chaîne du nom
sshvault load --fingerprint SHA256:…  # empreinte exacte
sshvault load --id UUID               # id exact de l'élément
```


## Lier des clés à des hôtes

Les hôtes d'une clé (champ `sshvault-hosts` de l'élément) disent à quels hôtes `ssh` l'offre. Motif de ligne `Host`
(lettres, chiffres, `.` `-` `_` `*` `?`), en minuscules ; `bw sync` puis écriture dans le coffre, puis `ssh_config`
régénéré.

```bash
sshvault hosts add    --id UUID prod.example.org '*.lab'   # ajoute (crée le champ si besoin)
sshvault hosts remove 'Serveur Prod' prod.example.org      # retire ; hôte absent : code 1
sshvault hosts set    --id UUID a.example,b.example        # remplace la liste ; "" la vide
sshvault hosts list   --id UUID                            # un hôte par ligne
```

- La sélection doit désigner **un seul** élément (plusieurs : code 2, préciser `--id`).
- Les hôtes se passent en arguments séparés ou en liste à virgules.
- Un motif sans partie littérale (`*`) prend toutes les connexions ssh : sshvault avertit.


## ssh transparent

`ssh-config` génère `~/.ssh/sshvault/config` (blocs `Match originalhost …`) et les clés publiques ; `install` fait lire ce
fichier par ssh.

```bash
sshvault ssh-config                   # (re)génère la config et les clés publiques
sshvault ssh-config --print           # affiche la config générée, sans rien écrire
sshvault ssh-config --check           # n'écrit rien ; 0 = à jour et Include en tête, 1 sinon
sshvault ssh-config install           # ajoute Include "~/.ssh/sshvault/config" en 1re ligne de ~/.ssh/config
sshvault ssh-config uninstall         # retire la ligne Include, la config générée et les clés publiques
```

Ensuite, `ssh <hôte>` suffit : plus de `ssh-add` à la main.

```bash
sshvault sync                         # voir une modification faite ailleurs (web vault…)
sshvault ssh-config                   # puis régénérer
```

- `install` sauvegarde d'abord (`~/.ssh/config.sshvault.bak`, puis `.bak.1`…, jamais écrasée) ; idempotent ; ligne
  déjà en tête = rien à faire.
- **`~/.ssh/config` est un lien symbolique** (config versionnée par git) : le lien est suivi et la ligne `Include` est
  écrite dans la **cible finale**, qui doit être à vous et non modifiable par le groupe ni les autres (ssh refuse
  sinon : « Bad owner or permissions »). Le lien n'est jamais remplacé. Contrôle refusé : code 4, rien modifié, et
  le message dit la ligne à ajouter à la main.
- `~/.ssh` lui-même lien symbolique : la sauvegarde va sous `$XDG_STATE_HOME/sshvault/` (défaut `~/.local/state/sshvault/`)
  et un avertissement rappelle que `~/.ssh/sshvault/` est dans l'arbre du lien.
- `install` et `uninstall` excluent `--print` et `--check` (code 2).
- `uninstall` ne touche pas aux agents, comptes, sessions ni données de `bw`, et ne demande rien au coffre.

Chargement automatique (`sshvault ensure`) :

- Chaque bloc a une ligne `Match originalhost <hôtes> exec "'…/sshvault' ensure --account <alias> --id <id>"` :
  ssh l'exécute avant l'authentification, `ensure` charge la clé si elle manque dans l'agent dédié, puis ssh continue.
- Marche aussi pour **chaque saut** `ProxyJump` / `ProxyCommand ssh -W` (le ssh du saut relit la config).
- Coffre verrouillé : une invite par compte concerné, sur le terminal si ssh est au premier plan, sinon askpass ;
  aucune invite si un ssh de la chaîne a `-o BatchMode=yes` en argument, ni avec `sshvault --nointeraction ensure`.
- Échec : une ligne `sshvault: <hôte> : <cause>` sur stderr, puis ssh continue et échoue proprement.
- `ssh -G` et `ssh -O` ne déclenchent aucun chargement.
- `Match originalhost` compare le nom **tapé** (`ssh Prod.Example.ORG`), pas le `HostName` : `ssh 10.0.0.5` ne reçoit
  pas la clé d'un bloc `Host prod.example.org` + `HostName 10.0.0.5`.
- Le chemin de sshvault est figé dans la config : après une réinstallation ailleurs, relancer `sshvault ssh-config`.

Réglages du chargement automatique :

```bash
sshvault config get                   # tous les réglages (+ « (défaut) »)
sshvault config set auto-load false   # plus de ligne Match exec : chargement à la main (sshvault load)
sshvault config set auto-restrict true  # clés chargées avec ssh-add -h (hôtes de l'élément)
sshvault config set auto-confirm true   # clés chargées avec ssh-add -c (confirmation à chaque usage)
sshvault config set key-ttl 2h        # durée de vie par défaut des clés (N, Ns, Nm, Nh, Nd ; 1 s à 30 j ; 0 = illimitée)
sshvault config unset auto-load       # retour au défaut
sshvault ssh-config                   # prise en compte à la prochaine génération
```

Défauts : `key-ttl` 1 h, `auto-load` true, `auto-restrict` false, `auto-confirm` false, `forward-confirm` true.
Booléens : `true`/`false` (aussi `yes`/`no`, `on`/`off`, `1`/`0`). Réglages dans
`${XDG_CONFIG_HOME:-~/.config}/sshvault/config.json`.


## Agent

Les clés vont dans un `ssh-agent` **dédié** (socket `$XDG_RUNTIME_DIR/sshvault/agent.sock`), jamais dans votre
agent habituel (`SSH_AUTH_SOCK` n'est ni lu ni modifié). OpenSSH ≥ 8.9 requis.

```bash
sshvault load web                       # charge la clé choisie (durée : -t, sinon key-ttl, sinon 1 h)
sshvault load --all                     # toutes les clés SSH du coffre
sshvault load web -t 30m                # durée de vie : N, Ns, Nm, Nh, Nd ; 0 = illimitée
sshvault load web --confirm             # confirmation à chaque usage (ssh-add -c)
sshvault load web --restrict            # restreinte aux hôtes de l'élément (ssh-add -h)
sshvault load web --force               # recharge une clé déjà présente (nouvelles options)
```

- `--restrict` : hôtes **littéraux** seulement (pas de `*`/`?`), présents dans `known_hosts` ; sinon code 4, rien chargé.
- Une clé déjà chargée n'est pas rechargée (« déjà chargée ») : `--force` pour changer ses options.
- Clé chiffrée par passphrase : `ssh-add` la demande à chaque chargement ; `--nointeraction` = code 3.
- Tout ou rien : un échec en cours de route retire les clés apparues pendant ce `load`.

```bash
sshvault agent status                   # socket, pid, clés (alias, nom, empreinte, hôtes, temps restant, options)
sshvault agent purge                    # retire toutes les clés (ssh-add -D), sous-agents de transfert compris
sshvault agent lock                     # vide les sous-agents de transfert, puis verrouille l'agent (mot de passe saisi par ssh-add)
sshvault agent unlock                   # déverrouille l'agent (ssh-add -X)
sshvault agent stop                     # arrête l'agent dédié et les sous-agents, supprime sockets et états
```

`agent status` : 0 actif, 3 arrêté, 4 sous-agent de transfert en erreur.

Verrouiller le coffre **et** retirer les clés (révocation immédiate) :

```bash
sshvault lock                           # coffre seul : les clés chargées restent utilisables jusqu'à leur durée de vie
sshvault lock --unload                  # + clés des comptes verrouillés retirées des agents (dédié et transfert)
sshvault lock --account perso --unload  # un compte seul
```

`lock --unload` : une clé partagée avec un compte non verrouillé reste chargée (attribuée à lui). Agent verrouillé ou en
erreur : le coffre est verrouillé quand même, les clés non retirées sont dites, code 4.

Agent verrouillé (`agent lock`) : `load` et `purge` refusent (code 3) et le chargement automatique de ssh aussi
(`ensure`, code 3) ; `agent unlock`, puis le prochain ssh recharge les clés manquantes.


## Transfert d'agent restreint

Pour un hôte (rebond) où l'on veut `ForwardAgent`, ne transférer qu'un **sous-agent** qui contient les clés
déclarées pour cet hôte, et non tout l'agent dédié.

```bash
sshvault forward add    --id UUID bastion '*.dmz'    # la clé sera transférée vers ces hôtes
sshvault forward remove --id UUID '*.dmz'
sshvault forward set    --id UUID bastion            # remplace la liste ; "" la vide
sshvault forward list   --id UUID                    # un motif par ligne
```

Même syntaxe, mêmes sélections et mêmes codes que `hosts` (champ `sshvault-forward` de l'élément). Un hôte de transfert
n'a pas besoin d'être un hôte d'identité.

**Pourquoi c'est plus sûr qu'un `ForwardAgent yes` seul.** Sur un hôte géré par sshvault **sans transfert déclaré**,
`ForwardAgent yes` (ou `ssh -A`) transfère **l'agent dédié entier** : toutes les clés chargées, pas seulement celle de
l'hôte, et un root distant peut s'en servir tant que la session est ouverte. Avec `forward`, seules les clés déclarées
pour cet hôte sont dans le sous-agent transféré, chargées **à la demande** par `ensure --forward`, et le bloc généré
l'emporte même sur `ForwardAgent yes` ou `ssh -A`. `sshvault ssh-config` avertit pour les hôtes littéraux d'identité
qui ont `ForwardAgent yes` sans transfert déclaré.

```bash
sshvault config set forward-confirm false   # défaut true : chaque usage de la clé depuis l'hôte distant est confirmé
```

- `forward-confirm` (défaut `true`) charge les clés transférées avec `ssh-add -c` : il faut un askpass utilisable
  (`DISPLAY`, ou `SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force`), sinon rien n'est chargé (code 4, la connexion se fait quand même).
- Tout changement de `forward-confirm` arrête les sous-agents ; ils sont rechargés au prochain ssh.
- Échec : `sshvault: <hôte> : transfert d'agent : <cause>`, la connexion se fait quand même, l'hôte distant voit un agent vide.
- Risque résiduel : root sur l'hôte distant peut utiliser les clés du sous-agent pendant la session ; la fenêtre de
  confirmation d'OpenSSH ne nomme pas l'hôte de destination.


## Mots de passe d'hôte (machines sans clé)

Pour une machine qui n'accepte qu'un mot de passe : un élément **identifiant** du coffre, relié à ses hôtes par des URI
`ssh://[utilisateur@]hôte`.

```bash
sshvault password list                          # alias, nom, hôtes ([user@]hôte) ; jamais le mot de passe
sshvault password list --json
sshvault password add Routeur --host routeur --user admin      # mot de passe saisi deux fois (masqué)
sshvault password add Base --host db --host root@db2           # --host répétable, ou liste à virgules
printf '%s\n' "$MDP" | sshvault password add Routeur --host routeur --user admin   # stdin non terminal : une ligne
```

- Le mot de passe n'est **jamais** un argument : terminal (saisi deux fois, masqué, trois essais) ou une ligne sur stdin.
- `--user U` : utilisateur attendu des hôtes écrits sans `USER@`. Hôte : lettres, chiffres, `.` `-` `_`, sans motif, **sans port**.
- Un hôte + utilisateur déjà portés par un autre élément identifiant : code 2 ; `--force` écrit quand même.
- Un seul compte écrit (`--account`, sinon le compte par défaut unique).

Hôtes d'un élément identifiant :

```bash
sshvault password hosts list   Routeur                       # [user@]hôte attendus
sshvault password hosts add    Routeur admin@routeur2 db     # ajoute des URI ssh://
sshvault password hosts remove Routeur root@db               # retire ces paires exactes ; absente : code 1
sshvault password hosts set    Routeur routeur               # remplace la liste ; "" les retire toutes
sshvault password hosts set    --id UUID ""                  # --id : aussi un élément sans URI ssh:
```

- Sélection : `--name`, `--host` (glob d'hôte), `--id` ; par défaut nom ou hôte.
- `remove` et `set` qui retirent des URI demandent « confirmer ? [o/N] » au terminal ; sans terminal ou avec
  `--nointeraction` : code 2, sauf `--yes`.
- `add` et `set` : `--force` pour passer outre un doublon d'hôte + utilisateur.

Mise en place de l'askpass (une fois, dans `~/.bashrc` ou `~/.profile`) :

```bash
export SSH_ASKPASS="$HOME/.local/bin/sshvault-askpass"
export SSH_ASKPASS_REQUIRE=force
```

Comment ça marche :

- À la connexion, la ligne `Match … exec "… ensure --password …"` enregistre le ssh appelant (aucun secret) et
  déverrouille le compte au besoin ; puis ssh appelle `sshvault-askpass`.
- `sshvault-askpass` ne donne le mot de passe du coffre que pour l'invite exacte `<utilisateur>@<hôte>'s password: ` (ou
  `(<utilisateur>@<hôte>) Password: `) d'un hôte enregistré, avec l'utilisateur attendu, une fois par connexion **et
  par saut** (ProxyJump compris).
- **Toute autre invite** (question de clé d'hôte, passphrase, code à usage unique…) est relayée : au terminal si
  `/dev/tty` est ouvrable, sinon à `askpass-fallback`, sinon refus (code 1).
- Avec `force`, ssh, `ssh-add` et `ssh-keygen` envoient **toutes** leurs invites à cet askpass : un programme sans terminal
  (cron…) et sans `askpass-fallback` voit ses invites refusées.
- Les invites de sshvault lui-même (déverrouillage, passphrase, verrou de l'agent) et ses enfants ne passent jamais par
  son askpass : terminal d'abord.

`askpass-fallback` : askpass graphique vers lequel les invites sont relayées quand aucun terminal n'est ouvrable.

```bash
sshvault config set askpass-fallback /usr/bin/ssh-askpass   # chemin absolu d'un exécutable (pas l'askpass de sshvault)
sshvault config get askpass-fallback
sshvault config unset askpass-fallback                      # défaut : /usr/bin/ssh-askpass s'il est exécutable et DISPLAY défini
```


## Synchronisation et cache

```bash
sshvault sync                         # bw sync : resynchronise le coffre depuis le serveur (réseau)
sshvault sync --account perso
```

- Hors `sync`, `login`, `import`, `generate` et les écritures (`hosts`, `forward`, `password add|hosts`),
  les commandes lisent le **cache local** de `bw` : `list`, `search`, `pubkey`, `deploy`, `ssh-config`, `ensure`…
- Une modification faite dans le web vault n'est vue qu'après `sshvault sync`.
- Pour qu'elle soit prise en compte par ssh : `sshvault sync` puis `sshvault ssh-config`.
- Clé changée dans le coffre sans `ssh-config` : l'ancienne reste offerte.


## Codes de sortie

| Code | Sens |
|---|---|
| 0 | succès |
| 1 | aucun résultat ; `hosts`/`forward remove` : hôte absent ; `import` : clé déjà dans le coffre ; `generate` : nom déjà pris ; `password hosts` : sélection sans élément, paire absente, perte d'URI non confirmée ; `ssh-config --check` : pas à jour |
| 2 | usage : option ou argument invalide, hôte invalide, sélection ambiguë, `--account` requis, alias inconnu, réglage invalide, doublon sans `--force`, `import` fichier refusé, `generate` type refusé |
| 3 | aucun compte, non connecté, ou coffre verrouillé (sans invite possible, invite annulée, mot de passe refusé) ; agent arrêté ou verrouillé ; passphrase refusée |
| 4 | erreur du backend ou de l'agent : `bw` introuvable ou en erreur, **session illisible**, `XDG_RUNTIME_DIR` inutilisable, OpenSSH < 8.9, écriture impossible (`ssh_config`, coffre, `config.json`), `ssh-keygen` ou `ssh` en échec, `install`/`uninstall` refusé, `logout`/`account …` en échec, `lock --unload` : clés non retirées |
| 130 | interrompu (Ctrl-C, SIGTERM, SIGHUP) |

Cas particuliers :

- `status` : 0 si chaque compte affiché est déverrouillé, 3 si l'un est verrouillé ou non connecté (ou aucun
  compte), 4 si `bw` est en erreur.
- `agent status` : 0 actif, 3 arrêté, 4 sous-agent de transfert en erreur.
- Plusieurs comptes : le **pire** des codes.
- `ensure` n'a aucun effet sur ssh : en cas d'échec, une ligne sur stderr et ssh continue.
- `sshvault-askpass` : 0 et la réponse sur stdout ; 1 sans terminal ni fallback, ou saisie annulée.
- Toute erreur est une ligne sur stderr, sans trace d'exécution.


## Dépannage

### Lire `status`

```bash
sshvault status                       # tous les comptes
sshvault status --account perso
```

- 1re ligne : `bw : <chemin> (SSHVAULT_BW | réglage bw-path | PATH)` ; sans `bw` trouvé : `bw : bw (introuvable dans le PATH)`.
- Par compte : `alias : …` (`(défaut)` si compte par défaut), `coffre :` `non connecté` / `verrouillé` /
  `déverrouillé`, `serveur :`, `compte :` (e-mail), `session :` (durée restante, ou `aucune`), `magasin :` et `données :`.
- `non connecté` → `sshvault login --account ALIAS` ; `verrouillé` → `sshvault unlock`.
- Avertissement « bw est connecté … le registre dit … » : bw n'est pas connecté au serveur ou à l'e-mail enregistrés ;
  le message propose le remède (`sshvault account set ALIAS --server … --email …`, ou `logout` puis `login`).

### Lire `ssh-config --check`

```bash
sshvault ssh-config --check; echo $?   # 0 = tout à jour ; 1 = différences (listées sur stdout)
```

Code 1 : contenu différent, fichier absent ou en trop, droits autres que 0600 (fichiers) ou 0700 (dossiers), ligne
`Include` absente, conditionnelle (dans un bloc `Host`/`Match`) ou pas en tête de `~/.ssh/config`. Remède : `sshvault
ssh-config` (génération) et/ou `sshvault ssh-config install` (ligne `Include`).

### Erreurs courantes

| Symptôme | Cause et remède |
|---|---|
| `Permission denied (publickey)` précédé de `Load key "…/pub/SHA256:….pub": error in libcrypto` | La clé n'est pas dans l'agent dédié (chargement automatique désactivé ou en échec). La ligne `sshvault: …` juste avant dit pourquoi ; `sshvault load <hôte>` la charge à la main. |
| ssh n'utilise pas la clé du coffre | `sshvault ssh-config --check` : `Include` absent ou pas en tête → `sshvault ssh-config install`. Un ssh lancé avec un autre `$HOME` (`sudo`, `su`) ne trouve pas la config. |
| `bw` introuvable sous ssh (cron, session graphique) | Le `PATH` de ssh ne contient pas `bw` : `sshvault config set bw-path /chemin/absolu/bw`. |
| Code 3, « coffre verrouillé » | `sshvault unlock`. Sans terminal ni askpass, pas d'invite possible. |
| Code 3, « non connecté » / compte déconnecté | `sshvault login --account ALIAS` (après `logout` ou `account set`). |
| Code 3, « agent verrouillé » | `sshvault agent unlock`. |
| Mauvais mot de passe maître | L'échec est mémorisé 30 s pour cette connexion : les sauts suivants échouent sans invite. `sshvault unlock` efface cette mémoire. |
| Code 4, `session illisible : keyctl <raison>` | Le trousseau noyau `@u` ne répond pas ni ne dit « pas de session » (délai, « Permission denied »…) et il n'y a pas de session dans le fichier de repli : la session rangée n'est ni effacée ni réécrite. Relancer `sshvault unlock` : il range la session dans le fichier de repli `$XDG_RUNTIME_DIR/sshvault/sessions/<alias>` (si `XDG_RUNTIME_DIR` est privé et sur tmpfs), sans toucher au trousseau. |
| Avertissement « session non rangée » | Ni trousseau, ni `XDG_RUNTIME_DIR` privé : chaque saut redemande le mot de passe maître. |
| Code 4, `XDG_RUNTIME_DIR` refusé | Il doit appartenir à l'utilisateur, sans droits groupe/autres, sur tmpfs ou ramfs (repli `/run/user/<uid>`). |
| Code 4 à l'import / `generate` (tmpfs) | `--decrypt` et `generate` passent par un dossier privé du tmpfs ; sans tmpfs privé, rien n'est créé. |
| `load --restrict` refusé (code 4) | Hôte non littéral (`*`, `?`, `user@hôte`, port, IPv6) ou absent de `known_hosts`, ou élément sans hôte. |
| `Bad owner or permissions` (ssh) ; `install` refusé (code 4) sur un lien | La cible du lien `~/.ssh/config` n'est pas à vous ou est modifiable par le groupe ou les autres : `chmod g-w,o-w <chemins>` puis relancer `install`. |
| Code 2, « préciser --account » | Plusieurs comptes : ajouter `--account ALIAS` (écriture, `login`, `logout`). |
| Code 2, « préciser --id » | La sélection désigne plusieurs éléments : utiliser `--id UUID`. |
| `import` code 1 | Empreinte déjà dans le coffre ; le message donne le nom et l'id de l'élément existant ; `--force` crée un second élément. |
| Invites refusées (cron, session graphique) avec `SSH_ASKPASS_REQUIRE=force` | Sans terminal ni `askpass-fallback`, `sshvault-askpass` refuse les invites qu'il ne sait pas traiter : poser `askpass-fallback`. |

Nettoyage complet : voir README, « Désinstaller ».


## Variables utiles

| Variable | Rôle |
|---|---|
| `SSHVAULT_BW` | exécutable `bw`, prioritaire sur `bw-path` |
| `SSHVAULT_BW_TIMEOUT` | délai d'un appel `bw`, secondes (défaut 60) |
| `SSHVAULT_PROMPT_TIMEOUT` | délai d'une invite, secondes (défaut 60) |
| `SSHVAULT_ENSURE_TIMEOUT` | délai global d'un `ensure`, secondes (défaut 240) |
| `SSHVAULT_DEPLOY_TIMEOUT` | délai global d'un `deploy`, secondes (défaut 120) |
| `BW_CLIENTID`, `BW_CLIENTSECRET` | clé API pour `login --apikey` |
| `XDG_RUNTIME_DIR` | socket et état de l'agent, session de repli (tmpfs privé exigé) |
| `XDG_CONFIG_HOME`, `XDG_DATA_HOME` | `config.json` ; données de `bw` par compte |

Liste complète : README, « Variables ».


## Référence rapide des commandes

| Commande | Rôle |
|---|---|
| `status [--account A]…` | état du coffre et de la session de chaque compte |
| `login [--account A] [--apikey]` | connexion d'un compte (interactive) |
| `logout [--account A]` | déconnecte, oublie la session, retire les clés des agents |
| `unlock [--account A]… [--ttl S]` | déverrouille le coffre, garde la session (900 s par défaut) |
| `lock [--account A]… [--unload]` | verrouille le coffre ; `--unload` : retire aussi les clés des agents |
| `sync [--account A]…` | resynchronise le coffre depuis le serveur |
| `account add ALIAS --server URL --email E` | enregistre un compte |
| `account list` | comptes enregistrés |
| `account default ALIAS…` | remplace les comptes par défaut |
| `account rename ANCIEN NOUVEAU` | renomme un compte |
| `account set ALIAS [--server URL] [--email E]` | corrige serveur et/ou e-mail (déconnecte) |
| `account remove ALIAS` | oublie le compte localement |
| `list [--json]` | liste les clés SSH |
| `search MOTIF [--host\|--name\|--fingerprint] [--json]` | cherche des clés |
| `import FICHIER… [--name N] [--hosts H,…] [--force] [--decrypt]` | importe des clés privées |
| `generate --name N [--type ed25519\|rsa] [--bits 3072\|4096] [--comment T] [--hosts H,…] [--force]` | génère une clé dans le coffre |
| `pubkey (SÉLECTION\|--all)` | affiche les clés publiques |
| `deploy SÉLECTION [U@]HÔTE [-p PORT] [-- OPTIONS_SSH…]` | ajoute la clé à `authorized_keys` de la cible |
| `hosts add\|remove\|set SÉLECTION HÔTE…` | hôtes d'une clé |
| `hosts list SÉLECTION` | affiche les hôtes d'une clé |
| `forward add\|remove\|set SÉLECTION HÔTE…` | hôtes de transfert d'agent restreint |
| `forward list SÉLECTION` | affiche les hôtes de transfert |
| `load (SÉLECTION\|--all) [-t DURÉE] [--confirm] [--restrict] [--force]` | charge des clés dans l'agent dédié |
| `agent status\|purge\|lock\|unlock\|stop` | état, purge, verrou, déverrouillage, arrêt de l'agent |
| `ssh-config [--print\|--check]` | génère (ou affiche, ou vérifie) la config ssh et les clés publiques |
| `ssh-config install\|uninstall` | ajoute ou retire la ligne `Include` et la config générée |
| `ensure --account A --id ID` | chargement à la demande (appelé par ssh, pas à la main) |
| `config get [CLÉ]\|set CLÉ VALEUR\|unset CLÉ` | réglages : `key-ttl`, `auto-load`, `auto-restrict`, `auto-confirm`, `forward-confirm`, `bw-path`, `askpass-fallback` |
| `password list [--json]` | éléments identifiant à URI `ssh://` |
| `password add NOM --host [U@]H… [--user U] [--force]` | crée un élément identifiant |
| `password hosts add\|remove\|set\|list SÉLECTION [U@]H…` | hôtes d'un élément identifiant |
| `sshvault-askpass` | askpass à mettre dans `SSH_ASKPASS` (appelé par ssh) |

Sélections : `--host` (glob d'hôte), `--name` (sous-chaîne), `--fingerprint`, `--id` (`search` : pas de `--id` ;
`password hosts` : pas de `--fingerprint`).
Presque toutes les commandes prennent `--account ALIAS`.

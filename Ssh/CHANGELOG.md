# Changelog — sshvault

## sshvault 0.11.0 — Révocation au verrouillage, désinstallation du ssh_config, robustesse de logout — 2026-10-13

- `sshvault lock --unload` : révoque aussitôt les clés chargées. Sous `ensure.lock`, compte
  après compte : agents (dédié et sous-agents) vérifiés comme pour `logout`, clés du compte
  retirées (une clé partagée avec un compte non verrouillé reste chargée, attribuée à lui ;
  une clé partagée par deux comptes verrouillés part avec le second), puis coffre verrouillé
  (après le retrait : la session sert aux entrées chargées avant la 0.9.0). Agent verrouillé
  ou en erreur : le coffre est verrouillé quand même, une ligne dit les clés non retirées et
  la commande à relancer, code 4. `bw lock` en échec : une ligne (plusieurs comptes :
  `<alias> : …`), clés retirées dites quand même, autres comptes traités, code le pire ; la
  ligne de compte rendu dit l'état réel du coffre (« coffre non verrouillé » si bw a échoué,
  « coffre verrouillé » si seule la session n'a pas pu être oubliée) et de la session
  (« session oubliée » ou « session non oubliée », relu dans le magasin).
  `lock` sans `--unload` : inchangé (aucun agent touché).
- `sshvault ssh-config uninstall` : retire de `~/.ssh/config` les lignes `Include` qui ne
  désignent que le fichier généré (en tête, plus bas ou dans un bloc ; sauvegarde
  `config.sshvault.bak*` d'abord, mode et propriétaire gardés : après `install` puis
  `uninstall`, le fichier est identique, sauf un `~/.ssh/config` créé par `install` (gardé,
  vide) et une ligne `Include` qu'`install` a déplacée ou une ligne à joker qu'il a retirée
  (pas remises en place ; dans sa sauvegarde)), supprime `~/.ssh/sshvault/config` et les `*.pub` de
  `pub/` (dossier supprimé s'il est vide). Une ligne qui inclut aussi d'autres fichiers ou un
  joker : gardée, avertissement. Mêmes refus qu'`install` (lien symbolique, non ordinaire ;
  aussi `~/.ssh/sshvault`, sa config ou `pub/` d'un type inattendu) : code 4, rien modifié.
  Rien d'installé : « rien à faire », code 0. Ligne `Include` gardée : la sortie dit qu'elle
  inclut toujours le fichier généré (la prochaine régénération réactive sshvault), pas « ssh
  n'utilise plus sshvault ». `--print`/`--check` exclus (code 2). Ni coffre,
  ni agent, ni compte, ni session touchés ; se fait même si l'adoption 0.8.0 est en attente
  (comme `install`). Remplace la désinstallation à la main du README.
- Sonde de verrou d'agent : un agent qui ne liste aucune clé est départagé par `ssh-add -D`
  (réussi : vide et déverrouillé, rien à retirer ; « Failed to remove all identities. » :
  verrouillé ; mesuré sur OpenSSH 8.9p1), jamais par `-x`/`-X`.
  - Contrôles de retrait (`logout`, `account set`, `account remove`, `lock --unload`) :
    sonde seulement si l'état attend une clé non échue. Un agent vidé à la main n'est plus
    pris pour verrouillé (avant : code 4) ; clé partie entre les deux passes, agent devenu
    vide (durée de vie écoulée, retrait à la main) : comptée retirée, plus « agent
    verrouillé » à tort.
  - `ensure` d'un compte déconnecté (marqueur) : dès que l'agent dédié ne liste aucune clé,
    quel que soit son état (état vide compris), la CLI sonde sous `ensure.lock` ; agent
    verrouillé hors de sshvault (`ssh-add -x`) : « agent verrouillé : lancer « sshvault agent
    unlock » » (code 3) au lieu de « déconnecté ». Le chemin rapide ne sonde jamais : il lit
    l'agent (un `ssh-add -L`, sur ce chemin seulement) et ne dit « déconnecté » que si
    l'agent liste une clé ou n'a pas de socket (sinon la CLI tranche). Coût : compte
    déconnecté dont l'agent dédié tourne mais est vide, chaque `ssh` vers ses hôtes charge
    la CLI et sonde.
  - `agent unlock`, quel que soit l'état : agent qui ne liste aucune clé, état non marqué
    verrouillé : verrouillé hors de sshvault → `ssh-add -X` (avant : « déjà déverrouillé ») ;
    vide → « déjà déverrouillé », entrées d'état périmées retirées. Liste, sonde et
    déverrouillage sous `ensure.lock` : un `ensure` en cours finit d'abord, et un `ssh` lancé
    pendant la saisie du mot de passe attend (borné par son délai), comme pour `agent lock`.
  - La sonde n'est pas sans perte dans tous les cas : une clé ajoutée à cet instant par
    `sshvault load` (hors `ensure.lock`) ou à la main serait retirée (`ensure` recharge une
    clé du coffre à son prochain usage).
- Interruption (Ctrl-C, SIGTERM, SIGHUP) pendant `bw logout` (`logout`, `account set`) : bw
  tué, état relu (10 s au plus), session oubliée, marqueur `logged-out` posé si bw est
  déconnecté ou si son état est inconnu ; Ctrl-C, SIGTERM et SIGHUP retenus le temps de la
  relecture et de la pose du marqueur (un second signal est servi après) ; session impossible
  à oublier : « session non oubliée : … » dit après la ligne ; « interrompu », code 130
  (`account set` : registre inchangé). Avant : marqueur jamais posé, `ensure`
  pouvait dire « verrouillé » au lieu de proposer `login`. Adaptateur : `BwBackend.logout(on_interrupt)`.
- Tests : garde de fin de session stricte sur les dossiers sshvault réels déjà existants
  (runtime, données, config) : instantané récursif comparé, échec qui liste les chemins
  changés ; `SSHVAULT_TEST_GUARD=warn` le ramène à un avertissement (usage réel concurrent ;
  `~/.ssh` modifié, dossier réel créé ou disparu restent des échecs) ; garde éprouvée par une écriture
  simulée. Matrice de la story dans `tests/test_accounts.py`, `tests/test_sshconfig.py`,
  `tests/test_cli.py` ; faux `bw` : `logout=hangafter` (déconnecté puis bloqué).

## sshvault 0.10.0 — Déconnexion et modification d'un compte — 2026-10-12

- `sshvault logout [--account ALIAS]` : `--account` obligatoire dès qu'il y a plusieurs
  comptes (code 2, une ligne qui liste les alias) ; un seul compte : visé ; `bw-path`
  invalide : code 2, rien fait (même sans données de `bw`). Sous `ensure.lock` : état lu
  d'abord dans bw (`bw status` sans session, sans effet sur la session rangée), puis chaque
  agent (dédié, sous-agents) vérifié lisible et non verrouillé avant tout `bw list` ; clés du
  compte retirées (une clé partie entre-temps compte comme retirée si l'agent liste encore
  d'autres clés ou si sa durée de vie est écoulée ; un agent qui ne liste plus rien alors que
  la clé vit encore est tenu pour verrouillé : code 4, entrée gardée ; une clé du compte
  chargée pendant la commande est laissée, entrée gardée, une ligne d'avertissement ; une clé
  partagée avec un autre compte reste chargée, attribuée à l'autre compte) ; `bw logout` si le compte est
  connecté ou si son état est illisible ; session oubliée (aussi quand bw a été déconnecté
  hors de sshvault). `bw list` seulement pour des clés chargées avant la 0.9.0. Compte gardé
  au registre, blocs du `ssh_config` gardés. Rien du tout à faire (non connecté, ni clé, ni
  état d'agent, aucune session à coup sûr) : code 0, une ligne, rien touché (mémoire d'échec
  de déverrouillage comprise ; bw jamais lancé sans données). Agent verrouillé ou en erreur :
  rien modifié, ou état partiel dit (clés retirées, agents mis à jour, agent en cours),
  code 4. `bw logout` en échec : code 4, une ligne qui dit que les données restent connectées
  sous l'alias (après un délai dépassé, état relu en 10 s au plus ; `bw status` et `bw
  logout` en échec : état inconnu, cause dite une fois si c'est la même ; relecture qui voit
  bw toujours connecté : « toujours connectées ») et ce qui est fait ; « session oubliée »
  seulement si c'est vrai.
- Changement : `logout`, `account set` et `account remove` refusent maintenant (code 4, rien
  modifié) dès qu'un agent qui porte une clé possible du compte (entrée du compte, entrée
  sans compte d'avant la 0.9.0, ou référence `also` à ce compte) est verrouillé, même si
  aucune clé du compte n'est à retirer (simple promotion d'une clé partagée, par exemple) :
  le contrôle se fait avant tout `bw list`. Avant, `account remove` ne regardait que les clés
  à retirer.
- Marqueur persistant `${XDG_DATA_HOME:-~/.local/share}/sshvault/accounts/<alias>/logged-out`
  (fichier ordinaire à côté des données de `bw`, survit au redémarrage ; un autre objet à sa
  place ne compte pas) posé par `logout` (et `account set` qui déconnecte, et sur un état
  inconnu), sauf « rien à faire » ou dossier du compte absent (jamais créé ; échec
  d'écriture : avertissement) ; retiré par le backend dès que bw est vu connecté (tout `bw
  status` qui le voit connecté, `login` compris même en échec « déjà connecté », et tout
  déverrouillage réussi : `unlock`, invite de `load`, `list`, `ensure`), puis reposé si bw
  finit déconnecté dans la même commande (`login --apikey` avec la clé d'un autre compte,
  `logout`/`account set` qui voient bw connecté puis non connecté) ; avertissement « non
  retiré » une seule fois, et jamais dans une commande qui pose le marqueur ; suit `account
  rename`, part avec `account remove`. `ensure` sur ce compte, clé absente, échoue en une
  ligne qui propose `sshvault login --account ALIAS`, même sans invite possible ; le chemin
  rapide la donne sans charger la CLI si l'agent dédié est connu et non verrouillé.
- `sshvault account set ALIAS [--server URL] [--email E]` : validé comme `account add`
  (serveur normalisé, e-mail validé, `-` initial refusé, avertissement `http://`, couple
  unique ; au moins une option ; code 2). Valeurs identiques aux actuelles : rien fait, code
  0. bw déjà connecté avec exactement ces valeurs : registre corrigé seul, même avec un agent
  verrouillé (aucun contrôle d'agent sur ce chemin ; ni déconnexion, ni
  clé ni bloc retiré ; `serverUrl` nul = serveur par défaut de bw, même règle que `status`). Sinon, sous `ensure.lock` : clés du compte retirées des agents, `bw
  logout` (compte connecté), session oubliée, registre mis à jour ; puis `ssh_config`
  régénéré sans les blocs de ce compte. Alias et comptes par défaut gardés ; une ligne dit de
  lancer `sshvault login --account ALIAS`. Agent verrouillé ou en erreur, `bw logout` en
  échec : registre inchangé, code 4. Registre refusé après la déconnexion : une ligne qui dit
  ce qui est déjà fait (code 2 ; 4 si l'écriture échoue). `bw status` illisible : rien fait,
  code de l'erreur (pas de registre corrigé à l'aveugle). `bw-path` invalide : code 2, rien
  fait, même sans données de `bw`.
- `status` : l'écart d'e-mail ou de serveur avec le registre tient en une ligne, avec un seul
  remède `sshvault account set ALIAS [--server …] [--email …]` (valeurs de bw citées pour le
  shell ; invalides : `URL`/`E` à saisir) ou `sshvault logout --account ALIAS` puis `login` ;
  couple de bw déjà enregistré sous un autre alias : reconnexion seulement.
- `ssh-config --check` d'une config générée : un compte **déconnecté** (bw non connecté)
  garde ses blocs tels quels, même seul : « à jour » si le fichier correspond (avant : code 3
  avec un seul compte). Compte seulement verrouillé, `bw` en erreur : comme avant (seul ou
  tous illisibles : leur code ; jamais « à jour »). L'avertissement d'un compte déconnecté
  propose `sshvault login --account ALIAS` (plus `unlock`), une seule fois dans la ligne.
- `status` : ligne `serveur :` d'un compte connecté lue comme l'avertissement (`serverUrl`
  nul = serveur par défaut de bw).
- Adaptateur : `VaultBackend.logout()`, `LogoutUnknown` (état inconnu) et `status(forget=False)`
  (sonde sans effet sur la session) ; `BwBackend.logout()` (session oubliée même si bw échoue
  ou si l'appel est interrompu ; « You are not logged in. » : rien à faire ; délai dépassé :
  état relu à délai court), repris par `login --apikey` (clé API d'un autre compte : déconnecté,
  déjà déconnecté, échec ou état inconnu dits). `data_root`/`account_dir` déplacés dans
  `settings` (module léger, lu par le chemin rapide).
- Tests : matrice de la story dans `tests/test_accounts.py`, `logout()` dans
  `tests/test_backend.py` ; intégration à deux comptes : `logout` puis `login` du second
  compte (`ensure` sans invite propose `login`, `ssh-config --check` à jour avant et après,
  marqueur retiré au `login`), `account set` aller-retour puis `login`. Intégration :
  traceback court (les valeurs des fixtures — sessions bw, clés de test — ne sont plus
  affichées) ; `sshvault login` en échec : fin masquée du terminal gardée dans le message.
- `deploy` : `re.split(…, maxsplit=1)` (argument nommé) : plus d'avertissement
  `DeprecationWarning` sous Python 3.13 et suivants (antérieur à la story).

## sshvault 0.9.0 — Plusieurs comptes Vaultwarden simultanés — 2026-10-09

- Comptes du coffre (CAP-10) : registre alias → serveur + e-mail dans `config.json` (clés
  `accounts`, `default-accounts`), géré par `sshvault account add ALIAS --server URL
  --email E`, `account list`, `account remove ALIAS`, `account default ALIAS…` (remplace la
  liste des comptes par défaut) et `account rename ANCIEN NOUVEAU`. Alias
  `[a-z0-9][a-z0-9_-]{0,31}`, unique ; couple (serveur normalisé, e-mail en minuscules)
  unique ; refus en code 2, registre inchangé. Le premier compte ajouté est compte par défaut.
- Par compte : données de `bw` propres (`…/sshvault/accounts/<alias>/bw`), session propre
  (clé keyring `sshvault:session:<alias>`, repli `$XDG_RUNTIME_DIR/sshvault/sessions/<alias>`),
  mémoire d'échec de déverrouillage propre (`unlock-failed.<alias>`). `bw-path`, l'agent dédié,
  les sous-agents et leurs sockets restent communs.
- `--account ALIAS` sur `status`, `login`, `unlock`, `lock`, `sync`, `list`, `search`, `load`,
  `hosts`, `forward`, `import`, `generate`, `pubkey` et `deploy` ; alias inconnu : code 2.
  Lecture : comptes par défaut (une invite au plus par compte, qui nomme l'alias ; un compte
  en erreur est dit en une ligne `<alias> : …`, les autres traités, code le pire). Écriture :
  un seul compte, le défaut s'il est unique, sinon `--account` obligatoire (code 2, une ligne,
  rien écrit). Sans `--account` : `status` montre tous les comptes, `lock` les verrouille tous,
  `login` exige `--account` dès qu'il y a plusieurs comptes.
- `login` : `bw login <e-mail du registre>` (bw ne demande plus que le mot de passe, et la
  2FA), serveur du registre posé par `bw config server` ; l'option `--server` est retirée
  (le serveur vient du compte) ; `--account` obligatoire dès qu'il y a plusieurs comptes.
  `--apikey` : compte connecté vérifié (clé API d'un autre compte : `bw logout`, code 4).
- `account add` : port par défaut retiré de l'URL, `http://` accepté avec un avertissement,
  refus si `accounts/<alias>/` existe (code 2) ou si une installation 0.8.0 attend son
  adoption (code 4). `status` avertit d'un e-mail ou d'un serveur différent du registre.
  `lock` sans compte : code 3.
- `list`/`search` texte : alias en première colonne, toujours (`alias⇥nom⇥empreinte⇥hôtes`) ;
  `--json` : clé `account`.
- Élément désigné par (compte, id) partout : état des agents (champ `account` ; `also` en
  `<alias>:<id>` ; entrées d'avant 0.9.0 comparées par id seul), blocs générés
  (`# <nom> <alias> <id>`), lignes `Match exec` `ensure --account <alias> --id <uuid>` et
  `ensure --forward <fid> --id <alias>:<uuid>…` (alias et UUID validés). Le chemin rapide
  d'`ensure` reconnaît la nouvelle forme sans charger la CLI ; l'ancienne (`ensure --id`,
  `--forward … --id <uuid>`) reste acceptée jusqu'à la régénération : compte trouvé par l'id
  (seul compte, sinon état de l'agent, comptes déverrouillés, puis seul compte verrouillé ;
  introuvable : une ligne).
- Toute régénération du `ssh_config` (`ssh-config`, `hosts`, `forward`, `import`,
  `generate`) part des éléments de tous les comptes. Un compte illisible (verrouillé sans
  invite possible, non connecté, bw en erreur) garde ses blocs actuels, relus dans le fichier
  généré, avec un avertissement : jamais retirés. `ssh-config` demande le mot de passe de
  chaque compte verrouillé ; les écritures lisent les autres comptes sans invite. Tous les
  comptes illisibles : rien écrit.
- `ensure --forward` peut mêler plusieurs comptes : au plus une invite par compte, échec
  mémorisé pour son seul compte, tout ou rien.
- `account remove` : verrouille le compte (session oubliée), supprime ses données locales de
  `bw`, retire ses clés de l'agent dédié et des sous-agents, le retire du registre, régénère
  le `ssh_config`, sous `ensure.lock`. Une clé partagée avec un autre compte reste (promue) ;
  agent verrouillé ou en erreur : état gardé, une ligne, code 4 ; clés d'avant 0.9.0 d'un
  compte verrouillé : laissées, une ligne. Rien n'est modifié dans le coffre. `account
  rename` : données, registre, défauts, session (durée restante gardée, arrondie vers le bas à
  l'unité de `/proc/keys`), état des agents et
  `ssh_config` suivent ; alias pris : code 2, destination existante : code 4.
- Installation 0.8.0 adoptée au premier lancement : le compte connecté devient un alias
  déduit de l'e-mail, ses données passent dans `accounts/<alias>/`, compte par défaut, une
  ligne le dit ; l'ancienne session est oubliée (déverrouillage à refaire). Déplacement
  impossible : rien modifié, code 4 (sauf `config`, `agent`, `account list`, `ssh-config
  install` : avertissement). `bw` illisible : avertissement, retenté plus tard ; entre-temps
  `ssh-config` n'écrit rien (code 3) et `account add` est refusé.
- Messages qui suggèrent une commande : `--account <alias>` dès qu'il y a plusieurs comptes.
- `login` réussi : `ssh_config` régénéré s'il existe (tous les comptes), sinon « lancer
  sshvault ssh-config ». `agent status` : alias du compte en première colonne (`?` inconnu).
  Écriture sans élément trouvé, plusieurs comptes : le compte cherché est nommé. `config
  set/unset` sous le verrou du registre. E-mail commençant par `-` refusé ; `bw login -- <e-mail>`.
  Adoption remise : `status`, `list`, `lock` disent la cause au lieu de suggérer `account add`.
- Changements incompatibles : `login --server` retiré (`account add` puis `login`) ;
  `list`/`search` et `agent status` texte : colonne alias en tête, `--json` : clé `account` ; `status` : un
  groupe de lignes par compte (`alias : …`), `comptes : aucun` et code 3 sans compte ; données,
  session et mémoire d'échec par compte (nouveaux chemins) ; `ssh_config` généré : commentaire
  et lignes `ensure` avec l'alias ; état des agents : champ `account`, `also` en
  `<alias>:<id>` ; texte de l'invite du coffre.
- Invite du coffre : `sshvault : mot de passe maître du coffre « <alias> » (<e-mail>) : `
  (`(<e-mail>)` absent quand bw l'a déjà dit connecté, session refusée) ; sous `ssh`, la fin
  devient `…, clé pour <hôte> : ` (sans e-mail : `… « <alias> », clé pour <hôte> : `).
- Tests : faux `bw` multi-serveurs (`FAKE_BW_VAULTS`), `tests/test_accounts.py` (matrice de
  la story, trois sshd de test, rebond sur deux comptes) ; intégration à deux comptes
  (`SSHVAULT_IT2_*`, volet sauté sans eux).

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

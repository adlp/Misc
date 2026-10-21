# Changelog — borgHelper

## borgHelper 1.0.209, borgHelperWWW 1.34.0, UI 1.27.0, Service Worker 1.4.0 — Place libre des stockages et alertes — 2026-10-21

Chantier « reconstruction progressive », story 87b (cadrage story 87, D195/A45 ; mesures du 2026-10-20 — `work/s87b/m1.out` :
`df` par ssh refusé en ~1 s (code 2) par une clé à commande forcée `borg serve`, 0,2 s sans restriction ; `borg config` refuse un
dépôt distant ; `borg info --json` ne donne ni quota ni place ; décisions de l'utilisateur du 2026-10-20, 1 à 15).

- **borgHelper** : place libre de chaque **dépôt** (décision 8), **mesurée à la fin de chaque Bkp** (après la mesure de taille du
  dépôt et l'Index de fin, tous verrous rendus — `priority.lock` et `index-running` : un Restore, un Prune ou un Index en pause
  n'attend jamais la mesure —, après la fin enregistrée — le push de fin ne l'attend jamais, un Ctrl-C pendant elle laisse le
  Bkp « success » et son code — et, en échec, après l'alerte `bkp_error` ; JSON de sortie imprimé ensuite), gardée dans
  `history.db` — Storage, Report, borgHelperWWW et l'UI lisent la dernière mesure, sans jamais lancer ssh ni borg à l'affichage.
  - Source, dans cet ordre (décision 1) : **df local** quand le dépôt est sur cette machine — dépôt local (sauf `SSH_REPO` ou
    `SSH_REMFO` : le borg du Bkp tourne ailleurs, même prédicat que le verrou du dépôt), hôte ssh qui est cette machine **sur le
    port 22** (un autre port : `-L`, conteneur, VM — mesuré par ssh), ou **contre-tunnel** (`SSH_REMFO` vers cette machine, port
    22, ex. `8022:localhost:22` : chemin relatif ou `~u` lu dans le dossier personnel) ; sinon **df par ssh** (`<BORG_RSH|ssh>`
    dont l'exécutable ssh est suivi aussitôt de `-o BatchMode=yes -o ConnectTimeout=4 -o ControlMaster=no -o ControlPath=none` —
    OpenSSH garde la première valeur d'une option : `BORG_RSH` ne peut pas les défaire —, `[-p port] [user@]hôte "sh -c 'P=<chemin
    cité>; … $T df --output=avail,size,used -B1 -- \"$P\" 2>/dev/null || $T df -P -k -- \"$P\"'"` : `T` = `timeout 5` quand
    `timeout 5 true` marche à distance (BusyBox ancien à `timeout -t` : sans) — un df bloqué en état D peut lui survivre, le ssh
    local reste tué à 6 s ; repli pour un df sans `--output`, BusyBox ou FreeBSD ; script
    POSIX quel que soit le shell de connexion) — aussi quand le df local d'un dépôt ssh de cette machine échoue sur un dossier
    illisible ici ou un utilisateur inconnu ici (dossier d'un autre compte : mesuré par son ssh) ; sinon **capacité déclarée** (nouvelle clé `STORAGE_SIZE = 2T`, base 1000, `i` : 1024 ; une par stockage :
    la plus petite de ses nicks ; ≤ 0 ou illisible : `[WARN]`, écartée) : libre = capacité − taille mesurée des dépôts du stockage,
    marquée « ~ » — jamais à la place d'un df de moins de 7 jours du même dépôt, quel que soit le nick qui l'a mesuré (place
    inconnue, raison) ; sinon **place inconnue**. Taille de système de fichiers nulle, ou occupé + libre nuls (FUSE, rclone) :
    inconnue. `~u` d'un contre-tunnel développé par l'enfant borné du df, jamais dans borgHelper (annuaire SSSD lent) ; df local
    sans `--output` (BusyBox, Alpine) : repli `df -P -k` dans cet enfant. Quota borg (`storage_quota`, lu dans le fichier
    `config` d'un dépôt de cette machine seulement — `borg config` refuse un dépôt distant) : libre = min(libre, quota − taille du
    dépôt), taille = min(taille, quota). % occupé comme df : occupé / (occupé + libre) (décision 14). Raisons des sources écartées
    gardées, sans chemin ni sortie distante. Forme borg 2 ou à identifiants sans `STORAGE` : ligne « place inconnue » + raison,
    `[WARN]` seulement quand la raison change.
  - Jamais bloquante : **un budget de 10 s pour tout** — nom de la machine (1 s au plus), dépôt du nick (résolu par l'enfant borné
    de 87a, 5 s au plus, relecture et verrou de marque 0,5 s ; délai plein : montage marqué), autres nicks (leurs sections lues
    sous l'échéance), df, bases, Sentry (~1 s gardée pour lui). Pire cas réel : ~11 s — au-delà de l'échéance, seuls la marque
    « Sentry envoyé » (0,5 s) et les planchers des attentes SQLite (0,1 s chacune, quelques-unes) ; verrou des marques des
    autres nicks 0,5 s, sauté passé l'échéance. **Aucun accès
    disque non borné dans le processus de borgHelper** : dépôts locaux des autres nicks lus par leur section du rc seule et
    résolus par UN enfant borné (`realpath` sans ouverture, `~u` ; 3 s au plus, dans le budget ; chemin couvert par une marque de
    df bloqué ou non résolu à temps : chemin écrit) — un NFS figé ou un montage autofs d'un autre nick ne retient jamais la fin du
    Bkp ; identité du dépôt = `repo_id` (chemin résolu, sinon écrit : deux chemins vers le même dépôt par un lien ou un bind = un
    seul dépôt ; pair non résolu au même chemin écrit qu'un dépôt résolu : ce dépôt), chemin ÉCRIT gardé avec la mesure
    (`repo_wkey`) — Storage et Report retrouvent la mesure par lui sans rien résoudre, Report ne résout aucun autre nick ;
    mesure de repli (dépôt non résolu à temps) : dernière identité résolue du même chemin écrit, ⚠ et code 1 gardés. **`~` d'un
    dépôt LOCAL jamais développé** — borg ne le fait pas (mesuré le 2026-10-21 avec les trois borg de la machine : `BORG_REPO='~/r1'
    borg init` -> « <cwd>/~/r1 ») : dossier relatif au dossier courant ; **corrige aussi Storage (87a)**, qui développait `~/` par
    `$HOME` et `~u` par l'annuaire. Dépôt ssh de cette machine (`localhost:~/r`, contre-tunnel) : `~` = dossier de l'annuaire du
    compte de connexion (utilisateur du dépôt, sinon l'utilisateur courant), développé par l'enfant borné — jamais le `$HOME` de
    borgHelper. Bases lues : celles des seuls nicks du même stockage et des nicks cités par son état, attentes SQLite et écriture
    (une tentative) bornées par ce reste ; ssh 6 s au plus, processus dans sa propre session, tué avec borgHelper
    (`PR_SET_PDEATHSIG`, `prctl` résolu dans le processus parent, jamais entre fork et exec ; une enveloppe `BORG_RSH` qui lance
    ssh en petit-enfant n'est couverte que par la mise à mort du groupe au délai), entrée fermée ; df local par un enfant
    `python -I` ; toute erreur (`SystemExit` compris) : `[WARN] <nick>: place du stockage non mesurée (…)`, code du Bkp inchangé ;
    Ctrl-C : relancé par la mesure, absorbé par le Bkp (`[WARN] … mesure de place interrompue`, déjà fini). SIGTERM pendant la
    mesure (arrêt systemd, délai de borgHelperWWW) : Bkp déjà enregistré « success », mais sortie 143 sans JSON — fenêtre connue.
  - Sans injection : chemin cité pour le shell distant (`shlex.quote` ; `~u` seul non cité, nom vérifié, majuscules permises),
    utilisateur, hôte (IPv6 compris) et port restreints à des formes sûres (jamais une option de ssh, `-oProxyCommand=…` refusé
    avant tout lancement), caractère de contrôle refusé.
  - Alerte (décisions 3, 4, 6-11) : **par stockage**, chaque dépôt évalué sur sa dernière mesure avec les seuils de chacun de ses
    nicks — `STORAGE_ALERT` (défaut 90 % occupé ; nombre seul de 1 à 100 = pourcentage, « % » permis ; quantité **avec unité** =
    place libre minimale, ex. `50G` ; `off` : éteint ; autre : `[WARN]` et 90 %) et `STORAGE_ALERT_DAYS` (défaut 30 jours restants
    = libre du dépôt / croissance mensuelle du stockage, seulement si cette croissance couvre au moins 7 jours ; croissance ≤ 0 :
    inactif ; `0`/`off` : éteint ; croissance = somme des rythmes des seuls dépôts mesurés depuis au moins 7 jours) ; premier
    critère atteint ; « 90% » écrit tel quel (lu sans interpolation), « 90%% » (convention du rc) aussi ; section d'un nick
    illisible : son dépôt est inconnu, son état gardé ; nick dont tous les
    critères sont éteints : ni cité ni notifié. Stockage en alerte dès qu'un dépôt dépasse, **réarmé quand aucun ne dépasse** —
    un second disque sous le seuil ne réarme rien. **Au franchissement** seulement : `[WARN] Stockage <étiquette> presque plein :
    92 % occupé, 150.00 GB libres, ~12 j restants (df ssh, 2026-10-20 14:03) — nicks a, b` (nicks du dépôt trop plein) et Sentry
    (`SENTRY_ALERTS` gagne `storage` ; `all` = les trois ; étiquette et empreinte Sentry = identité du stockage, jamais son
    étiquette, qui peut être un chemin) ; place inconnue : état inchangé. État par stockage dans
    `CACHE_DIR/<préfixe>-storage-alert.json` (partagé par les nicks du rc ; verrou `.lock` borné, lecture sans lien ni blocage,
    `.tmp` exclusif 0600 puis `os.replace` ; fichier présent mais illisible : jamais réécrit, dit ; mesure plus ancienne que celle
    déjà notée : ignorée ; entrée non mesurée depuis 180 jours : retirée ; même dépôt sous une autre identité de stockage —
    `STORAGE` renommé, montage déplacé — : retiré de l'ancienne entrée, lui et ses nicks seuls ; nick cité dont le dépôt n'est
    plus suivi par l'entrée — `BORG_REPO` changé, passé à un autre stockage — : retiré ; taille, croissance et capacités : nicks
    du même stockage seuls ; nick absent du rc retiré seulement si le rc est lu ; `repos`, `nicks`, `views` d'un autre type :
    écartés) : deux Bkp qui finissent ensemble ne font qu'une alerte —
    dépôts des autres nicks réévalués SOUS le verrou (dépôt mesuré depuis la lecture de sa ligne : inconnu, état gardé), envoi
    Sentry réservé sous le verrou (`sentry_claim`, 120 s, horloge reculée comprise) ; Sentry jamais perdu : budget épuisé ->
    `[WARN] … reportée`, `sentry_sent` faux, envoyé à la mesure suivante ; marqué envoyé seulement si l'événement est parti (ou
    sans DSN, ou Sentry inutilisable — `sentry_sdk` absent, client non initialisé : rien ne partira jamais), sinon `[WARN] … non
    envoyée` une fois par franchissement, réservation rendue ; marque non écrite : `[WARN]`. Vue par nick cité (`views` : % occupé, libre, taille, jours, source, date) ;
    chiffres de l'entrée = nick cité le plus plein, sinon ceux d'avant (nick cité devenu inconnu). Étiquette de repli (« local ? »,
    montage non lu) : mesure gardée sans étiquette, état non touché ; ligne `storage_space` non écrite : état non touché. JSON du
    Bkp : `alert` = nick cité par l'état (mesure inconnue comprise).
  - `history.db` : nouvelle table `storage_space` (nick, stockage — empreinte et étiquette fusionnée —, dépôt, source, libre,
    taille, occupé, taille des dépôts, croissance mensuelle, quota, raison, date UTC ; dépôt : `repo_key` = identité résolue,
    `repo_wkey` = chemin écrit, colonne ajoutée sous `BEGIN IMMEDIATE` à une table d'une version de travail
    d'avant), purgée comme `repo_stats`
    (`STATS_RETENTION_MONTHS`) ; ajout pur, `HISTORY_DB_SCHEMA_VERSION` inchangée (1), comme `archive_chart`.
  - **Storage** : `space` de chaque dépôt — dernière ligne du nick pour le chemin écrit de son dépôt (`repo_wkey`, sans accès
    disque), jamais par l'étiquette re-résolue ; ⚠ par l'identité résolue de cette mesure — (`source`, `source_text`, `free`, `size`, `pct`, `days_left`, `measured_at`, `approx`, `reason`,
    `quota`, `unknown_since`, `last_known` ; jamais l'étiquette ni l'occupation du système de fichiers, hors du périmètre du nick)
    et `alert` (nick cité par un état déclenché qui suit ce dépôt) ; par
    stockage : `alert` (l'un de ses dépôts) et `space` du dépôt le plus plein ; jours restants calculés sur la croissance des seuls
    nicks de l'appel ; décision 15 : place inconnue -> « place inconnue depuis <date> (raison) — dernière mesure connue : … ».
    Texte : « — ⚠ stockage presque plein » sur la ligne du stockage, ligne « place : … » sous chaque dépôt.
  - **Report** (jumelles live et hors ligne, lignes sans archive et dépôt vide compris ; décisions 5, 12, 15) : colonne `reste`
    d'un dépôt distant = dernière place mesurée de son dépôt courant (par nick et clé de dépôt : `STORAGE` renommé, place et ⚠
    gardés ; `BORG_REPO` changé depuis : vide) — « ~ » si capacité déclarée ; mesure inconnue : la dernière connue « (place
    inconnue depuis <date>, dernière mesure connue du <date>) » (décision 15, texte et HTML) ; jamais mesuré : vide — ; dépôt dépassant son seuil : « — ⚠ stockage presque plein », nick en alerte (`***`, ligne rouge en HTML) et **code 1**
    (inventaire des consommateurs du code : borgHelperWWW `/report` — HTTP 400 comme pour MAX_AGE_BKP, réponse `-o` en cache
    renouvelée par la date de l'état d'alerte —, UI — carte en rouge par `***`, liste et carte lues sur code 1 comme avant —, cron
    et README ; aucun contrôle existant n'a de stockage mesuré) ; `-j` : champ `stockage` (étiquette, source, libre, taille,
    % occupé, date, approx, quota, inconnue depuis, dernière connue, alerte — jamais la croissance du stockage entier).
  - Bkp : `borgHelper_storage` dans le JSON de sortie. Aide : Storage, Bkp, Report (code 1).
- **CodecSelfTest** : 12 contrôles « Stockage, … » sur un df factice (aucun ne dépend du remplissage du disque ; Sentry neutralisé —
  `sentry_alert` remplacé, `BORGHELPERC_SENTRY_FILE` vide — dans chacun) : unités et seuils ; sources dans l'ordre (local,
  contre-tunnel, hôte local port 22, relatif et `~u`, autre port, `SSH_REMFO`, ssh — options juste après ssh —, repli `df -P`,
  tunnel distant, `borg serve` -> capacité déclarée par stockage, df récent gardé, taille nulle, quota, borg 2) ; injection ;
  budget (10 s / 6 s par défaut, ssh lent, base verrouillée, bases du seul stockage, aucun dépôt d'un autre nick ouvert, montage
  figé, pannes) ; alertes par dépôt (séquence à deux disques, réarmement, 2e franchissement, nick à off, ⚠ retiré, place inconnue,
  jours sur 7 jours, contrat de l'état lu par borgHelperWWW, état illisible, mesure ancienne, purge) ; deux mesures simultanées
  (deux processus) ; fin de Bkp et Report (ordre, Bkp en échec, panne, jumelles sans ssh, « ~ », inconnue depuis, quota, ⚠ et
  code 1, HTML, ligne sans archive, dépôt vide, `BORG_REPO` changé) ; fusion mode dossier ; history.db en schéma 1 ;
  `SENTRY_ALERTS` : `storage`. Revue 87b 2 : ordre de fin de Bkp prouvé par les fichiers détenteurs (`priority.lock.<pid>`,
  `index-running` — `check_priority_lock` ignore le sien) et, en échec, après la fin enregistrée et `bkp_error` ; commande distante
  `sh -c` (`timeout 5`, repli sans `timeout` par un vrai `sh`), enfant tué avec son parent (PDEATHSIG, mesuré) ; `~u` passé tel
  quel ; identité fusionnée ; taille 0 et occupé + libre nuls (local, ssh) ; % avec blocs réservés (91,8 %) ; dossier illisible ici
  -> ssh, dépôt absent ici -> jamais ssh ; df récent d'un autre nick ; Storage `-j`, texte et Popen espionné, vue sans étiquette
  ni occupation ; course forcée (1 s de sommeil sous le verrou : une alerte, un Sentry) ; fusion indépendante de l'ordre ; ligne
  rouge HTML ; date de la dernière mesure connue ; `STORAGE` renommé ; jumeau direct sans archive ; seuils propres d'un pair,
  « 90%% », alerte du JSON = nick cité, vue par nick, chiffres d'avant gardés, réévaluation sous le verrou (témoin), autre
  identité retirée, Sentry reporté puis envoyé une fois, écriture ratée, croissance sur 7 jours. Revue 87b 3 : système de
  fichiers bloquant d'un autre nick (accès du processus et enfant de résolution figés : fin de Bkp dans le budget, Report sans
  délai) ; fin enregistrée avant la mesure, Ctrl-C pendant elle ; sérialisation des deux mesures prouvée (poignée de main, aucun
  « non écrit », `sentry_sent`) ; Sentry raté renvoyé, sans DSN marqué, horloge reculée tenue ; pairs du même stockage, dépôt
  déplacé retiré seul, mesure ancienne, rc illisible ; df local `-P`. Contrôles à vrai borg et à Bkp
  sur dépôt local (`/tmp`) : `STORAGE_ALERT=off`, `STORAGE_ALERT_DAYS=0` dans leur rc — jamais dépendants du remplissage du
  disque.
- **borgHelperWWW** : alerte push « stockage presque plein » (watcher, `_storage_alert_pass`) — une par franchissement, par
  stockage **et par abonné** (décision 13, comme le retard : table `storage_alerts` de `push.db`, schéma 3, version écrite 1) ;
  chaque abonnement au type Échec d'un des nicks cités reçoit UN push qui ne cite que les nicks de son périmètre ; nick en pause
  écarté, l'alerte reste due à son abonné et part à la reprise si le stockage est toujours au-dessus ; sans abonné : non
  consommée ; mode dossier : noms exposés, un état par rc, préfixe suspendu écarté. Report `-o` en cache : empreinte avec la date
  de l'état d'alerte de chaque rc. `GET /storage` relaie `space` et `alert` (fusion des rc). Envoi push commun (`_push_deliver`).
  Revue 87b 2 : réservation lue avant écriture (aucune écriture à chaque passe), réserver puis envoyer abonné par abonné (une
  panne d'envoi ne consomme jamais l'alerte des suivants), réservations purgées avec l'abonnement (expiré, désabonné, mort) ;
  chiffres du dépôt le plus plein parmi les nicks de CHAQUE abonné ; `storage_key` (`<préfixe>|<identité>`) dans le payload ;
  « tunnel non résolu (<nick nu>) » exposé (push, Report `stockage.storage`). Revue 87b 3 et 4 : `_push_deliver` rend le succès —
  échec transitoire (5xx, 429, réseau, panne de l'envoi) : nouvel essai au passage suivant, puis attente doublée depuis 60 s
  (`storage_alerts.attempts`, `retry_at` — posé AVANT l'envoi, bail de 60 s : envoi interrompu ou suivi non écrit, renvoyé,
  jamais perdu ; colonnes ajoutées à une table d'avant sous `BEGIN IMMEDIATE`, colonne dupliquée par un autre worker tolérée), abandon après 5 envois ; échec définitif (400,
  403, 413…) : jamais renvoyé ; aucune vue des nicks
  de l'abonné : chiffres omis ; réservations d'un stockage absent de tout état servi purgées (état illisible, rc en erreur,
  suspendu ou indisponible en mode dossier : gardées ; mode `-C` sans nick lu : aucune purge). Push selftest : 5 contrôles (push par abonné, reprise après pause, mode dossier, état écrit par le vrai
  borgHelper, vue par abonné, tag, tunnel exposé, relu sans écriture, panne d'envoi, échec transitoire renvoyé, chiffres omis,
  purges, échecs transitoire/définitif, abandon, rc indisponible, -C vide, empreinte du cache, appel par le watcher) ; garde
  SQLite : 28 ouvertures (migration de `storage_alerts` sous verrou : contrôle à part).
- **Service Worker 1.4.0** : notification « ⚠ Stockage presque plein — <stockage> » (% occupé, place libre, jours restants,
  nicks), tag propre au stockage de CE rc (`storage-<préfixe>|<identité>` : deux rc au même nom de stockage distincts ; source
  vérifiée par le push selftest, aucun harnais de Service Worker).
- **UI** : bloc « Stockages » — « ⚠ stockage presque plein » sous un stockage en alerte, ligne « Place : … — <source>, <date
  UTC> » sous chaque dépôt mesuré (« ~ » si capacité déclarée ; inconnue : « depuis », raison, dernière mesure connue) ; la carte
  d'un serveur montre `reste` tel que Report le donne (rouge en alerte). Test UI : rendu et échappement.

## borgHelper 1.0.208, borgHelperWWW 1.33.0, UI 1.26.0 — Vue par hôte de stockage — 2026-10-20

Chantier « reconstruction progressive », story 87a (cadrage story 87, D195/A45 ; décisions de l'utilisateur du 2026-10-20).
Place libre et alertes avant plein : story 87b.

- **borgHelper** : nouvelle commande `Storage` (`-c Storage [-n nick|a,b|ALL] [-j]`, groupe RAPPORTS ET ÉTAT de l'aide ; sans
  `-n` : `ALL`, décision 5) — dépôts des nicks regroupés par hôte de stockage, sans jamais lancer borg ni ssh (lecture de
  `history.db`, `df` pour un dépôt local).
  - Stockage d'un nick : `user@hôte[:port]` d'un dépôt ssh (`ssh://…` ou `user@hôte:chemin`, IPv6 entre crochets ; hôte en
    minuscules ; port lu comme un nombre, 22 omis ; utilisateur implicite : son propre stockage) ; dépôt `ssh://[user@]localhost:<p>/…`
    avec un `SSH_REMFO` qui ouvre ce port : cible du tunnel (`9:nas:22` -> `nas`, avec l'utilisateur du dépôt et le port de la
    cible), jamais « localhost » (cette machine : `localhost…`, `ip6-…`, adresses de bouclage ou non spécifiées par `ipaddress`
    — `127.1`, `::ffff:…`, `::` —, son nom ; DNS inverse seulement pour un nom à point, 2 s au plus) — `SSH_REMFO` d'un autre
    port : dépôt ssh de cette machine ; illisible : « tunnel non résolu (<nick>) », jamais réuni ; dépôt local : « local <point de
    montage> » (`u@h://r` aussi, comme borg 1) ; nouvelle clé de nick `STORAGE = nom` : ce nom, quelle que soit la forme ; forme à
    identifiants ou borg 2 (`xxx://` hors ssh/file, `s3:`/`b2:` avec `…@`, `ssh://user:mdp@`) : rangée sous `STORAGE` (schéma
    seul, empreinte sans identifiants), sinon erreur du nick qui cite le schéma seul — jamais l'URL ni un secret ; liste
    blanche : seules les formes strictes de borg 1 (`ssh://[user@]hôte[:port]/chemin`, `[user@]hôte:chemin` à un seul `@`, sans
    `=` ni `::`, chemin local, `file://`) sont lues, toute autre (`rclone::…,secret=…`, `ssh://u:p/w@h/r`, `u:mdp@h:/r`…) l'est
    par son schéma seul — pris d'une liste fixe (`ssh`, `file`, `sftp`, `s3`, `b2`, `rclone`, `http(s)`, `rest`, `socket`),
    sinon « … », comme pour une valeur à caractère de contrôle (`BORG_REPO` sur plusieurs lignes, ligne suivante du rc
    comprise : chemin local et `file://` compris) ; empreinte d'un `rclone:` sans ses paires `,clé=valeur`.
  - Dépôt local : chemin réel (liens, `~`), dossier seul ouvert d'abord (`O_DIRECTORY|O_NOCTTY|O_NONBLOCK` : jamais un
    périphérique derrière un lien ; autofs ; absent ou pas un dossier : aucun `df`), `df --output=target -- .` dans ce dossier
    (`fchdir` ; environnement `PATH` et `LC_ALL=C` seuls ; inaccessible : « dossier inaccessible ») par un enfant dans
    sa propre session (`python -I`, dossier courant `/`), tué avec borgHelper (`PR_SET_PDEATHSIG`, PID du parent vérifié) : 10 s par chemin, 30 s pour l'appel dès le
    premier dépôt local (tous résolus avant toute lecture de base), groupe tué au délai, sortie relue 2 s au plus (chemin réel
    gardé), jamais attendu au-delà ; délai coupé par l'échéance : « délai de Storage épuisé », rien retenu ; sinon retenu pour
    l'appel : le montage du chemin réel, ou le chemin exact (réel inconnu, `/`, autofs) — un lien qui y mène arrête aussitôt son
    enfant ; décision 7 : `df` encore vivant après sa mise à mort -> clé, PID et heure de démarrage notés dans `CACHE_DIR`
    (`<préfixe>-storage-df-bloque.json` : verrou `.lock` non bloquant réessayé 2 s, lecture sans lien ni blocage — fichier
    ordinaire de 64 Kio au plus —, entrées filtrées — clé réduite à `/` écartée —, `.tmp` exclusif sans lien, écriture atomique)
    — aucun `df` relancé dessous tant que ce PID vit avec la même heure de démarrage (`/proc` refusé : gardée ; masqué :
    `kill(pid, 0)`, `EPERM` = vivant) ; erreur du nick « montage
    <m> ne répond pas (df bloqué) » (« ; marque non écrite » si besoin), dépôt « local ? (<chemin>) » ; `df` introuvable, en
    échec ou enfant impossible : « point de montage non lu (…) ».
  - Même dépôt sous plusieurs écritures (`ssh://h/./r`, `ssh://h/~/r`, `h:r`, `//`, `~u/`, « / » final, racine du home, lien
    symbolique local) : un seul dépôt, compté une fois, ses nicks réunis. Taille d'un stockage = somme des dernières mesures
    (`unique_csize` de `repo_stats`, première et dernière par date, id en départage) de ses dépôts distincts ; croissance = cette
    somme − somme de leurs premières mesures ; durée couverte = de la plus ancienne première mesure à la plus récente dernière ;
    moyenne par mois = somme des rythmes des dépôts mesurés sur au moins un jour (croissance / sa propre durée, mois de 30,4375
    jours). Dépôt jamais mesuré : listé, taille « — ».
  - Texte (stderr) : une ligne par stockage et une par dépôt ; `-j` (stdout) : `{borghelper_version, storages:[{storage, named,
    nicks, repos:[{repo, repo_id, kind, named, nicks, size, measured_at, first_size, first_at}], measured_repos, size, first_size,
    growth, first_at, last_at, days, growth_per_month}], errors:{nick: message}}` (tailles en octets, dates UTC ; chaînes non
    UTF-8 échappées).
  - Erreurs par nick, jamais bloquantes, code 1 : rc illisible (seule erreur `*` : « Fichier <rc> absent » ou type de l'erreur
    et clé seuls, jamais la ligne ni la valeur ; `-n ALL` passé tel quel à Storage, qui contrôle le rc d'abord), nick inconnu du
    rc (`DEFAULT`, `_…` compris), section illisible, `BORG_REPO` absent
    ou borg 2 sans `STORAGE` (nick non placé), montage qui ne répond pas, `history.db` ou `diff.db` illisible (nick placé, sans
    mesure ; base partagée verrouillée attendue une fois par appel), mesures d'avant 1.0.139 encore dans la `diff.db` (Storage ne
    migre jamais : la commande qui les migre est dite). Report inchangé.
  - Fonctions de module `_storage_of`, `_LocalResolver`, `_storage_aggregate`, `_storage_merge` (réutilisée par borgHelperWWW),
    `BorgHelperDB.get_storage_measures`/`storage_unmigrated`, `BorgHelper.storage` (`ALL` développé).
- **CodecSelfTest** : 15 contrôles « Storage » (regroupement — ssh, ports, IPv6, `user@hôte:chemin`, tunnel, bouclage, STORAGE,
  formes à identifiants sans secret, `getfqdn` compté et borné — ; identité de dépôt ; `df` borné — groupe tué, petit-enfant
  `setsid`, échéance et délai coupé, `/` et autofs au chemin exact, lien vers une clé expirée, absent sans `df`, raisons, un
  résolveur par appel — ; `df` bloqué noté avec son PID et son heure de démarrage, entrées hostiles, `/proc` refusé, marque non
  écrite ; rc illisible ; moyenne par mois ; tailles, croissance et étiquette locale
  — oracle `ismount` — sur une base connue ; mesures par date et départage ; texte ; erreurs ; bases partagées verrouillées ; sans
  `-n` = `ALL` ; chaînes non UTF-8 ; lecture seule ; fusion) ; aide : 37 entrées ; garde de fermeture SQLite : 118 ouvertures.
- **borgHelperWWW** : route `GET /storage` (niveau lecture, sans `nick`) — `Storage -j` sur les nicks que l'appelant peut lire
  (groupes actifs : niveau lecture au moins, accès direct par périmètre compris ; un autre nick n'est ni compté ni nommé, ni son
  dépôt) ; décision 6 : droits d'un nick illisibles -> nick omis, ni compté ni nommé, seule l'erreur générique
  `errors["*"]` = « droits illisibles : un ou plusieurs nicks omis (détail : journal du serveur) », le détail au journal ; aucun
  nick lisible : vue vide, rien lancé. Un borgHelper par rc (mode dossier), une seule vue réunie (même dépôt servi par deux rc :
  compté une fois), noms exposés `préfixe:nick` (« tunnel non résolu » et conseils « borgHelper -C <rc> » compris) ; rc en échec
  (délai, lancement refusé ou impossible, sortie illisible) ou illisible (absent ou refusé, rc listé par le maître compris ; `"*"`
    d'un borgHelper renommé) : `errors["<préfixe>:*"]` (`"*"` en mode `-C`), vue des
  autres rc gardée — rc illisible sous autorisation par groupes : erreur générique de la décision 6, jamais le nom du rc ; avis
  d'une même clé réunis ; journal : erreur de lecture d'un rc par son type et son numéro de ligne seuls ; section au nom de nick
  invalide (`[ALL]`…) jamais lancée ; `?nick=` ignoré (route hors `_check_group_access` : jamais un 403 qui nommerait un nick). Jamais en
  cache. Push selftest : `/storage` en mode `-C` (filtrage par groupes, vue vide, groupes inactifs, droits illisibles — nick ni
  compté ni nommé, détail au journal —, borgHelper en échec, illisible ou non lancé, rc illisible ou absent, noms exposés,
  `?nick=`, formes à secrets absentes de la réponse) et en mode
  dossier (tous, g-mail, g-web, aucun groupe, groupes inactifs — vues comparées aux sorties CLI de chaque rc ; rc refusé au
  lancement, illisible, indisponible).
- **UI** : bloc « Stockages » au-dessus de la liste des serveurs (chargé avec elle, à part) — une ligne par stockage (dépôts,
  taille, croissance, par mois, depuis la première mesure et durée en jours) et une par dépôt (nicks, taille, date de mesure ou
  « aucune mesure ») ; erreurs par nick et par rc dessous ; masqué si le serveur n'a pas `/storage`. Test UI : rendu, échappement
  (dates comprises), chargement (succès, code 1, 404 de route, 403, illisible, réponse dépassée), appel par la liste.
- Report différé : `get_repo_stats` (Report) lit encore la dernière mesure par id (deferred-work.md, story 87a).

## borgHelperWWW 1.32.1, UI 1.25.0 — UI groupée par fichier de conf (mode dossier) — 2026-10-20

Chantier « reconstruction progressive », story 86b (suite de la story 86, décisions de l'utilisateur du 2026-10-20).

- **borgHelperWWW** : `GET /access` donne, en mode dossier seulement, `rc_order` — préfixes dans l'ordre des lignes
  `[_borgHelperWWW_rc]` du maître (relu à chaud), restreints à ceux dont l'appelant peut lire au moins un nick (même
  ensemble que `suspended_prefixes`). Ce filtre ne cache rien de plus : `nicks` de la même réponse liste déjà tout nick exposé, y
  compris ceux sans droit (`level: "none"`, comportement antérieur, report différé). Mode `-C` : champ absent, réponse inchangée. Push selftest : contrôle
  « /access rc_order » (ordre du maître, maître inversé à chaud, filtré par droits : tous, g-mail, g-web, aucun groupe,
  groupes inactifs) ; contrôle `/access` du mode `-C` : `rc_order` absent.
- **UI** (mode dossier, `rc_order` présent) : liste des serveurs groupée par fichier de conf — un titre par préfixe, ses
  cartes dessous, groupes dans l'ordre du maître (préfixe absent de l'ordre ensuite, trié), nicks triés par nom dans chaque
  groupe ; carte titrée du nick nu, nom complet `préfixe:nick` en infobulle, dans les boutons, liens, URL et requêtes.
  Groupes repliables (titre `h3` portant un vrai bouton : clic, Entrée/Espace du navigateur ; `aria-expanded`,
  `aria-controls`, flèche `aria-hidden`) : replié, nombre de serveurs et « ⚠ erreur » si l'un est en
  erreur (tenu à jour au rechargement d'une carte en fin de Bkp) ; état par navigateur (`localStorage`, clé
  `bhww_rc_collapsed`, réduite aux préfixes affichés), tout déplié par défaut ou si le stockage est indisponible ; lien rapide
  vers un groupe replié : déplié à l'écran seulement, choix « replié » gardé ; une carte rechargée en fin de Bkp garde le titre
  de la liste dessinée. Barre de liens rapides groupée (« web : db · front │ mail : db · imap »), page Notifications : un sous-titre par
  fichier de conf ; abonné, la page montre la portée figée de l'abonnement (AD-4) — un préfixe qu'on ne lit plus y garde
  son sous-titre, après ceux de l'ordre (nom sans préfixe d'un ancien abonnement : « (sans préfixe) », en dernier). Un seul utilitaire de
  regroupement (`nickGroups`) pour les trois listes. L'UI n'a aucun sélecteur de nick (`<select>`) : rien à grouper en
  `optgroup`. Mode `-C` : rendu identique à 1.24.3.
- **Test UI** (`borgHelperWWW_ui_test.js`) : mode `-C` comparé au rendu de 1.24.3 (empreintes de la liste, de la barre et des
  Notifications avant et après abonnement, relevées sur e790e8b avec le même décor) ; mode dossier : ordre, préfixe hors
  ordre, nicks nus triés, noms complets (boutons, liens, cases, Report), droits (groupe absent), stockage indisponible ou
  illisible, Notifications abonné ; par les vrais gestionnaires (clic sur le titre, lien rapide, bouton Ouvrir) sur un faux DOM
  tiré du HTML produit : repli mémorisé, lien rapide sans mémoire, mémoire réduite, `reloadMachineCard` en mode dossier (titre de
  la liste dessinée, ⚠ du groupe replié), carte retrouvée par le nom de ses boutons ; noms hostiles (préfixe et nick) échappés
  dans les titres, la barre, les cartes et les Notifications ; exception du rendu = FAIL.

## borgHelperWWW 1.32.0, UI 1.24.3 — Mode dossier : plusieurs .borghelperrc — 2026-10-20

Chantier « reconstruction progressive », story 86 (report D194, point « plusieurs fichiers borghelperrc », tri A46/A122 S-t).
Un seul borgHelperWWW sert plusieurs `.borghelperrc` ; la CLI borgHelper garde un seul `-C` (borgHelper inchangé).

- **Correctif de sécurité (mode `-C` compris, faille de 1.31.19)** : le contrôle des groupes est fait aussi quand `nick` est
  absent — `/stats`, `/report`, `/cacheinfo`, `/cacheclean`, `/idxtop`, `/difftop`, `/idxpurge` sans `nick` (défaut : tous les
  nicks) sont contrôlés comme `nick=ALL`. Avant, `_check_group_access` sortait sans contrôle : un groupe sans droit sur un nick
  lisait ses données et `/cacheclean`/`/idxpurge` agissaient. Désormais 403, rien lancé ; groupe qui a les droits : inchangé.
  `/stats` sans `nick` : chaque section que `borgHelper -c Stats` affiche est contrôlée (une section à clé `ALL` comprise).
- **Correctif de sécurité (mode `-C` compris)** : routes à un nick (LstBkpFls, DiffBkp, Restore, Restore -L, téléchargements),
  appelant à périmètre restreint — périmètre calculé sur le nick réellement lancé ; `ALL`, vide, espaces autour, liste ou doublon :
  400, rien lancé. Avant : périmètre lu sur la chaîne brute (`cfgread` -> aucune section = « illimité ») ; mesuré en `-C` (deux
  nicks, groupe à périmètre) : aucune donnée livrée (borgHelper y voit un nick inconnu), 1.31.19 comme 1.32.0 ; en mode dossier,
  le nom nettoyé était lancé — périmètre contourné.

- **Lancement** `--cfgdir <dossier> --master <rc>` (`BORGHELPERWWW_CFGDIR`/`_MASTER`, clés `cfgdir`/`master` du fichier de
  conf ; variable vide = absente), exclusif de `-C` ; `--selftest` exige `-C` (refus avant tout effet) ;
  `BORGHELPERC_RUNTIME_PASSPHRASE` dans l'environnement : refus au démarrage (`[ERREUR]` : elle serait remise au borgHelper de chaque
  rc). Mode `-C` : `BORGHELPERWWW_CFGFILE` présent mais vide jamais comblé par le `cfgfile` du fichier de conf (comme 1.31.19). Le maître, un des rc du dossier, est le seul lu
  pour `[_borgHelperWWW]` (celle d'un autre rc : `[WARN]`, ignorée) et liste les rc servis, maître compris : section
  `[_borgHelperWWW_rc]`, une ligne `fichier = préfixe` (chemin relatif au dossier ; préfixe : mêmes caractères qu'un nick). Un rc
  listé par un lien garde le nom du lien (`-C`, préfixe des bases).
- **Noms** : tout nick est exposé `préfixe:nick` (API, `/access`, abonnements, notifications, caches, UI en liste plate) — un
  même nick dans deux rc est permis. Chaque borgHelper lancé reçoit le `-C` du rc de son nick et le nick nu ; toute lecture de
  base passe par ce rc. Requête sur plusieurs rc (`ALL` = tous les nicks de tous les rc, développé une fois par requête) : un
  borgHelper par rc, qui reçoit la liste EXPLICITE des nicks contrôlés (jamais `-n ALL` ; nicks dont l'opération n'est pas
  permise écartés comme la CLI), sorties JSON réunies aux noms exposés (Report : `Totaux` = somme des Totaux affichés,
  réarrondie : écart au plus 0,005 unité affichée par rc plus 0,005 de l'unité du total ; DuIdx `-R` : recalcul des lignes
  brutes de chaque rc, lues entières en mémoire — limite —, erreurs de chaque rc gardées, `{}` sans ligne ; même clé de valeurs
  différentes : `préfixe:clé` ; JSON demandé : jamais un corps texte ; appelant à périmètre : sortie non JSON d'un rc jamais
  recopiée, même dans stderr — erreur dite), texte concaténé sous `── préfixe ──`, code le plus grand. `X-Borg-Passphrase` sur
  plusieurs rc : 400. Au lancement, CACHE_DIR du rc relu : 503 + `[WARN]` s'il diffère de la liste servie. `/stats` sans `nick` :
  chaque rc lancé sans `-n` (une liste `a,b` donnait « a,b pas trouvé »). `nick=` vide : 404 (seul l'absent prend la valeur par
  défaut ; avant : tous les nicks de tous les rc — Prune, DelBkp compris). Restore : `-L` reconnu comme option seulement, jamais
  comme valeur de `-f` (dépôts externes écartés). Limite : un nick devenu externe entre ce filtre et le lancement fait sortir
  l'enfant en code 4 et saute tout son rc (fenêtre étroite). Report HTML, RepoHistory, ArchiveHistory, LstBkpFls, DiffBkp, IdxTop/DiffTop JSON sur plusieurs rc : `400` « un
  seul fichier de conf par requête pour cette commande ». Délai ou lancement détaché refusé sur un rc après d'autres : ce qui
  est fait est dit. Chemin d'un rc jamais exposé (`<rc préfixe>` : stderr, le message « … pas trouvé dans <rc> » de stdout, détail
  d'erreur ; rc illisible : 500 « configuration illisible » comme en `-C` ; les données de stdout jamais touchées) ; conseils « borgHelper -c … » de stderr complétés en « borgHelper -C <rc préfixe> -c … ».
  Nom sans préfixe, préfixe inconnu, `préfixe:ALL`, liste vide : 404 « Nick inconnu » (`web:zzz` : réponse de borgHelper pour
  un nick inconnu, comme avant). `POST /login` : `nickname=préfixe:nick` obligatoire, droit admin du `[DEFAULT]` de ce rc.
- **Bases propres à WWW** (scopecache.db, push.db, préférences push) : dossier et préfixe du maître. **CACHE_DIR distinct par
  rc** exigé (borgHelper résout la passphrase d'une base par son dossier : deux rc au même dossier se liraient l'un l'autre).
- **Erreurs au démarrage** (`[ERREUR]`, refus) : rc listé absent ou illisible, préfixe en double ou invalide, fichier absolu,
  hors du dossier ou listé deux fois, maître absent de sa liste, section de liste absente, CACHE_DIR partagé ou inutilisable,
  `-C` avec `--cfgdir`, `--cfgdir` sans `--master`, dossier ou maître introuvable, maître hors du dossier.
- **À chaud** : maître, rc listés et mémoire des préfixes relus quand ils changent (signature prise avant la lecture ; relecture
  hors de la boucle d'événements, une par requête et par passe du watcher, du contrôle de schéma et du nettoyage horaire) — rc
  ajouté (`[WARN]` s'il porte `[_borgHelperWWW]`), retiré ou modifié pris en compte sans redémarrage ; liste devenue invalide
  (CACHE_DIR non créable compris ; validée entière avant toute construction, rien créé) : `[WARN]` une fois, ancienne liste
  gardée et ses fichiers toujours surveillés, nouvel essai toutes les 30 s, aucun nettoyage d'abonnement ; CACHE_DIR d'un rc
  indisponible toujours réservé ; rc devenu absent ou illisible : `[WARN]` une fois, ses nicks absents (jamais une erreur), ses
  abonnements gardés. **Préfixe réattribué** à un autre fichier : abonnements et alertes de retard de ce préfixe suspendus
  (fichier mémorisé par préfixe, relatif au dossier, dans `<préférences push sans .json>-rc-files.json` ; mémoire illisible ou
  verrouillée : préfixes non prouvés inchangés suspendus ; écriture en échec : `[WARN]` une fois, jamais une erreur, réessayée
  toutes les 30 s), hôtes de ce préfixe ignorés à l'abonnement et au PATCH (jamais un 409 : l'UI envoie tous ses hôtes) et gardés
  avec leurs réglages dans un abonnement existant (synchro, réabonnement), suspension dite par `/access` pour les seuls nicks
  lisibles par l'appelant, `[WARN]` une fois.
- **Passage au mode dossier** : au démarrage, nick nu d'un abonnement push et d'une alerte de retard déjà envoyée rattaché au
  MAÎTRE seulement (`maître:nick`, si le maître a ce nick ; atomique, jamais une perte ; une seule fois par push.db — marque posée
  seulement si les préférences ont été lues, sinon réessayé au démarrage suivant ; nom nu restant ensuite : `[WARN]` à chaque
  démarrage ; ligne nue d'alerte retirée si la préfixée existe) ; sinon `[WARN]` une fois, laissé tel quel (sans effet, jamais retiré par le
  watcher), jamais rattaché à l'homonyme d'un autre rc. Limite : un push.db explicite repris sous un autre maître que l'ancien
  rc `-C` rattache à ce maître. Retour au mode `-C` : noms
  préfixés jamais retirés par le nettoyage horaire. Aucune clé API à portée n'existe : rien d'autre à migrer.
- `/access` `borg_cleanup` : fichiers borgHelper de chaque rc ; entrées borg qu'aucun rc servi ne reconnaît (aucune si un rc
  listé est indisponible).
- **UI 1.24.3** : badge « base non chiffrée » — commande conseillée juste en mode dossier (`borgHelper -C <rc du préfixe P> -c
  DbEncrypt -n <nick nu> -y`) ; test du routeur : adresses à nick préfixé.
- **Mode `-C`** : chaque site garde son appel d'avant (écarts : noms préfixés jamais retirés du nettoyage horaire ; correctif de
  sécurité ci-dessus). Mesure
  ponctuelle (`work/s86/cmp86.py`) : 38 requêtes sur le bac lk, mêmes réponses que 1.31.19 sans groupes, avec un groupe qui lit
  `la`/`lb` (27 réponses 200) et avec un groupe borné par GROUPS_PATHS (24 réponses 200) — seuls version, clé VAPID et chemin de
  travail diffèrent (mesure faite avant le correctif de sécurité, qui change les routes sans `nick` sous un groupe sans
  droit). Push selftest 1.31.19 sans écart.
- Push selftest : +25 contrôles (liste du maître, sorties exposées/fusionnées, correctifs `nick` absent, `/stats` et route à un
  nick en `-C`, passphrase d'environnement refusée, `cfgfile` vide en `-C`, migration réessayée, nettoyage, miroir DuIdx, garde AST, démarrages
  refusés, précédence des modes, enfant réel en mode dossier : noms, argv de chaque borgHelper, décision 11, lancement partiel
  et délai, nick inconnu, groupes et Login par rc, migration au maître et nom de la notification, rechargement à chaud et
  préfixe réattribué, lectures réelles par rc — téléchargements, caches, DuIdx `ALL`, `/access`, watcher, rapprochement).
  `_SCG_SEEN_WWW` 20 (ouvertures de push.db de la migration).
- Constat, non corrigé : le `-wal` vide d'une base, recréé par chaque lecture, change l'empreinte des routes à périmètre — leurs
  lignes de scopecache.db ne sont jamais resservies (les deux modes, 1.31.19 compris ; mesuré en story 86).
- Limites : UI groupée par rc à venir (story 86b) ; le texte de borgHelper garde les nicks nus et les conseils de commande de
  stdout leur forme sans `-C`.

## borgHelper 1.0.207 — Snapshots des archives anciennes après reconstruction — 2026-10-17

Chantier « reconstruction progressive », story 85 (report D193, point « snapshots d'archives anciennes non refaits
par une reconstruction »). Mesuré sur 1.0.206 (borg 1.2.6, bac neuf, `work/s85/mesure85.sh`) : nick à 4 archives sauvegardées
avec Index -> 4 snapshots ; `Index --rebuild` -> 1 snapshot (dernière archive) ; `LstBkpFls -b <2e archive>` : 3 fichiers
avant, « Aucun fichier indexé pour … — lancer 'indexsnap'. » après (`Index -S` ne refait que la dernière archive).

- **Reconstruction** (`Index --rebuild`, fantôme ou construction directe d'une base absente ; décision A de l'utilisateur) :
  refait le snapshot de chaque archive que la rétention garde (`IDX_SNAP_KEEP`, défaut : somme des `KEEP_*`, sinon 10 —
  les archives que `_snapurge_check` garderait), avec les règles `IDX_*` actuelles. En dernier dans la tranche : snapshot de
  la dernière archive, statistiques, diffs, puis snapshots anciens de la plus récente à la plus ancienne. Une archive = une
  unité (`borg list` complet, même code que le snapshot de la dernière : `indexsnap(archive=…)`) ; échéance vérifiée entre
  unités, `borg` en cours tué à l'échéance, rien d'écrit pour l'archive tuée ; reprise sans refaire les archives déjà
  faites. `-T snap` les comprend, `-T stats`/`diff` non ; `-b/-B` les restreint comme les statistiques.
- **Fantôme complet** (`build_state`, bascule) seulement une fois ces snapshots faits : `snapshot` reste `false` tant qu'il
  en manque (clés de `build_state`, format de `Status -j` et texte « Construction partielle » inchangés). Ligne de fin de
  tranche d'une reconstruction : « snapshots k/N » au lieu de « snapshot fait/à faire » ; un snapshot ancien fait compte
  comme une progression (pas d'avertissement « aucune progression »).
- **`borg list` d'une archive ancienne tué hors échéance ou en échec** (décision 3, précisée par les revues) : snapshots
  anciens arrêtés pour la tranche, nouvel essai à la suivante ; au 3e échec ou arrêt consécutif de la même archive (nom et
  date de début), sautée sans bloquer la bascule — `[WARN] <nick>: snapshot de <archive> sauté pour cette reconstruction (3e
  échec ou arrêt consécutif de borg list : <cause>) — Index --rebuild -F pour la reprendre de zéro` (`DB_NAME` partagé :
  supprimer la base puis relancer `Index --rebuild`) ; `--rebuild -F` réessaie tout. Tué = code négatif, ≥ 128 (143 d'un
  SIGTERM géré par borg) ou 1 sans sortie ; l'échéance ne compte jamais. Compteurs dans le `db_meta` de la cible
  (`snap_failed:`/`snap_skipped:<nick>`), retirés à la bascule et à la fin d'une construction directe.
- **Construction directe** (base absente) poursuivie par `Index -t` et `Index` sans option (marqueur `rebuild_direct:<nick>`,
  jamais sous NOIDX, illisible = présent) jusqu'à ce qu'elle soit complète — avant (revue) : la tranche suivante la
  déclarait complète sans les snapshots anciens. Jamais par l'Index d'un Bkp (ciblé ou en attente), qui ne la déclare pas
  complète ; base servie avec un fichier fantôme : seul le fantôme fait la phase (tout Index). Marqueur non écrit :
  `[ERREUR]`, passe arrêtée (code 1) ; illisible : `[WARN]`, ni phase ni état de construction écrit. Un snapshot non gardé
  après son unité ou un code d'erreur d'`indexsnap` comptent comme un échec (même seuil).
- **Rétention des snapshots chronologique** (`indexsnap`, `IdxPurge`) : les plus anciens par date d'archive, jamais la
  dernière. Mesuré sur 1.0.206 (bac s85, `IDX_SNAP_KEEP=2`, dernière archive `…-0000-recente`) : par nom, son snapshot était
  fait puis supprimé aussitôt (« 11 entrées snapshot supprimées (3 archives anciennes) ») ; sur 1.0.207, `…0000-recente` et
  `…222619` gardées. Un snapshot sans aucune date connue est gardé (hors compte) ; IdxPurge garde aussi celui de
  l'archive la plus récente d'`archive_stats`.
- `IDX_SNAP_KEEP`/`KEEP_*` invalide : un `[ERREUR]` lisible, seule la phase des snapshots anciens ou la purge est sautée
  (diffs et statistiques faits ; reconstruction jamais complète), jamais une trace — Index, `indexsnap`, IdxPurge (code 1,
  plus de ligne « aucun IDX_INCLUDE » trompeuse) ; `-H Index` : ordre de la tranche corrigé, snapshots
  des archives gardées par `IDX_SNAP_KEEP` mentionnés.
- **LstBkpFls** (décision A) : archive sans snapshot -> « Aucun snapshot pour <archive> dans la base (seules les
  IDX_SNAP_KEEP archives les plus récentes en ont un) » ; sentinelle sans ligne -> « Aucun fichier dans le snapshot de
  <archive> (archive vide ou chemins exclus par IDX_INCLUDE/IDX_EXCLUDE) » ; archive inconnue de la base -> « Archive <archive>
  inconnue de la base (voir LstBkp) » seulement si elle n'est dans aucune table d'archives ; message de rétention seulement
  pour une archive plus ancienne que la fenêtre gardée (sinon « … (jamais fait ou sauté — Index --rebuild refait …) ») ;
  base absente -> message existant ; NOIDX -> « <nick>: indexation désactivée (NOIDX=1) ». Code 1 inchangé, `{"error": …}`
  avec `-j`.
- Inchangés : `Index` sans `--rebuild` (snapshot de la dernière archive), tranche ordinaire de la base servie, `Index -S`.
  Rétention factorisée (`_snap_keep`, mêmes valeurs pour `indexsnap` et `IdxPurge`).
- Mesure rejouée (bac recréé) : 4 snapshots avant et après `--rebuild` (2, 3, 4, 5 fichiers), lignes (archive, date, chemin
  stocké, taille, mtime, type, mode, propriétaire) identiques, `LstBkpFls -b` identique pour les 4 archives, 8,5 s.
- borgHelperWWW non modifié : `Status` (`build`/`rebuild`, mêmes clés) et `rebuild` relayés tels quels ; message de
  `LstBkpFls` relayé dans `{"error": …}`.
- CodecSelfTest (vrai borg) : neuf contrôles (dont : fenêtre de rétention avec 8 archives et IDX_SNAP_KEEP 10, 8, 5 ; codes 143 et 1 sans sortie comptés, échéance jamais comptée, 0 sans
  sentinelle compté ; marqueur jamais sous NOIDX, base marquée + fantôme, conseil `DB_NAME` partagé, marqueur illisible ;
  archive connue des seules paires ou lignes de snapshot ; sentinelles non rapprochées datées plus tard) — — dépôt neuf à 5 archives indexées une à une : snapshots refaits identiques
  (sentinelles, chemins, versions) à ceux d'Index successifs, en clair, chiffrée et `IDX_SNAP_KEEP=3` (jamais un `borg list`
  au-delà), après le dernier `borg diff`, construction directe, Index ordinaire et `-t` sans `--rebuild` inchangés, Index sans
  option après une reconstruction sans phase, chaque message de LstBkpFls ; tranche tuée pendant le snapshot d'une archive
  ancienne -> rien d'écrit pour elle, fantôme partiel (clés exactes, pas d'« aucune progression »), reprise, bascule ; tué
  hors échéance / en échec -> compté, phase arrêtée, retour entier, entrées disparues retirées, sautée au 3e, clés retirées
  à la bascule ; construction directe en plusieurs appels (`--rebuild -t`, `Index -t`, Index d'un Bkp sans phase, `Index`),
  clés retirées à la fin ; noms non chronologiques (Index, `--rebuild`, IdxPurge dry-run et réel, sentinelle sans date
  gardée) ; `IDX_SNAP_KEEP` invalide.

## borgHelper 1.0.206 — Aide simplifiée — 2026-10-17

Chantier « reconstruction progressive », story 93 (demande de l'utilisateur). Mesuré sur 1.0.205 : `-h` de 110 lignes à
plat, `DiffTop` absent, textes sans accents ; `-H` n'annonçait que 7 commandes (dont deux noms inconnus de `-c`), aucune fiche
n'avait d'exemple, `-H DiffTop` et `-H LstBkpFls` répondaient « Desole pas de documentation » ; `usage()` sortait toujours
en 1 (`sys.exit(1)` en fin de fonction) — aide réussie, erreur d'arguments, getopt invalide et argument parasite compris ;
messages illisibles (`p`, `r`, `step2f`, « Mais comment on peut en arriver la ? ») ; `Login -n <nick> -r x` sans `-p`
réécrivait la section du nick dans le fichier de conf AVANT de signaler l'option manquante.

- **`-h`** (stdout) : les 36 commandes, une ligne chacune, en sept groupes (SAUVEGARDE ; CONSULTATION ET RESTAURATION ;
  INDEX ET RECHERCHE ; RAPPORTS ET ÉTAT ; BASES LOCALES ; CONNEXION ; DIAGNOSTIC), ⚡ sur Prune, DelBkp, IdxPurge ; options
  communes ; renvoi « Fiche détaillée avec exemples : borgHelper -H <commande> ». 54 lignes, 92 colonnes au plus. Code 0.
- **`-H <commande>`** (stdout) : fiche pour chaque commande — titre, Syntaxe, Options (une par ligne, exactement celles que
  la commande accepte), Description (détails longs repris des anciennes fiches et vérifiés dans le code), 2 à 4 exemples
  commentés. Nom insensible à la casse ; `ListBkp`, `ListBkpFiles`, `listbkpfls` acceptés. Code 0 ; nom inconnu ou vide :
  `[ERREUR] pas de fiche pour <nom>` (`''` si vide) + liste des fiches, code 2. Corrections au passage : TreeFind `-m`
  facultatif (défaut `*`) ; FileHist sans `-b` : dernière archive indexée (tout l'historique : `-b ALL`) ; DiffBkp `-w`
  accepté sans effet ; DuIdx `-R` : un JSON `{borghelper_version,pattern,rows}` ; RepoHistory/ArchiveHistory : plusieurs
  nicks sans `-j`, un seul avec ; variable Sentry `BORGHELPERC_SENTRY_DSN` (l'aide citait `BORGHELPERC_SENTRY_ID`, jamais
  lue) ; fiches qui citent des codes : « code 2 aussi : erreur d'arguments ».
- **Erreur d'arguments** (stderr) : `[ERREUR] <Commande> : <message>`, la syntaxe de la commande, `  détail : borgHelper -H
  <Commande>`, code 2 (avant : 1) — option manquante (`-f <chemin> obligatoire`…), refusée (`option -f non acceptée`),
  réservée (`--rebuild réservé à Index`), getopt (`option -Z inconnue`, `option --h ambiguë`…), argument en trop, valeurs
  d'Index (`-t`, `-T`, tranche incompatible), `-j` sur plusieurs nicks. Nouveaux refus (avant : trace Python, code 1) :
  `-N`/`-p` non entiers (Report, IdxTop, DiffTop), DiffBkp `-b` à plus de deux archives. CodecSelfTest et PerfBench
  refusent les options qui ne sont pas les leurs (avant : ignorées) et donnent leurs erreurs de valeur dans ce format
  (« motif vide refusé », « motif invalide », « -n invalide » ; avant : leur propre ligne, code 2). `-c` inconnu (même avec
  une option ou un argument en trop) : `[ERREUR] commande inconnue : <nom>` + `  commandes : borgHelper -h`, code 2 ; sans
  `-c` : aide globale sur stderr, code 2.
- **Avant toute écriture** : toutes ces vérifications passent avant la création du dossier de cache, la porte d'autorité des
  dépôts externes (code 4) et la première écriture — Login ne réécrit plus le fichier de conf quand `-p` ou `-r` manque
  (avec ou sans `-k`). Pour `-j` avec `-n ALL`, la liste des nicks est lue dans le rc (lecture seule). Analyse des options
  inchangée (`_CLI_OPTAB`, mêmes règles).
- **DelBkp** : seul `-b last` exact est refusé ; un nom d'archive qui contient « last » est désormais accepté (avant : refusé),
  en CLI comme par `DELETE /delbkp` (décision de l'utilisateur). `-b` vide ou blanc refusé (code 2), en CLI et dans
  `BorgHelper.delbkp` avant tout verrou et tout borg — mesuré sur 1.0.205 : `-b ''` lançait `borg delete ::`, qui demandait
  de supprimer le DÉPÔT ENTIER (arrêté seulement par la question YES de borg, faute de terminal). Nom littéral pour borg :
  accolades doublées dans `borg delete ::<nom>` (mesuré sur 1.0.206 avant ce correctif : `-b '{user:.0}'` ou `'{now:%n}'`,
  marqueurs remplacés par borg, donnaient `::` — même question) ; nom non chaîne (bibliothèque) ou avec un caractère de
  contrôle (saut de ligne, tabulation, NUL…) refusé, code 2. Login : `-r` vide ou blanc refusé.
- **Login** : `-p`, `-r`, les noms `-n`/`-s` (règles de `_valid_nick_name` : ni `ALL`, ni liste, ni caractère spécial) et la
  présence du fichier `-k` sont vérifiés avant toute écriture (avant : section du nick réécrite, puis refus ; `-n ALL`
  étendu au nick du rc).
- **Exemples** : Search `-f 'etc/nginx*'` et IdxPurge `-x var/log` (sans `/` initial : les chemins de l'index n'en ont pas ;
  Search, DuIdx et IdxPurge ne le retirent pas — mesuré ; FileHist, TreeHist, TreeFind si). Argument parasite : conseil
  `-n <nick>` seulement si la commande accepte `-n`.
- borgHelperWWW non modifié : quatre routes peuvent tomber dans une erreur d'arguments (`DELETE /delbkp` avec `bid=last` ou
  vide, `/diffbkp` avec une virgule dans un `bid` — avant : trace, code 1 —, /repohistory et /archivehistory sur plusieurs
  nicks) — toujours 400 ; le corps porte `exitcode` 2 et le nouveau message ; les deux routes d'historique ne mettent plus
  cette erreur en cache.
- CodecSelfTest : dix contrôles « aide : … » (dont DelBkp `-b` vide : CLI et bibliothèque, aucun borg, aucun verrou) (table et groupes, ⚡, options, Syntaxe et Description, exemples analysés, `-h`,
  `-H`, `-H` inconnu, `-c` absent ou inconnu, erreurs d'arguments par `_cli_main`, aucune écriture avant l'erreur) ;
  RepoHistory/ArchiveHistory `-j` multi-nicks et la CLI d'Index exigent désormais le code 2 (et le texte de l'erreur).

## borgHelper 1.0.205, borgHelperWWW 1.31.19, UI 1.24.2 — Mesures jamais faites — 2026-10-17

Chantier « reconstruction progressive », story 84 (reports D149, D155, D171, D198). Quatre mesures faites (borgHelper
1.0.204, borgHelperWWW 1.31.18, borg 1.2.6) ; D198 change des délais d'attente de verrou, D149 le texte du `[WARN]` et du badge
HTTP/1.0.

- **Écrivains de diff.db pendant une bascule** (D198) : mesuré sur le SSD NVMe du poste de test (Samsung PM9A1), `_swap_db` bascule `diff.db` à
  116-127 Mo/s (370 Mo en 3,2 s, 699 Mo en 5,5 s) ; des écrivains lancés ~1 s après le début de la copie (défaut de sqlite3 5 s,
  `timeout=60`, reprise 300 s) écrivent tous, rien perdu. Un écrivain présent dès le début de la copie l'attend en entier : au
  défaut de 5 s, il échoue dès ~550-600 Mo ; plafonds désormais : 60 s ≈ 7 Go, reprise 300 s ≈ 34 Go (moins sur un disque plus
  lent ou NFS). Inventaire site par site : le compactage d'IdxPurge ne prend aucun verrou, un Index tourne donc pendant sa
  bascule. Passent à `timeout=60` : `indexsnap` (`--force` et lignes sans sentinelle), `_index_select_pairs` (purge des paires à
  refaire), `_index_finish` (état de construction), `_shadow_swap` (après la bascule), `_db_migrate_run` (DbEncrypt/DbDecrypt),
  `db_rekey` et `archive_view_check(repair=True)` (nouveau paramètre `timeout`, 60 s par défaut). Index, DbEncrypt, DbDecrypt et
  DbRekey attendent donc jusqu'à 60 s pendant une bascule concurrente au lieu d'échouer (avant : « SQLite error … database is
  locked » — Index : paire non refaite, état de construction non écrit ; DbEncrypt, DbRekey : échec). Délais courts voulus,
  sans perte : `_recheck_zero_pairs` et `_drop_orphan_exclusions` (2 s, refaits au prochain Index), `ensure_diff_db`/
  `ensure_cache_db` en lecteur (2 s, rien écrit si occupée), réparation de vue de borgHelperWWW (2 s, passe suivante).
  DbEncrypt/DbDecrypt et DbRekey font leur KDF hors de tout verrou d'écriture (comme avant), puis prennent le verrou
  d'écriture, relisent l'en-tête (identique à celui de la KDF, sinon « en-tête changé entre-temps — relancer ») et revérifient
  les verrous de borgHelper (une opération prioritaire démarrée pendant l'attente est vue : refus, rien écrit) ; première
  écriture d'en-tête dans la même transaction (`_enc_header_write`/`_enc_header_cas`, paramètre `held` ; `held=True` sans
  transaction ouverte : RuntimeError, rien écrit) ; erreur SQLite sous ce verrou : `[ERREUR]` habituel, jamais une trace brute —
  `sqlite3.OperationalError` (verrou, disque plein, base en lecture seule, E/S) -> DbModeError (« … — relancer »), toute autre
  `sqlite3.DatabaseError` (base abîmée) -> DbTamperError, même règle pour les deux sens et pour DbRekey. Réparation de la vue relue sous `BEGIN IMMEDIATE` avant DROP/CREATE
  VIEW (un état lu avant une bascule ne décide plus d'une écriture faite après), par une seule fonction
  (`_repair_archive_view(conn, held)`) pour `ensure_diff_db` et `archive_view_check` ; celle-ci rend l'état relu sous verrou. Docstring d'`_open_db` corrigée (elle disait « timeout=60 » ; sans `timeout`,
  c'est le défaut de sqlite3, 5 s). Contrôles CodecSelfTest : bascule étirée à ~7 s dans un autre processus (témoin au défaut
  refusé avant la fin de la copie ; `archive_view_check` et `_index_finish` attendent puis écrivent dans la base basculée ; base
  basculée qui porte déjà la bonne vue : `'ok'`, aucun DROP/CREATE) ; DbEncrypt/DbRekey et opération prioritaire apparue pendant
  l'attente du verrou ; KDF hors verrou (une autre connexion prend le verrou sans attendre à chaque KDF) ;
  `_repair_archive_view(held=True)` sans transaction : RuntimeError ; garde AST de tous les écrivains (délai ≥ 60 s jugé par valeur, paramètre jamais réaffecté et appelants
  vérifiés, `_with_lock_retry` réellement passé sans `max_wait` court ni appel direct, ou liste blanche par appel avec sa raison,
  une entrée = un site, branche lecteur seule pour `ensure_*` ; `**kw` refusé ; témoins ; limites reportées : paramètre relié par
  with/except/import/nonlocal/match).
- **borgHelperWWW 1.31.19** : le contrôle périodique de la vue (`_schema_watch_pass`) répare avec un délai de 2 s
  (`archive_view_check(…, timeout=2)`) — base tenue par une bascule (`_db_busy` de borgHelper) : aucun `[WARN]`, nouvel essai à
  la passe suivante, jamais 60 s par nick dans la boucle du watcher ; à la 3e passe verrouillée consécutive d'un nick, le `[WARN]`
  habituel une fois (compteur remis à zéro par une passe sans erreur) ; autre erreur : `[WARN]` une fois, comme avant. Contrôle
  du push selftest : base tenue -> rendu en ~2 s, muet deux passes, `[WARN]` à la 3e, réparée ensuite, compte remis à zéro ;
  contrôles de la vue : version sur disque épinglée à la version chargée.
- **HTTP/1.0 derrière nginx** (D149) : mesuré avec nginx 1.31.7 (`nginx:alpine`) et uvicorn 0.54 seulement — sans
  `proxy_http_version`, nginx parle déjà HTTP/1.1 à l'amont (aucun `[WARN]`) et une coupure de `/download/file` (borg tué) arrive
  au client (curl code 18) ; `proxy_http_version 1.0` forcé : `[WARN]` une fois, `/access` rend `http_version: "1.0"` (badge de
  l'UI), coupure invisible (curl code 0, 8,5 millions d'octets reçus sur 60 millions). Versions antérieures non mesurées
  (documentation de nginx : HTTP/1.0 par défaut avant le changement ; version du changement non vérifiée). Textes neutres sur la cause (décision de l'utilisateur) : `[WARN] requête reçue en
  HTTP/1.0 …` (borgHelperWWW 1.31.19) et infobulle (`title`) du badge — texte du badge inchangé (UI 1.24.2) — disent « proxy en HTTP/1.0 vers borgHelperWWW (nginx
  ancien, ou proxy_http_version 1.0) », conseil inchangé (`proxy_http_version 1.1;` et `proxy_set_header Connection "";`).
- **Débit de `/download/*`** (D155) : `/download/file` de 60 000 000 octets, 5 essais, `read1` médiane 13,2 s (≈ 4,5 millions
  d'octets/s) contre 16,8 s pour une copie en `read(n)` ; `read1` gardé (TECHNICAL).
- **Coût du `borg list` du rapprochement** (D171) : 100 archives, médianes — local `borg list --json` 0,66 s, avec
  `--format '{comment}{end}'` 0,74 s ; ssh://localhost (`borg serve`) 1,81 s et 1,90 s, `--glob-archives` 1,74 s : ~0,1 s de plus
  que le `borg list` de tout Index, surcoût distant ~1,1 s (démarrage ssh et `borg serve`). Latence d'un vrai réseau non mesurée
  (TECHNICAL).
- **CodecSelfTest, « snapshot incrémental (ajouts) »** : échec intermittent sous charge (run complet, reproduit sous 14 processus
  de calcul, 1.0.204 comme 1.0.205 : départ du `borg list --format` des ajouts à +4,6-4,8 s pour une échéance de 6 s). Le
  ralentissement visait tout `borg list`, `list --json` des archives compris ; seul le `list --format` des ajouts est ralenti
  désormais, 8 s, au-delà de l'échéance.

## borgHelper 1.0.204, borgHelperWWW 1.31.18 — Contrôles manquants — 2026-10-16

Chantier « reconstruction progressive », story 83 (reports D214, D162, D132, D215). Code de production inchangé : contrôles
et outillage de CodecSelfTest seulement (aucun défaut trouvé par le contrôle D215).

- **borg list du dépôt entier tué pendant le rapprochement** (D214) : nouveau contrôle vrai borg — GLOB_ARCH posé, archives de la
  base hors de la liste filtrée, `borg list` du dépôt entier (`_repo_archive_names`) ralenti ; tué par l'échéance d'une tranche
  (Index rendu dans le budget) puis par une opération prioritaire (tour relâché en moins de 4 s, pause) : « liste complète du
  dépôt interrompue … rapprochement reporté », rien retiré de diff.db ni de history.db (mesures et lignes de graphique des
  archives hors motif comprises), report noté (`deferred`, `plan['reconcile_deferred']`) ; reprise (« reprise de l'Index ») :
  rapprochement abouti ; le `borg list` lent écrit son PID et celui de son attente (`sleep`) : les deux disparus après l'échéance comme
  après la pause (arbre tué, pas abandonné). Avant : retirer l'arrêt autour de ce borg list survivait aux 51 contrôles du rapprochement, du
  périmètre et des tranches.
- **borgHelperWWW vérifié par son push selftest** (D162a) — mutrun ne juge un mutant de WWW que par lui : (a) `_exec_borghelper`,
  `_launch_bkp_detached` (Bkp, POST /index ; enfants attendus, groupe tué au délai) et `_reconcile_run` (BkpReconcile) lancent un
  vrai sous-processus qui reçoit `BORGHELPERC_NO_CLEANUP_NOTICE=1` (avant : ligne retirée = 135/135 OK) ; (b) gardes de source de
  borgHelper appliquées à WWW par le module importé, même portée que la garde « compatibilité Python » de borgHelper : marqueurs
  SQL anonymes seulement et aucun appel déprécié (fichier entier), fermeture SQLite prouvée (`_sql_marker_scan`,
  `_py_calls_scan`, `_sqlite_close_scan`/`_sqlite_close_file`, désormais au niveau du module de borgHelper, voir LIBRARY) ; liste
  blanche et compte exact de WWW déplacés dans WWW (`_SCG_WL_WWW`, `_SCG_SEEN_WWW`), lus par la garde de borgHelper dans sa
  source (un changement de WWW seul ne touche plus borgHelper).
- **ensure_cache_db / ensure_diff_db / ensure_history_db** (D162b) : contrôle de comportement, 35 cas — interrompus après
  l'ouverture, transaction d'écriture ouverte, à la création, au commit, en lecteur (`create=False`), dans `_migrate_to_history`
  et pendant une création chiffrée (DbKeyError réelle) : Ctrl-C (sous-classe privée : un vrai Ctrl-C arrête le run),
  `DbKeyError`, `SchemaVersionError` réelle, `sqlite3.OperationalError` (sortie 1, ou lecteur sur base occupée) — exception
  attendue, connexion fermée (aucun descripteur, autre écrivain libre, rien validé). Avant : seule la garde de forme le voyait.
- **CodecSelfTest `-f`, `-l`** (D132) : (a) l'échantillon du contrôle des plans couvre aussi ListBkpFiles,
  `_find_last_archive_with_file` (égalité et joker), TreeHist -X et les jokers de Search, TreeFind et DuIdx ; chaque appel tourne
  sauf si le contrôle de parité qui le couvre est lui-même sélectionné (avant : tout l'échantillon sauté dès qu'un contrôle tracé
  avait tourné), résultat non vide (listes entries/matches/rows/files comprises), sans erreur, clair == chiffré, et tracé sur la
  connexion chiffrée — les contrôles de parité qui couvrent ces appels exigent aussi un résultat non vide et sans erreur ; (b) un décor `_pre` en
  échec (exception ou résultat faux) dont le contrôle est écarté par `-f` donne une ligne « DÉCOR EN ÉCHEC <nom> (décor _pre exécuté
  hors sélection : …) », HORS des totaux, et le code de sortie 1, même sur une sélection vide (avant : rien, run vert) — cst
  (`_verdict`) et mutrun la lisent comme un échec nommé (mutrun : FILTRE VIDE si la sélection est vide) ; (c) `-l` n'exécute plus aucun décor `_pre` (avant, `-f plans -l`
  créait la base de décor `snapv-qp.db`) — contrôle par un CLI enfant : aucun fichier hors des bases communes ; aide, README et
  TECHNICAL disent ce que `-l` exécute encore (code commun hors contrôles : `t.db` et les bases temporaires des contrôles).
- **Lecteurs sur des chemins à plusieurs versions** (D215) : base d'un scénario réel (paire ancienne purgée, paires
  récentes avec leurs entrées réelles, DIFF_KEEP=2, quatre archives) écrite par `_snap_link_versions`, en clair et chiffrée —
  Search, FileHist et DuIdx (-R, -j ; -b ALL, défaut, -b de la dernière archive), ListBkpFiles par archive,
  `_find_last_archive_with_file`, TreeHist et TreeHist -X (depuis et jusqu'à une archive intermédiaire) rendent pour chaque
  archive, l'intermédiaire comprise, la version de cette archive (version partagée, retour à une version antérieure 7 -> 8 -> 7,
  chemin changé dans une paire purgée, supprimé, ajouté). Avant : décor de parité à une version par chemin.

## borgHelper 1.0.203, borgHelperWWW 1.31.17 — Connexions SQLite fermées sur les chemins d'erreur — 2026-10-15

Chantier « reconstruction progressive », story 81 (report D161 de la story 48 ; décision de l'utilisateur : Q1 = A, tous les
sites de production + garde AST contre les nouveaux, selftests hors périmètre).

- **Fermeture garantie de toute connexion de production** (D161) : 42 ouvertures (`_open_db`, `sqlite3.connect`) n'étaient
  fermées que sur le chemin normal (`conn=…` … `conn.close()` sans `finally`) — lecteurs (IdxTop, DiffTop, Search, FileHist,
  TreeHist, TreeFind, DuIdx, ArchiveHistory, RepoHistory, ListFiles, DiffBkp, CacheInfo, sondes d'index, notifications du
  watcher, statistiques), écrivains (purge et vidage du cache, mise en cache de `borg list`/`prune --dry-run`, IndexSnap complet
  et incrémental, purge des paires à réindexer, IdxPurge) et DbEncrypt/DbDecrypt. Une exception entre l'ouverture et la
  fermeture (erreur imprévue, `DbKeyError`, `SystemExit`, Ctrl-C) abandonnait la connexion : sous Python 3.11+, elle n'est
  fermée qu'au ramasse-miettes. Mesuré avant le correctif (Python 3.14, `clear_cache_nick` réel, exception après son
  DELETE) : un autre écrivain reçoit « database is locked » jusqu'au `gc.collect()`, 4 descripteurs de la base gardés ;
  dans un même processus (Index multi-nicks, watcher de borgHelperWWW qui appelle borgHelper en processus), un écrivain
  suivant attendait son délai (60 s) puis échouait. Désormais chaque site est fermé par un `finally` (transaction en cours
  annulée par la fermeture, comportement SQLite) : autre écrivain libre et descripteurs fermés dès le retour, sous toute
  version — hors deux fenêtres inhérentes à Python : entre le retour de `sqlite3.connect` dans `_open_db` et l'entrée dans
  son `try`, et entre le retour de l'ouvreur et l'affectation à la variable du site (un Ctrl-C qui tombe exactement là laisse
  la connexion au ramasse-miettes). Chemin normal inchangé : mêmes requêtes, sorties et codes de sortie (Python 3.10 : déjà libre au retour, mesuré).
  Écartés avec leur raison (fermeture déjà assurée autrement) : `_open_db` (connexion rendue), `ensure_*`,
  `_diff_stats_for_nick`, `_reconcile_archives`, sonde du témoin d'isolation ; sonde de DbStatus (déjà sûre) réécrite pour la
  garde, sans effet. PerfBench (outil de mesure) inchangé.
- **Bascule par copie (`_swap_db`)** : ses deux connexions étaient fermées dans le `finally`, mais APRÈS le checkpoint WAL
  de fin de copie, qui n'attrape que `sqlite3.Error` — un Ctrl-C ou un `SystemExit` pendant ce checkpoint sautait leur
  fermeture ET la suppression de la copie `new` (copie temporaire laissée ; avec `keep_new` et une copie validée, fantôme
  déjà basculé gardé, donc rebasculé plus tard). Désormais `src` puis `dst` sont fermées chacune dans son propre `finally`
  (un Ctrl-C pendant la fermeture de `src` ne saute plus celle de `dst`, qui tient le verrou d'écriture de la base servie),
  puis la suppression (même règle keep_new/résultat) dans un dernier `finally`.
- **borgHelperWWW 1.31.17** : `ensure_scope_cache_db` et `ensure_push_db` (démarrage du serveur) ne fermaient leur connexion
  que sur le chemin normal — base corrompue (« DB corrompue » + sortie 1) ou schéma plus récent : connexion laissée ouverte.
  Fermée par un `finally`, messages et codes inchangés ; contrôle du push selftest (base corrompue -> sortie 1, connexion
  fermée).
- **Gardes CodecSelfTest** : garde AST sur borgHelper et sur borgHelperWWW (deux contrôles ; WWW absent : SKIP) — toute
  ouverture de production dont la fermeture n'est pas prouvée sous une des formes usuelles = FAIL nommant fonction et ligne : `v=None` avant le try qui
  ferme (fermeture alors `_close_quiet(v)` ou sous `v is not None`), ouverture conditionnelle fermée sous le même test,
  fermeture en tête de son `finally`, pas d'ouverture dans une boucle ni d'autre écriture de la variable dans ce try (affectation,
  tuple, with, for, :=, +=, except as), seul `contextlib.closing` compte, `with sqlite3.connect(…)` seul refusé car il ne ferme pas, autres ouvreurs
  (`sqlite3.Connection(…)`, `sqlite3.dbapi2.connect`, `BhConnection(…)`) comptés, alias d'ouvreur refusés (`import sqlite3
  as …`, `getattr`, `functools.partial`…) ; liste blanche nommée et nombre d'ouvertures EXACTS ; témoins par règle. Limites connues, absentes du code de production
  (relevé AST) : variable d'ancrage réaffectée entre l'ouverture et la fermeture ; `del`/`nonlocal`/`global`/`match` sur la variable ; écriture de la variable dans le finally avant sa fermeture ; `break` dans la boucle de fermeture ; alias de module (`S=sqlite3`) ; sous-classe de `sqlite3.Connection` autre que `BhConnection` appelée directement ; fonction imbriquée nommée `_pb_*` (exclue comme PerfBench) ; `yield` dans le try ; liste blanche comptée par NOM de fonction (une homonyme partagerait le compte).
  Contrôles de comportement : par famille (écrivains, lecteurs, multi-nicks, sys.exit, sortie anticipée, `sqlite3.connect`
  nu ; exception privée, Ctrl-C et `SystemExit` injectés une fois, code vérifié : verrou relâché, rien validé après un DELETE
  appliqué, aucun descripteur ouvert au retour), arrêt réel d'un nick (DbKeyError, nick suivant servi, connexion fermée
  avant lui), `_swap_db` interrompu pendant son checkpoint ; SKIP sans `/proc/self/fd`.
- **Bibliothèque** (LIBRARY.md) : une connexion obtenue par `_open_db` appartient à l'appelant, qui la ferme aussi sur ses chemins d'erreur (`try/finally` ou `contextlib.closing`).

## borgHelper 1.0.202 — Bascule du fantôme après un rapprochement reporté ; paires tronquées et vidées par IdxPurge closes — 2026-10-15

Chantier « reconstruction progressive », story 80 (reports D200, D202, D203 de la puce « Robustesse, cas rares » du tri
A46 ; décisions de l'utilisateur : Q1 = A, Q2 = A, Q3 = A). Mesuré sur borg 1.2.6 (PyInstaller), CLI réelle, bacs neufs.

- **Bascule du fantôme après un rapprochement reporté** (D200) : quand le rapprochement de la base servie était reporté
  pendant une tranche, le fantôme — qui purge les archives disparues sans rien figer (AD-7) — basculait quand même :
  l'Index suivant figeait l'archive disparue SANS valeurs (`nfiles`/`original_size` None) et sans la ligne héritière de
  l'archive suivante (statistiques du graphique perdues). Désormais `_reconcile_archives(…, deferred=)` signale un
  rapprochement reporté, rien retiré faute d'information : base servie occupée par un autre processus, opération
  prioritaire en cours, `borg list` du dépôt entier en échec ou interrompu, figeage des lignes de graphique en échec.
  Base servie occupée : reporté même sans archive disparue, son état étant inconnu. `history.db` illisible ou corrompue
  (décision A de l'utilisateur) : figeage en échec, donc pas de bascule tant qu'elle n'est pas réparée — les valeurs des
  archives disparues restent dans la base servie. Jamais reporté : base servie illisible, corrompue ou chiffrée sans clé,
  à n'importe quelle lecture — la reconstruction la remplace, bascule permise comme avant ; purge interrompue — lignes de
  graphique déjà figées ; « rien à retirer » ; liste vide. La passe en tranches le note et `_shadow_swap` ne bascule
  pas dans cette passe : « `<nick>: bascule reportée (rapprochement de la base servie reporté) — fantôme gardé, nouvel
  essai à la prochaine tranche` » (décision Q1 = A, format des autres reports de bascule). Le fantôme avance
  normalement ; la tranche suivante fige l'archive disparue avec ses valeurs puis bascule. Mesuré (CLI réelle, dépôt neuf
  de 3 archives de 200 fichiers ; `Index`, puis `Index --rebuild -T snap` ; archive du milieu supprimée par `borg
  delete` ; `borg list` du dépôt entier mis en échec par un script `BORG_EXE` ; tranche `Index -t 5m`, puis tranche sans
  panne) : avant, « nouvelle base en service » dans la tranche en panne, puis archive figée sans valeurs ; après, pas de
  bascule à la tranche en panne, puis « 1 archive(s) disparue(s) retirée(s) … 1 ligne(s) de graphique figée(s) » et
  bascule à la tranche suivante, archive figée avec ses valeurs (200 fichiers, 5944 o) ; témoin sans panne inchangé
  (figée puis basculée à la première tranche). Prune, DelBkp, rapprochement du fantôme : inchangés.
- **Paire de diff tuée hors du moniteur — limite 1.0.153 réécrite** (D202, clos, Q2 = A) : non reproduit. `borg diff`
  tué par un SIGTERM extérieur (chargeur PyInstaller seul, enfant seul, ou les deux comme `pkill` ; 0 s, 0,05 s et 0,4 s
  après le lancement ; 30 000 fichiers modifiés, `Index -F`) sort toujours en code -15 : « [WARN] … borg diff failed (code
  -15) — paire … non indexée », paire refaite par l'Index suivant. Le code 1 sans sortie de la story 16 venait du moniteur
  (corrigé en 1.0.153) ; code 1 après une sortie partielle : jamais observé. La limite de 1.0.153 (« tuée hors du moniteur
  (kill externe) n'est pas détectée ») ne tient plus : rejetée, mesuré borg 1.2.6.
- **Paire vidée par `IdxPurge` jamais refaite** (D203, clos, Q3 = A) : confirmé, bases d'avant 1.0.116 seulement (le Bkp
  y écrivait des paires sans tailles depuis `borg create --list` ; aucun code actuel n'en écrit). Seul effet : les exclus
  de la paire vidée par `IdxPurge -x` ont une taille 0, lue par IdxTop, DiffTop et la moitié « taille » des
  `modifications` de Report et ArchiveHistory (`_diff_stats_for_nick`). Pas de correctif : refaire la paire ferait revenir
  les entrées purgées par `-x` (documenté dans README, `IdxPurge`).
- Tests : `deferred` reçoit la raison exacte de chaque report — base occupée : verrou exclusif d'un autre ouvreur, même
  sans disparue, lecture des archives connues ou du figeage « database is locked » ; opération prioritaire ; dépôt entier
  None/False ; figeage ; `history.db` illisible — et rien pour une base corrompue à toute lecture (fichier, table abîmée,
  lecture du figeage « malformed »), chiffrée sans clé, une purge interrompue (ligne déjà figée), « rien à retirer », une
  liste vide, un rapprochement abouti, des disparues toutes hors `GLOB_ARCH`, le fantôme ; `plan['reconcile_deferred']`
  remis à chaque passe d'un même `index()` ; `_shadow_swap` avec le drapeau : message, aucun borg lancé. Vrai borg :
  fantôme complété par la tranche, archive du milieu supprimée, rapprochement de la base servie reporté — dépôt entier en
  échec injecté par le script `BORG_EXE`, base servie tenue plus de 2 s par un verrou exclusif, `history.db` illisible —
  -> pas de bascule, fantôme gardé, rien figé ; tranche suivante, ou `history.db` remise : figée avec ses valeurs,
  héritière présente, bascule ; témoin basculé à la première tranche ; base servie corrompue -> pas de report, bascule ;
  archive recréée ensuite depuis son contenu d'origine, dépôt partagé. `borg diff` tué par un SIGTERM extérieur pendant
  un Index — chargeur PyInstaller seul, enfant seul, ou les deux comme `pkill` ; cible trouvée par son argv, revérifiée
  avant le signal ->
  « [WARN] … (code -15) — paire … non indexée », refaite par l'Index suivant ; `_MEI*` relevés sur les borg tués retirés.

## borgHelper 1.0.201, borgHelperWWW 1.31.16 — Anciennes bases : migration vers history.db d'un lecteur, paliers de colonnes, exclus orphelins — 2026-10-14

Chantier « reconstruction progressive », story 79 (reports D206, D207, D199 de la puce « Robustesse, cas rares » du tri A46 ;
décision A de l'utilisateur : avertissement du lecteur qui n'a pas migré). Ne concerne que des bases d'avant 1.0.139 (D206,
D207) ou d'avant 1.0.140 (D199) ; bases récentes : comportement inchangé.

- Migration vers `history.db` lancée par un LECTEUR (D206) : `ensure_diff_db(create=False)` avec la sonde des lecteurs (Report,
  ArchiveHistory, Status, borgHelperWWW…) ouvre `history.db` avec l'attente des lecteurs (`_READER_WRITE_WAIT`, 2 s) à chaque
  ouverture — schéma (`ensure_history_db(…, reader=True)`), copie (`BEGIN IMMEDIATE`) et étape finale `done`. Occupée :
  migration abandonnée (rien écrit, transactions annulées), `diff.db` lue telle quelle (`_reader_busy_skip`), migration à une
  ouverture suivante. Avant : 60 s d'attente puis « [ERREUR] DB occupée : …-history.db », sortie en code 2 (mesuré : `Report
  -o`, 60,6 s ; après : 2,5 s, aucune `[ERREUR]` de base, migration faite à l'appel suivant). « Migration des mesures vers … »
  n'est plus affiché qu'après la copie validée. Écrivains (Index, Bkp ; `history_path` d'un écrivain, sonde 60 s) : inchangés
  (60 s, puis « DB occupée »).
- Avertissement (décision A) : un lecteur qui abandonne sur une base occupée — `history.db` (schéma, copie) ou `diff.db`
  (paliers, migration) — alors que des mesures d'avant 1.0.139 attendent leur migration écrit sur stderr « [WARN] <base>:
  mesures d'avant 1.0.139 pas encore migrées (<history.db|diff.db> occupée) — réponse sans elles, migration à la prochaine
  ouverture » (`<base>` : nom de la base, le nick ou `DB_NAME` pour une base partagée ; code de sortie inchangé). Rien en
  attente, ou schéma plus récent que le code : muet comme avant. Lecteur seulement : `history_path` d'un écrivain (Bkp, Prune,
  qui ouvre aussi `diff.db` sans la créer) reste muet comme avant.
- Marqueur `migrated_from_diff` resté à `copied` (étape `done` en échec ou processus tué après le retrait des tables) : passé
  à `done` à l'ouverture suivante — reconnu à une `diff.db` sans plus rien à migrer mais jamais tamponnée (version < 10) ;
  aucune lecture de `history.db` pour une base récente. `history.db` jamais créée par cette réparation ; lecteur et
  `history.db` occupée : rien (nouvel essai, muet) ; autre erreur : « DB corrompue » qui nomme `history.db` (données NON
  régénérables), comme la copie — sauf pour un lecteur : réparation sautée en silence (son accès réel à `history.db` dira
  le problème), trace gardée ; `history.db` sans `db_meta` (0 octet) : rien à réparer, muet. Base d'un schéma plus récent ou
  `migrating` (DbEncrypt/DbDecrypt en cours) : jamais touchée, réparation comprise. Avant : `copied` pour
  toujours, et une table recréée plus tard par un binaire d'avant aurait été retirée sans recopie.
- Trace du retrait dans `diff.db` (`db_meta`, clé `hist_tables_dropped`, même transaction que le `DROP`, effacée une fois
  `done` posé) : `copied` + trace = retrait déjà fait — des tables présentes ont été recréées par un binaire d'avant, leurs
  lignes sont recopiées comme après `done`. Avant : copie sautée, lignes perdues au `DROP`. `copied` sans trace (processus
  tué avant le retrait) : rien recopié, aucun doublon.
- Paliers d'ajout de colonnes de `diff.db` (D207) : une seule étape, `_add_columns_locked` — transaction `BEGIN IMMEDIATE`,
  table et colonnes RELUES sous verrou (table présente et colonne absente -> `ALTER TABLE … ADD COLUMN` et son remplissage
  dans la même transaction ; sinon rien) — pour `bkp_status` (C/E, `start_notified_at`) et `snapshot_file`
  (`type`/`mode`/`owner`). Avant : `ALTER` en autocommit sur un état lu sans verrou — `start_notified_at` ajoutée puis
  remplie dans une autre transaction (verrou perdu avant le remplissage -> lignes NULL, copiées dans `history.db` : le
  watcher de borgHelperWWW les prenait pour des « débuts » à notifier, rafale de notifications pour d'anciens Bkp) ; second
  ouvreur : « duplicate column name » ou « no such table » (`bkp_status` retirée entre-temps par une migration finie)
  présentés comme « DB corrompue … Supprimez », code 1.
- Copie de `bkp_status` vers `history.db`, à CHAQUE copie (première migration, recopie après `done` ou trace du retrait) :
  ligne FINIE (`finished_at` non NULL) dont `start_notified_at` est NULL copiée avec `started_at` — un Bkp fini ne donne
  jamais de « début » à notifier ; ligne non finie : NULL gardé (Bkp peut-être encore en cours sous un binaire d'avant, début
  à notifier). Valeur déjà posée : copiée telle quelle. Couvre une `diff.db` touchée par l'ancien palier et pas encore
  migrée ; ne répare PAS une base déjà migrée (les NULL sont déjà dans `history.db`). Divergence connue (reportée) : le remplissage du palier 7 (colonne ajoutée) marque TOUTES les lignes déjà notifiées, Bkp encore en cours compris, alors que la copie vers `history.db` garde NULL pour une ligne non finie.
- Exclus orphelins (D199) : la purge `DIFF_KEEP` d'avant 1.0.140 retirait `diff_index` et la paire (`diff_indexed_pairs`) mais
  pas ses `diff_excluded_stats` ; Report et ArchiveHistory les agrègent sans jointure et donnaient un comptage partiel (mesuré :
  `files_added: 7` au lieu de `null` pour l'archive) ; IdxTop les somme de même (« Exclus » gonflés, archive dans « Inchangés
  par archive ») et `DiffTop -b <paire purgée>` affichait ses exclus. L'Index les retire désormais (`_drop_orphan_exclusions`, même passe que le
  rapprochement des archives) : une lecture bornée par la petite table des exclus, écriture seulement s'il y en a ; base
  occupée (2 s au plus, ouverture comprise), illisible ou chiffrée sans clé (disparue : rien, jamais recréée) : `[WARN] <nick>: exclus orphelins (paires
  purgées avant 1.0.140) non retirés (…) — nouvel essai au prochain Index`, jamais l'échec de l'Index. Exclus d'une paire
  indexée : jamais touchés ; lecteurs inchangés (aucun retrait hors Index).
- Exclus écrits avec leur paire seulement si cette écriture a créé la paire : DiffBkp (`store_diff_entries(…, exclu=…)`, même
  transaction ; avant : à part, même quand l'écriture de la paire avait échoué — exclus orphelins possibles) et Index (avant :
  réécrits pour une paire déjà là, écrite par un DiffBkp concurrent).
- borgHelperWWW 1.31.16 : `_never_cache` refuse aussi toute réponse qui contient « mesures d'avant 1.0.139 pas encore
  migrées » (`_MIGR_PENDING_TXT`, importé de borgHelper) — rendue sans ces mesures, elle aurait été resservie sans nouvel essai
  de migration (rien écrit : empreinte inchangée). La ligne est relayée telle quelle (stderr des réponses `CommandResult` :
  `/report`, `/archivehistory`, `/repohistory`, `/search`, `/idxtop`… et l'UI qui l'affiche). Push selftest : cas ajouté au
  contrôle du cache des réponses (134/134, Python 3.10 et 3.14). Push selftest : `alive()` des deux contrôles
  « /download/* client parti » et « chien de garde » lisait `/proc/<pid>/stat` sans garde — processus récolté entre
  l'ouverture et la lecture -> `ProcessLookupError` (ESRCH, mesuré sous 3.10 et 3.14), FAIL intermittent (1 run sur 3) ;
  lecture en échec = processus mort.
- CodecSelfTest : 18 contrôles « story 79 » (matrice de la story sur bases construites par `_hm_legacy`, puis revues :
  `diff.db` tenue pendant le palier, second ouvreur, marqueur `copied` — tenu, corrompu, disparu, `history.db` de 0 octet —,
  trace du retrait — tables, colonnes C/E seules —, réparation gardée — schéma plus récent, lecteur sur `history.db`
  illisible —, règles de l'avertissement — stderr, base partagée, schéma plus récent, écrivain muet —, exclus de DiffBkp
  et de l'Index, exclus orphelins — IdxTop et DiffTop corrigés, base illisible, chiffrée avec et sans clé, disparue, base
  partagée `DB_NAME`) ; « tables recréées par un binaire d'avant » étendu : après `done`, ligne non finie recopiée avec
  `start_notified_at` NULL (à notifier), ligne finie avec `started_at` (jamais un « début »).

## borgHelper 1.0.200 — Lecteurs et Prune : base supprimée, bases créées trop tôt, erreurs SQLite muettes — 2026-10-14

Chantier « reconstruction progressive », story 78 (reports D116, D115, D137 ; décision de l'utilisateur Q1 = A pour D137,
puis A pour le code 1 de Status). borgHelperWWW inchangé.

- Base supprimée APRÈS son ouverture par un lecteur (D116) : `ensure_cache_db` et `ensure_diff_db` en `create=False` (lecteurs)
  testent `_file_gone` dans leur `except sqlite3.DatabaseError` — base disparue : lue comme absente, rien recréé, aucun message
  (comme la fenêtre sonde/ouverture fermée en 1.0.172). Avant : « [ERREUR] DB corrompue … -> disk I/O error … Supprimez le
  fichier et relancez », code 1, pour un simple lecteur. `ensure_history_db(create=False)` reçoit la même garde (jumelle ; aucun
  appelant en production, pas de changement visible). Base présente et corrompue : message et code 1 inchangés ; écrivains
  (`create=True`) inchangés.
- Prune ne crée plus `diff.db` ni `cache.db` d'un nick qui n'en a pas (D115) : sonde courte (`_db_probe`, 2 s) ; base non absente
  (illisible ou occupée comprise) -> `ensure_cache_db`/`ensure_diff_db` en écrivain comme avant (migrations, réparation
  d'en-tête, attente de 60 s, arrêt AVANT borg sur une base illisible) ; absente -> rien appelé, laissée absente. Limites : une
  base supprimée entre la sonde et l'écrivain est recréée (fenêtre de l'écrivain, comme `_cleanup_index_after_prune`) ; la
  migration d'une ancienne `diff.db` existante peut créer `history.db` avant borg (base existante traitée comme avant).
- Gain de Prune (`history.db`, `op=prune`) seulement si `borg prune` ET `borg compact` ont réussi (code 0 ou 1) ; sinon `borg
  info` n'est pas lancé : un Prune en échec ne crée aucune base. Avant : un gain « prune » (et `history.db`) enregistré après un
  échec de prune ou de compact si `borg info` répondait.
- Lecteurs « coût seulement » (D137) — `is_archive_snapshot_indexed`, `_refresh_chart_stats`, `_index_tranche`, `_build_state`,
  `_db_meta_value` : une vraie erreur SQLite est dite par `_reader_sqlite_err` (« [ERREUR] SQLite error (<base>): … ») ; une fois
  par base et par processus, sauf `_db_meta_value` (lu en boucle par borgHelperWWW, `/access`) : marque propre (base, lecteur),
  levée par toute lecture réussie, base ou table absente, base disparue — une ligne par épisode d'erreur. Même valeur de repli,
  travail refait (borg info) ; table absente : muet ; base supprimée après l'ouverture (fantôme jeté par une bascule) : lue
  comme absente, muette et non comptée (règle D116, helper unique `_cost_reader_err`, ces cinq lecteurs seulement — les autres
  lecteurs : report différé) ; codes d'Index et de Bkp inchangés ; Status : code 1 quand
  la ligne est dite (sa règle depuis 1.0.193 — `db_meta` du fantôme illisible ; avant : code 0 sans message).
- `is_archive_snapshot_indexed` rend None (inconnu) sur une vraie erreur, comme `is_diff_pair_indexed` (1.0.176) ; False pour
  une base absente, une table absente ou une base disparue. `indexsnap` saute alors le snapshot (refait à un Index suivant) :
  rien supprimé, pas de borg, code 1 (avant : False -> lignes `archive_snapshot` valides supprimées puis snapshot refait, sur
  un simple délai de verrou).
- Mesuré : `work/s78/race78.py` (+ `probe78.py` pour history.db et les écrivains) — avant : diff.db, cache.db -> « DB corrompue
  … disk I/O error », `SystemExit(1)` ; après : retour normal, aucun message, rien recréé ; écrivains : inchangés. Prune d'un
  dépôt `ssh://…nohost.invalid` sans base (`work/s78/prune2`) — avant : `rc-pd-cache.db`, `rc-pd-diff.db` créées ; après :
  « borg prune a échoué : Connection closed by remote host », code 2, CACHE_DIR vide. `work/s78/d137.py` (pages de la table lue
  et de ses index écrasées) — avant : muet ; après : une ligne `[ERREUR] SQLite error` par base, valeurs inchangées ;
  `d137gone.py` : base supprimée après l'ouverture, muet ; `status78.py` : Status code 1.
- Contrôles CodecSelfTest : « base supprimée après l'ouverture : lecteur (diff, cache, history) … », « base présente et
  corrompue : lecteur … ; écrivain … », « Prune sans base, dépôt injoignable … » (prune ou compact en échec : ni borg info ni
  gain), « Prune réussi sur bases existantes (ancien schéma compris) … » (bases partielles, base illisible : arrêt avant borg),
  « Prune réussi sur un nick jamais indexé … » (quatre Prune, avertissement de prune ou de compact compris ; `--dry-run`), «
  lecteurs « coût seulement » : vraie erreur SQLite … », « … : table absente … », « … : base supprimée après l'ouverture … », «
  _db_meta_value : une ligne [ERREUR] par épisode d'erreur … », « indexsnap : snapshot indexé inconnu … », « Status, fantôme à
  db_meta illisible … » (texte et `-j`, nick sain inchangé).

## borgHelper 1.0.199, borgHelperWWW 1.31.15 — Passphrase du watcher (BkpReconcile) — 2026-10-13

Chantier « reconstruction progressive », story 77 (report D182 de la revue 2 de la story 63 ; décision de l'utilisateur
Q1 = A). Nick dont la passphrase borg n'est donnée qu'à la requête (`-P`, `X-Borg-Passphrase`, rc sans `BORG_PASSPHRASE`) :
pour un Bkp tué, le watcher de borgHelperWWW lançait `BkpReconcile -j` sans passphrase, son `borg list` échouait, et il
réessayait toutes les 10 min, par worker, jusqu'au délai `BKP_STATUS_TIMEOUT` — une ligne de journal à chaque essai.

- borgHelper : l'échec de `borg list` FAUTE de passphrase est reconnu au message propre de borg (`NoPassphraseFailure` :
  « can not acquire a passphrase » en 1.2.6, « Cannot acquire a passphrase » en 1.4.5, mesurés ; `msgid` sous `--log-json`) et
  devient un état du rapprochement, figé pour le watcher seulement : runs candidats `passphrase absente` (constante
  `RK_NOPASS`, importée par borgHelperWWW), `[WARN] <nick> : rapprochement impossible — passphrase borg absente : la donner
  par …` qui cite les sources d'une passphrase (`BORG_PASSPHRASE` dans le rc ou `POST /login`, `BORGHELPERC_RUNTIME_PASSPHRASE`
  dans l'environnement du serveur, `-P` en CLI, `X-Borg-Passphrase` en HTTP), rien vérifié (code 1 de BkpReconcile ; texte :
  « vérification impossible (passphrase borg absente) »). À l'Index et au début du Bkp, même `[WARN]` suivi de « réessayé au
  prochain Index » (l'Index réessaie). Détection mesurée sur borg 1.2.6 et 1.4.5 : un autre message retombe sur `non vérifié`
  (réessayé, comme avant). Passphrase fausse, dépôt verrouillé, réseau : `non vérifié`, inchangés ; dépôt non chiffré ou
  passphrase dans le rc : comportement actuel.
- borgHelperWWW : run `passphrase absente` -> état `fait`, une ligne de journal par processus serveur (chaque worker, chaque
  redémarrage refait son `borg list`) — « passphrase absente côté serveur — fin au délai BKP_STATUS_TIMEOUT, sans avis d'échec
  immédiat (pour le retrouver : passphrase côté serveur — …) » —, ni nouvel essai par ce processus, ni notification d'échec,
  ni Sentry ; la fin vient du délai, comme un Bkp non vérifiable. Aucune passphrase de requête gardée côté serveur
  (BkpReconcile hérite de l'environnement du serveur : `BORGHELPERC_RUNTIME_PASSPHRASE`, s'il y est, lui en donne une).
  `BkpReconcile -P` à la main n'avance la fin que si l'archive du run existe (fermée en succès) ; `absent` : l'avis d'échec
  arrive au délai `BKP_STATUS_TIMEOUT`, le watcher ayant gardé ce run comme traité.
- Mesuré (`work/s77/mesure77.sh`, CLI réelle, borg 1.2.6 et 1.4.5) : avant, `BkpReconcile -j` sans `-P` -> `non vérifié`, code 1,
  `[WARN] … Enter passphrase for key …` ; après -> `passphrase absente`, `[WARN]` des sources, code 1 ; témoin `-P` : `absent`,
  code 0 (inchangé).
- Contrôles : CodecSelfTest « Bkp tué, passphrase absente (rc sans passphrase) … (1.0.199) » (sorties de borg 1.2.6/1.4.5,
  texte et `--log-json` ; passphrase fausse, dépôt verrouillé, borg tué inchangés) et « Bkp tué, passphrase absente sur vrai
  borg … (1.0.199) » (repokey sans -P en -j et en texte, ligne restée ouverte, -P fausse, -P, dépôt non chiffré) ; push selftest : sous-contrôles « passphrase
  absente » et « passphrase fausse » du rapprochement par le watcher.

## borgHelper 1.0.198, borgHelperWWW 1.31.14 — Orphelin avant le verrou, borg create d'un autre uid — 2026-10-13

Chantier « reconstruction progressive », story 76 (reports D183 et D181 de la revue 2 de la story 63 ; décisions de
l'utilisateur Q1 = A, Q2 = A). Un `borg create` du run d'un Bkp tué, vivant, est un orphelin qu'il tienne le verrou du dépôt
ou non, et qu'on lise son environnement ou seulement son argv.

- D183 — orphelin avant le verrou : un Bkp tué dont le `borg create` vit encore mais ne tient pas encore le verrou du dépôt
  (démarrage du chargeur PyInstaller, attente du verrou : 1 s par défaut, plus avec `BORG_LOCK_WAIT`) n'était cherché que dans
  le `lock.roster` : Report, Report -o, Status et `/access` le disaient « Bkp interrompu … — aucun processus » le temps de la
  fenêtre, pendant que BkpReconcile le voyait orphelin — le watcher de borgHelperWWW relançait BkpReconcile à chaque passage.
  Désormais même état qu'un orphelin détenteur du verrou partout : Report/Report -o « ⏳ Bkp interrompu, borg create encore
  actif » (alerte, code 1), Status « Bkp interrompu (borgHelper arrêté), borg create encore actif », `/access` `orphelin` (le
  watcher ne relance plus BkpReconcile pendant la fenêtre). `/proc` n'est parcouru que sans marqueur de Bkp vivant du nick,
  sans orphelin de ses lignes dans le roster, et s'il existe une ligne `bkp_status` ouverte non périmée (dépôt local) : un nick
  sans telle ligne ne lit pas `/proc` (Report de tous les nicks). Sans marqueur vivant, les lignes ouvertes du nick sont lues
  dans la base (avant : rien). Règle d'un processus = celle d'un détenteur du roster (borgHelper du Bkp mort ; un `borg create`
  dont le borgHelper vit n'est jamais orphelin). Dépôt distant : inchangé (« borg non vérifiable (dépôt distant) »).
- D181 — `borg create` d'un autre uid (Bkp par root/cron, borgHelperWWW sous un compte de service) : `/proc/<pid>/environ`
  illisible, BkpReconcile concluait « absent » et le watcher notifiait un échec (push, Sentry) alors que l'archive pouvait
  arriver ensuite. Le create est reconnu aussi par son argv : élément `borgHelper run <run_id>` qui suit `--comment` (posé par
  `backup()` depuis 1.0.185, lisible d'un uid à l'autre) — dans `run_create_alive` (BkpReconcile) et pour un détenteur du
  roster (`repo_orphan_create` : borgHelper du Bkp mort prouvé alors par l'absence de marqueur vivant de ce run, faute de
  `BORGHELPER_BKP_PID` lisible). Environnement lisible : sa règle seule, inchangée. Chemin argv réservé (revue, décision de
  l'utilisateur « Q2 précisé » : « un commentaire reste un commentaire ») à un processus d'uid réel 0 (Bkp par root/cron)
  ou du propriétaire du dossier du dépôt local (`os.stat` de `BORG_REPO`) : tout utilisateur local peut lancer `x create
  --comment "borgHelper run <run_id>"` (run_id visible par `ps` pendant le Bkp) — faux orphelin, aucune fin « échec » avant le
  délai ; le falsifier exige d'être root ou ce propriétaire. Forme exacte de `backup()` exigée : `create`, puis `--comment`,
  puis `borgHelper run <run_id>` en 32 caractères hexadécimaux. Dépôt distant ou propriétaire illisible : pas de voie argv.
  Lecture argv/environ/uid commune (`_proc_create_run`) ; chaque appelant garde sa règle de vie. Limites : Bkp sous un
  troisième compte, ni root ni propriétaire du dépôt — dépôt d'un groupe partagé (dossier setgid écrit par plusieurs
  comptes) compris : tout compte autre que le propriétaire en est un — (jamais reconnu par l'argv) ; `/proc` en `hidepid` (argv illisible) — comme avant ; commentaire cité pour le shell distant
  (`SSH_REMFO`) jamais lu.
- Un `borg create` d'un AUTRE run, ou sans le commentaire du run (environnement illisible), n'en est jamais un ; aucune
  écriture dans la base depuis ces lecteurs.
- Revue : le chemin du voisin (Report d'un autre nick du même dépôt) ne cherche jamais l'orphelin avant le verrou — un create
  qui ne tient pas le verrou ne bloque pas le borg de ce nick, et la réponse aurait dépendu du marqueur mort du voisin encore
  sur disque. Une erreur de lecture dans cette recherche (history.db occupée ou illisible, `/proc` illisible) vaut « aucun
  orphelin avant le verrou » (règle d'avant), jamais une exception : Status garde « Bkp interrompu » (pas d'état inconnu) ;
  erreurs de lecture seules (OSError, SQLite, base refusée), dites par Report et Report -o avec `-d` (Status : jamais) ; une
  erreur de programmation se propage. Le délai rc (`BKP_STATUS_TIMEOUT`) est lu sans `[WARN]` sur ce chemin (story 52 : rien
  dit sans détenteur). Un détenteur du roster mort ou un roster invalide n'empêchent pas de voir le create du run vivant
  ailleurs dans `/proc`. Coût mesuré du parcours de `/proc` : ~10 ms pour 666 processus, dans la sonde bornée de 1 s de
  `/access`.
- Texte « borg create encore actif » défini une fois (`_ORPHAN_TXT`), aux 5 sites qui l'impriment (Status, Report, voisin),
  importé par borgHelperWWW comme les états `RK_*`.
- borgHelperWWW 1.31.14 : toute réponse qui contient le texte d'un borg create orphelin (« borg create encore actif », stdout
  ou stderr — Report, Report -o, voisin, Status compris) n'est jamais mise en cache (`_never_cache`, prédicat partagé) : un
  create orphelin avant le verrou n'est pas dans le `lock.roster`, et s'il meurt sans avoir pris le verrou
  (`BORG_LOCK_WAIT` dépassé) l'empreinte ne change pas — `/report?offline=true` resservait « encore actif » (code 1)
  jusqu'à 5 min. Effet réel dans `run_borghelper` (`_RESPONSE_CACHE`, codes 0 et 1) ; les caches par périmètre ne gardent
  que le code 0 de commandes qui n'impriment jamais ce texte. Push selftest : contrôle du cache des réponses étendu (formes
  réelles construites sur `_ORPHAN_TXT` importé : orphelin du nick, voisin, stderr seul ; prédicat vérifié aussi aux
  caches par périmètre sur la forme code 0).
- Mesuré (CLI réelle, `work/s76/mesure76.sh`, bacs `avant1` sur 1.0.197 / `apres1`) : Bkp tué (ligne ouverte, marqueur
  mort), faux `borg create` vivant sans `lock.roster` — environnement lisible : avant, Status « … — aucun processus », Report -o
  rien, BkpReconcile `orphelin` ; après, Status et Report -o « borg create encore actif », BkpReconcile `orphelin` ;
  environnement illisible (processus non dumpable, argv lisible) : avant, BkpReconcile `absent` ; après, `orphelin` et les
  mêmes Status/Report -o ; témoin sans create inchangé (interrompu, `absent`).
- CodecSelfTest : deux contrôles « Orphelin avant le verrou » — environnement lisible (avant le verrou, témoin, autre run,
  argv illisible, dépôt distant, `/proc` non lu sans ligne ouverte non périmée, erreurs de lecture, voisin avec marqueur mort
  présent puis absent, create en file derrière l'orphelin du roster d'un autre nick, deux lignes ouvertes dont la plus
  ancienne a son create vivant, formes refusées de l'argv, règle d'uid : root et propriétaire du dépôt acceptés, lecteur
  non propriétaire et troisième compte refusés) et environnement illisible (propriétaire du dépôt, root, autre run,
  troisième compte et lecteur non propriétaire ignorés, roster) — ce dernier sauté (SKIP dit) quand une sonde montre
  qu'un processus non dumpable garde ici un environnement lisible (root, CAP_SYS_PTRACE…) ; run_id neufs (uuid4) à chaque
  run, faux create dans leur propre groupe de processus, tué en fin de contrôle ; erreurs : programmation propagée,
  Ctrl-C propagé, base refusée et clé absorbées, `[debug]` de Report -o ; délai rc invalide muet ; détenteur du roster
  mort ou roster invalide. Contrôles réels `_proc_uid` : ce processus = `os.getuid()` ; PID 1 lu 0 s'il appartient à root
  (sinon SKIP dit). Décors des contrôles 1.0.184 et 1.0.196 ajustés (run propre aux négatifs ; lignes ouvertes lues sans
  marqueur vivant).

## borgHelper 1.0.197, borgHelperWWW 1.31.13 — PID repris dans l'empreinte du roster — 2026-10-13

Chantier « reconstruction progressive », story 75 (report D173, reste du tri A122 : le zombie était réglé par
borgHelperWWW 1.31.3 / borgHelper 1.0.188).

- borgHelperWWW : l'empreinte du cache de `/api/report?offline=true` notait chaque détenteur du `lock.roster` du dépôt local
  en « pid:vivant » seulement. Un détenteur tué dont le PID était réattribué à un autre processus entre deux appels laissait
  l'empreinte identique : la réponse en cache (« Bkp interrompu (borgHelper arrêté), borg create encore actif », code 1)
  était resservie jusqu'à 5 min alors que Report -o ne la disait plus. Un détenteur vivant y porte désormais aussi son heure
  de démarrage (champ 22 de `/proc/<pid>/stat`, lue dans la même lecture que son état : aucun coût de plus par appel) — un
  PID repris change l'empreinte, la réponse est recalculée. Mort, zombie ou `/proc` illisible : « pid:0 », comme avant ;
  sonde bornée, repli « dernier état lu » et partie « marqueurs de Bkp » inchangés, TTL inchangé.
- Part « porteur » de D173 (marqueurs de Bkp dans l'empreinte) : déjà réglée, inchangée. `_lock_holder` applique la règle
  du PID repris (processus démarré plus de 60 s après la dernière écriture du marqueur -> mort, 1.0.148), la même que Report
  (`bkp_markers`) : le cache et la CLI disent la même chose. Reste : un PID repris dans les 60 s qui suivent la dernière
  écriture du marqueur est encore vu vivant par les deux.
- borgHelper : `_pid_stat(pid)` -> (état, début) en une lecture de `/proc/<pid>/stat`, seul parseur de `_pid_state`,
  `_proc_start` et `_proc_live` (comportement inchangé), lu par borgHelperWWW (`_pid_alive_start`, aussi derrière
  `_pid_alive`) — jamais un second parseur de `/proc` dans borgHelperWWW.
- Mesuré (`work/s75/mesure75.sh`, espace de noms PID `unshare -Urpf`, PID réattribué par `ns_last_pid`) : faux `borg create`
  orphelin détenteur, tué, son PID repris par `sleep` -> avant, l'API resservait « borg create encore actif » depuis le cache
  quand la CLI ne le disait plus ; après, l'API recalcule et dit comme la CLI. Push selftest : contrôle du cache Report -o
  étendu (PID repris -> recalculé, `/proc` illisible et mort -> « pid:0 », retour à « pid:1:<début> » réel ;
  début attendu lu par le contrôle lui-même).

## borgHelper 1.0.196, borgHelperWWW 1.31.12 — Bkp vivant rapproché de sa ligne, Bkp sans ligne bkp_status dit en cours — 2026-10-13

Chantier « reconstruction progressive », story 74 (report D172 ; décision de l'utilisateur Q1 = A). Deux limites de `_bkp_live`,
la source de Report (en ligne et `-o`) et de Status (et, par `bkp_state`, de `/access` de borgHelperWWW).

- L1 — Bkp vivant plus ancien masqué : seule la ligne `bkp_status` ouverte la plus récente du nick était comparée aux
  marqueurs de Bkp. Un Bkp A vivant derrière la ligne restée ouverte d'un Bkp B tué plus récent (B lancé pendant l'Index de
  fin de A, puis tué) n'était plus vu : Report et Report -o ne disaient aucun Bkp en cours (Report interrogeait borg, qui butait
  sur le verrou du dépôt), Status disait seulement « Bkp interrompu ». Chaque marqueur vivant est désormais rapproché de SA
  ligne (`bkp_status_open` de son run) ; le plus récent des Bkp vivants (en cours, sans suivi ou en attente de l'Index, par
  date de début) est rendu ; ligne périmée ou close : ce run ne compte pas. Status : A « en cours », B « interrompu » (règle
  existante : ligne d'un autre run) ; la ligne d'un run dont le marqueur vit n'est jamais « Bkp interrompu … — aucun
  processus » (`bkp_interrupted` ; Bkp vivant moins récent que celui affiché ; avant : fausse alerte dans Status et
  `/access`) — périmée, elle reste « Bkp sans fin … » (`bkp_stale`). Mesuré (CLI réelle, `work/s74/mesure74.sh`, bacs `base3`
  avant / `apres1` après) : A vivant + B ouvert ->
  avant, Status « Bkp interrompu … — aucun processus » seul et Report -o sans ligne de Bkp ; après, « Bkp en cours depuis » de A
  dans les deux (et B interrompu dans Status) ; témoin A seul inchangé.
- L2 — marqueur sans ligne : quand `store_bkp_status_start` échoue (`[WARN]`), `backup()` pose à côté de son marqueur une trace
  `<marqueur>.sans-suivi` (le fichier PID reste intact) ; le Bkp est dit « ⏳ Bkp en cours depuis … (suivi bkp_status
  indisponible) » (Report, stderr de Report, Status ; début = date du marqueur ; base non lue pour ce run, même illisible)
  au lieu de « en attente de l'Index » pendant toute sa durée ; jamais soumis à `BKP_STATUS_TIMEOUT` (sans ligne, aucun
  « Bkp sans fin » possible : passé le délai, Status nommerait « Restore, Prune ou DelBkp » le verrou prioritaire du Bkp et
  `/access` le dirait fini pendant que borg tourne ; son marqueur vivant prouve le processus). JSON : `sans_suivi` (booléen) dans Status `bkp_running`, Report `bkp_en_cours` et
  `bkp_voisin`. Trace retirée avec le marqueur (`clear_bkp_marker`, avant lui) et, marqueur mort ou absent, par `bkp_markers`.
  Trace non écrite (`_set_pid_lock` avale l'erreur) : `[WARN] <nick>: trace sans-suivi non écrite`.
- borgHelperWWW 1.31.12 : l'empreinte du cache de `/report?offline=true` compte aussi les traces `.sans-suivi`
  (`_MARKER_RE`) — sinon « en attente de l'Index » restait en cache jusqu'à 5 min après leur apparition.
- Inchangé : un seul Bkp (en cours, en attente de l'Index, orphelin, périmé, voisin), marqueur vivant à ligne close, lecture
  impossible (règle actuelle, `strict` pour Status), aucune lecture de plus sans marqueur vivant, rapprochement des Bkp tués.
  `/access` (code inchangé pour cet état) dit le Bkp `sans_suivi` « en cours » (`bkp_detail` `"en_cours"`) et le Bkp A de L1
  en cours — si `history.db` est lisible ; sinon état inconnu (`bkp_running` null, garde `bkp_running_state`), comme avant.
- CodecSelfTest : « Bkp vivant : chaque marqueur rapproché de sa ligne (L1), suivi bkp_status indisponible (L2) … » (matrice :
  L1, témoin, deux marqueurs vivants, L2 et base illisible, témoin illisible sans trace, marqueur mort avec trace, trace sans
  marqueur, marqueur vivant à ligne close, en attente ; Report, Report -o, Status ; aucune lecture sans marqueur ; `backup()`
  borg simulé, trace non écrite ; revue : voisin d'un Bkp sans suivi, sans suivi derrière un précédent en erreur, lignes
  périmées de marqueurs vivants, en attente plus récent qu'un en cours, sans suivi au-delà du délai toujours en cours (verrou
  prioritaire tenu : aucune « opération prioritaire »), run au marqueur vivant jamais interrompu, lecture sans marqueur vivant
  sur fichiers recréés) ; borgHelperWWW : « cache Report -o … » (trace posée -> recalculé) ; « Bkp réel sans ligne bkp_status … »
  (vrai borg, CLI : déclencheur SQLite qui refuse l'INSERT, `borg create`
  retenu — Status, Status -j, Report -o -j, Report -j pendant le Bkp, puis plus rien) ; contrôles Status existants : clé
  `sans_suivi` dans les `bkp_running` attendus.

## Documentation (borgHelperWWW) — uvicorn externe : arrêt et --timeout-graceful-shutdown — 2026-10-13

Chantier « reconstruction progressive », story 73 (report D176 ; décision de l'utilisateur : documentation seule). Remesuré sous
uvicorn 0.54 (Python 3.14, `python -m uvicorn borgHelperWWW:app`, bac à sable isolé, fichier de 60 Mo) : un téléchargement dont le
client ne lit plus garde le serveur et son borg vivants malgré deux SIGTERM puis deux SIGINT ; avec `--timeout-graceful-shutdown 5`,
sortie 5,2 s après le premier SIGTERM, borg arrêté.

- README (installation, « Arrêt ») et TECHNICAL (« Lancement externe ») : limite remesurée ; `--timeout-graceful-shutdown N` décrite
  comme variante (absente d'uvicorn 0.15 : exemples laissés sans elle), avec ses effets — toute requête encore en cours coupée après
  N s (téléchargement tronqué, `/restore`, Prune, DelBkp), entrée `lock.roster` du borg arrêté (mesuré), `_MEI*` possibles, `[req]`
  « (client parti) » ; `TimeoutStopSec=` de systemd au-delà de N. Mesure : un seul worker. Aucun code changé.

## borgHelper 1.0.195, borgHelperWWW 1.31.11 — Codes de sortie hérités demandés à borg 1.4 — 2026-10-10

Chantier « reconstruction progressive », story 72 (reports D134, D142 ; décisions de l'utilisateur Q1 = A, Q2 = A). borgHelper et
borgHelperWWW lisent les codes de borg selon la convention 1.2 (0 et 1 = utilisable, 2 et plus = échec ; `/download/file` :
« never matched » en code 1 -> 404). borg 1.4 avec `BORG_EXIT_CODES=modern` rend ses avertissements en 100-127 et ses erreurs
en 3-99 — mesuré sur borg 1.4.5 (binaire officiel, signature vérifiée, bac à sable) : « never matched » 101 au lieu de 1,
archive absente 31 au lieu de 2 ; variable absente = codes hérités. **Seul borgHelperWWW était exposé** : `_borg_env` copie
son environnement vers le borg des téléchargements — lancé avec `BORG_EXIT_CODES=modern`, `/download/file` d'un chemin absent
répondait **502** au lieu de 404, `/download/tar` d'un préfixe absent 502 au lieu d'un tar vide et d'un `[WARN]` (mesuré).
La CLI construit l'environnement de borg de zéro (clés borg du rc, PATH, LC_ALL) : avant 1.0.195, la variable n'y arrivait
que par un wrapper `BORG_EXE` ou l'environnement de la machine distante d'un Bkp `SSH_REMFO` — sa part est défensive.

- borgHelperWWW : `_borg_env` (dernière archive et téléchargements) force `BORG_EXIT_CODES=legacy`.
- borgHelper : environnement de borg construit par une seule fonction, `_borg_child_env` (boex — toutes les commandes —,
  `borg diff` de l'Index, sonde de version du Bkp), qui ajoute `BORG_EXIT_CODES=legacy` (PATH absent ou vide : `os.defpath`).
  Bkp distant (`SSH_REMFO`) : commande distante inchangée (`<borg> …`, jamais de préfixe — décision de l'utilisateur : clé à
  commande forcée « borg … », `sudo` qui remet l'environnement à zéro) ; le borg distant ne reçoit la variable que par
  `SendEnv BORG_*`, si son sshd l'accepte (`AcceptEnv`). `boex` copie la liste `preBorg` (celle de l'appelant n'est plus
  modifiée). Sonde de version en ssh direct : la variable atteint le client ssh local, pas le `borg --version` distant
  (code 0 dans les deux modes, sans effet).
- Codes hérités garantis avec borg 1.4, variable ignorée par borg 1.2 ; lectures des codes, codes de sortie de borgHelper et
  statuts HTTP inchangés pour une même situation. Hors couverture (documenté) : un wrapper `BORG_EXE` qui force lui-même
  `BORG_EXIT_CODES=modern` (jamais touché par borgHelper) ; l'environnement distant d'un Bkp `SSH_REMFO` qui force `modern`
  ou dont le sshd refuse `BORG_*`.
- Mesuré de bout en bout (borg 1.4.5, bac à sable `s72`, serveur lancé avec `BORG_EXIT_CODES=modern`, Sentry neutralisé) :
  `/download/file` d'un chemin absent -> 404 (avec ou sans `bid`), fichier présent -> 200, `/download/tar` d'un préfixe
  absent -> 200 (tar vide) et `[WARN] borg export-tar (téléchargement) : Include pattern … never matched.`, archive inconnue
  -> 502 ; témoin 1.31.10, même serveur : 502, 200, 502, 502. Dossiers borg de l'utilisateur et `/tmp/_MEI*` inchangés.
- CodecSelfTest : « environnement de borg : PATH absent ou vide -> os.defpath » (absent, vide, présent ; `legacy` et `LC_ALL`
  posés, clés borg du rc seules).
- CodecSelfTest : « codes de sortie hérités demandés à borg (BORG_EXIT_CODES=legacy) : borg 1.4 « moderne » = borg 1.2 —
  avertissement gardé, erreur en échec, sondes de version (D134) » — borg factice « 1.4 » contre « 1.2 » : DiffBkp et Index en
  avertissement (code 0, sortie et `[WARN]` de borg list, borg diff, borg diff de l'Index) et en erreur (code 2, « a échoué »),
  mêmes codes et lignes sous 1.2 et 1.4, `legacy` reçu à chaque appel ; sondes de version (ssh direct, tunnel inverse local) :
  `legacy` reçu ; borg distant (boex avec `preBorg`, relais qui transmet l'environnement comme un sshd qui accepte `BORG_*`) :
  commande distante `<borg> …` sans préfixe, `legacy` reçu, avertissement en code 1, liste `preBorg` de l'appelant intacte. Le
  borg factice partagé (`_bf_env`) note la variable reçue (`exitcodes`) ; son fichier `b14` est une SENTINELLE de « legacy
  reçu » (codes modernes 101/31 seulement si la variable vaut `modern` ou est absente ; toute autre valeur — `legacy`, `Legacy`,
  vide — : codes hérités), pas un modèle de borg 1.4 (qui lit une variable absente comme `legacy`). Harnais « vrai borg »
  (`_rb_env`, environnements de `_rb_isolation` et `_rb_wrapper_rewrite`) : `BORG_EXIT_CODES=legacy`, comme boex.
- push selftest : « /download/* : codes de sortie hérités demandés à borg (BORG_EXIT_CODES=legacy) — serveur en codes
  modernes, borg 1.4 = borg 1.2 : 404 introuvable, 502 erreur, avertissement gardé (D142) » — bout en bout par l'application,
  borg factice 1.4/1.2 (variable absente = legacy, comme le vrai), serveur avec et sans `BORG_EXIT_CODES=modern` : chemin
  absent sans `bid` -> `[WARN]` de borg list puis 404 ; avec `bid` -> 404 ; `/download/tar` d'un préfixe absent -> 200, tar
  vide, `[WARN] … never matched` ; erreur -> 502 ; fichier et tar avec avertissement -> 200 et `[WARN]` ; `legacy` reçu par
  chaque borg.

## borgHelperWWW 1.31.10 — Journal des téléchargements : une ligne à la fin réelle, issue dite — 2026-10-10

Chantier « reconstruction progressive », story 71 (reports D143, D146 ; décisions de l'utilisateur Q1 = A, Q2 = A). Avant : la
ligne `[req]` était écrite au retour de `call_next`, avant l'envoi du corps — mesuré sur serveur réel (bac à sable `s71`, fichier
de 60 Mo) : téléchargement complet, abandonné par le client ou coupé par borg tué, toujours `[req] … 200 ~1000ms` (durée de
l'en-tête, jamais celle du transfert) ; client parti avant la réponse : `[req] … 500` et une trace complète
`RuntimeError: No response returned.` (BaseHTTPMiddleware, Starlette 0.18).

- `/download/*` : la ligne `[req]` est écrite UNE fois, à la fin réelle du transfert, durée totale ; issue en fin de ligne
  quand le flux n'est pas complet : ` (flux coupé)` (borg en échec en cours d'envoi, chien de garde d'inactivité — borg
  arrêté, ou données restées non lues —, arrêt du serveur pendant l'envoi, erreur inattendue pendant l'envoi) ou
  ` (client parti)` (abandon, et issue par défaut d'un transfert non fini qu'aucune autre règle ne classe). Complet : forme
  inchangée. Lignes `[ERREUR]` / `[WARN]` du téléchargement inchangées, sauf l'erreur inattendue du corps et les données non
  lues (voir Revue) ; quand le corps constate l'échec, son `[ERREUR]` vient avant la ligne `[req]` (chien de garde
  d'inactivité, `[WARN]` d'abandon : ordre non garanti) ; elle arrive tard pour un client qui cesse de lire et manque si le
  processus est tué avant, ou si la requête est annulée entre la route et la réponse. Derrière nginx en HTTP/1.0 (A85), le
  client peut toujours voir un flux coupé comme complet.
- Revue : erreur inattendue du corps après l'en-tête (lecture) -> flux coupé, fin de transfert retenue, `[ERREUR] <borg> :
  erreur pendant l'envoi (<exception>) — téléchargement interrompu (flux coupé)` à la place du `[WARN]` d'abandon (avant :
  fin envoyée, fichier tronqué tenu pour complet, « (client parti) », cause jamais dite sous Starlette 0.18) ; tube fermé par
  le chien de garde avec des octets non lus (borg fini, client arrêté `TIMEOUT` s) -> flux coupé, fin retenue, `[ERREUR]
  <borg> : téléchargement plus lu depuis <n> s — flux coupé` (avant : tronqué, fin envoyée, journalisé complet) — EOF seul restant : complet, le tube n'est plus relu après l'EOF ; tâche annulée
  pendant un arrêt du serveur -> « (flux coupé) » (arrêt demandé sans annulation : complet ou client parti, selon le cas) ;
  erreur de la sonde de l'en-tête, ou de celle du chemin 499 de Starlette 0.18, = client présent (jamais un téléchargement
  cassé pour le journal ; `RuntimeError` d'origine relancée).
- Client parti avant la réponse : `[req] … 499 <durée>ms (client parti avant la réponse)`, aucune trace, sur les deux piles —
  Starlette 0.18 : `RuntimeError` de Starlette lui-même ET client parti ; Starlette 1.7 (pas d'erreur : l'en-tête est produit
  puis ignoré par uvicorn, mesuré `200 … (client parti)` sans cette sonde) : client déjà parti au relais de l'en-tête. Une
  exception de l'application (même au texte « No response returned. ») ou une application sans réponse, client présent :
  500 et trace, comme avant.
- Inchangés : routes non diffusées (ligne écrite à la réponse, même forme), 403 de `require_user`, chemins masqués, codes
  HTTP envoyés, fin de transfert retenue d'un flux coupé (`_AbortableResponse`).
- Push selftest : contrôle bout en bout par la vraie application, une ligne de la matrice par cas (complet, client parti
  — deux variantes —, borg tué, client parti avant la réponse, route JSON, exception de l'application, RuntimeError de
  l'application au même texte, application sans réponse), plus les cas des revues (refus 502/404 avant le corps, erreur du
  corps, arrêt demandé avec ou sans annulation, tube fermé avec ou sans octets non lus, petit fichier, complet en code 1,
  sonde en erreur ou vraie, priorités de l'issue, exception hors envoi).
- Mesuré (serveur réel, bac à sable `s71`, `mesure.py`, 60 Mo, deux piles 3.10 / Starlette 0.18 et 3.14 / Starlette 1.7) :
  complet `200 1469ms` / `200 1445ms` ; client parti après 3 s `200 3009ms (client parti)` / `200 3006ms (client parti)` ;
  borg tué `200 50818ms (flux coupé)` / `200 52616ms (flux coupé)` (`[ERREUR]` inchangé) ; client parti avant la réponse
  `499 1043ms (client parti avant la réponse)` / `499 1021ms (…)`, aucune trace (mesure faite avant les corrections de revue ;
  remesuré après les trois revues, 3.10 : `200 1377ms`, `200 3008ms (client parti)`, `200 51915ms (flux coupé)`,
  `499 1062ms (client parti avant la réponse)`, aucune trace).
  Avant (3.10) : `200 990ms`, `200 1046ms`,
  `200 1036ms`, `500 1038ms` + trace ; 3.14 sans la sonde de l'en-tête : `200 1037ms (client parti)` pour le dernier cas.
  Push selftest 133/133 (3.10 et 3.14).

## UI 1.24.1 — Explorateur : refus 403 et JSON illisible dits clairement — 2026-10-10

Chantier « reconstruction progressive », story 70 (report D154 ; décision de l'utilisateur Q1 = B). Avant : un refus de
borgHelperWWW sans `exitcode` ni `stderr` — mesuré : `BORGHELPERWWW_REQUIRE_USER=1` et requête sans l'en-tête utilisateur ->
HTTP 403, corps `{"detail": "Identité utilisateur absente (header X-User) — accès refusé (require_user)"}` — s'affichait
« exitcode undefined » dans l'explorateur et sa recherche, et « HTTP 403 » (sans la raison) sur la liste des serveurs, la carte
d'un serveur, l'Historique complet et ses graphiques. Une réponse JSON illisible de `/treehist` laissait le spinner dans le
tableau, et toute erreur de l'explorateur gardait les entrées du répertoire précédent (lues par la boîte de téléchargement).

- Message d'erreur commun (`respError`) : `stderr` de borgHelper, sinon le `detail` du serveur (non textuel : « HTTP <code> —
  <JSON> » ; vide : ignoré), sinon « HTTP <code> » (« exitcode <n> » gardé dans l'explorateur pour une erreur de borgHelper sans stderr). Utilisé
  par l'explorateur, sa recherche et les cinq affichages qui montraient `stderr` ou « HTTP <code> » (droits/périmètre en
  erreur 5xx, liste des serveurs, carte, Historique complet, graphiques) ; préfixes « Erreur : » gardés.
- Explorateur : sur toute erreur (refus, erreur de borgHelper, JSON illisible ou `null`, erreur du nick, « Aucune donnée »),
  message affiché, tableau vidé et entrées oubliées ; la navigation réussie suivante affiche le nouveau répertoire et efface
  le message. Recherche : résultats vidés sur toute erreur (déjà le cas), message tiré de `respError`.
- Inchangés : 401 (déconnexion), réponses réussies, « Aucune donnée », « Répertoire vide », messages de stderr ;
  borgHelperWWW et borgHelper inchangés. Un 403 sur `/access` reste silencieux (forme inattendue), la liste des serveurs
  disant le refus par `/report`.
- Test de l'UI (`node borgHelperWWW_ui_test.js`) : réponse 403 capturée passée par le vrai `apiCall`, puis rendue par
  l'explorateur, la recherche, la liste des serveurs, la carte, l'Historique complet et les graphiques (le `detail`, jamais
  « undefined ») ; 403 sans `detail` (« HTTP 403 ») ; JSON illisible (message, tableau sans spinner, entrées vidées) ; erreur de
  borgHelper (stderr inchangé) ; réussite après erreur ; aucun ancien affichage `r.stderr||('HTTP '+…)` restant.

## borgHelper 1.0.194 — Passphrase avec « % » passée par -P ou BORGHELPERC_RUNTIME_PASSPHRASE — 2026-10-10

Chantier « reconstruction progressive », story 69 (report D190). Avant : la passphrase de `-P` ou de
`BORGHELPERC_RUNTIME_PASSPHRASE` était posée telle quelle dans la section du rc, lue avec interpolation (`%(…)s`) : `a%b`
faisait planter la commande (`ValueError`, trace — LstBkp, Bkp… — ou « Erreur : invalid interpolation syntax » dans Status ;
`BKP_STATUS_TIMEOUT` du nick ignoré en silence par un Status lancé avec cette passphrase), `a%(x)s` donnait « Bad value
substitution », et `a%%b` était relue `a%b` (passphrase fausse). Même défaut pour le téléchargement de borgHelperWWW
(`/download`, en-tête `X-Borg-Passphrase` contenant `%` : erreur 500 ou passphrase fausse), qui lit le rc par la même fonction.

- La passphrase injectée est échappée (`%` -> `%%`) comme `cfgwrite` le fait depuis 1.0.175 : relue à l'identique quel que
  soit son contenu. Valeurs du rc et passphrase lue dans le rc : inchangées. Passphrase non textuelle (bibliothèque) :
  `TypeError`, comme avant.
- **Compatibilité :** qui doublait les `%` de sa passphrase dans `-P`, `BORGHELPERC_RUNTIME_PASSPHRASE` ou `X-Borg-Passphrase`
  pour contourner le défaut doit cesser : la valeur passe désormais telle quelle (`a%%b` = deux `%`).
- Mesuré de bout en bout (dépôt borg neuf, passphrase `p%q%%r%(x)s`, Sentry neutralisé) : Init, Bkp, LstBkp, Status en code 0,
  par la variable comme par `-P` ; une passphrase voisine refusée par borg.
- CodecSelfTest : « passphrase injectée avec « % » (-P, variable) : relue à l'identique, BKP_STATUS_TIMEOUT lu, aucune
  exception (1.0.194) » — `a%b`, `a%%b`, `a%(x)s`, `a%(BORG_REPO)s`, `%`, `100%`, `plain`, chaîne vide (`cfg[…]`, `cfg.get`,
  `dict(cfg)`, `BKP_STATUS_TIMEOUT`) ; passphrase `bytes` -> `TypeError` ; CLI réelle `-P 'a%b'` et variable -> Status code 0 ;
  témoin sans passphrase (rc relu, délai lu).

## borgHelper 1.0.193 — CLI : DiffBkp -j en JSON, ArchiveHistory sans archive_stats en rows, Status en code 1 quand un nick est en erreur — 2026-10-09

Chantier « reconstruction progressive », story 68 (reports D114, D138, D148 ; décisions de l'utilisateur Q1-Q3). Avant, trois
sorties trompaient un consommateur machine : `DiffBkp -j` sur un dépôt de moins de deux archives n'écrivait rien sur stdout
(la ligne sur stderr, code 3) ; `ArchiveHistory -j` sur une `diff.db` sans table `archive_stats` rendait
`{"error": "… no such table: archive_stats"}` quand `RepoHistory` rend `rows: []` dans le même cas ; `Status` sortait en code 0
avec une base illisible ou corrompue (texte et `-j`) — un cron ne voyait pas l'erreur.

- `DiffBkp -j`, moins de deux archives (une ou aucune) : `{"error": "<nick>: <n> archive(s) dans le dépôt, 2 nécessaire(s)"}`
  seul sur stdout, rien sur stderr, code 3 — comme les autres erreurs de `DiffBkp -j`. Texte : inchangé (ligne sur stderr,
  code 3) ; Restore et Mount (autres appelants) inchangés.
- `ArchiveHistory -j`, `diff.db` sans `archive_stats` : `rows` sans archive vivante, lignes figées de `history.db` (`pruned`)
  gardées, code 0, aucune ligne `[ERREUR]`. Colonne absente (« no such column », schéma abîmé) et vraie erreur SQLite :
  inchangées.
- `Status` : code **1** dès qu'un nick demandé finit en erreur — `last_backup.error` (base illisible, corrompue, passphrase
  absente, base en migration) ou exception isolée du nick (champ `error`, même au message vide) — ou qu'une erreur SQLite réelle
  d'une lecture est dite pendant l'appel (`[ERREUR] SQLite error …` : `history.db` corrompue ou verrouillée, fantôme, marqueurs),
  texte comme `-j` ; état de tous les nicks toujours écrit, sorties inchangées, notice de nettoyage gardée ; sinon 0.
  `BorgHelper.status()` rend ce code (avant : `None`). Aide `-H Status` : ligne du code 1. LIBRARY.md : `status()` et
  `getlastbkp(…, as_json=False)`.
- borgHelperWWW et UI inchangés : `/diffbkp` sans périmètre lance `DiffBkp` en texte (inchangé) ; avec périmètre (`-j` forcé),
  l'erreur arrive dans `stdout` (`{"error"}`, relayée telle quelle par le filtre, HTTP 400, jamais en cache) au lieu de `stderr` ;
  `/archivehistory` rend `rows` (graphiques : les lignes figées, ou « Aucune statistique d'archive enregistrée — lancer un Index… »)
  au lieu de `{"error"}` en rouge ;
  Status n'est pas relayé (`/access` appelle `_status_one`).
- Tests : CodecSelfTest, un contrôle par ligne de la matrice (D114 : `DiffBkp -j` une archive et dépôt vide, texte une archive
  + Mount `-b last` et Restore `-L` ; D138 : table absente avec et sans ligne figée, colonne absente ; D148 : base corrompue,
  exception isolée — message vide compris —, aucun nick en erreur ; history.db corrompue, passphrase absente réelle, notice de
  nettoyage en code 1) ; borg factice : mode `archn` (nombre d'archives exact). Contrôle A87 (« lecteurs :
  erreur SQLite réelle ou nick arrêté… ») : Status sur une base verrouillée au-delà du délai attendu en code 1 (avant : 0).

## borgHelper 1.0.192, UI 1.24.0 — Graphiques : axe temporel réel, gain du premier Prune — 2026-10-09

Chantier « reconstruction progressive », story 67 (reports D034, D035, D040, D050, D192, D197 ; décisions de
l'utilisateur Q1-Q5). Avant : les graphiques de la page Historique avaient un axe X en catégories (intervalles inégaux
dessinés égaux), des étiquettes brutes décalées de 2 h d'une famille à l'autre (`updated_at` en UTC, `archive_date` en heure
locale), et le gain d'un Prune dont la mesure précédente était sortie de la fenêtre `STATS_RETENTION_MONTHS` n'était jamais
dessiné (`pruneDeltas` exigeait une ligne précédente).

- borgHelper 1.0.192 : la purge de `repo_stats` à l'écriture (fin de Bkp/Prune/Index) garde la plus récente des mesures
  d'avant `STATS_RETENTION_MONTHS` (une seule par nick) ; `RepoHistory -j` la rend à part, clé `baseline` (même forme qu'une
  ligne, `null` s'il n'y en a pas ; plusieurs mesures anciennes encore là après une rétention abaissée : la plus grande
  `id` avant la borne), jamais dans `rows` — `rows` inchangé. Borne de la fenêtre calculée une fois par lecture
  (`rows` et `baseline` jamais d'accord sur une même ligne). Aide de `RepoHistory` complétée. Aucun gain calculé ni stocké
  côté serveur ; `ArchiveHistory` et borgHelperWWW (relais tel quel) inchangés.
- UI 1.24.0 : échelle `time` de Chart.js sur les cinq graphiques (taille du dépôt, gain Prune, métriques par archive, fichiers
  modifiés, durée), points et barres à leur date ; adaptateur de dates écrit dans l'UI (Date native, posé au premier
  dessin — Chart.js local ou CDN de repli), aucune dépendance ni ressource externe nouvelle. `updated_at` lu en UTC,
  `archive_date` en heure locale (celle de l'hôte de borgHelper, lue dans le fuseau du navigateur : les heures des deux
  familles concordent quand navigateur et hôte partagent le même fuseau), tout affiché en heure locale du navigateur, en
  ISO : infobulle « 2026-10-04 10:46 »
  (« (supprimée) » gardé), graduations selon l'unité (« 2026-10-04 », « 2026-10 », « 2026-10-04 10:00 »). Axe borné aux
  dates des données ; une seule date : un jour centré, une graduation à cette date. Barres (durée, fichiers modifiés, gain
  Prune) de largeur fixe 8 px — sinon dimensionnées sur le plus petit écart (0 px pour deux archives à 5 s sur un axe d'un
  mois, toute la largeur pour une seule). Graphique par archive vide si seules des lignes à date illisible portent ses
  valeurs : son message habituel. Date illisible (vide, malformée,
  31 février) : ligne hors de l'axe, graphique dessiné, jamais d'exception (sa mesure compte encore pour le gain du Prune
  suivant). Premier Prune de la fenêtre : gain = `baseline.unique_csize - unique_csize du Prune` ; sans aucune mesure
  antérieure (`baseline` nulle, ou borgHelper < 1.0.192) : Prune marqué d'une croix sans barre, infobulle et ligne sous le
  graphique « gain inconnu : aucune mesure précédente ». Messages existants (aucune donnée, erreur, données partielles,
  bibliothèque absente) inchangés.
- Tests : CodecSelfTest — purge (défaut 13 mois, surcharge par nick : 3 mesures hors fenêtre + 1 écrite -> la plus récente
  hors fenêtre gardée, autre nick intact), `RepoHistory -j` `baseline` (forme, hors `rows`, `null` sans mesure ancienne ou
  sans mesure). `borgHelperWWW_ui_test.js` : échelle `time` et adaptateur (formats, startOf/endOf/add/diff), premier Prune
  (avec base, sans base, ancien serveur), dates illisibles, même `updated_at`, une seule ligne ; vraie Chart.js
  (`vendor/chartjs`) sur un canvas simulé, fuseau Europe/Paris : réponses réelles capturées (borgHelperWWW, Bkp à J, J+5 s,
  J+35 s puis Prune ; premier Prune chiffré par `baseline`) -> espacement proportionnel au temps, heures des deux familles
  concordantes (navigateur et hôte au même fuseau), graduations ISO par unité, barres de 8 px (J, J+5 s, J+30 j ; barre
  seule). CodecSelfTest : `baseline` = plus grande id avant la borne quand plusieurs mesures anciennes restent.

## borgHelperWWW 1.31.9, borgHelper 1.0.191 — Commande arrêtée par borgHelperWWW : dossiers _MEI* de borg retirés à l'arrêt — 2026-10-08

Chantier « reconstruction progressive », story 65 (F334, décision de l'utilisateur). Avant : une commande arrêtée par
borgHelperWWW (délai `BORGHELPERWWW_TIMEOUT` -> 504, restes après la sortie de borgHelper, arrêt du serveur relayé) laissait le
dossier d'extraction PyInstaller de son borg (`/tmp/_MEI*`, ~57 Mo) quand borg était tué au SIGKILL ou arrêté pendant son
démarrage — le chargeur ne retire son dossier que si borg sort de lui-même. Les téléchargements les retiraient déjà (1.31.1).

- borgHelperWWW 1.31.9 : `_run_group` relève les `_MEI*` de son groupe juste avant chaque signal (SIGTERM, SIGKILL ; 1er signal
  d'arrêt du serveur relayé par `_signal_groups`) et les retire une fois le groupe vide, s'ils ne sont plus utilisés — seuls
  ceux de ce borg, jamais l'extraction d'un autre ; jamais par motif ni par âge. Une erreur du relevé n'empêche jamais le
  signal. Signaux, délais et codes HTTP inchangés ; sortie normale : rien relevé, aucune attente. Concerne toute commande passée
  à borgHelper par l'API (`/restore` compris), le `BkpReconcile` du watcher et le `borg list` des téléchargements.
- borgHelper 1.0.191 : `_mei_mapped` ne relève plus qu'un dossier au nom PyInstaller (`_MEI` + 6 caractères alphanumériques)
  situé dans un dossier temporaire du processus relevé (TMPDIR, TEMP, TMP de son environnement, puis /tmp, /var/tmp, /usr/tmp) —
  avant, tout chemin contenant « /_MEI » : un `borg extract` (boex, `/restore`) qui écrivait dans `<dest>/…/_MEIxxx` ou y
  travaillait voyait ce dossier de données retiré à son arrêt. `_purge_mei_dirs`, `_purge_mei_orphans` et `_mei_dirs` (fin de
  CodecSelfTest) refusent tout nom hors motif (un `/tmp/_MEIdonnees` vieux et inutilisé n'est plus retiré).
- Limites : arrêt forcé du serveur (2e signal, atexit) non couvert (le serveur sort : rien relevé ni retiré) ; sous un uvicorn
  externe (`uvicorn borgHelperWWW:app`), le 1er signal n'est pas relayé (seul le SIGKILL d'atexit) — non couvert ; relevé
  ponctuel — un chargeur saisi entre deux fichiers de son extraction (ni fichier ouvert ni mappage à cet instant) échappe ; un
  membre qui survit au SIGKILL (état D) garde son dossier, jamais repris ensuite ; extraction jamais relevée si le TMPDIR de borg
  est relatif, si borg est construit avec un `runtime_tmpdir`, ou si son environnement est illisible alors qu'il a son propre
  TMPDIR ; une restauration dont un chemin devient enfant direct d'un dossier temporaire avec un nom au motif (`dest=/`,
  `tmp/_MEIxxxxxx` dans l'archive) reste relevée.
- Mesuré (`mesure65.py`, deux piles 3.10 / 3.14, `TIMEOUT=4`) — G (borg figé, SIGKILL), D (délai pendant le démarrage de borg),
  T (borg relâché 1 s après le délai). Avant (`work/m65/mesure65-o3.log`) : G 504 en 14,1 s / 14,1 s, D 5,0 s / 5,1 s, T 5,1 s /
  5,1 s, un `_MEI*` laissé dans chaque cas. Après (`work/m65/mesure65-f.log`) : G 14,2 s / 14,1 s, D 5,1 s / 5,1 s, T 5,1 s /
  5,1 s, aucun `_MEI*` laissé ; code final (`mesure65-f2.log`) : G 14,1 s / 14,2 s, D 5,1 s / 5,1 s, T 5,0 s / 5,1 s, aucun.
- Contrôles : push selftest « délai et arrêts de borgHelperWWW (_run_group) : _MEI* du groupe… » — `os.killpg` espionné (le jeu du
  groupe contient le dossier au moment du signal attendu) ; délai avec dossier tenu seulement au SIGTERM (vu au SIGKILL), membre
  mort au SIGTERM qui tient le dossier par mmap, par un fd seul, par son cwd seul ; restes après sortie ; 1er signal relayé ;
  2e signal (SIGKILL relayé) sans relevé ; dossier encore utilisé gardé ; relevé en erreur : signal envoyé (SIGTERM et SIGKILL du
  délai, relais) ; membre de type `/restore` : dossier de données au motif hors de son TMPDIR, tenu par fd ou cwd, intact après
  le 504 ; sortie normale sans relevé ni purge ; voisin au motif, vieilli, dans `tempfile.tempdir` du contrôle : intact. Factices
  fidèles (TMPDIR = dossier du test, noms au motif) dans les contrôles `_MEI` de borgHelper et de borgHelperWWW. CodecSelfTest :
  « _MEI* d'un borg tué » (données `_MEI…` hors dossier temporaire tenues par fd et cwd, nom long tenu dans TMPDIR : jamais
  relevés ; TMPDIR par lien symbolique ; repli /tmp, /var/tmp, /usr/tmp sans TMPDIR ; TEMP seul) ; orphelins de boex et fin de
  run : nom hors motif vieilli gardé ; nouveau contrôle sur vrai borg (`borg serve` figé, avec TMPDIR et sans) : un dossier au
  motif dans son dossier temporaire, retiré après l'arrêt, rien laissé.

## borgHelper 1.0.190 — BkpReconcile : nick inconnu en une ligne — 2026-10-08

Chantier « reconstruction progressive », story 64 (rétrospective 61-63, F336, A121 ; décision de l'utilisateur). Avant :
`BkpReconcile -n <nick absent du rc>` (ou sans `-n`, nom de la machine absent du rc) écrivait deux lignes pour une seule cause,
« `<nick> : nick inconnu du rc` » puis « `<nick> : vérification impossible` ».

- borgHelper 1.0.190 : nick inconnu du rc dit en une seule ligne, « `<nick> : nick inconnu du rc` », à sa place dans l'ordre
  de la demande (texte et `-j`). Inchangés : code 1, JSON `-j` (`{nick, verified: false, runs: {}}`, la ligne restant sur
  stderr), lignes des autres nicks (« `aucun Bkp interrompu` », « `vérification impossible` » d'un nick connu non vérifié,
  `[WARN] … base illisible`), « `aucun nick dans le rc` ». Aide `-h bkpreconcile` : « code 1 : vérification impossible ou nick
  inconnu du rc, ou rc sans nick ». borgHelperWWW non touché (le watcher ne passe que des nicks du rc, en `-j`).
- Contrôles : CodecSelfTest (nick inconnu : une ligne exacte en texte, JSON inchangé en `-j` ; liste mixte dans les deux ordres,
  lignes dans l'ordre de la demande, seul le nick connu lance `borg list` ; CLI sans `-n` ; code 1 ; nick connu non vérifié :
  « `vérification impossible` » toujours dit ; rc sans nick : « `aucun nick dans le rc` », texte et `-j`).

## borgHelperWWW 1.31.8, borgHelper 1.0.189 — Fin d'un Bkp tué notifiée aussitôt — 2026-10-07

Chantier « reconstruction progressive », story 63 (rétrospective 57-60, A118 ; décisions de l'utilisateur). Avant : pour un Bkp
tué, `/access` le disait interrompu tout de suite (1.31.5), mais la fin n'était notifiée qu'au rapprochement par un Index ou au
délai `BKP_STATUS_TIMEOUT` (6 h) — mesuré (délai ramené à 90 s, `work/m63/mesure63-o.log`) : borgHelper et borg tués -> échec au
délai ; borgHelper tué, archive écrite -> **échec au délai alors que l'archive existait** (l'Index suivant rapprochait en succès,
jamais renotifié).

- borgHelper 1.0.189 : commande `BkpReconcile [-n nick/ALL] [-j]` — rapprochement des Bkp tués sans Index (même règle, un `borg
  list` par nick à candidat, qui cède à une opération prioritaire) ; compte rendu par run (`fermé`, `absent`, `vivant`,
  `orphelin`, `fin illisible`, `erreur de base`, `non fermé`, `non vérifié`, `non vérifiable` — dépôt distant, jamais `absent`) ;
  `borg create` d'un run vu dans /proc même avant son verrou (`orphelin`) ; base illisible dite en `[WARN]` ; code 1 si la
  vérification est impossible, nick inconnu du rc, rc sans nick. Ligne `absent` laissée ouverte (décision de l'utilisateur) :
  une archive arrivée ensuite reste rapprochable.
- borgHelperWWW 1.31.8 : le watcher lance `BkpReconcile` dès qu'un Bkp tué est interrompu (dépôt local, état lisible ; une fois
  par Bkp et par processus serveur, jamais après la fin notifiée ; dans un fil, un seul par nick) ; archive écrite : fin
  « succès » au passage suivant ; aucune archive de ce run (vérifié) : fin « échec » aussitôt + Sentry « Sauvegarde interrompue —
  <nick> (borgHelper arrêté, aucune archive de ce Bkp) », pour chaque Bkp tué ainsi vérifié. Dépôt distant, état illisible :
  délai inchangé ; vérification impossible, fermeture ou réclamation refusée par la base : nouvel essai 10 min après ; fin
  d'archive illisible : dit au journal, fin au délai.
- Mesuré (`work/m63/mesure63-f3.log`, vrai serveur, vrai borg, watcher toutes les 5 s) : échec à 4,4 s (avant : 88 s), archive
  écrite -> succès à 9,9 s (avant : échec à 86 s), Index aussitôt : inchangé (succès).
- Contrôles : CodecSelfTest (compte rendu par run sur 19 cas dont `borg create` sans verrou, dépôt distant, base en erreur,
  fermeture refusée ; leurres de `run_create_alive` ; vraie requête de la garde « fin déjà notifiée » ; commande : code 0 et
  JSON, dépôt absent code 1, base illisible dite, arrêt prioritaire, nick inconnu, rc sans nick, `-n` nettoyé, sortie texte) ;
  push selftest (échec vérifié notifié une fois + Sentry, fin déjà notifiée, garde illisible, plusieurs Bkp tués dont une
  réclamation en échec, CAS perdu, réclamation impossible ou refusée par la base, fermé, fin illisible, non vérifiable, non
  fermé, ligne fermée ailleurs, erreur de base, sortie non JSON, délai illimité borné à 3600 s, vérification impossible avec
  code et [WARN] au journal, vivant, état inconnu, Bkp vivant, dépôt distant, un seul fil par nick, passage jamais bloqué,
  purge au-delà de 500, appel par le passage du watcher).

## borgHelperWWW 1.31.7 — Borg bloqué en écriture : il rend son verrou au SIGTERM — 2026-10-07

Chantier « reconstruction progressive », story 62 (rétrospective 57-60, A117 ; décision de l'utilisateur : documentation
seule). Le report A117 et la doc de 1.31.6 disaient qu'un borg bloqué en écriture (client qui ne lit plus), arrêté par le chien
de garde ou le premier signal d'arrêt, « ne traite pas SIGTERM » et laisse son entrée de `lock.roster`. Mesuré faux
(`work/m62/mesure62-o.log`, chronologies `roster62.out` et `roster62b.out` : chien de garde et premier signal, deux piles,
`--timeout 4`, dépôt local, `export-tar`) : au SIGTERM, borg retire son entrée dans les 0,1 s (verrou rendu) puis reste bloqué
en écriture (`pipe_write`) jusqu'au SIGKILL du délai (5 s ; `_MEI*` retirés, `[ERREUR]` du chien de garde au journal). La
mesure de la story 60 le montrait déjà (`mesure60-f.log` : borg mort à 5,0 s, aucune entrée) — la conclusion avait été tirée du
seul délai de mort. Une entrée reste après un SIGKILL immédiat (arrêt forcé, `atexit`, fin du lifespan : décision de la story
60 maintenue) et pour un borg figé.

- README, TECHNICAL, commentaire de `stop()` et docstring du contrôle bout en bout corrigés ; phrase de 1.31.6 marquée.
- Aucun changement de comportement.

## borgHelperWWW 1.31.6 — Téléchargement abandonné : borg arrêté aussitôt — 2026-10-07

Chantier « reconstruction progressive », story 60 (constat de la story 57 ; décision de l'utilisateur). Avant : un client qui
abandonnait un `/download/*` ne voyait pas borg arrêté « aussitôt » (README 1.30.2) — mesuré sur vrai serveur : 28 s, 56 s, ou
plus de 90 s (jusqu'à l'arrêt du serveur) ; borg et le verrou du dépôt restaient tenus, un Bkp suivant échouait sur le verrou.
Cause mesurée (copie instrumentée) : la réponse externe du middleware finissait aussitôt, mais le corps de `_borg_stream`,
annulé pendant un envoi dans la tâche interne de `BaseHTTPMiddleware`, n'était jamais fermé — son `finally` (qui arrête borg)
attendait le ramasse-miettes.

- Corps fermé à la fin de la réponse, même annulée (`_ClosingStreamingResponse` : `aclose()` protégé de l'annulation), sous les
  deux piles (fastapi 0.63 / starlette 0.18, fastapi 0.142 / starlette 1.7).
- Arrêt de borg (décision de l'utilisateur) : SIGTERM au groupe — borg rend lui-même son entrée de `lock.roster` —, SIGKILL
  5 s après (`_KILL_GRACE`, fil d'arrière-plan) s'il vit encore ; client parti, chien de garde et premier signal d'arrêt du
  serveur. Arrêt forcé (second signal), `atexit`, fin du lifespan : SIGKILL immédiat, comme avant. Avant : SIGKILL toujours —
  entrée périmée laissée dans `lock.roster`.
- Client parti : sortie de borg vidée pendant l'arrêt (mesuré : bloqué en écriture sur un tube plein, borg ne traitait pas
  SIGTERM et finissait au SIGKILL du délai [corrigé en 1.31.7 : il traite SIGTERM et rend son verrou ; c'est sa sortie à la
  fermeture qui reste bloquée jusqu'au SIGKILL]) ; attente et récolte dans un fil (la boucle d'événements n'attend plus borg).
- Lectures du corps annulables (`run_in_executor`, exécuteur dédié de 40 fils comme le limiteur d'anyio ; `run_in_threadpool`
  attendait la fin du fil même annulé) : un client parti pendant que borg se tait est traité aussitôt (mesuré : borg gelé, départ
  jamais traité en 90 s sous 3.14).
- Client parti avant le premier envoi du corps : borg arrêté aussi (avant : la fermeture d'un corps jamais commencé ne faisait
  rien — borg et le verrou gardés jusqu'au chien de garde, 3.10 ; revue).
- Causes et journal avec le vrai borg : il traite SIGTERM et sort en 143 (mesuré) — « aucune activité depuis N s », « arrêt du
  serveur » et la ligne `[ERREUR]` du chien de garde reconnaissent cette sortie (sans quoi : « code 143 », ligne perdue ; revue).
- SIGKILL différé armé sans démarrer de fil dans le gestionnaire de signal (un seul fil `borg-kill`, file sans verrou ; revue).
- `_MEI*` d'un borg arrêté pour client parti relevés avant le signal et retirés — avant : jamais relevés sur ce chemin (témoin
  de la baseline : un dossier `/tmp/_MEI*` de 57 Mo laissé par abandon tué par SIGKILL ; 27 retirés de /tmp après les mesures).
- Mesuré (vrai serveur, rc de démo, vrai borg ; `work/m60/mesure60-f5.log`, `mesure60-fgel3.log`, témoin baseline
  `mesure60-o.log`) : abandon après 512 Ko, 4 tours par pile -> borg arrêté par SIGTERM (sortie 143) en 0,06-0,07 s, aucune entrée dans `lock.roster`, aucun `_MEI*` laissé
  (témoin : 28 s à plus de 90 s, entrée laissée par 3 tours sur 4 — le 4e, arrêté par le SIGTERM du dispositif après 90 s) ; borg gelé (sourd à SIGTERM), 2 tours par pile -> SIGKILL à
  5,05-5,10 s, `_MEI*` retirés (entrée de `lock.roster` laissée par le SIGKILL, retirée par le borg suivant).
- Contrôles : push selftest — bout en bout par la vraie application, corps retenu et ramasse-miettes coupé, envois après le
  départ ignorés comme uvicorn (envoi bloqué puis déconnexion, aussi par `/download/file` ; envoi qui lève ; borg muet ; départ
  avant le premier envoi), application finie et borg mort moins de 2 s après le départ ; borg factice qui traite SIGTERM comme
  borg (143) ; borg sourd à SIGTERM -> SIGKILL au délai, fermeture du corps sans attente ; `_MEI*` du client parti retirés ;
  chien de garde et arrêt du serveur avec un borg sorti en 143 ; premier signal = SIGTERM ; arrêt forcé et `atexit` : SIGKILL
  aussitôt d'un borg sourd à SIGTERM.

## borgHelperWWW 1.31.5, UI 1.23.1, borgHelper 1.0.188 — /access et alerte de retard alignés sur le marqueur et l'orphelin — 2026-10-06

Chantier « reconstruction progressive », story 59 (rétrospective F305, A115 ; décisions de l'utilisateur). Avant : `/access`
(`bkp_running`, ⏳ de l'UI, suivi d'un ▶ Backup) et l'alerte de retard lisaient la base seule — un Bkp tué restait « en cours »
jusqu'à `BKP_STATUS_TIMEOUT` (6 h par défaut), alors que Status (1.0.186) le dit interrompu.

- borgHelper 1.0.188 : `BorgHelper.bkp_state(nick)` — l'état du Bkp de Status extrait de `_status_one`, source unique de Status
  et de borgHelperWWW. `_lock_holder` (tous les verrous à PID : priority, index-running, marqueurs…) : un PID zombie compte mort — un Bkp lancé par `POST /bkp` puis tué reste enfant non
  récolté du worker (`os.kill(pid, 0)` y réussit) : Status et /access le disaient « en cours », et l'Index se mettait en pause
  sans fin derrière son `priority.lock` (mesuré : témoin bloqué, `index-paused.lock` resté). `/proc` illisible (hidepid) : inchangé.
- borgHelperWWW 1.31.5 : `/access` — `bkp_running` vrai seulement si un processus du Bkp vit (vivant, en attente de l'Index,
  borg create orphelin), `bkp_detail` (`en_cours`, `en_attente`, `orphelin`), `bkp_interrupted` (`{started_at, verifie}` comme
  Status) ; alerte de retard : suspendue par un Bkp vivant ou un état illisible (décision de l'utilisateur, revue), plus par un
  Bkp tué — même si son borg a écrit une archive que seul le prochain Index fera connaître (décision de l'utilisateur). Coût par
  relecture (30 s) : base et marqueurs ; `bkp_state` (lock.roster d'un dépôt local) seulement s'il y a une ligne ouverte ou un
  marqueur, dans une sonde bornée (1 s ; figée : dernier état lu, sinon inconnu ; état oublié dès qu'il n'y a plus rien).
- UI 1.23.1 : badges « ⏳ Bkp en cours », « ⏳ Bkp en attente de l'Index », « ⏳ Bkp interrompu, borg create encore actif »,
  « ⚠ Bkp interrompu » (au survol : « borgHelper arrêté — fermé au prochain Index si son archive existe » ; dépôt distant :
  « borgHelper arrêté, borg non vérifiable (dépôt distant) — … ») ; suivi d'un ▶ Backup : fin aussi pour un Bkp tué avant toute
  relecture (`bkp_interrupted`). Effet de WWW 1.31.5 : un ▶ Backup suivi se termine dès que le Bkp n'est plus en cours (avant :
  au délai).
- Mesuré (serveur de test, rc de démo, vrai borg ; `work/m59/mesure59b.log`, témoin sur le code d'avant
  `mesure59-temoin.log`) : vivant -> en cours ; borgHelper tué, borg suspendu -> orphelin (avant : en cours) ; borg fini ->
  interrompu (avant : en cours) ; après Index -> rien ; même parcours par `POST /bkp` avec le borgHelper tué ZOMBIE dans le worker
  -> orphelin puis interrompu (avant : en cours, et l'Index du témoin en pause sans fin).
- Contrôles : push selftest — état relayé (orphelin, attente, interrompu, inconnu), coût (ni ligne ni marqueur : `bkp_state`
  jamais appelé), sonde figée ; décors des contrôles /access et retard dotés d'un marqueur vivant (vrai processus) quand ils
  simulent un Bkp vivant ; CodecSelfTest « porteur zombie -> mort » ; test UI (node) des badges.
- Séries de mutations (code final après revue, lignes entières ; journaux vérifiés : échec sur l'assertion de sa pièce) :
  borgHelperWWW et borgHelper sous Python 3.14 strict 17/17 DÉTECTÉES — /access et alerte sur la base seule, garde de coût
  retirée, sonde non bornée, sans dernier état, impossible (500), marqueurs ou base illisibles pris pour « rien », erreur avalée
  prise pour « rien », dernier état jamais oublié, alerte envoyée en état inconnu, détail toujours « en_cours », interrompu
  jamais relayé ; zombie compté vivant, état de processus jamais lu, `bkp_unknown` toujours faux, Status hors de `bkp_state`
  (W6 a d'abord survécu : cas « marqueur sans ligne » ajouté au contrôle, puis DÉTECTÉ) ; UI (test node) 5/5 — orphelin et
  attente dits « en cours », interrompu sans badge, infobulle du dépôt distant, suivi d'un Bkp tué avant relecture jamais clos.

## borgHelper 1.0.187 — Archive rapprochée : dite, pas « borg : — » — 2026-10-06

Chantier « reconstruction progressive », story 58 (rétrospective F313, A116 ; décisions de l'utilisateur). Avant : l'archive d'un
Bkp tué que l'Index rapproche (1.0.185) n'avait aucune mesure de Bkp — Status `borg : —`, Report et UI colonne borg `—`,
ArchiveHistory versions et C/E `null` : indiscernable d'une archive faite hors borgHelper (mesuré, `work/m58/mesure58b.log`).

- Rapprochement (Index, ou début du Bkp suivant) : l'archive est marquée juste avant la fermeture de la ligne
  (`archive_measure.reconciled`, colonne ajoutée par introspection comme 1.0.165 ; version de schéma inchangée ; jamais sur une
  archive qui a une mesure ; échec : ligne fermée quand même, Index ou Bkp continue).
- Status : `borg : inconnue (Bkp interrompu, archive rapprochée)` ; Report (texte, HTML, JSON) et UI : `— (rapprochée)` ;
  JSON `reconciled` (Status `last_backup`, ArchiveHistory ; `false` = aucune marque, pas une preuve). Versions et compteurs
  d'avertissements restent inconnus ; push de fin, borgHelperWWW et UI inchangés (valeurs relayées telles quelles, mesuré) ;
  archives rapprochées avant 1.0.187 : `—`.
- Contrôles : « archive rapprochée sur vrai borg » (Index réel ; Status texte et JSON, Report -o texte/JSON/HTML, Report en
  direct texte et JSON, ArchiveHistory) ; rapprochement (archive marquée, à l'Index et par le Bkp suivant ; marque impossible) ;
  history.db d'avant 1.0.165 et de 1.0.165 à 1.0.186 (colonne ajoutée, marque refusée sur une archive mesurée) ; listes de
  colonnes figées revues.
- Série de mutations (3.14 strict, lignes entières, code final après revue ; journaux vérifiés : échec sur l'assertion de sa
  pièce) : 11/11 DÉTECTÉES — archive jamais marquée, marque écrite sur une archive mesurée, marque jamais lue, colonne non
  ajoutée aux bases d'avant (boucle ALTER) puis garde de 1.0.186 (bases 1.0.165–1.0.186), Report/UI et Status muets,
  `reconciled` toujours faux (Status -j, ArchiveHistory), `sys.exit` de la marque qui arrête le rapprochement, marque posée
  après la fermeture. Deux mutants d'une première série mal construits (SQL aux marqueurs faux ; constante partagée qui cassait
  la lecture : ils plantaient au lieu de viser leur pièce) refaits.

## borgHelperWWW 1.31.4 — Compatible fastapi 0.63 (Python 3.10) et 0.142 (Python 3.14) — 2026-10-06

Chantier « reconstruction progressive », story 57 (rétrospective F311, A114 ; décision de l'utilisateur : « compatible des deux »).
Avant : le push selftest ne tournait que sous le Python système (3.10, fastapi 0.63, pydantic 1.8) — `work/py/venv-3.14` n'avait pas
fastapi. Installée, la pile courante sous 3.14 (fastapi 0.142, pydantic 2.13, starlette 1.7, uvicorn 0.54) donnait 122/125
et, en avertissements stricts, une erreur au chargement (`@app.on_event` déprécié).

- Démarrage/arrêt (watcher bkp_status, borg des téléchargements) par `app.router.lifespan_context` (existe dans les deux piles ;
  `FastAPI(lifespan=)` n'existe pas en 0.63, `on_event` est déprécié en 0.142).
- pydantic : `_mdump` (`model_dump` ou `dict`), `_mset` (`model_fields_set` ou `__fields_set__`).
- fastapi 0.142 : télémétrie OpenTelemetry et `strict_content_type` coupés quand ces options existent (`_fastapi_compat_kw`) —
  corps JSON sans `Content-Type` accepté comme en 0.63.
- Arrêt en exécution directe (`_make_server`), écarts d'uvicorn 0.54 : force l'arrêt à tout second signal (0.54 : second SIGINT
  seulement) ; ne relance plus les signaux reçus après `serve()` (mort par SIGTERM, atexit sauté) ; `_LIVE_BORG_LOCK` et
  `_LIVE_GROUPS_LOCK` en `RLock` (`handle_exit` tourne dans le vrai gestionnaire de signal : un verrou déjà tenu s'interbloquait) ;
  au second signal, connexions ouvertes coupées — sous Python >= 3.12, un client qui ne lisait plus gardait le serveur vivant
  (borg déjà arrêté) jusqu'au SIGKILL (mesuré).
- `_borg_stream` : tube stderr de borg fermé à la fin de sa lecture (avant : par le ramasse-miettes, ResourceWarning) ;
  `_restore_where` : itérateur `os.scandir` fermé.
- Selftest : `_flat_routes` récursif (fastapi 0.142 garde un `_IncludedRouter` paresseux dans `app.routes` : 11 routes vues au lieu
  de 40+, deux contrôles faussement en échec) ; TestClient en `raise_server_exceptions=False` (une exception du serveur devient
  l'échec du contrôle, jamais l'arrêt du selftest) ; nouveaux contrôles « lifespan : le watcher démarre au démarrage du serveur et
  s'arrête à l'arrêt, sans on_event » (piloté par le protocole ASGI lifespan, TestClient en contexte ; garde de structure : ni `on_event`, ni `add_event_handler`, ni `on_startup`/`on_shutdown`)
  et « FastAPI : corps JSON sans Content-Type accepté, télémétrie coupée » ; contrôle d'arrêt étendu (signal reçu verrous tenus,
  signaux capturés vidés, connexions coupées au second signal seulement).
- Push selftest 127/127 sous Python 3.10 (fastapi 0.63) et 3.14 en avertissements stricts (fastapi 0.142). Mesuré, serveurs réels
  sous les deux piles (`work/m57/mesure57*.log`) : watcher démarré par le lifespan, `/healthz`, `/api/report?offline`, `/api/access`
  à 200 ; SIGTERM ou SIGINT au repos : code 0 ; téléchargement en cours (client qui ne lit plus) : second SIGTERM -> sortie en
  0,2 s, borg arrêté (3.14 avant ce correctif : aucune sortie en 30 s) ; `uvicorn borgHelperWWW:app --workers 2` : watcher par
  worker, SIGTERM -> code 0. Sous uvicorn externe 0.54 (Python 3.14), un client qui ne lit plus garde le serveur et son borg
  vivants malgré deux SIGTERM puis deux SIGINT ; au SIGKILL du serveur, borg meurt avec lui (tube fermé) — documenté (README).
- Restent (bibliothèque ou selftest, non bloquant) : `StarletteDeprecationWarning` du TestClient avec httpx ; `ResourceWarning` de
  fichiers ouverts par des contrôles du selftest (tous alloués dans `push_selftest`, tracemalloc) ; `CancelledError` au journal
  d'uvicorn lors d'un arrêt forcé.
- Outillage (hors git) : `tools/make_pyvenvs.sh` installe et vérifie la pile de borgHelperWWW dans `venv-3.14` (`PKGS_WWW`).
- Séries de mutations (push selftest, source finale, lignes entières ; journaux vérifiés : chaque échec sur l'assertion de sa pièce) :
  sous Python 3.14 strict (fastapi 0.142) 18/18 DÉTECTÉES — lifespan (non posé, sans démarrage, sans arrêt), second signal sans arrêt
  forcé, pydantic 1 seul (`.dict`, `__fields_set__`), routes incluses ignorées, verrous non réentrants (2), signaux capturés gardés,
  connexions jamais coupées / coupure jamais planifiée / coupées dès le 1er signal, boucle du serveur non retenue, options de
  compatibilité non passées, télémétrie gardée, `strict_content_type` gardé, stderr de borg jamais fermé ; miroir sous Python 3.10
  (fastapi 0.63) 14 DÉTECTÉES dont pydantic 2 seul (`model_dump`, `model_fields_set`), routes directes ignorées, `on_event` remis,
  8 SURVIT — les pièces sans objet sous cette pile (arrêt forcé et signaux d'uvicorn 0.54, branches pydantic 1 et `_IncludedRouter`,
  options de fastapi 0.142).

## borgHelperWWW 1.31.3 — Cache /report?offline : empreinte avec roster et marqueurs — 2026-10-06

Chantier « reconstruction progressive », story 56 (rétrospective A113 ; décision de l'utilisateur). Avant : `/report?offline=true`
était resservi depuis `_RESPONSE_CACHE` jusqu'à 5 min tant que les bases ne changeaient pas ; « ⏳ Bkp en cours / en attente de
l'Index / interrompu, borg create encore actif » vient des marqueurs de Bkp et du `lock.roster` du dépôt, hors empreinte — un Bkp
qui démarre (marqueur avant sa ligne), un borgHelper tué, un borg orphelin qui finit restaient invisibles jusqu'à 5 min.

- `_external_fingerprint('report', …)` ajoute `_bkp_markers_state()` (tous les marqueurs de Bkp de `CACHE_DIR`, voisin compris —
  décision de l'utilisateur —, « nom:porteur » par `_lock_holder`, porteur zombie compté à part, `.tmp` d'écriture ignorés, lecture
  seule) et `_repo_roster_state(nick)` (détenteurs exclusifs du `lock.roster` du dépôt local, « pid:vivant », zombie = mort ; sonde
  bornée à 1 s ; montage figé : dernier état lu, réponse en cache gardée). Mêmes empreintes à la lecture et à l'écriture (une
  réponse dont l'empreinte change pendant l'exécution n'est jamais rangée, comme avant).
- Sondes de présence et du roster : `_bounded_probe` — une seule en vol par nick, inscrite sous verrou (avant : lue puis inscrite
  sans verrou, des requêtes concurrentes en lançaient chacune une), une requête concurrente attend la même.
- Inchangés : borgHelper, diffbkp et les autres routes, durée de vie de 5 min (« depuis … » peut retarder de 5 min, comme avant).
- Contrôle du push selftest « cache Report -o : marqueurs de Bkp et lock.roster dans l'empreinte, … (story 56, A113) » (13 cas) :
  marqueur posé, marqueur d'un voisin, porteur mort (marqueur gardé) ou zombie, détenteur du roster ajouté, mort ou zombie ->
  exécuté ; sinon resservi ; `.tmp` ignoré ; roster figé : ~1 s, dernier état lu, réponse en cache gardée, une sonde ; résultat
  tardif adopté ; requêtes concurrentes : une lecture, sa vraie valeur rendue à toutes ; diffbkp sans marqueurs ni roster. Push selftest 125/125.
- Revue (3 relecteurs, `work/rev56/`) : montage figé qui invalidait le cache (`?`) au lieu de le garder ; zombie d'un Bkp lancé par
  POST /bkp compté vivant ; sondes concurrentes sans verrou (aussi la présence, préexistant) ; `.tmp` dans l'empreinte ; `KeyError`
  du contrôle qui masquait trois détections ; mesure sans appel servi par le cache — corrigés.
- Mesuré (borg 1.2.6, trois serveurs de test sur le même rc de démo : 1.31.3, 1.31.2, et 1.31.3 sans roster ; appels répétés,
  « servi par le cache » = ~5 ms ; `work/m56/mesure56b.log`) : Bkp en attente de l'Index (Index réel suspendu) -> 1.31.3 le dit
  aussitôt, 1.31.2 resservait sa réponse sans mention ; borgHelper tué -> 1.31.3 « interrompu, borg create encore actif » au
  premier appel (puis servi par le cache), 1.31.2 « en cours » ; orphelin fini -> seul 1.31.3 à jour, le témoin sans roster
  resservait « interrompu » (la part roster est nécessaire). Première mesure (`mesure56.log`) : aucun appel servi par le cache,
  non discriminante (revue) ; `mesure56b-1.log` : script qui attendait l'Index avant le create (états 1-3 manqués).
- Séries de mutations (pré-vérifiées, push selftest complet sous le Python système — fastapi —, avertissements stricts) : avant
  revue 8/8 (trois détectées par un `KeyError` du contrôle, pas par l'assertion visée — revue), après revue 16/16 DÉTECTÉES —
  Report -o sans marqueurs ni roster, marqueurs retirés, porteur ignoré, roster retiré, vie des détenteurs ignorée, sonde sans
  délai, sonde figée jamais marquée, diffbkp avec marqueurs et roster, WWW qui retire les marqueurs morts, porteur ou détenteur
  zombie compté vivant, `.tmp` dans l'empreinte, roster figé rendu `?`, dernier état jamais gardé, sonde non inscrite, sonde en
  vol rendue figée (a d'abord survécu : le contrôle concurrent ne vérifiait pas la valeur rendue — renforcé).

## borgHelper 1.0.186 — Status aligné sur le marqueur et l'orphelin — 2026-10-05

Chantier « reconstruction progressive », story 55 (rétrospective A112 ; décisions de l'utilisateur au checkpoint et en revue).
Avant : `Status` disait « Bkp en cours depuis … » pour toute ligne `bkp_status` ouverte non périmée — pour un Bkp tué, Report
disait « Bkp interrompu, borg create encore actif » ou rien, Status « en cours ».

- `status()` lit l'état du Bkp par `_bkp_live(nick, quiet=True, strict=True)`, la source de Report (marqueur de Bkp, borg create
  orphelin) : Bkp vivant « Bkp en cours depuis X » (inchangé) ; marqueur sans ligne « Bkp en attente de l'Index depuis X » ;
  orphelin « Bkp interrompu (borgHelper arrêté), borg create encore actif depuis X » ; ligne ouverte non périmée sans rien de
  vivant « Bkp interrompu depuis X — aucun processus ; fermé au prochain Index si son archive existe » — dépôt distant, où un
  orphelin ne se voit pas : « — borgHelper arrêté, borg non vérifiable (dépôt distant) ; … » ; ligne périmée : inchangé
  (`bkp_stale`, « probablement interrompu »). Ligne d'un autre run que le Bkp vivant ou en attente : dite aussi. Lecture
  impossible : rien sur le Bkp. Comme Report, Status retire les marqueurs de processus morts.
- JSON : `bkp_running` = `{started_at, en_attente, orphelin}` (avant `{started_at}`) ; nouvelle clé `bkp_interrupted`
  `{started_at, verifie}` (`verifie` : `false` pour un dépôt distant ; `null` dans le résultat d'erreur d'un nick).
- « Opération prioritaire en cours » : cachée sous un Bkp vivant ou en attente seulement (un orphelin ne tient plus
  `priority.lock`) ; variante « Bkp peut-être toujours actif » aussi sous un Bkp interrompu non vérifiable.
- `_status_one(nick)` par défaut (`bkp_live=False`) : base seule, comme avant — borgHelperWWW /access (qui n'en garde que
  build/rebuild, sondé toutes les 30 s) ne lit ni marqueurs ni `lock.roster`. Nouveaux : `BorgHelperDB.repo_orphan_checkable`,
  `_repo_local_path` (prédicat partagé avec `repo_lock_holders`).
- Inchangés : Report, `bkp_running_state` (/access et ⏳ de l'UI, alerte de retard : base seule — hors story, décision de
  l'utilisateur), borgHelperWWW.
- Mesuré (vrai borg 1.2.6, `work/m55/mesure55b.log`) : Bkp vivant, tué avec borg suspendu — Status (texte et JSON) dit ce que dit
  Report ; tué borg fini — Status « interrompu, aucun processus » (Report : rien) ; après le rapprochement de l'Index (1.0.185),
  plus rien.
- Contrôle « Status aligné sur Report : … (1.0.186) » (12 nicks, borg compté) ; contrôles Status existants revus : leurs
  « Bkp en cours » n'avaient pas de marqueur (décor fictif) — marqueur vivant ajouté ; factice de `_status_one` à la nouvelle
  signature.
- Revue (3 relecteurs, `work/rev55/`) : /access payait marqueurs et `lock.roster` à chaque sondage ; « aucun processus » affirmé
  pour un dépôt distant (décision : « non vérifiable ») ; ligne d'un autre run masquée (décision : les deux) ; lecture en
  échec prise pour « interrompu » ; doc périmée (README, « lecture seule ») — corrigés.
- Séries de mutations (pré-vérifiées, Python 3.14 strict) : avant revue 10/10, après revue 22/22 DÉTECTÉES — marqueur et orphelin
  ignorés, lecture impossible prise pour « rien de vivant » (deux sites), ligne d'un autre run masquée, Bkp interrompu jamais
  dit, `bkp_live` ignoré, /access payant `_bkp_live`, `status()` sans `bkp_live`, drapeaux faux, `verifie` toujours vrai,
  `SSH_REPO`/`SSH_REMFO` comptés locaux, orphelin/attente dits « en cours », distant dit « aucun processus », interrompu muet,
  opération prioritaire cachée sous un orphelin ou dite sous un Bkp vivant, variante « peut-être » absente sous un distant,
  résultat d'erreur sans `bkp_interrupted`, ligne stderr de Report dans Status. (M13 « `:` retiré » a d'abord survécu :
  `hôte:chemin` n'est pas absolu, la garde `isabs` suffit — remplacé par le décor `SSH_REPO`.)

## borgHelper 1.0.185 — Bkp tué dont le borg a fini : ligne fermée et Index — 2026-10-05

Chantier « reconstruction progressive », story 54 (rétrospective F299, A111 ; décisions de l'utilisateur). Observé avant
(`work/m50/retro52.log`) : borgHelper tué pendant un Bkp, son `borg create` finit et écrit l'archive, mais la ligne `bkp_status`
du Bkp reste ouverte — le Bkp suivant affiche « Bkp précédent en erreur » (`***`, code 1) et, au bout de `BKP_STATUS_TIMEOUT`,
le watcher de borgHelperWWW notifie un échec et alerte Sentry alors que l'archive est complète.

- **L'archive porte son run** : `backup()` passe `--comment "borgHelper run <run_id>"` à `borg create` (visible dans `borg
  list`/`borg info` ; archives écrites à partir de 1.0.185 ; avec `SSH_REMFO`, cité pour le shell distant).
- **Rapprochement** (`BorgHelper._reconcile_killed_bkp`) une fois par Index (après la garde « dépôt absent » ; son `borg list` cède
  à une opération prioritaire ou à l'échéance comme les autres : reprise après la pause, ou fin de tranche muette) et au début de
  chaque Bkp (après l'attente d'Index, avant sa propre ligne) : ligne OUVERTE du nick (sans fin, et aucun Bkp démarré après elle
  n'a réussi — décision de l'utilisateur en revue, borne le coût), sans marqueur de Bkp vivant (celui du processus courant compté
  vivant), sans `borg create` orphelin vivant de ce run (dépôt local) ; dépôt local présent ; s'il y en a, UN `borg list --json
  --format '{comment}{end}'` (`TZ=UTC` passé à borg : `end` lu en UTC, sans conversion ni heure ambiguë) ; la ligne dont l'archive
  (hors `.checkpoint`) porte « borgHelper run <run_id> » est fermée en succès (fin = fin de l'archive ; jamais d'écrasement).
  Ligne : `<nick> : Bkp interrompu <run_id 8 car.> rapproché — archive <nom> écrite, ligne fermée en succès` ; échec de borg :
  `[WARN] <nick> : rapprochement impossible (borg list : …) — réessayé au prochain Index`. Sans candidat : aucun borg. Erreur de
  base : rien fermé, jamais le Bkp ni l'Index interrompus (à la lecture : muet ; à la fermeture : message SQLite habituel, après
  l'attente d'une base verrouillée).
- Effets : le Bkp suivant voit un précédent réussi ; si un Index ou un Bkp du nick passe avant `BKP_STATUS_TIMEOUT`, le watcher
  notifie la fin en succès (plus d'échec ni d'alerte Sentry pour ce Bkp ; compteurs d'avertissements C/E inconnus, vides) — sinon
  l'échec déjà notifié reste (le watcher ne re-notifie pas, décision de l'utilisateur) et l'historique dit succès.
- Jamais rapprochés : Bkp vivant, orphelin qui tourne encore (dépôt local), archive sans ce commentaire (d'avant 1.0.185, `borg
  create` manuel, autre run, autre nick), `.checkpoint`, ligne dépassée par un Bkp réussi — y compris celle dont l'examen a échoué
  ou qui était écartée au début de ce Bkp (borg list en échec, orphelin alors vivant, Bkp `-I`) : le `[WARN]` « réessayé » ne vaut
  que tant qu'aucun Bkp ne réussit. Un orphelin vivant (dépôt distant, ou local avec une autre ligne candidate) fait échouer le
  `borg list` sur son verrou -> `[WARN]` à chaque Index jusqu'à sa fin.
- Coût : un `borg list` qui lit chaque archive du motif (mesuré en local : 0,82 s contre 0,63 s, 34 archives ; distant non mesuré),
  seulement tant qu'une ligne est candidate — au plus au début du Bkp suivant et dans son Index de fin, la ligne étant ensuite
  dépassée par ce Bkp s'il réussit.
- Mesuré après (vrai borg 1.2.6, `work/m50/mesure54c.log`, `BORG_EXE` qui journalise chaque appel) : borgHelper tué, orphelin
  suspendu -> `Index` sans aucun `borg list` du rapprochement, ligne intacte ; orphelin fini -> `Index` ferme la ligne en succès,
  fin = `end` UTC de borg ; idem sous un `TZ` étranger ; Bkp suivant : rapprochement à son début, Report pendant ce Bkp sans
  « précédent en erreur » ; ensuite plus aucune ligne ouverte, aucun `borg list` du rapprochement. La première mesure
  (`mesure54-1.log`) a montré l'Index de fin d'un Bkp rapprochant sa PROPRE ligne (marqueur du processus courant non compté
  vivant) : corrigé.
- Contrôle « Bkp tué dont le borg a fini : ligne rapprochée en succès … » (22 nicks, borg list simulé, marqueurs à la main ; fins
  distinctes par archive ; `_index_pass` exécuté avec un faux borg qui obéit à son arrêt : interrompu, reprise, une fois par Index,
  échéance ; `backup()` local, `SSH_REMFO`, Ctrl-C pendant son `borg list` : 130, aucun create, `priority.lock` et marqueur retirés).
- Revue 1 (3 relecteurs, `work/rev54/`) : commentaire coupé en trois mots par le shell distant avec `SSH_REMFO` (tous ces Bkp
  cassés) ; lignes jamais rapprochables relançant un `borg list` à chaque Index ; `borg list` du rapprochement sans arrêt
  prioritaire et avant la garde « dépôt absent » ; fuseau de borg non transmis ; erreur de base à la fermeture qui pouvait tuer le
  Bkp ; promesse du watcher sans condition — corrigés. Revue 2 (`work/rev54b/`) : `TZ` vide ou heure ambiguë (-> `TZ=UTC`) ;
  tranche dont le rapprochement atteint l'échéance : faux `[WARN]` sur le `borg list` initial ; dépôt absent au début d'un Bkp ;
  checkpoint de borg 1.1 ; une erreur sur un candidat abandonnait les suivants ; preuves par structure seule — corrigés.
MUTATIONS54

## borgHelper 1.0.184 — Report pendant un borg orphelin : base et mention — 2026-10-05

Chantier « reconstruction progressive », story 52 (rétrospective F291, A109 ; décisions de l'utilisateur au checkpoint).
Mesuré avant sur un vrai Bkp de `demo.borghelperrc` (sans `BORG_EXE`) : borgHelper tué par SIGKILL pendant `borg create`,
son borg survit (parent 1), garde le verrou du dépôt et va au bout (archive écrite après le kill) ; pendant ce temps `Report`
en ligne -> `*** ERREUR … Failed to create/acquire the lock`, code 2 ; `-o` -> code 0, rien sur le Bkp.

- **Lien au Bkp exact, mort prouvée** : `backup()` passe à son seul `borg create` `BORGHELPER_BKP_RUN=<run_id>` (sa ligne
  `bkp_status`) et `BORGHELPER_BKP_PID=<pid>:<début>` (son propre processus). Détection (`BorgHelperDB.repo_lock_holders`,
  `repo_orphan_create(nick)`, `bkp_status_open`) : détenteur exclusif du `lock.roster` du dépôt local, vivant, première
  sous-commande borg de son argv = `create`, les deux variables dans `/proc/<pid>/environ`, le processus `BORGHELPER_BKP_PID` mort
  (PID réattribué compris) ; puis la ligne de CE `run_id` du nick, ouverte et non périmée (pas la plus récente : un Bkp suivant
  tué avant son create ne masque rien). Jamais : `borg create` lancé à la main, par cron ou par borgmatic (sans ces variables),
  un Bkp vivant même sans marqueur (son borgHelper vit), un autre Bkp ou un autre nick (ligne absente), un borg d'Index, de
  Restore, de Prune (autre sous-commande). Revues : la première version (« aucun ancêtre nommé borgHelper » + nom d'hôte)
  prenait un `create` manuel pour l'orphelin et l'attribuait au premier nick du dépôt à ligne ouverte ; la deuxième déduisait
  la mort de borgHelper de l'absence de marqueur (marqueur non écrit : faux « arrêté »).
- **Report, en ligne comme `-o`** : nick tiré de la base, sans borg ; `reste` suffixé `— ⏳ Bkp interrompu, borg create encore
  actif depuis HH:MM (XhYYmin)` ; stderr `<nick> : Bkp interrompu (borgHelper arrêté), borg create encore actif depuis … —
  rapport tiré de la base, borg non interrogé` ; JSON `bkp_en_cours.orphelin: true` (`false` dans les autres cas, aussi dans
  `bkp_voisin`) ; nick `***`, **code 1** (le Bkp est déjà en échec pour borgHelper).
- **Nick voisin** (même `BORG_REPO`) : tiré de la base, `— ⏳ Bkp de A interrompu, borg create encore actif sur le dépôt depuis
  …`, `bkp_voisin.orphelin: true`, sans alerte de ce fait.
- Sans détenteur dans le roster du dépôt local, ni délai rc (`BKP_STATUS_TIMEOUT`) ni base ne sont lus (le rc l'est, pour le
  chemin du dépôt) : Report inchangé hors Bkp.
- Changement de code : `Report -o` pendant un tel orphelin passe de 0 (rien sur le Bkp) à 1 (décision de l'utilisateur).
- Limites (comportement d'avant, sans détection) : Bkp lancé par borgHelper < 1.0.184 ; environnement du borg illisible (Report
  sous un autre compte, `/proc` en `hidepid`) ou vidé par `BORG_EXE` (`sudo`, `env -i`) ; dépôt non local au sens de borgHelper
  (`:`, `{…}`, chemin relatif, `~`, `file://`, `SSH_REPO`, `SSH_REMFO`) ; borg 2 (pas de `lock.roster`) ; ligne au-delà de
  `BKP_STATUS_TIMEOUT`. Après la fin de l'orphelin, son archive existe mais la ligne `bkp_status` reste ouverte et l'Index n'est
  pas fait : le Bkp suivant voit un « Bkp précédent en erreur » (règle de la story 50). Status dit encore « Bkp en cours ».
  borgHelperWWW garde `/report?offline=true` 5 min (empreinte : bases seulement) — mention présente ou absente jusqu'à 5 min de
  trop au début et à la fin de l'orphelin.
- Mesuré après (vrai borg 1.2.6, borgHelper tué pendant `borg create`, borg gelé par SIGSTOP pour tenir le verrou) : texte,
  `-j`, `-l`, `-o`, `-o -j` -> code 1 avec la mention, aucune erreur de verrou ; nick voisin -> mention et `bkp_voisin` ; une fois
  l'orphelin fini (SIGCONT) -> code 0, comportement normal. Contrôle « Report pendant un borg orphelin » (20 nicks, faux
  `borg.wrapped` lancés par double fork avec ou sans les variables, borgHelper mort ou vivant, roster écrit à la main, argv réel
  PyInstaller simulé ; jumelles ; `backup()` par le vrai `boex` avec un `BORG_EXE` qui enregistre son environnement) ;
  14 mutations détectées.

## borgHelper 1.0.183 — Report pendant un Bkp : pas d'erreur, Bkp en cours dit, historique rendu — 2026-10-05

Chantier « reconstruction progressive », story 50 (demande de l'utilisateur du 2026-10-04 ; décisions de l'utilisateur au
checkpoint et après les deux revues). Mesuré avant sur un vrai Bkp de `demo.borghelperrc` (verrou du dépôt tenu 45 s) : Report
en ligne (texte, `-j`, `-l`) -> `borg info` en échec sur `lock.exclusive (timeout)`, ligne `*** ERREUR demo-modules`, code 2
(HTTP 400 par `/report` de borgHelperWWW), aucun historique ; `-o` -> code 0 mais rien sur le Bkp.

- **Marqueur de Bkp** : `backup()` pose `<prefix>-<nick>-bkp.lock.<run_id>` (son PID, écriture atomique) dans `CACHE_DIR`
  AVANT le verrou de priorité et le retire à sa toute fin (Index de fin compris, aussi après une exception). Bkp VIVANT =
  marqueur vivant (PID vivant, non repris) ET sa ligne `bkp_status` ouverte, plus récente que `BKP_STATUS_TIMEOUT` — ou pas
  encore de ligne : **Bkp en attente de l'Index** (le Bkp attend qu'un Index extérieur se mette en pause, jusqu'à 120 s).
  Un marqueur mort (Bkp tué) est retiré par le Report suivant. Seul le processus du Bkp compte : un Index extérieur repris
  après un Bkp tué, un Restore ou un Prune ne le fait jamais passer pour vivant.
- **Report, en ligne comme `-o`** : un nick dont le Bkp est vivant est tiré de la base (`prep_report_from_db`), sans borg ni
  attente du verrou d'Index ; colonne `reste` gardée (espace libre, `⚠ dépôt absent`) et suffixée `— ⏳ Bkp en cours depuis
  HH:MM (XhYYmin)` (`— ⏳ Bkp en attente de l'Index depuis …` avant la ligne) ; JSON : champ `bkp_en_cours` (`started_at` en
  UTC `…Z`, `depuis`, `precedent_en_erreur`, `en_attente`) ; stderr : `<nick> : Bkp en cours depuis … — rapport tiré de la
  base, borg non interrogé`.
- **Nick voisin** (même `BORG_REPO`) : pendant le Bkp vivant de A, le Report de B est aussi tiré de la base (borg info
  buterait sur le verrou du dépôt) : `reste` suffixé `— ⏳ Bkp de A en cours sur le dépôt depuis …`, JSON `bkp_voisin`
  (`nick`, `started_at`, `depuis`, `en_attente`), stderr `B : Bkp de A en cours sur le même dépôt depuis … — rapport tiré de
  la base, borg non interrogé` ; code selon les règles habituelles de B.
- **Erreur seulement si le Bkp précédent manque ou a échoué** : Bkp précédent (dernier démarré AVANT celui en cours ; en
  attente : dernière ligne du nick) fini en `error` — un Bkp concurrent refusé sur le verrou du dépôt compris — ou jamais
  fini et sans marqueur vivant (tué) -> `… — Bkp précédent en erreur`, nick `***`, code 1 ; un précédent jamais fini dont le
  marqueur vit encore (Bkp concurrent en cours) n'est pas en erreur. Dernière archive au-delà de `MAX_AGE_BKP`, aucune
  archive -> code 1 ; dépôt absent, base illisible -> code 2 (avec la mention) ; sinon code 0.
- Inchangé : Bkp tué, ligne au-delà de `BKP_STATUS_TIMEOUT` (même processus vivant : un Bkp plus long que ce délai retombe
  sur borg), Restore/Prune/DelBkp en cours ; sans marqueur, ni le rc (`BKP_STATUS_TIMEOUT`) ni `history.db` ne sont lus.
- Limites : marqueur illisible (`/proc` monté `hidepid`, autre compte) : `_lock_holder` le tient pour vivant ; écriture de
  la ligne `bkp_status` en échec : Bkp vu « en attente de l'Index » jusqu'à sa fin. borgHelperWWW (inchangé) garde
  `/report?offline=true` 5 min : son empreinte couvre `history.db`, donc le début du Bkp (ligne écrite) renouvelle la réponse ;
  après un Bkp tué, pendant l'attente de l'Index et pour un nick voisin, la mention peut apparaître ou rester jusqu'à 5 min
  en retard.
- Contrôle : « Report pendant un Bkp vivant » (18 nicks, marqueurs au PID d'un enfant `sleep` vivant ou d'un processus
  fini, verrous d'autres processus, attente de l'Index, voisin, précédent vivant/tué/en erreur de même `started_at`, base
  corrompue, schéma plus récent ; borg piégé ; matrice jouée sur `report` et `report_offline` ; texte, JSON exact, HTML,
  multi-nicks ; `backup()` réel à borg simulé : marqueur posé avant l'attente, retiré après un create planté).
- Mesuré après sur de vrais Bkp de `demo.borghelperrc` (copie du rc ; wrapper `BORG_EXE` qui tient le verrou du dépôt 20 s
  pendant create et retarde le diff de l'Index de fin) : texte, `-j`, `-l`, `-o`, `-o -j` en code 0 avec la mention, 0,5 à
  1 s, pendant l'attente de l'Index, `borg create` et l'Index de fin ; 100 Reports en boucle du début à la fin du Bkp (Index
  de fin qui écrit compris) : aucun code non nul ; nick voisin : `Bkp de demo-modules en cours sur le dépôt`, son propre
  code (1 : jamais indexé) ; aucun marqueur restant. 31 mutations détectées.

## borgHelper 1.0.182 — Python 3.10 à 3.14 sans plantage ni avertissement — 2026-10-04

Chantier « reconstruction progressive », story 48 (demande de l'utilisateur : avertissement sqlite3 sur un hôte, puis exigence
« tourner de Python 3.10 à 3.14 sans plantage »). Mesuré par un CodecSelfTest complet sous chaque version — 3.10.12 système
(SQLite 3.37.2, sentry-sdk 1.4.3), 3.11.15, 3.12.13, 3.13.13, 3.14.5 (SQLite 3.50.4, sentry-sdk 2.71.0) — avec les dépréciations
attribuées au code de borgHelper levées en erreur dans les CLI que lancent les contrôles, et affichées par le processus du selftest.

- **sqlite3** : `_known_archives` (rapprochement AD-9) passait `?1` avec une séquence — `DeprecationWarning` sous des Python 3.12
  (« Binding 1 ('?1') is a named parameter… »). Marqueurs `?` anonymes et `(nick, nick)` : même requête, même résultat.
- **Sentry facultatif, jamais de plantage** : DSN vide ou absent -> `sentry_sdk` n'est plus importé. Sentry inutilisable -> un
  seul `[WARN] Sentry désactivé : <cause> — erreurs et alertes non envoyées` par processus, la commande continue normalement :
  `module sentry_sdk absent (DSN configuré)` (avant : plantage au démarrage de toute commande) ; `initialisation impossible
  (BadDsn)` pour un DSN invalide (avant : plantage, mesuré sous sentry-sdk 1.4.3 et 2.71) ; `import de sentry_sdk impossible
  (dépendance urllib3 absente)` ou `(<type>)` pour une installation cassée ; `fichier DSN illisible (UnicodeDecodeError)` pour un
  fichier DSN non UTF-8 (avant : plantage). Une alerte `SENTRY_ALERTS` dans ces cas : plus aucun avertissement par alerte, et
  jamais « envoyée ». Lancée par borgHelperWWW, la CLI se tait (décision de l'utilisateur) : rien dans le stderr que l'API
  relaie ; le serveur le dit une fois dans son journal, à sa première alerte. La CLI reconnaît WWW à `BORGHELPERC_NO_CLEANUP_NOTICE=1`
  (posée par le serveur sur chacun de ses appels) ou `BORGHELPER_VIA=http` — posée à la main, cette variable coupe donc aussi ce
  `[WARN]`. sentry-sdk 2.x pris par son API (`get_client`, `new_scope`) : plus d'avertissement `Hub`/`push_scope` ; 1.x
  inchangé (vérifié avec 1.4.3 sous 3.10 seulement).
- **Avertissements Python** : `datetime.utcnow()` (déprécié 3.12) et `PurePath.as_uri()` (3.14) remplacés.
- **Connexions SQLite fermées** : depuis Python 3.11, une connexion non fermée reste ouverte jusqu'au ramasse-miettes. Une base
  recréée pendant qu'un autre processus la tenait laissait ainsi la relance échouer (« disk I/O error ») dans le même processus :
  toute sortie en erreur d'`ensure_diff_db`/`ensure_cache_db` ferme sa connexion (schéma trop récent, clé, Ctrl-C compris). Un
  nick en erreur dans un Bkp, un Index, un Report (en ligne ou hors ligne) ou un lecteur multi-nicks libère ses connexions
  orphelines avant le nick suivant (et en fin de boucle) — hors du bloc `except`, où la trace les retient encore, et après avoir
  effacé les variables des cadres de l'exception, que Sentry garde (DedupeIntegration) une fois envoyée (mesuré).
- Contrôles : garde AST (SQL en `?` ; ni `utcnow()`, ni `utcfromtimestamp()`, ni `PurePath.as_uri()` ; `ensure_*` qui ferment ;
  libérations placées hors des `except` et réellement atteignables) ; `sentry_sdk` absent (CLI réelle) ; Sentry inutilisable
  (alerte sans module, DSN invalide, import cassé, dépendance absente, fichier DSN illisible, silence sous WWW, marqueur posé par
  la source de borgHelperWWW) ; `_utcnow_naive` contre un oracle indépendant, fuseau forcé à UTC+5 ; connexion orpheline libérée,
  par comportement, pour `_PerNick` et pour l'Index et le Bkp multi-nicks avec un Sentry qui garde l'exception ; `sentry_alert`
  par un transport factice en classe (le transport en fonction est déprécié en sentry-sdk 2.x), sauté (SKIP) si le module manque ;
  contrôle `_vacuum_wal` corrigé pour 3.11+ (il laissait sa propre connexion ouverte).
- Limites : Python 3.8/3.9 non vérifiés, ni les 3.12 antérieures à 3.12.13 (seules à avertir sur `?1` : garde AST seulement) ;
  `ResourceWarning` (connexion fermée implicitement, émis depuis 3.13, masqué par défaut), dépréciations attribuées aux
  bibliothèques, code de borgHelper importé sous un autre nom (borgHelperWWW, bibliothèque) et dépréciation levée dans un enfant
  puis avalée par un `except` large : non couverts — audit des 55 ouvertures sans fermeture garantie reporté.

## borgHelper 1.0.181 — borg diff lancé pendant l'arrêt de l'Index : sortie lue pendant l'attente — 2026-10-03

Chantier « reconstruction progressive », story 44 (actions de rétrospective A96, A97 ; regroupement demandé par l'utilisateur).

- **Index : un borg diff lancé alors que l'arrêt était déjà demandé sort proprement** (mesuré sur 1.0.180, vrai borg 1.2.6,
  `borg diff --json-lines` de 5,9 Mo) : sa sortie n'était pas lue pendant les 5 s d'attente — SIGTERM reçu après 0,5 s ou plus,
  tube plein, borg ne pouvait pas sortir et finissait au SIGKILL (verrou de dépôt non rendu proprement) ; elle est désormais
  vidée (et jetée) pendant l'attente, comme boex le fait déjà : sortie propre en 0,13 s (code 143). borgHelper retire aussi
  les `_MEI*` de ce borg (mesuré : un borg tué au démarrage en laisse un, ~60 Mo).
- **Un borg diff tué au SIGKILL par l'Index est dit** (décision de l'utilisateur) : `[WARN] <nick>: borg diff <a> → <b> arrêté
  par SIGKILL — verrou de dépôt possiblement resté`, une ligne par borg réellement tué (borg lui-même, pas un simple
  descendant ; décidé après le signal), qu'il ait été arrêté par le moniteur (échéance, priorité) ou lancé pendant l'arrêt —
  chaque borg n'est pris que par un seul des deux chemins (jamais deux lignes) ; code de sortie de l'Index inchangé ; ces
  lignes ne remplacent jamais la raison de l'arrêt dans le dernier Index (`/access`, Status). Avant : silencieux. En pratique ce SIGTERM part juste après le
  lancement (sortie immédiate, mesuré à 0,03 s) : seul un arrêt retardé (charge) était touché.
- CodecSelfTest : faux borg à la structure du vrai (SIGTERM -> exception, nettoyage qui écrit encore sur stdout : bloqué tant
  que le tube est plein ; témoin sans vidage bloqué), sortie propre, borg sourd tué, `_MEI*` tenu ouvert retiré, jeu partagé
  modifié pendant la purge ; SIGKILL dit (tête vivante) et jamais dit (borg sorti au SIGTERM, seul un descendant tué) ;
  dernier Index non masqué ; garde AST de structure de `_run_diff` (inscription et décision sous verrou, exclusivité avec
  le moniteur, arrêt avant la lecture, avertissement sous le code de borg).
- Outillage hors dépôt (A96) : serveurs borgHelperWWW de mesure lancés, suivis par leur port et arrêtés avec vérification.

## borgHelper 1.0.180 / borgHelperWWW 1.31.2 — SIGKILL du groupe garanti, arrêts qui attendent l'arbre de borg — 2026-10-03

Chantier « reconstruction progressive », story 43 (actions de rétrospective A93 à A95 ; regroupement demandé par l'utilisateur).

- **borgHelperWWW : SIGKILL du groupe garanti** (défaut de 1.31.1 mesuré sur serveur réel : au délai, borgHelper mourait au
  SIGTERM, ses tubes se fermaient et le SIGKILL n'était jamais envoyé — un enfant de borg qui ignore SIGTERM restait orphelin).
  La fin d'un arrêt est désormais le groupe vide : au délai, SIGTERM, 10 s au plus, SIGKILL des restes, puis 504 (en
  général 10 s plus tard qu'avant dans ce cas, 30 s au plus ; un groupe qui sort au SIGTERM répond toujours aussitôt).
  borgHelper qui sort sans délai atteint (tué de l'extérieur, OOM, 1er signal d'arrêt du serveur) en laissant son borg :
  restes arrêtés de même (SIGTERM, 10 s, SIGKILL), ligne `[WARN]` au journal, puis réponse (décision de l'utilisateur). Le
  2e signal d'arrêt du serveur atteint les groupes encore peuplés. /proc illisible : jamais pris pour « groupe vide ».
- **borgHelper : chaque arrêt attend l'arbre de borg**, plus la fin de sa tête ni de ses tubes : boex arrêté (arrêt demandé,
  Ctrl-C), Index (échéance, priorité ; aussi l'arbre d'un borg diff déjà récolté, et l'Index attend désormais la fin du
  SIGKILL avant de rendre la main ; une tranche peut dépasser son budget d'environ 20 s au plus) — un enfant sans tubes qui
  restait vivant est attendu 5 s puis tué, et l'arbre est attendu après chaque SIGKILL avant de retirer ses `_MEI*`. Vrai
  borg (`with-lock … sleep`, mesuré) : arrêt en 0,1 s, inchangé. Version du borg serveur sans réponse : seuls les `_MEI*` de
  CE borg sont retirés — mappés, ouverts ou dossier courant (un chargeur tué pendant son extraction ne mappe rien) ; avant :
  listing de /tmp, qui pouvait viser l'extraction d'un autre borg.
- CodecSelfTest : borg dont la tête sort au SIGTERM et dont l'enfant sans tubes reste (boex, Index, délai de grâce ≥ 4 s) ;
  petit-enfant né au SIGTERM dont le parent sort ; version muette qui mappe ou tient ouvert un `_MEI*` (voisin né pendant
  l'appel intact) ; /proc illisible ; garde AST « chaque SIGKILL suivi d'une attente de l'arbre ou du groupe ». push_selftest : délai, `_latest_archive`, borgHelper qui sort en laissant son borg, arrêt du serveur — à la
  structure réelle borgHelper -> borg -> enfant (tubes de l'enfant vers borgHelper ; l'ancien contrôle donnait à l'enfant
  les tubes du serveur et cachait le défaut), tubes du serveur tenus par l'enfant (vrai `borg list`), chemins rapides.

## borgHelper 1.0.179 / borgHelperWWW 1.31.1 — Index vide en avertissement, lecteurs sans résultat dits, borg arrêté par arbre de processus, erreurs avalées dites — 2026-10-03

Chantier « reconstruction progressive », story 42 (actions de rétrospective A89 à A92 ; regroupement demandé par l'utilisateur).

- **« Index vide » en `[WARN]`** (décision de l'utilisateur ; avant : marqué `[ERREUR]` en code 0) : nick jamais indexé ->
  `[WARN] Index vide pour X — lancez Index`, code 0, aux 7 sites (Search, FileHist, TreeHist, TreeFind, trois collecteurs de
  DuIdx) ; JSON inchangé (`{nick: {error}}`). borgHelperWWW met cette réponse en cache comme toute réponse saine : l'empreinte
  des bases change dès qu'un Index crée la base (mesuré) et suit désormais aussi leur journal `-wal`.
- **Lecteurs sans résultat après une erreur** (décision de l'utilisateur) : quand une lecture a échoué, Search dit « Aucun
  résultat dans les bases lisibles (erreurs ci-dessus). », FileHist « Aucune entrée pour : … dans les bases lisibles (erreurs
  ci-dessus). », DuIdx « Aucune donnée dans les bases lisibles (erreurs ci-dessus). » (`-j` : `{}` inchangé) ; sans erreur :
  messages d'avant.
- **borg arrêté par arbre de processus** (mesuré : le vrai borg = `exec nice borg.wrapped`, chargeur PyInstaller + enfant ;
  SIGKILL jamais relayé à l'enfant) : un Index qui arrête un borg diff (échéance de tranche, priorité) ou un borg arrêté sous
  boex (arrêt demandé, Ctrl-C) reçoit SIGTERM puis SIGKILL sur TOUT son arbre (enfants rattachés à init compris), lectures
  bornées — avant : un enfant qui ne sortait pas bloquait l'Index jusqu'à sa fin. Ctrl-C au terminal toujours propagé à borg
  (même groupe) ; `_MEI*` des borg tués retirés (relevés par leur mappage, jamais l'extraction d'un autre borg).
- **borgHelperWWW : délai = tout arrêter** (décision de l'utilisateur ; avant : `subprocess.run(timeout)` tuait borgHelper
  seul, son borg continuait orphelin, verrou de dépôt gardé) : commandes borgHelper et `borg list` de `/download/*` en session
  propre ; au délai SIGTERM au groupe, SIGKILL 10 s après, 504 inchangé — un `/restore` plus long que TIMEOUT est réellement
  arrêté (fichiers partiels). Arrêt du serveur : signal relayé aux commandes en cours (2e signal : SIGKILL).
- **Erreurs avalées dites** : RepoHistory/ArchiveHistory sur un dossier de cache non traversable -> erreur réelle et code 1,
  texte comme `-j` (avant : « diff.db absent » ou « disponible via -j », code 0) ; `_diff_stats_for_nick` ne rattrape plus
  que les erreurs SQLite (DbModeError, DbKeyError, DbTamperError remontent : ArchiveHistory en erreur) ; Report (et `-o`) :
  comptes illisibles -> ligne gardée, Modifs « — », `[ERREUR] <nick>: comptes de modifications illisibles — …`, code 1
  (décision de l'utilisateur).
- CodecSelfTest : « Index vide » [WARN] (Search, DuIdx `-f`/`-R -j`, FileHist, TreeHist, TreeFind), messages sans résultat,
  dossier non traversable (SKIP sous root), Report `_stats_error` (+ garde AST des jumelles live), borg dont l'enfant ignore
  SIGTERM et lance un petit-enfant (Index, boex arrêté, Ctrl-C), `_MEI*` mappé.
  push_selftest : délai (`_exec_borghelper`, `_latest_archive` réel, arrêt du serveur), cache « Index vide » et `-wal`,
  `_MEI*` d'un borg de téléchargement tué par le chien de garde.

## borgHelper 1.0.178 / borgHelperWWW 1.31.0 / UI 1.23.0 — HTTP/1.0 détecté, durée de borg bornée dans /download, code 1 des lecteurs en erreur, filtre -f exact — 2026-10-02

Chantier « reconstruction progressive », story 41 (actions de rétrospective A85 à A88 ; regroupement demandé par l'utilisateur).

- **Lecteurs en erreur : code 1** (décisions de l'utilisateur ; mesuré : code 0 même quand tous les nicks échouent). Search,
  FileHist, TreeHist, TreeFind, DuIdx, IdxTop, DiffTop, ArchiveHistory, RepoHistory, CacheInfo, LstBkp, LstBkpFls sortent en 1
  après une erreur SQLite réelle (base verrouillée au-delà du délai, page de données illisible), un nick arrêté parmi plusieurs
  (base occupée, passphrase absente…, décision de l'utilisateur ; avant : 0) ou un chemin illisible ; données des autres nicks
  gardées (CacheInfo isolé par nick comme les autres). En-tête de base altéré : `DbTamperError`, code 2 (inchangé) ; LstBkpFls
  sur un chemin illisible : 3 (inchangé). `[ERREUR] SQLite error` toujours sur stderr,
  `-j` compris (avant : JSON seul ; sept chemins d'erreur l'imprimaient sans marque). LstBkp/LstBkpFls : message au lieu d'une
  trace Python envoyée à Sentry. borgHelperWWW : `400` avec le JSON (inchangé) ; UI : l'explorateur montre l'erreur du nick, les
  graphiques restent dessinés avec « Données partielles : <erreur> » dessous ; CacheInfo n'affiche plus « Cache vide. » après une
  erreur. Status, Report, Bkp, Index, Prune, Restore, DiffBkp : codes inchangés.
- **`/download/*` : inactivité bornée** (décision de l'utilisateur : `BORGHELPERWWW_TIMEOUT`, 3600 s ; mesuré : borg muet
  bloquait un fil sans fin, client parti avant le premier octet = borg orphelin) : aucun octet lu pendant TIMEOUT s -> borg
  arrêté, `502` « aucune activité depuis N s » ou flux coupé. **borg arrêté par groupe de processus** (revue, mesuré : le vrai
  borg est un exécutable PyInstaller lancé par `exec nice …` — tuer le seul PID de tête laissait l'enfant vivant, tube ouvert ;
  touchait aussi l'abandon par le client de 1.30.2) ; dossiers `/tmp/_MEI*` du borg tué retirés. **Arrêt du serveur** (décision
  de l'utilisateur) : au premier signal, borg sans octet lu depuis 10 s arrêtés, puis tout borg qui le devient ; téléchargements
  sains servis jusqu'au bout ; second signal : tous (mesuré avant : uvicorn attendait sans limite, borg survivait au SIGKILL).
  `BORGHELPERWWW_TIMEOUT` négatif refusé au démarrage ; démarrage en échec (port pris) : code 3.
- **HTTP/1.0 détecté** (note de l'utilisateur, décision : signaler) : `[WARN]` au journal une fois par processus (chemin et
  client ; `/healthz` ignoré), `http_version` dans `/version` et `/access` (vu sous le préfixe d'API, comme `/download/*`), badge
  UI « ⚠ Proxy en HTTP/1.0 : téléchargement tronqué non détectable — proxy_http_version 1.1 ». Mesuré sur uvicorn direct (nginx
  absent du poste de test).
- **CodecSelfTest `-f '=<nom>'`** : nom exact, casse respectée, sans échappement (le filtre regex, insensible à la casse, ne
  pouvait pas isoler 10 contrôles) ; `-f` regex inchangé.
- Tests : CodecSelfTest — verrou exclusif réel (diff.db : Search texte/-j/multi, FileHist, TreeHist, TreeFind, DuIdx -R, IdxTop
  -j/multi, DiffTop, ArchiveHistory, LstBkp, LstBkpFls ; les `except` internes de Search/FileHist/TreeHist/TreeFind/DuIdx ;
  cache.db : CacheInfo ; history.db : RepoHistory, ArchiveHistory partielle), page corrompue (LstBkp, LstBkpFls), chemin
  illisible, nick isolé (IdxTop, CacheInfo), nick sans base et Status : 0 ; les 13 contrôles multi-nicks de la story 30 passent
  à « code 1 » ; `-f '=nom'` (noms qui ne diffèrent que par la casse). push_selftest — chien de garde (groupe tué derrière un
  script sans exec, corps jamais lu, registre vidé, lent mais actif après le 1er bloc, corps plus lu), arrêt (`handle_exit` :
  inactifs puis tous), `/version` complète, `/access` `http_version`. Test UI — graphiques en code 1, explorateur
  (`_readerJson`), badge HTTP/1.0 par `/version` et `/access`. Mutations : 43, toutes détectées. CodecSelfTest 573/573,
  push_selftest 121/121.

## borgHelper 1.0.177 / borgHelperWWW 1.30.2 / UI 1.22.1 — /download avec le code de borg, index_last aligné, lecteurs sans attente de 60 s — 2026-10-02

Chantier « reconstruction progressive », story 40 (actions de rétrospective A81 à A84 ; regroupement demandé par l'utilisateur).

- **borgHelperWWW `/download/file` et `/download/tar` lisent le code de borg** (décisions de l'utilisateur ; mesuré sur un vrai
  serveur : `200` pour borg en échec, borg tué, tar tronqué à 5 octets — le navigateur enregistrait un fichier faux). Échec ou
  borg tué avant le premier octet -> `502` « borg extract a échoué : <cause> » ; fichier introuvable -> `404` (avant : `200`
  vide), hors périmètre : même `404` (leurre) ; échec **pendant** l'envoi -> **flux coupé** (connexion fermée sans fin de
  transfert, `[ERREUR]` au journal) ; code 1 : réponse complète, `[WARN]` au journal. UI : « Téléchargement interrompu » au
  lieu du message brut du navigateur. **Reverse proxy : HTTP/1.1 requis** (nginx : `proxy_http_version 1.1;`) — en HTTP/1.0 la
  coupure vaut fin normale (décision de l'utilisateur : documenté). Client qui abandonne un téléchargement : borg arrêté aussitôt
  (antérieur : borg bloqué, processus zombie, verrou de dépôt gardé, serveur à 100 % CPU — mesuré en revue).
- **`index_last.code` = code de sortie** : erreur de base chiffrée 2 (avant : 1), borg tué par le signal N 256−N (SIGKILL : 247 ; avant : code négatif), Ctrl-C 130.
- **Lecteurs sans attente de 60 s** : sur une diff.db tenue par un verrou exclusif, RepoHistory, Status, ArchiveHistory, le
  watcher, Report (purge du cache) attendaient 60 s (mesuré 60,3 s) avant de lire history.db ou de signaler la base ; sonde
  lecteur de 2 s, comme le reste des lecteurs (écrivains : 60 s, inchangé).
- **Message d'échec de borg** : en `--log-json` (Bkp, Prune), un échec (code ≥ 2) sans erreur dite donne « failed (code N) —
  avertissement de borg : … » (avant : le code seul) ; CRITICAL lu comme ERROR. Bkp et Prune (écrivains) gardent une attente de
  60 s sur diff.db avant la migration des mesures ; `/access` (bases en clair) et DiffTop n'attendent plus 60 s.
- Tests : chacun des 567 contrôles de 1.0.176 lancé seul, puis les 18 variantes de casse et les nouveaux avec un filtre sensible
  à la casse : tous OK (aucune dépendance de décor restante) ; nouveaux contrôles `index_last`, verrou exclusif réel, délai de
  sonde par site (lecteurs 2 s, écrivains 60 s), `_rb_errmsg` ; push_selftest : `/download/*` (vrais sous-processus, borg tué si
  le client part, flux coupé de bout en bout par l'application) ; test UI : téléchargement interrompu. CodecSelfTest 571/571.

## borgHelper 1.0.176 / borgHelperWWW 1.30.1 — code 1 de borg en avertissement, Bkp tué en échec, lecteurs annexes marqués, Index multi-nicks robuste, --numeric-ids — 2026-10-02

Chantier « reconstruction progressive », story 39 (actions de rétrospective A77 à A80 ; regroupement demandé par l'utilisateur).

- **Bkp dont `borg create` est tué ou sort en code 2 sans ligne ERROR -> échec** (décision de l'utilisateur ; trouvé en
  mesurant) : avant, « success », code 0, ni notification d'échec ni alerte Sentry (OOM, `kill -9`, borg qui sort en 2 sans
  rien écrire). Désormais `[ERREUR] nick: borg create a échoué : <cause ou code>`, code 2, `bkp_status` « error ». Code 1
  (avertissements de fichiers) : inchangé.
- **Code 1 de borg = avertissement, partout** (décision de l'utilisateur) : sur les lectures (Index, Report, DiffBkp, Mount
  `-b last`, Restore/ListPerms sans `-b`, CacheClean, rapprochement après Prune/DelBkp, snapshot d'Index), un `borg list`/`info`/
  `diff` en code 1 avec une sortie valide était un échec (« borg list failed (code 1) », code 2, sortie jetée) ; DelBkp en code 1
  disait « a échoué » alors que l'archive était supprimée, sans compact ni rapprochement ; Prune : `borg compact` en code 1 ->
  « a échoué », code 1 (WWW : 400) après un élagage réussi. Désormais la sortie est utilisée et les avertissements affichés
  `[WARN] nick: borg <commande> : <ligne>` (stderr ; 5 lignes au plus, puis leur nombre), code de la commande inchangé (DelBkp,
  Prune : 0) ; avertissements de `borg diff` d'Index, de `borg prune` (`--log-json` : les lignes « Keeping »/« Would prune » ne
  sont jamais des avertissements) et du `borg info` des archives de Report dits (avant : jetés). Code ≥ 2, borg tué, ou code 1
  sans aucune sortie là où une sortie est attendue (`borg diff` de DiffBkp, snapshot : borg tué par SIGTERM sort ainsi) : échec.
  Restore, ListPerms, Mount, Key, Init, Umount, Login : règle inchangée (code de borg, lignes de borg). borgHelperWWW
  `/download/*` sans archive : `borg list` en code 1 -> dernière archive (avant : 502), avertissement au journal du serveur.
- **Lecteurs annexes : vraie erreur SQLite dite** (`[ERREUR] SQLite error (<base>): …`) : watcher de borgHelperWWW
  (notifications de début/fin, alerte « en retard » — une base corrompue les faisait sauter sans trace ; ligne de nouveau dite
  après une lecture réussie de ce même lecteur), Restore/ListPerms sans `-b` (repli sur la dernière archive), IdxTop/DiffTop
  (texte et `-j`), RepoHistory/ArchiveHistory `-j`. **Paire de diff jamais réinsérée en double** : une base verrouillée au-delà
  du délai faisait lire la paire « non indexée » — DiffBkp relançait `borg diff` et réinsérait ses lignes (doublons mesurés :
  4 lignes pour 2) ; désormais DiffBkp s'arrête (`[ERREUR] … non vérifiable`, code 2), Index laisse la paire à la passe
  suivante (aussi quand la purge d'une paire échoue) ; et les deux écrivains (DiffBkp, Index — y compris en même temps, Index de
  fin de Bkp et Diff demandé dans l'UI) n'ajoutent les lignes que s'ils ont eux-mêmes enregistré la paire.
- **RepoHistory `-j` sur une history.db sans `repo_stats`** (0 octet, en-tête seul, vue seule, `-wal` orphelin) : `rows: []`
  (décision de l'utilisateur ; avant : `{"error": "… no such table: repo_stats"}`, rouge sur les graphiques). Colonne absente
  (schéma abîmé) : erreur, comme avant.
- **Index sur plusieurs nicks** : une exception ou un arrêt sur un nick (base corrompue…) n'arrête plus les suivants (comme Bkp) :
  message du nick, `index_last` de chacun, code = le pire ; Ctrl-C arrête. Un seul nick : inchangé. Exception imprévue d'un nick
  (Index et Bkp multi-nicks) : envoyée à Sentry comme pour un nick seul (décision de l'utilisateur ; Bkp multi-nicks : avant,
  ligne `[ERREUR]` seule). Alerte Sentry `bkp_error` d'un `borg create` tué : avec la cause.
- **Restore : `--numeric-ids`** (décision de l'utilisateur) au lieu de `--numeric-owner`, déprécié depuis borg 1.2 (avertissement à
  chaque extraction). **borg 1.2 ou plus requis** (déjà le cas de fait : `borg compact`).
- CodecSelfTest : nouveaux contrôles « borg en code 1 », « Bkp : borg create tué », « Index plusieurs nicks », « lecteurs
  annexes », `--numeric-ids` ; push_selftest : `/download/*` en code 1.

## borgHelper 1.0.175 / borgHelperWWW 1.30.0 / UI 1.22.0 — sorties de borg lisibles partout, /login sans chemin libre, erreurs SQLite marquées, codes d'Index et d'Init — 2026-10-02

Chantier « reconstruction progressive », story 38 (actions de rétrospective A70 à A75 ; regroupement demandé par
l'utilisateur).

- **Sorties de borg lisibles à chaque site** : Restore (`-w`, `-W`, tar), ListPerms, Mount et Key (code 1), Bkp, Umount,
  Login (`key import`), Init, DiffBkp et Index. Avant : sur un plantage de borg, 20 lignes brutes (bloc « Exception ignored »,
  trace Python, bandeau `sys.argv` avec les chemins) ; Umount, Login, Init : dictionnaire Python brut ; `borg diff` : « code N »
  seul ; `borg diff` d'Index : échec muet. Désormais : échec -> une ligne « nick: borg <commande> a échoué : <cause> »
  (« ⚠ dépôt absent » pour un dépôt local introuvable), code de borg ; code 0/1 -> lignes de borg gardées (avertissements de
  fichiers, conseils de `borg init`), trace réduite à son exception, bandeau écarté. Sur un échec, les avertissements
  (« Warning: … », ex. `--numeric-owner` déprécié) passent après la cause.
- **Init rend le code de borg** (décision de l'utilisateur) : dépôt existant -> code 2 (avant : 0) ; `POST /init` -> 400.
- **Index : `borg list` en échec -> code 2** (décision de l'utilisateur ; avant : 1), message commun (« ⚠ dépôt absent » ou
  « borg list a échoué : … »), `index_last` code 2 ; `borg diff` en échec : `[WARN] … — paire … non indexée` (avant : rien).
- **borgHelperWWW `POST /login` sans chemin libre du serveur** (décisions de l'utilisateur, **⚠ rupture**) : `keyfile` et
  `mountpoint` refusés (400, même vides ; `key import` lisait un fichier arbitraire du serveur), dépôt **distant seulement**
  au sens de borg 1.2 (`ssh://[user@]hôte[:port]/…`, `[user@]hôte:…` — hôte sans `/` ni `:` ; `/srv/a:b`, `./x:y`, `/srv/x::a`,
  `%(…)s`, `file://` refusés : un chemin local suivi de `POST /init` créait un dépôt n'importe où, droits du service) — refus
  avant tout lancement de borgHelper. UI : champs retirés, refus affiché.
- **Noms de serveur/nick de Login : liste blanche** (revue, décision de l'utilisateur ; CLI et `POST /login`) : lettres,
  chiffres, `.`, `_`, `-`, début lettre ou chiffre, `ALL`/`DEFAULT` refusés (400 / code 2). Avant : écrits tels quels comme
  section du rc — `]` + retour à la ligne injectait des clés (`BORG_RSH`, `BORG_EXE` : commande exécutée au prochain Init/Bkp),
  `ALL` ou `a,b` écrasaient ou dupliquaient des sections. **`%` dans une valeur de Login** (passphrase, dépôt) : écrit `%%`
  (avant : `ValueError`, trace envoyée à Sentry ; `%(…)s` relu par interpolation).
- **Erreurs SQLite plus jamais muettes** (décision de l'utilisateur) : un lecteur qui rencontrait une vraie erreur (verrou au-delà
  du délai, corruption, I/O) l'avalait — Report (mesures, tailles, modifications « — »), ArchiveHistory (« Aucune archive
  indexée »), Status (« aucune archive indexée »), IdxTop/DiffTop (lignes Exclus perdues), lecteurs `-j` (« Index vide »).
  Désormais `[ERREUR] SQLite error (<base>): <erreur>` sur stderr, une fois par base ; sortie partielle et code inchangés
  (jamais mise en cache par borgHelperWWW) ; « Index vide » remplacé par la cause réelle. Base ou table absente : silencieux.
- **Report en ligne : `borg prune --dry-run` en échec jamais mis en cache** (décisions de l'utilisateur) : récupérable et ligne
  Prunable « — » (JSON : `null`), `[WARN] … — récupérable inconnu` ; avant, « rien à récupérer » restait servi jusqu'au prochain changement du dépôt (une entrée vide déjà en cache le
  reste jusque-là). `borg diff` d'Index : stderr lu (un stderr de plus de ~64 Ko bloquait borg). Index sur un dépôt local
  introuvable : ni base créée ni borg lancé (comme les autres commandes). Report : un `borg info` en échec donne sa cause (avant :
  « list index out of range »). borgHelperWWW `/download/*` sans archive : `borg list` en échec -> message réduit (avant : stderr
  brut coupé à 300 caractères, trace sans cause).
- CodecSelfTest : six contrôles dépendaient d'un décor logé dans un autre contrôle — `-f` changeait leur verdict (`-f Key` :
  2 FAIL) ; décors exécutés hors filtre (`_pre`), contrôle « plans » autonome. Nouveaux : « plantage de borg relayé »
  (plantage réel rejoué), « sorties de borg en processus », « erreur SQLite réelle d'un lecteur » ; push_selftest :
  « POST /login ».

## borgHelper 1.0.174 / borgHelperWWW 1.29.0 / UI 1.21.0 — cache attentif à l'état extérieur, /restore sous une racine, cause des plantages de borg — 2026-10-02

Chantier « reconstruction progressive », story 37 (actions de rétrospective A66, A67, A68, A69 ; regroupement demandé par
l'utilisateur).

- **borgHelperWWW : `POST /restore` écrit sous une racine de restauration seulement** (décisions de l'utilisateur).
  Nouveau réglage **`--restore-root` / `BORGHELPERWWW_RESTORE_ROOT` / `restore_root`** (conf ou `[_borgHelperWWW]`).
  Avant : `where` passé tel quel à Restore — chemin relatif au répertoire du service, `..`, liens, dossiers créés n'importe
  où avec les droits du service (root possible), seule la permission « restore » du nick le limitait. Désormais : sans
  racine (ou racine introuvable) -> `403`, action « Restaurer » masquée dans l'UI ; `where` est **relatif à la racine**
  (un chemin absolu à l'intérieur reste accepté), résolu (liens et `..` suivis) et doit y rester, sinon `403` ; vide ->
  `400` ; **destination déjà remplie -> `409`** (revue, décision de l'utilisateur : un lien laissé dessous par une
  restauration précédente ferait écrire borg hors de la racine — restaurer dans un dossier absent ou vide) — refus avant
  tout lancement de borgHelper ; Restore reçoit le chemin résolu. Racine `/` : démarrage refusé. **⚠ Rupture** : une
  instance qui restaurait via l'API doit configurer la racine. `/version` : `restore_enabled` (faux si la racine est
  introuvable) ; `/access` : `restore_root` (appelant qui peut restaurer sur au moins un nick). `/download/*` et
  `GET /restore/perms` : inchangés.
- **borgHelperWWW : Report hors ligne et DiffBkp en cache suivent l'état extérieur** (décisions de l'utilisateur) :
  l'empreinte ajoute la présence de chaque dépôt local — disque démonté -> recalcul, « ⚠ dépôt absent » plus jamais masqué
  (remonté : la réponse d'avant, même état, resservie) ; durée de vie de 5 min (Report : « depuis », alerte de sauvegarde
  trop ancienne, place libre ; DiffBkp : `borg list` en direct, dernière paire d'archives d'un dépôt externe). DiffBkp dans
  le cache par périmètre aussi. Les 12 autres routes en cache ne lisent que les bases (inchangées). Présence sondée en
  1 s au plus (montage réseau figé : présumé présent, jamais un thread de requête bloqué) ; réponse calculée pendant un
  changement d'état : pas mise en cache.
- **borgHelperWWW : l'arrêt d'un nick n'est plus mis en cache** : un lecteur multi-nicks (Search, IdxTop…) sort en code 0
  quand un seul nick s'arrête (« DB occupée », base corrompue ou illisible, schéma) — la réponse restait servie après la
  fin d'une erreur passagère. Toute réponse dont le stderr porte `[ERREUR]`, ou qui porte « SQLite error » (erreur SQLite
  avalée en code 0 par Search, FileHist, TreeHist, TreeFind, IdxTop, DiffTop), est recalculée à chaque appel, dans les
  deux caches (comme une DbKeyError) ; « Index vide » en texte l'est aussi (en `-j`, état stable, toujours en cache).
- **Message d'un plantage de borg** (`Local Exception`, exception distante) : la cause figure (« Local Exception;
  ValueError: could not convert string to float: 'x' ») — avant, sur borg 1.2.6 (mesuré) « Exception ignored in:
  <function Repository.__del__ …>; Traceback (most recent call last): », ailleurs « Local Exception; Traceback … ».
  Trace Python réduite à sa ligne d'exception (dernière d'une chaîne ; omise si elle répète le message d'une erreur borg
  « avec trace », CheckNeeded…), bandeau sysinfo écarté après une trace, bloc « Exception ignored … » écarté — Key, DelBkp,
  Mount, Prune, Report en ligne, et le `borg list` de DiffBkp, Restore sans `-b`, Mount et Index. Erreurs
  ordinaires de borg : inchangées. Restent bruts (sortie de borg complète) : Restore, ListPerms, Bkp, repli
  `borg list --format` d'Index.
- UI : « Restaurer » masqué sans racine, libellé « Destination (sous-dossier de <racine>) ».
- CodecSelfTest : « message d'échec borg » (sorties réelles) ; push_selftest : « cache des réponses » (état extérieur,
  arrêt d'un nick), « POST /restore sous la racine » ; test UI : « restauration ».

## borgHelper 1.0.173 / borgHelperWWW 1.28.8 — cache sans erreurs, Restore vers dossier absent, message d'échec unique — 2026-10-02

Chantier « reconstruction progressive », story 36 (actions de rétrospective A62, A63, A64, A65 ; regroupement demandé par
l'utilisateur ; A65 = outillage de test hors dépôt).

- **borgHelperWWW : plus d'échec « extérieur » mis en cache** (`_RESPONSE_CACHE`, 14 routes : lstbkp, lstbkpfls, report
  hors ligne, diffbkp, search, filehist, treehist, treefind, duidx, cacheinfo, repohistory, archivehistory, idxtop,
  difftop). Avant : « ⚠ dépôt absent » ou une coupure ssh restait servi après remontage, tant que diff.db/cache.db ne
  changeaient pas. Décisions de l'utilisateur : codes 0 et 1 gardés (1 = alerte tirée des bases : Report -o « diff.db
  absent », sauvegarde trop ancienne — la page d'accueil reste servie du cache), code >= 2 jamais ; forme et statut HTTP
  inchangés.
- **Restore `-w` vers un dossier absent** (décision de l'utilisateur) : le dossier est créé, comme avec `-W` (avant :
  trace Python `FileNotFoundError`, envoyée à Sentry, code 1) ; si `borg extract` échoue ensuite, les dossiers créés
  restés vides sont retirés. Destination vide, qui n'est pas un dossier (fichier, lien cassé), non traversable, ou
  création impossible : « [ERREUR] destination … : … », code 3, avant la sélection d'archive et tout appel à borg.
  **`-W` aussi** (décision de l'utilisateur, revue) : vers un fichier ou sous un dossier sans droits, plus de trace
  (`FileExistsError`, `PermissionError`), mêmes messages, code 3. Cible tar : inchangée (son dossier n'est pas créé).
- **Une seule règle de message d'échec de borg** (`_rb_errmsg`) : `_boex_last_modified` (Report, CacheClean) en gardait
  une copie — même texte qu'avant ; ses autres appelants (`borg list`, Mount, Key, DelBkp, Prune) écartent désormais aussi
  le bandeau « Borg: … » d'un rapport de plantage (sans effet sur une vraie sortie de borg 1.2, où il suit le message).
- CodecSelfTest : « destination de Restore », « message d'échec borg » ; push_selftest : « cache des réponses » (codes,
  DbKeyError, écriture unique).

## borgHelper 1.0.172 — dépôt absent sans trace, ensure sans création — 2026-10-02

Chantier « reconstruction progressive », story 35 (actions de rétrospective A59, A60, A61 ; regroupement demandé par
l'utilisateur ; A59 = outillage de test hors dépôt).

- **Dépôt absent ou borg en échec** (décisions de l'utilisateur) : DiffBkp (sans `-b`, `-b a,b`, `-j`), Restore sans `-b`
  (`-L`, `-w`) et Mount `-b last` finissaient en **trace Python** (`RuntimeError` de `borg list`, envoyée à Sentry), code 1 ;
  Key n'affichait rien (code 0) ; DelBkp, Prune et Mount imprimaient un dictionnaire brut. Désormais : dépôt local
  introuvable -> « nick: ⚠ dépôt absent (BORG_REPO) », code 2 (comme Report 1.0.167), borg jamais lancé, aucune base créée ;
  autre échec -> « nick: borg <commande> a échoué : <message de borg> », code 2 (DelBkp, Prune, Mount : code de borg).
  `DiffBkp -j` : `{"error": …}`. Key et Prune sur plusieurs nicks : le pire code (Prune : avant, le dernier non nul ; borg
  tué par un signal : jamais 0). Code 1 de borg (avertissement) : Key affiche la clé, Mount ses lignes. Prune : un `borg prune`
  en échec rend son code et son message (avant : ceux de `compact`, code 0 si compact réussissait).
- **« ⚠ dépôt absent » à tort** (Report compris, depuis 1.0.167) : `BORG_REPO` avec un marqueur borg (`{hostname}`, `{user}`…)
  n'est plus jamais dit absent ; test par ouverture (un dépôt autofs se monte, `stat` ne le montait pas).
- **Lecteur et base supprimée en même temps** : `ensure_diff_db`/`ensure_cache_db(create=False)` ouvraient la base en
  création après l'avoir sondée — supprimée entre les deux, elle était recréée avec tout son schéma, en clair. Ouverture
  sans création (`_open_db(create_file=False)`) : la base est vue absente, rien n'est recréé. `ensure_history_db(create=False)`
  sur le même test d'état que les deux autres.
- CodecSelfTest : « borg en échec » (11 commandes × dépôt local absent / distant en échec, CLI réelle, borg factice ;
  plusieurs nicks ; Bkp garde le comportement de `getlastbkp`), « course sonde/ouverture » (diff, cache, history ; palier 10
  migré par un lecteur ; base illisible intacte).

## borgHelper 1.0.171 — lecteurs sans création de fichier, état de base unique, dry-run sans écriture — 2026-10-01

Chantier « reconstruction progressive », story 34 (actions de rétrospective A56, A57, A58 ; regroupement demandé par
l'utilisateur).

- **Lecteurs** (Search, FileHist, TreeHist, TreeFind, DuIdx, CacheInfo, lookups du cache…) : ne créent plus de fichier.
  Avant, chaque lecture d'un nick jamais indexé laissait un `diff.db`/`cache.db` de 0 octet (cause des correctifs
  1.0.168-1.0.170). Réponse inchangée. Les fichiers de 0 octet déjà présents sur les disques restent traités comme une
  base absente.
- **Un seul test « est-ce une base ? »** pour toutes les commandes : absente (inexistante, 0 octet, aucune table — en-tête
  seul, vue seule), base (au moins une table), illisible (corrompue, ou verrouillée au-delà du délai). Un fichier « vue
  seule » (posé par le contrôle de vue de borgHelperWWW avant 1.0.169) ne fait plus naître une base en clair, et le
  nettoyage après Prune ne crée plus de base sur un fichier vide.
- **diff.db corrompue** (décision de l'utilisateur) : `Report -o` affiche la ligne du nick en erreur avec le message réel
  (« ⚠ DB corrompue … file is not a database »), code 2 — avant : « diff.db absent — lancez Index », code 1. `DbStatus` :
  « diff.db: illisible (…) » au lieu de « absent » ; history.db suit les mêmes états. Report -o sur plusieurs nicks : code de
  sortie = le pire (avant : un nick suivant sans base ou en retard ramenait un 2 à 1).
- **Base illisible pour cause de droits** (fichier ou dossier inaccessible, dossier en lecture seule) : « [ERREUR] DB illisible
  … Vérifier propriétaire et droits — ne PAS supprimer le fichier » au lieu de « DB corrompue … Supprimez le fichier »
  (décision de l'utilisateur), pour Report -o comme pour Index, Bkp…
- **Prune / DelBkp, diff.db corrompue** : arrêt « DB corrompue » comme avant, history.db intacte (le rapprochement ne lit plus
  jamais une base illisible comme absente : ses mesures d'archives auraient été retirées). Plus de `cache.db` vide créé
  par le vidage du cache d'un nick sans cache.
- **Dry-run** (décision de l'utilisateur : `-D` n'écrit jamais) : `DbEncrypt -D` / `DbDecrypt -D` (et sans `-y`)
  migraient le schéma d'une base ancienne (palier 10) tout en annonçant « aucune modification ». Le rapport est désormais
  fait sur la base telle quelle (« ? » pour une table qui n'existe pas encore) ; seule l'exécution réelle (`-y`) migre.
  Mêmes arrêts qu'avant sans rien écrire : base corrompue (« DB corrompue », code 1), occupée (« DB occupée »), schéma plus
  récent (« Erreur schéma DB »). Limite documentée (décision de l'utilisateur) : des trames WAL laissées par un processus
  tué sont reportées par SQLite à la fermeture de toute connexion, -D compris (contenu identique).
- CodecSelfTest : « sans création » (17 lecteurs : même réponse qu'un fichier vide, rien créé ; `_open_db` en lecture,
  chemin `bytes`, fichier supprimé pendant l'ouverture, dossier absent, fichier sans droits, base existante intacte, vue
  seule sans avertissement ; nettoyage après Prune, base corrompue), « état de base » (chaque état × prédicat, verrou,
  dossier fermé, vue seule -> base née chiffrée ; base corrompue, occupée, droits, schéma récent : Report -o CLI multi-nicks,
  DbStatus, Db* -D), « dry-run sans écriture » (9 commandes -D/aperçu × 11 états de diff.db : empreintes de CACHE_DIR
  inchangées ; rapport sur la base non migrée).
- CodecSelfTest « versions de borg : serveur selon le mode » : l'enfant tué au délai pouvait être vu vivant (zombie pas
  encore récolté, mesuré 7 fois sur 20) — attente bornée, zombie compté mort.

## borgHelper 1.0.170 — base absente : fichier vide laissé par un lecteur — 2026-10-01

Chantier « reconstruction progressive », story 33 (action de rétrospective A55, périmètre élargi après mesure, décision
de l'utilisateur).

- Un lecteur qui passe sur un nick jamais indexé laisse un `diff.db` de 0 octet (autres formes sans table : en-tête seul
  d'une création ratée, vue seule posée par le contrôle de vue de borgHelperWWW avant 1.0.169). IdxTop, DiffTop (texte et
  `-j`) et IdxPurge le prenaient pour une base (« SQLite error … no such table ») ; **DbEncrypt -D / DbDecrypt -D créaient une
  base en clair pendant un dry-run** (« aucune modification ») — la base n'était plus neuve, le chiffrement d'office
  (1.0.168) était contourné ; DbRekey répondait « base non chiffrée (plain) », code 2. Désormais : le message « absent » de
  chaque commande, comme pour un fichier inexistant ; rien n'est créé ni modifié. DbRekey : code 1 (base absente).
- DbEncrypt -y / DbDecrypt -y, diff.db absente : une cache.db existante est quand même mise dans le mode cible (décision de
  l'utilisateur, comme la règle de 1.0.168) ; un Index en cours pour le nick : refus (code 2), comme avant.
- DbEncrypt, DbDecrypt, DbRekey sur plusieurs nicks : code de sortie = le pire des nicks (avant : le dernier non nul).
- Base corrompue ou verrouillée : jamais dite absente — son erreur réelle reste affichée.
- CodecSelfTest : « nick sans base » (vide, en-tête seul, vue seule, `-wal` orphelin == absent pour les 6 commandes, rien
  créé ; base corrompue ; multi-nicks des deux jumelles ; cache.db ; verrou ; pire code en CLI).

## borgHelper 1.0.169 / borgHelperWWW 1.28.7 — base vide née d'une autre passphrase, base recréée tenue ailleurs — 2026-10-01

Chantier « reconstruction progressive », story 32 (actions de rétrospective A52, A53 ; regroupement demandé par
l'utilisateur).

- **Lecteurs, base née d'une passphrase fausse** (premier Index avant que borg ne la refuse) **et passphrase corrigée** :
  la base n'a aucun chemin, elle se lit désormais comme une base vide — « Index vide pour lb — lancez : borgHelper -c
  Index -n lb », Report -o comme un nick jamais indexé, UI sans erreur. Avant : `DbKeyError : passphrase incorrecte`
  (code 2) sur toute lecture jusqu'au prochain Index/Bkp, qui répare (1.0.168). Le lecteur n'écrit rien et garde sa vue
  vide même si un Index répare la base pendant sa lecture. Base avec données, passphrase absente, KDF indisponible, base
  hors WAL, Index/Bkp eux-mêmes : `DbKeyError` comme avant (l'Index ne lance jamais de `borg diff` sur une telle base sans
  la réparer). `cache.db` dans le même état : Report direct n'échoue plus sur la purge du cache ; la base est réparée par
  le cache manqué qui suit.
- **Base recréée alors qu'un autre processus tient encore l'ancienne** (supprimée pendant un Index, un Bkp ou une
  requête borgHelperWWW) : `[ERREUR] DB : … recréée alors qu'un autre processus tenait encore l'ancienne ouverte —
  attendre la fin de ce processus (ou l'arrêter), puis relancer`. Avant : « DB corrompue … disk I/O error — Supprimez le
  fichier et relancez » (conseil faux), et le deuxième essai redonnait ce conseil. `diff.db`/`cache.db` seulement. Rien
  n'est supprimé.
- Contrôle périodique de borgHelperWWW : plus de vue créée dans un fichier encore sans table (lui donnait un schéma avant
  sa création : base née en clair).
- Mesuré, sans correctif : un `-wal`/`-shm` orphelin (processus tué) n'est jamais rejoué à la recréation d'une base
  supprimée (SQLite 3.37.2) ; KDF dérivée pour rien sur une base corrompue : 0,2 s au plus.
- **borgHelperWWW 1.28.7** : la sonde de chiffrement d'un nick (`_nick_owner_codec`) garde ce nick verrouillé (aucune
  ligne de cache de périmètre), jamais pris pour une base en clair.
- CodecSelfTest : « base vide clé fausse » (10 lecteurs == base vide : sortie, code, rien écrit ; limites du repli ;
  lecture seule ; vue figée et reprise pendant une réparation ; contrôle de vue ; vrai borg passphrase fausse puis corrigée),
  « base supprimée tenue » (vrai tenant en sous-processus, deux essais, diff.db, cache.db, création chiffrée ; vraie
  corruption par `ensure_*`) ; push_selftest : sonde verrouillée.

## borgHelper 1.0.168 — base neuve chiffrée d'office, message réel du Report — 2026-10-01

Chantier « reconstruction progressive », story 31 (actions de rétrospective A48, A50, A51 ; regroupement demandé par
l'utilisateur).

- **Base neuve chiffrée dès sa création** : `diff.db` ou `cache.db` d'un nick créée par Index, Bkp, Prune, Diff ou un
  cache de `borg` alors que `DB_ENCRYPT` est actif et la passphrase présente -> en-tête `siv1` posé dans la même
  transaction que le schéma (KDF `DB_KDF`), sans message. Avant : base créée en clair, `[WARN] base non chiffrée` à
  chaque commande jusqu'à un `DbEncrypt -y`. Jamais pour une base existante (même vide : `[WARN]` et `DbEncrypt` comme
  avant), un nick avec `DB_NAME` (base partagée, peut-être d'autres passphrases), un fantôme `.rebuild`, ni sans
  passphrase / avec `DB_ENCRYPT=false`. Deux créateurs simultanés : une seule clé ; un créateur en clair passé avant :
  base laissée en clair.
- `[WARN] base non chiffrée` n'apparaît plus pour un fichier encore sans table (lecture du cache avant sa création,
  par exemple au premier Report) : ce n'était pas une base en clair ; `DbStatus` l'affiche `absent`.
- Base partagée vue de l'autre côté (nick sans `DB_NAME` dont le fichier est la cible du `DB_NAME` d'un autre nick) :
  jamais chiffrée d'office non plus. `DB_ENCRYPT`/`DB_KDF` invalides : base en clair, sans ligne `[ERREUR]` de plus.
- Base née d'une passphrase fausse (premier Index/Bkp avant que borg ne la refuse) et **sans aucun chemin** : le
  créateur suivant, avec la bonne passphrase, remplace son en-tête (décision de l'utilisateur) ; base avec données :
  `DbKeyError` comme avant.
- `DbEncrypt -y` / `DbDecrypt -y` : `diff.db` déjà dans le mode cible -> `cache.db` mise quand même dans ce mode (avant :
  « déjà chiffrée » et `cache.db` laissée en clair, `[WARN]` sans issue).
- **Report, base illisible** : `reste` porte le message réel de l'arrêt (`⚠ DB corrompue : …/rc-nick-diff.db ->
  database disk image is malformed …`), complet, en texte, HTML et JSON, hors ligne comme en direct — avant
  `⚠ base illisible (voir message)`. Report direct : plus de ligne `[ERREUR] nick: base illisible (voir message)` en
  doublon sur stderr.
- Interne : les 7 lecteurs multi-nicks et la boucle de `main` des lectures texte partagent une seule règle d'isolation
  par nick (`_PerNick`) au lieu de 8 copies ; sorties inchangées (96 cas comparés à 1.0.167 : 3 configurations ×
  nick seul/plusieurs × 16 commandes, stdout, stderr et code identiques).
- CodecSelfTest : « base neuve chiffrée » (création diff/cache, 6 refus, créateur concurrent en clair ou chiffrant,
  Index réel sans base -> siv1 et sorties == base en clair) ; « base occupée : Report multi-nicks » attend le message
  réel et l'absence de doublon ; Report HTML (`-l`) : message réel échappé, repli `⚠ arrêt (code N)`.

## borgHelper 1.0.167 / borgHelperWWW 1.28.6 — Bkp -n ALL, lecteurs multi-nicks, dépôt absent — 2026-10-01

Chantier « reconstruction progressive », story 30 (tri A46 de deferred-work, A47, A49 ; regroupement demandé par
l'utilisateur).

- **`Bkp -n ALL`** (ou liste) avec plusieurs nicks internes : un Bkp après l'autre, ordre du rc, un échec n'arrête pas
  les suivants, Ctrl-C arrête tout ; code = le pire ; objets JSON à la suite. Avant : « Ce serveur est inconnu »,
  code 3, aucune sauvegarde (le README affirmait le contraire).
- **Lecteurs multi-nicks** (Search, FileHist, TreeHist, TreeFind, DuIdx, IdxTop, DiffTop) : une base inutilisable pour
  un nick (passphrase fausse, base illisible, migration de chiffrement, schéma plus récent) n'efface plus les autres ;
  message réel du nick (stderr ; `{nick: {"error": …}}` en JSON, sauf DuIdx : totaux des autres nicks), code 0. Avant :
  code 2, aucune sortie. Nick seul ou tous en échec : inchangé (première erreur).
- **Report, dépôt local absent** : archives affichées (hors ligne), `reste` = `⚠ dépôt absent`, nick en alerte, code 2
  (avant : `df … | tail -1` lisait le code de `tail`, `ValueError`, aucune archive du nick en hors ligne) ; `dfRepo`
  sans shell ; dépôt présent mais inaccessible (droits) : jamais « absent ».
- **borgHelperWWW 1.28.6** : la sortie d'un appelant à périmètre restreint est filtrée quel que soit le code de sortie
  (`_scoped_filter_result`, commun aux deux chemins filtrés) — avant, un code ≠ 0 relayait stdout non filtré ; une
  réponse dont un nick a une base chiffrée inutilisable n'est jamais mise en cache, même en code 0 (AD-13 : cache de
  réponses et fragments par nick du cache de périmètre).
- CodecSelfTest : contrôles « multi-nicks » (CLI réelle avec passphrase fausse pour chaque lecteur ; message réel,
  tous en échec, Ctrl-C ; dfRepo et Report jumelles ; Bkp sur vrai borg : deux nicks, premier en échec, Ctrl-C) ;
  push_selftest : filtrage quel que soit le code.

## borgHelper 1.0.166 — une base occupée ne masque plus les autres hôtes — 2026-10-01

Chantier « reconstruction progressive », story 29 (demande de l'utilisateur : un verrou pendant une migration faisait
disparaître les autres hôtes de borgHelperWWW).

- **Cause (mesurée)** : un lecteur écrit pour entretenir la base d'un nick (migration de palier, vue, tampon de version
  réécrit à chaque nouvelle version de borgHelper). Base tenue par un autre processus : 60 s d'attente puis arrêt —
  `Report -o -n ALL` sans aucune sortie, `Status` 2 × 60 s, `/access` puis la liste des machines bloqués.
- **Lecteur** : attente du verrou d'écriture 2 s au plus par base ; ensuite la migration et le tampon sont abandonnés
  (paliers déjà validés gardés) et la base est lue telle quelle, en silence ; plus de nouvelle attente pendant 60 s pour
  la même base. Base libre : migrée
  comme avant ; écrivains (Index, Bkp) inchangés ; base d'un schéma plus récent toujours refusée.
- **Report** (hors ligne et direct) : une base illisible n'arrête plus la commande — ligne
  `*** nick ⚠ base illisible (voir message)`, autres dépôts affichés, code 2 ; Ctrl-C arrête toujours le Report.
- CodecSelfTest : contrôles « base occupée » (verrou tenu par un autre processus : Report multi-nicks rapide et
  silencieux, base ni migrée ni tamponnée ; base libre migrée ; schéma plus récent refusé ; attentes 60 s / 2 s ; mémo ;
  cache.db ; Status ; base illisible isolée ; verrou report-running retiré ; Ctrl-C).

## borgHelper 1.0.165 / UI 1.20.0 — versions de borg dans les rapports — 2026-10-01

Chantier « reconstruction progressive », story 28 (actions de rétrospective A44, note de l'utilisateur, et A40/A41).

- **Versions de borg** : borg n'enregistre aucune version logicielle (archive, manifeste, dépôt ; `borg serve` ne
  transmet pas la sienne — mesuré, borg 1.2.6). borgHelper les relève désormais **au Bkp** et les garde dans
  `history.db` (`archive_measure.borg_version`, `borg_server_version`, colonnes ajoutées sans changer la version de
  schéma) :
  - créateur de l'archive : `borg create --show-version` (message `borgbackup version X`), local comme distant
    (`SSH_REMFO` : borg de la machine sauvegardée), sans connexion de plus ;
  - borg qui a reçu les données : tunnel inverse `SSH_REMFO` vers cette machine -> `borg --version` local (vers une
    autre machine : inconnue) ; dépôt ssh direct -> `ssh hôte borg --version` (environnement du borg du Bkp, entrée
    fermée, sans terminal, `BatchMode`, 15 s) — une clé à commande forcée lance `borg serve`, dont la réponse porte la
    version (mesuré) ; dépôt local -> celle du créateur ;
  - réponse sans numéro -> « — » en silence ; échec -> `[WARN]` ; jamais d'échec du Bkp ni de mesure perdue ; JSON du
    Bkp : `borgHelper_borg_versions`.
- **Affichage** : colonne `borg` de Report (texte, HTML, JSON ; `1.2.6`, `1.2.6 / srv 1.2.4`, `—`), champs
  `borg_version`/`borg_server_version` d'ArchiveHistory et de `last_backup` dans Status (ligne `borg : …` en texte).
  Archives créées hors borgHelper ou avant 1.0.165 : `—`.
- **UI 1.20.0** : colonne « borg » dans les historiques court et complet.
- CodecSelfTest : contrôles « versions de borg » (lecture, serveur selon le mode avec exécutables simulés — délai,
  sortie non UTF-8, agent ssh, vrai `borg serve` en commande forcée —, tunnel inverse simulé dans `backup()`, history.db
  d'avant, à moitié migrée ou plus récente ; vrai borg local et par ssh : Bkp, Report, ArchiveHistory, Status, archive
  externe, sans `--show-version`).

## borgHelper 1.0.164 — snapshots par version, convertisseur borgmatic — 2026-09-30

Chantier « reconstruction progressive », story 27 (actions de rétrospective A37, note de l'utilisateur, et A39).

- **Snapshots par version** : `snapshot_file` garde une ligne par chemin **et** attributs (taille, date, type, droits,
  propriétaire), partagée par les archives où elle est identique et jamais modifiée sur place : la base garde les
  valeurs de chaque archive (vérifié par la base, vrai borg), que lisent les lecteurs par archive (vue
  `archive_snapshot_v` : lignes « présent » de `Search`/`FileHist`, `DuIdx`) — avant, une seule ligne par chemin, mise à
  jour à chaque snapshot, donnait l'état actuel.
- **Schéma `diff.db` 11** : migration automatique à la première ouverture, SQL seul, une transaction (table reconstruite
  sans `UNIQUE(nick, path)`, ids, liens et compteur gardés, vue recréée ; 3 s pour un million de chemins, mesuré). Le
  passé n'est pas reconstitué. Un borgHelper plus ancien refuse ensuite la base (régénérable). La migration des bases
  d'avant le palier 2 crée une version par taille et date.
- **Snapshot incrémental** : tout chemin changé (ajouté, modifié, droits, propriétaire, date, changement de type) est
  relu par `borg list` (motifs `pf:`, ce chemin seul) — avant, seuls les ajouts, et un `modified` ne changeait que la
  taille. Repli sur le snapshot complet au-delà de 5 000 chemins changés ou de 1 Mo de motifs (ligne de commande), et
  si `borg list` ne peut être lancé. Un chemin changé que `borg list` ne rend pas garde la ligne de l'archive précédente ;
  un chemin rendu deux fois (racines imbriquées) n'est lié qu'une fois.
- **Auto-réparation** (type/droits/propriétaire inconnus) : ne regarde plus que l'archive précédente — les versions
  anciennes n'étant plus réécrites, elle aurait sinon forcé un snapshot complet à chaque Index.
- **Corrigé** : un nom de fichier finissant par une espace était tronqué dans le snapshot (complet et incrémental).
- **Corrigé, base chiffrée** : le snapshot incrémental passait les chemins chiffrés de `diff_index` à `borg list` (aucune
  ligne rendue : fichiers ajoutés absents du snapshot) et à `IDX_INCLUDE`/`IDX_EXCLUDE`.
- **Corrigé** : un répertoire ajouté faisait entrer tout son contenu dans le snapshot incrémental, enfants exclus par
  `IDX_EXCLUDE` compris (`borg list` d'un chemin simple liste son sous-arbre).
- Snapshot complet : premier snapshot plus lent (mesuré, 300 000 chemins : 11,8 s au lieu de 5,2 s), suivants plus
  rapides (8,0 s au lieu de 25,4 s).
- **Nouveau script `borgmatic2borghelper` 1.0.0** (fichier à part, PyYAML requis) : convertit une configuration
  borgmatic 1.7 (sections) ou 1.8+ (à plat) en sections `.borghelperrc` — aperçu sur stdout, non converti sur stderr
  (valeurs à `${…}`, `{credential …}`, `~`, valeurs non textuelles au sens de YAML 1.1, clés sans équivalent), `-o` écrit
  un rc neuf en 0600 (jamais d'écrasement ni de fusion), `-e` nicks externes, `-p` préfixe, `--selftest`.
- CodecSelfTest : contrôles « snapshot par version » (migration en clair et chiffrée, refus par un binaire de schéma 10,
  palier 2, incrémental à borg simulé, bornes et attributs NULL, auto-réparation, vrai borg en clair et chiffré).

## borgHelper 1.0.163 — plusieurs chemins par nick, changement de type d'entrée — 2026-09-30

Chantier « reconstruction progressive », story 26 (actions de rétrospective A36, note de l'utilisateur, et A38).

- **`BORG_ROOTBKP`** accepte plusieurs chemins (séparés par des espaces, guillemets pour un chemin qui en contient) :
  `BORG_ROOTBKP = /etc /home "/srv/mes documents"`. Une valeur qui désigne un chemin existant reste entière (rc
  d'avant, espace sans guillemets compris). Chemin absent : `[WARN]`, les autres sont sauvegardés ; aucun présent
  ou valeur illisible : Bkp refusé (code 2, enregistré en échec, alerte). Borg distant (`SSH_REMFO`) : valeur
  transmise telle quelle, comme avant.
- **Snapshot** : `snapshot_file` mis à jour sur place — un chemin retiré puis rajouté (ou changé de type) disparaissait
  des snapshots plus anciens (l'id de sa ligne changeait).
- **Changement de type d'entrée** : un fichier devenu lien, répertoire ou fifo (ou l'inverse) compte comme supprimé ou
  ajouté dans Report, ArchiveHistory et le graphique ; le snapshot (TreeHist) prend le nouveau type — il gardait
  l'ancien (y compris quand le propriétaire change aussi). Paires indexées avant : non comptées.

## borgHelper 1.0.162 — Report en fichiers ordinaires, comptes de BorgCleanup — 2026-09-30

Chantier « reconstruction progressive », story 25 (actions de rétrospective A24 et A35).

- **Report, colonne `modifications`** : `XX%nb` et le dénominateur `nfiles − added + removed` comptent désormais les
  seuls fichiers ordinaires, comme `nfiles` de borg. Répertoires, liens et entrées `ctime`/`mtime` d'un répertoire dont
  le contenu change étaient comptés : pourcentage surestimé (mesuré, borg 1.2.6 : 200 %nb au lieu de 100 %nb). Tailles
  inchangées. Mêmes comptes pour `ArchiveHistory` (`files_added/modified/removed`) et le graphique « Fichiers modifiés
  par archive » ; lignes figées d'archives déjà purgées gardées telles quelles.
- **IdxPurge** : un ancien `removed` sans taille (répertoire) rejoint les exclus comme `removed directory` — comptes de
  Report inchangés par la purge.
- **BorgCleanup** : la question et le bilan comptent en éléments (entrées borg, fichiers borgHelper ; clés et
  historiques à part) — « Supprimer 2 élément(s) » puis « 2 élément(s) retiré(s) », plus « 3 » ; titre de la section
  des anciens identifiants exact pour les dépôts non chiffrés.

## borgHelper 1.0.161 — isolation des selftests, dépôt recréé au même chemin — 2026-09-30

Chantier « reconstruction progressive », story 24 (actions de rétrospective A33 et A34).

- **`BorgCleanup`** : signale aussi l'entrée borg d'un **ancien dépôt recréé au même chemin** (dépôt présent, du rc ou
  non, dont l'identifiant lu dans `<dépôt>/config` diffère) — section à part dans l'aperçu (« disque en rotation ? »),
  hors notice. Doute (config absente, illisible, sans identifiant, montage bloqué) : jamais proposé ; identifiant relu
  avant suppression (ancien disque remis : gardé). Clé de l'ancien identifiant : seulement avec `--keys` et « oui »,
  avertissement « disque en rotation ». Mesuré sur cette machine : 16 entrées périmées pour un dépôt de démo recréé.
- **`BorgCleanup`, dépôt non chiffré** (`none`, `authenticated`) : borg sans terminal refuse un tel dépôt dont l'entrée
  de sécurité a disparu (mesuré : code 2). Cette entrée est désormais gardée comme une clé : `-y` ne retire que le
  cache, `-y --keys` + « oui » l'entrée. Un stat qui ne répond pas (montage bloqué) ne déclenche plus aucune autre
  lecture.
- **CodecSelfTest** : crochet d'audit Python (ce processus et les borgHelper enfants) ; dernier contrôle « isolation
  des selftests » : aucun accès aux vrais dossiers borg et borgHelper de l'utilisateur, témoins par évènement et par
  dossier à chaque run. Défaut trouvé en le mesurant (strace) et corrigé : trois contrôles RepoHistory/ArchiveHistory
  lançaient `mkdir ~/.cache/borghelper` (rc de test sans `CACHE_DIR` ; le dossier était créé sur une machine neuve). Contrôles du dépôt recréé en bac à sable et sur vrai borg.

## borgHelper 1.0.160 / borgHelperWWW 1.28.5 / UI 1.19.5 — nettoyage des restes borg, signaux du selftest — 2026-09-30

Chantier « reconstruction progressive », story 23 (actions de rétrospective A30, demande de l'utilisateur, et A32).

- **Nouvelle commande `BorgCleanup`** : restes de dépôts borg **locaux** disparus (hors rc) dans le dossier personnel
  de l'utilisateur de borgHelper — entrées `~/.config/borg/security`, caches `~/.cache/borg`, clés
  `~/.config/borg/keys` — et fichiers borgHelper de nicks retirés du rc dans `CACHE_DIR`. Aperçu par défaut ; `-y`
  retire les entrées borg et les fichiers régénérables (`-D` : aperçu explicite, l'emporte sur `-y`) ; `--keys`
  (irréversible) et `--history` (historique mesuré) à
  part, avec confirmation sur l'entrée standard (« o », puis « oui » pour les clés et historiques ; sans réponse : rien
  supprimé, code 2). Jamais un dépôt distant ou configuré (`~`, relatif et `file://` compris), jamais un fichier encore
  produit par un nick (tronc exact ; dépôts et `DB_NAME` partagés), jamais un verrou tenu ni les fichiers de son nick ;
  rc vide ou illisible : rien ; chemin inaccessible ou montage bloqué (2 s) compté présent ; emplacements et verrous
  revérifiés avant suppression ; clé gardée : son emplacement aussi, hors notice.
  Mesuré sur cette machine : 26 entrées de dépôts locaux absents (6,3 Mo), toutes dans `/tmp`.
- **Notice** : ligne finale de `Status` et `Report` en texte, en ligne de commande (JSON et HTML inchangés ; jamais
  pour borgHelperWWW, qui pose `BORGHELPERC_NO_CLEANUP_NOTICE`) ; `GET /access` `borg_cleanup`
  (nombres et tailles, jamais de chemin ; admin seulement quand les groupes sont actifs ; recalculé au plus toutes les
  5 min) ; UI : bandeau sur la page des serveurs. Seule la CLI supprime.
- **CodecSelfTest** : SIGTERM et SIGHUP pendant le selftest lèvent `KeyboardInterrupt` (les `finally` tournent) ; tous
  les groupes d'enfants lancés sont tués en fin de selftest ; les 9 lancements de borgHelper avec délai passent par
  `_rb_run`, qui tue tout le groupe (wrapper, borg) si le délai expire, en gardant la sortie ; `raises()` laisse passer
  l'interruption ; registre élagué (jamais un `killpg` sur un PID réattribué). Gardes avec témoins (SIGKILL ; kill de
  l'enfant seul). `Status`/`Report` et `/access` ne lisent jamais le vrai dossier borg pendant les selftests
  (`BORGHELPERC_CLEANUP_HOME`).

## borgHelper 1.0.159 — wrapper atomique, tests de chargement des graphiques — 2026-09-30

Chantier « reconstruction progressive », story 22 (actions de rétrospective A29, A31). Aucun changement du code de
production ; UI et borgHelperWWW inchangés.

- **CodecSelfTest : plus de borg orphelin hors de son dossier.** Le contrôle « fantôme : kill -9 » tuait un borgHelper
  enfant pendant un `borg diff` ralenti ; le script `BORG_EXE` (en attente) et son borg survivaient, puis le script
  était réécrit en place. bash lit un script par position : la copie en cours reprenait dans le nouveau contenu, sautait
  `export BORG_BASE_DIR`, et le borg orphelin écrivait dans `~/.config/borg/security` (mesuré sur 1.0.157 : une entrée
  par run ; 1.0.158 n'y échappait que par hasard de position). Désormais :
  - le script `BORG_EXE` est écrit à côté puis remplacé (`os.replace`), jamais réécrit en place ;
  - les borgHelper enfants tués par le selftest ont leur propre groupe de processus, tué en entier (wrapper et borg
    compris), y compris sur Ctrl-C ; le contrôle vérifie qu'aucun processus du wrapper ni du dépôt ne reste.
- Nouveau contrôle : un wrapper réécrit pendant qu'une copie dort (marqueur avant son `sleep`), avec une reprise calée
  sur la ligne `exec`, garde son `BORG_BASE_DIR` (`HOME` d'un bac à sable, qui reste vide) ; témoin : la même séquence
  avec une réécriture en place écrit dans le bac à sable.
- Test de l'UI, réponses en erreur : aussi HTTP 502 avec code 0, `stderr` seul, champ `error`, réponse sans `rows` ;
  échec partiel (dépôt lisible, archives en erreur) et reprise après une erreur.
- **Test de l'UI** : chargement des graphiques — deux chargements qui se croisent (seul le dernier dessine), instances
  détruites avant de redessiner (faux Chart.js qui refuse un canvas encore utilisé), réponses en erreur (HTTP 500,
  code 1, JSON illisible, 401 : message sur les cinq graphiques), bibliothèque absente.

## borgHelper 1.0.158 — harnais vrai borg isolé, tests des graphiques — 2026-09-30

Chantier « reconstruction progressive », story 21 (actions de rétrospective A27, A28). Aucun changement du code de
production ; UI et borgHelperWWW inchangés.

- **CodecSelfTest : les contrôles sur un vrai borg n'écrivent plus chez l'utilisateur.** Deux fuites mesurées (borg
  1.2.6) :
  - les contrôles « repo_stats » et « rapprochement » lançaient borg par `boex`, qui ne transmet que les clés du rc,
    `PATH` et `LC_ALL` (ni `HOME` ni `BORG_BASE_DIR`) : chaque run complet laissait deux entrées dans
    `~/.config/borg/security` et `~/.cache/borg` (dépôts `/tmp/borghelper-selftest-*/realborg` et `realreconcile`) ;
  - `BORG_CACHE_DIR` et `BORG_SECURITY_DIR` exportés priment sur `BORG_BASE_DIR`.

  Un seul jeu d'aides pour les sept familles de contrôles (tranche, périmètre, fantôme, dépôt externe, rapprochement,
  repo_stats, Inchangés) : sous-processus borg sans aucune `BORG_*` ; tout `BorgHelper` du selftest passe par un script
  `BORG_EXE` qui retire `BORG_CACHE_DIR`, `BORG_CONFIG_DIR`, `BORG_SECURITY_DIR`, `BORG_KEYS_DIR` et pose le
  `BORG_BASE_DIR` du test (chemins entre guillemets) ; borgHelper enfants sans DSN Sentry ni passphrase d'exécution
  héritée (jamais le fichier DSN réel). Plus de `os.environ['BORG_BASE_DIR']` posé puis retiré (une valeur de
  l'utilisateur était effacée).
- Chaque contrôle sur un vrai borg échoue s'il laisse une entrée de sécurité borg chez l'utilisateur (dossier personnel,
  `HOME`, `XDG_CONFIG_HOME`, `BORG_*` de l'utilisateur) pour un dépôt du selftest.
- Nouveau contrôle : dossiers `BORG_*` factices dans l'environnement ; un dépôt neuf par chemin (sous-processus, script
  `BORG_EXE` avec et sans `exec`, `boex`, CLI) -> dossiers factices vides, cache et sécurité sous le `BORG_BASE_DIR` du
  test.
- Sans borg, chaque contrôle est sauté sous son propre nom (`-f` montre le `SKIP` du contrôle filtré, `-l` le liste) ;
  le bilan compte les `SKIP` (« 0/0 OK, 2 SKIP »). Garde sur un selftest imbriqué sans borg.
- **Test de l'UI** (`borgHelperWWW_ui_test.js`) : graphiques de la page Historique, sur les vraies fonctions de la page,
  un DOM limité aux `id` du balisage et un faux Chart.js — les cinq graphiques construits et eux seuls, `/repohistory`
  et `/archivehistory` demandés pour le nick affiché, séries `original_size`/`compressed_size`/`deduplicated_size` et
  leurs données, aucun indicateur de chargement laissé, message propre à chaque graphique sans données, archive
  supprimée atténuée et « (supprimée) » dans l'infobulle, bloc HTML (canvas et message) de chaque graphique, filet
  « Aucune donnée. ».

## borgHelper 1.0.157 / UI 1.19.4 — garde « Inchangés » sur vrai borg, bargraphe retiré — 2026-09-29

Chantier « reconstruction progressive », story 20 (actions de rétrospective A25, A26).

- **UI : bargraphe « Taille dédupliquée par archive » retiré** (demande de l'utilisateur) : la série
  `deduplicated_size` est déjà dans la courbe des tailles par archive. Il avait été ajouté (UI 1.13.0) parce que
  l'échelle de la taille originale l'écrase sur cette courbe : cliquer sur `original_size` et `compressed_size` dans
  la légende les masque et recadre l'axe (README).
- **CodecSelfTest : garde sur un vrai dépôt borg jetable** (sauté sans borg) des faits dont dépend « Inchangés »
  (1.0.156) : `nfiles` ne compte que les fichiers ordinaires (ni répertoires, ni lien, ni fifo) ; un `chmod` seul est
  `modified` dans `borg diff` ; « Inchangés » de DiffTop et d'IdxTop égale le décompte `borg list` / `borg diff`
  (répertoire ajouté et supprimé, lien changé, 5 exclus `IDX_EXCLUDE` : modifié, ajouté, supprimé, répertoire ajouté et
  son fichier). Une nouvelle version de borg qui changerait ces comptes fait échouer le contrôle, avec le chemin et la
  version du borg testé, et les sorties de DiffTop et IdxTop. Retour au comptage par familles dans DiffTop ou IdxTop
  (indexés ou exclus) : détecté. Isolé : variables `BORG_*` de l'environnement retirées (`BORG_CACHE_DIR`… primeraient
  sur `BORG_BASE_DIR`), `TMPDIR` du selftest, archives datées (`--timestamp`), attente d'une seconde avant le `chmod`
  (ctime à la seconde sur certains systèmes de fichiers).
- UI : une entrée inconnue de la liste des graphiques par archive lève une erreur (attrapée) au lieu d'être dessinée en
  « Durée ».

## borgHelper 1.0.156 — Inchangés en fichiers ordinaires — 2026-09-29

Chantier « reconstruction progressive », story 19 (actions de rétrospective A21, A23).

- **DiffTop : « Inchangés » en fichiers ordinaires**, comme IdxTop. Mesuré sur borg 1.2.6 : `nfiles` ne compte que les
  fichiers ordinaires (ni répertoires, ni liens, ni fifos), alors que `borg diff` liste aussi `added directory`,
  `removed directory`, `changed link` et des entrées `ctime`/`mtime` pour un répertoire dont le contenu change. DiffTop
  retranchait tout ajout et toute « modification » indexés, répertoires compris : « Inchangés » était sous-estimé et
  différait d'IdxTop. Désormais, seuls les types exacts `added` et `modified` (indexés et exclus) sont retranchés,
  dans les deux commandes. Le détail des exclus (familles, 1.0.155) et le tableau de DiffTop ne changent pas.
  Limites mesurées, documentées dans le README : borg 1.2.6 signale `modified` (+0/−0) dès que le ctime d'un fichier
  change (droits, dates) — compté modifié ; liens physiques comptés une fois dans `nfiles` mais une ligne par nom
  (« Inchangés » sous-estimé) ; lien ou répertoire remplacé par un fichier : ligne `mode` seule, compté inchangé.
  IdxTop cumule les paires qui aboutissent à une même archive, DiffTop n'en lit qu'une.
- La colonne `modifications` de Report mêle aussi répertoires et liens (`XX%nb`, `prev_nf`) : reporté (story à part).
- Docstring de `get_running_bkp_status` corrigée : plusieurs lignes `bkp_status` ouvertes sont possibles
  (`priority.lock` a plusieurs porteurs ; un Bkp tué laisse sa ligne ouverte).
- Tests : même « Inchangés » dans DiffTop et IdxTop sur une paire avec répertoires ajoutés ou supprimés, entrées
  `ctime`/`mode`/`owner`, liens ajoutés ou changés, et exclus de types variés, suppressions comprises (clair et
  chiffré) ; mutations détectées. Vrai dépôt : 32 inchangés sur 37 fichiers, égal au
  décompte réel (`borg list` / `borg diff`).

## borgHelper 1.0.155 / borgHelperWWW 1.28.4 — délai des Bkp par nick, détail des exclus — 2026-09-29

Chantier « reconstruction progressive », story 18 (actions de rétrospective A18, A19, A20).

- **Un Bkp tué suivi d'un Bkp réussi n'est plus « en cours »** (`bkp_running_state` pour `/access` et l'alerte de
  retard ; `get_running_bkp_status` pour `Status`) : une ligne ouverte n'est effacée que par un Bkp plus récent fini en
  succès. Avant, `/access` le gardait « en cours » jusqu'à 6 h après le démarrage du Bkp tué. Décision de l'utilisateur
  en revue : pas « dernière ligne seulement » (règle de `Status` 1.0.154, corrigée ici), car un second Bkp arrêté par le
  verrou du dépôt tenu par un premier, encore vivant, fermait sa ligne en échec et masquait le premier (`/access`
  `false`, alerte de retard possible pendant la sauvegarde). Un Bkp tué suivi d'un échec reste « en cours » jusqu'au
  délai. `timeout_s` y est validé (< 1 s ou invalide : 6 h, plafond 10 ans, `inf` compris).
- **Délai des Bkp par nick** : nouvelle clé rc `BKP_STATUS_TIMEOUT`, dans la section du nick ou en `[DEFAULT]` :
  secondes, ou suffixe `s`/`m`/`h` (`12h` ; attention, `12` seul = 12 s, contrairement à `MAX_AGE_BKP` en heures).
  Priorité : clé, puis variable `BORGHELPERWWW_BKP_STATUS_TIMEOUT` (mêmes formes acceptées), puis 6 h ; vide : la
  variable ; invalide, nulle, négative ou `%` : 6 h. `[WARN]` une fois par nick et par valeur si la valeur est invalide
  ou sous 300 s (un Bkp plus long serait réclamé en échec, et sa vraie fin jamais notifiée). Relue à chaque passage : un
  abaissement s'applique aux Bkp en cours. La CLI et le service lisent chacun leur rc (`-C`, `BORGHELPERWWW_CFGFILE`) :
  même fichier, ou même clé dans les deux. Lue par `Status` et par borgHelperWWW (`/access`, passage de fin du watcher —
  message et alerte Sentry « sans fin après N s » —, alerte de retard) : la CLI et le service disent enfin la même
  chose, et un gros serveur peut avoir un délai plus long. `Status -j` : `bkp_stale` porte `timeout_s`. Nouvelle
  méthode `BorgHelper.bkp_status_timeout(nick)`. Aide `-c Status` complète (`bkp_stale`, `build`, `rebuild`, délai).
- **Détail des exclus par familles** (DiffTop, IdxTop) : `+` tous les ajouts, `-` toutes les suppressions, `=` tout le
  reste, comme Report. Avant, seuls `added`/`removed`/`modified` étaient détaillés (13 exclus affichés « +11 »). IdxTop
  affiche aussi les exclus quand `diff_index` a été vidé par `IdxPurge` (au lieu de « diff_index vide »).
- Docs de 1.0.154 : « IdxStats » corrigé en « IdxTop » (la commande IdxStats n'existe pas).
- Tests : CodecSelfTest (dernière ligne du nick, délai invalide validé ; priorité clé / `[DEFAULT]` / variable / vide /
  invalide / `%` / nick absent ; Status avec la clé du nick ; familles d'exclus, somme = total, DiffTop et IdxTop sur
  une paire vidée) ; push_selftest (`/access` Bkp tué puis fini → `false`, puis en cours → `true` ; clé du nick sur
  `/access`, le watcher et l'alerte de retard, autre nick gardé à 6 h, `extra.timeout_s` de l'alerte Sentry ; Bkp
  vivant suivi d'un échec, égalité de `started_at`, unités, `[WARN]` une seule fois, rc devenu illisible). Gardes
  vérifiées par mutation (23/23).

## borgHelper 1.0.154 — Status sans Bkp fantôme, IdxPurge trace ses exclus — 2026-09-29

Chantier « reconstruction progressive », story 17 (reports des stories 8 et 16).

- **`Status` : un Bkp tué n'est plus « en cours »**. Une ligne `bkp_status` sans fin, démarrée depuis plus de
  `BORGHELPERWWW_BKP_STATUS_TIMEOUT` (défaut 6 h, même lecture que borgHelperWWW : invalide ou < 1 → défaut), s'affiche
  `Bkp sans fin depuis HH:MM (XhYYmin) — probablement interrompu (délai 6 h dépassé)`. Avant, `Status` affichait
  « Bkp en cours » sans limite, alors que `/access` (1.28.1) et le watcher le tenaient déjà pour fini en échec. JSON :
  `bkp_running` vaut alors `null` et le nouveau champ `bkp_stale` porte `{started_at}` (`null` sinon). Un Bkp interrompu
  n'empêche plus la ligne « Opération prioritaire en cours » (libellée « Bkp peut-être toujours actif, Restore, Prune ou
  DelBkp »). Un vrai Bkp de plus de 6 h est affiché « probablement interrompu », comme le watcher le notifie en échec au
  même moment. Seule la dernière ligne du nick compte : un Bkp tué suivi d'autres Bkp n'est plus affiché du tout. Date
  affichée au-delà de 24 h. La variable se lit dans l'environnement de `Status` (shell, cron), pas dans celui du
  service. `get_running_bkp_status` ne rend plus que la dernière ligne du nick si elle est ouverte, et prend un
  `timeout_s` optionnel (clé `stale`, validé comme la variable, plafonné à 10 ans).
- **`IdxPurge` enregistre ce qu'il retire** : les entrées supprimées de `diff_index` rejoignent les exclus de leur paire
  (`diff_excluded_stats`, nombre et taille par type de changement, taille comme à l'Index : taille après, sinon taille
  avant), ajoutés aux exclus déjà présents. Conséquences : la colonne `modifications` de Report, ArchiveHistory et
  IdxTop ne changent plus après une purge (les fichiers purgés comptent comme exclus ; seule exception, un fichier
  `modified` dont la taille après vaut 0 compte ensuite sa taille avant) ; une paire entièrement vidée par `IdxPurge`
  n'est plus « 0 entrée sans exclu », donc plus confondue avec une paire vide à tort (révision de 1.0.153) ; DiffTop
  affiche ses exclus au lieu de « aucune entrée », libellés « IDX_* / IdxPurge » (DiffTop, IdxTop). Agrégat et
  suppression se font sous le même verrou d'écriture (`BEGIN IMMEDIATE`) : une purge ou un Index concurrent ne fait
  jamais compter une ligne non supprimée. Rien n'est écrit en dry-run (`-D`). Les purges faites avant 1.0.154 ne sont
  pas rattrapées.
- Tests : Status (Bkp récent, tué, délai réglé, invalide, nul, négatif ou démesuré, texte du délai, Bkp vivant avec
  verrou sans ligne redondante, interrompu avec opération prioritaire, date au-delà de 24 h, Bkp tué suivi d'un Bkp
  fini ou en cours, JSON, clés de la branche d'erreur) ; IdxPurge (exclus attendus pour chaque motif et chaque règle
  `IDX_*`, identiques en clair et chiffré, rien en dry-run, stats de Report égales avant et après ; exclus existants
  additionnés ; taille après nulle ; deux paires au même `archive_new` ; paire vidée jamais reprise par la révision ;
  ligne retirée par un autre processus pendant la purge). Gardes vérifiées par mutation.

## borgHelper 1.0.153 — diffs tués jamais gardés, paires vides revues — 2026-09-29

Chantier « reconstruction progressive », story 16 (contrôle intermittent `_ix_same_as_full`, reporté en story 14).

- **Défaut du moteur de tranches corrigé** (depuis 1.0.141) : `borg diff` (borg 1.2.6) tué par SIGTERM pendant qu'il
  tourne peut sortir en **code 1 sans aucune sortie** (mesuré). Le moteur acceptait 0 et 1 comme succès : quand
  l'échéance d'une tranche (ou une opération prioritaire) tuait un diff à ce moment, la paire était enregistrée comme
  faite avec 0 changement, et jamais refaite (rapport « 0%nb / — », historique et explorateur incomplets pour cette
  archive). Désormais, une paire dont le borg a reçu un signal du moniteur est toujours jetée et refaite ensuite.
- **Bases en service** (décision de l'utilisateur) : une seule fois par nick et par base (servie ou fantôme), la première
  passe d'`Index` qui refait les paires (diffs dans les natures, après un `borg list` et un rapprochement réussis) retire
  la sentinelle des paires à 0 entrée sans ligne ni exclu ; elles sont refaites (un `borg diff` chacune, sans budget
  pour un Index sans option ; une paire vraiment vide est simplement recalculée). Message
  `<nick>: N paire(s) de diff vide(s) à refaire (1.0.153)`. Jamais avec `-S`, NOIDX, une période `-b`/`-B`, ni dans un
  Index lancé par un Bkp. Base occupée : une tentative de 2 s, puis reporté à la passe suivante. Les paires vides qui
  ont des exclus sont gardées. Limites : une paire vidée par un `IdxPurge -x` d'avant 1.0.153 est refaite aussi
  (relancer l'`IdxPurge`) ; une paire tronquée (code 1 après une sortie partielle, jamais observé) ou tuée hors du
  moniteur (kill externe) n'est pas détectée — `Index --rebuild` reconstruit la base au besoin.
- Tests : `borg diff` simulé qui sort en 1 sans sortie sous SIGTERM (échéance de tranche) : paire jamais marquée, puis
  refaite comme un Index complet (sans le correctif : paire vide gardée — vérifié) ; code 1 non signalé toujours
  gardé ; révision unique (paire refaite avec ses entrées, paire à exclus gardée ; `-S`, `-T stats`, période, Index
  lancé par un Bkp et base verrouillée sans révision ; DB_NAME partagé ; deuxième passe sans révision) ; révision dans
  un fantôme ; `_ix_same_as_full` exige zéro paire vide et affiche l'état de la base par tranches en cas d'écart. Sous forte charge (12 boucles CPU), aucune paire vide ; les contrôles de
  minutage du groupe tranche peuvent alors échouer par base incomplète (budgets de 6 s) — le contrôle d'ordre l'affiche
  au lieu de lever `TypeError`.

## borgHelper 1.0.152 / borgHelperWWW 1.28.3 / UI 1.19.3 — suivi d'un Bkp lancé depuis l'UI — 2026-09-29

Chantier « reconstruction progressive », story 15 (report de la story 8).

- **▶ Backup suivi par `run_id`, sans minutage** (UI) : au clic, l'UI note le dernier Bkp connu du nick ; elle recharge
  la carte une fois dès qu'un Bkp différent apparaît comme fini dans `/access`, ou quand le Bkp vu « en cours » est
  fini. Avant, sans le voir « en cours » au bout de 60 s, elle rechargeait et abandonnait : un Bkp démarré tard
  (`backup()` attend jusqu'à 120 s l'Index, un `borg list` SSH sans délai, des verrous SQLite) puis fini entre deux
  relectures (30 s) n'était jamais rechargé. Une fenêtre fixe plus longue a été écartée en revue : aucun délai ne borne
  le démarrage. Un lancement qui n'écrit jamais `bkp_status` laisse une entrée inerte, sans recharge. Le clic relit
  d'abord `/access` (un Bkp cron fini pendant que l'onglet dormait n'est pas pris pour le nôtre) ; un Bkp cron en cours au
  clic qui finit recharge la carte sans terminer le suivi ; état illisible au clic : la première lecture lisible sert de
  référence ; deux ▶ Backup de suite : deux fins suivies.
- **`GET /access`** (borgHelperWWW) : nouveau champ `bkp_last` par nick lisible — dernier Bkp du nick
  (`run_id`, `started_at`, `finished_at`, `result`), `null` si aucun ou si la lecture est impossible ; jamais de
  création de `history.db`.
- **`BorgHelperDB.last_bkp_status(nick)`** (borgHelper) : cette lecture ; `None` sans ligne ni base, lève si la base
  est illisible.
- Tests : CodecSelfTest (`last_bkp_status`), push_selftest (`/access` `bkp_last` : en cours puis fini, sans ligne,
  base absente jamais créée, illisible → `null`), `borgHelperWWW_ui_test.js` (Bkp non encore écrit après 400 s, en
  cours, fini ; démarrage à 200 s jamais vu en cours ; premier Bkp du nick ; `null` jamais pris pour une fin ni pour
  « en cours » ; Bkp cron en cours au clic ; état illisible au clic ; deux ▶ Backup ; une seule recharge ; `/access` relu
  et relevé avant le lancement ; vérifiés par mutation).

## borgHelper 1.0.151 — _MEI orphelins en fin de selftest — 2026-09-29

Chantier « reconstruction progressive », story 14 (rétrospective : A15 ; F24).

- **`CodecSelfTest`** retire en fin de run (même en échec ou filtré, pas avec `-l`) les `_MEI*` laissés par les borg
  tués pendant le run, dans `/tmp` et le `TMPDIR` de Python. Seulement ceux apparus pendant le run, à l'utilisateur
  courant, utilisés par aucun processus (`_mei_in_use`) et dont rien, arborescence comprise, n'a changé depuis 10 s ;
  un plus récent est attendu (15 s au plus en tout), puis revérifié. Fait après la restauration de l'état global (un
  Ctrl-C pendant l'attente ne laisse rien de modifié). Ligne `/tmp/_MEI* : N orphelin(s) du run retiré(s)` si N > 0 ;
  bilan et code de sortie inchangés. Avant, `_purge_mei_orphans` (après un arrêt de borg, au-delà de 2 min) laissait
  le dernier d'un run (~60 Mo). Production inchangée : le prochain arrêt de borg le retire.
- Tests : contrôle sur de faux répertoires uniquement (orphelin du run retiré ; présent avant, borg vivant, autre
  propriétaire, récent, sous-répertoire actif, modifié pendant l'attente gardés ; récent retiré après attente) ;
  branchement (codec_selftest imbriqué, nettoyage espionné : relevé avant le run, 10 s / 15 s, ligne si N > 0, rien
  avec `-l`).

## borgHelper 1.0.150 — erreurs d'Index marquées — 2026-09-28

Chantier « reconstruction progressive », story 13 (rétrospective : A13 ; F23).

- **Erreurs marquées `[ERREUR]`** (préfixe ajouté en tête de ligne, avec le suffixe de version sur stderr) :
  - `Index` : `borg list` en échec et période `-b`/`-B` invalide (code 1) ; refus de `--rebuild` (code 3 : base
    partagée, illisible, espace disque, migration, fantôme non créé). Le même refus dans une tranche ordinaire, qui
    continue sur la base servie, reste un message simple ;
  - toutes les commandes (décision de l'utilisateur) : première ligne des diagnostics de base, `[ERREUR] DB occupée :
    …`, `[ERREUR] DB corrompue : …`, `[ERREUR] DB : …` (répertoire introuvable, permission, fichier inaccessible,
    impossible d'ouvrir). Elle s'affiche aussi quand l'appelant continue en mode dégradé (purge DIFF_KEEP reportée,
    lecture des mesures, DelBkp), et l'Index de fin de Bkp peut afficher `[ERREUR]` (`borg list` en échec) alors que le
    Bkp sort en 0. Codes de sortie et issue inchangés ; seules les lignes gagnent le préfixe.
- **Message du résultat d'Index** (`index_last.message`) : pour un échec ou un refus, la dernière ligne `[ERREUR]` et son
  détail indenté (2 lignes au plus) ; sans `[ERREUR]`, les 3 dernières lignes non vides sans `[WARN]` (celles du nick
  d'abord), sinon toutes. Avant, un avertissement sans
  rapport pouvait passer en tête (« [WARN] int: GLOB_ARCH absent … | int: période : 'inconnue' … »), et une base
  occupée pouvait donner un message sans l'erreur.
- Tests : `CodecSelfTest` (période après un `[WARN]`, par la CLI et en direct ; `borg list` en échec ; dernière
  `[ERREUR]` et 2 lignes de détail au plus ; repli ; base occupée, corrompue, impossible à ouvrir ; refus `--rebuild`
  réel par la CLI, refus non marqué dans une tranche ordinaire).

## borgHelper 1.0.149 / borgHelperWWW 1.28.2 / UI 1.19.2 — résultat du dernier Index, suppression de base unifiée — 2026-09-28

Chantier « reconstruction progressive », story 12 (rétrospective : A4, A6 ; F11, F3).

- **Résultat du dernier Index par nick** (borgHelper) : chaque `Index` CLI (toutes options, cron, lancé par
  `POST /index`) écrit, après chaque nick, `CACHE_DIR/<conf>-<nick>-index-last.json` (0600, écriture atomique) :
  `{nick, started_at, finished_at, outcome, code, via, message}` (heures ISO avec décalage). `outcome` ∈ `ok`,
  `error` (code 1 ou exception, relancée après écriture), `refused` (code 3, `sys.exit(3)` compris), `busy`
  (« Index déjà en cours »), `deadline` (échéance atteinte pendant l'attente) ; `via` = `http` ou `cli` ; `message` =
  texte de l'exception ou de `sys.exit`, ou dernières lignes d'erreur du nick (500 caractères au plus), vide si `ok`.
  Un `busy`/`deadline` reporte l'échec précédent (`last_failure`) jusqu'au prochain `ok`. Une écriture ratée (disque,
  encodage) n'est qu'un `[WARN]`. Fichier jetable, jamais dans `history.db` ; l'Index de fin de Bkp n'en écrit pas. Nouveaux `BorgHelperDB.index_last_path`, `write_index_last`, `read_index_last`.
  Avant, le résultat d'un Index détaché (sortie vers `DEVNULL`) ou d'un Index cron n'était visible nulle part.
- **`GET /access`** (borgHelperWWW) : nouveau champ `index_last` par nick lisible (ce fichier, `null` s'il est absent ou
  illisible ; lecture locale). `POST /index` pose `BORGHELPER_VIA=http` pour le sous-processus (pas `POST /bkp`).
- **Badges** (UI) : « ⚠ Index en échec » (`error`, `refused`, ou `last_failure`) avec l'heure et le message en
  infobulle, jusqu'au prochain Index réussi ; « ⏸ Index déjà en cours — rien lancé » pour un `busy` venu de `POST /index` il y a moins d'une heure.
- **`_unlink_db`** (borgHelper) : une seule fonction retire une base et ses `-wal`/`-shm` (`_swap_db`, `_vacuum_db`,
  `_shadow_discard`) ; auparavant écrit quatre fois. Aucun changement de comportement.
- Tests : `CodecSelfTest` (ok, erreur via HTTP, déjà en cours avec échec reporté, plusieurs nicks, échéance, refus
  réel par la CLI, `sys.exit`, exception, écriture ratée, fichier illisible, 0600 sous umask 0, file de messages
  tronquée, `_unlink_db`, `_vacuum_db` en échec), push_selftest (`BORGHELPER_VIA` posé pour l'Index seul, `/access`
  `index_last`, JSON invalide ⇒ `null`, vrai fichier du nick remis en place), `borgHelperWWW_ui_test.js` (badges,
  `last_failure`, fuseaux horaires).

## borgHelper 1.0.148 — petits correctifs de fin de chantier — 2026-09-28

Chantier « reconstruction progressive », story 11 (rétrospective : A9, A10, A11 ; F15, R8, D1).

- **Verrous à PID** : la garde contre un PID repris vaut maintenant pour tous (`index-running`, `index-paused`,
  `report-running`, prioritaire), dans `_lock_holder`. Un verrou plus ancien que le processus qui porte son PID compte
  comme mort, y compris quand c'est le processus courant ou un autre utilisateur ; `_owns_lock` suit ce verdict ; un
  PID ≤ 0 compte comme mort. Avant, seul le verrou prioritaire l'était (1.0.145) : un Index tué par SIGKILL dont le PID
  était repris bloquait tout Index du dépôt (« Index déjà en cours »).
  - Marge portée de 2 s (1.0.145) à **1 min** : l'heure de démarrage vient de `btime`, qui suit l'horloge murale.
    Avant, un saut d'horloge de quelques secondes (correction NTP) pouvait faire prendre un verrou vivant pour mort ;
    un saut de plus d'une minute (VM suspendue puis resynchronisée, machine sans horloge matérielle) le peut encore —
    risque accepté. En contrepartie, un PID repris moins d'une minute après l'écriture du verrou n'est pas détecté.
- **Reconstruction limitée** : une tranche `-T` (sans les trois natures) ou `-b/-B` (avec une borne) qui fait avancer
  un fantôme l'avertit : elle ne l'avance que dans ses limites, et il ne sera complet (puis basculé) que lorsque le
  reste aura été couvert (R8). `-b ALL` ne compte pas comme une limite.
- **README** : une seule ligne cron conseillée, `0 * * * * borgHelper -c Index -n ALL -t 20m`, dans les exemples de
  crontab, le bloc Index et la section reconstruction. L'ancien `*/10 … -t 1m` pouvait ne pas couvrir le snapshot
  d'un gros dépôt, première unité depuis 1.0.146. **À faire** : remplacer dans sa crontab une ligne
  `*/10 * * * * … Index -n ALL -t 1m` par la nouvelle ; les lancements qui se chevauchent tournent sur des nicks
  différents (`flock -n` pour n'en garder qu'un).
- Contrôles : verrous à PID repris (`index-running`, `index-paused`, `report-running`, processus courant, autre
  utilisateur, PID 0) ; avertissement du fantôme limité (`-T`, `-b`, `-B` seul, `-b ALL`), bascule quand des tranches
  limitées couvrent tout ; diagnostic « base finie par tranches » montrant le premier écart.

## borgHelper 1.0.147 — CodecSelfTest par groupe — 2026-09-28

Chantier « reconstruction progressive », story 10 (rétrospective : A5 ; F2, F12, F14).

- `CodecSelfTest -f <motif>` n'exécute que les contrôles dont le nom correspond (expression régulière, sans casse).
  - Le bilan annonce un run **PARTIEL**, avec le nombre de contrôles écartés. Le run complet reste exigé avant commit.
  - Code de sortie 2 si le motif est invalide, vide (il sélectionnerait tout) ou ne sélectionne rien, `-l` compris.
  - Un contrôle SKIP (borg absent) compte comme sélectionné. Un échec en run partiel rappelle qu'il peut venir d'un
    contrôle écarté.
  - Exemple : `-f 'tranche|surveillance'`, 15 contrôles en ~4 min au lieu de ~12 min pour 429.
- `CodecSelfTest -l` liste les noms des contrôles sans les exécuter, filtrés par `-f`.
- Sans option : sortie et code de sortie inchangés.
- Nouveau contrôle : `-f` et `-l` en sous-processus (groupe, rien sélectionné, motif invalide, liste).

## borgHelper 1.0.146 — périmètre du nick et ordre des tranches — 2026-09-28

Chantier « reconstruction progressive », story 9 (rétrospective : R6, R7 ; SPEC CAP-6 et spine AD-3 amendés).

- **Périmètre du nick (`GLOB_ARCH`)** : une archive sortie du motif mais encore présente dans le dépôt appartient à une
  autre machine (dépôt partagé). Elle quitte la base du nick **sans aucune écriture dans `history.db`**. Avant, elle
  passait pour disparue : ligne de graphique figée « supprimée » et mesures (non régénérables) retirées.
  - Seule une archive absente du dépôt entier est une disparition.
  - Pour le savoir, un `borg list` sans filtre n'est lancé que si une archive a quitté la liste filtrée, jamais pour un
    nick sans `GLOB_ARCH`. S'il échoue ou est interrompu, le rapprochement est reporté.
  - Vaut pour l'Index, le fantôme, et le nettoyage après Prune et DelBkp. Les lignes figées à tort avant 1.0.146
    restent en place.
- **Tranche** : le snapshot de la dernière archive passe avant les statistiques. Sur un gros dépôt, la dernière archive
  est explorable dès la première tranche (avant : après les `borg info` de toutes les archives).
  C'est la première unité : le budget `-t` doit la couvrir (message « aucune progression » mis à jour).
- ⚠️ Un `GLOB_ARCH` qui exclut des archives de **ce** nick les traite aussi en « autre machine » : elles quittent ses
  graphiques sans y être figées. Si le nick n'en connaît plus que les mesures, celles-ci sont gardées, avec un message
  dédié (« GLOB_ARCH exclut-il des archives de ce nick ? »), et le `borg list` complet est refait à chaque passe.
- Revue : la liste complète interrompue (échéance, opération prioritaire) est distinguée d'une liste en échec ; le
  balayage unique des orphelins ne fige plus d'héritière d'une autre machine ; aucun `borg list` en plus quand rien ne
  manque (contrôlé), ni pour un nick sans filtre ; DelBkp couvert.

## borgHelper 1.0.145 / borgHelperWWW 1.28.1 / UI 1.19.1 — robustesse des verrous, de l'état et des codes de sortie — 2026-09-28

Chantier « reconstruction progressive », story 8 (rétrospective : A3, R1 à R5, R9).

- **Code de sortie d'`Index`** : la CLI sort avec le pire code rendu sur les nicks traités (1 = erreur : `borg list` en
  échec, période refusée… ; 3 = `--rebuild` refusé), tranches et `-S` compris. Index déjà en cours, échéance ou pause :
  0. Avant : 0 sauf pour le code 3, donc un cron ne voyait pas une tranche qui ne pouvait pas démarrer.
- **`priority.lock` par processus** : chaque Bkp, Restore, Prune ou DelBkp tient son propre fichier
  `<…>-priority.lock.<pid>`. Un Restore qui finit pendant un Bkp du même dépôt ne retire plus le verrou du Bkp :
  l'Index en pause attend vraiment la fin du Bkp. Les fichiers de processus morts sont retirés à la lecture.
  L'ancien fichier unique est encore lu (processus d'avant la mise à jour). L'API est inchangée. Un fichier dont le PID
  a été repris par un processus plus récent (porteur tué par SIGKILL) compte comme mort.
  **Mise à jour** : l'inverse n'est pas vrai — un processus d'avant 1.0.145 ne voit pas les nouveaux fichiers.
  Mettre à jour hors de tout `Index` en cours et redémarrer borgHelperWWW (il lit l'état par borgHelper importé).
- **Plus de `borg break-lock`** quand une opération prioritaire interrompt les diffs d'un Index. Il cassait aussi le
  verrou d'un `borg create` externe, d'un `borg mount` ou d'un autre hôte. Les diffs sont maintenant arrêtés par
  SIGTERM (borg rend son verrou), puis SIGKILL après 5 s, comme `boex`.
- **`/tmp/_MEI*`** : un borg (binaire PyInstaller) arrêté par SIGKILL, ou par SIGTERM pendant son démarrage, laisse
  environ 60 Mo dans `/tmp`. Ces répertoires orphelins sont maintenant retirés après tout arrêt de borg, y compris par
  `boex` à l'échéance d'une tranche (depuis 1.0.141, ils s'accumulaient : un CodecSelfTest en laissait 2 Go).
  « Orphelin » = à nous, inchangé depuis 2 min et utilisé par aucun processus d'après `/proc` (bibliothèques mappées,
  répertoire courant, descripteurs). Avant, `fuser` seul jugeait, et un borg vivant lui semblait inutilisé : son
  répertoire pouvait être supprimé.
- CodecSelfTest : budget du contrôle « fantôme par tranches » porté de 3 à 6 s (3 s ne couvraient plus `borg list`,
  le point de taille et une unité sur une machine chargée).
- **DelBkp** : l'archive supprimée disparaît aussitôt des rapports, de l'historique et de l'explorateur
  (rapprochement comme après Prune), sans attendre le prochain Index — sauf si une autre opération prioritaire tourne
  sur le dépôt (reporté au prochain Index). Un rapprochement en échec n'est qu'un avertissement.
- **`Status`** : une base chiffrée sans passphrase (ou en migration) affiche l'erreur sans perdre « Bkp en cours »,
  la reconstruction et l'opération prioritaire, lisibles sans clé.
- borgHelper : `BorgHelperDB.bkp_running_state(nick, timeout_s)` → `True` / `False` / `None` (lecture impossible) ;
  `bkp_running` s'appuie dessus (une seule requête).
- borgHelperWWW 1.28.1 : `/access` `bkp_running` vaut `true` seulement pour un Bkp démarré depuis moins de
  `BKP_STATUS_TIMEOUT`. Un Bkp tué n'est plus affiché « en cours » pour toujours. `null` si la lecture échoue, jamais
  pris pour une fin.
- UI 1.19.1 : le Bkp lancé par ▶ Backup est suivi à part (`loadMachines` écrasait l'indication). Sa fin recharge la
  carte une fois, y compris un Bkp fini avant la première relecture (au bout de 60 s).

## borgHelperWWW 1.28.0 / UI 1.19.0 / borgHelper 1.0.144 — état de construction et dépôts externes dans le web — 2026-09-28

Chantier « reconstruction progressive », story 7 (spine AD-10, AD-12).

- **Refus en amont** : borgHelperWWW vérifie `EXTERNAL_OPS` avant tout borg ou sous-processus (fonction `op_allowed`
  de borgHelper, jamais une liste recopiée) : `403` sur `/bkp`, `/init`, `/login` ; sur `/restore`,
  `/download/file`, `/download/tar` sans `restore` ; sur `/prune`, `/delbkp` sans `prune`/`delete`. `/download/*` et
  `/bkp`, qui ne passent pas par la CLI, sont couverts.
- Code de sortie 4 de la CLI ⇒ **HTTP 403** (au lieu de 400), réponses en cache comprises.
- `GET /access` : par nick lisible, `external`, `ops`, `build`, `rebuild`, `bkp_running` (lectures locales).
- **⚠️ `POST /index` asynchrone** (rupture de compatibilité) : lancement détaché comme `/bkp`, réponse immédiate
  (`stdout` = message de lancement, jamais la sortie de l'Index) ; plus de requête bloquée jusqu'au délai d'expiration
  quand l'Index se met en pause pendant un Bkp. `ALL` et listes acceptés, nick inconnu ⇒ 404.
- Revue : clé API vérifiée avant le refus `EXTERNAL_OPS` (401, jamais un 403 révélateur) ; `nick=ALL` laissé à la
  CLI (nicks refusés écartés) ; configuration illisible ⇒ 500 ; `/access` : `bkp_running` `null` si inconnu, `EXTERNAL`
  invalide ⇒ `external:null`, `ops:["read"]` ; UI : relectures sans chevauchement, fin d'un Bkp court lancé par
  ▶ Backup vue, motif d'un 403 affiché.
- UI 1.19.0 : badges 🔗 externe, ⏳ Bkp en cours, 🏗 construction partielle x/y, ♻ reconstruction ; actions interdites
  masquées (▶ Backup, Bkp/Init/Restore/Prune/DelBkp, 🗑 et ⚡ Prune de l'historique, téléchargements) ; relecture de
  `/access` toutes les 30 s et **rechargement de la carte d'un serveur à la fin de son Bkp** (demande du 2026-09-27).
- borgHelper 1.0.144 : `allowed_ops(cfg, nick)` et `ALL_OPS` (liste des opérations permises pour `/access`).

## borgHelper 1.0.143 — reconstruction dans un fichier fantôme — 2026-09-28

Chantier « reconstruction progressive », story 6 (spine AD-1, AD-2, AD-3, AD-5, AD-6).

- **`Index --rebuild`** : reconstruit `diff.db` dans `<diff.db>.rebuild` pendant que l'ancienne base reste servie
  (explorateur, recherche, rapports, borgHelperWWW inchangés). Les tranches suivantes (`Index -t …`, la ligne cron)
  font d'abord l'incrémental de la base servie, puis avancent le fantôme avec le budget restant. Complet, il remplace
  la base servie d'un coup (`_swap_db`, API backup de SQLite). `--rebuild -F` repart de zéro ; abandon = supprimer le
  fichier `.rebuild`, jamais servi. Base servie absente : construction directe.
- Bascule seulement si un `borg list` frais rend la même liste que la tranche (archive d'un outil externe arrivée
  entre-temps : reportée, rattrapée à la tranche suivante). Opération prioritaire, écriture d'un autre processus ou
  verrou pendant la copie : bascule annulée, base servie intacte, **fantôme gardé** (`_swap_db(keep_new=True)`).
- Chiffrement : l'en-tête de la base servie est recopié tel quel (même DEK), son empreinte notée ; un
  `DbEncrypt`/`DbDecrypt`/`DbRekey` passé entre deux tranches fait jeter le fantôme, qui est refait.
- Refus (code 3, rien créé) : espace libre < 2,2 × la base servie, `diff.db` partagée par `DB_NAME`, base en migration
  de chiffrement.
- `IDX_EXCLUDE`/`IDX_INCLUDE` : `Index` les applique déjà à l'écriture ; juste avant la bascule, la purge d'`IdxPurge`
  passe aussi sur le fantôme (`idxpurge(db_path=)`) pour les lignes indexées avant un changement de motif.
- Le fantôme n'écrit jamais dans `history.db` (ni figeage de graphique, ni retrait de mesures, ni point de taille).
- `Status` : état du fantôme par nick (texte et champ `rebuild` de `-j`).
- Kill -9 à tout moment : base servie intacte, la tranche suivante reprend (unités finies jamais refaites).
- Garde-fous (revue) : `borg list` vide -> fantôme ni avancé ni basculé ; fantôme supprimé pendant une tranche ->
  abandonné ; `-F` ne jette le fantôme que si la création est possible ; `-wal`/`-shm` orphelins supprimés avant la
  création ; base servie illisible -> refus sans jeter le fantôme ; tranche ordinaire refusée -> « reconstruction
  suspendue ».
- Limite : la base reconstruite ne garde que le snapshot de la dernière archive, comme un Index complet.

## borgHelper 1.0.142 / borgHelperWWW 1.27.9 — dépôts borg externes — 2026-09-28

Chantier « reconstruction progressive », story 5 (spine AD-11, AD-12, AD-13, AD-14).

- **Dépôts externes** : une section `EXTERNAL = true` déclare un dépôt dont les archives sont créées hors borgHelper.
  Construit et suivi par `Index` (et la ligne cron par tranches), il est listé, exploré, cherché, comparé, tracé et
  surveillé pour l'âge maximal comme les autres. Aucune clé de Bkp exigée ; `GLOB_ARCH` facultatif (absent = toutes
  les archives du dépôt) ; mesures du passé absentes (trous, jamais d'erreur).
- **`EXTERNAL_OPS`** : lecture toujours permise, `Restore` par défaut, `Prune`/`DelBkp` si listés, `Bkp`/`Init`/`Login`
  jamais. Refus au dispatch, avant tout borg, **code de sortie 4** ; `-n ALL` écarte simplement les nicks refusés.
- Un seul helper (`glob_args`) produit le filtre d'archives, dans borgHelper comme dans borgHelperWWW ; une
  garde du selftest interdit toute autre lecture de `GLOB_ARCH`.
- `Prune` d'un nick interne sans `GLOB_ARCH` refusé (il aurait élagué les archives de tous les hôtes du dépôt).
- `DelBkp` devient une opération prioritaire (verrou, pause de l'Index en cours) comme `Prune`.
- `Stats`/`Mount`/`UMount` sans `MOUNTPOINT` : message au lieu d'une erreur Python.
- `demo.borghelperrc` : section `demo-externe`, remplie par `borg create` brut.
- borgHelperWWW 1.27.9 : téléchargement de la dernière archive via `glob_args` (plus d'erreur sans `GLOB_ARCH`).
  Refus `EXTERNAL_OPS` côté HTTP et UI : story 7 — les routes qui appellent la CLI héritent du refus (code 4) ;
  `/download` et `/bkp` n'y passent pas et ne refusent pas encore.
- Revue : `Prune -n ALL` continue après un nick refusé (`GLOB_ARCH`/`KEEP_*` absent, message) ; `Prune` externe sans
  `KEEP_*` refusé avec message ; `Login` vers un nick externe refusé (code 4) ; `Restore -L` classé lecture ;
  `EXTERNAL` invalide = code 2 ; dépôt vide sans archive : message (code 3) au lieu d'une erreur Python
  (`getlastbkp(..., strict=False)` rend `[]`, utilisé par le premier `Bkp`) ; un Index
  complet sans option efface la demande d'Index en attente ; avertissement si un nick interne n'a pas de `GLOB_ARCH`.
- Bibliothèque (LIBRARY.md) : `glob_args`, `is_external`, `external_ops`, `command_op`, `op_allowed`, `require_op`,
  `OpNotAllowed`.

## borgHelper 1.0.141 — Index par tranches, pause/reprise de l'Index, correction de DIFF_KEEP — 2026-09-27

Chantier « reconstruction progressive », story 4 (spine AD-1, AD-3, AD-4 amendé, AD-10).

- **Index par tranches** : `-t <durée>` (budget par nick : `90`, `5m`, `1h`), `-T stats,snap,diff`, `-b`/`-B`
  (période). Ordre : statistiques (un `borg info` par archive, la plus récente d'abord), snapshot de la dernière
  archive, diffs du plus récent au plus ancien. Chaque morceau est une transaction avec sa sentinelle : jamais refait,
  jamais à moitié écrit. À l'échéance, le `borg` en cours est tué. Priorité basse (`nice` 10, `ionice` idle). Pensé
  pour le cron : `*/10 * * * * borgHelper -c Index -n ALL -t 1m`. Incompatible avec `-F`, `-S`, `-A`.
- **État de construction** (`build_state` dans `diff.db`) : `Status -j` gagne un champ `build`
  (`partial`/`complete`, paires faites/visées) ; `Status` affiche « Construction partielle : X/Y paires ».
- **Surveillance croisée** : Bkp, Restore, Prune et Report mettent un Index en cours en pause, à toute étape (avant :
  seulement pendant les diffs), en une seconde environ au lieu d'attendre jusqu'à 120 s. L'Index reprend seul après
  la fin de l'opération (Index de fin du Bkp compris) : avant, il s'arrêtait et seul le Bkp suivant le relançait.
  Un seul Index par dépôt : un second sort aussitôt (« Index déjà en cours »), au lieu de tourner en parallèle.
  Prune attend désormais l'Index comme Bkp et Restore.
- **Corrigé : `DIFF_KEEP`** relançait à chaque Index le `borg diff` des paires qu'il venait de purger, et gardait la
  paire indexée en dernier plutôt que la plus récente (la paire gardée changeait d'un Index à l'autre). Seules les N
  paires les plus récentes sont désormais calculées et gardées.
- Snapshot incrémental : le `borg list` des fichiers ajoutés passe avant toute écriture (plus de lignes sans
  sentinelle après une interruption) ; lignes orphelines d'un arrêt brutal retirées avant de refaire le snapshot.
- `-S` passe aussi par le verrou d'Index et la pause. Période `-b`/`-B` validée (archive, date `AAAA-MM-JJ…` ou
  `ALL`) : une faute de frappe est refusée au lieu de ne rien sélectionner en silence.
- Revue en trois couches, correctifs : `-F` repris après une pause ne refait plus les paires déjà recalculées ; borg
  arrêté par SIGTERM puis SIGKILL (verrou du dépôt relâché) et `break-lock` réservé aux opérations prioritaires (jamais
  à l'échéance d'une tranche) ; verrou orphelin retiré sans pouvoir voler celui d'un autre processus, repli sans liens
  physiques, PID d'un autre utilisateur jamais pris pour mort ; demande d'arrêt vérifiée aussi entre les phases SQL et
  reprise même si elle a déjà disparu ; Bkp sans tour d'Index → `index-pending` ; `build_state` par nick (`DB_NAME`
  partagé), avec statistiques et snapshot ; avertissement quand une tranche ne progresse pas ; DbEncrypt refuse aussi
  pendant une pause ; `-t` démesuré refusé.
- **Changement de comportement (bibliothèque, cron)** : un Index sans budget lancé pendant une opération prioritaire
  attend sa fin (sans limite) au lieu de sortir aussitôt ; `pause=False` garde l'ancien comportement.
- Bibliothèque (LIBRARY.md) : `index()` gagne `budget`, `natures`, `period`, `pause`, `snap_only` ; `indexsnap()` gagne
  `archives` ; verrous `acquire_index_running_lock`, `release_index_running_lock`, `index_running_owned`,
  `acquire_index_paused_lock`, `release_index_paused_lock`, `check_index_paused`.

## borgHelper 1.0.140 / UI 1.18.0 — archives supprimées hors borgHelper retirées, graphiques gardés 13 mois — 2026-09-27

Chantier « reconstruction progressive », story 3 (spine AD-9, AD-7 amendé).

- **Rapprochement à chaque Index** (sur la liste `borg list` qu'Index obtient déjà, aucun appel borg de plus) et au
  nettoyage après Prune : une archive absente du dépôt (`borg prune`/`borg delete` bruts, `DelBkp`, archive devenue
  hors `GLOB_ARCH`) est retirée de toutes les tables de `diff.db` et ses mesures de `history.db`. Tous les nicks,
  `NOIDX` compris (leur `archive_stats` n'était jamais nettoyée).
- Corrigé : le nettoyage après Prune ne retirait une paire de diff que si l'archive **nouvelle** avait disparu. Une
  archive du milieu supprimée laissait ses événements, et `TreeHist`/`FileHist` proposaient une archive absente. Les
  lignes orphelines héritées sont retirées une seule fois par base au premier Index de cette version.
- Corrigé : une liste d'archives vide effaçait tout l'index. Désormais rien n'est retiré, avec un avertissement.
- **Graphiques sur `STATS_RETENTION_MONTHS` (13 mois) même avec une rétention d'archives courte** : avant de purger
  une archive disparue, sa ligne de graphique (tailles, durée, nombre de fichiers, ajoutés/modifiés/supprimés, C/E,
  taille dédupliquée affichée) est figée dans `history.db` (nouvelle table `archive_chart`). Les comptages de fichiers
  d'une archive restante dont la paire entrante est retirée (archive précédente disparue, `DIFF_KEEP`) sont figés
  aussi. `ArchiveHistory -j` rend les archives présentes et les archives disparues encore dans la rétention, avec un
  nouveau champ `pruned` (booléen) sur chaque ligne.
- UI : les archives supprimées sont atténuées dans les graphiques par archive, infobulle « (supprimée) ».
- Aucune écriture quand rien n'a disparu (cache par périmètre de borgHelperWWW intact). Jamais de compactage lancé par
  Index. Rapprochement reporté si un Bkp d'un autre processus a démarré entre `borg list` et la purge.
- `DIFF_KEEP` retire aussi les `diff_excluded_stats` de la paire purgée (restés seuls, ils donnaient des comptages
  partiels).
- Une archive disparue pendant que `diff.db` était absente n'a rien à figer (hors C/E et taille dédupliquée
  mesurées) : trou dans les graphiques, jamais d'erreur. `HISTORY_DB_SCHEMA_VERSION` inchangée (table ajoutée,
  ignorée sans dommage par 1.0.139).
- `Index` : le refresh des statistiques passe avant `DIFF_KEEP` (dates nécessaires pour figer les comptages au
  premier Index d'un dépôt).
- ⚠️ Modifier `GLOB_ARCH` : les archives hors du nouveau motif sont traitées comme disparues dès l'Index suivant.
  `Index` ne compacte jamais `diff.db` : dépôt élagué hors borgHelper → `IdxPurge` de temps en temps.
- Bibliothèque (LIBRARY.md) : nouvelles méthodes `freeze_archive_chart`, `get_archive_chart` ; `_diff_stats_for_nick`
  accepte `archives=` et `conn=`.
- Revue en trois couches, correctifs : mesures retirées par liste explicite des disparues (la mesure d'un Bkp écrite
  pendant le rapprochement survit) ; balayage unique des orphelins par nick (`diff.db` partagée par `DB_NAME`) ; base
  chiffrée sans clé, mode changé ou `history.db` illisible → message, rien retiré, Index continue (plus de sortie
  du processus) ; `DIFF_KEEP` ne purge rien si le figeage échoue ; nom d'archive réutilisé → jamais de valeurs
  héritées ; compactage après Prune seulement si `diff.db` a perdu des lignes ; message dédié au nettoyage unique ;
  test de rétention indépendant de la longueur du mois.
- Tests : `CodecSelfTest` 384/384 (16 contrôles nouveaux : archive du milieu, plus ancienne, rien de disparu sans
  écriture, liste vide ou `borg list` en échec, `NOIDX`, figeage en échec, rétention, orphelins hérités, `DIFF_KEEP`
  puis disparition, `DIFF_KEEP` en échec, verrou prioritaire d'un autre processus, Bkp concurrent, `DB_NAME` partagé, nom réutilisé, base sans clé, et
  scénario sur vrai dépôt borg) ; `push_selftest` 89/89 ; `ArchiveHistory -j` identique à 1.0.139 hors `pruned`.

## borgHelper 1.0.139 / borgHelperWWW 1.27.8 — `history.db` : les mesures quittent `diff.db`, qui devient jetable — 2026-09-27

Chantier « reconstruction progressive », story 2 (spine AD-7, AD-8, AD-14).

- Nouveau fichier par nick `<conf>-<nick>-history.db`, en clair (aucun chemin), `0600` : il reçoit tout ce qu'aucun
  appel borg ne redonne ensuite — `repo_stats` (tailles du dépôt dans le temps), `bkp_status` (suivi des Bkp pour les
  notifications et `Status`) et, par archive, les compteurs C/E et la taille dédupliquée mesurés au Bkp.
  **C'est désormais la seule base à sauvegarder** : `diff.db` et `cache.db` se reconstruisent depuis le dépôt.
- Migration automatique à la première ouverture de `diff.db` par cette version (commande, route ou watcher), sans
  rien à faire : copie, puis retrait de `diff.db`. Sûre si elle est interrompue ou lancée par plusieurs processus à la
  fois. Seules les mesures prouvées d'un Bkp (C/E connus, ≥ 1.0.117) sont reprises comme telles.
- **Pas de retour arrière** : la `diff.db` migrée passe en version de schéma 10, qu'une version antérieure de
  borgHelper refuse. Pour revenir en arrière, restaurer une copie de `diff.db` faite avant la mise à jour.
- Sorties inchangées (JSON comparés entre 1.0.138 et 1.0.139, hors numéro de version, sur des bases construites par
  de vrais Bkp et Prune, en clair et chiffrée) : `RepoHistory -j`, `ArchiveHistory -j`, `Report -o -j`. La taille dédupliquée affichée
  est la mesure du Bkp si elle existe, sinon celle de `borg info` (comme avant). Un rattrapage d'`Index -F` n'écrase
  plus jamais une mesure.
- `RepoHistory` ne lit plus que `history.db` : elle répond même sans passphrase pour une base chiffrée (aucun chemin
  n'y figure).
- `DbStatus` affiche aussi `history.db` (toujours `plain`, jamais d'avertissement).
- borgHelperWWW : le watcher (notifications de début/fin, alerte « dépassé ») lit `bkp_status` dans `history.db` ; la
  clé du cache par périmètre tient compte de `history.db`.
- Sauvegarder `history.db` (voir README « `history.db` : la seule base à sauvegarder ») : `CACHE_DIR` est souvent
  exclu des sauvegardes. Arrêter les anciens processus (Bkp, borgHelperWWW) avant la mise à jour.
- Bibliothèque (LIBRARY.md) : `store_archive_stats` n'accepte plus `changed_during_backup`/`read_errors` (changement
  cassant) ; nouvelles méthodes `get_history_db`, `store_archive_measure`, `get_archive_measures`,
  `delete_archive_measures`.
- Revue en trois couches, correctifs : migration tenue sous le verrou d'écriture de `diff.db` et état relu sous ce
  verrou (sinon un second processus concurrent sortait sur un faux « DB corrompue ») ; base d'un schéma plus récent
  jamais migrée ; SQLite < 3.35 : colonnes C/E vidées (la migration ne se relance plus) ; mesures des archives
  disparues purgées aussi pour un nick `NOIDX` ou sans `diff.db`, jamais sur une liste d'archives vide ; lecteurs de
  mesures qui ne quittent plus le processus sur une `diff.db` occupée ; `RepoHistory` servie sans `diff.db` ; repli
  par nom d'archive si la date diffère ; filet de `backup()` réparé (variable non définie si l'ouverture échouait).
- Tests : `CodecSelfTest` 368/368 (migration, reprise après kill réaliste, 3 processus concurrents sans échec,
  processus en retard, SQLite < 3.35, schéma plus récent, ancien binaire refusé, tables recréées par un ancien binaire,
  purge après Prune, `diff.db` jetée puis reconstruite, `RepoHistory` sans `diff.db`, `Report -o`, lecture sans
  historique, base chiffrée et `migrating`, Bkp/Prune réels avec mesures) ; `push_selftest` 89/89 (watcher sur une
  base non migrée, alerte de retard avec le vrai « Bkp en cours »).

## borgHelper 1.0.138 — bascule de base sûre (API backup), compactage sans perte d'écriture — 2026-09-27

Chantier « reconstruction progressive », story 1 (AD-6 amendé).

- Nouvelle fonction unique `_swap_db` pour remplacer une base servie : copie par l'API backup de SQLite, par tranches,
  puis checkpoint. Un lecteur voit l'ancienne base ou la nouvelle, jamais un mélange ; les connexions déjà ouvertes
  voient la nouvelle ; les écritures sont conservées. Annulable si un Bkp/Restore/Prune démarre.
- `_vacuum_db` (après `Prune` et `IdxPurge`) l'utilise au lieu de `os.replace`. Mesuré : avec un WAL non vide,
  `os.replace` faisait rejouer l'ancien WAL sur la nouvelle base (lectures en erreur, ancien contenu réapparu).
- Correction au passage : une écriture faite par un autre processus entre la copie et le remplacement était écrasée
  sans message. Le compactage est désormais reporté (une nouvelle tentative) si la base a changé entre-temps.
- La copie de compactage porte le PID (`.vacuum_tmp.<pid>`) : deux compactages simultanés (IdxPurge et Prune ne
  partagent aucun verrou) ne peuvent plus supprimer la copie l'un de l'autre, ce qui aurait fait recopier une base
  vide sur la base servie. `_swap_db` refuse de toute façon une copie absente, vide ou d'une seule page. Les restes
  orphelins (processus disparu, ancien nom `.vacuum_tmp`) sont nettoyés au compactage suivant.
- Base verrouillée par un écrivain au moment de la copie : l'annulation (Bkp qui démarre) reste sondée pendant
  l'attente, et l'attente est bornée (`busy`, 120 s). Les checkpoints de fin et de début de compactage n'attendent plus
  (un `TRUNCATE` en attente bloque les nouveaux écrivains, jusqu'à 60 s si un lecteur était en cours).
- Compactage reporté d'emblée si une opération prioritaire est déjà en cours (pas de copie inutile). Chemin passé en
  paramètre à `VACUUM INTO` (un répertoire de cache contenant une apostrophe faisait échouer le compactage).
- `priority.lock` est écrit de façon atomique : lu pile entre sa troncature et son écriture, il pouvait être pris pour
  un verrou orphelin et supprimé, faisant perdre sa protection à un Bkp (défaut ancien, exposé davantage par la bascule
  qui le sonde à chaque tranche).
- Erreurs de fichier (`OSError`) du compactage rattrapées : elles ne font plus échouer Prune/IdxPurge après la purge.
- Procédure manuelle de LIBRARY.md corrigée : le `mv` (dangereux sur une base ouverte) est remplacé par une recopie
  par l'API backup ; le conseil « mv » affiché en cas d'échec est retiré.
- Coût : pendant la copie, le disque porte la base servie + son WAL + la copie ; les écritures attendent la fin
  (100 Mo : environ 0,5 s).
- `CodecSelfTest` 354/354 : lecteurs éphémères et persistants avec WAL non vide ; WAL non vide + 4 lecteurs + écrivain
  persistant pendant 5 compactages (aucun commit perdu) ; écriture après préparation → `changed`, rien d'écrasé, deux
  essais puis report ; annulation ; compactage sous `priority.lock` d'un autre processus (reporté) et de ce processus
  (effectué, cas de Prune) ; copie absente ou vide refusée ; base verrouillée : annulable, attente bornée ; kill -9 au
  milieu de la copie ; compactage d'une base chiffrée. Revue en trois couches (29 constats triés, voir la spec de story). Vérifié aussi en
  fonctionnement : borgHelperWWW interrogé en boucle pendant un `IdxPurge` de 200 000 entrées (75 → 21 Mo), 20/20
  réponses correctes.

## borgHelperWWW 1.27.7 — un `sys.exit` de borgHelper dans une route n'arrête plus le serveur — 2026-09-27

Suite de 1.27.6, qui protégeait le watcher.

- Les fonctions de borgHelper appelées dans le processus de borgHelperWWW (`cfgread`, `ensure_*_db`…) font
  `sys.exit` sur un rc invalide ou une base occupée ou corrompue. Dans une route HTTP, ce `SystemExit` rendait le
  serveur muet : processus vivant mais plus aucune connexion acceptée (vérifié sous uvicorn, route sync et async).
- Toutes les routes (`app` et `router`) utilisent désormais une classe de route qui convertit ce `SystemExit` en
  réponse 500 (« borgHelper s'est arrêté pendant cette requête… »), journalisée sur stderr, et le serveur continue.
  Un filet autour de toute l'application ne suffisait pas : le middleware http exécute la route dans une tâche
  asyncio séparée, où `SystemExit` arrête la boucle.
- `push_selftest` 87/87 : un `sys.exit` pendant `GET /access` donne un 500, `/healthz` répond ensuite, et aucune
  route n'échappe à la protection (contrôle sur toutes les routes).

## borgHelper 1.0.137 / borgHelperWWW 1.27.6 — « DB corrompue : database is locked » qui arrêtait borgHelperWWW — 2026-09-27

Symptôme constaté en production (borgHelperWWW 1.27.5) : `DB corrompue : …-diff.db -> database is locked — Supprimez le
fichier…`, puis arrêt complet de borgHelperWWW (`SystemExit: 1` depuis le watcher `bkp_status`).

- **Cause** : `VACUUM INTO`, utilisé par le compactage après `Prune`/`IdxPurge`, produit une base en mode journal
  `delete`, et `diff.db` restait ainsi hors WAL. L'ouverture suivante relançait `PRAGMA journal_mode=WAL`, qui exige un
  accès exclusif et échoue immédiatement quand un autre processus (Index, Bkp, lecture) a la base ouverte.
- **borgHelper** : le compactage remet la base en WAL (et vide le WAL avant la copie). Le passage en WAL n'est plus
  demandé que si nécessaire ; s'il est refusé pour cause de verrou, la base reste utilisable dans son mode courant et
  repasse en WAL à la prochaine ouverture sans concurrent. Une base déjà hors WAL après une ancienne version se répare
  donc seule. `ensure_diff_db`/`ensure_cache_db` attendent jusqu'à 60 s un verrou, comme les autres ouvertures (5 s
  auparavant).
- **borgHelper** : un verrou n'est plus présenté comme une corruption. Nouveau message « DB occupée … réessayer plus
  tard (ne PAS supprimer le fichier) ». Supprimer `diff.db` sur ce conseil faisait perdre l'historique mesuré
  (tailles du dépôt, compteurs C/E).
- **borgHelperWWW** : le watcher (passage par nick et boucle) absorbe aussi `SystemExit`, que borgHelper lève sur une
  base occupée ou corrompue. Le nick concerné est sauté et réessayé au passage suivant, les autres sont traités, et le
  serveur ne s'arrête plus.
- Contrôles : `CodecSelfTest` 345/345 (compactage qui garde le WAL ; base hors WAL + écrivain actif : le `PRAGMA` brut
  échoue, `ensure_diff_db` passe ; verrou ≠ corruption), `push_selftest` 86/86 (le watcher survit à un `sys.exit` sur
  un nick et traite les suivants).

## borgHelperWWW 1.27.5 — hors périmètre : vraie réponse « introuvable » au lieu d'une imitation — 2026-09-27

Issu de l'entretien `deferred-work.md` (point 8, option D).

- Pour un utilisateur limité par `GROUPS_PATHS`, une restauration ou un téléchargement hors de son périmètre doit
  répondre comme pour un chemin inexistant (sans révéler que le chemin existe). Cette réponse était **imitée** à la
  main, et avait dérivé : pour un **joker**, l'imitation renvoyait code 1 et « Include pattern … never matched. »
  alors que la vraie réponse est code 0 sans ce message ; elle était aussi instantanée. On pouvait donc distinguer
  « hors périmètre » de « n'existe pas ».
- Désormais la vraie commande est exécutée sur un **leurre** inexistant de même forme, et le leurre est remplacé par
  le chemin demandé : réponse identique par construction (texte, code, contenu, nom de fichier, temps), quelles que
  soient les versions. Rien n'est extrait. Imitations et libellés recopiés supprimés.
- `push_selftest` 85/85 : les quatre routes (restauration, droits, fichier, `.tar`), avec et sans joker, comparées à
  la vraie réponse d'un chemin absent sur le dépôt de démo.

## borgHelper 1.0.136 — test de la capture `repo_stats` sur un vrai borg — 2026-09-27

Issu de l'entretien `deferred-work.md` (point 9, option B).

- `CodecSelfTest` crée un dépôt borg jetable, lance deux Bkp puis un Prune réels et vérifie les points `repo_stats`
  (`bkp`, `bkp`, `prune`, tailles renseignées) : l'enchaînement réel et le format de `borg info --json` de la version
  installée sont désormais couverts. `BORG_BASE_DIR` temporaire ; sauté sans borg. 344/344.

## borgHelper 1.0.135 — recherche (TreeFind) deux fois plus rapide à la racine — 2026-09-27

Issu de l'entretien `deferred-work.md` (point 7 : mesurer puis optimiser).

- Mesure (250 000 lignes d'historique) : à la racine, la détection des fichiers supprimés prenait ~1,0 s sur 1,3 s.
  Nouvelle requête (seules les suppressions sont examinées, chacune par une recherche indexée) : mêmes résultats,
  recherche 🔍 de l'explorateur **1,18 → 0,60 s** en clair, **1,24 → 0,85 s** en base chiffrée.
- Sorties identiques à la version précédente sur 48 cas ; `CodecSelfTest` 343/343.

## borgHelperWWW 1.27.4 / borgHelperWWW_ui.html 1.17.2 — abonnements push réalignés sur les droits — 2026-09-27

Issu de l'entretien `deferred-work.md` (point 4, option B).

- À chaque visite de la page Notifications, la liste des hosts de l'abonnement est réalignée sur les droits
  **actuels** : un host devenu inaccessible est retiré (plus aucune notification), un host nouvellement accessible est
  ajouté **décoché** ; message « Liste des hosts mise à jour… » quand quelque chose change. Nouvelle route
  `POST /push/subscribe/sync`.
- Le watcher retire des abonnements, toutes les heures, les serveurs qui n'existent plus dans le rc.
- Limite : un abonné qui a perdu des droits sans revenir sur la page reste notifié jusqu'à l'expiration de son
  abonnement (30 jours par défaut). `push_selftest` 84/84.

## borgHelperWWW 1.27.3 — `/cacheinfo` et `/cacheclean` couvrent le cache par périmètre — 2026-09-27

Issu de l'entretien `deferred-work.md` (point 3, option A).

- `GET /cacheinfo` : en plus des caches de borgHelper, lignes de `scopecache.db` (réponses filtrées par
  `GROUPS_PATHS`) par serveur, date de la plus ancienne, taille du fichier.
- `POST /cacheclean` : purge aussi les lignes de ces serveurs dans `scopecache.db` (les autres restent). Plus besoin de
  supprimer le fichier à la main. `push_selftest` 83/83.

## borgHelperWWW 1.27.2 / borgHelperWWW_ui.html 1.17.1 — coupe-circuit des notifications push — 2026-09-27

Issu de l'entretien `deferred-work.md` (point 2, options A + C).

- `BORGHELPERWWW_PUSH_DISABLED=1` : suspend l'envoi de toutes les notifications push (journal seulement) ;
  `POST /push/test` répond `503`, la page Notifications affiche un bandeau, les réglages des abonnés sont conservés.
- `PUSH_MUTE = true` dans le rc (par serveur ou `[DEFAULT]`) : pause des notifications de ce serveur, prise en compte
  sans redémarrage — pour une maintenance. Une alerte « sauvegarde en retard » n'est pas perdue : elle part à la
  reprise si le retard persiste. Les fins de sauvegarde pendant la pause ne sont pas rejouées (pas de rafale).
- Sentry non concerné (réglage `SENTRY_ALERTS`). `push_selftest` 82/82.

## borgHelper 1.0.134 / borgHelperWWW 1.27.1 / borgHelperWWW_ui.html 1.17.0 — badge « base non chiffrée » — 2026-09-27

Issu de l'entretien `deferred-work.md` (point 1, story 5b) : badge seulement pour les anomalies.

- Liste des serveurs et page d'un serveur : **🔓 base non chiffrée** quand `diff.db` ou `cache.db` est en clair alors que
  `DB_ENCRYPT` est actif et qu'une passphrase est disponible (même condition que l'avertissement du CLI) ; la bulle
  donne la commande `borgHelper -c DbEncrypt -n <serveur> -y`. Rien pour une base chiffrée ni pour `DB_ENCRYPT=false`.
- `GET /access` : champ `db_plain` par serveur (vide pour un serveur sans droit).
- `CodecSelfTest` 343/343, `push_selftest` 80/80, badge vérifié dans Chrome headless (liste et page serveur).

## borgHelperWWW_ui.html 1.16.2 — notice sur les droits : seule sous l'explorateur — 2026-09-27

- Retour utilisateur : la notice sous l'explorateur suffit — bulles ⓘ des en-têtes Droits/Propriétaire retirées.

## borgHelperWWW_ui.html 1.16.1 — notice sur les droits dans l'explorateur — 2026-09-27

Demande utilisateur : ajouter une notice quant aux droits.

- Explorateur : notice permanente (tous modes : normal, archive épinglée, changements) et bulle ⓘ sur les colonnes
  Droits et Propriétaire — elles montrent le **dernier état connu** (plus récente sauvegarde indexée contenant
  l'entrée), pas forcément celui de la sauvegarde épinglée ou comparée ; inconnus (—) pour une entrée supprimée ;
  pour les droits exacts d'une sauvegarde : téléchargement `.tar` « préserve les droits d'accès ». Auparavant, seuls
  les modes épinglé et changements le mentionnaient, en fin de phrase.
- Vérifié : notice visible dans les trois modes (Chrome headless), routeur UI 39/39.

## borgHelper 1.0.133 / borgHelperWWW 1.27.0 / borgHelperWWW_ui.html 1.16.0 — explorateur : changements entre deux sauvegardes — 2026-09-27

Demande utilisateur : dans l'explorateur, n'afficher que les fichiers qui ont changé (ou disparu) entre deux
sauvegardes choisies.

- Explorateur web : affichage **« Changements entre deux sauvegardes »**, avec « Depuis » (état de départ, exclue) et
  « Jusqu'à » (incluse). Seules les entrées ajoutées, modifiées ou supprimées s'affichent, avec leurs événements ; un
  dossier apparaît dès qu'un changement a eu lieu en dessous et on y descend en restant dans ce mode. Par défaut :
  avant-dernière → dernière sauvegarde. Bouton **🔀 Changements** dans l'Historique complet (depuis la sauvegarde
  précédente). Mode reflété dans l'adresse (`?depuis=A&jusqua=B`) et le titre de l'onglet.
- CLI : `TreeHist -X` (avec `-b`/`-B`), même résultat. Rapide aussi en base chiffrée (un décodage par entrée
  affichée). Erreur claire si une archive est inconnue ou si les bornes sont inversées.
- borgHelperWWW : `/treehist?changes=true`, compris dans la clé du cache par périmètre.
- Vérifié : `CodecSelfTest` 342/342 (sémantique + parité clair/chiffré), `push_selftest` 79/79, routeur UI 39/39,
  parcours Chrome headless 10/10 sur un dépôt borg de test (fichier, répertoire, lien, fifo), non-régression des
  parcours précédents.

## borgHelper 1.0.132 / borgHelperWWW 1.26.8 — Sentry : erreurs logicielles et alertes demandées seulement — 2026-09-27

Demande utilisateur : Sentry ne doit recevoir que les erreurs logicielles, plus un réglage pour être alerté d'une
sauvegarde en échec ou trop ancienne.

- Plus aucune trace de performance envoyée (auparavant une par invocation de borgHelper, donc à chaque clic de
  l'interface web). Restent les erreurs logicielles (exceptions non prévues).
- Nouveau réglage `SENTRY_ALERTS` dans le rc (par serveur ou `[DEFAULT]`, désactivé par défaut) : `bkp_error`
  (sauvegarde en échec — envoyée par borgHelper ; ou bloquée — constatée par borgHelperWWW), `overdue` (dernière
  sauvegarde plus vieille que `MAX_AGE_BKP` — constatée par borgHelperWWW, rappel à chaque période, indépendamment
  des notifications push), `all` pour les deux. Événement Sentry de niveau `error`, étiqueté `alert`/`nick`, une issue
  par type et par serveur.
- `CodecSelfTest` 341/341, `push_selftest` 79/79 (faux transport Sentry, aucun envoi réel).

## borgHelperWWW 1.26.7 — contrôles automatiques manquants — 2026-09-27

Issu de `deferred-work.md` (lot A : vérifications absentes). Aucun changement de comportement.

- `push_selftest` 78/78, nouveaux contrôles :
  - chaque paramètre des 9 routes servies par le cache de périmètre figure dans la clé de cache (analyse du code des
    routes — un paramètre oublié ferait servir le résultat d'une autre requête, ex. IdxTop `topn=5` pour `topn=50`) ;
    vérifié par mutation (retirer `topn` de la clé d'IdxTop est détecté). `json_output` exempté : sans effet dans la
    branche à périmètre, toujours en JSON ;
  - cache : paramètres différents → miss, identiques → hit ; `scopecache.db` impossible à ouvrir → miss silencieux ;
  - routes `/repohistory` et `/archivehistory` de bout en bout en HTTP.

## borgHelper 1.0.131 / borgHelperWWW 1.26.6 — structure des bases contrôlée, y compris en continu — 2026-09-27

Issu de `deferred-work.md` (point B10 : « comparaison régulière, borgHelperWWW restant tout le temps démarré »).

- La vue `archive_snapshot_v` de chaque base est comparée à la définition du code et recréée si elle diffère (avant :
  seulement si elle manquait — une évolution de sa définition ne se serait jamais appliquée aux bases existantes).
  Rien n'est réécrit quand elle est identique ; une base d'une version plus récente n'est jamais touchée.
- borgHelperWWW refait ce contrôle au démarrage puis toutes les heures (`BORGHELPERWWW_SCHEMA_CHECK_INTERVAL`), et
  signale une fois `[WARN] … redémarrer borgHelperWWW` si borgHelper a été mis à jour sur disque depuis son démarrage
  (il ne répare alors rien : son code en mémoire est périmé).
- `CodecSelfTest` 339/339, `push_selftest` 75/75.

## borgHelper 1.0.130 — Sentry : chemins masqués aussi dans le texte des erreurs — 2026-09-27

Issu de `deferred-work.md` (point B9).

- Avant envoi à Sentry, le texte libre des événements (message d'exception, message, journal, fils d'Ariane) est
  filtré : tout ce qui ressemble à un chemin devient `<chemin>` (absolu, relatif, `~/`, URL de dépôt `ssh://…`), et la
  passphrase du processus `[redacted]`. Auparavant seuls les champs structurés l'étaient : un
  `FileNotFoundError: /home/…` partait tel quel. Filtre volontairement large (« 3/4 » est aussi masqué).
- `CodecSelfTest` 338/338.

## borgHelperWWW 1.26.5 — purge des lignes de cache restées en clair — 2026-09-27

Complément du correctif de sécurité de 1.26.4.

- Les lignes de `scopecache.db` écrites en clair pour un serveur avant son `DbEncrypt` (par une version antérieure
  qui le croyait encore en clair) sont supprimées dès que borgHelperWWW constate que la base est chiffrée — y compris
  après un redémarrage. Aucune action manuelle nécessaire.
- `push_selftest` 74/74 (contrôle étendu, désormais sur un `scopecache.db` temporaire).

## borgHelperWWW 1.26.4 / borgHelper 1.0.129 — chiffrement modifié en CLI pris en compte sans redémarrage — 2026-09-27

Issu de `deferred-work.md` (point B8).

- borgHelperWWW relit l'en-tête de chiffrement d'une base à chaque usage de son memo de codec : un `DbEncrypt`,
  `DbDecrypt` ou `DbRekey` lancé en CLI pendant qu'il tourne est pris en compte immédiatement.
- **Correctif de sécurité** trouvé en traitant ce point : après un `DbEncrypt` CLI, borgHelperWWW continuait (jusqu'à
  son redémarrage) de considérer la base comme non chiffrée et **écrivait en clair** les lignes de son cache de
  périmètre (`scopecache.db`, chemins compris) pour ce serveur. Reproduit sur la version précédente, corrigé.
- borgHelper 1.0.129 : messages et aide de `DbRekey` sans consigne de redémarrage (texte seulement).
- Vérifié : base en clair → `DbEncrypt` CLI → chiffrée → `DbDecrypt` CLI → en clair, sans redémarrage ;
  `push_selftest` 74/74 (nouveau contrôle : en-tête chiffré posé pendant que le memo est chaud).

## borgHelper 1.0.128 — mémo de décodage : éviction de moitié — 2026-09-27

Issu de `deferred-work.md` (lot A).

- Bases chiffrées : le mémo de décodage des chemins (262 144 entrées) était vidé d'un seul coup une fois plein —
  sur une grosse base, les répertoires les plus fréquents étaient recalculés sans cesse. Il retire désormais la
  moitié la plus ancienne. Aucune incidence sur la vérification des chemins. `CodecSelfTest` 337/337.

## borgHelper 1.0.127 / borgHelperWWW 1.26.3 — historiques bornés à 13 mois, purges manquantes — 2026-09-27

Issu de `deferred-work.md` (point B4 « bornage par défaut surchargeable, 13 mois », plus lot A).

- Graphiques : les séries `RepoHistory`/`ArchiveHistory` couvrent les `STATS_RETENTION_MONTHS` derniers mois (13 par
  défaut — une vue annuelle complète —, surchargeable par nick dans le rc). Les statistiques des archives plus
  anciennes restent en base tant que l'archive existe (Report, Historique complet) ; elles partent au Prune réel.
- `bkp_status` (suivi des sauvegardes pour les notifications) : purgé au-delà de `STATS_RETENTION_MONTHS`, au
  démarrage d'une sauvegarde (croissance auparavant illimitée).
- Ordre stable à date d'archive égale (ArchiveHistory, Report).
- borgHelperWWW : abonnements push expirés retirés du fichier de préférences et de `push.db` (au plus tard une heure
  après expiration ; auparavant jamais nettoyés) ; `BORGHELPERWWW_PUSH_VAPID_SUB` invalide signalé dès le démarrage.
- `CodecSelfTest` 337/337, `push_selftest` 73/73 (nouveaux : bornage des séries, rétention `bkp_status`, purge push,
  `expires_in_days=0` via la route).

## borgHelper 1.0.126 / borgHelperWWW 1.26.2 — entrées supprimées : tous les types, avec leur vrai genre — 2026-09-27

Issu de `deferred-work.md` (point B5, « rajout du type »). En le traitant : **bug plus large que prévu**.

- **Répertoires, liens symboliques, fifos, périphériques supprimés n'apparaissaient pas du tout** dans `TreeHist`
  (explorateur web compris) ni dans `TreeFind` : seul `change_type='removed'` (fichier ordinaire) était reconnu,
  alors que borg diff émet `removed directory`, `removed link`, `removed fifo`… Ils sont désormais listés comme
  supprimés, avec leur **vrai genre** (plus d'heuristique « pas de taille = répertoire », qui classait un lien en
  répertoire). Un répertoire supprimé reste explorable.
- Aucune colonne ni migration : le type est déjà dans `change_type` — les données déjà indexées sont corrigées
  immédiatement, sans réindexation.
- `removed fifo|chrdev|blkdev` et `added fifo|chrdev|blkdev` manquaient aux listes de types : l'index incrémental ne
  retirait pas une fifo/un périphérique supprimé du snapshot.
- `DiffBkp` : suppressions et ajouts de répertoires/liens/fifos comptés en `-`/`+` (étaient en `=`), type affiché
  (`[removed directory]`) ; `DiffTop` et borgHelperWWW (DiffBkp/DiffTop filtrés par périmètre) : même comptage.
- Vérifié sur un dépôt borg de test (fichier, répertoire vide et non vide, lien, fifo créés puis supprimés, puis
  archive incrémentale). `CodecSelfTest` 335/335, `push_selftest` 71/71.

## borgHelper 1.0.125 / borgHelperWWW 1.26.1 — DuIdx : motif groupé honoré en entier — 2026-09-27

Issu de `deferred-work.md` (point B1, passé en lot A : « honorer le motif »).

- `DuIdx -f 'home/*_old'` agissait comme `home/*` (tout ce qui suivait le dernier `/*` était ignoré sans prévenir) ;
  `a/b*/c/*` échouait. Désormais chaque composant du motif filtre le composant de même rang du chemin (`*`/`?` ne
  franchissent pas `/`), regroupement à la profondeur du motif : `home/*_old`, `home/*/.cache`, `lib/modules/*/kernel`.
- `foo/*` et `*` : sortie strictement identique (36 combinaisons comparées à la version précédente).
- borgHelperWWW 1.26.1 : même règle pour le regroupement après filtrage par périmètre (fonction importée de
  borgHelper, plus de recopie) ; résultat identique au CLI sur 5 motifs. `push_selftest` 71/71.
- `CodecSelfTest` 334/334.

## borgHelper 1.0.124 — robustesse des bases (erreurs de chiffrement, migrations, connexions) — 2026-09-27

Issu de `deferred-work.md` (lot A).

- **Base chiffrée, passphrase fausse ou absente** : toutes les commandes de lecture (TreeHist, Search, DuIdx, IdxTop,
  DiffTop, RepoHistory, ArchiveHistory, FileHist, TreeFind…) plantaient avec une trace Python — **envoyée à Sentry**
  quand il est configuré. Désormais `[ERREUR] DbKeyError : <nick>: passphrase incorrecte ou en-tête altéré`, code 2,
  jamais de trace ni d'événement Sentry. Même traitement pour `DbModeError` (migration en cours), `DbTamperError`,
  `DbCodecError`.
- **Base illisible** (fichier corrompu, pas une base SQLite) : auparavant ouverte comme « non chiffrée » faute de
  pouvoir lire l'en-tête ; désormais refusée (`DbTamperError : <nick>: base illisible, mode de chiffrement
  invérifiable`). `DbStatus` l'affiche comme en-tête invalide et continue avec les autres bases.
- **Migrations de schéma atomiques** (`repo_stats`, `archive_snapshot`) : une seule transaction, ROLLBACK sur erreur —
  un crash entre `DROP TABLE` et `RENAME` ne peut plus laisser `diff.db` sans la table.
- Connexions SQLite fermées sur erreur dans DuIdx, IdxTop, DiffTop (10 sites).
- Prune/Report : un JSON `borg info` tronqué ou inattendu n'est plus une exception non attrapée.
- `CodecSelfTest` 333/333 (nouveaux : migration interrompue après `DROP TABLE`, passphrase fausse en vrai
  processus CLI). Sorties inchangées (IdxTop, DiffTop, DuIdx, Report, clair et chiffré, comparées à 1.0.120).

## borgHelper 1.0.123 — réécriture atomique du rc — 2026-09-27

Issu de `deferred-work.md` (lot A).

- `Login` (`cfgwrite`) réécrivait le `.borghelperrc` en place (troncature puis écriture) : un crash au milieu perdait
  le fichier qui contient les passphrases. Désormais fichier temporaire dans le même répertoire, `fsync`, puis
  remplacement atomique. Droits et propriétaire du rc existant conservés (0600 à la création) ; si le rc est un
  lien symbolique, c'est sa cible qui est remplacée.
- `CodecSelfTest` 331/331 (nouveau : crash simulé en cours d'écriture → rc intact, aucun temporaire résiduel).

## borgHelper 1.0.122 — restauration par joker réparée — 2026-09-27

Issu de `deferred-work.md` (lot A, traité avec l'utilisateur).

- `Restore -f` avec `*`/`?` (et `Restore -L`) **n'avait jamais fonctionné** : borg 1.2 refuse `--pattern=sh:X` (un
  opérateur `+`/`-` est obligatoire) et plantait. Désormais `--pattern=+sh:X --pattern=-sh:**` : inclure le motif puis
  exclure le reste — un `+` seul ne restreindrait rien. Vérifié sur la démo : motif
  `lib/modules/*/kernel/drivers/net/ethernet/intel/e1000*/*` → 4 fichiers restaurés sur 15 244 ; `modules.de?` → 1.

## borgHelper 1.0.121 — explorateur des bases chiffrées : décodage limité aux enfants directs — 2026-09-27

Demande utilisateur : réaliser la « piste 2 » de l'étude d'accélération de l'exploration des bases chiffrées.

- `TreeHist` sur base chiffrée ne décode plus que le répertoire listé et ses enfants directs, au lieu de chaque
  chemin de la sous-arborescence : SQLite sépare enfants directs et descendants sur la valeur stockée (le `/` n'est
  pas chiffré), Python ne décode qu'une valeur par entrée affichée (`…/kernel` de la démo : 6 474 → 15).
- **Compromis accepté** : une altération de la base sur un chemin plus profond qu'un enfant direct n'est signalée
  qu'en descendant jusqu'à lui (ou par `TreeFind`/`Search`, qui vérifient tout). Le répertoire affiché et ses
  enfants restent vérifiés.
- Mesures : listing seul ~330 → ~90 ms (`…/kernel/drivers`) ; `PerfBench` 250k, `TreeHist` racine chiffré
  2,9–4,2 s → 1,4–1,6 s, au niveau d'une base claire. Sorties identiques (14 cas, clair/chiffré, avant/après).
- `CodecSelfTest` 330/330 : le contrôle d'altération profonde à la racine est remplacé par le nouveau contrat
  (2e segment altéré → racine affichée, détecté en descendant ; 1er segment → détecté à la racine).
- Base non chiffrée : inchangé.

## borgHelperWWW_ui.html 1.15.0 / borgHelperWWW_sw.js 1.3.0 — clic de notification vers le serveur, titre par page — 2026-09-27

Demande utilisateur : clic de notification vers `/serveur/<nick>` ; titre de la page/onglet propre à
chaque page.

- Clic sur une notification push : page du serveur concerné (`/serveur/<nick>`, `/` pour la
  notification de test). Onglet borgHelperWWW déjà ouvert : il y va sans se recharger (Précédent
  ramène à la page d'avant) et passe au premier plan ; sinon nouvel onglet (connexion d'abord). Droits
  vérifiés comme pour un lien partagé.
- Titre de l'onglet par page : `🖥 <nick>`, `🗂 <nick>:/<chemin> [@ <archive>]`,
  `📜 <nick> — Historique`, `Serveurs`, `🔔 Notifications`, `Connexion` (+ « — borgHelperWWW »).
- `borgHelperWWW_ui_test.js` couvre aussi les titres (33 cas).
- borgHelperWWW inchangé, mais **à redémarrer** : il lit `borgHelperWWW_sw.js` une seule fois au
  démarrage. Le navigateur récupère ensuite le nouveau Service Worker de lui-même.
- Vérifié : test Node 33/33 ; Chrome headless (script ponctuel) : titres, clic de notification via le
  vrai Service Worker, parcours précédent 27/27 ; `push_selftest` 71/71.

## borgHelperWWW_ui.html 1.14.0 — test du routeur versionné — 2026-09-27

Demande utilisateur : versionner le test du routeur des adresses partageables.

- Nouveau `borgHelperWWW_ui_test.js` : `node borgHelperWWW_ui_test.js [chemin du HTML]`. Node seul, sans
  dépendance ni navigateur ; extrait `routePath`/`parseRoute` de `borgHelperWWW_ui.html` et vérifie 25
  cas (analyse, adresses invalides, aller-retour d'encodage, archive épinglée). Code de sortie 1 en cas
  d'échec. Aucune modification de l'UI ni du serveur (versions inchangées) ; fichier inutile au
  déploiement.

## borgHelperWWW 1.26.0 / borgHelperWWW_ui.html 1.14.0 — adresses partageables — 2026-09-27

Demande utilisateur : l'adresse doit suivre les menus (`https://host/explorer/<serveur>/<répertoire>`,
`https://host/historique/<serveur>`…) pour pouvoir passer une URL à un collègue, qui y accède
directement s'il a les droits.

- Adresses : `/`, `/serveur/<nick>`, `/explorer/<nick>[/<chemin…>][?archive=<nom>]`,
  `/historique/<nick>`, `/notifications` — mises à jour à chaque navigation (Précédent/Suivant et
  rechargement fonctionnent), servies par borgHelperWWW (auparavant `404`).
- Lien ouvert sans session : connexion, puis la page visée (l'adresse est conservée).
- Serveur inconnu ou hors droits : liste + « Serveur inconnu ou inaccessible avec vos droits : X »,
  identique dans les deux cas. Le lien n'accorde aucun droit.
- Adresse inconnue ouverte dans un navigateur : liste, adresse remplacée par `/` ; les clients API
  gardent le `404` JSON.
- Bouton **🔗 Copier le lien** près de l'étiquette du serveur (repli : adresse affichée à copier).
- `/notifications` quand le serveur ne peut pas envoyer de push (🔔 masqué) : liste, adresse `/`.
- Déconnexion : les droits en cache (`/access`) sont oubliés — la clé suivante recharge les siens.
- Vérifié : `push_selftest` 71/71 ; ponctuellement (scripts hors dépôt) test Node du routeur 25/25 et
  parcours Chrome headless 27/27, avec `api_prefix` `/api` puis `/v1`.

## borgHelper 1.0.120 — exploration plus rapide des bases chiffrées — 2026-09-26

Demande utilisateur : accélérer l'exploration d'une archive une fois la base chiffrée (étude, piste 1).

- Décodage des chemins chiffrés mémorisé **par segment** partout (auparavant réservé à TreeHist à la
  racine) : lister un sous-répertoire ne redécode plus son préfixe pour chacun des chemins du
  sous-arbre. Chaque segment reste vérifié — aucune concession sur la détection d'altération.
- Décodage base64 et XOR du codec réécrits (regex compilée, XOR par entier) — résultats identiques.
- Démo chiffrée, depuis un processus neuf comme chaque clic web : ouverture de `…/kernel` **1,2 s →
  0,36 s**, recherche `*.ko` **1,6 s → 0,54 s**. `PerfBench` (250k lignes) : TreeFind racine **~8 s →
  ~1,8 s**, décodage à froid de 20 000 chemins **1,15 s → 0,06 s** ; aucune régression sur les autres
  commandes.
- `CodecSelfTest` 330/330 (dont équivalence `_b64d`/`_xor` et altération profonde détectée malgré le mémo).

## borgHelperWWW 1.25.0 — identité de l'utilisateur, IP du navigateur, journal des requêtes — 2026-09-26

Demande utilisateur : enregistrer l'email/le nom transmis par le reverse proxy (notifications et
journaux), pouvoir bloquer l'accès sans lui, et journaliser l'IP du navigateur plutôt que celle du proxy.

- **`user_header`** (`BORGHELPERWWW_USER_HEADER` / `--user-header`) : nom du header portant l'email ou
  le nom de l'utilisateur. S'il est présent : journalisé avec chaque requête, et enregistré avec
  l'abonnement aux notifications (champ `user` du fichier JSON des préférences — à l'abonnement et à
  chaque modification, conservé si le header manque).
- **`require_user`** (`BORGHELPERWWW_REQUIRE_USER` / `--require-user`, défaut non) : 403 pour toute
  requête sans ce header, sauf `/healthz`. Sans `user_header`, borgHelperWWW refuse de démarrer.
- **Journal des requêtes** propre à borgHelperWWW : `[req] <IP navigateur> <utilisateur> "<requête>"
  <statut> <durée>`. Remplace le journal d'accès d'uvicorn en exécution directe (sous uvicorn externe :
  `--no-access-log`). **Paramètres sensibles masqués** : `/login?repo_passphrase=…` apparaissait en
  clair dans le journal d'uvicorn.
- **IP du navigateur** : lue dans `X-Forwarded-For` quand la connexion vient d'un proxy listé dans
  `trusted_proxies` (IP forgée par un client ignorée), **dans les deux modes de lancement** — le réglage
  était sans effet sous `uvicorn borgHelperWWW:app`. `trusted_proxies` invalide → refus de démarrer.
- `push_selftest` 69/69 ; essai réel en exécution directe et sous uvicorn externe.

## borgHelperWWW_ui.html 1.13.4 — explorateur : étiquette du serveur à la place de « ← Retour au serveur » — 2026-09-26

- Page Explorer (arborescence) : le bouton « ← Retour au serveur » est remplacé par la même étiquette
  **🖥 nom du serveur** que le détail et l'Historique complet. Retour à la liste : bouton **Serveurs**
  de l'en-tête. `closeBrowse()` (plus aucun appelant) supprimée.

## borgHelperWWW_ui.html 1.13.3 — étiquette du serveur en cours à la place de « ← Serveurs » — 2026-09-26

- Pages « détail d'un serveur » et « Historique complet » : le bouton « ← Serveurs » est remplacé par
  une étiquette **🖥 nom du serveur**. Le retour à la liste reste possible par le bouton **Serveurs** de
  l'en-tête (déjà présent sur toutes les pages). Page 🔔 Notifications inchangée (pas propre à un
  serveur) ; explorateur inchangé (son bouton « ← Retour au serveur » ramène au détail ou à
  l'Historique).

## borgHelperWWW 1.24.0 / borgHelper 1.0.119 / UI 1.13.2 / borgHelperWWW_sw.js 1.2.0 — notification « sauvegarde en retard » — 2026-09-26

Demande utilisateur : un serveur non sauvegardé depuis plus de `MAX_AGE_BKP` heures est une erreur —
pas seulement affichée (Report le marquait déjà), mais notifiée.

- Le watcher de borgHelperWWW compare à chaque passage l'âge de la dernière archive connue de chaque
  serveur à son `MAX_AGE_BKP` (heures, défaut 25 — même règle que Report). Au-delà : notification push
  de type **Échec** — « ⏰ Sauvegarde en retard — nick / Dernière sauvegarde il y a 31 h (seuil : 25 h) ».
- **Rappel** à chaque période supplémentaire (2×, 3× le seuil…) — « ⏰ Toujours aucune sauvegarde » —
  jusqu'à la prochaine archive. Aucun doublon, y compris avec plusieurs workers (réservation atomique,
  table `overdue_alerts` de `push.db`, schéma 2).
- Silence pendant un Bkp en cours et pour un serveur sans archive connue. Sans abonné aux échecs de ce
  host, l'alerte n'est pas consommée : un abonnement pris pendant le retard la reçoit aussitôt.
- UI : colonne « ❌ Échec / retard » dans les réglages de notification.
- borgHelper 1.0.119 : `last_archive_stat` / `bkp_running` (lectures pour le watcher, jamais de
  création de base).
- `CodecSelfTest` 327/327, `push_selftest` 63/63 ; essai réel de bout en bout (démo,
  `MAX_AGE_BKP = 0.5`) : notification reçue et déchiffrée, aucun doublon sur ~5 passages.

## borgHelper 1.0.118 / borgHelperWWW 1.23.0 / borgHelperWWW_sw.js 1.1.0 — avertissements dans la notification de fin — 2026-09-26

- La notification de fin de sauvegarde mentionne les fichiers modifiés pendant la sauvegarde et les
  erreurs de lecture (statuts C/E, 1.0.117) : « ⚠️ Sauvegarde terminée avec avertissements — nick /
  Bkp réussi — 2 fichiers modifiés pendant la sauvegarde, 1 erreur de lecture ». Un échec les
  mentionne aussi. Sans avertissement : notification inchangée (✅).
- Le type de notification (succès/échec) et donc le filtrage par host ne changent pas.
- Schéma `diff.db` palier 9 : `bkp_status.changed_during_backup` / `read_errors`, écrits par le Bkp
  avec son résultat et relus par le watcher ; payload push enrichi des deux compteurs quand ils sont
  connus.
- `CodecSelfTest` 325/325, `push_selftest` 58/58 ; essai réel de bout en bout (watcher, faux service
  push déchiffrant) : Bkp réussi et Bkp en échec, tous deux avec un fichier modifié pendant la
  sauvegarde et un fichier illisible → notification reçue avec les deux compteurs.

## borgHelper 1.0.117 / borgHelperWWW_ui.html 1.13.1 — fichiers modifiés pendant la sauvegarde, erreurs de lecture — 2026-09-26

Suite de 1.0.116 (abandon de `borg create --list` comme source des changements) : on en garde le seul
signal que `borg diff` ne fournit pas.

- `borg create --list --filter CE` : statuts **C** (fichier modifié pendant sa sauvegarde — copie
  possiblement incohérente) et **E** (erreur de lecture — fichier non ou partiellement sauvegardé).
  Jamais utilisés comme un diff ; volume quasi nul ; actifs même avec `-I`.
- Signalés par un `[WARN]` récapitulatif (stderr), dans le JSON de sortie du Bkp
  (`borgHelper_backup_warnings`), et **enregistrés par archive** — visibles depuis l'interface web,
  où un Bkp lancé en tâche de fond n'a pas de sortie consultable.
- Schéma `diff.db` palier 8 : `archive_stats.changed_during_backup` / `read_errors` (ajout de colonnes,
  NULL = inconnu). `store_archive_stats` devient un upsert : un rattrapage par `Index -F` ne les efface
  jamais.
- `ArchiveHistory -j` : champs `changed_during_backup` / `read_errors`.
- UI : deux séries de points dans le graphique « Fichiers modifiés par archive ».
- `CodecSelfTest` 324/324 ; essai réel : fichier illisible (`E`) et gros fichier modifié en continu
  pendant la sauvegarde (`C`) détectés, signalés et enregistrés.

## borgHelper 1.0.116 — Bkp : indexation par le vrai borg diff (répertoires faussement « supprimés ») — 2026-09-26

Défaut présent depuis borgHelper 0.45, trouvé en ajoutant le graphique des fichiers modifiés.

- **Bkp n'utilise plus `borg create --list`** pour enregistrer les changements. Ses statuts ne
  décrivent pas un diff : `d` (répertoire) était enregistré comme « supprimé » — **tous les
  répertoires marqués supprimés à chaque Bkp** — et aucune suppression réelle n'y figure. Surtout, le
  snapshot incrémental de la nouvelle archive était calculé sur ces données : **répertoires retirés
  du snapshot, fichiers réellement supprimés conservés**, erreur propagée aux snapshots suivants
  (TreeHist/TreeFind/Search sur le dernier état connu).
- Désormais : `borg create` sans `--list`, puis `borg diff` réel de la nouvelle paire (Index post-Bkp,
  déjà en place), puis snapshot incrémental sur ce diff. Coût : un `borg diff` par Bkp (déjà exécuté
  auparavant pour « remplir les tailles »), toujours interruptible par un Bkp/Restore.
- **Répertoires et liens** ajoutés/supprimés (`added directory`, `removed directory`...) : appliqués au
  snapshot incrémental (un répertoire supprimé y restait) et comptés comme ajoutés/supprimés dans la
  colonne « Modifs » de Report et le graphique des fichiers modifiés (étaient « modifiés »).
- **Sortie JSON de Bkp** : stdout ne contient plus que le JSON, imprimé après l'indexation (messages
  d'Index sur stderr) ; `borgHelper_file_counts`/`borgHelper_files` (`-d`) calculés à partir du vrai
  diff, avec les types de changement de `borg diff` ; absents si la paire n'est pas indexée.
- **Réparation recommandée** (une fois, au moment opportun) : `borgHelper -c Index -n ALL -S -F`
  reconstruit le dernier snapshot de chaque serveur par un `borg list` complet.
- `CodecSelfTest` 321/321 ; essai réel sur un dépôt de test (fichier ajouté/modifié/supprimé,
  répertoire ajouté/supprimé) : diff, snapshot, compteurs et JSON exacts.

## borgHelper 1.0.115 / borgHelperWWW_ui.html 1.13.0 — graphiques : fichiers modifiés, durée, taille dédupliquée — 2026-09-26

Demande utilisateur : graphiques du nombre de fichiers modifiés par archive, de la durée de sauvegarde
et de la taille dédupliquée par archive.

- `ArchiveHistory -j` (donc `/archivehistory`) : `files_added`/`files_modified`/`files_removed` par
  archive — mêmes comptages que la colonne « Modifs » de `Report` ; `null` si la paire d'archives
  n'est pas indexée.
- UI, Historique complet → Évolution : trois graphiques supplémentaires — fichiers modifiés (barres
  empilées ajoutés/modifiés/supprimés), durée de sauvegarde, taille dédupliquée seule. Archive sans
  valeur laissée vide (jamais comptée à zéro) ; message explicite si aucune donnée.
- `CodecSelfTest` 321/321 (comptages exacts, `null` pour une paire non indexée) ; rendu vérifié sous
  Node (DOM et Chart.js simulés) : données réelles de la démo, aucune donnée, exception Chart.js,
  session expirée.

## borgHelperWWW 1.22.0 / borgHelperWWW_ui.html 1.12.2 — Chart.js embarqué, favicon.ico local — 2026-09-26

- **Chart.js embarqué** : copie de Chart.js 4.5.1 dans `vendor/chartjs/` (licence MIT), servie par
  borgHelperWWW sur `/static/chart.umd.min.js` — les graphiques de l'Historique complet ne demandent
  plus d'accès Internet au navigateur (intranet, proxy restrictif). Fichier absent du déploiement :
  `[WARN]` au démarrage et repli automatique de l'UI sur le CDN. Même empreinte d'intégrité (SRI)
  vérifiée dans les deux cas.
- **`/favicon.ico`** : un fichier `favicon.ico` posé à côté de `borgHelperWWW_ui.html` (sinon à côté
  de `borgHelperWWW`) est servi, sans clé API ; pris en compte sans redémarrage ; absent → 404.
- `push_selftest` 56/56 ; essai réel : Chart.js servi à l'identique (empreinte vérifiée), favicon
  absent → 404, déposé → servi, retiré → 404, sans redémarrage.

## borgHelper 1.0.114 / borgHelperWWW_ui.html 1.12.1 — graphiques d'évolution visibles, alimentés par Index — 2026-09-26

Rapport utilisateur : graphiques d'évolution invisibles, chargement sans fin sur certains, et besoin
qu'une réindexation mette à jour leurs données.

- **UI — graphiques jamais affichés dès qu'il y avait des données** (depuis 1.9.0) : `_hideChartMsg()`
  n'était jamais appelée ; le graphique était dessiné sur un canvas resté masqué, l'indicateur de
  chargement restait affiché indéfiniment. Seul le cas « aucune donnée » s'affichait. Corrigé ; chaque
  graphique finit désormais toujours dessiné ou remplacé par un message (aucune donnée, erreur,
  session expirée, exception de Chart.js).
- **UI** : bloc « Évolution » placé au-dessus de la liste des archives dans l'Historique complet ;
  messages « aucune donnée » explicites ; points de taille du dépôt relevés par Index en carrés gris.
- **Index alimente les graphiques** : statistiques des archives qui n'en ont pas (antérieures, ou
  créées hors borgHelper) et point de taille du dépôt (`op='index'`, seulement si elle a changé) — y
  compris avec `NOIDX=1` ou moins de 2 archives. Erreurs `borg info` signalées au lieu d'être ignorées.
- **Correctif Index — faux « indexation interrompue »** : tout Index qui traitait au moins une paire
  d'archives se déclarait interrompu (code 1, reprise forcée au Bkp suivant, snapshot/statistiques/
  `DIFF_KEEP` jamais atteints). Seule une vraie opération prioritaire (Bkp/Restore) interrompt
  désormais l'Index.
- `CodecSelfTest` 320/320 ; essais réels sur la démo (statistiques vidées puis rattrapées par Index,
  pas de doublon au 2e Index, `NOIDX=1`, Index post-Bkp complet, vraie interruption toujours
  fonctionnelle) ; rendu des graphiques vérifié sous Node (DOM et Chart.js simulés) sur 4 cas.

## borgHelperWWW 1.21.0 / borgHelperWWW_ui.html 1.12.0 — notifications réglables par host, type « échec » distinct — 2026-09-26

Demande utilisateur : notifications paramétrables par host, et notifications en cas d'erreur.

- **Par host, trois types** : début de sauvegarde, **succès**, **échec** (Bkp en erreur, ou bloqué
  au-delà de `BORGHELPERWWW_BKP_STATUS_TIMEOUT`). Remplace le couple global début/fin. Défaut d'un
  nouvel abonnement : succès + échec sur chaque host.
- **UI** : tableau host × Début/Succès/Échec, ligne « Tous » par colonne. Les cases non enregistrées
  ne sont plus effacées par un message de statut (ex. « Envoyer un test »).
- **API** : `POST /push/subscribe` accepte `hosts` et `defaults` ; `PATCH` accepte `hosts` (host hors
  périmètre de l'abonnement → 422) ; réponses : champ `hosts` au lieu de `notify_start`/`notify_end`.
  `notify_start`/`notify_end` restent acceptés en entrée (compatibilité).
- **Fichier JSON** : format 2 (`hosts`). Les entrées existantes sont converties à la lecture (début =
  ancien début, succès et échec = ancienne fin), sans action requise.
- `push_selftest` 54/54 ; essai réel : Bkp réussi sur un host réglé « échec seul » → aucune
  notification ; Bkp en échec forcé → notification ❌ reçue.

## borgHelperWWW 1.20.2 / borgHelperWWW_ui.html 1.11.1 — envoi push : délai, TTL, diagnostic — 2026-09-26

Rapport utilisateur : « Envoyer un test » ne provoque aucun affichage dans Firefox.

- **Délai d'envoi** : `webpush()` était appelé sans `timeout` (pywebpush transmet alors `None` à
  `requests`) — un service push injoignable depuis le serveur (pare-feu, proxy sortant) bloquait
  l'appel sans fin, sans message dans l'UI. Désormais 10 s, puis `502` explicite nommant l'hôte du
  service push (ex. `updates.push.services.mozilla.com`).
- **TTL** : pywebpush envoie `TTL: 0` par défaut — le service push accepte puis jette le message si
  le navigateur n'est pas connecté à cet instant. Désormais 24 h pour début/fin de sauvegarde, 5 min
  pour le test.
- **UI** : « Envoi en cours… » pendant le test ; nouveau bouton « Tester l'affichage local » (sans
  serveur ni service push) pour distinguer un blocage d'affichage (navigateur/système) d'un problème
  d'acheminement ; message de succès expliquant la marche à suivre.
- README : section de dépannage.

## borgHelperWWW 1.20.1 — avertissements push précis, plus jamais « pip install » — 2026-09-26

Rapport utilisateur : au démarrage, `[WARN] py_vapid absent ... 'pip3 install pywebpush'` — conseil
contraire au choix de déploiement (aucun pip/venv, dépendances push vendorisées dans `vendor/` depuis
1.18.2). Cause réelle : `vendor/` absent du déploiement.

- Nouveaux `[WARN]` (import de `pywebpush`, génération des clés VAPID) : diagnostic précis au lieu de
  pip — dossier `vendor/` introuvable (chemin attendu affiché), module vendorisé manquant dans
  `vendor/` (copie partielle), ou dépendance système absente (`apt install python3-cryptography` /
  `python3-aiohttp` / `python3-requests`).
- `POST /push/test` : message 503 renvoyant au `[WARN]` de démarrage.
- DEPLOIEMENT.md : rappel de déployer `vendor/` avec `borgHelperWWW`.
- Vérifié en simulant un serveur sans ces bibliothèques installées globalement : sans `vendor/`,
  `vendor/` partiel, `cryptography` absent → message attendu ; `vendor/` complet → aucun
  avertissement, push disponible sans pip.

## borgHelperWWW 1.20.0 / borgHelperWWW_ui.html 1.11.0 — accès direct par GROUPS_PATHS, sans tier — 2026-09-26

Demande utilisateur : `GROUPS_ADMIN`/`GROUPS_WRITE`/`GROUPS_READ` équivalent à un accès racine aux
sauvegardes d'un host ; devoir en donner un pour ensuite le restreindre n'a pas de sens.

- Un groupe **sans aucun tier** mais cité dans `GROUPS_PATHS` obtient directement la **lecture** de ses
  chemins (arborescence, Search/TreeFind, historique, Report filtré...) — **sans téléchargement**.
- Cité dans `GROUPS_PATHS_RESTORE` : lecture **et téléchargement** (fichier, `.tar`, consultation des
  droits) de ces chemins. Lecture = union de ses entrées `GROUPS_PATHS` et `GROUPS_PATHS_RESTORE`.
- Jamais au-delà du niveau lecture : `POST /restore`, `Bkp`, `Index`, `Prune`... restent réservés à
  `GROUPS_WRITE`/`GROUPS_ADMIN`.
- Groupes à tier : comportement inchangé (restriction, repli par groupe de `GROUPS_PATHS_RESTORE` sur
  `GROUPS_PATHS`).
- `GET /access` : `level:"read"` et `restore_scope: []` pour un groupe `GROUPS_PATHS` seul.
- UI : boutons de téléchargement masqués hors du périmètre de téléchargement.
- Changement de comportement : `GROUPS_PATHS` est désormais lu pour tout appelant ; une valeur rendue
  ambiguë en cours d'exécution renvoie 500 aussi à un appelant sans tier.
- Docs : README (tableau), `docs/borghelperrc.example` (nouvel host `[dbserver01]`), DEPLOIEMENT,
  TECHNIQUE, TECHNICAL. `push_selftest` 48/48.
- README, exemple `.borghelperrc` : `GROUPS_PATHS`/`GROUPS_PATHS_RESTORE` illustrent les deux usages
  (restriction d'un groupe à tier, accès direct sans tier) ; commentaires des lignes `GROUPS_*`
  déplacés sur leur propre ligne (en fin de ligne, `configparser` les intégrait au nom de groupe).
- README : même correctif pour tous les autres exemples `.borghelperrc` (`EXCLUDE_NEXT`,
  `BORG_ARCHNAME`, `BORG_ROOTBKP`, `MAX_AGE_BKP`, `DISPLAY_BKP`, `SSH_REPO`, `SSH_REMFO`, `DB_NAME`,
  `IDX_INCLUDE`, `IDX_EXCLUDE`, `DB_ENCRYPT`, `DB_KDF`) — copiés tels quels, ils donnaient des valeurs
  fausses (`MAX_AGE_BKP` non numérique, motifs `#`/`liste`/`noire` ajoutés à `IDX_EXCLUDE`...).

## borgHelperWWW 1.19.1 / borgHelperWWW_ui.html 1.10.1 — répertoires parents du périmètre navigables — 2026-09-26

Bug rapporté : un groupe borné par `GROUPS_PATHS = AD-Borg admin:/opt/backups/mysql/` voyait une
racine vide dans l'arborescence de l'UI — `opt` et `opt/backups`, parents du périmètre mais pas dans
le périmètre, étaient filtrés, rendant `mysql/` inatteignable.

- `/treehist` (appelant à périmètre restreint) : les répertoires parents d'un préfixe du périmètre sont
  gardés comme entrées de navigation nues (`scope_ancestor: true`, sans droits/propriétaire/
  historique). Leurs autres enfants restent masqués. Search/TreeFind/FileHist/rapports/restauration
  inchangés (filtrage strict).
- Cache par périmètre de TreeHist : clé enrichie, les réponses mises en cache avant la mise à jour ne
  sont pas resservies.
- UI : badge « accès partiel » sur ces entrées, pas de téléchargement au clic droit.
- README : rappel que `GROUPS_PATHS` restreint un accès, n'en accorde jamais.
- `push_selftest` 47/47 (nouveau contrôle TreeHist/parents du périmètre).

## borgHelperWWW 1.19.0 / borgHelperWWW_ui.html 1.10.0 — paramétrage des notifications dans l'UI + préférences en JSON — 2026-09-26

`spec-push-ui-prefs-json` (Story 2c de `spec-notifications-push`), demande directe utilisateur :
régler ses notifications depuis l'interface Web, réglages stockés dans un fichier JSON.

- **UI** : bouton **🔔 Notifications** dans l'en-tête (si `GET /version` → `push_available`), nouvelle
  vue : s'abonner (permission navigateur), début et/ou fin de sauvegarde, durée (défaut serveur,
  7/30/90/365 jours, à vie), enregistrer, **envoyer un test**, se désabonner.
- **Service Worker** : nouveau fichier `borgHelperWWW_sw.js` (`SW_VERSION 1.0.0`), servi sur
  `GET /sw.js` sans `X-API-Key` (`Service-Worker-Allowed: /`, `no-cache`) — affiche les notifications
  (une fin remplace le début du même nick), clic → onglet borgHelperWWW au premier plan. À déployer à
  côté de l'UI. **HTTPS requis** (ou `localhost`) côté navigateur.
- **Préférences par abonné en JSON** : nouveau réglage `push_prefs` / `BORGHELPERWWW_PUSH_PREFS` /
  `--push-prefs` (défaut `<prefixe>-push-prefs.json` à côté de `push.db`). Source de vérité de
  `scope_nicks`/`notify_start`/`notify_end`/`expires_at`, éditable à la main et pris en compte à chaud.
  Écritures atomiques (`0600`, `os.replace`) sous `flock` ; normalisation fail-closed ; fichier corrompu
  jamais écrasé (`/push/*` → 500 explicite, watcher n'envoie rien). `push.db` ne garde que les clés
  VAPID et `endpoint`/`p256dh`/`auth` (anciennes colonnes conservées, plus lues — schéma inchangé).
- **Migration automatique** au premier démarrage : préférences des abonnements existants recopiées de
  `push.db` vers le JSON (une seule fois).
- **Nouvelle route `POST /push/test?endpoint=...`** : notification de test (`404` inconnu, `410` mort →
  désabonné, `502` échec service push, `503` push indisponible).
- `GET /push/subscriptions` : champs `updated_at` et `prefs_missing` ; `PATCH` → `409` si l'entrée JSON
  manque (se réabonner).
- `GET /version` : `push_available`, `push_default_expiry_days`, `push_max_expiry_days`.
- `push_selftest` 26 → 46 contrôles (JSON, migration, corruption, routes via `TestClient`).

## borgHelperWWW 1.18.7 — GROUPS_PATHS scindé lecture/restauration — 2026-09-26

`spec-groups-paths-restore`, demande directe utilisateur : `GROUPS_PATHS` restreignait un même
périmètre de chemin pour la lecture (`Search`/`TreeFind`/...) ET la restauration
(`Restore`/téléchargements) — un seul réglage pour deux besoins distincts.

- Nouvelle clé `.borghelperrc` : `GROUPS_PATHS_RESTORE` (même syntaxe exacte que `GROUPS_PATHS`),
  régissant désormais spécifiquement `Restore`/`RestorePerms`/`DownloadFile`/`DownloadTar`. Repli
  **par groupe** sur `GROUPS_PATHS` si absent de `GROUPS_PATHS_RESTORE` — rétro-compatible, une
  config existante qui n'utilise que `GROUPS_PATHS` continue de restreindre la restauration comme
  avant.
- `_resolve_path_scope(user_groups, cfg, for_restore=False)` : nouveau paramètre. Frontière
  d'implémentation trouvée par investigation avant tout code : `require_path_in_scope()` n'a que 4
  appelants dans tout `borgHelperWWW` (`download_file`, `download_tar`, `restore_perms`, `restore`)
  — tous des routes de restauration, aucune route de lecture — donc `for_restore=True` y est
  systématique et **aucun des ~10 call sites de lecture n'a eu besoin d'être touché**.
  `_resolve_scopes_for_request()` propage le paramètre.
- `GET /access` : `scope` remplacé par `read_scope`/`restore_scope` séparés (changement de contrat
  JSON, `/access` n'est consommé par aucun code fonctionnel de l'UI actuellement).
- **Confirmé et documenté** (demande explicite utilisateur) : aucune permission UNIX de l'host
  sauvegardé n'intervient jamais dans ces décisions — `Search`/`TreeFind`/`FileHist` lisent
  exclusivement l'index SQLite, `Restore`/`listperms` appellent `borg list`/`borg extract` contre
  l'archive (métadonnées figées au moment du `Bkp`), jamais un `os.stat`/`os.access` sur l'host
  distant ni sur le serveur `borgHelperWWW`. Voir `docs/TECHNIQUE.md`/`TECHNICAL.md`.
- `docs/borghelperrc.example` : exemple `[fileserver01]` étendu — `AD-Borg-Restore-Audit` peut
  désormais chercher partout sous `/srv/data/compta` mais ne restaure que depuis
  `/srv/data/compta/archives`, démontrant concrètement la scission. Vérifié contre le vrai parser.
- `push_selftest` : 2 nouveaux contrôles dédiés (repli par groupe, `require_path_in_scope` applique
  bien le périmètre de restauration) — 31/31 OK.

## borgHelper 1.0.113 / borgHelperWWW 1.18.6 — section renommée [_borgHelperWWW] + borgHelper l'ignore — 2026-09-26

Révision de `spec-borghelperrc-www-section` (1.18.4, `fa88c38`) à la demande de l'utilisateur : la
section `.borghelperrc[DEFAULT.borghelperwww]` devient `[_borgHelperWWW]` (préfixe `_` réservé, plus
court, plus explicitement "technique interne" qu'un nom composé avec un point) — même mécanique,
même priorité (CLI > env > `borghelperwww.conf` > `.borghelperrc[_borgHelperWWW]` > défauts).

**Nouveauté** (pas dans la V1) : `borgHelper` (CLI) ignore désormais **silencieusement** toute section
`.borghelperrc` dont le nom commence par `_` lors de l'énumération des nicks — jamais traitée comme un
nick réel. Sans ce correctif, `-n ALL` (ou toute commande qui itère via `cfgreadnicks()`) aurait tenté
de traiter `[_borgHelperWWW]` comme un nick et planté (section sans `MOUNTPOINT`/`BORG_REPO`/etc.).

- `BorgRunner.cfgreadnicks()` : filtre `not nick.startswith('_')`, générique — toute future section
  réservée `_*` est ignorée sans code supplémentaire.
- `stats()` (commande `Stats` sans argument) : même filtre, ajouté à son énumération propre (pas via
  `cfgreadnicks`) ; corrige au passage un bug latent (`if n in 'DEFAULT'` — test de sous-chaîne, pas
  d'égalité — un nick dont le nom était une sous-chaîne de "DEFAULT" aurait été silencieusement
  sauté ; devient `if n=='DEFAULT'`).
- `borgHelperWWW` : toutes les références à `[DEFAULT.borghelperwww]` renommées `[_borgHelperWWW]`
  (code, commentaires, `push_selftest`).
- `CodecSelfTest` (borgHelper) : nouveau contrôle dédié — 320/320 OK. `push_selftest`
  (borgHelperWWW) : 29/29 OK inchangé (renommage transparent). Vérifié en réel : `Status -n ALL` sur
  un `.borghelperrc` portant `[_borgHelperWWW]` liste bien les vrais nicks, jamais la section
  réservée.

## borgHelperWWW 1.18.5 — garde GROUPS_HEADER + docs/borghelperrc.example corrigé — 2026-09-26

Incident réel (rapporté par l'utilisateur) : `500 Internal Server Error`/`UnicodeEncodeError` sur
toute route RBAC-protégée (`request.headers.get(GROUPS_HEADER)` encode le nom en latin-1). Cause :
`configparser` n'a `inline_comment_prefixes` réglé nulle part dans ce projet — un commentaire posé
après une valeur sur la même ligne (`CLE = valeur   ; commentaire`) n'est **jamais** coupé, tout le
texte devient littéralement la valeur. La source exacte : `docs/borghelperrc.example` (ajouté cette
session) avait des commentaires en ligne sur plusieurs réglages, y compris l'exemple `groups_header`
— l'utilisateur l'a copié et décommenté tel quel.

- **`docs/borghelperrc.example` réécrit** : plus aucun commentaire en ligne nulle part (fichier
  entier réaudité programmatiquement) — chaque commentaire sur sa propre ligne, au-dessus du réglage,
  seule convention déjà utilisée partout ailleurs dans ce fichier et dans `demo.borghelperrc`/
  `borghelperwww.conf.example` (confirmés indemnes). Avertissement explicite ajouté en tête de
  fichier.
- **Garde `_is_valid_http_token()` + validation `GROUPS_HEADER` au démarrage** : `GROUPS_HEADER` doit
  être un token HTTP valide (RFC 7230 — lettres/chiffres/`-`/quelques symboles, jamais d'espace ni de
  caractère non-ASCII) ; sinon `borgHelperWWW` refuse de démarrer avec un message clair plutôt que de
  planter sur la première requête RBAC reçue (et toutes les suivantes). Défense en profondeur : même
  un commentaire inline **sans** caractère non-latin1 (donc qui n'aurait jamais crashé, juste
  silencieusement corrompu `GROUPS_HEADER`) est maintenant détecté.
- `push_selftest` : nouveau contrôle dédié (29/29 OK). Vérifié en réel : le scénario exact rapporté
  (valeur avec commentaire inline + tiret cadratin) est bloqué au démarrage avec un message clair ;
  une valeur propre démarre normalement.

## borgHelperWWW 1.18.4 — borgHelperWWW configurable depuis .borghelperrc — 2026-09-26

`spec-borghelperrc-www-section` : suite directe de la garde 1.18.3 — il existe désormais un moyen
légitime de faire ce que l'admin visait avec le piège original (poser `GROUPS_HEADER` dans le même
fichier que la CLI) : une section `[DEFAULT.borghelperwww]` dans le `.borghelperrc` dédié à l'API.

- Nouvelle section `[DEFAULT.borghelperwww]` (section `configparser` **ordinaire** — seul le nom
  exact `DEFAULT` a un sens spécial ; celle-ci n'hérite de rien, nom choisi pour ne jamais collisionner
  avec un nom de nick réel) : mêmes clés que `borghelperwww.conf` (`_CONF_KEYS` — `api_key`,
  `groups_header`, `host`, `port`, etc.).
- Priorité : flag CLI > variable d'environnement `BORGHELPERWWW_*` > `borghelperwww.conf`
  (`--conf`/`BORGHELPERWWW_CONF`, inchangé) > `.borghelperrc[DEFAULT.borghelperwww]` (nouveau, dernier
  repli) > défauts. `borghelperwww.conf` garde la main quand présent — déploiements existants non
  affectés.
- `_apply_conf_section()` (factorisée) : même logique de remplissage `os.environ` partagée par
  `borghelperwww.conf` et la nouvelle section — un seul patron, deux sources.
- La garde `_warn_stray_borghelperwww_keys()` (1.18.3) ne scanne que le `[DEFAULT]` réel
  (`cp.defaults()`) — `[DEFAULT.borghelperwww]` est une section distincte, jamais confondue avec le
  piège, aucun faux positif sur ce nouveau mécanisme légitime (vérifié).
- `push_selftest` : nouveau contrôle dédié (28/28 OK). Vérifié en réel : résolution de `GROUPS_HEADER`
  depuis `.borghelperrc[DEFAULT.borghelperwww]`, garde toujours silencieuse dessus, garde toujours
  active sur le piège original (`[DEFAULT]` nu), et priorité `borghelperwww.conf` > `.borghelperrc`
  confirmée sur les trois scénarios.

## borgHelperWWW 1.18.3 — garde contre BORGHELPERWWW_* égarée dans .borghelperrc — 2026-09-26

Piège réel constaté en production : un admin a posé `BORGHELPERWWW_GROUPS_HEADER=X-GROUPS` dans
`[DEFAULT]` de son `.borghelperrc`, pensant activer le RBAC par groupes. `.borghelperrc` n'est lu que
par `borgHelper` (CLI, par nick) — `borgHelperWWW` lit ses propres réglages uniquement depuis
l'environnement ou `--conf`/`BORGHELPERWWW_CONF` (`borghelperwww.conf.example`). La clé était donc
silencieusement ignorée (configparser ne signale jamais une clé inconnue) : RBAC resté désactivé,
X-API-Key seule faisant foi — accès total à tous les nicks pour quiconque a une clé API valide, sans
aucune erreur ni avertissement pour le détecter.

- Nouvelle garde `_warn_stray_borghelperwww_keys()`, appelée juste après la validation de `CFGFILE` :
  relit `.borghelperrc` en `configparser` séparé (`optionxform=str`, casse préservée), et avertit
  (`[WARN]`, stderr) si `[DEFAULT]` contient une ou plusieurs clés `BORGHELPERWWW_*` — jamais
  bloquant, juste un signal impossible à manquer au démarrage.
- `push_selftest` : nouveau contrôle dédié (27/27 OK) — avertit sur un `.borghelperrc` piégé,
  silencieux sur un propre.

## borgHelperWWW 1.18.2 — pywebpush/py_vapid/http_ece vendorisés — 2026-09-26

`spec-push-vendoring` : les notifications push (spec-notifications-push) sont maintenant réellement
utilisables en production sans `pip`/`venv`. `pywebpush`/`py_vapid`/`http_ece` (PyPI-only, aucun paquet
apt Ubuntu) sont vendorisés dans `Borg/vendor/` — copie strictement fidèle des wheels 2.5.0/1.9.4/1.2.1
(purs Python, aucune extension compilée, ~240 Ko, licences MPL-2.0/MPL-2.0/MIT préservées). Leurs
propres dépendances lourdes (`aiohttp`/`requests`/`cryptography`) restent des paquets apt externes
(déjà présents dans les dépôts Ubuntu jammy) — jamais vendorisées.

- `sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))` ajouté juste avant les imports
  optionnels `pywebpush`/`py_vapid` (mêmes conditions de fallback qu'en 1.18.1 : `aiohttp`/`requests`/
  `cryptography` absents = démarrage quand même, notifications désactivées).
- Installation désormais : `apt install python3-aiohttp python3-requests python3-cryptography` +
  `git pull` — plus jamais de `pip install pywebpush` ni de venv.
- Vérifié en masquant temporairement les paquets pip installés (`pywebpush`/`py_vapid`/`http_ece` retirés
  de `site-packages`) : import réussi, clés VAPID générées, `push_selftest` 26/26 OK — uniquement via
  `Borg/vendor/`, confirmé par `pywebpush.__file__`/`py_vapid.__file__` pointant vers ce dossier.
- Mise à jour future du code vendorisé : manuelle, sur CVE/bug rapporté uniquement (voir
  `vendor/README.md`).

## borgHelper 1.0.112 — TreeFind : recherche par nom insensible à la casse — 2026-09-26

`_treefind_listing` comparait le nom (dernier segment du chemin) au motif `-m` via
`fnmatch.fnmatchcase` — sensible à la casse (`-m error` ne trouvait pas `ERROR.log`), contrairement à
`Search`/`DuIdx` dont le `LIKE` est déjà insensible à la casse (ASCII) par défaut SQLite. Corrigé :
comparaison via `str.casefold()` des deux côtés (nom et motif) — insensible à la casse, y compris pour
les caractères accentués (plus large que l'ASCII-only des `LIKE` SQL ailleurs dans ce fichier).
319/319 `CodecSelfTest` OK (nouveau contrôle dédié ajouté, données réelles indexées — `bin/b.log`
trouvé par `*.LOG`/`B.LOG`, `upper.txt` par `UPPER`, `Etc` par `etc`).

## borgHelperWWW 1.18.1 — pywebpush et py_vapid deviennent des dépendances optionnelles — 2026-09-26

Ni `pywebpush` ni `py_vapid` (sa dépendance transitive) ne sont des paquets d'un dépôt apt (PyPI-only)
— pas forcément installés sur un hôte de production. Jusqu'ici, deux points faisaient planter tout
`borgHelperWWW` (y compris `uvicorn borgHelperWWW:app`) si l'une des deux libs était absente, même pour
un admin n'utilisant pas du tout les notifications push :

- Import de `pywebpush` en tête de fichier — mis en `try/except ImportError` : si absent,
  `_PYWEBPUSH_AVAILABLE=False`, `webpush=None`.
- Génération de la première paire de clés VAPID (`_init_vapid_keys()`, appelée sans garde au niveau
  module) — importait `py_vapid` sans filet. Mis en `try/except ImportError` : si absent, `None,None`
  (une paire déjà en base, cas courant après un premier démarrage réussi, se relit sans jamais
  ré-importer `py_vapid` — seule la toute première génération l'exige).

Dans les deux cas : le reste de `borgHelperWWW` (toutes les routes, y compris `/push/subscribe` en
CRUD et `GET /version`) démarre et fonctionne normalement ; `_send_bkp_push` (watcher) court-circuite
immédiatement (`return`, aucune exception) si l'une des deux dépendances manque. Avertissement `[WARN]`
au démarrage (stderr) dans chaque cas, invitant à `pip3 install pywebpush` (inclut `py_vapid` en
dépendance transitive). Vérifié en simulant l'absence des deux libs sur un `push.db` tout neuf (premier
démarrage, aucune paire encore stockée) : démarrage complet sans exception. Aucun changement de
comportement quand les deux sont installées (cas actuel de `demo.borghelperrc`) — 26/26
`push_selftest` toujours OK.

## borgHelper 1.0.111 — commande Status : état rapide par nick, 100% local — 2026-09-26

`spec-status-cli-etat-rapide` : nouvelle commande CLI en lecture seule pour obtenir rapidement l'état
d'un ou plusieurs nicks (dernier backup, Bkp en cours, opération prioritaire) sans jamais appeler
`borg` — utile quand le dépôt distant est lent/injoignable et que `getlastbkp`/`list_backups`
bloqueraient.

### `prune()` pose désormais `priority.lock`

- `prune()` ne posait jusqu'ici aucun `priority.lock`, contrairement à `backup()`/`restore()` — corrigé :
  `self.db.set_priority_lock(nick)` juste après `cfgreaded`/`ensure_*_db` (avant tout appel `boex`),
  `self.db.clear_priority_lock(nick)` dans un `finally` couvrant tout le corps de la fonction (succès
  et exception, y compris `--dry-run`). Sans ce changement, `Status` ne pouvait pas détecter un Prune
  en cours.

### `BorgHelperDB.get_running_bkp_status(nick, db_path=None)`

- Nouvelle méthode lecture seule : dernière ligne `bkp_status` non terminée (`finished_at IS NULL`)
  pour ce nick, s'il y en a une (normalement 0 ou 1). Voisine de `list_pending_bkp_status`/
  `claim_bkp_status`, même style.

### Commande CLI `Status`

- `-c Status [-n nick1,nick2/ALL] [-j]` : pour chaque nick, affiche le dernier backup connu
  (`archive_stats`, avec âge lisible), le Bkp en cours (`bkp_status`, depuis quand) et une opération
  prioritaire en cours (`priority.lock`, Restore **ou** Prune — ambiguïté assumée, `priority.lock` ne
  distingue pas laquelle ; non affichée si un Bkp est déjà détecté, pour éviter un message redondant).
- Supporte nativement `-n nick1,nick2` et `ALL` (contrairement à `RepoHistory`/`ArchiveHistory` qui
  rejettent le multi-nick) — c'est le cas d'usage principal de `Status`.
- `-j` : JSON, toujours une liste de `{nick,last_backup,bkp_running,priority_op_running}`, même à un
  seul nick, pour une forme homogène côté consommateurs machine.
- 100% local : jamais d'appel `boex`/`borg` — rapide, fonctionne hors ligne, dépôt distant injoignable
  sans bloquer.
- Correctif (revue avant commit) : `-n ALL` était traité comme un nick littéral `'ALL'` au lieu de
  s'étendre à tous les nicks configurés (régression du même type que celle déjà connue pour
  `DbStatus`/`DbEncrypt`) — `status()` applique désormais le même patron
  `nick.split(',') if nick and nick!='ALL' else cfgreadnicks(...).split(',')` que les autres commandes
  multi-nick. Test de non-régression ajouté au `CodecSelfTest`.

## borgHelper 1.0.110 / borgHelperWWW 1.18.0 — envoi push réel (début+fin), watcher étendu — 2026-09-26

Story 2b de `spec-notifications-push` : le watcher `bkp_status` (Story 1) ne se contente plus de
journaliser, il envoie désormais un vrai push (`pywebpush`) à chaque abonnement concerné (Story 2a) —
à la fois au **début** d'une sauvegarde (nouveau, décision utilisateur ajoutée au spec) et à sa
**fin** (succès/échec/timeout AD-7, inchangé dans son critère de détection).

### `bkp_status.start_notified_at` (`borgHelper`, colonne + réclamation dédiée)

Réclamer un **début** de sauvegarde nécessite un second signal : `notified_at` (Story 1) ne couvre que
la fin, et un début est immédiatement éligible (`started_at` toujours posé dès l'`INSERT`), contrairement
à une fin qui attend soit `finished_at` soit le timeout AD-7. Nouvelle colonne `start_notified_at TEXT`
sur `bkp_status`, ajoutée par `ALTER TABLE ... ADD COLUMN` (même patron exact que `snapshot_file.type`/
`mode`/`owner`, contrôle via `PRAGMA table_info`) — `DIFF_DB_SCHEMA_VERSION` 6→7 (palier 7). Nouvel
index `idx_bkpstatus_pending_start ON bkp_status(nick, start_notified_at)`. Deux nouvelles méthodes
`BorgHelperDB`, gabarit symétrique exact de `list_pending_bkp_status`/`claim_bkp_status` (fin) :
`list_pending_bkp_status_start(nick, db_path=None)` (lecture seule, `WHERE start_notified_at IS NULL`,
aucun délai) et `claim_bkp_status_start(nick, run_id, db_path=None)` (CAS, `UPDATE ... SET
start_notified_at=datetime('now') WHERE ... AND start_notified_at IS NULL`).

### Watcher étendu (`borgHelperWWW`, `_bkp_status_watcher_pass`)

Chaque passage réclame désormais **deux** familles de lignes dans le même bloc `try`/`except` par nick
(isolation inchangée) : la réclamation de fin existante, **et** une nouvelle réclamation de début
(`list_pending_bkp_status_start`/`claim_bkp_status_start`). Chaque réclamation gagnée déclenche un
envoi push réel — remplace la simple journalisation (`stderr`) de la Story 1.

### Envoi push réel (`_send_bkp_push`, `pywebpush`)

Pour chaque réclamation gagnée (début ou fin), interroge `push_subscriptions` (`push.db`) : `scope_nicks`
(JSON) contient le nick, non expiré (`expires_at IS NULL OR expires_at > datetime('now')`), type
correspondant actif (`notify_start=1` pour un début, `notify_end=1` pour une fin). Pour chaque
abonnement matché : `pywebpush.webpush(subscription_info=..., data=<payload JSON>,
vapid_private_key=PUSH_VAPID_PRIVATE_KEY, vapid_claims={'sub': PUSH_VAPID_SUB})`. Payload :
`{"nick":..., "event":"start"|"end", "result":"success"|"error"|null, "timestamp":...}` — `result`
toujours `null` pour un début. Nouvelle variable `BORGHELPERWWW_PUSH_VAPID_SUB` (déf.
`mailto:admin@example.invalid`, générique — contact requis par le protocole Web Push RFC 8292, aucune
valeur "correcte" universelle ne pouvant être devinée pour un déploiement tiers).

Gestion d'erreur `pywebpush`, par abonnement, jamais propagée : `WebPushException` avec
`status_code in (404,410)` (abonnement mort côté navigateur) → désabonnement automatique (`DELETE FROM
push_subscriptions WHERE endpoint=?`, factorisé dans `_push_delete_endpoint`, réutilisé aussi par
`DELETE /push/subscribe`). Toute autre erreur (autre code HTTP, exception réseau/non-`WebPushException`)
→ journalisée seule (`[watcher] push: ...`), abonnement conservé, **aucun retry** : la ligne
`bkp_status` est déjà réclamée par CAS, elle ne sera jamais revisitée par aucun watcher — limitation
assumée (voir Design Notes du spec), pas un bug ; concevoir un retry par abonnement déplacerait le CAS
du niveau ligne-événement au niveau ligne-événement-×-abonnement, hors périmètre de cette story.

### Tests

`CodecSelfTest` (`borgHelper`) : migration `start_notified_at` sur une base `bkp_status` existante
(colonne absente, sans perte de données), `list_pending_bkp_status_start`, `claim_bkp_status_start` CAS
concurrent (deux réclamations simultanées, une seule gagne) — 314/314 `OK`. `push_selftest`
(`borgHelperWWW --selftest`) : `pywebpush.webpush` mocké — envoi réussi, `WebPushException(status_code=
410)` → désabonnement, `status_code` autre/exception réseau → conservé sans retry, filtrage
`notify_start`/`notify_end` — 26/26 `OK`. Test manuel réel sur `demo.borghelperrc` : abonnements avec
clés `p256dh`/`auth` factices mais valides (chiffrement Web Push réel) sur des `endpoint` de test
contrôlés (`httpbin.org/status/410` et `/status/500`), `Bkp` réel déclenché via `POST /bkp` — log
serveur confirmant réclamation début/fin, envoi réel, désabonnement automatique sur 410, conservation
sans retry sur 500 (détails : `TECHNICAL.md`).

### Non couvert (périmètre de la story suivante)

UI/Service Worker (Story 2c) : aucun changement ici, la notification affichée au navigateur reste à
construire.

## borgHelperWWW 1.17.0 — `push.db`, clés VAPID, abonnements push (`POST`/`PATCH`/`DELETE /push/subscribe`, `GET /push/subscriptions`) — 2026-09-26

Story 2a de `spec-notifications-push` : préalable indispensable à l'envoi réel de notifications push
(Story 2b, qui câblera le watcher `bkp_status` de la story précédente à `pywebpush`) — cette story ne
fait que stocker/exposer les abonnements navigateur et générer les clés VAPID, aucun vrai push envoyé.

### `push.db` : nouveau fichier dédié (jamais `scopecache.db`, AD-6)

`ensure_push_db()` : même gabarit exact que `ensure_scope_cache_db()` (`db_meta`/`_check_set_meta`,
`PUSH_DB_SCHEMA_VERSION`=1, `sqlite3.DatabaseError` → message + `sys.exit(1)`, appelée une fois au
démarrage) — réglage `BORGHELPERWWW_PUSH_DB`/`--push-db`, défaut co-localisé avec `cache.db`/`diff.db`.
Deux tables : `push_vapid_keys` (`id` unique, `CHECK(id=1)`) et `push_subscriptions` (`endpoint`
`UNIQUE`, `scope_nicks` JSON figé, `notify_start`/`notify_end`, `expires_at` nullable = « à vie »).

### Clés VAPID (EC P-256), générées une fois au premier démarrage

Via `py_vapid` (dépendance transitive de `pywebpush`, confinée à `borgHelperWWW` — AD-5, `borgHelper`
reste stdlib-only). Stockées en brut base64url (compatible `py_vapid.Vapid.from_string()` pour la
Story 2b **et** `applicationServerKey` navigateur pour la clé publique, sans ré-encodage). Jamais
régénérées ensuite. Clé publique exposée sur `GET /version` (déjà public) : `vapid_public_key`.

### Routes `/push/*`

`POST /push/subscribe` : upsert par `endpoint` (`INSERT ... ON CONFLICT DO UPDATE`) — `scope_nicks`
calculé à chaque appel via le même mécanisme que `GET /access` (tout nick où `eff>=1`), recalculé à
chaque réabonnement explicite (jamais entre-temps, AD-4). `expires_in_days` absent → défaut serveur
(`BORGHELPERWWW_PUSH_DEFAULT_EXPIRY_DAYS`, déf. 30, clampé) ; `null` explicite → « à vie » ; hors
bornes `[1, PUSH_MAX_EXPIRY_DAYS=3650]` (y compris une valeur absurde comme `999999999999`, qui ferait
sinon déborder silencieusement `datetime('now','+N days')` côté SQLite vers `NULL`, donc « à vie » par
accident) → même repli que l'absence. Logique de résolution (`_resolve_push_expiry_days`) partagée
entre `POST` et `PATCH`, plus de copie dupliquée. `PATCH /push/subscribe` : préférences + expiration
seules, jamais `scope_nicks` — 404 explicite si `endpoint` inconnu (pas de création silencieuse) ;
`notify_start`/`notify_end` explicitement `null` → `422` (pas d'état « null » significatif, contraire
à `expires_in_days`, jamais un no-op silencieux). `DELETE /push/subscribe` : idempotent,
`{"deleted": bool}`, jamais 404 bruyant. `GET /push/subscriptions` : abonnement(s) connus pour un
`endpoint`. Toutes protégées par `X-API-Key` uniquement ; cataloguées dans `_ROUTE_LEVELS` par
cohérence mais `_check_group_access` les laisse toujours passer (pas de paramètre `nick`, comme
`/access`) — le RBAC réel se fait dans le corps de la route via `scope_nicks`, et `endpoint` agit de
facto comme un jeton de capacité (README) : quiconque détient une clé API valide et connaît/devine un
`endpoint` peut lire/modifier/supprimer l'abonnement correspondant, quel que soit son propre périmètre
par groupes — compromis de conception assumé, pas un oubli.

`endpoint`/`keys.p256dh`/`keys.auth` : `Field(min_length=1)` — une chaîne vide n'occupe plus
silencieusement le créneau `UNIQUE` de `endpoint`. Après le commit d'un `POST`/`PATCH`, un garde
défensif (`row is None` → `410`) couvre le cas, rare mais réel, d'un `DELETE` concurrent (autre
connexion) entre le commit et le `SELECT` final construisant la réponse — jamais un `TypeError` 500
brut depuis `_push_row_to_dict(None)`.

### Vérification

`push_selftest()` (`borgHelperWWW --selftest`, équivalent `CodecSelfTest` adapté — la logique testée
est confinée à `borgHelperWWW`, AD-5) : génération VAPID (une fois), CRUD abonnement, calcul
`expires_at` (fourni/absent/« à vie »), clamp de `BORGHELPERWWW_PUSH_DEFAULT_EXPIRY_DAYS`, bornes de
`_resolve_push_expiry_days`, et désormais aussi la boucle `eff>=1` de calcul de `scope_nicks` sous
`GROUPS_HEADER` (`_scope_nicks_for_groups`, cœur de `_current_scope_nicks` extrait pour rester
testable sans `Request` réelle — cette branche n'était exercée par aucun test jusqu'ici, le CRUD
insérant `scope_nicks` en SQL brut et la vérif manuelle tournant `GROUPS_HEADER` désactivé) — 19/19
`OK`, sur fichiers temporaires uniquement. Testé en direct sur `demo.borghelperrc` (`curl` : création,
lecture, modification des préférences et de l'expiration, suppression idempotente, réabonnement =
mise à jour sans doublon, et les cas d'erreur ci-dessus : endpoint vide `422`, `expires_in_days`
absurde replié sur le défaut, `notify_start:null` rejeté `422`).

## borgHelper 1.0.109 / borgHelperWWW 1.16.0 / borgHelperWWW_ui.html 1.9.1 — détection de fin de sauvegarde (`bkp_status`), `POST /bkp` asynchrone — 2026-09-25

Story 1 de `spec-notifications-push` : préalable indispensable à l'envoi de notifications push
(Story 2, à venir) — un signal fiable pour savoir, après coup et quel que soit le déclencheur, si
une sauvegarde `Bkp` a réussi ou échoué.

### ⚠️ Rupture de compatibilité : `POST /bkp` (`borgHelperWWW`) devient asynchrone

Jusqu'ici synchrone : la requête HTTP restait ouverte toute la durée de la sauvegarde et recevait le
résultat complet (`CommandResult` : `exitcode`/`stdout`/`stderr` de `borgHelper -c Bkp` lui-même).
Désormais : `POST /bkp` lance `borgHelper -c Bkp` en sous-processus **détaché**
(`subprocess.Popen(..., start_new_session=True)`, jamais attendu par la requête) et répond dès le
lancement confirmé — `exitcode=0`/`stdout="Sauvegarde démarrée pour <nick> (pid <pid>) — ..."`
signifie **« lancement réussi »**, plus « sauvegarde réussie ». Tout appelant externe de cette route
qui interprétait la réponse comme le résultat final de la sauvegarde doit s'adapter (interroger l'état
autrement — pas d'équivalent HTTP pour l'instant, la Story 2 ajoutera la notification push). Seul
appelant interne recensé, `runBackupNow` (UI), adapté dans le même commit (affiche « démarré », plus
d'attente du résultat).

### `bkp_status` : nouvelle table (`diff.db`, exclusive à `Bkp`)

`nick, run_id, started_at, finished_at, result('success'|'error'), notified_at` — ajoutée dans
`ensure_diff_db()` (additive, `CREATE TABLE IF NOT EXISTS`, comme `archive_stats`/`diff_excluded_stats`
en leur temps : pas de bump `DIFF_DB_SCHEMA_VERSION`, aucune donnée existante à transformer). Aucune
colonne `path` : hors du périmètre du codec de chiffrement des chemins, jamais touchée par
`_write_mode_check`/`_path_stored`. Jamais écrite par `Restore`/`Index`/`Prune` — exclusive à
`backup()`.

`backup()` écrit une ligne à son début (juste après `set_priority_lock`, avant tout appel `boex()`),
`started_at` posé, tout le reste `NULL`. À la fin normale (avant `sys.exit(newretC)`), la ligne est
complétée : `finished_at`, `result` dérivé du même `newretC` qu'aujourd'hui (`0`→`success`, sinon
`error`). **Filet de sécurité** dans le `finally` existant (qui relâche déjà `priority.lock`) : si une
exception non gérée (`boex()` ou ailleurs) a empêché l'écriture normale, la ligne encore sans
`finished_at` est fermée immédiatement en `result='error'` — sans attendre le timeout watcher
ci-dessous (qui reste un filet supplémentaire pour un processus tué avant même d'atteindre ce
`finally`, ex. SIGKILL/OOM). Nouvelles méthodes `BorgHelperDB` : `store_bkp_status_start`,
`store_bkp_status_finish`, `store_bkp_status_safety_net`, `list_pending_bkp_status`,
`claim_bkp_status`.

### Watcher `borgHelperWWW` (premier composant de fond du fichier)

Tâche de fond démarrée via `@app.on_event("startup")` (un watcher par processus worker uvicorn,
cohérent avec `--workers 2` déjà documenté — aucune coordination inter-process requise). Interroge
`bkp_status` de chaque nick connu toutes les 30s (`BORGHELPERWWW_BKP_WATCHER_INTERVAL`), réclame par
comparer-et-échanger (`UPDATE bkp_status SET notified_at=? WHERE nick=? AND run_id=? AND notified_at
IS NULL`, via `_with_lock_retry` réutilisé tel quel — jamais de lecture-puis-écriture séparées, donc
jamais de double traitement même avec plusieurs workers) les lignes terminées, ou bloquées depuis plus
de 6h (`BORGHELPERWWW_BKP_STATUS_TIMEOUT`, largement supérieur à la durée normale d'un `Bkp` — une
ligne `started_at` sans `finished_at` passé ce délai est traitée comme un échec). Pour cette story,
journalise (log serveur) `nick`/`run_id`/`result` — la Story 2 remplacera la journalisation par
l'envoi push réel (`pywebpush`).

Vérifié par test réel sur `demo.borghelperrc` : `POST /bkp` répond en ~0.1s (contre la durée complète
de la sauvegarde auparavant) ; ligne `bkp_status` observée `started_at` posé puis `finished_at`/
`result='success'` à la fin réelle du `Bkp` ; watcher réclame et journalise dans la minute suivante.
Plus `CodecSelfTest` (le nom ne couvre plus que l'historique — convention existante pour toute
vérification DB de ce projet) : écriture start/finish/filet de sécurité, `list_pending_bkp_status`
(lignes finies + AD-7, jamais les récentes), `claim_bkp_status` CAS concurrent (`ThreadPoolExecutor`,
une seule des deux réclamations gagne) — 309/309 `OK`.

## borgHelperWWW_ui.html 1.9.0 — graphiques Chart.js dans « Historique complet » — 2026-09-25

Story 3 (spec-charts-evolution-sauvegardes) : `/repohistory`/`/archivehistory` (Story 2, 1.15.3)
exposaient déjà les valeurs brutes nécessaires, mais rien dans l'UI ne les affichait dans le temps —
seul un tableau texte (`/report`, valeurs déjà formatées, ex. « 1.23 GB », inutilisables pour un
graphique) existait. Chart.js 4.5.1 chargé une seule fois en CDN
(`cdn.jsdelivr.net/npm/chart.js@4.5.1`, avant le `<script>` principal, AD-7) — aucune
`Content-Security-Policy` n'existe dans ce fichier, rien à ajuster côté `borgHelperWWW`.

Nouvelle `.card` dans `#view-history`, sous le tableau existant, trois `<canvas>` : `chartRepoSize`
(ligne, `unique_csize`/`total_size`/`total_csize` par `updated_at`, points marqués différemment selon
`op='bkp'`/`'prune'` — cercle bleu / triangle rouge), `chartPruneGain` (barres, un point par événement
Prune), `chartArchiveSize` (ligne, `original_size`/`compressed_size`/`deduplicated_size` par
`archive_date`). Nouvelle fonction `loadCharts(nick)`, appelée depuis `openHistory(nick)` en plus de
(pas à la place de) `loadHistoryFull(nick)` — deux appels réseau indépendants (`Promise.all`) qui ne se
bloquent pas mutuellement, `apiCall('GET','/repohistory'|'/archivehistory',{nick},false)` puis
`JSON.parse(r.stdout)`, patron exact de `apiCall` déjà utilisé partout.

Forme de la réponse **non indexée par nick** (contrairement à `/report`/`/treehist`) :
`{'borghelper_version','nick','rows':[...]}` — accès direct `parsed.rows`, jamais `parsed[nick]`.
Ligne d'erreur (`diff.db` jamais indexé) `{'error':...}` distinguée explicitement, `rows:[]` (nick sans
historique) et absence de Prune (graphique 2) chacun avec leur propre message `hint`/`error` à la place
du graphique concerné — jamais de canvas Chart.js vide ni d'exception JS.

Gain Prune (graphique 2) calculé **entièrement côté client**, à partir des mêmes lignes `repohistory`
déjà chargées pour le graphique 1 (pas de second appel) : pour chaque ligne `op='prune'`, delta =
`unique_csize` de la ligne précédente moins `unique_csize` de cette ligne, valeur brute non tronquée —
aucune valeur envoyée au serveur, aucune persistance (paradigme de la spine, AD-1/AD-3). Garde de course
dédiée (`chartsLoadSeq`, même patron que `historyLoadSeq`/`browseLoadSeq`) et `chart.destroy()`
systématique avant toute recréation d'instance — une réponse tardive pour un ancien nick ne dessine
jamais sur le graphique du nick actuellement affiché.

Vérifié : `demo.borghelperrc`, `Init`+3×`Bkp`+1×`Prune` réels sur `demo-modules`, `borgHelperWWW` lancé
localement (`-K testkey --port 18765`) ; `curl` direct sur `/repohistory`/`/archivehistory` (200, JSON
brut conforme, `rows` avec 4/2 lignes attendues, delta Prune recalculé à la main = 1376 octets,
identique au calcul JS) et sans clef (401). Logique de rendu (parsing `rows`/`error`, calcul du delta
Prune, messages `hint`/`error`, formatage octets) rejouée en isolation sous Node avec les JSON réels
renvoyés par le serveur (`Chart` stubbé) : aucune exception, tous les cas de l'I/O matrix couverts
(peuplé, `rows:[]`, `{'error':...}`, aucun Prune). `python3 -m py_compile borgHelper borgHelperWWW`
propre (aucun fichier Python modifié par cette story). Vérification visuelle dans un navigateur réel
non effectuée (aucun outil de capture d'écran/navigateur disponible dans cet environnement) — à refaire
manuellement avant mise en production.

`borgHelperWWW_ui.html` 1.8.0 → **1.9.0** (`borgHelperWWW`/`WWW_VERSION` et `borgHelper`/`Version`
inchangés — aucune ligne de ces deux fichiers modifiée par cette story).

## borgHelperWWW 1.15.3 — routes `/repohistory`, `/archivehistory` — 2026-09-25

Story 2 (spec-charts-evolution-sauvegardes) : `repo_stats` (historique, 1.0.107) et `archive_stats`
n'étaient exposées par aucune route — rien ne permettait à l'UI de tracer l'évolution d'un dépôt dans
le temps. Deux nouvelles routes `GET /repohistory?nick=<nick>` et `GET /archivehistory?nick=<nick>`,
patron exact de `/idxtop`/`/cacheinfo` : `nick` en paramètre de requête requis (jamais un segment
d'URL — `_check_group_access` lit `request.query_params.get('nick')`, un segment le contournerait
silencieusement), `require_api_key`, délégation au sous-processus `borgHelper -c RepoHistory`/
`-c ArchiveHistory -j` (AD-1, jamais d'accès SQLite direct depuis `borgHelperWWW`), `cacheable=True`
(lecture pure `diff.db`, même empreinte mtime que `/idxtop`/`/difftop`). `_ROUTE_LEVELS` : deux
nouvelles entrées niveau `1` (lecture). Pas de filtrage par périmètre de chemin (`_resolve_single_scope`) :
ces agrégats ne portent aucun chemin de fichier, seul le niveau d'accès par nick s'applique.

Côté `borgHelper` : nouvelles commandes CLI `RepoHistory`/`ArchiveHistory -n <nick> -j`, gabarit exact
de `IdxTop -j` — requête SQL directe (`repo_stats`/`archive_stats WHERE nick=?`, ordre chronologique),
JSON brut `{'borghelper_version','nick','rows':[...]}`, colonnes brutes uniquement (aucune métrique
dérivée calculée ici — reste pour l'affichage, Story 3). Un seul nick à la fois : `nick=a,b`/`ALL` sur
plusieurs nicks rejeté par `usage(cmd)` (code de sortie non nul), même contrôle que `IdxTop -j`. `diff.db`
jamais indexé : `{'error':...}`, jamais une exception non attrapée.

12 nouveaux contrôles `CodecSelfTest` dédiés (299/299 OK) : table peuplée (ordre par `id`/`archive_date`),
table vide, `diff.db` absent, isolation entre plusieurs nicks, mode texte sans `-j` (pas de crash),
rejet CLI multi-nick (`a,b` et `ALL` après expansion). Vérifié aussi de bout en bout sur
`demo.borghelperrc` (`Init`+`Bkp` réels, `borgHelperWWW` lancé localement) : `curl` sur les deux routes
avec clef API valide (200, JSON), sans clef (401), `nick=a,b` (400), nick inconnu ({'error':...} en 200
côté cache/RBAC désactivé — RBAC nick-level testé au niveau du dictionnaire `_ROUTE_LEVELS`/
`_check_group_access`, mécanisme inchangé).

Deux correctifs issus de la revue : `repo_history()`/`archive_history()` gagnent le même garde-fou
`_db_has_schema()` que le reste de la couche `diff.db` — un nick jamais indexé mais dont le fichier
`diff.db` existe (table absente) renvoyait auparavant l'erreur SQLite brute « no such table », remplacée
par le même `{'error':...}` propre que le cas fichier absent. RBAC (403 niveau insuffisant / nick inconnu)
revérifié en direct sur `/repohistory`/`/archivehistory` avec `BORGHELPERWWW_GROUPS_HEADER` effectivement
configuré (et pas seulement présumé par analogie avec `/idxtop`).

## borgHelper 1.0.108 — commandes CLI `RepoHistory`/`ArchiveHistory` — 2026-09-25

Story 2 (spec-charts-evolution-sauvegardes) : voir l'entrée `borgHelperWWW 1.15.3` ci-dessus pour le
détail — nouvelles méthodes `BorgHelper.repo_history()`/`archive_history()` et commandes CLI associées,
consommées par les nouvelles routes `borgHelperWWW`.

## borgHelper 1.0.107 — `repo_stats` historique + capture du gain Prune — 2026-09-25

`repo_stats` (`diff.db`) n'était jusqu'ici qu'un instantané écrasé par nick (`INSERT OR REPLACE`, clé
primaire `nick`) — l'évolution de la taille du dépôt dans le temps et le gain réel d'un Prune étaient
perdus, alors que les valeurs brutes nécessaires (`unique_csize`/`total_size`/`total_csize`) sont déjà
récupérées de `borg` à chaque `Bkp`. Nouveau schéma historique, une ligne par événement : `id INTEGER
PRIMARY KEY AUTOINCREMENT`, colonne `op` (`'bkp'|'prune'`). Migration des bases existantes par contrôle
structurel (`if 'op' not in cols`), même patron que `_migrate_archive_snapshot` — la ligne unique par
nick devient la première ligne historique `op='bkp'`, aucune valeur perdue ; une DB neuve reçoit le
nouveau schéma directement. Comme pour `archive_snapshot`, cette migration n'est jamais gatée par
`schema_version`/`db_meta` (bookkeeping en écriture seule) — palier `DIFF_DB_SCHEMA_VERSION` 6, purement
documentaire.

`Prune` capture désormais une ligne `op='prune'` : appel léger `borg info --json` (métadonnées seulement)
fait **après** `compact --cleanup-commits`, jamais juste après `prune --stats` — c'est `compact` qui
libère réellement l'espace disque, un appel plus tôt donnerait un delta gain-Prune faux/quasi nul. Rien
n'est écrit en `--dry-run`. `store_repo_stats()` passe d'un `INSERT OR REPLACE` à un `INSERT` historique
et purge, dans la même transaction, les lignes plus anciennes que `STATS_RETENTION_MONTHS` (nouvelle clef
`.borghelperrc` par nick, 13 mois par défaut, même patron que `KEEP_DAILY`/`DIFF_KEEP`). `get_repo_stats()`
lit désormais `ORDER BY id DESC LIMIT 1` (au lieu d'un `SELECT` nu sans ordre) — nécessaire dès qu'une
même seconde peut porter deux événements (`updated_at` à résolution seconde).

Aucune métrique dérivée stockée : le gain Prune (delta entre la ligne juste avant et juste après un
`op='prune'`) et tout calcul de ce type restent pour l'affichage (graphiques `borgHelperWWW`, hors
périmètre de cette livraison) — seules les valeurs brutes borg sont persistées, comme pour `archive_stats`.
`archive_stats` et son mécanisme de purge (via Prune uniquement) restent inchangés.

6 nouveaux contrôles `CodecSelfTest` dédiés (286/286 OK) : migration ancien schéma → historique,
schéma direct sur DB neuve, historisation append-only + `get_repo_stats` sur la dernière ligne, résolution
du cas deux lignes à la même seconde (plus grand `id`), purge par ancienneté (défaut 13 mois), surcharge
`STATS_RETENTION_MONTHS` par nick. Vérifié aussi de bout en bout sur `demo.borghelperrc` (Bkp réel ×2 puis
Prune réel) : lignes `op='bkp'`/`op='bkp'`/`op='prune'` cohérentes en base ; confirmé par ailleurs qu'un
Prune en `--dry-run` n'écrit aucune ligne.

`_stats_retention_months` clampe désormais toute valeur `< 1` (0 ou négative) au défaut de 13 mois, comme
le fallback déjà existant pour une valeur non numérique — `0` rendait `datetime('now','-0 months')` égal
à « maintenant » (purge de la quasi-totalité de l'historique à chaque écriture), une valeur négative
produisait un modificateur SQLite invalide (`datetime()` → `NULL`, purge silencieusement no-op). 1 contrôle
`CodecSelfTest` supplémentaire dédié au fallback non-numérique existant (287/287 OK).

## borgHelper 1.0.106 — chiffrement des chemins SQLite, story 6 (suite) : correctif `TreeHist` à la racine — 2026-09-23

Story 6 (1.0.105) avait confirmé 4 sites au-dessus du seuil de jugement (>1 s) par la mesure, sans les corriger
(Boundaries de la story : décision posée à l'utilisateur). Décision reçue : corriger `TreeHist` à la racine
(le plus sévère, 5,7 s en base chiffrée), documenter/différer les 3 autres (`TreeFind`, `DuIdx -R`, `IdxTop`).

`TreeHist` à la racine fait deux lectures pleine-table sans possibilité de filtre SQL sur le nom (AD-8) :
l'instantané complet (`snap_rows`, pour les enfants présents) et `diff_index` sans borne (`del_rows`, pour les
supprimés récupérables). Le premier correctif tenté sur `del_rows` (requête fenêtrée `ROW_NUMBER()`, comme
suggéré) a été **mesuré plus lent** que l'original — le tri qu'exige la fenêtre coûte plus cher que les ~300
requêtes ponctuelles (déjà bon marché, indexées) qu'il économise ; non retenu. Correctif retenu à la place :
AD-3 ne chiffre pas le séparateur `/` entre segments, donc la profondeur d'un chemin est déjà lisible sur sa
valeur **stockée** sans la décoder (fuite de structure déjà acceptée, Deferred de la spine) — filtrer sur la
valeur stockée AVANT `_path_decode` évite l'essentiel du décodage. Mesuré isolément (même connexion/jeu, 5
essais, médiane) : `del_rows` ×56–58 plus rapide (4 365 ms → 77,7 ms à 250k lignes `diff_index` ; 16 649 ms →
285 ms à 1M). Ce filtre s'applique quel que soit le préfixe (racine ou non, conditionné seulement par
`conn.codec is not None`) — sans effet mesurable pour un préfixe non vide, `_psel_under` bornant déjà le
`SELECT DISTINCT` à un petit sous-arbre.

Pour `snap_rows`, un premier correctif (décoder SEULEMENT le premier segment de chaque chemin, nouvelle méthode
`decode_first_segment`) a été **retiré après revue** : il faisait perdre la détection d'altération sur tout
segment à 2 niveaux de profondeur ou plus dans `snapshot_file.path` — une régression de sécurité réelle par
rapport au comportement d'avant cette story (`TreeHist` à la racine avait la même garantie que `Search`, testée
par `_tamper_search`). Corrigé en gardant le gain de performance mais sans concession de sécurité : nouvelle
méthode `DbCodec.decode_path_verified` décode et valide CHAQUE segment (même garantie que `_path_decode`), mais
mémoïse par segment partagé entre chemins de même préfixe de répertoires — ×3,4 plus rapide (4 835 ms → 1 418 ms
à 250k) plutôt que ×6 pour la version retirée, sans compromis. Un contrôle `CodecSelfTest` dédié corrompt
spécifiquement le 2e segment d'un chemin imbriqué (1er segment intact) et vérifie que `TreeHist` à la racine
échoue proprement (`DbCodecError`, pas de traceback) — il aurait échoué avec `decode_first_segment`, il passe
avec `decode_path_verified` (280/280, +1 contrôle par rapport à 1.0.105).

Bout en bout (`PerfBench`, 3 exécutions) : `TreeHist` racine chiffré 5 675–7 607 ms → **1 927–2 182 ms**, soit
**×2,6 à ×4** selon les exécutions comparées (plage, pas un chiffre unique — variance d'une exécution complète à
l'autre), toujours au-dessus du seuil de 1 s. Le reste du coût (une requête `DISTINCT archive_new,archive_new_date`
par répertoire de tête dans `_events_for`, plus un balayage complet supplémentaire pour l'entrée `.` elle-même)
n'a pas été touché dans cette livraison, documenté dans TECHNICAL.md pour une décision séparée.

`PerfBench` gagne aussi une mesure LIKE-préfixe-vs-intervalle-d'index reproductible (24,5 ms vs 0,15 ms à 250k
lignes, ~×163), qui remplace dans TECHNICAL.md le chiffre jetable 170 ms → 1 ms de la Story 2 (déjà retiré en
1.0.105, jamais vraiment remplacé jusqu'ici) ; et `-K` sans `-n` explicite ne migre plus le jeu par défaut
(83k–333k lignes) mais un jeu réduit dédié (`_PB_KDF_DEFAULT_ROWS=30000`), conforme au « plus lent, optionnel »
déjà documenté — `-n` explicite (même combiné à `-K`) continue de gouverner la taille migrée, comme avant.

- **`DbCodec.decode_path_verified(stored)`** (nouvelle méthode, remplace la tentative retirée
  `PathCodec.decode_first_segment`, supprimée). Décode/valide chaque segment comme `PathCodec.decode`, mémoïsé
  par segment (`(prev_tag,segment_chiffré) -> (segment_clair,tag)`, borné comme le mémo existant).
- **`_treehist_listing`** : `snap_rows` (racine, base chiffrée) utilise `decode_path_verified` ; `del_rows`
  filtre la valeur stockée (comptage de `/`) avant tout décodage, ne décode et n'interroge que les candidats
  structurellement enfants directs — ce filtre s'applique à tout préfixe (racine ou non), pas seulement à la
  racine.
- **`CodecSelfTest`** : nouveau contrôle d'altération à 2 niveaux de profondeur sur `TreeHist` racine (mirroir
  de `_tamper_search`).
- **`perf_bench()`** : nouvelle mesure LIKE-vs-intervalle-d'index (« Plan d'exécution ») ; `-K` sans `-n`
  explicite migre désormais un jeu réduit dédié au lieu du jeu par défaut ; docstring de valeur de retour
  corrigée (0 si tout s'exécute, 1 si une mesure a levé une exception — ce que le code a toujours fait).
- **Architecture Spine** (Deferred) : `TreeFind`/`DuIdx -R`/`IdxTop` portent désormais leurs chiffres mesurés
  (décision : documenter et différer, pas de correctif) ; croissance des bases (×1,87) et taille des lots de
  migration (~85–115 ms/lot) marquées résolues par la mesure.

## borgHelper 1.0.105 — chiffrement des chemins SQLite, story 6 : mesures de performance (PerfBench) — 2026-09-23

TECHNICAL.md listait, depuis la Story 2, une dizaine de points « à mesurer en Story 6 » sur une base réaliste
(jusqu'à plusieurs Go) — aucun n'avait de chiffre réel, et le seul chiffre publié (170 ms → 1 ms) provenait
d'une table jetable non reproductible. Cette livraison ajoute `PerfBench`, un harnais reproductible qui
construit un jeu de données synthétique par `INSERT`/`executemany` directs (jamais un vrai `borg backup`,
bien trop lent pour représenter plusieurs Go en temps de test raisonnable), sur des bases temporaires plain
et chiffrée, et chronomètre chaque commande listée. Les chiffres réels remplacent les estimations dans
TECHNICAL.md. Vérifié par `CodecSelfTest` (279/279, inchangé) et `PerfBench` (jeu par défaut, 250 000 lignes
`diff_index` par mode, ~37 s, aucun résidu temporaire avant/après).

- **`PerfBench [-n <taille>] [-K]`.** Comme `CodecSelfTest`, s'exécute avant `BorgHelper()` (aucune vraie
  base/rc touché). `-n` : nombre de lignes `diff_index` visé par mode (défaut 250 000 — voir TECHNICAL.md pour
  la justification de cet ordre de grandeur). `-K` : ajoute le coût KDF par niveau (`light`/`standard`/`strong`)
  et une mesure réelle `DbEncrypt`/`DbDecrypt` sur un jeu réduit (30 000 lignes, pour rester rapide — le coût
  KDF et la migration par lot ne dépendent pas de la taille du jeu complet pour donner un chiffre représentatif).
  Chronomètre `TreeHist` (racine et sous-répertoire profond), `TreeFind`, `Search`, `DuIdx -R`, `IdxTop`,
  `DiffTop`, `_find_last_archive_with_file`, `IdxPurge -D`, et le mémo de décodage (`DbCodec._memo`, passe
  froide vs mémoïsée), en mode `plain` et `siv1`, sur les mêmes deux bases temporaires. Tout fichier temporaire
  nettoyé en `finally` (succès ou échec).
- **4 sites confirmés problématiques par la mesure** (seuil : >1 s sur le jeu de référence, pour une commande
  de lecture interactive) : `TreeHist` à la racine en base chiffrée (5,7 s — `SELECT DISTINCT path` sans borne
  puis décodage de tout `diff_index`), `TreeFind` motif large à la racine (~1,05 s dans les deux modes —
  fenêtre `ROW_NUMBER()` qui décode tout le sous-arbre avant filtrage), `DuIdx` motif large `-R` (~1,3–1,5 s —
  mode brut sans agrégation SQL), `IdxTop` en base chiffrée (1,04 s). Aucun correctif appliqué : conformément
  aux Boundaries de la story, la décision (corriger maintenant vs documenter et différer) est posée à
  l'utilisateur plutôt que décidée ici. Détail et chiffres complets : TECHNICAL.md, section « Mesures PerfBench ».
- **Points du Deferred de l'Architecture Spine levés par la mesure** : `_MIGRATE_BATCH=2000` (~85–115 ms/lot,
  jugé correct, aucun changement proposé) ; coût KDF (20–70 ms/appel selon niveau, cohérent avec l'estimation
  AD-4) ; croissance de la base (×1,87 mesurée sur ce jeu, plain → chiffré, dans l'ordre de grandeur estimé
  2–2.5×).
- Le chiffre jetable 170 ms → 1 ms (Story 2) est retiré de TECHNICAL.md ; la section « Plan d'exécution »
  renvoie désormais aux mesures réelles de `PerfBench`.

## borgHelper 1.0.104 — chiffrement des chemins SQLite, story 5 : migration (DbEncrypt/DbDecrypt/DbRekey/DbStatus) — 2026-09-22

Dernière pièce du chiffrement des chemins : les Stories 1-4 posaient tout le mécanisme (codec, en-tête,
barrière AD-11, autorité de création AD-12, requêtes/écritures/caches indépendants du mode) mais aucune
base réelle ne pouvait encore passer en chiffré. Cette livraison ajoute `DbEncrypt`, `DbDecrypt`, `DbRekey`,
`DbStatus`, et active enfin l'avertissement AD-6 différé depuis la Story 1. Vérifié par `CodecSelfTest`
(279/279) et par un aller-retour réel sur `demo.borghelperrc` (`TreeHist`/`Search` identiques avant/après).
Revue post-implémentation : `-n ALL` correctement étendu pour les 4 nouvelles commandes CLI (comme
`CacheInfo`/`CacheClean`), `_db_migrate_cache` capturée par le même `except` que `_db_migrate_run` (sinon
traceback non attrapée sur un échec tardif), `DbRekey` capture désormais l'échec de sa propre CAS (même
discipline que ses autres refus), `_enc_header_cas`/`_enc_header_cas_delete` convertissent
`sqlite3.OperationalError` (contention) en `DbModeError`, `-D`+`-y` simultanés refusés explicitement, la
validation finale d'une migration reprise après interruption couvre aussi les lignes migrées avant la
reprise (échantillon `legacy`), et `_warn_plain_db` est protégée par un verrou (accès concurrent depuis
plusieurs threads).

- **`DbEncrypt -n nick [-D] [-y]`.** Migre `diff.db` en place, table par table (`snapshot_file` puis
  `diff_index` — `archive_snapshot` n'a pas de colonne `path` propre, rien à y migrer directement), par lots
  transactionnels de 2000 lignes (`_MIGRATE_BATCH`, valeur de départ non mesurée sur base réelle — voir
  TECHNICAL.md), curseur `(table,rowid)` persisté dans `enc_header.migration_cursor` (repris après
  interruption, DEK jamais régénérée). Convention `IdxPurge` : `-D` rapporte tables/lignes/espace estimé sans
  rien changer ; ni `-D` ni `-y` -> refus explicite, rien changé ; `-y` exécute réellement. Refuse si
  `DB_ENCRYPT=false` pour ce nick, si `check_index_running`/`check_priority_lock`/`check_report_running`
  signale une opération en cours, ou si l'espace disque libre est insuffisant (`shutil.disk_usage`, marge de
  120% de la taille actuelle du `.db` — `_DB_SPACE_MARGIN`, non mesurée, documentée). Avant le tout dernier
  commit (`path_enc: migrating -> siv1`), relit un échantillon de lignes migrées et vérifie l'aller-retour
  (`decode(stored)==original`) — jamais de commit final avant validation. `cache.db`
  (`cachejsonboexlm`) est purgée puis recréée directement en mode chiffré (pas de migration ligne à ligne,
  cohérent avec la Story 4).
- **`DbDecrypt -n nick [-D] [-y]`.** Symétrique (sens inverse, `path_enc: migrating -> plain` au commit
  final — l'en-tête est alors supprimé, jamais réécrit à `path_enc='plain'`, cf AD-2). Même discipline
  (verrous, curseur repris, validation avant le dernier commit). Pas de contrôle `DB_ENCRYPT` : déchiffrer
  reste toujours permis.
- **`DbRekey -n nick [-y]`.** Ré-enveloppe la DEK existante avec une nouvelle KEK (nouveau sel, nouveau
  nonce, `DB_KDF` courant du nick) — aucune ligne de donnée n'est rechiffrée. Refuse sur une base non `siv1`
  (rien à re-clé). Limitation documentée, non comblée : `borgHelperWWW` n'a aucun mécanisme pour être
  notifié d'un `DbRekey` exécuté en CLI (pas de canal inter-process dans ce projet) — son memo de codec
  (`_NICK_CODEC_MEMO`, Story 4) reste périmé jusqu'à son redémarrage.
- **`DbStatus -n nick/ALL`.** Affiche le mode (`plain`/`siv1`/`migrating`) de `cache.db` et `diff.db` pour
  chaque nick — lecture directe de `db_meta.enc_header` (seule exception documentée à AD-1 : aucune ligne
  de chemin/blob n'est lue, le codec n'entre jamais en jeu, donc aucune passphrase n'est nécessaire pour
  simplement annoncer un mode).
- **AD-6 activé.** `_open_db` avertit désormais une fois par base et par nick (stderr, précédent
  `_warn_rc_perms`) quand la base reste `plain` alors que `DB_ENCRYPT` est actif pour ce nick et qu'une
  passphrase est disponible — cite la commande `DbEncrypt` à lancer. Jamais bloquant (le mode `plain` reste
  valide, AD-2/AD-5).
- **Barrière AD-11 étendue.** `_open_db` refuse désormais (`DbModeError`) tout rôle non-admin sur une base
  `path_enc='migrating'` — seule la connexion admin de `DbEncrypt`/`DbDecrypt` peut l'ouvrir pendant la
  migration ; tout lecteur/écrivain concurrent (y compris un `Bkp`/`Index` déjà en cours d'ouverture) est
  refusé net plutôt que de voir un mode mixte.
- **Nouvelles primitives internes :** `_enc_header_cas`/`_enc_header_cas_delete` (mise à jour/suppression
  compare-and-swap d'un en-tête déjà existant — distinctes de `_enc_header_write`, réservée à la toute
  première écriture) ; `_check_disk_space` (nouveau, aucun précédent) ; champ d'en-tête `migrating_dir`
  (`'encrypt'`/`'decrypt'`, présent uniquement pendant `path_enc='migrating'`, disparaît au commit final) —
  dit laquelle des deux commandes a le droit de reprendre une migration interrompue (sans lui, `DbDecrypt`
  pourrait reprendre à tort une migration lancée par `DbEncrypt`, et réciproquement). Toute transition qui
  change `path_enc` reconstruit l'en-tête en entier via `_enc_header_build` (même DEK, nouveau sel/nonce/MAC)
  — le MAC de l'enveloppe couvre `path_enc`, un simple `dict(header,path_enc=...)` laisserait un MAC calculé
  pour l'ancien mode.

## borgHelper 1.0.103 — chiffrement des chemins SQLite, story 4 : caches + durcissement Sentry — 2026-09-22

Chiffre le dernier cache en clair de `borgHelper` (`cachejsonboexlm.details`) et durcit l'initialisation Sentry contre
la fuite de chemins/secrets (AD-9/AD-15). Toujours **aucune base réelle chiffrée** (`DbEncrypt` reste Story 5).
**Aucun changement observable en `plain`** : vérifié par `CodecSelfTest` (258/258).

- **`cachejsonboexlm.details` chiffré (AD-9).** `cache_prune_dryrun` et `cacheJsonBoexWithLM` chiffrent/déchiffrent le
  payload JSON via `conn.codec.blob.encrypt`/`decrypt` quand `conn.codec is not None` (les deux sites ouvrent déjà la
  base avec `nick=nick`, donc `conn.codec` est déjà correct — aucun changement de signature d'ouverture). No-op en
  `plain`. Une ligne illisible (`DbCodecError`, ex. MAC de blob invalide) est traitée comme un cache miss — borg est
  simplement rappelé — jamais comme une erreur propagée. Seule la colonne `details` est concernée ; `nom`/
  `lastmodified` restent en clair (déjà indispensables tels quels pour la clé `UNIQUE`).
- **Sentry durci (AD-15).** `sentry_sdk.init` reçoit désormais `include_local_variables=False` (repli automatique sur
  `with_locals=False` pour `sentry-sdk` < 1.26, où l'option a été renommée — le repli ne s'applique qu'à cette
  `TypeError` précise, toute autre remonte normalement) et un `before_send` (`_sentry_before_send`) qui redacte, dans
  `event['extra']`, `event['contexts']` et les `vars` de chaque frame de chaque exception capturée, toute valeur dont
  la clé évoque un chemin ou un secret (`passphrase`, `pw`, `dek`, `kek`, `k_path`, `k_enc`, `k_blob`, `k_hdr`,
  `chemin`, `path`, …), avec une profondeur de récursion bornée (au-delà : `'[truncated]'`, jamais la valeur brute).
  **Portée précise, ne pas surestimer** : seuls `extra`/`contexts`/les `vars` de frame sont couverts ; le **texte
  libre** du message d'exception lui-même (`event['exception']['values'][*]['value']`, ex. `FileNotFoundError:
  /home/nick/repo/...`) n'est PAS scrubbé — un chemin peut y apparaître verbatim. Limitation connue, documentée dans
  `deferred-work.md` (nécessiterait un filtrage par motif/heuristique de chemin, hors périmètre de cette story).
  `auto_enabling_integrations=False` reste seul (régression du CHANGELOG 1.0.98 : ne jamais lui adjoindre
  `default_integrations=False`, qui désactiverait aussi l'excepthook et couperait toute capture d'exception).
- **`CodecSelfTest`.** Trois nouveaux contrôles bout-en-bout : `cacheJsonBoexWithLM` **et** `cache_prune_dryrun` sur un
  nick dont le `cache.db` est chiffré (`details` chiffré au repos — vérifié différent du JSON en clair —, hit sans
  second appel borg, ligne altérée déclenchant un cache miss et un rappel borg plutôt qu'une exception) ; et
  `_sentry_before_send`/`_sentry_scrub` eux-mêmes (clés sensibles redactées, clé non sensible conservée, profondeur
  bornée -> `'[truncated]'`) — sans ce dernier contrôle, une régression sur le cœur d'AD-15 passait inaperçue avec
  tous les autres contrôles au vert. 261/261 contrôles passent (+3 vs 1.0.102).

## borgHelperWWW 1.15.2 — chiffrement des chemins SQLite, story 4 : scopecache + `_RESPONSE_CACHE` — 2026-09-22

Chiffre `scopecache.db` ligne par ligne avec la DEK du nick propriétaire et aligne `_RESPONSE_CACHE` sur AD-13
(passphrase dans la clé, jamais une erreur de clé mise en cache). `scopecache.db` reste elle-même une base **non
chiffrée** au niveau fichier (AD-9) : seule la colonne `result_json` change.

- **`scopecache.db` : chiffrement par ligne (AD-9).** Nouvelle fonction `_nick_owner_codec(nick)` : ouvre le `diff.db`
  du nick propriétaire de la ligne via le point d'ouverture unique `_open_db` (AD-1, passphrase résolue comme pour
  toute commande borgHelper de ce nick, donc jamais un second mécanisme de résolution), et retourne son `DbCodec` —
  ou `None` si le nick est en clair/jamais indexé (comportement actuel inchangé, ligne non chiffrée), ou le sentinel
  interne `_CACHE_LOCKED` si le nick est chiffré mais que sa passphrase est absente/incorrecte. Mémoïsé par
  (nick, empreinte de passphrase) dans `_NICK_CODEC_MEMO`, borné (`_NICK_CODEC_MEMO_MAX=256`), en mémoire du
  processus WWW uniquement — jamais persisté. `_scope_cache_get`/`_scope_cache_put` chiffrent/déchiffrent
  `result_json` via `codec.blob` quand le codec est présent ; un nick verrouillé (`_CACHE_LOCKED`) dégrade la lecture
  et l'écriture en no-op silencieux (jamais une lecture erronée, jamais une erreur visible pour l'appelant) ; une
  ligne illisible (`DbCodecError`) est un cache miss, jamais une exception propagée.
- **`_RESPONSE_CACHE` aligné sur AD-13.** La clé inclut désormais un condensé HMAC-SHA256 salé
  (`_RESPONSE_CACHE_SALT`, aléatoire par processus, jamais persisté) de la passphrase de la requête
  (`_passphrase_digest`) — deux passphrases différentes pour le même `(cmd,nick,args)` n'interfèrent jamais. Sans
  passphrase (route non protégée), la clé reste `(cmd,nick,args)` telle quelle : comportement inchangé pour une base
  `plain`. Un résultat détecté comme une erreur de clé/mode/altération (`_is_db_key_error` : `exitcode!=0` et l'un des
  marqueurs `DbKeyError`/`DbModeError`/`DbTamperError`/`DbCodecError` présent en sortie — ces exceptions ne sont pas
  toutes encore converties en JSON structuré côté `borgHelper`, la détection couvre donc aussi le traceback non
  attrapé ; sur-approximation par sous-chaîne assumée, documentée en commentaire) n'est jamais écrit dans
  `_RESPONSE_CACHE` : rejoué en erreur à chaque appel plutôt que servi comme obsolète.
  **Capacité** : une passphrase suffixant désormais la clé pour les appels protégés, un même `(cmd,nick,args)`
  interrogé avec plusieurs passphrases différentes occupe plusieurs entrées au lieu d'une seule — le seuil de purge
  totale à 500 entrées (inchangé) est donc atteint plus vite qu'avant cette version dans ce cas d'usage.
- **`_nick_owner_codec`** : `cfgread(nick)` n'est plus avalé par un `except (Exception,SystemExit)` générique —
  `configparser.Error`/`OSError` (cas attendus : rc absent/malformé) dégradent silencieusement en passphrase absente,
  toute autre exception dégrade de la même façon mais imprime un avertissement distinct sur stderr (pour distinguer
  une vraie mauvaise configuration serveur d'un simple nick verrouillé). `conn.close()` déplacé dans un `finally`
  séparé de la capture `DbKeyError`/`DbTamperError`/`DbCodecError`/`sqlite3.Error` : un échec de `close()` après une
  ouverture réussie ne fait plus passer à tort un codec valide pour `_CACHE_LOCKED` (mémoïsation collante sinon).
- Vérifié manuellement (pas de framework de test côté `borgHelperWWW`) : aller-retour chiffré/déchiffré sur
  `scopecache.db` pour un nick chiffré, comportement inchangé (clair) pour un nick plain, verrouillage silencieux
  (ni lecture ni écriture) pour un nick chiffré à passphrase absente/incorrecte, condensés de passphrase distincts
  (`''`/absente traitées identiquement, par choix délibéré — voir commentaire de `_passphrase_digest`), et détection
  positive/négative de `_is_db_key_error` — voir TECHNICAL.md pour le protocole reproductible.

## borgHelper 1.0.102 — chiffrement des chemins SQLite, story 3 : écriture — 2026-09-22

Fait passer chaque écriture de chemin par le codec et pose la barrière de migration (AD-11), sans chiffrer aucune base
réelle (`DbEncrypt` reste Story 5). **Aucun changement observable en `plain`** : `_path_stored`/`_write_mode_check` sont
des no-op/silencieux tant qu'aucun `enc_header` n'existe ; vérifié par `CodecSelfTest` (257/257) et par un `Bkp`/`Index`
complet sur `demo.borghelperrc`.

- **Écriture de chemin unifiée (AD-3/AD-8).** `store_diff_entries`, `store_archive_snapshot`, `_indexsnap_incremental`
  (chemins ajoutés via `borg list`) et le bloc d'écriture inline de `index()` passent désormais chaque valeur de chemin
  par `_path_stored(conn,path)` avant le paramètre SQL — les 4 sites qui écrivaient encore un chemin en clair,
  indépendamment du mode de la connexion.
- **Barrière de migration `_write_mode_check(conn)` (AD-11).** Relit `enc_header.path_enc` dans la transaction en cours
  et le compare au mode constaté à l'ouverture (`conn.mode`) ; lève `DbModeError` avant tout `INSERT`/`UPDATE`/
  `executemany` de chemin si le mode a changé depuis l'ouverture (migration passée en `migrating` entre-temps). Posée en
  tout premier dans les 4 sites ci-dessus — `_indexsnap_incremental` la pose deux fois : à l'ouverture, puis à nouveau
  juste avant la seconde phase d'écriture (fichiers ajoutés), qui suit un appel `borg list` en sous-processus capable de
  durer assez longtemps pour qu'un changement de mode survienne entre les deux. Ce n'est **pas** un verrou d'exclusion
  mutuelle (pas de `BEGIN IMMEDIATE` généralisé) — une garde de cohérence sur laquelle la Story 5 (`DbEncrypt`,
  compare-and-swap) s'appuiera sans retoucher ces sites.
- **`index()` : `DbModeError` interceptée spécifiquement, une fois par run.** Avant le `except Exception` générique
  existant : sur la première occurrence, la paire n'est ni marquée indexée ni committée, `set_index_pending_lock(nick)`
  est appelée (mécanisme `index_pending` existant, réutilisé sans être dupliqué), et un message dédié est imprimé
  (jamais « borg diff échoué »). Le mode changé étant durable pour le reste du run, un drapeau local évite de
  re-tester la barrière et d'écrire pour chaque paire restante — sans ce drapeau, chaque paire suivante émettait son
  propre `set_index_pending_lock`/message, bruyant et redondant. `Bkp` ne peut jamais échouer à cause de cette erreur :
  `index()` retourne normalement comme pour toute paire en échec.
- **`indexsnap()` : `DbModeError` interceptée spécifiquement (tentative incrémentale + fallback).** Même traitement que
  ci-dessus (message dédié, `set_index_pending_lock`, retour `1`, pas de "traceback"). Corrige un bug réel repéré en
  revue : sans cette interception, une `DbModeError` levée par `_indexsnap_incremental` remontait NON attrapée à
  travers `indexsnap()` puis l'appel `self.indexsnap(...)` en fin d'`index()` — masquée en échec générique par le
  `try/except Exception` de `backup()` (pas d'`index_pending` posé), mais une traceback brute jusqu'à l'utilisateur
  via `Index`/`Index -S` en CLI direct (aucun `try/except` englobant sur ce chemin).
- **`ensure_diff_db`/`ensure_cache_db(db_path, create=True)` (AD-12).** **Tous** les appelants de lecture — l'ensemble
  complet, pas un sous-ensemble — passent désormais `create=False` : `TreeHist`, `TreeFind`, `Search`, `DuIdx`,
  `ListBkp`, `ListBkpFiles`, `FileHist`, `DiffBkp`, `Report` en mode DB-only, `CacheInfo`
  (`BorgHelperDB.get_cache_rows`), purge/consultation de cache, recherche de dernière archive. Une base absente ou vide
  n'est plus créée par une simple lecture, qui répond « non indexé »/« index vide » comme si la base existait mais
  était vide. Seuls `Index`, `Bkp` et `indexsnap` (créateurs légitimes) gardent le défaut `create=True`.
  `list_backups`, `list_files` et `prep_report_from_db` gèrent maintenant explicitement l'absence de schéma
  (`sqlite3.OperationalError` contenant `no such table`, narrowé — pas un `except sqlite3.Error` générique qui
  confondrait une vraie corruption/erreur disque avec « jamais indexé ») comme un index vide, ferment systématiquement
  leur connexion sur ce chemin, et laissent remonter toute autre erreur — nécessaire car `_open_db` touche toujours un
  fichier 0 octet même en lecture seule (permissions à la création), donc `os.path.exists` seul ne suffit plus à
  distinguer « jamais indexé » de « base réelle » : nouvel helper `_db_has_schema(db_path)` (au moins une table,
  `timeout=60` comme `_open_db` ailleurs — un `database is locked` transitoire ne doit pas se lire comme « pas de
  schéma »), utilisé par `ensure_*_db(create=False)` et ces trois fonctions.
  `cache_prune_dryrun`, `cacheJsonBoexWithLM` (cache de sortie `boex`) et `diffbkp` restent des créateurs légitimes sur
  leur propre chemin d'écriture : elles ne créent plus la base pour un simple lookup (`create=False` au début, comme les
  autres lecteurs), mais réappellent `ensure_*_db()` (`create=True`, défaut) juste avant d'écrire un résultat en cache
  ou une paire nouvellement diffée — un miss de cache confirmé, ou une paire non indexée, écrivent toujours comme avant
  ; seul le lookup initial ne crée plus rien. `cache_prune_dryrun`/`cacheJsonBoexWithLM` n'appellent
  `purge_stale_cache(...)` (`role='write'`, touche aussi le fichier à l'ouverture) que si `_db_has_schema(db_path)` est
  déjà vrai — rien à purger, et rien à toucher, pour un cache jamais écrit.
- **`CodecSelfTest`** : aller-retour d'écriture (`store_diff_entries`/`store_archive_snapshot`) sur une base chiffrée
  temporaire ; simulation de bascule de mode pendant une transaction ouverte (`_write_mode_check` lève `DbModeError`,
  propagée sans être avalée, aucune ligne écrite) ; simulation équivalente pour `indexsnap()` (retour `1`,
  `index_pending` posé, pas de traceback) ; vérification qu'un nick jamais indexé/jamais mis en cache ne crée aucun
  schéma via l'ensemble des sites de lecture convertis (`ensure_diff_db`/`ensure_cache_db(create=False)`), y compris
  ceux qui appellent `borg` avant d'écrire (`boex` monkeypatché pour échouer immédiatement, déterministe).

## borgHelper 1.0.101 — chiffrement des chemins SQLite, story 2 : requêtes — 2026-09-22

Rend toutes les lectures de chemins indépendantes du mode (`plain`/chiffré) : préfixes et égalités passent par des
bornes/valeurs fournies par le codec, prédicats sur le nom et tris s'exécutent en Python sur des chemins décodés quand la
connexion est chiffrée (AD-8, AD-16). **Aucune base n'est chiffrée** : en `plain` les sorties et codes de sortie sont
inchangés, aux exceptions ci-dessous ; le mode chiffré est vérifié par `CodecSelfTest` sur des bases temporaires.

- **Comportements modifiés en `plain` par rapport à `a53b9fa`** (toutes les sorties `plain` étaient auparavant garanties
  identiques : les points ci-dessous sont les seules exceptions, listées explicitement ; le dernier documente au
  contraire un comportement volontairement PRÉSERVÉ malgré un changement qui aurait pu l'affecter) :
  - **Préfixe sensible à la casse (AD-16).** Un préfixe de chemin (`TreeHist -f`, `TreeFind -f`, `FileHist -f`,
    `DuIdx -f 'préfixe/*'`, `IdxPurge -x préfixe`) ne correspond plus qu'à la casse exacte : `/Etc` ne trouve plus `/etc`
    (l'ancien `LIKE` était insensible à la casse ASCII et n'utilisait pas l'index). Les préfixes sont aussi littéraux :
    `%` et `_` n'y sont plus des jokers (`DuIdx -f 'a%b/*'` ne remonte plus `aXYZb/…`, `TreeHist -f a%b` non plus).
    `Search`, `DuIdx` sans `/*` et `IdxPurge` (glob) gardent leurs prédicats de nom inchangés (`LIKE` insensible à la casse
    ASCII, `GLOB` sensible) et `FileHist` reste une égalité exacte (après normalisation, voir point suivant).
  - **Préfixe/chemin normalisé.** Un `/` initial ou final, ou un `//` interne, dans un préfixe (`TreeHist -f`,
    `TreeFind -f`, `DuIdx -f 'préfixe/*'`) ou un chemin exact (`FileHist -f`) est maintenant retiré/fusionné avant
    comparaison, dans les deux modes (`plain` comme chiffré, un seul normaliseur `_norm_lp`) : `-f /etc`, `-f etc/` et
    `-f etc` donnent désormais le même résultat, `FileHist -f /etc/passwd` trouve la même entrée que
    `FileHist -f etc/passwd`. Auparavant le comportement différait selon la présence de ces caractères (l'ancien `LIKE`
    de préfixe les traitait différemment de l'égalité de `FileHist`, elle-même sensible au moindre `/` superflu).
  - **`DuIdx` global : correction du filtre de plage d'archives.** `_duidx_collect_global` plaçait la condition de plage
    (`archive_new=?`, dernière archive par défaut) *après* le `GROUP BY` : elle devenait une expression de regroupement
    au lieu d'un filtre, si bien que toutes les entrées de diff étaient comptées, toutes archives confondues, sous un
    seul type arbitraire. La condition est maintenant placée avant le `GROUP BY` : le résumé global par type change (il
    est désormais correct). Nécessaire pour que `DuIdx` donne les mêmes résultats en `plain` et en chiffré.
  - **Ordre des lignes non contractuel.** `DuIdx -R`, `IdxTop -j` et `DiffTop -j` peuvent renvoyer leurs lignes dans un
    ordre différent (ordre d'index au lieu de l'ordre de table) : ces sorties n'ont jamais été triées, l'ordre n'était
    qu'un détail d'implémentation de l'ancien `LIKE`/balayage de table.
  - **`IdxPurge` avec un `/` initial : comportement inchangé.** Un pattern (`-x` ou une entrée `IDX_INCLUDE`/`IDX_EXCLUDE`)
    commençant par `/` ne cible toujours rien (les chemins stockés n'ont jamais de `/` initial) — vérifié explicitement
    malgré la normalisation ci-dessus, qui ne s'applique pas à `IdxPurge` (commande destructive : on préserve son
    comportement historique plutôt que de le faire bénéficier de la normalisation).
- **Index de chemin.** Un préfixe devient `path >= 'p/' AND path < 'p0'` (plus de `LIKE 'p/%'`, de
  `(path=? OR path LIKE ?)`, de `NOT LIKE 'p/%/%'` ni de `_like_escape`, supprimé) : `diff_index` et `snapshot_file`
  utilisent `idx_diff_nick_path` / `idx_snapfile_nick_path`. La vue `archive_snapshot_v` balaie toujours par
  `(nick, archive)` puis filtre le chemin (comportement inchangé, voir TECHNICAL.md).
- **`TreeHist`** : la profondeur se calcule en Python après décodage ; les enfants supprimés se cherchent par chemins
  distincts du sous-arbre puis par dernier événement des seuls enfants directs (plus de fenêtre `ROW_NUMBER` sur tout le
  sous-arbre) ; la détection des événements descendants d'un répertoire n'interprète plus `%`/`_` du nom du répertoire.
- **Tris en Python** (ordre octet UTF-8, identique à l'ancien tri SQLite) pour `ListBkpFiles`, `DiffBkp` et `Search`.
- **Chiffré uniquement** : helpers `_path_range`/`_psel_under`/`_psel_eq`/`_psel_like`/`_psel_glob`/`_path_decode`/
  `_path_stored`/`_path_sort_key`, `DbCodec.decode_path` (mémo borné à 262 144 entrées, partagé entre connexions du processus),
  `LIKE` ASCII et `GLOB` reproduits en Python (regex en cache borné), `PRAGMA case_sensitive_like=ON` sur les seules
  connexions chiffrées, `IdxPurge` : préfixe par intervalle, glob en Python, `DELETE` par `id`.
- **`CodecSelfTest`** : parité plain/chiffré sur `TreeHist`, `TreeFind` (dont supprimés), `Search`, `FileHist`, `DuIdx`,
  `IdxTop`, `DiffTop`, `ListBkpFiles`, `IdxPurge` (préfixe, glob, `IDX_INCLUDE`/`IDX_EXCLUDE`), RBAC (`_path_in_scope`),
  jeu de chemins avec `%`, `_`, casse différente, imbrication, racine, non UTF-8 ; comparaison `LIKE`/`GLOB`/tri avec
  SQLite ; plans `EXPLAIN QUERY PLAN` ; aucun `LIKE`/`GLOB`/`ORDER BY path` émis sur une connexion chiffrée.

## borgHelper 1.0.100 / borgHelperWWW 1.15.1 — chiffrement des chemins SQLite, story 1 : fondations — 2026-09-21

Première brique du chiffrement des chemins/payloads des bases SQLite (architecture : AD-1 à AD-5, AD-10,
AD-12, AD-14). **Aucune donnée n'est chiffrée ni migrée** : toutes les bases restent `plain` et se
comportent exactement comme avant (mêmes sorties, mêmes codes de sortie, mêmes requêtes SQL).

- **Ouverture unique** : `_open_db(db_path, nick=None, role='read', passphrase=None, **kw)` remplace
  `BorgHelperDB._db_connect` (méthode supprimée, remplacée par la fonction de module `_open_db`) et les 50 appels de connexion SQLite directs de `borgHelper` (plus les 3 de
  `borgHelperWWW` sur `scopecache.db`). Renvoie une `BhConnection` (sous-classe de `sqlite3.Connection`) portant
  `.codec` (`None` si `plain`), `.mode`, `.role`, `.nick`. `role` (`read|write|admin`) est validé et mémorisé, sans
  effet fonctionnel pour l'instant. `_vacuum_db` reçoit désormais le nick.
- **Codec** (stdlib seule) : `PathCodec` (SIV déterministe chaîné par segment, `HMAC-SHA256` tronqué 12 o +
  keystream `SHAKE-256`, alphabet `A-Za-z0-9.-`, décodage strict), `BlobCodec` (nonce 16 o, chiffrer puis MAC),
  enveloppe DEK/KEK (chiffrer puis MAC, le MAC couvre `path_enc`, KDF, sel, nonce et chiffré), `enc_header`
  (ligne JSON de `db_meta`, `INSERT … ON CONFLICT DO NOTHING` sous `BEGIN IMMEDIATE`). Aucun chemin de production
  ne crée encore d'`enc_header`.
- **Erreurs typées** `DbKeyError`, `DbModeError`, `DbTamperError`, `DbCodecError` (n'héritent pas de
  `sqlite3.Error`). `enc_header` présent avec `path_enc='plain'` → `DbTamperError`.
- **Versions de schéma** : chaque constante est désormais la version *maximale comprise*
  (`DIFF_DB_SCHEMA_VERSION` 4→5, `CACHE_DB_SCHEMA_VERSION` 1→2, `SCOPE_CACHE_DB_SCHEMA_VERSION` 1→2) ; la version
  *écrite* dans une base `plain` reste 4 / 1 / 1 (`*_BASE_SCHEMA_VERSION`). `_check_set_meta` ne réécrit jamais une
  base `plain` à la version maximale : un ancien binaire continue de l'ouvrir ; seule la future `DbEncrypt` écrira
  la maximale. Un binaire 1.0.99 refusera donc une future base chiffrée (version maximale) mais continue d'ouvrir les
  bases `plain`.
- **Config** : `DB_ENCRYPT` (booléen, défaut activé mais **sans aucun effet tant que `DbEncrypt` n'existe pas** ; la clé sera
  dérivée de `BORG_PASSPHRASE`, donc changer la passphrase borg exigera un `DbRekey` ; `false`/`no`/`off`/`0` pour désactiver, global `[DEFAULT]`
  ou par nick) et `DB_KDF` (`light`/`standard`/`strong`, défaut `standard`), lues via `db_encrypt_enabled(nick)` /
  `db_kdf_level(nick)`. Valeur invalide → arrêt avec message. Sans effet runtime dans cette story.
- **Permissions** : `~/.borghelperrc` créé en `0600` par `Login` ; avertissement unique sur stderr à la lecture d'un
  rc accessible au groupe/autres ; répertoire de cache créé en `0700` ; `.db` créées en `0600`. Les fichiers et
  répertoires existants ne sont pas modifiés.
- **`CodecSelfTest`** (nouvelle commande) : auto-test du codec, de l'en-tête, des versions de schéma, de la config et
  des permissions sur des bases temporaires ; `OK`/`FAIL` par contrôle, code de sortie non nul au moindre échec.
- `borgHelperWWW` : les accès à `scopecache.db` passent par `_open_db`. Un échec d'ouverture dans `_scope_cache_get`
  / `_scope_cache_put` est désormais traité comme un cache miss (comme documenté) au lieu d'un `sys.exit(1)`.

## borgHelper 1.0.99 / borgHelperWWW_ui 1.8.0 — fichiers/répertoires effacés visibles dans TreeHist/TreeFind — 2026-09-19

`TreeHist`/`TreeFind` (l'explorateur d'arborescence de `borgHelperWWW_ui.html`) ne listaient que le
contenu du DERNIER snapshot indexé (`archive_snapshot_v`) — un chemin supprimé depuis n'apparaissait
plus jamais, même s'il restait réellement récupérable depuis une archive plus ancienne encore
présente. Spec : `_bmad-output/implementation-artifacts/spec-fichiers-effaces-exploration.md`.

- `_treehist_listing()`/`_treefind_listing()` : ajoutent désormais les chemins supprimés, sourcés
  depuis `diff_index` — **jamais** `archive_snapshot_v`/`archive_snapshot`, purgés indépendamment
  selon `IDX_SNAP_KEEP` (fenêtre glissante fixe, sans rapport avec l'existence réelle des archives),
  alors qu'une ligne `diff_index` survivante référence toujours une archive encore restaurable
  (`_cleanup_index_after_prune` ne la purge qu'au prune réel de l'archive). Détection : l'événement
  `diff_index` le PLUS RÉCENT (`archive_new_date`/`id` max, via une fenêtre `ROW_NUMBER()`) d'un
  chemin candidat est `change_type='removed'` — jamais "supprimé un jour" ; un chemin réajouté depuis
  réapparaît normalement, sans marque. Un chemin déjà présent dans le dernier snapshot n'est jamais
  reconsidéré via `diff_index` (priorité systématique au snapshot courant).
- `TreeHist` : enfants DIRECTS uniquement (même granularité que l'existant), fusionnés avec les
  enfants du snapshot. `TreeFind` : recherche récursive sous le préfixe, même sémantique de motif
  que l'existant.
- Entrée supprimée : `deleted:true`, `last_seen_archive` = `archive_old` de l'événement de
  suppression (l'archive à restaurer). `is_dir` déduit par heuristique (`size_before IS NULL` sur la
  ligne `diff_index` — `diff_index` n'a pas de colonne de type, et `borg diff` n'inclut pas de taille
  pour une entrée répertoire, voir `parse_diff_line_json()`).
- `TreeHist` sur un répertoire entièrement supprimé (absent du dernier snapshot) : ne renvoie plus
  "vide ou introuvable" — ses anciens enfants directs (trouvés via `diff_index`) restent explorables.
- Forme JSON des entrées présentes strictement inchangée (pas de champ `deleted` ajouté).
- Mode texte CLI (PrettyTable) : entrées supprimées marquées distinctement (`TreeHist` : colonne
  `type`="supprimé" ; `TreeFind` : nouvelle colonne `état`) — jamais une fonctionnalité JSON-only.
- RBAC (Epic 1, `_filter_per_nick_listkey`/`_path_in_scope`) : aucune modification — les entrées
  supprimées portent `full_path` comme les entrées présentes, le filtrage existant s'applique
  automatiquement et identiquement.
- `borgHelperWWW_ui.html` : marqueur visuel "supprimé" (`badge warn`) sur les lignes concernées
  (navigation normale et résultats de recherche) ; `openDownloadDialog()` présélectionne
  `last_seen_archive` dans le sélecteur d'archive pour une entrée supprimée au lieu de "dernière
  archive" (qui échouerait, le fichier n'y est plus).
- `borgHelperWWW` (routes `/treehist`/`/treefind`) : aucun changement — le filtrage RBAC et le cache
  de réponses existants s'appliquent tels quels.
- `python3 -m py_compile borgHelper borgHelperWWW` propre. Requête `ROW_NUMBER() OVER (...)`
  vérifiée manuellement sur une base SQLite de test (isolée, supprimée après vérification).
- `borgHelper` 1.0.98 → **1.0.99**. `borgHelperWWW_ui.html` 1.7.1 → **1.8.0** (`borgHelperWWW` et son
  `WWW_VERSION` inchangés — aucune ligne de `borgHelperWWW` modifiée par cette story).

## borgHelper 1.0.98 — désactive la découverte automatique d'intégrations Sentry — 2026-09-19

`sentry_sdk.init()` (`_cli_main()`) coûtait à lui seul ~100-180ms sur *chaque* invocation CLI
(mesuré empiriquement, DSN réel de production), dominé par la découverte automatique d'une
vingtaine d'intégrations tierces sans rapport avec cet outil (frameworks web, SDK cloud comme
`boto3`). `borgHelperWWW` spawn un sous-processus borgHelper par requête HTTP — ce coût était donc
payé à chaque appel API, y compris pour des commandes qui ne lisent que du SQLite local (`LstBkp`,
`Search`, etc.).

- `sentry_sdk.init(...,auto_enabling_integrations=False)` — option officielle du SDK. Élimine la
  découverte automatique, garde toutes les intégrations par défaut actives (`excepthook`,
  `logging`, `dedupe`, `atexit`, `modules`, `argv`, `stdlib`, `threading`) — capture des exceptions
  non gérées inchangée, vérifiée directement (`'excepthook' in client.integrations` → `True` après
  le changement).
- **Écueil trouvé en revue** : une première version de ce correctif ajoutait aussi
  `default_integrations=False`, qui désactive `excepthook` avec le reste — `borgHelper` n'appelle
  jamais `capture_exception()` explicitement, donc plus aucune exception ne serait jamais remontée
  à Sentry, silencieusement. Corrigé avant commit : seul `auto_enabling_integrations=False` est
  utilisé.
- Vérifié en conditions réelles contre `demo.borghelperrc` et le DSN de production
  (`/usr/local/etc/borghelper-sentry`) : `LstBkp` (commande 100% SQLite) passe de 199-273ms à
  88-93ms sur 3 mesures répétées, avant/après. `python3 -m py_compile borgHelper` propre.
- Issu du spine `_bmad-output/planning-artifacts/architecture/architecture-Borg-2026-09-19/`
  (AD-1) — voir `SOLUTION-DESIGN.md` pour le diagnostic complet.
- `borgHelper` 1.0.97 → **1.0.98**.

## borgHelperWWW 1.15.0 — garde pré-appel Restore/téléchargements hors périmètre (Epic 2, Story 2.1) — 2026-09-19

Dernière story de l'initiative RBAC arborescence : `Restore`, `Restore -L`/`listperms`,
`/download/file`, `/download/tar` n'avaient aucune conscience du périmètre de chemin
(`GROUPS_PATHS`, Epic 1) — un appelant scopé à un sous-arbre d'un nick pouvait restaurer/télécharger
n'importe quel chemin du nick entier. Contrairement aux commandes de liste d'Epic 1 (filtrage a
posteriori, sûr car rien n'est écrit avant le filtre), ces quatre routes écrivent sur le disque du
serveur ou streament des octets directement (`/download/*` appelle `borg` en sous-processus, en
contournant `borgHelper`) — un filtre après coup serait déjà trop tard.

- Nouvelle fonction `require_path_in_scope(request, nick, path)` — validation AVANT tout appel
  `borg`/`borgHelper`, réutilise `_resolve_scopes_for_request`/`_path_in_scope` (Epic 1) telles
  quelles. Retourne un booléen (jamais une exception) : l'investigation en direct (voir Intent du
  spec 2.1) a montré que les quatre routes doivent répondre avec des **formes différentes** sur le
  cas hors périmètre pour ne jamais confirmer l'existence d'un chemin hors périmètre (FR9/AD-2) —
  un `403` uniforme (pattern `require_destructive_allowed()`/`require_downloads_allowed()` suggéré
  en planification) aurait permis de distinguer « hors périmètre » de « n'existe pas » par le seul
  code de statut.
- Chaque route synthétise donc sa propre réponse « introuvable » sur un chemin hors périmètre,
  **jamais un 403** : `POST /restore` → `400` imitant `Include pattern '<ftor>' never matched.` ;
  `GET /restore/perms` → `200` imitant l'en-tête d'archive sans ligne de permissions ; `GET
  /download/file` → `200`, corps vide ; `GET /download/tar` → `200`, tar minimal vide — voir
  README.md/TECHNICAL.md pour les formes exactes. Aucun appel `borg`/`borgHelper` portant sur le
  chemin demandé n'est fait dans ces cas (`/download/*`) ; `/restore`/`/restore/perms` peuvent
  encore appeler `borg list --short` pour nommer la dernière archive quand `bid` est omis — métadonnée
  de nick, pas du chemin protégé, déjà accessible via `/lstbkp`.
- `GET /download/tar` sans `prefix` (export de l'archive entière) est traité comme toujours hors
  périmètre pour un appelant restreint — un export non borné ne peut être « dans le périmètre »
  d'aucun appelant restreint.
- Un appelant sans restriction (admin, groupe absent de `GROUPS_PATHS`, ou autorisation par groupes
  désactivée) ne voit **aucun** changement de comportement sur ces quatre routes.

**Deux écarts trouvés entre le texte gelé de l'Intent du spec 2.1 (capturé à la rédaction du spec) et
le comportement re-vérifié en direct avant implémentation (exigé par les Design Notes du spec)** —
l'implémentation suit le comportement observé, pas le texte gelé, écarts consignés dans le Spec
Change Log du spec 2.1 : (1) `GET /restore/perms` sans `bid`, cas introuvable : la ligne d'archive
est `"Archive (dernière) : <dernière archive>"`, jamais `"Archive : <dernière archive>"` (qui ne peut apparaître que si le
chemin a été trouvé dans l'index — jamais le cas « introuvable ») ; (2) `GET /download/tar`, tar
minimal vide : 10240 octets (`RECORDSIZE` de `tarfile`, toujours bufferisé en entier même vide),
jamais 1024. Connu, non corrigé : `POST /restore` sur `borg` 1.2.6 ajoute une ligne `Warning:
"--numeric-owner" has been deprecated...` à tout `stderr` réel de `borg extract` (trouvé ou non,
dans ou hors périmètre) ; reproduite littéralement dans la réponse synthétique pour préserver
l'indiscernabilité vérifiée en direct, mais couplée à la version de `borg` installée — à
re-vérifier si `borg`/`_borg_extract_args` changent (voir TECHNICAL.md).

Vérifié en conditions réelles contre une copie scratch de `demo.borghelperrc` (nick dédié, deux
sauvegardes, `Index` exécuté, `GROUPS_ADMIN/WRITE/READ` + `GROUPS_PATHS` actifs) :
`python3 -m py_compile borgHelper borgHelperWWW` propre ; pour chacune des quatre routes, diff
byte-pour-byte (JSON field-for-field pour `/restore`/`/restore/perms`) entre (a) un appelant scopé
sur un chemin hors périmètre et (b) le même appelant sur un chemin dans son périmètre mais
réellement absent de l'archive — identiques dans les deux cas `bid` omis/fourni ; `GET /download/tar`
sans `prefix` pour un appelant restreint → même tar vide ; restauration/téléchargement réels d'un
fichier dans le périmètre → inchangés (contenu restauré/téléchargé correct) ; appelant admin
(illimité) restaurant un chemin hors du périmètre d'un autre groupe → procède normalement, aucun
changement ; `GROUPS_HEADER` désactivé → aucun changement. Scratch config et dépôts `/tmp` supprimés
après vérification.

`README.md`/`TECHNICAL.md` mis à jour (nouveau garde, formes synthétiques par route, les deux écarts
trouvés en re-vérification, la limite connue de l'avertissement `--numeric-owner`). `borgHelperWWW`
1.14.0 → **1.15.0** ; `borgHelper` inchangé par cette story.

**Corrections de revue (même story, avant premier commit)** :
- `_oos_last_archive_line` catch désormais l'`HTTPException` (404/502/504) que peut lever
  `_latest_archive()` (nick sans aucune archive, `borg list` en échec/timeout) et omet simplement la
  ligne d'archive plutôt que de la laisser se propager — sans ce correctif, un nick sans archive
  cassait la garantie d'indiscernabilité de cette story (troisième forme de réponse, ni « introuvable »
  ni « dans le périmètre »).
- Nouveau helper `_download_tar_filename(nick, prefix)` — factorise l'expression du nom de fichier
  `.tar`, partagée avant ce correctif (copiée-collée identique) entre `download_tar()` et
  `_synth_download_tar_out_of_scope`, même risque de divergence silencieuse documenté pour `_fmt_stats`
  dans AGENTS.md.
- `require_path_in_scope(request, nick, path)` : type de `path` corrigé en `Optional[str]` (`download_tar`
  l'appelle avec `prefix: Optional[str]`, déjà accepté en pratique via la normalisation de
  `_path_in_scope`, mais pas reflété par l'annotation).
- Disclosure `--numeric-owner` élargie aux libellés de ligne d'archive codés en dur (`"Archive
  sélectionnée (dernière)"`, `"Archive (dernière)"`) — même risque de dérive silencieuse si les
  prints de `borgHelper.restore()`/`listperms()` changent de formulation.
- Docs : ambiguïté `<bid>` (paramètre de requête vs archive résolue serveur) levée dans TECHNICAL.md/
  CHANGELOG.md (`<dernière archive>`, déjà correct dans README.md) ; absence de tout réglage
  d'activation pour `POST /restore` rendue explicite (README.md, section « Actions destructrices et
  téléchargements ») ; note ajoutée à « Limites connues » sur le `borg list --short` toujours déclenché
  par requête hors périmètre sans `bid`.

## borgHelper 1.0.97 + borgHelperWWW 1.14.0 — cache SQLite des réponses filtrées par périmètre (Epic 1, Story 1.5) — 2026-09-19

Cinquième et dernière brique de la consultation scopée par arborescence (Epic 1) : depuis les
Stories 1.3/1.4, tout appelant scopé (au moins un nick à périmètre restreint) contournait
entièrement `_RESPONSE_CACHE` — chaque requête, même identique et récemment servie, relançait
`borgHelper` et refiltrait de zéro (AD-5). Cette story ajoute le cache SQLite dédié que ces deux
stories laissaient volontairement de côté.

- Nouveau fichier SQLite `SCOPE_CACHE_DB` (réglage `BORGHELPERWWW_SCOPE_CACHE_DB`/`--scope-cache-db`,
  défaut co-localisé avec `cache.db`/`diff.db`), même convention `db_meta`/`schema_version` que ces
  deux bases (réutilise `_bh_paths.db._db_connect()`/`_check_set_meta()`, jamais dupliqué). Table
  `scope_cache(cache_key, fingerprint, result_json, written_at)` — une ligne par `(nick réel,
  commande, paramètres, signature de périmètre)`, jamais une clé combinée pour une requête
  multi-nick (AD-5) : deux nicks scopés différemment dans la même requête ne partagent jamais une
  ligne.
- `_capture_fingerprints(nick)` : **tout premier appel** de chacune des neuf routes, strictement
  avant la résolution du périmètre — empreinte = mtimes `cache.db`/`diff.db` du nick **et** mtime de
  `.borghelperrc` lui-même (un `GROUPS_PATHS` resserré/relâché invalide donc le cache sans attendre
  une nouvelle sauvegarde), capturée par nick réel pour qu'un backup/index sur un seul nick n'invalide
  que sa propre ligne, même à l'intérieur d'une requête multi-nick. Garde-fou TOCTOU d'AD-5 : jamais
  recapturée après l'appel `borgHelper`.
- `_scoped_cached_mono()`/`_scoped_cached_multi()` enveloppent `_run_scoped()`/`_run_scoped_raw()`
  (Stories 1.3/1.4, strictement inchangées) dans chacune des neuf endpoints — jamais à l'intérieur de
  ces deux fonctions elles-mêmes, qui restent des primitives non-cacheables. Pour les quatre routes
  multi-nick (`Search`/`FileHist`/`TreeHist`/`TreeFind`) : un hit **complet** (tous les nicks
  demandés ont une ligne fraîche) synthétise la réponse sans appeler `borgHelper` ; tout miss (même
  un seul nick) relance l'appel combiné existant exactement comme avant cette story, puis
  rafraîchit une ligne par nick à partir de ce résultat.
- Même garde-fou anti-croissance que `_RESPONSE_CACHE` (purge totale au-delà de 500 lignes, pas de
  LRU) — cohérence plutôt que sophistication.

**Deux correctifs `borgHelper` requis pour que ce cache produise un hit en pratique** (limites
`borgHelper` initialement frozen, renégociées en cours de story après deux tours d'investigation
live — voir `_bmad-output/implementation-artifacts/spec-1-5-cache-perimetre.md`, Amendments
iteration 1 et 2) :
1. `_check_set_meta()` n'écrit plus `db_meta` (`schema_version`/`borghelper_version`) que si la
   valeur stockée diffère réellement — avant, ces deux lignes étaient réécrites à **chaque** appel,
   même en lecture pure, avançant la date de modification de `cache.db`/`diff.db` à chaque fois
   (chaque appel `borgHelper` est un sous-processus séparé ; fermer sa connexion SQLite déclenche un
   checkpoint WAL qui touche le fichier).
2. `ensure_diff_db()` ne recrée plus la vue `archive_snapshot_v` (`DROP VIEW`/`CREATE VIEW`) que si
   elle n'existe pas déjà (simple contrôle d'existence contre `sqlite_master`, jamais une comparaison
   textuelle du SQL stocké) — même défaut d'écriture inconditionnelle à chaque appel, découvert en
   test live **après** le premier correctif, qui à lui seul ne suffisait pas.

Sans ces deux correctifs combinés, l'empreinte qu'un appel scopé doit retrouver inchangée pour faire
un hit était invalidée par l'appel `borgHelper` lui-même — un miss garanti à chaque fois, quelle que
soit la justesse du mécanisme de cache. Comportement CLI/format de sortie de `borgHelper` inchangés
par ces deux correctifs — seule la date de modification des fichiers `.db` en bénéficie.

Vérifié en conditions réelles contre une copie scratch de `demo.borghelperrc` (`GROUPS_ADMIN/WRITE/
READ` + `GROUPS_PATHS` actifs sur les deux nicks de démo, données déjà indexées réutilisées sans
réindexation) : `python3 -m py_compile borgHelper borgHelperWWW` propre ;
`borgHelperWWW` piloté via `fastapi.testclient.TestClient` avec `_exec_borghelper` instrumenté d'un
compteur d'appels — (1) ligne `scope_cache` écrite après un appel scopé, désérialise vers la même
forme `CommandResult` qu'une réponse live ; (2) 5 appels `LstBkpFls` scopés identiques consécutifs →
**1 seul** sous-processus `borgHelper` (0 hit avant les deux correctifs `borgHelper`, confirmé lors
de la première tentative d'implémentation — voir spec) ; (3) `Search` multi-nick avec une seule ligne
supprimée → exactement 1 appel combiné, réponse correcte et identique pour les deux nicks (chemin
hit-partiel) ; (4) appelant admin (illimité) : 2 appels identiques → 1 seul exec (hit
`_RESPONSE_CACHE` normal), **0** ligne `scope_cache` écrite (additivité confirmée) ; (5) `.borghelperrc`
touché (`os.utime`) entre deux requêtes identiques → 2e requête toujours `200`, données correctement
re-scopées (miss, pas de crash) ; (6) garde-fou de croissance : 501 lignes de remplissage insérées
directement, l'écriture suivante vide la table et n'y laisse qu'1 ligne ; (7) `db_meta` du nouveau
fichier contient `schema_version='1'`, `borghelper_version` = `borgHelper.Version` ; (8) mêmes
vérifications de stabilité (n identiques → 1 exec) répétées pour `DiffBkp`/`DuIdx`/`IdxTop`/
`DiffTop`/`FileHist`/`TreeHist`/`TreeFind` — les neuf routes couvertes. **Test explicite requis par
le spec** : deux appels `LstBkpFls` consécutifs directement en CLI (`borgHelper -C ... -c LstBkpFls
-n demo-modules -j`, hors `borgHelperWWW`) contre un nick à données existantes non modifiées → mtime
de `diff.db` identique après le 2e appel (confirmé stable sur 3 appels consécutifs) — ce test avait
échoué avec seulement le premier correctif lors de l'itération précédente ; passe désormais avec les
deux ensemble. Scratch config et tous les fichiers `story15_test_rc-*`
(cache/diff-db/scope-cache) supprimés après vérification ; l'état `Index` propre aux deux dépôts de
démo laissé en place (inchangé par cette vérification, en lecture pure).

`README.md`/`TECHNICAL.md`/`borghelperwww.conf.example` mis à jour (nouveau cache, réglage
`--scope-cache-db`/`BORGHELPERWWW_SCOPE_CACHE_DB`, règle d'invalidation, et les deux correctifs
`borgHelper`). `borgHelper` 1.0.96 → **1.0.97** ; `borgHelperWWW` 1.13.0 → **1.14.0**.

## borgHelper 1.0.96 + borgHelperWWW 1.13.0 — filtrage par périmètre sur DuIdx/IdxTop/DiffTop (Epic 1, Story 1.4) — 2026-09-19

Quatrième brique de la consultation scopée par arborescence (Epic 1) : le périmètre de chemin
étend maintenant aux trois commandes d'**agrégats** (`DuIdx`/`IdxTop`/`DiffTop`) le filtrage déjà
en place depuis Story 1.3 sur les six commandes de liste/recherche — les neuf routes liées à AD-1
sont désormais toutes couvertes.

- Ces trois commandes groupent/agrègent déjà (Python, voire SQL pour `DuIdx`) **avant** de produire
  leur JSON existant — filtrer ce JSON après coup serait incorrect (une frontière de périmètre peut
  tomber au milieu d'un groupe déjà constitué). `borgHelper` gagne donc un mode **brut**, ungroupé,
  une ligne JSON par chemin, distinct du JSON groupé existant : `-R` pour `DuIdx` (son `-j` existant
  reste le mode groupé historique, byte-identique, jamais touché) ; `-j` pour `IdxTop`/`DiffTop`,
  qui n'avaient aucun mode JSON avant cette story. `borgHelper` reste RBAC-ignorant (AD-3) : ce mode
  brut est une option de sortie générique, jamais scope/groupe-aware.
- Quand l'appelant est scopé, `borgHelperWWW` demande ce mode brut, retire les lignes hors
  périmètre, puis **recalcule lui-même** — en miroir ligne-à-ligne de l'algorithme de regroupement
  de `borgHelper` au moment de l'écriture — le regroupement/tri/top-N (`_recompute_duidx`,
  `_recompute_idxtop`, `_recompute_difftop`) : jamais un total/classement transmis depuis le calcul
  non filtré puis partiellement masqué. `topn` s'applique sur l'ensemble **complet** filtré, jamais
  sur une tranche tronquée avant filtrage.
- Les figures « Exclus » (`IDX_EXCLUDE`) et « Inchangés par archive » (dérivées de `nfiles`) sont
  des figures portant sur le **nick entier**, sans colonne de chemin — non scopables correctement —
  et sont donc **omises** pour tout appelant scopé, jamais approximées.
- `DuIdx`/`IdxTop`/`DiffTop` sont traitées **mono-nick** pour le périmètre (comme `LstBkpFls`/
  `DiffBkp` en Story 1.3) : `nick` est développé via `_nick_list()` avant résolution du périmètre
  (jamais `cfgread('ALL')` direct) ; un appelant scopé sur `nick=ALL`/plusieurs nicks est refusé
  (`400`, aucune donnée) plutôt que de tenter un regroupement inter-nicks que cette story ne
  construit pas. Une paire d'archives (`DiffTop`) sans la moindre ligne dans le périmètre renvoie un
  résultat vide (`rows: []`), jamais une erreur.
- Un appelant sans restriction (admin, ou autorisation par groupes désactivée) ne voit **aucun**
  changement : texte/JSON groupé existant byte-identique à avant cette story.
- `_RESPONSE_CACHE` étendu (Story 1.3) aux trois nouvelles routes : contourné entièrement dès qu'un
  périmètre restreint s'applique, comme pour les six commandes précédentes.
- `borgHelper` 1.0.95 → **1.0.96** ; `borgHelperWWW` 1.12.0 → **1.13.0**.

Vérifié en conditions réelles contre `demo.borghelperrc` : `python3 -m py_compile` propre ; sortie
texte de `DuIdx`/`IdxTop`/`DiffTop` et JSON groupé existant (`-j`) de `DuIdx` diffées byte-à-byte
contre la sortie d'avant cette story (seule différence : le numéro de version après le bump) ;
lignes `diff_index` synthétiques insérées temporairement sous deux préfixes noyau distincts pour
exercer un cas réel de filtrage (données réelles du dépôt de démo sans diff exploitable entre les
dernières archives indexées) — `borgHelperWWW` lancé avec `--groups-header X-Groups`, `ops-readers`
scopé sur un sous-répertoire de `demo-modules` : `DuIdx` (modes groupé et global), `IdxTop`,
`DiffTop` ne renvoient que les lignes du sous-répertoire, totaux/pourcentages recalculés
correctement depuis l'ensemble filtré (confirmé par comparaison ligne à ligne avec la réponse admin
non filtrée) ; paire d'archives sans ligne en périmètre → résultat vide, `200`, pas d'erreur ;
`nick=ALL` scopé → `400`, aucune donnée. Configuration et lignes de test entièrement retirées après
vérification (`git checkout -- demo.borghelperrc`, lignes `diff_index` supprimées).

`README.md`/`TECHNICAL.md`/`LIBRARY.md` mis à jour (mécanisme de filtrage par mode brut + recalcul,
traitement mono-nick, options CLI `-R`/`-j`, retrait du caveat « `DuIdx`/`IdxTop`/`DiffTop` non
filtrés » de Story 1.3).

**Risque signalé, non corrigé dans cette story** : `_check_group_access` ne vérifie le tier que si
`nick` figure littéralement dans la query string de la requête HTTP — un appel à `/idxtop` ou
`/difftop` **sans aucun `?nick=`** (ces deux routes ont un défaut de route `nick="ALL"`) contourne
donc la vérification de tier grossière. Angle mort **pré-existant** (présent avant cette story, non
introduit par elle — `/cacheinfo`, `/cacheclean`, `/idxpurge` partagent le même défaut `nick="ALL"`
et le même angle mort, hors périmètre de Story 1.3/1.4). `_resolve_single_scope()` de cette story ne
le comble que par accident pour un appelant scopé sur au moins un nick réel (son propre refus
multi-nick s'applique avant toute lecture) ; un appelant sans **aucun** tier sur aucun nick resterait
exposé. Non corrigé ici : modifier `_check_group_access` est hors des limites frozen du spec 1.4, et
un correctif confiné à `IdxTop`/`DiffTop` serait incohérent avec les autres routes touchées par le
même angle mort — signalé pour triage humain/architecture (voir TECHNICAL.md).

## borgHelperWWW 1.12.0 — filtrage par périmètre sur Search/FileHist/LstBkpFls/DiffBkp/TreeHist/TreeFind (Epic 1, Story 1.3) — 2026-09-18

Troisième brique de la consultation scopée par arborescence (Epic 1) : le périmètre de chemin
résolu par Story 1.1 (`GROUPS_PATHS`) est désormais **appliqué**, en filtrage a posteriori, sur les
six commandes de lecture qui renvoient des chemins ou des listes indexées par chemin —
`Search`/`FileHist`/`LstBkpFls`/`DiffBkp`/`TreeHist`/`TreeFind`. `DuIdx`/`IdxTop`/`DiffTop`
(agrégats) restent hors périmètre de cette story (Story 1.4, distincte : recalcul de totaux/top-N).

- Dès qu'**au moins un** nick de la requête porte un périmètre restreint, `borgHelperWWW` appelle
  `borgHelper` avec `-j` en interne (même si le client n'a rien demandé), retire du JSON les
  lignes/chemins hors périmètre, et répond avec ce JSON — **la réponse devient JSON même sans
  `?json=true`** (`TreeHist`/`TreeFind`), sans aucun nouveau paramètre `?json=` côté client pour
  `Search`/`FileHist`/`LstBkpFls`/`DiffBkp`. `DiffBkp` recalcule `n_add`/`n_rem`/`n_mod` depuis les
  entrées filtrées, jamais depuis le compte non filtré. Un appelant sans restriction (admin, ou
  autorisation par groupes désactivée) ne voit **aucun** changement : texte par défaut, JSON
  seulement sur demande explicite là où c'était déjà possible — byte-identical à avant cette story.
- Requête multi-nick (`Search`/`FileHist`/`TreeHist`/`TreeFind`, `nick=a,b`) : chaque nick est
  filtré contre **son propre** périmètre résolu ; un seul nick scopé force tout le corps en JSON,
  les nicks non scopés de la même requête restent non filtrés.
- Nouvelle fonction partagée `_path_in_scope(path, scope)` (AD-7 : comparaison par segments de
  chemin complets, jamais sous-chaîne) — **corrige un bug trouvé en investigation d'implémentation,
  avant tout déploiement** : les chemins stockés par `borgHelper` (`archive_snapshot_v`/
  `diff_index`, vérifié contre un dépôt réel) n'ont jamais de `/` initial, alors que les préfixes
  `GROUPS_PATHS` s'écrivent **avec** un `/` initial (convention Story 1.1) — sans normalisation de
  ce décalage, toute comparaison scopée échouait silencieusement et un appelant scopé n'obtenait
  jamais aucun résultat, pour aucun nick (fail-closed, jamais une fuite, mais un vrai bug
  fonctionnel qui serait passé inaperçu sans un test contre des chemins stockés réels).
- `_RESPONSE_CACHE` (cache mémoire existant) n'est plus utilisé (ni lu, ni écrit) pour un appel dont
  au moins un nick est scopé — reste réservé au cas entièrement non restreint, exactement comme
  avant cette story. Un cache dédié au résultat filtré (clé incluant le périmètre) est prévu pour
  Story 1.5, pas celle-ci.
- `borgHelperWWW` 1.11.0 → **1.12.0**.

Vérifié en conditions réelles contre `demo.borghelperrc` (données déjà indexées par Story 1.2) :
`borgHelperWWW` lancé avec `--groups-header X-Groups`, un groupe `ops-readers` scopé sur un sous-
répertoire de `demo-modules` (`/lib/modules/6.2.0-39-generic`, un des trois répertoires de version
noyau réellement présents dans les données indexées) — `Search`/`FileHist`/`LstBkpFls`/`DiffBkp`/
`TreeHist`/`TreeFind` ne renvoient que des chemins de ce sous-répertoire, en JSON même sans
`?json=true` ; le même groupe non scopé sur `demo-usrlocal` (multi-nick `Search`) reste non
filtré dans la même réponse ; un appelant `ops-admins` (illimité) obtient un texte byte-identique à
l'appel direct `borgHelper` (diff vide) et, sur `TreeHist`/`TreeFind` avec `?json=true`, un JSON
byte-identique à l'appel direct `borgHelper -j`. Complété par des tests unitaires en isolation
(`_path_in_scope`, `_filter_diffbkp` + recalcul des compteurs sur des entrées synthétiques
couvrant les deux répertoires, `_filter_per_nick_listkey`, `_filter_filehist`) pour les cas que les
données réelles du dépôt de démo ne couvraient pas (aucune différence entre les dernières archives
indexées). `python3 -m py_compile borgHelperWWW borgHelper` propre.

`README.md`/`TECHNICAL.md` mis à jour (mécanisme de filtrage, normalisation du `/` initial avec sa
justification, caveat de cache, limite connue côté UI qui ne distingue pas encore une réponse
filtrée).

**Correction issue de la revue (itération 1, avant commit)** : `Search`/`FileHist`/`TreeHist`/
`TreeFind` construisaient leur liste de nicks par un simple `nick.split(',')`, sans passer par
`_nick_list()` (déjà utilisé par `_check_group_access` pour exactement ce besoin) — un appelant
scopé demandant `nick=ALL` littéral voyait `cfgread('ALL')` renvoyer `None` (aucune section `ALL`
n'existe), interprété comme périmètre illimité par `_resolve_scopes_for_request`, donc `_any_scoped`
à `False` et la requête retombait entièrement non filtrée — un contournement complet du filtrage de
cette story pour ces quatre routes via `nick=ALL`, confirmé en conditions réelles avant correction
puis re-vérifié après (réponse filtrée, JSON forcé, aucun changement pour un appelant illimité).
Corrigé en remplaçant le découpage manuel par `_nick_list(nick)` dans les quatre routes.
`LstBkpFls`/`DiffBkp` (mono-nick) ne sont pas affectées : `nick=ALL` y échoue déjà proprement
(exitcode non nul, aucune donnée) côté `borgHelper`, qui ne sait pas résoudre un nick agrégé sur ces
deux commandes — vérifié, pas de correctif nécessaire. `_run_scoped()` durci en complément : un
`stdout` non-JSON malgré `-j` pour un appelant scopé renvoie désormais une erreur (fail-closed)
plutôt que de relayer tel quel une sortie potentiellement non filtrée (cas non atteignable
aujourd'hui, mais contraire au principe fail-closed affiché par cette story).

## borgHelper 1.0.95 — mode JSON sur Search, FileHist, LstBkpFls, DiffBkp (Epic 1, Story 1.2) — 2026-09-18

Deuxième brique de la consultation scopée par arborescence (Epic 1) : `Search`, `FileHist`,
`LstBkpFls` et `DiffBkp` gagnent un flag `-j`/`as_json`, sur le même modèle que `TreeHist`/
`TreeFind` — prérequis mécanique pour le filtrage par périmètre d'une story ultérieure du même
epic (rien n'est filtré ici, ce changement est CLI-only).

- `-j` sur les quatre commandes : sortie JSON structurée à la place du tableau texte habituel,
  qui reste strictement inchangé sans `-j`. `Search`/`FileHist` : `{nick:[{...},...]}`, une entrée
  par nick (comme `TreeHist`/`TreeFind`). `LstBkpFls` : `{nick,archive,files:[...]}`. `DiffBkp` :
  `{archive_old,archive_new,entries:[...],n_add,n_rem,n_mod}`.
- Toutes les sorties d'erreur de ces quatre commandes (index vide, paire non trouvée, échec
  `borg list`/`borg diff`, erreur SQLite) passent aussi par `-j` — `{"error": "..."}` sur stdout
  plutôt qu'une phrase en clair, pour ne jamais casser un consommateur qui s'attend à du JSON.
- Champs JSON en valeurs brutes (tailles en octets, pas `convert_octets_readable`) — utile pour un
  programme, contrairement au tableau texte destiné à un terminal.

Vérifié contre le dépôt `demo.borghelperrc` réel (`Init`+`Bkp` x2 en local) : sortie texte vs `-j`
comparées champ par champ pour `Search`/`FileHist`, `LstBkpFls -j` et `DiffBkp -j` (cas
différence vide et compteurs `n_add/n_rem/n_mod`) conformes ; `python3 -m py_compile` propre.

`README.md`/`LIBRARY.md` mis à jour (exemples `-j`, signatures) ; usage CLI (`-h`/`-H`) documente
le nouveau flag sur les quatre commandes.

## borgHelperWWW 1.11.0 + UI 1.7.1 — périmètre de chemin par groupe (Epic 1, Story 1.1) — 2026-09-18

Première brique de la consultation scopée par arborescence (Epic 1) : `borgHelperWWW` peut
désormais **résoudre et exposer** un périmètre de chemin par groupe, en plus du tier
admin/écriture/lecture existant — cette story ne filtre encore **aucune** réponse de commande
(prévu dans une story ultérieure du même epic) ; elle pose la fonction de résolution partagée et
l'expose via `/access`.

- Nouvelle clef `.borghelperrc` par nick **`GROUPS_PATHS`** (repli `[DEFAULT]` natif, même
  convention que `GROUPS_ADMIN/WRITE/READ`) : associe un groupe à un ou plusieurs préfixes de
  chemin (`groupe:/a|/b, groupe2:/c`). Orthogonale au tier — ne fait que le restreindre, jamais
  l'étendre ; un groupe absent de la clef garde un accès chemin illimité dans son tier.
- `_resolve_path_scope(user_groups, cfg)` (miroir de `_effective_level`) : résolution strictement
  par nick, la plus permissive gagne (un seul groupe correspondant non scopé ⇒ périmètre illimité,
  sinon union canonicalisée des préfixes de tous les groupes correspondants scopés).
  `_parse_groups_paths` rejette bruyamment (`ValueError`) tout nom de groupe/chemin contenant un
  des séparateurs réservés (`:`, `|`, `,`) — jamais un découpage silencieusement ambigu.
- `_canonicalize_scope` : dédoublonne, retire les `/` finaux, élimine les préfixes redondants —
  **corrigé pour que la racine `/` absorbe bien tout le reste** (`_canonicalize_scope(['/',
  '/var/www'])` renvoie maintenant `['/']` ; le check générique `p.startswith(kept+'/')` ne
  fonctionnait pas pour `kept=='/'`, qui devient `'//'`).
- `GET /access` : chaque nick expose désormais `{level, scope}` au lieu d'une simple chaîne de
  niveau — `scope` est `null` (illimité) ou la liste des préfixes résolus, `null` partout quand
  l'autorisation par groupes est désactivée. **Changement de forme de réponse, non rétro-compatible**
  côté client (voir correctif UI ci-dessous).
  - `_validate_groups_paths_startup()` valide `GROUPS_PATHS` de chaque nick une fois au démarrage
    (fail-fast pour la faute de config la plus courante) — mais **n'est pas le seul point
    d'application** : `.borghelperrc` étant relu à chaque appel (`cfgread()`, sans cache), une
    valeur rendue ambiguë **pendant que le process tourne** fait échouer le prochain `/access`
    concerné en `500` non catché — **uniquement pour un appelant qui détient déjà un tier sur ce
    nick** (`_resolve_path_scope` court-circuite en `None` avant de lire `GROUPS_PATHS` pour un
    appelant sans aucun accès au nick, qui reçoit donc `scope:null` en `200` normal, sans jamais
    voir l'erreur) — jamais une réponse dégradée en silence pour l'appelant concerné. Conséquence
    documentée : `/access` n'est plus inconditionnellement `200` pour un appel authentifié qui a un
    tier sur le nick concerné — son `summary=`, le README et TECHNICAL.md sont corrigés en ce sens.
- `borgHelperWWW_ui.html` — **correctif de compatibilité**, dans le même commit : `loadMyAccess()`/
  `applyBadges()`/`loadMachines()` lisaient encore `nicks[nick]` comme une chaîne brute ; corrigés
  pour lire `.level` (nouvelle forme `{level, scope}`). Restaure exactement le comportement
  existant (calcul des badges, filtrage de la liste des serveurs) — `scope` lui-même n'est pas
  encore consommé côté UI, ce sera une story ultérieure.
- `demo.borghelperrc` : exemple commenté `GROUPS_PATHS` ajouté à côté de l'exemple
  `GROUPS_ADMIN/WRITE/READ` existant.

**Toujours pas de filtrage effectif** : `Search`, `FileHist`, `TreeHist`, `TreeFind`, `LstBkpFls`,
`DiffBkp`, `DuIdx`, `IdxTop`, `DiffTop` renvoient toujours l'intégralité de ce que le tier
autorise, périmètre ou pas — le filtrage a posteriori de ces neuf commandes est une story
ultérieure du même epic. `Restore`/`Restore -L`/`/download/file`/`/download/tar` sont, eux,
couverts par un **epic séparé** (garde pré-appel, pas un filtrage a posteriori) qui réutilisera
cette même résolution de périmètre — ils ne sont ni concernés ni « oubliés » par cette liste, ils
sont hors périmètre de cet epic. `Bkp/Index/Prune/DelBkp/Init/Key/IdxPurge/Stats` n'ont aucune
notion de sous-chemin et ne sont jamais concernés, dans aucun epic.

Vérifié : `python3 -m py_compile borgHelperWWW borgHelper` (aucune erreur de syntaxe) ; les 8
scénarios de la matrice E/S de la spec (groupe scopé seul, groupe scopé + groupe non scopé,
même groupe sur deux nicks indépendants, `GROUPS_PATHS` absent, préfixes redondants, séparateur
ambigu au démarrage, `groups_auth_enabled=false`, séparateur rendu ambigu **pendant que le
process tourne** → `500` non catché puis rétabli en `200` dès la config corrigée) rejoués contre
un `.borghelperrc` de scratch via `curl` sur `/api/access`, plus `_canonicalize_scope(['/',
'/var/www']) == ['/']` vérifié directement.

## borgHelperWWW 1.10.0 + UI 1.7.0 — droits alignés sur les badges, nicks sans accès invisibles — 2026-09-18

Complète l'autorisation par groupes (1.9.0) : les badges de sécurité et la liste des serveurs
reflètent désormais les droits **personnels** de l'utilisateur connecté, pas seulement les réglages
globaux `allow_destructive`/`allow_downloads`.

- Nouvel endpoint `GET /access` : niveau effectif (`none`/`read`/`write`/`admin`) de l'appelant sur
  **chaque** nick connu, d'après ses groupes — `{'admin': ...}` partout si l'autorisation par groupes
  est désactivée. Protégé par `X-API-Key` mais spécial-casé dans `_check_group_access` (accessible
  quels que soient les groupes de l'appelant — son rôle est justement de les refléter).
- **Liste des serveurs** : un nick sans aucun droit de lecture n'apparaît plus ni dans la liste ni dans
  la navigation rapide (au lieu de faire échouer toute la liste en `403` dès qu'un seul nick configuré
  est inaccessible — comportement *fail-closed* correct pour un appel explicite `nick=a,b,c`, mais
  inadapté à `nick=ALL`). `loadMachines()` appelle `/access` en premier, puis n'envoie à `/report`
  qu'une liste explicite des nicks accessibles ; liste vide ⇒ « Aucun serveur accessible avec vos
  droits actuels. » sans appeler `/report`.
- **Badges de sécurité affinés après connexion** : 🔒 Destructions désactivées tient compte de l'accès
  admin réel (pas seulement `allow_destructive`), 🚫 Téléchargements désactivés de l'accès à au moins un
  nick, ⚠️ Tout autorisé exige en plus l'admin sur la totalité des nicks configurés.
- Piste de réécriture côté serveur de `nick=ALL` (mutation de `request.scope['query_string']` dans
  `_check_group_access`) testée et écartée : sans effet sur le paramètre `nick` déjà résolu côté
  endpoint (voir TECHNICAL.md).

Vérifié : `/access` par curl sur plusieurs profils de groupes (admin, lecteur, aucun groupe, groupes
non pertinents, fonctionnalité désactivée), simulation complète de la séquence `loadMachines()`
(`/access` puis `/report` avec liste explicite dérivée), non-régression `nick=ALL` avec l'autorisation
par groupes désactivée.

## borgHelperWWW 1.9.0 — autorisation par groupes (reverse proxy OIDC/auth_request) — 2026-09-18

Nouveau mécanisme d'autorisation **par nick et par groupes**, complémentaire à `X-API-Key` (jamais un
remplacement) — pensé pour un reverse proxy (nginx `auth_request`, oauth2-proxy…) qui authentifie par
OIDC et transmet les groupes de l'utilisateur dans un header HTTP.

**Désactivé par défaut** — `BORGHELPERWWW_GROUPS_HEADER` / `--groups-header` / clé `groups_header`
absente : comportement strictement inchangé. Une fois activé (nom du header à lire, ex. `X-Groups`,
liste de groupes séparés par des virgules) :

- Trois nouvelles clefs `.borghelperrc` par nick (repli natif sur `[DEFAULT]`, comme toute autre
  clef) : **`GROUPS_ADMIN`**, **`GROUPS_WRITE`**, **`GROUPS_READ`** — hiérarchiques (admin ⊇ écriture
  ⊇ lecture, pas besoin de répéter un groupe dans les trois listes). Reconnues uniquement par
  `borgHelperWWW` — ignorées par `borgHelper` CLI lui-même (aucun changement de code côté
  `borgHelper`, juste de nouvelles clefs de configuration documentées).
- Chaque route classée lecture/écriture/admin (`_ROUTE_LEVELS`), appliqué à toutes via un seul
  `APIRouter(dependencies=[Depends(_check_group_access)])` — aucune signature d'endpoint modifiée.
- `Login` traité à part (accès admin sur le nick visé s'il existe déjà, sinon sur `[DEFAULT]`).
- Requête multi-nick (`nick=ALL` ou `nick=a,b,c`) : *fail-closed* — toute la requête est refusée si le
  niveau manque pour ne serait-ce qu'un seul des nicks visés.
- Header absent/vide (fonctionnalité active) : aucun groupe ⇒ aucun accès.
- `GET /version` renvoie `groups_auth_enabled` (booléen seulement — jamais le nom du header ni les
  groupes).

⚠️ Le header n'est vérifié que pour sa valeur, jamais sa provenance — suppose `borgHelperWWW` non
atteignable autrement que via le reverse proxy de confiance (même hypothèse déjà documentée pour
`X-Forwarded-For`/`BORGHELPERWWW_TRUSTED_PROXIES`).

Vérifié de bout en bout sur une configuration à deux nicks/trois groupes (`ops-admins`/`writers`/
`readers` équivalents) : hiérarchie admin/écriture/lecture, isolation stricte entre nicks (accès sur
l'un n'accorde rien sur l'autre), repli `[DEFAULT]`, multi-nick fail-closed, header absent/vide
refusé, cas `Login` (nouveau nick refusé sans `GROUPS_ADMIN` en `[DEFAULT]`, nick existant accepté
pour un groupe admin dessus), et non-régression complète avec la fonctionnalité désactivée.

`borghelperwww.conf.example` et `demo.borghelperrc` mis à jour (nouvelles clés documentées/exemples
commentés).

## UI 1.6.3 — correctif : les badges de sécurité ignoraient leur état réel — 2026-09-18

**Bug corrigé** : les trois badges de sécurité (🔒 Destructions désactivées, 🚫 Téléchargements
désactivés, ⚠️ Tout autorisé) s'affichaient systématiquement, sans tenir compte de leur attribut
`hidden` — donc sans rapport avec l'état réel du serveur (`allow_destructive`/`allow_downloads`).

**Cause** : `.badge{display:inline-block;...}` (CSS auteur) l'emportait sur le comportement par défaut
du navigateur pour `[hidden]` (`display:none`, une règle de la feuille de style *user-agent*) — en CSS,
une déclaration auteur l'emporte toujours sur une déclaration *user-agent*, quelle que soit la
spécificité du sélecteur. Seule `section[hidden]` avait une règle explicite ; aucune règle générique ne
couvrait les autres éléments (ici des `<span class="badge">`).

**Correctif** : règle globale `[hidden]{display:none!important}` ajoutée en tête de la feuille de
style (remplace l'ancienne règle `section[hidden]` devenue redondante).

Vérifié dans un vrai navigateur (Chrome headless, `getComputedStyle`) : avant le correctif, les trois
badges rendent `display:inline-block` quel que soit leur `hidden` (reproduit le bug rapporté) ; après,
`hidden=true` → `display:none`, `hidden=false` → `display:inline-block`, dans tous les cas testés.

## UI 1.6.2 — même lien « borgHelperWWW » dans le pied de page — 2026-09-18

`borgHelperWWW` dans le pied de page devient aussi un lien vers `/` (même principe que le titre en
en-tête, 1.6.1). Vérifié en direct.

## UI 1.6.1 — le titre « borgHelperWWW » ramène à la page d'accueil — 2026-09-18

`<h1>borgHelperWWW</h1>` dans l'en-tête devient un lien vers `/`. Vérifié en direct.

## borgHelperWWW 1.8.0 + UI 1.6.0 — préfixe configurable des routes API (`/api` par défaut) — 2026-09-18

Toutes les routes API métier de `borgHelperWWW` sont désormais montées sous un préfixe configurable
(**`/api` par défaut**, ex. `GET /lstbkp` → `GET /api/lstbkp`) — nouveau
`BORGHELPERWWW_API_PREFIX` / `--api-prefix` / clé `api_prefix` du fichier de conf. Vide ou `/`
désactive le préfixe (comportement d'avant ce changement).

Implémenté via un `APIRouter()` regroupant toutes les routes métier (`app.include_router(router,
prefix=API_PREFIX)`) ; `/`, `/version` et `/healthz` restent **délibérément hors préfixe** (comme
`/docs`/`/openapi.json`, natifs FastAPI) — condition nécessaire pour que la page web puisse se charger
et apprendre le préfixe effectif (`GET /version` renvoie désormais aussi `api_prefix`) avant de savoir
où se trouve le reste de l'API. L'interface web lit cette valeur au chargement et l'applique à tous ses
appels API ultérieurs (`apiCall()`, `downloadViaFetch()`).

Vérifié de bout en bout : préfixe par défaut (`/lstbkp` nu → 404, `/api/lstbkp` → 200, `/version` et
`/docs` toujours accessibles nus, `/openapi.json` liste bien les chemins préfixés) ; préfixe
personnalisé (`--api-prefix /borgapi`) ; préfixe désactivé (`--api-prefix ''`) ; téléchargements
(`/download/file`) également montés sous le préfixe.

`borghelperwww.conf.example` mis à jour avec la nouvelle clé `api_prefix`.

## UI 1.5.0 — badge « Tout autorisé » (rappel) — 2026-09-18

Badge **⚠️ Tout autorisé** dans l'en-tête, visible quand `allow_destructive` **et** `allow_downloads`
sont tous les deux à `true` (aucune restriction active sur l'instance) — couleur `err` (rouge), pour
attirer l'attention sur cet état sans protection. Vérifié en direct avec `--allow-destructive`
(`allow_downloads` restant à `true` par défaut).

## UI 1.4.1 — badge « Téléchargements désactivés » — 2026-09-18

Badge **🚫 Téléchargements désactivés** dans l'en-tête (même emplacement/mécanisme que
**🔒 Destructions désactivées**), visible quand `allow_downloads` est à `false` — couleur `warn`
(plutôt que `ok` comme le badge destructions) car ce n'est pas le réglage par défaut : signale une
restriction explicitement choisie par l'administrateur. Vérifié en direct avec `--no-downloads`.

## UI 1.4.0 — masque les boutons d'actions interdites (destruction / téléchargements) — 2026-09-18

Quand `allow_destructive`/`allow_downloads` (récupérés via `GET /version` au chargement de la page)
interdisent une action, le bouton correspondant **n'apparaît plus** dans l'interface web, plutôt que
de rester visible et d'échouer en `403` au clic :

- `allow_destructive=false` : retire **Prune** et **DelBkp** de la liste d'actions de la page Détail
  (nouveau flag `requiresDestructive` sur ces deux entrées d'`ACTIONS`), le bouton **⚡ Lancer Prune**
  et les boutons **🗑 Supprimer** par archive de la vue Historique complet.
- `allow_downloads=false` : retire le bouton **⬇ Télécharger** des résultats de recherche de
  l'explorateur ; masque le bouton de confirmation de la fenêtre de téléchargement (remplacé par un
  message explicite — ouvrir la fenêtre reste possible via clic sur un fichier/clic droit sur un
  dossier, mais plus aucun téléchargement n'y est déclenchable).

Vérifié : filtrage de la liste d'actions et des boutons conditionnels simulés en isolation (logique
identique à celle du fichier), markup et `GET /version` cohérents en direct.

## borgHelperWWW 1.7.1 + UI 1.3.0 — badge « Destructions désactivées » dans l'UI — 2026-09-18

`GET /version` renvoie désormais aussi `allow_destructive` et `allow_downloads` (postures de sécurité
au démarrage, voir 1.7.0 ci-dessous). Interface web : badge **🔒 Destructions désactivées** dans
l'en-tête (visible sur toutes les pages, même avant connexion) quand `allow_destructive` est à `false`
(le défaut) — masqué quand `Prune`/`DelBkp` sont explicitement autorisés. Vérifié en direct : badge
markup présent, `allow_destructive` correctement `false` par défaut et `true` avec `--allow-destructive`.

## borgHelperWWW 1.7.0 + UI 1.2.1 — postures de sécurité par défaut (destruction / téléchargements) — 2026-09-18

Deux nouveaux réglages de sécurité au démarrage de `borgHelperWWW`, affichés sur `stderr` :

- **`BORGHELPERWWW_ALLOW_DESTRUCTIVE`** / `--allow-destructive` / `--no-allow-destructive` / clé
  `allow_destructive` du fichier de conf — **`false` par défaut**. `POST /prune` et `DELETE /delbkp`
  répondent `403 Forbidden` tant qu'il n'est pas explicitement activé. `IdxPurge` (index local, pas les
  sauvegardes elles-mêmes) n'est pas concerné.
- **`BORGHELPERWWW_ALLOW_DOWNLOADS`** / `--allow-downloads` / `--no-downloads` / clé `allow_downloads`
  du fichier de conf — **`true` par défaut**. `GET /download/file` et `GET /download/tar`
  (téléchargement de données en vue d'une restauration) répondent `403 Forbidden` si désactivé.
  `POST /restore` (écrit sur le disque du serveur borgHelperWWW, pas un téléchargement navigateur)
  n'est pas concerné.

Interface web : messages d'erreur de suppression d'archive et de Prune (vue Historique complet)
affichent désormais le détail HTTP (`r.detail`/`HTTP {status}`) au lieu d'un générique « (pas de
détail) » quand la réponse n'a pas la forme `CommandResult` habituelle (cas d'un `403` de ce nouveau
gate).

Vérifié de bout en bout : défauts (`DelBkp`/`Prune` → 403, téléchargement → 200) ; `--allow-destructive`
(`DelBkp` atteint bien le sous-processus) ; `--no-downloads` (téléchargement → 403 avec message clair) ;
mêmes réglages via le fichier de conf (`allow_destructive`/`allow_downloads`).

`borghelperwww.conf.example` mis à jour avec les deux nouvelles clés.

## borgHelperWWW 1.6.0 — endpoint `/healthz` (liveness) — 2026-09-18

Nouvel endpoint `GET /healthz` : répond `{"status":"ok"}` (HTTP 200) dès que le processus tourne, sans
accès `borg`/SQLite ni sous-processus `borgHelper` — pour sondes de liveness (Kubernetes, Docker,
systemd, load-balancer…). Non protégé par `X-API-Key`, comme `/` et `/version`. Vérifié en direct :
200 sans header d'authentification.

## borgHelperWWW 1.5.0 — fichier de conf dédié (`BORGHELPERWWW_CONF`) — 2026-09-18

Nouveau fichier de conf ini pour `borgHelperWWW` lui-même (`BORGHELPERWWW_CONF` / `--conf`), distinct
du `.borghelperrc` qu'il exécute — un seul fichier peut désormais regrouper tous ses réglages :
`cfgfile`, `api_key`, `borghelper_bin`, `ui_file`, `timeout`, `host`, `port`, `trusted_proxies`.
Priorité : option CLI > variable d'environnement déjà présente > fichier de conf > défaut — le fichier
ne comble que ce qui n'est pas déjà réglé autrement, et fonctionne dans les deux modes de lancement
(exécution directe et `uvicorn borgHelperWWW:app` externe, via la variable d'environnement).

Nouveau réglage `BORGHELPERWWW_UI_FILE` / `--ui-file` / clé `ui_file` : chemin de
`borgHelperWWW_ui.html` désormais surchargeable (jusqu'ici toujours à côté du script, sans option).

Fichier `borghelperwww.conf.example` ajouté (toutes les clés documentées, commentées par défaut).
Vérifié de bout en bout : `cfgfile`/`api_key`/`port`/`timeout` depuis le fichier → serveur démarre et
répond avec la clé du fichier sur le port du fichier ; option CLI (`--port`) prioritaire sur la même
clé dans le fichier ; `--ui-file` sert bien un fichier HTML alternatif.

## borgHelperWWW 1.4.0 — IP client réelle dans les logs derrière un reverse proxy — 2026-09-18

`uvicorn.run()` (exécution directe `python3 borgHelperWWW ...`) appelé désormais avec
`proxy_headers=True` (déjà le défaut uvicorn, rendu explicite) et `forwarded_allow_ips=` réglable via
la nouvelle option `--trusted-proxies` / variable `BORGHELPERWWW_TRUSTED_PROXIES` (défaut `127.0.0.1`,
même défaut qu'uvicorn) : les logs d'accès affichent l'IP client réelle (`X-Forwarded-For`) plutôt que
celle du reverse proxy, **uniquement** si la connexion TCP brute provient d'une IP de confiance
(sinon un client pourrait usurper son IP en forgeant lui-même ce header). Vérifié de bout en bout :
`X-Forwarded-For` spoofé depuis une IP de confiance (127.0.0.1, défaut) → apparaît dans le log ; même
en-tête depuis une IP explicitement exclue de `--trusted-proxies` → ignoré, IP réelle du client TCP
loggée. Lancement via `uvicorn borgHelperWWW:app ...` externe : options natives uvicorn
`--proxy-headers`/`--forwarded-allow-ips` (déjà fonctionnelles, aucun changement nécessaire côté code).

## borgHelperWWW 1.3.0 — clé API générée automatiquement si absente — 2026-09-18

`borgHelperWWW` ne refuse plus de démarrer faute de clé API (`-K`/`--api-key`/`BORGHELPERWWW_API_KEY`) :
il en génère une aléatoirement (`secrets.token_urlsafe(32)`) et l'affiche sur `stderr` au démarrage
(encadrée, bien visible). Clé valable pour cette exécution uniquement — perdue au redémarrage, jamais
persistée. Vérifié de bout en bout : démarrage sans clé → clé affichée → fonctionne pour l'auth → une
clé erronée reste rejetée (401) ; démarrage avec `-K` explicite → comportement inchangé, aucune
génération.

## borgHelper 1.0.94 + borgHelperWWW 1.2.0 + UI 1.2.0 — recherche récursive dans l'explorateur (TreeFind) — 2026-09-18

Nouvelle commande **`TreeFind`** : recherche **récursive par nom** (pas le chemin complet) sous un
préfixe (racine entière si omis), dans le dernier snapshot connu — comme `TreeHist`, mais récursif et
filtré par motif. Motif minimal `-m` : `*` = n'importe quelle suite de caractères, `.` reste littéral ;
sans `*` (ni `?`), sous-chaîne implicite (comme `Search`). JSON (`-j`) inclut `parent` (répertoire
contenant l'entrée) par résultat. Aucune migration de schéma — réutilise `archive_snapshot_v` tel quel.

Endpoint `GET /treefind` (mêmes paramètres, `cacheable=True`). Interface web : champ de recherche dans
l'explorateur d'arborescence, scope = répertoire actuellement affiché, récursif. Résultats en liste
avec, par entrée, un lien **📂 Aller au dossier** (navigue directement — le dossier trouvé lui-même, ou
le parent pour un fichier) et un bouton **⬇ Télécharger** réutilisant la fenêtre de téléchargement
existante (mêmes formats brut/`.tar`, même commande `borgHelper` équivalente affichée). Toute
navigation normale efface la recherche en cours.

## borgHelperWWW 1.1.0 — cache de réponses basé sur la date de modification de la base — 2026-09-18

Les endpoints qui ne lisent (ou n'écrivent, pour `DiffBkp` lors de son tout premier appel sur une paire
non indexée) que `cache.db`/`diff.db` — `LstBkp`, `LstBkpFls`, `Report -o`, `DiffBkp`, `Search`,
`FileHist`, `TreeHist`, `DuIdx`, `CacheInfo`, `IdxTop`, `DiffTop` — sont désormais mis en cache en
mémoire par `borgHelperWWW` : un appel identique (même commande, nick, paramètres) est servi depuis le
cache, **sans relancer `borgHelper`**, tant que la date de modification de tous les
`cache.db`/`diff.db` concernés n'a pas changé. Dès qu'un `Bkp`/`Index`/`Prune`/`DelBkp`/… modifie ces
fichiers, l'empreinte change et l'appel suivant recalcule une réponse fraîche — vérifié de bout en bout
(un vrai `Bkp` sur le dépôt de démo fait bien apparaître la nouvelle archive dans `LstBkp` dès l'appel
suivant). Cache borné à 500 entrées (purge totale au-delà) et perdu au redémarrage du processus.

## UI 1.1.0 — animation de chargement + protection contre les réponses tardives — 2026-09-17

**Bug corrigé** : quand un appel API était lent (explorateur d'arborescence notamment), rien
n'indiquait qu'un chargement était en cours, et si l'utilisateur naviguait entre-temps (autre dossier,
autre archive, autre serveur), la réponse tardive du **premier** appel pouvait s'afficher **après**
celle du second — montrant le contenu d'un mauvais répertoire ou d'un mauvais serveur sans que rien ne
le signale.

Corrigé par un numéro de séquence par vue (`browseLoadSeq`, `historyLoadSeq`, `machinesLoadSeq`) :
l'état demandé (nick/chemin/archive) est capturé au moment de l'appel, et une réponse qui revient après
qu'une navigation plus récente a eu lieu est silencieusement ignorée. Animation de chargement
(spinner CSS + « Chargement… ») affichée immédiatement sur : explorateur d'arborescence, liste des
serveurs, historique des 10 dernières sauvegardes par carte, Historique complet.

## borgHelperWWW 1.0.1 + UI 1.0.0 — versionnage UI, intégré à /version — 2026-09-17

`borgHelperWWW_ui.html` reçoit lui aussi son propre numéro de version (`UI_VERSION`, commentaire
`<!-- UI_VERSION: X.Y.Z -->` en tête du fichier) — à incrémenter à chaque commit qui modifie ce fichier
(même règle symétrique que `borgHelper`/`Version` et `borgHelperWWW`/`WWW_VERSION`).

`borgHelperWWW` extrait cette version par regex au démarrage (lecture de `_UI_HTML`) et l'ajoute à la
réponse de `GET /version` (`ui_version`). Pied de page : affiche désormais les trois versions
(borgHelperWWW, borgHelper, UI).

## borgHelperWWW 1.0.0 — versionnage propre + affichage dans le pied de page — 2026-09-17

`borgHelperWWW` reçoit son propre numéro de version (`WWW_VERSION`, jusqu'ici il réutilisait par erreur
`Version` de `borgHelper` pour le champ `version` de l'app FastAPI) — à incrémenter uniquement quand le
source de `borgHelperWWW` change (même règle que `borgHelper` pour son propre `Version`).

Nouvel endpoint `GET /version` (non protégé, comme `/`) renvoyant `borghelperwww_version` et
`borghelper_version`, toutes deux résolues une fois au démarrage du processus (import de `borgHelper`
pour la seconde). Pied de page de l'interface web : affiche désormais les deux versions, récupérées via
`/version` au chargement de la page (avant même la connexion).

## Interface web — navigation rapide + alerte visuelle sur la liste des serveurs — 2026-09-17

Ligne de liens rapides au-dessus de la liste des serveurs : clic sur un nom → défilement direct
(`scrollIntoView`) vers la carte de ce serveur, utile quand la liste est longue. Nom affiché en rouge
(lien ET titre de la carte) si `Report` remonte une erreur pour ce serveur — détecté via le préfixe
`***` déjà posé par `report_offline()` sur le champ `nom` (diff.db absent, dernière sauvegarde plus
ancienne que `MAX_AGE_BKP`, ou erreur SQLite). Aucun changement côté `borgHelper`.

Page élargie (`main` 1100px → 1400px) pour réduire les marges latérales vides. Tableau de l'Historique
complet : colonnes ajustées au contenu (`width:auto`) au lieu d'un étirement uniforme forcé qui créait
de grosses colonnes vides et des sauts de ligne inutiles ; cellules non-coupables (`white-space:nowrap`) ;
défilement horizontal (`overflow-x:auto`) en secours sur petit écran.

## Interface web — alignement des boutons Explorer/Supprimer (Historique complet) — 2026-09-17

Colonne Actions de la vue Historique complet : boutons **🗂 Explorer** et **🗑 Supprimer** alignés en
ligne (flexbox, espacement constant), plus de retour à la ligne intempestif.

## Interface web — vue Historique complet par serveur (Prune / DelBkp / Explorer par archive) — 2026-09-17

Le tableau des **10 dernières sauvegardes** sur chaque carte de la page Serveurs s'affiche désormais
**automatiquement** (aucun clic requis — c'était auparavant un panneau à déplier).

Nouveau bouton **📜 Historique complet** (remplace l'ancien bouton de dépli) : ouvre une nouvelle vue
listant **toutes** les archives indexées en base pour ce serveur (`Report -o -j`, sans `-N`), avec par
archive :
- **🗂 Explorer** — ouvre l'explorateur d'arborescence épinglé sur cette seule archive
  (`archive_from`/`archive_to` = l'archive choisie), pour ne voir que les événements propres à cette
  sauvegarde, sans l'historique des autres. Un bandeau d'information rappelle que droits/genre/
  propriétaire restent le dernier état connu (limitation déjà documentée de `TreeHist`).
- **🗑 Supprimer** — `DelBkp` sur cette archive (confirmation, 🔑 passphrase).

Bouton **⚡ Lancer Prune** en haut de la vue (portée sur tout le dépôt, confirmation, 🔑 passphrase).

Aucun changement côté `borgHelper` — endpoints `/report`, `/treehist`, `/delbkp`, `/prune` déjà
existants, simplement recombinés côté UI.

## Interface web — lien Swagger dans le pied de page — 2026-09-17

Lien **Swagger / API** (`/docs`) ajouté dans le pied de page de l'interface web, visible sur toutes
les pages y compris la page de connexion.

## Interface web — bouton Serveurs dans l'en-tête — 2026-09-17

Bouton **Serveurs** ajouté à côté de **Déconnexion** dans l'en-tête : retour direct à la liste des
serveurs depuis n'importe quelle page (détail, explorateur). Masqué sur la page de connexion et sur
la page Serveurs elle-même.

## Interface web — bouton Explorer sur la liste des serveurs — 2026-09-17

Bouton **🗂 Explorer** ajouté à côté du bouton **▶ Backup** sur chaque carte de la page Serveurs :
ouvre directement l'explorateur d'arborescence (`TreeHist`) du serveur concerné, sans passer par la
page de détail au préalable.

## 1.0.93 — TreeHist affiche aussi le propriétaire (user:group, uid:gid) — 2026-09-17

### Nouvelle colonne `propriétaire` sur `TreeHist`

Précision sur la demande précédente (1.0.92, droits unix) : « droits » incluait aussi
utilisateur/groupe. `TreeHist` affiche désormais le propriétaire du **dernier état connu** de chaque
entrée sous la forme `user:group (uid:gid)` (ex. `root:root (0:0)`), à côté du genre et des droits —
colonne `owner` en JSON (`-j`).

Nécessite une nouvelle colonne `snapshot_file.owner` (migration `ALTER TABLE` automatique dans
`ensure_diff_db()`, additive/rétrocompatible — `DIFF_DB_SCHEMA_VERSION` 3→4). `indexsnap()` (chemins
complet et incrémental) demande désormais `{user}`/`{group}`/`{uid}`/`{gid}` en plus de
`{mode}`/`{type}`/`{size}`/`{isomtime}` à `borg list`. L'auto-réparation d'`indexsnap()` détecte
maintenant `type IS NULL OR mode IS NULL OR owner IS NULL` — un resnapshot complet se déclenche
automatiquement au prochain `Bkp`/`Index` si l'une des trois colonnes manque. Les entrées déjà
snapshotées avant cette version affichent `—` jusqu'à réindexation.

Interface web : nouvelle colonne **Propriétaire** dans l'explorateur d'arborescence.

Vérifié par test réel : migration + auto-réparation sur la DB demo (colonnes absentes → détectées,
resnapshot complet, `owner` peuplé — `root:root (0:0)` — `schema_version` remonté à 4) ; affiché
correctement en CLI, en JSON, et sur la page web servie.

## Interface web — bouton Backup immédiat sur la liste des serveurs — 2026-09-17

Bouton **▶ Backup** sur chaque carte serveur de la page « Serveurs » : lance un `Bkp` immédiat
(`POST /bkp`) sans passer par la page détail. Confirmation avant lancement ; utilise la passphrase de
session déjà enregistrée pour ce nick si présente, sinon avertit et propose de continuer sans (comme les
actions 🔑 de la page détail). Bouton désactivé pendant l'exécution, résultat affiché (succès/erreur +
détail), liste rafraîchie automatiquement ensuite pour refléter le nouveau backup.

Vérifié par test réel : appel `POST /bkp` tel que déclenché par le bouton → exitcode 0, backup réel
effectué sur le dépôt démo.

## 1.0.92 — TreeHist affiche les droits unix — 2026-09-17

### Nouvelle colonne `droits` (mode ls-style) sur `TreeHist`

`TreeHist` affiche désormais les droits unix du **dernier état connu** de chaque fichier/répertoire
(ex. `drwxr-xr-x`, `-rwxr-xr-x`, `lrwxrwxrwx`), à côté du genre — colonne `mode` en JSON (`-j`).

Nécessite une nouvelle colonne `snapshot_file.mode` (migration `ALTER TABLE` automatique dans
`ensure_diff_db()`, additive/rétrocompatible — `DIFF_DB_SCHEMA_VERSION` 2→3). `indexsnap()` (chemins
complet et incrémental) demande désormais `{mode}` en plus de `{type}`/`{size}`/`{isomtime}` à
`borg list`. L'auto-réparation d'`indexsnap()` (1.0.89) détecte maintenant `type IS NULL OR mode IS
NULL` — un resnapshot complet se déclenche automatiquement au prochain `Bkp`/`Index` si l'une ou
l'autre colonne manque. Les entrées déjà snapshotées avant cette version affichent `—` jusqu'à
réindexation.

Interface web : nouvelle colonne **Droits** dans l'explorateur d'arborescence.

Vérifié par test réel : migration + auto-réparation sur la DB demo (`type`/`mode` absents → détectés,
resnapshot complet, colonnes peuplées, `schema_version` remonté à 3) ; droits corrects affichés pour un
répertoire, un fichier exécutable et un lien symbolique (CLI, JSON, et page web).

## Interface web — téléchargement .tar (droits préservés) + commande équivalente — 2026-09-17

### Téléchargement de fichier au format .tar

Le téléchargement brut (`borg extract --stdout`) ne transporte que le contenu, pas les métadonnées
(mode, propriétaire, date). Ajout d'une case « Format .tar (préserve les droits d'accès) » dans la
fenêtre de téléchargement d'un fichier : cochée, réutilise `/download/tar` avec ce fichier comme
`prefix` (déjà générique — fonctionnait sans changement backend, `borg export-tar` acceptant un chemin
de fichier comme de dossier). Vérifié par test réel : `tar tvf` sur un fichier ainsi téléchargé montre
mode/propriétaire/date d'origine préservés (`-rwxr-xr-x root/root ... 2023-04-22 ...`).

### Commande `borgHelper` équivalente, systématique

La fenêtre de téléchargement (fichier brut, fichier .tar, ou dossier .tar) affiche désormais toujours la
commande `borgHelper -c Restore -n <nick> -f <chemin> -w <destination> [-b <archive>]` qui produit le
même résultat en ligne de commande (extraction disque réelle, droits préservés) — mise à jour en direct
quand l'archive sélectionnée change.

## Interface web — téléchargement de fichier : archives filtrées au mouvement réel — 2026-09-17

La liste déroulante d'archives pour télécharger un fichier proposait tout l'historique du dépôt
(`/lstbkp`), sans lien avec ce fichier précis. Elle ne propose désormais que les archives où **ce
fichier** a réellement changé (`added`/`modified` — `removed` exclu, le fichier n'y existe plus).
`loadBrowse()` charge maintenant l'explorateur avec `archive_from=ALL` (historique complet par entrée,
au lieu de la dernière paire seulement) et réutilise ces événements déjà en mémoire — aucun appel API
supplémentaire pour peupler le menu. Sans mouvement indexé pour ce fichier : la dernière archive reste
proposée par défaut. Le `.tar` d'un dossier (clic droit) continue de proposer toutes les archives —
sans objet à filtrer pour un instantané complet.

Vérifié par test réel : fichier modifié 2 fois sur 3 backups → 2 archives (et seulement ces 2)
proposées ; fichier jamais retouché → 0 archive proposée avec le fichier lui-même.

## 1.0.91 + borgHelperWWW — Explorateur d'arborescence — 2026-09-17

### `borgHelper` : `TreeHist -j`

Nouveau flag `-j` sur `TreeHist` : sortie JSON `{nick:{path,archive,entries:[{name,full_path,genre,
is_dir,events}]}}` au lieu du tableau texte — même contenu, structuré pour une consommation
programmatique (utilisé par le nouvel explorateur web).

### `borgHelperWWW` : endpoints `/download/file` et `/download/tar`

Nouveaux endpoints streamant des octets bruts (`borg extract --stdout` / `borg export-tar`) directement
vers l'appelant — seule exception au principe « tout passe par le binaire borgHelper en sous-processus »,
binaire streaming incompatible avec la réponse JSON texte des autres endpoints. Conf lue via `BorgRunner`
en mode librairie, `borg` appelé directement.

### Interface web : explorateur d'arborescence

Bouton **🗂 Explorer l'arborescence** dans le bandeau du serveur. Navigation façon gestionnaire de
fichiers sur `TreeHist -j` : clic sur un dossier = l'ouvrir, clic droit sur un dossier = télécharger un
`.tar` de son contenu (à une archive choisissable), clic sur un fichier = le télécharger (à une archive
choisissable) — téléchargement direct dans le navigateur (fetch + blob + `<a download>`), jamais écrit
sur le disque du serveur borgHelperWWW.

Vérifié par test réel : navigation JSON via `/treehist`, téléchargement d'un fichier régulier
(comparaison octet-à-octet avec l'original — identique) et d'un `.tar` de ~140 Mo (contenu vérifié via
`tar tf`) — le tout via curl et via la page servie par `borgHelperWWW`.

## borgHelperWWW UI — 2026-09-17

Retiré la saisie de passphrase de la page « Serveurs » (liste) — champ input + bouton Enregistrer par
carte serveur, remplacés par un badge lecture-seule (enregistrée / non renseignée). La passphrase ne se
saisit plus que sur la page détail du serveur concerné.

## 1.0.90 — 2026-09-17

### `Prune` migre désormais la DB comme `Bkp`/`Index` — `DIFF_DB_SCHEMA_VERSION` bumpée à 2

`prune()` ne passait par aucun `ensure_diff_db()`/`ensure_cache_db()` avant d'exécuter
`_cleanup_index_after_prune()` et `clear_cache_nick()` — contrairement à `Bkp`/`Index`/`Report`, il
pouvait donc opérer sur un schéma non migré (colonne `snapshot_file.type` manquante, ancien
`archive_snapshot`). Corrigé : `prune()` appelle désormais `ensure_cache_db()`/`ensure_diff_db()` en
tout premier, et `_cleanup_index_after_prune()` le fait aussi en défense en profondeur.

`DIFF_DB_SCHEMA_VERSION` passe de 1 à 2, documentant enfin correctement les deux migrations
structurelles déjà en place (déduplication `archive_snapshot`, `snapshot_file.type`) — jusqu'ici les
deux étaient appliquées sous version 1, rendant le numéro inexploitable pour savoir si une DB était à
jour. Les migrations restent auto-détectées par introspection (`PRAGMA table_info`), pas seulement par
comparaison de version — donc rejouables sans risque. Table de correspondance version ↔ migration dans
TECHNICAL.md.

Vérifié par test réel : DB ramenée à un état pré-migration (colonne `type` supprimée, `schema_version`
forcé à 1), seul `Prune` lancé (aucun `Bkp`/`Index`) → colonne restaurée, `schema_version` remonté à 2.
Garde anti-régression (DB plus récente que le binaire) revérifiée, toujours fonctionnelle.

## 1.0.89 — 2026-09-17

### `IndexSnap` : auto-réparation du `type` manquant

Le clonage incrémental (`_indexsnap_incremental`) réutilise le `file_id` (donc le `type`) des fichiers
inchangés — un `type` manquant (migration `snapshot_file.type` ou ancien snapshot pré-1.0.86) ne se
réparait jamais tout seul via l'incrémental normal, obligeant un `Index -F -S` manuel. `indexsnap()`
détecte désormais toute entrée `type IS NULL` avant de tenter l'incrémental et, si trouvée, force un
resnapshot complet cette fois-là (message « type manquant… auto-réparation ») — les backups suivants
repassent en incrémental normal une fois tout repeuplé. Se déclenche automatiquement au prochain `Bkp`
(indexation auto activée) ou `Index`, sans intervention.

Vérifié par test réel : `type` neutralisé manuellement (simulation de données pré-1.0.86), `Bkp` normal
(sans `-F`/`-S`) lancé → détection, resnapshot complet automatique, tous les `type` repeuplés.

## 1.0.88 — 2026-09-17

### `TreeHist` : added/removed ne concernent que l'entrée elle-même

Le rollup des sous-répertoires (1.0.87) pouvait afficher `added` ou `removed` sur un répertoire alors
que seul un descendant avait été ajouté/supprimé — trompeur (laissait croire que le répertoire lui-même
avait été créé/supprimé). Désormais : `added`/`removed` ne s'affichent que si l'entrée du répertoire
**elle-même** a ce marqueur dans `diff_index` (ex. `added directory`/`removed directory`) ; tout
mouvement interne quelconque (ajout/suppression/modification d'un descendant, à n'importe quelle
profondeur) remonte en `modified` générique. Un événement propre à l'entrée (ex. `ctime`) prime sur le
synthétique `modified` pour la même archive — pas de doublon.

Vérifié par test réel : fichier ajouté 2 niveaux sous un répertoire → le répertoire affiche `modified`
(pas `added`) ; un sous-répertoire ayant à la fois son propre `ctime` et un descendant ajouté à la même
archive n'affiche que son `ctime` (pas de ligne `modified` redondante).

## 1.0.87 — 2026-09-17

### `TreeHist` : un sous-répertoire "a eu des événements" si sa sous-arborescence a changé

Un sous-répertoire n'affichait un événement que si SA PROPRE entrée avait un marqueur direct dans
`diff_index` (ex. `added directory`) — restant "aucun événement" même si un fichier profondément niché
en dessous avait changé. Désormais : un sous-répertoire (et `.`, toujours un répertoire) affiche un
événement dès qu'un changement a eu lieu n'importe où dans sa sous-arborescence (`path=<lui> OR path
LIKE '<lui>/%'`, `SELECT DISTINCT` sur type/archive/date) — sans en lister le détail, toujours pas de
contenu de sous-répertoire. Les fichiers, eux, n'affichent que leurs propres événements (inchangé).

Vérifié par test réel : fichier modifié 2 niveaux sous un sous-répertoire dont la propre entrée n'a
aucun marqueur → le sous-répertoire, son parent et `.` affichent tous `modified` grâce au rollup.

## 1.0.86 — 2026-09-17

### `TreeHist` : un seul tableau, colonne genre (répertoire/fichier/lien/…)

Fusionné en un seul tableau (au lieu de sections séparées « entrée elle-même »/« sous-répertoires »/
« fichiers ») : le répertoire courant apparaît en `.`, suivi de ses enfants immédiats. Nouvelle colonne
`genre` tirée du **type réel stocké par borg** (`{type}` de `borg list`) : `répertoire`, `fichier`,
`lien symbolique`, `fifo`, `socket`, `périph. bloc`/`caractère` — plus fiable que l'ancienne heuristique
par profondeur de chemin.

Nécessite une nouvelle colonne `snapshot_file.type` (migration `ALTER TABLE` automatique dans
`ensure_diff_db()`, additive/rétrocompatible, pas de bump `DIFF_DB_SCHEMA_VERSION`). `indexsnap()`
(chemins complet et incrémental) demande désormais `{type}` en plus de `{size}`/`{isomtime}` à
`borg list`. Les entrées déjà snapshotées avant cette version affichent `inconnu (réindexer)` jusqu'à
réindexation (`Index -F -S` ou nouveau `Bkp`).

Vérifié par test réel : répertoire, fichier régulier, lien symbolique et fifo tous correctement
identifiés ; DB pré-migration testée (dégradation propre vers `inconnu (réindexer)`, pas de crash).

## 1.0.85 — 2026-09-17

### `TreeHist` : liste toujours l'intégralité du répertoire courant

`TreeHist` n'affichait que les entrées ayant changé dans la plage demandée ; les fichiers/répertoires
présents mais inchangés (ou dont l'historique a été purgé) étaient absents. Unifié les deux anciens
modes (table plate des changements / listing de secours) en un seul : toujours l'intégralité du
répertoire courant (snapshot), chaque entrée annotée de ses propres événements dans la plage `-b`/`-B`
(défaut : dernière archive indexée, comme avant), avec `aucun événement dans la plage` pour les entrées
présentes mais inchangées sur la période — au lieu d'être simplement omises. Vérifié par test réel
(fichier modifié + fichier jamais touché dans le même répertoire, aux deux apparaissent désormais).

## 1.0.84 — 2026-09-17

### `TreeHist` : ne remonte que le contenu direct du répertoire

Corrigé : `TreeHist` listait tout le sous-arbre sous `<préfixe>` (n'importe quelle profondeur) au lieu de
son seul contenu direct. Restreint désormais à `path=<préfixe>` (l'entrée du répertoire lui-même) et à
ses enfants immédiats (`path LIKE 'préfixe/%' AND path NOT LIKE 'préfixe/%/%'`) — jamais le contenu d'un
sous-répertoire. Pour y descendre, relancer `TreeHist -f <sous-répertoire>`. Vérifié par test réel
(changements à 3 profondeurs : racine, sous-répertoire direct, sous-répertoire imbriqué).

## 1.0.83 — 2026-09-17

### `TreeHist` : bascule en listing courant si rien n'a changé

Quand la requête (répertoire + plage `-b`/`-B`) ne trouve aucune modification, `TreeHist` affiche
désormais le contenu courant du répertoire (dernier snapshot indexé) au lieu d'un message vide :
sous-répertoires avec leurs apparitions/disparitions, fichiers avec tout leur historique de
création/modification/suppression — historique par entrée toujours calculé sur tout l'index, sans
tenir compte de `-b`/`-B` (qui ne sert qu'à décider du mode d'affichage).

### Correctif `_indexsnap_incremental` : colonnes `archive_snapshot` corrompues

Repéré en marge du travail sur `TreeHist` : l'INSERT qui applique les fichiers `added` (indexation
incrémentale du snapshot, chemin par défaut) liait ses paramètres dans le mauvais ordre —
`(archive_name,archive_date,nick,nick,path)` au lieu de `(nick,archive_name,archive_date,nick,path)` —
ce qui corrompait les colonnes `nick`/`archive`/`archive_date` de `archive_snapshot` pour chaque fichier
ajouté via ce chemin. `diff_index` n'était pas affecté. Corrigé (paramètres réordonnés), vérifié par
test réel (backup incrémental avec fichier ajouté → `archive_snapshot` cohérent).

⚠️ Les lignes déjà écrites avant ce correctif restent corrompues en base — réindexer le snapshot
(`borgHelper -c Index -n <nick> -F -S`) pour les régénérer proprement.

## 1.0.82 — 2026-09-17

### Nouvelle commande `TreeHist`

Pour chaque objet sous un préfixe d'arborescence (toute l'arborescence si `-f` omis) : liste triée par
chemin des événements (`added`/`modified`/`removed`/…) et de l'archive où ils ont eu lieu. DB-only
(`diff_index`), pas d'appel borg, pas de passphrase requise — même mécanique que `Search`/`FileHist`
(`-b ALL` pour tout l'historique, sinon dernière archive indexée seulement). Reportée dans
`borgHelperWWW` (`GET /treehist`) et dans l'interface web.

Au passage, repéré (non corrigé — hors scope) un bug préexistant dans `index()` : le `threading.Event`
utilisé pour arrêter le thread moniteur de priorité est aussi lu comme indicateur d'interruption après
la boucle — il est toujours `set()` à la fin, donc `index()` affiche systématiquement "indexation
interrompue" et pose `index_pending_lock`, même en cas de succès complet. Les insertions en base ne sont
pas affectées (elles ont lieu avant ce check), seuls le message et le code de retour sont faux.

## 1.0.81 — 2026-09-17

### `borgHelperWWW` : interface web

Nouveau fichier `borgHelperWWW_ui.html` (SPA vanilla JS, servi sur `/`, aucune dépendance externe) :
connexion par clé API, liste des serveurs (rapport hors-ligne, aucune passphrase requise), passphrase
par serveur saisie et conservée en `sessionStorage` pour la session du navigateur, puis panneau
d'actions par serveur (toutes les commandes de l'API, confirmation pour les actions destructives).
Testé via curl sur chaque endpoint utilisé par la page + vérification statique du JS (syntaxe, ids DOM,
handlers) faute d'extension Chrome disponible dans cette session.

## 1.0.80 — 2026-09-17

### `borgHelperWWW` : options CLI (-C, -K, --host, --port, ...)

En exécution directe (`python3 borgHelperWWW ...`), la conf peut désormais être passée en options CLI
en plus des variables d'environnement : `-C/--cfgfile`, `-K/--api-key`, `--borghelper-bin`, `--timeout`,
`--host`, `--port` (priment sur l'environnement). Sous `uvicorn borgHelperWWW:app`, uvicorn possède
seul `sys.argv` — les variables d'environnement `BORGHELPERWWW_*` restent le seul canal dans ce mode
(inchangé). `python3 borgHelperWWW --help` pour le détail.

## demo.borghelperrc — 2026-09-17

Fichier de conf démo, 100% local (pas de SSH) : deux nicks `demo-modules` (`/lib/modules`) et
`demo-usrlocal` (`/usr/local`) sur le host courant, dépôts/cache/DB SQLite sous `/tmp/demo_borghelper`.
Testé de bout en bout (Init, Bkp, Stats, LstBkp, LstBkpFls, Report).

## 1.0.79 — 2026-09-17

### `borgHelperWWW.py` : symlink manquant pour `uvicorn borgHelperWWW:app`

`uvicorn <module>:app` importe le module par son nom via `importlib` — échoue sans extension `.py`
("Could not import module"). Ajout du symlink `borgHelperWWW.py → borgHelperWWW`, même principe que
`borgHelper.py`. Sans impact sur `python3 borgHelperWWW` (exécution directe).

## 1.0.78 — 2026-09-17

### `-P` : passphrase en paramètre + correctif `-C`

Nouveau paramètre `-P <passphrase>` (et variable d'environnement `BORGHELPERC_RUNTIME_PASSPHRASE`,
prioritaire sur `-P` uniquement par ordre de résolution — l'env est le défaut, `-P` le supplante s'il
est fourni explicitement) : complète ou supplante `BORG_PASSPHRASE` du `.borghelperrc` pour l'appel en
cours, sans le persister. Permet de garder un `.borghelperrc` sans passphrase en clair et de l'injecter
à l'exécution — cas d'usage principal : `borgHelperWWW`.

Corrigé au passage : `-C <fichier>` n'acceptait en réalité aucun argument (absent du spec `getopt`,
`-C /chemin` provoquait "Argument(s) non reconnu(s)") alors que la doc l'a toujours documenté comme
prenant un chemin. `-C` fonctionne maintenant comme documenté.

### Nouveau : `borgHelperWWW`

API HTTP (FastAPI + Swagger) au-dessus de `borgHelper`, en sous-processus (aucune modification du
comportement CLI). Toutes les commandes sauf `Mount`/`UMount`. Auth par clé partagée (`X-API-Key`),
passphrase par appel (`X-Borg-Passphrase` → `-P`). Voir [README.md](README.md#borghelperwww--api-http).

## 1.0.77 — 2026-09-17

### `LstBkp` et `LstBkpFls` : DB uniquement, plus d'appel `borg`

`list_backups` lit désormais `archive_stats` et `list_files` lit `archive_snapshot_v` (via `get_diff_db`) au lieu d'exécuter `borg list`. Réponse quasi-instantanée pour les dépôts distants, au prix de dépendre de l'indexation (`Bkp`/`Index` pour la liste d'archives, `Indexsnap` pour les fichiers) — message d'erreur explicite si rien n'est indexé.

## 1.0.76 — 2026-06-13

### Refactoring interne : consolidation du système de locks PID

Extraction de `_repo_key(nick)` (calcul de la clé repo à partir de `BORG_REPO` ou `DB_NAME`) pour éliminer la duplication dans les 3 méthodes `_*_lock_path`. Ajout de `_pid_lock_path(nick, suffix)`, `_set_pid_lock`, `_clear_pid_lock`, `_check_pid_lock` comme helpers génériques. Les 12 méthodes publiques de lock (priority, report-running, index-running) deviennent des wrappers d'une ligne. Aucun changement de comportement.

## 1.0.75 — 2026-06-13

### Report résumé : suppression de la clé `size_delta_last` du dict résumé

`size_delta_last` était visible dans la sortie JSON (`-j`) et en fallback `colnames`. Remplacé `get()` par `pop()` dans `report` et `report_offline` pour consommer la clé après usage.

## 1.0.74 — 2026-06-12

### Report résumé : `size_delta` de la dernière sauvegarde dans la colonne `derniere`

La colonne `derniere` du résumé (ligne par hôte) affiche maintenant le `size_delta` de la dernière archive entre parenthèses — ex. `1.37 GB (+11%)`. Absent si première archive. Stocké via `size_delta_last` dans `tcmpl[nick]` (non affiché séparément), appendé après `convert_octets_readable` dans `report` et `report_offline`.

## 1.0.72 — 2026-06-12

### `Index` interrompu par `bkp` : reprise automatique après le backup

Quand un `Index` externe est interrompu par un backup prioritaire, un fichier `index-pending.lock` est posé. `backup()` le détecte en fin d'exécution (après son propre `index` ciblé) et lance automatiquement un `Index` complet — sans intervention manuelle.

Deux cas couverts :
- **Early-exit** : `priority_lock` déjà actif au démarrage de `Index` → pending posé immédiatement
- **Interrupt mid-run** : `_priority_monitor` tue les diffs → pending posé après le retour de la phase diff

Les appels internes à `index()` depuis `backup()` utilisent `set_pending=False` pour ne pas déclencher de reprise récursive.

## 1.0.71 — 2026-06-12

### `Index` : priorité `bkp` étendue à toute la durée d'exécution

Deux correctifs :

1. **Early-exit au démarrage** : si `priority_lock` est posé au moment où `Index` démarre (Bkp/Restore déjà actif), l'indexation est annulée immédiatement sans lancer `borg list` ni aucun diff.

2. **Arrêt complet après interrupt** : lorsque `_priority_monitor` interrompt les diffs en cours, `index()` s'arrête aussitôt après (au lieu de continuer avec `borg info` + `indexsnap`). `bkp` peut donc reprendre sans attendre la fin de ces opérations post-diff.

## 1.0.70 — 2026-06-12

### `bkp` : indexation complète (avec tailles) automatique après backup

La commande `bkp` lance maintenant automatiquement `index()` après `indexsnap()`, ciblé sur la nouvelle archive (`-A <archive_new>`). Cela déclenche `borg diff --json-lines` pour remplir les tailles (`size_before`/`size_after`) dans `diff_index` — opération jusqu'ici nécessitant un appel manuel séparé à `Index`. Le `priority_lock` est levé avant l'appel à `index()` (le travail borg est terminé) ; le `finally` reste inoffensif (double `clear` absorbé par `OSError: pass`).

## 1.0.69 — 2026-06-12

### Report : `size_delta` remplace `dedup_delta` — basé sur `original_size`

`dedup_delta` (variation de `deduplicated_size`) remplacé par `size_delta` (variation de `original_size`). `original_size` est stable dans le temps (taille réelle des données de l'archive, indépendante de la déduplication inter-archives) — contrairement à `deduplicated_size` qui varie selon les archives voisines. La colonne est repositionnée après `original_size` dans le tableau. Le chargement de valeurs figées depuis `archive_stats` dans `prep_report` devient inutile et est supprimé.

## 1.0.68 — 2026-06-12

### Report : `dedup_delta` utilise les valeurs figées de `archive_stats`

Dans `prep_report` (rapport live), le calcul de `dedup_delta` utilisait les `deduplicated_size` retournées par `borg info` — valeurs qui varient à chaque nouveau backup (la déduplication redistribue les chunks entre archives). Corrigé : `prep_report` charge les valeurs de `archive_stats` (figées au moment de l'indexation initiale) et les utilise pour le delta. Fallback sur la valeur live si l'archive n'est pas encore dans `archive_stats`.

## 1.0.67 — 2026-06-12

### Report : colonne `dedup_delta` — variation de taille dédupliquée

Nouvelle colonne dans le tableau des sauvegardes du rapport (`Report` et `Report -o`) : `dedup_delta` affiche le pourcentage de variation de `deduplicated_size` par rapport à l'archive précédente (`+11%`, `-5%`, `—` pour la première). Calculé dans `prep_report` et `prep_report_from_db` à partir des valeurs déjà stockées dans `archive_stats`.

## 1.0.66 — 2026-06-12

### `indexsnap` incrémental via `diff_index`

Nouveau `_indexsnap_incremental` : si un snapshot précédent et un diff indexé existent, met à jour le snapshot par diff SQL au lieu d'un `borg list` complet :
- `removed` → DELETE de archive_snapshot + cleanup orphelins
- `modified` → UPDATE size dans snapshot_file (mtime conservé)
- `added` → `borg list` ciblé sur ces chemins uniquement (mtime exact)
- Fallback automatique vers `borg list` complet si : pas de snapshot précédent, diff absent, > 5000 ajouts, ou erreur borg
- `-F` force toujours le `borg list` complet

## 1.0.65 — 2026-06-12

### `indexsnap` : purge automatique des snapshots anciens

Après indexation du snapshot, `indexsnap` appelle `_snapurge_check` / `_snapurge_exec` et purge les archives au-delà de `IDX_SNAP_KEEP` (même logique que `IdxPurge`). Erreur non bloquante (`[WARN]`).

## 1.0.64 — 2026-06-10

### IdxPurge : IDX_SNAP_KEEP déduit de KEEP_* par défaut

Si `IDX_SNAP_KEEP` absent de la config, le seuil de rétention des snapshots est calculé comme `sum(KEEP_DAILY + KEEP_WEEKLY + KEEP_MONTHLY + KEEP_YEARLY + KEEP_HOURLY)`. Fallback à 10 si aucune règle KEEP_* n'est définie.

## 1.0.63 — 2026-06-10

### Refactor : purge des snapshots intégrée dans `IdxPurge`

La commande `SnapUrge` (1.0.62) est supprimée. `IdxPurge` purge désormais automatiquement les snapshots anciens en fin d'opération, via deux helpers privés `_snapurge_check` / `_snapurge_exec`. Seuil configurable : `IDX_SNAP_KEEP=10` dans borghelperrc (défaut 10). Un seul commit SQLite + un seul VACUUM pour les deux opérations. Le dry-run affiche aussi les snapshots qui seraient purgés.

## 1.0.62 — 2026-06-10

### Nouvelle commande : `SnapUrge` (remplacée par 1.0.63)

## 1.0.61 — 2026-06-10

### Bugfix : option `-A` de la commande `index` non reconnue

`-A` absent du string `getopt` (`A:` ajouté) et de `optab['index']` (`A` ajouté). L'option était parsée nulle part — `getopt` levait une erreur avant même d'atteindre le dispatch.

## 1.0.60 — 2026-06-10

### Résumé : factorisation du VACUUM SQLite

Nouvelle méthode `BorgHelper._vacuum_db(db_path, verbose)` : `VACUUM INTO` dans le même répertoire + `os.replace`, `[WARN]` non bloquant en cas d'échec. `verbose=True` (IdxPurge) affiche compactage en cours/terminé + hint manuel ; `verbose=False` (_cleanup_index_after_prune) est silencieux en cas de succès. Les deux anciens blocs dupliqués sont remplacés par un appel à cette méthode.

## 1.0.59 — 2026-06-10

### Résumé : VACUUM après prune via VACUUM INTO (évite l'erreur "disk is full")

`_cleanup_index_after_prune` utilisait `VACUUM` qui crée une copie complète en espace temporaire (`/tmp`). Sur les serveurs où `/tmp` est un `tmpfs` plus petit que `diff.db`, cela échouait avec "database or disk is full" même si la partition de données avait de l'espace. Remplacé par `VACUUM INTO db_path.vacuum_tmp` (même répertoire que la DB) + `os.replace`, identique au pattern déjà utilisé par `IdxPurge`. Échec de compactage → `[WARN]` non bloquant, les entrées purgées sont conservées.

## 1.0.58 — 2026-06-10

### Résumé : version borgHelper dans les messages d'erreur stderr

`printer()` ajoute automatiquement `[borgHelper vX.Y.Z]` en suffixe de tout message stderr contenant `[ERREUR]` ou `[WARN]`. Aucun site d'appel modifié — effet global sur tous les avertissements et erreurs.

## 1.0.57 — 2026-06-10

### Résumé : report live toujours via borg (plus de fallback DB)

`report` (sans `-o`) appelle désormais toujours `prep_report()` (borg live), y compris quand Bkp/Restore est en cours. Dans ce cas, `borg info` sera mis en attente du verrou borg plutôt que de tomber en fallback DB. `wait_index_idle` + `set_report_running_lock` stoppent l'indexation avant l'appel borg (inchangé). Alerte uniquement si borg échoue (`errcode=2`) ou si l'âge du dernier backup dépasse `MAX_AGE_BKP` ou si le dépôt est vide (`duree==-1`). La correction de `_msg` → alerte ne s'applique plus qu'à `report_offline` (`-o`), où elle est légitime.

## 1.0.56 — 2026-06-10

### Résumé : alerte systématique si aucun backup détectable (-o ou non)

`report` et `report_offline` génèrent désormais `errcode=1` + marqueur `***` / `errhost` dans deux cas : (1) `_msg` retourné par `prep_report_from_db` (diff.db absent ou aucune archive indexée) ; (2) dépôt borg vide (`c==0`, `duree==-1`) dans `prep_report` — le `depuis` affiché vaut `—` au lieu de la date de modification du repo, `duree` et `derniere` valent `—`.

## 1.0.55 — 2026-06-10

### Résumé : borg diff --json-lines + streaming stdout + insert pipeline

`borg diff` lancé avec `--json-lines` : sortie JSON structurée par ligne au lieu de texte humain. Nouveau parser `parse_diff_line_json` remplace les regex de `parse_diff_line`. `_run_diff` lit désormais le stdout de borg ligne à ligne (streaming) au lieu d'attendre `communicate()` : la mémoire pic est réduite et le parsing débute dès la première ligne. L'insert SQLite est déplacé dans la boucle `as_completed` (ancienne Phase 3 supprimée) : chaque paire est écrite en DB dès que son diff se termine, sans attendre les paires encore en cours. Même changement appliqué à `listperms`. Sur les gros dépôts, la latence entre fin du dernier diff et données disponibles en DB est quasi nulle.

## 1.0.54 — 2026-06-10

### Résumé : suppression des TODO obsolètes

Supprime les 4 commentaires TODO en tête de fichier (gestion erreurs borg, paramètres borgrc manquants, aide création borgrc, nettoyage caches) — fonctionnalités toutes implémentées.

## 1.0.53 — 2026-06-10

### Résumé : version borgHelper dans tous les stdout JSON

Tous les outputs JSON stdout incluent désormais la clé `borghelper_version` (valeur : string X.Y.Z). Concerne : `backup` (stdout borg create), `report`/`report_offline` (clé `-j`), et les commandes `DiffIndex`/`SnapIndex` en mode JSON (`-J`).

## 1.0.52 — 2026-06-10

### Résumé : réindexation ciblée sur une archive spécifique (`-A`)

Nouvelle option `-A <archive>` pour `borgHelper -c Index` : réindexe uniquement la paire dont `archive_new` correspond à l'archive donnée, sans toucher aux autres paires. Utile pour forcer la réindexation d'un backup précis (ex : `12%nb / —` qui indique des tailles manquantes). Implémenté via `target_archive=None` dans `index()`.

## 1.0.51 — 2026-06-10

### Résumé : message colspan quand archive_stats est vide

Quand `archive_stats` est vide (diff.db absent ou aucune archive indexée), le résumé affiche la commande à exécuter dans une seule cellule qui regroupe toutes les colonnes sauf `nom` — au lieu de lever une exception. En HTML : `colspan=100` sur la cellule message. En terminal : message dans la colonne `duree`. `prep_report_from_db` retourne un dict `_msg` au lieu de lever une exception ; `htmlTabelise` gère le rendu colspan.

## 1.0.50 — 2026-06-10

### Suppression colonne `moy` du résumé

La taille dédupliquée moyenne par archive est redondante avec la colonne `derniere`. Supprimée de `prep_report_from_db`, `prep_report` et de la boucle de conversion dans `report`.

## 1.0.49 — 2026-06-10

### `modifications` : espace disque en valeur absolue lisible

Remplace `YY%B` (pourcentage entier, toujours 0 avant fix des tailles) par la somme des tailles absolues des fichiers ajoutés + modifiés + supprimés, affichée en format lisible (`convert_octets_readable`). Exemple : `24%nb / 1.37 GB`. Affiche `—` si aucune donnée de taille disponible.

## 1.0.48 — 2026-06-10

### Correction `%B` toujours 0 dans le rapport

`backup()` stockait les entrées post-backup depuis `_bkp_parse_list` (tailles toutes NULL) et marquait la paire comme indexée dans `diff_indexed_pairs`. `index()` voyait la paire déjà indexée et la sautait → les tailles restaient NULL → `0%B` permanent.

Fix : ajout de `diff_pair_has_sizes()` dans `BorgHelperDB`. Dans la phase 1 de `index()`, si une paire est déjà indexée mais sans tailles (post-backup), elle est ajoutée à `pairs_to_purge` et re-indexée via `borg diff` — qui fournit les vraies tailles. Sans changement de schéma DB.

Cas particuliers : `entry_count=0` (aucun changement) et paires avec uniquement des entrées `C/B/T` (sans taille par nature) sont correctement traités comme "avec tailles" pour éviter une boucle de re-indexation.

## 1.0.47 — 2026-06-10

### Message `wait_index_idle` plus explicite

Inclut le nom du dépôt (nick) et le timeout dans le message affiché quand `report` attend la fin d'une indexation en cours.

## 1.0.46 — 2026-06-10

### `report` interrompt l'indexation en cours

`report` (sans `-o`) pose un verrou `report-running.lock` avant d'appeler borg, ce qui déclenche l'arrêt du `_priority_monitor` dans `index` (comme pour Bkp/Restore). Puis attend `wait_index_idle` (max 30 s) que les `borg diff` en cours libèrent le dépôt avant de lancer `prep_report` en live. Résultat : le rapport obtient toujours les données fraîches du backup le plus récent, même si une indexation parallèle était en cours.

Seul cas de fallback sur la DB conservé : quand un Bkp/Restore tient le `priority.lock`.

## 1.0.45 — 2026-06-09

### Parsing stderr ligne par ligne dans `boex`

Remplace le parsing en bloc (`json.loads('[' + join + ']')`) par un parsing ligne par ligne. Quand le JSON global échouait (ex. bannière SSH mélangée au JSON borg), les entrées `file_status` restaient sous forme de chaîne brute `{"type":"file_status"...}` et n'étaient pas filtrées. Désormais chaque ligne est parsée indépendamment : les lignes JSON valides deviennent des dicts (correctement filtrés), les autres restent des strings.

## 1.0.44 — 2026-06-09

### Filtrage messages DEBUG borg sur `bkp`

Supprime du stderr les messages `DEBUG` de borg (ex. `Merging into master chunks index`, `Reading cached archive chunk index`) lors d'un backup. Ces messages n'apparaissent qu'avec l'option `--debug`. Les entrées fichier par fichier (`file_status`) étaient déjà filtrées.

## 1.0.43 — 2026-06-09

### Format nom d'archive sans deux-points

`{now}` → `{now:%Y-%m-%dT%H%M%S}` : `sg210-root-2026-05-31T230006` au lieu de `sg210-root-2026-05-31T23:00:06`. Compatible avec les systèmes de fichiers qui n'acceptent pas les `:`.

## 1.0.42 — 2026-06-09

### `SchemaVersionError` : mismatch DB non bloquant pour `bkp`/`restore`

Remplace `sys.exit(1)` de `_check_set_meta` par `raise SchemaVersionError`. Pour `bkp`, l'exception est absorbée par le `except Exception` existant → warning + borg s'exécute normalement. Pour `Index`, `Report`, etc., l'exception remonte jusqu'à `__main__` et affiche un message propre avant de quitter.

## 1.0.41 — 2026-06-09

### Versionning schéma DB (`db_meta`)

Ajout table `db_meta (key, value)` dans `cache.db` et `diff.db`. Stocke `schema_version` (entier, incrémenté uniquement sur changement de schéma) et `borghelper_version` (version du script). Au démarrage : si `schema_version` DB > constante attendue → erreur + exit (DB d'une version future incompatible). Constantes actuelles : `DIFF_DB_SCHEMA_VERSION=1`, `CACHE_DB_SCHEMA_VERSION=1`.

## 1.0.40 — 2026-06-09

### `diffbkp` : cache conservé + stockage filtré corrigé

Restaure le comportement cache : si la paire est déjà indexée, lecture depuis `diff_index` (rapide, sans appel borg). Si non indexée : borg diff → filtre via `_idx_path_ok` → stockage filtré (`diff_index`) + exclus (`diff_excluded_stats`) → affichage complet (non filtré). Les paires mal indexées antérieurement nécessitent un `borgHelper -c Index -n <nick> --force`.

## 1.0.39 — 2026-06-09

### `diffbkp` : re-calcul forcé + stockage filtré + affichage complet

**Bug** : l'indexation à la volée de `diffbkp` stockait tous les fichiers sans appliquer `IDX_EXCLUDE`, polluant `diff_index`. De plus, si la paire était déjà en cache (même incorrectement), `diffbkp` lisait les données corrompues sans recalculer.

**Fix** :
- `diffbkp` force toujours un re-calcul via `borg diff` (purge préalable de la paire)
- Stockage filtré : `entries_ok` → `diff_index`, fichiers exclus → `diff_excluded_stats`
- Affichage depuis `all_entries` (non filtré) — le diff complet reste visible à l'écran
- L'utilisateur doit relancer `borgHelper -c Index -n <nick> --force` une fois pour nettoyer les paires déjà mal indexées

## 1.0.38 — 2026-06-09

### Statistiques : fichiers exclus inclus dans `modifications`

`_diff_stats_for_nick` agrège maintenant `diff_excluded_stats` (par `archive_new`) en plus de `diff_index`. Les fichiers filtrés par `IDX_EXCLUDE` (added/modified/removed) sont comptés dans le numérateur et le dénominateur de la colonne `modifications`, ce qui donne un pourcentage représentatif de l'intégralité des fichiers modifiés.

## 1.0.37 — 2026-06-09

### Index : annulation propre en base des diffs interrompus

**Bug** : quand un `borg diff` en cours était tué (`ps.kill()`), `communicate()` retournait quand même (returncode=-9), entries=[], et la paire était insérée dans `diff_indexed_pairs` avec 0 entrées — marquée "indexée" à tort, impossible à reprendre.

**Fix** : `_run_diff` retourne maintenant un flag `ok = returncode in (0,1)`. En Phase 3, les paires `ok=False` déclenchent une purge (`diff_index`, `diff_indexed_pairs`, `diff_excluded_stats`) au lieu d'un insert. Elles seront réindexées au prochain lancement.

## 1.0.36 — 2026-06-09

### Colonne `modifications` unifiée résumé + détail — suffixes `%nb` / `%B`

Colonne `modifications` étendue au détail par archive (remplace `fichiers` + `espace`). Même formule partout. Format : `"3%nb / 8%B"` — `%nb` pour le pourcentage fichiers, `%B` pour le pourcentage espace disque.

## 1.0.35 — 2026-06-09

### Résumé : colonne `modifications` (fichiers + espace)

Remplace les colonnes `fichiers`/`espace` du résumé par une seule colonne `modifications` affichant `"XX% / YY%"`.

Formule : dénominateur = état précédent (`inchangés + modifiés + supprimés`), numérateur = `modifiés + supprimés`. Première valeur = pourcentage fichiers, seconde = pourcentage espace disque.

Le détail par archive conserve `fichiers` et `espace` inchangés.

## 1.0.34 — 2026-06-09

### Erreurs SQLite : nom de fichier inclus dans le message

Tous les `printer()` et `raise Exception()` sur erreur SQLite affichent maintenant `({db_path})` en plus du message d'erreur. Plus besoin de deviner quelle base est en cause (ex. `database or disk is full`).

## 1.0.33 — 2026-06-08

### `Report` : fix `—` sur archives indexées sans changements visibles

**Bug** : quand tous les changements entre deux archives sont filtrés par `IDX_EXCLUDE`, `diff_index` reste vide pour cette paire mais `diff_indexed_pairs` la marque quand même comme indexée. Au report suivant, `_diff_stats_for_nick` ne trouvait rien dans `diff_index` → `None` → `—`.

**Fix** : `_diff_stats_for_nick` initialise maintenant un stat-zéro pour toutes les archives présentes dans `diff_indexed_pairs` avant de les surcharger avec les valeurs réelles de `diff_index`. Les archives indexées sans changements visibles affichent désormais `Pre(N/100%)+Add(0/0%)-Supp(0/0%)`.

## 1.0.32 — 2026-06-08

### `boex` : purge `_MEI*` PyInstaller sur Ctrl+C

Même nettoyage que 1.0.31 : après `ps.kill()/wait()` sur `KeyboardInterrupt` dans `boex`, les répertoires `/tmp/_MEI*` orphelins sont supprimés (via `fuser`).

## 1.0.31 — 2026-06-08

### `Index` : nettoyage des répertoires PyInstaller orphelins après SIGKILL

Quand `Bkp`/`Restore` interrompt un `Index` en cours via SIGKILL, les répertoires `/tmp/_MEI*` créés par borg (binaire PyInstaller) ne sont pas nettoyés. Le moniteur de priorité purge désormais ces répertoires orphelins après avoir attendu que les processus tués soient reap'd, en vérifiant via `fuser` qu'aucun process actif ne les utilise encore.

## 1.0.30 — 2026-06-08

### `Report -o` : colonne `taille` alimentée depuis `repo_stats`

`borg create --json` retourne `cache.stats.unique_csize` (taille dédupliquée du dépôt entier). Ce champ est désormais persisté dans une nouvelle table `repo_stats` après chaque `Bkp` réussi, et utilisé par `Report -o`.

**Nouvelle table `diff.db`** :
```sql
repo_stats (nick PK, unique_csize, total_size, total_csize, updated_at)
```

Nouveaux méthodes `BorgHelperDB` : `store_repo_stats()`, `get_repo_stats()`.

Limite : `repo_stats` n'est mis à jour qu'après `Bkp` (pas après `Prune` — `borg prune` sans `--json` ne retourne pas les stats structurées).

## 1.0.29 — 2026-06-08

### `Report -o` : colonne `reste` désormais alimentée

En mode offline (`-o`), la colonne `reste` (espace disque disponible sur le dépôt) était toujours `None`. Elle appelle maintenant `dfRepo` (simple `df` local) — disponible tant que le système de fichiers est accessible, même sans connexion borg.

Pas d'effet sur les dépôts distants (SSH) : `dfRepo` retourne `None` si `BORG_REPO` contient `:`.

## 1.0.28 — 2026-06-08

### `Report` : résumé — format `Chg(X%) Supp(Y%)`

Le tableau résumé par hôte remplace `Pre()+Add()-Supp()` par deux indicateurs orthogonaux :

| Colonne | Formule |
|---------|---------|
| `fichiers` | `Chg((added+modified)/nfiles_new) Supp(removed/nfiles_prev)` |
| `espace`   | `Chg((added_sz+modified_sz)/total_sz) Supp(removed_sz/prev_sz)` |

Avec `nfiles_prev = nfiles_new − added + removed` et `prev_sz = total_sz − added_sz + removed_sz`.

`Chg` et `Supp` ont des dénominateurs distincts et cohérents — pas de problème de somme > 100%.

## 1.0.27 — 2026-06-08

### `IdxTop` : inchangés par archive

Section `Inchangés par archive` ajoutée avant le tableau, listant pour chaque archive indexée :

```
Inchangés par archive :
  archive-2024-01-01 : 95 000 (97%) / 98 000 fichiers
  archive-2024-01-02 : 96 200 (96%) / 100 000 fichiers
```

Calcul : `nfiles` (depuis `archive_stats`) − added_total − modified_total (indexés + exclus). Seules les archives présentes dans `archive_stats` et `diff_index` sont affichées.

## 1.0.26 — 2026-06-08

### `DiffTop` : fichiers inchangés calculés depuis les index

Ligne `Inchangés` ajoutée après les exclusions :

```
Indexés  : 3 200 changements · 450 MB
Exclus   :   800 entrées · 1.2 GB (IDX_EXCLUDE) — +300 · -50 · =450
Inchangés: 96 000 (97%) sur 99 500 fichiers dans archive-new
```

Calcul : `nfiles_new` (depuis `archive_stats`) − added_total − modified_total, où les totaux incluent indexés et exclus. Ligne omise si `archive_stats` ne contient pas `nfiles` pour l'archive cible.

## 1.0.25 — 2026-06-08

### `IdxTop` / `DiffTop` : détail +/-/= des exclus sur une ligne

La ligne `Exclus` affiche désormais le détail par type de changement :

```
Exclus  : 18 200 entrées · 3.4 GB (IDX_EXCLUDE) — +5 000 · -200 · =13 000
```

Seuls les types présents sont affichés. Note : les fichiers **inchangés** ne peuvent pas être comptés car `borg diff` ne les liste pas.

## 1.0.24 — 2026-06-08

### `IdxTop` / `DiffTop` / `Index` : affichage des entrées non indexées

Les fichiers exclus par `IDX_EXCLUDE` (stockés dans `diff_excluded_stats`) sont désormais visibles :

- **`IdxTop`** — ligne `Exclus : N · taille (IDX_EXCLUDE)` après le total indexé (toutes paires confondues)
- **`DiffTop`** — idem pour la paire spécifique affichée
- **`Index` résumé final** — `, N exclus` ajouté au bilan de paires indexées

La ligne Exclus est omise si aucun fichier n'a été filtré.

## 1.0.23 — 2026-06-07

### `Report` : résumé % seuls, détail valeur+%

Affichage différencié entre résumé (tableau par hôte) et détail (tableau par archive) :

| Contexte | `fichiers` | `espace` |
|----------|-----------|---------|
| Résumé | `Pre(80%)+Add(8%)-Supp(3%)` | `Pre(85%)+Add(12%)-Supp(2%)` |
| Détail | `Pre(800/80%)+Add(80/8%)-Supp(30/3%)` | `Pre(8.5 GB/85%)+Add(1.2 GB/12%)-Supp(200 MB/2%)` |

## 1.0.22 — 2026-06-07

### `Report` : colonnes fichiers/espace au format `Pre()+Add()-Supp()`

Les trois colonnes `+ajouté`, `-supprimé`, `=présent` remplacées par deux colonnes :

- `fichiers` : `Pre(80%)+Add(8%)-Supp(3%)` — pourcentages relatifs à l'archive courante
- `espace`   : `Pre(8.5 GB)+Add(1.2 GB)-Supp(200 MB)` — tailles réelles

Format identique en résumé et en détail par archive.

## 1.0.21 — 2026-06-07

### `Report` : résumé en pourcentages seuls

Dans le tableau résumé par hôte, les colonnes `+ajouté`, `-supprimé`, `=présent` affichaient le même format verbeux que le détail par archive (`15 (8%) · 1.2 GB (12%)`).

Format résumé : `8% · 12%` — pourcentage fichiers · pourcentage taille, sans les valeurs absolues.  
Le détail par archive conserve le format complet `N (P%) · SIZE (Q%)`.

## 1.0.20 — 2026-06-07

### `Report` : pourcentages cohérents — base unique = archive courante

Les colonnes `+ajouté`, `-supprimé`, `=présent` affichaient deux bases différentes :
- comptages (fichiers) → base = archive précédente
- tailles (octets)     → base = archive courante

Les deux utilisent maintenant la même base : **l'archive courante** (`nfiles` / `original_size`).

Lecture uniforme : "X% des fichiers de ce backup sont nouveaux / supprimés / inchangés".  
`ajouté% + présent% ≈ 100%` (les fichiers modifiés sont comptés dans `=présent`).

## 1.0.19 — 2026-06-07

### `DiffTop` : top N arborescences par changements sur une paire d'archives

Nouveau diagnostic ciblé sur un diff précis (par défaut : la dernière paire indexée).

```bash
borgHelper -c DiffTop -n mon-serveur          # top 10, profondeur 3, dernière paire
borgHelper -c DiffTop -n mon-serveur -N 5     # top 5
borgHelper -c DiffTop -n mon-serveur -p 4     # profondeur 4
borgHelper -c DiffTop -n mon-serveur -b archive-old,archive-new  # paire explicite
```

Colonnes : `total (nb+%)`, `+nb`, `+taille`, `-nb`, `-taille`, `=nb`, `taille`.  
Tri par total. Source : `diff_index` — aucun appel borg.

## 1.0.18 — 2026-06-07

### `IdxTop` : fix regroupement des chemins sans `/` initial

`get_prefix` ignorait la profondeur pour les chemins sans `/` initial (borg peut produire des chemins relatifs) — chaque fichier formait sa propre clé au lieu d'être regroupé. Corrigé : les chemins relatifs sont maintenant tronqués à la même profondeur que les chemins absolus.

`IdxTop` est trié par nombre d'entrées (colonne `entrées`), pas par poids.

## 1.0.17 — 2026-06-07

### `IdxPurge` : `VACUUM INTO` pour éviter l'erreur "database or disk is full"

`VACUUM` (et `PRAGMA incremental_vacuum` sur les DB en mode `auto_vacuum=NONE`) écrit son fichier temporaire dans `/tmp`, qui peut être sur une partition séparée et saturée — même si le filesystem du `diff.db` a de l'espace disponible.

`VACUUM INTO 'chemin.tmp'` crée la copie compacte dans le **même répertoire** que le `diff.db`, utilisant l'espace libre du bon filesystem. Suivi d'un `os.replace` atomique.

Si le compactage échoue malgré tout (disque vraiment plein), les entrées sont quand même supprimées et borgHelper affiche la commande manuelle à relancer quand de l'espace sera libéré :

```
[WARN] compactage impossible (...) — entrées supprimées mais espace non récupéré
[WARN] relancer manuellement : sqlite3 'diff.db' "VACUUM INTO 'diff.db.tmp'" && mv 'diff.db.tmp' 'diff.db'
```

## 1.0.16 — 2026-06-07

### `IdxPurge` : `PRAGMA incremental_vacuum` au lieu de `VACUUM`

`VACUUM` crée une copie complète du fichier avant de remplacer l'original — sur un `diff.db` de plusieurs GB, cela nécessite autant d'espace libre que la taille du fichier, et échoue avec `database or disk is full` si le disque est serré.

Remplacé par `PRAGMA incremental_vacuum` : reclaime les pages libérées en tronquant le fichier depuis la fin, sans aucune copie. Possible car `diff.db` a `PRAGMA auto_vacuum=INCREMENTAL` depuis l'origine.

L'espace est récupéré immédiatement et proportionnellement aux entrées supprimées, sans risque de remplir le disque.

## 1.0.15 — 2026-06-07

### `IdxPurge` sans `-x` : purge selon IDX_EXCLUDE/IDX_INCLUDE du borghelperrc

Sans l'option `-x`, `IdxPurge` lit directement les filtres `IDX_EXCLUDE` et `IDX_INCLUDE` de la configuration du nick et purge tout ce que ces filtres auraient exclu à l'indexation.

```bash
# Après avoir modifié IDX_EXCLUDE dans borghelperrc :
borgHelper -c IdxPurge -n mon-serveur -D   # dry-run — voir le volume
borgHelper -c IdxPurge -n mon-serveur      # purger selon la config
```

- Affiche les patterns lus depuis la config avant d'agir
- Logique identique à `_idx_path_ok` : IDX_INCLUDE whitelist d'abord, IDX_EXCLUDE blacklist ensuite
- La condition SQL est construite dynamiquement à partir des patterns (GLOB ou LIKE selon présence de `*?[`)
- `-x` reste disponible pour un pattern explicite ponctuel (comportement 1.0.14 inchangé)

## 1.0.14 — 2026-06-07

### `IdxTop` et `IdxPurge` — diagnostic et nettoyage rétroactif du diff.db

Deux nouvelles commandes pour gérer les `diff.db` devenus trop volumineux (accumulation d'entrées sur des arborescences très actives comme `/var/lib/docker`, caches, artefacts de compilation).

#### `IdxTop` — diagnostic des gros contributeurs

```bash
borgHelper -c IdxTop -n mon-serveur
borgHelper -c IdxTop -n mon-serveur -N 30 -p 4   # top 30, profondeur 4
```

- Stream de `diff_index` par batch (50 000 lignes), regroupement par préfixe en Python
- Affiche les N arborescences avec le plus d'entrées : chemin, nb entrées, taille cumulée, % du total
- Configurable : `-N` (nb résultats, défaut 20) · `-p` (profondeur répertoire, défaut 3)
- Résultat typique : identifie en quelques secondes quelle arbo représente 35 % des entrées

#### `IdxPurge` — purge rétroactive + VACUUM

```bash
borgHelper -c IdxPurge -n mon-serveur -x /var/lib/docker -D   # dry-run
borgHelper -c IdxPurge -n mon-serveur -x /var/lib/docker       # purge réelle
borgHelper -c IdxPurge -n mon-serveur -x '*.pyc'               # glob
borgHelper -c IdxPurge -n mon-serveur -x '/home/*/.cache/*'    # glob (* matche /)
```

- Préfixe plain : supprime toutes les entrées dont le chemin vaut exactement le préfixe ou commence par `préfixe/`
- Glob : utilise SQLite `GLOB` (`*` matche tout y compris `/`)
- Après suppression : recalcule `diff_indexed_pairs.entry_count` + `VACUUM` pour récupérer l'espace immédiatement
- `-D` : dry-run — affiche le volume concerné sans rien modifier

#### Workflow recommandé

```
borgHelper -c IdxTop -n mon-serveur          # identifier les arbo volumineuses
  → ajouter les arbo à IDX_EXCLUDE dans le borghelperrc
borgHelper -c IdxPurge -n mon-serveur -D -x /var/lib/docker  # vérifier
borgHelper -c IdxPurge -n mon-serveur -x /var/lib/docker     # purger
  → diff.db : 6 GB → quelques centaines de MB
```

**Patterns depth-independent :** `*` matche `/`, donc `*/.git/*` purge tous les fichiers dans n'importe quel `.git/` quelle que soit la profondeur :

```bash
borgHelper -c IdxPurge -n mon-serveur -x '*/.git/*'
borgHelper -c IdxPurge -n mon-serveur -x '*/node_modules/*'
borgHelper -c IdxPurge -n mon-serveur -x '*/__pycache__/*'
```

Même syntaxe dans `IDX_EXCLUDE` pour le futur :

```ini
IDX_EXCLUDE = */.git/* */.git
    */node_modules/* */__pycache__/*
```

## 1.0.13 — 2026-06-06

### Index : attente automatique si SQLite verrouillé

- Lors de l'indexation, si la base `diff.db` est verrouillée par un backup ou une restauration en cours sur le même dépôt, borgHelper attend automatiquement le déverrouillage au lieu d'échouer immédiatement
- Affiche `SQLite verrouillé — attente déverrouillage (max 300s)...` au premier blocage, puis retente toutes les 2 s jusqu'à 300 s
- Concerne toutes les opérations d'écriture d'indexation : `store_diff_entries`, `store_archive_stats`, `store_archive_snapshot`, `_diff_keep_purge`, `store_excluded_diff_stats`, `store_excluded_snap_stats`
- Implémenté via `_with_lock_retry(fn, max_wait=300)` dans `BorgHelperDB` — chaque méthode d'écriture ferme proprement sa connexion entre deux tentatives (pas de fuite de connexion)

## 1.0.12 — 2026-06-06

### Report `-o` : même résumé que Report, toutes machines affichées

- `report_offline` (`-o`) produit désormais le même tableau résumé que `report` : colonnes `nom`, `duree`, `depuis`, `derniere`, `taille`, `recuperable`, `reste`, `+ajouté`, `-supprimé`, `=présent` + ligne `Totaux`
- Les nicks sans index (`diff.db` absent ou `archive_stats` vide) sont affichés avec `—` au lieu d'être silencieusement ignorés — le rapport est exhaustif même pour les machines non encore indexées
- Réécrit pour utiliser `prep_report_from_db()` (partagé avec le fallback offline de `report`) + même code de rendu que `report()`
- Les champs borg-only (`taille`/unique_csize, `récupérable`, `reste`) restent vides puisqu'il n'y a aucun appel borg

## 1.0.11 — 2026-06-06

### Report : fallback base uniquement si dépôt occupé

- Si `Report` est lancé pendant un `Bkp`, `Restore` ou `Index` sur le même dépôt, borgHelper détecte le lock actif (`priority.lock` ou `index-running.lock`) et lit les données depuis la base SQLite (`archive_stats` + `diff_index`) au lieu d'appeler borg
- Affiche un message : `dépôt occupé (Bkp/Index en cours) — rapport depuis la base uniquement`
- Les champs borg-only (`taille`/unique_csize, `récupérable`/prune, `reste`/df) apparaissent vides — les autres champs (archives, tailles, diffs, durées) sont complets depuis l'index
- Compatible multi-nick : chaque nick est évalué indépendamment (mixte online/offline possible)
- Nouveau : `BorgHelperDB.check_index_running(nick)` — symétrique de `check_priority_lock`
- Nouveau : `BorgHelper.prep_report_from_db(nick, maxp)` — construit `(tcmpl, tbkps)` depuis SQLite uniquement

## 1.0.10 — 2026-06-06

### Index : SIGKILL + `borg break-lock` — arrêt garanti sans stale locks

**Problème 1.0.9 :** SIGINT demande à borg de faire son cleanup, mais ce cleanup lui-même se bloque (I/O sur FUSE, ou opération interne en attente). `ps.communicate()` attend que le process meure → tout le threadpool hang → `wait_index_idle` timeout 120s → `borg create` voit encore les locks → échec.

**Solution :**

1. **SIGKILL** (`ps.kill()`) → mort instantanée, aucun cleanup, aucune chance de bloquer
2. **Poll `running_procs`** jusqu'à vide (deadline 15 s) → les threads `_run_diff` ont exécuté `ps.communicate()` qui reap les zombies ; les PIDs ne sont plus dans la table de processus
3. **`borg break-lock <BORG_REPO>`** → borg liste ses lock files, trouve les PIDs morts → les supprime → dépôt déverrouillé
4. `clear_index_running_lock` → `wait_index_idle` retourne → `borg create` démarre sans conflit

**Pourquoi le poll PIDs avant break-lock ?** Tant qu'un process est zombie (tué mais non reap), `os.kill(pid, 0)` retourne 0 — borg croit le lock légitime et ne le supprime pas. Le poll garantit que `ps.communicate()` (appel à `waitpid`) a reapé tous les zombies avant break-lock.

- Import `signal` supprimé (inutile)
- `ps.send_signal(signal.SIGINT)` → `ps.kill()` + poll `running_procs` + `borg break-lock`

## 1.0.9 — 2026-06-06

### Index : SIGINT au lieu de SIGTERM — libération propre des locks borg

**Problème :** `ps.terminate()` envoie SIGTERM au processus `borg diff`. Sous Python, SIGTERM appelle `_exit()` au niveau C — les blocs `finally` et les `__exit__` de context managers ne s'exécutent **pas**. Borg stocke ses locks dans des fichiers applicatifs (pas des OS file locks) via des context managers `with Lock(...):`. Avec SIGTERM, ces locks ne sont jamais libérés. Résultat : `borg create` voit des stale lock files et timeout.

**Solution :** `ps.send_signal(signal.SIGINT)` à la place de `ps.terminate()`.  
SIGINT (KeyboardInterrupt en Python) est intercepté par l'interpréteur Python, qui lève `KeyboardInterrupt` dans le thread courant. Cette exception remonte normalement à travers la pile : les blocs `finally` s'exécutent, les `with Lock():` appellent leur `__exit__` → borg supprime ses fichiers de lock → `borg create` trouve le dépôt libre.

- Ajout de `signal` aux imports
- `ps.terminate()` → `ps.send_signal(signal.SIGINT)` dans `_priority_monitor`

## 1.0.8 — 2026-06-06

### Index : thread moniteur priority lock — arrêt sans attendre la fin d'un diff

**Problème :** En 1.0.7, le check priority lock était dans la boucle `as_completed`. Si tous les workers `IDX_WORKERS` étaient bloqués dans `ps.communicate()`, aucun future ne complétait → `as_completed` ne progressait pas → `terminate()` non appelé → `Bkp` attendait jusqu'à 120 s.

**Solution — thread moniteur dédié :**
- Un thread daemon `_priority_monitor` démarre dès la soumission des futures, poll le priority lock toutes les 0.5 s
- Dès détection : `interrupted_event.set()`, `cancel()` sur les futures en attente, `ps.terminate()` sur tous les `Popen` actifs via `running_procs`
- Indépendant du rythme de `as_completed` — réagit dans les 0.5 s quelle que soit la charge
- Thread arrêté proprement (`interrupted_event.set()` dans `finally`, `monitor.join(timeout=2)`)
- `interrupted` booléen remplacé par `interrupted_event.is_set()` pour cohérence

**Délai d'interruption :** ≤ 0.5 s après pose du priority lock par `Bkp`

## 1.0.7 — 2026-06-06

### Index : arrêt immédiat des `borg diff` actifs sur priority lock

- `_run_diff` gère désormais son propre `subprocess.Popen` (au lieu de `boex`) pour conserver la référence au processus
- Dict thread-safe `running_procs` stocke les `Popen` actifs pendant Phase 2
- Quand le priority lock est détecté dans la boucle `as_completed` :
  - futures en attente → `cancel()`
  - processus `borg diff` en cours → `ps.terminate()` (SIGTERM)
  - `ps.communicate()` retourne immédiatement → running lock libéré → `Bkp` débloqué en quelques secondes
- Avant : `Bkp` attendait la fin naturelle de chaque diff (potentiellement plusieurs minutes)
- Après : arrêt en quelques secondes, quelle que soit la taille des archives

## 1.0.6 — 2026-06-06

### Bkp/Restore : attente réelle de la fin des `borg diff` actifs

**Problème :** `Bkp` posait le priority lock et appelait `borg create` immédiatement. Si des `borg diff` étaient encore en cours (IDX_WORKERS threads), borg ne pouvait pas acquérir le verrou exclusif → `Failed to create/acquire the lock … (timeout)`.

**Solution — `index-running` lock :**
- `Index` pose un lock `<cache>/<prefix>-<repo>-index-running.lock` (PID) au début de Phase 2 (avant le ThreadPoolExecutor), le supprime dans un `finally` après la fin de tous les diffs
- `Bkp`/`Restore` appellent `wait_index_idle(nick)` après `set_priority_lock` : attend jusqu'à 120 s que le running lock disparaisse (polling 1 s), puis lance `borg create`/`borg extract`
- Lock périmé (PID mort) → supprimé automatiquement, pas de blocage
- Séquence complète :
  1. `Bkp` set priority lock → `Index` détecte, annule les futures en attente
  2. `Bkp` attend running lock → les diffs en cours terminent, running lock supprimé
  3. `Bkp` lance `borg create` sans conflit de verrou borg

**Nouvelles méthodes `BorgHelperDB` :** `_index_running_lock_path`, `set_index_running_lock`, `clear_index_running_lock`, `wait_index_idle`

## 1.0.5 — 2026-06-06

### Priority lock par BORG_REPO (inter-nicks)

- Correction : le lock prioritaire est maintenant keyed sur `BORG_REPO` (sanitisé) plutôt que sur le nick
- Si plusieurs nicks pointent le même dépôt borg, `Bkp` sur `nick-A` interrompt `Index` sur `nick-B`, `nick-C`, etc. (même `BORG_REPO`)
- Nicks sur des dépôts différents → locks différents → aucune interférence
- Fallback sur le nick si `BORG_REPO` non disponible (comportement inchangé pour usage standalone)

## 1.0.4 — 2026-06-06

### BORG_EXE : chemin borg configurable

- Nouvelle clé de configuration `BORG_EXE` par section (ou `[DEFAULT]`)
- Spécifie le chemin complet vers l'exécutable borg (ex : `/usr/local/bin/borg1`, `/opt/borg/bin/borg`)
- Si absent : utilise `borg` depuis le `PATH` (comportement inchangé)
- Utile si plusieurs versions de borg coexistent ou si borg n'est pas dans le PATH standard

## 1.0.3 — 2026-06-06

### DiffBkp : affichage ligne par ligne depuis l'index

- Affichage un fichier par ligne : `+ chemin`, `- chemin`, `= chemin`
  - `+` = ajouté, `-` = supprimé, `=` = modifié/permissions/type (présent dans les deux archives)
- Taille affichée en fin de ligne : taille finale pour `+`, initiale pour `-`, `avant → après` pour `=`
- Types non-`modified` (`C`, `B`, `T`) affichent le code entre crochets si pas de taille (`[C]`, `[B]`, `[T]`)
- Tri alphabétique par chemin (toutes entrées mélangées, symbol différencie)
- Ligne résumé `+ N  - N  = N` à la fin
- Source : index SQLite si la paire est indexée, sinon `borg diff` + stockage automatique (comportement inchangé)
- Suppression de la `PrettyTable` pour ce résultat

## 1.0.2 — 2026-06-06

### Priorité Bkp/Restore sur Index

**Problème :** `Index` parallèle (`IDX_WORKERS` workers `borg diff`) peut bloquer le démarrage d'un `Bkp` ou ralentir une restauration par contention sur le dépôt borg.

**Solution — lock PID :**
- `Bkp` et `Restore` posent un lock fichier (`<cache>/<prefix>-<nick>-priority.lock`, contient le PID) avant tout appel `borg`, et le retirent dans un `finally` (garanti même sur `sys.exit()`/exception)
- `Index` vérifie le lock après chaque `borg diff` complété (dans la boucle `as_completed`)
  - Si lock actif (PID vivant) → annule les futures en attente, termine proprement les diffs déjà lancés
  - Affiche le nombre de paires non indexées et la commande pour reprendre
- Lock périmé (PID mort) → supprimé automatiquement, pas de blocage
- Reprise transparente : `diff_indexed_pairs` est incrémental, les paires déjà indexées sont ignorées au prochain `Index`

**Nouvelles méthodes `BorgHelperDB` :** `set_priority_lock`, `clear_priority_lock`, `check_priority_lock`, `_priority_lock_path`

## 1.0.1 — 2026-06-06

### IDX_INCLUDE / IDX_EXCLUDE : glob complet + stats fichiers exclus

**Patterns glob dans les filtres d'indexation :**
- `_idx_path_ok` distingue maintenant explicitement patron glob (contient `*`, `?`, `[`) vs préfixe plain
- Glob → `fnmatch` : `*` matche n'importe quelle séquence y compris `/`
  - `*.bak` → filtre tous les fichiers `.bak` quel que soit le répertoire
  - `/home/*/.bash_history` → filtre tous les `.bash_history` dans toute arborescence sous `/home/`
- Préfixe plain → `startswith` (comportement inchangé)

**Stats des fichiers exclus (nouvelles tables diff.db) :**
- `diff_excluded_stats` — agrégat par paire (archive_old, archive_new) et change_type : `file_count`, `total_size`
- `snap_excluded_stats` — agrégat par archive snapshot : `file_count`, `total_size`
- Compteurs accumulés en RAM pendant chaque `borg diff` / listing snapshot, écrits en lot en fin de paire
- Peuplés par `Index`, `IndexSnap (-S)` et `Bkp` (taille non disponible pour Bkp car `--list` ne donne pas les tailles)
- Nettoyés automatiquement lors du Prune (archives supprimées) et lors du force-reindex (`-F`)
- Nouvelles méthodes `BorgHelperDB` : `store_excluded_diff_stats`, `store_excluded_snap_stats`

## 1.0.0 — 2026-06-06

### Documentation : découpage en 3 fichiers

- `README.md` — présentation, installation, config, toutes les commandes CLI, crontab, codes retour
- `TECHNICAL.md` *(nouveau)* — architecture interne, schémas ERD cache.db + diff.db, indexes, flux d'indexation, gestion taille, migration schéma, Sentry
- `LIBRARY.md` *(nouveau)* — usage des classes avec exemples complets (backup, report, search, requêtes SQL directes, script de supervision, référence méthodes)

### Refactoring : architecture 3 classes, importable comme librairie

- `BorgHelperDB` : toutes les opérations SQLite (cache.db + diff.db)
- `BorgRunner` : subprocess borg + lecture/écriture borghelperrc
- `BorgHelper` : services haut niveau, combine DB + Borg

API librairie :
```python
from borgHelper import BorgHelper
bh = BorgHelper('/path/to/.borghelperrc')
bh.backup('myserver')
bh.index('myserver')
bh.report('myserver')
```

- `if __name__ == '__main__': _cli_main()` — importable sans effets de bord
- Comportement CLI identique (optab, dispatch, exit codes inchangés)
- Méthodes publiques : `backup`, `prune`, `index`, `indexsnap`, `report`, `report_offline`, `search`, `filehist`, `duidx`, `diffbkp`, `restore`, `stats`, `key`, `mount`, `umount`, `cache_info`, `cache_clean`, etc.
- 1999 lignes (−1060 vs 0.69 : suppression inline changelog, dead code, legacy functions)
- `borgHelper.py` : symlink vers `borgHelper` — import direct `from borgHelper import BorgHelper`
- README : section usage librairie + version `v1.0.0` en en-tête

## 0.69 — 2026-06-06

### Erreurs SQLite : messages explicites

- Ajout helper `_db_connect(db_path)` : capture `OperationalError` à l'ouverture et affiche un message ciblé selon la cause :
  - répertoire parent inexistant → nom du répertoire manquant
  - permission refusée sur le répertoire → chemin concerné
  - fichier existant non lisible/inscriptible → nom du fichier
  - autre cause → message brut SQLite + chemin
- `ensure_diff_db` : ajout `try/except DatabaseError` → message de corruption avec nom du fichier + instruction de suppression
- `ensure_cache_db` : même traitement

Avant : traceback Python brut sans indication du fichier.  
Après : message d'erreur actionnable avec chemin précis et cause.

## 0.68 — 2026-06-06

### Performance — `diff.db` : réduction taille et fragmentation

- **`VACUUM` après Prune** : espace des lignes supprimées récupéré immédiatement après nettoyage
- **`PRAGMA auto_vacuum=INCREMENTAL`** : récupération incrémentale des pages vides au fil du temps
- **`DIFF_KEEP = N`** dans borghelperrc : purge automatique des N+1 paires les plus anciennes de `diff_index` après chaque `Index`

```ini
DIFF_KEEP = 30   # conserver les 30 dernières paires indexées seulement
```

---

## 0.67 — 2026-06-06

### Fix — CLI : arguments positionnels non reconnus rejetés

- `borgHelper -c bkp toto` : `toto` était silencieusement ignoré, le backup tournait avec `nick = hostname`
- Désormais : erreur explicite `"Argument(s) non reconnu(s) : toto"` + rappel d'utiliser `-n <nick>`

---

## 0.66 — 2026-06-05

### Performance — `Index` : `borg diff` parallèle + insert groupé

- **Phase 1** : détermination des paires à indexer + purge groupée en une seule transaction SQLite (si `-F`)
- **Phase 2** : appels `borg diff` en parallèle via `ThreadPoolExecutor` — `borg diff` est read-only (lock partagé)
- **Phase 3** : insert groupé en une seule connexion SQLite avec commit unique
- `IDX_WORKERS` dans borghelperrc : nombre de workers parallèles (défaut : 4)

```ini
IDX_WORKERS = 8   # pour dépôts distants rapides
IDX_WORKERS = 1   # pour forcer le séquentiel
```

---

## 0.65 — 2026-06-05

### Fix — `Index` : `borg info` pour `archive_stats` uniquement si archives manquantes

- Régression 0.64 : `borg info --json --glob-archives` appelé à chaque `Index` même si `archive_stats` était complet
- Désormais : comparaison entre les archives connues de borg et celles présentes dans `archive_stats`
- `borg info` n'est appelé que si au moins une archive manque (ou `-F` forcé)

---

## 0.64 — 2026-06-05

### Ajout — `archive_stats` dans `diff.db` : tailles d'archives persistées localement

- Nouvelle table `archive_stats(nick, archive, archive_date, duration, original_size, compressed_size, deduplicated_size, nfiles)`
- Peuplée par `Bkp` : stats issues de `borg create --json` (archive juste créée)
- Peuplée par `Index` : appel `borg info --json --glob-archives` en fin d'indexation (toutes les archives)
- Nettoyée par `Prune` : `_cleanup_index_after_prune` supprime les archives prunées
- `Report -o` : colonnes `taille` et `nfiles` disponibles sans appel borg si `archive_stats` est peuplée

---

## 0.63 — 2026-06-05

### Ajout — `Report -o` : mode offline stats-only depuis diff.db

- `-o` : rapport sans aucun appel borg — lit uniquement `diff.db`
- Colonnes : dernière archive, date, +ajouté, -supprimé, =modifié (avec tailles)
- Combinable avec `-j` (JSON), `-l` (HTML), `-N <n>` (limite archives)
- Erreur explicite si `diff.db` absent ou index vide

---

## 0.62 — 2026-06-05

### Correction — `Bkp` : `borgHelper_messages` retiré du stdout

- La sortie stderr (messages `[INFO]`/`[WARNING]`) reste dans stderr — elle n'est plus copiée dans stdout
- `borgHelper_file_counts` et `borgHelper_files` (debug) restent dans le JSON stdout si exit 0

---

## 0.61 — 2026-06-05

### Changement — `Report` : `-N <n>` remplace `-b <n>` pour surcharger `DISPLAY_BKP`

- `-b` retiré de `Report` (sémantique ambiguë — dans les autres commandes `-b` = nom d'archive)
- `-N <n>` : affiche les `n` dernières archives, surcharge `DISPLAY_BKP` de la conf
- Les deux niveaux de filtrage (`prep_report` et `filtrer_lignes`) sont maintenant cohérents

---

## 0.60 — 2026-06-05

### Fix — `Report` : `filtrer_lignes` respecte maintenant `maxp`

- `filtrer_lignes` ignorait `maxp` et utilisait toujours `DISPLAY_BKP` de la conf
- Corrigé en préparation du remplacement `-b` → `-N`

---

## doc — 2026-06-05

### Documentation — README et aide intégrée mis à jour

- Schéma relationnel Mermaid ERD : `cache.db`, `diff.db` + table `archive_stats`
- `Bkp` : exemples JSON stdout (`borgHelper_file_counts`, `borgHelper_files` debug), exit codes
- `Prune` : mention purge diff.db + `archive_stats` après suppression d'archives
- `Report` : `-N n` (remplace `-b`), `-o` mode offline + description colonnes
- `Index` : `-F`, `-S`, `IDX_WORKERS` parallélisme
- `IndexSnap` retiré — remplacé par `Index -S` dans aide et README
- Usage inline (`-H`) : toutes les commandes mises à jour (Report, Bkp, Prune, Index, Init)

---

## 0.59 — 2026-06-05

### Changement — `Index -S` remplace la commande `IndexSnap`

- Nouvelle option `-S` sur `Index` : exécute uniquement le snapshot (équivalent à l'ancienne commande `IndexSnap`)
- `-S -F` : force le recalcul du snapshot seul
- `IndexSnap` retiré du dispatch CLI (la fonction interne `cmd_indexsnap` reste utilisée par `Index` et `Bkp`)

---

## 0.58 — 2026-06-05

### Ajout — `Bkp` : stdout JSON enrichi si exit 0

- `borgHelper_messages` : liste des messages stderr filtrés (`[LEVEL] msg`), hors entrées fichiers
- `borgHelper_file_counts` : dict `{change_type: count}` — nombre de fichiers par type (added, removed, modified…)
- En mode debug (`-d`) : `borgHelper_files` — liste complète des entrées fichiers (chemin + type)
- Le stderr interactif (`[LEVEL] msg`) reste inchangé
- `newretC` calculé avant les prints pour cohérence

---

## 0.57 — 2026-06-05

### Changement — `Report` : suppression de la réindexation automatique

- Le bloc auto-repair de `prep_report` (réindexation à la volée des paires manquantes) est supprimé
- Si une paire n'est pas indexée, les stats affichent `—` sans déclencher `borg diff`
- Pour indexer, utiliser explicitement `borgHelper -c Index -n <nick>`

---

## 0.56 — 2026-06-05

### Refactor — DB : déduplication de contenu, WAL, indexes couvrants

**Schéma `diff.db` — déduplication `archive_snapshot`**

- Nouvelle table `snapshot_file(id, nick, path, size, mtime)` — états de fichiers uniques, `UNIQUE(nick, path)`
- `archive_snapshot` devient une table mince `(nick, archive, archive_date, file_id)` — référence par id
- Vue `archive_snapshot_v` — jointure transparente pour toutes les lectures (Search, FileHist, DuIdx, Restore)
- `store_archive_snapshot` : `INSERT OR REPLACE INTO snapshot_file` puis `INSERT … SELECT id` — plus de duplication de paths
- Migration automatique au premier lancement : `ensure_diff_db` détecte l'ancienne colonne `path` et migre sans intervention
- `_cleanup_snapshot_file_orphans` : supprime les `snapshot_file` orphelins après prune ou force re-index

**Indexes ajoutés**

- `diff_index` : `idx_diff_nick_newtype(nick, archive_new, change_type)` — accélère `_diff_stats_for_nick`
- `diff_index` : `idx_diff_nick_date(nick, archive_new_date)` — accélère les filtres par plage de dates
- `diff_indexed_pairs` : `idx_pairs_nick(nick)` — accélère les suppressions par nick lors du prune
- `snapshot_file` : `idx_snapfile_nick_path(nick, path)` — lookup O(log n) pour l'insertion et la recherche
- `archive_snapshot` : `idx_snap_nick_archive(nick, archive)` — accélère les suppressions par archive

**WAL mode**

- `PRAGMA journal_mode=WAL` activé dans `ensure_diff_db` et `ensure_cache_db` — lectures concurrentes sans blocage

---

## 0.55 — 2026-06-04

### Fix — `Bkp` : exit 0 si stderr contient uniquement INFO/WARNING

- Borg renvoie exit code 1 quand des avertissements se produisent pendant le backup (fichiers modifiés, droits insuffisants, etc.)
- Précédemment : cet exit 1 était propagé tel quel si aucun `ERROR` n'était trouvé
- Désormais : si aucun message de niveau `ERROR` ou `CRITICAL` n'est présent dans stderr, exit code = 0
- Seule la présence d'un `ERROR` ou `CRITICAL` déclenche exit 2

---

## 0.54 — 2026-06-04

### Ajout — `Prune` : nettoyage automatique du diff.db après prune réel

- Après `borg prune` + `compact`, `_cleanup_index_after_prune()` récupère la liste courante des archives
- Supprime de `diff_index` les entrées dont `archive_new` n'existe plus
- Supprime de `diff_indexed_pairs` les paires dont `archive_old` ou `archive_new` n'existe plus
- Supprime de `archive_snapshot` et `archive_snapshot_indexed` les archives disparues
- Affiche un résumé si des entrées ont été supprimées : `N diff, N paires, N+N snapshots`
- Pas exécuté sur dry-run ; ignoré si `NOIDX=1` ou si le diff.db n'existe pas encore

---

## 0.53.1 — 2026-06-04

### Fix — suppression du `print` debug dans `getDataFromEnvOrFile`

- `"📄 Fichier trouvé : <path>"` affiché à chaque démarrage si le fichier sentry existe
- Ligne `print(f"📄 Fichier trouvé : {path}")` supprimée

---

## 0.53 — 2026-06-04

### Ajout — `Report` : option `-j` sortie JSON

- `-j` : sortie `json.dumps({'summary': ..., 'backups': ...})` à la place des tableaux ASCII/HTML
- `summary` : dict par nick (même données que le tableau résumé, stats du dernier backup incluses)
- `backups` : dict par nick → dict par archive (toutes colonnes, stats +ajouté/-supprimé/=présent)
- Mutuellement exclusif avec `-l` (HTML) : `-j` prioritaire
- Ajout de `j` dans `optab['report']` et paramètre `as_json` dans `cmd_report()`

---

## 0.52 — 2026-06-04

### Ajout — `Report` : réindexation automatique des paires manquantes

- Lors de la génération du rapport, si une archive affiche `—` en stats et que sa paire n'est pas dans `diff_indexed_pairs`, elle est réindexée automatiquement (borg diff à la volée)
- Seules les paires non indexées sont traitées — le premier dump (sans prédécesseur) est ignoré
- Les paires déjà indexées mais vides (0 changements) restent `—` (comportement attendu)
- Message de diagnostic vers `stderr` : `réindexation auto <old> → <new>`
- Après réparation, `diff_stats` est recalculé avant d'afficher le rapport

---

## 0.51.2 — 2026-06-04

### Fix — `-F` absent de `optab` pour `index` / `indexsnap`

- `-F` non listé dans `optab['index']` et `optab['indexsnap']` → `step2F` + `usage()` appelé
- Ajout de `F` dans les deux entrées `optab`

---

## 0.51.1 — 2026-06-04

### Fix — `-F` absent de `getopt`

- `-F` n'était pas déclaré dans la chaîne `getopt` → `option -F not recognized` à l'exécution
- Ajout de `F` (sans `:`, flag sans argument) dans la chaîne getopt

---

## 0.51 — 2026-06-04

### Ajout — `Index` / `IndexSnap` : option `-F` (force réindexation)

- `-F` force la réindexation même si les paires/snapshots sont déjà présents en cache SQLite
- `cmd_index -F` : supprime les entrées `diff_index` + `diff_indexed_pairs` existantes avant de réindexer chaque paire
- `cmd_indexsnap -F` : supprime `archive_snapshot` + `archive_snapshot_indexed` de la dernière archive avant réindexation
- Utile quand l'index existe mais contient des données manquantes ou corrompues
- Propagé automatiquement : `Index -F` appelle `IndexSnap -F` en fin de traitement

---

## 0.50 — 2026-06-04

### Ajout — `Restore` : `-w -` / `-W -` → tar vers stdout

- `where == '-'` : tar non-compressé streamé vers `sys.stdout.buffer` (`mode='w|'`)
- Fonctionne avec `-w -` (arborescence) et `-W -` (plat)
- Tous les messages informatifs (archive sélectionnée, erreurs) redirigés vers stderr pour ne pas corrompre le flux binaire
- `BrokenPipeError` géré proprement (pipe fermé par le lecteur → exit 0)
- Exemple : `borgHelper -c Restore -n srv -f 'home/user' -w - | tar -tvf -`
- Exemple : `borgHelper -c Restore -n srv -f 'home/user' -w - | ssh autre "tar -xf - -C /restore"`

---

## 0.49.5 — 2026-06-04

### Ajout — `Report` : `=présent` avec taille disque et %

- `present_sz = original_size - added_sz - modified_sz` (calculé sans requête supplémentaire)
- Format : `N (P%) · SIZE (S%)` — cohérent avec `+ajouté` et `-supprimé`

---

## 0.49.4 — 2026-06-04

### Ajout — `Report` : taille disque exprimée en % dans les stats

- `_fmt_stats(s, nf, total_sz)` : nouveau paramètre `total_sz` = `original_size` de l'archive courante
- Format : `N (P%) · SIZE (S%)` — ex : `12 (3%) · 3.2 MiB (1%)`
- `=présent` : nb fichiers + % uniquement (taille des fichiers stables non stockée dans diff_index)
- Dénominateur taille : `original_size` du backup courant (disponible depuis borg info)

---

## 0.49.3 — 2026-06-04

### Ajout — `Report` : stats dans le tableau résumé + taille disque

#### Tableau résumé du haut (par serveur)
- Colonnes `+ajouté`, `-supprimé`, `=présent` ajoutées : stats du **dernier backup**
- Format : `N (P%) · SIZE` pour ajouté/supprimé, `N (P%)` pour présent
- `—` si l'index n'a pas encore été construit pour ce nick

#### Taille disque dans les stats (tous tableaux)
- `_diff_stats_for_nick` : requête étendue avec `SUM(size_after)` / `SUM(size_before)`
- added → `size_after` (taille des nouveaux fichiers)
- removed → `size_before` (taille des fichiers supprimés)
- modified → `size_after` (taille après modification)
- Format unifié via `_fmt_stats(s, nf)` : `"N (P%) · X MiB"`

---

## 0.49.2 — 2026-06-04

### Correctifs

#### `_diff_stats_for_nick` : `sqlite3.connect` manquant
- `conn=get_diff_db(nick)` retournait un chemin (string) au lieu d'une connexion
- `conn.execute(...)` → `AttributeError` → avalé par `except Exception: return {}` → stats toujours `—`
- Fix : `db_path=get_diff_db(nick)` + `conn=sqlite3.connect(db_path)`

#### `boex` : `KeyboardInterrupt` non géré
- Ctrl-C pendant `ps.communicate()` provoquait un traceback Python + message Sentry
- Fix : `try/except KeyboardInterrupt` autour de `communicate()` → `ps.kill()` + exit 130

---

## 0.49.1 — 2026-06-04

### Correctif — `Report` : colonnes stats toujours visibles en ASCII

- `prettyTabelise` auto-découvre les colonnes depuis les clés des entrées → si aucune archive n'a de stats (index absent), les colonnes n'apparaissaient pas
- Fix : toutes les vraies archives (celles avec `nfiles`) reçoivent toujours les 3 colonnes (`+ajouté`, `-supprimé`, `=présent`), avec `'—'` quand aucune donnée d'index n'est disponible
- Résultat : colonnes présentes dans ASCII et HTML, que l'index soit construit ou non

---

## 0.49 — 2026-06-04

### Ajout — `Report` : statistiques % ajoutés/supprimés/présents par backup

- Nouvelle fonction `_diff_stats_for_nick(nick)` : agrège les counts par type depuis `diff_index` pour chaque archive
- Calcul par archive : `+ajouté`, `-supprimé`, `=présent` en nb de fichiers et % relatif au total de la backup précédente
- Formule : `total_précédent = nfiles_courant - ajoutés + supprimés` (derivé de `nfiles` borg info)
- Format d'affichage : `N (P%)` — ex : `12 (3%)` / `5 (1%)` / `380 (96%)`
- Si pas d'index pour l'archive : colonnes absentes (pas d'erreur)
- Colonnes ajoutées dans les tables ASCII (prettyTabelise) et HTML (htmlTabelise)

---

## 0.48 — 2026-06-04

### Ajout — `Restore` : préservation des droits d'origine + option `-L` (liste des droits)

#### Droits d'origine dans le tar (`--numeric-owner`)
- `borg extract` appelé avec `--numeric-owner` : préserve les uid/gid numériques des fichiers extraits
- `tarfile.add()` capture `mode`, `uid`, `gid`, `mtime` via `os.lstat()` sur les fichiers extraits
- Résultat : le tar contient les droits/propriétaires exacts de l'archive d'origine (quand lancé en root)

#### Option `-L` : affichage des droits sans restauration
- `borgHelper -c Restore -n <nick> -f <chemin> -L`
- Affiche les droits des fichiers/répertoires correspondants (format `ls -la`) depuis l'archive
- Si `-b` absent : recherche via SQLite la dernière archive contenant le fichier (comme `Restore` normal)
- Sortie redirigeable vers un fichier texte : `borgHelper -c Restore -n srv -f 'home/*' -L > droits.txt`
- Implémenté via `borg list --format '{mode} {user:8} {group:8} {size:>12} {isomtime} {path}{NL}'`

---

## 0.47.2 — 2026-06-04

### Correctif — `Restore` : `OSError: No space left on device`

- `_restore_to_tar` et restauration plate (`-W`) : `OSError` attrapé autour des opérations d'écriture
- `errno 28` (ENOSPC) : message `[ERREUR] Espace disque insuffisant sur la cible : <fichier>` + exit 3
- Autres `OSError` : message d'erreur + exit 3
- Le répertoire temporaire est nettoyé proprement dans tous les cas (context manager)

---

## 0.47.1 — 2026-06-04

### Ajout — `IDX_INCLUDE` et `IDX_EXCLUDE` dans borghelperrc

- `IDX_INCLUDE = /etc /home /root` : liste blanche — seuls ces chemins sont indexés
- `IDX_EXCLUDE = /proc /sys /tmp /var/log` : liste noire — ces chemins sont exclus de l'index
- Support préfixe et glob (`*`, `?`) pour chaque entrée
- Si les deux sont définis : `IDX_INCLUDE` filtre d'abord, puis `IDX_EXCLUDE` s'applique
- Appliqué dans : `Index` (diffs), `IndexSnap` (snapshot), `Bkp` (--list parsing)

---

## 0.47 — 2026-06-04

### Ajout — `NOIDX` et détection index vide

#### `NOIDX = 1` dans borghelperrc
- Désactive toute indexation pour ce nick : `Index`, `IndexSnap`, et `Bkp` (en plus du flag `-I`)
- Message informatif quand le nick est ignoré

#### Index vide → erreur explicite
- `_is_index_empty(nick)` : vérifie si `diff_index` et `archive_snapshot` sont tous deux vides pour ce nick
- `Search`, `FileHist`, `DuIdx` : si index vide pour un nick → `[ERREUR] Index vide pour X — lancez : borgHelper -c Index -n X`
- Permet de distinguer "aucun résultat" de "index jamais initialisé"

---

## 0.46.2 — 2026-06-04

### Correctifs — `IndexError: list index out of range`

- `_boex_check_stdout` : helper commun qui lève `RuntimeError` si `boex` retourne stdout vide ou code d'erreur
- `getlastbkp` : crash si borg list échoue → RuntimeError propagée aux appelants
- `cmd_index` : borg list inaccessible → message d'erreur + return 1 (ne crash plus)
- `cmd_indexsnap` : même fix
- `cmd_diffbkp` : même fix → exit 2

---

## 0.46.1 — 2026-06-04

### Améliorations — `Restore`

- `-f` accepte les globs `*` et `?` (ex : `etc/nginx/*.conf`, `home/user*`)
  - Avec glob : `borg extract --pattern=sh:...` utilisé à la place du chemin direct
  - `_find_last_archive_with_file` utilise `LIKE` sur l'index SQLite pour les patterns
- Structure des répertoires préservée dans les tar (sous-répertoires inclus par défaut)
- `-w <dest>` : restauration avec sous-répertoires (comportement précédent)
- `-W <dest>` : restauration plate — fichiers à la racine, sans arborescence
  - Pour tar : `arcname = basename(fichier)`
  - Pour répertoire : copie plate via `shutil.copy2`
- `.tgz` existant : exit 3 avec message d'erreur (au lieu de warning + écrasement silencieux)

---

## 0.46 — 2026-06-04

### Améliorations — `Restore`

#### Sans `-b` : sélection automatique de l'archive depuis le SQLite
- `_find_last_archive_with_file` : cherche dans `archive_snapshot` puis `diff_index` la dernière archive connue contenant le chemin
- Si trouvée : utilisée et affichée ; sinon : fallback sur la dernière archive (comportement précédent)

#### `-w .tar` ou `-w .tgz` : sortie archive tar
- Extraction vers un répertoire temporaire puis création/append du tar via Python `tarfile`
- `.tar` : append si le fichier existe déjà
- `.tgz` / `.tar.gz` : recréation (gzip ne supporte pas l'append) avec warning si le fichier existe
- Répertoire temporaire nettoyé automatiquement

#### Fix
- `cmd_resto` : affichage stderr propre au lieu de `print(rb)` (dump dict brut)

---

## 0.45.2 — 2026-06-04

### Ajout — `BORG_KEY_FILE` dans borghelperrc

- `boex` passe `BORG_KEY_FILE` à borg si la clé est définie dans la section du nick
- Utile quand plusieurs nicks partagent le même dépôt physique avec chiffrement `keyfile`
- Inactif si absent de la conf (pas d'effet de bord)

---

## 0.45.1 — 2026-06-04

### Optimisation — `Report` : cache du prune dry-run + 1 seul appel borg info

- `_boex_last_modified(nick)` : extrait le point commun des deux caches
- `cache_prune_dryrun(nick, last_modified)` : met en cache le résultat de `borg prune --dry-run` (clé `{nick}:prune` dans `cachejsonboexlm`)
- `cacheJsonBoexWithLM` : accepte `last_modified=` pour éviter un appel borg info redondant
- `prep_report` : **1 seul `borg info --json`** par nick → `last_modified` partagé entre les deux caches
- Cache hit complet : 1 appel réseau au lieu de 3 (borg info + borg info --glob + prune dry-run)
- Fix : `suffix="-info.json"` retiré de l'appel `cacheJsonBoexWithLM` dans `prep_report` (TypeError latent)
- `clear_cache_nick` : purge aussi `{nick}:prune`
- `cmd_cache_clean` : purge aussi les entrées `:prune` périmées

---

## 0.45 — 2026-06-04

### Ajout — `Bkp` : indexation automatique pendant le backup

- Par défaut, `Bkp` ajoute `--list --filter AMCBTd` au `borg create`
- Après backup réussi : parse la sortie `--list` (entrées `borg.output.list`) → stocke dans `diff_index`
- Appelle ensuite `IndexSnap` pour le snapshot de la nouvelle archive
- Entrées list masquées dans l'affichage stderr (sauf debug) — évite des milliers de lignes `[INFO] A /etc/...`
- `-I` : désactive tout (pas de `--list`, pas d'indexation)
- Statuts capturés : `A`→added, `M`→modified, `C`/`B`/`T`→flags, `d`→removed
- Note : les tailles ne sont pas disponibles depuis `--list` (stockées à `None`) — `DuIdx` affichera `—` pour ces entrées

---

## 0.44.3 — 2026-06-04

### Correctifs — `Report` : gestion des erreurs borg par nick

- `cacheJsonBoexWithLM` : si `borg info` retourne un code non-nul ou stdout vide, lève `RuntimeError` avec le message d'erreur borg (fin du crash IndexError)
- `cmd_report` : attrape l'exception par nick, affiche une ligne erreur dans le tableau (rouge en HTML, `*** ERREUR` en ASCII), note exit code 2, continue les autres nicks
- Colonne `reste` contient le message d'erreur tronqué pour identification rapide

---

## 0.44.2 — 2026-06-04

### Ajout — `-B <archive>` borne de fin pour `Search`, `FileHist`, `DuIdx`

- `-B <archive>` : limite la recherche jusqu'à cet archive (inclus)
- Combinable avec `-b` : `-b X -B Y` → plage [X, Y]
- `-b ALL -B Y` → tout l'index jusqu'à Y
- Sans `-B` : comportement inchangé (jusqu'au dernier)

---

## 0.44.1 — 2026-06-04

### Correctifs — Aide `-h` / `-H`

- `-h` général : ajout `IndexSnap`, `DuIdx`, mention `-b` pour `Search`/`FileHist`
- `-H indexsnap`, `-H duidx` : nouvelles entrées détaillées
- `-H search`, `-H filehist` : mention de `-b` et du snapshot
- `-H index` : mention de l'appel automatique à `IndexSnap`

---

## 0.44 — 2026-06-04

### Ajout — Filtre plage d'archives pour `Search`, `FileHist`, `DuIdx`

- Sans `-b` : uniquement la dernière paire d'archives (archive_new = MAX)
- `-b <archive>` : depuis cet archive jusqu'au dernier (archive_new_date ≥ date de l'archive)
- `-b ALL` : tout l'index, toutes les paires
- Filtre appliqué aussi sur la clause `NOT EXISTS` du snapshot (présent)

---

## 0.43.1 — 2026-06-04

### Correctifs et améliorations — `DuIdx`

- Fix : colonne `added/modif` toujours vide (clé `'added/modif'` vs `'added'` dans le dict)
- Vue pivotée : tri par colonne avec `-s <col>[:asc|desc]` — valeurs : `chemin`, `added`, `removed`, `present`
- Sortie JSON avec `-j` — structure `{pattern, rows:[{chemin, added/modif:{nb,taille}, ...}], total}`

---

## 0.43 — 2026-06-04

### Ajout — commande `DuIdx`

- Résumé `du -sh`-like à partir du SQLite : taille totale et nombre de fichiers par type de changement
- Types : `added`, `modified`, `removed`, `C`, `B`, `T`, `présent` (stables)
- Pattern de chemin : sous-chaîne libre ou glob `*`/`?` (ex : `home/*`, `*.conf`)
- `-f` optionnel — défaut `*` (tout le dépôt)
- Ligne TOTAL en bas du tableau
- Taille : `size_after` pour added/modified, `size_before` pour removed, `size` pour présent
- Note : les entrées `diff_index` comptent les événements, pas les fichiers uniques

---

## 0.42.2 — 2026-06-04

### Ajout — `DB_NAME` dans borghelperrc

- Nouvelle clé optionnelle `DB_NAME` dans la section d'un dépôt
- Si définie, remplace le nick dans le nom des fichiers SQLite : `<conf>-<DB_NAME>-cache.db`
- Utile quand plusieurs nicks partagent le même dépôt physique
- Caractères non alphanumériques sanitisés automatiquement

---

## 0.42.1 — 2026-06-04

### Changement cassant — Un SQLite par nick

- Chaque dépôt (nick) possède désormais ses propres fichiers DB
- Nommage : `<conf>-<nick>-cache.db` et `<conf>-<nick>-diff.db`
- `get_cache_db(nick)` / `get_diff_db(nick)` remplacent les globals `cache_db_file` / `diff_db_file`
- `cmd_cache_info`, `cmd_cache_clean`, `cmd_search`, `cmd_filehist` : connexion par nick
- **Migration** : relancer `Index` et `IndexSnap` pour reconstruire les index dans les nouveaux fichiers

---

## 0.42 — 2026-06-04

### Changement cassant — Emplacement des fichiers DB

- Les deux DBs SQLite (`-cache.db` et `-diff.db`) sont maintenant dans `~/.cache/borghelper/` par défaut
- Le nom des fichiers inclut le basename sanitisé du fichier de configuration : `borghelperrc-cache.db`, `borghelperrc-diff.db`
- Configurable via la clé `CACHE_DIR` dans la section `[DEFAULT]` de `.borghelperrc`
- Exemple avec `-C /etc/borg-prod.rc` → `~/.cache/borghelper/borg-prod_rc-cache.db`
- **Migration** : les anciens `~/.borghelper-cache.db` et `~/.borghelper-diff.db` ne sont plus utilisés — relancer `Index` et `IndexSnap` pour reconstruire les index

---

## 0.41.1 — 2026-06-04

### Correctifs — `IndexSnap`

- `borg list --json ::archive` non supporté dans borg 1.x pour le contenu d'une archive → remplacé par `borg list --format '{size} {isomtime} {path}{NL}' ::archive` avec parse ligne par ligne
- Affichage du stderr borg en cas d'échec (était silencieux)

---

## 0.41 — 2026-06-04

### Ajouts — Snapshot archive + recherche de fichiers stables

#### Nouvelle table `archive_snapshot`
- Stocke le listing complet des fichiers de la dernière archive (`borg list --json ::archive`)
- Clé : `(nick, archive, path)` — incrémental, paires déjà indexées ignorées
- Champs : nick, archive, archive_date, path, size, mtime

#### Nouvelle commande `IndexSnap [-n nick/ALL]`
- Indexe le listing de la dernière archive de chaque nick
- Appelée automatiquement par `Index` à la fin de chaque indexation de diffs

#### `Search` étendu
- Résultats UNION : diff_index (changements) + archive_snapshot (fichiers présents sans historique de changement)
- Les fichiers stables depuis plus longtemps que la rétention de prune apparaissent maintenant avec le type `présent`

#### `FileHist` étendu
- Ajoute les lignes `présent` depuis archive_snapshot, triées chronologiquement avec le reste

---

## 0.40.3 — 2026-06-04

### Refactoring — `DiffBkp` sur SQLite

- `DiffBkp` utilise désormais `~/.borghelper-diff.db` au lieu d'appeler `borg diff` en direct
- Si la paire d'archives n'est pas encore indexée, le diff est calculé et stocké automatiquement à la volée
- Affichage en tableau (prettytable) : colonnes type / chemin / taille avant / taille après
- Paires indexées via `Index` : réponse instantanée, sans appel réseau

---

## 0.40.2 — 2026-06-04

### Correctifs — `cmd_bkp` : affichage et codes retour

- Suppression du double affichage : `boex()` n'imprime plus `stderr` directement — c'est `cmd_bkp` qui gère
- Stderr parsé (JSON borg) : chaque entrée affichée sous forme `[LEVELNAME] message` (lisible humain)
- Stderr fallback (strings, cas JSONDecodeError) : chaque ligne non-vide affichée telle quelle
- Code retour : si borg sort avec code ≠ 0 et qu'aucun dict `ERROR` n'est trouvé dans stderr, le code retour borg est propagé directement (couvre la branche fallback de 0.39.1)

---

## 0.40.1 — 2026-06-03

### Suppressions
- `cmd_bkp` n'écrit plus `/tmp/borgHelper-bkp-<nick>.json`
- Commande `poc` supprimée (commande debug morte qui lisait ce fichier)

---

## 0.40 — 2026-06-03

### Ajouts

#### Cache persistant (`~/.borghelper-cache.db`)
- Cache déplacé de `/tmp/borgsql.db` vers `~/.borghelper-cache.db` (persistant entre reboots)
- `purge_stale_cache` : supprime les entrées périmées dès que `last_modified` du dépôt change
- `clear_cache_nick` : vide tout le cache d'un nick — appelé automatiquement après `DelBkp` et `Prune`
- Nouvelle commande `CacheInfo [-n nick/ALL]` : affiche le contenu du cache (nick, last_modified, taille)
- Nouvelle commande `CacheClean [-n nick/ALL]` : nettoyage manuel des entrées périmées et des nicks inconnus

### Correctifs
- `cacheJsonBoexWithLM` : `return(ret[0])` → `return(details[0])` (bug : `ret` non défini)
- `cacheJsonBoexWithLM` : suppression des paramètres inutilisés `prefix` et `suffix`

---

## 0.39.1 — 2026-06-03

### Correctifs
- `boex` : `ret['stderr']=theJson` stockait la chaîne brute au lieu de la parser → `json.loads(theJson)`
- `boex` : le `except` re-encodait en JSON → crash sur tout `\` dans le texte (chemins Windows, messages borg)
- Fallback : `except json.JSONDecodeError` → split lignes brutes (cohérent avec la branche `else`)

---

## 0.39 — 2026-06-03

### Ajouts

#### Index diff — historique des changements de fichiers
- Nouvelle commande `Index [-n nick/ALL]` : indexe les diffs entre archives consécutives dans `~/.borghelper-diff.db`
- Incrémental : les paires déjà traitées sont ignorées (`diff_indexed_pairs`)
- Nouvelle commande `Search -f <pattern> [-n nick/ALL]` : recherche par nom de fichier (sous-chaîne ou glob `*`/`?`)
- Nouvelle commande `FileHist -f <chemin> [-n nick/ALL]` : historique complet d'un chemin exact
- Parsing de la sortie `borg diff` : `added`, `removed`, `modified` (avec tailles avant/après), `C`, `B`, `T`
- Tailles stockées en octets entiers, affichées via `convert_octets_readable`

#### Mount
- Sans `-b` : monte toutes les archives (`ALL`) — était la dernière archive
- `-b last` : comportement précédent (dernière archive uniquement)

---

## 0.38.2 — antérieur

- Division par zéro corrigée dans `prep_report` (cas 0 archives)

## 0.38.1

- Correctifs et amélioration de la partie Sentry

## 0.38

- Cache des appels `borg info/list` en SQLite — remplace les fichiers JSON temporaires

## 0.37

- Fichier de conf paramétrable (`-C`)

## 0.36.2

- Correction version + déplacement import Sentry

## 0.36

- Intégration Sentry (DSN via env, fichier ou `/usr/local/etc/borghelper-sentry`)

## 0.35

- Rapport HTML colorisé et limité

## 0.34

- Export de clef (`Key`)

## 0.33

- `Mount` sur la dernière archive ou archive précisée

## 0.32

- `ALL` exclut les sections sans archives

## 0.31

- Nom serveur en tête de tableau dans `Report`

## 0.30

- `BORG_ARCHNAME` commençant par `::` → nom d'archive complet

## 0.29

- `-n ALL` pour `Report` et `Prune`
- `Prune` opérationnel

## 0.27

- `Report` multi-host fonctionnel (texte + HTML)

## 0.22

- `Init` : initialisation repo local (`repokey`)

## 0.20

- `BORG_ARCHNAME` et `BORG_ROOTBKP` configurables

## 0.1

- Première version officielle

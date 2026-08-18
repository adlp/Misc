# Changelog

## firewall-xgs/fail2ban — 2026-08-18 (5)

Config-only, aucun changement de script Python.

### Changed
- `nginx-conf/tarpit-server.conf` : abandon de `alias`/`error_page` pour
  le tarpit — après tests approfondis en conditions réelles (nginx
  1.31.3, build Debian officiel, sans module tiers), `error_page` ne
  redirige jamais en interne vers la location cible (vérifié avec/sans
  `if`, avec/sans `internal`, plusieurs codes sans collision possible,
  et même pour un 404 nginx natif) — cause non identifiée. Remplacé par
  `return CODE "texte";` (payload désormais en dur dans le fichier,
  ~2964 octets, plus de fichier externe/`location`/`alias`) — seule
  méthode constatée fiable pour choisir le code HTTP tout en servant du
  contenu throttlé. `nginx-conf/tarpit/payload.txt` n'est plus utilisé
  par nginx (conservé comme référence de génération dans le README).
- `nginx-conf/geo-badguys.conf` : débit par défaut du tarpit passé de
  10 à 100 octets/s (`map $is_banned $tarpit_rate`).
- `nginx-conf/README.md` : documentation mise à jour (installation
  simplifiée, section expliquant le choix `return` vs `error_page`,
  script de régénération du payload adapté).

## firewall-xgs/fail2ban — 2026-08-18 (4)

Config-only, aucun changement de script Python.

### Changed
- `nginx-conf/tarpit-server.conf` : code HTTP retourné aux IP bannies
  désormais configurable (403 par défaut) au lieu d'être fixé à 200 via
  `alias`. Remplace le `rewrite ^ /__tarpit__ last;` par `return
  $CODE;` + `error_page $CODE = /__tarpit__;` (le `=` sans valeur
  derrière `error_page` conserve le code d'origine au lieu de le forcer
  à 200) — le contenu du tarpit reste servi et throttlé via
  `limit_rate` normalement. Documenté dans `nginx-conf/README.md`.

## firewall-xgs/fail2ban — 2026-08-18 (3)

Config-only (nouveaux filtres), aucun changement de script Python.

### Added
- `filter.d/php-404-syslog.conf`, `filter.d/scanner-404-403-syslog.conf` :
  variantes syslog des filtres `-extended` (probes PHP/WordPress et
  scanner générique), pour des logs nginx reçus via syslog (ex:
  conteneur Authentik/nginx qui logue sur stdout, capté par rsyslog —
  enveloppe timestamp ISO8601 + hostname + tag `nginx[pid]:` en tête de
  ligne). Sans realip sur ce flux : IP réelle prise dans
  `$http_x_forwarded_for` (après le `/` dans `$remote_addr/$xff`),
  `$remote_addr` valant l'IP interne du proxy/passerelle docker. Ancrage
  du match sur le tag syslog `nginx\[\d+\]: ` plutôt que `^` en début de
  ligne. Testé avec 6 cas Python `re` (200 jamais matché, 404 PHP, 403
  scanner, 404 scanner, ignoreregex favicon).

## firewall-xgs/fail2ban — 2026-08-18 (2)

Config-only (filtres existants), aucun changement de script Python.

### Changed
- `filter.d/php-404-extended.conf`, `filter.d/scanner-404-403-extended.conf` :
  ajout de failregex pour un second `log_format` nginx (`snmain`,
  `$server_name` en 1ère colonne) utilisé sur un autre vhost. IP réelle
  prise dans `$http_x_forwarded_for` (dernier champ) au lieu de
  `$remote_addr` — ce vhost n'a pas `realip` configuré, `$remote_addr` y
  vaut l'IP interne du reverse-proxy amont. Statut HTTP en clair (`404`,
  pas `HTTP:404`). Tolère une chaîne XFF (`"ip1, ip2"`), seule la
  1ère IP sert de HOST. Les failregex du format `extended` précédent
  sont conservées telles quelles (autre vhost, toujours en service) —
  chaque filtre matche maintenant les deux formats indifféremment.
  Testé avec 8 cas Python `re` (nouveau format, ancien format, 200
  jamais matché, chaîne XFF, ignoreregex favicon).

## firewall-xgs/fail2ban — 2026-08-18

Config-only (nouveau filtre), aucun changement de script Python.

### Added
- `filter.d/scanner-404-403-extended.conf` : détecte un comportement de
  scanner générique — trop d'erreurs 404/403 en rafale sur n'importe
  quel chemin (pas seulement PHP/WordPress comme `php-404-extended.conf`).
  Le seuil "trop" vient du `maxretry`/`findtime` de la jail, le filtre
  matche juste "requête en erreur 404/403". `ignoreregex` exclut les 404
  bénins fréquents (favicon/robots/apple-touch-icon). Exemple de jail
  documenté dans le README, réglé sur un débit de scan observé en réel
  (~10 erreurs/s) : `maxretry=10 findtime=3` détecte en ~1s au lieu
  d'attendre jusqu'à 60s. Testé (5 cas : 404 générique, 403 générique,
  succès jamais matché, favicon/robots ignorés malgré 404).

## firewall-xgs/fail2ban — 2026-08-17

Config-only (filtre fail2ban + snippets nginx), aucun changement de
script Python (pas de bump de version).

### Added
- `filter.d/php-404-extended.conf` : variante de `php-404.conf` adaptée
  au `log_format extended` custom (nginx derrière Sophos XGS avec
  `ngx_http_realip_module`) — IP réelle dans `$remote_addr` (premier
  champ après le 5e ` - `), pas en dernier champ de ligne comme
  l'original. Détecte les mêmes sondes PHP/WordPress, `HTTP:404`
  littéral (jamais de match sur 200). Testé (5 cas : extensions PHP,
  chemins WordPress, succès jamais matché, trafic normal Authentik
  jamais matché, chaîne X-Forwarded-For présente).
- `nginx-conf/` : snippets nginx complets (companion de
  `nginx_fw_block.py`) pour bloquer les IP bannies **sans renvoyer
  d'erreur** — tarpit (réponse lente via `limit_rate` + payload
  statique) plutôt qu'un 403 immédiat, empêchant tout accès au backend
  réel pour les IP bannies (`if` en amont de toute `location`, jamais
  de `proxy_pass` atteint). Fichiers : `geo-badguys.conf` (bloc
  `geo`/`map`, niveau `http{}` — doit y être inclus, erreur "geo
  directive is not allowed here" sinon), `realip.conf` (optionnel, pour
  restaurer la vraie IP client derrière un reverse-proxy applicatif type
  Sophos XGS WAF), `tarpit-server.conf` (snippet `server{}`),
  `tarpit/payload.txt` (payload de padding, ~3000 octets ⇒ ~5min à 10
  octets/s), `README.md` (installation, réglages, debug).

## firewall-xgs/fail2ban action.d — 2026-08-13

Config-only, aucun changement de script (pas de bump de version).

### Changed
- `action.d/sophos-xgs.conf` et `action.d/nginx-local.conf` : `actionban`/
  `actionunban` passent par `systemd-run --quiet --no-block` — fail2ban
  rend la main immédiatement au lieu d'attendre le push Sophos (~5-8s) ou
  le reload nginx. Nécessite systemd sur l'hôte (vérifié dispo/testé).
  Contrepartie documentée : un échec de ban/unban n'apparaît plus dans
  les logs fail2ban, seulement via `journalctl`/syslog (tag
  `sophos-fw-block`/`nginx-fw-block`). Aucun changement requis côté
  script — le verrouillage déjà en place (`_ip_activity_lock`, `locked()`)
  gérait déjà le cas d'invocations concurrentes.

## firewall-xgs/fail2ban 2.5.0 — 2026-08-12

### Added
- IP list shardées (`iplist_prefix`) : alternative à `iplist` (mutuellement
  exclusifs) pour contourner la limite Sophos de 1000 entrées par IP
  list. Nouvelles clés config : `iplist_prefix`, `iplist_seed_ip`
  (requis — IP placeholder pour créer une liste, Sophos exige >= 1
  adresse), `iplist_max_entries` (défaut/plafond 1000), `alert_email`,
  `smtp_host`/`smtp_port` (défaut `localhost:25`).
- `ban` ajoute l'IP à la liste shardée **active** (la plus récente non
  pleine) ; une fois `iplist_max_entries` atteint, crée automatiquement
  la liste suivante (seedée) et envoie un mail à `alert_email` si
  configuré (sinon warning loggé, jamais fatal).
- `unban` retire l'IP de la liste shardée qui la contient **uniquement**
  — aucune autre liste n'est touchée, donc **aucun décalage en cascade**
  quand une IP est retirée d'une liste antérieure (exigence explicite :
  minimiser les modifications de liste). Chaque ban/unban ne fait donc
  jamais plus d'1 appel Sophos d'écriture, sur exactement la liste
  concernée.
- État shardé (quelle IP dans quelle liste) suivi localement dans
  `/var/lib/sophos-fw-block/shards-*.json` (persistant, contrairement aux
  verrous/état éphémère de `/run` — c'est la seule trace permettant à
  `unban` de cibler la bonne liste sans relire tout Sophos).
- `start` crée la/les listes shardées si absentes et resynchronise
  (ajoute les IP manquantes, retire les IP expirées de leur liste
  respective) depuis fail2ban — même principe que pour `group`/`iplist`.
- `list` affiche l'état shardé local (pas d'appel Sophos — reflète ce
  que le script croit avoir poussé).
- Testé : bootstrap sans email, dépassement de seuil avec email (réel,
  vérifié via un serveur SMTP local de test — from/to/subject corrects),
  échec SMTP non fatal, unban ciblé sans impact sur les autres listes,
  `start` répartissant/resynchronisant correctement sur plusieurs listes.

## firewall-xgs/fail2ban/nginx_fw_block.py 1.1.0 — 2026-08-12

Nouveau script, indépendant de `sophos_fw_block.py` (stdlib uniquement,
pas d'import croisé) : maintient un fichier geo-map nginx local listant
les IP bannies, et déclenche un reload nginx quand ce fichier change.
Alternative/complément à Sophos : purement local, reload nginx
(~instantané) au lieu des 5-8s observées côté API Sophos.

### Added
- Actions `ban`/`unban`/`list`/`start`, config `[nginx]` (`jail`,
  `fail2ban_client`, `map_file`, `reload_cmd`), `--jail`/`--map-file`/
  `--reload-cmd`/`--debug`/`--debug-timing`.
- `reload_cmd` : commande shell arbitraire définie dans la config
  (adaptable au déploiement — bare metal ou `docker exec ... nginx -s
  reload`).
- Verrou non-bloquant par IP (identique à `sophos_fw_block.py` 2.3.1) :
  un ban/unban déjà en cours pour une IP fait abandonner immédiatement
  tout appel concurrent pour cette même IP.
- `action.d/nginx-local.conf`, `nginx.conf.example`, doc dans le README
  (section "Bonus : blocage local nginx").

### Changed
- `ban`/`unban` **ne dépendent pas de fail2ban** : ils lisent/modifient/
  réécrivent `map_file` directement (I/O locale uniquement), idempotent
  (aucune écriture ni reload si l'IP est déjà dans l'état voulu). Design
  initial (1.0.0) les faisait interroger `fail2ban-client status <jail>`
  et pousser la liste complète à chaque appel — remplacé par un
  ajout/retrait incrémental local, fail2ban n'étant plus nécessaire pour
  ces deux actions (utile car aucune raison d'éviter une lecture locale,
  contrairement à l'API Sophos lente). Seule l'action `start` interroge
  encore fail2ban, pour une resynchro complète (bootstrap ou après
  intervention manuelle sur le fichier). Testé : zéro appel
  `fail2ban-client` pendant ban/unban, idempotence confirmée (pas de
  reload sur IP déjà présente/absente).

## firewall-xgs/fail2ban 2.4.0 — 2026-08-12

### Removed
- Cache du dernier push réussi (2.3.0, `_load_last_pushed`/
  `_save_last_pushed`/`_clear_cache`/`_unchanged_since_last_push`,
  `/run/sophos-fw-block/lastpush-*.json`). Retiré : le verrou par IP
  (2.3.1, `_ip_activity_lock`) couvre déjà le cas motivant le cache
  (rebans rapides de la même IP pendant qu'un push est en vol), et le
  supprimer restaure une propriété perdue en 2.3.0 — chaque push non
  dédupliqué repousse la liste complète, corrigeant gratuitement toute
  dérive côté XGS au lieu de la laisser filer silencieusement derrière
  un skip. Simplifie aussi le code (plus de gestion d'invalidation par
  `flush`). `push_from_fail2ban()` redevient inconditionnel.

Argument retenu : le délai ban→unban dépasse largement la durée d'un
push (~5-8s), donc la collision que le cache aurait pu éviter dans ce
sens ne se produit pas en pratique ; et un ban qui suit rapidement un
unban sur la même IP fait de toute façon office de resync. Le verrou par
IP reste la seule protection contre les appels redondants — testé
(collision en vol toujours dédupliquée ; sans collision, chaque appel
repousse réellement, plus de skip sur état inchangé).

## firewall-xgs/fail2ban 2.3.1 — 2026-08-12

### Added
- Verrou non-bloquant par IP (`_ip_activity_lock`,
  `/run/sophos-fw-block/inprogress-*.lock`) : si un ban/unban est déjà en
  cours pour une IP donnée, tout appel concurrent pour la **même IP** est
  abandonné immédiatement (pas d'attente, pas de push en double) plutôt
  que de vérifier après coup si l'état a changé. Complète le cache de
  2.3.0 : celui-ci évite un push redondant une fois l'état stabilisé,
  celui-ci évite un push **concurrent** redondant pendant qu'un premier
  est encore en vol pour la même IP — le cas exact rapporté en prod
  (rebans rapides de la même IP pendant qu'un push lent est en cours).
  Des IP différentes restent traitées en parallèle (pas de blocage
  croisé, testé). Diminue d'autant le besoin de `sync` périodique.

Compromis documenté (voir docstring `_ip_activity_lock`) : un unban(X)
arrivant pendant qu'un ban(X) est en vol est abandonné sans repush —
l'état le plus récent n'est reflété qu'au prochain événement sur cette
IP, ou via `sync`/`start` manuel. Cas rare (retrait bien plus espacé
qu'un ban), accepté pour éliminer le cas fréquent.

## firewall-xgs/fail2ban 2.3.0 — 2026-08-12

### Added
- Cache local du dernier push réussi (`/run/sophos-fw-block/lastpush-*.json`,
  un fichier par combinaison host/group/iplist/jail) : `ban`/`unban`
  comparent la liste fail2ban actuelle à ce cache et **sautent tout appel
  Sophos** si elle est identique. Répond au cas observé en prod : un push
  lent (5-8s) fait que fail2ban redemande le même ban pour la même IP
  avant que le premier push soit terminé — désormais ces appels
  redondants ne touchent plus le firewall du tout. Écriture atomique
  (fichier temporaire + rename) pour rester correct si plusieurs
  ban/unban tournent en parallèle (verrou partagé).
- `flush` invalide ce cache (il modifie l'XGS en dehors de
  `push_from_fail2ban`) — sans ça, un ban/unban suivant avec la même
  liste fail2ban croirait à tort que rien n'a changé et sauterait le
  repush après un flush.

### Changed
- Compromis à connaître : avant ce cache, un ban/unban redondant
  re-poussait quand même la liste (sans effet réel, mais ça corrigeait
  au passage une éventuelle modification manuelle faite sur le firewall
  entre deux pushes identiques). Avec le cache, ce filet de sécurité
  implicite disparaît pour les pushes identiques — `sync`/`start` restent
  les outils pour vérifier/forcer un état réel en cas de doute.

## firewall-xgs/fail2ban 2.2.2 — 2026-08-12

### Added
- `test_iplist_add.py` : nouveau script diagnostic, teste
  `Set operation="add"` sur un `IPHost` de type IP list (jamais testé
  jusqu'ici, seulement sur `IPHostGroup`).

### Fixed
- Confirmé en réel : `operation="add"` échoue aussi sur un `IPHost`
  existant (502 "Entity having same name already exists", IP list
  inchangée) — même comportement générique que sur `IPHostGroup`. Aucune
  sémantique d'ajout incrémental nulle part dans cette API pour un objet
  nommé déjà existant. Documenté dans `set_iplist_addresses()`.
- Mesure clé : la restauration en fin de test (`operation="update"` avec
  un contenu **identique** à l'existant) a quand même pris ~8.4s en
  conditions réelles — le coût observé (~5-8s par push) n'est donc pas lié
  à la taille du diff ni au fait que le contenu change réellement, mais au
  fait qu'une écriture réussie sur un objet référencé par une règle active
  déclenche systématiquement le même coût (recompile de policy probable).
  Confirme qu'aucune optimisation de la requête elle-même n'est possible ;
  seuls le batching/debounce ou un mécanisme différent (liste tirée par le
  firewall) peuvent réduire l'impact perçu.

## firewall-xgs/fail2ban 2.2.1 — 2026-08-12

### Added
- `--debug-timing` logue aussi la durée de `fail2ban-client status
  <jail>` (`get_banned_ips()`) — permet de distinguer le temps passé côté
  fail2ban (local, rapide) du temps côté API Sophos (dominant, voir
  action `sync`/tests réels : ~5s pour un push `iplist` de 8 IP, tout
  côté serveur).

## firewall-xgs/fail2ban 2.2.0 — 2026-08-11

### Added
- Action `start` : comme `ban` mais pour toutes les IP actuellement
  bannies par fail2ban, sans IP en argument — crée l'`IPHost` manquant
  pour chacune (idempotent) avant de pousser la liste complète. Comble le
  vide documenté en 2.0.0 (jail avec des bans déjà en cours au premier
  déploiement, ou après un redémarrage). `push_from_fail2ban()` accepte
  désormais un paramètre `ips` optionnel pour éviter un second appel à
  `fail2ban-client` quand l'appelant l'a déjà récupérée (cas de `start`).

## firewall-xgs/fail2ban 2.1.0 — 2026-08-11

### Added
- Action `flush` : vide entièrement `group` puis lance `vacuum`, sans
  interroger fail2ban. N'agit pas sur `iplist`. `--dry-run` disponible —
  calcule les candidats vacuum comme si le groupe était déjà vide (tous
  les `IPHost` `<prefix>*` deviennent orphelins une fois le groupe vidé),
  donc reflète fidèlement ce que ferait un flush réel. Verrou exclusif
  posé pour toute la durée (vidage + vacuum), pas seulement le sous-appel
  vacuum, pour éviter qu'un ban concurrent ne crée un IPHost entre les
  deux étapes.

## firewall-xgs/fail2ban 2.0.0 — 2026-08-11

Refonte architecturale : fail2ban devient la seule source de vérité côté
`ban`/`unban`, au lieu d'un ajout/retrait incrémental interrogeant l'XGS.
Casse la compatibilité de config (nouvelle clé `jail` requise) — d'où le
bump majeur.

### Changed
- `ban`/`unban` interrogent désormais `fail2ban-client status <jail>` et
  **écrasent** l'état XGS (`group` et/ou `iplist`) avec cette liste
  complète, sans plus jamais lire l'état XGS actuel avant d'écrire.
  `ban` crée en plus l'`IPHost` de la nouvelle IP avant de pousser (pour
  que le groupe puisse la référencer) ; `unban` ne fait que repousser
  (fail2ban a déjà retiré l'IP de sa propre liste avant l'appel) — plus
  de suppression explicite d'`IPHost` dans `unban`, ce rôle revient à
  `vacuum`.
- Nouvelle clé de config `jail` (requise pour ban/unban/sync) et
  `fail2ban_client` (optionnel, défaut `fail2ban-client`), + option
  `--jail`.
- `_run_parallel()` retiré (n'était utile que pour paralléliser
  group/iplist dans l'ancien ban/unban incrémental — le nouveau push est
  1 lecture fail2ban + 1-2 écritures XGS, plus besoin) ainsi que
  `add_to_group()` (remplacé par `set_group_hosts()` appelé directement
  depuis `push_from_fail2ban()`).

### Added
- Action `sync` : compare, en lecture seule, la liste fail2ban actuelle à
  l'état XGS (`group`/`iplist`) — IP communes, seulement dans fail2ban
  (seraient ajoutées au prochain push), seulement sur XGS (seraient
  retirées). Utile avant activation (jail avec bans préexistants) ou pour
  détecter une dérive.

## firewall-xgs/fail2ban 1.6.1 — 2026-08-11

### Fixed
- **Bug silencieux introduit en 1.6.0** : `add_to_group()` interprétait
  toute erreur contenant "already"/"exist" comme "membre déjà présent"
  et s'arrêtait là sans jamais faire le repli get+set. Confirmé en réel :
  `Set operation="add"` sur un `IPHostGroup` existant renvoie
  `502 Entity having same name already exists` même pour un tout nouveau
  membre — l'entité en conflit est le **groupe**, pas le membre. Résultat
  en prod : l'IPHost était créé mais jamais ajouté au groupe → IP non
  bloquée, alors que le script ne loggait qu'un warning (pas d'erreur,
  exit code 0). `add_to_group()` refait systématiquement get_group_hosts
  + set_group_hosts, comme avant 1.6.0. `operation="add"` sur un
  IPHostGroup existant est maintenant confirmé non fonctionnel dans tous
  les cas testés (host fictif : 501 ; host réel : 502) — plus aucune
  tentative de ce type dans le script.
- Si vous avez utilisé `ban` en 1.6.0, vérifiez que les IP bannies depuis
  sont bien membres du groupe (`sophos_fw_block.py list`) — possible
  qu'elles aient été créées sans être bloquées.

## firewall-xgs/fail2ban 1.6.0 — 2026-08-11

### Added
- `vacuum` : nouvelle action qui supprime les objets `IPHost` `<prefix>*`
  orphelins (plus membres du groupe configuré — ex: après un `unban`
  interrompu avant la suppression de l'objet). `--dry-run` affiche la
  liste sans agir. Refuse de s'exécuter sans `group` configuré ou avec
  un préfixe vide (garde-fou, évite de tout supprimer par erreur).
- Verrou inter-process (`fcntl.flock`, `/run/lock/sophos-fw-block.lock`) :
  ban/unban prennent un verrou partagé (plusieurs peuvent tourner
  simultanément, cas normal avec fail2ban), `vacuum` un verrou exclusif —
  évite qu'un vacuum supprime un `IPHost` qu'un ban est en train de créer
  (race condition entre lecture de la liste et écriture).
- `add_to_group()` : `ban` tente d'ajouter le membre au groupe en 1 appel
  (`Set operation="add"`, sans lecture préalable de la liste), avec repli
  automatique sur le chemin sûr get+set si ça échoue. Gain de vitesse non
  garanti (testé en échec avec un objet fictif, pas encore confirmé avec
  un objet réel) mais sans risque grâce au repli.

### Changed
- `create_iphost`/`delete_iphost`/`unban` : les cas "déjà fait" (objet
  déjà existant, déjà absent du groupe, déjà supprimé) passent de `info`
  à `warning` en log — plus visibles sans être des erreurs.
- `ban` simplifié : `create_iphost` puis `add_to_group`, sans lecture
  préalable de la liste du groupe (l'ancien code lisait le groupe avant
  d'ajouter, devenu inutile avec `add_to_group`).

### Fixed
- `test_group_merge.py` : le test de retrait ciblé (`Remove` sur
  `IPHostGroup` avec `HostList`) a été retiré du script — confirmé
  reproductible en conditions réelles : au lieu de retirer le seul membre
  visé, il vide tout le groupe et laisse l'objet dans un état où même un
  `Set operation="update"` normal échoue ensuite (500). Documenté dans
  `set_group_hosts()` et le README : ne jamais utiliser cette opération.

## firewall-xgs/fail2ban 1.5.0 — 2026-08-11

### Added
- `--debug-timing` : log la durée de chaque appel API (label = fonction
  appelante), la durée d'établissement de chaque connexion TCP+TLS
  (une fois par connexion mise en pool, réutilisée ensuite — permet de
  voir si la lenteur vient du réseau ou du traitement côté firewall),
  la durée de chaque tâche parallèle (group/iplist, ou lookups `list`),
  et le temps total de l'action. Utile car la parallélisation côté
  client (1.4.1/1.4.2) n'a pas réduit les délais constatés en usage
  réel — cette option permet de voir si l'API Sophos sérialise les
  requêtes côté serveur malgré le parallélisme client.

## firewall-xgs/fail2ban 1.4.2 — 2026-08-11

### Fixed
- Vrai goulot d'étranglement de `list` identifié : `list_group()` faisait
  1 appel Get par membre du groupe, **séquentiellement** (N+1 appels pour
  N machines — 11 appels pour 10 machines, ~1s/appel côté API Sophos =
  les ~12s constatés). Ces lookups sont indépendants entre eux : lancés
  en parallèle (jusqu'à `MAX_PARALLEL_REQUESTS = 10` à la fois). Testé :
  10 hôtes à 0.3s/appel simulé passe de 3.3s (séquentiel) à 0.6s.
- ban/unban (chemin `group`) : les 2-3 appels internes (création/lecture/
  écriture de l'IPHost et du groupe) ne sont pas tous dépendants les uns
  des autres — les paires indépendantes (create+get pour ban ; update
  groupe+delete IPHost pour unban) tournent maintenant en parallèle.
- Pool de connexions HTTP de la session dimensionné pour encaisser les
  requêtes parallèles (`pool_maxsize=10`) sans recréer de connexion à
  chaque lot.

## firewall-xgs/fail2ban 1.4.1 — 2026-08-11

### Changed
- Réutilisation d'une session HTTP (`requests.Session`) entre tous les
  appels API d'une même invocation — évite un handshake TCP/TLS neuf à
  chaque appel.
- ban/unban : traitement de `group` et `iplist` en parallèle (threads)
  quand les deux sont configurés, au lieu de séquentiel — ces deux
  objets étant indépendants sur le firewall, ça réduit d'autant le
  temps total de l'opération. Comportement identique en cas d'échec :
  les deux branches vont à leur terme, erreurs combinées levées ensuite.

## firewall-xgs/fail2ban 1.4.0 — 2026-08-10

### Added
- Support d'un objet `IPHost` de type `IP list` (onglet IP Host → type
  "IP list") en plus ou à la place du `IPHostGroup` existant. Nouvelle
  clé config `iplist` (optionnelle) + option `--iplist`. Au moins une
  des deux clés `group`/`iplist` est requise ; les deux peuvent être
  actives simultanément (ban/unban répercuté sur les deux objets).
  `list` affiche le contenu des deux si configurés.

### Documentation
- README/`--help`/`api.conf.example` mis à jour (nouveau prérequis IP
  list côté firewall, exemples `--iplist`). Champ XML supposé
  (`ListOfIPAddresses`, liste séparée par virgules) non confirmé contre
  la doc API officielle — à valider avec `--debug` en conditions réelles.

## firewall-xgs/fail2ban 1.3.1 — 2026-08-10

### Documentation
- README : exemples de jail passés à `action = sophos-xgs` seul (pas de
  double blocage iptables + Sophos par défaut). Note expliquant comment
  ajouter `%(action_)s` si un blocage local iptables est aussi voulu, et
  comment nettoyer les règles iptables déjà posées par une jail
  reconfigurée (`fail2ban-client reload` / `unban --all`).

## firewall-xgs/fail2ban 1.3.0 — 2026-08-07

### Added
- `filter.d/php-404.conf` : détecte les sondes de scripts PHP inexistants
  (404) — scan de vulnérabilités classique (xmlrpc.php, wp-login.php,
  etc). Une requête PHP en 200 ne matche jamais (code littéral dans le
  failregex). Capture l'IP client réelle en dernier champ de la ligne
  (cas proxy/CDN), avec variante commentée pour logs sans proxy.
- README : exemple de jail complet (`[php-404]`) branché sur l'action
  `sophos-xgs`, et 2 exemples `fail2ban-regex` pour tester le filtre
  (sur une ligne précise, puis sur tout le fichier de log)

### Changed
- `filter.d/php-404.conf` : failregex remplacé par une version testée en
  conditions réelles — 2 patterns distincts (`.php`/`.php7`/`.php8`, et
  chemins WordPress `wp-login`/`wp-admin`/`xmlrpc`/`wp-content`/
  `wp-includes`/`wordpress`), chacun avec `404` littéral pour garantir
  qu'un hit PHP/WordPress en 200 ne matche jamais

## firewall-xgs/fail2ban 1.2.1 — 2026-08-07

### Documentation
- `--help` détaillé : description de chaque option, format complet du
  fichier de config attendu (`[api]` : host, port, username, password,
  verify_ssl, group, prefix), exemples d'appel

## firewall-xgs/fail2ban 1.2.0 — 2026-08-07

### Added
- Action `list` (place de `ban`/`unban`) : affiche les IP actuellement
  bloquées dans le groupe configuré (`ip introuvable` marquée `?` si
  l'objet `IPHost` référencé n'existe plus)
- Préfixe des noms `IPHost` (`f2b_` par défaut) rendu paramétrable via la
  clé `prefix` du fichier de config et surchargeable via `--prefix`

## firewall-xgs/fail2ban 1.1.0 — 2026-08-07

### Added
- `--group` : surcharge en ligne de commande le groupe (`IPHostGroup`)
  défini dans le fichier de config — utile pour tester/gérer plusieurs
  groupes sans dupliquer la config

## firewall-xgs/fail2ban 1.0.1 — 2026-08-07

### Fixed
- Filtre le `RequestsDependencyWarning` (`urllib3`/`chardet` "doesn't match a
  supported version") émis par le `requests` apt (2.25.1) au chargement du
  module, sans toucher aux paquets système ni faire de `pip install`

## firewall-xgs/fail2ban 1.0.0 — 2026-08-07

Première version fonctionnelle, validée sur firewall XGS réel.

### Added
- Initialisation du projet — scope Sophos Firewall (XGS)
- `firewall-xgs/fail2ban/` : script Python + action fail2ban pour bloquer/débloquer
  des IP via un `IPHostGroup` XGS (API XML legacy)
- `--debug` : log des requêtes/réponses XML brutes (mot de passe masqué)
- `parse_status()` : fallback sur `<Error>/<Message>` ou XML brut quand la
  réponse ne contient pas de `<Status>` sous la balise attendue (ex: erreur
  globale type `534 API operations are not allowed from the requester IP
  address`), pour ne jamais remonter un message vide en cas d'échec

### Documentation
- README : ajout du prérequis "IP autorisée" côté compte API (cause du
  code erreur 534 rencontré en test)

# Changelog

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

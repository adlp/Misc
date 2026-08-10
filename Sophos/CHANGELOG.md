# Changelog

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

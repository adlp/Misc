# Changelog

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

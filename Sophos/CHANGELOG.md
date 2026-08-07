# Changelog

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

# Changelog

## [Unreleased]

### Added
- `perl-lib/mailauth.pm` : chemin de `dom2srv.txt` configurable via `MAP_FILE` dans `.env`, garde la valeur par défaut actuelle si absent
- Ajout README.md et CLAUDE.md racine (arborescence `mailqOnOneLine` + `nginx-mua/`)
- `nginx-mua/README.md` : documentation complète (utilité, architecture, config, flux d'auth, déploiement, limites connues)
- `nginx-mua/README.md` : exemples de configuration (`.env`, règles `dom2srv.txt` : routage simple, réécriture login, catch-all, tarpit `KILL`)
- Commentaires dans `nginx.conf`, `conf.d/http.conf`, `conf.d/mail.conf` (rôle des blocs, protocoles par port, portée de `xclient`)
- Commentaires dans `perl-lib/mailauth.pm` (logique de matching/catch-all, sémantique `KILL`, validation POP3 unique tous protocoles, ordre réécriture/validation)

### Changed
- `perl-lib/mailauth.pm` : renomme variables peu parlantes (`@cdc`→`@fields`, `$cont`→`$keepSearching`, `%hash`→`%rules`, `$pop`→`$popClient`, `$mail_server`/`$mail_serpor`→`$popHost`/`$popPort`, `$key`/`$value`→`$envKey`/`$envValue`) — pas de changement de comportement

### Removed
- `nginx-mua/POC/` : brouillon obsolète (docker-compose seul, chemins hôte inexistants), absorbé par le service `smtp` du compose principal

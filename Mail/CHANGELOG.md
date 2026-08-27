# Changelog

## [Unreleased]

### Added
- Ajout README.md et CLAUDE.md racine (arborescence `mailqOnOneLine` + `nginx-mua/`)
- `nginx-mua/README.md` : documentation complète (utilité, architecture, config, flux d'auth, déploiement, limites connues)
- `nginx-mua/README.md` : exemples de configuration (`.env`, règles `dom2srv.txt` : routage simple, réécriture login, catch-all, tarpit `KILL`)
- Commentaires dans `nginx.conf`, `conf.d/http.conf`, `conf.d/mail.conf` (rôle des blocs, protocoles par port, portée de `xclient`)

### Removed
- `nginx-mua/POC/` : brouillon obsolète (docker-compose seul, chemins hôte inexistants), absorbé par le service `smtp` du compose principal

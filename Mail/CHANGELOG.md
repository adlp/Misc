# Changelog

## [Unreleased]

### Added
- `src/Dockerfile-pf` : flush périodique de la queue Postfix (`postqueue -f` en arrière-plan dans `run.sh`, intervalle configurable via `QUEUE_FLUSH_INTERVAL` dans `.env`, défaut `300`s) — force une tentative de livraison immédiate des messages en attente au lieu du seul backoff naturel de Postfix. `docker-compose.yml` : `env_file: .env` ajouté au service `smtp` pour lui exposer la variable. Validé en conditions réelles (image `local/postfix` buildée depuis ce Dockerfile, `relayhost` injoignable) : chaque cycle déclenche bien une nouvelle tentative de connexion sur le message en attente, défaut (300s) et override (`QUEUE_FLUSH_INTERVAL=17`) tous deux vérifiés
- `conf.d/mail.conf` : `xclient on` sur les blocs SMTP (465/587) — appliqué et **validé en conditions réelles de bout en bout** (conteneur `nginx:1.25.3-perl` + vraie image `local/postfix` buildée depuis `src/Dockerfile-pf` + vrai `mailauth.pm`/`dom2srv.txt`) : soumission SMTP réelle acceptée et mise en queue par le vrai Postfix, `Client-IP` identique entre les logs `mailauth.pm` et les logs pf-mua (XCLIENT propage bien la valeur), `error_log` sans erreur. Sûr uniquement parce que la soumission est routée vers pf-mua (qui trust XCLIENT), jamais vers un backend non confirmé
- `perl-lib/dom2srv.txt` : exemple de règle (commentée) routant `SMTP_HOST` vers pf-mua (`172.17.0.1:2535`) ; en-tête mis à jour avec le 9e champ `TARPIT_AFTER` (oublié précédemment)
- `etc+postfix/main.cf` : commentaire sur `relayhost` rappelant de le pointer vers le vrai backend final avant déploiement
- `nginx-mua/README.md` : documente le routage de la soumission via pf-mua (service `smtp` local) comme tampon — évite le risque XCLIENT (Zimbra n'a plus besoin de le supporter, l'IP réelle passe par le `Received:` généré par pf-mua) et réduit les "lost connection after DATA" en découplant le tronçon fragile (client↔nginx-mua) du tronçon interne (pf-mua↔Zimbra) ; pattern maintenant appliqué (voir ci-dessus)
- `etc+postfix/main.cf` : `smtpd_authorized_xclient_hosts = $mynetworks` — fait confiance à XCLIENT depuis les réseaux déjà trustés ; vérifié avec le vrai binaire Postfix qu'il annonce bien `XCLIENT` en EHLO (le backend réel en prod, un Zimbra externe, nécessite sa propre config vérifiée séparément — non concerné par ce changement puisque XCLIENT ne parle plus qu'à pf-mua)
- `nginx-mua/README.md` : section détaillant le mécanisme XCLIENT (déroulé protocolaire, ce qui est visible ou non dans les logs backend une fois activé) et l'alternative PROXY protocol. **Validé en conditions réelles** (conteneur `nginx:1.25.3-perl`, deux backends SMTP factices avec/sans support XCLIENT) que nginx envoie la commande XCLIENT sans condition (ne vérifie pas l'annonce EHLO du backend) et casse toute la session si le backend la rejette — corrige une hypothèse initiale erronée, doc et commentaires `mail.conf` mis à jour en conséquence avec avertissement bloquant
- `conf.d/mail.conf` : commentaires diagnostic sur `xclient` (danger confirmé si un backend non-pf-mua est un jour routé directement) et `timeout` du bloc 587 (ajustable si coupures "lost connection after DATA" viennent du proxy plutôt que du client), reportés dans `README.md`
- `nginx-mua/README.md` : documente le double tag syslog Postfix (`syslog_name` interne via `maillog_file`, puis tag Docker `pf-${SITE}`)
- `perl-lib/mailauth.pm` : coupe-circuit global `TARPIT_ENABLED` (`.env`) pour le tarpit pop3/imap — `0` désactive le mécanisme entièrement quelles que soient les règles `dom2srv.txt` ; absent/autre valeur = activé (défaut, rétrocompatible)
- `perl-lib/mailauth.pm` : tarpit pop3/imap configurable par règle (`TARPIT_AFTER`, 9e champ de `dom2srv.txt`) — `sleep` après N échecs dépassés **par IP cliente** (compteur en mémoire du worker, indépendant de la connexion, remis à zéro sur succès), log `Tarpit delivered` ; désactivé par défaut, rétrocompatible avec les règles sans ce champ. Validé en conditions réelles (conteneur `nginx:1.25.3-perl`, `worker_processes 1`, backend POP3 factice) : délai de 5s exact dès la 3e connexion distincte pour une même IP, log `Tarpit delivered` unique (un doublon trouvé lors du test a été retiré)
- `nginx-mua/fail2ban/filter.d/nginx-mua.conf` + `nginx-mua/fail2ban/jail.d/nginx-mua.conf` : filter/jail proposés pour les lignes `TRACKER-Out` de `mailauth.pm` (même convention que `Zimbra/fail2ban/`)
- `nginx-mua/README.md` : section fail2ban documentant ces fichiers
- `perl-lib/mailauth.pm` : chemin de `dom2srv.txt` configurable via `MAP_FILE` dans `.env`, garde la valeur par défaut actuelle si absent (ajouté à l'exemple `.env` du README)
- Ajout README.md et CLAUDE.md racine (arborescence `mailqOnOneLine` + `nginx-mua/`)
- `nginx-mua/README.md` : documentation complète (utilité, architecture, config, flux d'auth, déploiement, limites connues)
- `nginx-mua/README.md` : exemples de configuration (`.env`, règles `dom2srv.txt` : routage simple, réécriture login, catch-all, tarpit `KILL`)
- Commentaires dans `nginx.conf`, `conf.d/http.conf`, `conf.d/mail.conf` (rôle des blocs, protocoles par port, portée de `xclient`)
- Commentaires dans `perl-lib/mailauth.pm` (logique de matching/catch-all, sémantique `KILL`, validation POP3 unique tous protocoles, ordre réécriture/validation)

### Changed
- `conf.d/mail.conf` : `timeout` du bloc 587 monté de `30s` à `60s` — réduit les "lost connection after DATA" côté backend causées par le proxy (clients mobiles/pièces jointes volumineuses), contrepartie : connexions tenues plus longtemps par worker en cas d'abus délibéré
- `nginx.conf` : `error_log` pointe sur `/dev/stderr` au lieu d'un fichier du conteneur — capté par le driver `syslog` du service `nginx-mua`, les erreurs (ex. timeout proxy 587/465) étaient invisibles jusqu'ici (pas de volume sur `/var/log/nginx`)
- `perl-lib/mailauth.pm` : renomme variables peu parlantes (`@cdc`→`@fields`, `$cont`→`$keepSearching`, `%hash`→`%rules`, `$pop`→`$popClient`, `$mail_server`/`$mail_serpor`→`$popHost`/`$popPort`, `$key`/`$value`→`$envKey`/`$envValue`) — pas de changement de comportement

### Removed
- `nginx-mua/POC/` : brouillon obsolète (docker-compose seul, chemins hôte inexistants), absorbé par le service `smtp` du compose principal

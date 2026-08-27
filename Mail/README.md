# Mail

Outils et infra mail : proxy IMAP/POP3/SMTP multi-domaines (nginx-mua) + utilitaire mailq.

## Contenu

### `mailqOnOneLine`

Script Perl (GPLv3) qui affiche la mailq Postfix compactée en une ligne par message (from, to, sender, subject, date, dernier "Received"), avec filtres et actions.

```
./mailqOnOneLine [--SMTP <regex>] [--FromOrTo <email>|[--From <email> [--To <email>]]] [--Sender <regex>]
                  [--Delete | --Hold | --Send] [--Stat] [--Log] [--help]
```

- `--FromOrTo`/`--From`/`--To`/`--Sender`/`--SMTP` : filtres regex sur les champs (SMTP filtre sur le dernier `Received: from`)
- `--Delete` / `--Hold` / `--Send` : actions `postsuper -d/-h/-r` sur les messages matchés (nécessite un filtre From/To/SMTP)
- `--Stat` : agrège les comptages par champ au lieu de lister les messages
- `--Log` : affiche aussi les 2 dernières lignes de `/var/log/mail.log` par message

### `nginx-mua/`

Stack Docker Compose : reverse-proxy nginx (mail module) devant un backend Postfix.

- **`nginx-mua`** (service) — expose POP3/POP3S/IMAP/IMAPS/SMTP submission (587) publiquement, termine le TLS (certs Let's Encrypt montés), route chaque connexion vers un backend par domaine via `auth_http` → `perl-lib/mailauth.pm`.
- **`smtp`** (service, image `local/postfix`) — Postfix interne, non exposé publiquement (bind sur `172.17.0.1:2535`), utilisé par `mailauth.pm` pour valider les credentials en POP3 avant de renvoyer les infos de routage à nginx.

Routage par domaine : `perl-lib/dom2srv.txt` (une ligne par règle) :

```
MATCH ; SMTP HOST[:PORT] ; POP3 HOST[:PORT] ; IMAP HOST[:PORT] ; LOGIN IN ; LOGIN OUT ; PASS IN ; PASS OUT
```

`MATCH` est une regex testée sur `Auth-User`. `LOGIN/PASS IN→OUT` permettent de réécrire login/mot de passe (regex `s///`) avant transmission au backend. `SMTP HOST = KILL` déclenche un tarpit (sleep répété, logué, sans jamais authentifier) — utile en réponse à du bruteforce.

`mailauth.pm` logue chaque tentative (in/out) en syslog vers `SYSLOG_SERVER:SYSLOG_PORT` avec les tags `TRACKER_F2B`/`TRACKER_LOG` définis dans `.env`, pensés pour être consommés par fail2ban.

Configuration (`.env`) : domaine du site, image nginx, ports exposés, chemins hôte (`DOPATH`, `DOPATHLETS`), config syslog. `.env` présent dans le repo contient des valeurs d'exemple (`mua.example.com`, `8.8.8.8`) — à adapter par déploiement, ne jamais y committer de vraies valeurs.

`etc+postfix/` et `var+spool+postfix/` sont les bind-mounts du conteneur Postfix (`/etc/postfix`, `/var/spool/postfix`). `src/Dockerfile-pf` construit une image qui, au premier démarrage, dézippe un squelette Postfix stock si ces dossiers sont vides — permet de persister la conf hors du conteneur sans avoir à la committer entièrement.

`POC/` : ancien docker-compose autonome pour Postfix seul (préfigure `nginx-mua/docker-compose.yml`, conservé pour référence).

## Voir aussi

- [nginx-mua/README.md](nginx-mua/README.md) — détail du format `dom2srv.txt`

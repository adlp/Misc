# nginx-mua

Proxy mail multi-domaines (IMAP/POP3/SMTP) avec authentification et routage centralisés par domaine, devant des backends mail réels.

## Utilité

Objectif : exposer un point d'entrée unique (un couple IP/ports) qui route chaque connexion IMAP/POP3/SMTP vers le bon backend mail selon le compte utilisé, plutôt que d'exposer chaque backend individuellement. Ça permet :

- **TLS centralisé** : un seul endroit où gérer les certificats (Let's Encrypt), quel que soit le backend réel derrière.
- **Auth centralisée** : la validation des identifiants passe par un point unique (`mailauth.pm`), qui peut réécrire login/mot de passe avant de les transmettre au backend (utile si le backend attend un format différent, ex. alias vs adresse réelle).
- **Routage par règle** : le choix du backend (SMTP/POP3/IMAP) se fait par un motif (regex) sur le nom d'utilisateur, dans un fichier texte (`dom2srv.txt`) — pas de redéploiement pour ajouter/changer un domaine.
- **Anti-bruteforce mutualisé** : chaque tentative d'auth (succès/échec) est loguée en syslog dans un format exploitable par fail2ban, avec un mécanisme de tarpit (`KILL`) pour ralentir un compte/motif ciblé.

## Architecture

Deux services Docker Compose :

```
Client IMAP/POP3/SMTP
        │ (TLS)
        ▼
┌─────────────────────┐        auth_http (HTTP interne, 127.0.0.1:3615/auth)
│  nginx-mua          │───────────────────────────────┐
│ (nginx mail module) │                               ▼
│  ports publics :    │                        ┌───────────────┐
│ 110/995/143/993/587 │                        │  mailauth.pm  │
└─────────┬───────────┘                        │ (perl, module │
          │ proxy (xclient)                    │  nginx perl)  │
          ▼                                    └───────┬───────┘
   backend IMAP/POP3/SMTP                              │ lit dom2srv.txt
   désigné par mailauth.pm                             │ valide via POP3
   (peut être le service `smtp`                        ▼
   local ou un serveur externe)                    backend POP3 (validation)
```

- **`nginx-mua`** (image `nginx:${IMNG}-perl`) : reverse-proxy mail (module `mail` + `ngx_http_perl_module`). Expose publiquement POP3 (110), POP3S (995), IMAP (143), IMAPS (993), SMTP submission (587). Termine le TLS, applique `xclient` pour faire suivre l'IP client réelle au backend.
- **`smtp`** (image `local/postfix`, buildée depuis `src/Dockerfile-pf`) : instance Postfix locale, non exposée publiquement (bind sur `172.17.0.1:2535:25`, réseau Docker uniquement). Sert de backend candidat pour les règles `dom2srv.txt`, et/ou de relais interne — `main.cf` la configure en `relayhost` vers un smart-host externe et en `mynetworks` incluant les plages Docker privées, donc elle relaie sans authentification supplémentaire tout trafic reçu depuis le réseau Docker (la validation ayant déjà été faite en amont par `mailauth.pm`).

## Configuration

### `.env`

Variables lues par `docker-compose.yml` :

| Variable | Rôle |
|---|---|
| `SITE` | nom du conteneur/hostname nginx-mua (= domaine du déploiement) |
| `IMNG` | tag de l'image `nginx:*-perl` à utiliser |
| `EXPOPOP3`, `EXPOPOP3S`, `EXPOIMAP`, `EXPOIMAPS`, `EXPOSMTP`, `EXPOWWW` | bindings publics `IP:PORT` pour chaque service (permet de choisir l'IP d'écoute si la machine en a plusieurs) |
| `DOPATH` | chemin hôte du déploiement (racine des fichiers montés dans le conteneur) |
| `DOPATHLETS` | chemin hôte de `/etc/letsencrypt` (certs) |
| `SYSLOG_SERVER`, `SYSLOG_PORT`, `SYSLOG_PROTO` | destination syslog pour les logs d'auth |
| `TRACKER_F2B`, `TRACKER_LOG` | tags utilisés dans les lignes de log (à filtrer côté fail2ban/log parsing) |

### `dom2srv.txt` (monté dans `perl-lib/`, lu par `mailauth.pm`)

Une règle par ligne, format :

```
MATCH ; SMTP_HOST[:PORT] ; POP3_HOST[:PORT] ; IMAP_HOST[:PORT] ; LOGIN_IN ; LOGIN_OUT ; PASS_IN ; PASS_OUT
```

- `MATCH` : regex testée sur `Auth-User` (le login envoyé par le client). Première ligne qui matche = règle retenue. `*` sert de règle par défaut/fourre-tout.
- `*_HOST[:PORT]` : backend à utiliser pour chaque protocole. Le SMTP cible **ne doit pas demander d'authentification** (nginx a déjà authentifié via POP3, cf. plus bas) — il doit accepter la relève depuis le réseau où tourne nginx-mua.
- `LOGIN_IN`/`LOGIN_OUT` et `PASS_IN`/`PASS_OUT` : paire regex `s/IN/OUT/` appliquée au login et au mot de passe avant transmission au backend (ex. réécrire un alias en adresse réelle). Optionnel — laisser vide si pas de réécriture.
- `SMTP_HOST = KILL` : au lieu de router, déclenche un tarpit — boucle de `sleep(3)` (répétée `POP3_PORT` fois) avec log à chaque itération, sans jamais authentifier. Sert à ralentir/bannir un motif de login ciblé (ex. scanners, comptes bruteforcés) sans bloquer nginx pour les autres clients.
- Caractères interdits dans les mots de passe (alias de compte) : `+ % ^ $ * )`.

### `conf.d/`

- `mail.conf` : bloc `mail {}` nginx — certs TLS, `auth_http` pointant vers `mailauth.pm`, un `server {}` par protocole/port (465 SSL implicite, 587 STARTTLS, 110/995 POP3, 143/993 IMAP).
- `http.conf` : bloc `http {}` minimal, sert uniquement à exposer `mailauth.pm` en local (`127.0.0.1:3615/auth`) via `ngx_http_perl_module` — jamais exposé publiquement.

### `etc+postfix/` et `var+spool+postfix/`

Bind-mounts de `/etc/postfix` et `/var/spool/postfix` du service `smtp`. Persistent la conf et le spool Postfix hors du conteneur. `src/Dockerfile-pf` embarque un squelette Postfix stock (tar.gz) et, au démarrage (`run.sh`), ne le décompresse dans ces dossiers que s'ils sont vides (`test -e master.cf || tar xzf ...`) — donc une fois initialisés, ces dossiers hôte font foi et le squelette embarqué dans l'image n'est plus utilisé. `var+spool+postfix/` (spool de messages, données utilisateur) est exclu du dépôt (`.gitignore`) ; dans `etc+postfix/`, seuls `main.cf`, `header_checks` et `sender_bcc` sont personnalisés, le reste est la config Postfix stock nécessaire au fonctionnement du paquet.

## Fonctionnement (flux d'une connexion)

1. Un client se connecte en IMAP/POP3/SMTP sur un port public de `nginx-mua`. TLS terminé par nginx si applicable.
2. Le client s'authentifie (`Auth-User`/`Auth-Pass`). nginx appelle en interne `auth_http` → `GET /auth` sur `127.0.0.1:3615`, avec les en-têtes `Auth-User`, `Auth-Pass`, `Auth-Protocol` (imap/pop3/smtp), `Client-IP`, etc.
3. `mailauth.pm::handler` :
   - logue la tentative en syslog (tag `TRACKER_F2B-In`).
   - parcourt `dom2srv.txt` ligne par ligne jusqu'à trouver un `MATCH` qui correspond à `Auth-User` (ou retombe sur `*`).
   - si le backend SMTP de la règle vaut `KILL` : bascule en tarpit (boucle de `sleep`, log, jamais d'auth) et s'arrête là.
   - applique la réécriture `LOGIN_IN→LOGIN_OUT` / `PASS_IN→PASS_OUT` si définie sur la règle.
   - **valide les identifiants en se connectant en POP3 au backend `POP3_HOST` de la règle** (`Net::POP3->login`), quel que soit le protocole réellement demandé par le client (IMAP/POP3/SMTP) — POP3 sert de vérification d'auth générique pour les trois. Un login/pass invalide sur ce backend POP3 invalide toute la demande.
   - si l'auth réussit : répond `Auth-Status: OK` + `Auth-Server`/`Auth-Port` pointant vers le backend du protocole demandé dans la règle matchée (pour SMTP, en plus login/pass sont vidés dans la réponse — le backend SMTP ne doit pas redemander d'auth).
   - si l'auth échoue : répond `Auth-Status: Invalid login or password`.
   - logue le résultat (tag `TRACKER_F2B-Out` / `TRACKER_LOG-Log`) — ces lignes sont la matière première pour un filtre fail2ban en aval.
4. nginx reçoit la réponse et, si OK, proxy la connexion (mode `xclient`, IP client réelle transmise) vers `Auth-Server:Auth-Port`.

## Déploiement

1. Copier/adapter `.env` (domaine, IPs/ports d'écoute, chemins `DOPATH*`, config syslog).
2. Renseigner `perl-lib/dom2srv.txt` avec les règles de routage réelles (backends, réécritures éventuelles).
3. S'assurer que `${DOPATHLETS}` (Let's Encrypt) contient un certificat valide pour le nom utilisé dans `conf.d/mail.conf` (`ssl_certificate`/`ssl_certificate_key`).
4. `docker compose up -d` — démarre `smtp` (Postfix, initialise `etc+postfix/`/`var+spool+postfix/` au premier lancement si vides) puis `nginx-mua`.
5. `POC/` contient un compose autonome pour tester le service Postfix seul, indépendamment de nginx-mua.

## Limites connues / points de vigilance

- La validation d'auth passe toujours par POP3, même pour IMAP/SMTP — un backend POP3 down/mal configuré bloque l'auth des trois protocoles pour les comptes de la règle concernée.
- Le mécanisme `KILL` bloque le worker nginx-perl le temps du tarpit (`sleep` synchrone) — dimensionner selon le volume d'attaque attendu.
- Les mots de passe transitent en clair entre `mailauth.pm` et le backend POP3 (pas de TLS sur cette connexion interne) — acceptable seulement si le backend est sur un réseau de confiance (Docker bridge / LAN).
- Voir aussi `../CLAUDE.md` pour les fichiers à ne jamais committer tels quels (`.env`, `dom2srv.txt` réels, spool Postfix).

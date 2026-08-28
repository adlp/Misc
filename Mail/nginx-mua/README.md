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
| `MAP_FILE` | *(optionnel)* chemin du fichier de règles lu par `mailauth.pm`, défaut `/etc/nginx/perl/lib/dom2srv.txt` (= `dom2srv.txt` monté dans `perl-lib/`) |
| `TARPIT_ENABLED` | *(optionnel)* coupe-circuit global du tarpit pop3/imap (`TARPIT_AFTER`, cf. `dom2srv.txt`) : `0` le désactive entièrement, quelles que soient les règles. Absent/autre valeur = activé (défaut) |

Exemple :

```dotenv
SITE=mail.mondomaine.example
IMNG=1.25.3
EXPOPOP3=203.0.113.10:110
EXPOPOP3S=203.0.113.10:995
EXPOIMAP=203.0.113.10:143
EXPOIMAPS=203.0.113.10:993
EXPOSMTP=203.0.113.10:587
EXPOWWW=203.0.113.10:80
DOPATH=/home/_Dockers/mail.mondomaine.example
DOPATHLETS=/etc/letsencrypt
SYSLOG_SERVER=172.17.0.1
SYSLOG_PORT=514
SYSLOG_PROTO=udp
TRACKER_F2B=TRACKER
TRACKER_LOG=MUA-LOG
MAP_FILE=/etc/nginx/perl/lib/dom2srv.txt
TARPIT_ENABLED=1
```

### `dom2srv.txt` (monté dans `perl-lib/`, lu par `mailauth.pm`)

Une règle par ligne, format :

```
MATCH ; SMTP_HOST[:PORT] ; POP3_HOST[:PORT] ; IMAP_HOST[:PORT] ; LOGIN_IN ; LOGIN_OUT ; PASS_IN ; PASS_OUT ; TARPIT_AFTER
```

- `MATCH` : regex testée sur `Auth-User` (le login envoyé par le client). Première ligne qui matche = règle retenue. `*` sert de règle par défaut/fourre-tout.
- `*_HOST[:PORT]` : backend à utiliser pour chaque protocole. Le SMTP cible **ne doit pas demander d'authentification** (nginx a déjà authentifié via POP3, cf. plus bas) — il doit accepter la relève depuis le réseau où tourne nginx-mua.
- `LOGIN_IN`/`LOGIN_OUT` et `PASS_IN`/`PASS_OUT` : paire regex `s/IN/OUT/` appliquée au login et au mot de passe avant transmission au backend (ex. réécrire un alias en adresse réelle). Optionnel — laisser vide si pas de réécriture.
- `SMTP_HOST = KILL` : au lieu de router, déclenche un tarpit — boucle de `sleep(3)` (répétée `POP3_PORT` fois) avec log à chaque itération, sans jamais authentifier. Sert à ralentir/bannir un motif de login ciblé (ex. scanners, comptes bruteforcés) sans bloquer nginx pour les autres clients.
- `TARPIT_AFTER` (9e champ, optionnel) : active un tarpit **pop3/imap** pour cette règle (soumis au coupe-circuit global `TARPIT_ENABLED` de `.env`, ci-dessus — `TARPIT_ENABLED=0` l'emporte sur toute valeur ici). Valeur = nombre d'échecs d'auth **par IP cliente** (`Client-IP`, compté côté `mailauth.pm`, indépendamment de la connexion TCP — un client qui se reconnecte n'échappe donc pas au compteur) au-delà duquel un nouvel échec déclenche un `sleep` (5 s, constante `$tarpitDelay` dans `mailauth.pm`) avant la réponse `Invalid login or password`, avec un log `Tarpit delivered`. Le compteur est remis à zéro pour cette IP dès un succès. Vide/absent = désactivé (comportement par défaut, y compris pour les règles écrites avant l'ajout de ce champ). N'affecte pas SMTP, qui a son propre mécanisme `KILL` ci-dessus.
  - Compteur en mémoire du worker nginx (`%failsByIP` dans `mailauth.pm`), pas de fichier/DB : pas de décroissance temporelle en dehors d'un succès, perdu au reload/redémarrage de nginx, et **pas partagé entre workers** si `worker_processes` > 1 (approximatif dans ce cas — chaque worker a son propre compteur). Suffisant comme dissuasion ; fail2ban (section dédiée) reste l'autorité pour le bannissement IP réel, sur la base des mêmes logs `TRACKER-Out`.
- Caractères interdits dans les mots de passe (alias de compte) : `+ % ^ $ * )`.

Exemple :

```
# MATCH                  ; SMTP HOST         ; POP3 HOST         ; IMAP HOST         ; LOGIN IN                 ; LOGIN OUT ; PASS IN ; PASS OUT ; TARPIT_AFTER

# Routage simple, tous les comptes de exemple1.example vers le même backend
@exemple1\.example$      ; 10.0.10.9:25      ; 10.0.10.9:110      ; 10.0.10.9:143      ;

# Réécriture d'alias : jdupont@exemple2.example -> jean.dupont@exemple2.example côté backend
^jdupont@exemple2\.example$ ; 10.0.20.5:25   ; 10.0.20.5:110      ; 10.0.20.5:143      ; jdupont   ; jean.dupont

# Tarpit SMTP : bloque/ralentit tout login commençant par "admin" (scan/bruteforce), 5 itérations de sleep(3)
^admin                   ; KILL:5            ;                    ;                    ;

# Tarpit pop3/imap : ralentit après 3 échecs sur la même connexion
@exemple3\.example$      ; 10.0.30.5:25      ; 10.0.30.5:110      ; 10.0.30.5:143      ;           ;           ;         ;          ; 3

# Règle par défaut (dernière ligne, sert de filet si aucun MATCH précédent ne correspond)
*                        ; 172.17.0.1:2535   ; 172.17.0.1:110     ; 172.17.0.1:143     ;
```

Sur une règle `KILL`, le port du champ `SMTP_HOST` (ici `KILL:5`) est lu comme le nombre d'itérations du tarpit, pas comme un numéro de port.

### `conf.d/`

- `mail.conf` : bloc `mail {}` nginx — certs TLS, `auth_http` pointant vers `mailauth.pm`, un `server {}` par protocole/port (465 SSL implicite, 587 STARTTLS, 110/995 POP3, 143/993 IMAP).
- `http.conf` : bloc `http {}` minimal, sert uniquement à exposer `mailauth.pm` en local (`127.0.0.1:3615/auth`) via `ngx_http_perl_module` — jamais exposé publiquement.

### `etc+postfix/` et `var+spool+postfix/`

Bind-mounts de `/etc/postfix` et `/var/spool/postfix` du service `smtp`. Persistent la conf et le spool Postfix hors du conteneur. `src/Dockerfile-pf` embarque un squelette Postfix stock (tar.gz) et, au démarrage (`run.sh`), ne le décompresse dans ces dossiers que s'ils sont vides (`test -e master.cf || tar xzf ...`) — donc une fois initialisés, ces dossiers hôte font foi et le squelette embarqué dans l'image n'est plus utilisé. `var+spool+postfix/` (spool de messages, données utilisateur) est exclu du dépôt (`.gitignore`) ; dans `etc+postfix/`, seuls `main.cf`, `header_checks` et `sender_bcc` sont personnalisés, le reste est la config Postfix stock nécessaire au fonctionnement du paquet.

**Logs Postfix** : `main.cf` fixe `maillog_file = /dev/stdout` — Postfix (≥3.4) n'appelle pas `syslog(3)`, il écrit directement sur le stdout du conteneur, mais en reproduisant lui-même le format syslog traditionnel (`<horodatage> <hostname> <programme>[<pid>]: <message>`), un tag par sous-processus (`postfix/smtpd[...]:`, `postfix/qmgr[...]:`, etc.). Ce tag interne vient de `syslog_name` dans `main.cf` — absent ici, donc défaut `postfix`. Le service `smtp` de `docker-compose.yml` renvoie ensuite ce stdout via le driver `syslog` de Docker (`tag: "pf-${SITE}"`), qui enveloppe la ligne (déjà taguée par Postfix) dans son propre envoi syslog. Deux tags superposés côté récepteur : `pf-${SITE}` en tag syslog externe (RFC3164 APP-NAME), `postfix/<sous-processus>` à l'intérieur du message. Pour changer le tag interne Postfix, ajouter `syslog_name = ...` dans `main.cf`.

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

## fail2ban (`fail2ban/`)

`mailauth.pm` envoie chaque tentative en syslog (voir `perl-lib/mailauth.pm`), via `Sys::Syslog`, directement au serveur `SYSLOG_SERVER:SYSLOG_PORT` défini dans `.env` (UDP par défaut) — indépendamment des logs du conteneur nginx-mua lui-même (driver `syslog` de Docker). Le host qui reçoit ces paquets doit avoir un rsyslog en écoute UDP sur ce port :

```
# /etc/rsyslog.d/49-nginx-mua.conf sur le host SYSLOG_SERVER
module(load="imudp")
input(type="imudp" port="514")
```

- `fail2ban/filter.d/nginx-mua.conf` — à copier dans `/etc/fail2ban/filter.d/`
- `fail2ban/jail.d/nginx-mua.conf` — à copier dans `/etc/fail2ban/jail.d/` (adapter `logpath`/`port` au déploiement)

Ligne ciblée par le filtre, tag `TRACKER_F2B` (`TRACKER` dans l'exemple `.env`) suivi de `-Out` : `TRACKER-Out;<auth_ok>;Host;Client-IP;Client-Host;Auth-User;Auth-Protocol;Auth-Method;Auth-Login-Attempt;match;backend-host;backend-port;status`. `auth_ok=0` = échec (login/pass invalide sur le backend POP3, motif matché par une règle `KILL`, ou tarpit `TARPIT_AFTER` pop3/imap délivré — `status` vaut alors `Tarpit delivered`) ; `auth_ok=1` = succès, jamais matché par le filtre.

Le `KILL` de `dom2srv.txt` génère plusieurs lignes `TRACKER-Out;0;...` pour une seule connexion (une par itération du tarpit) — le `maxretry` bas du jail suffit à bannir dès la première tentative sur un motif déjà connu comme malveillant.

Filtre non vérifié avec `fail2ban-regex` sur un serveur réel (juste une regex Python équivalente sur une ligne construite à partir du code, cf. commentaire du filtre) — à revalider avant activation en prod.

## Limites connues / points de vigilance

- La validation d'auth passe toujours par POP3, même pour IMAP/SMTP — un backend POP3 down/mal configuré bloque l'auth des trois protocoles pour les comptes de la règle concernée.
- Le mécanisme `KILL` bloque le worker nginx-perl le temps du tarpit (`sleep` synchrone) — dimensionner selon le volume d'attaque attendu.
- Les mots de passe transitent en clair entre `mailauth.pm` et le backend POP3 (pas de TLS sur cette connexion interne) — acceptable seulement si le backend est sur un réseau de confiance (Docker bridge / LAN).
- Voir aussi `../CLAUDE.md` pour les fichiers à ne jamais committer tels quels (`.env`, `dom2srv.txt` réels, spool Postfix).

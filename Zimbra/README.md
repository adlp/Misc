# zimLocAccZam

Script Python remplaçant avantageusement :
```
/opt/zimbra/bin/zmaccts | grep -v "^zzz_" | grep " lockout "
```

Détecte les comptes Zimbra non actifs (lockout, locked, closed, maintenance, pending...) via LDAP, crée/rouvre/ferme automatiquement des tickets Zammad correspondants, et journalise les lignes d'échec d'authentification associées depuis `audit.log`.

## Fonctionnement

1. Bind LDAP admin (mot de passe récupéré via `zmlocalconfig`).
2. Recherche des comptes avec `zimbraAccountStatus` renseigné et différent de `active`.
3. Pour chaque compte verrouillé :
   - Nouveau (absent du cache) → création ticket Zammad + note avec logs d'échec.
   - Déjà connu mais ticket fermé/disparu → recréation du ticket.
   - Déjà connu et ticket ouvert → rien (sauf `--always`).
4. Pour chaque compte du cache qui n'est plus verrouillé → ticket fermé côté Zammad.
5. Cache persisté en JSON (`cache_file` de la config).

## Configuration

Fichier INI, par défaut `~/.zimLocAccZam` (override avec `-C`) :

```ini
[zammad]
url = https://zammad.example.org
token = xxxxxxxx
group = Support
customer_id = 1
organization_id = 1

[general]
cache_file = /var/lib/zimLocAccZam/cache.json
base_dn = dc=example,dc=org
exclude_regexes = ^zzz_.*, ^test_.*

[sentry]
dsn = https://...  # optionnel
```

## Usage

```bash
zimLocAccZam [-d] [-C fichier_config] [-a] [-s] [-n]
```

- `-d, --debug` : infos complémentaires
- `-C, --config` : chemin config alternatif
- `-a, --always` : affiche aussi les comptes toujours locked (ticket déjà ouvert)
- `-s, --silent` : aucune sortie
- `-n, --no-create` : ne crée pas de ticket (dry-run côté création)

## Codes de sortie

- `0` : exécution normale
- `1` : erreur de configuration (fichier manquant/invalide) ou erreur inattendue
- `2` : erreur d'accès Zimbra/LDAP (bind, recherche, `zmlocalconfig`)
- `3` : erreur d'accès Zammad (requête HTTP en échec)

Aucun cas ne remonte de stack trace brute : message d'erreur clair sur stderr dans tous les cas, enrichi du compte/ticket en cours de traitement quand cette info est connue (ex : `Erreur d'accès Zammad : ... [compte=bob@example.org, ticket=5]`).

## fail2ban (`fail2ban/`)

Filtre + jail pour bannir les IP en échec d'authentification répété sur Zimbra, à partir de `/opt/zimbra/log/audit.log` (couvre webmail/SOAP, IMAP, POP, SMTP auth — tout remonte dans ce log via la catégorie `security`).

- `fail2ban/filter.d/zimbra-audit.conf` — à copier dans `/etc/fail2ban/filter.d/`
- `fail2ban/jail.d/zimbra-audit.conf` — à copier dans `/etc/fail2ban/jail.d/` (adapter `port` aux services réellement exposés)

**Prérequis si Zimbra est derrière un reverse proxy** (nginx Zimbra lui-même, et/ou un reverse proxy externe devant) : sans ça, `ip=` dans `audit.log` est l'IP du proxy, pas celle du client, et le jail bannirait le proxy au lieu de l'attaquant.

1. `zmprov mcf +zimbraMailTrustedIP <IP du nginx zimbra-proxy>` (+ `127.0.0.1` si colocalisé avec mailboxd) → fait apparaître un champ `oip=` (originating IP) dans `audit.log`, que le filtre utilise en priorité.
2. Si un reverse proxy externe est en plus devant le nginx Zimbra : remplacer `$proxy_add_x_forwarded_for` par `$http_x_forwarded_for` dans `/opt/zimbra/conf/nginx/templates/*` puis `zmproxyctl restart` (sinon `audit.log` reçoit une liste d'IP concaténées, rejetée par Zimbra).

Avant d'activer le jail en prod, valider la regex sur le serveur : `fail2ban-regex /opt/zimbra/log/audit.log /etc/fail2ban/filter.d/zimbra-audit.conf` (le format exact des lignes peut varier selon la version de Zimbra).

**Whitelisting** : géré par `ignoreip` dans chaque `jail.d/*.conf` (déjà `127.0.0.1/8 ::1` par défaut), pas par `ignoreregex` (vide à dessein dans les deux filtres). Ajouter les IP admin/monitoring à whitelister dans `ignoreip`, sur les deux jails si besoin. IPv6 entre crochets (`ip=[::1]`) non vérifié — pas de log IPv6 réel disponible pour tester.

Format vérifié pour `http_dav` (vraie ligne de prod) et `imap` (exemples documentés par Zimbra, `ip=` + `oip=` dans le même bloc, `oip=` après `ip=`) — la regex cherche `oip=`/`ip=` n'importe où dans le bloc plutôt que d'ancrer sur l'ordre des champs, donc `pop3`/`soap` (même mécanisme de logging, non vérifiés sur log réel) devraient aussi matcher.

### Scanners web hors-sujet (`fail2ban/filter.d/zimbra-nginx-scanners.conf`)

Deuxième jail, sur `/opt/zimbra/log/nginx.access.log` : bannit les scans de chemins qui n'ont rien à faire sur Zimbra (WordPress, phpMyAdmin, `.env`/`.git` leakés, exploits Laravel/Symfony/Spring, webshells, tout `.php` — Zimbra ne sert jamais de PHP). Une seule requête sur ces chemins suffit à déclencher (`maxretry=2`), contrairement à un jail brute-force classique.

- `fail2ban/filter.d/zimbra-nginx-scanners.conf` → `/etc/fail2ban/filter.d/`
- `fail2ban/jail.d/zimbra-nginx-scanners.conf` → `/etc/fail2ban/jail.d/`

**Prérequis reverse proxy (différent de celui d'`audit.log`)** : ici c'est le module `realip` de nginx lui-même, pas `zimbraMailTrustedIP`. Sans ça, `$remote_addr` dans l'access log est l'IP du reverse proxy, pas du client. Dans un template `/opt/zimbra/conf/nginx/templates/nginx.conf.web.https.default.template` (ou équivalent) :
```
set_real_ip_from <IP_ou_CIDR_du_reverse_proxy>;
real_ip_header X-Forwarded-For;
real_ip_recursive on;
```
puis `zmproxyctl restart`.

Regex basée sur le format `combined` de nginx, corrigée suite à test sur une vraie ligne de prod (IP loggée en `IP:port`, requête parfois en URI absolue plutôt qu'en chemin relatif) — reste à valider avec `fail2ban-regex` en conditions réelles avant activation, comme pour le jail `audit.log`.

### Abus postfix submission (`fail2ban/filter.d/zimbra-postfix-submission.conf`)

Troisième jail, sur les logs postfix (`postfix/submission/smtpd`, port 587 — et `postfix/smtpd` classique par la même occasion, la regex couvre les deux) : bannit deux signatures d'abus vues en prod, indépendantes d'`audit.log`/`nginx.access.log`.

- `improper command pipelining after CONNECT` : protocole cassé juste après connexion (scanner ou smuggling TLS envoyant du binaire brut au lieu de parler SMTP).
- `NOQUEUE: reject: RCPT ... 554 5.7.1 ... Access denied` : rejet host-level (RBL/access map/postscreen, pas un souci de contenu type "User unknown"). Couvre aussi bien le spam/relais classique que les tentatives d'injection de commande (payload base64/Shellshock-like) dans le HELO ou l'adresse — la regex n'a pas besoin de parser le payload, seul le "Access denied" compte.

Pas de règle sur `Anonymous TLS connection established` seule (ligne qui précède parfois le reject) : une négo TLS anonyme n'est pas malveillante en soi, c'est le reject qui suit qui est le signal et qui matche déjà via la deuxième regex.

Pourquoi c'est un signal fiable sur submission (587) : ce service n'accepte que des clients authentifiés (SASL) ; un rejet host-level à ce stade ne peut venir que d'un client qui tente de relayer/injecter sans auth valide, jamais de trafic légitime.

- `fail2ban/filter.d/zimbra-postfix-submission.conf` → `/etc/fail2ban/filter.d/`
- `fail2ban/jail.d/zimbra-postfix-submission.conf` → `/etc/fail2ban/jail.d/`

**⚠️ `logpath` à vérifier avant activation** : contrairement aux deux autres jails, postfix ne logue pas dans `/opt/zimbra/log/` mais via syslog (facility mail). Chemin mis par défaut à `/var/log/zimbra.log` (Debian/Ubuntu) — sur RHEL/CentOS/Rocky c'est `/var/log/maillog`. Confirmer avec `grep 'postfix/submission/smtpd' <fichier candidat>` et adapter `logpath` dans le jail. Comme les deux autres filtres, non testé avec `fail2ban-regex` sur un vrai serveur — à valider avant activation.

Faux positifs vérifiés (simulation Python) : ligne d'acceptation SASL légitime (`client=...sasl_username=...`) et reject "User unknown" (contenu, pas host-level) → aucun des deux ne matche.

**Analyse d'une tentative réelle (2026-09-03)** : un des rejects observés portait un payload d'injection de commande dans le `to=` (pas du Shellshock — un `$(...)` shell générique). Décodage : `id; hostname` exécuté via `eval`, sortie encodée en base64 puis exfiltrée en GET HTTP vers un domaine `*.oast.online` (Interactsh, callback OOB utilisé par les scanners de vuln automatisés type nuclei — pas une attaque ciblée). Postfix rejette au stade RCPT (avant DATA), donc Zimbra/sieve/amavis ne voient jamais cette valeur : le danger n'est pas Zimbra lui-même mais tout outil tiers en aval (milter custom, parseur de logs/bounces, webhook/SIEM) qui interpolerait ce champ brut dans un `eval`/`os.system`/backtick shell au lieu d'un appel paramétré. Recommandations : auditer les scripts custom qui consomment `from=`/`to=`/`helo=` des logs postfix (jamais de shell interpolé, `shlex.quote` ou appel par liste d'arguments sinon) ; en défense en profondeur, bloquer en sortie les domaines `*.oast.online`/`*.burpcollaborator.net`/`*.dnslog.cn` si le firewall le permet. Le jail `zimbra-postfix-submission` ci-dessus bannit déjà l'IP source sur ce type de reject, aucun changement de filtre nécessaire pour ce cas.

## Versions

Voir `CHANGELOG.md`.

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

Avant d'activer le jail en prod, valider la regex sur le serveur : `fail2ban-regex /opt/zimbra/log/audit.log /etc/fail2ban/filter.d/zimbra-audit.conf` (le format exact des lignes peut varier selon la version de Zimbra — non vérifié ici contre un vrai log).

## Versions

Voir `CHANGELOG.md`.

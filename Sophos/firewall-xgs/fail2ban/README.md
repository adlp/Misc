# fail2ban → Sophos Firewall (XGS)

Script d'action fail2ban qui reflète l'état d'une jail fail2ban sur un
Sophos Firewall XGS via son API XML legacy (`webconsole/APIController`),
dans un `IPHostGroup` et/ou une IP list (`IPHost` type `IP list`)
référencé(e) par une règle Deny existante. Au moins un des trois
(`group`, `iplist`, `iplist_prefix` — voir "IP list shardées" plus bas)
doit être configuré, combinables.

**fail2ban est la seule source de vérité** : `ban`/`unban` interrogent
`fail2ban-client status <jail>` et écrasent l'état XGS avec cette liste
complète, sans jamais lire l'état XGS actuel au préalable. Ce n'est donc
plus un ajout/retrait incrémental d'IP côté XGS, mais un push intégral à
chaque événement.

## Fonctionnement

- **ban** : crée l'objet `IPHost` pour la nouvelle IP (`f2b_<ip>`, sans
  vérifier au préalable s'il existe — warning si le firewall répond que
  l'objet existe déjà), puis pousse la liste complète de la jail
  (`fail2ban-client status <jail>`) sur `group` et/ou `iplist`.
- **unban** : repousse la liste complète de la jail (déjà mise à jour par
  fail2ban avant l'appel de ce script) — pas de suppression explicite de
  l'IPHost, c'est le rôle de `vacuum`.
- **list** : affiche les IP actuellement présentes sur XGS (groupe et/ou
  IP list, selon config) — état XGS brut, indépendant de fail2ban.
- **sync** : compare, sans rien modifier, la liste fail2ban actuelle à
  l'état XGS (communes / seulement fail2ban / seulement XGS) — pour voir
  ce qu'un prochain ban/unban changerait avant qu'il n'écrase l'état XGS.
- **vacuum** : supprime les objets `IPHost` `<prefix>*` qui ne sont plus
  membres du groupe (orphelins — ex: `ban` a créé l'objet mais échoué
  avant le push). `--dry-run` affiche la liste sans agir.
- **flush** : vide entièrement `group` puis lance `vacuum` — sans
  interroger fail2ban. N'agit pas sur `iplist`. `--dry-run` affiche ce
  qui serait supprimé sans rien modifier.
- **start** : comme `ban`, mais pour toutes les IP actuellement bannies
  par fail2ban (pas d'IP en argument) — crée l'`IPHost` manquant pour
  chacune avant de pousser la liste complète. À lancer au démarrage du
  service ou si la jail avait déjà des bans avant le premier ban/sync.
- Idempotent : ré-appeler ban/unban/start n'importe quand ne casse rien
  (repush la même liste fail2ban) — et corrige gratuitement toute dérive
  côté XGS au passage (pas de cache d'état, chaque push non dédupliqué
  repousse réellement la liste complète).
- **Dédup par IP en vol** : si un ban/unban est déjà en cours pour une
  IP donnée, tout appel concurrent pour la **même IP** est abandonné
  immédiatement (pas d'attente) — évite un push concurrent redondant
  pendant qu'un premier push (lent) est encore en cours pour cette même
  IP (seule protection contre les appels redondants). Des IP différentes
  restent traitées en parallèle. Contrepartie : un unban(X) arrivant
  pendant qu'un ban(X) est en vol est abandonné sans repush ; reflété au
  prochain événement sur cette IP ou via `sync`/`start`. Jugé négligeable
  en pratique (écart ban→unban >> durée d'un push).
- Session HTTP réutilisée entre les appels API d'une même invocation.
- `list`/`sync` : les IP des membres du groupe sont récupérées en
  parallèle (jusqu'à 10 requêtes simultanées) au lieu d'une par une.
- Verrou inter-process (`/run/lock/sophos-fw-block.lock`) : ban/unban
  prennent un verrou partagé (plusieurs peuvent tourner en même temps,
  cas normal avec fail2ban), vacuum prend un verrou exclusif — évite
  qu'un vacuum supprime un `IPHost` qu'un ban est en train de créer.

Détail de toutes les options et du format de config attendu :
`sophos_fw_block.py --help`

## IP list shardées (`iplist_prefix`)

Alternative à `iplist` (mutuellement exclusifs) pour contourner la
limite Sophos de 1000 entrées par IP list : le script gère une **famille**
de listes nommées `<iplist_prefix><N>` (`Fail2Ban-List-1`,
`Fail2Ban-List-2`, ...), créées automatiquement au fur et à mesure.

- **ban** ajoute l'IP à la liste **active** (la plus récente non pleine).
  Une fois `iplist_max_entries` atteint (défaut/plafond 1000, la seed
  comprise), une nouvelle liste est créée automatiquement (seedée avec
  `iplist_seed_ip` — Sophos exige au moins une adresse pour créer
  l'objet) et un mail est envoyé à `alert_email` si configuré (sinon
  simple warning loggé, jamais fatal pour le ban en cours).
- **unban** retire l'IP de la liste qui la contient — **uniquement
  celle-ci**. Les autres listes ne sont jamais touchées : pas de
  décalage en cascade quand une liste antérieure se vide partiellement.
  Chaque ban/unban ne fait donc jamais plus d'1 appel Sophos d'écriture.
- L'état (quelle IP dans quelle liste) est suivi localement dans
  `/var/lib/sophos-fw-block/shards-*.json` — persistant (pas `/run`),
  c'est la seule trace permettant à `unban` de cibler la bonne liste
  sans tout relire sur Sophos. En cas de perte (rare), `start`
  reconstruit l'état en resynchronisant depuis fail2ban.
- **start** crée la/les listes manquantes et resynchronise (ajoute les
  IP manquantes, retire les IP expirées de leur liste respective).
- **list** affiche l'état shardé local (pas d'appel Sophos — reflète ce
  que le script croit avoir poussé ; en cas de doute, relancer `start`).

Config (section `[api]`) :

```ini
iplist_prefix      = Fail2Ban-List-
iplist_seed_ip     = 192.0.2.1        # placeholder, reste en permanence dans chaque liste
iplist_max_entries = 1000             # optionnel, défaut/plafond 1000
alert_email        = admin@example.com  # optionnel
smtp_host          = localhost        # optionnel, défaut localhost
smtp_port          = 25               # optionnel, défaut 25
```

Une règle firewall par liste (ou une règle référençant chaque liste)
est nécessaire côté Sophos si le blocage doit couvrir toutes les
listes créées au fil du temps — pensez à ajouter la nouvelle liste à
la règle lors de la réception du mail d'alerte.

## Prérequis côté Sophos Firewall

1. **Objet(s) cible(s)** — au choix, ou les deux :
   - **Groupe IP** : créer un `IPHostGroup` (ex: `Fail2Ban-Block`) — vide au
     départ.
   - **IP list** : onglet `IP Host` → créer un objet, type `IP list`
     (ex: `Fail2Ban-List`) — vide au départ.
2. **Règle firewall** : créer une règle Deny (source = groupe et/ou IP list)
   sur la zone concernée (WAN typiquement), placée avant les règles
   d'autorisation.
3. **Utilisateur API** : Backup & Firmware / System Services → créer un
   compte avec profil ayant l'accès API, puis activer l'API sur la zone
   d'administration (System → Administration → Device Access → coche "API"
   sur la zone depuis laquelle ce script appelle le firewall).
4. **IP autorisée** : si l'appel échoue avec `534: API operations are not
   allowed from the requester IP address`, ajouter l'IP de la machine qui
   lance le script à la liste d'accès autorisée du compte API
   (Administration → User → Edit → "Login Restriction for this User").

## Installation

```bash
sudo mkdir -p /etc/sophos-fw
sudo cp api.conf.example /etc/sophos-fw/api.conf
sudo chmod 600 /etc/sophos-fw/api.conf
sudo vim /etc/sophos-fw/api.conf   # host, username, password, group, jail

pip3 install -r requirements.txt   # ou: apt install python3-requests

sudo cp sophos_fw_block.py /usr/local/bin/
sudo chmod +x /usr/local/bin/sophos_fw_block.py

sudo cp action.d/sophos-xgs.conf /etc/fail2ban/action.d/
```

Dans `jail.local` :

```ini
[sshd]
enabled = true
action  = sophos-xgs
```

`action = sophos-xgs` seul : blocage uniquement côté Sophos (aucune règle
iptables locale ajoutée). Pour bloquer aussi localement (iptables) en plus
du firewall Sophos, ajouter `%(action_)s` :

```ini
action = %(action_)s
          sophos-xgs
```

Si des jails existantes remplissent déjà iptables inutilement (action
`%(action_)s` sans besoin de blocage local), retirer `%(action_)s` de
`action`, `reload` fail2ban, puis nettoyer les règles déjà posées :

```bash
sudo fail2ban-client reload
sudo fail2ban-client unban --all   # si des règles iptables persistent
```

### Exemple : sonde de scripts PHP inexistants (404)

`filter.d/php-404.conf` détecte les requêtes `GET/POST/HEAD` vers un
`*.php`/`*.php7`/`*.php8`, ou vers un chemin WordPress classique
(`wp-login`, `wp-admin`, `xmlrpc`, `wp-content`, `wp-includes`,
`wordpress`), qui répondent `404`. Une requête PHP/WordPress en `200` ne
matche jamais — le code `404` est littéral dans chacun des deux
failregex.

```bash
sudo cp filter.d/php-404.conf /etc/fail2ban/filter.d/
```

```ini
[php-404]
enabled  = true
port     = http,https
filter   = php-404
logpath  = /var/log/nginx/access.log
action   = sophos-xgs
maxretry = 3
findtime = 600
bantime  = 86400
```

Le filtre attend l'IP client réelle en dernier champ de la ligne (cas
courant derrière un proxy/CDN qui l'ajoute en fin de log) — voir le
commentaire dans `filter.d/php-404.conf` pour la variante sans proxy.

Tester le filtre avec `fail2ban-regex`, sans toucher à fail2ban :

```bash
# sur une ligne précise
fail2ban-regex '192.168.2.1 - - [06/Aug/2026:13:53:05 +0000] "GET /xmlrpc.php?rsd HTTP/1.1" 404 5140 "-" "Mozilla/5.0" "34.22.236.107"' filter.d/php-404.conf

# sur tout le fichier de log
fail2ban-regex /var/log/nginx/access.log filter.d/php-404.conf
```

`fail2ban-server` tourne en root : le script lit `/etc/sophos-fw/api.conf`
(root:root, 600) sans souci de permissions.

## Test manuel

```bash
/usr/local/bin/sophos_fw_block.py ban 203.0.113.5
/usr/local/bin/sophos_fw_block.py unban 203.0.113.5
```

Ajouter `--debug` pour logger les requêtes/réponses XML brutes (mot de
passe masqué) — utile pour diagnostiquer une erreur API (ex: code `534`
ci-dessus).

Ajouter `--debug-timing` pour logger la durée de chaque appel API, de
`fail2ban-client status <jail>`, de chaque connexion TCP+TLS établie
(une fois par connexion mise en pool, réutilisée ensuite), de chaque
tâche parallèle, et le temps total de l'action — utile pour situer où
passe le temps (ex: en usage réel, un push `iplist` de quelques IP prend
~5s, entièrement côté traitement Sophos — connexion et fail2ban-client
étant chacun de l'ordre de quelques ms) :

```bash
/usr/local/bin/sophos_fw_block.py ban 203.0.113.5 --debug-timing
```

Ajouter `--group <nom>` pour surcharger ponctuellement le groupe défini
dans la config (ex: tester sur un groupe de test avant bascule en prod) :

```bash
/usr/local/bin/sophos_fw_block.py ban 203.0.113.5 --group Fail2Ban-Test
```

Ajouter `--iplist <nom>` pour surcharger ponctuellement l'IP list définie
dans la config :

```bash
/usr/local/bin/sophos_fw_block.py ban 203.0.113.5 --iplist Fail2Ban-List
```

Ajouter `--prefix <préfixe>` pour surcharger ponctuellement le préfixe
des noms `IPHost` défini dans la config (défaut : `f2b_`, utilisé
seulement avec `group`).

Ajouter `--jail <nom>` pour surcharger ponctuellement la jail fail2ban
définie dans la config (requis pour ban/unban/sync).

Lister les IP actuellement bloquées dans le groupe (pas d'IP à fournir) :

```bash
/usr/local/bin/sophos_fw_block.py list
```

Comparer fail2ban et XGS sans rien modifier — utile avant le premier
déploiement (si la jail a déjà des bans en cours) ou pour vérifier
l'absence de dérive :

```bash
/usr/local/bin/sophos_fw_block.py sync
```

Nettoyer les objets `IPHost` orphelins (préfixés mais plus dans le
groupe) — nécessite `group` configuré et un préfixe non vide :

```bash
/usr/local/bin/sophos_fw_block.py vacuum --dry-run   # affiche sans agir
/usr/local/bin/sophos_fw_block.py vacuum             # supprime
```

À lancer en cron périodique si besoin (ex: quotidien) plutôt qu'à chaque
ban — le verrou exclusif empêche toute collision avec un ban/unban en cours.

Tout vider (groupe + IPHost orphelins), sans toucher fail2ban ni iplist —
utile pour repartir d'un état propre côté XGS :

```bash
/usr/local/bin/sophos_fw_block.py flush --dry-run   # affiche sans agir
/usr/local/bin/sophos_fw_block.py flush             # vide + nettoie
```

Resynchroniser toutes les IP actuellement bannies (démarrage du service,
ou jail avec des bans déjà en cours) :

```bash
/usr/local/bin/sophos_fw_block.py start
```

Logs envoyés sur syslog (tag `sophos-fw-block`) + stderr (visible dans les
logs fail2ban en cas d'échec, exit code 1).

## Limites connues

- `verify_ssl = false` par défaut (certificat webadmin souvent self-signed).
  Passer à `true` + fournir un cert de confiance si le firewall est joignable
  sur un réseau non fiable.
- IPv4 uniquement pour l'instant (`HostType=IP`, `IPFamily=IPv4`).
- IP list : le script suppose le champ `<ListOfIPAddresses>` (liste
  d'adresses séparées par des virgules) pour un `IPHost` de type `IP
  list`. Non confirmé contre la doc API officielle — à valider avec
  `--debug` sur le premier `ban` réel ; en cas d'erreur `parse_status`
  affichera le XML brut retourné par le firewall pour ajuster si besoin.
- `Set operation="add"` sur un `IPHostGroup` existant échoue toujours
  (501 avec un objet fictif, 502 avec un objet réel — l'entité en conflit
  est le groupe lui-même, pas le membre). `ban`/`unban` utilisent
  `set_group_hosts()` (Get puis Set complet) pour toute écriture du
  groupe. `Remove` avec une `HostList` (retrait ciblé d'un membre) est
  confirmé dangereux — vide tout le groupe au lieu du seul membre visé,
  voir `test_group_merge.py`. Ni l'un ni l'autre n'est utilisé.
- `vacuum` ne détecte l'usage d'un `IPHost` que via son appartenance au
  groupe configuré — un objet `<prefix>*` référencé directement par une
  autre règle firewall (sans passer par ce groupe) ne serait pas détecté
  comme utilisé et serait supprimé à tort. Cas non couvert : `vacuum`
  n'est prévu que pour nettoyer les orphelins issus du flux ban/unban de
  ce script.
- Premier déploiement sur une jail ayant déjà des IP bannies : lancer
  `start` (crée l'IPHost manquant pour chaque IP déjà bannie et pousse la
  liste complète) — `sync` avant permet de voir l'écart au préalable.
- `fail2ban-client status <jail>` doit renvoyer une ligne `Banned IP
  list:` — format observé sur les versions testées ; `get_banned_ips()`
  lève une erreur explicite si absent plutôt que de deviner.

## Note : warning `RequestsDependencyWarning`

Le paquet `python3-requests` d'apt (2.25.1) émet parfois un warning au
chargement si une version d'`urllib3`/`chardet` plus récente que celle
attendue est présente sur le système. Ce warning est filtré directement
dans le script (aucune action requise, pas de `pip install`).

## Bonus : blocage local nginx (`nginx_fw_block.py`)

Script indépendant (aucune dépendance à `sophos_fw_block.py` ni à
Sophos — stdlib Python uniquement) qui maintient un fichier geo-map
nginx local listant les IP bannies, et déclenche un reload nginx quand
ce fichier change. Utile en complément ou à la place de Sophos :
purement local, un reload nginx (~instantané) au lieu des 5-8s observées
côté API Sophos (voir plus haut). Peut tourner en parallèle de
`sophos-xgs` sur la même jail (les deux actions dans `action =`).

**`ban`/`unban` ne dépendent pas de fail2ban** : ils lisent/modifient/
réécrivent `map_file` directement (I/O locale uniquement) — ajoute/retire
juste l'IP concernée, idempotent (aucune écriture ni reload si l'IP est
déjà dans l'état voulu). Seule l'action `start` interroge
`fail2ban-client status <jail>` pour régénérer le fichier en entier
(bootstrap ou resynchro complète) ; `jail` n'est donc requis que pour
`start`. Verrou non-bloquant par IP identique à `sophos_fw_block.py`
2.3.1 : un ban/unban déjà en cours pour une IP fait abandonner
immédiatement tout appel concurrent pour cette même IP.

### Installation

```bash
sudo mkdir -p /etc/nginx-fw-block
sudo cp nginx.conf.example /etc/nginx-fw-block/config.conf
sudo vim /etc/nginx-fw-block/config.conf   # jail, map_file, reload_cmd

sudo cp nginx_fw_block.py /usr/local/bin/
sudo chmod +x /usr/local/bin/nginx_fw_block.py

sudo cp action.d/nginx-local.conf /etc/fail2ban/action.d/
```

Dans `jail.local` (combinable avec `sophos-xgs`) :

```ini
[php-404]
enabled = true
action  = sophos-xgs
          nginx-local
```

Côté nginx (voir `nginx_fw_block.py --help` pour le format exact du
fichier généré) :

```nginx
geo $remote_addr $is_banned {
    default 0;
    include /etc/nginx/banned_ips.conf;
}

server {
    if ($is_banned) { return 403; }   # global

    location /wp-login.php {
        if ($is_banned) { return 403; }   # ou ciblé sur une route précise
    }
}
```

Si le trafic est proxysé (IP réelle dans un header, pas `$remote_addr`),
configurer `ngx_http_realip_module` en amont :

```nginx
set_real_ip_from  <IP/CIDR du proxy ou CDN>;
real_ip_header    X-Forwarded-For;
```

### Test manuel

```bash
/usr/local/bin/nginx_fw_block.py start           # régénère tout depuis fail2ban
/usr/local/bin/nginx_fw_block.py list             # affiche le fichier local actuel
/usr/local/bin/nginx_fw_block.py ban 203.0.113.5 --debug-timing
```

`reload_cmd` est une commande shell arbitraire définie dans la config —
adapter selon le déploiement (`nginx -s reload` en bare metal,
`docker exec <conteneur> nginx -s reload` en Docker).

### Limites connues

- `reload_cmd` ne s'exécute que si `ban`/`unban` change réellement le
  contenu de `map_file` (idempotent) — pas de reload inutile.
- `ban`/`unban` ne connaissent que `map_file`, pas fail2ban : si le
  fichier est modifié/supprimé manuellement, ou après un décalage quelconque,
  relancer `start` pour resynchroniser depuis fail2ban (source de vérité
  pour cette action précise uniquement).
- Pas d'équivalent `vacuum`/`sync` : pas d'objet firewall persistant à
  nettoyer (contrairement aux `IPHost` Sophos) — juste un fichier plat.

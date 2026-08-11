# fail2ban → Sophos Firewall (XGS)

Script d'action fail2ban qui bloque/débloque des IP sur un Sophos Firewall
XGS via son API XML legacy (`webconsole/APIController`), en ajoutant/retirant
l'IP d'un `IPHostGroup` et/ou d'une IP list (`IPHost` type `IP list`)
référencé(e) par une règle Deny existante. Au moins un des deux doit être
configuré, les deux peuvent l'être en même temps.

## Fonctionnement

- **ban** :
  - si `group` configuré : crée un objet `IPHost` pour l'IP (`f2b_<ip>`)
    sans vérifier au préalable s'il existe déjà (un warning est loggé si
    le firewall répond que l'objet existe), puis l'ajoute au groupe, de
    même sans lecture préalable de la liste (warning si déjà membre).
  - si `iplist` configuré : ajoute l'IP directement dans la liste
    d'adresses de l'IP list.
- **unban** : retire l'IP du groupe et supprime l'objet `IPHost` — un
  warning est loggé si l'IP était déjà absente du groupe ou si l'objet
  `IPHost` n'existait déjà plus (au lieu d'une erreur).
- **list** : affiche les IP actuellement bloquées (groupe et/ou IP list,
  selon config).
- **vacuum** : supprime les objets `IPHost` `<prefix>*` qui ne sont plus
  membres du groupe (orphelins — ex: après un `unban` interrompu avant la
  suppression de l'objet). `--dry-run` affiche la liste sans agir.
- Idempotent : ré-appeler ban/unban sur une IP déjà (dés)activée ne casse rien.
- group et iplist (si les deux configurés) traités en parallèle, et
  session HTTP réutilisée entre les appels API d'une même invocation.
- `list` : les IP des membres du groupe sont récupérées en parallèle
  (jusqu'à 10 requêtes simultanées) au lieu d'une par une — c'était le
  vrai facteur dominant sur un groupe de plusieurs machines (ex: ~12s
  pour 10 hôtes en séquentiel).
- Verrou inter-process (`/run/lock/sophos-fw-block.lock`) : ban/unban
  prennent un verrou partagé (plusieurs peuvent tourner en même temps,
  cas normal avec fail2ban), vacuum prend un verrou exclusif — évite
  qu'un vacuum supprime un `IPHost` qu'un ban est en train de créer.

Détail de toutes les options et du format de config attendu :
`sophos_fw_block.py --help`

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
sudo vim /etc/sophos-fw/api.conf   # host, username, password, group

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
chaque connexion TCP+TLS établie (une fois par connexion mise en pool,
réutilisée ensuite), de chaque tâche parallèle, et le temps total de
l'action — utile pour situer où passe le temps si un ban/unban/list
reste lent malgré le parallélisme client (ex: API Sophos qui
sérialise les requêtes côté serveur, indépendamment du client) :

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

Lister les IP actuellement bloquées dans le groupe (pas d'IP à fournir) :

```bash
/usr/local/bin/sophos_fw_block.py list
```

Nettoyer les objets `IPHost` orphelins (préfixés mais plus dans le
groupe) — nécessite `group` configuré et un préfixe non vide :

```bash
/usr/local/bin/sophos_fw_block.py vacuum --dry-run   # affiche sans agir
/usr/local/bin/sophos_fw_block.py vacuum             # supprime
```

À lancer en cron périodique si besoin (ex: quotidien) plutôt qu'à chaque
ban — le verrou exclusif empêche toute collision avec un ban/unban en cours.

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
- `ban` tente d'ajouter le membre au groupe en 1 appel
  (`Set operation="add"`, sans lire la liste au préalable) ; testé en
  échec avec un objet fictif (501, voir `test_group_merge.py`), pas
  encore confirmé avec un objet réel. Repli automatique et sûr sur le
  chemin get+set si ça échoue, donc pas de risque, mais le gain de temps
  espéré n'est pas garanti tant que ce n'est pas observé en usage réel.
- `vacuum` ne détecte l'usage d'un `IPHost` que via son appartenance au
  groupe configuré — un objet `<prefix>*` référencé directement par une
  autre règle firewall (sans passer par ce groupe) ne serait pas détecté
  comme utilisé et serait supprimé à tort. Cas non couvert : `vacuum`
  n'est prévu que pour nettoyer les orphelins issus du flux ban/unban de
  ce script.
- `Remove` sur un `IPHostGroup` avec une `HostList` (retrait ciblé d'un
  membre) est confirmé dangereux — vide tout le groupe au lieu du seul
  membre visé, voir `test_group_merge.py`. Jamais utilisé dans le script.

## Note : warning `RequestsDependencyWarning`

Le paquet `python3-requests` d'apt (2.25.1) émet parfois un warning au
chargement si une version d'`urllib3`/`chardet` plus récente que celle
attendue est présente sur le système. Ce warning est filtré directement
dans le script (aucune action requise, pas de `pip install`).

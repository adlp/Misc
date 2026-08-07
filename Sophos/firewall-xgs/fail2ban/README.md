# fail2ban → Sophos Firewall (XGS)

Script d'action fail2ban qui bloque/débloque des IP sur un Sophos Firewall
XGS via son API XML legacy (`webconsole/APIController`), en ajoutant/retirant
l'IP d'un `IPHostGroup` référencé par une règle Deny existante.

## Fonctionnement

- **ban** : crée un objet `IPHost` pour l'IP (`f2b_<ip>`), l'ajoute au groupe.
- **unban** : retire l'IP du groupe, supprime l'objet `IPHost`.
- **list** : affiche les IP actuellement bloquées dans le groupe.
- Idempotent : ré-appeler ban/unban sur une IP déjà (dés)activée ne casse rien.

Détail de toutes les options et du format de config attendu :
`sophos_fw_block.py --help`

## Prérequis côté Sophos Firewall

1. **Groupe IP** : créer un `IPHostGroup` (ex: `Fail2Ban-Block`) — vide au départ.
2. **Règle firewall** : créer une règle Deny (source = ce groupe) sur la zone
   concernée (WAN typiquement), placée avant les règles d'autorisation.
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
action  = %(action_)s
          sophos-xgs
```

### Exemple : sonde de scripts PHP inexistants (404)

`filter.d/php-404.conf` détecte les requêtes `GET/POST/HEAD` vers un
`*.php` qui répondent `404` (scan de vulnérabilités classique :
`xmlrpc.php`, `wp-login.php`, etc). Une requête PHP en `200` ne matche
jamais — le code est littéral dans le failregex.

```bash
sudo cp filter.d/php-404.conf /etc/fail2ban/filter.d/
```

```ini
[php-404]
enabled  = true
port     = http,https
filter   = php-404
logpath  = /var/log/nginx/access.log
action   = %(action_)s
           sophos-xgs
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

Ajouter `--group <nom>` pour surcharger ponctuellement le groupe défini
dans la config (ex: tester sur un groupe de test avant bascule en prod) :

```bash
/usr/local/bin/sophos_fw_block.py ban 203.0.113.5 --group Fail2Ban-Test
```

Ajouter `--prefix <préfixe>` pour surcharger ponctuellement le préfixe
des noms `IPHost` défini dans la config (défaut : `f2b_`).

Lister les IP actuellement bloquées dans le groupe (pas d'IP à fournir) :

```bash
/usr/local/bin/sophos_fw_block.py list
```

Logs envoyés sur syslog (tag `sophos-fw-block`) + stderr (visible dans les
logs fail2ban en cas d'échec, exit code 1).

## Limites connues

- `verify_ssl = false` par défaut (certificat webadmin souvent self-signed).
  Passer à `true` + fournir un cert de confiance si le firewall est joignable
  sur un réseau non fiable.
- IPv4 uniquement pour l'instant (`HostType=IP`, `IPFamily=IPv4`).

## Note : warning `RequestsDependencyWarning`

Le paquet `python3-requests` d'apt (2.25.1) émet parfois un warning au
chargement si une version d'`urllib3`/`chardet` plus récente que celle
attendue est présente sur le système. Ce warning est filtré directement
dans le script (aucune action requise, pas de `pip install`).

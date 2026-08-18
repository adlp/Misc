# nginx — blocage IP + tarpit (companion de `nginx_fw_block.py`)

Snippets nginx pour bloquer (en fait : ralentir volontairement, voir plus
bas) les IP bannies par fail2ban, alimentées via `../nginx_fw_block.py`
(qui écrit `badguys.map` et recharge nginx à chaque ban/unban).

## Fichiers

| Fichier | Contexte d'inclusion | Rôle |
|---|---|---|
| `geo-badguys.conf` | `http {}` | Définit `$is_banned` depuis `badguys.map`, et `$tarpit_rate` (débit selon `$is_banned`) |
| `realip.conf` | `http {}` (ou `server {}`) | Restaure la vraie IP client si nginx est derrière un reverse-proxy applicatif (ex: Sophos XGS WAF) — **optionnel, seulement si concerné** |
| `tarpit-server.conf` | `server {}`, avant toute `location` | Applique le ralentissement et empêche toute IP bannie d'atteindre un backend réel |
| `tarpit/payload.txt` | — | Contenu servi aux IP bannies (texte de padding, ~3000 octets) |

## Pourquoi ralentir plutôt que rejeter (403) ?

Un rejet rapide (403) coûte quasi rien à un attaquant — il retente
immédiatement. Servir une réponse **lente** (tarpit) immobilise sa
connexion pendant la durée configurée (`taille du payload / débit`),
ce qui ralentit concrètement un scan ou un brute-force automatisé.
Contrepartie : consomme une connexion/worker nginx pendant ce temps
(acceptable pour du trafic déjà identifié comme malveillant, en volume
limité — pas une solution à généraliser à tout le trafic).

## Installation

1. Copier les fichiers :
   ```bash
   sudo cp geo-badguys.conf tarpit-server.conf /etc/nginx/include.d/
   sudo mkdir -p /etc/nginx/tarpit
   sudo cp tarpit/payload.txt /etc/nginx/tarpit/payload.txt
   ```
   (adapter les chemins à ton bind-mount Docker si nginx tourne en
   conteneur — ex: `/home/_Dockers/nginx/data/include.d/` côté hôte pour
   `/etc/nginx/include.d/` côté conteneur, comme pour `badguys.map`)

2. Dans `nginx.conf`, inclure `geo-badguys.conf` **au niveau `http {}`**
   (pas `server{}`/`location{}` — `geo`/`map` n'y sont pas autorisés,
   erreur `"geo" directive is not allowed here` sinon) :
   ```nginx
   http {
       ...
       include /etc/nginx/include.d/geo-badguys.conf;

       # seulement si nginx est derrière un reverse-proxy applicatif
       # (voir realip.conf pour savoir si c'est le cas) :
       include /etc/nginx/include.d/realip.conf;

       server {
           listen 443 ssl;
           server_name exemple.tld;
           ...

           include /etc/nginx/include.d/tarpit-server.conf;

           location / {
               proxy_pass http://backend_reel;
               ...
           }
       }
   }
   ```

3. `nginx -t` puis reload (ou laisser `nginx_fw_block.py` s'en charger au
   prochain ban — mais teste `nginx -t` manuellement au moins une fois
   après cette installation).

## `realip.conf` : quand c'est nécessaire

Si nginx est en frontal direct d'Internet (pas de reverse-proxy en
amont), **ne pas inclure** `realip.conf` — `$remote_addr` est déjà la
bonne IP.

Si un équipement en amont (Sophos XGS en mode Web Server Protection/WAF,
CDN, etc.) termine la connexion et se reconnecte à nginx avec sa propre
IP source, `$remote_addr` vaut l'IP de cet équipement, pas celle du
client réel — `geo-badguys.conf` ne matcherait jamais la bonne IP sans
correction.

Pour vérifier si tu es dans ce cas et quel header contient la vraie IP,
logguer temporairement les headers candidats :
```nginx
log_format debug_headers '$remote_addr - XFF:"$http_x_forwarded_for" '
                          'XRIP:"$http_x_real_ip"';
```
Comparer à l'IP publique réellement utilisée pour un test externe, puis
renseigner `set_real_ip_from`/`real_ip_header` dans `realip.conf` en
conséquence (l'IP interne de l'équipement amont + le nom du header
confirmé).

## Réglages

- **Débit** : `map $is_banned $tarpit_rate { ... }` dans
  `geo-badguys.conf` — défaut `10` (octets/s). Plus bas = plus lent.
- **Durée du tarpit** ≈ taille de `tarpit/payload.txt` ÷ débit. Fourni à
  ~3000 octets ⇒ ~5 min à 10 octets/s. Régénérer avec une taille
  différente si besoin :
  ```bash
  python3 -c "
  line = 'Please wait, your request is being processed. Do not close this connection.\n'
  target = 3000  # <-- ajuster (octets)
  print((line * (target // len(line) + 1))[:target], end='')
  " > payload.txt
  ```
  Un payload trop petit part quasi instantanément quel que soit le
  débit configuré (tient dans un seul paquet TCP) — rester au-dessus de
  quelques centaines d'octets pour un effet perceptible.
- **Code HTTP retourné** : `403` par défaut dans `tarpit-server.conf`
  (lignes `return` et `error_page`, à modifier ensemble avec le même
  code). Codes usuels : `403`, `429`, `503`. Éviter `444` (coupe la
  connexion sans réponse chez nginx — contraire au principe du tarpit).

## Test

```bash
# temps de réponse observé pour une IP bannie (doit être lent, proche
# de taille_payload/débit) :
time curl -s -o /dev/null https://exemple.tld/  # depuis l'IP bannie

# confirme que le backend réel n'est jamais contacté pour cette IP :
# rien ne doit apparaître dans les logs applicatifs du backend pour
# cette requête, seulement dans les logs nginx (accès + $is_banned).
```

## Débogage

```bash
# conf réellement chargée par nginx (compare avec les fichiers ci-dessus) :
docker exec nginx nginx -T | grep -A5 'geo \$remote_addr'

# contenu actuel de la liste de bannis :
docker exec nginx cat /etc/nginx/include.d/badguys.map
# ou, sans passer par le conteneur :
/usr/local/bin/nginx_fw_block.py list --config /etc/nginx-fw-block/config.conf
```

Si une IP dans `badguys.map` n'est toujours pas ralentie : vérifier dans
l'ordre — `realip.conf` bien inclus et header confirmé (le plus
fréquent), conf effectivement rechargée (`nginx -T` à jour), format des
lignes de `badguys.map` (`1.2.3.4 1;` exactement), et que
`tarpit-server.conf` est bien inclus **avant** les `location` du
`server{}` testé.

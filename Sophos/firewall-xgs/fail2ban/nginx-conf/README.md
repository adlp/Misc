# nginx — blocage IP + tarpit (companion de `nginx_fw_block.py`)

Snippets nginx pour bloquer (en fait : ralentir volontairement, voir plus
bas) les IP bannies par fail2ban, alimentées via `../nginx_fw_block.py`
(qui écrit `badguys.map` et recharge nginx à chaque ban/unban).

## Fichiers

| Fichier | Contexte d'inclusion | Rôle |
|---|---|---|
| `geo-badguys.conf` | `http {}` | Définit `$is_banned` depuis `badguys.map`, et `$tarpit_rate` (débit selon `$is_banned`) |
| `realip.conf` | `http {}` (ou `server {}`) | Restaure la vraie IP client si nginx est derrière un reverse-proxy applicatif (ex: Sophos XGS WAF) — **optionnel, seulement si concerné** |
| `tarpit-server.conf` | `server {}`, avant toute `location` | Applique le ralentissement et empêche toute IP bannie d'atteindre un backend réel — payload embarqué directement dans le fichier (voir plus bas pourquoi) |
| `ratelimit.conf` | `http {}` | Définit `$ratelimit_key` (vide pour les IP RFC1918 exemptées) et la zone `limit_req_zone` |
| `ratelimit-server.conf` | `server {}`, avant toute `location` | Applique le rate-limiting — indépendant du tarpit, protège contre les rafales trop rapides pour que fail2ban réagisse à temps |

`tarpit/payload.txt` n'existe plus séparément : une tentative de le servir via
`alias`/`error_page` (code HTTP personnalisable) s'est révélée non fiable
dans certains environnements nginx (voir section suivante) — le payload est
maintenant un littéral directement dans `return CODE "...";`.

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
   sudo cp geo-badguys.conf tarpit-server.conf ratelimit.conf ratelimit-server.conf /etc/nginx/include.d/
   ```
   (adapter les chemins à ton bind-mount Docker si nginx tourne en
   conteneur — ex: `/home/_Dockers/nginx/data/include.d/` côté hôte pour
   `/etc/nginx/include.d/` côté conteneur, comme pour `badguys.map`)

2. Dans `nginx.conf`, inclure `geo-badguys.conf` et `ratelimit.conf`
   **au niveau `http {}`** (pas `server{}`/`location{}` — `geo`/`map`/
   `limit_req_zone` n'y sont pas autorisés, erreur `"geo" directive is
   not allowed here` sinon) :
   ```nginx
   http {
       ...
       include /etc/nginx/include.d/geo-badguys.conf;
       include /etc/nginx/include.d/ratelimit.conf;

       # seulement si nginx est derrière un reverse-proxy applicatif
       # (voir realip.conf pour savoir si c'est le cas) :
       include /etc/nginx/include.d/realip.conf;

       server {
           listen 443 ssl;
           server_name exemple.tld;
           ...

           include /etc/nginx/include.d/tarpit-server.conf;
           include /etc/nginx/include.d/ratelimit-server.conf;

           location / {
               proxy_pass http://backend_reel;
               ...
           }
       }
   }
   ```
   (`tarpit-server.conf` et `ratelimit-server.conf` sont indépendants —
   inclure l'un, l'autre, ou les deux selon le besoin)

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

## Pourquoi `return CODE "texte";` et pas `alias`/`error_page` ?

Version testée initialement : `location = /__tarpit__ { alias
payload.txt; }`, atteinte via `error_page CODE = /__tarpit__;` (pour
choisir le code HTTP tout en gardant le payload dans un fichier séparé).
Constat en conditions réelles (nginx 1.31.3, build Debian officiel,
sans module tiers) : `error_page` ne redirige **jamais** en interne vers
la location cible — vérifié avec/sans `if`, avec/sans `internal`,
plusieurs codes (dont un sans collision possible), et même pour un 404
généré nativement par nginx (pas via `return`) — cause non identifiée.
Seul `rewrite ... last;` (sans changer le code, donc 200 fixe) atteignait
la location de façon fiable.

`return CODE "texte";` contourne le problème : le contenu est renvoyé
directement, sans passer par une seconde location ni par `error_page`.
Contrepartie : le payload est en dur dans `tarpit-server.conf` (pas de
fichier externe).

## Réglages

- **Débit** : `map $is_banned $tarpit_rate { ... }` dans
  `geo-badguys.conf` — défaut `100` (octets/s). Plus bas = plus lent.
- **Durée du tarpit** ≈ taille du payload (dans `tarpit-server.conf`) ÷
  débit. Fourni à ~2964 octets ⇒ ~30s à 100 octets/s. Régénérer avec une
  taille différente si besoin (remplacer le texte entre guillemets dans
  `tarpit-server.conf`) :
  ```bash
  python3 -c "
  line = 'Please wait, your request is being processed. Do not close this connection.'
  n = 3000 // (len(line) + 1)  # <-- ajuster 3000 (octets cible)
  print('\n'.join([line]*n) + '\n', end='')
  "
  ```
  Un payload trop petit part quasi instantanément quel que soit le
  débit configuré (tient dans un seul paquet TCP) — rester au-dessus de
  quelques centaines d'octets pour un effet perceptible. Si le texte
  change, échapper `"` (`\"`), `\` (`\\`) et `$` (`\$` — sinon interprété
  comme une variable nginx).
- **Code HTTP retourné** : `403` par défaut dans `tarpit-server.conf`
  (le nombre juste après `return`). Codes usuels : `403`, `429`, `503`.
  Éviter `444` (coupe la connexion sans réponse chez nginx — contraire
  au principe du tarpit).

## Réglages du rate-limiting (`ratelimit.conf` / `ratelimit-server.conf`)

- **rate** : `rate=10r/s` dans `ratelimit.conf` — débit nominal max par
  IP. Ajuster selon le trafic légitime réel (une page avec beaucoup
  d'assets/API calls simultanés peut dépasser ça pour un seul
  visiteur — surveiller les faux positifs en prod).
- **burst/nodelay** : `burst=20 nodelay` dans `ratelimit-server.conf` —
  tolère une rafale de 20 requêtes au-delà du débit nominal avant de
  rejeter, traitées immédiatement (`nodelay`, pas de mise en file
  d'attente qui ralentirait artificiellement des visiteurs légitimes).
- **Exemption RFC1918** : IP privées (`10/8`, `172.16/12`, `192.168/16`)
  vues comme IP "réelle" (`$remote_addr`, donc après `realip` si
  configuré) exemptées via `geo`/`map` dans `ratelimit.conf` — utile
  pour un équipement interne (Sophos lui-même, monitoring...). Ne
  fonctionne que si `realip.conf` est correctement configuré pour ce
  vhost ; sinon `$remote_addr` vaut déjà l'IP interne du proxy amont
  pour TOUT le trafic (voir avertissement dans `ratelimit.conf`).
- **Exemption requêtes authentifiées** : toute requête où `$remote_user`
  est renseigné (auth_basic, auth_request, ou tout mécanisme nginx qui
  peuple cette variable après succès de l'authentification) est
  également exemptée — un visiteur authentifié qui déclenche
  beaucoup d'appels légitimes (SPA, API...) ne doit pas être bloqué
  comme un bot anonyme. `$remote_user` vide = non authentifié = toujours
  soumis au rate-limit. Suppose que le mécanisme d'auth (absent de ces
  snippets) est déjà configuré sur le vhost et peuple bien cette
  variable — sinon cette exemption ne fait simplement rien.
- **Code retourné en cas de dépassement** : `429` (via
  `limit_req_status 429;` dans `ratelimit-server.conf` — nginx renvoie
  `503` par défaut pour des raisons historiques, `limit_req` existait
  avant la normalisation du code `429` "Too Many Requests", RFC 6585,
  2012).

## Test

```bash
# temps de réponse observé pour une IP bannie (doit être lent, proche
# de taille_payload/débit) :
time curl -s -o /dev/null https://exemple.tld/  # depuis l'IP bannie

# confirme que le backend réel n'est jamais contacté pour cette IP :
# rien ne doit apparaître dans les logs applicatifs du backend pour
# cette requête, seulement dans les logs nginx (accès + $is_banned).

# rate-limiting : rafale de requêtes depuis une IP normale, doit
# recevoir des 429 après le burst configuré. IMPORTANT : en séquentiel
# (boucle for), le débit réel reste souvent sous rate+burst à cause du
# temps d'établissement TCP/TLS de chaque curl -- aucun 429 ne sort
# alors que limit_req fonctionne très bien (confirmé en réel). Utiliser
# du parallèle avec un volume net au-dessus de rate+burst (~30) :
seq 1 100 | xargs -P 100 -I{} curl -s -o /dev/null -w "%{http_code}\n" https://exemple.tld/
```

Si aucun `429` ne sort même en parallèle : vérifier que ce n'est pas
l'IP de test qui est exemptée (RFC1918, voir plus haut) via les headers
de debug suivants, temporairement dans le `server{}` :
```nginx
add_header X-Debug-RemoteAddr $remote_addr always;
add_header X-Debug-RatelimitKey $ratelimit_key always;
```
`curl -sv https://exemple.tld/ 2>&1 | grep -i X-Debug` -- une
`X-Debug-RatelimitKey:` vide confirme l'exemption (attendu pour une IP
RFC1918 ; tester depuis une IP publique pour valider le rate-limit).

Un ralentissement perceptible pendant le test parallèle (les requêtes
semblent mises en pause plutôt que de recevoir un 429 immédiat) sans
qu'aucun 429 n'apparaisse peut aussi venir du backend proxifié qui
sature sous la charge parallèle générée par le test lui-même, pas de
`limit_req` (qui s'applique avant `proxy_pass`, donc rejette
immédiatement sans jamais atteindre le backend une fois le seuil
dépassé).

## Débogage

```bash
# conf réellement chargée par nginx (compare avec les fichiers ci-dessus) :
docker exec nginx nginx -T | grep -A5 'geo \$remote_addr'

# contenu actuel de la liste de bannis :
docker exec nginx cat /etc/nginx/include.d/badguys.map
# ou, sans passer par le conteneur :
/usr/local/bin/nginx_fw_block.py list --config /usr/local/etc/nginx-fw-block.conf
```

Si une IP dans `badguys.map` n'est toujours pas ralentie : vérifier dans
l'ordre — `realip.conf` bien inclus et header confirmé (le plus
fréquent), conf effectivement rechargée (`nginx -T` à jour), format des
lignes de `badguys.map` (`1.2.3.4 1;` exactement), et que
`tarpit-server.conf` est bien inclus **avant** les `location` du
`server{}` testé.

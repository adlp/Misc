# Borg/dist — borgHelperWWW autonome

`dist/` contient une version **autonome** de `borgHelperWWW` : à l'exécution elle ne dépend que de

- la bibliothèque standard de Python 3 (>= 3.10),
- `borgHelper` (+ le lien `borgHelper.py`), toujours présent à côté,
- les fichiers `borgHelperWWW_ui.html`, `borgHelperWWW_sw.js` et `vendor/chartjs/chart.umd.min.js`.

Plus de `fastapi`, `starlette`, `pydantic`, `uvicorn`, `anyio`, ni de `pywebpush` / `py_vapid` / `http_ece` (donc plus
de `vendor/pywebpush` etc. à déployer). `cryptography`, si elle est installée, sert seulement de primitives (plus
sûres, temps constant) au Web Push ; sinon un repli pur Python est utilisé. `aiohttp` et `requests` ne sont plus
nécessaires.

Le fichier produit **est** le `borgHelperWWW` d'une release : le source d'origine est repris tel quel (une seule
transformation textuelle, voir plus bas), précédé d'une couche de compatibilité embarquée (`compat/`).

## Contenu

| Fichier | Rôle |
|---|---|
| `build_standalone.py` | Générateur (stdlib seule). Lit `Borg/borgHelperWWW` d'une révision git ou d'un fichier, produit `borgHelperWWW-<WWW_VERSION>`. |
| `borgHelperWWW-<version>` | Fichier généré, exécutable. **Ne pas éditer à la main** (l'en-tête le rappelle : version, commit source, hash de `compat/`). |
| `borgHelperWWW` | Lien symbolique vers la dernière version générée. |
| `compat/` | Sources de la couche embarquée : sous-ensembles de `fastapi`, `starlette`, `pydantic`, `uvicorn`, `anyio` (serveur HTTP/1.1 asyncio, routage, injection de paramètres, validation 422, middleware, lifespan, `TestClient`, `/openapi.json`, `/docs`) et `webpush_lite.py` (Web Push : VAPID ES256, chiffrement `aes128gcm` RFC 8291, envoi par `urllib`). |
| `tests/` | `test_webpush_lite.py` (vecteurs RFC 8291 / RFC 6979, signature vérifiée par `cryptography`) et `compare_standalone.py` (équivalence original / autonome, voir plus bas). |

## Déployer

Copier le fichier généré **à la place** de `borgHelperWWW`, dans le dossier qui contient déjà `borgHelper`,
`borgHelper.py`, `borgHelperWWW_ui.html`, `borgHelperWWW_sw.js` et `vendor/chartjs/` :

    cp Borg/dist/borgHelperWWW-1.34.1 /opt/borg/borgHelperWWW

Mêmes options CLI, mêmes variables `BORGHELPERWWW_*`, mêmes routes, mêmes codes HTTP, mêmes en-têtes, même journal
`[req]` que l'original. Les fichiers sont cherchés relativement à l'emplacement du fichier (liens symboliques résolus),
exactement comme avant. Lancé depuis `Borg/dist/` du dépôt (sans `borgHelper` à côté), le fichier retombe sur
`Borg/borgHelper` du dossier parent pour l'import (utile pour `--help` et les essais), mais le binaire `borgHelper`
et l'UI restent cherchés à côté du fichier : déployer pour servir.

## Régénérer (à chaque bump de `WWW_VERSION`)

    python3 Borg/dist/build_standalone.py --rev HEAD

(ou `--src Borg/borgHelperWWW` pour un fichier du disque, `--out-dir DOSSIER`, `--no-link`). Le générateur est
déterministe : même entrée, même sortie octet pour octet. Il échoue bruyamment si

- `WWW_VERSION="…"` n'apparaît pas exactement une fois ;
- le motif de la transformation du source (génération des clés VAPID, `REPLACEMENTS` dans le générateur) n'est plus
  trouvé exactement une fois ;
- le résultat ne compile pas, ou si un import hors stdlib / `borgHelper` / modules embarqués n'est pas optionnel.

Puis committer `Borg/dist/` (fichier généré + lien). Si une release de `borgHelperWWW` utilise une nouvelle API de
fastapi/starlette/pydantic/uvicorn que `compat/` ne fournit pas, l'import ou le `--selftest` du fichier généré le
dit tout de suite : compléter `compat/` (jamais le fichier généré).

## Vérifier

    python3 Borg/dist/tests/test_webpush_lite.py                       # Web Push : vecteurs RFC, deux backends
    python3 -I -S Borg/dist/borgHelperWWW-<version> --help             # démarre sans site-packages
    python3 Borg/dist/tests/compare_standalone.py --help               # équivalence original / autonome sur une conf démo
    python3 -I -S ./borgHelperWWW -C <rc> -K x --selftest              # le selftest de borgHelperWWW tourne sur la version autonome

## Limites connues

- **Pas de `--workers` multi-processus**, pas de `uvicorn borgHelperWWW:app` (le serveur HTTP est intégré : un seul
  processus, une boucle asyncio, fonctions synchrones des routes dans un pool de 40 fils comme avant). Derrière nginx
  comme avant : HTTP/1.1 keep-alive, `X-Forwarded-For` pris en compte pour `--trusted-proxies`.
- **Pas de TLS, de WebSocket ni de HTTP/2** (l'original non plus : TLS se termine sur le reverse proxy).
- Serveur HTTP plus strict qu'`uvicorn`/h11 sur quelques entrées mal formées : `Content-Length` avec
  `Transfer-Encoding` -> 400 (anti request smuggling), versions autres que HTTP/1.0 et 1.1 -> 400, URI absolue
  (`GET http://hôte/chemin`) servie comme son chemin. Pas d'en-tête `server:`. Un échec de bind (port pris) sort avec le
  code 3 (celui que l'original attend ; uvicorn 0.15 sort en 1).
- `/docs` et `/redoc` : gabarits HTML équivalents (mêmes scripts CDN, jsdelivr) mais pas octet pour octet ;
  `/docs/oauth2-redirect` est une page minimale (aucune authentification OAuth2 dans l'API) ; `/openapi.json` couvre
  chemins, méthodes, paramètres (type, défaut, description), corps et schémas des modèles, sans les raffinements de
  FastAPI (exemples, `anyOf` détaillés…).
- Messages d'erreur réseau du Web Push : texte d'`urllib` (`URLError: <urlopen error …>`) au lieu de celui de
  `requests` ; les redirections 3xx du service push ne sont pas suivies (jamais d'`Authorization` renvoyé ailleurs) ;
  seul le chiffrement `aes128gcm` est pris en charge (le seul utilisé par `borgHelperWWW` ; `aesgcm`, déprécié, refusé).
- **Crypto pure Python en repli** (sans `cryptography`) : ~13 ms par envoi push, nonce ECDSA déterministe (RFC 6979)
  mais pas de garantie de temps constant ; avec `cryptography` : ~1,5 ms. Les clés VAPID déjà stockées
  (`push_vapid_keys`, brutes base64url) restent lisibles telles quelles.
- Messages d'erreur de validation (422) alignés sur pydantic 1.x / FastAPI 0.63 (c'est ce que l'API expose) ; un
  FastAPI/pydantic 2 donnerait d'autres textes : la version autonome garde ceux de 0.63.

## Licences

`compat/` est un code original (aucune ligne reprise de starlette, FastAPI, pydantic, uvicorn, anyio, pywebpush,
py_vapid ni http_ece). Ces projets (BSD-3, MIT, MPL-2.0) ont servi de référence de comportement ; les gabarits HTML de
`/docs` et `/redoc` suivent ceux de FastAPI (MIT, Sebastián Ramírez), les scripts Swagger UI / ReDoc étant chargés
depuis cdn.jsdelivr.net. Le fichier généré est sous la licence de `borgHelperWWW` (GPL v3 ou ultérieure, en-tête
conservé).

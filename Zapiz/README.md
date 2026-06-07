# Zapiz

Wrapper FastAPI minimaliste avec routing dynamique et authentification intégrée (locale CSV + OIDC).

## Fonctionnalités

- **Routing hot-swap** : les handlers peuvent être remplacés à chaud sans redémarrer le serveur
- **Auth locale** : utilisateurs dans un fichier CSV, mots de passe bcrypt
- **Auth OIDC** : compatible Authentik (et tout fournisseur OIDC standard)
- **JWT en cookies** : paire access token (2 min) + refresh token (7 jours), renouvellement transparent à chaque requête
- **Multi-type de réponse** : Jinja2 HTML, JSON, Markdown→HTML, HTML brut, FileResponse
- **Logging** : middleware automatique — user, IP, méthode, path, status, durée

## Installation

```bash
pip install fastapi "uvicorn[standard]" authlib starlette python-jose[cryptography] bcrypt httpx markdown
```

## Usage minimal

```python
from zapiz import Zapiz

app = Zapiz(
    host="0.0.0.0",
    port=8080,
    secret_key="change-me",
    template_dir="templates",
    static_dir="static",
    # Optionnel
    startup=my_startup_fn,          # callback FastAPI on_event("startup")
    sentry="https://…@sentry.io/1", # DSN injecté dans tous les templates
    title="Mon API", version="1.0", # passés à FastAPI (pour Swagger)
)

async def home(varSession, params):
    return {"template": "index.html", "template_data": {"title": "Accueil"}}

app.api_add("/", home, daType="html")
app.run()
```

## Authentification

### Locale (CSV)

```python
app = Zapiz(..., user_csvfile="users.csv")
```

Format du fichier `users.csv` :

```
username:$2b$12$…bcrypt…:Nom Affiché:email@example.com:groupe1,groupe2
```

Générer un hash bcrypt :

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'motdepasse', bcrypt.gensalt()).decode())"
```

### OIDC (ex. Authentik)

```python
app = Zapiz(
    ...
    oidc_client_id="mon-client",
    oidc_client_secret="secret",
    oidc_issuer="https://authentik.example.com/application/o/mon-app/",
    oidc_auth_url="https://authentik.example.com/application/o/authorize/",
    oidc_toke_url="https://authentik.example.com/application/o/token/",
    oidc_redi_url="https://monapp.example.com/login/callback",
    oidc_jwks_url="https://authentik.example.com/application/o/mon-app/jwks/",
    oidc_usin_url="https://authentik.example.com/application/o/userinfo/",
)
```

## API de routing

### Ajouter une route

```python
app.api_add(uri, func, daType="html", verb="GET", acl=None)
```

| Paramètre | Description |
|-----------|-------------|
| `uri` | Chemin URL |
| `func` | Handler `async def f(varSession, params) → dict` |
| `daType` | `"html"`, `"json"`, `"md"`, `"Dhtml"`, ou `"fileResponse"` |
| `verb` | `"GET"` ou `"POST"` |
| `acl` | Nom de groupe requis (vérifié dans `varSession['groups']`) |

### Format de retour des handlers

```python
# Rendu Jinja2
return {"template": "page.html", "template_data": {"clé": "valeur"}}

# Redirection
return {"redirect": "/autre-page"}

# Fichier statique
return {"fileResponse": "/chemin/vers/fichier.pdf"}

# Cookies (ajoutables à n'importe quel retour)
return {"redirect": "/", "set_cookie": {"ma_cle": "valeur"}}
return {"redirect": "/", "del_cookie": ["ma_cle"]}
```

### `varSession` disponible dans les handlers

| Clé | Contenu |
|-----|---------|
| `request` | Objet `Request` FastAPI |
| `verb` | `"GET"` ou `"POST"` |
| `form` | Params GET/POST/JSON parsés |
| `sub` | Identifiant utilisateur (si authentifié) |
| `name` | Nom affiché |
| `email` | Email |
| `groups` | Liste de groupes |

### Clé `templateid` dans le retour

Pour utiliser un répertoire de templates non-default (enregistré via `add_template`) :

```python
app.add_template("templates/admin", templateid="admin")

async def admin_page(varSession, params):
    return {"template": "dashboard.html", "templateid": "admin", "template_data": {}}
```

### Autres méthodes

```python
app.api_del("/uri")          # Désactive une route (retourne 404)
app.api_lst()                # Retourne le tableau de toutes les routes actives
app.add_template("dossier")  # Ajoute un répertoire de templates supplémentaire
```

> **Note** : `api_add("/foo", …)` enregistre automatiquement `/foo` et `/foo/`.

## Routes auth intégrées

| Route | Méthode | Description |
|-------|---------|-------------|
| `GET /login` | GET | Page de connexion |
| `POST /login/localback` | POST | Connexion locale (CSV) |
| `GET /login/callback` | GET | Callback OIDC |
| `GET /login/whoami` | GET | Infos utilisateur courant |
| `GET /logout` | GET | Déconnexion (supprime les cookies) |

## Debug

```python
# Active les logs bugprint()
app = Zapiz(..., debug=True)
```

```bash
# Expose GET /debug — arrêt propre du serveur + redirection vers /
HAPIMIE_DEBUG=1 python app.py
```

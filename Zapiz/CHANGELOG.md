# Changelog

## [1.1.1] - 2026-06-08

### Corrections

- Swagger affiche désormais le nom et la docstring du handler utilisateur (via `__name__` et `__doc__` copiés sur le `wrapper` FastAPI lors du premier `api_add`)

---

## [1.1.0] - 2026-06-08

### Ajouts

- `Zapiz.Route` dataclass — porte `func`, `daType`, `acl`, `file`
- `app["GET /path"] = Zapiz.Route(fn, daType="html")` — ajout de route
- `del app["GET /path"]` — suppression de route
- `app["/path"]` — lecture d'une route (retourne `Zapiz.Route`)
- Verbe optionnel dans la clé : `app["/"]` équivaut à `app["GET /"]`
- `api_add` / `api_del` / `api_lst` restent fonctionnels (inchangés)

---

## [1.0.0] - 2026-06-08

Version initiale mise en production.

### Fonctionnalités

- Routing dynamique hot-swap (`api_add` / `api_del` / `api_lst`)
- Auth locale CSV (bcrypt) + OIDC (Authentik)
- JWT access/refresh en cookies `httponly`, renouvellement transparent
- Réponses multi-types : `html`, `json`, `md`, `Dhtml`, `fileResponse`
- Middleware de logging automatique
- Support multi-répertoires de templates (`add_template`)
- `Zapiz.VERSION` — version accessible sur la classe

### Corrections (bugs au lancement)

- `add_static` : variable `root` non définie → `self.root`
- `decode_payload` : `self` manquant → `@staticmethod`
- `auth_refresh` : `self` manquant + `referer` utilisé avant assignation
- `md` daType : chemin hardcodé `templates/` → `self.template_dirs[templateid]`
- `HAPIMIE_DEBUG` renommé en `ZAPIZ_DEBUG`

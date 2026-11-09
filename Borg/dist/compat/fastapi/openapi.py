"""/openapi.json (OpenAPI 3.0, version simplifiée : chemins, méthodes, paramètres, corps, schémas des modèles) et pages
/docs (Swagger UI) et /redoc, qui chargent leurs scripts depuis cdn.jsdelivr.net comme FastAPI."""
import json

from pydantic import BaseModel, Undefined, _schema_of
import typing

from starlette.routing import Route


def _operation_id(route, method):
    import re
    return re.sub(r"\W", "_", route.name + route.path_format).lower() + "_" + method.lower()


def get_openapi(*, title, version, description="", routes):
    paths, schemas = {}, {}

    def add_model(m):
        if m.__name__ not in schemas:
            schemas[m.__name__] = m.schema()
            for f in m.__fields__.values():
                for a in (f.type_,) + typing.get_args(f.type_) + tuple(x for t in typing.get_args(f.type_) for x in typing.get_args(t)):
                    if isinstance(a, type) and issubclass(a, BaseModel):
                        add_model(a)

    for route in routes:
        if not getattr(route, "include_in_schema", True) or not hasattr(route, "dependant"):
            continue
        for method in sorted(route.methods or []):
            if method in ("HEAD", "OPTIONS"):
                continue
            op = {}
            if route.tags:
                op["tags"] = route.tags
            op["summary"] = route.summary or route.name.replace("_", " ").title()
            if route.description:
                op["description"] = route.description
            op["operationId"] = route.operation_id or _operation_id(route, method)
            parameters = []
            dep = route.dependant

            def collect(d):
                for f in d.path_params + d.query_params + d.header_params + d.cookie_params:
                    sch = _schema_of(f.type_, f.info, f.alias)
                    if f.default is not None and f.default is not Undefined and not f.required:
                        sch["default"] = f.default
                    param = {"required": f.required, "schema": sch, "name": f.alias, "in": f.kind}
                    if f.info is not None and getattr(f.info, "description", None):
                        param["description"] = f.info.description
                    parameters.append(param)
                for s in d.dependencies:
                    collect(s)
            collect(dep)
            if parameters:
                op["parameters"] = parameters
            if dep.body_params:
                f = dep.body_params[0]
                for a in (f.type_,) + typing.get_args(f.type_):
                    if isinstance(a, type) and issubclass(a, BaseModel):
                        add_model(a)
                op["requestBody"] = {"content": {"application/json": {"schema": _schema_of(f.type_, None)}},
                                     "required": f.required}
            ok = {"description": route.response_description}
            if route.response_model is not None:
                if isinstance(route.response_model, type) and issubclass(route.response_model, BaseModel):
                    add_model(route.response_model)
                ok["content"] = {"application/json": {"schema": _schema_of(route.response_model, None)}}
            else:
                ok["content"] = {"application/json": {"schema": {}}}
            op["responses"] = {str(route.status_code): ok}
            if parameters or dep.body_params:
                op["responses"]["422"] = {"description": "Validation Error", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/HTTPValidationError"}}}}
            paths.setdefault(route.path_format, {})[method.lower()] = op
    if any("422" in o["responses"] for p in paths.values() for o in p.values()):
        schemas["HTTPValidationError"] = {"title": "HTTPValidationError", "type": "object", "properties": {
            "detail": {"title": "Detail", "type": "array", "items": {"$ref": "#/components/schemas/ValidationError"}}}}
        schemas["ValidationError"] = {"title": "ValidationError", "required": ["loc", "msg", "type"], "type": "object",
                                      "properties": {"loc": {"title": "Location", "type": "array",
                                                             "items": {"type": "string"}},
                                                     "msg": {"title": "Message", "type": "string"},
                                                     "type": {"title": "Error Type", "type": "string"}}}
    info = {"title": title, "version": version}
    if description:
        info["description"] = description
    out = {"openapi": "3.0.2", "info": info, "paths": paths}
    if schemas:
        out["components"] = {"schemas": schemas}
    return out


def swagger_ui_html(openapi_url, title, oauth2_redirect_url=None):
    cfg = {"url": openapi_url, "dom_id": "#swagger-ui", "layout": "BaseLayout", "deepLinking": True,
           "showExtensions": True, "showCommonExtensions": True}
    if oauth2_redirect_url:
        cfg["oauth2RedirectUrl"] = oauth2_redirect_url
    return f"""<!DOCTYPE html>
<html>
<head>
<link type="text/css" rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@3/swagger-ui.css">
<link rel="shortcut icon" href="https://fastapi.tiangolo.com/img/favicon.png">
<title>{title}</title>
</head>
<body>
<div id="swagger-ui">
</div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@3/swagger-ui-bundle.js"></script>
<script>
const ui = SwaggerUIBundle({{
    url: {json.dumps(openapi_url)},
    dom_id: '#swagger-ui',
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: "BaseLayout",
    deepLinking: true,
    showExtensions: true,
    showCommonExtensions: true{(", oauth2RedirectUrl: window.location.origin + " + json.dumps(oauth2_redirect_url)) if oauth2_redirect_url else ""}
}})
</script>
</body>
</html>
"""


def redoc_html(openapi_url, title):
    return f"""<!DOCTYPE html>
<html>
<head>
<title>{title}</title>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
<style>body {{ margin: 0; padding: 0; }}</style>
</head>
<body>
<redoc spec-url="{openapi_url}"></redoc>
<script src="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"> </script>
</body>
</html>
"""


SWAGGER_OAUTH2_REDIRECT_HTML = """<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><title>OAuth2 redirect</title></head>
<body>borgHelperWWW n'utilise aucune authentification OAuth2 : cette page de redirection de Swagger UI est sans objet.</body>
</html>
"""

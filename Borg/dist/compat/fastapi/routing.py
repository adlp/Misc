"""APIRoute / APIRouter : un endpoint = une route ; le gestionnaire de requête lit le corps JSON, résout les
dépendances/paramètres (422 si invalides), exécute l'endpoint (fonction synchrone -> fil du pool) et met la valeur
rendue en réponse (JSON par défaut, `response_class` sinon, `response_model` validé)."""
import asyncio
import inspect
import json
import re
import typing

from pydantic import BaseModel, ValidationError, _validate
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Match, Route, Router, compile_path, request_response

from fastapi.dependencies import get_dependant, solve_dependencies
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException, RequestValidationError


def get_name(endpoint):
    return getattr(endpoint, "__name__", endpoint.__class__.__name__)


def _prepare_response_content(res):
    if isinstance(res, BaseModel):
        return res.dict(by_alias=True)
    if isinstance(res, list):
        return [_prepare_response_content(x) for x in res]
    if isinstance(res, dict):
        return {k: _prepare_response_content(v) for k, v in res.items()}
    return res


def get_request_handler(dependant, *, has_body, status_code=200, response_class=JSONResponse, response_model=None):
    is_coroutine = asyncio.iscoroutinefunction(dependant.call)

    async def app(request):
        try:
            body = None
            if has_body:
                body_bytes = await request.body()
                if body_bytes:
                    body = await request.json()
        except json.JSONDecodeError as e:
            raise RequestValidationError([{
                "loc": ("body", e.pos), "msg": str(e), "type": "value_error.jsondecode",
                "ctx": {"msg": e.msg, "doc": e.doc, "pos": e.pos, "lineno": e.lineno, "colno": e.colno}}], body=e.doc)
        except Exception as e:
            raise HTTPException(status_code=400, detail="There was an error parsing the body") from e
        values, errors = await solve_dependencies(request=request, dependant=dependant, body=body)
        if errors:
            raise RequestValidationError(errors, body=body)
        if is_coroutine:
            raw = await dependant.call(**values)
        else:
            raw = await run_in_threadpool(dependant.call, **values)
        if isinstance(raw, Response):
            return raw
        content = _prepare_response_content(raw)
        if response_model is not None:
            content, errs = _validate(response_model, content, ("response",))
            if errs:
                raise ValidationError(errs, response_model)
        return response_class(content=jsonable_encoder(content) if response_class is JSONResponse or
                              not isinstance(content, (str, bytes)) else content, status_code=status_code)

    return app


class APIRoute(Route):
    def __init__(self, path, endpoint, *, response_model=None, status_code=200, tags=None, dependencies=None,
                 summary=None, description=None, response_description="Successful Response", responses=None,
                 deprecated=None, name=None, methods=None, operation_id=None, response_class=JSONResponse,
                 include_in_schema=True, **ignored):
        assert path.startswith("/"), "Routed paths must start with '/'"
        self.path = path
        self.endpoint = endpoint
        self.name = get_name(endpoint) if name is None else name
        self.path_regex, self.path_format, self.param_convertors = compile_path(path)
        self.response_model = response_model
        self.status_code = status_code
        self.tags = tags or []
        self.dependencies = list(dependencies or [])
        self.summary = summary
        self.description = description or inspect.cleandoc(endpoint.__doc__ or "").split("\f")[0]
        self.response_description = response_description
        self.responses = responses or {}
        self.deprecated = deprecated
        self.operation_id = operation_id
        self.response_class = response_class
        self.include_in_schema = include_in_schema
        self.methods = {m.upper() for m in (methods or ["GET"])}
        self.dependant = get_dependant(path=path, call=endpoint)
        for depends in self.dependencies[::-1]:
            self.dependant.dependencies.insert(0, get_dependant(path=path, call=depends.dependency, use_cache=depends.use_cache))
        self.app = request_response(self.get_route_handler())

    def get_route_handler(self):
        return get_request_handler(self.dependant, has_body=bool(self.dependant.body_params),
                                   status_code=self.status_code, response_class=self.response_class,
                                   response_model=self.response_model)

    def matches(self, scope):
        match, child_scope = super().matches(scope)
        if match != Match.NONE:
            child_scope["route"] = self
        return match, child_scope


class APIRouter(Router):
    def __init__(self, *, prefix="", tags=None, dependencies=None, default_response_class=JSONResponse,
                 responses=None, callbacks=None, routes=None, redirect_slashes=True, default=None,
                 dependency_overrides_provider=None, route_class=APIRoute, on_startup=None, on_shutdown=None,
                 deprecated=None, include_in_schema=True):
        super().__init__(routes=routes, redirect_slashes=redirect_slashes, default=default,
                         on_startup=on_startup, on_shutdown=on_shutdown)
        self.prefix = prefix
        self.tags = tags or []
        self.dependencies = list(dependencies or [])
        self.default_response_class = default_response_class
        self.route_class = route_class
        self.include_in_schema = include_in_schema

    def add_api_route(self, path, endpoint, *, response_model=None, status_code=200, tags=None, dependencies=None,
                      summary=None, description=None, response_description="Successful Response", responses=None,
                      deprecated=None, methods=None, operation_id=None, response_class=None,
                      include_in_schema=True, name=None, route_class_override=None, **ignored):
        route_class = route_class_override or self.route_class
        current_dependencies = list(self.dependencies)
        if dependencies:
            current_dependencies.extend(dependencies)
        route = route_class(self.prefix + path, endpoint=endpoint, response_model=response_model,
                            status_code=status_code, tags=(self.tags + (tags or [])), dependencies=current_dependencies,
                            summary=summary, description=description, response_description=response_description,
                            responses=responses, deprecated=deprecated, methods=methods, operation_id=operation_id,
                            response_class=response_class or self.default_response_class,
                            include_in_schema=self.include_in_schema and include_in_schema, name=name)
        self.routes.append(route)

    def api_route(self, path, **kw):
        def decorator(func):
            self.add_api_route(path, func, **kw)
            return func
        return decorator

    def include_router(self, router, *, prefix="", tags=None, dependencies=None, default_response_class=None,
                       responses=None, deprecated=None, include_in_schema=True):
        if prefix:
            assert prefix.startswith("/"), "A path prefix must start with '/'"
            assert not prefix.endswith("/"), "A path prefix must not end with '/', as the routes will start with '/'"
        for route in router.routes:
            if isinstance(route, APIRoute):
                current_dependencies = []
                if dependencies:
                    current_dependencies.extend(dependencies)
                if route.dependencies:
                    current_dependencies.extend(route.dependencies)
                self.add_api_route(prefix + route.path, route.endpoint, response_model=route.response_model,
                                   status_code=route.status_code, tags=(tags or []) + (route.tags or []),
                                   dependencies=current_dependencies, summary=route.summary,
                                   description=route.description, response_description=route.response_description,
                                   responses=route.responses, deprecated=route.deprecated, methods=route.methods,
                                   operation_id=route.operation_id, response_class=route.response_class,
                                   include_in_schema=route.include_in_schema and include_in_schema,
                                   name=route.name, route_class_override=type(route))
            elif isinstance(route, Route):
                self.add_route(prefix + route.path, route.endpoint, methods=list(route.methods or []),
                               name=route.name, include_in_schema=route.include_in_schema)

    def _method(self, method):
        def deco(path, **kw):
            return self.api_route(path, methods=[method], **kw)
        return deco

    def get(self, path, **kw):
        return self.api_route(path, methods=["GET"], **kw)

    def put(self, path, **kw):
        return self.api_route(path, methods=["PUT"], **kw)

    def post(self, path, **kw):
        return self.api_route(path, methods=["POST"], **kw)

    def delete(self, path, **kw):
        return self.api_route(path, methods=["DELETE"], **kw)

    def options(self, path, **kw):
        return self.api_route(path, methods=["OPTIONS"], **kw)

    def head(self, path, **kw):
        return self.api_route(path, methods=["HEAD"], **kw)

    def patch(self, path, **kw):
        return self.api_route(path, methods=["PATCH"], **kw)

"""Routage : Match, compilation des chemins (`{nom}`, `{nom:path}`, `{nom:int}`…), Route, Router (lifespan, redirection
de barre oblique finale), comme starlette 0.18."""
import asyncio
import contextlib
import enum
import re
import traceback
import typing

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.datastructures import URL


class Match(enum.Enum):
    NONE = 0
    PARTIAL = 1
    FULL = 2


class _Convertor:
    regex = "[^/]+"

    def convert(self, value):
        return value


class _PathConvertor(_Convertor):
    regex = ".*"


class _IntegerConvertor(_Convertor):
    regex = "[0-9]+"

    def convert(self, value):
        return int(value)


class _FloatConvertor(_Convertor):
    regex = r"[0-9]+(\.[0-9]+)?"

    def convert(self, value):
        return float(value)


CONVERTORS = {"str": _Convertor(), "path": _PathConvertor(), "int": _IntegerConvertor(), "float": _FloatConvertor()}
PARAM_REGEX = re.compile("{([a-zA-Z_][a-zA-Z0-9_]*)(:[a-zA-Z_][a-zA-Z0-9_]*)?}")


def compile_path(path):
    path_regex = "^"
    path_format = ""
    idx = 0
    param_convertors = {}
    for match in PARAM_REGEX.finditer(path):
        param_name, convertor_type = match.groups("str")
        convertor_type = convertor_type.lstrip(":")
        assert convertor_type in CONVERTORS, f"Unknown path convertor '{convertor_type}'"
        convertor = CONVERTORS[convertor_type]
        path_regex += re.escape(path[idx:match.start()])
        path_regex += f"(?P<{param_name}>{convertor.regex})"
        path_format += path[idx:match.start()]
        path_format += "{%s}" % param_name
        param_convertors[param_name] = convertor
        idx = match.end()
    path_regex += re.escape(path[idx:]) + "$"
    path_format += path[idx:]
    return re.compile(path_regex), path_format, param_convertors


def request_response(func):
    """Adapte `async def f(request) -> Response` (ou fonction synchrone) en application ASGI."""
    is_coroutine = asyncio.iscoroutinefunction(func)

    async def app(scope, receive, send):
        request = Request(scope, receive=receive, send=send)
        if is_coroutine:
            response = await func(request)
        else:
            response = await run_in_threadpool(func, request)
        await response(scope, receive, send)
    return app


class BaseRoute:
    def matches(self, scope):
        raise NotImplementedError()

    async def handle(self, scope, receive, send):
        raise NotImplementedError()

    async def __call__(self, scope, receive, send):
        match, child_scope = self.matches(scope)
        if match == Match.NONE:
            if scope["type"] == "http":
                response = PlainTextResponse("Not Found", status_code=404)
                await response(scope, receive, send)
            return
        scope.update(child_scope)
        await self.handle(scope, receive, send)


class Route(BaseRoute):
    def __init__(self, path, endpoint, *, methods=None, name=None, include_in_schema=True):
        assert path.startswith("/"), "Routed paths must start with '/'"
        self.path = path
        self.endpoint = endpoint
        self.name = endpoint.__name__ if name is None else name
        self.include_in_schema = include_in_schema
        self.app = request_response(endpoint)
        if methods is None:
            self.methods = None
        else:
            self.methods = {m.upper() for m in methods}
            if "GET" in self.methods:
                self.methods.add("HEAD")
        self.path_regex, self.path_format, self.param_convertors = compile_path(path)

    def matches(self, scope):
        if scope["type"] == "http":
            match = self.path_regex.match(scope["path"])
            if match:
                matched_params = match.groupdict()
                for key, value in matched_params.items():
                    matched_params[key] = self.param_convertors[key].convert(value)
                path_params = dict(scope.get("path_params", {}))
                path_params.update(matched_params)
                child_scope = {"endpoint": self.endpoint, "path_params": path_params}
                if self.methods and scope["method"] not in self.methods:
                    return Match.PARTIAL, child_scope
                return Match.FULL, child_scope
        return Match.NONE, {}

    async def handle(self, scope, receive, send):
        if self.methods and scope["method"] not in self.methods:
            if "app" in scope:
                raise HTTPException(status_code=405)
            response = PlainTextResponse("Method Not Allowed", status_code=405)
            await response(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    def __repr__(self):
        return f"{self.__class__.__name__}(path={self.path!r}, name={self.name!r}, methods={sorted(self.methods or [])!r})"


@contextlib.asynccontextmanager
async def _default_lifespan(app):
    yield


class Router:
    def __init__(self, routes=None, redirect_slashes=True, default=None, on_startup=None, on_shutdown=None,
                 lifespan=None):
        self.routes = [] if routes is None else list(routes)
        self.redirect_slashes = redirect_slashes
        self.default = self.not_found if default is None else default
        self.on_startup = [] if on_startup is None else list(on_startup)
        self.on_shutdown = [] if on_shutdown is None else list(on_shutdown)
        self.lifespan_context = lifespan if lifespan is not None else _default_lifespan

    async def not_found(self, scope, receive, send):
        if scope["type"] == "websocket":
            return
        if "app" in scope:
            raise HTTPException(status_code=404)
        response = PlainTextResponse("Not Found", status_code=404)
        await response(scope, receive, send)

    async def lifespan(self, scope, receive, send):
        started = False
        app = scope.get("app")
        await receive()
        try:
            async with self.lifespan_context(app):
                await send({"type": "lifespan.startup.complete"})
                started = True
                await receive()
        except BaseException:
            exc_text = traceback.format_exc()
            if started:
                await send({"type": "lifespan.shutdown.failed", "message": exc_text})
            else:
                await send({"type": "lifespan.startup.failed", "message": exc_text})
            raise
        else:
            await send({"type": "lifespan.shutdown.complete"})

    async def __call__(self, scope, receive, send):
        assert scope["type"] in ("http", "websocket", "lifespan")
        if "router" not in scope:
            scope["router"] = self
        if scope["type"] == "lifespan":
            await self.lifespan(scope, receive, send)
            return
        partial = None
        for route in self.routes:
            match, child_scope = route.matches(scope)
            if match == Match.FULL:
                scope.update(child_scope)
                await route.handle(scope, receive, send)
                return
            elif match == Match.PARTIAL and partial is None:
                partial = route
                partial_scope = child_scope
        if partial is not None:
            scope.update(partial_scope)
            await partial.handle(scope, receive, send)
            return
        if scope["type"] == "http" and self.redirect_slashes and scope["path"] != "/":
            redirect_scope = dict(scope)
            if scope["path"].endswith("/"):
                redirect_scope["path"] = redirect_scope["path"].rstrip("/")
            else:
                redirect_scope["path"] = redirect_scope["path"] + "/"
            for route in self.routes:
                match, child_scope = route.matches(redirect_scope)
                if match != Match.NONE:
                    redirect_url = URL(scope=redirect_scope)
                    response = RedirectResponse(url=str(redirect_url))
                    await response(scope, receive, send)
                    return
        await self.default(scope, receive, send)

    def add_route(self, path, endpoint, methods=None, name=None, include_in_schema=True):
        self.routes.append(Route(path, endpoint=endpoint, methods=methods, name=name, include_in_schema=include_in_schema))

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.exceptions import HTTPException as StarletteHTTPException

from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.openapi import get_openapi, swagger_ui_html, redoc_html, SWAGGER_OAUTH2_REDIRECT_HTML
from fastapi.routing import APIRouter


class FastAPI(Starlette):
    def __init__(self, *, debug=False, routes=None, title="FastAPI", description="", version="0.1.0",
                 openapi_url="/openapi.json", openapi_tags=None, servers=None, dependencies=None,
                 default_response_class=JSONResponse, docs_url="/docs", redoc_url="/redoc",
                 swagger_ui_oauth2_redirect_url="/docs/oauth2-redirect", middleware=None, exception_handlers=None,
                 on_startup=None, on_shutdown=None, root_path="", **extra):
        self.title = title
        self.description = description
        self.version = version
        self.openapi_url = openapi_url
        self.openapi_tags = openapi_tags
        self.docs_url = docs_url
        self.redoc_url = redoc_url
        self.swagger_ui_oauth2_redirect_url = swagger_ui_oauth2_redirect_url
        self.root_path = root_path
        self.openapi_schema = None
        self.extra = extra
        self.router = APIRouter(routes=routes, dependencies=dependencies, default_response_class=default_response_class,
                                on_startup=on_startup, on_shutdown=on_shutdown)
        self.exception_handlers = {} if exception_handlers is None else dict(exception_handlers)
        self.exception_handlers.setdefault(StarletteHTTPException, http_exception_handler)
        self.exception_handlers.setdefault(RequestValidationError, request_validation_exception_handler)
        self.user_middleware = [] if middleware is None else list(middleware)
        self.debug = debug
        from starlette.datastructures import State
        self.state = State()
        self.middleware_stack = self.build_middleware_stack()
        self._setup()

    def openapi(self):
        if not self.openapi_schema:
            self.openapi_schema = get_openapi(title=self.title, version=self.version, description=self.description,
                                              routes=self.routes)
        return self.openapi_schema

    def _setup(self):
        if self.openapi_url:
            urls = (self.openapi_url,)
            server_urls = {u for u in urls if u}

            async def openapi(req):
                return JSONResponse(self.openapi())
            self.add_route(self.openapi_url, openapi, include_in_schema=False)
            if self.openapi_url and self.docs_url:
                async def swagger_ui_html_route(req):
                    root_path = req.scope.get("root_path", "").rstrip("/")
                    openapi_url = root_path + self.openapi_url
                    oauth2_redirect_url = self.swagger_ui_oauth2_redirect_url
                    if oauth2_redirect_url:
                        oauth2_redirect_url = root_path + oauth2_redirect_url
                    return HTMLResponse(swagger_ui_html(openapi_url, self.title + " - Swagger UI", oauth2_redirect_url))
                self.add_route(self.docs_url, swagger_ui_html_route, include_in_schema=False)
                if self.swagger_ui_oauth2_redirect_url:
                    async def swagger_ui_redirect(req):
                        return HTMLResponse(SWAGGER_OAUTH2_REDIRECT_HTML)
                    self.add_route(self.swagger_ui_oauth2_redirect_url, swagger_ui_redirect, include_in_schema=False)
            if self.openapi_url and self.redoc_url:
                async def redoc_html_route(req):
                    root_path = req.scope.get("root_path", "").rstrip("/")
                    return HTMLResponse(redoc_html(root_path + self.openapi_url, self.title + " - ReDoc"))
                self.add_route(self.redoc_url, redoc_html_route, include_in_schema=False)

    def add_route(self, path, route, methods=None, name=None, include_in_schema=True):
        self.router.add_route(path, route, methods=methods, name=name, include_in_schema=include_in_schema)

    async def __call__(self, scope, receive, send):
        if self.root_path:
            scope["root_path"] = self.root_path
        await super().__call__(scope, receive, send)

    def add_api_route(self, path, endpoint, **kw):
        self.router.add_api_route(path, endpoint, **kw)

    def api_route(self, path, **kw):
        return self.router.api_route(path, **kw)

    def include_router(self, router, **kw):
        self.router.include_router(router, **kw)

    def get(self, path, **kw):
        return self.router.get(path, **kw)

    def put(self, path, **kw):
        return self.router.put(path, **kw)

    def post(self, path, **kw):
        return self.router.post(path, **kw)

    def delete(self, path, **kw):
        return self.router.delete(path, **kw)

    def options(self, path, **kw):
        return self.router.options(path, **kw)

    def head(self, path, **kw):
        return self.router.head(path, **kw)

    def patch(self, path, **kw):
        return self.router.patch(path, **kw)

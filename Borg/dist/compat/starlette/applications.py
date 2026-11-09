"""Application ASGI : pile de middlewares (ServerErrorMiddleware > middlewares utilisateur > ExceptionMiddleware >
routeur), gestionnaires d'exceptions, `@app.middleware("http")`."""
from starlette.datastructures import State
from starlette.exceptions import ExceptionMiddleware
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.routing import Router


class Starlette:
    def __init__(self, debug=False, routes=None, middleware=None, exception_handlers=None, on_startup=None,
                 on_shutdown=None, lifespan=None):
        self.debug = debug
        self.state = State()
        self.router = Router(routes, on_startup=on_startup, on_shutdown=on_shutdown, lifespan=lifespan)
        self.exception_handlers = {} if exception_handlers is None else dict(exception_handlers)
        self.user_middleware = [] if middleware is None else list(middleware)
        self.middleware_stack = self.build_middleware_stack()

    def build_middleware_stack(self):
        debug = self.debug
        error_handler = None
        exception_handlers = {}
        for key, value in self.exception_handlers.items():
            if key in (500, Exception):
                error_handler = value
            else:
                exception_handlers[key] = value
        middleware = ([Middleware(ServerErrorMiddleware, handler=error_handler, debug=debug)]
                      + self.user_middleware
                      + [Middleware(ExceptionMiddleware, handlers=exception_handlers)])
        app = self.router
        for cls, options in reversed(middleware):
            app = cls(app=app, **options)
        return app

    @property
    def routes(self):
        return self.router.routes

    async def __call__(self, scope, receive, send):
        scope["app"] = self
        await self.middleware_stack(scope, receive, send)

    def add_middleware(self, middleware_class, **options):
        self.user_middleware.insert(0, Middleware(middleware_class, **options))
        self.middleware_stack = self.build_middleware_stack()

    def add_exception_handler(self, exc_class_or_status_code, handler):
        self.exception_handlers[exc_class_or_status_code] = handler
        self.middleware_stack = self.build_middleware_stack()

    def exception_handler(self, exc_class_or_status_code):
        def decorator(func):
            self.add_exception_handler(exc_class_or_status_code, func)
            return func
        return decorator

    def middleware(self, middleware_type):
        assert middleware_type == "http", 'Currently only middleware("http") is supported.'

        def decorator(func):
            self.add_middleware(BaseHTTPMiddleware, dispatch=func)
            return func
        return decorator

import asyncio
import http

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response


class HTTPException(Exception):
    def __init__(self, status_code, detail=None):
        if detail is None:
            detail = http.HTTPStatus(status_code).phrase
        self.status_code = status_code
        self.detail = detail

    def __repr__(self):
        return f"{self.__class__.__name__}(status_code={self.status_code!r}, detail={self.detail!r})"


class ExceptionMiddleware:
    """Gestionnaires d'exceptions (par code HTTP ou par classe, MRO parcouru) — ceux de 500/Exception sont pour
    ServerErrorMiddleware, pas pour celui-ci."""

    def __init__(self, app, handlers=None):
        self.app = app
        self._status_handlers = {}
        self._exception_handlers = {HTTPException: self.http_exception}
        for key, value in (handlers or {}).items():
            self.add_exception_handler(key, value)

    def add_exception_handler(self, exc_class_or_status_code, handler):
        if isinstance(exc_class_or_status_code, int):
            self._status_handlers[exc_class_or_status_code] = handler
        else:
            self._exception_handlers[exc_class_or_status_code] = handler

    def _lookup_exception_handler(self, exc):
        for cls in type(exc).__mro__:
            if cls in self._exception_handlers:
                return self._exception_handlers[cls]
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def sender(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, sender)
        except Exception as exc:
            handler = None
            if isinstance(exc, HTTPException):
                handler = self._status_handlers.get(exc.status_code)
            if handler is None:
                handler = self._lookup_exception_handler(exc)
            if handler is None:
                raise exc
            if response_started:
                raise RuntimeError("Caught handled exception, but response already started.") from exc
            request = Request(scope, receive=receive)
            if asyncio.iscoroutinefunction(handler):
                response = await handler(request, exc)
            else:
                response = await run_in_threadpool(handler, request, exc)
            await response(scope, receive, sender)

    async def http_exception(self, request, exc):
        if exc.status_code in {204, 304}:
            return Response(status_code=exc.status_code)
        return PlainTextResponse(exc.detail, status_code=exc.status_code)

"""ServerErrorMiddleware : toute exception non traitée -> 500 « Internal Server Error » (texte), puis relancée au serveur
qui l'écrit au journal avec sa trace."""
import asyncio

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse


class ServerErrorMiddleware:
    def __init__(self, app, handler=None, debug=False):
        self.app = app
        self.handler = handler
        self.debug = debug

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def _send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:
            if not response_started:
                request = Request(scope)
                if self.handler is None:
                    response = PlainTextResponse("Internal Server Error", status_code=500)
                elif asyncio.iscoroutinefunction(self.handler):
                    response = await self.handler(request, exc)
                else:
                    response = await run_in_threadpool(self.handler, request, exc)
                await response(scope, receive, send)
            raise exc

"""BaseHTTPMiddleware (starlette 0.18) : `dispatch(request, call_next)`. L'application interne tourne dans sa propre tâche
asyncio ; ses messages ASGI passent par un canal SANS tampon (l'émetteur attend que le receveur ait pris le message :
contre-pression d'un téléchargement vers un client lent, comme le flux mémoire d'anyio) ; `call_next` rend une
StreamingResponse. Les tâches internes encore vivantes sont annulées à la sortie."""
import asyncio

from starlette.requests import Request
from starlette.responses import StreamingResponse

_END = object()


class BaseHTTPMiddleware:
    def __init__(self, app, dispatch=None):
        self.app = app
        self.dispatch_func = self.dispatch if dispatch is None else dispatch

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        tasks = []

        async def call_next(request):
            app_exc = None
            loop = asyncio.get_running_loop()
            queue = asyncio.Queue()

            async def chan_send(message):
                taken = loop.create_future()
                queue.put_nowait((message, taken))
                await taken

            async def chan_recv():
                message, taken = await queue.get()
                if taken is not None and not taken.done():
                    taken.set_result(None)
                return message

            async def coro():
                nonlocal app_exc
                try:
                    await self.app(scope, request.receive, chan_send)
                except Exception as exc:
                    app_exc = exc
                finally:
                    queue.put_nowait((_END, None))

            tasks.append(asyncio.ensure_future(coro()))
            message = await chan_recv()
            if message is _END:
                if app_exc is not None:
                    raise app_exc
                raise RuntimeError("No response returned.")
            assert message["type"] == "http.response.start"

            async def body_stream():
                while True:
                    message = await chan_recv()
                    if message is _END:
                        break
                    assert message["type"] == "http.response.body"
                    yield message.get("body", b"")

            response = StreamingResponse(status_code=message["status"], content=body_stream())
            response.raw_headers = message["headers"]
            return response

        try:
            request = Request(scope, receive=receive)
            response = await self.dispatch_func(request, call_next)
            await response(scope, receive, send)
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def dispatch(self, request, call_next):
        raise NotImplementedError()

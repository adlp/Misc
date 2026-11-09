import asyncio
import http.cookies
import json
from urllib.parse import quote

from starlette.concurrency import iterate_in_threadpool
from starlette.datastructures import MutableHeaders


class Response:
    media_type = None
    charset = "utf-8"

    def __init__(self, content=None, status_code=200, headers=None, media_type=None, background=None):
        self.status_code = status_code
        if media_type is not None:
            self.media_type = media_type
        self.background = background
        self.body = self.render(content)
        self.init_headers(headers)

    def render(self, content):
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        return content.encode(self.charset)

    def init_headers(self, headers=None):
        if headers is None:
            raw_headers = []
            populate_content_length = True
            populate_content_type = True
        else:
            raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
            keys = [h[0] for h in raw_headers]
            populate_content_length = b"content-length" not in keys
            populate_content_type = b"content-type" not in keys
        body = getattr(self, "body", None)
        if body is not None and populate_content_length and not (self.status_code < 200 or self.status_code in (204, 304)):
            raw_headers.append((b"content-length", str(len(body)).encode("latin-1")))
        content_type = self.media_type
        if content_type is not None and populate_content_type:
            if content_type.startswith("text/"):
                content_type += "; charset=" + self.charset
            raw_headers.append((b"content-type", content_type.encode("latin-1")))
        self.raw_headers = raw_headers

    @property
    def headers(self):
        if not hasattr(self, "_headers"):
            self._headers = MutableHeaders(raw=self.raw_headers)
        return self._headers

    def set_cookie(self, key, value="", max_age=None, expires=None, path="/", domain=None, secure=False,
                   httponly=False, samesite="lax"):
        cookie = http.cookies.SimpleCookie()
        cookie[key] = value
        if max_age is not None:
            cookie[key]["max-age"] = max_age
        if expires is not None:
            cookie[key]["expires"] = expires
        if path is not None:
            cookie[key]["path"] = path
        if domain is not None:
            cookie[key]["domain"] = domain
        if secure:
            cookie[key]["secure"] = True
        if httponly:
            cookie[key]["httponly"] = True
        if samesite is not None:
            cookie[key]["samesite"] = samesite
        self.raw_headers.append((b"set-cookie", cookie.output(header="").strip().encode("latin-1")))

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
        await send({"type": "http.response.body", "body": self.body})
        if self.background is not None:
            await self.background()


class HTMLResponse(Response):
    media_type = "text/html"


class PlainTextResponse(Response):
    media_type = "text/plain"


class JSONResponse(Response):
    media_type = "application/json"

    def render(self, content):
        return json.dumps(content, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")).encode("utf-8")


class RedirectResponse(Response):
    def __init__(self, url, status_code=307, headers=None, background=None):
        super().__init__(content=b"", status_code=status_code, headers=headers, background=background)
        self.headers["location"] = quote(str(url), safe=":/%#?=@[]!$&'()*+,;")


class StreamingResponse(Response):
    def __init__(self, content, status_code=200, headers=None, media_type=None, background=None):
        if hasattr(content, "__aiter__"):
            self.body_iterator = content
        else:
            self.body_iterator = iterate_in_threadpool(content)
        self.status_code = status_code
        self.media_type = self.media_type if media_type is None else media_type
        self.background = background
        self.init_headers(headers)

    async def listen_for_disconnect(self, receive):
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break

    async def stream_response(self, send):
        await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
        async for chunk in self.body_iterator:
            if not isinstance(chunk, bytes):
                chunk = chunk.encode(self.charset)
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def __call__(self, scope, receive, send):
        # Deux tâches (écoute de la déconnexion, envoi du corps) : la première finie annule l'autre — client parti =
        # envoi annulé en cours de route ; fin du corps = écoute arrêtée. L'écoute prend la main EN PREMIER (comme anyio :
        # client déjà parti -> le corps n'envoie jamais son en-tête). Une exception de l'envoi est relancée.
        listen = asyncio.ensure_future(self.listen_for_disconnect(receive))
        stream = None
        try:
            await asyncio.sleep(0)
            if not listen.done():
                stream = asyncio.ensure_future(self.stream_response(send))
                await asyncio.wait({stream, listen}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            for t in (stream, listen):
                if t is not None:
                    t.cancel()
            await asyncio.gather(*[t for t in (stream, listen) if t is not None], return_exceptions=True)
            raise
        tasks = [t for t in (stream, listen) if t is not None]
        for t in tasks:
            if not t.done():
                t.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError):
                raise r
        if self.background is not None:
            await self.background()

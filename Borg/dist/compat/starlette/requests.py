import asyncio
import json
import typing
from collections.abc import Mapping
from http import cookies as http_cookies

from starlette.datastructures import URL, Address, Headers, QueryParams, State


def cookie_parser(cookie_string):
    out = {}
    for chunk in cookie_string.split(";"):
        if "=" in chunk:
            key, val = chunk.split("=", 1)
        else:
            key, val = "", chunk
        key, val = key.strip(), val.strip()
        if key or val:
            out[key] = http_cookies._unquote(val)
    return out


class ClientDisconnect(Exception):
    pass


class HTTPConnection(Mapping):
    """Accès commun à une connexion ASGI : le scope se lit comme un Mapping."""

    def __init__(self, scope, receive=None):
        assert scope["type"] in ("http", "websocket")
        self.scope = scope

    def __getitem__(self, key):
        return self.scope[key]

    def __iter__(self):
        return iter(self.scope)

    def __len__(self):
        return len(self.scope)

    __eq__ = object.__eq__
    __hash__ = object.__hash__

    @property
    def app(self):
        return self.scope["app"]

    @property
    def url(self):
        if not hasattr(self, "_url"):
            self._url = URL(scope=self.scope)
        return self._url

    @property
    def base_url(self):
        if not hasattr(self, "_base_url"):
            base = dict(self.scope)
            base["path"] = "/"
            base["query_string"] = b""
            base["root_path"] = base.get("app_root_path", base.get("root_path", ""))
            self._base_url = URL(scope=base)
        return self._base_url

    @property
    def headers(self):
        if not hasattr(self, "_headers"):
            self._headers = Headers(scope=self.scope)
        return self._headers

    @property
    def query_params(self):
        if not hasattr(self, "_query_params"):
            self._query_params = QueryParams(self.scope["query_string"])
        return self._query_params

    @property
    def path_params(self):
        return self.scope.get("path_params", {})

    @property
    def cookies(self):
        if not hasattr(self, "_cookies"):
            cookies = {}
            cookie_header = self.headers.get("cookie")
            if cookie_header:
                cookies = cookie_parser(cookie_header)
            self._cookies = cookies
        return self._cookies

    @property
    def client(self):
        host, port = self.scope.get("client") or (None, None)
        if host is None and port is None:
            return None
        return Address(host=host, port=port)

    @property
    def state(self):
        if not hasattr(self, "_state"):
            self.scope.setdefault("state", {})
            self._state = State(self.scope["state"])
        return self._state


async def empty_receive():
    raise RuntimeError("Receive channel has not been made available")


async def empty_send(message):
    raise RuntimeError("Send channel has not been made available")


class Request(HTTPConnection):
    def __init__(self, scope, receive=empty_receive, send=empty_send):
        super().__init__(scope)
        assert scope["type"] == "http"
        self._receive = receive
        self._send = send
        self._stream_consumed = False
        self._is_disconnected = False

    @property
    def method(self):
        return self.scope["method"]

    @property
    def receive(self):
        return self._receive

    async def stream(self):
        if hasattr(self, "_body"):
            yield self._body
            yield b""
            return
        if self._stream_consumed:
            raise RuntimeError("Stream consumed")
        self._stream_consumed = True
        while True:
            message = await self._receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                if body:
                    yield body
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                self._is_disconnected = True
                raise ClientDisconnect()
        yield b""

    async def body(self):
        if not hasattr(self, "_body"):
            chunks = []
            async for chunk in self.stream():
                chunks.append(chunk)
            self._body = b"".join(chunks)
        return self._body

    async def json(self):
        if not hasattr(self, "_json"):
            body = await self.body()
            self._json = json.loads(body)
        return self._json

    async def is_disconnected(self):
        """Sonde sans attente : un `receive` qui ne rend pas la main aussitôt est annulé (rien n'est perdu — le serveur
        redonne `http.disconnect` à chaque `receive` suivant)."""
        if not self._is_disconnected:
            task = asyncio.ensure_future(self._receive())
            await asyncio.sleep(0)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            else:
                message = task.result()   # exception du receive : relancée, comme starlette
                if message.get("type") == "http.disconnect":
                    self._is_disconnected = True
        return self._is_disconnected

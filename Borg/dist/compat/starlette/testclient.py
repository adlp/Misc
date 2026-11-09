"""TestClient : appelle l'application ASGI en mémoire, sans réseau (API proche de `requests`/`httpx`). Hors bloc
`with`, chaque requête tourne dans sa propre boucle d'événements (un fil dédié) ; dans un bloc `with`, une boucle
unique vit dans un fil de fond pendant tout le bloc et porte le lifespan ASGI (démarrage/arrêt de l'application)."""
import asyncio
import io
import json as _json
import queue
import threading
import typing
import urllib.parse
from http import HTTPStatus

from starlette.datastructures import Headers


class _CIDict(dict):
    """En-têtes de réponse : accès insensible à la casse."""

    def __init__(self, items=()):
        super().__init__()
        self._multi = []
        for k, v in items:
            self._multi.append((k, v))
            lk = k.lower()
            if lk in self.keys_lower():
                super().__setitem__(self._real(lk), self[lk] + ", " + v)
            else:
                super().__setitem__(k, v)

    def keys_lower(self):
        return {k.lower() for k in dict.keys(self)}

    def _real(self, lk):
        for k in dict.keys(self):
            if k.lower() == lk:
                return k
        return lk

    def __getitem__(self, key):
        return dict.__getitem__(self, self._real(key.lower()))

    def __contains__(self, key):
        return isinstance(key, str) and key.lower() in self.keys_lower()

    def get(self, key, default=None):
        return self[key] if key in self else default

    def get_list(self, key):
        return [v for k, v in self._multi if k.lower() == key.lower()]

    getlist = get_list

    def multi_items(self):
        return list(self._multi)


class _Request:
    def __init__(self, method, url, headers, content):
        self.method = method
        self.url = url
        self.headers = _CIDict(headers)
        self.content = content
        self.body = content


class TestResponse:
    __test__ = False

    def __init__(self, status_code, headers, content, url, request, history=None):
        self.status_code = status_code
        self.headers = _CIDict(headers)
        self.content = content
        self.url = url
        self.request = request
        self.history = history or []
        try:
            self.reason_phrase = HTTPStatus(status_code).phrase
        except ValueError:
            self.reason_phrase = ""
        self.reason = self.reason_phrase
        self.encoding = "utf-8"

    @property
    def text(self):
        ct = self.headers.get("content-type", "")
        enc = "utf-8"
        if "charset=" in ct:
            enc = ct.split("charset=")[1].split(";")[0].strip() or "utf-8"
        return self.content.decode(enc, errors="replace")

    def json(self, **kw):
        return _json.loads(self.content, **kw)

    @property
    def ok(self):
        return self.status_code < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def __repr__(self):
        return f"<Response [{self.status_code}]>"


def _encode_form(data):
    return urllib.parse.urlencode(data, doseq=True).encode()


class TestClient:
    __test__ = False

    def __init__(self, app, base_url="http://testserver", raise_server_exceptions=True, root_path="",
                 backend="asyncio", backend_options=None, cookies=None, headers=None):
        self.app = app
        self.base_url = base_url
        self.raise_server_exceptions = raise_server_exceptions
        self.root_path = root_path
        self.headers = {"user-agent": "testclient", "accept-encoding": "gzip, deflate", "accept": "*/*",
                        "connection": "keep-alive"}
        if headers:
            self.headers.update(headers)
        self.cookies = dict(cookies or {})
        self._portal = None

    # ---- contexte (lifespan) ----
    def __enter__(self):
        ready = queue.Queue()
        self._lifespan_error = None

        def runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop

            async def main():
                recv_q, state = asyncio.Queue(), {}
                self._recv_q = recv_q
                started, stopped = asyncio.Event(), asyncio.Event()
                self._stopped = stopped

                async def receive():
                    return await recv_q.get()

                async def send(message):
                    t = message["type"]
                    if t == "lifespan.startup.complete":
                        started.set()
                    elif t == "lifespan.startup.failed":
                        state["err"] = message.get("message")
                        started.set()
                    elif t == "lifespan.shutdown.complete":
                        stopped.set()
                    elif t == "lifespan.shutdown.failed":
                        stopped.set()

                async def run_app():
                    try:
                        await self.app({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send)
                    except BaseException as exc:
                        if not started.is_set():
                            state["exc"] = exc
                            started.set()
                        stopped.set()
                task = asyncio.ensure_future(run_app())
                self._lifespan_task = task
                recv_q.put_nowait({"type": "lifespan.startup"})
                await started.wait()
                ready.put(state)
                self._stop_future = loop.create_future()
                await self._stop_future
                recv_q.put_nowait({"type": "lifespan.shutdown"})
                await stopped.wait()
                await asyncio.gather(task, return_exceptions=True)
            try:
                loop.run_until_complete(main())
            finally:
                try:
                    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                    for t in pending:
                        t.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                finally:
                    loop.close()

        self._thread = threading.Thread(target=runner, name="testclient-loop", daemon=True)
        self._thread.start()
        state = ready.get()
        if state.get("exc") is not None:
            raise state["exc"]
        if state.get("err"):
            raise RuntimeError(state["err"])
        self._portal = True
        return self

    def __exit__(self, *args):
        if self._portal:
            self._loop.call_soon_threadsafe(lambda: self._stop_future.done() or self._stop_future.set_result(None))
            self._thread.join()
            self._portal = None

    # ---- requêtes ----
    def request(self, method, url, *, params=None, data=None, headers=None, cookies=None, files=None, auth=None,
                timeout=None, allow_redirects=True, follow_redirects=None, proxies=None, hooks=None, stream=None,
                verify=None, cert=None, json=None, content=None):
        if follow_redirects is not None:
            allow_redirects = follow_redirects
        full = urllib.parse.urljoin(self.base_url + "/", url) if not url.startswith(("http://", "https://")) else url
        if params:
            sep = "&" if "?" in full else "?"
            full += sep + urllib.parse.urlencode(params, doseq=True)
        hdrs = dict(self.headers)
        extra = {}
        body = b""
        if json is not None:
            body = _json.dumps(json, separators=(",", ":"), ensure_ascii=False).encode()
            extra["content-type"] = "application/json"
        elif content is not None:
            body = content.encode() if isinstance(content, str) else bytes(content)
        elif data is not None:
            if isinstance(data, (bytes, str)):
                body = data.encode() if isinstance(data, str) else data
            elif isinstance(data, dict):
                body = _encode_form(data)
                extra["content-type"] = "application/x-www-form-urlencoded"
        hdrs.update({k.lower(): v for k, v in extra.items()})
        if headers:
            for k, v in headers.items():
                hdrs[k.lower()] = v
        if body or method.upper() in ("POST", "PUT", "PATCH"):
            hdrs.setdefault("content-length", str(len(body)))
        ck = dict(self.cookies)
        ck.update(cookies or {})
        if ck:
            hdrs["cookie"] = "; ".join(f"{k}={v}" for k, v in ck.items())
        history = []
        for _ in range(20):
            resp = self._send(method.upper(), full, hdrs, body)
            if allow_redirects and resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                history.append(resp)
                full = urllib.parse.urljoin(full, resp.headers["location"])
                if resp.status_code in (301, 302, 303) and method.upper() != "HEAD":
                    method, body = "GET", b""
                    hdrs.pop("content-length", None)
                continue
            resp.history = history
            return resp
        raise RuntimeError("Trop de redirections")

    def _send(self, method, url, headers, body):
        u = urllib.parse.urlsplit(url)
        host = u.netloc
        hdrs = dict(headers)
        hdrs.setdefault("host", host)
        raw_path = u.path or "/"
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": urllib.parse.unquote(raw_path),
            "raw_path": raw_path.encode(),
            "root_path": self.root_path,
            "scheme": u.scheme or "http",
            "query_string": u.query.encode(),
            "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in hdrs.items()],
            "client": ("testclient", 50000),
            "server": (u.hostname or "testserver", u.port or (443 if u.scheme == "https" else 80)),
            "extensions": {},
        }
        result = {}

        async def call():
            sent_request = [False]
            response_complete = asyncio.Event()
            chunks = []
            msg = {}

            async def receive():
                if not sent_request[0]:
                    sent_request[0] = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await response_complete.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == "http.response.start":
                    msg["status"] = message["status"]
                    msg["headers"] = message["headers"]
                elif message["type"] == "http.response.body":
                    if method != "HEAD":
                        chunks.append(message.get("body", b""))
                    if not message.get("more_body", False):
                        response_complete.set()
            exc = None
            try:
                await self.app(scope, receive, send)
            except BaseException as e:
                exc = e
            result.update(msg=msg, chunks=chunks, exc=exc)

        if self._portal:
            fut = asyncio.run_coroutine_threadsafe(call(), self._loop)
            fut.result()
        else:
            t = threading.Thread(target=lambda: asyncio.run(call()), daemon=True)
            t.start()
            t.join()
        exc = result.get("exc")
        if exc is not None and self.raise_server_exceptions:
            raise exc
        msg = result["msg"]
        if not msg:
            raise RuntimeError("Aucune réponse de l'application")
        req = _Request(method, url, hdrs.items(), body)
        resp_headers = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in msg["headers"]]
        return TestResponse(msg["status"], resp_headers, b"".join(result["chunks"]), url, req)

    def get(self, url, **kw):
        kw.setdefault("allow_redirects", True)
        return self.request("GET", url, **kw)

    def head(self, url, **kw):
        return self.request("HEAD", url, **kw)

    def options(self, url, **kw):
        return self.request("OPTIONS", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def patch(self, url, **kw):
        return self.request("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)

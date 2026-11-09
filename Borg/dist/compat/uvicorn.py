"""Serveur ASGI HTTP/1.1 minimal (asyncio + stdlib) : l'interface de `uvicorn` utilisée par borgHelperWWW
(`uvicorn.Config`, `uvicorn.Server` — `run`, `startup`, `handle_exit`, `should_exit`, `force_exit`, `started`,
`server_state.connections` — et `uvicorn.run`). Une connexion = un `asyncio.Protocol` ; une requête à la fois par
connexion (pas de pipeline parallèle) ; keep-alive 5 s ; corps de requête (Content-Length ou chunked) transmis par
`receive()` avec contre-pression ; réponse sans Content-Length : chunked (HTTP/1.1) ou fermeture (HTTP/1.0) ;
`http.disconnect` rendu à chaque `receive()` après la perte de la connexion ; lifespan ASGI ; en-têtes
X-Forwarded-For/Proto pris en compte pour les proxys de confiance. Pas de TLS, pas de WebSocket, pas de HTTP/2."""
import asyncio
import email.utils
import functools
import http
import ipaddress
import os
import signal
import sys
import threading
import time
import traceback
import urllib.parse

__version__ = "0.15.0-borgHelperWWW-autonome"

HANDLED_SIGNALS = (signal.SIGINT, signal.SIGTERM)
_MAX_HEADER_BYTES = 65536
_HIGH_WATER = 65536


_LEVELS = {"critical": 50, "error": 40, "warning": 30, "info": 20, "debug": 10, "trace": 5}


def _log(level, msg, threshold=20):
    if _LEVELS[level.lower()] >= threshold:
        print(f"{level + ':':<9} {msg}", file=sys.stderr, flush=True)


class ServerState:
    """État partagé entre le serveur et ses connexions."""

    def __init__(self):
        self.total_requests = 0
        self.connections = set()
        self.tasks = set()
        self.default_headers = []


class FlowControl:
    def __init__(self, transport):
        self._transport = transport
        self.read_paused = False
        self.write_paused = False
        self._is_writable_event = asyncio.Event()
        self._is_writable_event.set()

    async def drain(self):
        await self._is_writable_event.wait()

    def pause_reading(self):
        if not self.read_paused:
            self.read_paused = True
            self._transport.pause_reading()

    def resume_reading(self):
        if self.read_paused:
            self.read_paused = False
            self._transport.resume_reading()

    def pause_writing(self):
        if not self.write_paused:
            self.write_paused = True
            self._is_writable_event.clear()

    def resume_writing(self):
        if self.write_paused:
            self.write_paused = False
            self._is_writable_event.set()


class ProxyHeadersMiddleware:
    """X-Forwarded-For / X-Forwarded-Proto pris en compte si le pair direct est un proxy de confiance (IP exacte, CIDR
    ou « * »)."""

    def __init__(self, app, trusted_hosts="127.0.0.1"):
        self.app = app
        if isinstance(trusted_hosts, str):
            trusted_hosts = [h.strip() for h in trusted_hosts.split(",")]
        self.always_trust = "*" in trusted_hosts
        self.trusted_hosts = set(h for h in trusted_hosts if "/" not in h)
        self.trusted_nets = []
        for h in trusted_hosts:
            if "/" in h:
                try:
                    self.trusted_nets.append(ipaddress.ip_network(h, strict=False))
                except ValueError:
                    pass

    def _trusted(self, host):
        if self.always_trust or host in self.trusted_hosts:
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        return any(ip in n for n in self.trusted_nets)

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            client_addr = scope.get("client")
            client_host = client_addr[0] if client_addr else None
            if client_host is not None and self._trusted(client_host):
                headers = dict(scope["headers"])
                if b"x-forwarded-proto" in headers:
                    scope["scheme"] = headers[b"x-forwarded-proto"].decode("latin1").strip()
                if b"x-forwarded-for" in headers:
                    host = headers[b"x-forwarded-for"].decode("latin1").split(",")[-1].strip()
                    scope["client"] = (host, 0)
        return await self.app(scope, receive, send)


class Config:
    def __init__(self, app, host="127.0.0.1", port=8000, *, lifespan="auto", access_log=True, log_level=None,
                 proxy_headers=True, forwarded_allow_ips=None, root_path="", backlog=2048, timeout_keep_alive=5,
                 limit_concurrency=None, server_header=True, date_header=True, **ignored):
        self.app = app
        self.host = host
        self.port = port
        self.lifespan = lifespan
        self.access_log = access_log
        self.log_level = log_level
        self.log_threshold = _LEVELS.get(str(log_level).lower(), 20) if log_level is not None else 20
        self.proxy_headers = proxy_headers
        if forwarded_allow_ips is None:
            forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
        self.forwarded_allow_ips = forwarded_allow_ips
        self.root_path = root_path
        self.backlog = backlog
        self.timeout_keep_alive = timeout_keep_alive
        self.limit_concurrency = limit_concurrency
        self.date_header = date_header
        self.loaded = False

    def log(self, level, msg):
        _log(level, msg, self.log_threshold)

    def load(self):
        self.lifespan_class = LifespanOff if self.lifespan == "off" else Lifespan
        self.loaded_app = self.app
        if self.proxy_headers:
            self.loaded_app = ProxyHeadersMiddleware(self.loaded_app, trusted_hosts=self.forwarded_allow_ips)
        self.loaded = True


class Lifespan:
    """Pilote le protocole ASGI lifespan de l'application (démarrage/arrêt)."""

    def __init__(self, config):
        self.config = config
        self.startup_event = asyncio.Event()
        self.shutdown_event = asyncio.Event()
        self.receive_queue = asyncio.Queue()
        self.error_occured = False
        self.startup_failed = False
        self.shutdown_failed = False
        self.should_exit = False
        self._task = None

    async def startup(self):
        self.config.log("INFO", "Waiting for application startup.")
        self._task = asyncio.get_running_loop().create_task(self.main())
        await self.receive_queue.put({"type": "lifespan.startup"})
        await self.startup_event.wait()
        if self.startup_failed or (self.error_occured and self.config.lifespan == "on"):
            self.config.log("ERROR", "Application startup failed. Exiting.")
            self.should_exit = True
        else:
            self.config.log("INFO", "Application startup complete.")

    async def shutdown(self):
        if self.error_occured:
            return
        self.config.log("INFO", "Waiting for application shutdown.")
        await self.receive_queue.put({"type": "lifespan.shutdown"})
        await self.shutdown_event.wait()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        self.config.log("INFO", "Application shutdown complete.")

    async def main(self):
        try:
            scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}}
            await self.config.loaded_app(scope, self.receive, self.send)
        except BaseException as exc:
            self.error_occured = True
            if self.startup_failed or self.shutdown_failed:
                return
            if self.config.lifespan == "auto":
                self.config.log("INFO", "ASGI 'lifespan' protocol appears unsupported.")
            else:
                self.config.log("ERROR", "Exception in 'lifespan' protocol\n" + "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)))
        finally:
            self.startup_event.set()
            self.shutdown_event.set()

    async def send(self, message):
        mtype = message["type"]
        if mtype == "lifespan.startup.complete":
            self.startup_event.set()
        elif mtype == "lifespan.startup.failed":
            self.startup_event.set()
            self.startup_failed = True
            if message.get("message"):
                self.config.log("ERROR", message["message"])
        elif mtype == "lifespan.shutdown.complete":
            self.shutdown_event.set()
        elif mtype == "lifespan.shutdown.failed":
            self.shutdown_event.set()
            self.shutdown_failed = True
            if message.get("message"):
                self.config.log("ERROR", message["message"])

    async def receive(self):
        return await self.receive_queue.get()


class LifespanOff:
    """lifespan='off' : aucun protocole lifespan (démarrage/arrêt de l'application non notifiés)."""

    def __init__(self, config):
        self.config = config
        self.should_exit = False
        self.error_occured = False

    async def startup(self):
        pass

    async def shutdown(self):
        pass


class RequestResponseCycle:
    """Une requête HTTP : fournit `receive`/`send` ASGI et suit l'état de la réponse."""

    def __init__(self, protocol, scope, keep_alive, expect_continue, has_body):
        self.p = protocol
        self.scope = scope
        self.keep_alive = keep_alive
        self.waiting_for_100_continue = expect_continue
        self.is_head = scope["method"] == "HEAD"
        self.disconnected = False
        self.response_started = False
        self.response_complete = False
        self.body = b""
        self.more_body = has_body
        self.message_event = asyncio.Event()
        self.chunked_response = False
        self.http10 = scope["http_version"] == "1.0"

    # ---- ASGI ----
    async def run_asgi(self, app):
        try:
            result = await app(self.scope, self.receive, self.send)
        except asyncio.CancelledError:
            self.p.transport.close()
            raise
        except BaseException as exc:
            self.p.config.log("ERROR", "Exception in ASGI application\n" + "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip("\n"))
            if not self.response_started:
                await self.send_500_response()
            else:
                self.p.transport.close()
        else:
            if result is not None:
                self.p.config.log("ERROR", f"ASGI callable should return None, but returned '{result}'.")
                self.p.transport.close()
            elif not self.response_started and not self.disconnected:
                self.p.config.log("ERROR", "ASGI callable returned without starting response.")
                await self.send_500_response()
            elif not self.response_complete and not self.disconnected:
                self.p.config.log("ERROR", "ASGI callable returned without completing response.")
                self.p.transport.close()
        finally:
            self.p.on_cycle_end(self)

    async def send_500_response(self):
        await self.send({"type": "http.response.start", "status": 500, "headers": [
            (b"content-type", b"text/plain; charset=utf-8"), (b"content-length", b"21"), (b"connection", b"close")]})
        await self.send({"type": "http.response.body", "body": b"Internal Server Error"})

    async def send(self, message):
        p = self.p
        mtype = message["type"]
        if p.flow.write_paused and not self.disconnected:
            await p.flow.drain()
        if self.disconnected:
            return
        if not self.response_started:
            if mtype != "http.response.start":
                raise RuntimeError(f"Expected ASGI message 'http.response.start', but got '{mtype}'.")
            status = message["status"]
            headers = [(bytes(k), bytes(v)) for k, v in message.get("headers", [])]
            for k, v in headers:
                if b"\r" in k or b"\n" in k or b":" in k or not k or b"\r" in v or b"\n" in v:
                    raise RuntimeError("Illegal header in ASGI response")
            names = {k.lower() for k, _ in headers}
            has_length = b"content-length" in names
            bodyless = self.is_head or status < 200 or status in (204, 304)
            if p.config_date_header and b"date" not in names:
                headers.append((b"date", p.date_header()))
            if self.waiting_for_100_continue or self.more_body_pending():
                self.keep_alive = False   # corps de requête non lu : connexion non réutilisable
            if b"transfer-encoding" in names:
                self.chunked_response = any(v.lower() == b"chunked" for k, v in headers if k.lower() == b"transfer-encoding")
            elif not has_length and not bodyless:
                if self.http10:
                    self.keep_alive = False
                else:
                    headers.append((b"transfer-encoding", b"chunked"))
                    self.chunked_response = True
            conn = [v for k, v in headers if k.lower() == b"connection"]
            if not self.keep_alive and not any(b"close" in v.lower() for v in conn):
                headers.append((b"connection", b"close"))
            try:
                phrase = http.HTTPStatus(status).phrase
            except ValueError:
                phrase = ""
            lines = [f"HTTP/1.1 {status} {phrase}".encode("latin-1")]
            lines.extend(k + b": " + v for k, v in headers)
            p.transport.write(b"\r\n".join(lines) + b"\r\n\r\n")
            self.response_started = True
            self.waiting_for_100_continue = False
            self.bodyless = bodyless
        elif not self.response_complete:
            if mtype != "http.response.body":
                raise RuntimeError(f"Expected ASGI message 'http.response.body', but got '{mtype}'.")
            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            if body and not self.bodyless:
                if self.chunked_response:
                    p.transport.write(b"%x\r\n" % len(body) + body + b"\r\n")
                else:
                    p.transport.write(body)
            if not more_body:
                if self.chunked_response and not self.bodyless:
                    p.transport.write(b"0\r\n\r\n")
                self.response_complete = True
                self.message_event.set()
                p.on_response_complete(self)
        else:
            raise RuntimeError(f"Unexpected ASGI message '{mtype}' sent, after response already completed.")

    def more_body_pending(self):
        return self.more_body

    async def receive(self):
        p = self.p
        if self.waiting_for_100_continue and not p.transport.is_closing():
            p.transport.write(b"HTTP/1.1 100 Continue\r\n\r\n")
            self.waiting_for_100_continue = False
        if not self.disconnected and not self.response_complete:
            p.flow.resume_reading()
            await self.message_event.wait()
            self.message_event.clear()
        if self.disconnected or self.response_complete:
            return {"type": "http.disconnect"}
        message = {"type": "http.request", "body": self.body, "more_body": self.more_body}
        self.body = b""
        return message


class HttpProtocol(asyncio.Protocol):
    def __init__(self, config, server_state):
        self.config = config
        self.app = config.loaded_app
        self.config_date_header = config.date_header
        self.server_state = server_state
        self.loop = asyncio.get_event_loop()
        self.transport = None
        self.flow = None
        self.server = None
        self.client = None
        self.scheme = "http"
        self.buf = bytearray()
        self.cycle = None
        self.keepalive_handle = None
        self.body_mode = None      # None | ("length", restant) | ("chunked", état)
        self._date = (0, b"")

    # ---- connexion ----
    def connection_made(self, transport):
        self.server_state.connections.add(self)
        self.transport = transport
        self.flow = FlowControl(transport)
        sock = transport.get_extra_info("sockname")
        peer = transport.get_extra_info("peername")
        self.server = (sock[0], sock[1]) if isinstance(sock, tuple) else None
        self.client = (peer[0], peer[1]) if isinstance(peer, tuple) else None
        self._arm_keepalive()

    def connection_lost(self, exc):
        self.server_state.connections.discard(self)
        self._cancel_keepalive()
        if self.cycle is not None:
            self.cycle.disconnected = True
            self.cycle.message_event.set()
        if self.flow is not None:
            self.flow.resume_writing()
        self.buf.clear()

    def eof_received(self):
        return None

    def pause_writing(self):
        self.flow.pause_writing()

    def resume_writing(self):
        self.flow.resume_writing()

    def shutdown(self):
        """Arrêt du serveur : connexion inactive fermée ; requête en cours : fermée à la fin de sa réponse."""
        if self.cycle is None or self.cycle.response_complete:
            self.transport.close()
        else:
            self.cycle.keep_alive = False

    def date_header(self):
        now = int(time.time())
        if self._date[0] != now:
            self._date = (now, email.utils.formatdate(now, usegmt=True).encode("latin-1"))
        return self._date[1]

    # ---- keep-alive ----
    def _arm_keepalive(self):
        self._cancel_keepalive()
        t = self.config.timeout_keep_alive
        if t:
            self.keepalive_handle = self.loop.call_later(t, self._keepalive_timeout)

    def _cancel_keepalive(self):
        if self.keepalive_handle is not None:
            self.keepalive_handle.cancel()
            self.keepalive_handle = None

    def _keepalive_timeout(self):
        if self.cycle is None and not self.transport.is_closing():
            self.transport.close()

    # ---- réception ----
    def data_received(self, data):
        self._cancel_keepalive()
        self.buf += data
        self._process()

    def _bad_request(self, why):
        self.config.log("WARNING", f"Invalid HTTP request received ({why}).")
        if self.cycle is None or not self.cycle.response_started:
            try:
                body = (why + "\n").encode("latin-1", "replace")
                self.transport.write(b"HTTP/1.1 400 Bad Request\r\ncontent-type: text/plain; charset=utf-8\r\n"
                                     b"connection: close\r\ncontent-length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            except Exception:
                pass
        self.transport.close()

    def _process(self):
        while True:
            if self.transport is None or self.transport.is_closing():
                return
            if self.cycle is not None:
                if self.body_mode is not None:
                    if not self._feed_body():
                        return
                    continue
                if len(self.buf) > _HIGH_WATER:
                    self.flow.pause_reading()   # requête suivante (pipeline) : attendre la fin de la réponse
                return
            idx = self.buf.find(b"\r\n\r\n")
            if idx < 0:
                if len(self.buf) > _MAX_HEADER_BYTES:
                    self._bad_request("En-têtes de requête trop longs")
                return
            head = bytes(self.buf[:idx])
            del self.buf[:idx + 4]
            if not self._start_request(head):
                return

    def _start_request(self, head):
        try:
            lines = head.split(b"\r\n")
            while lines and not lines[0]:
                lines.pop(0)
            reqline = lines[0].split(b" ")
            if len(reqline) != 3:
                raise ValueError("ligne de requête invalide")
            method, target, version = reqline
            if not method.isalpha() and not method.replace(b"-", b"").isalnum():
                raise ValueError("méthode invalide")
            if version not in (b"HTTP/1.1", b"HTTP/1.0"):
                raise ValueError("version HTTP non prise en charge")
            headers = []
            for line in lines[1:]:
                if b":" not in line or line[:1] in (b" ", b"\t"):
                    raise ValueError("en-tête invalide")
                k, v = line.split(b":", 1)
                if not k or k != k.strip() or b" " in k:
                    raise ValueError("nom d'en-tête invalide")
                headers.append((k.lower(), v.strip(b" \t")))
        except ValueError as e:
            self._bad_request(str(e))
            return False
        http_version = version[5:].decode()
        hd = {}
        for k, v in headers:
            hd.setdefault(k, []).append(v)
        # corps de la requête
        te = hd.get(b"transfer-encoding")
        cl = hd.get(b"content-length")
        mode = None
        if te:
            if cl or [x.strip().lower() for x in b",".join(te).split(b",")] != [b"chunked"]:
                self._bad_request("Transfer-Encoding/Content-Length invalides")
                return False
            mode = ("chunked", "size", 0)
        elif cl:
            vals = {v.strip() for v in b",".join(cl).split(b",")}
            if len(vals) != 1 or not next(iter(vals)).isdigit():
                self._bad_request("Content-Length invalide")
                return False
            n = int(next(iter(vals)))
            if n:
                mode = ("length", n)
        conn_tokens = [t.strip().lower() for v in hd.get(b"connection", []) for t in v.split(b",")]
        if http_version == "1.0":
            keep_alive = False   # HTTP/1.0 : toujours fermée après la réponse (comme h11 d'uvicorn)
        else:
            keep_alive = b"close" not in conn_tokens
        expect = http_version == "1.1" and any(v.lower() == b"100-continue" for v in hd.get(b"expect", [])) and mode is not None
        # cible
        try:
            tgt = target
            if not tgt.startswith(b"/") and tgt != b"*":
                u = urllib.parse.urlsplit(tgt.decode("latin-1"))
                tgt = (u.path or "/").encode("latin-1") + ((b"?" + u.query.encode("latin-1")) if u.query else b"")
            raw_path, _, query = tgt.partition(b"?")
            raw_path = raw_path.partition(b"#")[0]
            path = urllib.parse.unquote(raw_path.decode("utf-8", "replace"))
        except Exception:
            self._bad_request("Cible de requête invalide")
            return False
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.1"},
            "http_version": http_version,
            "server": self.server,
            "client": self.client,
            "scheme": self.scheme,
            "method": method.decode("ascii").upper(),
            "root_path": self.config.root_path,
            "path": path,
            "raw_path": raw_path,
            "query_string": query,
            "headers": headers,
        }
        self.server_state.total_requests += 1
        self.cycle = RequestResponseCycle(self, scope, keep_alive, expect, mode is not None)
        self.body_mode = mode
        if mode is None:
            self.cycle.more_body = False
            self.cycle.message_event.set()
        task = self.loop.create_task(self.cycle.run_asgi(self.app))
        self.server_state.tasks.add(task)
        task.add_done_callback(self.server_state.tasks.discard)
        return True

    def _feed_body(self):
        """Consomme le tampon pour le corps de la requête en cours ; rend False s'il faut attendre des octets."""
        cyc = self.cycle
        mode = self.body_mode
        got = False
        if mode[0] == "length":
            rest = mode[1]
            take = min(rest, len(self.buf))
            if take:
                cyc.body += bytes(self.buf[:take])
                del self.buf[:take]
                got = True
            rest -= take
            if rest == 0:
                self.body_mode = None
                cyc.more_body = False
            else:
                self.body_mode = ("length", rest)
        else:   # chunked
            state, rest = mode[1], mode[2]
            while True:
                if state == "size":
                    i = self.buf.find(b"\r\n")
                    if i < 0:
                        if len(self.buf) > 4096:
                            self._bad_request("Chunk invalide")
                            return False
                        break
                    try:
                        size = int(bytes(self.buf[:i]).split(b";")[0].strip(), 16)
                    except ValueError:
                        self._bad_request("Taille de chunk invalide")
                        return False
                    del self.buf[:i + 2]
                    state, rest = ("trailer", 0) if size == 0 else ("data", size)
                elif state == "data":
                    take = min(rest, len(self.buf))
                    if take:
                        cyc.body += bytes(self.buf[:take])
                        del self.buf[:take]
                        got = True
                    rest -= take
                    if rest:
                        break
                    state = "crlf"
                elif state == "crlf":
                    if len(self.buf) < 2:
                        break
                    if bytes(self.buf[:2]) != b"\r\n":
                        self._bad_request("Chunk invalide")
                        return False
                    del self.buf[:2]
                    state = "size"
                else:   # trailer : jusqu'à une ligne vide
                    i = self.buf.find(b"\r\n")
                    if i < 0:
                        break
                    line = bytes(self.buf[:i])
                    del self.buf[:i + 2]
                    if not line:
                        self.body_mode = None
                        cyc.more_body = False
                        break
            if self.body_mode is not None:
                self.body_mode = ("chunked", state, rest)
        if got or not cyc.more_body:
            cyc.message_event.set()
        if cyc.more_body and len(cyc.body) > _HIGH_WATER:
            self.flow.pause_reading()
        return self.body_mode is None   # corps complet : poursuivre l'analyse ; sinon attendre

    # ---- fin de requête ----
    def on_response_complete(self, cycle):
        self.server_state.total_requests += 0
        # la suite (nouvelle requête) est lancée en fin de tâche : on_cycle_end

    def on_cycle_end(self, cycle):
        if self.cycle is not cycle:
            return
        if self.transport is None or self.transport.is_closing():
            self.cycle = None
            return
        if not cycle.response_complete or not cycle.keep_alive or cycle.disconnected:
            self.cycle = None
            self.transport.close()
            return
        self.cycle = None
        self.body_mode = None
        self.flow.resume_reading()
        if self.buf:
            self._process()
        else:
            self._arm_keepalive()


class Server:
    def __init__(self, config):
        self.config = config
        self.server_state = ServerState()
        self.started = False
        self.should_exit = False
        self.force_exit = False
        self.last_notified = 0
        self.servers = []
        self.lifespan = None

    def run(self, sockets=None):
        return asyncio.run(self.serve(sockets=sockets))

    async def serve(self, sockets=None):
        process_id = os.getpid()
        config = self.config
        if not config.loaded:
            config.load()
        self.lifespan = config.lifespan_class(config)
        self.install_signal_handlers()
        self.config.log("INFO", f"Started server process [{process_id}]")
        await self.startup(sockets=sockets)
        if self.should_exit:
            return
        await self.main_loop()
        await self.shutdown(sockets=sockets)
        self.config.log("INFO", f"Finished server process [{process_id}]")

    async def startup(self, sockets=None):
        await self.lifespan.startup()
        if self.lifespan.should_exit:
            self.should_exit = True
            return
        config = self.config
        loop = asyncio.get_running_loop()
        create_protocol = functools.partial(HttpProtocol, config=config, server_state=self.server_state)
        try:
            server = await loop.create_server(create_protocol, host=config.host, port=config.port, backlog=config.backlog)
        except OSError as exc:
            self.config.log("ERROR", str(exc))
            await self.lifespan.shutdown()
            self.should_exit = True
            return
        self.servers = [server]
        host = config.host
        port = config.port
        if server.sockets:
            port = server.sockets[0].getsockname()[1]
        shown = f"[{host}]" if ":" in str(host) else host
        self.config.log("INFO", f"Serveur HTTP à l'écoute sur http://{shown}:{port} (CTRL+C pour arrêter)")
        self.started = True

    async def main_loop(self):
        counter = 0
        should_exit = await self.on_tick(counter)
        while not should_exit:
            counter += 1
            counter = counter % 864000
            await asyncio.sleep(0.1)
            should_exit = await self.on_tick(counter)

    async def on_tick(self, counter):
        if self.should_exit:
            return True
        max_requests = None
        return max_requests is not None and self.server_state.total_requests >= max_requests

    async def shutdown(self, sockets=None):
        self.config.log("INFO", "Shutting down")
        for server in self.servers:
            server.close()
        for server in self.servers:
            await server.wait_closed()
        for connection in list(self.server_state.connections):
            connection.shutdown()
        await asyncio.sleep(0.1)
        if self.server_state.connections and not self.force_exit:
            self.config.log("INFO", "Waiting for connections to close. (CTRL+C to force quit)")
            while self.server_state.connections and not self.force_exit:
                await asyncio.sleep(0.1)
        if self.server_state.tasks and not self.force_exit:
            self.config.log("INFO", "Waiting for background tasks to complete. (CTRL+C to force quit)")
            while self.server_state.tasks and not self.force_exit:
                await asyncio.sleep(0.1)
        if not self.force_exit:
            await self.lifespan.shutdown()

    def install_signal_handlers(self):
        if threading.current_thread() is not threading.main_thread():
            return
        loop = asyncio.get_running_loop()
        try:
            for sig in HANDLED_SIGNALS:
                loop.add_signal_handler(sig, self.handle_exit, sig, None)
        except NotImplementedError:
            for sig in HANDLED_SIGNALS:
                signal.signal(sig, self.handle_exit)

    def handle_exit(self, sig, frame):
        if self.should_exit:
            self.force_exit = True
        else:
            self.should_exit = True


def run(app, **kwargs):
    config = Config(app, **kwargs)
    server = Server(config=config)
    server.run()

"""Agent OpenSSH dédié : `ssh-agent` et `ssh-add` d'OpenSSH (≥ 8.9), sur un socket à sshvault.

- Socket : `$XDG_RUNTIME_DIR/sshvault/agent.sock` (chemin canonique), sur un XDG_RUNTIME_DIR
  vérifié privé et en tmpfs ; variable absente : repli sur `/run/user/<uid>` s'il passe la
  même vérification ; sinon refus (AgentError).
- Démarrage : `ssh-agent -s -a <socket>` (jamais `-d`/`-D`), pid relevé dans sa sortie et
  enregistré dans l'état avec l'identité du socket (st_dev, st_ino). Un surveillant détaché
  (`python -m sshvault.watch`, sa propre session) arrête l'agent dès que son socket ou
  XDG_RUNTIME_DIR disparaît (fin de session), puis s'arrête ; il s'arrête aussi si l'agent meurt.
- Un agent est « à sshvault » si son socket répond, est celui enregistré, et si le pid
  enregistré est un processus de l'utilisateur dont la ligne de commande est
  `ssh-agent … -a <socket>`. Ce contrôle précède tout signal. État perdu ou illisible : un
  seul ssh-agent de l'utilisateur visant ce socket est repris (enregistrement reconstruit).
  Un socket vivant sans tel agent est un agent tiers : refus, rien n'est touché.
- Orphelins : tout ssh-agent de l'utilisateur visant notre socket alors que ce socket a
  disparu, ne répond plus, ou appartient à l'agent enregistré, est arrêté.
- Verrou inter-processus : `flock` sur le dossier `sshvault/` (aucun fichier créé), tenu de
  l'examen au démarrage de l'agent et autour de chaque lecture-modification-écriture de l'état.
- Chaque appel `ssh-add` reçoit `SSH_AUTH_SOCK` = socket dédié : l'agent de l'utilisateur
  (`SSH_AUTH_SOCK` hérité) n'est jamais lu ni modifié.
- La clé privée ne passe que par le stdin de `ssh-add -` : jamais en argument, fichier,
  journal ou sortie.
"""
from __future__ import annotations

import base64
import contextlib
import errno
import fcntl
import os
import re
import shutil
import signal
import socket as _socket
import stat
import subprocess
import sys
import termios
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

from .agentstate import STATE_NAME, AgentState, empty
from .fsutil import ensure_dir
from .prompt import open_foreground_tty
# briques légères (aussi pour le chemin rapide d'ensure), réexportées ici
from .runtime import (DIR_NAME, RUN_USER, SOCKET_NAME, SUN_PATH_MAX, AgentError, fingerprint,  # noqa: F401
                      parse_listing, public_blob, resolve_dir)

CMD_TIMEOUT = 30.0
STOP_WAIT = 5.0
MIN_OPENSSH = (8, 9)
#: _PATH_SSH_ASKPASS_DEFAULT d'ssh-add 8.9 (Ubuntu), utilisé si SSH_ASKPASS n'est pas défini
DEFAULT_ASKPASS = "/usr/bin/ssh-askpass"
WATCH_MODULE = "sshvault.watch"
_PID_RE = re.compile(rb"SSH_AGENT_PID=(\d+);")
_NO_HOSTKEY_RE = re.compile(r'No host keys found for destination "([^"]*)"')
#: Hôte accepté par --restrict : nom ou IPv4 littéral (pas de motif, user@, >, :port, IPv6).
LITERAL_HOST_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")


class AgentStopped(AgentError):
    """Agent dédié arrêté (code 3)."""


class AgentLocked(AgentError):
    """Agent verrouillé, ou mot de passe de verrouillage refusé (code 3)."""


class PassphraseRefused(AgentError):
    """Passphrase de la clé refusée, annulée ou impossible à saisir (code 3)."""


class AgentForeign(AgentError):
    """Socket vivant d'un agent non lancé par sshvault (code 4)."""


class HostKeyMissing(AgentError):
    """`--restrict` : hôte absent de known_hosts (code 4)."""


def _one_line(data, limit: int = 300) -> str:
    if isinstance(data, bytes):
        data = data.decode(errors="replace")
    s = " ".join(l.strip() for l in (data or "").splitlines() if l.strip())
    s = re.sub(r"[\x00-\x1f\x7f-\x9f]", "?", s)
    return s if len(s) <= limit else s[: limit - 1] + "…"


@dataclass(frozen=True)
class AgentKey:
    type: str
    blob: str
    comment: str
    fingerprint: str


def is_encrypted(key: bytes) -> bool:
    """Clé privée chiffrée par passphrase ? (en-tête OpenSSH, PEM `Proc-Type: 4,ENCRYPTED`,
    PKCS#8 chiffré). Lecture des seuls en-têtes, aucun déchiffrement."""
    if b"-----BEGIN ENCRYPTED PRIVATE KEY-----" in key or b"Proc-Type: 4,ENCRYPTED" in key:
        return True
    m = re.search(rb"-----BEGIN OPENSSH PRIVATE KEY-----(.*?)-----END OPENSSH PRIVATE KEY-----", key, re.S)
    if not m:
        return False
    try:
        blob = base64.b64decode(b"".join(m.group(1).split()))
    except ValueError:
        return False
    magic = b"openssh-key-v1\0"
    if not blob.startswith(magic) or len(blob) < len(magic) + 4:
        return False
    n = int.from_bytes(blob[len(magic):len(magic) + 4], "big")
    return blob[len(magic) + 4:len(magic) + 4 + n] != b"none"


def literal_host(host: str) -> bool:
    return bool(LITERAL_HOST_RE.fullmatch(host or ""))


# --- invites (règles de readpass.c, OpenSSH 8.9) ---------------------------------------

def askpass_rules(env: Mapping[str, str]):
    """(permis, utilisable) pour un `read_passphrase()` d'OpenSSH 8.9 : askpass permis si
    DISPLAY est non vide ou SSH_ASKPASS_REQUIRE=force, jamais si =never (WAYLAND_DISPLAY
    n'est pas lu par la 8.9) ; utilisable si le programme (SSH_ASKPASS, sinon
    /usr/bin/ssh-askpass) est exécutable."""
    allow = bool(env.get("DISPLAY"))
    req = (env.get("SSH_ASKPASS_REQUIRE") or "").lower()
    if req == "force":
        allow = True
    elif req == "never":
        allow = False
    prog = env.get("SSH_ASKPASS") or DEFAULT_ASKPASS
    path = prog if "/" in prog else (shutil.which(prog, path=env.get("PATH")) or "")
    usable = allow and bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)
    return allow, usable


def tty_available() -> bool:
    """Terminal de contrôle utilisable : `/dev/tty` ouvrable **et** processus au premier plan
    (en arrière-plan, ssh-add lisant `/dev/tty` serait arrêté par SIGTTIN, et couper l'écho
    toucherait le terminal d'un autre travail)."""
    fd = open_foreground_tty()
    if fd is None:
        return False
    os.close(fd)
    return True


class NoEcho:
    """Écho de /dev/tty coupé le temps d'un `ssh-add` interactif.

    Mesuré (OpenSSH 8.9p1-3ubuntu0.17) : avec la clé sur stdin (`ssh-add -`), ssh-add lit la
    passphrase sur /dev/tty **sans couper l'écho** : elle s'afficherait en clair (avec un
    fichier en argument, ou pour `-x`/`-X`, l'écho est bien coupé). Il respecte en revanche
    un écho déjà coupé. Saisie anticipée jetée (TCSAFLUSH), état d'origine rétabli sur tous
    les chemins ; fin de ligne ajoutée si `newline` (invite probable)."""

    def __init__(self, newline: bool = True):
        self.fd, self.old, self.newline = None, None, newline

    def __enter__(self):
        self.fd = open_foreground_tty()
        if self.fd is None:
            return self
        try:
            self.old = termios.tcgetattr(self.fd)
            new = list(self.old)
            new[3] = (new[3] & ~(termios.ECHO | termios.ECHONL)) | termios.ICANON
            termios.tcsetattr(self.fd, termios.TCSAFLUSH, new)
        except (OSError, termios.error):
            self.old = None
        return self

    def __exit__(self, *exc):
        if self.fd is None:
            return False
        try:
            if self.old is not None:
                termios.tcsetattr(self.fd, termios.TCSANOW, self.old)
                if self.newline:
                    os.write(self.fd, b"\n")
        except (OSError, termios.error):
            pass
        finally:
            os.close(self.fd)
        return False


# --- processus ---------------------------------------------------------------------------

def _alive(pid: int) -> bool:
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[-1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def _cmdline(pid: int) -> Optional[list]:
    try:
        if os.stat("/proc/%d" % pid).st_uid != os.getuid():
            return None
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    return [a.decode(errors="replace") for a in raw.split(b"\0")[:-1]] if raw else None


def _user_pids():
    for d in os.listdir("/proc"):
        if d.isdigit():
            yield int(d)


def _wait_gone(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while _alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def openssh_version(ssh_add: str) -> Optional[tuple]:
    """Version d'OpenSSH par `ssh -V` (le `ssh` voisin de ssh-add, sinon celui du PATH)."""
    found = shutil.which(ssh_add) or ""
    ssh = os.path.join(os.path.dirname(os.path.abspath(found)), "ssh") if found else ""
    if not (ssh and os.access(ssh, os.X_OK)):
        ssh = shutil.which("ssh") or "ssh"
    try:
        r = subprocess.run([ssh, "-V"], capture_output=True, timeout=CMD_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(rb"OpenSSH_(\d+)\.(\d+)", r.stderr + r.stdout)
    return (int(m.group(1)), int(m.group(2))) if m else None


class Agent:
    def __init__(self, directory: str, env: Optional[Mapping[str, str]] = None,
                 ssh_agent: Optional[str] = None, ssh_add: Optional[str] = None,
                 known_hosts: Optional[str] = None, clock=time.time):
        self.env = dict(os.environ if env is None else env)
        self.dir = directory
        self.socket = os.path.join(directory, SOCKET_NAME)
        self.state = AgentState(os.path.join(directory, STATE_NAME))
        self.ssh_agent = ssh_agent or self.env.get("SSHVAULT_SSH_AGENT") or "ssh-agent"
        self.ssh_add = ssh_add or self.env.get("SSHVAULT_SSH_ADD") or "ssh-add"
        kh = known_hosts if known_hosts is not None else self.env.get("SSHVAULT_KNOWN_HOSTS", "")
        self.known_hosts = [p for p in kh.split(os.pathsep) if p]
        self.clock = clock
        self._lock_depth = 0
        self._lock_fd = None

    # --- verrou inter-processus ----------------------------------------------------

    @contextlib.contextmanager
    def locked(self, create: bool = True):
        """`flock` exclusif sur le dossier `sshvault/` (réentrant dans le processus). Sans
        `create`, un dossier absent n'est pas créé et rien n'est verrouillé."""
        if self._lock_depth:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return
        if create:
            try:
                ensure_dir(self.dir)
            except OSError as e:
                raise AgentError("dossier %s : %s" % (self.dir, e.strerror or e)) from None
        try:
            fd = os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY)
        except FileNotFoundError:
            if create:
                raise AgentError("dossier %s disparu" % self.dir) from None
            yield
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self._lock_fd, self._lock_depth = fd, 1
            yield
        finally:
            self._lock_depth, self._lock_fd = 0, None
            os.close(fd)  # libère le verrou

    # --- identité de l'agent -----------------------------------------------------

    def targets_socket(self, pid: int) -> bool:
        """Processus vivant de l'utilisateur dont la ligne de commande contient `-a <socket>`."""
        if not isinstance(pid, int) or pid <= 1 or not _alive(pid):
            return False
        argv = _cmdline(pid)
        return bool(argv) and any(a == "-a" and i + 1 < len(argv) and argv[i + 1] == self.socket
                                  for i, a in enumerate(argv))

    def pid_is_agent(self, pid: int) -> bool:
        """Processus vivant de l'utilisateur, lancé comme `ssh-agent … -a <ce socket>`."""
        if not self.targets_socket(pid):
            return False
        return os.path.basename(_cmdline(pid)[0]) == "ssh-agent"

    def is_watcher(self, pid: int, agent_pid: Optional[int] = None) -> bool:
        """Surveillant `python -m sshvault.watch <pid> <socket> …` de l'utilisateur."""
        if not isinstance(pid, int) or pid <= 1 or not _alive(pid):
            return False
        argv = _cmdline(pid) or []
        if WATCH_MODULE not in argv:
            return False
        i = argv.index(WATCH_MODULE)
        rest = argv[i + 1:]
        return (len(rest) >= 2 and rest[1] == self.socket
                and (agent_pid is None or rest[0] == str(agent_pid)))

    def _agents_on_path(self) -> list:
        return [p for p in _user_pids() if p != os.getpid() and self.pid_is_agent(p)]

    def _listening(self) -> bool:
        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        s.settimeout(5)
        try:
            s.connect(self.socket)
            return True
        except OSError as e:
            if e.errno in (errno.ECONNREFUSED, errno.ENOENT):
                return False
            raise AgentError("socket %s : %s" % (self.socket, e.strerror or e)) from None
        finally:
            s.close()

    def _socket_stat(self) -> Optional[os.stat_result]:
        try:
            st = os.lstat(self.socket)
        except FileNotFoundError:
            return None
        except OSError as e:
            raise AgentError("socket %s : %s" % (self.socket, e.strerror or e)) from None
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
            raise AgentError("%s n'est pas un socket à l'utilisateur : rien touché" % self.socket)
        return st

    def _record_ok(self, rec, st) -> bool:
        return bool(rec and st and rec["socket"] == self.socket
                    and (rec["dev"], rec["ino"]) == (st.st_dev, st.st_ino) and self.pid_is_agent(rec["pid"]))

    def reap_orphans(self) -> list:
        """Arrête les ssh-agent de l'utilisateur qui visent notre socket sans le servir : socket
        disparu ou muet, ou socket servi par l'agent enregistré. Renvoie leurs pids."""
        with self.locked(create=False):
            cands = self._agents_on_path()
            if not cands:
                return []
            st = self._socket_stat()
            live = st is not None and self._listening()
            rec = self.state.load().get("agent")
            if live and not self._record_ok(rec, st):
                return []  # repris ou refusé par probe(), pas un orphelin
            orphans = [p for p in cands if not live or p != rec["pid"]]
            for p in orphans:
                self._kill(p, self.pid_is_agent, hard=True)
            return orphans

    def probe(self):
        """("absent" | "dead" | "ours" | "foreign", état enregistré). Sous verrou s'il est tenu."""
        self.reap_orphans()
        data, how = self.state.load_checked()
        st = self._socket_stat()
        if st is None:
            return "absent", data
        if not self._listening():
            return "dead", data
        if self._record_ok(data.get("agent"), st):
            return "ours", data
        # état perdu, illisible, ou base écrite autrement : reprise d'un seul ssh-agent visant ce socket
        cands = self._agents_on_path()
        if len(cands) == 1:
            with self.locked():
                if how != "ok":
                    data = empty()
                pid = cands[0]
                watchers = [p for p in _user_pids() if self.is_watcher(p, pid)]
                data["agent"] = {"pid": pid, "socket": self.socket, "dev": st.st_dev, "ino": st.st_ino,
                                 "started": None, "askpass": None,
                                 "watcher": watchers[0] if watchers else self._spawn_watcher(pid, st)}
                self.state.save(data)
            return "ours", data
        return "foreign", data

    def save(self, data: dict) -> None:
        """Écrit l'état. Jamais un état sans agent par-dessus l'enregistrement d'un agent vivant."""
        try:
            if data.get("agent") is None:
                cur = self.state.load().get("agent")
                if cur and self.pid_is_agent(cur["pid"]):
                    data["agent"] = cur
            self.state.save(data)
        except OSError as e:
            raise AgentError("écriture de l'état %s : %s" % (self.state.path, e.strerror or e)) from None

    def update(self, fn: Callable[[dict], None]) -> dict:
        """Lecture-modification-écriture de l'état sous verrou."""
        with self.locked():
            data = self.state.load()
            fn(data)
            self.save(data)
            return data

    def foreign(self) -> AgentForeign:
        return AgentForeign("agent non lancé par sshvault sur %s : rien touché (l'arrêter à la main ou "
                            "libérer ce socket)" % self.socket)

    def running(self) -> dict:
        """État d'un agent vivant à sshvault ; sinon AgentStopped ou AgentForeign."""
        kind, data = self.probe()
        if kind == "foreign":
            raise self.foreign()
        if kind != "ours":
            raise AgentStopped("agent arrêté (%s)" % self.socket)
        return data

    # --- démarrage, nettoyage, arrêt ------------------------------------------

    def _kill(self, pid: int, check: Callable[[int], bool], hard: bool = False) -> None:
        """Arrête `pid` s'il passe `check` : SIGTERM, puis SIGKILL s'il survit (revérifié avant).
        `hard` : SIGKILL d'emblée. Pour un ssh-agent qui n'est pas celui du socket : sur SIGTERM,
        ssh-agent supprime le **chemin** de son socket, qui peut être celui d'un autre agent."""
        for sig in ((signal.SIGKILL,) if hard else (signal.SIGTERM, signal.SIGKILL)):
            if not check(pid):
                return
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                return
            if _wait_gone(pid, STOP_WAIT):
                return
        raise AgentError("processus %d toujours vivant après SIGKILL" % pid)

    def _stop_watcher(self, rec) -> None:
        w = rec.get("watcher") if rec else None
        if isinstance(w, int):
            self._kill(w, lambda p: self.is_watcher(p, rec["pid"]))

    def _unlink_socket(self) -> None:
        try:
            if self._socket_stat() is not None:
                os.unlink(self.socket)
        except FileNotFoundError:
            pass
        except OSError as e:
            raise AgentError("suppression de %s : %s" % (self.socket, e.strerror or e)) from None

    def _clear_state(self) -> None:
        try:
            self.state.clear()
        except OSError as e:
            raise AgentError("suppression de l'état %s : %s" % (self.state.path, e.strerror or e)) from None

    def cleanup(self, data: dict) -> Optional[str]:
        """Socket absent ou mort : arrête l'agent enregistré s'il vit encore (pid vérifié) et son
        surveillant, retire le socket et l'état. Note si le pid enregistré n'est plus l'agent."""
        with self.locked(create=False):
            rec = data.get("agent")
            note = None
            if rec:
                if self.pid_is_agent(rec["pid"]):
                    self._kill(rec["pid"], self.pid_is_agent)
                elif _alive(rec["pid"]):
                    note = "pid %d n'est plus l'agent (réutilisé) : aucun signal" % rec["pid"]
                self._stop_watcher(rec)
            self._unlink_socket()
            self._clear_state()
            return note

    def _agent_env(self) -> dict:
        # Environnement de l'utilisateur gardé (SSH_ASKPASS, DISPLAY : confirmation `-c`
        # demandée par l'agent), sans référence à un autre agent.
        return {k: v for k, v in self.env.items() if k not in ("SSH_AUTH_SOCK", "SSH_AGENT_PID")}

    def _spawn_watcher(self, pid: int, st: os.stat_result) -> Optional[int]:
        env = self._agent_env()
        pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = pkg_parent + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        try:
            w = subprocess.Popen([sys.executable, "-m", WATCH_MODULE, str(pid), self.socket, str(st.st_dev),
                                  str(st.st_ino)], env=env, cwd="/", stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            raise AgentError("surveillant de l'agent : %s" % (e.strerror or e)) from None
        w.returncode = 0  # détaché : jamais attendu par ce processus (pas d'avertissement à la sortie)
        return w.pid

    def _start(self) -> dict:
        v = openssh_version(self.ssh_add)
        if v is None or v < MIN_OPENSSH:
            raise AgentError("OpenSSH %s : 8.9 ou plus requis (ssh-add -h/-H)"
                             % ("%d.%d" % v if v else "de version illisible (ssh -V)"))
        try:
            r = subprocess.run([self.ssh_agent, "-s", "-a", self.socket], env=self._agent_env(),
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=CMD_TIMEOUT,
                               start_new_session=True)
        except FileNotFoundError:
            raise AgentError("ssh-agent introuvable (%s) : installer openssh-client" % self.ssh_agent) from None
        except subprocess.TimeoutExpired:
            raise AgentError("ssh-agent sans réponse en %gs" % CMD_TIMEOUT) from None
        except OSError as e:
            raise AgentError("lancement de %s : %s" % (self.ssh_agent, e.strerror or e)) from None
        m = _PID_RE.search(r.stdout)
        if r.returncode != 0 or not m:
            raise AgentError("ssh-agent n'a pas démarré (code %d) : %s"
                             % (r.returncode, _one_line(r.stderr) or "pid absent de sa sortie"))
        pid = int(m.group(1))
        watcher = None
        try:
            st = self._socket_stat()
            if st is None or not self.pid_is_agent(pid):
                raise AgentError("ssh-agent (pid %d) lancé, mais socket ou processus introuvable "
                                 "(ligne de commande « ssh-agent … -a %s » attendue)" % (pid, self.socket))
            watcher = self._spawn_watcher(pid, st)
            data = empty()
            data["agent"] = {"pid": pid, "socket": self.socket, "dev": st.st_dev, "ino": st.st_ino,
                             "started": int(self.clock()), "watcher": watcher,
                             "askpass": askpass_rules(self._agent_env())[1]}
            self.save(data)
        except BaseException:
            # jamais d'agent sans état enregistré : le processus lancé (quel que soit son nom)
            # est arrêté s'il vise notre socket
            self._kill(pid, self.targets_socket)
            if watcher:
                self._kill(watcher, lambda p: self.is_watcher(p, pid))
            self._unlink_socket()
            raise
        return data

    def ensure_running(self):
        """Agent à sshvault vivant (lancé s'il le faut) : (état, lancé maintenant ?)."""
        with self.locked():
            kind, data = self.probe()
            if kind == "foreign":
                raise self.foreign()
            if kind == "ours":
                return data, False
            self.cleanup(data)
            return self._start(), True

    def stop(self) -> str:
        with self.locked(create=False):
            kind, data = self.probe()
            if kind == "foreign":
                raise self.foreign()
            if kind == "ours":
                rec = data["agent"]
                self._kill(rec["pid"], self.pid_is_agent)
                self._stop_watcher(rec)
                self._unlink_socket()
                self._clear_state()
                return "agent arrêté (pid %d), socket et état supprimés" % rec["pid"]
            note = self.cleanup(data)
            what = "agent déjà arrêté" if kind == "absent" else "agent mort : socket supprimé"
            return "%s%s" % (what, " ; " + note if note else "")

    # --- ssh-add ----------------------------------------------------------------------

    def prompt_plan(self, stdin_tty: bool = False):
        """(tty, askpass) : comment `ssh-add` demandera une saisie, selon readpass.c 8.9.
        stdin terminal (lock/unlock) : le terminal ; sinon askpass s'il est permis et
        utilisable, sinon /dev/tty s'il existe."""
        allow, usable = askpass_rules(self.env)
        if stdin_tty and (self.env.get("SSH_ASKPASS_REQUIRE") or "").lower() != "force":
            return True, False
        if allow and usable:
            return False, True
        return tty_available(), False

    def _add_env(self, interactive: bool) -> dict:
        env = self._agent_env()
        env["SSH_AUTH_SOCK"] = self.socket
        allow, usable = askpass_rules(self.env)
        if not interactive or (allow and not usable):
            # aucune invite (hors interactif) ; askpass permis mais absent : le terminal
            env["SSH_ASKPASS_REQUIRE"] = "never"
        return env

    def _ssh_add(self, args: Sequence[str], input: Optional[bytes] = None, interactive: bool = False,
                 tty: bool = False, timeout: float = CMD_TIMEOUT) -> subprocess.CompletedProcess:
        """`ssh-add` sur le socket dédié. Saisie sur le terminal (`tty`) : même session et
        même groupe (lecture de /dev/tty au premier plan), seul ssh-add est tué au délai ou à
        l'interruption. Sinon : session à part, tout le groupe (askpass compris) est tué."""
        argv = [self.ssh_add, *args]
        try:
            p = subprocess.Popen(argv, env=self._add_env(interactive),
                                 stdin=subprocess.PIPE if input is not None else (None if tty
                                                                                  else subprocess.DEVNULL),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=not tty)
        except FileNotFoundError:
            raise AgentError("ssh-add introuvable (%s) : installer openssh-client" % self.ssh_add) from None
        except OSError as e:
            raise AgentError("lancement de %s : %s" % (self.ssh_add, e.strerror or e)) from None
        done = False
        try:
            out, err = p.communicate(input=input, timeout=timeout)
            done = True
        except subprocess.TimeoutExpired:
            raise subprocess.TimeoutExpired(argv[:2], timeout) from None
        finally:
            if not done:
                try:
                    if tty:
                        p.kill()
                    else:
                        os.killpg(p.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    p.communicate(timeout=5)
                except Exception:
                    pass
        return subprocess.CompletedProcess(argv, p.returncode, out, err)

    def _ssh_add_simple(self, args: Sequence[str], what: str, input: Optional[bytes] = None):
        try:
            return self._ssh_add(args, input=input)
        except subprocess.TimeoutExpired:
            raise AgentError("ssh-add %s sans réponse en %gs" % (what, CMD_TIMEOUT)) from None

    def keys(self) -> list:
        """Clés de l'agent (`ssh-add -L`). Un agent verrouillé n'en montre aucune."""
        r = self._ssh_add_simple(["-L"], "-L")
        return [AgentKey(t, blob, comment, fingerprint(blob))
                for t, blob, comment in parse_listing(r.returncode, r.stdout, r.stderr)]

    def remove(self, key: AgentKey) -> None:
        """`ssh-add -d -`, clé **publique** sur stdin (mesuré : accepté par la 8.9)."""
        r = self._ssh_add_simple(["-d", "-"], "-d", input=("%s %s\n" % (key.type, key.blob)).encode())
        if r.returncode != 0:
            raise AgentError("ssh-add -d (code %d) : %s" % (r.returncode, _one_line(r.stderr)))

    def _dest_args(self, hosts: Sequence[str]) -> list:
        args = []
        if hosts:
            for kh in self.known_hosts:
                args += ["-H", kh]
            for h in hosts:
                # minuscules : ssh-add ne normalise pas la casse, et un known_hosts haché
                # (ssh-keygen -H) l'est sur le nom en minuscules (mesuré, 8.9p1)
                args += ["-h", h.lower()]
        return args

    def check_hosts(self, hosts: Sequence[str]) -> None:
        """Vérifie que chaque hôte de `-h` a une clé d'hôte dans known_hosts, par `ssh-add`
        lui-même, sans clé : il résout les contraintes avant de lire stdin (mesuré, 8.9p1),
        donc un hôte absent donne « No host keys found » (code 255), sinon la lecture d'une
        entrée vide échoue (code 1). Rien n'est ajouté à l'agent."""
        r = self._ssh_add_simple(self._dest_args(hosts) + ["-"], "-h", input=b"")
        err = r.stderr.decode(errors="replace")
        m = _NO_HOSTKEY_RE.search(err)
        if m:
            raise HostKeyMissing("hôte %s absent de known_hosts (restriction -h) : rien chargé" % _one_line(m.group(1)))
        if r.returncode != 1 or "Error loading key" not in err:
            raise AgentError("ssh-add -h (code %d) : %s" % (r.returncode, _one_line(err)))

    def add(self, key: bytes, lifetime: int, confirm: bool, hosts: Sequence[str], interactive: bool,
            encrypted: bool, timeout: float) -> None:
        """`ssh-add [-t N] [-c] [-H f] [-h hôte…] -`, clé par stdin. Interactif : `ssh-add`
        demande la passphrase (tty ou askpass) ; écho du terminal coupé dès qu'un tty existe."""
        args = (["-t", str(lifetime)] if lifetime else []) + (["-c"] if confirm else [])
        args += self._dest_args(hosts) + ["-"]
        tty, _ = self.prompt_plan() if interactive else (False, False)
        guard = NoEcho(newline=encrypted) if interactive and tty_available() else contextlib.nullcontext()
        try:
            with guard:
                r = self._ssh_add(args, input=key, interactive=interactive, tty=tty, timeout=timeout)
        except subprocess.TimeoutExpired:
            if encrypted:
                raise PassphraseRefused("aucune passphrase acceptée en %gs : clé non chargée" % timeout) from None
            raise AgentError("ssh-add sans réponse en %gs : clé non chargée" % timeout) from None
        if r.returncode == 0:
            return
        err = r.stderr.decode(errors="replace")
        m = _NO_HOSTKEY_RE.search(err)
        if m:
            raise HostKeyMissing("hôte %s absent de known_hosts (restriction -h) : clé non chargée" % _one_line(m.group(1)))
        if "agent refused operation" in err and self.state.load().get("locked"):
            raise AgentLocked("agent verrouillé : lancer « sshvault agent unlock »")
        if encrypted and "Could not add identity" not in err and "Error connecting" not in err:
            raise PassphraseRefused("passphrase de la clé refusée, annulée ou impossible à saisir : clé non chargée")
        raise AgentError("ssh-add (code %d) : %s" % (r.returncode, _one_line(err)))

    def purge(self) -> None:
        r = self._ssh_add_simple(["-D"], "-D")
        if r.returncode != 0:
            err = _one_line(r.stderr) or _one_line(r.stdout)
            if self.state.load().get("locked"):
                raise AgentLocked("agent verrouillé : lancer « sshvault agent unlock » (%s)" % err)
            raise AgentError("ssh-add -D (code %d) : %s" % (r.returncode, err))

    def set_locked(self, lock: bool, timeout: float) -> None:
        """`ssh-add -x` / `-X` : saisie du mot de passe par ssh-add (tty ou askpass). Ici
        ssh-add coupe l'écho lui-même, stdin terminal ou non (mesuré, 8.9p1)."""
        flag = "-x" if lock else "-X"
        try:
            stdin_tty = os.isatty(0)
        except OSError:
            stdin_tty = False
        tty, _ = self.prompt_plan(stdin_tty)
        try:
            r = self._ssh_add([flag], interactive=True, tty=tty, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AgentLocked("ssh-add %s : aucune saisie en %gs" % (flag, timeout)) from None
        if r.returncode != 0:
            raise AgentLocked("ssh-add %s : %s" % (flag, _one_line(r.stderr) or "code %d" % r.returncode))

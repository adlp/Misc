"""Chemin rapide de `sshvault ensure --id ID` (appelé par ssh à chaque connexion, `Match exec`).

Importé avant tout le reste par le point d'entrée (`launch`), avec la seule bibliothèque
standard de base : `ssh -G` / `ssh -O` (aucune connexion) et « clé déjà présente » répondent
sans charger la CLI, bw ni l'invite. Tout autre cas (clé absente, presque expirée, changée
dans le coffre, agent arrêté, erreur) passe la main à la CLI complète (`ensure.py`), qui
refait ces contrôles.

- ssh appelant : premier processus `ssh` parmi les ancêtres (bash exécute la commande de
  `-c` à sa place, dash ou zsh gardent le shell intermédiaire), lu dans /proc ; ses
  arguments sont relus comme le fait le getopt d'ssh pour y trouver `-G`, `-O`, la
  destination (messages) et `-o BatchMode=yes`. Le `ssh` le plus haut de la chaîne (le
  ssh tapé, au-dessus des ssh de ProxyJump/ProxyCommand) identifie la connexion (pid et
  date de démarrage).
- Clé présente : une empreinte enregistrée pour l'élément dans `agent.json`, valable encore
  plus de min(FRESH_MIN, durée/2) s, listée par `ssh-add -L` sur le socket dédié, et égale à
  celle du `.pub` de l'élément dans le ssh_config généré (clé changée dans le coffre :
  rechargée). Ni bw, ni réseau, ni écriture.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from typing import Mapping, Optional, Sequence

from .agentstate import STATE_NAME, AgentState, remaining
from .fsutil import read_private
from .runtime import SOCKET_NAME, AgentError, fingerprint, parse_listing, public_blob, resolve_dir
from .settings import seconds

#: Début du processus (délai global d'ensure : le chemin rapide en fait partie).
STARTED = time.monotonic()
#: Durée restante (s) en dessous de laquelle une clé présente est rechargée (au plus la moitié
#: de sa durée de vie).
FRESH_MIN = 60
#: Délai global d'un `ensure` (s), chemin rapide et attente du verrou compris.
DEFAULT_TIMEOUT = 240.0
TIMEOUT_VAR = "SSHVAULT_ENSURE_TIMEOUT"
#: Délai de `ssh-add -L` dans le chemin rapide (s), borné aussi par le délai global.
LIST_TIMEOUT = 10.0
#: Options d'ssh qui prennent un argument (getopt de ssh.c 8.9, plus -P des versions récentes).
SSH_ARG_OPTS = "bceilmopBDEFIJLOPQRSwW"
#: Id d'élément : UUID (seule partie variable de la commande de `Match exec`).
ITEM_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.ASCII | re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_BATCH_RE = re.compile(r"\s*batchmode\s*(=\s*|\s+)\"?(yes|true)\"?\s*$", re.IGNORECASE)


def clean(text: str) -> str:
    return _CONTROL.sub(lambda m: "\\x%02x" % ord(m.group()), text)


# --- ssh appelant ------------------------------------------------------------------------

def _proc_argv(pid: int) -> Optional[list]:
    try:
        if os.stat("/proc/%d" % pid).st_uid != os.getuid():
            return None
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    return [a.decode(errors="replace") for a in raw.split(b"\0")[:-1]] if raw else None


def _stat(pid: int) -> Optional[list]:
    """Champs de /proc/<pid>/stat après le nom (état, ppid, …)."""
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None


def ssh_ancestors(start: Optional[int] = None) -> list:
    """[(pid, argv)] des processus `ssh` de l'utilisateur parmi les ancêtres, du plus proche au
    plus haut (on remonte jusqu'à init ou un processus d'un autre utilisateur)."""
    out = []
    pid = os.getppid() if start is None else start
    seen = set()
    while pid and pid > 1 and pid not in seen:
        seen.add(pid)
        argv = _proc_argv(pid)
        if argv is None:
            break
        if os.path.basename(argv[0]) == "ssh":
            out.append((pid, argv))
        st = _stat(pid)
        try:
            pid = int(st[1]) if st else 0
        except ValueError:
            pid = 0
    return out


def ssh_parent(start: Optional[int] = None) -> Optional[list]:
    """argv du ssh le plus proche parmi les ancêtres, ou None."""
    found = ssh_ancestors(start)
    return found[0][1] if found else None


def parse_ssh_args(args: Sequence[str]) -> dict:
    """Arguments d'ssh relus à la manière de son getopt : options groupées (`-vG`), argument
    collé ou suivant, options aussi après la destination (ssh relance getopt), `--` ; le 2e
    argument hors option commence la commande. {"G": -G, "O": -O (commande de contrôle),
    "batch": -o BatchMode=yes, "dest": destination}."""
    r = {"G": False, "O": False, "batch": False, "dest": None}
    i, n = 0, len(args)
    while i < n:
        a = args[i]
        if a == "--":
            if r["dest"] is None and i + 1 < n:
                r["dest"] = args[i + 1]
            break
        if a.startswith("-") and len(a) > 1:
            for j in range(1, len(a)):
                c = a[j]
                if c == "G":
                    r["G"] = True
                if c in SSH_ARG_OPTS:
                    if j == len(a) - 1:
                        i += 1  # argument dans le mot suivant
                        val = args[i] if i < n else ""
                    else:
                        val = a[j + 1:]
                    if c == "O":
                        r["O"] = True
                    elif c == "o" and _BATCH_RE.match(val):
                        r["batch"] = True
                    break
            i += 1
            continue
        if r["dest"] is not None:
            break  # commande distante
        r["dest"] = a
        i += 1
    return r


def dest_label(dest: Optional[str]) -> Optional[str]:
    """Hôte d'une destination ssh (`user@hôte`, `ssh://user@hôte:port`), pour les messages."""
    if not dest:
        return None
    d = dest
    if d.startswith("ssh://"):
        d = d[len("ssh://"):].split("/", 1)[0].rsplit("@", 1)[-1]
        if d.startswith("["):
            d = d[1:].split("]", 1)[0]
        else:
            d = d.split(":", 1)[0]
    else:
        d = d.rsplit("@", 1)[-1]
    d = clean(d)
    return (d if len(d) <= 100 else d[:99] + "…") or None


class Caller:
    """Ce qu'`ensure` sait du ssh qui l'a lancé."""

    def __init__(self, ancestors: list):
        first = parse_ssh_args(ancestors[0][1][1:]) if ancestors else parse_ssh_args([])
        #: ssh -G (lecture de config) ou -O (commande de contrôle) : aucune connexion
        self.no_connect = first["G"] or first["O"]
        self.host = dest_label(first["dest"])
        #: BatchMode=yes en argument d'un ssh de la chaîne : aucune invite
        self.batch = any(parse_ssh_args(argv[1:])["batch"] for _, argv in ancestors)
        #: connexion : pid et date de démarrage du ssh le plus haut (None hors ssh)
        self.conn = None
        if ancestors:
            pid = ancestors[-1][0]
            st = _stat(pid)
            if st and len(st) > 19:
                self.conn = "%d:%s" % (pid, st[19])


def caller() -> Caller:
    return Caller(ssh_ancestors())


# --- clé présente ------------------------------------------------------------------------

def fresh(e: dict, now: float) -> bool:
    """Durée restante au-dessus du seuil : min(FRESH_MIN, durée/2) ; illimitée : toujours."""
    left = remaining(e, now)
    return left is None or left > min(FRESH_MIN, e["lifetime"] / 2)


def owns(e: dict, item_id: str) -> bool:
    """Entrée de l'état enregistrée pour cet élément (ou pour un autre élément de même clé)."""
    return e["id"].lower() == item_id or item_id in [x.lower() for x in e.get("also") or [] if isinstance(x, str)]


def ssh_home(env: Mapping[str, str]) -> Optional[str]:
    home = env.get("SSHVAULT_SSH_HOME") or ""
    if not home:
        import pwd
        try:
            home = pwd.getpwuid(os.getuid()).pw_dir or ""
        except KeyError:
            return None
    return home if os.path.isabs(home) else None


def pub_fingerprint(item_id: str, env: Mapping[str, str]) -> Optional[str]:
    """Empreinte du `.pub` de l'élément dans le ssh_config généré (bloc `# <nom> <id>`), ou
    None si la config, le bloc ou le fichier manque."""
    home = ssh_home(env)
    if not home:
        return None
    raw = read_private(os.path.join(home, ".ssh", "sshvault", "config"))
    if raw is None:
        return None
    inside = False
    for line in raw.decode(errors="replace").splitlines():
        if line.startswith("# "):
            inside = line.rstrip().lower().endswith(" " + item_id)
        elif inside and line.strip().startswith("IdentityFile "):
            path = line.strip()[len("IdentityFile "):].strip().strip('"').replace("%%", "%")
            pub = read_private(path)
            blob = public_blob(pub.decode(errors="replace")) if pub else None
            return fingerprint(blob) if blob else None
    return None


def agent_fingerprints(directory: str, env: Mapping[str, str], timeout: float = LIST_TIMEOUT) -> Optional[set]:
    """Empreintes des clés de l'agent dédié (`ssh-add -L`, même environnement qu'`Agent`), ou
    None si l'agent ne répond pas."""
    e = {k: v for k, v in env.items() if k not in ("SSH_AUTH_SOCK", "SSH_AGENT_PID")}
    e["SSH_AUTH_SOCK"] = os.path.join(directory, SOCKET_NAME)
    e["SSH_ASKPASS_REQUIRE"] = "never"
    try:
        r = subprocess.run([env.get("SSHVAULT_SSH_ADD") or "ssh-add", "-L"], env=e, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=max(0.1, timeout), start_new_session=True)
        return {fingerprint(blob) for _, blob, _ in parse_listing(r.returncode, r.stdout, r.stderr)}
    except (OSError, subprocess.SubprocessError, AgentError, ValueError):
        return None


def present_fresh(directory: str, item_id: str, env: Mapping[str, str], timeout: float = LIST_TIMEOUT) -> bool:
    """Une clé enregistrée pour cet élément, encore valable, est listée par l'agent dédié et
    correspond au `.pub` de l'élément dans la config générée (verrouillé : non)."""
    data = AgentState(os.path.join(directory, STATE_NAME)).load()
    if data.get("locked"):
        return False
    now = time.time()
    want = {fp for fp, e in data["keys"].items() if owns(e, item_id) and fresh(e, now)}
    if not want:
        return False
    pub = pub_fingerprint(item_id, env)
    if pub is not None:
        want &= {pub}  # clé changée dans le coffre (et config régénérée) : l'ancienne ne compte plus
        if not want:
            return False
    got = agent_fingerprints(directory, env, timeout)
    return bool(got and want & got)


def ensure_timeout(env: Mapping[str, str]) -> float:
    """SSHVAULT_ENSURE_TIMEOUT validé (ValueError sinon)."""
    return seconds(env, TIMEOUT_VAR, DEFAULT_TIMEOUT)


def time_left(total: float) -> float:
    return total - (time.monotonic() - STARTED)


# --- entrée -----------------------------------------------------------------------------

class _Stop(BaseException):
    pass


def _stop(signum, frame):
    raise _Stop(signum)


def ensure_args(argv: Sequence[str]):
    """(id, --nointeraction) si `argv` est exactement `[--nointeraction] ensure --id ID`, sinon None."""
    argv = list(argv)
    noint = bool(argv) and argv[0] == "--nointeraction"
    if noint:
        argv = argv[1:]
    if len(argv) == 3 and argv[0] == "ensure" and argv[1] == "--id":
        return argv[2], noint
    if len(argv) == 2 and argv[0] == "ensure" and argv[1].startswith("--id="):
        return argv[1][len("--id="):], noint
    return None


def try_fast(argv: Sequence[str]) -> Optional[int]:
    """Code de sortie si `ensure` n'a rien à faire (`ssh -G`, `ssh -O`, clé présente), sinon
    None : la CLI complète prend la suite (elle refait ces contrôles et rend toute erreur, délai
    invalide compris, en une ligne)."""
    parsed = ensure_args(argv)
    if parsed is None:
        return None
    item_id = parsed[0].strip().lower()
    if not ITEM_ID_RE.fullmatch(item_id):
        return None
    label = item_id
    rc = None
    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, _stop)
        c = caller()
        label = c.host or item_id
        if c.no_connect:
            rc = 0
        else:
            try:
                total = ensure_timeout(os.environ)
            except ValueError:
                total = None
            if total is not None and time_left(total) > 0:
                try:
                    d = resolve_dir(os.environ)
                except AgentError:
                    d = None
                if d is not None and present_fresh(d, item_id, os.environ, min(LIST_TIMEOUT, time_left(total))):
                    rc = 0
    except (KeyboardInterrupt, _Stop):
        try:
            sys.stderr.write("sshvault: %s : interrompu\n" % label)
        except (OSError, ValueError):
            pass
        rc = 130
    except Exception:
        rc = None  # la CLI complète refait tout et rend l'erreur en une ligne
    finally:
        # jusqu'à ce que la CLI pose les siens : signal = fin du processus, sans traceback
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_DFL)
    return rc

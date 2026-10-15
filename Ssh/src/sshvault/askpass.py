"""`sshvault-askpass` : programme `SSH_ASKPASS` de l'utilisateur (CAP-11).

Mise en place dans le shell : `SSH_ASKPASS=<chemin de sshvault-askpass>` et
`SSH_ASKPASS_REQUIRE=force` (`prefer` n'appelle l'askpass qu'avec DISPLAY en 8.9, mesuré). ssh
appelle alors ce programme pour **toute** invite (mot de passe, keyboard-interactive, question
de clé d'hôte, passphrase…), texte de l'invite en `argv[1]` ; la réponse va sur stdout.

Mot de passe du coffre donné seulement si :
- le parent (ssh qui demande) a un enregistrement `pw/<pid>.json` (même pid **et** même date de
  début), posé par `sshvault ensure --password` (ligne `Match exec` du bloc à mot de passe) ;
- l'invite est exactement `<u>@<h>'s password: ` (password) ou `(<u>@<h>) Password: `
  (keyboard-interactive), mesurées sur OpenSSH 8.9 ; `<h>` (HostName ou HostKeyAlias) n'est pas
  comparé : l'hôte tapé est celui de l'enregistrement ;
- `<u>` est l'utilisateur attendu d'un hôte enregistré (plusieurs éléments : le premier, par
  nom, compte puis id) ;
- ce mot de passe n'a pas encore été donné à ce ssh (une fois par connexion et par saut).
Il est lu par `bw get item` à ce moment (session rangée, jamais d'invite du mot de passe
maître), gardé en mémoire, écrit seulement sur stdout ; jamais en argument, fichier, état ou
message.

Toute autre invite est relayée : `/dev/tty` ouvrable → invite au terminal (écho coupé, sauf
question de clé d'hôte) ; sinon le réglage `askpass-fallback` (même argv, même environnement ;
jamais cet askpass) ; sinon code 1. `SSH_ASKPASS_PROMPT=confirm` (confirmation `-c` d'un
agent) : relais seul. Mot de passe déjà donné et redemandé : une ligne « refusé », puis relais.

Module léger : bibliothèque standard ; `bw` (et la CLI du coffre) importé seulement quand
l'enregistrement du parent et la forme de l'invite correspondent.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import signal
import sys
import termios
from typing import Mapping, Optional

from .fsutil import ensure_dir, read_private, write_private
from .prompt import askpass_fallback, own_askpass
from .runtime import ALIAS_RE, AgentError, resolve_dir
from .text import clean

#: Sous-dossier des enregistrements de `ensure --password` : `<pid du ssh>.json`.
PW_DIR = "pw"
_RECORD_RE = re.compile(r"(\d{1,10})\.json")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.ASCII)
#: Formes d'invite de mot de passe (OpenSSH 8.9, mesurées) ; l'utilisateur est vérifié à part.
_PASSWORD_FORMS = re.compile(r"[^\n\r]+@[^\s@]+'s password: |\([^\n\r]+@[^\s@()]+\) Password: ")
_HOST_PART = re.compile(r"[^\s@]+")
_KI_HOST_PART = re.compile(r"[^\s@()]+")
#: Question de clé d'hôte (réponse affichée au terminal).
_HOSTKEY_MARKS = ("(yes/no", "Please type 'yes', 'no'")


class _Signal(BaseException):
    pass


def _raise(signum, frame):
    raise _Signal(signum)


# --- enregistrements pw/ ----------------------------------------------------------------------

def proc_start(pid: int) -> Optional[str]:
    """Date de début (champ 22 de /proc/<pid>/stat) d'un processus de l'utilisateur, ou None."""
    try:
        if os.stat("/proc/%d" % pid).st_uid != os.getuid():
            return None
        with open("/proc/%d/stat" % pid) as f:
            fields = f.read().rsplit(")", 1)[1].split()
    except (OSError, IndexError, ValueError):
        return None
    if len(fields) < 20 or fields[0] == "Z":
        return None
    return fields[19]


def records_dir(directory: str) -> str:
    return os.path.join(directory, PW_DIR)


@contextlib.contextmanager
def _locked(d: str):
    """`flock` exclusif sur le dossier `pw/` (aucun fichier créé)."""
    fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _valid(rec, pid: int) -> bool:
    if not isinstance(rec, dict) or rec.get("pid") != pid or not isinstance(rec.get("start"), str):
        return False
    for key in ("entries", "given"):
        if not isinstance(rec.get(key), list) or not all(isinstance(e, dict) for e in rec[key]):
            return False
    return True


def _read(path: str, pid: int) -> Optional[dict]:
    raw = read_private(path)
    if raw is None:
        return None
    try:
        rec = json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError):
        return None
    return rec if _valid(rec, pid) else None


def _write(path: str, rec: dict) -> None:
    write_private(path, (json.dumps(rec, sort_keys=True) + "\n").encode())


def prune(d: str, keep: Optional[int] = None) -> list:
    """Retire les enregistrements dont le ssh n'existe plus (pid absent ou date de début
    différente) ; à appeler sous `_locked`. Renvoie les pids retirés."""
    gone = []
    try:
        names = os.listdir(d)
    except OSError:
        return gone
    for name in names:
        m = _RECORD_RE.fullmatch(name)
        if not m or int(m.group(1)) == keep:
            continue
        pid = int(m.group(1))
        rec = _read(os.path.join(d, name), pid)
        if rec is None or proc_start(pid) != rec["start"]:
            try:
                os.unlink(os.path.join(d, name))
                gone.append(pid)
            except OSError:
                pass
    return gone


def register(directory: str, pid: int, start: str, account: str, item_id: str, host: str) -> str:
    """Enregistre (compte, élément, hôte) pour le ssh `pid` (date de début `start`) : fichier
    `pw/<pid>.json` 0600 dans un dossier 0700, aucun secret. Un enregistrement d'un autre
    processus de même pid est remplacé ; les enregistrements morts sont retirés. Renvoie le
    chemin."""
    d = ensure_dir(records_dir(directory))
    path = os.path.join(d, "%d.json" % pid)
    with _locked(d):
        rec = _read(path, pid)
        if rec is None or rec["start"] != start:
            rec = {"pid": pid, "start": start, "entries": [], "given": []}
        entry = {"account": account, "id": item_id, "host": host}
        if entry not in rec["entries"]:
            rec["entries"].append(entry)
            _write(path, rec)
        prune(d, keep=pid)
    return path


def load(directory: str, pid: int) -> Optional[dict]:
    """Enregistrement du ssh `pid` s'il est encore ce processus (date de début), sinon None."""
    start = proc_start(pid)
    if start is None:
        return None
    rec = _read(os.path.join(records_dir(directory), "%d.json" % pid), pid)
    if rec is None or rec["start"] != start:
        return None
    return rec


def mark_given(directory: str, pid: int, start: str, given: dict) -> bool:
    """Note (sous verrou) qu'un mot de passe a été donné à ce ssh. False : déjà noté, ou
    enregistrement disparu ou remplacé, ou écriture impossible (rien ne sera donné)."""
    d = records_dir(directory)
    path = os.path.join(d, "%d.json" % pid)
    try:
        with _locked(d):
            rec = _read(path, pid)
            if rec is None or rec["start"] != start:
                return False
            if any((g.get("account"), g.get("id")) == (given["account"], given["id"]) for g in rec["given"]):
                return False
            rec["given"].append(given)
            _write(path, rec)
    except OSError:
        return False
    return True


# --- invite ----------------------------------------------------------------------------------

def password_form(text: str) -> bool:
    """L'une des deux formes d'invite de mot de passe d'OpenSSH 8.9 (utilisateur quelconque)."""
    return bool(_PASSWORD_FORMS.fullmatch(text or ""))


def prompt_matches(text: str, user: Optional[str]) -> bool:
    """`text` est exactement `<user>@<h>'s password: ` ou `(<user>@<h>) Password: `."""
    if not user or not text or "\n" in text or "\r" in text:
        return False
    head, tail = user + "@", "'s password: "
    if text.startswith(head) and text.endswith(tail):
        return bool(_HOST_PART.fullmatch(text[len(head):-len(tail)]))
    head, tail = "(" + user + "@", ") Password: "
    if text.startswith(head) and text.endswith(tail):
        return bool(_KI_HOST_PART.fullmatch(text[len(head):-len(tail)]))
    return False


def prompt_target(text: str) -> str:
    """`<u>@<h>` d'une invite de mot de passe (l'une des deux formes), pour un message."""
    if text.endswith("'s password: "):
        return text[:-len("'s password: ")]
    if text.startswith("(") and text.endswith(") Password: "):
        return text[1:-len(") Password: ")]
    return text


def _say(text: str) -> None:
    try:
        sys.stderr.write("sshvault: %s\n" % clean(text))
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def _entries(rec: dict) -> list:
    out = []
    for e in rec["entries"]:
        a, i, h = e.get("account"), e.get("id"), e.get("host")
        if isinstance(a, str) and ALIAS_RE.fullmatch(a) and isinstance(i, str) and _UUID_RE.fullmatch(i) \
                and isinstance(h, str) and h:
            if (a, i, h) not in out:
                out.append((a, i, h))
    return out


def _read_vault(entries: list, env: Mapping[str, str]) -> list:
    """[(compte, id, hôte, LoginItem, mot de passe)] des éléments lisibles sans invite ; une
    ligne par compte illisible (verrouillé, non connecté, bw en erreur). Seul endroit qui
    importe bw."""
    from .accounts import Accounts
    from .backend import ItemNotFound, NotLoggedIn, VaultError, VaultLocked
    from .config import Config, ConfigError
    from .session import SessionStoreError

    cfg = Config()
    accts = Accounts(cfg, cfg.bw_path, _say)
    out, failed = [], set()
    try:
        for a, i, h in entries:
            if a in failed:
                continue
            try:
                b = accts.backend(a)
                item, pw = b.get_login(i, None)
            except ItemNotFound:
                _say("élément %s du compte %s : identifiant absent du coffre (« sshvault ssh-config »)" % (i, a))
                continue
            except (NotLoggedIn, VaultLocked):
                failed.add(a)
                _say("coffre « %s » verrouillé : mot de passe du coffre non donné (« sshvault unlock%s »)"
                     % (a, " --account %s" % a if accts.multi else ""))
                continue
            except (VaultError, SessionStoreError, ConfigError, Exception) as e:  # noqa: B014
                failed.add(a)
                _say("coffre « %s » illisible (%s) : mot de passe du coffre non donné" % (a, e))
                continue
            out.append((a, i, h, item, pw))
    finally:
        for a, b in accts.backends():
            for w in b.warnings:
                _say("%s : %s" % (a, w))
    return out


def answer(text: str, env: Optional[Mapping[str, str]] = None, ppid: Optional[int] = None) -> Optional[bytes]:
    """Mot de passe à donner pour cette invite (octets), ou None : relais."""
    env = os.environ if env is None else env
    if (env.get("SSH_ASKPASS_PROMPT") or "").lower() in ("confirm", "none"):
        return None
    if not password_form(text):
        return None
    try:
        directory = resolve_dir(env)
    except AgentError:
        return None
    ppid = os.getppid() if ppid is None else ppid
    rec = load(directory, ppid)
    if rec is None:
        return None
    for g in rec["given"]:
        if prompt_matches(text, g.get("user")):
            _say("mot de passe du coffre refusé pour %s@%s (%s) : saisie relayée"
                 % (g.get("user"), g.get("host") or "?", g.get("name") or g.get("id")))
            return None
    entries = _entries(rec)
    if not entries:
        return None
    found = _read_vault(entries, env)
    try:
        cands, expected = [], []
        for a, i, h, item, pw in found:
            users = [u for host, u in item.hosts if host == h.lower() and u]
            if not users:
                expected.append("« %s » : aucun utilisateur pour %s (hôte retiré de ses URI ?)" % (item.name, h))
            expected += ["%s@%s" % (u, h) for u in users]
            for u in users:
                if prompt_matches(text, u):
                    cands.append(((item.name.casefold(), a, i), a, i, h, u, item.name, pw))
                    break
        if not cands:
            if found:
                _say("invite pour %s : aucun élément du coffre ne correspond (attendu : %s) : saisie relayée"
                     % (prompt_target(text), " ; ".join(expected)))
            return None
        cands.sort(key=lambda c: c[0])
        _, a, i, h, u, name, pw = cands[0]
        if not pw:
            _say("élément « %s » (%s) sans mot de passe : saisie relayée" % (name, a))
            return None
        if not mark_given(directory, ppid, rec["start"], {"account": a, "id": i, "user": u, "host": h, "name": name}):
            _say("mot de passe du coffre refusé pour %s@%s (%s) : saisie relayée" % (u, h, name))
            return None
        return pw
    finally:
        found.clear()


# --- relais ----------------------------------------------------------------------------------

def host_key_question(text: str) -> bool:
    return any(m in (text or "") for m in _HOSTKEY_MARKS)


def _tty_read(fd: int, text: str, echo: bool) -> Optional[bytes]:
    """Invite au terminal (écho coupé sauf `echo`), une ligne lue ; None : fin de fichier.
    Attributs du terminal rétablis sur tous les chemins."""
    old = termios.tcgetattr(fd)
    new = list(old)
    if not echo:
        new[3] &= ~(termios.ECHO | termios.ECHONL)
    new[3] |= termios.ICANON
    data = b""
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, new)
        os.write(fd, text.encode(errors="replace"))
        while not data.endswith(b"\n"):
            chunk = os.read(fd, 1024)
            if not chunk:
                break
            data += chunk
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSANOW, old)
            if not echo:
                os.write(fd, b"\n")
        except (OSError, termios.error):
            pass
    if not data:
        return None
    return data.rstrip(b"\r\n")


def relay(argv: list, env: Optional[Mapping[str, str]] = None) -> int:
    """Invite relayée : terminal, sinon `askpass-fallback`, sinon code 1."""
    env = os.environ if env is None else env
    text = argv[0] if argv else ""
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        fd = None
    if fd is not None:
        try:
            line = _tty_read(fd, text, host_key_question(text))
        except (OSError, termios.error):
            line = None
        finally:
            os.close(fd)
        if line is None:
            return 1
        try:
            _write_all(line + b"\n")
        except OSError:
            return 1
        return 0
    fallback = askpass_fallback(env)
    if fallback and not own_askpass(fallback, env) and os.path.isfile(fallback) and os.access(fallback, os.X_OK):
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
        try:
            os.execve(fallback, [fallback] + list(argv), dict(env))
        except OSError as e:
            _say("askpass-fallback %s : %s" % (fallback, e.strerror or e))
    return 1


def _write_all(data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(1, view)
        view = view[n:]


def main(argv: Optional[list] = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _raise)
    try:
        text = argv[0] if argv else ""
        try:
            pw = answer(text)
        except (_Signal, KeyboardInterrupt):
            raise
        except Exception as e:  # jamais de traceback ; le message ne porte jamais le mot de passe
            _say("erreur interne : %s : saisie relayée" % type(e).__name__)
            pw = None
        if pw is not None:
            try:
                _write_all(pw + b"\n")
            except OSError:
                return 1
            finally:
                del pw
            return 0
        return relay(argv)
    except (_Signal, KeyboardInterrupt):
        return 1


if __name__ == "__main__":
    sys.exit(main())

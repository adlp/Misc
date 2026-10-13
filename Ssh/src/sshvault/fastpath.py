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
- Élément désigné par (compte, id) (CAP-10) : `ensure --account <alias> --id <uuid>`, et
  `ensure --forward <fid> --id <alias>:<uuid>…`. Ancienne forme (`ensure --id <uuid>`,
  `--forward <fid> --id <uuid>…`, config générée par la 0.8.0) acceptée : clé reconnue par son
  id seul, compte cherché par la CLI complète.
- `ensure --forward <fid> --id ID…` (sous-agent de transfert, CAP-8) : toutes les clés des
  éléments fraîches dans le sous-agent `fwd/<fid>.sock`, et aucune autre clé ; agent dédié
  non verrouillé (état lu seulement, jamais contacté). ssh appelant en `-W` (saut ProxyJump
  ou ProxyCommand `ssh -W`) ou `-N` : aucun canal de session, rien n'est transféré, aucune clé
  chargée ; mais `-W` impose `ExitOnForwardFailure` (mesuré, 8.9p1 : socket absent → le saut
  s'arrête aussitôt, même avec `-a`) : le socket du sous-agent doit exister (sous-agent vide
  lancé par la CLI s'il manque). ssh appelant avec `-a` ou `-o ForwardAgent=no` (sans -W/-N) :
  rien n'est transféré, code 0 sans rien faire.
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
from .runtime import (ALIAS_RE, FID_RE, SOCKET_NAME, AgentError, fingerprint, forward_paths, parse_listing, public_blob,
                      resolve_dir)
from .settings import is_logged_out, seconds

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
_FORWARD_RE = re.compile(r"\s*forwardagent\s*(?:=\s*|\s+)\"?([^\"]*?)\"?\s*$", re.IGNORECASE)


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
    r = {"G": False, "O": False, "W": False, "N": False, "batch": False, "dest": None, "agent": None}
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
                elif c == "N":
                    r["N"] = True
                elif c in "aA":
                    # -a / -A : affectation directe (getopt de ssh.c), la dernière gagne
                    r["agent"] = c == "A"
                if c in SSH_ARG_OPTS:
                    if j == len(a) - 1:
                        i += 1  # argument dans le mot suivant
                        val = args[i] if i < n else ""
                    else:
                        val = a[j + 1:]
                    if c == "O":
                        r["O"] = True
                    elif c == "W":
                        r["W"] = True
                    elif c == "o" and _BATCH_RE.match(val):
                        r["batch"] = True
                    elif c == "o" and _FORWARD_RE.match(val) and r["agent"] is None:
                        # -o ForwardAgent : première valeur seulement (process_config_line)
                        r["agent"] = _FORWARD_RE.match(val).group(1).lower() not in ("no", "false")
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
        #: ssh -W (saut ProxyJump/ProxyCommand) ou -N : aucun canal de session, rien n'est transféré
        self.no_session = first["W"] or first["N"]
        #: ssh -a ou -o ForwardAgent=no : aucun agent transféré, quelle que soit la config
        self.no_forward = first["agent"] is False
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


def parse_ref(ref: str):
    """`<alias>:<uuid>` → (alias, uuid en minuscules) ; `<uuid>` (ancienne forme) → (None, uuid) ;
    sinon None."""
    ref = (ref or "").strip()
    alias, sep, iid = ref.rpartition(":")
    if sep and not ALIAS_RE.fullmatch(alias):
        return None
    if not ITEM_ID_RE.fullmatch(iid):
        return None
    return (alias or None), iid.lower()


def _pair(x):
    """(compte ou None, id) d'un id donné seul, en couple, ou `<alias>:<id>`."""
    if isinstance(x, tuple):
        return x[0], x[1].lower()
    a, _, i = x.rpartition(":")
    return (a or None), i.lower()


def owns(e: dict, item_id: str, account: Optional[str] = None) -> bool:
    """Entrée de l'état enregistrée pour cet élément (ou pour un autre élément de même clé).
    Compte comparé seulement s'il est connu des deux côtés (entrées d'avant CAP-10, ancienne
    forme d'`ensure` : par id)."""
    item_id = item_id.lower()

    def same(acc, iid):
        return iid.lower() == item_id and (account is None or not acc or acc == account)
    if same(e.get("account"), e["id"]):
        return True
    for x in e.get("also") or []:
        if isinstance(x, str):
            a, i = _pair(x)
            if same(a, i):
                return True
    return False


def ssh_home(env: Mapping[str, str]) -> Optional[str]:
    home = env.get("SSHVAULT_SSH_HOME") or ""
    if not home:
        import pwd
        try:
            home = pwd.getpwuid(os.getuid()).pw_dir or ""
        except KeyError:
            return None
    return home if os.path.isabs(home) else None


_EXEC_ACCOUNT_RE = re.compile(r" ensure --account (\S+) --id ")


def pub_fingerprint(item_id: str, env: Mapping[str, str], account: Optional[str] = None) -> Optional[str]:
    """Empreinte du `.pub` de l'élément (compte, id) dans le ssh_config généré, ou None si la
    config, le bloc ou le fichier manque. Bloc : commentaire `# <nom> <alias> <id>` (l'id en fin
    de ligne) ; le compte est celui de la ligne `ensure --account <alias>` du bloc, sinon le
    dernier mot du commentaire ; un bloc d'ancienne forme (`# <nom> <id>`, `ensure --id`, sans
    compte) vaut pour tout compte. `account` None : par id seul."""
    home = ssh_home(env)
    if not home:
        return None
    raw = read_private(os.path.join(home, ".ssh", "sshvault", "config"))
    if raw is None:
        return None
    inside, word, exec_seen = False, None, False
    for line in raw.decode(errors="replace").splitlines():
        if line.startswith("# "):
            body = line.rstrip()
            inside = body.lower().endswith(" " + item_id)
            parts = body.split(" ")
            word = parts[-2] if len(parts) >= 4 else None
            exec_seen = False
        elif inside and line.startswith("Match ") and ' exec "' in line:
            exec_seen = True
            m = _EXEC_ACCOUNT_RE.search(line)
            # ligne exec d'ancienne forme (sans --account) : bloc sans compte, vaut pour tout compte
            if account is not None and m is not None and m.group(1) != account:
                inside = False
        elif inside and line.strip().startswith("IdentityFile "):
            if account is not None and not exec_seen and word is not None and ALIAS_RE.fullmatch(word) \
                    and word != account:
                # sans ligne exec (auto-load false) : le commentaire nomme un autre compte
                inside = False
                continue
            path = line.strip()[len("IdentityFile "):].strip().strip('"').replace("%%", "%")
            pub = read_private(path)
            blob = public_blob(pub.decode(errors="replace")) if pub else None
            return fingerprint(blob) if blob else None
    return None


def agent_fingerprints(directory: str, env: Mapping[str, str], timeout: float = LIST_TIMEOUT,
                       socket: Optional[str] = None) -> Optional[set]:
    """Empreintes des clés de l'agent dédié (ou du socket `socket`) par `ssh-add -L`, même
    environnement qu'`Agent`, ou None si l'agent ne répond pas."""
    e = {k: v for k, v in env.items() if k not in ("SSH_AUTH_SOCK", "SSH_AGENT_PID")}
    e["SSH_AUTH_SOCK"] = socket or os.path.join(directory, SOCKET_NAME)
    e["SSH_ASKPASS_REQUIRE"] = "never"
    try:
        r = subprocess.run([env.get("SSHVAULT_SSH_ADD") or "ssh-add", "-L"], env=e, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=max(0.1, timeout), start_new_session=True)
        return {fingerprint(blob) for _, blob, _ in parse_listing(r.returncode, r.stdout, r.stderr)}
    except (OSError, subprocess.SubprocessError, AgentError, ValueError):
        return None


def present_fresh(directory: str, item_id: str, env: Mapping[str, str], timeout: float = LIST_TIMEOUT,
                  account: Optional[str] = None) -> bool:
    """Une clé enregistrée pour cet élément, encore valable, est listée par l'agent dédié et
    correspond au `.pub` de l'élément dans la config générée (verrouillé : non)."""
    data = AgentState(os.path.join(directory, STATE_NAME)).load()
    if data.get("locked"):
        return False
    now = time.time()
    want = {fp for fp, e in data["keys"].items() if owns(e, item_id, account) and fresh(e, now)}
    if not want:
        return False
    pub = pub_fingerprint(item_id, env, account)
    if pub is not None:
        want &= {pub}  # clé changée dans le coffre (et config régénérée) : l'ancienne ne compte plus
        if not want:
            return False
    got = agent_fingerprints(directory, env, timeout)
    return bool(got and want & got)


def main_locked(directory: str) -> bool:
    """L'état de l'agent dédié le dit verrouillé (`sshvault agent lock`) **et** le pid enregistré
    est encore cet ssh-agent (`ssh-agent … -a <socket>` de l'utilisateur, lu dans /proc) : un
    verrou laissé par un agent mort ne bloque rien. L'agent n'est jamais contacté."""
    data = AgentState(os.path.join(directory, STATE_NAME)).load()
    rec = data.get("agent")
    if not data.get("locked") or not rec:
        return False
    sock = os.path.join(directory, SOCKET_NAME)
    st = _stat(rec["pid"])
    argv = _proc_argv(rec["pid"])
    return bool(st and st[0] != "Z" and argv and os.path.basename(argv[0]) == "ssh-agent"
                and any(a == "-a" and argv[i + 1:i + 2] == [sock] for i, a in enumerate(argv)))


def forward_wanted(data: dict, ids: Sequence[str], env: Mapping[str, str], now: float):
    """(empreintes autorisées, empreintes voulues ou None) d'un sous-agent d'après son état :
    autorisées = enregistrées pour l'un des éléments (et égales au `.pub` de sa config générée
    s'il en a un) ; voulues = les autorisées encore fraîches. None : un élément sans clé fraîche."""
    allowed, want, missing = set(), set(), False
    for x in ids:
        a, i = _pair(x)
        mine = {fp for fp, e in data["keys"].items() if owns(e, i, a)}
        pub = pub_fingerprint(i, env, a)
        if pub is not None:
            mine &= {pub}  # clé changée dans le coffre (config régénérée) : l'ancienne n'est plus autorisée
        allowed |= mine
        cand = {fp for fp in mine if fresh(data["keys"][fp], now)}
        if not cand:
            missing = True
        want |= cand
    return allowed, (None if missing else want)


def forward_fresh(directory: str, fid: str, ids: Sequence[str], env: Mapping[str, str],
                  timeout: float = LIST_TIMEOUT) -> bool:
    """Sous-agent `fid` : toutes les clés des éléments `ids` fraîches et listées, aucune autre
    clé ; agent dédié pas verrouillé. Ni bw, ni réseau, ni écriture."""
    if main_locked(directory):
        return False
    _, sock, state = forward_paths(directory, fid)
    data = AgentState(state).load()
    allowed, want = forward_wanted(data, ids, env, time.time())
    if not want:
        return False
    got = agent_fingerprints(directory, env, timeout, socket=sock)
    return bool(got) and want <= got and got <= allowed


def ensure_timeout(env: Mapping[str, str]) -> float:
    """SSHVAULT_ENSURE_TIMEOUT validé (ValueError sinon)."""
    return seconds(env, TIMEOUT_VAR, DEFAULT_TIMEOUT)


def logged_out(account: Optional[str], env: Optional[Mapping[str, str]] = None) -> bool:
    """Compte déconnecté par `sshvault logout` (marqueur, fichier ordinaire seulement)."""
    return is_logged_out(account, env)


def _agent_maybe_locked(directory: str, env: Mapping[str, str], timeout: float) -> bool:
    """Compte déconnecté seulement : agent dédié verrouillé, ou peut-être (il ne liste aucune
    clé, quel que soit son état ; un `ssh-add -L`) : la CLI tranche, par la sonde `ssh-add -D`
    sous `ensure.lock` (jamais ici, hors verrou : elle pourrait vider une clé qu'un `ensure`
    parallèle vient de charger). Agent jamais lancé (pas de socket) : il ne peut être
    verrouillé, False."""
    data = AgentState(os.path.join(directory, STATE_NAME)).load()
    if data.get("locked"):
        return True
    if not os.path.exists(os.path.join(directory, SOCKET_NAME)):
        return False
    return not agent_fingerprints(directory, env, timeout)


def logged_out_message(account: str) -> str:
    return "compte « %s » déconnecté (sshvault logout) : lancer « sshvault login --account %s »" % (account, account)


def time_left(total: float) -> float:
    return total - (time.monotonic() - STARTED)


# --- entrée -----------------------------------------------------------------------------

class _Stop(BaseException):
    pass


def _stop(signum, frame):
    raise _Stop(signum)


def ensure_args(argv: Sequence[str]):
    """(ids, fid ou None, --nointeraction, compte ou None) si `argv` est `[--nointeraction] ensure`
    suivi de `[--account ALIAS] --id ID` (une fois chacun), ou de `--forward FID` et d'au moins un
    `--id ID` (formes `--opt=v` acceptées) ; sinon None (la CLI complète tranche)."""
    argv = list(argv)
    noint = bool(argv) and argv[0] == "--nointeraction"
    if noint:
        argv = argv[1:]
    if not argv or argv[0] != "ensure":
        return None
    ids, fids, accts, i = [], [], [], 1
    while i < len(argv):
        a = argv[i]
        for opt, dest in (("--id", ids), ("--forward", fids), ("--account", accts)):
            if a == opt and i + 1 < len(argv):
                dest.append(argv[i + 1])
                i += 2
                break
            if a.startswith(opt + "="):
                dest.append(a[len(opt) + 1:])
                i += 1
                break
        else:
            return None
    if len(fids) > 1 or len(accts) > 1 or not ids or (not fids and len(ids) != 1) or (fids and accts):
        return None
    return ids, (fids[0] if fids else None), noint, (accts[0] if accts else None)


def try_fast(argv: Sequence[str]) -> Optional[int]:
    """Code de sortie si `ensure` n'a rien à faire (`ssh -G`, `ssh -O`, clé présente), sinon
    None : la CLI complète prend la suite (elle refait ces contrôles et rend toute erreur, délai
    invalide compris, en une ligne)."""
    parsed = ensure_args(argv)
    if parsed is None:
        return None
    fid, account = parsed[1], parsed[3]
    refs = [parse_ref(i) for i in parsed[0]]
    if any(r is None for r in refs) or (fid is not None and not FID_RE.fullmatch(fid)):
        return None
    if account is not None and (not ALIAS_RE.fullmatch(account) or refs[0][0] is not None):
        return None
    ids = [(a, i) for a, i in refs]
    item_id = ids[0][1]
    if fid is None and account is None:
        account = refs[0][0]  # `ensure --id <alias>:<uuid>` : le compte de la référence
    label = item_id
    rc = None
    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, _stop)
        c = caller()
        label = c.host or item_id
        if c.no_connect:
            rc = 0
        elif fid is not None and c.no_session:
            if os.path.exists(forward_paths(resolve_dir(os.environ), fid)[1]):
                rc = 0  # saut -W, -N : socket présent, rien à transférer
        elif fid is not None and c.no_forward:
            rc = 0  # ssh -a, -o ForwardAgent=no : rien à transférer
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
                left = min(LIST_TIMEOUT, time_left(total))
                if d is not None and (forward_fresh(d, fid, ids, os.environ, left) if fid is not None
                                      else present_fresh(d, item_id, os.environ, left, account)):
                    rc = 0
                elif (fid is None and d is not None and logged_out(account)
                      and not _agent_maybe_locked(d, os.environ, left)):
                    # clé absente, compte déconnecté par `sshvault logout`, agent dédié connu et non
                    # verrouillé (il liste une clé, ou n'a pas de socket) : la ligne qui propose
                    # `login`, sans charger la CLI (même texte que `ensure._unlock_possible`) ;
                    # sinon la CLI tranche (sonde « agent verrouillé » avant « déconnecté »)
                    sys.stderr.write("sshvault: %s : %s\n" % (clean(label), logged_out_message(account)))
                    rc = 3
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

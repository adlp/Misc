"""Briques légères de l'agent dédié, partagées par `agent` et par le chemin rapide d'`ensure`
(`fastpath`) : chemin du socket, empreinte, lecture de `ssh-add -L`. Rien d'autre que la
bibliothèque standard de base : un `ensure` qui n'a rien à faire doit démarrer vite."""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Mapping, Optional

from .fsutil import NotPrivateTmpfs, check_private_tmpfs

DIR_NAME = "sshvault"
SOCKET_NAME = "agent.sock"
RUN_USER = "/run/user"
SUN_PATH_MAX = 107  # sun_path : 108 octets, NUL final compris


class AgentError(Exception):
    """Erreur de l'agent dédié (code 4), message d'une ligne."""


# --- socket -------------------------------------------------------------------------

def resolve_dir(env: Optional[Mapping[str, str]] = None, uid: Optional[int] = None,
                run_user: str = RUN_USER, mounts: str = "/proc/self/mounts") -> str:
    """Dossier `<base>/sshvault` du socket et de l'état ; base : XDG_RUNTIME_DIR, ou
    `/run/user/<uid>` si la variable est absente ; tmpfs privé exigé (sinon AgentError).
    Chemin canonique (realpath) : une même base écrite autrement donne le même socket."""
    env = os.environ if env is None else env
    uid = os.getuid() if uid is None else uid
    rt = env.get("XDG_RUNTIME_DIR") or ""
    if rt:
        if not os.path.isabs(rt):
            raise AgentError("XDG_RUNTIME_DIR n'est pas un chemin absolu (%r) : agent dédié refusé" % rt)
        try:
            check_private_tmpfs(rt, mounts)
        except NotPrivateTmpfs as e:
            raise AgentError("XDG_RUNTIME_DIR refusé pour l'agent dédié : %s" % e) from None
        base = rt
    else:
        base = os.path.join(run_user, str(uid))
        try:
            check_private_tmpfs(base, mounts)
        except NotPrivateTmpfs as e:
            raise AgentError("XDG_RUNTIME_DIR absent, repli refusé : %s ; agent dédié impossible" % e) from None
    d = os.path.join(os.path.realpath(base), DIR_NAME)
    if len(os.fsencode(os.path.join(d, SOCKET_NAME))) > SUN_PATH_MAX:
        raise AgentError("chemin du socket trop long (%d octets au plus) : %s"
                         % (SUN_PATH_MAX, os.path.join(d, SOCKET_NAME)))
    return d


# --- clés -------------------------------------------------------------------------------

def fingerprint(blob_b64: str) -> str:
    """Empreinte SHA256 au format d'OpenSSH (`SHA256:` + base64 sans `=`)."""
    raw = base64.b64decode(blob_b64, validate=True)
    return "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")


def public_blob(public_key: str) -> Optional[str]:
    """`type base64 [commentaire]` → base64 de la clé, ou None si illisible."""
    parts = (public_key or "").split()
    if len(parts) < 2:
        return None
    try:
        base64.b64decode(parts[1], validate=True)
    except (ValueError, TypeError):
        return None
    return parts[1]


def parse_listing(rc: int, out: bytes, err: bytes) -> list:
    """Sortie de `ssh-add -L` → [(type, blob base64, commentaire)] ; agent sans clé → [] ;
    autre échec → AgentError. Un agent verrouillé ne montre aucune clé."""
    text = out.decode(errors="replace")
    if rc == 1 and "has no identities" in text + err.decode(errors="replace"):
        return []
    if rc != 0:
        msg = " ".join(l.strip() for l in (err.decode(errors="replace") or text).splitlines() if l.strip())
        raise AgentError("ssh-add -L (code %d) : %s" % (rc, msg[:300]))
    keys = []
    for line in text.splitlines():
        blob = public_blob(line)
        if blob is None:
            continue
        parts = line.split(None, 2)
        keys.append((parts[0], blob, parts[2] if len(parts) > 2 else ""))
    return keys

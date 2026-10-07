"""Magasin de la session du coffre, gardée hors de tout disque persistant.

1. Keyring noyau (`keyctl`, anneau `@u` par défaut) : clé `user` nommée
   `sshvault:session`, jeton passé par stdin (jamais en argument), expiration
   posée par le noyau (`keyctl timeout`).
2. Si `keyctl` échoue (absent, session keyring non liée à `@u` ou révoquée…) :
   fichier 0600 `$XDG_RUNTIME_DIR/sshvault/session` (dossier 0700), qui porte sa
   date d'expiration ; il est expiré à la lecture et purgé au `lock`. XDG_RUNTIME_DIR
   doit être à l'utilisateur, sans droits groupe/autres, sur tmpfs ou ramfs.

Rien n'est écrit sur un stockage persistant. Sans keyring utilisable ni
`XDG_RUNTIME_DIR`, la session n'est pas rangée (`SessionStoreError`).
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Callable, Optional

from .fsutil import NotPrivateTmpfs, check_private_tmpfs, read_private, write_private

KEY_DESC = "sshvault:session"
DEFAULT_TTL = 900
KEYCTL_TIMEOUT = 10
_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_.:-]{8,4096}")


class SessionStoreError(Exception):
    pass


def valid_token(token: Optional[str]) -> bool:
    return bool(token) and bool(_TOKEN_RE.fullmatch(token))


def check_private_runtime(rt: str, mounts: str = "/proc/self/mounts") -> None:
    """Le repli fichier exige un XDG_RUNTIME_DIR à l'utilisateur, sans droits groupe/autres,
    sur tmpfs ou ramfs (jamais un disque persistant)."""
    try:
        check_private_tmpfs(rt, mounts)
    except NotPrivateTmpfs as e:
        if e.reason is not None:
            raise SessionStoreError("XDG_RUNTIME_DIR inutilisable : %s" % e.reason) from None
        raise SessionStoreError("XDG_RUNTIME_DIR n'est pas un tmpfs privé (%s) : session non rangée" % rt) from None


class SessionStore:
    def __init__(self, keyring: Optional[str] = None, keyctl: Optional[str] = None,
                 runtime_dir: Optional[str] = None, clock: Callable[[], float] = time.time,
                 mounts: str = "/proc/self/mounts"):
        env = os.environ
        # Anneau et exécutable injectables (tests : anneau dédié, jamais le @u réel).
        self.keyring = keyring or env.get("SSHVAULT_KEYRING") or "@u"
        self.keyctl = keyctl or env.get("SSHVAULT_KEYCTL") or "keyctl"
        rt = runtime_dir if runtime_dir is not None else env.get("XDG_RUNTIME_DIR", "")
        self.file = os.path.join(rt, "sshvault", "session") if rt and os.path.isabs(rt) else None
        self.clock = clock
        self.mounts = mounts
        self.last_backend: Optional[str] = None  # "keyring" | "file" : où get() a trouvé la session

    # --- keyring -------------------------------------------------------------

    def _keyctl(self, *args: str, data: Optional[str] = None):
        try:
            r = subprocess.run([self.keyctl, *args], input=data, capture_output=True, text=True,
                               timeout=KEYCTL_TIMEOUT, stdin=None if data is not None else subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            return None, str(e)
        if r.returncode != 0:
            return None, (r.stderr or r.stdout).strip() or "code %d" % r.returncode
        return r.stdout, None

    def _key_id(self) -> Optional[str]:
        out, _ = self._keyctl("search", self.keyring, "user", KEY_DESC)
        return out.strip() if out else None

    def _keyring_put(self, token: str, ttl: int) -> Optional[str]:
        """Renvoie None si la session est rangée avec son délai, sinon la raison de l'échec."""
        out, err = self._keyctl("padd", "user", KEY_DESC, self.keyring, data=token)
        if out is None:
            return "keyctl padd : " + err
        kid = out.strip()
        _, err = self._keyctl("timeout", kid, str(ttl))
        if err is not None:
            # Sans délai, la session resterait indéfiniment dans l'anneau : on la retire.
            self._keyctl("unlink", kid, self.keyring)
            return "keyctl timeout : " + err
        return None

    def _keyring_get(self) -> Optional[str]:
        kid = self._key_id()
        if not kid:
            return None
        out, _ = self._keyctl("pipe", kid)
        return out if out and valid_token(out) else None

    def _keyring_clear(self) -> None:
        for _ in range(8):
            kid = self._key_id()
            if not kid:
                return
            _, err = self._keyctl("unlink", kid, self.keyring)
            if err is not None:
                raise SessionStoreError("impossible de retirer la session du keyring : " + err)
        raise SessionStoreError("session toujours présente dans le keyring après purge")

    # --- fichier tmpfs ------------------------------------------------------

    def _file_get(self) -> Optional[str]:
        if not self.file:
            return None
        raw = read_private(self.file)
        if raw is None:
            return None
        try:
            token, exp = raw.decode().split()
            expired = float(exp) <= self.clock()
        except (ValueError, UnicodeDecodeError):
            token, expired = None, True
        if expired or not valid_token(token):
            try:
                self._file_clear()
            except SessionStoreError:
                pass  # périmé de toute façon : ignoré, retenté au prochain lock
            return None
        return token

    def _file_put(self, token: str, ttl: int) -> None:
        if not self.file:
            raise SessionStoreError("XDG_RUNTIME_DIR absent : impossible de ranger la session hors disque")
        check_private_runtime(os.path.dirname(os.path.dirname(self.file)), self.mounts)
        write_private(self.file, ("%s %d\n" % (token, int(self.clock()) + ttl)).encode())

    def _file_clear(self) -> None:
        if not self.file:
            return
        try:
            os.unlink(self.file)
        except FileNotFoundError:
            pass
        except OSError as e:
            raise SessionStoreError("impossible de supprimer %s : %s" % (self.file, e.strerror or e)) from None

    # --- API ------------------------------------------------------------------

    def get(self) -> Optional[str]:
        token = self._keyring_get()
        if token:
            self.last_backend = "keyring"
            return token
        token = self._file_get()
        self.last_backend = "file" if token else None
        return token

    def put(self, token: str, ttl: int = DEFAULT_TTL) -> str:
        """Range la session ; renvoie "keyring" ou "file". Lève SessionStoreError si rien ne marche."""
        if not valid_token(token):
            raise SessionStoreError("jeton de session invalide")
        if not isinstance(ttl, int) or ttl < 1:
            raise SessionStoreError("durée de vie invalide : %r" % (ttl,))
        why = self._keyring_put(token, ttl)
        if why is None:
            self.last_backend = "keyring"
            try:
                self._file_clear()  # pas de doublon périmé
            except SessionStoreError:
                pass
            return "keyring"
        try:
            self._file_put(token, ttl)
        except (OSError, SessionStoreError) as e:
            raise SessionStoreError("%s ; repli fichier impossible : %s" % (why, e)) from None
        self.last_backend = "file"
        return "file"

    def clear(self) -> None:
        """Vide le keyring et le fichier. Lève SessionStoreError si la session reste quelque part."""
        self.last_backend = None
        first = None
        for step in (self._file_clear, self._keyring_clear):
            try:
                step()
            except SessionStoreError as e:
                first = first or e
        if first is not None:
            raise first

    def describe(self) -> str:
        return "keyring %s (repli : %s)" % (self.keyring, self.file or "aucun, XDG_RUNTIME_DIR absent")

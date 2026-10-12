"""Réglages lus dans l'environnement."""
from __future__ import annotations

import os
import stat
import time
from typing import Mapping, Optional

from .fsutil import write_private

MAX_SECONDS = 86400.0


def seconds(env: Mapping[str, str], name: str, default: float) -> float:
    """Durée en secondes dans `env[name]` : 0 < v <= 86400, sinon ValueError (message d'une ligne)."""
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = float(raw)
    except ValueError:
        v = float("nan")
    if not 0 < v <= MAX_SECONDS:
        raise ValueError("%s invalide : %r (secondes, entre 0 exclu et %d)" % (name, raw, MAX_SECONDS))
    return v


def data_root(env: Optional[Mapping[str, str]] = None) -> str:
    """`${XDG_DATA_HOME:-~/.local/share}/sshvault`."""
    env = os.environ if env is None else env
    base = env.get("XDG_DATA_HOME") or ""
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "sshvault")


def account_dir(alias: str, env: Optional[Mapping[str, str]] = None) -> str:
    """Données locales d'un compte : `<data_root>/accounts/<alias>` (données de bw dans `bw/`)."""
    return os.path.join(data_root(env), "accounts", alias)


#: Marqueur posé par `sshvault logout` (et `account set` qui déconnecte), à côté des données de
#: bw : persistant, suit `account rename` (dossier déplacé), disparaît avec `account remove`.
LOGGED_OUT_NAME = "logged-out"


def logged_out_path(alias: str, env: Optional[Mapping[str, str]] = None) -> str:
    """Seul chemin du marqueur `logged-out` d'un compte (écrit par la CLI, lu par `ensure` et
    par le chemin rapide)."""
    return os.path.join(account_dir(alias, env), LOGGED_OUT_NAME)


def is_logged_out(alias: Optional[str], env: Optional[Mapping[str, str]] = None) -> bool:
    """Marqueur présent : seul un fichier ordinaire compte (un dossier ou un lien à sa place ne
    vaut pas marqueur). Lecture commune à la CLI, à `ensure` et au chemin rapide."""
    if not alias:
        return False
    try:
        return stat.S_ISREG(os.lstat(logged_out_path(alias, env)).st_mode)
    except OSError:
        return False


def clear_logged_out(alias: str, env: Optional[Mapping[str, str]] = None) -> None:
    """Retire le marqueur s'il est là (fichier ordinaire seulement) ; OSError si impossible."""
    if is_logged_out(alias, env):
        try:
            os.unlink(logged_out_path(alias, env))
        except FileNotFoundError:
            pass


def set_logged_out(alias: str, env: Optional[Mapping[str, str]] = None) -> bool:
    """Pose le marqueur, seulement si le dossier du compte existe (jamais créé ici) : True si
    posé, False sans dossier ; OSError si l'écriture échoue (chemin occupé, droits)."""
    path = logged_out_path(alias, env)
    if not os.path.isdir(os.path.dirname(path)):
        return False
    write_private(path, ("%d\n" % int(time.time())).encode())
    return True

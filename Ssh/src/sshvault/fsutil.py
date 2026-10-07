"""Écritures locales : chaque dossier créé en 0700, chaque fichier en 0600.

Aussi : vérification qu'un dossier est un tmpfs privé (session du coffre, socket et état
de l'agent dédié), d'après `/proc/self/mounts`."""
from __future__ import annotations

import os
import re
import stat
from typing import Optional

PRIVATE_FS = ("tmpfs", "ramfs")


class NotPrivateTmpfs(Exception):
    """Dossier absent, à un autre utilisateur, ouvert au groupe ou aux autres, ou hors tmpfs/ramfs.
    `reason` : strerror si le dossier est inaccessible, sinon None."""

    def __init__(self, msg: str, reason: Optional[str] = None):
        super().__init__(msg)
        self.reason = reason


def _unescape_mount(path: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), path)


def fs_type(path: str, mounts: str = "/proc/self/mounts") -> Optional[str]:
    """Type du système de fichiers qui porte `path` (point de montage le plus long)."""
    path = os.path.realpath(path)
    best, kind = "", None
    try:
        with open(mounts) as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mp = _unescape_mount(parts[1])
                if (path == mp or path.startswith(mp.rstrip("/") + "/")) and len(mp) >= len(best):
                    best, kind = mp, parts[2]
    except OSError:
        return None
    return kind


def check_private_tmpfs(path: str, mounts: str = "/proc/self/mounts") -> None:
    """`path` doit appartenir à l'utilisateur, sans droits groupe/autres, sur tmpfs ou ramfs
    (jamais un disque persistant) ; sinon NotPrivateTmpfs (message d'une ligne)."""
    try:
        st = os.stat(path)
    except OSError as e:
        raise NotPrivateTmpfs("%s inutilisable : %s" % (path, e.strerror or e), str(e.strerror or e)) from None
    if st.st_uid != os.getuid() or st.st_mode & 0o077 or fs_type(path, mounts) not in PRIVATE_FS:
        raise NotPrivateTmpfs("%s n'est pas un tmpfs privé" % path)


def ensure_dir(path: str) -> str:
    """Crée `path` et ses parents manquants, chacun en 0700 (indépendamment de l'umask).

    Un dossier déjà existant n'est pas modifié, sauf le dernier : s'il appartient à
    l'utilisateur, il est ramené à 0700. Un composant qui existe sans être un dossier
    lève NotADirectoryError (rien n'est modifié)."""
    path = os.path.abspath(path)
    missing = []
    p = path
    while not os.path.isdir(p):
        if os.path.lexists(p):
            raise NotADirectoryError("%s existe et n'est pas un dossier" % p)
        missing.append(p)
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    for d in reversed(missing):
        try:
            os.mkdir(d, 0o700)
        except FileExistsError:
            if not os.path.isdir(d):
                raise NotADirectoryError("%s existe et n'est pas un dossier" % d) from None
            continue  # créé entre-temps par un autre : pas à nous de le modifier
        os.chmod(d, 0o700)
    st = os.stat(path)
    if st.st_uid == os.getuid() and st.st_mode & 0o777 != 0o700:
        os.chmod(path, 0o700)
    return path


def write_private(path: str, data: bytes) -> None:
    """Écrit `data` dans `path` (0600) par fichier temporaire + rename ; le temporaire est
    supprimé sur tout échec ou interruption avant le rename."""
    d = ensure_dir(os.path.dirname(path))
    tmp = os.path.join(d, ".%s.%d.tmp" % (os.path.basename(path), os.getpid()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_private(path: str):
    """Contenu de `path` s'il est un fichier ordinaire à nous en 0600 (sans lien), sinon None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            return None
        chunks = []
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            chunks.append(b)
        return b"".join(chunks)
    finally:
        os.close(fd)

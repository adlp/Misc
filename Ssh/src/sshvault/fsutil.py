"""Écritures locales : chaque dossier créé en 0700, chaque fichier en 0600."""
from __future__ import annotations

import os
import stat


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

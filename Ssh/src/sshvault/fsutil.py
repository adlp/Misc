"""Écritures locales : chaque dossier créé en 0700, chaque fichier en 0600.

Aussi : vérification qu'un dossier est un tmpfs privé (session du coffre, socket et état
de l'agent dédié), d'après `/proc/self/mounts`."""
from __future__ import annotations

import os
import re
import shlex
import stat
from typing import Optional

from .text import clean

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
    """Contenu de `path` s'il est un fichier ordinaire à nous en 0600 (sans lien), sinon None.
    O_NONBLOCK : une FIFO à ce chemin ne bloque pas l'ouverture (rejetée par fstat)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
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


def exe_problem(path: str) -> Optional[str]:
    """Raison (une ligne, sans le chemin) pour laquelle `path` ne peut pas servir d'exécutable,
    ou None : lien symbolique suivi, la cible doit exister, être un fichier ordinaire et être
    exécutable par l'utilisateur. Propriété et droits d'écriture : `exe_exposure`."""
    try:
        st = os.stat(path)
    except OSError as e:
        return str(e.strerror or e)
    if not stat.S_ISREG(st.st_mode):
        return "pas un fichier ordinaire"
    if not os.access(path, os.X_OK):
        return "non exécutable par l'utilisateur"
    return None


def _ancestors(d: str) -> list:
    """`d` puis chacun de ses parents jusqu'à `/` (chemin normalisé, liens non résolus)."""
    out = []
    d = os.path.normpath(d)
    while True:
        out.append(d)
        up = os.path.dirname(d)
        if up == d:
            return out
        d = up


def _link_chain(path: str) -> tuple:
    """(cible finale, dossiers à contrôler) : `path` puis chaque lien symbolique suivi (lstat,
    lien relatif résolu depuis son propre dossier) ; dossiers = dossier de chaque maillon et
    ses parents jusqu'à `/`, sous leur forme écrite et résolue (sans doublon, dans l'ordre)."""
    dirs = []

    def add(d):
        for a in _ancestors(d) + _ancestors(os.path.realpath(d)):
            if a not in dirs:
                dirs.append(a)
    p = os.path.abspath(path)
    for _ in range(40):  # au-delà : boucle de liens, que exe_problem refuse
        add(os.path.dirname(p))
        try:
            if not stat.S_ISLNK(os.lstat(p).st_mode):
                break
            p = os.path.normpath(os.path.join(os.path.dirname(p), os.readlink(p)))
        except OSError:
            break
    return p, dirs


def exe_exposure(path: str) -> Optional[tuple]:
    """(raisons, à chmod, à déplacer) si d'autres que l'utilisateur et root peuvent remplacer
    l'exécutable `path`, sinon None. Contrôlés, comme le StrictModes d'OpenSSH (safe_path) :
    la cible finale, le dossier de chaque maillon de liens symboliques et tous leurs parents
    jusqu'à `/`. Chacun doit être à l'utilisateur ou à root et non modifiable par le groupe ni
    les autres (pas d'exception pour le sticky bit : n'importe qui peut y créer un fichier).
    À chmod (`g-w,o-w`) : ce qui est à l'utilisateur, ouvert en écriture, sans sticky bit ;
    sinon (sticky, autre propriétaire, dossier système) : déplacer bw."""
    target, dirs = _link_chain(path)
    uid = os.getuid()
    reasons, to_chmod, move = [], [], False
    for what, p in [("fichier", target)] + [("dossier", d) for d in dirs]:
        try:
            st = os.stat(p)
        except OSError:
            continue  # disparu entre-temps : exe_problem le dira au lancement
        if st.st_uid not in (uid, 0):
            reasons.append("%s %s à un autre utilisateur (uid %d)" % (what, p, st.st_uid))
            move = True
        if st.st_mode & 0o022:
            reasons.append("%s %s modifiable par le groupe ou les autres" % (what, p))
            if st.st_uid == uid and not st.st_mode & stat.S_ISVTX:
                to_chmod.append(p)
            else:
                move = True
    return (reasons, to_chmod, move) if reasons else None


def exposure_warning(path: str, key: str = "bw-path") -> Optional[str]:
    """Avertissement d'une ligne si d'autres que l'utilisateur et root peuvent remplacer
    l'exécutable `path` (`exe_exposure`), sinon None. N'empêche rien : choix de l'utilisateur
    (dossier partagé avec son groupe). Jamais de chmod proposé sur ce qui n'est pas à lui ni
    sur un dossier à sticky bit (/tmp)."""
    found = exe_exposure(path)
    if found is None:
        return None
    reasons, to_chmod, move = found
    fixes = []
    if to_chmod:
        fixes.append("corriger par « chmod g-w,o-w %s »" % " ".join(shlex.quote(clean(p)) for p in to_chmod))
    if move:
        fixes.append("déplacer bw dans un dossier à vous non modifiable par d'autres")
    return ("avertissement : %s « %s » exposé à d'autres (%s) : ils pourraient remplacer bw et recevoir le "
            "mot de passe maître ; %s" % (key, clean(path), " ; ".join(clean(r) for r in reasons), " et ".join(fixes)))

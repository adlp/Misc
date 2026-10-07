"""`ssh_config` inclus (CAP-5) : `~/.ssh/sshvault/config` et `~/.ssh/sshvault/pub/*.pub`,
puis, sur demande seulement, la ligne `Include` en tête de `~/.ssh/config`.

- Un bloc par élément associé, triés par nom d'élément puis par id, ouvert par
  `Match originalhost <motif>,<motif>` : comparé au nom **tapé** (pas au HostName), sans
  tenir compte de la casse (mesuré sur OpenSSH 8.9p1 : `Host foo` ne s'applique pas à
  `ssh FOO`). Directives : `IdentityAgent` (socket dédié résolu, sans `${XDG_RUNTIME_DIR}`),
  `IdentityFile` (clé publique), `IdentitiesOnly yes`. Jamais `HostName`, `User`, `Port`,
  `ProxyJump` ni `ProxyCommand`.
- Chargement automatique (réglage `auto-load`, défaut oui) : avant chaque bloc, une ligne
  `Match originalhost <motifs> exec "'<sshvault>' ensure --id <id>"` sans directive (ssh
  n'exécute la commande que si `originalhost` correspond). La commande, passée au shell de
  l'utilisateur, ne contient que des éléments contrôlés : chemin absolu de sshvault entre
  apostrophes (refusé s'il contient `'`, `"`, `\\`, `${` ou un caractère de contrôle ; `%`
  doublé) et id de l'élément, un UUID validé (sinon pas de ligne, avertissement). Jamais
  `%h` ni `%n` : un motif `*.lab` y ferait passer un nom tapé par l'utilisateur.
- Chemins absolus, entre guillemets, `%` échappé en `%%` (IdentityAgent et IdentityFile
  développent les tokens `%x` et `${VAR}` : un chemin avec `"`, `\\`, `${` ou un caractère de
  contrôle est refusé).
- Écriture atomique en 0600 dans un dossier 0700 ; rien n'est réécrit si le contenu est
  identique (mtime inchangée) ; `pub/` ne garde que les clés des éléments associés.
- Verrou `flock` sur `~/.ssh/sshvault/` autour de l'écriture et de la purge : deux
  régénérations simultanées ne se gênent pas.
- `Include` : seul `install` écrit `~/.ssh/config` (sauvegarde jamais écrasée, mode et
  propriétaire gardés, lien symbolique ou fichier non ordinaire refusé) ; ailleurs, on ne fait
  que lire, sans jamais bloquer sur une FIFO.
- `~` = répertoire de passwd (celui où ssh lit `~/.ssh/config`), pas `$HOME`.
"""
from __future__ import annotations

import contextlib
import fcntl
import fnmatch
import os
import pwd
import re
import shlex
import stat
import sys
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .agent import fingerprint, public_blob
from .backend import SshKeyItem, valid_host
from .fastpath import ITEM_ID_RE
from .fsutil import ensure_dir, read_private, write_private

HEADER = ("# Généré par sshvault, ne pas éditer : « sshvault ssh-config » le réécrit.\n"
          "# Chargé par la ligne Include en tête de ~/.ssh/config (« sshvault ssh-config install »).\n")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_KEY_TYPE = re.compile(r"[A-Za-z0-9@._-]+")
_KEYWORD = re.compile(r"([A-Za-z]+)(?:\s*=\s*|\s+|$)(.*)$", re.S)
_TMP = re.compile(r"\..+\.(\d+)\.tmp$")
_CATCH_ALL = re.compile(r"[*?.]+")
#: Avertissement des motifs sans partie littérale (décision de l'utilisateur, 2026-10-07).
CATCH_ALL_WARNING = "ce bloc prend toutes les connexions ssh et désactive ton agent habituel"
#: Répertoire personnel imposé (tests seulement) ; sinon celui de passwd.
HOME_ENV = "SSHVAULT_SSH_HOME"
EXE_NAME = "sshvault"


class SshConfigError(Exception):
    """Génération ou installation impossible (code 4), message d'une ligne."""


def clean(text: str) -> str:
    return _CONTROL.sub(lambda m: "\\x%02x" % ord(m.group()), text)


# --- chemins -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Paths:
    home: str

    @property
    def ssh_dir(self) -> str:
        return os.path.join(self.home, ".ssh")

    @property
    def dir(self) -> str:
        return os.path.join(self.ssh_dir, "sshvault")

    @property
    def config(self) -> str:
        return os.path.join(self.dir, "config")

    @property
    def pub(self) -> str:
        return os.path.join(self.dir, "pub")

    @property
    def user_config(self) -> str:
        return os.path.join(self.ssh_dir, "config")

    @property
    def backup(self) -> str:
        return os.path.join(self.ssh_dir, "config.sshvault.bak")


def default_paths(env=None) -> Paths:
    """Répertoire de passwd de l'utilisateur : ssh y lit `~/.ssh/config`, quel que soit $HOME."""
    env = os.environ if env is None else env
    home = env.get(HOME_ENV) or ""
    if not home:
        try:
            home = pwd.getpwuid(os.getuid()).pw_dir or ""
        except KeyError:
            home = ""
    if not os.path.isabs(home) or os.path.normpath(home) == "/":
        raise SshConfigError("répertoire personnel inconnu ou inutilisable (passwd : %r) : ~/.ssh refusé" % home)
    return Paths(os.path.normpath(home))


def is_catch_all(host: str) -> bool:
    """Motif sans partie littérale (`*`, `*.*`, `?*`…) : il prend toutes les connexions."""
    return bool(_CATCH_ALL.fullmatch(host))


def fp_filename(fp: str) -> str:
    """Nom du `.pub` : empreinte en base64url (`/`→`_`, `+`→`-`), qui peut sinon contenir `/`."""
    return fp.replace("/", "_").replace("+", "-") + ".pub"


def _check_path(path: str, what: str, forbidden: str = "") -> None:
    if not os.path.isabs(path) or '"' in path or "\\" in path or "${" in path or _CONTROL.search(path) \
            or any(c in path for c in forbidden):
        raise SshConfigError("%s inutilisable dans un ssh_config : %s (chemin absolu sans « \" », « \\ », "
                             "« ${ »%s ni caractère de contrôle)"
                             % (what, clean(path), "".join(", « %s »" % c for c in forbidden)))


def quote_path(path: str, what: str) -> str:
    """Chemin pour IdentityAgent/IdentityFile : guillemets, `%` → `%%`."""
    _check_path(path, what)
    return '"%s"' % path.replace("%", "%%")


#: Version minimale d'une commande sshvault pour les lignes `Match exec` (`ensure`).
ENSURE_MIN_VERSION = (0, 4, 0)
_VERSION_RE = re.compile(r"sshvault (\d+)\.(\d+)\.(\d+)")
_exe_checked: dict = {}


def exe_version(exe: str):
    """Version rendue par `<exe> --version` (tuple), ou None ; mise en cache pour le processus
    (une génération)."""
    if exe not in _exe_checked:
        import subprocess
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30,
                               stdin=subprocess.DEVNULL)
            m = _VERSION_RE.search(r.stdout) if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            m = None
        _exe_checked[exe] = tuple(int(x) for x in m.groups()) if m else None
    return _exe_checked[exe]


def sshvault_exe(argv0: Optional[str] = None, env=None) -> str:
    """Chemin absolu de la commande `sshvault` pour `Match exec` : celle qui tourne si elle a
    été lancée sous ce nom (console script installé), sinon les `sshvault` exécutables des
    dossiers **absolus** du PATH, dans l'ordre ; la première qui connaît `ensure`
    (`--version` ≥ 0.4.0) est retenue. Aucune : SshConfigError."""
    env = os.environ if env is None else env
    argv0 = sys.argv[0] if argv0 is None else argv0
    cands = []
    if os.path.basename(argv0 or "") == EXE_NAME:
        cands.append(os.path.abspath(argv0))
    cands += [os.path.join(d, EXE_NAME) for d in (env.get("PATH") or "").split(os.pathsep) if os.path.isabs(d)]
    old = []
    for c in cands:
        c = os.path.normpath(c)
        if not (os.path.isfile(c) and os.access(c, os.X_OK)):
            continue
        v = exe_version(c)
        if v is not None and v >= ENSURE_MIN_VERSION:
            return c
        old.append(c)
    raise SshConfigError("commande sshvault %s pour le chargement automatique%s : l'installer (uv tool install "
                         "--force), ou « sshvault config set auto-load false »"
                         % ("0.4.0 ou plus introuvable (PATH)" if not old else "trop ancienne",
                            " (%s)" % ", ".join(clean(o) for o in old) if old else ""))


def exe_warnings(exe: str, paths: "Paths") -> list:
    """Avertissements sur le chemin retenu : différent de celui de la config générée existante,
    ou dans un environnement de projet (`.venv`), dont la config dépendrait."""
    out = []
    raw = read_private(paths.config)
    m = re.search(r"exec \"'([^']*)' ensure --id ", raw.decode(errors="replace")) if raw else None
    if m and m.group(1).replace("%%", "%") != exe:
        out.append("chemin de sshvault des lignes Match exec changé : %s → %s"
                   % (clean(m.group(1).replace("%%", "%")), clean(exe)))
    if ".venv" in exe.split(os.sep):
        out.append("sshvault pris dans un environnement de projet (%s) : la config générée en dépendra ; "
                   "préférer la commande installée (uv tool install)" % clean(exe))
    return out


def ensure_command(exe: str, item_id: str) -> str:
    """Commande de `Match exec` : `'<exe>' ensure --id <uuid>` (`%` doublé pour ssh). Rien
    d'autre que le chemin vérifié et l'id validé : la commande passe par un shell."""
    _check_path(exe, "chemin de sshvault", "'")
    if not ITEM_ID_RE.fullmatch(item_id or ""):
        raise SshConfigError("id d'élément inattendu (UUID attendu) : %s" % clean(item_id))
    return "'%s' ensure --id %s" % (exe.replace("%", "%%"), item_id.lower())


def include_line(paths: Paths) -> str:
    """`Include "<config>"`. Include ne développe pas `%` en 8.9 (mesuré) mais le fait dans
    les versions récentes (man) : un chemin avec `%`, `$` ou un joker de glob est refusé."""
    _check_path(paths.config, "chemin du ssh_config généré", "%$*?[")
    return 'Include "%s"' % paths.config


# --- génération --------------------------------------------------------------------------

@dataclass
class Plan:
    config: bytes
    pubs: dict = field(default_factory=dict)  # nom de fichier -> contenu
    blocks: int = 0
    warnings: list = field(default_factory=list)


def _label(it: SshKeyItem) -> str:
    return "« %s » (%s)" % (clean(it.name), clean(it.id))


def build(items: Sequence[SshKeyItem], paths: Paths, socket: str, exe: Optional[str] = None) -> Plan:
    """Contenu du fichier généré et des `.pub`, sans rien écrire. Vérifie aussi les chemins
    (SshConfigError) : sert de contrôle préalable avant une écriture dans le coffre.
    `exe` : chemin de sshvault ; s'il est donné, chaque bloc est précédé de sa ligne
    `Match … exec` (chargement automatique)."""
    agent = quote_path(socket, "socket de l'agent dédié")
    _check_path(paths.pub, "dossier des clés publiques")
    if exe is not None:
        _check_path(exe, "chemin de sshvault", "'")
    plan = Plan(config=b"")
    out = [HEADER]
    entries = []  # (motif, élément), dans l'ordre des blocs
    for it in sorted(items, key=lambda i: (i.name.casefold(), i.id)):
        if not it.hosts:
            continue
        bad = [h for h in it.hosts if not valid_host(h)]
        if bad:
            plan.warnings.append("%s : hôte invalide « %s » : élément sauté" % (_label(it), clean(bad[0])))
            continue
        parts = (it.public_key or "").split()
        blob = public_blob(it.public_key)
        if blob is None or not _KEY_TYPE.fullmatch(parts[0]):
            plan.warnings.append("%s : clé publique illisible : élément sauté" % _label(it))
            continue
        name = fp_filename(fingerprint(blob))
        plan.pubs[name] = ("%s %s\n" % (parts[0], blob)).encode()
        hosts = []
        for h in it.hosts:
            h = h.strip().lower()
            if h not in hosts:
                hosts.append(h)
                entries.append((h, it))
                if is_catch_all(h):
                    plan.warnings.append("%s : motif « %s » : %s" % (_label(it), h, CATCH_ALL_WARNING))
        # hôtes validés (HOST_RE) : ni virgule ni espace, la liste à virgules est sûre
        out.append("\n# %s %s\n" % (clean(it.name), clean(it.id)))
        if exe is not None:
            if ITEM_ID_RE.fullmatch(it.id):
                out.append('Match originalhost %s exec "%s"\n' % (",".join(hosts), ensure_command(exe, it.id)))
            else:
                plan.warnings.append("%s : id inattendu (UUID attendu) : pas de chargement automatique pour "
                                     "cet élément" % _label(it))
        out.append("Match originalhost %s\n    IdentityAgent %s\n    IdentityFile %s\n"
                   "    IdentitiesOnly yes\n"
                   % (",".join(hosts), agent, quote_path(os.path.join(paths.pub, name), "clé publique")))
        plan.blocks += 1
    owners = {}
    for h, it in entries:
        owners.setdefault(h, []).append(it)
    for h, its in owners.items():
        if len(its) > 1:
            plan.warnings.append("hôte « %s » porté par %d éléments (%s) : ssh offrira leurs clés dans l'ordre "
                                 "des blocs" % (h, len(its), ", ".join(_label(i) for i in its)))
    for n, (h1, a) in enumerate(entries):
        for h2, b in entries[n + 1:]:
            if a is b or h1 == h2 or is_catch_all(h1) or is_catch_all(h2):
                continue
            if fnmatch.fnmatchcase(h1, h2) or fnmatch.fnmatchcase(h2, h1):
                plan.warnings.append("motifs « %s » de %s et « %s » de %s se recouvrent : pour les hôtes communs, "
                                     "ssh offrira les deux clés dans l'ordre des blocs" % (h1, _label(a), h2, _label(b)))
    plan.config = "".join(out).encode()
    return plan


@dataclass
class Applied:
    config_written: bool = False
    pubs_written: list = field(default_factory=list)
    pubs_removed: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@contextlib.contextmanager
def _locked(directory: str):
    """`flock` exclusif sur le dossier (aucun fichier créé), relâché à la fermeture."""
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _kind(path: str) -> str:
    """« absent », « file » (ordinaire), « link », « dir » ou « other » (FIFO, socket…)."""
    try:
        m = os.lstat(path).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return "absent"
    except OSError:
        return "unknown"  # dossier parent illisible
    return ("file" if stat.S_ISREG(m) else "link" if stat.S_ISLNK(m) else "dir" if stat.S_ISDIR(m)
            else "other")


def _live_tmp(name: str) -> bool:
    """Temporaire `.<nom>.<pid>.tmp` d'un autre processus encore vivant."""
    m = _TMP.match(name)
    if not m or int(m.group(1)) == os.getpid():
        return False
    try:
        os.kill(int(m.group(1)), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _dir_note(name: str) -> str:
    return "%s : dossier inattendu, laissé en place" % clean(name)


def _write_if_changed(path: str, data: bytes) -> bool:
    k = _kind(path)
    if k in ("dir", "other"):
        raise SshConfigError("%s n'est pas un fichier ordinaire : refusé" % clean(path))
    if k == "file" and read_private(path) == data:
        return False
    write_private(path, data)
    return True


def apply(plan: Plan, paths: Paths) -> Applied:
    """Écrit ce qui diffère, sous verrou : `.pub` d'abord, puis la config, puis purge de `pub/`."""
    res = Applied()
    try:
        ensure_dir(paths.dir)
        with _locked(paths.dir):
            ensure_dir(paths.pub)
            for name, data in sorted(plan.pubs.items()):
                if _write_if_changed(os.path.join(paths.pub, name), data):
                    res.pubs_written.append(name)
            res.config_written = _write_if_changed(paths.config, plan.config)
            for name in sorted(os.listdir(paths.pub)):
                if name in plan.pubs or _live_tmp(name):
                    continue
                p = os.path.join(paths.pub, name)
                if _kind(p) == "dir":
                    res.warnings.append(_dir_note(p))
                    continue
                os.unlink(p)
                res.pubs_removed.append(name)
    except OSError as e:  # NotADirectoryError d'ensure_dir compris
        where = " (%s)" % clean(str(e.filename)) if e.filename else ""
        raise SshConfigError("écriture du ssh_config généré : %s%s" % (clean(str(e.strerror or e)), where)) from None
    return res


def check(plan: Plan, paths: Paths):
    """(différences, avertissements) entre le plan et le disque ; rien n'est écrit. Mêmes
    règles qu'`apply` : un sous-dossier de `pub/` est signalé, pas compté comme différence."""
    diffs, warnings = [], []
    for d in (paths.dir, paths.pub):
        k = _kind(d)
        if k == "absent":
            continue
        if k != "dir":
            diffs.append("%s : pas un dossier" % d)
            continue
        m = stat.S_IMODE(os.lstat(d).st_mode)
        if m != 0o700:
            diffs.append("%s : droits %04o au lieu de 0700" % (d, m))
    for path, data, absent in [(paths.config, plan.config, "absent")] + [
            (os.path.join(paths.pub, n), b, "absente") for n, b in sorted(plan.pubs.items())]:
        k = _kind(path)
        if k in ("dir", "other"):
            diffs.append("%s : pas un fichier ordinaire" % path)
        elif k == "unknown":
            diffs.append("%s : illisible" % path)
        elif read_private(path) != data:
            diffs.append("%s : %s" % (path, absent if k == "absent" else "à réécrire"))
    if _kind(paths.pub) == "dir":
        try:
            names = sorted(os.listdir(paths.pub))
        except OSError as e:
            diffs.append("%s : illisible (%s)" % (paths.pub, e.strerror or e))
            names = []
        for name in names:
            if name in plan.pubs or _live_tmp(name):
                continue
            p = os.path.join(paths.pub, name)
            if _kind(p) == "dir":
                warnings.append(_dir_note(p))
            else:
                diffs.append("%s : en trop" % clean(p))
    return diffs, warnings


# --- ligne Include -----------------------------------------------------------------------

def _keyword(line: str):
    """(mot-clé en minuscules, reste) d'une ligne de ssh_config ; (None, None) si vide ou commentaire."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None, None
    m = _KEYWORD.match(s)
    return (m.group(1).lower(), m.group(2)) if m else ("", s)


def _refs(args_text: str, paths: Paths) -> list:
    """Pour chaque argument d'`Include` : désigne-t-il le fichier généré ? (`~`, `~user`,
    relatif à ~/.ssh, chemin réel, joker de glob)."""
    try:
        args = shlex.split(args_text, comments=True)
    except ValueError:
        return []
    target, real = os.path.normpath(paths.config), os.path.realpath(paths.config)
    out = []
    for a in args:
        if a == "~" or a.startswith("~/"):
            a = paths.home + a[1:]
        elif a.startswith("~"):
            a = os.path.expanduser(a)  # ~user : passwd
        if not os.path.isabs(a):
            a = os.path.join(paths.ssh_dir, a)
        a = os.path.normpath(a)
        out.append(a == target or os.path.realpath(a) == real
                   or (any(c in a for c in "*?[") and fnmatch.fnmatchcase(target, a)))
    return out


@dataclass
class Scan:
    lines: list
    head: bool = False
    ours: list = field(default_factory=list)  # (index, dans un bloc Host/Match, seul argument : le nôtre)

    @property
    def conditional(self) -> list:
        return [i for i, cond, _ in self.ours if cond]

    def state(self) -> str:
        if self.head:
            return "head"
        if self.conditional:
            return "conditional"
        return "below" if self.ours else "missing"


def scan(text: str, paths: Paths) -> Scan:
    """Lignes coupées sur « \n » seulement (comme ssh). En tête = l'`Include` est la première
    ligne qui n'est ni vide ni un commentaire ; après une ligne Host/Match, il est conditionnel."""
    sc = Scan(text.split("\n"))
    first, in_block = None, False
    for i, line in enumerate(sc.lines):
        kw, rest = _keyword(line)
        if kw is None:
            continue
        if first is None:
            first = i
        if kw in ("host", "match"):
            in_block = True
        elif kw == "include":
            refs = _refs(rest, paths)
            if any(refs):
                sc.ours.append((i, in_block, all(refs)))
                if i == first:
                    sc.head = True
    return sc


def _read_regular(path: str, follow: bool):
    """(données, stat) d'un fichier ordinaire, sans jamais bloquer (FIFO) ; SshConfigError sinon."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | (0 if follow else os.O_NOFOLLOW))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SshConfigError("%s n'est pas un fichier ordinaire : refusé, rien modifié" % path)
        chunks = []
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            chunks.append(b)
        return b"".join(chunks), st
    finally:
        os.close(fd)


def include_state(paths: Paths):
    """(état, scan ou None) ; état : « head », « below », « conditional », « missing »,
    « nofile », « notregular » ou « unreadable »."""
    try:
        data, _ = _read_regular(paths.user_config, follow=True)
    except FileNotFoundError:
        return "nofile", None
    except SshConfigError:
        return "notregular", None
    except OSError:
        return "unreadable", None
    sc = scan(data.decode(errors="surrogateescape"), paths)
    return sc.state(), sc


def include_warning(paths: Paths) -> Optional[str]:
    st, sc = include_state(paths)
    p = paths.user_config
    if st == "head":
        return None
    if st == "below":
        return ("la ligne Include de sshvault n'est pas en tête de %s : les lignes qui la précèdent l'emportent ; "
                "lancer « sshvault ssh-config install »" % p)
    if st == "conditional":
        return ("%s ligne %d : Include conditionnel (dans un bloc Host/Match) : sshvault ne s'applique que dans ce "
                "bloc ; le sortir du bloc, puis « sshvault ssh-config install »" % (p, sc.conditional[0] + 1))
    if st == "unreadable":
        return "%s illisible : ligne Include de sshvault non vérifiée" % p
    if st == "notregular":
        return "%s n'est pas un fichier ordinaire : ligne Include de sshvault non vérifiée" % p
    return "%s n'inclut pas %s : ssh ne s'en sert pas ; lancer « sshvault ssh-config install »" % (p, paths.config)


def _tmp_write(path: str, data: bytes, mode: int, uid: int, gid: int) -> str:
    d, base = os.path.split(path)
    tmp = os.path.join(d, ".%s.sshvault.%d.tmp" % (base, os.getpid()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        try:
            os.write(fd, data)
            os.fsync(fd)
            if (uid, gid) != (os.getuid(), os.getgid()):
                os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
    except BaseException:
        _unlink_quiet(tmp)
        raise
    return tmp


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _replace(path: str, data: bytes, mode: int, uid: int, gid: int, expect=None) -> None:
    """Remplacement atomique (temporaire dans le même dossier puis rename) avec mode et
    propriétaire donnés. `expect` : (st_ino, st_size, st_mtime_ns) que `path` doit encore
    avoir juste avant le rename (sinon rien n'est remplacé)."""
    tmp = _tmp_write(path, data, mode, uid, gid)
    try:
        if expect is not None:
            st = os.lstat(path)
            if (st.st_ino, st.st_size, st.st_mtime_ns) != expect:
                raise SshConfigError("%s modifié pendant l'installation : rien changé, relancer" % path)
        os.replace(tmp, path)
    except BaseException:
        _unlink_quiet(tmp)
        raise


def _create(path: str, data: bytes, mode: int) -> None:
    """Crée `path` seulement s'il n'existe pas (link d'un temporaire) : FileExistsError sinon."""
    tmp = _tmp_write(path, data, mode, os.getuid(), os.getgid())
    try:
        os.link(tmp, path)
    finally:
        _unlink_quiet(tmp)


def _backup(paths: Paths, data: bytes) -> str:
    """Sauvegarde jamais écrasée : `config.sshvault.bak`, sinon `.bak.1`, `.bak.2`…"""
    for n in range(1000):
        p = paths.backup + ("" if n == 0 else ".%d" % n)
        try:
            _create(p, data, 0o600)
            return p
        except FileExistsError:
            continue
    raise SshConfigError("trop de sauvegardes %s.N : en supprimer avant de relancer" % paths.backup)


def install(paths: Paths) -> str:
    """Met `Include "<config>"` en première ligne de ~/.ssh/config ; renvoie un message."""
    p = paths.user_config
    line = include_line(paths)
    try:
        for _ in range(3):
            k = _kind(p)
            if k == "link":
                raise SshConfigError("%s est un lien symbolique : refusé, rien modifié" % p)
            if k == "absent":
                if not os.path.isdir(paths.ssh_dir):
                    ensure_dir(paths.ssh_dir)  # créé en 0700 ; un ~/.ssh existant n'est pas touché
                try:
                    _create(p, (line + "\n").encode(), 0o600)
                except FileExistsError:
                    continue  # créé entre-temps par un autre : chemin normal
                return "%s créé : %s" % (p, line)
            if k != "file":
                raise SshConfigError("%s n'est pas un fichier ordinaire : refusé, rien modifié" % p)
            try:
                data, st = _read_regular(p, follow=False)
            except FileNotFoundError:
                continue
            sc = scan(data.decode(errors="surrogateescape"), paths)
            if sc.head:
                return "%s : ligne Include déjà en tête, rien changé" % p
            if sc.conditional:
                raise SshConfigError("%s ligne %d : la ligne Include de sshvault est dans un bloc Host/Match (Include "
                                     "conditionnel) : non déplacée, rien modifié ; la sortir de ce bloc ou la "
                                     "supprimer, puis relancer" % (p, sc.conditional[0] + 1))
            drop = {i for i, _, sole in sc.ours if sole}
            new = "\n".join([line] + [l for i, l in enumerate(sc.lines) if i not in drop])
            bak = _backup(paths, data)
            _replace(p, new.encode(errors="surrogateescape"), stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid,
                     expect=(st.st_ino, st.st_size, st.st_mtime_ns))
            return "%s : ligne Include %s en tête (sauvegarde : %s)" % (p, "déplacée" if drop else "ajoutée", bak)
    except OSError as e:
        raise SshConfigError("%s : %s" % (p, e.strerror or e)) from None
    raise SshConfigError("%s : créé ou supprimé pendant l'installation : rien changé, relancer" % p)

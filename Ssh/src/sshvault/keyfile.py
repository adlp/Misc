"""Clé privée existante à importer (`sshvault import`) : lecture, type, format, clé publique,
empreinte, commentaire ; passphrase selon les décisions de la story 6.

- Types acceptés : Ed25519 et RSA (≥ 2048 bits). Formats : OpenSSH ; PKCS#8 (PEM) et RSA PEM
  PKCS#1 (`BEGIN RSA PRIVATE KEY`, décision utilisateur) : en clair, convertis au format OpenSSH
  (`ssh-keygen -p -P "" -N ""` sur une copie tmpfs) ; PKCS#1 chiffrée seulement avec
  `--decrypt` ; PKCS#8 chiffrée gardée telle quelle (ou déchiffrée avec `--decrypt`). PKCS#8 :
  RSA seulement avec OpenSSH 8.9 (Ed25519 PKCS#8 illisible, « invalid format »). Tout le
  reste est refusé (`KeyRefused`, code 2) : ECDSA, DSA, `-sk`, PuTTY, SSH2, clé publique,
  fichier qui n'est pas une clé. Fins de ligne CRLF normalisées en LF.
- Clé publique :
  - OpenSSH (et PEM converti) : lue dans l'en-tête du fichier (en clair même si la clé est
    chiffrée), sans passphrase ;
  - PKCS#8 chiffré : `ssh-keygen -y -f <copie>`, passphrase demandée par ssh-keygen. Mesuré
    (OpenSSH 8.9p1) : avec une clé chiffrée, `ssh-keygen -y` relit le fichier après la saisie,
    et un tube (/dev/stdin) déjà lu est vide (« incorrect passphrase » même avec la bonne).
    D'où une copie, dans le tmpfs privé (voir `private_copy`).
- Empreinte : `SHA256:` + base64 du SHA-256 de la clé publique, comme `ssh-keygen -l`.
- Passphrase : jamais en argument (`-P` interdit), jamais lue par sshvault : `ssh-keygen` la
  demande lui-même, sur le terminal (premier plan) ou par askpass (règles de readpass.c 8.9).
- `--decrypt` : `ssh-keygen -p -N "" -f <copie>` ; copie 0600 dans un sous-dossier 0700 neuf
  de `$XDG_RUNTIME_DIR/sshvault/` (tmpfs privé vérifié), lue puis supprimée sur tous les
  chemins, signaux masqués pendant la suppression ; le propriétaire tient un `flock` sur
  `.lock` dans le sous-dossier : un sous-dossier dont le verrou est libre (import tué par
  SIGKILL) est supprimé au prochain import, même si son pid a été réutilisé.
- Le fichier d'origine et sa `.pub` ne sont jamais modifiés : lecture seule.
"""
from __future__ import annotations

import base64
import contextlib
import fcntl
import os
import sys
import re
import shutil
import signal
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from typing import Optional

from .agent import NoEcho, PassphraseRefused, askpass_rules, tty_available
from .fsutil import NotPrivateTmpfs, check_private_tmpfs, ensure_dir, read_private
from .prompt import prompt_timeout
from .runtime import AgentError, fingerprint, resolve_dir

MAX_SIZE = 64 * 1024
MIN_RSA_BITS = 2048
TYPES = ("ssh-ed25519", "ssh-rsa")
CMD_TIMEOUT = 30.0
WORK_PREFIX = "import."
LOCK_NAME = ".lock"
_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_OPENSSH = re.compile(rb"\s*-----BEGIN OPENSSH PRIVATE KEY-----\r?\n(.*?)-----END OPENSSH PRIVATE KEY-----\s*", re.S)
_PKCS1 = re.compile(rb"\s*-----BEGIN RSA PRIVATE KEY-----\r?\n(.*?)-----END RSA PRIVATE KEY-----\s*", re.S)
_PKCS8 = re.compile(rb"\s*-----BEGIN (ENCRYPTED )?PRIVATE KEY-----\r?\n(.*?)-----END \1?PRIVATE KEY-----\s*", re.S)
_TYPE_NAMES = {"ecdsa": "ECDSA", "ssh-dss": "DSA", "sk-": "-sk (clé matérielle)"}


class KeyRefused(ValueError):
    """Fichier refusé : illisible, pas une clé privée, type ou format non accepté (code 2)."""


class KeyToolError(AgentError):
    """`ssh-keygen` absent, en erreur ou sans réponse (code 4)."""


@dataclass(frozen=True)
class KeyFile:
    path: str
    data: bytes                  # contenu à stocker (le fichier tel que lu, ou la copie déchiffrée)
    fmt: str                     # "openssh" | "pkcs8"
    encrypted: bool
    key_type: Optional[str] = None   # "ssh-ed25519" | "ssh-rsa" ; None tant qu'inconnu (PKCS#8 chiffré)
    blob: Optional[str] = None       # base64 de la clé publique
    bits: Optional[int] = None
    comment: str = ""                # commentaire de la clé (fichier, ou `.pub` voisine qui correspond)
    warnings: tuple = field(default_factory=tuple)

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.blob)

    @property
    def public_key(self) -> str:
        return "%s %s%s" % (self.key_type, self.blob, " " + self.comment if self.comment else "")

    def default_name(self) -> str:
        return self.comment or os.path.basename(self.path)


# --- lecture binaire (format SSH : uint32, string) ------------------------------------------

class _Reader:
    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def u32(self) -> int:
        if self.i + 4 > len(self.b):
            raise ValueError("tronqué")
        v = int.from_bytes(self.b[self.i:self.i + 4], "big")
        self.i += 4
        return v

    def string(self) -> bytes:
        n = self.u32()
        if n > len(self.b) - self.i:
            raise ValueError("tronqué")
        v = self.b[self.i:self.i + n]
        self.i += n
        return v

    def done(self) -> bool:
        return self.i == len(self.b)


def describe_blob(raw: bytes):
    """(type, bits, parties publiques) d'une clé publique au format SSH ; bits None hors
    Ed25519/RSA. ValueError si la structure est fausse."""
    r = _Reader(raw)
    t = r.string().decode("ascii")
    if t == "ssh-ed25519":
        pk = r.string()
        if len(pk) != 32 or not r.done():
            raise ValueError("Ed25519 malformée")
        return t, 256, (pk,)
    if t == "ssh-rsa":
        e, n = r.string(), r.string()
        if not r.done():
            raise ValueError("RSA malformée")
        return t, int.from_bytes(n, "big").bit_length(), (n.lstrip(b"\0"), e.lstrip(b"\0"))
    return t, None, ()


def _type_label(t: str) -> str:
    for prefix, label in _TYPE_NAMES.items():
        if t.startswith(prefix):
            return label
    return t


def check_type(key_type: str, bits: Optional[int]) -> None:
    if key_type not in TYPES:
        raise KeyRefused("type %s refusé (Ed25519 ou RSA d'au moins %d bits)" % (_clean(_type_label(key_type)),
                                                                                    MIN_RSA_BITS))
    if key_type == "ssh-rsa" and (bits or 0) < MIN_RSA_BITS:
        raise KeyRefused("RSA de %d bits refusée (au moins %d)" % (bits or 0, MIN_RSA_BITS))


def _clean(text: str) -> str:
    return _CONTROL.sub(lambda m: "\\x%02x" % ord(m.group()), text)


def _comment(raw: bytes) -> str:
    """Commentaire utilisable comme nom et dans la clé publique : une ligne, sans contrôle."""
    c = raw.decode("utf-8", errors="replace").strip()
    return "" if _CONTROL.search(c) else c


# --- fichier ---------------------------------------------------------------------------------------

def read_file(path: str) -> bytes:
    """Contenu d'un fichier ordinaire (lien suivi) de 64 Kio au plus ; lecture seule.
    O_NONBLOCK : une FIFO ne bloque pas (rejetée par fstat)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
    except OSError as e:
        raise KeyRefused("illisible : %s" % (e.strerror or e)) from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise KeyRefused("pas un fichier ordinaire")
        if st.st_size > MAX_SIZE:
            raise KeyRefused("trop gros pour une clé (%d octets, %d au plus)" % (st.st_size, MAX_SIZE))
        chunks, total = [], 0
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            total += len(b)
            if total > MAX_SIZE:
                raise KeyRefused("trop gros pour une clé (plus de %d octets)" % MAX_SIZE)
            chunks.append(b)
        return b"".join(chunks)
    except OSError as e:
        raise KeyRefused("illisible : %s" % (e.strerror or e)) from None
    finally:
        os.close(fd)


def _b64(body: bytes) -> bytes:
    try:
        return base64.b64decode(b"".join(body.split()), validate=True)
    except ValueError:
        raise KeyRefused("clé illisible (base64 invalide)") from None


def detect(data: bytes):
    """(format, chiffrée, corps décodé) ; format « openssh », « pkcs8 » ou « pkcs1 » (RSA PEM, corps
    None : converti par ssh-keygen) ; KeyRefused pour tout le reste."""
    head = data.lstrip()[:100]
    if head.startswith(b"PuTTY-User-Key-File-"):
        raise KeyRefused("format PuTTY refusé (OpenSSH ou PKCS#8 attendu ; puttygen … -O private-openssh)")
    if head.startswith(b"---- BEGIN SSH2"):
        raise KeyRefused("format SSH2 (RFC 4716) refusé : OpenSSH ou PKCS#8 attendu")
    if head.startswith(b"-----BEGIN DSA PRIVATE KEY-----"):
        raise KeyRefused("type DSA refusé (Ed25519 ou RSA d'au moins %d bits)" % MIN_RSA_BITS)
    if head.startswith(b"-----BEGIN EC PRIVATE KEY-----"):
        raise KeyRefused("type ECDSA refusé (Ed25519 ou RSA d'au moins %d bits)" % MIN_RSA_BITS)
    if re.match(rb"(ssh-|ecdsa-|sk-)\S+ [A-Za-z0-9+/]", head) or head.startswith(
            (b"-----BEGIN PUBLIC KEY-----", b"-----BEGIN RSA PUBLIC KEY-----", b"---- BEGIN SSH2 PUBLIC KEY")):
        raise KeyRefused("clé publique, pas une clé privée")
    m = _OPENSSH.fullmatch(data)
    if m:
        return "openssh", None, _b64(m.group(1))
    m = _PKCS8.fullmatch(data)
    if m:
        return "pkcs8", bool(m.group(1)), _b64(m.group(2))
    m = _PKCS1.fullmatch(data)
    if m:
        if re.match(rb"\s*Proc-Type:\s*4,ENCRYPTED", m.group(1)):
            return "pkcs1", True, None
        _b64(m.group(1))
        return "pkcs1", False, None
    if b"PRIVATE KEY-----" in data:
        raise KeyRefused("format de clé privée non reconnu (OpenSSH ou PKCS#8 attendu, un seul bloc)")
    raise KeyRefused("pas une clé privée (OpenSSH ou PKCS#8 attendu)")


def parse_openssh(raw: bytes):
    """En-tête d'une clé OpenSSH : (chiffrée, blob public, section privée). KeyRefused si illisible."""
    magic = b"openssh-key-v1\0"
    if not raw.startswith(magic):
        raise KeyRefused("clé OpenSSH illisible (en-tête)")
    r = _Reader(raw[len(magic):])
    try:
        cipher = r.string()
        r.string()  # kdf
        r.string()  # options du kdf
        n = r.u32()
        if n != 1:
            raise KeyRefused("clé OpenSSH à %d clés : une seule attendue" % n)
        pub = r.string()
        priv = r.string()
        if not r.done():
            raise ValueError("données en trop")
    except KeyRefused:
        raise
    except ValueError:
        raise KeyRefused("clé OpenSSH illisible (structure)") from None
    return cipher != b"none", pub, priv


def private_comment(key_type: str, parts: tuple, priv: bytes) -> str:
    """Commentaire d'une section privée en clair, après contrôle de sa cohérence avec l'en-tête."""
    r = _Reader(priv)
    try:
        if r.u32() != r.u32():
            raise ValueError("contrôle")
        if r.string().decode("ascii") != key_type:
            raise ValueError("type")
        if key_type == "ssh-ed25519":
            pk, sk = r.string(), r.string()
            if (pk,) != parts or len(sk) != 64 or sk[32:] != pk:
                raise ValueError("clé publique")
        else:
            n, e = r.string(), r.string()
            for _ in range(4):  # d, iqmp, p, q
                r.string()
            if (n.lstrip(b"\0"), e.lstrip(b"\0")) != parts:
                raise ValueError("clé publique")
        return _comment(r.string())
    except (ValueError, UnicodeDecodeError):
        raise KeyRefused("clé OpenSSH illisible (partie privée incohérente avec l'en-tête)") from None


def analyze(path: str, env=None, decrypt: bool = False) -> KeyFile:
    """Lecture et analyse sans invite. Clé PKCS#8 chiffrée, ou PKCS#1 chiffrée (acceptée avec
    `decrypt` seulement) : type, clé publique et commentaire restent inconnus (`blob` None)
    jusqu'à `public_from_encrypted` ou `decrypt`. PKCS#1 ou PKCS#8 en clair : convertie au
    format OpenSSH (`convert_pem`)."""
    data = read_file(path)
    fmt, encrypted, raw = detect(data)
    # Fins de ligne CRLF : normalisées en LF (mesuré, OpenSSH 8.9 : `ssh-add -` refuse une clé
    # OpenSSH en CRLF, « error in libcrypto ») ; le fichier d'origine n'est pas touché.
    data = data.replace(b"\r\n", b"\n")
    if fmt in ("pkcs1", "pkcs8") and not encrypted:
        return convert_pem(KeyFile(path, data, fmt, False), env)
    if fmt == "pkcs1":
        if not decrypt:
            raise KeyRefused("clé RSA PEM PKCS#1 (« BEGIN RSA PRIVATE KEY ») chiffrée : acceptée seulement avec "
                             "--decrypt (stockée déchiffrée, au format OpenSSH)")
        return KeyFile(path, data, fmt, True)
    if fmt == "openssh":
        encrypted, pub, priv = parse_openssh(raw)
        try:
            key_type, bits, parts = describe_blob(pub)
        except (ValueError, UnicodeDecodeError):
            raise KeyRefused("clé OpenSSH illisible (clé publique de l'en-tête)") from None
        check_type(key_type, bits)
        comment = "" if encrypted else private_comment(key_type, parts, priv)
        kf = KeyFile(path, data, fmt, encrypted, key_type, base64.b64encode(pub).decode(), bits, comment)
        return with_neighbor(kf)
    return KeyFile(path, data, fmt, encrypted)  # PKCS#8 chiffrée


def _with_public(kf: KeyFile, out: bytes, what: str) -> KeyFile:
    line = (out.decode(errors="replace").strip().splitlines() or [""])[0]
    parts = line.split(None, 2)
    try:
        raw = base64.b64decode(parts[1], validate=True)
        key_type, bits, _ = describe_blob(raw)
    except (IndexError, ValueError, UnicodeDecodeError):
        raise KeyToolError("%s : clé publique illisible dans la sortie" % what) from None
    if key_type != parts[0]:
        raise KeyToolError("%s : type incohérent dans la sortie" % what)
    check_type(key_type, bits)
    return replace(kf, key_type=key_type, blob=parts[1], bits=bits)


def with_neighbor(kf: KeyFile) -> KeyFile:
    """`.pub` voisine : son commentaire sert si la clé n'en donne pas et qu'elle correspond ;
    différente ou illisible : avertissement, ignorée. Jamais modifiée."""
    pub = kf.path + ".pub"
    if not os.path.lexists(pub):
        return kf
    try:
        text = read_file(pub).decode("utf-8", errors="replace")
    except KeyRefused as e:
        return replace(kf, warnings=kf.warnings + ("%s illisible (%s) : ignorée" % (_clean(pub), e),))
    lines = [l for l in text.splitlines() if l.strip()]
    parts = lines[0].split(None, 2) if len(lines) == 1 else []
    if len(parts) < 2 or parts[1] != kf.blob or parts[0] != kf.key_type:
        return replace(kf, warnings=kf.warnings + ("%s ne correspond pas à la clé privée : ignorée" % _clean(pub),))
    if kf.comment or len(parts) < 3:
        return kf
    return replace(kf, comment=_comment(parts[2].encode()))


# --- ssh-keygen -------------------------------------------------------------------------------

def keygen_exe(env=None) -> str:
    env = os.environ if env is None else env
    return env.get("SSHVAULT_SSH_KEYGEN") or "ssh-keygen"


def passphrase_mode(env) -> Optional[str]:
    """Comment `ssh-keygen` demandera la passphrase (readpass.c 8.9, RP_ALLOW_STDIN) :
    « stdin » (stdin terminal hérité), « askpass », « tty » (/dev/tty, stdin /dev/null), ou None
    si aucune invite n'est possible. Terminal : seulement au premier plan (sinon SIGTTIN)."""
    allow, usable = askpass_rules(env)
    fg = tty_available()
    try:
        stdin_tty = os.isatty(0)
    except OSError:
        stdin_tty = False
    # readpass.c : askpass d'abord si SSH_ASKPASS_REQUIRE=force (askpass_rules : permis), ou
    # prefer et askpass permis ; sinon le terminal si stdin en est un ; sinon askpass permis.
    if allow and usable and (env.get("SSH_ASKPASS_REQUIRE") or "").lower() in ("force", "prefer"):
        return "askpass"
    if fg and stdin_tty:
        return "stdin"
    if allow and usable:
        return "askpass"
    if fg:
        return "tty"
    return None


def keygen(args, input: Optional[bytes] = None, env=None, mode: Optional[str] = None,
           timeout: float = CMD_TIMEOUT, refuse: bool = False) -> bytes:
    """`ssh-keygen args` ; sortie standard. `mode` None : aucune invite possible (session à part,
    askpass interdit). Sinon (voir passphrase_mode) : invite par ssh-keygen ; au terminal, même
    session et écho coupé (état d'origine rétabli sur tous les chemins). Délai : seul
    ssh-keygen est tué (terminal) ou tout son groupe (askpass compris)."""
    base = dict(os.environ if env is None else env)
    exe = keygen_exe(base)
    allow, usable = askpass_rules(base)
    if mode is None or (allow and not usable):
        base["SSH_ASKPASS_REQUIRE"] = "never"
    tty = mode in ("stdin", "tty")
    argv = [exe, *args]
    stdin = subprocess.PIPE if input is not None else (None if mode == "stdin" else subprocess.DEVNULL)
    guard = NoEcho(newline=False) if tty else contextlib.nullcontext()
    with guard:
        try:
            p = subprocess.Popen(argv, env=base, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=not tty)
        except FileNotFoundError:
            raise KeyToolError("ssh-keygen introuvable (%s) : installer openssh-client" % exe) from None
        except OSError as e:
            raise KeyToolError("lancement de %s : %s" % (exe, e.strerror or e)) from None
        done = False
        try:
            out, err = p.communicate(input=input, timeout=timeout)
            done = True
        except subprocess.TimeoutExpired:
            if mode is not None:
                raise PassphraseRefused("aucune passphrase acceptée en %gs : rien importé" % timeout) from None
            raise KeyToolError("ssh-keygen %s sans réponse en %gs" % (args[0], timeout)) from None
        finally:
            if not done:
                try:
                    if tty:
                        p.kill()
                    else:
                        os.killpg(p.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    p.communicate(timeout=5)
                except Exception:
                    pass
    if p.returncode != 0:
        msg = " ".join(l.strip() for l in err.decode(errors="replace").splitlines() if l.strip())
        msg = _clean(msg)[:300] or "code %d" % p.returncode
        if mode is not None and "passphrase" in msg:
            raise PassphraseRefused("passphrase refusée ou annulée (ssh-keygen : %s) : rien importé" % msg)
        if mode is not None and ("invalid format" in msg or "unsupported" in msg):
            # mesuré (8.9p1) : Ed25519 PKCS#8 chiffrée d'OpenSSL, après la passphrase
            raise KeyRefused("clé illisible par ssh-keygen de ce poste (%s) ; PKCS#8 : RSA seulement avec "
                             "OpenSSH 8.9" % msg)
        if mode is None and (input is not None or refuse):
            # ssh-keygen a lu la clé fournie et la refuse (format, clé illisible ou chiffrée)
            raise KeyRefused("clé illisible par ssh-keygen (%s)" % msg)
        raise KeyToolError("ssh-keygen %s (code %d) : %s" % (args[0], p.returncode, msg))
    return out


# --- copie dans le tmpfs privé -----------------------------------------------------------------

@contextlib.contextmanager
def _blocked():
    old = signal.pthread_sigmask(signal.SIG_BLOCK, _SIGNALS)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


def _alive(pid: int) -> bool:
    return os.path.exists("/proc/%d" % pid)


def _stale(d: str, pid: int) -> bool:
    """Le sous-dossier `d` n'est plus tenu ? Son propriétaire garde un `flock` sur `d/.lock` tant
    qu'il existe (un pid réutilisé ne le retient donc pas) ; sans `.lock` (créé juste après le
    dossier) : pid disparu."""
    try:
        fd = os.open(os.path.join(d, LOCK_NAME), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return not _alive(pid)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def reap_stale(base: str) -> None:
    """Sous-dossiers `import.<pid>.*` d'un import disparu (tué par SIGKILL) : supprimés."""
    try:
        names = os.listdir(base)
    except OSError:
        return
    for n in names:
        m = re.fullmatch(re.escape(WORK_PREFIX) + r"(\d+)\..+", n)
        d = os.path.join(base, n)
        if m and os.path.isdir(d) and not os.path.islink(d) and _stale(d, int(m.group(1))):
            shutil.rmtree(d, ignore_errors=True)


@contextlib.contextmanager
def private_copy(data: bytes, env=None):
    """Chemin d'une copie 0600 de `data` dans un sous-dossier 0700 neuf de
    `$XDG_RUNTIME_DIR/sshvault/` (tmpfs privé vérifié, comme en 0.1.0) ; le sous-dossier est
    supprimé à la sortie, quelle qu'elle soit, signaux SIGINT/SIGTERM/SIGHUP masqués pendant
    la création et la suppression (un signal arrivé entre-temps est traité après)."""
    try:
        base = ensure_dir(resolve_dir(env))
    except AgentError as e:
        raise AgentError("copie de la clé impossible dans un tmpfs privé : %s ; rien importé" % e) from None
    except OSError as e:
        raise AgentError("copie de la clé impossible dans un tmpfs privé (%s) : rien importé"
                         % (e.strerror or e)) from None
    reap_stale(base)
    work, lock = None, None
    try:
        try:
            with _blocked():
                work = tempfile.mkdtemp(prefix="%s%d." % (WORK_PREFIX, os.getpid()), dir=base)
                lock = os.open(os.path.join(work, LOCK_NAME), os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                               0o600)
                fcntl.flock(lock, fcntl.LOCK_EX)
        except OSError as e:
            raise AgentError("copie de la clé impossible dans un tmpfs privé (%s) : rien importé"
                             % (e.strerror or e)) from None
        try:
            check_private_tmpfs(work)
        except NotPrivateTmpfs as e:
            raise AgentError("copie refusée : %s" % e) from None
        path = os.path.join(work, "key")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
            finally:
                os.close(fd)
        except OSError as e:  # ENOSPC, EDQUOT…
            raise AgentError("copie de la clé impossible dans un tmpfs privé (%s) : rien importé"
                             % (e.strerror or e)) from None
        yield path
    except BaseException:
        # erreur en cours : un échec du nettoyage n'est qu'un avertissement, l'erreur d'origine reste
        _cleanup(work, lock, strict=False)
        raise
    _cleanup(work, lock, strict=True)


def _cleanup(work, lock, strict: bool) -> None:
    if work is None:
        return
    with _blocked():
        shutil.rmtree(work, ignore_errors=True)
        if lock is not None:
            os.close(lock)
        if os.path.lexists(work):
            msg = "copie temporaire %s non supprimée : la supprimer à la main" % work
            if strict:
                raise AgentError(msg)
            try:
                sys.stderr.write("sshvault: avertissement : %s\n" % msg)
            except (OSError, ValueError):
                pass


def public_from_encrypted(kf: KeyFile, mode: str, env=None, notice=None) -> KeyFile:
    """PKCS#8 chiffré, sans --decrypt : passphrase demandée par `ssh-keygen -y`, pour la seule
    clé publique ; la clé stockée reste le fichier chiffré. `notice` : appelé juste avant l'invite."""
    with private_copy(kf.data, env) as copy:
        if notice:
            notice()
        out = keygen(["-y", "-f", copy], env=env, mode=mode, timeout=prompt_timeout(env or os.environ) + 10)
    return with_neighbor(_with_public(kf, out, "ssh-keygen -y"))


def decrypt(kf: KeyFile, mode: str, env=None, notice=None) -> KeyFile:
    """`--decrypt` : copie déchiffrée par `ssh-keygen -p -N "" -f <copie>` (ancienne passphrase
    demandée par ssh-keygen), relue, puis supprimée. Résultat : clé OpenSSH en clair, même clé
    publique que l'originale si elle était connue."""
    with private_copy(kf.data, env) as copy:
        if notice:
            notice()
        keygen(["-p", "-N", "", "-f", copy], env=env, mode=mode, timeout=prompt_timeout(env or os.environ) + 10)
        data = read_private(copy)
    return _rewritten(kf, data)


def convert_pem(kf: KeyFile, env=None) -> KeyFile:
    """PEM en clair (RSA PKCS#1, PKCS#8) : convertie au format OpenSSH par `ssh-keygen -p -P ""
    -N "" -f <copie>` (passphrases vides : aucun secret en argument ; aucune invite possible),
    copie dans le tmpfs privé, relue puis supprimée. Fichier d'origine intact."""
    with private_copy(kf.data, env) as copy:
        keygen(["-p", "-P", "", "-N", "", "-f", copy], env=env, refuse=True)
        data = read_private(copy)
    out = _rewritten(kf, data)
    what = "RSA PEM PKCS#1" if kf.fmt == "pkcs1" else "PKCS#8"
    return replace(out, warnings=out.warnings + ("%s : %s convertie au format OpenSSH pour l'import "
                                                 "(fichier d'origine inchangé)" % (_clean(kf.path), what),))


def _rewritten(kf: KeyFile, data: Optional[bytes]) -> KeyFile:
    """Copie réécrite par `ssh-keygen -p` : clé OpenSSH en clair, analysée et vérifiée."""
    if data is None:
        raise KeyToolError("copie réécrite par ssh-keygen -p illisible")
    fmt, _, raw = detect(data)
    if fmt != "openssh":
        raise KeyToolError("ssh-keygen -p : format inattendu de la copie réécrite")
    encrypted, pub, priv = parse_openssh(raw)
    if encrypted:
        raise KeyToolError("ssh-keygen -p : copie toujours chiffrée")
    try:
        key_type, bits, parts = describe_blob(pub)
    except (ValueError, UnicodeDecodeError):
        raise KeyToolError("ssh-keygen -p : clé publique illisible dans la copie") from None
    blob = base64.b64encode(pub).decode()
    if kf.blob is not None and blob != kf.blob:
        raise KeyToolError("ssh-keygen -p : la copie réécrite n'a pas la clé publique du fichier")
    check_type(key_type, bits)
    comment = private_comment(key_type, parts, priv) or kf.comment
    out = replace(kf, data=data, fmt="openssh", encrypted=False, key_type=key_type, blob=blob, bits=bits,
                  comment=comment)
    return out if kf.blob is not None else with_neighbor(out)

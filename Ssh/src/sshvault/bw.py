"""`BwBackend` : le coffre via le CLI officiel `bw`, en sous-processus.

- Exécutable : `SSHVAULT_BW` (tests), sinon le réglage `bw-path` de sshvault (chemin absolu),
  sinon `bw` cherché dans le PATH. Un réglage posé n'est jamais doublé par le PATH : `bw`
  absent à ce chemin = erreur (BackendNotFound) qui cite le chemin et le réglage. Le chemin
  n'est jamais passé à un shell (argv de Popen).
- Données propres à sshvault, une par compte (CAP-10 : une instance = un compte) :
  `BITWARDENCLI_APPDATA_DIR=${XDG_DATA_HOME:-~/.local/share}/sshvault/accounts/<alias>/bw`,
  donc un login séparé de l'usage personnel de `bw` (0.8.0 : `sshvault/bw`, un seul compte).
- `--nointeraction` partout sauf `login` ; délai borné (`SSHVAULT_BW_TIMEOUT`,
  défaut 60 s) ; la session passe par `BW_SESSION` dans l'environnement du
  sous-processus, le mot de passe maître par `--passwordenv` sur un environnement
  propre au sous-processus ; jamais en argument, jamais dans un fichier.
- `bw serve` n'est jamais utilisé.

`bw` répond en JSON sur stdout (sans retour à la ligne final) et ses erreurs
sont une ligne sur stderr avec le code 1. Messages reconnus (lus dans le source
embarqué de bw 2026.9.1) : « You are not logged in. », « Vault is locked. ».
"""
from __future__ import annotations

import base64
import copy
import errno
import sys
import json
import os
import re
import shutil
import signal
import subprocess
import termios
from typing import Callable, Optional

from .backend import (FORWARD_FIELD, HOSTS_FIELD, BackendError, BackendNotFound, ItemNotFound, LogoutUnknown,
                      NotLoggedIn,
                      PasswordRefused, Prompt, SshKeyItem, VaultBackend, VaultError, VaultLocked, VaultStatus, WriteFailed,
                      normalize_fingerprint, normalize_hosts, parse_hosts)
from .fsutil import ensure_dir, exe_problem, exposure_warning
from .session import DEFAULT_TTL, SessionStore, SessionStoreError, valid_token
from .settings import account_dir, clear_logged_out, data_root, is_logged_out, seconds  # noqa: F401 (réexportés)
from .settings import logged_out_path, set_logged_out
from .text import clean as _clean

DEFAULT_TIMEOUT = 60.0
LOGIN_TIMEOUT = 600.0  # login interactif (saisie, 2FA)
REREAD_TIMEOUT = 10.0  # relecture de `bw status` après un `bw logout` sans réponse (local, rapide)
SSH_KEY_TYPE = 5
PASSWORD_VAR = "SSHVAULT_BW_MASTER_PASSWORD"
EXE_VAR = "SSHVAULT_BW"
BW_PATH_KEY = "bw-path"
INSTALL_HINT = ("installer le binaire natif (https://bitwarden.com/download/?app=cli&platform=linux), "
                "par exemple dans ~/.local/bin, puis « sshvault config set bw-path <chemin absolu> » "
                "si son dossier n'est pas dans le PATH de ssh")
#: Source de l'exécutable → (ce qui a été essayé, comment corriger), pour les messages d'erreur.
#: Le réglage `bw-path` est revérifié avant chaque lancement (`fsutil.exe_problem`) ; s'il est
#: modifiable par d'autres, un avertissement (une fois par processus) : bw reçoit le mot de
#: passe maître et BW_SESSION.
_EXE_SOURCES = {
    EXE_VAR: ("(%s, " + EXE_VAR + ")", "corriger ou retirer " + EXE_VAR),
    BW_PATH_KEY: ("(%s, réglage " + BW_PATH_KEY + ")",
                  "corriger par « sshvault config set " + BW_PATH_KEY + " <chemin absolu> » ou revenir au "
                  "PATH par « sshvault config unset " + BW_PATH_KEY + " »"),
    "PATH": ("(%s cherché dans le PATH, réglage " + BW_PATH_KEY + " non posé)", INSTALL_HINT),
    "argument": ("(%s)", INSTALL_HINT),
}
# Variables de l'utilisateur qui changeraient le comportement ou la sortie de bw.
_STRIP_ENV = ("BW_SESSION", "BW_NOINTERACTION", "BW_RAW", "BW_RESPONSE", "BW_QUIET",
              "BW_PRETTY", "BW_CLEANEXIT", "BITWARDENCLI_APPDATA_DIR", PASSWORD_VAR,
              # BITWARDENCLI_DEBUG=true écrit les journaux info/debug sur stdout (console.log)
              "BITWARDENCLI_DEBUG")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
MSG_NOT_LOGGED_IN = "You are not logged in."
MSG_LOCKED = "Vault is locked."


def one_line(text: str, limit: int = 300) -> str:
    text = _ANSI.sub("", text or "")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # bw annonce sur stderr la création de son dossier de données : ce n'est pas l'erreur.
    lines = [l for l in lines if not l.startswith("Could not find ")] or lines
    s = " ".join(lines)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def last_line(text: str) -> str:
    """Dernière ligne utile : le SDK de bw journalise d'abord des lignes « ERROR <module>: … »
    (mesuré, mauvais mot de passe, bw 2026.9.1), la dernière est le message."""
    lines = [l.strip() for l in _ANSI.sub("", text or "").splitlines() if l.strip()]
    useful = [l for l in lines if not l.startswith(("ERROR ", "Could not find "))]
    return one_line((useful or lines or [""])[-1])


def default_appdata(env=None) -> str:
    """Dossier de données de bw de la 0.8.0 (un seul compte), repris à l'adoption."""
    return os.path.join(data_root(env), "bw")


def account_appdata(alias: str, env=None) -> str:
    """Dossier de données de bw d'un compte : `<data_root>/accounts/<alias>/bw`."""
    return os.path.join(account_dir(alias, env), "bw")


def resolve_exe(env=None, configured: Optional[Callable[[], Optional[str]]] = None) -> tuple:
    """(exécutable, source) de bw : `SSHVAULT_BW`, sinon le réglage `bw-path` (`configured()`,
    lu seulement si `SSHVAULT_BW` est vide ; ConfigError s'il est invalide), sinon `bw` du PATH.
    Source : "SSHVAULT_BW", "bw-path" ou "PATH"."""
    env = os.environ if env is None else env
    v = env.get(EXE_VAR)
    if v:
        return v, EXE_VAR
    path = configured() if configured is not None else None
    if path:
        return path, BW_PATH_KEY
    return "bw", "PATH"


def _stderr_warning(text: str) -> None:
    try:
        sys.stderr.write("sshvault: %s\n" % text)
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def bw_timeout(env=None) -> float:
    env = os.environ if env is None else env
    try:
        return seconds(env, "SSHVAULT_BW_TIMEOUT", DEFAULT_TIMEOUT)
    except ValueError as e:
        raise BackendError(str(e)) from None


def _save_tty():
    """(fd, attributs) de /dev/tty, ou None sans terminal."""
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return None
    try:
        return fd, termios.tcgetattr(fd)
    except (OSError, termios.error):
        os.close(fd)
        return None


def _restore_tty(saved) -> None:
    if saved is None:
        return
    fd, attrs = saved
    try:
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (OSError, termios.error):
        pass
    finally:
        os.close(fd)


#: bw-path déjà vérifiés (avertissement d'exposition) dans ce processus ; vidé au début de
#: chaque commande (`reset_process_state`).
_EXPOSURE_CHECKED: set = set()


def reset_process_state() -> None:
    """Début d'une commande (`main` appelé plusieurs fois dans un même processus) : chaque
    commande redit l'avertissement d'exposition de bw-path une fois."""
    _EXPOSURE_CHECKED.clear()


class BwTimeout(BackendError):
    """bw n'a pas fini dans le délai (mesuré : connexion TLS bloquée, bw ne l'abandonne jamais)."""


class Result:
    __slots__ = ("rc", "out", "err")

    def __init__(self, rc: int, out: str, err: str):
        self.rc, self.out, self.err = rc, out, err

    def has(self, msg: str) -> bool:
        return msg in _ANSI.sub("", self.err)


class BwBackend(VaultBackend):
    def __init__(self, store: Optional[SessionStore] = None, exe: Optional[str] = None,
                 appdata: Optional[str] = None, timeout: Optional[float] = None,
                 bw_path: Optional[Callable[[], Optional[str]]] = None,
                 warn: Optional[Callable[[str], None]] = None, label: Optional[str] = None,
                 email: Optional[str] = None, server: Optional[str] = None, hint: str = ""):
        """`label` : alias du compte (invite) ; `email`, `server` : ceux du registre (login) ;
        `hint` : suffixe des commandes suggérées (« --account <alias> » s'il y a plusieurs
        comptes). `exe` : exécutable imposé ; sinon résolu au premier appel de bw (`resolve_exe`) avec
        `bw_path()`, le réglage `bw-path` (None : non posé) : une commande qui ne lance pas bw
        ne lit pas la configuration. `warn` : affiche aussitôt un avertissement d'une ligne
        (bw-path exposé à d'autres, avant le premier lancement de bw) ; défaut : stderr."""
        self.store = store or SessionStore()
        # session que le magasin a refusée (« session non rangée ») : gardée en mémoire pour la
        # suite de cette commande seulement, jamais écrite
        self._mem_session: Optional[str] = None
        self._exe = (exe, "argument") if exe else None
        self._bw_path = bw_path
        self.label, self.email, self.server, self.hint = label, email, server, hint
        self._warn = warn or _stderr_warning
        self.appdata = appdata or default_appdata()
        self.timeout = timeout if timeout is not None else bw_timeout()
        self.calls = 0  # nombre d'appels à bw (mesure du coût : ~1,4 s chacun)
        self.marker_cleared = False  # marqueur `logged-out` retiré par cette commande (bw vu connecté)
        self.marker_warning: Optional[str] = None  # avertissement « non retiré », dit une fois
        self.warnings: list = []  # avertissements d'une ligne pour l'utilisateur

    @property
    def exe(self) -> str:
        return self._resolved()[0]

    def _resolved(self) -> tuple:
        if self._exe is None:
            self._exe = resolve_exe(configured=self._bw_path)
        return self._exe

    def _not_found(self, what: str, why: Optional[str] = None) -> BackendNotFound:
        """`<what> (<chemin>, <source>)[ : <why>] : <remède de la source>`, une ligne."""
        exe, source = self._resolved()
        tried, fix = _EXE_SOURCES[source]
        return BackendNotFound("%s %s%s : %s" % (what, tried % _clean(exe), " : " + _clean(why) if why else "", fix))

    def _target(self) -> Optional[str]:
        """Fichier que lance Popen (PATH résolu comme lui), s'il existe."""
        exe = self.exe
        found = exe if os.sep in exe else shutil.which(exe, mode=os.F_OK)
        return found if found and os.path.exists(found) else None

    def _check_exe(self) -> None:
        """Réglage `bw-path` : revérifié avant chaque lancement (le PATH n'est jamais essayé)."""
        exe, source = self._resolved()
        if source != BW_PATH_KEY:
            return
        try:
            os.stat(exe)
        except OSError as e:
            if e.errno in (errno.ENOENT, errno.ENOTDIR):
                raise self._not_found("bw introuvable") from None
            raise self._not_found("bw refusé", str(e.strerror or e)) from None  # EACCES, ELOOP…
        why = exe_problem(exe)
        if why:
            raise self._not_found("bw refusé", why)
        if exe not in _EXPOSURE_CHECKED:
            # accepté, mais dit tout de suite (une fois par processus, quel que soit le nombre de
            # comptes), avant que bw reçoive le mot de passe maître ou la session : choix de l'utilisateur
            _EXPOSURE_CHECKED.add(exe)
            warning = exposure_warning(exe, BW_PATH_KEY)
            if warning:
                self._warn(warning)

    def describe_exe(self) -> str:
        """`<chemin> (<source>)` du bw qui sera lancé, sans le lancer (ligne `bw :` de status)."""
        exe, source = self._resolved()
        if source == "PATH":
            found = shutil.which(exe)
            return "%s (PATH)" % _clean(found) if found else "bw (introuvable dans le PATH)"
        label = {EXE_VAR: EXE_VAR, BW_PATH_KEY: "réglage " + BW_PATH_KEY}.get(source, source)
        return "%s (%s)" % (_clean(exe), label)

    def cmd(self, name: str) -> str:
        """`sshvault <name>[ --account <alias>]` pour un message."""
        return "sshvault %s%s" % (name, self.hint)

    def _not_logged_in(self, what: str = "non connecté au coffre") -> NotLoggedIn:
        return NotLoggedIn("%s : lancer « %s »" % (what, self.cmd("login")))

    def info(self) -> dict:
        return {"session": self.store.last_backend, "store": self.store.describe(), "data": self.appdata}

    # --- sous-processus --------------------------------------------------------

    def _env(self, session: Optional[str], extra: Optional[dict] = None) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
        env["BITWARDENCLI_APPDATA_DIR"] = self.appdata
        if session:
            env["BW_SESSION"] = session
        if extra:
            env.update(extra)
        return env

    def _run(self, args: list, session: Optional[str] = None, extra_env: Optional[dict] = None,
             interactive: bool = False, timeout: Optional[float] = None,
             input: Optional[bytes] = None) -> Result:
        """`input` : octets passés sur le stdin de bw (jamais en argument : argv est lisible par ps)."""
        try:
            ensure_dir(self.appdata)
        except OSError as e:
            raise BackendError("dossier de données de bw %s : %s" % (self.appdata, e.strerror or e)) from None
        self._check_exe()
        argv = [self.exe] + ([] if interactive else ["--nointeraction"]) + args  # jamais de shell
        timeout = timeout or self.timeout
        self.calls += 1
        tty = _save_tty() if interactive else None
        try:
            return self._spawn(argv, args, session, extra_env, interactive, timeout, input)
        finally:
            # bw tué (Ctrl-C, signal, délai) pendant une saisie masquée : écho rétabli
            _restore_tty(tty)

    def _spawn(self, argv, args, session, extra_env, interactive, timeout, input=None) -> Result:
        try:
            p = subprocess.Popen(
                argv, env=self._env(session, extra_env), umask=0o077,
                stdin=None if interactive else subprocess.PIPE if input is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=None if interactive else subprocess.PIPE,
                # hors interactif : groupe à part, tué en entier si le délai expire
                start_new_session=not interactive)
        except FileNotFoundError:
            # fichier présent mais ENOENT : interpréteur du shebang ou chargeur ELF absent
            raise self._not_found("interpréteur ou chargeur de bw introuvable" if self._target()
                                  else "bw introuvable") from None
        except PermissionError:
            raise self._not_found("bw non exécutable") from None
        except OSError as e:
            if e.errno == errno.ENOEXEC:
                raise self._not_found("bw : format non exécutable") from None
            exe, source = self._resolved()
            raise BackendError("erreur bw : lancement de bw %s : %s"
                               % (_EXE_SOURCES[source][0] % _clean(exe), e.strerror or e)) from None
        done = False
        try:
            out, err = p.communicate(input=input, timeout=timeout)
            done = True
        except subprocess.TimeoutExpired:
            raise BwTimeout("erreur bw : « bw %s » sans réponse en %gs" % (args[0], timeout)) from None
        finally:
            if not done:
                self._kill(p, interactive)
        return Result(p.returncode, out.decode(errors="replace"),
                      (err or b"").decode(errors="replace"))

    def _run_retry(self, args: list, attempts: int, **kw) -> Result:
        """Commande réseau idempotente (sync) : `attempts` essais dans le même délai total.

        Mesuré (2026-10-07, compte de test) : sur un chemin réseau qui perd des paquets, une
        connexion neuve de bw peut rester bloquée, ClientHello TLS jamais acquitté ; bw (Node)
        n'a pas de délai propre et retransmet pendant des minutes. Une nouvelle connexion passe.
        """
        if attempts <= 1:
            return self._run(args, **kw)
        each = (kw.pop("timeout", None) or self.timeout) / attempts
        for n in range(attempts):
            try:
                return self._run(args, timeout=each, **kw)
            except BwTimeout:
                if n == attempts - 1:
                    raise BwTimeout("erreur bw : « bw %s » sans réponse (%d essais de %gs ; réseau ?)"
                                    % (args[0], attempts, each)) from None
        raise AssertionError("inaccessible")

    @staticmethod
    def _kill(p: subprocess.Popen, interactive: bool) -> None:
        try:
            if interactive:
                p.kill()
            else:
                os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            p.communicate(timeout=5)
        except Exception:
            pass

    def _json(self, r: Result, what: str):
        try:
            return json.loads(r.out)
        except ValueError:
            raise BackendError("erreur bw : réponse illisible à « %s » (JSON invalide)" % what) from None

    def _fail(self, r: Result, what: str) -> BackendError:
        msg = one_line(r.err) or one_line(r.out) or "code %d" % r.rc
        return BackendError("erreur bw (%s, code %d) : %s" % (what, r.rc, msg))

    # --- session ---------------------------------------------------------------

    def _stored_session(self) -> Optional[str]:
        """Session rangée, sinon celle gardée en mémoire par cette commande (magasin en panne)."""
        try:
            session = self.store.get()
        except SessionStoreError:
            if self._mem_session:
                return self._mem_session
            raise
        return session or self._mem_session

    def _put_session(self, token: str, ttl: int) -> None:
        """Range la session ; magasin en panne : gardée en mémoire (cette commande), puis l'erreur."""
        try:
            self.store.put(token, ttl)
        except SessionStoreError:
            self._mem_session = token
            raise

    def _forget(self) -> None:
        """La session rangée a été refusée par bw (expirée, invalidée) : on la purge."""
        self._mem_session = None
        try:
            self.store.clear()
        except SessionStoreError:
            pass

    def _seen_connected(self) -> None:
        """bw vu connecté (état lu, déverrouillage ou login réussi) : le marqueur `logged-out` du
        compte (posé par `sshvault logout`) est retiré. Point commun à tous les chemins ; échec :
        avertissement de fin de commande."""
        if not self.label:
            return
        try:
            if is_logged_out(self.label):
                clear_logged_out(self.label)
                self.marker_cleared = True
        except OSError as e:
            if self.marker_warning is None:  # une fois par backend
                self.marker_warning = ("marqueur %s non retiré (%s) : « sshvault ensure » continuera de proposer "
                                       "« sshvault login »" % (logged_out_path(self.label), e.strerror or e))
                self.warnings.append(self.marker_warning)

    def restore_marker(self) -> None:
        """bw finalement non connecté alors que cette commande avait retiré le marqueur : reposé
        (échec : avertissement)."""
        if not (self.label and self.marker_cleared):
            return
        try:
            set_logged_out(self.label)
            self.marker_cleared = False
        except OSError as e:
            self.warnings.append("marqueur %s non reposé (%s) : « sshvault ensure » ne proposera pas de relancer "
                                 "« sshvault login »" % (logged_out_path(self.label), e.strerror or e))

    def _bw_status(self, session: Optional[str], timeout: Optional[float] = None) -> VaultStatus:
        r = self._run(["status"], session=session, timeout=timeout)
        if r.rc != 0:
            raise self._fail(r, "status")
        d = self._json(r, "status")
        state = d.get("status") if isinstance(d, dict) else None
        if state not in ("unauthenticated", "locked", "unlocked"):
            raise BackendError("erreur bw : état inconnu dans « status » : %r" % (state,))
        if state != "unauthenticated":
            self._seen_connected()
        return VaultStatus(state, d.get("serverUrl"), d.get("userEmail"), d.get("lastSync"))

    def status(self, forget: bool = True) -> VaultStatus:
        """État du compte dans bw. `forget=False` : sonde sans effet, sans lire ni toucher la
        session rangée (« unlocked » n'est alors jamais rendu : « locked » pour un compte connecté)."""
        if not forget:
            return self._bw_status(None)
        session = self._stored_session()
        st = self._bw_status(session)
        if session and st.state != "unlocked":
            self._forget()
        return st

    def _unlock_with(self, prompt: Optional[Prompt], ttl: int, known_logged_in: bool,
                     must_store: bool = False) -> str:
        if not known_logged_in:
            st = self._bw_status(None)
            if st.state == "unauthenticated":
                raise self._not_logged_in()
            if st.state == "unlocked":
                return ""  # déverrouillé sans session (bw configuré sans verrouillage)
            who = st.user or "?"
        else:
            who = None
        if prompt is None:
            raise VaultLocked("coffre verrouillé : lancer « %s » (invite désactivée)" % self.cmd("unlock"))
        password = prompt("sshvault : mot de passe maître du coffre%s%s : "
                          % (" « %s »" % self.label if self.label else "", " (%s)" % _clean(who) if who else ""))
        try:
            r = self._run(["unlock", "--passwordenv", PASSWORD_VAR, "--raw"],
                          extra_env={PASSWORD_VAR: password})
        finally:
            del password
        if r.rc != 0:
            if r.has(MSG_NOT_LOGGED_IN):
                raise self._not_logged_in()
            # unlock est local : un refus est presque toujours le mot de passe (mesuré :
            # « Cryptography error, The decryption operation failed », code 1).
            raise PasswordRefused("mot de passe maître refusé par bw (%s)" % (last_line(r.err) or "code %d" % r.rc))
        token = r.out.strip()
        if not valid_token(token):
            raise BackendError("erreur bw : « unlock » n'a pas renvoyé de session")
        self._seen_connected()  # tout déverrouillage réussi (unlock, invite de load, list, ensure…)
        try:
            self._put_session(token, ttl)
        except SessionStoreError as e:
            if must_store:
                raise
            # La session sert à la suite de cette commande (en mémoire), jamais à la suivante.
            self.warnings.append("session non rangée : %s" % e)
        return token

    def unlock(self, prompt: Optional[Prompt], ttl: int = DEFAULT_TTL) -> None:
        session = self.store.get()
        if session:
            st = self._bw_status(session)
            if st.state == "unlocked":
                self.store.put(session, ttl)  # nouvelle durée de vie
                return
            self._forget()
            if st.state == "unauthenticated":
                raise self._not_logged_in()
            self._unlock_with(prompt, ttl, known_logged_in=True, must_store=True)
            return
        self._unlock_with(prompt, ttl, known_logged_in=False, must_store=True)

    def _with_session(self, args: list, what: str, prompt: Optional[Prompt], attempts: int = 1,
                      input: Optional[bytes] = None) -> Result:
        """Lance `bw args` avec la session rangée ; un seul appel si elle est valide.
        Session refusée : purge, puis traité comme verrouillé (invite, unlock, nouvel essai :
        « Vault is locked. » dit que bw n'a rien fait)."""
        session = self._stored_session()
        known_logged_in = False
        if session:
            r = self._run_retry(args, attempts, session=session, input=input)
            if r.rc == 0:
                return r
            if r.has(MSG_NOT_LOGGED_IN):
                self._forget()
                raise self._not_logged_in()
            if not r.has(MSG_LOCKED):
                raise self._fail(r, what)
            self._forget()
            known_logged_in = True
        session = self._unlock_with(prompt, DEFAULT_TTL, known_logged_in)
        r = self._run_retry(args, attempts, session=session or None, input=input)
        if r.rc == 0:
            return r
        if r.has(MSG_NOT_LOGGED_IN):
            raise self._not_logged_in()
        if r.has(MSG_LOCKED):
            self._forget()
            raise VaultLocked("coffre verrouillé : session refusée par bw juste après le déverrouillage")
        raise self._fail(r, what)

    def lock(self) -> None:
        self._mem_session = None
        first, r = None, None
        try:
            r = self._run(["lock"])
        except BaseException as e:  # magasin vidé quand même ; la première erreur est gardée
            first = e
        try:
            self.store.clear()
        except SessionStoreError:
            if first is None:
                raise
        if first is not None:
            raise first
        if r.rc != 0 and not r.has(MSG_NOT_LOGGED_IN):
            raise self._fail(r, "lock")

    def logout(self, on_interrupt: Optional[Callable[[Optional[bool]], None]] = None) -> bool:
        """`bw logout` dans les données de ce compte, puis session oubliée (même si bw échoue ou
        si l'appel est interrompu). True : déconnecté ; False : rien à faire (bw non connecté, ou
        dossier de données absent : jamais créé ici). BackendError (bw en erreur…) : toujours
        connecté, sauf LogoutUnknown : bw sans réponse et état relu impossible. Après un délai
        dépassé, l'état est relu (délai court) : déconnecté quand même → True. Session
        impossible à oublier : avertissement si bw a répondu (bw déconnecté, elle ne sert plus) ;
        interrompu : avertissement aussi (`_interrupted_logout`) ; autre échec : l'appelant le dit.
        Interrompu (Ctrl-C, SIGTERM, SIGHUP) : bw tué, puis, signaux retenus, état relu (délai
        court), session oubliée et `on_interrupt(déconnecté ?)` appelé (True : bw déconnecté ;
        False : toujours connecté ; None : état inconnu) ; l'interruption est ensuite relevée."""
        r, first = None, None
        if os.path.isdir(self.appdata):
            try:
                r = self._run(["logout"])
            except (SystemExit, GeneratorExit):
                raise
            except BwTimeout as e:
                # bw tué : il a pu se déconnecter avant ; l'état relu (délai court) tranche
                try:
                    gone = self._bw_status(None, timeout=min(self.timeout, REREAD_TIMEOUT)).state == "unauthenticated"
                except (SystemExit, GeneratorExit):
                    raise
                except BackendError as e2:
                    first = LogoutUnknown("%s ; état relu impossible (%s)" % (e, e2))
                except BaseException as e2:  # interrompu pendant la relecture : état inconnu
                    self._interrupted_logout(on_interrupt, reread=False)
                    raise e2
                else:
                    if gone:
                        r = Result(0, "", "")
                    else:
                        e.reread_connected = True  # relu : toujours connecté (état connu)
                        first = e
            except Exception as e:  # session oubliée quand même ; l'erreur de bw est gardée
                first = e
            except BaseException:  # interrompu : bw tué (_spawn), état relu sous signaux retenus
                self._interrupted_logout(on_interrupt)
                raise
        not_logged_in = r is not None and r.rc != 0 and r.has(MSG_NOT_LOGGED_IN)
        failed = first is not None or (r is not None and r.rc != 0 and not not_logged_in)
        try:
            self.store.clear()
        except SessionStoreError as e:
            if not failed:
                self.warnings.append("session non oubliée : %s" % e)
        if first is not None:
            raise first
        if r is None or not_logged_in:
            return False
        if r.rc != 0:
            raise self._fail(r, "logout")
        return True

    def _interrupted_logout(self, on_interrupt, reread: bool = True) -> None:
        """`bw logout` interrompu (bw déjà tué) : Ctrl-C, SIGTERM, SIGHUP retenus le temps de
        relire l'état (`REREAD_TIMEOUT`), d'oublier la session et d'appeler `on_interrupt`
        (déconnecté ? None : inconnu). Un nouveau signal arrivé entre-temps est servi après."""
        from .ensure import signals_blocked
        with signals_blocked():
            gone = None
            try:
                if reread:
                    try:
                        gone = self._bw_status(None, timeout=min(self.timeout, REREAD_TIMEOUT)).state == "unauthenticated"
                    except Exception:
                        gone = None
            finally:  # session oubliée et marqueur, quoi qu'il arrive à la relecture
                try:
                    self.store.clear()
                except SessionStoreError as e:  # dit en fin de commande, après « interrompu »
                    self.warnings.append("session non oubliée : %s" % e)
                if on_interrupt is not None:
                    on_interrupt(gone)

    def sync(self, prompt: Optional[Prompt] = None) -> None:
        # commandes réseau de sshvault : sync, login, edit et create (mesuré : status, unlock, lock, list
        # et get lisent le cache local, aucune connexion)
        self._with_session(["sync"], "sync", prompt, attempts=2)

    def login(self, server: Optional[str] = None, apikey: bool = False, ttl: int = DEFAULT_TTL,
               email: Optional[str] = None) -> str:
        """Login délégué à bw en interactif (`bw login <e-mail>` : bw demande le mot de passe, et la
        2FA s'il y a lieu) ; serveur et e-mail du registre par défaut. Renvoie "unlocked" si bw a
        donné une session (rangée), sinon "locked" (clé API : il reste à faire `unlock`)."""
        server = server or self.server
        email = email or self.email
        if server:
            st = self._bw_status(None)
            # bw refuse de changer de serveur une fois connecté : le login dira « déjà connecté »
            if st.state == "unauthenticated" and (st.server or "").rstrip("/").lower() != server.rstrip("/").lower():
                r = self._run(["config", "server", server])
                if r.rc != 0:
                    raise self._fail(r, "config server")
        # « -- » : un e-mail n'est jamais lu comme une option de bw
        args = ["login", "--raw"] + (["--apikey"] if apikey else []) + (["--", email] if email and not apikey else [])
        r = self._run(args, interactive=True, timeout=LOGIN_TIMEOUT)
        if r.rc != 0:
            st = self._bw_status(None)
            if st.state == "unauthenticated":
                # causes mesurées : mot de passe, limite de débit des connexions de Vaultwarden
                # (« Rate limit exceeded. Try again later. », 2026-10-14), réseau
                raise NotLoggedIn("login refusé par bw (code %d, message ci-dessus : mot de passe refusé, limite de "
                                  "débit du serveur — réessayer dans une minute — ou réseau)" % r.rc)
            raise BackendError("erreur bw : login refusé (code %d) ; déjà connecté comme %s"
                               % (r.rc, _clean(st.user or "?")))
        token = r.out.strip()
        if valid_token(token) and not apikey:
            self._seen_connected()
            try:
                self._put_session(token, ttl)
            except SessionStoreError as e:
                # bw est connecté : on le dit, sans échouer (même règle que le déverrouillage)
                self.warnings.append("session non rangée : %s" % e)
            return "unlocked"
        # bw peut finir en code 0 sans connexion (saisie interrompue, stdin fermé) : on vérifie.
        st = self._bw_status(None)
        if st.state == "unauthenticated":
            raise NotLoggedIn("login non abouti : toujours non connecté au coffre")
        if email and (st.user or "").strip().lower() != email.strip().lower():
            # clé API d'un autre compte : ses données ne restent pas sous cet alias
            try:
                outcome = "déconnecté" if self.logout() else "déjà déconnecté"
                self.restore_marker()  # retiré quand bw a été vu connecté (à l'autre compte)
            except LogoutUnknown as e:
                self.restore_marker()
                outcome = ("bw logout sans réponse (%s) : état de connexion inconnu, données sous cet alias (%s)"
                           % (e, self.appdata))
            except BackendError:
                outcome = ("bw logout en échec : les données de %s restent sous cet alias (%s)"
                           % (_clean(st.user or "?"), self.appdata))
            raise BackendError("erreur bw : la clé API est celle de %s, pas de %s (compte %s) : %s"
                               % (_clean(st.user or "?"), _clean(email), _clean(self.label or "?"), outcome))
        if valid_token(token):
            try:
                self._put_session(token, ttl)
            except SessionStoreError as e:
                self.warnings.append("session non rangée : %s" % e)
            return "unlocked"
        return st.state

    # --- lecture ---------------------------------------------------------------

    @staticmethod
    def _item(d) -> Optional[SshKeyItem]:
        if not isinstance(d, dict) or d.get("type") != SSH_KEY_TYPE:
            return None
        key = d.get("sshKey")
        if not isinstance(key, dict):
            return None
        lists = {HOSTS_FIELD: [], FORWARD_FIELD: []}
        for f in d.get("fields") or []:
            # types 0 (texte) et 1 (masqué)
            if (isinstance(f, dict) and isinstance(f.get("name"), str) and f["name"] in lists
                    and f.get("type", 0) in (0, 1)):
                lists[f["name"]].extend(parse_hosts(f.get("value") or ""))
        return SshKeyItem(id=str(d.get("id") or ""), name=str(d.get("name") or ""),
                          public_key=str(key.get("publicKey") or ""),
                          fingerprint=str(key.get("keyFingerprint") or ""),
                          hosts=parse_hosts(",".join(lists[HOSTS_FIELD])),
                          forward=parse_hosts(",".join(lists[FORWARD_FIELD])))

    def list_ssh_keys(self, prompt: Optional[Prompt] = None) -> list:
        r = self._with_session(["list", "items"], "list items", prompt)
        data = self._json(r, "list items")
        del r  # la sortie brute contient les clés privées : pas plus loin que nécessaire
        if not isinstance(data, list):
            raise BackendError("erreur bw : « list items » n'a pas renvoyé de liste")
        items = [it for it in (self._item(d) for d in data) if it is not None]
        del data
        return sorted(items, key=lambda i: (i.name.casefold(), i.id))

    def get_item(self, item_id: str, prompt: Optional[Prompt] = None) -> dict:
        """Élément complet tel que `bw get item` le rend (cache local), clé privée comprise :
        l'appelant le garde en mémoire seulement, ne l'affiche ni ne l'écrit."""
        try:
            r = self._with_session(["get", "item", item_id], "get item", prompt)
        except BackendError as e:
            if "Not found." in str(e):
                raise ItemNotFound("élément %s absent du coffre" % item_id) from None
            raise
        d = self._json(r, "get item")
        del r
        if not isinstance(d, dict):
            raise BackendError("erreur bw : « get item » n'a pas renvoyé d'objet")
        return d

    def get_ssh_key(self, item_id: str, prompt: Optional[Prompt] = None):
        """Un seul `bw get item` (cache local) : élément et clé privée (chargement automatique)."""
        d = self.get_item(item_id, prompt)
        try:
            item = self._item(d)
            if item is None:
                raise ItemNotFound("élément %s : pas une clé SSH" % item_id)
            key = d["sshKey"].get("privateKey") or ""
            if not key:
                raise BackendError("erreur bw : élément %s sans clé privée" % item_id)
            return item, key.encode()
        finally:
            del d

    def get_private_key(self, item_id: str, prompt: Optional[Prompt] = None) -> bytes:
        d = self.get_item(item_id, prompt)
        if d.get("type") != SSH_KEY_TYPE or not isinstance(d.get("sshKey"), dict):
            raise ItemNotFound("élément %s : pas une clé SSH" % item_id)
        key = d["sshKey"].get("privateKey") or ""
        if not key:
            raise BackendError("erreur bw : élément %s sans clé privée" % item_id)
        return key.encode()

    # --- écriture --------------------------------------------------------------

    def edit_item(self, item_id: str, item: dict, prompt: Optional[Prompt] = None) -> None:
        """`bw edit item <id>` avec l'élément encodé (base64 du JSON, comme `bw encode`, mesuré
        identique) sur **stdin** : jamais en argument. Appel réseau, sans nouvel essai ici
        (une écriture n'est pas idempotente : voir set_hosts)."""
        enc = base64.b64encode(json.dumps(item).encode())
        try:
            r = self._with_session(["edit", "item", item_id], "edit item", prompt, input=enc)
        finally:
            del enc
        del r  # bw rend l'élément modifié, clé privée comprise : non gardé

    def set_hosts(self, item_id: str, hosts, prompt: Optional[Prompt] = None) -> SshKeyItem:
        return self._set_field(item_id, hosts, prompt, HOSTS_FIELD)

    def set_forward(self, item_id: str, hosts, prompt: Optional[Prompt] = None) -> SshKeyItem:
        return self._set_field(item_id, hosts, prompt, FORWARD_FIELD)

    def _set_field(self, item_id: str, hosts, prompt: Optional[Prompt], field: str) -> SshKeyItem:
        """`set_hosts` / `set_forward` : seul le champ `field` change (mêmes règles d'écriture)."""
        want = normalize_hosts(hosts)
        before = self.get_item(item_id, prompt)
        if before.get("type") != SSH_KEY_TYPE or not isinstance(before.get("sshKey"), dict):
            raise ItemNotFound("élément %s : pas une clé SSH" % item_id)
        name = _clean(str(before.get("name") or item_id))
        new = with_hosts(before, want, field)
        if new == before:
            return self._item(before)
        check = "vérifier par « %s » puis « sshvault %s list%s --id %s »" % (self.cmd("sync"), _COMMAND[field], self.hint,
                                                                       item_id)
        try:
            return self._write_hosts(item_id, name, before, new, want, prompt, check, field)
        except Exception:
            raise
        except BaseException:
            # Ctrl-C, SIGTERM… pendant bw edit ou la relecture : l'écriture a pu passer.
            self.warnings.append("%s de « %s » : écriture peut-être passée : %s" % (_WHAT[field], name, check))
            raise

    def create_item(self, item: dict, prompt: Optional[Prompt] = None) -> dict:
        """`bw create item` avec l'élément encodé (base64 du JSON) sur **stdin**, jamais en
        argument ; renvoie l'élément créé tel que bw le rend. Appel réseau, sans nouvel essai
        ici (une création n'est pas idempotente : voir create_ssh_key)."""
        r = self._with_session(["create", "item"], "create item", prompt,
                               input=base64.b64encode(json.dumps(item).encode()))
        d = self._json(r, "create item")
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"]:
            raise BackendError("erreur bw : « create item » n'a pas renvoyé d'élément avec un id")
        return d

    def _list_raw(self, prompt: Optional[Prompt]) -> list:
        r = self._with_session(["list", "items"], "list items", prompt)
        data = self._json(r, "list items")
        del r
        if not isinstance(data, list):
            raise BackendError("erreur bw : « list items » n'a pas renvoyé de liste")
        return data

    def create_ssh_key(self, name: str, private_key: str, public_key: str, fingerprint: str, hosts,
                       prompt: Optional[Prompt] = None, existing=None, extra_fields=()) -> SshKeyItem:
        """Crée l'élément, le relit et le compare (trois champs `sshKey` et hôtes).

        Échec ou blocage de `bw create` : `sync`, puis recherche par empreinte d'un élément
        absent de `existing` (ids qui portaient déjà cette empreinte ; None : lus dans le cache
        local avant la création). Trouvé : vérifié, succès. Absent : rejeu une seule fois."""
        want = normalize_hosts(hosts)
        item = new_ssh_item(name, private_key, public_key, fingerprint, want, extra_fields)
        if existing is None:
            existing = [i.id for i in self.list_ssh_keys(prompt) if i.match_fingerprint(fingerprint)]
        known = set(existing)
        label = _clean(name)
        check = "vérifier par « %s » puis « sshvault search%s --fingerprint %s »" % (self.cmd("sync"), self.hint,
                                                                                fingerprint)
        try:
            return self._create_checked(item, label, fingerprint, want, known, prompt, check)
        except BaseException as e:
            if not isinstance(e, Exception):
                # interruption (KeyboardInterrupt, Interrupted de la CLI sur SIGTERM/SIGHUP) pendant
                # bw create ou la relecture : la création a pu passer
                self.warnings.append("« %s » : création peut-être passée : %s" % (label, check))
            raise

    def _create_checked(self, item, label, fp, want, known, prompt, check) -> SshKeyItem:
        for attempt in (1, 2):
            try:
                created = self.create_item(item, prompt)
                failure = None
            except BackendError as e:  # code d'erreur, réponse illisible, délai dépassé
                failure = e
            if failure is None:
                iid = created["id"]
                del created
                try:
                    after = self.get_item(iid, prompt)
                except VaultError as e:
                    raise WriteFailed("« %s » : bw create a réussi (id %s), relecture impossible (%s) : état inconnu, "
                                      "%s" % (label, iid, e, check)) from None
                diff = _created_diff(after, item, want)
                if diff:
                    raise WriteFailed("« %s » : bw create a réussi (id %s) mais l'élément relu diffère (%s) : "
                                      "%s" % (label, iid, diff, _delete_hint(iid)))
                return self._item(after)
            # Échec ou blocage : la création a pu passer côté serveur. État réel relu (sync,
            # puis recherche par empreinte) avant tout rejeu, jamais de doublon.
            what = "« %s » : création en échec (%s)" % (label, failure)
            try:
                self._with_session(["sync"], "sync", prompt, attempts=2)
                found = [d for d in self._list_raw(prompt) if _fp_of(d) == normalize_fingerprint(fp)
                         and str(d.get("id") or "") not in known]
            except VaultError as e:
                raise WriteFailed("%s ; relecture impossible (%s) : état inconnu, %s" % (what, e, check)) from None
            if len(found) > 1:
                raise WriteFailed("%s ; %d éléments nouveaux portent cette empreinte (%s) : rien rejoué, %s"
                                  % (what, len(found), ", ".join(str(d.get("id")) for d in found), check))
            if found:
                diff = _created_diff(found[0], item, want)
                if diff:
                    raise WriteFailed("%s ; élément créé malgré l'erreur (id %s) mais différent (%s) : rien rejoué ; "
                                      "%s" % (what, found[0].get("id"), diff, _delete_hint(found[0].get("id"))))
                return self._item(found[0])  # créé malgré l'erreur : vérifié à la relecture
            if attempt == 2:
                raise WriteFailed("%s, deux fois ; état relu : élément absent du coffre" % what)
        raise AssertionError("inaccessible")

    def _write_hosts(self, item_id, name, before, new, want, prompt, check, field=HOSTS_FIELD) -> SshKeyItem:
        what = _WHAT[field]
        for attempt in (1, 2):
            try:
                self.edit_item(item_id, new, prompt)
                failure = None
            except BackendError as e:  # code d'erreur, réponse illisible, délai dépassé
                failure = e
            if failure is None:
                try:
                    after = self.get_item(item_id, prompt)
                except VaultError as e:
                    raise WriteFailed("%s de « %s » : bw edit a réussi, relecture impossible (%s) : état inconnu, "
                                      "%s" % (what, name, e, check)) from None
                if not _is_written(after, before, want, field):
                    raise WriteFailed("%s de « %s » : bw edit a réussi mais l'élément relu diffère "
                                      "(%s relus : %s)" % (what, name, what, _fmt(hosts_of(after, field))))
                return self._item(after)
            # Échec ou blocage : l'écriture a pu passer côté serveur. Relecture de l'état réel
            # (sync, puis get) avant de décider ; rejeu une seule fois, et seulement si
            # l'élément n'a pas changé.
            failed = "%s de « %s » : écriture en échec (%s)" % (what, name, failure)
            try:
                self._with_session(["sync"], "sync", prompt, attempts=2)
                after = self.get_item(item_id, prompt)
            except VaultError as e:
                raise WriteFailed("%s ; relecture impossible (%s) : état inconnu, %s" % (failed, e, check)) from None
            if _is_written(after, before, want, field):
                return self._item(after)  # écrit malgré l'erreur : vérifié à la relecture
            unchanged = (after.get("revisionDate") == before.get("revisionDate")
                         and hosts_of(after, field) == hosts_of(before, field))
            if not unchanged:
                raise WriteFailed("%s ; l'élément a changé dans le coffre (%s relus : %s) : rien rejoué ; "
                                  "lancer « %s » puis relancer la commande"
                                  % (failed, what, _fmt(hosts_of(after, field)), self.cmd("sync")))
            if attempt == 2:
                raise WriteFailed("%s, deux fois ; état relu : élément inchangé (%s : %s)"
                                  % (failed, what, _fmt(hosts_of(after, field))))
            before, new = after, with_hosts(after, want, field)
        raise AssertionError("inaccessible")


def _fmt(hosts) -> str:
    return ",".join(_clean(h) for h in hosts) or "aucun"


#: Noms des listes d'hôtes dans les messages, et commande qui les relit.
_WHAT = {HOSTS_FIELD: "hôtes", FORWARD_FIELD: "transferts"}
_COMMAND = {HOSTS_FIELD: "hosts", FORWARD_FIELD: "forward"}


def _hosts_fields(item: dict, field: str = HOSTS_FIELD) -> list:
    return [f for f in (item.get("fields") or [])
            if isinstance(f, dict) and f.get("name") == field and f.get("type", 0) in (0, 1)]


def hosts_of(item: dict, field: str = HOSTS_FIELD) -> tuple:
    """Hôtes de l'élément (tous les champs `field` texte ou masqués, `sshvault-hosts` par
    défaut), en minuscules."""
    return tuple(h.lower() for h in parse_hosts(",".join(f.get("value") or "" for f in _hosts_fields(item, field))))


def _others(item: dict, field: str = HOSTS_FIELD) -> tuple:
    """Ce qu'une écriture du champ `field` ne doit pas changer : nom, notes, clé, autres champs
    (l'autre liste d'hôtes comprise). null et "" sont confondus (bw peut rendre l'un pour l'autre)."""
    def v(x):
        return "" if x is None else x
    mine = _hosts_fields(item, field)
    fields = [(v(f.get("name")), v(f.get("value")), f.get("type")) if isinstance(f, dict) else f
              for f in (item.get("fields") or []) if not (isinstance(f, dict) and f in mine)]
    key = item.get("sshKey") or {}
    return (item.get("type"), v(item.get("name")), v(item.get("notes")), fields,
            v(key.get("privateKey")), v(key.get("publicKey")), v(key.get("keyFingerprint")))


def _is_written(after: dict, before: dict, want: tuple, field: str = HOSTS_FIELD) -> bool:
    return hosts_of(after, field) == tuple(want) and _others(after, field) == _others(before, field)


def new_ssh_item(name: str, private_key: str, public_key: str, fingerprint: str, hosts: tuple,
                 extra_fields=()) -> dict:
    """Élément « SSH key » à créer, sur le modèle de `bw get template item` (2026.9.1) :
    les trois champs `sshKey` remplis ; `sshvault-hosts` s'il y a des hôtes ; champs texte en plus."""
    fields = []
    if hosts:
        fields.append({"name": HOSTS_FIELD, "value": ",".join(hosts), "type": 0, "linkedId": None})
    fields += [{"name": n, "value": v, "type": 0, "linkedId": None} for n, v in extra_fields]
    return {"passwordHistory": [], "revisionDate": None, "creationDate": None, "deletedDate": None,
            "organizationId": None, "collectionIds": None, "folderId": None, "type": SSH_KEY_TYPE,
            "name": name, "notes": None, "favorite": False, "fields": fields, "login": None,
            "secureNote": None, "card": None, "identity": None,
            "sshKey": {"privateKey": private_key, "publicKey": public_key, "keyFingerprint": fingerprint},
            "reprompt": 0}


def _delete_hint(iid) -> str:
    return ("supprimer l'élément %s (interface web) avant de relancer la commande, sinon il sera vu comme "
            "doublon (ou relancer avec --force)" % iid)


def _fp_of(item) -> Optional[str]:
    if not isinstance(item, dict) or item.get("type") != SSH_KEY_TYPE or not isinstance(item.get("sshKey"), dict):
        return None
    return normalize_fingerprint(str(item["sshKey"].get("keyFingerprint") or ""))


def _created_diff(after: dict, item: dict, want: tuple) -> str:
    """Ce qui diffère entre l'élément relu et celui demandé (les trois champs `sshKey`, hôtes) ;
    "" si rien. Jamais la valeur d'un champ de clé dans le message."""
    if after.get("type") != SSH_KEY_TYPE or not isinstance(after.get("sshKey"), dict):
        return "pas une clé SSH"
    bad = [k for k in ("privateKey", "publicKey", "keyFingerprint")
           if (after["sshKey"].get(k) or "") != item["sshKey"][k]]
    if hosts_of(after) != tuple(want):
        bad.append("hôtes relus : %s" % _fmt(hosts_of(after)))
    return ", ".join(bad)


def with_hosts(item: dict, hosts: tuple, field: str = HOSTS_FIELD) -> dict:
    """Copie de l'élément où seul le champ `field` (`sshvault-hosts` par défaut, ou
    `sshvault-forward`) change : valeur remplacée (premier champ texte ou masqué de ce nom, type
    gardé ; les autres de ce nom fusionnés), créé s'il manque, retiré si `hosts` est vide. Tout
    le reste tel que bw l'a rendu (revisionDate compris). `fields` reste une liste, vide au
    besoin : bw garde les anciens champs si `fields` est null."""
    value = ",".join(hosts)
    new = copy.deepcopy(item)
    old = item.get("fields") or []
    out, placed = [], False
    for f in old:
        if isinstance(f, dict) and f.get("name") == field and f.get("type", 0) in (0, 1):
            if placed or not hosts:
                continue
            f = copy.deepcopy(f)
            f["value"] = value
            placed = True
        else:
            f = copy.deepcopy(f)
        out.append(f)
    if hosts and not placed:
        out.append({"name": field, "value": value, "type": 0, "linkedId": None})
    if out != old:
        new["fields"] = out
    return new

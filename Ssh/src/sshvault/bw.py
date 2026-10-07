"""`BwBackend` : le coffre via le CLI officiel `bw`, en sous-processus.

- Exécutable : `SSHVAULT_BW` (défaut `bw`, cherché dans le PATH).
- Données propres à sshvault, login séparé de l'usage personnel de bw :
  `BITWARDENCLI_APPDATA_DIR=${XDG_DATA_HOME:-~/.local/share}/sshvault/bw`,
  donc un login séparé de l'usage personnel de `bw`.
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
import json
import os
import re
import signal
import subprocess
import termios
from typing import Optional

from .backend import (HOSTS_FIELD, BackendError, BackendNotFound, ItemNotFound, NotLoggedIn,
                      Prompt, SshKeyItem, VaultBackend, VaultError, VaultLocked, VaultStatus, WriteFailed,
                      normalize_hosts, parse_hosts)
from .fsutil import ensure_dir
from .settings import seconds
from .session import DEFAULT_TTL, SessionStore, SessionStoreError, valid_token

DEFAULT_TIMEOUT = 60.0
LOGIN_TIMEOUT = 600.0  # login interactif (saisie, 2FA)
SSH_KEY_TYPE = 5
PASSWORD_VAR = "SSHVAULT_BW_MASTER_PASSWORD"
INSTALL_HINT = ("installer le binaire natif dans ~/.local/bin "
                "(https://bitwarden.com/download/?app=cli&platform=linux) ou définir SSHVAULT_BW")
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
    env = os.environ if env is None else env
    base = env.get("XDG_DATA_HOME") or ""
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "sshvault", "bw")


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
                 appdata: Optional[str] = None, timeout: Optional[float] = None):
        self.store = store or SessionStore()
        self.exe = exe or os.environ.get("SSHVAULT_BW") or "bw"
        self.appdata = appdata or default_appdata()
        self.timeout = timeout if timeout is not None else bw_timeout()
        self.calls = 0  # nombre d'appels à bw (mesure du coût : ~1,4 s chacun)
        self.warnings: list = []  # avertissements d'une ligne pour l'utilisateur

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
        argv = [self.exe] + ([] if interactive else ["--nointeraction"]) + args
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
            raise BackendNotFound("bw introuvable (%s) : %s" % (self.exe, INSTALL_HINT)) from None
        except PermissionError:
            raise BackendNotFound("bw non exécutable (%s) : %s" % (self.exe, INSTALL_HINT)) from None
        except OSError as e:
            raise BackendError("erreur bw : lancement de %s : %s" % (self.exe, e.strerror or e)) from None
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

    def _forget(self) -> None:
        """La session rangée a été refusée par bw (expirée, invalidée) : on la purge."""
        try:
            self.store.clear()
        except SessionStoreError:
            pass

    def _bw_status(self, session: Optional[str]) -> VaultStatus:
        r = self._run(["status"], session=session)
        if r.rc != 0:
            raise self._fail(r, "status")
        d = self._json(r, "status")
        state = d.get("status") if isinstance(d, dict) else None
        if state not in ("unauthenticated", "locked", "unlocked"):
            raise BackendError("erreur bw : état inconnu dans « status » : %r" % (state,))
        return VaultStatus(state, d.get("serverUrl"), d.get("userEmail"), d.get("lastSync"))

    def status(self) -> VaultStatus:
        session = self.store.get()
        st = self._bw_status(session)
        if session and st.state != "unlocked":
            self._forget()
        return st

    def _unlock_with(self, prompt: Optional[Prompt], ttl: int, known_logged_in: bool,
                     must_store: bool = False) -> str:
        if not known_logged_in:
            st = self._bw_status(None)
            if st.state == "unauthenticated":
                raise NotLoggedIn("non connecté au coffre : lancer « sshvault login »")
            if st.state == "unlocked":
                return ""  # déverrouillé sans session (bw configuré sans verrouillage)
            who = st.user or "?"
        else:
            who = None
        if prompt is None:
            raise VaultLocked("coffre verrouillé : lancer « sshvault unlock » (invite désactivée)")
        password = prompt("sshvault : mot de passe maître du coffre%s : " % (" (%s)" % who if who else ""))
        try:
            r = self._run(["unlock", "--passwordenv", PASSWORD_VAR, "--raw"],
                          extra_env={PASSWORD_VAR: password})
        finally:
            del password
        if r.rc != 0:
            if r.has(MSG_NOT_LOGGED_IN):
                raise NotLoggedIn("non connecté au coffre : lancer « sshvault login »")
            # unlock est local : un refus est presque toujours le mot de passe (mesuré :
            # « Cryptography error, The decryption operation failed », code 1).
            raise VaultLocked("mot de passe maître refusé par bw (%s)" % (last_line(r.err) or "code %d" % r.rc))
        token = r.out.strip()
        if not valid_token(token):
            raise BackendError("erreur bw : « unlock » n'a pas renvoyé de session")
        try:
            self.store.put(token, ttl)
        except SessionStoreError as e:
            if must_store:
                raise
            # La session sert à l'opération en cours, sans être gardée pour la suivante.
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
                raise NotLoggedIn("non connecté au coffre : lancer « sshvault login »")
            self._unlock_with(prompt, ttl, known_logged_in=True, must_store=True)
            return
        self._unlock_with(prompt, ttl, known_logged_in=False, must_store=True)

    def _with_session(self, args: list, what: str, prompt: Optional[Prompt], attempts: int = 1,
                      input: Optional[bytes] = None) -> Result:
        """Lance `bw args` avec la session rangée ; un seul appel si elle est valide.
        Session refusée : purge, puis traité comme verrouillé (invite, unlock, nouvel essai :
        « Vault is locked. » dit que bw n'a rien fait)."""
        session = self.store.get()
        known_logged_in = False
        if session:
            r = self._run_retry(args, attempts, session=session, input=input)
            if r.rc == 0:
                return r
            if r.has(MSG_NOT_LOGGED_IN):
                self._forget()
                raise NotLoggedIn("non connecté au coffre : lancer « sshvault login »")
            if not r.has(MSG_LOCKED):
                raise self._fail(r, what)
            self._forget()
            known_logged_in = True
        session = self._unlock_with(prompt, DEFAULT_TTL, known_logged_in)
        r = self._run_retry(args, attempts, session=session or None, input=input)
        if r.rc == 0:
            return r
        if r.has(MSG_NOT_LOGGED_IN):
            raise NotLoggedIn("non connecté au coffre : lancer « sshvault login »")
        if r.has(MSG_LOCKED):
            self._forget()
            raise VaultLocked("coffre verrouillé : session refusée par bw juste après le déverrouillage")
        raise self._fail(r, what)

    def lock(self) -> None:
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

    def sync(self, prompt: Optional[Prompt] = None) -> None:
        # commandes réseau de sshvault : sync, login et edit (mesuré : status, unlock, lock, list
        # et get lisent le cache local, aucune connexion)
        self._with_session(["sync"], "sync", prompt, attempts=2)

    def login(self, server: Optional[str] = None, apikey: bool = False, ttl: int = DEFAULT_TTL) -> str:
        """Login délégué à bw en interactif. Renvoie "unlocked" si bw a donné une session
        (rangée), sinon "locked" (clé API : il reste à faire `unlock`)."""
        if server:
            r = self._run(["config", "server", server])
            if r.rc != 0:
                raise self._fail(r, "config server")
        args = ["login", "--raw"] + (["--apikey"] if apikey else [])
        r = self._run(args, interactive=True, timeout=LOGIN_TIMEOUT)
        if r.rc != 0:
            st = self._bw_status(None)
            if st.state == "unauthenticated":
                raise NotLoggedIn("login refusé par bw (code %d, message ci-dessus)" % r.rc)
            raise BackendError("erreur bw : login refusé (code %d) ; déjà connecté comme %s"
                               % (r.rc, st.user or "?"))
        token = r.out.strip()
        if valid_token(token):
            try:
                self.store.put(token, ttl)
            except SessionStoreError as e:
                # bw est connecté : on le dit, sans échouer (même règle que le déverrouillage)
                self.warnings.append("session non rangée : %s" % e)
            return "unlocked"
        # bw peut finir en code 0 sans connexion (saisie interrompue, stdin fermé) : on vérifie.
        st = self._bw_status(None)
        if st.state == "unauthenticated":
            raise NotLoggedIn("login non abouti : toujours non connecté au coffre")
        return st.state

    # --- lecture ---------------------------------------------------------------

    @staticmethod
    def _item(d) -> Optional[SshKeyItem]:
        if not isinstance(d, dict) or d.get("type") != SSH_KEY_TYPE:
            return None
        key = d.get("sshKey")
        if not isinstance(key, dict):
            return None
        hosts = []
        for f in d.get("fields") or []:
            # types 0 (texte) et 1 (masqué)
            if isinstance(f, dict) and f.get("name") == HOSTS_FIELD and f.get("type", 0) in (0, 1):
                hosts.extend(parse_hosts(f.get("value") or ""))
        return SshKeyItem(id=str(d.get("id") or ""), name=str(d.get("name") or ""),
                          public_key=str(key.get("publicKey") or ""),
                          fingerprint=str(key.get("keyFingerprint") or ""),
                          hosts=parse_hosts(",".join(hosts)))

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
        want = normalize_hosts(hosts)
        before = self.get_item(item_id, prompt)
        if before.get("type") != SSH_KEY_TYPE or not isinstance(before.get("sshKey"), dict):
            raise ItemNotFound("élément %s : pas une clé SSH" % item_id)
        name = _clean(str(before.get("name") or item_id))
        new = with_hosts(before, want)
        if new == before:
            return self._item(before)
        check = "vérifier par « sshvault sync » puis « sshvault hosts list --id %s »" % item_id
        try:
            return self._write_hosts(item_id, name, before, new, want, prompt, check)
        except Exception:
            raise
        except BaseException:
            # Ctrl-C, SIGTERM… pendant bw edit ou la relecture : l'écriture a pu passer.
            self.warnings.append("hôtes de « %s » : écriture peut-être passée : %s" % (name, check))
            raise

    def _write_hosts(self, item_id, name, before, new, want, prompt, check) -> SshKeyItem:
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
                    raise WriteFailed("hôtes de « %s » : bw edit a réussi, relecture impossible (%s) : état inconnu, "
                                      "%s" % (name, e, check)) from None
                if not _is_written(after, before, want):
                    raise WriteFailed("hôtes de « %s » : bw edit a réussi mais l'élément relu diffère "
                                      "(hôtes relus : %s)" % (name, _fmt(hosts_of(after))))
                return self._item(after)
            # Échec ou blocage : l'écriture a pu passer côté serveur. Relecture de l'état réel
            # (sync, puis get) avant de décider ; rejeu une seule fois, et seulement si
            # l'élément n'a pas changé.
            what = "hôtes de « %s » : écriture en échec (%s)" % (name, failure)
            try:
                self._with_session(["sync"], "sync", prompt, attempts=2)
                after = self.get_item(item_id, prompt)
            except VaultError as e:
                raise WriteFailed("%s ; relecture impossible (%s) : état inconnu, %s" % (what, e, check)) from None
            if _is_written(after, before, want):
                return self._item(after)  # écrit malgré l'erreur : vérifié à la relecture
            unchanged = (after.get("revisionDate") == before.get("revisionDate")
                         and hosts_of(after) == hosts_of(before))
            if not unchanged:
                raise WriteFailed("%s ; l'élément a changé dans le coffre (hôtes relus : %s) : rien rejoué ; "
                                  "lancer « sshvault sync » puis relancer la commande" % (what, _fmt(hosts_of(after))))
            if attempt == 2:
                raise WriteFailed("%s, deux fois ; état relu : élément inchangé (hôtes : %s)"
                                  % (what, _fmt(hosts_of(after))))
            before, new = after, with_hosts(after, want)
        raise AssertionError("inaccessible")


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _clean(text: str) -> str:
    return _CONTROL.sub(lambda m: "\\x%02x" % ord(m.group()), text)


def _fmt(hosts) -> str:
    return ",".join(_clean(h) for h in hosts) or "aucun"


def _hosts_fields(item: dict) -> list:
    return [f for f in (item.get("fields") or [])
            if isinstance(f, dict) and f.get("name") == HOSTS_FIELD and f.get("type", 0) in (0, 1)]


def hosts_of(item: dict) -> tuple:
    """Hôtes de l'élément (tous les champs `sshvault-hosts` texte ou masqués), en minuscules."""
    return tuple(h.lower() for h in parse_hosts(",".join(f.get("value") or "" for f in _hosts_fields(item))))


def _others(item: dict) -> tuple:
    """Ce qu'une écriture des hôtes ne doit pas changer : nom, notes, clé, autres champs.
    null et "" sont confondus (bw peut rendre l'un pour l'autre)."""
    def v(x):
        return "" if x is None else x
    fields = [(v(f.get("name")), v(f.get("value")), f.get("type")) if isinstance(f, dict) else f
              for f in (item.get("fields") or []) if not (isinstance(f, dict) and f in _hosts_fields(item))]
    key = item.get("sshKey") or {}
    return (item.get("type"), v(item.get("name")), v(item.get("notes")), fields,
            v(key.get("privateKey")), v(key.get("publicKey")), v(key.get("keyFingerprint")))


def _is_written(after: dict, before: dict, want: tuple) -> bool:
    return hosts_of(after) == tuple(want) and _others(after) == _others(before)


def with_hosts(item: dict, hosts: tuple) -> dict:
    """Copie de l'élément où seul le champ `sshvault-hosts` change : valeur remplacée (premier
    champ texte ou masqué de ce nom, type gardé ; les autres de ce nom fusionnés), créé s'il
    manque, retiré si `hosts` est vide. Tout le reste tel que bw l'a rendu (revisionDate compris).
    `fields` reste une liste, vide au besoin : bw garde les anciens champs si `fields` est null."""
    value = ",".join(hosts)
    new = copy.deepcopy(item)
    old = item.get("fields") or []
    out, placed = [], False
    for f in old:
        if isinstance(f, dict) and f.get("name") == HOSTS_FIELD and f.get("type", 0) in (0, 1):
            if placed or not hosts:
                continue
            f = copy.deepcopy(f)
            f["value"] = value
            placed = True
        else:
            f = copy.deepcopy(f)
        out.append(f)
    if hosts and not placed:
        out.append({"name": HOSTS_FIELD, "value": value, "type": 0, "linkedId": None})
    if out != old:
        new["fields"] = out
    return new

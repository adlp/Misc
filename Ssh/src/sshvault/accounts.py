"""Comptes du coffre (CAP-10) : registre `config.json` → un `BwBackend` et une session par compte.

- Compte = alias choisi par l'utilisateur → serveur + e-mail ; données de bw propres
  (`${XDG_DATA_HOME:-~/.local/share}/sshvault/accounts/<alias>/bw`), session propre (clé keyring
  `sshvault:session:<alias>`, repli `$XDG_RUNTIME_DIR/sshvault/sessions/<alias>`). `bw-path`
  reste commun.
- Comptes par défaut : périmètre des lectures sans `--account` ; une écriture vise un seul
  compte (le défaut s'il est unique, sinon `--account` obligatoire).
- Installation 0.8.0 (un seul compte, données dans `sshvault/bw`) : adoptée au premier
  lancement (`adopt_legacy`) : alias déduit de l'e-mail du compte connecté, données déplacées
  sous `accounts/<alias>/`, compte par défaut, une ligne le dit ; l'ancienne session est
  oubliée (déverrouillage à refaire). Déplacement impossible : rien modifié, code 4.
"""
from __future__ import annotations

import fcntl
import os
from dataclasses import replace
from typing import Callable, Optional

from .backend import VaultError
from .bw import BwBackend, account_appdata, data_root, default_appdata
from .config import (ACCOUNTS, DEFAULT_ACCOUNTS, DEFAULT_SERVER, Config, ConfigError, alias_from_email,
                     normalize_email, normalize_server)
from .fsutil import ensure_dir
from .session import SessionStore, SessionStoreError
from .text import clean


class AccountError(Exception):
    """Compte inconnu, absent ou ambigu (code 2), message d'une ligne."""


class NoAccount(VaultError):
    """Aucun compte enregistré (code 3, comme « non connecté »)."""


class AdoptError(Exception):
    """Adoption de l'installation 0.8.0 impossible (code 4) : rien modifié."""


class AccountIOError(Exception):
    """Données locales d'un compte impossibles à déplacer ou supprimer, ou agents en erreur
    (account rename, account remove ; code 4), message d'une ligne."""


#: Cause de la dernière adoption remise dans ce processus (bw illisible), pour les messages.
DEFERRED: list = []


def legacy_pending(cfg: Config) -> Optional[str]:
    """Dossier de l'installation 0.8.0 pas encore adoptée (registre absent), ou None."""
    try:
        if cfg.has_registry():
            return None
    except ConfigError:
        return None
    d = default_appdata()
    return d if os.path.isdir(d) else None


def pending_message(cfg: Config, what: str) -> Optional[str]:
    """« installation 0.8.0 pas encore adoptée (<dossier>) : <cause> ; … » si elle attend, sinon None."""
    d = legacy_pending(cfg)
    if d is None:
        return None
    return ("installation 0.8.0 pas encore adoptée (%s)%s : %s ; corriger bw (« sshvault config set bw-path … » ou "
            "PATH) puis relancer une commande" % (d, " : " + DEFERRED[-1] if DEFERRED else "", what))


ADD_HINT = "« sshvault account add ALIAS --server URL --email E »"


def tag(alias: str, items) -> list:
    """Éléments du compte `alias` (champ `account` posé)."""
    return [replace(i, account=alias) for i in items]


class Accounts:
    """Registre lu une fois par commande, et un backend par compte (créé à la demande)."""

    def __init__(self, cfg: Optional[Config] = None, bw_path: Optional[Callable] = None,
                 warn: Optional[Callable[[str], None]] = None):
        self.cfg = cfg or Config()
        self._registry = self._defaults = None
        self._bw_path, self._warn = bw_path, warn
        self._backends: dict = {}

    @property
    def registry(self) -> dict:
        """Lu à la première demande : une commande qui ne vise aucun compte (config, agent) ne le
        lit pas."""
        if self._registry is None:
            self._registry = self.cfg.accounts()
        return self._registry

    @property
    def defaults(self) -> list:
        if self._defaults is None:
            self._defaults = self.cfg.default_accounts()
        return self._defaults

    @property
    def multi(self) -> bool:
        return len(self.registry) > 1

    def hint(self, alias: Optional[str]) -> str:
        """` --account <alias>` pour une commande suggérée, s'il y a plusieurs comptes."""
        return " --account %s" % alias if alias and self.multi else ""

    def prefix(self, alias: Optional[str]) -> str:
        """`<alias> : ` en tête d'un message, s'il y a plusieurs comptes."""
        return "%s : " % alias if alias and self.multi else ""

    def check(self, alias: str) -> str:
        if alias not in self.registry:
            if not self.registry:
                raise AccountError("compte « %s » inconnu : aucun compte enregistré (%s)" % (clean(alias), ADD_HINT))
            raise AccountError("compte « %s » inconnu (comptes : %s)" % (clean(alias), ", ".join(self.registry)))
        return alias

    def backend(self, alias: str) -> BwBackend:
        self.check(alias)
        b = self._backends.get(alias)
        if b is None:
            reg = self.registry[alias]
            b = self._backends[alias] = BwBackend(
                store=SessionStore(alias=alias), appdata=account_appdata(alias), bw_path=self._bw_path,
                warn=self._warn, label=alias, email=reg["email"], server=reg["server"], hint=self.hint(alias))
        return b

    def backends(self) -> list:
        """[(alias, backend)] créés pendant la commande (avertissements de fin)."""
        return list(self._backends.items())

    def need_some(self) -> None:
        if not self.registry:
            pending = pending_message(self.cfg, "aucun compte utilisable pour l'instant")
            raise NoAccount(pending or "aucun compte du coffre : %s, puis « sshvault login »" % ADD_HINT)

    def read_set(self, given=None) -> list:
        """Comptes d'une lecture : `--account` (une ou plusieurs fois), sinon les comptes par défaut."""
        self.need_some()
        if given:
            out = []
            for a in given:
                if self.check(a) not in out:
                    out.append(a)
            return out
        if not self.defaults:
            raise AccountError("aucun compte par défaut : préciser --account ALIAS ou « sshvault account default "
                               "ALIAS… » (comptes : %s)" % ", ".join(self.registry))
        return list(self.defaults)

    def write_one(self, given=None, what: str = "écriture") -> str:
        """Compte d'une écriture : `--account`, sinon le seul compte par défaut."""
        self.need_some()
        if given:
            if len(set(given)) > 1:
                raise AccountError("%s : un seul compte (--account une fois)" % what)
            return self.check(given[0])
        if len(self.defaults) == 1:
            return self.defaults[0]
        if not self.defaults:
            raise AccountError("%s : préciser --account ALIAS (aucun compte par défaut ; comptes : %s)"
                               % (what, ", ".join(self.registry)))
        raise AccountError("%s : préciser --account ALIAS (plusieurs comptes par défaut : %s)"
                           % (what, ", ".join(self.defaults)))

    def all(self, given=None) -> list:
        """Comptes de `status` et `lock` sans `--account` : tous."""
        if given:
            return self.read_set(given)
        return list(self.registry)


# --- adoption de l'installation 0.8.0 ------------------------------------------------------

def adopt_legacy(cfg: Config, notify: Callable[[str], None], bw_path: Optional[Callable] = None,
                 warn: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """Installation 0.8.0 (registre absent, `sshvault/bw` présent) : adoptée. Renvoie l'alias
    créé, ou None (rien à adopter). bw illisible (absent, en erreur) : avertissement, rien
    modifié, retenté au lancement suivant. Déplacement impossible : AdoptError, rien modifié."""
    legacy = default_appdata()
    try:
        if cfg.has_registry() or not os.path.isdir(legacy):
            return None
    except ConfigError:
        return None  # config.json invalide : la commande le dira elle-même
    root = data_root()
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as e:
        raise AdoptError("adoption de l'installation 0.8.0 : %s : %s" % (root, e.strerror or e)) from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if cfg.has_registry() or not os.path.isdir(legacy):
            return None  # adoptée par un autre processus pendant l'attente
        try:
            st = BwBackend(store=SessionStore(), appdata=legacy, bw_path=bw_path, warn=warn).status()
        except (VaultError, ConfigError) as e:  # bw absent, bw-path invalide… : `config set` doit rester possible
            DEFERRED.append(str(e))
            notify("avertissement : installation 0.8.0 non adoptée (%s) : retenté au prochain lancement" % e)
            return None
        if st.state == "unauthenticated":
            # rien à reprendre : registre créé vide, l'ancien dossier reste tel quel
            cfg.update(lambda d: d.setdefault(ACCOUNTS, {}))
            return None
        try:
            email = normalize_email(st.user or "")
            server = normalize_server(st.server or DEFAULT_SERVER)
        except ConfigError as e:
            raise AdoptError("adoption de l'installation 0.8.0 impossible (%s) : rien modifié" % e) from None
        alias = alias_from_email(email)
        dest = account_appdata(alias)
        parent = os.path.dirname(dest)
        if os.path.lexists(dest) or os.path.lexists(parent):
            raise AdoptError("adoption de l'installation 0.8.0 impossible : %s existe déjà : rien modifié" % parent)
        created = []
        try:
            d = parent
            while not os.path.isdir(d):
                created.append(d)
                d = os.path.dirname(d)
            ensure_dir(parent)
            os.rename(legacy, dest)
        except OSError as e:
            for c in created:  # rien modifié : dossiers créés retirés
                try:
                    os.rmdir(c)
                except OSError:
                    pass
            raise AdoptError("adoption de l'installation 0.8.0 : déplacement de %s vers %s impossible (%s) : "
                             "rien modifié" % (legacy, dest, e.strerror or e)) from None
        try:
            def reg(d):
                d[ACCOUNTS] = {alias: {"server": server, "email": email}}
                d[DEFAULT_ACCOUNTS] = [alias]
            cfg.update(reg)
        except BaseException:
            try:
                os.rename(dest, legacy)
                for c in created:
                    os.rmdir(c)
            except OSError:
                pass
            raise
        try:
            SessionStore().clear()  # session de la 0.8.0 : un déverrouillage est à refaire
        except SessionStoreError:
            pass
        notify("installation 0.8.0 adoptée : compte « %s » (%s, %s), compte par défaut ; données dans %s ; "
               "déverrouillage à refaire (« sshvault unlock ») ; renommer : « sshvault account rename %s NOUVEAU »"
               % (alias, clean(email), clean(server), dest, alias))
        return alias
    finally:
        os.close(fd)

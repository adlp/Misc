"""Réglages de l'utilisateur : `${XDG_CONFIG_HOME:-~/.config}/sshvault/config.json`.

Fichier 0600 dans un dossier 0700, sans aucun secret. Clés :
  - `key-ttl` : durée de vie par défaut d'une clé chargée dans l'agent dédié (`load` et
    chargement automatique), en secondes, 0 = illimitée ; défaut 1 h ;
  - `auto-load` : le `ssh_config` généré charge la clé à la connexion (`Match … exec
    "sshvault ensure"`) ; défaut `true` ; `false` = config de la 0.3.0 ;
  - `auto-restrict`, `auto-confirm` : le chargement automatique ajoute `ssh-add -h`
    (hôtes de l'élément) ou `-c` ; défaut `false` ;
  - `forward-confirm` : les clés des sous-agents de transfert (CAP-8) sont chargées avec
    `ssh-add -c` (confirmation à chaque usage, par l'askpass de l'agent) ; défaut `true` ;
  - `bw-path` : chemin absolu de l'exécutable `bw`, commun à tous les comptes ; défaut : `bw` cherché dans le PATH
    (`SSHVAULT_BW` reste prioritaire). Vérifié à `set` : absolu, sans caractère de contrôle,
    fichier ordinaire exécutable par l'utilisateur (`fsutil.exe_problem`) ; fichier ou dossier
    (lien suivi) à un autre utilisateur que lui ou root, ou modifiable par le groupe ou les
    autres (dossiers parents et liens compris) : accepté avec un avertissement
    (`fsutil.exposure_warning`) ; à la lecture : chaîne absolue sans caractère de contrôle.

Registre des comptes du coffre (CAP-10), hors de `config get/set` : changé par `sshvault
account …` seulement :
  - `accounts` : {alias : {"server": URL normalisée, "email": e-mail en minuscules}} ; alias
    `[a-z0-9][a-z0-9_-]{0,31}`, unique ; couple (serveur, e-mail) unique ;
  - `default-accounts` : alias des comptes par défaut (lecture sans `--account`), dans l'ordre.
    Liste vide (ou absente) et un seul compte : ce compte.

Durées acceptées : `N`, `Ns`, `Nm`, `Nh`, `Nd` (N entier), entre 1 s et 30 j, ou `0`
(illimitée). Booléens : `true`/`false` (aussi `yes`/`no`, `on`/`off`, `1`/`0`). Toute
valeur invalide lève ConfigError (code de sortie 2).
"""
from __future__ import annotations

import json
import os
import re
from typing import Mapping, Optional

import contextlib
import fcntl
from urllib.parse import urlsplit

from .fsutil import ensure_dir, exe_problem, read_private, write_private
from .runtime import ALIAS_RE
from .text import CONTROL_RE, clean

DEFAULT_KEY_TTL = 3600
MAX_DURATION = 30 * 86400
BW_PATH = "bw-path"
DEFAULTS = {"key-ttl": DEFAULT_KEY_TTL, "auto-load": True, "auto-restrict": False, "auto-confirm": False,
            "forward-confirm": True, BW_PATH: None}
KEYS = tuple(DEFAULTS)
BOOL_KEYS = ("auto-load", "auto-restrict", "auto-confirm", "forward-confirm")
PATH_KEYS = (BW_PATH,)
_TRUE, _FALSE = ("true", "yes", "on", "1"), ("false", "no", "off", "0")
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION_RE = re.compile(r"(\d{1,12})([smhd]?)")
ACCOUNTS = "accounts"
DEFAULT_ACCOUNTS = "default-accounts"
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+")
#: Serveur pris pour un compte que bw ne rattache à aucun serveur (cloud Bitwarden par défaut).
DEFAULT_SERVER = "https://vault.bitwarden.com"


class ConfigError(Exception):
    """Durée, clé ou fichier de configuration invalide (message d'une ligne)."""


class ConfigWriteError(ConfigError):
    """Écriture du fichier de configuration impossible (code 4, pas une erreur d'usage)."""


def parse_duration(text: str) -> int:
    """`90`, `90s`, `15m`, `2h`, `7d` → secondes ; `0` → 0 (illimitée)."""
    m = _DURATION_RE.fullmatch((text or "").strip())
    if m:
        v = int(m.group(1)) * _UNITS[m.group(2)]
        if v == 0 or 1 <= v <= MAX_DURATION:
            return v
    raise ConfigError("durée invalide : %r (N, Ns, Nm, Nh ou Nd, entre 1s et 30d ; 0 = illimitée)" % (text,))


def parse_bool(text: str) -> bool:
    t = (text or "").strip().lower()
    if t in _TRUE:
        return True
    if t in _FALSE:
        return False
    raise ConfigError("booléen invalide : %r (true ou false)" % (text,))


def check_alias(alias: str) -> str:
    """Alias de compte valide (rendu tel quel), sinon ConfigError (code 2)."""
    if not isinstance(alias, str) or not ALIAS_RE.fullmatch(alias):
        raise ConfigError("alias invalide : %s (minuscules, chiffres, « - », « _ », 32 caractères au plus, "
                          "commençant par une lettre ou un chiffre)" % show_value(alias))
    return alias


def normalize_server(url: str) -> str:
    """URL du serveur : `http(s)://hôte[:port][/chemin]`, schéma et hôte en minuscules, sans `/`
    final ni port par défaut (:443 en https, :80 en http) ; ni identifiants, ni requête, ni
    fragment, ni espace ou caractère de contrôle."""
    u = (url or "").strip()
    bad = ConfigError("serveur invalide : %s (URL https://hôte[:port][/chemin] attendue)" % show_value(url))
    if not u or CONTROL_RE.search(u) or any(c.isspace() for c in u):
        raise bad
    try:
        p = urlsplit(u)
        p.port  # port invalide : ValueError
    except ValueError:
        raise bad from None
    if p.scheme.lower() not in ("http", "https") or not p.hostname or "@" in p.netloc or p.query or p.fragment \
            or "\\" in u or '"' in u or "'" in u:
        raise bad
    scheme = p.scheme.lower()
    host = p.hostname  # en minuscules, sans crochets IPv6
    netloc = "[%s]" % host if ":" in host else host
    if p.port is not None and p.port != {"https": 443, "http": 80}[scheme]:
        netloc += ":%d" % p.port  # `:0443` → 443 (port par défaut retiré), `hôte:` → hôte
    return "%s://%s%s" % (scheme, netloc, p.path.rstrip("/"))


def normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    # « - » en tête : bw le lirait comme une option
    if not _EMAIL_RE.fullmatch(e) or CONTROL_RE.search(e) or len(e) > 254 or e.startswith("-"):
        raise ConfigError("e-mail invalide : %s" % show_value(email))
    return e


def alias_from_email(email: str) -> str:
    """Alias déduit d'un e-mail (installation adoptée) : partie avant `@`, en minuscules, chaque
    suite de caractères non permis remplacée par `-`, ni `-` ni `_` en tête, 32 caractères au
    plus ; « compte » si rien ne reste."""
    local = (email or "").split("@", 1)[0].lower()
    a = re.sub(r"[^a-z0-9_-]+", "-", local).lstrip("-_")[:32].rstrip("-") or "compte"
    return a if ALIAS_RE.fullmatch(a) else "compte"


def path_value_problem(v) -> Optional[str]:
    """Raison pour laquelle `v` n'est pas un chemin enregistrable (chaîne absolue sans caractère
    de contrôle), ou None."""
    if not isinstance(v, str):
        return "chemin absolu attendu"
    if CONTROL_RE.search(v):
        return "caractère de contrôle"
    if not os.path.isabs(v):
        return "chemin absolu attendu"
    return None


def show_value(v) -> str:
    """Valeur pour un message : « chemin nettoyé » pour une chaîne, sinon sa forme JSON."""
    if isinstance(v, str):
        return "« %s »" % clean(v)
    return clean(json.dumps(v, ensure_ascii=False))


def parse_exe_path(text: str, key: str = BW_PATH) -> str:
    """Chemin absolu d'un exécutable (`bw-path`), vérifié maintenant : forme
    (`path_value_problem`), puis fichier (`fsutil.exe_problem`). Rendu tel quel (pas de
    résolution des liens : `~/.local/bin/bw` peut pointer vers une version installée à côté)."""
    text = text or ""
    why = path_value_problem(text) or exe_problem(text)
    if why:
        raise ConfigError("%s refusé : %s (%s)" % (key, show_value(text), why))
    return text


def format_value(key: str, v) -> str:
    if key in PATH_KEYS:
        return "PATH" if v is None else clean(v)
    if key in BOOL_KEYS:
        return "true" if v else "false"
    return format_duration(v) + (" (illimitée)" if v == 0 else "")


def format_duration(v: int) -> str:
    """Forme exacte la plus courte : 7200 → `2h`, 90 → `90s`, 0 → `0`."""
    if v == 0:
        return "0"
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if v % n == 0:
            return "%d%s" % (v // n, unit)
    return "%ds" % v


def describe_duration(v: int) -> str:
    return "illimitée" if v == 0 else format_duration(v)


def default_path(env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or ""
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "sshvault", "config.json")


class Config:
    def __init__(self, path: Optional[str] = None):
        self.path = path or default_path()

    def _read(self) -> dict:
        """Objet JSON du fichier, sans validation des valeurs ; {} si le fichier n'existe pas."""
        if not os.path.lexists(self.path):
            return {}
        raw = read_private(self.path)
        if raw is None:
            raise ConfigError("%s illisible (attendu : fichier ordinaire 0600 à l'utilisateur)" % self.path)
        try:
            data = json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError):
            raise ConfigError("%s : JSON invalide" % self.path) from None
        if not isinstance(data, dict):
            raise ConfigError("%s : objet JSON attendu" % self.path)
        return data

    def _check_path(self, data: dict, key: str) -> None:
        if key in data:
            why = path_value_problem(data[key])
            if why:
                raise ConfigError("%s : %s invalide : %s (%s)" % (self.path, key, show_value(data[key]), why))

    def load(self) -> dict:
        """Réglages enregistrés (sans les défauts) ; {} si le fichier n'existe pas."""
        data = self._read()
        ttl = data.get("key-ttl")
        if ttl is not None and not (isinstance(ttl, int) and not isinstance(ttl, bool)
                                    and (ttl == 0 or 1 <= ttl <= MAX_DURATION)):
            raise ConfigError("%s : key-ttl invalide : %r" % (self.path, ttl))
        for k in BOOL_KEYS:
            if k in data and not isinstance(data[k], bool):
                raise ConfigError("%s : %s invalide : %r (true ou false)" % (self.path, k, data[k]))
        for k in PATH_KEYS:
            self._check_path(data, k)
        self._check_accounts(data)
        return data

    def _check_accounts(self, data: dict) -> None:
        bad = lambda what: ConfigError("%s : %s invalide (%s)" % (self.path, ACCOUNTS, what))  # noqa: E731
        accts = data.get(ACCOUNTS, {})
        if not isinstance(accts, dict):
            raise bad("objet attendu")
        pairs = set()
        for a, v in accts.items():
            if not isinstance(a, str) or not ALIAS_RE.fullmatch(a):
                raise bad("alias %s" % show_value(a))
            if not isinstance(v, dict) or not isinstance(v.get("server"), str) or not isinstance(v.get("email"), str):
                raise bad("compte %s : server et email attendus" % a)
            try:
                ok = normalize_server(v["server"]) == v["server"] and normalize_email(v["email"]) == v["email"]
            except ConfigError:
                ok = False
            if not ok or (v["server"], v["email"]) in pairs:
                raise bad("compte %s : serveur ou e-mail" % a)
            pairs.add((v["server"], v["email"]))
        d = data.get(DEFAULT_ACCOUNTS, [])
        if not isinstance(d, list) or any(not isinstance(a, str) or a not in accts for a in d) or len(set(d)) != len(d):
            raise ConfigError("%s : %s invalide (liste d'alias enregistrés, sans doublon)" % (self.path, DEFAULT_ACCOUNTS))

    # --- registre des comptes (CAP-10) ----------------------------------------------

    def has_registry(self) -> bool:
        """Le registre des comptes existe (même vide) : installation déjà adoptée ou neuve."""
        return ACCOUNTS in self._read()

    def _registry(self) -> dict:
        """Registre seul, validé : les autres réglages, même invalides, n'y changent rien."""
        data = self._read()
        self._check_accounts(data)
        return data

    def accounts(self) -> dict:
        """{alias : {"server", "email"}}, dans l'ordre alphabétique des alias."""
        a = self._registry().get(ACCOUNTS, {})
        return {k: dict(a[k]) for k in sorted(a)}

    def default_accounts(self) -> list:
        """Comptes par défaut : la liste enregistrée, sinon le seul compte s'il n'y en a qu'un."""
        data = self._registry()
        d = list(data.get(DEFAULT_ACCOUNTS, []))
        accts = data.get(ACCOUNTS, {})
        if not d and len(accts) == 1:
            d = list(accts)
        return d

    @contextlib.contextmanager
    def locked(self):
        """`flock` sur le dossier de config.json : lecture-modification-écriture du registre."""
        try:
            d = ensure_dir(os.path.dirname(self.path))
            fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
        except OSError as e:
            raise ConfigWriteError("écriture de %s : %s" % (self.path, e.strerror or e)) from None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def update(self, fn) -> dict:
        """`fn(données)` sous verrou, puis écriture (registre seul validé : un autre réglage
        invalide est gardé tel quel) ; renvoie les données écrites."""
        with self.locked():
            data = self._registry()
            fn(data)
            self._check_accounts(data)  # jamais un registre invalide écrit
            self.save(data)
            return data

    def bw_path(self) -> Optional[str]:
        """Réglage `bw-path` seul (None : non posé), pour lancer bw : les autres réglages, même
        invalides, n'y changent rien. ConfigError si sa valeur ne peut être établie (fichier
        illisible, droits, JSON invalide, pas un objet) ou n'est pas un chemin absolu."""
        data = self._read()
        self._check_path(data, BW_PATH)
        return data.get(BW_PATH)

    def save(self, data: dict) -> None:
        try:
            write_private(self.path, (json.dumps(data, indent=1, sort_keys=True) + "\n").encode())
        except OSError as e:
            raise ConfigWriteError("écriture de %s : %s" % (self.path, e.strerror or e)) from None

    def get(self, key: str):
        """Valeur du réglage (enregistrée, sinon défaut)."""
        self.check_key(key)
        v = self.load().get(key)
        return DEFAULTS[key] if v is None else v

    def key_ttl(self) -> int:
        return self.get("key-ttl")

    @staticmethod
    def check_key(key: str) -> None:
        if key not in KEYS:
            raise ConfigError("clé de configuration inconnue : %r (connues : %s)" % (key, ", ".join(KEYS)))

    def set(self, key: str, value: str):
        self.check_key(key)
        # avant toute lecture ou écriture : config inchangée si invalide
        if key in PATH_KEYS:
            v = parse_exe_path(value, key)
        elif key in BOOL_KEYS:
            v = parse_bool(value)
        else:
            v = parse_duration(value)
        with self.locked():  # même verrou que le registre : rien d'écrasé par un `account …` concurrent
            data = self.load()
            data[key] = v
            self.save(data)
        return v

    def unset(self, key: str) -> None:
        self.check_key(key)
        if not os.path.exists(self.path):
            return
        with self.locked():
            data = self.load()
            if key in data:
                del data[key]
                self.save(data)

    def lines(self, key: Optional[str] = None) -> list:
        """Lignes de `config get` : `key-ttl 2h`, `key-ttl 1h (défaut)`, `auto-load true (défaut)`,
        `bw-path /home/u/.local/bin/bw`, `bw-path PATH (défaut)`."""
        if key is not None:
            self.check_key(key)
        data = self.load()
        out = []
        for k in ([key] if key else list(KEYS)):
            if k in data:
                out.append("%s %s" % (k, format_value(k, data[k])))
            else:
                out.append("%s %s (défaut)" % (k, format_value(k, DEFAULTS[k])))
        return out

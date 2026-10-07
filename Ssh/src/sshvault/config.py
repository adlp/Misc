"""Réglages de l'utilisateur : `${XDG_CONFIG_HOME:-~/.config}/sshvault/config.json`.

Fichier 0600 dans un dossier 0700, sans aucun secret (seule clé à ce jour : `key-ttl`,
durée de vie par défaut d'une clé chargée dans l'agent dédié, en secondes, 0 = illimitée).

Durées acceptées : `N`, `Ns`, `Nm`, `Nh`, `Nd` (N entier), entre 1 s et 30 j, ou `0`
(illimitée). Toute valeur invalide lève ConfigError (code de sortie 2).
"""
from __future__ import annotations

import json
import os
import re
from typing import Mapping, Optional

from .fsutil import read_private, write_private

DEFAULT_KEY_TTL = 3600
MAX_DURATION = 30 * 86400
KEYS = ("key-ttl",)
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION_RE = re.compile(r"(\d{1,12})([smhd]?)")


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

    def load(self) -> dict:
        """Réglages enregistrés (sans les défauts) ; {} si le fichier n'existe pas."""
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
        ttl = data.get("key-ttl")
        if ttl is not None and not (isinstance(ttl, int) and not isinstance(ttl, bool)
                                    and (ttl == 0 or 1 <= ttl <= MAX_DURATION)):
            raise ConfigError("%s : key-ttl invalide : %r" % (self.path, ttl))
        return data

    def save(self, data: dict) -> None:
        try:
            write_private(self.path, (json.dumps(data, indent=1, sort_keys=True) + "\n").encode())
        except OSError as e:
            raise ConfigWriteError("écriture de %s : %s" % (self.path, e.strerror or e)) from None

    def key_ttl(self) -> int:
        v = self.load().get("key-ttl")
        return DEFAULT_KEY_TTL if v is None else v

    @staticmethod
    def check_key(key: str) -> None:
        if key not in KEYS:
            raise ConfigError("clé de configuration inconnue : %r (connues : %s)" % (key, ", ".join(KEYS)))

    def set(self, key: str, value: str) -> int:
        self.check_key(key)
        v = parse_duration(value)  # avant toute lecture ou écriture : config inchangée si invalide
        data = self.load()
        data[key] = v
        self.save(data)
        return v

    def unset(self, key: str) -> None:
        self.check_key(key)
        data = self.load()
        if key in data:
            del data[key]
            self.save(data)

    def lines(self, key: Optional[str] = None) -> list:
        """Lignes de `config get` : `key-ttl 2h` ou `key-ttl 1h (défaut)`."""
        if key is not None:
            self.check_key(key)
        data = self.load()
        out = []
        for k in ([key] if key else list(KEYS)):
            if k in data:
                out.append("%s %s%s" % (k, format_duration(data[k]), " (illimitée)" if data[k] == 0 else ""))
            else:
                out.append("%s %s (défaut)" % (k, format_duration(DEFAULT_KEY_TTL)))
        return out

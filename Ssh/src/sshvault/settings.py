"""Réglages lus dans l'environnement."""
from __future__ import annotations

from typing import Mapping

MAX_SECONDS = 86400.0


def seconds(env: Mapping[str, str], name: str, default: float) -> float:
    """Durée en secondes dans `env[name]` : 0 < v <= 86400, sinon ValueError (message d'une ligne)."""
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = float(raw)
    except ValueError:
        v = float("nan")
    if not 0 < v <= MAX_SECONDS:
        raise ValueError("%s invalide : %r (secondes, entre 0 exclu et %d)" % (name, raw, MAX_SECONDS))
    return v

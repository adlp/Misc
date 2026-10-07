"""État de l'agent dédié : ce que `ssh-agent` ne dit pas.

Fichier JSON 0600 `agent.json`, à côté du socket (tmpfs privé, dossier 0700). Aucune clé
privée : par empreinte SHA256, l'élément d'origine (id, nom, hôtes), l'heure de
chargement, la durée de vie et les options ; plus le pid de l'agent lancé par sshvault,
l'identité de son socket (st_dev, st_ino) et le verrou posé par `sshvault agent lock`.

Les lignes de clés sont réconciliées avec `ssh-add -L` : une clé absente de l'agent
(expirée, retirée à la main) disparaît de l'état.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .fsutil import read_private, write_private

STATE_NAME = "agent.json"
VERSION = 1


def empty() -> dict:
    return {"version": VERSION, "agent": None, "locked": False, "keys": {}}


def _valid_agent(a) -> bool:
    return (isinstance(a, dict) and all(isinstance(a.get(k), int) and not isinstance(a.get(k), bool)
                                        for k in ("pid", "dev", "ino"))
            and a["pid"] > 1 and isinstance(a.get("socket"), str))


def _valid_entry(e) -> bool:
    return (isinstance(e, dict) and isinstance(e.get("id"), str) and isinstance(e.get("name"), str)
            and isinstance(e.get("hosts"), list) and all(isinstance(h, str) for h in e["hosts"])
            and isinstance(e.get("loaded"), (int, float)) and isinstance(e.get("lifetime"), int)
            and isinstance(e.get("confirm"), bool) and isinstance(e.get("restrict"), bool))


class AgentState:
    def __init__(self, path: str):
        self.path = path

    def load_checked(self):
        """(état, "none" | "ok" | "unreadable"). « unreadable » : fichier présent mais illisible
        (droits, lien), JSON invalide, ou version inconnue (plus récente) ; l'état rendu est
        alors vide et ne doit pas écraser le fichier sans reconstruire l'enregistrement de l'agent."""
        if not os.path.lexists(self.path):
            return empty(), "none"
        raw = read_private(self.path)
        if raw is None:
            return empty(), "unreadable"
        try:
            d = json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError):
            return empty(), "unreadable"
        if not isinstance(d, dict) or d.get("version") != VERSION:
            return empty(), "unreadable"
        out = empty()
        if _valid_agent(d.get("agent")):
            out["agent"] = dict(d["agent"])
        out["locked"] = d.get("locked") is True
        keys = d.get("keys")
        if isinstance(keys, dict):
            out["keys"] = {fp: e for fp, e in keys.items() if isinstance(fp, str) and _valid_entry(e)}
        return out, "ok"

    def load(self) -> dict:
        return self.load_checked()[0]

    def save(self, data: dict) -> None:
        write_private(self.path, (json.dumps(data, indent=1, sort_keys=True) + "\n").encode())

    def clear(self) -> None:
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def entry(item_id: str, name: str, hosts, loaded: float, lifetime: int, confirm: bool, restrict: bool) -> dict:
    return {"id": item_id, "name": name, "hosts": list(hosts), "loaded": loaded, "lifetime": lifetime,
            "confirm": confirm, "restrict": restrict}


def remaining(e: dict, now: float) -> Optional[int]:
    """Secondes restantes (≥ 0), ou None pour une durée illimitée."""
    if not e["lifetime"]:
        return None
    return max(0, int(e["loaded"] + e["lifetime"] - now))


def reconcile(data: dict, present: set, now: float) -> bool:
    """Retire de `data` les clés absentes de l'agent (`present` : empreintes de `ssh-add -L`).

    L'agent ne montre aucune clé alors que l'état en a (verrou posé par sshvault, ou peut-être
    à la main) : seules les clés dont la durée est écoulée sont retirées. Renvoie True si
    `data` a changé."""
    keys = data["keys"]
    if data.get("locked") or not present:
        gone = [fp for fp, e in keys.items() if remaining(e, now) == 0]
    else:
        gone = [fp for fp in keys if fp not in present]
    for fp in gone:
        del keys[fp]
    return bool(gone)


def maybe_locked(data: dict, present: set) -> bool:
    """Verrou probable posé hors de sshvault : l'agent ne montre rien, l'état garde des clés."""
    return not data.get("locked") and not present and bool(data["keys"])

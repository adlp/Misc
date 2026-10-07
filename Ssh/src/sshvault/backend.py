"""Interface d'accès au coffre : la couche qui lit (et plus tard écrit) les éléments
« SSH key », derrière un adaptateur interchangeable (aujourd'hui le CLI `bw`).

Rien de propre à un client particulier (bw, rbw…) ne doit sortir de ce module
ni des implémentations : la CLI ne connaît que `VaultBackend`, `SshKeyItem`,
`VaultStatus` et les exceptions ci-dessous.
"""
from __future__ import annotations

import abc
import fnmatch
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

#: Champ personnalisé qui porte les hôtes d'un élément : liste séparée par des virgules,
#: espaces autour ignorés, comparaison insensible à la casse.
HOSTS_FIELD = "sshvault-hosts"

#: Hôte accepté : motif de ligne `Host` d'OpenSSH fait de lettres, chiffres, `.`, `-`, `_`, `*`, `?`
#: (ASCII seulement, vérifié avant la mise en minuscules).
HOST_RE = re.compile(r"[A-Za-z0-9._*?-]+", re.ASCII)

#: Fonction d'invite : reçoit le texte de l'invite, renvoie le mot de passe.
#: Elle lève `VaultLocked` si aucune invite n'est possible ou si l'utilisateur annule.
Prompt = Callable[[str], str]


class VaultError(Exception):
    """Erreur d'accès au coffre, avec un message d'une ligne pour l'utilisateur."""


class NotLoggedIn(VaultError):
    """Aucun compte connecté dans le client du coffre."""


class VaultLocked(VaultError):
    """Coffre verrouillé et pas de déverrouillage possible (pas d'invite, mot de passe refusé…)."""


class PasswordRefused(VaultLocked):
    """Mot de passe maître saisi puis refusé par le client du coffre."""


class BackendError(VaultError):
    """Le client du coffre a échoué : absent, code d'erreur, sortie illisible, délai dépassé."""


class BackendNotFound(BackendError):
    """Exécutable du client introuvable."""


class ItemNotFound(BackendError):
    """Élément absent du coffre."""


class WriteFailed(BackendError):
    """Écriture dans le coffre non aboutie ou non vérifiée ; le message dit l'état relu (code 4)."""


class InvalidHost(ValueError):
    """Hôte refusé (caractère hors de lettres, chiffres, `.`, `-`, `_`, `*`, `?`) ; code 2."""


@dataclass(frozen=True)
class VaultStatus:
    state: str  # "unauthenticated" | "locked" | "unlocked"
    server: Optional[str] = None
    user: Optional[str] = None
    last_sync: Optional[str] = None


@dataclass(frozen=True)
class SshKeyItem:
    id: str
    name: str
    public_key: str
    fingerprint: str
    hosts: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "fingerprint": self.fingerprint,
                "hosts": list(self.hosts), "publicKey": self.public_key}

    # --- recherche par hôte, nom ou empreinte --------------------------------

    def match_host(self, pattern: str) -> bool:
        """Insensible à la casse, dans les deux sens : le motif glob (fnmatch) donné couvre
        un hôte associé (`*.example` → `prod.example`), ou un hôte associé écrit en glob
        couvre le nom donné (`x.lab` → `*.lab`, la clé qui sert à cet hôte)."""
        p = pattern.strip().lower()
        return any(fnmatch.fnmatchcase(h.lower(), p)
                   # sens inverse seulement pour un hôte associé écrit en glob (* ou ?) :
                   # un nom littéral avec « [ » n'est pas un motif
                   or (("*" in h or "?" in h) and fnmatch.fnmatchcase(p, h.lower()))
                   for h in self.hosts)

    def match_name(self, text: str) -> bool:
        """Sous-chaîne du nom, insensible à la casse."""
        return text.casefold() in self.name.casefold()

    def match_fingerprint(self, fp: str) -> bool:
        """Empreinte exacte, avec ou sans le préfixe `SHA256:`."""
        want = normalize_fingerprint(fp)
        return bool(want) and want == normalize_fingerprint(self.fingerprint)


def normalize_fingerprint(fp: str) -> str:
    fp = (fp or "").strip()
    if fp[:7].upper() == "SHA256:":
        fp = fp[7:]
    return fp


def parse_hosts(value: str) -> tuple:
    """`a, B ,c` → ('a', 'B', 'c') : virgules, espaces autour ignorés, vides retirés,
    doublons (sans tenir compte de la casse) retirés."""
    out, seen = [], set()
    for h in (value or "").split(","):
        h = h.strip()
        if h and h.lower() not in seen:
            seen.add(h.lower())
            out.append(h)
    return tuple(out)


def valid_host(host: str) -> bool:
    """Motif de ligne `Host` accepté (voir HOST_RE), espaces autour ignorés."""
    return bool(HOST_RE.fullmatch((host or "").strip()))


def normalize_hosts(values: Iterable[str]) -> tuple:
    """Hôtes donnés par l'utilisateur (chacun peut être une liste à virgules) → tuple en
    minuscules, sans vide ni doublon, dans l'ordre. Un hôte invalide lève InvalidHost."""
    out = []
    for v in values:
        for h in (v or "").split(","):
            h = h.strip()
            if not h:
                continue
            if not valid_host(h):
                raise InvalidHost("hôte invalide : %r (lettres, chiffres, « . », « - », « _ », « * », « ? »)" % h)
            h = h.lower()
            if h not in out:
                out.append(h)
    return tuple(out)


class VaultBackend(abc.ABC):
    """Accès au coffre. `prompt=None` veut dire : ne jamais demander de mot de passe.

    `warnings` : avertissements d'une ligne que la CLI affiche en fin de commande."""

    warnings: list

    @abc.abstractmethod
    def info(self) -> dict:
        """{"session": où la session est rangée ou None, "store": description du magasin,
        "data": dossier de données du client}."""

    @abc.abstractmethod
    def login(self, server: Optional[str] = None, apikey: bool = False) -> str:
        """Connexion interactive ; renvoie l'état atteint ("unlocked" ou "locked")."""

    @abc.abstractmethod
    def sync(self, prompt: Optional[Prompt] = None) -> None:
        """Resynchronise le cache local depuis le serveur."""

    @abc.abstractmethod
    def status(self) -> VaultStatus:
        ...

    @abc.abstractmethod
    def unlock(self, prompt: Optional[Prompt], ttl: int) -> None:
        """Déverrouille (si besoin) et range la session pour `ttl` secondes."""

    @abc.abstractmethod
    def lock(self) -> None:
        """Verrouille le coffre et vide le magasin de session."""

    @abc.abstractmethod
    def list_ssh_keys(self, prompt: Optional[Prompt] = None) -> list:
        """Éléments « SSH key » : id, nom, clé publique, empreinte, hôtes. Jamais de clé privée."""

    @abc.abstractmethod
    def get_private_key(self, item_id: str, prompt: Optional[Prompt] = None) -> bytes:
        """Clé privée, en mémoire seulement : l'appelant ne l'écrit ni ne l'affiche."""

    def get_ssh_key(self, item_id: str, prompt: Optional[Prompt] = None):
        """(élément, clé privée) d'un seul élément « SSH key » ; ItemNotFound s'il manque. La clé
        reste en mémoire : l'appelant ne l'écrit ni ne l'affiche. Une implémentation peut le
        faire en un seul appel au client du coffre."""
        found = [i for i in self.list_ssh_keys(prompt) if i.id == item_id]
        if not found:
            raise ItemNotFound("élément %s absent du coffre (ou pas une clé SSH)" % item_id)
        return found[0], self.get_private_key(item_id, prompt)

    @abc.abstractmethod
    def set_hosts(self, item_id: str, hosts: Sequence[str], prompt: Optional[Prompt] = None) -> SshKeyItem:
        """Remplace les hôtes de l'élément par `hosts` (validés, en minuscules ; vide = champ
        retiré), sans toucher au reste de l'élément. Renvoie l'élément relu après écriture.
        InvalidHost si un hôte est refusé (rien écrit) ; WriteFailed si l'écriture n'a pas
        abouti ou ne se relit pas (message avec l'état relu)."""

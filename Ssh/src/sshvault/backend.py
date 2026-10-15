"""Interface d'accès au coffre : la couche qui lit et écrit les éléments
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
#: Champ personnalisé des hôtes vers lesquels la clé est transférée (sous-agent par motif,
#: CAP-8) : mêmes règles que `sshvault-hosts`.
FORWARD_FIELD = "sshvault-forward"

#: Hôte accepté : motif de ligne `Host` d'OpenSSH fait de lettres, chiffres, `.`, `-`, `_`, `*`, `?`
#: (ASCII seulement, vérifié avant la mise en minuscules).
HOST_RE = re.compile(r"[A-Za-z0-9._*?-]+", re.ASCII)

#: Hôte d'un mot de passe d'hôte (CAP-11) : nom tapé, lettres, chiffres, `.`, `-`, `_`, sans motif ni
#: `-` en tête (il passe en argument de `ensure --host` dans la ligne `Match exec`).
LOGIN_HOST_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,252}", re.ASCII)
#: URI d'un élément identifiant : `ssh://[user@]hôte[:port]` (schéma insensible à la casse).
_SSH_URI_RE = re.compile(r"(?i:ssh)://(?:([^@/?#\s]+)@)?([^@/?#:\s\[\]]+)(?::([0-9]{1,5}))?", re.ASCII)
_URI_SECRET_RE = re.compile(r"(://[^/@:?#]*):[^/@?#]*@")

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


class LogoutUnknown(BackendError):
    """Déconnexion sans réponse du client, et état de connexion impossible à relire : ni
    « déconnecté » ni « toujours connecté »."""


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
    #: motifs d'hôtes vers lesquels la clé est transférée (champ `sshvault-forward`)
    forward: tuple = field(default_factory=tuple)
    #: alias du compte du coffre (CAP-10), posé par la CLI ; None : inconnu
    account: Optional[str] = None

    def to_dict(self) -> dict:
        return {"account": self.account, "id": self.id, "name": self.name, "fingerprint": self.fingerprint,
                "hosts": list(self.hosts), "forward": list(self.forward), "publicKey": self.public_key}

    # --- recherche par hôte, nom ou empreinte --------------------------------

    def match_host(self, pattern: str) -> bool:
        """Insensible à la casse, dans les deux sens : le motif glob (fnmatch) donné couvre
        un hôte associé (`*.example` → `prod.example`), ou un hôte associé écrit en glob
        couvre le nom donné (`x.lab` → `*.lab`, la clé qui sert à cet hôte)."""
        return _match_patterns(pattern, self.hosts)

    def match_forward(self, pattern: str) -> bool:
        """Comme `match_host`, sur les motifs de transfert (`sshvault-forward`)."""
        return _match_patterns(pattern, self.forward)

    def match_name(self, text: str) -> bool:
        """Sous-chaîne du nom, insensible à la casse."""
        return text.casefold() in self.name.casefold()

    def match_fingerprint(self, fp: str) -> bool:
        """Empreinte exacte, avec ou sans le préfixe `SHA256:`."""
        want = normalize_fingerprint(fp)
        return bool(want) and want == normalize_fingerprint(self.fingerprint)


def parse_ssh_uri(uri) -> Optional[tuple]:
    """`ssh://[user@]hôte[:port]` → (hôte en minuscules, utilisateur ou None) ; port accepté
    (1 à 65535) et ignoré (topologie dans ~/.ssh/config) ; utilisateur décodé (`%40` → `@`), sans
    blanc ni caractère de contrôle ni `:` (mot de passe dans l'URI refusé). Autre forme (chemin,
    requête, motif, autre schéma) : None."""
    if not isinstance(uri, str):
        return None
    m = _SSH_URI_RE.fullmatch(uri.strip())
    if not m:
        return None
    raw_user, host, port = m.groups()
    if not LOGIN_HOST_RE.fullmatch(host):
        return None
    if port is not None and not 1 <= int(port) <= 65535:
        return None
    user = None
    if raw_user is not None:
        if ":" in raw_user:
            return None
        from urllib.parse import unquote
        user = unquote(raw_user)
        if not user or any(c.isspace() or ord(c) < 0x20 or 0x7f <= ord(c) <= 0x9f for c in user):
            return None
    return host.lower(), user


def ssh_scheme(uri) -> bool:
    """URI au schéma `ssh:` (valide ou non)."""
    return isinstance(uri, str) and uri.strip().lower().startswith("ssh:")


def redact_uri(uri: str) -> str:
    """URI pour un message : mot de passe éventuel (`scheme://user:secret@…`) masqué."""
    return _URI_SECRET_RE.sub(r"\1:***@", uri or "")


def login_hosts(username, uris) -> tuple:
    """(hôtes, URI ignorées) d'un élément identifiant : hôtes = ((hôte, utilisateur ou None), …)
    dans l'ordre des URI, sans doublon ; l'utilisateur de l'URI remplace `username`."""
    default = username if isinstance(username, str) and username else None
    hosts, ignored = [], []
    for u in uris:
        parsed = parse_ssh_uri(u)
        if parsed is None:
            ignored.append(u)
            continue
        h, user = parsed
        pair = (h, user if user is not None else default)
        if pair not in hosts:
            hosts.append(pair)
    return tuple(hosts), tuple(ignored)


@dataclass(frozen=True)
class LoginItem:
    """Élément « identifiant » (type 1) relié à des hôtes par URI `ssh://` (CAP-11). Jamais le
    mot de passe."""
    id: str
    name: str
    #: ((hôte en minuscules, utilisateur attendu ou None), …), dans l'ordre des URI
    hosts: tuple = field(default_factory=tuple)
    #: URI ignorées (autre forme ou autre schéma), telles que dans l'élément
    ignored: tuple = field(default_factory=tuple)
    account: Optional[str] = None

    def host_names(self) -> tuple:
        out = []
        for h, _ in self.hosts:
            if h not in out:
                out.append(h)
        return tuple(out)

    def users(self, host: str) -> tuple:
        """Utilisateurs attendus pour `host` (sans tenir compte de la casse de l'hôte)."""
        host = (host or "").lower()
        return tuple(u for h, u in self.hosts if h.lower() == host and u)

    def labels(self) -> list:
        return ["%s@%s" % (u, h) if u else h for h, u in self.hosts]

    def to_dict(self) -> dict:
        return {"account": self.account, "id": self.id, "name": self.name, "hosts": self.labels(),
                "ignored": [redact_uri(u) for u in self.ignored]}


def _match_patterns(pattern: str, hosts) -> bool:
    p = pattern.strip().lower()
    return any(fnmatch.fnmatchcase(h.lower(), p)
               # sens inverse seulement pour un hôte associé écrit en glob (* ou ?) :
               # un nom littéral avec « [ » n'est pas un motif
               or (("*" in h or "?" in h) and fnmatch.fnmatchcase(p, h.lower()))
               for h in hosts)


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
    def status(self, forget: bool = True) -> VaultStatus:
        """État du compte ; `forget=False` : sonde sans effet sur la session rangée."""

    @abc.abstractmethod
    def unlock(self, prompt: Optional[Prompt], ttl: int) -> None:
        """Déverrouille (si besoin) et range la session pour `ttl` secondes."""

    @abc.abstractmethod
    def lock(self) -> None:
        """Verrouille le coffre et vide le magasin de session."""

    @abc.abstractmethod
    def logout(self, on_interrupt=None) -> bool:
        """Déconnecte le compte (données locales du client) et oublie la session. True :
        déconnecté ; False : il n'était pas connecté. LogoutUnknown : état de connexion inconnu
        (client sans réponse, état impossible à relire) ; toute autre BackendError : toujours
        connecté. Interrompu : client tué, état relu, `on_interrupt(déconnecté ? ou None)`
        appelé signaux retenus, puis l'interruption est relevée."""

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
    def list_logins(self, prompt: Optional[Prompt] = None) -> list:
        """Éléments « identifiant » à URI `ssh://` (CAP-11) : LoginItem, sans le mot de passe ;
        un élément dont seules des URI `ssh:` invalides existent est rendu sans hôte (`ignored`)."""

    @abc.abstractmethod
    def get_login(self, item_id: str, prompt: Optional[Prompt] = None):
        """(LoginItem, mot de passe en octets) d'un élément identifiant ; ItemNotFound s'il manque
        ou n'en est pas un. Le mot de passe reste en mémoire : l'appelant ne l'écrit que vers le
        ssh qui le demande, jamais dans un message."""

    def get_password(self, item_id: str, prompt: Optional[Prompt] = None) -> bytes:
        return self.get_login(item_id, prompt)[1]

    @abc.abstractmethod
    def set_hosts(self, item_id: str, hosts: Sequence[str], prompt: Optional[Prompt] = None) -> SshKeyItem:
        """Remplace les hôtes de l'élément par `hosts` (validés, en minuscules ; vide = champ
        retiré), sans toucher au reste de l'élément. Renvoie l'élément relu après écriture.
        InvalidHost si un hôte est refusé (rien écrit) ; WriteFailed si l'écriture n'a pas
        abouti ou ne se relit pas (message avec l'état relu)."""

    @abc.abstractmethod
    def set_forward(self, item_id: str, hosts: Sequence[str], prompt: Optional[Prompt] = None) -> SshKeyItem:
        """Comme `set_hosts`, pour le champ `sshvault-forward` (hôtes de transfert d'agent)."""

    @abc.abstractmethod
    def create_ssh_key(self, name: str, private_key: str, public_key: str, fingerprint: str, hosts: Sequence[str],
                       prompt: Optional[Prompt] = None, existing: Optional[Iterable[str]] = None,
                       extra_fields: Sequence[tuple] = ()) -> SshKeyItem:
        """Crée un élément « SSH key » (les trois champs `privateKey`, `publicKey`,
        `keyFingerprint` ; hôtes validés dans `sshvault-hosts` ; `extra_fields` : champs texte
        (nom, valeur) en plus), le relit et le compare. Une création n'est pas idempotente :
        après un échec, l'état du serveur est relu (recherche par empreinte d'un élément absent
        de `existing`, les ids qui la portaient déjà) avant tout rejeu, sans doublon.
        Renvoie l'élément relu ; WriteFailed si la création n'aboutit pas ou ne se relit pas."""

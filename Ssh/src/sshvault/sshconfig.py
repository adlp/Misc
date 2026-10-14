"""`ssh_config` inclus (CAP-5) : `~/.ssh/sshvault/config` et `~/.ssh/sshvault/pub/*.pub`,
puis, sur demande seulement, la ligne `Include` en tête de `~/.ssh/config`.

- Plusieurs comptes (CAP-10) : un élément est désigné par (compte, id) ; le fichier couvre les
  éléments de tous les comptes. Commentaire d'un bloc d'identité : `# <nom> <alias> <id>` (l'id
  en fin de ligne). Un compte illisible à la régénération (verrouillé sans invite possible) garde
  ses blocs actuels, relus dans le fichier (`kept_items`), jamais retirés.
- Un bloc par élément associé, triés par nom d'élément, alias puis id, ouvert par
  `Match originalhost <motif>,<motif>` : comparé au nom **tapé** (pas au HostName), sans
  tenir compte de la casse (mesuré sur OpenSSH 8.9p1 : `Host foo` ne s'applique pas à
  `ssh FOO`). Directives : `IdentityAgent` (socket dédié résolu, sans `${XDG_RUNTIME_DIR}`),
  `IdentityFile` (clé publique), `IdentitiesOnly yes`. Jamais `HostName`, `User`, `Port`,
  `ProxyJump` ni `ProxyCommand`.
- Chargement automatique (réglage `auto-load`, défaut oui) : avant chaque bloc, une ligne
  `Match originalhost <motifs> exec "'<sshvault>' ensure --account <alias> --id <id>"` sans directive (ssh
  n'exécute la commande que si `originalhost` correspond). La commande, passée au shell de
  l'utilisateur, ne contient que des éléments contrôlés : chemin absolu de sshvault entre
  apostrophes (refusé s'il contient `'`, `"`, `\\`, `${` ou un caractère de contrôle ; `%`
  doublé) et id de l'élément, un UUID validé (sinon pas de ligne, avertissement). Jamais
  `%h` ni `%n` : un motif `*.lab` y ferait passer un nom tapé par l'utilisateur.
- Chemins absolus, entre guillemets, `%` échappé en `%%` (IdentityAgent et IdentityFile
  développent les tokens `%x` et `${VAR}` : un chemin avec `"`, `\\`, `${` ou un caractère de
  contrôle est refusé).
- Écriture atomique en 0600 dans un dossier 0700 ; rien n'est réécrit si le contenu est
  identique (mtime inchangée) ; `pub/` ne garde que les clés des éléments associés.
- Verrou `flock` sur `~/.ssh/sshvault/` autour de l'écriture et de la purge : deux
  régénérations simultanées ne se gênent pas.
- `Include` : seuls `install` et `uninstall` écrivent `~/.ssh/config` (sauvegarde jamais
  écrasée, mode et propriétaire gardés, lien symbolique ou fichier non ordinaire refusé) ;
  ailleurs, on ne fait que lire, sans jamais bloquer sur une FIFO. `uninstall` retire aussi
  `~/.ssh/sshvault/config` et les `*.pub` de `pub/`, rien d'autre.
- `~` = répertoire de passwd (celui où ssh lit `~/.ssh/config`), pas `$HOME`.
- Transfert d'agent restreint (CAP-8) : pour chaque motif de `sshvault-forward`, **avant** les
  blocs d'identité (première valeur gagnante), une ligne `Match originalhost <motif> exec
  "'<sshvault>' ensure --forward <fid> --id <uuid>…"` (sous-agent chargé à la demande) puis
  `Match originalhost <motif>` + `ForwardAgent "<socket résolu du sous-agent>"`. Ordre : motifs
  littéraux, puis motifs à joker du plus au moins précis (nombre de caractères littéraux),
  attrape-tout en dernier, alphabétique à égalité. Pour un hôte couvert par deux motifs, le
  premier bloc gagne (avertissement) ; la ligne `Match … exec` d'un bloc exclut les motifs des
  blocs précédents (`<motif>,!<motif précédent>…`) : les clés d'un sous-agent jamais transféré
  ne sont ni lues ni chargées. Aucun `ForwardAgent` pour un hôte
  d'identité sans transfert déclaré : la config de l'utilisateur décide. Bloc sans ligne
  `Match exec` (`auto-load false`, aucune clé utilisable) : `ForwardAgent no` (un socket jamais
  créé arrêterait un saut `ssh -W` par cet hôte).
"""
from __future__ import annotations

import contextlib
import fcntl
import fnmatch
import os
import pwd
import re
import shlex
import stat
import sys
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .agent import FID_RE, FWD_DIR, SUN_PATH_MAX, fingerprint, forward_id, public_blob
from .backend import SshKeyItem, valid_host
from .fastpath import ITEM_ID_RE, parse_ref
from .runtime import ALIAS_RE
from .fsutil import ensure_dir, read_private, write_private

HEADER = ("# Généré par sshvault, ne pas éditer : « sshvault ssh-config » le réécrit.\n"
          "# Chargé par la ligne Include en tête de ~/.ssh/config (« sshvault ssh-config install »).\n")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_KEY_TYPE = re.compile(r"[A-Za-z0-9@._-]+")
_KEYWORD = re.compile(r"([A-Za-z]+)(?:\s*=\s*|\s+|$)(.*)$", re.S)
_TMP = re.compile(r"\..+\.(\d+)\.tmp$")
_CATCH_ALL = re.compile(r"[*?.]+")
#: Avertissement des motifs sans partie littérale (décision de l'utilisateur, 2026-10-07).
CATCH_ALL_WARNING = "ce bloc prend toutes les connexions ssh et désactive ton agent habituel"
#: Avertissement d'un motif de transfert sans partie littérale.
FORWARD_CATCH_ALL_WARNING = "ce sous-agent de transfert sera transféré à toutes les connexions ssh"
#: Commentaire qui ouvre un bloc de transfert : `# transfert d'agent <motif> <fid>`.
FORWARD_COMMENT = "# transfert d'agent "
#: Délai d'un `ssh -G` de contrôle (s), et de l'ensemble des contrôles d'une commande.
SSH_G_TIMEOUT = 15
SSH_G_BUDGET = 30.0
SSH_G_BUDGET_VAR = "SSHVAULT_SSH_G_BUDGET"
#: Répertoire personnel imposé (tests seulement) ; sinon celui de passwd.
HOME_ENV = "SSHVAULT_SSH_HOME"
EXE_NAME = "sshvault"


class SshConfigError(Exception):
    """Génération ou installation impossible (code 4), message d'une ligne."""


def clean(text: str) -> str:
    return _CONTROL.sub(lambda m: "\\x%02x" % ord(m.group()), text)


# --- chemins -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Paths:
    home: str

    @property
    def ssh_dir(self) -> str:
        return os.path.join(self.home, ".ssh")

    @property
    def dir(self) -> str:
        return os.path.join(self.ssh_dir, "sshvault")

    @property
    def config(self) -> str:
        return os.path.join(self.dir, "config")

    @property
    def pub(self) -> str:
        return os.path.join(self.dir, "pub")

    @property
    def user_config(self) -> str:
        return os.path.join(self.ssh_dir, "config")

    @property
    def backup(self) -> str:
        return os.path.join(self.ssh_dir, "config.sshvault.bak")


def default_paths(env=None) -> Paths:
    """Répertoire de passwd de l'utilisateur : ssh y lit `~/.ssh/config`, quel que soit $HOME."""
    env = os.environ if env is None else env
    home = env.get(HOME_ENV) or ""
    if not home:
        try:
            home = pwd.getpwuid(os.getuid()).pw_dir or ""
        except KeyError:
            home = ""
    if not os.path.isabs(home) or os.path.normpath(home) == "/":
        raise SshConfigError("répertoire personnel inconnu ou inutilisable (passwd : %r) : ~/.ssh refusé" % home)
    return Paths(os.path.normpath(home))


def is_catch_all(host: str) -> bool:
    """Motif sans partie littérale (`*`, `*.*`, `?*`…) : il prend toutes les connexions."""
    return bool(_CATCH_ALL.fullmatch(host))


def fp_filename(fp: str) -> str:
    """Nom du `.pub` : empreinte en base64url (`/`→`_`, `+`→`-`), qui peut sinon contenir `/`."""
    return fp.replace("/", "_").replace("+", "-") + ".pub"


def _check_path(path: str, what: str, forbidden: str = "") -> None:
    if not os.path.isabs(path) or '"' in path or "\\" in path or "${" in path or _CONTROL.search(path) \
            or any(c in path for c in forbidden):
        raise SshConfigError("%s inutilisable dans un ssh_config : %s (chemin absolu sans « \" », « \\ », "
                             "« ${ »%s ni caractère de contrôle)"
                             % (what, clean(path), "".join(", « %s »" % c for c in forbidden)))


def quote_path(path: str, what: str) -> str:
    """Chemin pour IdentityAgent/IdentityFile : guillemets, `%` → `%%`."""
    _check_path(path, what)
    return '"%s"' % path.replace("%", "%%")


#: Version minimale d'une commande sshvault pour les lignes `Match exec` (`ensure`).
ENSURE_MIN_VERSION = (0, 4, 0)
_VERSION_RE = re.compile(r"sshvault (\d+)\.(\d+)\.(\d+)")
_exe_checked: dict = {}


def exe_version(exe: str):
    """Version rendue par `<exe> --version` (tuple), ou None ; mise en cache pour le processus
    (une génération)."""
    if exe not in _exe_checked:
        import subprocess
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30,
                               stdin=subprocess.DEVNULL)
            m = _VERSION_RE.search(r.stdout) if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            m = None
        _exe_checked[exe] = tuple(int(x) for x in m.groups()) if m else None
    return _exe_checked[exe]


def sshvault_exe(argv0: Optional[str] = None, env=None) -> str:
    """Chemin absolu de la commande `sshvault` pour `Match exec` : celle qui tourne si elle a
    été lancée sous ce nom (console script installé), sinon les `sshvault` exécutables des
    dossiers **absolus** du PATH, dans l'ordre ; la première qui connaît `ensure`
    (`--version` ≥ 0.4.0) est retenue. Aucune : SshConfigError."""
    env = os.environ if env is None else env
    argv0 = sys.argv[0] if argv0 is None else argv0
    cands = []
    if os.path.basename(argv0 or "") == EXE_NAME:
        cands.append(os.path.abspath(argv0))
    cands += [os.path.join(d, EXE_NAME) for d in (env.get("PATH") or "").split(os.pathsep) if os.path.isabs(d)]
    old = []
    for c in cands:
        c = os.path.normpath(c)
        if not (os.path.isfile(c) and os.access(c, os.X_OK)):
            continue
        v = exe_version(c)
        if v is not None and v >= ENSURE_MIN_VERSION:
            return c
        old.append(c)
    raise SshConfigError("commande sshvault %s pour le chargement automatique%s : l'installer (uv tool install "
                         "--force), ou « sshvault config set auto-load false »"
                         % ("0.4.0 ou plus introuvable (PATH)" if not old else "trop ancienne",
                            " (%s)" % ", ".join(clean(o) for o in old) if old else ""))


def exe_warnings(exe: str, paths: "Paths") -> list:
    """Avertissements sur le chemin retenu : différent de celui de la config générée existante,
    ou dans un environnement de projet (`.venv`), dont la config dépendrait."""
    out = []
    raw = read_private(paths.config)
    m = re.search(r"exec \"'([^']*)' ensure --(?:id|forward|account) ", raw.decode(errors="replace")) if raw else None
    if m and m.group(1).replace("%%", "%") != exe:
        out.append("chemin de sshvault des lignes Match exec changé : %s → %s"
                   % (clean(m.group(1).replace("%%", "%")), clean(exe)))
    if ".venv" in exe.split(os.sep):
        out.append("sshvault pris dans un environnement de projet (%s) : la config générée en dépendra ; "
                   "préférer la commande installée (uv tool install)" % clean(exe))
    return out


def _check_alias(alias) -> None:
    if not ALIAS_RE.fullmatch(alias or ""):
        raise SshConfigError("alias de compte inattendu : %s" % clean(alias or ""))


def ensure_command(exe: str, item_id: str, account: Optional[str] = None) -> str:
    """Commande de `Match exec` : `'<exe>' ensure --account <alias> --id <uuid>` (`%` doublé pour
    ssh ; sans compte : ancienne forme `ensure --id <uuid>`). Rien d'autre que le chemin vérifié,
    l'alias et l'id validés : la commande passe par un shell."""
    _check_path(exe, "chemin de sshvault", "'")
    if not ITEM_ID_RE.fullmatch(item_id or ""):
        raise SshConfigError("id d'élément inattendu (UUID attendu) : %s" % clean(item_id))
    if account is not None:
        _check_alias(account)
    return "'%s' ensure %s--id %s" % (exe.replace("%", "%%"), "--account %s " % account if account else "",
                                      item_id.lower())


def forward_command(exe: str, fid: str, ids: Sequence) -> str:
    """Commande de `Match exec` d'un bloc de transfert : `'<exe>' ensure --forward <fid> --id
    <alias>:<uuid>…` (`%` doublé pour ssh ; id sans compte : `--id <uuid>`). Seulement le chemin
    vérifié, le `fid` (16 hex), des alias et des ids validés (UUID) : la commande passe par un
    shell. Ni `%h` ni `%n`."""
    _check_path(exe, "chemin de sshvault", "'")
    if not FID_RE.fullmatch(fid or ""):
        raise SshConfigError("identifiant de sous-agent inattendu : %s" % clean(fid or ""))
    if not ids:
        raise SshConfigError("bloc de transfert sans clé")
    refs = []
    for x in ids:
        a, i = x if isinstance(x, tuple) else (None, x)
        if not ITEM_ID_RE.fullmatch(i or ""):
            raise SshConfigError("id d'élément inattendu (UUID attendu) : %s" % clean(i or ""))
        if a is not None:
            _check_alias(a)
        refs.append("%s:%s" % (a, i.lower()) if a else i.lower())
    return "'%s' ensure --forward %s%s" % (exe.replace("%", "%%"), fid, "".join(" --id %s" % r for r in refs))


def forward_socket(agent_socket: str, fid: str) -> str:
    """Socket du sous-agent `fid` : `fwd/<fid>.sock` à côté du socket de l'agent dédié."""
    return os.path.join(os.path.dirname(agent_socket), FWD_DIR, fid + ".sock")


def _forward_order(pattern: str):
    """Ordre des blocs de transfert (le premier gagne) : motifs littéraux, puis motifs à joker
    du plus au moins précis (nombre de caractères littéraux), attrape-tout en dernier ;
    alphabétique à égalité."""
    wild = "*" in pattern or "?" in pattern
    return (wild, is_catch_all(pattern), -len(pattern.replace("*", "").replace("?", "")) if wild else 0, pattern)


def include_line(paths: Paths) -> str:
    """`Include "<config>"`. Include ne développe pas `%` en 8.9 (mesuré) mais le fait dans
    les versions récentes (man) : un chemin avec `%`, `$` ou un joker de glob est refusé."""
    _check_path(paths.config, "chemin du ssh_config généré", "%$*?[")
    return 'Include "%s"' % paths.config


# --- génération --------------------------------------------------------------------------

@dataclass
class Plan:
    config: bytes
    pubs: dict = field(default_factory=dict)  # nom de fichier -> contenu
    blocks: int = 0
    warnings: list = field(default_factory=list)
    #: sous-agents référencés : fid -> (motif, [(compte, id) des clés autorisées])
    forward: dict = field(default_factory=dict)


def _label(it: SshKeyItem) -> str:
    return "« %s » (%s%s)" % (clean(it.name), clean(it.account) + " " if it.account else "", clean(it.id))


def _order(i: SshKeyItem):
    return (i.name.casefold(), i.account or "", i.id)


def build(items: Sequence[SshKeyItem], paths: Paths, socket: str, exe: Optional[str] = None,
          kept: frozenset = frozenset()) -> Plan:
    """Contenu du fichier généré et des `.pub`, sans rien écrire. Vérifie aussi les chemins
    (SshConfigError) : sert de contrôle préalable avant une écriture dans le coffre.
    `exe` : chemin de sshvault ; s'il est donné, chaque bloc est précédé de sa ligne
    `Match … exec` (chargement automatique). `kept` : (compte, id) des éléments relus dans le
    fichier actuel (compte illisible, `kept_items`) : clé publique d'un élément de transfert sans
    bloc d'identité inconnue, mais déjà vérifiée à la génération précédente."""
    agent = quote_path(socket, "socket de l'agent dédié")
    _check_path(paths.pub, "dossier des clés publiques")
    if exe is not None:
        _check_path(exe, "chemin de sshvault", "'")
    plan = Plan(config=b"")
    out = [HEADER]
    _forward_blocks(items, socket, exe, plan, out, kept)
    entries = []  # (motif, élément), dans l'ordre des blocs
    for it in sorted(items, key=_order):
        if not it.hosts:
            continue
        bad = [h for h in it.hosts if not valid_host(h)]
        if bad:
            plan.warnings.append("%s : hôte invalide « %s » : élément sauté" % (_label(it), clean(bad[0])))
            continue
        parts = (it.public_key or "").split()
        blob = public_blob(it.public_key)
        if blob is None or not _KEY_TYPE.fullmatch(parts[0]):
            plan.warnings.append("%s : clé publique illisible : élément sauté" % _label(it))
            continue
        name = fp_filename(fingerprint(blob))
        plan.pubs[name] = ("%s %s\n" % (parts[0], blob)).encode()
        hosts = []
        for h in it.hosts:
            h = h.strip().lower()
            if h not in hosts:
                hosts.append(h)
                entries.append((h, it))
                if is_catch_all(h):
                    plan.warnings.append("%s : motif « %s » : %s" % (_label(it), h, CATCH_ALL_WARNING))
        # hôtes validés (HOST_RE) : ni virgule ni espace, la liste à virgules est sûre
        out.append("\n# %s %s%s\n" % (clean(it.name), clean(it.account) + " " if it.account else "", clean(it.id)))
        if exe is not None:
            if ITEM_ID_RE.fullmatch(it.id) and (it.account is None or ALIAS_RE.fullmatch(it.account)):
                out.append('Match originalhost %s exec "%s"\n' % (",".join(hosts), ensure_command(exe, it.id, it.account)))
            else:
                plan.warnings.append("%s : id inattendu (UUID attendu) : pas de chargement automatique pour "
                                     "cet élément" % _label(it))
        out.append("Match originalhost %s\n    IdentityAgent %s\n    IdentityFile %s\n"
                   "    IdentitiesOnly yes\n"
                   % (",".join(hosts), agent, quote_path(os.path.join(paths.pub, name), "clé publique")))
        plan.blocks += 1
    owners = {}
    for h, it in entries:
        owners.setdefault(h, []).append(it)
    for h, its in owners.items():
        if len(its) > 1:
            plan.warnings.append("hôte « %s » porté par %d éléments (%s) : ssh offrira leurs clés dans l'ordre "
                                 "des blocs" % (h, len(its), ", ".join(_label(i) for i in its)))
    for n, (h1, a) in enumerate(entries):
        for h2, b in entries[n + 1:]:
            if a is b or h1 == h2 or is_catch_all(h1) or is_catch_all(h2):
                continue
            if fnmatch.fnmatchcase(h1, h2) or fnmatch.fnmatchcase(h2, h1):
                plan.warnings.append("motifs « %s » de %s et « %s » de %s se recouvrent : pour les hôtes communs, "
                                     "ssh offrira les deux clés dans l'ordre des blocs" % (h1, _label(a), h2, _label(b)))
    plan.config = "".join(out).encode()
    return plan


def _forward_blocks(items: Sequence[SshKeyItem], socket: str, exe: Optional[str], plan: Plan, out: list,
                    kept: frozenset = frozenset()) -> None:
    """Blocs de transfert (CAP-8), avant les blocs d'identité : un par motif de `sshvault-forward`."""
    forwards = {}  # motif -> [éléments], dans l'ordre des éléments
    for it in sorted(items, key=_order):
        for h in it.forward:
            if not valid_host(h):
                plan.warnings.append("%s : motif de transfert invalide « %s » : ignoré" % (_label(it), clean(h)))
                continue
            h = h.strip().lower()
            its = forwards.setdefault(h, [])
            if it not in its:
                its.append(it)
    if not forwards:
        return
    if exe is None:
        plan.warnings.append("auto-load false : aucune ligne Match exec, aucun sous-agent de transfert : ForwardAgent no "
                             "pour les motifs de transfert (l'hôte distant ne verra aucune clé)")
    order = sorted(forwards, key=_forward_order)
    for p in order:
        fid = forward_id(p)
        sock = forward_socket(socket, fid)
        if len(os.fsencode(sock)) > SUN_PATH_MAX:
            raise SshConfigError("chemin du socket de transfert trop long (%d octets au plus) : %s"
                                 % (SUN_PATH_MAX, clean(sock)))
        ids = []
        for it in forwards[p]:
            ref = (it.account, it.id.lower())
            if not ITEM_ID_RE.fullmatch(it.id) or (it.account is not None and not ALIAS_RE.fullmatch(it.account)):
                plan.warnings.append("%s : id inattendu (UUID attendu) : pas de transfert de cette clé vers « %s »"
                                     % (_label(it), p))
            elif public_blob(it.public_key) is None and (it.account, it.id) not in kept:
                plan.warnings.append("%s : clé publique illisible : pas de transfert de cette clé vers « %s »"
                                     % (_label(it), p))
            elif ref not in ids:
                ids.append(ref)
        if not ids:
            plan.warnings.append("motif de transfert « %s » : aucune clé transférable : ForwardAgent no" % p)
        if is_catch_all(p):
            plan.warnings.append("motif de transfert « %s » : %s" % (p, FORWARD_CATCH_ALL_WARNING))
        # motif validé (HOST_RE) : ni espace ni virgule, sûr sur la ligne Match
        out.append("\n%s%s %s\n" % (FORWARD_COMMENT, p, fid))
        if exe is not None and ids:
            # motifs des blocs précédents exclus (« ! », hors de HOST_RE : sûr) : pour un hôte
            # qu'ils couvrent, ce bloc ne s'applique pas, ses clés ne sont pas chargées
            match = ",".join([p] + ["!" + q for q in order[:order.index(p)]])
            out.append('Match originalhost %s exec "%s"\n' % (match, forward_command(exe, fid, ids)))
            target = quote_path(sock, "socket du sous-agent de transfert")
        else:
            # sans Match exec, le socket n'existerait jamais : un saut `ssh -W` par cet hôte
            # s'arrêterait (-W impose ExitOnForwardFailure, mesuré) ; rien n'est transféré
            target = "no"
        out.append("Match originalhost %s\n    ForwardAgent %s\n" % (p, target))
        # sans Match exec, aucune clé autorisée : un sous-agent qui en garde est arrêté
        plan.forward[fid] = (p, ids if target != "no" else [])
        plan.blocks += 1
    for n, p1 in enumerate(order):
        for p2 in order[n + 1:]:
            if is_catch_all(p1) or is_catch_all(p2):
                continue
            if fnmatch.fnmatchcase(p1, p2) or fnmatch.fnmatchcase(p2, p1):
                plan.warnings.append("motifs de transfert « %s » et « %s » se recouvrent : pour les hôtes communs, seul "
                                     "le premier bloc (« %s ») s'applique" % (p1, p2, p1))


def forward_map(paths: Paths) -> dict:
    """{fid : motif} des blocs de transfert du fichier généré (commentaires `# transfert
    d'agent <motif> <fid>`, fid recalculé) ; {} si le fichier manque."""
    raw = read_private(paths.config)
    out = {}
    for line in (raw.decode(errors="replace").splitlines() if raw else []):
        if line.startswith(FORWARD_COMMENT):
            parts = line[len(FORWARD_COMMENT):].split()
            if len(parts) == 2 and forward_id(parts[0]) == parts[1]:
                out[parts[1]] = parts[0]
    return out


def kept_items(paths: Paths, keep, renamed: Optional[dict] = None, known=None, notes: Optional[list] = None):
    """Éléments relus dans le fichier généré actuel, pour garder tels quels les blocs d'un compte
    illisible (verrouillé sans invite possible) : [SshKeyItem] dont `keep(alias)` est vrai (alias
    None : bloc d'ancienne forme, sans compte). Nom, hôtes (ligne `Match originalhost`), clé
    publique (`.pub` du bloc) et motifs de transfert (lignes `ensure --forward … --id
    <alias>:<id>`). Compte d'un bloc d'identité : celui de sa ligne `ensure --account` ; sans
    ligne exec (`auto-load false`), le dernier mot du commentaire seulement s'il est dans `known`
    (alias du registre) ; sinon bloc d'ancienne forme (le mot reste dans le nom). `renamed` :
    {ancien alias : nouveau} (`account rename`). `.pub` absent : bloc impossible à refaire,
    un avertissement dans `notes`. Fichier absent : []."""
    renamed = renamed or {}
    known = set(known or ())
    raw = read_private(paths.config)
    if raw is None:
        return []
    blocks = []  # blocs d'identité : dict
    forwards = {}  # (compte, id) -> [motifs]
    order = []  # références de transfert, dans l'ordre
    cur = None
    fwd = None
    for line in raw.decode(errors="replace").splitlines():
        if line.startswith(FORWARD_COMMENT):
            parts = line[len(FORWARD_COMMENT):].split()
            fwd = parts[0] if len(parts) == 2 and forward_id(parts[0]) == parts[1] else None
            cur = None
            continue
        if line.startswith("# "):
            fwd, cur = None, None
            name, _, iid = line[2:].rpartition(" ")
            if not ITEM_ID_RE.fullmatch(iid):
                continue
            head, _, word = name.rpartition(" ")
            cur = {"id": iid.lower(), "full": name, "head": head, "word": word if head and ALIAS_RE.fullmatch(word)
                   else None, "exec": None, "hosts": (), "pub": None}
            blocks.append(cur)
            continue
        m = re.match(r'Match originalhost (\S+) exec "(.*)"$', line)
        if m and fwd is not None:
            for ref in re.findall(r" --id (\S+)", m.group(2)):
                r = parse_ref(ref)
                if r is None:
                    continue
                if r not in forwards:
                    forwards[r] = []
                    order.append(r)
                if fwd not in forwards[r]:
                    forwards[r].append(fwd)
            continue
        if m and cur is not None:
            m2 = re.search(r" ensure --account (\S+) --id ", m.group(2))
            cur["exec"] = m2.group(1) if m2 else ""  # "" : ancienne forme, sans compte
            continue
        m = re.match(r"Match originalhost (\S+)$", line)
        if m and cur is not None:
            cur["hosts"] = tuple(h for h in m.group(1).split(",") if h)
            continue
        s_ = line.strip()
        if s_.startswith("IdentityFile ") and cur is not None:
            path = s_[len("IdentityFile "):].strip().strip('"').replace("%%", "%")
            pub = read_private(path) if os.path.dirname(path) == paths.pub else None
            cur["pub"] = pub.decode(errors="replace").strip() if pub else None
    found = {}  # (compte, id) -> (nom, hôtes, clé publique)
    for b in blocks:
        if b["exec"]:
            account = b["exec"]
        elif b["exec"] is None and b["word"] and b["word"] in known:
            account = b["word"]
        else:
            account = None
        name = b["head"] if account is not None and b["word"] == account else b["full"]
        if not b["pub"]:
            # clé publique perdue : bloc impossible à refaire à l'identique ; dit s'il devait être gardé
            if notes is not None and keep(renamed.get(account, account)):
                notes.append("bloc « %s » (%s%s) non gardé : sa clé publique a disparu de %s (« sshvault unlock » puis "
                             "« sshvault ssh-config » le refont)" % (clean(name), account + " " if account else "",
                                                                   b["id"], paths.pub))
            continue
        found.setdefault((account, b["id"]), (name, b["hosts"], b["pub"]))
    out = []
    for key in list(found) + [r for r in order if r not in found]:
        account, iid = key
        name, hosts, pub = found.get(key, (iid, (), ""))
        account = renamed.get(account, account)
        if not keep(account):
            continue
        out.append(SshKeyItem(id=iid, name=name, public_key=pub, fingerprint="", hosts=hosts,
                              forward=tuple(forwards.get(key, ())), account=account))
    return out


def unforwarded_literal_hosts(items: Sequence[SshKeyItem], plan: Plan) -> list:
    """Hôtes d'identité **littéraux** (sans `*` ni `?`) qu'aucun motif de transfert ne couvre,
    dans l'ordre des blocs."""
    patterns = [p for p, _ in plan.forward.values()]
    out = []
    for it in sorted(items, key=_order):
        if any(not valid_host(h) for h in it.hosts) or public_blob(it.public_key) is None:
            continue  # élément sauté par build
        for h in it.hosts:
            h = h.strip().lower()
            if "*" in h or "?" in h or h.startswith("-") or h in out:
                continue
            if not any(fnmatch.fnmatchcase(h, p) for p in patterns):
                out.append(h)
    return out


def forwardagent_yes(hosts: Sequence[str], paths: Paths, env=None, budget: Optional[float] = None):
    """(hôtes, interrompu) : hôtes pour lesquels `ssh -G <hôte>` (config réelle de l'utilisateur ;
    `-F ~/.ssh/config` seulement si le répertoire personnel est imposé, tests) affiche
    `forwardagent yes` : l'agent dédié entier y serait transféré. Un `ssh -G` en échec ou trop
    long est ignoré ; l'ensemble est borné par `budget` s (SSH_G_BUDGET) : au-delà, interrompu.
    `ssh -G` évalue les lignes `Match exec` de l'utilisateur ; celles de sshvault n'y chargent
    rien (`ssh -G` reconnu)."""
    import signal
    import subprocess
    import time
    env = os.environ if env is None else env
    deadline = time.monotonic() + (SSH_G_BUDGET if budget is None else budget)
    argv = [env.get("SSHVAULT_SSH") or "ssh", "-G"]
    if env.get(HOME_ENV):
        argv += ["-F", paths.user_config if _kind(paths.user_config) == "file" else os.devnull]
    out = []
    for h in hosts:
        left = deadline - time.monotonic()
        if left <= 0:
            return out, True
        try:
            # sa propre session : au délai, tout le groupe (lignes Match exec comprises) est tué
            p = subprocess.Popen(argv + ["--", h], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                 stdin=subprocess.DEVNULL, env=dict(env), start_new_session=True)
        except OSError:
            continue
        try:
            stdout, _ = p.communicate(timeout=min(SSH_G_TIMEOUT, left))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            p.communicate()
            if time.monotonic() >= deadline:
                return out, True
            continue
        if p.returncode == 0 and "forwardagent yes" in stdout.splitlines():
            out.append(h)
    return out, False


FORWARD_YES_WARNING = ("ForwardAgent yes dans ta config (ssh -G) : l'agent dédié entier (toutes les clés chargées "
                       "par sshvault) y serait transféré ; déclarer un transfert restreint (« sshvault forward add "
                       "… %s ») ou poser ForwardAgent no pour cet hôte")


@dataclass
class Applied:
    config_written: bool = False
    pubs_written: list = field(default_factory=list)
    pubs_removed: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@contextlib.contextmanager
def _locked(directory: str):
    """`flock` exclusif sur le dossier (aucun fichier créé), relâché à la fermeture."""
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _kind(path: str) -> str:
    """« absent », « file » (ordinaire), « link », « dir » ou « other » (FIFO, socket…)."""
    try:
        m = os.lstat(path).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return "absent"
    except OSError:
        return "unknown"  # dossier parent illisible
    return ("file" if stat.S_ISREG(m) else "link" if stat.S_ISLNK(m) else "dir" if stat.S_ISDIR(m)
            else "other")


def _live_tmp(name: str) -> bool:
    """Temporaire `.<nom>.<pid>.tmp` d'un autre processus encore vivant."""
    m = _TMP.match(name)
    if not m or int(m.group(1)) == os.getpid():
        return False
    try:
        os.kill(int(m.group(1)), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _dir_note(name: str) -> str:
    return "%s : dossier inattendu, laissé en place" % clean(name)


def _write_if_changed(path: str, data: bytes) -> bool:
    k = _kind(path)
    if k in ("dir", "other"):
        raise SshConfigError("%s n'est pas un fichier ordinaire : refusé" % clean(path))
    if k == "file" and read_private(path) == data:
        return False
    write_private(path, data)
    return True


def apply(plan: Plan, paths: Paths) -> Applied:
    """Écrit ce qui diffère, sous verrou : `.pub` d'abord, puis la config, puis purge de `pub/`."""
    res = Applied()
    try:
        ensure_dir(paths.dir)
        with _locked(paths.dir):
            ensure_dir(paths.pub)
            for name, data in sorted(plan.pubs.items()):
                if _write_if_changed(os.path.join(paths.pub, name), data):
                    res.pubs_written.append(name)
            res.config_written = _write_if_changed(paths.config, plan.config)
            for name in sorted(os.listdir(paths.pub)):
                if name in plan.pubs or _live_tmp(name):
                    continue
                p = os.path.join(paths.pub, name)
                if _kind(p) == "dir":
                    res.warnings.append(_dir_note(p))
                    continue
                os.unlink(p)
                res.pubs_removed.append(name)
    except OSError as e:  # NotADirectoryError d'ensure_dir compris
        where = " (%s)" % clean(str(e.filename)) if e.filename else ""
        raise SshConfigError("écriture du ssh_config généré : %s%s" % (clean(str(e.strerror or e)), where)) from None
    return res


def check(plan: Plan, paths: Paths):
    """(différences, avertissements) entre le plan et le disque ; rien n'est écrit. Mêmes
    règles qu'`apply` : un sous-dossier de `pub/` est signalé, pas compté comme différence."""
    diffs, warnings = [], []
    for d in (paths.dir, paths.pub):
        k = _kind(d)
        if k == "absent":
            continue
        if k != "dir":
            diffs.append("%s : pas un dossier" % d)
            continue
        m = stat.S_IMODE(os.lstat(d).st_mode)
        if m != 0o700:
            diffs.append("%s : droits %04o au lieu de 0700" % (d, m))
    for path, data, absent in [(paths.config, plan.config, "absent")] + [
            (os.path.join(paths.pub, n), b, "absente") for n, b in sorted(plan.pubs.items())]:
        k = _kind(path)
        if k in ("dir", "other"):
            diffs.append("%s : pas un fichier ordinaire" % path)
        elif k == "unknown":
            diffs.append("%s : illisible" % path)
        elif read_private(path) != data:
            diffs.append("%s : %s" % (path, absent if k == "absent" else "à réécrire"))
    if _kind(paths.pub) == "dir":
        try:
            names = sorted(os.listdir(paths.pub))
        except OSError as e:
            diffs.append("%s : illisible (%s)" % (paths.pub, e.strerror or e))
            names = []
        for name in names:
            if name in plan.pubs or _live_tmp(name):
                continue
            p = os.path.join(paths.pub, name)
            if _kind(p) == "dir":
                warnings.append(_dir_note(p))
            else:
                diffs.append("%s : en trop" % clean(p))
    return diffs, warnings


# --- ligne Include -----------------------------------------------------------------------

def _keyword(line: str):
    """(mot-clé en minuscules, reste) d'une ligne de ssh_config ; (None, None) si vide ou commentaire."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None, None
    m = _KEYWORD.match(s)
    return (m.group(1).lower(), m.group(2)) if m else ("", s)


def _ref_kinds(args_text: str, paths: Paths) -> list:
    """Pour chaque argument d'`Include` : « exact » s'il désigne le fichier généré lui-même (`~`,
    `~user`, relatif à ~/.ssh, chemin réel), « glob » si c'est un joker de glob qui le couvre
    (il peut couvrir d'autres fichiers), None sinon."""
    try:
        args = shlex.split(args_text, comments=True)
    except ValueError:
        return []
    target, real = os.path.normpath(paths.config), os.path.realpath(paths.config)
    out = []
    for a in args:
        if a == "~" or a.startswith("~/"):
            a = paths.home + a[1:]
        elif a.startswith("~"):
            a = os.path.expanduser(a)  # ~user : passwd
        if not os.path.isabs(a):
            a = os.path.join(paths.ssh_dir, a)
        a = os.path.normpath(a)
        glob = any(c in a for c in "*?[")
        out.append("exact" if not glob and (a == target or os.path.realpath(a) == real)
                   else "glob" if glob and fnmatch.fnmatchcase(target, a) else None)
    return out


def _refs(args_text: str, paths: Paths) -> list:
    """Pour chaque argument d'`Include` : désigne-t-il le fichier généré ? (`~`, `~user`,
    relatif à ~/.ssh, chemin réel, joker de glob)."""
    return [k is not None for k in _ref_kinds(args_text, paths)]


@dataclass
class Scan:
    lines: list
    head: bool = False
    ours: list = field(default_factory=list)  # (index, dans un bloc Host/Match, seul argument : le nôtre)

    @property
    def conditional(self) -> list:
        return [i for i, cond, _ in self.ours if cond]

    def state(self) -> str:
        if self.head:
            return "head"
        if self.conditional:
            return "conditional"
        return "below" if self.ours else "missing"


def scan(text: str, paths: Paths) -> Scan:
    """Lignes coupées sur « \n » seulement (comme ssh). En tête = l'`Include` est la première
    ligne qui n'est ni vide ni un commentaire ; après une ligne Host/Match, il est conditionnel."""
    sc = Scan(text.split("\n"))
    first, in_block = None, False
    for i, line in enumerate(sc.lines):
        kw, rest = _keyword(line)
        if kw is None:
            continue
        if first is None:
            first = i
        if kw in ("host", "match"):
            in_block = True
        elif kw == "include":
            refs = _refs(rest, paths)
            if any(refs):
                sc.ours.append((i, in_block, all(refs)))
                if i == first:
                    sc.head = True
    return sc


def _read_regular(path: str, follow: bool):
    """(données, stat) d'un fichier ordinaire, sans jamais bloquer (FIFO) ; SshConfigError sinon."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | (0 if follow else os.O_NOFOLLOW))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SshConfigError("%s n'est pas un fichier ordinaire : refusé, rien modifié" % path)
        chunks = []
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            chunks.append(b)
        return b"".join(chunks), st
    finally:
        os.close(fd)


def include_state(paths: Paths):
    """(état, scan ou None) ; état : « head », « below », « conditional », « missing »,
    « nofile », « notregular » ou « unreadable »."""
    try:
        data, _ = _read_regular(paths.user_config, follow=True)
    except FileNotFoundError:
        return "nofile", None
    except SshConfigError:
        return "notregular", None
    except OSError:
        return "unreadable", None
    sc = scan(data.decode(errors="surrogateescape"), paths)
    return sc.state(), sc


def include_warning(paths: Paths) -> Optional[str]:
    st, sc = include_state(paths)
    p = paths.user_config
    if st == "head":
        return None
    if st == "below":
        return ("la ligne Include de sshvault n'est pas en tête de %s : les lignes qui la précèdent l'emportent ; "
                "lancer « sshvault ssh-config install »" % p)
    if st == "conditional":
        exact = set(_own_includes(sc.lines, paths)[0])
        blocked = [i for i in sc.conditional if i in exact]
        if not blocked:  # joker ou ligne mixte : install ajoute l'Include exact en tête sans la toucher
            return ("%s ligne %d : Include conditionnel (dans un bloc Host/Match) : sshvault ne s'applique que dans ce "
                    "bloc ; lancer « sshvault ssh-config install »" % (p, sc.conditional[0] + 1))
        return ("%s ligne %d : Include conditionnel (dans un bloc Host/Match) : sshvault ne s'applique que dans ce "
                "bloc ; le sortir du bloc, puis « sshvault ssh-config install »" % (p, blocked[0] + 1))
    if st == "unreadable":
        return "%s illisible : ligne Include de sshvault non vérifiée" % p
    if st == "notregular":
        return "%s n'est pas un fichier ordinaire : ligne Include de sshvault non vérifiée" % p
    return "%s n'inclut pas %s : ssh ne s'en sert pas ; lancer « sshvault ssh-config install »" % (p, paths.config)


def _tmp_write(path: str, data: bytes, mode: int, uid: int, gid: int) -> str:
    d, base = os.path.split(path)
    tmp = os.path.join(d, ".%s.sshvault.%d.tmp" % (base, os.getpid()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        try:
            os.write(fd, data)
            os.fsync(fd)
            if (uid, gid) != (os.getuid(), os.getgid()):
                os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
    except BaseException:
        _unlink_quiet(tmp)
        raise
    return tmp


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _replace(path: str, data: bytes, mode: int, uid: int, gid: int, expect=None) -> None:
    """Remplacement atomique (temporaire dans le même dossier puis rename) avec mode et
    propriétaire donnés. `expect` : (st_ino, st_size, st_mtime_ns) que `path` doit encore
    avoir juste avant le rename (sinon rien n'est remplacé)."""
    tmp = _tmp_write(path, data, mode, uid, gid)
    try:
        if expect is not None:
            st = os.lstat(path)
            if (st.st_ino, st.st_size, st.st_mtime_ns) != expect:
                raise SshConfigError("%s modifié pendant l'écriture : rien changé, relancer" % path)
        os.replace(tmp, path)
    except BaseException:
        _unlink_quiet(tmp)
        raise


def _create(path: str, data: bytes, mode: int) -> None:
    """Crée `path` seulement s'il n'existe pas (link d'un temporaire) : FileExistsError sinon."""
    tmp = _tmp_write(path, data, mode, os.getuid(), os.getgid())
    try:
        os.link(tmp, path)
    finally:
        _unlink_quiet(tmp)


def _backup(paths: Paths, data: bytes) -> str:
    """Sauvegarde jamais écrasée : `config.sshvault.bak`, sinon `.bak.1`, `.bak.2`…"""
    for n in range(1000):
        p = paths.backup + ("" if n == 0 else ".%d" % n)
        try:
            _create(p, data, 0o600)
            return p
        except FileExistsError:
            continue
    raise SshConfigError("trop de sauvegardes %s.N : en supprimer avant de relancer" % paths.backup)


@dataclass
class Installed:
    message: str
    warnings: list = field(default_factory=list)  # une ligne chacun (stderr, code 0)


def install(paths: Paths) -> Installed:
    """Met `Include "<config>"` en première ligne de ~/.ssh/config ; renvoie le message et les
    avertissements. Seules les lignes `Include` dont tous les arguments désignent exactement le
    fichier généré (« exact ») sont les siennes : déplacées en tête, ou refus (code 4, rien
    modifié) si l'une est dans un bloc Host/Match. Une ligne à joker ou mixte (qui couvre aussi
    d'autres fichiers) n'est jamais supprimée ni déplacée, même dans un bloc : l'`Include` exact
    est ajouté en tête et elle reste, avec un avertissement (fichier généré inclus deux fois,
    sans effet néfaste : la première valeur rencontrée gagne ; ses `Match exec` sont évalués deux
    fois à chaque lecture de la config : `ensure` lancé deux fois, le second trouve la clé déjà
    chargée quand le premier l'a chargée). Ligne de sshvault déjà en tête
    (même à joker) : rien changé."""
    p = paths.user_config
    line = include_line(paths)
    try:
        for _ in range(3):
            k = _kind(p)
            if k == "link":
                raise SshConfigError("%s est un lien symbolique : refusé, rien modifié" % p)
            if k == "absent":
                if not os.path.isdir(paths.ssh_dir):
                    ensure_dir(paths.ssh_dir)  # créé en 0700 ; un ~/.ssh existant n'est pas touché
                try:
                    _create(p, (line + "\n").encode(), 0o600)
                except FileExistsError:
                    continue  # créé entre-temps par un autre : chemin normal
                return Installed("%s créé : %s" % (p, line))
            if k != "file":
                raise SshConfigError("%s n'est pas un fichier ordinaire : refusé, rien modifié" % p)
            try:
                data, st = _read_regular(p, follow=False)
            except FileNotFoundError:
                continue
            sc = scan(data.decode(errors="surrogateescape"), paths)
            if sc.head:
                return Installed("%s : ligne Include déjà en tête, rien changé" % p)
            exact, kept = _own_includes(sc.lines, paths)
            blocked = [i for i in exact if i in set(sc.conditional)]
            if blocked:
                raise SshConfigError("%s ligne %d : la ligne Include de sshvault est dans un bloc Host/Match (Include "
                                     "conditionnel) : non déplacée, rien modifié ; la sortir de ce bloc ou la "
                                     "supprimer, puis relancer" % (p, blocked[0] + 1))
            drop = set(exact)
            new = "\n".join([line] + [l for i, l in enumerate(sc.lines) if i not in drop])
            warnings = []
            for i in kept:  # numéro de ligne du fichier réécrit (Include ajouté en tête)
                n = i + 2 - len([j for j in drop if j < i])
                warnings.append("%s ligne %d : Include de sshvault avec d'autres fichiers (ou joker) : ligne gardée ; "
                                "« %s » désormais inclus deux fois (en tête et ici), sans effet néfaste : la "
                                "première valeur rencontrée gagne ; ses lignes Match exec sont évaluées deux fois "
                                "à chaque lecture de la config (« sshvault ensure » lancé deux fois : le second "
                                "trouve la clé déjà chargée quand le premier l'a chargée)" % (p, n, paths.config))
            bak = _backup(paths, data)
            _replace(p, new.encode(errors="surrogateescape"), stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid,
                     expect=(st.st_ino, st.st_size, st.st_mtime_ns))
            return Installed("%s : ligne Include %s en tête (sauvegarde : %s)"
                             % (p, "déplacée" if drop else "ajoutée", bak), warnings)
    except OSError as e:
        raise SshConfigError("%s : %s" % (p, e.strerror or e)) from None
    raise SshConfigError("%s : créé ou supprimé pendant l'installation : rien changé, relancer" % p)


# --- désinstallation -----------------------------------------------------------------------

@dataclass
class Uninstalled:
    done: list = field(default_factory=list)  # ce qui a été retiré, une ligne chacun
    warnings: list = field(default_factory=list)
    kept: list = field(default_factory=list)  # numéros des lignes Include gardées (fichier réécrit)


def _own_includes(lines: list, paths: Paths):
    """(index des lignes `Include` qui ne désignent que le fichier généré, où qu'elles soient :
    en tête, plus bas ou dans un bloc Host/Match ; index des lignes qui le désignent avec
    d'autres fichiers ou par un joker de glob)."""
    sole, mixed = [], []
    for i, line in enumerate(lines):
        kw, rest = _keyword(line)
        if kw != "include":
            continue
        kinds = _ref_kinds(rest, paths)
        if kinds and all(k == "exact" for k in kinds):
            sole.append(i)
        elif any(kinds):
            mixed.append(i)
    return sole, mixed


def uninstall(paths: Paths) -> Uninstalled:
    """Défait `install` et ce qu'écrit `apply`, rien d'autre : lignes `Include` qui ne désignent
    que le fichier généré retirées de ~/.ssh/config (sauvegarde `config.sshvault.bak*` d'abord ;
    mode et propriétaire gardés) ; une ligne qui inclut aussi d'autres fichiers (ou un joker qui
    le couvre) est gardée, avec un avertissement ; `~/.ssh/sshvault/config` supprimé ; dans
    `pub/`, seuls les `*.pub` (fichiers ordinaires) supprimés, le dossier s'il est vide.
    `~/.ssh/sshvault/` lui-même est gardé. Refus, rien modifié (SshConfigError, code 4) :
    ~/.ssh/config lien symbolique ou non ordinaire, `~/.ssh/sshvault`, sa config ou `pub/` d'un
    type inattendu. Sous le verrou du dossier (une régénération concurrente attend). Rien
    d'installé : `done` vide."""
    res = Uninstalled()
    p = paths.user_config

    def refuse(path, what):
        raise SshConfigError("%s %s : refusé, rien modifié" % (clean(path), what))
    try:
        k = _kind(p)
        if k == "link":
            refuse(p, "est un lien symbolique")
        if k not in ("absent", "file"):
            refuse(p, "n'est pas un fichier ordinaire")
        dk = _kind(paths.dir)
        if dk not in ("absent", "dir"):
            refuse(paths.dir, "n'est pas un dossier")
        with _locked(paths.dir) if dk == "dir" else contextlib.nullcontext():
            ck, pk = _kind(paths.config), _kind(paths.pub)
            if ck not in ("absent", "file"):
                refuse(paths.config, "n'est pas un fichier ordinaire")
            if pk not in ("absent", "dir"):
                refuse(paths.pub, "n'est pas un dossier")
            data = st = None
            sole, mixed, lines = [], [], []
            if k == "file":
                try:
                    data, st = _read_regular(p, follow=False)
                except FileNotFoundError:
                    data = None
                if data is not None:
                    lines = data.decode(errors="surrogateescape").split("\n")
                    sole, mixed = _own_includes(lines, paths)
            pubs = []
            if pk == "dir":
                pubs = [n for n in sorted(os.listdir(paths.pub))
                        if n.endswith(".pub") and _kind(os.path.join(paths.pub, n)) == "file"]
            # 1) ligne Include : ssh cesse d'abord de lire les fichiers générés
            for i in mixed:  # numéro de ligne du fichier réécrit
                n = i + 1 - len([j for j in sole if j < i])
                res.kept.append(n)
                res.warnings.append("%s ligne %d : Include de sshvault avec d'autres fichiers : ligne gardée ; y retirer "
                                    "« %s » à la main" % (p, n, paths.config))
            if sole:
                new = "\n".join(l for i, l in enumerate(lines) if i not in set(sole))
                bak = _backup(paths, data)
                _replace(p, new.encode(errors="surrogateescape"), stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid,
                         expect=(st.st_ino, st.st_size, st.st_mtime_ns))
                res.done.append("%s : ligne%s Include de sshvault retirée%s (sauvegarde : %s)"
                                % (p, "s" if len(sole) > 1 else "", "s" if len(sole) > 1 else "", bak))
            # 2) fichiers générés
            try:
                if ck == "file":
                    os.unlink(paths.config)
                    res.done.append("%s supprimé" % paths.config)
                for n in pubs:
                    os.unlink(os.path.join(paths.pub, n))
                if pk == "dir":
                    left = os.listdir(paths.pub)
                    if not left:
                        os.rmdir(paths.pub)
                    else:
                        res.warnings.append("%s gardé : %d entrée%s autre%s que des clés publiques"
                                            % (paths.pub, len(left), "s" if len(left) > 1 else "",
                                               "s" if len(left) > 1 else ""))
                    if pubs or not left:
                        res.done.append("%s : %d clé%s publique%s supprimée%s%s"
                                        % (paths.pub, len(pubs), "s" if len(pubs) > 1 else "", "s" if len(pubs) > 1 else "",
                                           "s" if len(pubs) > 1 else "", ", dossier supprimé" if not left else ""))
            except OSError as e:
                where = " (%s)" % clean(str(e.filename)) if e.filename else ""
                raise SshConfigError("désinstallation : %s%s ; déjà fait : %s ; relancer « sshvault ssh-config uninstall »"
                                     % (clean(str(e.strerror or e)), where, " ; ".join(res.done) or "rien")) from None
    except OSError as e:
        raise SshConfigError("%s : %s" % (clean(str(e.filename or p)), e.strerror or e)) from None
    return res

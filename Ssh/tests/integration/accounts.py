"""Fichier des comptes de test d'intégration (`accounts.toml`) : lecture et contrôle, sans réseau.

Format (exemple : `tests/integration/accounts.example.toml`) :

    node_extra_ca_certs = "/chemin/ca.pem"   # optionnel, pour tous les comptes

    [[account]]                               # 1er : alias `it` (coffre peuplé)
    server = "https://vault.example.org"
    email = "test1@example.org"
    password = "…"

    [[account]]                               # 2e : `it2`, puis `it3`…
    …

Chemin : `SSHVAULT_IT_ACCOUNTS` (`~` développé ; chemin absent, lien cassé, autre chose qu'un
fichier ordinaire ou illisible : échec de la session), sinon
`~/.config/sshvault-test/accounts.toml` (0600, hors git ; absent : intégration sautée ; présent
sans être un fichier ordinaire utilisable : échec). Aucune valeur du fichier (serveur, e-mail, mot de passe, chemin du certificat) n'apparaît
dans un message : les erreurs nomment le numéro du compte (à partir de 1) et la clé ; une erreur
de syntaxe TOML ne donne que la ligne et la colonne. `account.env` et `SSHVAULT_IT_ENV`
(format précédent) ne sont plus lus.
"""
import os
import re
import stat
import sys
from urllib.parse import urlsplit

from sshvault.config import ConfigError, normalize_email, normalize_server

if sys.version_info >= (3, 11):
    import tomllib
else:  # dépendance de test seule (groupe dev), jamais de sshvault
    import tomli as tomllib

ENV_PATH = "SSHVAULT_IT_ACCOUNTS"
LEGACY_ENV = "SSHVAULT_IT_ENV"
FIELDS = ("server", "email", "password")
TOP = ("account", "node_extra_ca_certs")
EXAMPLE = "tests/integration/accounts.example.toml"


class AccountsError(Exception):
    """Fichier des comptes inutilisable : échec de la session d'intégration (message sans valeur)."""


def config_dir(home=None):
    return os.path.join(home or os.path.expanduser("~"), ".config", "sshvault-test")


def default_path(home=None):
    return os.path.join(config_dir(home), "accounts.toml")


def legacy_path(home=None):
    return os.path.join(config_dir(home), "account.env")


def _unusable(path):
    """Pourquoi `path` n'est pas un fichier ordinaire utilisable (None : il l'est) : « absent »,
    « lien cassé », « pas un fichier ordinaire » ou le texte de l'erreur du système."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return "lien cassé" if os.path.islink(path) else "absent"
    except OSError as e:
        return e.strerror or str(e)
    return None if stat.S_ISREG(st.st_mode) else "pas un fichier ordinaire"


def locate(env=None, home=None):
    """(chemin du fichier, None) ou (None, raison du saut : fichier par défaut absent) ;
    AccountsError, chemin et raison nommés (jamais une valeur du fichier), si SSHVAULT_IT_ENV est
    défini (ancien format, jamais lu), si SSHVAULT_IT_ACCOUNTS (`~` développé) désigne un chemin
    absent, un lien cassé, autre chose qu'un fichier ordinaire ou un chemin illisible, ou si le
    fichier par défaut existe sans être un fichier ordinaire utilisable."""
    env = os.environ if env is None else env
    if env.get(LEGACY_ENV):
        raise AccountsError("%s n'est plus lu (comptes de test en TOML) : désigner le fichier des comptes par %s "
                            "(défaut : %s ; exemple : %s), puis retirer %s"
                            % (LEGACY_ENV, ENV_PATH, default_path(home), EXAMPLE, LEGACY_ENV))
    chosen = os.path.expanduser(env.get(ENV_PATH) or "")
    path = chosen or default_path(home)
    bad = _unusable(path)
    if bad is None:
        return path, None
    if chosen:
        raise AccountsError("%s désigne %s : %s : corriger le chemin, ou retirer %s (défaut : %s)"
                            % (ENV_PATH, path, bad, ENV_PATH, default_path(home)))
    if bad != "absent":
        raise AccountsError("fichier des comptes de test %s : %s : y mettre un fichier ordinaire (0600), ou désigner "
                            "le fichier par %s" % (path, bad, ENV_PATH))
    why = "fichier des comptes de test absent (%s ; chemin par %s)" % (path, ENV_PATH)
    if os.path.exists(legacy_path(home)):
        why += " ; %s (ancien format) n'est plus lu : écrire accounts.toml d'après %s" % (legacy_path(home), EXAMPLE)
    return None, why


def _position(e):
    """Ligne et colonne d'une erreur TOML (attributs depuis 3.14 et tomli 2.x, sinon le
    suffixe « (at line L, column C) » du message), jamais le reste du message."""
    line, col = getattr(e, "lineno", None), getattr(e, "colno", None)
    if line is None:
        m = re.search(r"\(at line (\d+), column (\d+)\)\s*$", str(e))
        if m:
            line, col = int(m.group(1)), int(m.group(2))
    if line is None:
        return "position inconnue"
    return "ligne %d, colonne %d" % (line, col)


class Account:
    """Identifiants d'un compte de test ; jamais affichés."""

    def __init__(self, server, email, password, extra_env=None):
        self._v = {"server": server, "email": email, "password": password}
        self.extra_env = dict(extra_env or {})

    server = property(lambda self: self._v["server"])
    email = property(lambda self: self._v["email"])
    password = property(lambda self: self._v["password"])

    def __repr__(self):
        return "<Account masqué>"

    __str__ = __repr__

    def masks(self):
        """[(valeur, étiquette)] à masquer : valeurs brutes, e-mail en minuscules, serveur tel que
        sshvault l'affiche (normalisé : hôte en minuscules, sans `/` final ni port par défaut) et
        son seul nom d'hôte (`ENOTFOUND <hôte>` de bw), chemin du certificat."""
        out = [(v, "<%s>" % k) for k, v in self._v.items() if v]
        if self._v["email"]:
            out.append((self._v["email"].lower(), "<email>"))
        try:
            server = normalize_server(self._v["server"])
            out += [(server, "<server>"), (urlsplit(server).hostname, "<server-host>")]
        except ConfigError:
            pass
        ca = self.extra_env.get("NODE_EXTRA_CA_CERTS")
        if ca:
            out.append((ca, "<node_extra_ca_certs>"))
        return [(v, label) for v, label in out if v]

    def scrub(self, text):
        return scrub_with(self.masks(), text)


def scrub_with(masks, text):
    """Remplace chaque valeur, la plus longue d'abord (toutes listes confondues) : une valeur
    contenue dans une autre ne la laisse jamais à moitié visible."""
    text = str(text)
    for v, label in sorted(masks, key=lambda m: -len(m[0])):
        text = text.replace(v, label)
    return text


def parse(data):
    """`data` (octets ou texte) → (liste de dicts {server, email, password}, environnement
    commun) ; AccountsError (toutes les erreurs, une par ligne, sans valeur) sinon."""
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise AccountsError("fichier des comptes : pas de l'UTF-8 (octet %d)" % (e.start + 1)) from None
    try:
        doc = tomllib.loads(data)
    except tomllib.TOMLDecodeError as e:
        raise AccountsError("fichier des comptes : TOML illisible (%s)" % _position(e)) from None
    errors = []
    for k in doc:
        if k not in TOP:
            errors.append("clé inconnue au premier niveau : %s" % k)
    extra = {}
    ca = doc.get("node_extra_ca_certs")
    if "node_extra_ca_certs" in doc:
        if not isinstance(ca, str):
            errors.append("node_extra_ca_certs : chaîne attendue")
        elif not ca.strip():
            errors.append("node_extra_ca_certs : vide")
        else:
            # absolu : bw tourne depuis un autre dossier ; vérifié ici, sinon bw ne dirait plus
            # tard qu'une erreur TLS peu claire
            ca = os.path.abspath(os.path.expanduser(ca.strip()))
            if not os.path.isfile(ca):
                errors.append("node_extra_ca_certs : fichier ordinaire absent")
            elif not os.access(ca, os.R_OK):
                errors.append("node_extra_ca_certs : fichier illisible")
            else:
                extra["NODE_EXTRA_CA_CERTS"] = ca
    raw = doc.get("account")
    accounts = []
    if raw is None:
        errors.append("aucun compte ([[account]])")
        raw = []
    elif not isinstance(raw, list) or not all(isinstance(a, dict) for a in raw):
        errors.append("account : tableau de tables attendu ([[account]])")
        raw = []
    elif not raw:
        errors.append("aucun compte ([[account]])")
    seen = {}
    for n, a in enumerate(raw, 1):
        bad = False
        for k in a:
            if k not in FIELDS:
                errors.append("compte %d : clé inconnue : %s" % (n, k))
                bad = True
        for k in FIELDS:
            v = a.get(k)
            if k not in a:
                errors.append("compte %d : %s manquant" % (n, k))
                bad = True
            elif not isinstance(v, str):
                errors.append("compte %d : %s : chaîne attendue" % (n, k))
                bad = True
            elif not v.strip():
                errors.append("compte %d : %s vide" % (n, k))
                bad = True
        if bad:
            continue
        server, email = a["server"].strip(), a["email"].strip()
        try:
            key = (normalize_server(server), None)
        except ConfigError:
            errors.append("compte %d : server invalide (URL https://hôte[:port][/chemin] attendue)" % n)
            continue
        try:
            key = (key[0], normalize_email(email))
        except ConfigError:
            errors.append("compte %d : email invalide" % n)
            continue
        if key in seen:
            errors.append("comptes %d et %d : même serveur et même e-mail (doublon)" % (seen[key], n))
            continue
        seen[key] = n
        accounts.append({"server": server, "email": email, "password": a["password"]})
    if errors:
        raise AccountsError("fichier des comptes : " + " ; ".join(errors))
    return accounts, extra


def mode_warning(st, path):
    """Avertissement (sans valeur) si le fichier est ouvert au groupe ou aux autres (un droit
    quelconque), ou n'est pas à l'utilisateur ; None sinon. Jamais un échec (décision du
    2026-10-14)."""
    why = []
    if st.st_mode & 0o077:
        why.append("droits %04o (ouvert au groupe ou aux autres)" % stat.S_IMODE(st.st_mode))
    if st.st_uid != os.getuid():
        why.append("propriétaire uid %d, pas l'utilisateur" % st.st_uid)
    if not why:
        return None
    return "fichier des comptes de test %s : %s : « chmod 600 » conseillé (identifiants)" % (path, ", ".join(why))


def load(path):
    """Lit et contrôle le fichier `path` → (comptes, environnement commun, avertissements) ;
    AccountsError (sans valeur) s'il est inutilisable."""
    try:
        with open(path, "rb") as f:
            st = os.fstat(f.fileno())
            data = f.read()
    except OSError as e:
        raise AccountsError("fichier des comptes %s illisible : %s" % (path, e.strerror or type(e).__name__)) from None
    w = mode_warning(st, path)
    found, extra = parse(data)
    return found, extra, [w] if w else []


def alias(n):
    """Alias sshvault du compte d'index `n` (à partir de 0) : `it`, `it2`, `it3`…"""
    return "it" if n == 0 else "it%d" % (n + 1)


class Scrub:
    """Masque les valeurs de **tous** les comptes de test (rapport, messages d'échec) : valeurs
    de tous les comptes réunies, la plus longue remplacée d'abord."""

    def __init__(self, accounts):
        self.accounts = list(accounts)

    def scrub(self, text):
        return scrub_with([m for a in self.accounts for m in a.masks()], text)

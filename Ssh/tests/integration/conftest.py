"""Cible des tests d'intégration : compte de test dédié (défaut) ou conteneur local.

Deux modes :
- **compte de test** (défaut) : identifiants dans `~/.config/sshvault-test/account.env`
  (chemin remplaçable par SSHVAULT_IT_ENV) : SSHVAULT_IT_SERVER, SSHVAULT_IT_EMAIL,
  SSHVAULT_IT_PASSWORD, NODE_EXTRA_CA_CERTS en option ; second compte (volet deux comptes,
  CAP-10, créé par l'utilisateur) : SSHVAULT_IT2_SERVER, SSHVAULT_IT2_EMAIL,
  SSHVAULT_IT2_PASSWORD, sans eux ce volet est sauté (dit dans le rapport). Ces valeurs ne sont jamais
  affichées, journalisées ni comparées dans une assertion : `Account` masque son repr
  et `scrub()` les retire de tout message d'échec ;
- **conteneur** (SSHVAULT_IT_MODE=container) : `vaultwarden/server:1.37.4` sous docker,
  port libre de 127.0.0.1, données temporaires, comptes créés par `register.py` (le second à
  la demande),
  conteneur supprimé à la fin.
Ignoré si `bw` manque, ou si ni le fichier ni (en mode conteneur) docker ne sont disponibles.
"""
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import pytest

IMAGE = "vaultwarden/server:1.37.4"
NAME_PREFIX = "sshvault-it-"
DEFAULT_ENV_FILE = os.path.join(os.path.expanduser("~"), ".config", "sshvault-test", "account.env")
KEYS = ("SSHVAULT_IT_SERVER", "SSHVAULT_IT_EMAIL", "SSHVAULT_IT_PASSWORD", "NODE_EXTRA_CA_CERTS")
KEYS2 = ("SSHVAULT_IT2_SERVER", "SSHVAULT_IT2_EMAIL", "SSHVAULT_IT2_PASSWORD")


class Account:
    """Identifiants du compte de test ; jamais affichés."""

    def __init__(self, server, email, password, extra_env=None):
        self._v = {"server": server, "email": email, "password": password}
        self.extra_env = dict(extra_env or {})

    server = property(lambda self: self._v["server"])
    email = property(lambda self: self._v["email"])
    password = property(lambda self: self._v["password"])

    def __repr__(self):
        return "<Account masqué>"

    __str__ = __repr__

    def scrub(self, text):
        text = str(text)
        for k, v in self._v.items():
            if v:
                text = text.replace(v, "<%s>" % k)
                if k == "email":
                    text = text.replace(v.lower(), "<%s>" % k)
        return text


def load_account_env(path):
    """KEY=VALUE par ligne, commentaires (#) et lignes vides ignorés, guillemets retirés."""
    vals = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[len("export "):].strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            if k in KEYS or k in KEYS2:
                vals[k] = v
    return vals


def bw_path():
    exe = os.environ.get("SSHVAULT_BW") or shutil.which("bw")
    return exe if exe and os.access(exe, os.X_OK) else None


def docker_ok():
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def bw_exe():
    exe = bw_path()
    if not exe:
        pytest.skip("bw introuvable (SSHVAULT_BW ou PATH)")
    return exe


def _container(tmp_path_factory):
    if not docker_ok():
        pytest.skip("mode conteneur : docker indisponible")
    data = tmp_path_factory.mktemp("vw-data")
    port = free_port()
    name = NAME_PREFIX + uuid.uuid4().hex[:10]
    url = "http://127.0.0.1:%d" % port
    cmd = ["docker", "run", "-d", "--name", name, "--user", "%d:%d" % (os.getuid(), os.getgid()),
           "-p", "127.0.0.1:%d:8080" % port, "-v", "%s:/data" % data,
           "-e", "ROCKET_PORT=8080", "-e", "DOMAIN=%s" % url, "-e", "SIGNUPS_ALLOWED=true",
           "-e", "SIGNUPS_VERIFY=false", "-e", "LOG_LEVEL=warn", IMAGE]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            pytest.fail("docker run : %s" % r.stderr.strip())
        deadline = time.monotonic() + 90
        while True:
            try:
                with urllib.request.urlopen(url + "/alive", timeout=2) as resp:
                    if resp.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() > deadline:
                logs = subprocess.run(["docker", "logs", "--tail", "30", name], capture_output=True, text=True)
                pytest.fail("Vaultwarden ne répond pas sur %s : %s" % (url, logs.stderr[-2000:]))
            time.sleep(0.5)
        from register import register  # dépendance de test `cryptography`
        email = "it-%s@example.test" % uuid.uuid4().hex[:8]
        password = "integration pass phrase " + uuid.uuid4().hex[:8]
        register(url, email, password)
        acct = Account(url, email, password)
        acct.container_url = url  # second compte inscrit à la demande (fixture account2)
        yield acct
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, timeout=120)
        left = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "name=" + name],
                              capture_output=True, text=True).stdout.strip()
        assert not left, "conteneur de test %s encore présent" % name


@pytest.fixture(scope="session")
def account(tmp_path_factory, bw_exe):
    """Compte cible : fichier du compte de test (défaut) ou conteneur (SSHVAULT_IT_MODE=container)."""
    mode = os.environ.get("SSHVAULT_IT_MODE", "account")
    if mode == "container":
        yield from _container(tmp_path_factory)
        return
    if mode != "account":
        pytest.fail("SSHVAULT_IT_MODE inconnu (account ou container)")
    path = os.environ.get("SSHVAULT_IT_ENV") or DEFAULT_ENV_FILE
    if not os.path.isfile(path):
        pytest.skip("compte de test absent (SSHVAULT_IT_ENV ou ~/.config/sshvault-test/account.env) ; "
                    "mode conteneur : SSHVAULT_IT_MODE=container")
    vals = load_account_env(path)
    missing = [k for k in KEYS[:3] if not vals.get(k)]
    if missing:
        pytest.skip("compte de test incomplet : %s manquant(s)" % ", ".join(missing))
    extra = {"NODE_EXTRA_CA_CERTS": vals["NODE_EXTRA_CA_CERTS"]} if vals.get("NODE_EXTRA_CA_CERTS") else {}
    yield Account(vals["SSHVAULT_IT_SERVER"], vals["SSHVAULT_IT_EMAIL"], vals["SSHVAULT_IT_PASSWORD"], extra)


@pytest.fixture(scope="session")
def account2(account):
    """Second compte (CAP-10) : SSHVAULT_IT2_* du fichier du compte de test (créé par
    l'utilisateur), ou inscrit dans le conteneur ; None s'il manque (volet deux comptes sauté)."""
    url = getattr(account, "container_url", None)
    if url:
        from register import register
        email = "it2-%s@example.test" % uuid.uuid4().hex[:8]
        password = "integration pass phrase 2 " + uuid.uuid4().hex[:8]
        register(url, email, password)
        return Account(url, email, password)
    path = os.environ.get("SSHVAULT_IT_ENV") or DEFAULT_ENV_FILE
    vals = load_account_env(path) if os.path.isfile(path) else {}
    if not all(vals.get(k) for k in KEYS2):
        return None
    return Account(vals["SSHVAULT_IT2_SERVER"], vals["SSHVAULT_IT2_EMAIL"], vals["SSHVAULT_IT2_PASSWORD"],
                   account.extra_env)

"""Cible des tests d'intégration : comptes de test dédiés (défaut) ou conteneur local.

Deux modes :
- **comptes de test** (défaut) : fichier TOML `~/.config/sshvault-test/accounts.toml` (0600 ;
  chemin remplaçable par SSHVAULT_IT_ACCOUNTS ; format et contrôles : `accounts.py`, exemple :
  `accounts.example.toml`) : un `[[account]]` par compte (`server`, `email`, `password`),
  `node_extra_ca_certs` commun en option. Le 1er compte est `it` (coffre peuplé), les suivants
  `it2`, `it3`… (volet plusieurs comptes, CAP-10 ; un seul compte : volet sauté, dit dans le
  rapport). Fichier absent : intégration sautée ; fichier invalide (clé inconnue, champ
  manquant ou vide, type faux, doublon, TOML illisible) ou SSHVAULT_IT_ENV défini (ancien
  format `account.env`, jamais lu) : échec. Ces valeurs ne sont jamais affichées,
  journalisées ni comparées dans une assertion : `Account` masque son repr et `scrub()` les
  retire de tout message d'échec ;
- **conteneur** (SSHVAULT_IT_MODE=container) : `vaultwarden/server:1.37.4` sous docker,
  port libre de 127.0.0.1, données temporaires, 3 comptes inscrits par `register.py`,
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
import sys
import uuid

import pytest

from accounts import Account, AccountsError, alias, load as load_accounts, locate

IMAGE = "vaultwarden/server:1.37.4"
NAME_PREFIX = "sshvault-it-"
#: comptes inscrits dans le conteneur (volet plusieurs comptes : it, it2, it3)
CONTAINER_ACCOUNTS = 3


def pytest_configure(config):
    # traceback court : le format long affiche la valeur des fixtures (sessions bw, clés de
    # test, environnement) dans la sortie d'un échec
    if config.option.tbstyle in ("auto", "long"):
        config.option.tbstyle = "short"


class AccountList(list):
    """Comptes de test, dans l'ordre du fichier ; `warnings` : avertissements sur le fichier
    (droits, propriétaire), repris dans le rapport."""
    warnings = ()


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
        accts = []
        for n in range(CONTAINER_ACCOUNTS):
            email = "%s-%s@example.test" % (alias(n), uuid.uuid4().hex[:8])
            password = "integration pass phrase %d %s" % (n + 1, uuid.uuid4().hex[:8])
            register(url, email, password)
            accts.append(Account(url, email, password))
        yield AccountList(accts)
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, timeout=120)
        left = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "name=" + name],
                              capture_output=True, text=True).stdout.strip()
        assert not left, "conteneur de test %s encore présent" % name


@pytest.fixture(scope="session")
def accounts(tmp_path_factory, bw_exe, pytestconfig):
    """Comptes cibles, dans l'ordre du fichier (le 1er est `it`) : fichier des comptes de test
    (défaut) ou conteneur (SSHVAULT_IT_MODE=container, 3 comptes)."""
    mode = os.environ.get("SSHVAULT_IT_MODE", "account")
    if mode == "container":
        yield from _container(tmp_path_factory)
        return
    if mode != "account":
        pytest.fail("SSHVAULT_IT_MODE inconnu (account ou container)")
    try:
        path, why = locate()
        if path is None:
            pytest.skip(why + " ; mode conteneur : SSHVAULT_IT_MODE=container")
        found, extra, notes = load_accounts(path)
    except AccountsError as e:
        pytest.fail(str(e), pytrace=False)
    # droits ou propriétaire : avertissement seul, écrit dans la sortie de pytest (jamais par
    # `warnings` : `-W error` en ferait une erreur) et dans le rapport
    tr = pytestconfig.pluginmanager.get_plugin("terminalreporter")
    for w in notes:
        if tr is not None:
            tr.write_line("avertissement : " + w, yellow=True)
        else:
            print("avertissement : " + w, file=sys.__stderr__, flush=True)
    out = AccountList(Account(a["server"], a["email"], a["password"], extra) for a in found)
    out.warnings = list(notes)
    yield out


@pytest.fixture(scope="session")
def account(accounts):
    """1er compte du fichier (`it`) : celui du coffre peuplé."""
    return accounts[0]

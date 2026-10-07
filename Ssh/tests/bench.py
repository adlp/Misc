"""Banc des tests de sshvault (fixtures exposées par conftest.py) : faux bw, HOME et XDG temporaires, anneau de clés dédié.

Le processus pytest rejoint une session keyring anonyme neuve (ce que fait
`keyctl session -`) ; chaque test crée dans cette session un anneau dédié, passé à
sshvault par SSHVAULT_KEYRING. Le `@u` réel n'est jamais utilisé : sans anneau
dédié, les tests passent SSHVAULT_KEYCTL=/nonexistent (repli fichier).
"""
import ctypes
import json
import os
import pathlib
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
FAKE_BW = os.path.join(HERE, "fake_bw.py")
PASSWORD = "correct horse battery staple"
EMAIL = "alice@example.test"


# --- session keyring dédiée -----------------------------------------------------

def _join_new_session_keyring() -> bool:
    if not shutil.which("keyctl"):
        return False
    try:
        lib = ctypes.CDLL("libkeyutils.so.1", use_errno=True)
    except OSError:
        return False
    lib.keyctl_join_session_keyring.restype = ctypes.c_long
    if lib.keyctl_join_session_keyring(None) < 0:
        return False
    r = subprocess.run(["keyctl", "show", "@s"], capture_output=True, text=True)
    return r.returncode == 0


@pytest.fixture(scope="session")
def keyring_ok():
    return _join_new_session_keyring()


@pytest.fixture
def ring(keyring_ok):
    """Anneau dédié au test (dans la session keyring anonyme), ou None."""
    if not keyring_ok:
        yield None
        return
    r = subprocess.run(["keyctl", "newring", "sshvault-test-%s" % uuid.uuid4().hex[:8], "@s"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        yield None
        return
    rid = r.stdout.strip()
    yield rid
    subprocess.run(["keyctl", "clear", rid], capture_output=True)
    subprocess.run(["keyctl", "unlink", rid, "@s"], capture_output=True)


def keyring_session(rid):
    r = subprocess.run(["keyctl", "search", rid, "user", "sshvault:session"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return subprocess.run(["keyctl", "pipe", r.stdout.strip()], capture_output=True, text=True).stdout


# --- clés de test et coffre factice ---------------------------------------------

@pytest.fixture(scope="session")
def keys(tmp_path_factory):
    d = tmp_path_factory.mktemp("keys")
    out = {}
    for name, typ in (("prod", "ed25519"), ("perso", "ed25519"), ("bastion", "rsa")):
        path = d / name
        cmd = ["ssh-keygen", "-q", "-t", typ, "-N", "", "-C", "test-%s" % name, "-f", str(path)]
        if typ == "rsa":
            cmd[4:4] = ["-b", "2048"]
        subprocess.run(cmd, check=True)
        fp = subprocess.run(["ssh-keygen", "-l", "-E", "sha256", "-f", str(path) + ".pub"],
                            capture_output=True, text=True, check=True).stdout.split()[1]
        out[name] = {"private": path.read_text(), "public": (d / (name + ".pub")).read_text().strip(),
                     "fingerprint": fp}
        path.unlink()  # la clé privée ne reste que dans le faux coffre
    return out


def ssh_item(iid, name, key, hosts=None, extra_fields=()):
    fields = list(extra_fields)
    if hosts is not None:
        fields.append({"name": "sshvault-hosts", "value": hosts, "type": 0, "linkedId": None})
    return {"passwordHistory": None, "revisionDate": "2026-10-06T10:00:00.000Z",
            "creationDate": "2026-10-06T10:00:00.000Z", "deletedDate": None, "archivedDate": None,
            "object": "item", "id": iid, "organizationId": None, "folderId": None, "type": 5,
            "reprompt": 0, "name": name, "notes": None, "favorite": False,
            "fields": fields or None,
            "sshKey": {"privateKey": key["private"], "publicKey": key["public"],
                       "keyFingerprint": key["fingerprint"]},
            "collectionIds": []}


ID_PROD = "11111111-1111-4111-8111-111111111111"
ID_PERSO = "22222222-2222-4222-8222-222222222222"
ID_BASTION = "33333333-3333-4333-8333-333333333333"
ID_LOGIN = "44444444-4444-4444-8444-444444444444"


def default_items(keys):
    return [
        ssh_item(ID_PROD, "Serveur Prod", keys["prod"], hosts=" prod.example.com , *.Lab.example,"),
        ssh_item(ID_PERSO, "clé perso", keys["perso"]),
        ssh_item(ID_BASTION, "Bastion RSA", keys["bastion"], hosts="Bastion,jump",
                 extra_fields=[{"name": "note", "value": "rebond", "type": 0, "linkedId": None}]),
        {"object": "item", "id": ID_LOGIN, "type": 1, "name": "Serveur Prod (web)", "reprompt": 0,
         "fields": [{"name": "sshvault-hosts", "value": "prod.example.com", "type": 0, "linkedId": None}],
         "login": {"username": "alice", "password": "s3cret-web", "uris": []}},
        {"object": "item", "id": "55555555-5555-4555-8555-555555555555", "type": 2,
         "name": "note SSH", "notes": "-----BEGIN OPENSSH PRIVATE KEY----- pas une clé", "secureNote": {"type": 0}},
    ]


class Bench:
    """Un poste de test : HOME/XDG temporaires, faux serveur, faux bw."""

    def __init__(self, tmp_path, keys, ring):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        # repli fichier : XDG_RUNTIME_DIR doit être un tmpfs privé (vérifié par sshvault)
        self.runtime = pathlib.Path(private_runtime_dir())
        self.ring = ring
        self.vault_file = tmp_path / "server" / "vault.json"
        self.vault_file.parent.mkdir()
        self.log = tmp_path / "bw.log"
        self.pids = tmp_path / "bw.pids"
        self.keys = keys
        self.items = default_items(keys)
        self.write_vault()
        self.bw = tmp_path / "bin" / "bw"
        self.bw.parent.mkdir()
        self.bw.write_text("#!/bin/sh\nexec '%s' '%s' \"$@\"\n" % (sys.executable, FAKE_BW))
        self.bw.chmod(0o755)
        self.appdata = self.home / ".local" / "share" / "sshvault" / "bw"
        self.env = self.base_env()

    def write_vault(self):
        self.vault_file.write_text(json.dumps({
            "email": EMAIL, "password": PASSWORD, "userId": "aaaaaaaa-0000-4000-8000-000000000001",
            "clientId": "user.aaaa", "clientSecret": "apisecret", "items": self.items}))

    def base_env(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("BW_", "SSH_ASKPASS", "SSHVAULT_", "FAKE_BW_", "XDG_"))
               and k not in ("DISPLAY", "WAYLAND_DISPLAY", "BITWARDENCLI_APPDATA_DIR", "PYTHONPATH")}
        env.update(HOME=str(self.home), XDG_RUNTIME_DIR=str(self.runtime),
                   SSHVAULT_BW=str(self.bw), FAKE_BW_VAULT=str(self.vault_file),
                   FAKE_BW_LOG=str(self.log), FAKE_BW_PIDS=str(self.pids),
                   PYTHONPATH=SRC, SSHVAULT_PROMPT_TIMEOUT="10")
        if self.ring:
            env["SSHVAULT_KEYRING"] = self.ring
        else:
            env["SSHVAULT_KEYCTL"] = "/nonexistent/keyctl"
        return env

    # --- état du faux bw ---

    def state_file(self):
        return self.appdata / "data.json"

    def state(self):
        try:
            return json.loads(self.state_file().read_text())
        except FileNotFoundError:
            return {}

    def set_state(self, logged_in=True, session=None):
        self.appdata.mkdir(parents=True, exist_ok=True, mode=0o700)
        st = {"stateVersion": 85, "serverUrl": "https://vault.example.test"}
        if logged_in:
            st.update(userId="aaaaaaaa-0000-4000-8000-000000000001", userEmail=EMAIL,
                      lastSync="2026-10-06T00:00:00.000Z", session=session)
        self.state_file().write_text(json.dumps(st))

    def bw_session(self):
        return self.state().get("session")

    # --- magasin de session de sshvault ---

    def session_file(self):
        return self.runtime / "sshvault" / "session"

    def stored_session(self):
        """Session rangée par sshvault : (keyring, fichier)."""
        k = keyring_session(self.ring) if self.ring else None
        f = self.session_file().read_text().split()[0] if self.session_file().exists() else None
        return k, f

    def store_session(self, token, where="keyring", ttl=900):
        if where == "keyring":
            assert self.ring, "anneau dédié requis"
            r = subprocess.run(["keyctl", "padd", "user", "sshvault:session", self.ring],
                               input=token, capture_output=True, text=True, check=True)
            subprocess.run(["keyctl", "timeout", r.stdout.strip(), str(ttl)], check=True)
        else:
            d = self.runtime / "sshvault"
            d.mkdir(mode=0o700, exist_ok=True)
            fd = os.open(str(d / "session"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.write(fd, ("%s %d\n" % (token, int(time.time()) + ttl)).encode())
            os.close(fd)

    def unlocked(self, where="keyring"):
        """Coffre connecté et déverrouillé, session rangée par sshvault."""
        tok = "c2Vzc2lvbi1kZS10ZXN0LTEyMzQ1Njc4OTA="
        self.set_state(session=tok)
        self.store_session(tok, where)
        return tok

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    # --- exécution de sshvault ---

    def run(self, *args, env=None, timeout=60):
        e = dict(self.env)
        e.update(env or {})
        return subprocess.run([sys.executable, "-m", "sshvault", *args], env=e, capture_output=True,
                              text=True, timeout=timeout, start_new_session=True, stdin=subprocess.DEVNULL)

    def run_tty(self, *args, answer=None, env=None, timeout=30):
        """sshvault avec un terminal de contrôle (pty), stdin et stdout hors terminal comme
        sous `Match exec`. `answer` est tapé après l'apparition de l'invite."""
        e = dict(self.env)
        e.update(env or {})
        master, slave = pty.openpty()
        slave_name = os.ttyname(slave)

        def ctty():
            fd = os.open(slave_name, os.O_RDWR)  # après setsid : devient le terminal de contrôle
            os.close(fd)

        p = subprocess.Popen([sys.executable, "-m", "sshvault", *args], env=e, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                             preexec_fn=ctty)
        # le parent garde le côté esclave ouvert : sinon le maître lit EIO tant que
        # l'enfant n'a pas rouvert /dev/tty
        seen = b""
        sent = False
        deadline = time.monotonic() + timeout
        try:
            while p.poll() is None and time.monotonic() < deadline:
                r, _, _ = select.select([master], [], [], 0.1)
                if r:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    seen += chunk
                if answer is not None and not sent and b"mot de passe" in seen:
                    time.sleep(0.2)
                    os.write(master, (answer + "\n").encode())
                    sent = True
            out, err = p.communicate(timeout=max(1, deadline - time.monotonic()))
            try:
                while True:
                    r, _, _ = select.select([master], [], [], 0.1)
                    if not r:
                        break
                    chunk = os.read(master, 4096)
                    if not chunk:
                        break
                    seen += chunk
            except OSError:
                pass
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            os.close(master)
            os.close(slave)
        return subprocess.CompletedProcess(p.args, p.returncode, out.decode(), err.decode()), seen.decode(
            errors="replace")


def private_runtime_dir():
    """Dossier 0700 sur tmpfs (/dev/shm), comme un vrai XDG_RUNTIME_DIR."""
    d = tempfile.mkdtemp(prefix="sshvault-test-run-", dir="/dev/shm")
    os.chmod(d, 0o700)
    return d


@pytest.fixture
def runtime_dir():
    d = private_runtime_dir()
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def bench(tmp_path, keys, ring):
    b = Bench(tmp_path, keys, ring)
    yield b
    shutil.rmtree(str(b.runtime), ignore_errors=True)


def make_askpass(tmp_path, reply=PASSWORD, rc=0, name="askpass"):
    calls = tmp_path / (name + ".calls")
    script = tmp_path / name
    script.write_text("#!/bin/sh\necho \"$1\" >> '%s'\nprintf '%%s\\n' '%s'\nexit %d\n" % (calls, reply, rc))
    script.chmod(0o755)
    return str(script), calls

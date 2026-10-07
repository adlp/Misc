"""Banc des tests de sshvault (fixtures exposées par conftest.py) : faux bw, HOME et XDG temporaires, anneau de clés dédié,
agent témoin et agents de test.

Agent de l'utilisateur : chaque sshvault lancé par le banc reçoit `SSH_AUTH_SOCK` = socket
d'un agent témoin (vrai ssh-agent, une clé témoin chargée) ; son contenu est revérifié
inchangé après chaque test. Agents dédiés : vrais `ssh-agent` et `ssh-add` (OpenSSH du
poste) sur le XDG_RUNTIME_DIR temporaire du test ; `ssh-add` passe par un enveloppeur qui
journalise ses arguments et `SSH_AUTH_SOCK` (jamais stdin) puis exécute le vrai. En fin de
test, tout ssh-agent dont la ligne de commande vise le dossier du test est arrêté, et sa
disparition vérifiée.

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
import re
import select
import shutil
import signal
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
PASSPHRASE = "passphrase de la cle chiffree"
SSH_ADD = shutil.which("ssh-add") or "/usr/bin/ssh-add"
SSH_AGENT = shutil.which("ssh-agent") or "/usr/bin/ssh-agent"
HAVE_OPENSSH = all(os.access(p, os.X_OK) for p in (SSH_ADD, SSH_AGENT))


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


# --- garde de session : rien laissé hors des bancs -------------------------------

def _real_home():
    import pwd
    return pwd.getpwuid(os.getuid()).pw_dir


def real_paths():
    """Données réelles de l'utilisateur que les tests ne doivent pas toucher."""
    home = _real_home()
    rt = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    return {"ssh": os.path.join(home, ".ssh"),
            "runtime": os.path.join(rt, "sshvault"),
            "data": os.path.join(home, ".local", "share", "sshvault"),
            "config": os.path.join(home, ".config", "sshvault")}


def snapshot(path):
    """{chemin relatif : (mode, taille, mtime_ns, inode)} de tout ce qui est sous `path`, ou None."""
    if not os.path.lexists(path):
        return None
    out = {}
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            full = os.path.join(root, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            out[os.path.relpath(full, path)] = (st.st_mode, st.st_size, st.st_mtime_ns, st.st_ino)
    return out


def processes_matching(markers):
    """[(pid, ligne de commande)] des processus de l'utilisateur dont la ligne de commande
    contient l'un des marqueurs (pytest et ses parents exclus)."""
    me = {os.getpid(), os.getppid()}
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in me:
            continue
        try:
            if os.stat("/proc/" + d).st_uid != os.getuid():
                continue
            with open("/proc/%s/cmdline" % d, "rb") as f:
                cmd = " " + f.read().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if proc_alive(int(d)) and any(m in cmd for m in markers):
            out.append((int(d), cmd.strip()))
    return out


@pytest.fixture(scope="session", autouse=True)
def session_guard(tmp_path_factory):
    """Critère d'acceptation (stories 4 et 5), vérifié en fin de session : aucun processus de
    test restant (agent, surveillant, sshd, bw, askpass, ensure), `~/.ssh` réel inchangé, et ni
    socket, ni état, ni données sshvault réels créés par les tests."""
    paths = real_paths()
    before = {k: snapshot(p) for k, p in paths.items()}
    yield
    markers = ["/dev/shm/sshvault-test-", str(tmp_path_factory.getbasetemp()), FAKE_BW, "sshvault-it-",
               " -m sshvault "]
    deadline = time.monotonic() + 10
    left = processes_matching(markers)
    while left and time.monotonic() < deadline:
        time.sleep(0.2)
        left = processes_matching(markers)
    assert not left, "processus de test restants : %s" % left
    after = {k: snapshot(p) for k, p in paths.items()}
    assert after["ssh"] == before["ssh"], "~/.ssh réel modifié par les tests"
    for k in ("runtime", "data", "config"):
        if before[k] is None:
            assert after[k] is None, "%s réel créé par les tests" % paths[k]


# --- clés de test et coffre factice ---------------------------------------------

@pytest.fixture(scope="session")
def keys(tmp_path_factory):
    d = tmp_path_factory.mktemp("keys")
    out = {}
    for name, typ in (("prod", "ed25519"), ("perso", "ed25519"), ("bastion", "rsa"), ("chiffree", "ed25519")):
        path = d / name
        cmd = ["ssh-keygen", "-q", "-t", typ, "-N", PASSPHRASE if name == "chiffree" else "",
               "-C", "test-%s" % name, "-f", str(path)]
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
ID_CHIFFREE = "77777777-7777-4777-8777-777777777777"


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


# --- agents ---------------------------------------------------------------------------

def proc_alive(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[-1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def wait_gone(pids, timeout=5):
    deadline = time.monotonic() + timeout
    alive = list(pids)
    while alive and time.monotonic() < deadline:
        alive = [p for p in alive if proc_alive(p)]
        if alive:
            time.sleep(0.05)
    return not alive


def agents_under(path):
    """pids des ssh-agent et des surveillants (sshvault.watch) de l'utilisateur dont la ligne
    de commande contient `path`."""
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            if os.stat("/proc/" + d).st_uid != os.getuid():
                continue
            with open("/proc/%s/cmdline" % d, "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        ours = argv and (os.path.basename(argv[0]) == b"ssh-agent" or b"sshvault.watch" in argv)
        if ours and any(str(path).encode() in a for a in argv):
            if proc_alive(int(d)):
                out.append(int(d))
    return out


def kill_agents_under(path):
    """Arrête les ssh-agent du dossier ; renvoie leurs pids (vérifiés disparus)."""
    pids = agents_under(path)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    assert wait_gone(pids), "ssh-agent de test encore vivants : %s" % pids
    return pids


def agent_list(sock):
    """`ssh-add -L` (vrai, sans enveloppeur) sur `sock` : (code, lignes)."""
    env = {k: v for k, v in os.environ.items() if k not in ("SSH_AUTH_SOCK", "SSH_AGENT_PID")}
    env["SSH_AUTH_SOCK"] = str(sock)
    r = subprocess.run([SSH_ADD, "-L"], env=env, capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL)
    return r.returncode, [l for l in r.stdout.splitlines() if l.startswith("ssh-")]


def start_agent(sock, key_text=None):
    """Lance un vrai ssh-agent sur `sock` (et y charge `key_text`) ; renvoie son pid."""
    env = {k: v for k, v in os.environ.items() if k not in ("SSH_AUTH_SOCK", "SSH_AGENT_PID")}
    r = subprocess.run([SSH_AGENT, "-s", "-a", str(sock)], env=env, capture_output=True, text=True,
                       check=True, stdin=subprocess.DEVNULL, start_new_session=True)
    pid = int(re.search(r"SSH_AGENT_PID=(\d+);", r.stdout).group(1))
    if key_text is not None:
        env["SSH_AUTH_SOCK"] = str(sock)
        subprocess.run([SSH_ADD, "-q", "-"], input=key_text, env=env, check=True, text=True,
                       capture_output=True, start_new_session=True)
    return pid


@pytest.fixture(scope="session")
def witness(keys):
    """Agent témoin, à la place de l'agent de l'utilisateur : une clé, revérifiée inchangée.
    None sans ssh-agent/ssh-add (les tests de l'agent sont alors ignorés)."""
    if not HAVE_OPENSSH:
        yield None
        return
    d = tempfile.mkdtemp(prefix="sshvault-test-temoin-", dir="/dev/shm")
    os.chmod(d, 0o700)
    sock = os.path.join(d, "agent.sock")
    pid = start_agent(sock, keys["perso"]["private"])
    rc, listing = agent_list(sock)
    assert rc == 0 and len(listing) == 1
    w = {"sock": sock, "pid": pid, "listing": listing}
    try:
        yield w
    finally:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        assert wait_gone([pid]), "agent témoin encore vivant"
        shutil.rmtree(d, ignore_errors=True)


def check_witness(w):
    if w is None:
        return
    assert proc_alive(w["pid"]), "agent témoin mort"
    assert agent_list(w["sock"]) == (0, w["listing"]), "agent de l'utilisateur (témoin) modifié"


class Bench:
    """Un poste de test : HOME/XDG temporaires, faux serveur, faux bw."""

    def __init__(self, tmp_path, keys, ring, witness=None):
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
        self.witness = witness
        self.ssh_add_log = tmp_path / "ssh-add.log"
        self.ssh_add = tmp_path / "bin" / "ssh-add"
        self.ssh_add.write_text("#!/bin/sh\nprintf '%%s\\t%%s\\n' \"$SSH_AUTH_SOCK\" \"$*\" >> '%s'\nexec '%s' \"$@\"\n"
                                % (self.ssh_add_log, SSH_ADD))
        self.ssh_add.chmod(0o755)
        self.known_hosts = tmp_path / "known_hosts"
        self.known_hosts.write_text("")
        self.exe = write_exe(tmp_path / "exe")
        self.env = self.base_env()

    def write_vault(self):
        self.vault_file.write_text(json.dumps({
            "email": EMAIL, "password": PASSWORD, "userId": "aaaaaaaa-0000-4000-8000-000000000001",
            "clientId": "user.aaaa", "clientSecret": "apisecret", "items": self.items}))

    def base_env(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("BW_", "SSH_ASKPASS", "SSHVAULT_", "FAKE_BW_", "XDG_"))
               and k not in ("DISPLAY", "WAYLAND_DISPLAY", "BITWARDENCLI_APPDATA_DIR", "PYTHONPATH")}
        env.update(HOME=str(self.home), SSHVAULT_SSH_HOME=str(self.home), XDG_RUNTIME_DIR=str(self.runtime),
                   SSHVAULT_BW=str(self.bw), FAKE_BW_VAULT=str(self.vault_file),
                   FAKE_BW_LOG=str(self.log), FAKE_BW_PIDS=str(self.pids),
                   PYTHONPATH=SRC, SSHVAULT_PROMPT_TIMEOUT="10", SSHVAULT_TEST_BENCH="1",
                   PATH=str(self.exe.parent) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
                   SSHVAULT_SSH_ADD=str(self.ssh_add), SSHVAULT_KNOWN_HOSTS=str(self.known_hosts))
        env.pop("SSH_AGENT_PID", None)
        if self.witness:
            env["SSH_AUTH_SOCK"] = self.witness["sock"]
        else:
            env.pop("SSH_AUTH_SOCK", None)
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

    # --- agent dédié ---

    def sock(self):
        return self.runtime / "sshvault" / "agent.sock"

    def agent_state(self):
        p = self.runtime / "sshvault" / "agent.json"
        return json.loads(p.read_text()) if p.exists() else None

    def agent_keys(self):
        """Clés de l'agent dédié par le vrai `ssh-add -L` : liste des blobs base64."""
        rc, lines = agent_list(self.sock())
        return [l.split()[1] for l in lines]

    def blob(self, name):
        return self.keys[name]["public"].split()[1]

    def ssh_add_calls(self):
        """Appels de ssh-add par sshvault : [(SSH_AUTH_SOCK, arguments)]."""
        if not self.ssh_add_log.exists():
            return []
        return [tuple(l.split("\t", 1)) for l in self.ssh_add_log.read_text().splitlines()]

    def add_item(self, item):
        self.items.append(item)
        self.write_vault()

    def vault_item(self, iid):
        """Élément tel que le faux serveur le garde (après un éventuel `bw edit`)."""
        return next(i for i in json.loads(self.vault_file.read_text())["items"] if i.get("id") == iid)

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

    def run_tty(self, *args, answer=None, env=None, timeout=30, trigger=rb"mot de passe", signal_at_prompt=None):
        """sshvault avec un terminal de contrôle (pty), stdin et stdout hors terminal comme
        sous `Match exec`. `answer` (texte, ou liste : une réponse par invite) est tapé après
        chaque apparition de l'invite (`trigger`, expression régulière). `signal_at_prompt` :
        signal envoyé à sshvault à la première invite. Après la sortie, `self.tty_echo` dit si
        l'écho du terminal est actif."""
        e = dict(self.env)
        e.update(env or {})
        r = pty_run([[sys.executable, "-m", "sshvault", *args]], e, answers=answer, timeout=timeout,
                    trigger=trigger, signal_at_prompt=signal_at_prompt)
        self.tty_echo = r.echo
        return subprocess.CompletedProcess(r.args, r.returncode, r.stdout, r.stderr), r.screen


PTYLEAD = os.path.join(HERE, "ptylead.py")


def session_members(sid):
    """pids vivants de la session `sid` (champ « session » de /proc/<pid>/stat)."""
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % d) as f:
                fields = f.read().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if fields[0] != "Z" and int(fields[3]) == sid:
            out.append(int(d))
    return out


class PtyResult:
    def __init__(self, args, returncode, stdout, stderr, screen, echo, prompts, duration, rcs):
        self.args, self.returncode, self.stdout, self.stderr = args, returncode, stdout, stderr
        self.screen, self.echo, self.prompts, self.duration, self.rcs = screen, echo, prompts, duration, rcs


def pty_run(cmds, env, answers=None, trigger=rb"mot de passe", timeout=30, signal_at_prompt=None,
            send_at_prompt=None, mode="direct"):
    """Commande(s) `cmds` (liste d'argv) sur un pseudo-terminal neuf, terminal de contrôle de leur
    session ; stdin /dev/null, stdout et stderr hors du terminal (comme ssh lancé avec < /dev/null).
    mode « direct » : la commande unique est chef de session, donc au premier plan ;
    « fg » : un chef (ptylead.py) lance toutes les commandes dans son groupe, au premier plan ;
    « bg » : chaque commande dans son propre groupe, en arrière-plan (comme `cmd &` d'un shell
    interactif : lire le terminal l'arrêterait par SIGTTIN).
    `answers` (texte, ou liste : une réponse par invite) est tapé après chaque apparition de
    l'invite (`trigger`) ; `send_at_prompt` (octets) est écrit dans le terminal à la première
    invite (b"\\x03" : Ctrl-C) ; `signal_at_prompt` envoyé au processus lancé à la première invite.
    Résultat : codes, sorties, texte affiché sur le terminal, écho actif après la sortie,
    nombre d'invites vues, durée."""
    answers = [answers] if isinstance(answers, str) else list(answers or [])
    master, slave = pty.openpty()
    slave_name = os.ttyname(slave)

    def ctty():
        os.close(os.open(slave_name, os.O_RDWR))  # après setsid : devient le terminal de contrôle

    if mode == "direct":
        assert len(cmds) == 1
        argv = list(cmds[0])
    else:
        argv = [sys.executable, PTYLEAD, mode, slave_name, json.dumps([list(c) for c in cmds])]
    t0 = time.monotonic()
    p = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True, preexec_fn=ctty if mode == "direct" else None)
    # le parent garde le côté esclave ouvert : sinon le maître lit EIO tant que
    # l'enfant n'a pas rouvert /dev/tty
    seen = b""
    sent = 0
    deadline = time.monotonic() + timeout
    out = err = b""
    try:
        while p.poll() is None and time.monotonic() < deadline:
            r, _, _ = select.select([master], [], [], 0.1)
            if r:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                seen += chunk
            if (signal_at_prompt is not None or send_at_prompt is not None) and re.search(trigger, seen):
                time.sleep(0.2)
                if signal_at_prompt is not None:
                    p.send_signal(signal_at_prompt)
                    signal_at_prompt = None
                if send_at_prompt is not None:
                    os.write(master, send_at_prompt)
                    send_at_prompt = None
            if sent < len(answers) and len(re.findall(trigger, seen)) > sent:
                time.sleep(0.2)
                os.write(master, (answers[sent] + "\n").encode())
                sent += 1
        out, err = p.communicate(timeout=max(1, deadline - time.monotonic()))
        duration = time.monotonic() - t0
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
        # délai dépassé ou erreur : toute la session (chef, ssh lancés en arrière-plan dans
        # leurs propres groupes, ensure, bw…), pas seulement le processus lancé
        left = session_members(p.pid)
        for pid in left:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if p.poll() is None:
            p.kill()
        p.wait()
        assert wait_gone(left), "processus de la session pty encore vivants : %s" % left
        try:
            import termios
            echo = bool(termios.tcgetattr(slave)[3] & termios.ECHO)
        except Exception:
            echo = None
        os.close(master)
        os.close(slave)
    out, err = out.decode(errors="replace"), err.decode(errors="replace")
    stragglers = [x for x in left if x != p.pid]
    rcs = [p.returncode]
    if mode != "direct":
        m = re.search(r"^ptylead-rc: (\[.*\])$", out, re.M)
        rcs = json.loads(m.group(1)) if m else None
        out = re.sub(r"^ptylead-rc: .*\n?", "", out, flags=re.M)
    r = PtyResult(argv, p.returncode, out, err, seen.decode(errors="replace"), echo,
                  len(re.findall(trigger, seen)), duration, rcs)
    r.stragglers = stragglers  # processus de la session encore vivants à la fin (tués)
    return r


def write_exe(directory):
    """`sshvault` du PATH des bancs (lignes Match exec du ssh_config généré) : enveloppe de
    `python -m sshvault` du dépôt, jamais un sshvault installé sur le poste. Hors d'un banc
    (SSHVAULT_TEST_BENCH absent : un `ssh` lancé avec l'environnement de pytest, qui a le vrai
    XDG_RUNTIME_DIR et le vrai keyring), elle sort en code 1 sans rien lancer.
    SSHVAULT_TEST_TRACE=1 : une ligne « sshvault-test: fin <args> rc=N » sur stderr après chaque
    appel (ordre des appels dans la sortie de ssh -v)."""
    directory = pathlib.Path(directory)
    directory.mkdir(exist_ok=True)
    exe = directory / "sshvault"
    exe.write_text(
        "#!/bin/sh\n[ -n \"$SSHVAULT_TEST_BENCH\" ] || exit 1\n"
        "if [ -n \"$SSHVAULT_TEST_TRACE\" ]; then\n  '%s' -m sshvault \"$@\"\n  rc=$?\n"
        "  printf 'sshvault-test: fin %%s rc=%%d\\n' \"$*\" \"$rc\" >&2\n  exit $rc\nfi\n"
        "exec '%s' -m sshvault \"$@\"\n" % (sys.executable, sys.executable))
    exe.chmod(0o755)
    return exe


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
def bench(tmp_path, keys, ring, witness):
    b = Bench(tmp_path, keys, ring, witness)
    try:
        yield b
    finally:
        try:
            kill_agents_under(b.runtime)
        finally:
            try:
                shutil.rmtree(str(b.runtime), ignore_errors=True)
            finally:
                check_witness(witness)


def make_askpass(tmp_path, reply=PASSWORD, rc=0, name="askpass"):
    calls = tmp_path / (name + ".calls")
    script = tmp_path / name
    script.write_text("#!/bin/sh\necho \"$1\" >> '%s'\nprintf '%%s\\n' '%s'\nexit %d\n" % (calls, reply, rc))
    script.chmod(0o755)
    return str(script), calls

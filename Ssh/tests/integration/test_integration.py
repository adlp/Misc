"""Vrai bw contre le compte de test (ou le conteneur) : peuplement, puis lecture par sshvault.

- Peuplement par le vrai `bw` dans un dossier de données temporaire : 2 éléments SSH
  (clés ed25519 jetables, avec et sans `sshvault-hosts`) et 1 élément login, chacun
  avec le champ `sshvault-test-run=<uuid du run>`.
- Nettoyage dans un finaliseur, même en cas d'échec : chaque élément est relu et n'est
  supprimé (`bw delete item <id> --permanent`) que s'il porte le marqueur de ce run ;
  puis `bw logout` et suppression des dossiers de données temporaires.
- Les messages réels de bw dont dépend sshvault sont mesurés (et écrits, nettoyés des
  identifiants, dans SSHVAULT_IT_REPORT si défini).
Les identifiants du compte ne sont jamais affichés : tout message passe par `account.scrub`.
"""
import base64
import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import pytest

from bench import HAVE_OPENSSH, SRC, agent_list, check_witness, kill_agents_under, private_runtime_dir, wait_gone

pytestmark = pytest.mark.integration

MARK = "sshvault-test-run"
RUN = uuid.uuid4().hex
TAG = RUN[:8]
PW_VAR = "SSHVAULT_IT_PW"


# Mesuré (diagnostic du 2026-10-07) : une petite part des connexions TCP neuves vers le serveur
# restent bloquées (ClientHello TLS jamais acquitté, retransmis pendant des minutes). bw n'a pas de délai réseau propre. Seuls
# login, create, sync et delete ouvrent une connexion ; status, lock, unlock, list et get lisent
# le cache local. D'où : délai court par appel réseau, nouvel essai vérifié (jamais de doublon,
# jamais de suppression à l'aveugle).
NET_TIMEOUT = 45
NET_ATTEMPTS = 3
TIMEOUT_RC = 124


class Bw:
    """`bw` réel sur un dossier de données donné ; messages d'échec nettoyés des identifiants."""

    def __init__(self, exe, appdata, account, report=None):
        self.exe, self.appdata, self.account, self.report = exe, appdata, account, report
        self.blocked = 0

    def run(self, *args, session=None, env=None, nointeraction=True, timeout=NET_TIMEOUT):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("BW_", "BITWARDENCLI_", "SSHVAULT_IT"))}
        e.update(self.account.extra_env)
        e["BITWARDENCLI_APPDATA_DIR"] = str(self.appdata)
        if session:
            e["BW_SESSION"] = session
        e.update(env or {})
        argv = [self.exe] + (["--nointeraction"] if nointeraction else []) + list(args)
        try:
            return subprocess.run(argv, env=e, capture_output=True, text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            self.blocked += 1
            if self.report:
                self.report.add("bw %s bloqué (%ds), tué" % (args[0], timeout))
            return subprocess.CompletedProcess(argv, TIMEOUT_RC, "", "bw %s : sans réponse en %ds" % (args[0], timeout))

    def fail(self, args, r):
        return AssertionError(self.account.scrub("bw %s : code %d : %s" % (args[0], r.returncode, r.stderr.strip())))

    def ok(self, *args, **kw):
        r = self.run(*args, **kw)
        if r.returncode != 0:
            raise self.fail(args, r)
        return r

    def sync(self, session):
        for _ in range(NET_ATTEMPTS):
            r = self.run("sync", session=session)
            if r.returncode != TIMEOUT_RC:
                return r
        return r

    def login(self):
        self.ok("config", "server", self.account.server)
        args = ("login", self.account.email, "--passwordenv", PW_VAR, "--raw")
        for _ in range(NET_ATTEMPTS):
            r = self.run(*args, env={PW_VAR: self.account.password})
            if r.returncode == 0:
                return r.stdout.strip()
            if r.returncode != TIMEOUT_RC:
                raise self.fail(args, r)
            self.run("logout")  # état partiel éventuel du login tué
        raise self.fail(args, r)

    def create(self, enc, name, session):
        """Crée un élément ; après un blocage, cherche (marqueur + nom unique) avant de recréer."""
        for _ in range(NET_ATTEMPTS):
            r = self.run("create", "item", enc, session=session)
            if r.returncode == 0:
                return json.loads(r.stdout)["id"]
            if r.returncode != TIMEOUT_RC:
                raise self.fail(("create",), r)
            if self.sync(session).returncode == 0:
                lst = self.run("list", "items", session=session)
                found = [it["id"] for it in json.loads(lst.stdout or "[]")
                         if has_mark(it) and it.get("name") == name] if lst.returncode == 0 else []
                if found:
                    return found[0]
        raise self.fail(("create",), r)

    def delete(self, iid, session):
        """Suppression définitive ; après un blocage, relit l'élément avant de réessayer."""
        for _ in range(NET_ATTEMPTS):
            r = self.run("delete", "item", iid, "--permanent", session=session)
            if r.returncode != TIMEOUT_RC:
                return r
            if self.sync(session).returncode == 0:
                g = self.run("get", "item", iid, session=session)
                if g.returncode != 0 and "Not found." in g.stderr:
                    return subprocess.CompletedProcess(r.args, 0, "", "supprimé (vérifié après blocage)")
        return r


def has_mark(item, value=RUN):
    return any(isinstance(f, dict) and f.get("name") == MARK and (value is None or f.get("value") == value)
               for f in (item.get("fields") or []))


class Report:
    def __init__(self, account):
        self.account, self.lines = account, []

    def add(self, what, r=None, note=""):
        if r is not None:
            note = "rc=%d stdout=%r stderr=%r %s" % (r.returncode, r.stdout.strip()[:200], r.stderr.strip()[:2000], note)
        self.lines.append("%s : %s" % (what, self.account.scrub(note)))

    def flush(self):
        path = os.environ.get("SSHVAULT_IT_REPORT")
        if path:
            with open(path, "w") as f:
                f.write("\n".join(self.lines) + "\n")


@pytest.fixture(scope="module")
def report(account):
    rep = Report(account)
    yield rep
    rep.flush()


@pytest.fixture(scope="module")
def ssh_keys(tmp_path_factory):
    d = tmp_path_factory.mktemp("itkeys")
    out = {}
    for name in ("hotes", "sans-hotes"):
        p = d / name
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "sshvault-it-" + name, "-f", str(p)],
                       check=True)
        fp = subprocess.run(["ssh-keygen", "-l", "-E", "sha256", "-f", str(p) + ".pub"], capture_output=True,
                            text=True, check=True).stdout.split()[1]
        out[name] = {"private": p.read_text(), "public": (d / (name + ".pub")).read_text().strip(), "fingerprint": fp}
        p.unlink()
        (d / (name + ".pub")).unlink()
    return out


def cleanup(pop, session, created, report):
    """Supprime uniquement les éléments de ce run (marqueur relu avant chaque suppression)."""
    problems = []
    ids = list(created)
    for listing in (["list", "items"], ["list", "items", "--trash"]):
        r = pop.run(*listing, session=session)
        if r.returncode == 0:
            for it in json.loads(r.stdout):
                if has_mark(it) and it.get("id") not in ids:
                    ids.append(it["id"])
        else:
            problems.append("%s : code %d" % (" ".join(listing), r.returncode))
    for iid in ids:
        r = pop.run("get", "item", iid, session=session)
        if r.returncode != 0:
            problems.append("relecture de %s : %s" % (iid, r.stderr.strip()))
            continue
        if not has_mark(json.loads(r.stdout)):
            problems.append("%s sans le marqueur de ce run : non supprimé" % iid)
            continue
        r = pop.delete(iid, session)
        if r.returncode != 0:
            problems.append("suppression de %s : %s" % (iid, r.stderr.strip()))
            continue
        g = pop.run("get", "item", iid, session=session)
        report.add("get item après delete --permanent", g)
        if g.returncode == 0:
            problems.append("%s encore lisible après suppression" % iid)
    # contrôle final : plus aucun élément de ce run, ni actif ni à la corbeille
    left = 0
    any_mark = 0
    sy = pop.sync(session)
    source = "après sync" if sy.returncode == 0 else "cache local (sync : %s)" % sy.stderr.strip()
    for listing in (["list", "items"], ["list", "items", "--trash"]):
        r = pop.run(*listing, session=session)
        if r.returncode == 0:
            items = json.loads(r.stdout)
            left += sum(1 for it in items if has_mark(it))
            any_mark += sum(1 for it in items if has_mark(it, None))
    report.add("nettoyage", note="éléments de ce run restants=%d ; éléments %s (tout run) restants=%d ; %s ; "
               "appels bw bloqués puis relancés pendant le peuplement=%d" % (left, MARK, any_mark, source, pop.blocked))
    if left:
        problems.append("%d élément(s) de ce run encore présents" % left)
    return problems


@pytest.fixture(scope="module")
def vault(account, bw_exe, ssh_keys, report):
    appdata = tempfile.mkdtemp(prefix="sshvault-it-bw-")
    os.chmod(appdata, 0o700)
    pop = Bw(bw_exe, appdata, account, report)
    created, session = [], None
    problems = []
    try:
        session = pop.login()
        assert session, "login sans session"
        tpl = json.loads(pop.ok("get", "template", "item", session=session).stdout)

        def create(**fields):
            item = dict(tpl)
            item.update(fields)
            item["fields"] = list(fields.get("fields") or []) + [{"name": MARK, "value": RUN, "type": 0}]
            enc = base64.b64encode(json.dumps(item).encode()).decode()
            iid = pop.create(enc, item["name"], session)
            created.append(iid)
            return iid

        def ssh(name, key, hosts=None):
            return create(type=5, name=name, login=None, notes=None,
                          fields=[{"name": "sshvault-hosts", "value": hosts, "type": 0}] if hosts else [],
                          sshKey={"privateKey": key["private"], "publicKey": key["public"],
                                  "keyFingerprint": key["fingerprint"]})

        ids = {
            "hotes": ssh("sshvault-it %s prod" % TAG, ssh_keys["hotes"],
                         hosts="prod-%s.it.example , *.Lab-%s.it" % (TAG, TAG)),
            "sans-hotes": ssh("sshvault-it %s perso" % TAG, ssh_keys["sans-hotes"]),
            "login": create(type=1, name="sshvault-it %s web" % TAG, notes=None,
                            login={"username": "it", "password": "jetable-" + TAG, "uris": [], "totp": None}),
        }
    except BaseException as e:
        report.add("échec de mise en place", note="%s: %s" % (type(e).__name__, e))
        raise
    else:
        ids["_reader"] = (pop, session)  # autre client bw : relecture côté serveur (après sync)
        yield ids
    finally:
        try:
            if session:
                try:
                    problems = cleanup(pop, session, created, report)
                except Exception as e:  # le logout et la suppression du dossier ont lieu quand même
                    problems = ["nettoyage interrompu : %s: %s" % (type(e).__name__, e)]
        finally:
            lo = pop.run("logout")
            report.add("logout (peuplement)", lo)
            shutil.rmtree(appdata, ignore_errors=True)
        if problems:
            pytest.fail(account.scrub("nettoyage incomplet : " + " ; ".join(problems)))


@pytest.fixture
def home(account, bw_exe, ring, report, witness):
    """HOME temporaire de sshvault, son bw dédié connecté puis verrouillé ; logout et suppression à la fin.
    Agent de l'utilisateur remplacé par l'agent témoin ; agents dédiés du test arrêtés à la fin."""
    tmp = tempfile.mkdtemp(prefix="sshvault-it-home-")
    os.chmod(tmp, 0o700)
    h = os.path.join(tmp, "home")
    os.mkdir(h, 0o700)
    rt = private_runtime_dir()  # tmpfs privé, exigé par le repli fichier
    appdata = os.path.join(h, ".local", "share", "sshvault", "bw")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BW_", "SSH_ASKPASS", "SSHVAULT_", "XDG_", "BITWARDENCLI_"))
           and k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env.update(account.extra_env)
    env.update(HOME=h, SSHVAULT_SSH_HOME=h, XDG_RUNTIME_DIR=rt, SSHVAULT_BW=bw_exe, PYTHONPATH=SRC,
               SSHVAULT_PROMPT_TIMEOUT="30", SSHVAULT_BW_TIMEOUT="180")
    env.pop("SSH_AGENT_PID", None)
    env.pop("SSH_AUTH_SOCK", None)
    if witness:
        env["SSH_AUTH_SOCK"] = witness["sock"]
    if ring:
        env["SSHVAULT_KEYRING"] = ring
    else:
        env["SSHVAULT_KEYCTL"] = "/nonexistent/keyctl"
    askpass = os.path.join(tmp, "askpass")
    with open(askpass, "w") as f:
        f.write("#!/bin/sh\necho x >> '%s/askpass.calls'\nprintf '%%s\\n' \"$SSHVAULT_IT_ASKPASS_REPLY\"\n" % tmp)
    os.chmod(askpass, 0o700)
    own = Bw(bw_exe, appdata, account, report)
    try:
        yield {"env": env, "bw": own, "tmp": tmp, "askpass": askpass, "runtime": rt}
    finally:
        try:
            own.run("logout")
        finally:
            try:
                kill_agents_under(rt)
            finally:
                try:
                    shutil.rmtree(tmp, ignore_errors=True)
                    shutil.rmtree(rt, ignore_errors=True)
                finally:
                    check_witness(witness)


def sv(home, *args, env=None):
    e = dict(home["env"])
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "sshvault", *args], env=e, capture_output=True, text=True,
                          timeout=600, stdin=subprocess.DEVNULL, start_new_session=True)


def sv_login(home, account, report):
    """`sshvault login --server …` sous un pty : bw demande e-mail et mot de passe sur le
    terminal (saisie interactive réelle). Rien de ce qui passe sur le terminal n'est gardé
    ni affiché. Connexion bloquée (réseau) : sshvault interrompu, `bw logout`, nouvel essai."""
    for attempt in range(NET_ATTEMPTS):
        master, slave = pty.openpty()
        name = os.ttyname(slave)

        def ctty():
            os.close(os.open(name, os.O_RDWR))

        p = subprocess.Popen([sys.executable, "-m", "sshvault", "login", "--server", account.server],
                             env=home["env"], stdin=slave, stdout=subprocess.PIPE, stderr=slave,
                             start_new_session=True, preexec_fn=ctty)
        seen, sent, blocked = b"", set(), False
        deadline = time.monotonic() + NET_TIMEOUT + 30
        try:
            while p.poll() is None:
                if time.monotonic() > deadline:
                    blocked = True
                    p.send_signal(signal.SIGTERM)
                    p.wait(timeout=30)
                    break
                r, _, _ = select.select([master], [], [], 0.2)
                if r:
                    try:
                        seen += os.read(master, 4096)
                    except OSError:
                        pass
                for marker, what, value in ((b"Email address", "email", account.email),
                                            (b"Master password", "password", account.password)):
                    if marker in seen and what not in sent:
                        time.sleep(0.3)
                        os.write(master, value.encode() + b"\r")
                        sent.add(what)
            out = p.stdout.read().decode(errors="replace")
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            os.close(master)
            os.close(slave)
            del seen  # e-mail tapé, écho du terminal : jamais conservé
        if not blocked:
            report.add("sshvault login", note="rc=%d sortie=%r invites=%s" % (p.returncode, out.strip(), sorted(sent)))
            if p.returncode != 0:
                raise AssertionError("sshvault login : code %d (invites vues : %s)" % (p.returncode, sorted(sent)))
            return out
        report.add("sshvault login bloqué (%ds), interrompu" % (NET_TIMEOUT + 30))
        home["bw"].run("logout")
    raise AssertionError("sshvault login : bloqué %d fois" % NET_ATTEMPTS)


def check(account, r, rc, what):
    if r.returncode != rc:
        raise AssertionError(account.scrub("%s : code %d attendu, %d obtenu ; stderr : %s"
                                           % (what, rc, r.returncode, r.stderr.strip())))
    assert "Traceback" not in r.stderr
    assert "PRIVATE KEY" not in r.stdout + r.stderr


def ids_of(r):
    return [d["id"] for d in json.loads(r.stdout)]


def test_sshvault_sur_le_vrai_bw(account, vault, ssh_keys, home, report):
    own = home["bw"]
    session_file = os.path.join(home["runtime"], "sshvault", "session")
    ask = {"SSH_ASKPASS": home["askpass"], "SSH_ASKPASS_REQUIRE": "force"}
    good = dict(ask, SSHVAULT_IT_ASKPASS_REPLY=account.password)
    bad = dict(ask, SSHVAULT_IT_ASKPASS_REPLY="mauvais-" + RUN)

    # non connecté
    r = sv(home, "list")
    check(account, r, 3, "list non connecté")
    assert "sshvault login" in r.stderr

    # bw dédié de sshvault : `sshvault login` interactif (pty), session rangée, puis `sshvault lock`
    out = sv_login(home, account, report)
    assert "connecté, coffre déverrouillé" in out
    r = sv(home, "--nointeraction", "status")
    check(account, r, 0, "status après login")
    st = json.loads(own.ok("status").stdout)
    report.add("status sans session, connecté", note="clés=%s status=%s" % (sorted(st), st.get("status")))
    r = sv(home, "lock")
    check(account, r, 0, "lock après login")
    assert json.loads(own.ok("status").stdout)["status"] == "locked"

    # mesures des messages réels
    r = own.run("list", "items")
    report.add("list items sans session", r)
    assert r.returncode == 1 and "Vault is locked." in r.stderr
    r = own.run("unlock", "--passwordenv", PW_VAR, "--raw", env={PW_VAR: "mauvais-" + RUN})
    report.add("unlock mauvais mot de passe", r)
    assert r.returncode != 0 and "You are not logged in." not in r.stderr and not r.stdout.strip()
    r = own.run("list", "items", session="aW52YWxpZGUtc2Vzc2lvbi0wMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
    report.add("list items session invalide", r)
    assert r.returncode == 1 and "Vault is locked." in r.stderr
    r = own.run("status", session="aW52YWxpZGUtc2Vzc2lvbi0wMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
    report.add("status session invalide", r if r.returncode else None,
               "" if r.returncode else "status=%s" % json.loads(r.stdout).get("status"))
    assert r.returncode == 0 and json.loads(r.stdout)["status"] == "locked"

    # verrouillé, sans invite
    r = sv(home, "--nointeraction", "list")
    check(account, r, 3, "list --nointeraction verrouillé")
    assert "verrouillé" in r.stderr

    # mauvais mot de passe : code 3, aucune session rangée
    r = sv(home, "list", env=bad)
    report.add("sshvault list mauvais mot de passe", r)
    check(account, r, 3, "list mauvais mot de passe")
    assert r.stderr.strip() == ("sshvault: mot de passe maître refusé par bw "
                                "(Cryptography error, The decryption operation failed)")
    assert not os.path.exists(session_file)
    assert sv(home, "--nointeraction", "list").returncode == 3

    # bon mot de passe (askpass) : list
    r = sv(home, "list", "--json", env=good)
    check(account, r, 0, "list --json")
    got = {d["id"]: d for d in json.loads(r.stdout)}
    assert vault["hotes"] in got and vault["sans-hotes"] in got
    assert vault["login"] not in got, "l'élément login n'est pas une clé SSH"
    assert got[vault["hotes"]]["hosts"] == ["prod-%s.it.example" % TAG, "*.Lab-%s.it" % TAG]
    assert got[vault["hotes"]]["fingerprint"] == ssh_keys["hotes"]["fingerprint"]
    assert got[vault["hotes"]]["publicKey"] == ssh_keys["hotes"]["public"]
    assert got[vault["sans-hotes"]]["hosts"] == []
    assert set(got[vault["hotes"]]) == {"id", "name", "fingerprint", "hosts", "publicKey"}

    # sync (réseau ; sshvault relance lui-même une connexion bloquée)
    r = sv(home, "--nointeraction", "sync")
    report.add("sshvault sync", r)
    check(account, r, 0, "sync")
    assert "synchronisé" in r.stdout

    # session rangée : sans invite
    r = sv(home, "--nointeraction", "search", "--host", "x.lab-%s.it" % TAG, "--json")
    check(account, r, 0, "search --host")
    assert ids_of(r) == [vault["hotes"]]
    r = sv(home, "--nointeraction", "search", "--host", "PROD-%s.IT.EXAMPLE" % TAG, "--json")
    check(account, r, 0, "search --host casse")
    assert ids_of(r) == [vault["hotes"]]
    r = sv(home, "--nointeraction", "search", "--name", "%s PERSO" % TAG, "--json")
    check(account, r, 0, "search --name")
    assert ids_of(r) == [vault["sans-hotes"]]
    fp = ssh_keys["sans-hotes"]["fingerprint"]
    for pattern in (fp, fp.split(":", 1)[1]):
        r = sv(home, "--nointeraction", "search", "--fingerprint", pattern, "--json")
        check(account, r, 0, "search --fingerprint")
        assert ids_of(r) == [vault["sans-hotes"]]
    r = sv(home, "--nointeraction", "search", "--host", "aucun-%s.example" % TAG)
    check(account, r, 1, "search sans résultat")
    r = sv(home, "--nointeraction", "search", "--name", "%s web" % TAG)
    check(account, r, 1, "search élément login")
    r = sv(home, "--nointeraction", "status")
    check(account, r, 0, "status déverrouillé")

    # agent dédié (story 3) : load d'une clé de test, présence, agent status, purge, stop
    if HAVE_OPENSSH:  # sinon ignoré (ssh-agent/ssh-add absents)
        sock = os.path.join(home["runtime"], "sshvault", "agent.sock")
        fp = ssh_keys["hotes"]["fingerprint"]
        blob = ssh_keys["hotes"]["public"].split()[1]
        r = sv(home, "--nointeraction", "load", "--id", vault["hotes"], "-t", "10m")
        report.add("sshvault load", r)
        check(account, r, 0, "load --id")
        assert r.stdout == "chargée : sshvault-it %s prod %s (durée 10m)\n" % (TAG, fp)
        rc, listing = agent_list(sock)
        assert rc == 0 and [l.split()[1] for l in listing] == [blob], "clé dans l'agent dédié"
        r = sv(home, "--nointeraction", "load", "--host", "prod-%s.it.example" % TAG)
        check(account, r, 0, "load clé présente")
        assert r.stdout.startswith("déjà chargée : ")
        r = sv(home, "agent", "status")
        check(account, r, 0, "agent status")
        lines = r.stdout.splitlines()
        pid = int(lines[2].split(" : ")[1])
        assert lines[:2] == ["agent : actif", "socket : %s" % sock]
        assert lines[3].split("\t")[:3] == ["sshvault-it %s prod" % TAG, fp, "prod-%s.it.example,*.Lab-%s.it" % (TAG, TAG)]
        r = sv(home, "agent", "purge")
        check(account, r, 0, "agent purge")
        assert agent_list(sock) == (1, [])
        with open(os.path.join(home["runtime"], "sshvault", "agent.json")) as f:
            watcher = json.load(f)["agent"]["watcher"]
        r = sv(home, "agent", "stop")
        check(account, r, 0, "agent stop")
        assert wait_gone([pid, watcher]) and not os.path.exists(sock), "agent et surveillant arrêtés"
        r = sv(home, "agent", "status")
        check(account, r, 3, "agent status arrêté")

    # hôtes (story 4) : écriture par sshvault, relecture par un autre client bw, ssh-config
    check_hosts_and_ssh_config(account, vault, ssh_keys, home, report)

    # session invalidée par un autre unlock : purge, puis « verrouillé »
    own.ok("unlock", "--passwordenv", PW_VAR, "--raw", env={PW_VAR: account.password})
    r = sv(home, "--nointeraction", "list")
    report.add("sshvault list session invalidée", r)
    check(account, r, 3, "list session invalidée")
    assert not os.path.exists(session_file)

    # lock : bw verrouillé, magasin vide
    r = sv(home, "list", env=good)
    check(account, r, 0, "list après nouvel unlock")
    r = sv(home, "lock")
    check(account, r, 0, "lock")
    assert not os.path.exists(session_file)
    assert json.loads(own.ok("status").stdout)["status"] == "locked"
    r = sv(home, "--nointeraction", "status")
    check(account, r, 3, "status après lock")
    with open(os.path.join(home["tmp"], "askpass.calls")) as f:
        report.add("askpass", note="appels=%d" % len(f.read().splitlines()))


_B64ISH = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")


def b64_fragments(text):
    """Fragments du base64 de `text` sous les trois alignements possibles dans un JSON encodé."""
    out = []
    for shift in range(3):
        enc = base64.b64encode(("x" * shift + text).encode()).decode()
        out.append(enc[8:48])
    return out


class ArgvWatch:
    """Relève, pendant un appel, la ligne de commande (/proc/<pid>/cmdline) de chaque processus
    de l'utilisateur ; garde celles qui contiennent `needle` et signale tout argument suspect :
    clé privée ou son base64 (tout processus) ; pour bw et sshvault, tout argument (hors argv[0])
    de plus de 80 caractères, d'allure base64, ou contenant « { »."""

    def __init__(self, needle, secrets):
        self.needle, self.secrets = needle, [s for s in secrets if s]
        self.seen, self.suspect = set(), []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        me = os.getuid()
        while not self._stop.is_set():
            for d in os.listdir("/proc"):
                if not d.isdigit():
                    continue
                try:
                    if os.stat("/proc/" + d).st_uid != me:
                        continue
                    with open("/proc/%s/cmdline" % d, "rb") as f:
                        argv = f.read().decode(errors="replace").split("\0")
                except OSError:
                    continue
                # bw, ou sshvault (exécutable ou `python -m sshvault…`) ; « un argument contient
                # sshvault » attrapait aussi le shell qui lance pytest (faux positif mesuré)
                related = (any(self.needle in a for a in argv)
                           or os.path.basename(argv[0]) in ("bw", "sshvault")
                           or any(argv[i] == "-m" and argv[i + 1].startswith("sshvault")
                                  for i in range(len(argv) - 1)))
                if any(self.needle in a for a in argv):
                    self.seen.add(tuple(argv))
                for n, a in enumerate(argv):
                    if "PRIVATE KEY" in a or any(s in a for s in self.secrets) or (
                            related and n > 0 and ("{" in a or len(a) > 80 or _B64ISH.search(a))):
                        self.suspect.append([x[:60] for x in argv])
            time.sleep(0.002)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=10)


def _fields(item):
    return [(f.get("name"), f.get("value"), f.get("type")) for f in (item.get("fields") or [])]


def check_hosts_and_ssh_config(account, vault, ssh_keys, home, report):
    pop, session = vault["_reader"]

    def read(iid):
        assert pop.sync(session).returncode == 0, "sync du lecteur"
        return json.loads(pop.ok("get", "item", iid, session=session).stdout)

    for key, iid, orig_hosts in (("hotes", vault["hotes"], "prod-%s.it.example,*.lab-%s.it" % (TAG, TAG)),
                                 ("sans-hotes", vault["sans-hotes"], None)):
        before = read(iid)
        priv = ssh_keys[key]["private"]
        body = "".join(priv.splitlines()[1:-1])
        added = "ajout-%s.it.example" % TAG
        with ArgvWatch(iid, [body[:40], body[-40:]] + b64_fragments(priv)) as w:
            r = sv(home, "--nointeraction", "hosts", "add", "--id", iid, "Ajout-%s.IT.example" % TAG)
        report.add("sshvault hosts add (%s)" % key, r)
        check(account, r, 0, "hosts add %s" % key)
        edits = [a for a in w.seen if "edit" in a]
        assert edits, "bw edit observé dans /proc (surveillance effective) : %s" % sorted(w.seen)
        assert all(list(a[-4:]) == ["edit", "item", iid, ""] or list(a[-3:]) == ["edit", "item", iid]
                   for a in edits), edits
        assert not w.suspect, "argument suspect dans /proc/<pid>/cmdline : %s" % w.suspect[:3]
        after = read(iid)
        want = (orig_hosts + "," if orig_hosts else "") + added
        assert [v for n, v, t in _fields(after) if n == "sshvault-hosts"] == [want]
        assert [f for f in _fields(after) if f[0] != "sshvault-hosts"] == \
            [f for f in _fields(before) if f[0] != "sshvault-hosts"], "autres champs inchangés"
        assert after["sshKey"] == before["sshKey"], "clé inchangée"
        assert after["sshKey"]["privateKey"].strip() == priv.strip(), "clé privée identique"
        assert [after.get(k) for k in ("name", "notes", "type")] == [before.get(k) for k in ("name", "notes", "type")]
        r = sv(home, "--nointeraction", "hosts", "remove", "--id", iid, added)
        check(account, r, 0, "hosts remove %s" % key)
        final = read(iid)
        hf = [v for n, v, t in _fields(final) if n == "sshvault-hosts"]
        assert hf == ([orig_hosts] if orig_hosts else []), hf
        assert [f for f in _fields(final) if f[0] != "sshvault-hosts"] == \
            [f for f in _fields(before) if f[0] != "sshvault-hosts"]
        assert final["sshKey"] == before["sshKey"]
        r = sv(home, "--nointeraction", "hosts", "list", "--id", iid)
        check(account, r, 0, "hosts list %s" % key)
        assert r.stdout.split() == (orig_hosts.split(",") if orig_hosts else [])

    # hôte absent : code 1, rien écrit ; hôte invalide : code 2
    r = sv(home, "--nointeraction", "hosts", "remove", "--id", vault["hotes"], "absent-%s.example" % TAG)
    check(account, r, 1, "hosts remove absent")
    r = sv(home, "--nointeraction", "hosts", "add", "--id", vault["hotes"], "a b")
    check(account, r, 2, "hosts add invalide")

    # ssh-config dans le HOME de test, validé par l'OpenSSH du poste
    r = sv(home, "--nointeraction", "ssh-config")
    report.add("sshvault ssh-config", r)
    check(account, r, 0, "ssh-config")
    d = os.path.join(home["env"]["HOME"], ".ssh", "sshvault")
    text = open(os.path.join(d, "config")).read()
    assert "Match originalhost prod-%s.it.example,*.lab-%s.it\n" % (TAG, TAG) in text
    from sshvault.sshconfig import fp_filename
    pub = os.path.join(d, "pub", fp_filename(ssh_keys["hotes"]["fingerprint"]))
    with open(pub) as f:
        assert f.read().split() == ssh_keys["hotes"]["public"].split()[:2]
    assert not os.path.exists(os.path.join(d, "pub", fp_filename(ssh_keys["sans-hotes"]["fingerprint"])))
    if shutil.which("ssh"):
        main = os.path.join(home["tmp"], "ssh_config_de_test")
        with open(main, "w") as f:
            f.write('Include "%s"\n' % os.path.join(d, "config"))
        os.chmod(main, 0o600)
        g = subprocess.run(["ssh", "-G", "-F", main, "x.lab-%s.it" % TAG], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30)
        conf = [l.split(" ", 1) for l in g.stdout.splitlines()]
        assert [v for k, v in conf if k == "identityagent"] == [os.path.join(home["runtime"], "sshvault", "agent.sock")]
        assert [v for k, v in conf if k == "identityfile"] == [pub]
        assert [v for k, v in conf if k == "identitiesonly"] == ["yes"]
    r = sv(home, "--nointeraction", "ssh-config")
    check(account, r, 0, "ssh-config sans changement")
    assert "inchangé" in r.stdout

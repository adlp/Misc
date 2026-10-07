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
import time
import uuid

import pytest

from bench import (HAVE_OPENSSH, SRC, ArgvWatch, agent_list, b64_fragments, check_witness, kill_agents_under,
                   private_runtime_dir, wait_gone, write_exe)

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
    # `sshvault` des lignes Match exec : l'enveloppe du banc (dépôt), jamais celle du poste
    exe = write_exe(os.path.join(tmp, "exe"))
    env.update(HOME=h, SSHVAULT_SSH_HOME=h, XDG_RUNTIME_DIR=rt, SSHVAULT_BW=bw_exe, PYTHONPATH=SRC,
               SSHVAULT_PROMPT_TIMEOUT="30", SSHVAULT_BW_TIMEOUT="180", SSHVAULT_TEST_BENCH="1",
               PATH=str(exe.parent) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"))
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

    # chargement à la demande (story 5) : ssh vers un sshd local, agent vide, vrai bw
    check_ensure(account, vault, ssh_keys, home, report)

    # import d'une clé existante (story 6) : relecture par un autre client bw, load, ssh -G
    check_import(account, vault, home, report)

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


SSHD = "/usr/sbin/sshd"


def check_ensure(account, vault, ssh_keys, home, report):
    """Story 5 : `ssh` vers un sshd local (127.0.0.1, utilisateur courant) qui n'accepte que la
    clé de test ; agent dédié vide (arrêté), coffre déverrouillé (session rangée) : la connexion
    réussit par la ligne `Match … exec` du ssh_config généré, `sshvault ensure` et le vrai bw."""
    if not (HAVE_OPENSSH and shutil.which("ssh") and os.access(SSHD, os.X_OK)):
        report.add("ensure", note="ignoré : ssh, sshd, ssh-agent ou ssh-add absent")
        return
    import getpass
    import socket as _socket
    iid = vault["hotes"]
    host = "prod-%s.it.example" % TAG
    rt_dir = os.path.join(home["runtime"], "sshvault")
    sock = os.path.join(rt_dir, "agent.sock")
    d = os.path.join(home["env"]["HOME"], ".ssh", "sshvault")
    text = open(os.path.join(d, "config")).read()
    exe = os.path.join(home["tmp"], "exe", "sshvault")
    assert "Match originalhost prod-%s.it.example,*.lab-%s.it exec \"'%s' ensure --id %s\"\n" % (TAG, TAG, exe, iid) \
        in text, text
    r = sv(home, "agent", "stop")  # agent dédié vide avant la connexion
    check(account, r, 0, "agent stop avant ensure")
    assert not os.path.exists(sock)
    lab = os.path.join(home["tmp"], "sshd")
    os.mkdir(lab, 0o700)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", os.path.join(lab, "hostkey")], check=True)
    with open(os.path.join(lab, "authorized_keys"), "w") as f:
        f.write(ssh_keys["hotes"]["public"] + "\n")
    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with open(os.path.join(lab, "sshd_config"), "w") as f:
        f.write("Port %d\nListenAddress 127.0.0.1\nHostKey %s/hostkey\nPidFile %s/sshd.pid\nAuthorizedKeysFile "
                "%s/authorized_keys\nStrictModes no\nUsePAM no\nPasswordAuthentication no\n"
                "KbdInteractiveAuthentication no\nPrintMotd no\nLogLevel VERBOSE\n" % (port, lab, lab, lab))
    with open(os.path.join(lab, "sshd.log"), "wb") as log:
        sshd = subprocess.Popen([SSHD, "-D", "-e", "-f", os.path.join(lab, "sshd_config")], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while True:
            with _socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            assert time.monotonic() < deadline, "sshd de test muet"
            time.sleep(0.1)
        main = os.path.join(home["tmp"], "ssh_config_ensure")
        with open(main, "w") as f:
            f.write('Include "%s"\nHost %s\n    HostName 127.0.0.1\n    Port %d\nHost *\n    User %s\n'
                    "    UserKnownHostsFile /dev/null\n    GlobalKnownHostsFile /dev/null\n"
                    "    StrictHostKeyChecking no\n    BatchMode yes\n    LogLevel VERBOSE\n"
                    % (os.path.join(d, "config"), host, port, getpass.getuser()))
        os.chmod(main, 0o600)
        env = dict(home["env"], SSHVAULT_TEST_TRACE="1")
        t0 = time.monotonic()
        r = subprocess.run(["ssh", "-F", main, "-v", host, "true"], env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=600, start_new_session=True)
        took = time.monotonic() - t0
        report.add("ssh via ensure (agent vide, vrai bw)", note="rc=%d durée=%.2fs" % (r.returncode, took))
        if r.returncode != 0:
            raise AssertionError(account.scrub("ssh via ensure : code %d ; stderr : %s"
                                               % (r.returncode, r.stderr.strip()[-3000:])))
        assert re.findall(r"^sshvault-test: fin ensure --id (\S+) rc=(\d+)$", r.stderr, re.M) == [(iid, "0")]
        assert not [l for l in r.stderr.splitlines() if l.startswith("sshvault:")], "ensure silencieux"
        fp = ssh_keys["hotes"]["fingerprint"]
        assert re.findall(r"Offering public key: \S+ \S+ (SHA256:\S+)", r.stderr) == [fp], "une seule clé offerte"
        assert "Accepted publickey for %s" % getpass.getuser() in open(os.path.join(lab, "sshd.log")).read()
        rc, listing = agent_list(sock)
        assert rc == 0 and [l.split()[1] for l in listing] == [ssh_keys["hotes"]["public"].split()[1]]
        # 2e connexion : clé présente, chemin rapide (ni bw ni invite)
        t0 = time.monotonic()
        r = subprocess.run(["ssh", "-F", main, host, "true"], env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120, start_new_session=True)
        report.add("ssh via ensure (clé présente)", note="rc=%d durée=%.2fs" % (r.returncode, time.monotonic() - t0))
        assert r.returncode == 0, account.scrub(r.stderr)
        assert "PRIVATE KEY" not in r.stdout + r.stderr
    finally:
        try:
            sshd.terminate()
            try:
                sshd.wait(10)
            except subprocess.TimeoutExpired:
                sshd.kill()
                sshd.wait(10)
        finally:
            try:
                assert wait_gone([sshd.pid]), "sshd de test encore vivant"
            finally:
                r = sv(home, "agent", "stop")
                check(account, r, 0, "agent stop après ensure")


IMPORT_PASSPHRASE = "passphrase d'import " + TAG


def check_import(account, vault, home, report):
    """Story 6 : `sshvault import` de trois clés de test (Ed25519 en clair, Ed25519 chiffrée avec
    --decrypt par askpass, RSA PEM PKCS#1 convertie) avec un hôte, marquées pour le nettoyage (SSHVAULT_TEST_FIELD) ;
    /proc/<pid>/cmdline relevé pendant l'import ; relecture par le client du peuplement après
    sync (trois champs sshKey, hôtes, marqueur) ; doublon refusé ; load de la clé importée et
    ssh -G sur la config régénérée."""
    pop, session = vault["_reader"]
    d = os.path.join(home["tmp"], "import")
    os.mkdir(d, 0o700)
    files = {}
    for name, pp, typ in (("clair", "", ["-t", "ed25519"]), ("chiffree", IMPORT_PASSPHRASE, ["-t", "ed25519"]),
                          ("pkcs1", "", ["-t", "rsa", "-b", "2048", "-m", "PEM"])):
        p = os.path.join(d, name)
        subprocess.run(["ssh-keygen", "-q", *typ, "-N", pp, "-C", "sshvault-it-import-%s-%s" % (name, TAG),
                        "-f", p], check=True, stdin=subprocess.DEVNULL)
        with open(p) as f:
            private = f.read()
        with open(p + ".pub") as f:
            public = f.read().strip()
        fp = subprocess.run(["ssh-keygen", "-l", "-E", "sha256", "-f", p + ".pub"], capture_output=True, text=True,
                            check=True).stdout.split()[1]
        st = os.stat(p)
        files[name] = {"path": p, "private": private, "public": public, "fingerprint": fp,
                       "stat": (st.st_mtime_ns, st.st_size, st.st_ino)}
    host = "import-%s.it.example" % TAG
    env = {"SSHVAULT_TEST_FIELD": "%s=%s" % (MARK, RUN), "SSH_ASKPASS": home["askpass"],
           "SSH_ASKPASS_REQUIRE": "force", "SSHVAULT_IT_ASKPASS_REPLY": IMPORT_PASSPHRASE}
    secrets = [IMPORT_PASSPHRASE]
    for k in files.values():
        body = "".join(k["private"].splitlines()[1:-1])
        secrets += [body[:40], body[-40:]] + b64_fragments(k["private"])
    calls_file = os.path.join(home["tmp"], "askpass.calls")

    def askpass_calls():
        try:
            with open(calls_file) as f:
                return len(f.read().splitlines())
        except FileNotFoundError:
            return 0
    calls_before = askpass_calls()
    with ArgvWatch(home["env"]["SSHVAULT_BW"], secrets) as w:
        r = sv(home, "import", "--decrypt", "--hosts", host, files["clair"]["path"], files["chiffree"]["path"],
               files["pkcs1"]["path"], env=env)
    report.add("sshvault import", r)
    check(account, r, 0, "import")
    assert askpass_calls() - calls_before == 1, "une seule invite (passphrase de la clé chiffrée, --decrypt)"
    for k in files.values():
        assert "importée : %s (%s)" % (k["public"].split()[2], k["fingerprint"]) in r.stdout, r.stdout
    creates = [a for a in w.seen if "create" in a]
    assert creates, "bw create observé dans /proc (surveillance effective) : %s" % sorted(w.seen)
    assert all(list(a[-3:]) == ["create", "item", ""] or list(a[-2:]) == ["create", "item"] for a in creates), creates
    assert not w.suspect, "argument suspect dans /proc/<pid>/cmdline : %s" % w.suspect[:3]
    for k in files.values():
        st = os.stat(k["path"])
        assert (st.st_mtime_ns, st.st_size, st.st_ino) == k["stat"], "fichier d'origine inchangé"
        with open(k["path"]) as f:
            assert f.read() == k["private"]
    assert not [n for n in os.listdir(os.path.join(home["runtime"], "sshvault")) if n.startswith("import.")], \
        "copie tmpfs supprimée"

    # relecture par un second client bw, après sync
    assert pop.sync(session).returncode == 0, "sync du lecteur"
    found = {}
    for it in json.loads(pop.ok("list", "items", session=session).stdout):
        for name, k in files.items():
            if (it.get("sshKey") or {}).get("keyFingerprint") == k["fingerprint"]:
                found.setdefault(name, []).append(it)
    assert sorted(found) == ["chiffree", "clair", "pkcs1"] and all(len(v) == 1 for v in found.values()), found.keys()
    plain = found["clair"][0]
    assert has_mark(plain) and has_mark(found["chiffree"][0]), "marqueur de nettoyage"
    assert plain["type"] == 5 and plain["name"] == files["clair"]["public"].split()[2]
    report.add("import : clé privée relue", note="identique=%s ; identique sans blancs de fin=%s"
               % (plain["sshKey"]["privateKey"] == files["clair"]["private"],
                  plain["sshKey"]["privateKey"].rstrip() == files["clair"]["private"].rstrip()))
    assert plain["sshKey"] == {"privateKey": files["clair"]["private"], "publicKey": files["clair"]["public"],
                               "keyFingerprint": files["clair"]["fingerprint"]}
    dec = found["chiffree"][0]["sshKey"]
    assert dec["publicKey"] == files["chiffree"]["public"]
    assert dec["keyFingerprint"] == files["chiffree"]["fingerprint"]
    from sshvault.agent import is_encrypted
    assert dec["privateKey"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----") and not is_encrypted(
        dec["privateKey"].encode()), "stockée déchiffrée"
    y = subprocess.run(["ssh-keygen", "-y", "-f", "/dev/stdin"], input=dec["privateKey"], capture_output=True,
                       text=True)
    assert y.returncode == 0 and y.stdout.split()[:2] == files["chiffree"]["public"].split()[:2]
    assert has_mark(found["pkcs1"][0]), "marqueur de nettoyage"
    conv = found["pkcs1"][0]["sshKey"]
    assert files["pkcs1"]["private"].startswith("-----BEGIN RSA PRIVATE KEY-----")
    assert conv["keyFingerprint"] == files["pkcs1"]["fingerprint"] and conv["publicKey"] == files["pkcs1"]["public"]
    assert conv["privateKey"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----") and not is_encrypted(
        conv["privateKey"].encode()), "PKCS#1 convertie au format OpenSSH"
    y = subprocess.run(["ssh-keygen", "-y", "-f", "/dev/stdin"], input=conv["privateKey"], capture_output=True,
                       text=True)
    assert y.returncode == 0 and y.stdout.split()[:2] == files["pkcs1"]["public"].split()[:2], "même clé"
    for it in (plain, found["chiffree"][0], found["pkcs1"][0]):
        assert [v for n, v, t in _fields(it) if n == "sshvault-hosts"] == [host]

    # doublon : rien créé
    r = sv(home, "--nointeraction", "import", files["clair"]["path"], env=env)
    report.add("sshvault import doublon", r)
    check(account, r, 1, "import doublon")
    assert "déjà dans le coffre" in r.stderr and plain["id"] in r.stderr

    # load de la clé importée, ssh -G sur la config régénérée
    if HAVE_OPENSSH:
        sock = os.path.join(home["runtime"], "sshvault", "agent.sock")
        r = sv(home, "--nointeraction", "load", "--id", plain["id"], "-t", "5m")
        check(account, r, 0, "load de la clé importée")
        rc, listing = agent_list(sock)
        assert rc == 0 and [l.split()[1] for l in listing] == [files["clair"]["public"].split()[1]]
        r = sv(home, "agent", "stop")
        check(account, r, 0, "agent stop après import")
    if shutil.which("ssh"):
        from sshvault.sshconfig import fp_filename
        cfg = os.path.join(home["env"]["HOME"], ".ssh", "sshvault", "config")
        main = os.path.join(home["tmp"], "ssh_config_import")
        with open(main, "w") as f:
            f.write('Include "%s"\n' % cfg)
        os.chmod(main, 0o600)
        g = subprocess.run(["ssh", "-G", "-F", main, host], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30)
        conf = [l.split(" ", 1) for l in g.stdout.splitlines()]
        pubs = os.path.join(home["env"]["HOME"], ".ssh", "sshvault", "pub")
        assert sorted(v for k, v in conf if k == "identityfile") == sorted(
            os.path.join(pubs, fp_filename(k["fingerprint"])) for k in files.values())
        assert [v for k, v in conf if k == "identitiesonly"] == ["yes"]

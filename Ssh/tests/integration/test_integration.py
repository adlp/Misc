"""Vrai bw contre le compte de test (ou le conteneur) : peuplement, puis lecture par sshvault.

- Peuplement par le vrai `bw` dans un dossier de données temporaire : 2 éléments SSH
  (clés ed25519 jetables, avec et sans `sshvault-hosts`), 1 élément login sans URI et 1 élément
  login à URI `ssh://` (mot de passe d'hôte, CAP-11, créé par `bw create`, hors sshvault),
  chacun avec le champ `sshvault-test-run=<uuid du run>`.
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

from accounts import Scrub, alias as alias_of
from bench import (HAVE_OPENSSH, SRC, ArgvWatch, agent_list, b64_fragments, check_witness, kill_agents_under,
                   private_runtime_dir, wait_gone, write_exe)

pytestmark = pytest.mark.integration

MARK = "sshvault-test-run"
RUN = uuid.uuid4().hex
TAG = RUN[:8]
PW_VAR = "SSHVAULT_IT_PW"
#: alias du 1er compte de test dans sshvault (CAP-10) ; les suivants : it2, it3… (`alias_of`)
ALIAS = alias_of(0)
#: mesure du code de `sshvault login` (test opt-in) : nombre d'essais, écart minimal entre deux
LOGIN_REPEAT = "SSHVAULT_IT_LOGIN_REPEAT"
LOGIN_GAP = 7


# Mesuré (diagnostic du 2026-10-07) : une petite part des connexions TCP neuves vers le serveur
# restent bloquées (ClientHello TLS jamais acquitté, retransmis pendant des minutes). bw n'a pas de délai réseau propre. Seuls
# login, create, sync et delete ouvrent une connexion ; status, lock, unlock, list et get lisent
# le cache local. D'où : délai court par appel réseau, nouvel essai vérifié (jamais de doublon,
# jamais de suppression à l'aveugle).
NET_TIMEOUT = 45
NET_ATTEMPTS = 3
TIMEOUT_RC = 124
# Pannes réseau passagères (mesuré le 2026-10-08 : getaddrinfo ENOTFOUND pendant le nettoyage,
# 4 éléments marqués restés sur le compte) : nouvel essai après une pause croissante.
TRANSIENT = ("ENOTFOUND", "EAI_AGAIN", "ECONNRESET", "ECONNREFUSED", "ETIMEDOUT", "EHOSTUNREACH", "ENETUNREACH",
             "socket hang up", "fetch failed", "getaddrinfo", "network error", "Network")
BACKOFF = (2, 5, 10, 20)
# Limite de débit des connexions de Vaultwarden (mesuré le 2026-10-14 : 6 `login` sur 8 refusés
# après 12 réussis, « Rate limit exceeded. Try again later. ») : attente puis nouvel essai.
RATE_LIMIT = "Rate limit exceeded"
RATE_LIMIT_WAIT = 60
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_NOTE = "limite de débit du serveur : nouvel essai dans %d s" % RATE_LIMIT_WAIT


def transient(r) -> bool:
    return r.returncode == TIMEOUT_RC or (r.returncode != 0 and any(t in (r.stderr or "") for t in TRANSIENT))


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
        for n in range(NET_ATTEMPTS + 1):
            r = self.run("sync", session=session)
            if not transient(r):
                return r
            if self.report:
                self.report.add("bw sync : panne passagère, nouvel essai", r)
            time.sleep(BACKOFF[n])
        return r

    def login(self):
        self.ok("config", "server", self.account.server)
        args = ("login", self.account.email, "--passwordenv", PW_VAR, "--raw")
        attempt, limited = 0, 0
        while attempt < NET_ATTEMPTS:
            r = self.run(*args, env={PW_VAR: self.account.password})
            if r.returncode == 0:
                return r.stdout.strip()
            if RATE_LIMIT in (r.stderr or "") and limited < RATE_LIMIT_RETRIES:
                limited += 1
                if self.report:
                    self.report.add("bw login (peuplement)", note=RATE_LIMIT_NOTE)
                time.sleep(RATE_LIMIT_WAIT)
                continue
            if r.returncode != TIMEOUT_RC:
                raise self.fail(args, r)
            self.run("logout")  # état partiel éventuel du login tué
            attempt += 1
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
        """Suppression définitive ; après un blocage ou une panne réseau passagère, relit
        l'élément (sync, get) avant de réessayer."""
        for n in range(NET_ATTEMPTS + 1):
            r = self.run("delete", "item", iid, "--permanent", session=session)
            if not transient(r):
                return r
            if self.report:
                self.report.add("bw delete : panne passagère, relecture puis nouvel essai", r)
            time.sleep(BACKOFF[n])
            if self.sync(session).returncode == 0:
                g = self.run("get", "item", iid, session=session)
                if g.returncode != 0 and "Not found." in g.stderr:
                    return subprocess.CompletedProcess(r.args, 0, "", "supprimé (vérifié après panne)")
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
def report(accounts):
    rep = Report(Scrub(accounts))  # valeurs de tous les comptes masquées
    for w in getattr(accounts, "warnings", ()):
        rep.add("fichier des comptes", note="avertissement : " + w)
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


def purge_marked(pop, session, report, when):
    """Supprime TOUS les éléments marqués `sshvault-test-run` (quelle que soit la valeur : restes
    d'un run précédent interrompu), actifs ou à la corbeille ; sync d'abord, marqueur relu avant
    chaque suppression, puis contrôle final après sync. Renvoie les problèmes (texte nettoyé)."""
    problems = []
    sy = pop.sync(session)
    if sy.returncode != 0:
        problems.append("sync avant purge : %s" % sy.stderr.strip())
    ids = []
    for listing in (["list", "items"], ["list", "items", "--trash"]):
        r = pop.run(*listing, session=session)
        if r.returncode != 0:
            problems.append("%s : code %d" % (" ".join(listing), r.returncode))
            continue
        ids += [it["id"] for it in json.loads(r.stdout) if has_mark(it, None) and it.get("id") not in ids]
    deleted = 0
    for iid in ids:
        g = pop.run("get", "item", iid, session=session)
        if g.returncode != 0:
            if "Not found." not in g.stderr:
                problems.append("relecture de %s : %s" % (iid, g.stderr.strip()))
            continue
        if not has_mark(json.loads(g.stdout), None):
            problems.append("%s sans marqueur à la relecture : non supprimé" % iid)
            continue
        d = pop.delete(iid, session)
        if d.returncode != 0:
            problems.append("suppression de %s : %s" % (iid, d.stderr.strip()))
            continue
        deleted += 1
    left = 0
    sy = pop.sync(session)
    for listing in (["list", "items"], ["list", "items", "--trash"]):
        r = pop.run(*listing, session=session)
        if r.returncode == 0:
            left += sum(1 for it in json.loads(r.stdout) if has_mark(it, None))
        else:
            problems.append("contrôle %s : code %d" % (" ".join(listing), r.returncode))
    report.add("purge des éléments %s (%s)" % (MARK, when),
               note="trouvés=%d supprimés=%d restants=%d ; %s" % (
                   len(ids), deleted, left, "après sync" if sy.returncode == 0 else "cache local (sync en échec)"))
    if left:
        problems.append("%d élément(s) %s encore présents (%s)" % (left, MARK, when))
    return [report.account.scrub(p) for p in problems]


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
        # restes d'un run précédent interrompu : purgés d'abord (un échec ici est retenté à la fin)
        for p in purge_marked(pop, session, report, "début"):
            report.add("purge (début) incomplète", note=p)
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
            # mot de passe d'hôte (CAP-11) : utilisateur de l'élément, puis celui de l'URI (port ignoré),
            # et une URI web ignorée
            "pw": create(type=1, name="sshvault-it %s ssh" % TAG, notes=None,
                         login={"username": "it-user", "password": "jetable-ssh-" + TAG, "totp": None,
                                "uris": [{"match": None, "uri": "ssh://pw-%s.it.example" % TAG},
                                         {"match": None, "uri": "ssh://root@Pw2-%s.it.example:2222" % TAG},
                                         {"match": None, "uri": "https://pw-%s.it.example/" % TAG}]}),
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
                try:
                    problems += purge_marked(pop, session, report, "fin")
                except Exception as e:
                    problems.append("purge interrompue : %s: %s" % (type(e).__name__, e))
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
    appdata = os.path.join(h, ".local", "share", "sshvault", "accounts", ALIAS, "bw")
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


#: secondes au plus pour lire le reste du terminal, puis la sortie standard, après la sortie de
#: sshvault (un processus resté attaché au terminal qui écrirait sans fin, ou qui garderait le
#: tube de sortie ouvert, ne bloque pas le test)
PTY_DRAIN_LIMIT = 5.0


def drain_pty(master, limit=None):
    """Reste du terminal `master` après la sortie du processus : lu jusqu'à 0,2 s sans donnée,
    la fin du flux ou une erreur, et `limit` secondes au plus (PTY_DRAIN_LIMIT par défaut)."""
    end = time.monotonic() + (PTY_DRAIN_LIMIT if limit is None else limit)
    got = b""
    while True:
        left = end - time.monotonic()
        if left <= 0:
            break
        r, _, _ = select.select([master], [], [], min(0.2, left))
        if not r:
            break
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        got += chunk
    return got


def read_pipe(f, limit=None):
    """Tube `f` lu jusqu'à sa fin, `limit` secondes au plus (PTY_DRAIN_LIMIT par défaut) : un
    processus qui garde le tube ouvert ne bloque pas ; au-delà, ce qui a été lu."""
    end = time.monotonic() + (PTY_DRAIN_LIMIT if limit is None else limit)
    fd, got = f.fileno(), b""
    while True:
        left = end - time.monotonic()
        if left <= 0:
            break
        r, _, _ = select.select([fd], [], [], left)
        if not r:
            break
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        got += chunk
    return got


def pty_login(home, account, alias=None):
    """Un `sshvault login [--account ALIAS]` sous un pty : sshvault passe l'e-mail du registre à
    `bw login`, bw demande le mot de passe sur le terminal (saisie interactive réelle ; l'e-mail
    aussi s'il le demandait). Rien de ce qui passe sur le terminal n'est gardé ni affiché, sauf
    en échec : la fin (300 caractères) de ce que le terminal a reçu après l'invite du mot de
    passe (sans écho), ou de tout le terminal si l'invite n'est pas venue, masquée par
    `account.scrub`. Renvoie {rc, out, invites, tail, blocked, duration} ; bloqué (réseau) :
    sshvault interrompu (SIGTERM), `blocked` vrai."""
    master, slave = pty.openpty()
    name = os.ttyname(slave)

    def ctty():
        os.close(os.open(name, os.O_RDWR))

    t0 = time.monotonic()
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "login"] + (["--account", alias] if alias else []),
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
        # reste du terminal après la sortie (message d'erreur écrit juste avant), borné
        seen += drain_pty(master)
        out = read_pipe(p.stdout).decode(errors="replace")
        tail = ""
        if p.returncode:
            i = seen.rfind(b"Master password")
            rest = seen[i + len(b"Master password"):] if i >= 0 else seen
            tail = account.scrub(rest.decode(errors="replace").strip()[-300:])
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdout.close()
        os.close(master)
        os.close(slave)
        del seen  # e-mail tapé, écho du terminal : jamais conservé
    return {"rc": p.returncode, "out": out, "invites": sorted(sent), "tail": tail, "blocked": blocked,
            "duration": time.monotonic() - t0}


def sv_login(home, account, report, alias=None, own=None):
    """`sshvault login [--account ALIAS]` sous un pty (`pty_login`), code 0 exigé. Connexion
    bloquée (réseau) : `bw logout`, nouvel essai. Refus par la limite de débit du serveur
    (« Rate limit exceeded » dans la fin masquée du terminal) : attente de 60 s, nouvel essai,
    3 fois au plus (chaque attente dans le rapport)."""
    attempt, limited = 0, 0
    while attempt < NET_ATTEMPTS:
        res = pty_login(home, account, alias)
        if not res["blocked"] and res["rc"] != 0 and RATE_LIMIT in res["tail"] and limited < RATE_LIMIT_RETRIES:
            limited += 1
            report.add("sshvault login", note="rc=%d ; %s" % (res["rc"], RATE_LIMIT_NOTE))
            time.sleep(RATE_LIMIT_WAIT)
            continue
        attempt += 1
        if not res["blocked"]:
            report.add("sshvault login", note="rc=%d sortie=%r invites=%s" % (res["rc"], res["out"].strip(),
                                                                             res["invites"]))
            if res["rc"] != 0:
                raise AssertionError("sshvault login : code %d (invites vues : %s) ; terminal après l'invite : %r"
                                     % (res["rc"], res["invites"], res["tail"]))
            return res["out"]
        report.add("sshvault login bloqué (%ds), interrompu" % (NET_TIMEOUT + 30))
        (own or home["bw"]).run("logout")
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
    session_file = os.path.join(home["runtime"], "sshvault", "sessions", ALIAS)
    ask = {"SSH_ASKPASS": home["askpass"], "SSH_ASKPASS_REQUIRE": "force"}
    good = dict(ask, SSHVAULT_IT_ASKPASS_REPLY=account.password)
    bad = dict(ask, SSHVAULT_IT_ASKPASS_REPLY="mauvais-" + RUN)

    # aucun compte, puis compte enregistré mais non connecté
    r = sv(home, "list")
    check(account, r, 3, "list sans compte")
    assert "account add" in r.stderr
    r = sv(home, "account", "add", ALIAS, "--server", account.server, "--email", account.email)
    check(account, r, 0, "account add")
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
    # message de bw selon sa version (mesuré : 2026.9.1, puis 2025.12.0)
    assert r.stderr.strip() in ("sshvault: mot de passe maître refusé par bw "
                                "(%s)" % m for m in ("Cryptography error, The decryption operation failed",
                                                     "Invalid master password.")), r.stderr
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
    assert set(got[vault["hotes"]]) == {"account", "id", "name", "fingerprint", "hosts", "forward", "publicKey"}

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
        assert lines[3].split("\t")[:4] == [ALIAS, "sshvault-it %s prod" % TAG, fp,
                                            "prod-%s.it.example,*.Lab-%s.it" % (TAG, TAG)]
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

    # mots de passe d'hôte (story 17) : élément identifiant créé par bw, lu par password list et ssh-config
    check_passwords(account, vault, home, report)

    # chargement à la demande (story 5) : ssh vers un sshd local, agent vide, vrai bw
    check_ensure(account, vault, ssh_keys, home, report)

    # transfert d'agent restreint (story 8) : forward add relu par un autre client bw, puis ssh vers
    # un sshd local : l'hôte distant ne voit que la clé transférée
    check_forward(account, vault, ssh_keys, home, report)

    # import d'une clé existante (story 6) : relecture par un autre client bw, load, ssh -G
    check_import(account, vault, home, report)

    # génération dans le coffre (story 7) : relecture par un autre client bw, pubkey, load, ssh -G
    check_generate(account, vault, home, report)

    # désinstallation du ssh_config (story 12) : install puis uninstall dans le HOME de test
    check_uninstall(account, home, report)

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

    # lock --unload (story 12) : coffre déverrouillé à nouveau par l'invite (askpass), clé chargée,
    # puis révocation : clé retirée de l'agent dédié, coffre verrouillé
    if HAVE_OPENSSH:
        sock = os.path.join(home["runtime"], "sshvault", "agent.sock")
        blob = ssh_keys["hotes"]["public"].split()[1]
        r = sv(home, "list", env=good)
        check(account, r, 0, "list avant lock --unload")
        r = sv(home, "--nointeraction", "load", "--id", vault["hotes"], "-t", "10m")
        check(account, r, 0, "load avant lock --unload")
        rc, listing = agent_list(sock)
        assert rc == 0 and blob in [l.split()[1] for l in listing], "clé chargée avant lock --unload"
        r = sv(home, "lock", "--unload")
        report.add("sshvault lock --unload", r)
        check(account, r, 0, "lock --unload")
        assert r.stdout.startswith("coffre verrouillé, session oubliée, ") and "retirée" in r.stdout, \
            account.scrub(r.stdout)
        assert agent_list(sock) == (1, []), "lock --unload : clés retirées de l'agent dédié"
        assert not os.path.exists(session_file)
        assert json.loads(own.ok("status").stdout)["status"] == "locked"
        r = sv(home, "--nointeraction", "status")
        check(account, r, 3, "status après lock --unload")
        assert "coffre : verrouillé" in r.stdout
        r = sv(home, "agent", "stop")
        check(account, r, 0, "agent stop après lock --unload")
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


def check_passwords(account, vault, home, report):
    """Story 17 (CAP-11) : l'élément identifiant à URI ssh:// créé par `bw create` (hors sshvault) est
    lu par `password list` (hôtes `[user@]hôte`, URI web signalée, jamais le mot de passe) et
    donne son bloc à mot de passe dans le ssh_config ; l'élément identifiant sans URI ssh:// n'y
    est pas."""
    secret = "jetable-ssh-" + TAG
    r = sv(home, "--nointeraction", "password", "list", "--json")
    report.add("sshvault password list", r)
    check(account, r, 0, "password list")
    got = {d["id"]: d for d in json.loads(r.stdout)}
    assert got[vault["pw"]]["hosts"] == ["it-user@pw-%s.it.example" % TAG, "root@pw2-%s.it.example" % TAG]
    assert got[vault["pw"]]["account"] == ALIAS and vault["login"] not in got
    assert "URI ignorée « https://pw-%s.it.example/ »" % TAG in r.stderr
    assert secret not in r.stdout + r.stderr
    r = sv(home, "--nointeraction", "password", "list")
    check(account, r, 0, "password list (texte)")
    assert "%s\tsshvault-it %s ssh\tit-user@pw-%s.it.example,root@pw2-%s.it.example\n" % (ALIAS, TAG, TAG, TAG) in r.stdout
    assert vault["login"] not in sv(home, "--nointeraction", "list", "--json").stdout
    r = sv(home, "--nointeraction", "ssh-config")
    report.add("sshvault ssh-config (mots de passe)", r)
    check(account, r, 0, "ssh-config avec un élément identifiant")
    text = open(os.path.join(home["env"]["HOME"], ".ssh", "sshvault", "config")).read()
    exe = os.path.join(home["tmp"], "exe", "sshvault")
    assert "\n# sshvault-it %s ssh %s %s mot de passe\n" % (TAG, ALIAS, vault["pw"]) in text
    for h in ("pw-%s.it.example" % TAG, "pw2-%s.it.example" % TAG):
        assert ('Match originalhost %s exec "\'%s\' ensure --password --account %s --id %s --host %s"\n'
                % (h, exe, ALIAS, vault["pw"], h)) in text
    assert vault["login"] not in text and secret not in text
    if shutil.which("ssh"):
        # ssh -G évalue la ligne Match exec : ensure --password n'enregistre rien
        g = subprocess.run(["ssh", "-G", "-F", os.path.join(home["env"]["HOME"], ".ssh", "sshvault", "config"),
                            "pw-%s.it.example" % TAG], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           timeout=60, env=home["env"])
        assert g.returncode == 0, account.scrub(g.stderr)
        assert not os.path.exists(os.path.join(home["runtime"], "sshvault", "pw")) or \
            not os.listdir(os.path.join(home["runtime"], "sshvault", "pw"))


def check_uninstall(account, home, report):
    """Story 12 : `ssh-config install` puis `uninstall` dans le HOME de test : ~/.ssh/config
    revenu à ses octets d'avant, config générée et pub/ retirées, `ssh -G -F <~/.ssh/config du
    HOME de test>` sans l'agent dédié ; puis `ssh-config` (régénéré, inerte sans Include)."""
    h = home["env"]["HOME"]
    user_cfg = os.path.join(h, ".ssh", "config")
    d = os.path.join(h, ".ssh", "sshvault")
    sock = os.path.join(home["runtime"], "sshvault", "agent.sock")
    if not os.path.exists(user_cfg):
        with open(user_cfg, "w") as f:  # HOME de test seulement
            f.write("# config de test\nHost autre-%s.it\n    Port 2222\n" % TAG)
        os.chmod(user_cfg, 0o600)
    with open(user_cfg, "rb") as f:
        before = f.read()
    r = sv(home, "--nointeraction", "ssh-config")
    check(account, r, 0, "ssh-config avant install")
    r = sv(home, "ssh-config", "install")
    check(account, r, 0, "ssh-config install")

    def agents_for(host):
        g = subprocess.run(["ssh", "-G", "-F", user_cfg, host], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30, env=home["env"])
        assert g.returncode == 0, account.scrub(g.stderr)
        return [l.split(" ", 1)[1] for l in g.stdout.splitlines() if l.startswith("identityagent ")]
    host = "x.lab-%s.it" % TAG
    if shutil.which("ssh"):
        assert agents_for(host) == [sock], "install : agent dédié pour l'hôte géré"
    r = sv(home, "ssh-config", "uninstall")
    report.add("sshvault ssh-config uninstall", r)
    check(account, r, 0, "ssh-config uninstall")
    assert "ssh n'utilise plus sshvault" in r.stdout and r.stderr == "", account.scrub(r.stderr)
    with open(user_cfg, "rb") as f:
        assert f.read() == before, "uninstall : ~/.ssh/config revenu à ses octets d'avant install"
    assert not os.path.exists(os.path.join(d, "config")) and not os.path.exists(os.path.join(d, "pub"))
    if shutil.which("ssh"):
        assert sock not in agents_for(host), "uninstall : plus d'IdentityAgent sshvault"
    r = sv(home, "ssh-config", "uninstall")
    check(account, r, 0, "ssh-config uninstall, rien à faire")
    assert r.stdout.startswith("rien à faire")
    r = sv(home, "--nointeraction", "ssh-config")
    check(account, r, 0, "ssh-config après uninstall")
    assert "n'inclut pas" in r.stderr, "régénéré, inerte sans Include : avertissement"


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
    assert "Match originalhost prod-%s.it.example,*.lab-%s.it exec \"'%s' ensure --account %s --id %s\"\n" \
        % (TAG, TAG, exe, ALIAS, iid) in text, text
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
        assert re.findall(r"^sshvault-test: fin ensure --account it --id (\S+) rc=(\d+)$", r.stderr, re.M) \
            == [(iid, "0")]
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


def check_forward(account, vault, ssh_keys, home, report):
    """Story 8 : `sshvault forward add` écrit `sshvault-forward` (relu par le client du
    peuplement après sync, clé et hôtes inchangés) ; `ssh` vers un sshd local (127.0.0.1,
    utilisateur courant, `PermitUserRC no`) qui n'accepte que la clé `hotes`, avec
    `ForwardAgent yes` dans la config de test : sur l'hôte distant, `ssh-add -L` ne liste que la
    clé transférée (`sans-hotes`), aussi avec `ssh -A`, chargée par `ensure --forward` et le
    vrai bw ; puis `forward remove` : bloc retiré, sous-agent arrêté, champ retiré."""
    if not (HAVE_OPENSSH and shutil.which("ssh") and os.access(SSHD, os.X_OK)):
        report.add("forward", note="ignoré : ssh, sshd, ssh-agent ou ssh-add absent")
        return
    import getpass
    import socket as _socket
    from sshvault.agent import forward_id
    pop, session = vault["_reader"]
    host = "prod-%s.it.example" % TAG
    fwd = vault["sans-hotes"]
    r = sv(home, "--nointeraction", "forward", "add", "--id", fwd, host)
    report.add("sshvault forward add", r)
    check(account, r, 0, "forward add")
    assert pop.sync(session).returncode == 0, "sync du lecteur"
    it = json.loads(pop.ok("get", "item", fwd, session=session).stdout)
    assert [v for n, v, t in _fields(it) if n == "sshvault-forward"] == [host]
    assert [v for n, v, t in _fields(it) if n == "sshvault-hosts"] == [], "sshvault-hosts inchangé (absent)"
    assert has_mark(it) and it["sshKey"]["publicKey"] == ssh_keys["sans-hotes"]["public"]
    r = sv(home, "config", "set", "forward-confirm", "false")  # pas d'askpass de confirmation ici
    check(account, r, 0, "config set forward-confirm")
    r = sv(home, "--nointeraction", "ssh-config")
    check(account, r, 0, "ssh-config avec transfert")
    d = os.path.join(home["env"]["HOME"], ".ssh", "sshvault")
    fsock = os.path.join(home["runtime"], "sshvault", "fwd", forward_id(host) + ".sock")
    text = open(os.path.join(d, "config")).read()
    assert 'Match originalhost %s\n    ForwardAgent "%s"\n' % (host, fsock) in text, text
    assert text.index("ForwardAgent") < text.index("IdentityAgent"), "bloc de transfert avant les blocs d'identité"
    r = sv(home, "agent", "stop")
    check(account, r, 0, "agent stop avant forward")
    lab = os.path.join(home["tmp"], "sshd-fwd")
    os.mkdir(lab, 0o700)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", os.path.join(lab, "hostkey")], check=True)
    with open(os.path.join(lab, "authorized_keys"), "w") as f:
        f.write(ssh_keys["hotes"]["public"] + "\n")
    with _socket.socket() as s_:
        s_.bind(("127.0.0.1", 0))
        port = s_.getsockname()[1]
    with open(os.path.join(lab, "sshd_config"), "w") as f:
        f.write("Port %d\nListenAddress 127.0.0.1\nHostKey %s/hostkey\nPidFile %s/sshd.pid\nAuthorizedKeysFile "
                "%s/authorized_keys\nStrictModes no\nUsePAM no\nPasswordAuthentication no\n"
                "KbdInteractiveAuthentication no\nPrintMotd no\nAllowAgentForwarding yes\nPermitUserRC no\n"
                "LogLevel VERBOSE\n" % (port, lab, lab, lab))
    with open(os.path.join(lab, "sshd.log"), "wb") as log:
        sshd = subprocess.Popen([SSHD, "-D", "-e", "-f", os.path.join(lab, "sshd_config")], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while True:
            with _socket.socket() as s_:
                if s_.connect_ex(("127.0.0.1", port)) == 0:
                    break
            assert time.monotonic() < deadline, "sshd de test muet"
            time.sleep(0.1)
        main = os.path.join(home["tmp"], "ssh_config_forward")
        with open(main, "w") as f:
            f.write('Include "%s"\nHost %s\n    HostName 127.0.0.1\n    Port %d\nHost *\n    User %s\n'
                    "    UserKnownHostsFile /dev/null\n    GlobalKnownHostsFile /dev/null\n"
                    "    StrictHostKeyChecking no\n    BatchMode yes\n    ForwardAgent yes\n"
                    % (os.path.join(d, "config"), host, port, getpass.getuser()))
        os.chmod(main, 0o600)
        env = dict(home["env"], SSHVAULT_TEST_TRACE="1")
        for opts in ((), ("-A",)):
            t0 = time.monotonic()
            r = subprocess.run(["ssh", "-F", main, *opts, host, "ssh-add -L"], env=env, capture_output=True,
                               text=True, stdin=subprocess.DEVNULL, timeout=600, start_new_session=True)
            report.add("ssh %s'ssh-add -L' (transfert restreint, vrai bw)" % ("-A " if opts else ""),
                       note="rc=%d durée=%.2fs" % (r.returncode, time.monotonic() - t0))
            if r.returncode != 0:
                raise AssertionError(account.scrub("ssh (transfert) : code %d ; stderr : %s"
                                                   % (r.returncode, r.stderr.strip()[-3000:])))
            seen = [l.split()[1] for l in r.stdout.splitlines() if l.startswith("ssh-")]
            assert seen == [ssh_keys["sans-hotes"]["public"].split()[1]], "seule la clé transférée : %s" % seen
            assert not [l for l in r.stderr.splitlines() if l.startswith("sshvault:")], account.scrub(r.stderr)
            assert "PRIVATE KEY" not in r.stdout + r.stderr
        rc, listing = agent_list(fsock)
        assert rc == 0 and [l.split()[1] for l in listing] == [ssh_keys["sans-hotes"]["public"].split()[1]]
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
                r = sv(home, "--nointeraction", "forward", "remove", "--id", fwd, host)
                report.add("sshvault forward remove", r)
                check(account, r, 0, "forward remove")
    assert "plus référencé" in r.stdout and not os.path.exists(fsock), "sous-agent arrêté"
    assert "transfert d'agent" not in open(os.path.join(d, "config")).read()
    assert pop.sync(session).returncode == 0
    it = json.loads(pop.ok("get", "item", fwd, session=session).stdout)
    assert [v for n, v, t in _fields(it) if n == "sshvault-forward"] == [], "champ retiré"
    r = sv(home, "agent", "stop")
    check(account, r, 0, "agent stop après forward")


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


def check_generate(account, vault, home, report):
    """Story 7 : `sshvault generate` sur le compte de test, avec un hôte, marquée pour le nettoyage
    (SSHVAULT_TEST_FIELD) ; relecture par le client du peuplement après sync : `ssh-keygen -y`
    de `privateKey` = la ligne affichée sur stdout (hors commentaire), empreinte = `ssh-keygen -l`
    de cette ligne ; aucune ligne de commande relevée ne contient la clé privée ; aucun dossier
    de génération restant ; pubkey, load et ssh -G."""
    pop, session = vault["_reader"]
    name = "sshvault-it %s générée" % TAG
    host = "gen-%s.it.example" % TAG
    env = {"SSHVAULT_TEST_FIELD": "%s=%s" % (MARK, RUN)}
    with ArgvWatch(home["env"]["SSHVAULT_BW"], [], keep_all=True) as w:
        r = sv(home, "--nointeraction", "generate", "--name", name, "--hosts", host, env=env)
    report.add("sshvault generate", r)
    check(account, r, 0, "generate")
    lines = r.stdout.splitlines()
    assert len(lines) == 1, "stdout = la seule clé publique : %r" % r.stdout
    public = lines[0]
    assert public.startswith("ssh-ed25519 ") and public.endswith(" " + name)
    fp = subprocess.run(["ssh-keygen", "-l", "-E", "sha256", "-f", "/dev/stdin"], input=public + "\n",
                        capture_output=True, text=True, check=True).stdout.split()[1]
    assert not [n for n in os.listdir(os.path.join(home["runtime"], "sshvault")) if n.startswith("generate.")], \
        "dossier de génération supprimé"

    # relecture par un second client bw, après sync
    assert pop.sync(session).returncode == 0, "sync du lecteur"
    found = [it for it in json.loads(pop.ok("list", "items", session=session).stdout)
             if (it.get("sshKey") or {}).get("keyFingerprint") == fp]
    assert len(found) == 1, "un seul élément porte l'empreinte affichée"
    it = found[0]
    assert has_mark(it), "marqueur de nettoyage"
    assert it["type"] == 5 and it["name"] == name
    key = it["sshKey"]
    assert key["publicKey"] == public and key["keyFingerprint"] == fp
    from sshvault.agent import is_encrypted
    assert key["privateKey"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----") and not is_encrypted(
        key["privateKey"].encode()), "sans passphrase"
    y = subprocess.run(["ssh-keygen", "-y", "-f", "/dev/stdin"], input=key["privateKey"], capture_output=True,
                       text=True)
    assert y.returncode == 0 and y.stdout.split()[:2] == public.split()[:2], "privée relue → même clé publique"
    assert [v for n, v, t in _fields(it) if n == "sshvault-hosts"] == [host]
    report.add("generate : relecture", note="empreinte identique, ssh-keygen -y identique")

    # aucune ligne de commande relevée pendant generate ne contient la clé privée générée
    body = "".join(key["privateKey"].splitlines()[1:-1])
    secrets = [body[:40], body[-40:], body[100:140]] + b64_fragments(key["privateKey"])
    creates = [a for a in w.seen if "create" in a]
    assert creates, "bw create observé dans /proc (surveillance effective) : %s" % sorted(w.seen)
    assert all(list(a[-3:]) == ["create", "item", ""] or list(a[-2:]) == ["create", "item"] for a in creates), creates
    assert not w.suspect, "argument suspect dans /proc/<pid>/cmdline : %s" % w.suspect[:3]
    leaked = [a[:3] for a in w.all if any(s in x for x in a for s in secrets)]
    assert not leaked, "clé privée en argument : %s" % leaked

    # pubkey (cache local), load, ssh -G
    r = sv(home, "--nointeraction", "pubkey", "--id", it["id"])
    check(account, r, 0, "pubkey de la clé générée")
    assert r.stdout == public + "\n"
    if HAVE_OPENSSH:
        sock = os.path.join(home["runtime"], "sshvault", "agent.sock")
        r = sv(home, "--nointeraction", "load", "--id", it["id"], "-t", "5m")
        check(account, r, 0, "load de la clé générée")
        rc, listing = agent_list(sock)
        assert rc == 0 and [l.split()[1] for l in listing] == [public.split()[1]]
        r = sv(home, "agent", "stop")
        check(account, r, 0, "agent stop après generate")
    if shutil.which("ssh"):
        from sshvault.sshconfig import fp_filename
        cfg = os.path.join(home["env"]["HOME"], ".ssh", "sshvault", "config")
        main = os.path.join(home["tmp"], "ssh_config_generate")
        with open(main, "w") as f:
            f.write('Include "%s"\n' % cfg)
        os.chmod(main, 0o600)
        g = subprocess.run(["ssh", "-G", "-F", main, host], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30)
        conf = [l.split(" ", 1) for l in g.stdout.splitlines()]
        pubs = os.path.join(home["env"]["HOME"], ".ssh", "sshvault", "pub")
        assert [v for k, v in conf if k == "identityfile"] == [os.path.join(pubs, fp_filename(fp))]
        assert [v for k, v in conf if k == "identitiesonly"] == ["yes"]


def test_plusieurs_comptes_sur_le_vrai_bw(accounts, bw_exe, vault, ssh_keys, home, report):
    """CAP-10 sur le vrai bw, tous les comptes du fichier (au moins 2) : `it` (1er, coffre peuplé),
    puis `it2`, `it3`… dans l'ordre du fichier, chacun connecté par `sshvault login --account`
    dans ses propres données ; une clé générée et marquée dans chaque compte au-delà du premier
    (éléments marqués purgés au début et à la fin) ; `list` des comptes par défaut, alias de
    chaque élément ; `account default` change la liste suivante ; `ssh-config` couvre tous les
    comptes ; `ensure --account` charge la clé de chacun ; sur **chaque** compte, `it` compris :
    `logout --account` puis login, et `account set` aller-retour puis login ; `lock` les
    verrouille tous. Aucune valeur du fichier des comptes dans une assertion, un message ou le
    rapport (`scrub` de tous les comptes)."""
    if len(accounts) < 2:
        report.add("plusieurs comptes", note="sauté : un seul compte dans le fichier des comptes de test")
        pytest.skip("un seul compte de test : volet plusieurs comptes sauté")
    scrub = Scrub(accounts).scrub
    aliases = [alias_of(n) for n in range(len(accounts))]
    others = list(zip(aliases[1:], accounts[1:]))

    def need(cond, what):
        if not cond:
            raise AssertionError(scrub(what))

    def ok(r, rc, what):
        need(r.returncode == rc, "%s : code %d attendu, %d obtenu ; stderr : %s"
             % (what, rc, r.returncode, r.stderr.strip()))
        need("Traceback" not in r.stderr and "PRIVATE KEY" not in r.stdout + r.stderr, "%s : sortie inattendue" % what)

    def bw_status(alias):
        r = own[alias].ok("status")
        return json.loads(r.stdout)["status"]

    data_dir = os.path.join(home["env"]["HOME"], ".local", "share", "sshvault", "accounts")
    own = {ALIAS: home["bw"]}
    own.update({a: Bw(bw_exe, os.path.join(data_dir, a, "bw"), acct, report) for a, acct in others})
    pops = {}  # alias -> (Bw du peuplement, dossier, session) des comptes au-delà du premier
    cfg = os.path.join(home["env"]["HOME"], ".ssh", "sshvault", "config")
    sock = os.path.join(home["runtime"], "sshvault", "agent.sock")
    problems = []
    try:
        for a, acct in others:
            appdata = tempfile.mkdtemp(prefix="sshvault-it-bw-%s-" % a)
            os.chmod(appdata, 0o700)
            pop = Bw(bw_exe, appdata, acct, report)
            pops[a] = (pop, appdata, None)
            pops[a] = (pop, appdata, pop.login())
            for p in purge_marked(pop, pops[a][2], report, "début, compte %s" % a):
                report.add("purge (début, compte %s) incomplète" % a, note=p)
        for a, acct in zip(aliases, accounts):
            r = sv(home, "account", "add", a, "--server", acct.server, "--email", acct.email)
            ok(r, 0, "account add %s" % a)
        r = sv(home, "account", "list")
        ok(r, 0, "account list")
        listed = [l.split("\t")[0] for l in r.stdout.splitlines()]
        need(listed == aliases, "account list : alias %s" % listed)
        r = sv(home, "login")
        ok(r, 2, "login sans --account, plusieurs comptes")
        need("--account" in r.stderr, "login sans --account : --account non demandé")
        for a, acct in zip(aliases, accounts):
            out = sv_login(home, acct, report, alias=a, own=own[a])
            need("compte %s : connecté, coffre déverrouillé" % a in out, "login %s : sortie inattendue" % a)
        r = sv(home, "--nointeraction", "status")
        ok(r, 0, "status de tous les comptes")
        need(r.stdout.count("coffre : déverrouillé") == len(aliases), "status : comptes non tous déverrouillés")

        # écriture : un seul compte ; une clé générée (marquée) dans chaque compte au-delà du premier
        r = sv(home, "--nointeraction", "account", "default", *aliases)
        ok(r, 0, "account default (tous)")
        r = sv(home, "--nointeraction", "generate", "--name", "sshvault-it %s sans compte" % TAG, "--hosts",
               "aucun-%s.it.example" % TAG)
        ok(r, 2, "generate sans --account, plusieurs comptes par défaut")
        public = {ALIAS: ssh_keys["hotes"]["public"]}
        for a, _ in others:
            r = sv(home, "--nointeraction", "generate", "--account", a, "--name", "sshvault-it %s compte %s" % (TAG, a),
                   "--hosts", "%s-%s.it.example" % (a, TAG), env={"SSHVAULT_TEST_FIELD": "%s=%s" % (MARK, RUN)})
            report.add("generate --account %s" % a, r)
            ok(r, 0, "generate --account %s" % a)
            public[a] = r.stdout.strip()
        blob = {a: k.split()[1] for a, k in public.items()}

        # lecture : tous les comptes, alias de chaque élément
        r = sv(home, "--nointeraction", "list", "--json")
        ok(r, 0, "list des comptes par défaut")
        data = json.loads(r.stdout)
        mine = {(d["account"], d["id"]) for d in data}
        need((ALIAS, vault["hotes"]) in mine and (ALIAS, vault["sans-hotes"]) in mine, "list : éléments de it absents")
        ids = {ALIAS: vault["hotes"]}
        for a, _ in others:
            found = [d["id"] for d in data if d["account"] == a and d["publicKey"] == public[a]]
            need(len(found) == 1, "clé générée relue dans le compte %s : %d trouvée(s)" % (a, len(found)))
            ids[a] = found[0]
        r = sv(home, "--nointeraction", "list")
        ok(r, 0, "list texte")
        need(all(l.split("\t")[0] in aliases for l in r.stdout.splitlines()), "list : alias en 1re colonne")
        last = aliases[-1]
        r = sv(home, "--nointeraction", "account", "default", last)
        ok(r, 0, "account default %s" % last)
        r = sv(home, "--nointeraction", "list", "--json")
        ok(r, 0, "list après account default")
        need({d["account"] for d in json.loads(r.stdout)} == {last}, "list après account default : autres comptes")
        r = sv(home, "--nointeraction", "list", "--json", "--account", ALIAS)
        ok(r, 0, "list --account it")
        need({d["account"] for d in json.loads(r.stdout)} == {ALIAS}, "list --account it : autres comptes")

        # ssh_config sur tous les comptes, clés de tous chargées
        r = sv(home, "--nointeraction", "ssh-config")
        ok(r, 0, "ssh-config, tous les comptes")
        text = open(cfg).read()
        for a in aliases:
            need("ensure --account %s --id %s\"" % (a, ids[a]) in text, "ssh-config : bloc du compte %s absent" % a)

        def ensure_all():
            for a in aliases:
                r = sv(home, "--nointeraction", "ensure", "--account", a, "--id", ids[a])
                ok(r, 0, "ensure --account %s" % a)

        def loaded():
            rc, listing = agent_list(sock)
            return sorted(l.split()[1] for l in listing) if rc == 0 else []

        if HAVE_OPENSSH:
            ensure_all()
            need(loaded() == sorted(blob.values()), "ensure : clés de tous les comptes non chargées")
            r = sv(home, "agent", "stop")
            ok(r, 0, "agent stop, tous les comptes")

        # logout puis login sur chaque compte (story 11) : bw déconnecté, sa clé retirée de
        # l'agent, blocs gardés ; déjà déconnecté : rien à faire ; puis login. Ligne Include
        # posée dans le ~/.ssh/config du HOME de test (sinon --check rend toujours 1)
        r = sv(home, "logout")
        ok(r, 2, "logout sans --account, plusieurs comptes")
        r = sv(home, "--nointeraction", "ssh-config", "install")
        ok(r, 0, "ssh-config install")
        for a, acct in zip(aliases, accounts):
            if HAVE_OPENSSH:
                ensure_all()
            r = sv(home, "--nointeraction", "ssh-config")
            ok(r, 0, "ssh-config avant logout %s" % a)
            r = sv(home, "--nointeraction", "ssh-config", "--check")
            ok(r, 0, "ssh-config --check avant logout %s" % a)
            before = open(cfg).read()
            r = sv(home, "logout", "--account", a)
            ok(r, 0, "logout --account %s" % a)
            need("compte %s déconnecté" % a in r.stdout, "logout %s : sortie inattendue" % a)
            need(bw_status(a) == "unauthenticated", "logout %s : bw non déconnecté" % a)
            # session relue par le magasin de sshvault lui-même (keyring ou repli fichier)
            r = subprocess.run([sys.executable, "-c", "from sshvault.session import SessionStore; "
                                "print(SessionStore(alias=%r).get() is None)" % a],
                               env=home["env"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
            need(r.returncode == 0 and r.stdout.strip() == "True", "logout : session de %s non oubliée" % a)
            need(open(cfg).read() == before, "logout %s : blocs non gardés" % a)
            if HAVE_OPENSSH:
                need(loaded() == sorted(b for x, b in blob.items() if x != a),
                     "logout %s : autre chose que sa seule clé retirée" % a)
                # marqueur `logged-out` : ensure sans invite propose login (vrai `bw status`)
                r = sv(home, "--nointeraction", "ensure", "--account", a, "--id", ids[a])
                ok(r, 3, "ensure après logout %s" % a)
                need("sshvault login --account %s" % a in r.stderr, "ensure après logout %s : login non proposé" % a)
            r = sv(home, "--nointeraction", "ssh-config", "--check")
            ok(r, 0, "ssh-config --check après logout %s" % a)
            need(open(cfg).read() == before, "ssh-config --check après logout %s : blocs non gardés" % a)
            r = sv(home, "logout", "--account", a)
            ok(r, 0, "logout de %s déjà déconnecté" % a)
            need("rien à faire" in r.stdout, "logout de %s déjà déconnecté : sortie inattendue" % a)
            out = sv_login(home, acct, report, alias=a, own=own[a])
            need("compte %s : connecté, coffre déverrouillé" % a in out, "login %s après logout" % a)
            if HAVE_OPENSSH:
                r = sv(home, "--nointeraction", "ensure", "--account", a, "--id", ids[a])
                ok(r, 0, "ensure %s après logout puis login (marqueur retiré)" % a)
            report.add("logout puis login (compte %s)" % a, note="ok")

        # account set aller-retour sur chaque compte : e-mail factice (logout, blocs retirés),
        # puis le vrai, login
        for a, acct in zip(aliases, accounts):
            fake = "sshvault-it-%s-%s@example.invalid" % (TAG, a)
            r = sv(home, "account", "set", a, "--email", fake)
            ok(r, 0, "account set %s (aller)" % a)
            need("déconnecté de l'ancien compte" in r.stdout and "sshvault login --account %s" % a in r.stdout,
                 "account set %s (aller) : sortie inattendue" % a)
            need(bw_status(a) == "unauthenticated", "account set %s : bw non déconnecté" % a)
            text = open(cfg).read()
            need("--account %s --id" % a not in text, "account set %s : blocs non retirés" % a)
            need(all("--account %s --id" % x in text for x in aliases if x != a),
                 "account set %s : blocs des autres comptes retirés" % a)
            r = sv(home, "account", "set", a, "--email", fake.upper())
            ok(r, 0, "account set %s sans changement" % a)
            need("rien fait" in r.stdout, "account set %s sans changement : sortie inattendue" % a)
            r = sv(home, "account", "set", a, "--email", acct.email)
            ok(r, 0, "account set %s (retour)" % a)
            out = sv_login(home, acct, report, alias=a, own=own[a])
            need("compte %s : connecté, coffre déverrouillé" % a in out, "login %s après account set" % a)
            r = sv(home, "--nointeraction", "status", "--account", a)
            ok(r, 0, "status %s après account set et login" % a)
            need("avertissement" not in r.stderr, "status %s après account set : avertissement" % a)
            need("ensure --account %s --id %s\"" % (a, ids[a]) in open(cfg).read(), "login %s : blocs non régénérés" % a)
            report.add("account set aller-retour (compte %s)" % a, note="ok")
        r = sv(home, "lock")
        ok(r, 0, "lock de tous les comptes")
        for a in aliases:
            need(not os.path.exists(os.path.join(home["runtime"], "sshvault", "sessions", a)),
                 "lock : session de %s gardée" % a)
            need(bw_status(a) == "locked", "lock : bw de %s non verrouillé" % a)
        report.add("plusieurs comptes", note="%d comptes (%s) : list, account default, ssh-config, ensure, logout puis "
                                            "login, account set aller-retour : ok" % (len(aliases), ", ".join(aliases)))
    finally:
        try:
            for a, (pop, appdata, session) in pops.items():
                if session:
                    try:
                        problems += purge_marked(pop, session, report, "fin, compte %s" % a)
                    except Exception as e:
                        problems.append("purge interrompue (compte %s) : %s: %s" % (a, type(e).__name__, e))
        finally:
            for a, (pop, appdata, _) in pops.items():
                try:
                    report.add("logout (compte %s, peuplement)" % a, pop.run("logout"))
                    report.add("logout (compte %s, sshvault)" % a, own[a].run("logout"))
                finally:
                    shutil.rmtree(appdata, ignore_errors=True)
    if problems:
        pytest.fail(scrub("nettoyage incomplet (comptes au-delà du premier) : " + " ; ".join(problems)))


def test_adoption_rename_remove_sur_le_vrai_bw(account, bw_exe, home, report):
    """Installation 0.8.0 dans le HOME de test (bw connecté dans `sshvault/bw`, aucun registre) :
    adoptée par le premier lancement (alias déduit de l'e-mail, données déplacées, compte par
    défaut), utilisée après déverrouillage ; `account rename` (session déplacée : lecture sans
    invite) puis `account remove` (données supprimées, registre vide). Aucun élément créé dans le
    coffre ; dossiers réels jamais touchés (HOME, XDG du test)."""
    from sshvault.config import alias_from_email
    data = os.path.join(home["env"]["HOME"], ".local", "share", "sshvault")
    legacy = os.path.join(data, "bw")
    alias = alias_from_email(account.email)
    renamed = "itr" if alias != "itr" else "itr2"
    dirs = [legacy, os.path.join(data, "accounts", alias, "bw"), os.path.join(data, "accounts", renamed, "bw")]
    ask = {"SSH_ASKPASS": home["askpass"], "SSH_ASKPASS_REQUIRE": "force", "SSHVAULT_IT_ASKPASS_REPLY": account.password}

    def ok(r, rc, what):
        if r.returncode != rc:
            raise AssertionError(account.scrub("%s : code %d attendu, %d obtenu ; stderr : %s"
                                               % (what, rc, r.returncode, r.stderr.strip())))
        assert "Traceback" not in r.stderr

    try:
        os.makedirs(data, mode=0o700)
        Bw(bw_exe, legacy, account, report).login()  # disposition 0.8.0 : sshvault/bw, connecté
        assert not os.path.exists(os.path.join(home["env"]["HOME"], ".config", "sshvault", "config.json"))
        r = sv(home, "--nointeraction", "status")
        report.add("adoption 0.8.0 (vrai bw)", note="rc=%d" % r.returncode)
        ok(r, 3, "status : adoption, coffre verrouillé")
        adopted = "installation 0.8.0 adoptée : compte « %s »" % alias in r.stderr
        assert adopted, "ligne d'adoption absente"
        assert not os.path.exists(legacy) and os.path.isdir(dirs[1]), "données déplacées"
        r = sv(home, "account", "list")
        listed = r.stdout.split("\t")[0] == alias and r.stdout.rstrip().endswith("\tdéfaut")
        assert listed, "account list : alias déduit ou compte par défaut inattendu"
        r = sv(home, "unlock", env=ask)
        ok(r, 0, "unlock après adoption")
        r = sv(home, "--nointeraction", "list", "--json")
        ok(r, 0, "list après adoption")
        same = all(d["account"] == alias for d in json.loads(r.stdout))
        assert same, "list : alias des éléments"
        r = sv(home, "account", "rename", alias, renamed)
        ok(r, 0, "account rename")
        moved = "illisible" not in r.stderr and os.path.isdir(dirs[2]) and not os.path.exists(dirs[1])
        assert moved, "rename : données ou session non déplacées"
        r = sv(home, "--nointeraction", "list", "--account", renamed, "--json")
        ok(r, 0, "list après rename, sans invite (session déplacée)")
        r = sv(home, "account", "remove", renamed)
        ok(r, 0, "account remove")
        assert not os.path.exists(os.path.dirname(dirs[2])), "données locales supprimées"
        r = sv(home, "account", "list")
        empty = r.stdout.startswith("aucun compte")
        assert empty, "registre non vide après remove"
        assert not os.path.exists(os.path.join(home["runtime"], "sshvault", "sessions", renamed))
        report.add("adoption, rename, remove (vrai bw)", note="ok")
    finally:
        for d in dirs:  # login laissé par un échec en chemin : déconnecté
            if os.path.isdir(d):
                report.add("logout (adoption, %s)" % os.path.basename(os.path.dirname(d)),
                           Bw(bw_exe, d, account, report).run("logout"))


@pytest.mark.skipif(not os.environ.get(LOGIN_REPEAT),
                    reason="mesure du code de `sshvault login` : opt-in, SSHVAULT_IT_LOGIN_REPEAT=N")
def test_login_repete_sur_le_vrai_bw(account, home, report):
    """Mesure (pas un correctif) : un `sshvault login` sous pty a rendu 3 une fois sur 4
    (2026-10-13). N essais (`SSHVAULT_IT_LOGIN_REPEAT=N`) de `sshvault login` puis `sshvault
    logout`, HOME temporaire, 1er compte du fichier ; au moins 7 s entre la fin d'un essai et le
    début du suivant. Rapport : rc de chaque essai (durée, invites vues, rc du logout), sortie
    et fin du terminal de chaque échec (masquées), décompte par code. Échec si un essai rend
    autre chose que 0 (connexion bloquée comprise). `logout` en échec entre deux essais :
    anomalie (comptée dans les échecs), `bw logout` à la main (rc dans le rapport) ; s'il
    échoue aussi, la série s'arrête (l'essai suivant commencerait déjà connecté)."""
    import collections
    scrub = report.account.scrub
    raw = os.environ[LOGIN_REPEAT].strip()
    n = int(raw) if raw.isdigit() else 0
    if n < 1:
        pytest.fail("%s : entier ≥ 1 attendu" % LOGIN_REPEAT, pytrace=False)
    r = sv(home, "account", "add", ALIAS, "--server", account.server, "--email", account.email)
    check(account, r, 0, "account add")
    rcs, fails, last_end, stopped = [], [], None, False
    for k in range(1, n + 1):
        if last_end is not None:
            time.sleep(max(0.0, LOGIN_GAP - (time.monotonic() - last_end)))
        res = pty_login(home, account)
        rc = "bloqué" if res["blocked"] else res["rc"]
        lo = sv(home, "logout")
        manual = None
        if res["blocked"] or lo.returncode != 0:
            # login interrompu, ou logout en échec : bw déconnecté à la main, sinon l'essai
            # suivant commencerait déjà connecté
            manual = home["bw"].run("logout")
        last_end = time.monotonic()
        rcs.append(rc)
        note = "essai %d/%d : rc=%s durée=%.1fs invites=%s ; logout rc=%d" % (
            k, n, rc, res["duration"], res["invites"], lo.returncode)
        if rc != 0:
            note += " ; sortie : %r ; terminal après l'invite (masqué) : %r" % (
                scrub(res["out"].strip()[-300:]), res["tail"])
        if lo.returncode != 0:
            note += " ; anomalie : logout en échec (stderr : %r)" % scrub(lo.stderr.strip()[-300:])
        if manual is not None:
            note += " ; bw logout à la main rc=%d" % manual.returncode
            if manual.returncode != 0 and "You are not logged in." not in (manual.stderr or ""):
                note += " ; anomalie : bw logout à la main en échec (stderr : %r) : série arrêtée" % scrub(
                    (manual.stderr or "").strip()[-300:])
                stopped = True
        if rc != 0 or lo.returncode != 0 or stopped:
            fails.append(note)
        report.add("login répété", note=note)
        if stopped:
            break
    counts = collections.Counter(str(rc) for rc in rcs)
    summary = ", ".join("rc=%s : %d" % (c, counts[c]) for c in sorted(counts))
    report.add("login répété : décompte", note="%d essais sur %d%s ; %s" % (
        len(rcs), n, " (série arrêtée)" if stopped else "", summary))
    if fails:
        raise AssertionError(scrub("sshvault login répété : %d échec(s) ou anomalie(s) sur %d essais (%s) ; %s"
                                   % (len(fails), len(rcs), summary, " | ".join(fails))))

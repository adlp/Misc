"""Socle commun des tests opt-in (`integration`, `lab`) : vrai `bw`, compte de test, peuplement
marqué du coffre, HOME temporaire de sshvault.

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

Déplacé de `test_integration.py` sans changement de comportement (fixtures `report`, `ssh_keys`,
`vault`, `home`, clients `Bw`, `sv`, `sv_login`, `check`, `purge_marked`…), pour être partagé avec
`test_lab.py` ; les deux modules l'importent. Aucune marque pytest ici : chaque module pose la
sienne.
"""
import base64
import json
import os
import pty
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
from bench import RUN_ID, SRC, check_witness, kill_agents_under, private_runtime_dir, write_exe

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

    def flush(self, suffix=""):
        """Écrit le rapport dans SSHVAULT_IT_REPORT (+ `suffix` : la série `lab` ajoute « .lab »)."""
        path = os.environ.get("SSHVAULT_IT_REPORT")
        if path:
            with open(path + suffix, "w") as f:
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
               SSHVAULT_PROMPT_TIMEOUT="30", SSHVAULT_BW_TIMEOUT="180", SSHVAULT_TEST_BENCH="1", SSHVAULT_TEST_RUN=RUN_ID,
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


def sv(home, *args, env=None, input=None):
    """sshvault dans le HOME de test ; stdin /dev/null, ou `input` (texte) sur un tube."""
    e = dict(home["env"])
    e.update(env or {})
    io = {"stdin": subprocess.DEVNULL} if input is None else {"input": input}
    return subprocess.run([sys.executable, "-m", "sshvault", *args], env=e, capture_output=True, text=True,
                          timeout=600, start_new_session=True, **io)


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
    sshvault interrompu (SIGTERM), `blocked` vrai.
    `home["login_argv"]` (et `home["login_env"]`) : commande de login à lancer à la place de `python -m sshvault login`
    (`docker exec -it` dans le conteneur client de la maquette, story 21) : `--account ALIAS` lui est ajouté."""
    master, slave = pty.openpty()
    name = os.ttyname(slave)

    def ctty():
        os.close(os.open(name, os.O_RDWR))

    t0 = time.monotonic()
    p = subprocess.Popen(list(home.get("login_argv") or [sys.executable, "-m", "sshvault", "login"])
                         + (["--account", alias] if alias else []),
                         env=home.get("login_env") or home["env"], stdin=slave,
                         # docker exec -t : tout ce que le conteneur écrit revient sur la sortie du client docker, qui
                         # doit donc être le terminal (la sortie de sshvault est alors dans `seen`, pas dans `out`)
                         stdout=slave if home.get("login_argv") else subprocess.PIPE, stderr=slave,
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
        out = read_pipe(p.stdout).decode(errors="replace") if p.stdout else ""
        tail = ""
        if p.returncode:
            i = seen.rfind(b"Master password")
            rest = seen[i + len(b"Master password"):] if i >= 0 else seen
            tail = account.scrub(rest.decode(errors="replace").strip()[-300:])
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        if p.stdout:
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

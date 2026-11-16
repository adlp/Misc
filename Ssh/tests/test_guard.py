"""`session_guard` (tests/bench.py) ne compte que les processus de CE run : un `ssh-agent` d'une autre suite sshvault
(dossier `/dev/shm/sshvault-test-<autre run>-…`, environnement illisible) n'est pas un reste, celui de ce run l'est
(story 23).

Le critère d'acceptation est rejoué par un vrai pytest enfant (conftest : la garde de `bench`, délai ramené à 1 s) dont
le seul test laisse volontairement vivant un `ssh-agent` dans un dossier d'un autre run, puis de son propre run. Les agents
d'un run interrompu (pytest disparu) sont signalés par un avertissement, jamais un échec.

Registre des runs (`bench.REGISTRY_DIR`) : la fixture automatique `registry_dir` le redirige vers un dossier temporaire, mais
seulement pour les appels EN PROCESSUS de `register_run`, `remove_dead_registrations`, `run_alive` et `orphan_agents`. Le vrai
/dev/shm, où vivent les inscriptions des autres runs en cours, est encore touché par : le témoin de
`test_inscription_impossible_est_un_avertissement` (une inscription d'allure morte qu'il pose puis retire), les dossiers
d'agents (`agent_dir`, `test_inner_stop_verifie_socket_et_date_de_debut`, `test_agent_de_ce_run_n_est_pas_un_orphelin`), la
lecture de l'inscription de ce run (`test_ce_run_est_inscrit_pendant_la_session`) et le pytest enfant, dont `register_run`
inscrit son run et retire, dans le vrai /dev/shm, les inscriptions et temporaires morts de l'utilisateur (ménage normal de
`register_run`, que le test ne peut pas rediriger)."""
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import pytest

import bench
from bench import (FAKE_BW, GUARD_VAR, HAVE_OPENSSH, HERE, RUN_ID, RUN_VAR, kill_agents_under, orphan_agents, proc_alive,
                   processes_matching, register_run, run_alive, run_leftovers, shm_prefix, start_agent, wait_gone)

needs_agent = pytest.mark.skipif(not HAVE_OPENSSH, reason="ssh-agent absent")

REAL_SHM = "/dev/shm"


def real_registry(run_id):
    """Inscription d'un run dans le vrai /dev/shm (pytest enfant seulement)."""
    return "%s/sshvault-test-%s.run" % (REAL_SHM, run_id)


@pytest.fixture(autouse=True)
def registry_dir(tmp_path, monkeypatch):
    """Dossier du registre de CE test : temporaire. Les appels en processus de `register_run`, `remove_dead_registrations`,
    `run_alive` et `orphan_agents` n'atteignent pas le vrai /dev/shm (voir le docstring du module pour ce qui l'atteint encore)."""
    d = tmp_path / "registre"
    d.mkdir()
    monkeypatch.setattr(bench, "REGISTRY_DIR", str(d))
    return d


def registry(run_id):
    return bench._registry(run_id)


INNER_CONFTEST = '''
import bench
from bench import session_guard  # noqa: F401

bench.GUARD_WAIT = 1
'''

#: seul test du pytest enfant : un ssh-agent laissé vivant (détaché), dans le dossier désigné par INNER_MODE. INNER_FILE :
#: ligne 1 « <RUN_ID de l'enfant> <dossier> » écrite avant de lancer l'agent, ligne 2 « <pid de l'agent> <date de début> »
#: après (chaque ligne terminée par un saut de ligne : une ligne tronquée n'est pas lue)
INNER_TEST = '''
import os
import tempfile

import bench


def test_laisse_un_agent():
    mode = os.environ["INNER_MODE"]
    prefix = bench.shm_prefix("run") if mode == "run" else "sshvault-test-%s-run-" % os.environ["INNER_OTHER"]
    d = tempfile.mkdtemp(prefix=prefix, dir="/dev/shm")
    os.chmod(d, 0o700)
    with open(os.environ["INNER_FILE"] + ".reg", "w") as f:  # ce run est inscrit pendant la session
        f.write("1" if bench.run_alive(bench.RUN_ID) else "0")
    with open(os.environ["INNER_FILE"], "w") as f:
        f.write("%s %s\\n" % (bench.RUN_ID, d))
        f.flush()
        pid = bench.start_agent(os.path.join(d, "agent.sock"))
        f.write("%d %s\\n" % (pid, bench._stat_fields(pid)[1]))
'''


def is_agent_under(pid, d, started):
    """`/proc/<pid>` est-il bien l'ssh-agent lancé par l'enfant : exécutable de nom de base `ssh-agent`, socket (`-a`) sous
    `d`, même date de début que celle relevée au lancement (un pid réutilisé n'a pas la même) ?"""
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            argv = f.read().split(b"\0")
        now = bench._stat_fields(pid)[1]
    except (OSError, ValueError, IndexError):
        return False
    if os.path.basename(argv[0]) != b"ssh-agent" or now != started:
        return False
    return any(argv[i] == b"-a" and argv[i + 1].startswith(d.encode() + b"/") for i in range(len(argv) - 1))


class Inner:
    """Résultat du pytest enfant : `r` (CompletedProcess ou None si délai dépassé), `run_id`, `dir`, `pid` et `started`
    (agent laissé, date de début relevée par l'enfant)."""

    def __init__(self):
        self.r = self.run_id = self.dir = self.pid = self.started = None

    def read(self, info):
        """Lit le fichier d'information : seules les lignes complètes (terminées par un saut de ligne), jamais d'exception qui
        masquerait la vraie cause."""
        try:
            lines = info.read_text().split("\n")[:-1]
            if lines and " " in lines[0]:
                self.run_id, self.dir = lines[0].split(" ", 1)
            if len(lines) > 1 and len(lines[1].split()) == 2:
                pid, self.started = lines[1].split()
                self.pid = int(pid)
        except (OSError, ValueError):
            pass

    def stop(self):
        """Arrête l'agent de l'enfant seulement s'il est vérifié (`is_agent_under`), puis tout ssh-agent sous le dossier de
        l'enfant (même s'il a planté avant d'écrire le pid) ; retire dossier et inscription."""
        mine = self.pid is not None and self.dir is not None and is_agent_under(self.pid, self.dir, self.started)
        try:
            if mine:
                try:
                    os.kill(self.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            if self.dir and os.path.isdir(self.dir):
                kill_agents_under(self.dir)
            if mine:
                assert wait_gone([self.pid]), "ssh-agent de test encore vivant : %s" % self.pid
        finally:
            if self.dir:
                shutil.rmtree(self.dir, ignore_errors=True)
            if self.run_id:  # inscription de l'enfant, dans le vrai /dev/shm : la sienne seulement
                try:
                    os.unlink(real_registry(self.run_id))
                except OSError:
                    pass


def run_inner(tmp_path, mode, inner_out):
    """Lance le pytest enfant en `mode` (« autre » : agent dans le dossier d'un autre run, sans inscription : run interrompu ;
    « run » : dans un dossier de son propre run) ; remplit `inner_out` (`Inner`). L'appelant l'arrête (`inner_out.stop()`) ;
    ici, en cas de délai dépassé ou de plantage avant l'écriture du pid, les agents sous le dossier de l'enfant sont arrêtés."""
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "conftest.py").write_text(INNER_CONFTEST)
    (inner / "test_inner.py").write_text(INNER_TEST)
    (inner / "pytest.ini").write_text("[pytest]\n")
    info = tmp_path / "agent.info"
    env = {k: v for k, v in os.environ.items() if (not k.startswith(("SSHVAULT_", "PYTEST_"))) or k == GUARD_VAR}
    env.update(PYTHONPATH=HERE, INNER_MODE=mode, INNER_OTHER=uuid.uuid4().hex, INNER_FILE=str(info))
    try:
        inner_out.r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", str(inner / "pytest.ini"),
             "--rootdir", str(inner), "--basetemp", str(tmp_path / "inner-tmp"), str(inner / "test_inner.py")],
            env=env, cwd=str(inner), capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    except BaseException:
        inner_out.read(info)
        inner_out.stop()
        raise
    finally:
        inner_out.read(info)
    if inner_out.r.returncode not in (0, 1) or inner_out.pid is None:  # plantage ou pas d'agent : rien ne doit rester
        inner_out.stop()


def summary(out):
    """Ligne de résumé de pytest (-q) : `<n> passed[, …] in <t>s`, la dernière ligne non vide, texte entier."""
    lines = [l for l in out.splitlines() if l.strip()]
    assert lines, "sortie vide"
    return lines[-1].strip("= ")


@needs_agent
def test_agent_d_un_autre_run_ignore(tmp_path):
    res = Inner()
    try:
        run_inner(tmp_path, "autre", res)
        r = res.r
        assert res.pid is not None, "le pytest enfant n'a pas lancé son agent : %s %s" % (r.stdout[-1500:], r.stderr[-1500:])
        assert proc_alive(res.pid), "l'agent de l'autre run est resté vivant pendant la garde de l'enfant"
        assert r.returncode == 0, "la garde de l'enfant doit passer : %s" % r.stdout[-2000:]
        with open(str(tmp_path / "agent.info") + ".reg") as f:
            assert f.read() == "1", "le run de l'enfant est inscrit pendant sa session"
        assert not os.path.exists(real_registry(res.run_id)), "inscription retirée à la fin de la session de l'enfant"
        # un test passé, aucune erreur (d'autres avertissements, de garde ou de plugin, sont tolérés) ; l'agent d'un run
        # interrompu est signalé par un seul avertissement, qui le nomme
        assert re.fullmatch(r"1 passed(, \d+ warnings?)? in [0-9.]+s( \(\S+\))?", summary(r.stdout)), r.stdout[-1500:]
        assert r.stdout.count("UserWarning: processus de test d'un run interrompu") == 1 and str(res.pid) in r.stdout, \
            "l'agent d'un run interrompu est signalé : %s" % r.stdout[-1500:]
    finally:
        res.stop()


@needs_agent
def test_agent_de_ce_run_signale(tmp_path):
    res = Inner()
    try:
        run_inner(tmp_path, "run", res)
        r = res.r
        assert res.pid is not None, "le pytest enfant n'a pas lancé son agent : %s %s" % (r.stdout[-1500:], r.stderr[-1500:])
        assert r.returncode != 0, "la garde de l'enfant doit échouer : %s" % r.stdout[-2000:]
        assert re.fullmatch(r"1 passed(, \d+ warnings?)?, 1 error in [0-9.]+s( \(\S+\))?", summary(r.stdout)), r.stdout[-1500:]
        assert "processus de test restants" in r.stdout and str(res.pid) in r.stdout and "ssh-agent" in r.stdout, r.stdout[-2000:]
        assert res.dir in r.stdout, "le dossier du run est nommé : %s" % r.stdout[-2000:]
    finally:
        res.stop()


# --- agents d'un run interrompu : `orphan_agents`, inscription des runs (dossier temporaire du registre) ---------------

def agent_dir(run_id):
    d = "%s/sshvault-test-%s-run-orph" % (REAL_SHM, run_id)  # dossier d'agent : /dev/shm (le chemin que vise `orphan_agents`)
    os.mkdir(d, 0o700)
    return d


def stop_agents(pids, dirs):
    try:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        assert wait_gone(pids), "ssh-agent de test encore vivant : %s" % pids
    finally:
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)


@needs_agent
def test_agents_d_un_run_disparu_listes_pas_ceux_d_un_run_vivant():
    dead, alive = uuid.uuid4().hex, uuid.uuid4().hex
    dirs, pids = [], []
    try:
        for rid in (dead, alive):
            dirs.append(agent_dir(rid))
            pids.append(start_agent(os.path.join(dirs[-1], "agent.sock")))
        register_run(alive)  # `alive` : inscription de CE pytest (pid et date de début) ; `dead` : aucune inscription
        assert run_alive(alive) and not run_alive(dead)
        found = {pid for pid, _ in orphan_agents()}
        assert pids[0] in found, "agent d'un run sans pytest : listé"
        assert pids[1] not in found, "agent d'un run dont le pytest existe : pas listé"
        # même pid, autre date de début (pid réutilisé par un autre processus) : le run est disparu, listé
        register_run(alive, started="1")
        assert not run_alive(alive)
        assert pids[1] in {pid for pid, _ in orphan_agents()}
        # pid disparu : listé aussi
        with open(registry(alive), "w") as f:
            f.write("2147483646 1")
        assert pids[1] in {pid for pid, _ in orphan_agents()}
    finally:
        stop_agents(pids, dirs)


def test_ce_run_est_inscrit_pendant_la_session(monkeypatch):
    """`session_guard` inscrit le run (fichier ordinaire 0600, pid et date de début de pytest) dans le vrai /dev/shm ; l'enfant
    de `test_agent_d_un_autre_run_ignore` prouve qu'il est retiré à la fin. Lecture seule de la propre inscription de ce run."""
    path = real_registry(RUN_ID)
    if not bench.REGISTERED:
        pytest.skip("inscription de ce run ratée (avertissement de `register_run` : /dev/shm non inscriptible ?)")
    assert os.path.lexists(path), "l'inscription de ce run a réussi : elle a été supprimée en cours de session"
    monkeypatch.setattr(bench, "REGISTRY_DIR", REAL_SHM)
    assert run_alive(RUN_ID)
    st = os.lstat(path)
    assert stat.S_ISREG(st.st_mode) and st.st_mode & 0o777 == 0o600 and st.st_uid == os.getuid()
    with open(path) as f:
        assert f.read().split()[0] == str(os.getpid())


def test_inscription_impossible_est_un_avertissement(tmp_path, monkeypatch):
    """Dossier du registre inexistant : un avertissement. Le vrai /dev/shm n'est pas listé : l'inscription d'un autre run qui y
    est posée avec l'allure d'un run MORT (même pid que ce pytest, date de début fausse) survit ; une régression qui listerait le
    vrai /dev/shm la retirerait (inscription morte d'un fichier ordinaire de l'utilisateur) et ferait échouer ce test."""
    other = uuid.uuid4().hex
    witness = real_registry(other)
    with open(witness, "w") as f:
        f.write("%d 1" % os.getpid())  # date de début fausse : run mort
    try:
        monkeypatch.setattr(bench, "REGISTRY_DIR", str(tmp_path / "inexistant"))
        assert bench.REGISTRY_DIR != REAL_SHM
        with pytest.warns(UserWarning, match="inscription du run impossible"):
            register_run(uuid.uuid4().hex)
        assert os.path.exists(witness), "l'inscription (morte) d'un autre run, dans le vrai /dev/shm, est intacte"
    finally:
        try:
            os.unlink(witness)
        except OSError:
            pass


def test_inscription_exception_quelconque_est_un_avertissement(registry_dir, monkeypatch):
    """Une exception autre qu'`OSError` (lecture de /proc/self/stat) : avertissement, aucun fichier temporaire laissé."""
    def boom(pid):
        raise ValueError("stat illisible")
    monkeypatch.setattr(bench, "_stat_fields", boom)
    with pytest.warns(UserWarning, match="inscription du run impossible"):
        register_run(uuid.uuid4().hex)
    assert os.listdir(str(registry_dir)) == [], "ni inscription ni temporaire"


def test_inscription_retire_les_inscriptions_et_temporaires_morts_et_rien_d_autre(registry_dir, tmp_path):
    """Retirés : fichiers ordinaires de l'utilisateur dont le run (ou le pid) est mort. Gardés : run vivant, lien, dossier, nom
    étranger, temporaire d'un pid vivant."""
    dead, alive, link, folder, tmp_dead, tmp_live = (uuid.uuid4().hex for _ in range(6))
    other = registry_dir / ("sshvault-test-pas-une-inscription-%s.run" % uuid.uuid4().hex)
    target = tmp_path / "cible"
    target.write_text("cible")
    with open(registry(dead), "w") as f:
        f.write("2147483646 1")
    os.symlink(str(target), registry(link))
    os.mkdir(registry(folder))
    other.write_text("2147483646 1")
    dead_tmp = "%s.2147483646.tmp" % registry(tmp_dead)
    live_tmp = "%s.%d.tmp" % (registry(tmp_live), os.getpid())
    for t in (dead_tmp, live_tmp):
        with open(t, "w") as f:
            f.write("x")
    register_run(alive)  # retire d'abord les inscriptions mortes
    assert not os.path.lexists(registry(dead)), "inscription morte : retirée"
    assert not os.path.lexists(dead_tmp), "temporaire d'un pid disparu : retiré"
    assert os.path.exists(live_tmp), "temporaire d'un pid vivant : gardé"
    assert run_alive(alive), "run vivant : gardé"
    assert os.path.islink(registry(link)) and target.read_text() == "cible", "lien : jamais touché"
    assert os.path.isdir(registry(folder)), "dossier : jamais touché"
    assert other.exists(), "autre nom : jamais touché"


def test_run_alive_ne_suit_pas_les_liens_et_ne_bloque_pas_sur_une_fifo(tmp_path):
    """Une FIFO prend la place de l'inscription : refusée sans attendre (O_NONBLOCK) ; un lien vers une inscription valide :
    refusé (O_NOFOLLOW) ; une inscription ordinaire valide : acceptée."""
    fifo, link, good = (uuid.uuid4().hex for _ in range(3))
    valid = "%d %s" % (os.getpid(), bench._stat_fields(os.getpid())[1])
    os.mkfifo(registry(fifo))
    target = tmp_path / "valide"
    target.write_text(valid)
    os.symlink(str(target), registry(link))
    with open(registry(good), "w") as f:
        f.write(valid)
    result = {}
    t = threading.Thread(target=lambda: result.update(fifo=run_alive(fifo), link=run_alive(link), good=run_alive(good)),
                         daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive(), "`run_alive` ne doit pas bloquer sur une FIFO"
    assert result == {"fifo": False, "link": False, "good": True}, result


@needs_agent
def test_agent_de_ce_run_n_est_pas_un_orphelin():
    d = tempfile.mkdtemp(prefix=shm_prefix("run"), dir=REAL_SHM)
    os.chmod(d, 0o700)
    pid = start_agent(os.path.join(d, "agent.sock"))
    try:
        assert pid not in {p for p, _ in orphan_agents()}
        assert pid in {p for p, _ in run_leftovers(d)}, "mais c'est un reste de ce run"
    finally:
        stop_agents([pid], [d])


# --- `Inner.stop` : jamais de signal à un processus qui n'est pas l'agent de l'enfant ----------------------------------

def inner_for(pid, d, started):
    res = Inner()
    res.pid, res.dir, res.started = pid, d, started
    return res


def test_inner_stop_ne_tue_pas_un_processus_etranger(tmp_path):
    """Pid d'un processus qui n'est pas un ssh-agent (pid réutilisé) : aucun signal."""
    p = subprocess.Popen(["sleep", "30"])
    try:
        d = str(tmp_path / "dossier")
        os.mkdir(d)
        inner_for(p.pid, d, bench._stat_fields(p.pid)[1]).stop()
        assert p.poll() is None, "le processus étranger est toujours vivant"
    finally:
        p.kill()
        p.wait()


@needs_agent
def test_inner_stop_verifie_socket_et_date_de_debut(tmp_path):
    """Un ssh-agent dont la socket n'est pas sous le dossier de l'enfant, ou dont la date de début n'est pas celle relevée : pas
    signalé."""
    d = tempfile.mkdtemp(prefix=shm_prefix("run"), dir=REAL_SHM)
    os.chmod(d, 0o700)
    pid = start_agent(os.path.join(d, "agent.sock"))
    try:
        started = bench._stat_fields(pid)[1]
        elsewhere = str(tmp_path / "autre-dossier")
        os.mkdir(elsewhere)
        inner_for(pid, elsewhere, started).stop()
        assert proc_alive(pid), "socket hors du dossier de l'enfant : pas signalé"
        assert not is_agent_under(pid, d, "1") and is_agent_under(pid, d, started), "la date de début est comparée"
        # ligne du pid tronquée (« 12 » au lieu de « 1234 5678 ») : rien n'est lu
        info = tmp_path / "info"
        info.write_text("%s %s\n%d" % (uuid.uuid4().hex, d, pid))
        res = Inner()
        res.read(info)
        assert res.pid is None and res.dir == d
    finally:
        stop_agents([pid], [d])


# --- `collect_guard` : chaque étape protégée, tous les verdicts réunis -------------------------------------------------

def guard_setup(tmp_path, monkeypatch, runtime_change):
    """Restes de ce run simulés, étape des orphelins qui lève, et un dossier « réel » modifié (`~/.ssh` ou, avec
    `runtime_change`, le dossier de runtime sshvault, dont les changements sont tolérables sous SSHVAULT_TEST_GUARD=warn)."""
    def boom():
        raise RuntimeError("boom")
    monkeypatch.setattr(bench, "run_leftovers", lambda basetemp, root=None: [(1, "reste")])
    monkeypatch.setattr(bench, "orphan_agents", boom)
    paths = {k: str(tmp_path / k) for k in ("ssh", "runtime", "data", "config")}
    before = {k: None for k in paths}
    if runtime_change:  # dossier existant avant la session, un fichier y apparaît
        os.mkdir(paths["runtime"])
        before["runtime"] = bench.snapshot(paths["runtime"])
        changed = paths["runtime"]
    else:
        os.mkdir(paths["ssh"])  # `~/.ssh` « réel » apparu pendant la session
        changed = paths["ssh"]
    with open(os.path.join(changed, "x"), "w") as f:
        f.write("x")
    return paths, before


def test_collect_guard_une_exception_ne_masque_pas_les_autres_verdicts(tmp_path, tmp_path_factory, monkeypatch):
    """Restes de ce run, étape des orphelins qui lève, dossier réel modifié : trois échecs, dans l'ordre, un seul relevé."""
    monkeypatch.delenv(GUARD_VAR, raising=False)  # le mode `warn` du poste ne change pas ce verdict
    paths, before = guard_setup(tmp_path, monkeypatch, runtime_change=False)
    failures, notes = bench.collect_guard(tmp_path_factory.getbasetemp(), paths, before, wait=0)
    assert failures[0] == "processus de test restants : [(1, 'reste')]", failures
    assert failures[1] == "processus d'un run interrompu : RuntimeError: boom", failures
    assert len(failures) == 3 and "~/.ssh réel modifié" in failures[2], failures
    assert notes == []


def test_collect_guard_sous_warn_un_changement_toleré_est_un_avertissement(tmp_path, tmp_path_factory, monkeypatch):
    """SSHVAULT_TEST_GUARD=warn (usage réel concurrent) : un changement dans un dossier sshvault réel existant n'est qu'un
    avertissement (`notes`), les deux autres verdicts restent des échecs."""
    monkeypatch.setenv(GUARD_VAR, "warn")
    paths, before = guard_setup(tmp_path, monkeypatch, runtime_change=True)
    failures, notes = bench.collect_guard(tmp_path_factory.getbasetemp(), paths, before, wait=0)
    assert failures == ["processus de test restants : [(1, 'reste')]",
                        "processus d'un run interrompu : RuntimeError: boom"], failures
    assert len(notes) == 1 and "garde de session (%s=warn)" % GUARD_VAR in notes[0] and "x" in notes[0], notes


# --- marqueurs communs (faux bw, …) et dossier temporaire : seulement dans la portée du run -------------------

def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if k != RUN_VAR}
    env.update(extra)
    return env


def pids_of(token):
    return [pid for pid, _ in processes_matching([token])]


def detached(token, env, *args):
    """Processus dormant dont la ligne de commande porte `args` puis `token`, reparenté hors de pytest (le shell qui le lance
    sort aussitôt) ; seul son environnement le rattache (ou non) au run. Attend (borné) qu'il apparaisse ; renvoie ses pids."""
    subprocess.run(["sh", "-c", '"$0" -c "import time; time.sleep(30)" "$@" "$TOKEN" >/dev/null 2>&1 &', sys.executable, *args],
                   env=dict(env, TOKEN=token), check=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        pids = pids_of(token)
        if pids:
            return pids
        time.sleep(0.05)
    raise AssertionError("le processus %s n'a pas démarré" % token)


def stop(token):
    pids = pids_of(token)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    assert wait_gone(pids), "processus de test encore vivants : %s" % pids


def test_marqueur_commun_hors_portee_ignore(tmp_path_factory):
    token = "autre-suite-" + uuid.uuid4().hex
    try:
        detached(token, clean_env(), FAKE_BW)
        assert not [x for x in run_leftovers(tmp_path_factory.getbasetemp()) if token in x[1]]
    finally:
        stop(token)


def test_marqueur_commun_du_run_signale(tmp_path_factory):
    token = "ce-run-" + uuid.uuid4().hex
    try:
        detached(token, clean_env(**{RUN_VAR: RUN_ID}), FAKE_BW)
        assert [x for x in run_leftovers(tmp_path_factory.getbasetemp()) if token in x[1]], "marqué par ce run : compté"
    finally:
        stop(token)


def test_dossier_temporaire_de_pytest_sans_confusion_de_numero(tmp_path_factory):
    """`<basetemp>/x` est de ce run ; `<basetemp>0/x` (pytest-10 pour pytest-1) ne l'est pas."""
    base = str(tmp_path_factory.getbasetemp())
    mine, other = "base-" + uuid.uuid4().hex, "base-" + uuid.uuid4().hex
    try:
        detached(mine, clean_env(), base + "/x")
        detached(other, clean_env(), base + "0/x")
        left = run_leftovers(tmp_path_factory.getbasetemp())
        assert [x for x in left if mine in x[1]], "dossier de ce run : compté"
        assert not [x for x in left if other in x[1]], "numéro voisin : ignoré"
    finally:
        stop(mine)
        stop(other)

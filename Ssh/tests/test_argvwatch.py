"""`ArgvWatch` (tests/bench.py) ne relève que les processus du test : descendants de pytest, ou marqués par
SSHVAULT_TEST_RUN=<RUN_ID> (identifiant de cette session pytest) dans leur environnement. La commande d'une autre
session de l'utilisateur (mesurée sur un vrai run : un `grep -rqF 'OPENSSH PRIVATE KEY'` dans un autre conteneur) n'est
pas une fuite du test."""
import os
import signal
import subprocess
import sys
import time
import uuid

from bench import RUN_ID, RUN_VAR, ArgvWatch, descends_from, in_scope, processes_matching, scope_of


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if k != RUN_VAR}
    env.update(extra)
    return env


def detached(token, env):
    """Processus dormant dont l'argument est « PRIVATE KEY <token> », reparenté hors de pytest (le shell qui le lance
    sort aussitôt). Le jeton ne passe que par l'environnement du lanceur : sa ligne de commande (un descendant de
    pytest, que le relevé pourrait échantillonner) ne le porte pas, seul le python détaché l'a en argument."""
    subprocess.run(["sh", "-c", '"$0" -c "import time; time.sleep(4)" "PRIVATE KEY $TOKEN" >/dev/null 2>&1 &',
                    sys.executable], env=dict(env, TOKEN=token), check=True)


def pids_of(token):
    return [pid for pid, cmd in processes_matching([token]) if cmd.startswith(sys.executable)]


def stop(token):
    for pid in pids_of(token):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def watched(token, start):
    with ArgvWatch(token, []) as w:
        start()
        time.sleep(0.5)
        found = pids_of(token)
    return w, found


def test_processus_etranger_sans_marqueur_ignore():
    token = "etranger-" + uuid.uuid4().hex
    try:
        w, found = watched(token, lambda: detached(token, clean_env()))
        assert found, "le processus étranger a bien tourné pendant le relevé"
        assert not any(descends_from(pid, os.getpid()) for pid in found), "hors de l'arbre de pytest"
        assert all(scope_of(str(pid), os.getpid()) is False for pid in found)
    finally:
        stop(token)
    assert not w.suspect and not w.seen, "autre session : ni fuite ni relevé (%s)" % w.suspect[:2]


def test_processus_marque_detache_signale():
    token = "marque-" + uuid.uuid4().hex
    try:
        w, found = watched(token, lambda: detached(token, clean_env(**{RUN_VAR: RUN_ID})))
        assert found, "le processus marqué a bien tourné pendant le relevé"
        assert not any(descends_from(pid, os.getpid()) for pid in found), "détaché : hors de l'arbre de pytest"
        assert all(in_scope(str(pid), os.getpid()) for pid in found), "retenu par le marqueur, pas par sa filiation"
    finally:
        stop(token)
    assert w.suspect and w.suspect[0][0] == sys.executable[:60] and any(token in a for a in w.suspect[0]), \
        "processus marqué : clé privée signalée, sur le python détaché (%s)" % w.suspect[:2]
    assert w.seen and all(a[0] == sys.executable for a in w.seen), "relevé : le python détaché seul"


def test_marqueur_d_une_autre_session_ignore():
    token = "autre-session-" + uuid.uuid4().hex
    try:
        w, found = watched(token, lambda: detached(token, clean_env(**{RUN_VAR: "autre-" + RUN_ID})))
        assert found
    finally:
        stop(token)
    assert not w.suspect and not w.seen, "le marqueur d'une autre session pytest ne rattache rien à celle-ci"


def test_descendant_de_pytest_signale():
    token = "descendant-" + uuid.uuid4().hex
    procs = []
    try:
        w, _ = watched(token, lambda: procs.append(subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(3)", "PRIVATE KEY " + token], env=clean_env())))
    finally:
        for p in procs:
            p.kill()
            p.wait()
    assert w.suspect and w.seen, "descendant de pytest, sans marqueur : signalé"


def test_portee():
    assert in_scope(str(os.getpid()), os.getpid())
    assert in_scope("1", os.getpid()), "environnement illisible (init, autre utilisateur) : échec fermé, du test"
    assert scope_of("2147483646", os.getpid()) is None, "processus disparu : rien à relever"

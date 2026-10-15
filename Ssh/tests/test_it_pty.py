"""`pty_login` du test d'intégration (`tests/integration/test_integration.py`), sans réseau ni
vrai sshvault : un faux paquet `sshvault` (PYTHONPATH) se termine aussitôt en laissant un
petit-enfant qui écrit sans fin sur le terminal et garde la sortie standard ouverte. Lecture du
reste du terminal et de la sortie : bornées (PTY_DRAIN_LIMIT, 5 s au plus)."""
import os
import pty
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "integration"))
import test_integration as integ  # noqa: E402  (collecté aussi par pytest : même module)

#: petit-enfant : écrit sur le terminal (stderr) toutes les 10 ms, 30 s au plus, garde stdout
CHILD = r'''
import os, signal, sys, time
signal.signal(signal.SIGHUP, signal.SIG_IGN)
with open(sys.argv[1], "w") as f:
    f.write(str(os.getpid()))
end = time.monotonic() + 30
while time.monotonic() < end:
    try:
        os.write(2, b"x" * 64)
    except OSError:
        break
    time.sleep(0.01)
'''

MAIN = r'''
import subprocess, sys, os, time
subprocess.Popen([sys.executable, "-c", %r, os.environ["FAKE_PIDFILE"]], stdin=subprocess.DEVNULL)
while not os.path.exists(os.environ["FAKE_PIDFILE"]):
    time.sleep(0.01)
print("fini", flush=True)
''' % CHILD


class Acct:
    email, password = "e@x.invalid", "pw"

    @staticmethod
    def scrub(text):
        return text


def test_limite_au_plus_5_s():
    assert integ.PTY_DRAIN_LIMIT <= 5


def test_pty_login_borne(tmp_path, monkeypatch):
    """pty_login rend la main malgré un petit-enfant qui écrit sans fin sur le terminal et garde
    la sortie standard ouverte : reste du terminal et sortie lus PTY_DRAIN_LIMIT secondes au
    plus chacun."""
    pkg = tmp_path / "fake" / "sshvault"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(MAIN)
    pidfile = tmp_path / "petit-enfant.pid"
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path), "PYTHONPATH": str(tmp_path / "fake"),
           "FAKE_PIDFILE": str(pidfile)}
    monkeypatch.setattr(integ, "PTY_DRAIN_LIMIT", 1.0)
    res = {}
    t = threading.Thread(target=lambda: res.update(integ.pty_login({"env": env}, Acct)), daemon=True)
    try:
        t.start()
        t.join(timeout=20)
        assert not t.is_alive(), "pty_login sans échéance (reste du terminal ou sortie standard)"
        assert pidfile.exists(), "petit-enfant jamais lancé"
        pid = int(pidfile.read_text())
        os.kill(pid, 0)  # toujours vivant : il écrivait encore pendant la lecture bornée
        assert (res["rc"], res["out"], res["blocked"]) == (0, "fini\n", False), res
        assert res["duration"] < 6, res["duration"]
    finally:
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        t.join(timeout=30)


def test_reste_du_terminal_borne():
    """`drain_pty` : arrêt à l'échéance même si un processus écrit sans fin sur le terminal ;
    silence : arrêt aussitôt (0,2 s)."""
    master, slave = pty.openpty()
    stop = threading.Event()

    def writer():
        while not stop.is_set():
            try:
                os.write(slave, b"x" * 64)
            except OSError:
                return
            time.sleep(0.01)
    w = threading.Thread(target=writer, daemon=True)
    w.start()
    res = {}

    def drain():
        t = time.monotonic()
        res["got"] = integ.drain_pty(master, limit=1.0)
        res["took"] = time.monotonic() - t
    d = threading.Thread(target=drain, daemon=True)
    try:
        d.start()
        d.join(timeout=10)
        assert not d.is_alive(), "lecture du reste du terminal sans échéance"
        assert res["got"] and 0.9 <= res["took"] < 2.0, res["took"]
    finally:
        stop.set()
        w.join(timeout=5)
        os.close(slave)
        d.join(timeout=10)
        os.close(master)
    master, slave = pty.openpty()
    try:
        os.write(slave, b"fin\n")
        t = time.monotonic()
        got = integ.drain_pty(master)
        assert b"fin" in got and time.monotonic() - t < 2.0
    finally:
        os.close(slave)
        os.close(master)

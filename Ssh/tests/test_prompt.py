"""Invite : règles de `man ssh` / readpass.c, délais, descripteurs et groupes de processus."""
import os
import time

import pytest

from sshvault import prompt as P


def env(**kw):
    return {k: v for k, v in kw.items() if v is not None}


ASK = "/usr/local/bin/mon-askpass"


@pytest.mark.parametrize("e,tty,expected", [
    # sans SSH_ASKPASS_REQUIRE : le terminal ; sans terminal, askpass si DISPLAY
    (env(), True, "tty"),
    (env(SSH_ASKPASS=ASK, DISPLAY=":0"), True, "tty"),
    (env(SSH_ASKPASS=ASK, DISPLAY=":0"), False, "askpass"),
    (env(SSH_ASKPASS=ASK, WAYLAND_DISPLAY="wayland-0"), False, "askpass"),
    (env(SSH_ASKPASS=ASK, DISPLAY=""), False, None),
    (env(SSH_ASKPASS=ASK), False, None),
    (env(DISPLAY=":0"), False, None),
    (env(), False, None),
    # prefer : askpass si DISPLAY, sinon le terminal
    (env(SSH_ASKPASS=ASK, DISPLAY=":0", SSH_ASKPASS_REQUIRE="prefer"), True, "askpass"),
    (env(SSH_ASKPASS=ASK, SSH_ASKPASS_REQUIRE="prefer"), True, "tty"),
    (env(DISPLAY=":0", SSH_ASKPASS_REQUIRE="prefer"), True, "tty"),  # SSH_ASKPASS absent : repli tty
    (env(SSH_ASKPASS=ASK, SSH_ASKPASS_REQUIRE="prefer"), False, None),
    # force : askpass même sans DISPLAY
    (env(SSH_ASKPASS=ASK, SSH_ASKPASS_REQUIRE="force"), True, "askpass"),
    (env(SSH_ASKPASS=ASK, SSH_ASKPASS_REQUIRE="FORCE"), False, "askpass"),
    (env(SSH_ASKPASS_REQUIRE="force"), True, "tty"),
    (env(SSH_ASKPASS_REQUIRE="force"), False, None),
    # never : jamais d'askpass
    (env(SSH_ASKPASS=ASK, DISPLAY=":0", SSH_ASKPASS_REQUIRE="never"), False, None),
    (env(SSH_ASKPASS=ASK, DISPLAY=":0", SSH_ASKPASS_REQUIRE="never"), True, "tty"),
])
def test_plan(e, tty, expected):
    p = P.plan(e, tty)
    got = None if p is None else ("askpass" if p.use_askpass else "tty")
    assert got == expected
    if got == "askpass":
        assert p.askpass == ASK


def fds():
    return set(os.listdir("/proc/self/fd"))


def test_sans_invite_possible_ferme_tout(tmp_path):
    before = fds()
    with pytest.raises(P.PromptUnavailable):
        P.ask_password("x", env={}, tty_path=str(tmp_path / "pas-de-tty"))
    assert fds() == before


def test_tty_non_terminal_ferme_le_descripteur(tmp_path):
    f = tmp_path / "pas-un-terminal"
    f.write_text("")
    before = fds()
    with pytest.raises(P.PromptUnavailable):
        P.ask_password("x", env={}, tty_path=str(f))
    assert fds() == before


def script(tmp_path, body):
    s = tmp_path / "askpass"
    s.write_text("#!/bin/sh\n" + body + "\n")
    s.chmod(0o755)
    return str(s)


def test_askpass_reponse(tmp_path):
    prog = script(tmp_path, "printf 'mdp avec espaces\\n'")
    e = {"SSH_ASKPASS": prog, "SSH_ASKPASS_REQUIRE": "force"}
    assert P.ask_password("x", env=e, timeout=5, tty_path=str(tmp_path / "x")) == "mdp avec espaces"


def test_askpass_annule(tmp_path):
    prog = script(tmp_path, "exit 1")
    with pytest.raises(P.PromptError, match="annulé"):
        P.prompt_askpass(prog, "x", 5)


def test_askpass_absent(tmp_path):
    with pytest.raises(P.PromptError):
        P.prompt_askpass(str(tmp_path / "absent"), "x", 5)


@pytest.mark.parametrize("body", ["exec sleep 600", "sleep 600; echo fini"])
def test_askpass_bloque_tue_le_groupe(tmp_path, body):
    """Avec et sans exec : le petit-fils `sleep` doit mourir aussi."""
    pidfile = tmp_path / "pid"
    prog = script(tmp_path, "echo $$ > '%s'\n%s" % (pidfile, body))
    t0 = time.monotonic()
    with pytest.raises(P.PromptError, match="sans réponse en 1s"):
        P.prompt_askpass(prog, "x", 1)
    assert time.monotonic() - t0 < 4
    pgid = int(pidfile.read_text())
    deadline = time.monotonic() + 3
    left = None
    while time.monotonic() < deadline:
        left = [p for p in os.listdir("/proc") if p.isdigit() and _pgid(p) == pgid]
        if not left:
            break
        time.sleep(0.1)
    assert not left


def _pgid(pid):
    try:
        with open("/proc/%s/stat" % pid) as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return int(fields[2]) if fields[0] != "Z" else None
    except (OSError, IndexError, ValueError):
        return None


def test_timeout_invalide():
    with pytest.raises(P.PromptError):
        P.prompt_timeout({"SSHVAULT_PROMPT_TIMEOUT": "0"})
    assert P.prompt_timeout({}) == P.DEFAULT_TIMEOUT
    assert P.prompt_timeout({"SSHVAULT_PROMPT_TIMEOUT": "2.5"}) == 2.5


def test_tty_raccroche_pendant_l_invite(monkeypatch):
    """termios.error (pas un OSError) pendant l'invite ou la restauration : PromptError."""
    import pty
    import termios
    master, slave = pty.openpty()
    real = termios.tcsetattr

    def boom(*a):
        raise termios.error(5, "Input/output error")
    monkeypatch.setattr(P.termios, "tcsetattr", boom)
    try:
        with pytest.raises(P.PromptError, match="terminal inutilisable"):
            P.prompt_tty(slave, "x", 1)
    finally:
        monkeypatch.setattr(P.termios, "tcsetattr", real)
        os.close(master)
        os.close(slave)

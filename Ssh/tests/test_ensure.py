"""Chargement transparent à la demande (story 5, CAP-7) : `sshvault ensure`, appelé par ssh via
la ligne `Match originalhost … exec` du ssh_config généré.

Une ligne de test par ligne de la matrice de la story, avec de vrais `ssh`, deux sshd de test
(A, le rebond, et B, la cible, sur 127.0.0.1, sous l'utilisateur courant, chacun n'acceptant
que sa clé), les vrais `ssh-agent` et `ssh-add`, le faux `bw`, et un vrai terminal par pty
(`bench.pty_run`). La commande `sshvault` des lignes `Match exec` est l'enveloppe du banc
(`python -m sshvault` du dépôt) ; avec SSHVAULT_TEST_TRACE=1 elle écrit
« sshvault-test: fin ensure --id <id> rc=N » sur stderr, ce qui situe chaque appel dans la
sortie de `ssh -v`.
"""
import getpass
import json
import os
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import time

import pytest

from bench import (FAKE_BW, HAVE_OPENSSH, ID_CHIFFREE, ID_PERSO, PASSPHRASE, PASSWORD, SRC, make_askpass,
                   processes_matching, pty_run, ssh_item, wait_gone)
from sshvault import fastpath as E
from sshvault import sshconfig

SSH = shutil.which("ssh")
SSHD = "/usr/sbin/sshd"
HAVE_LAB = bool(SSH and os.access(SSHD, os.X_OK) and HAVE_OPENSSH)
needs_ssh = pytest.mark.skipif(SSH is None, reason="client ssh absent")

ID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
ID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
REFUSED = "mot de passe maître refusé par bw (Cryptography error, The decryption operation failed)"


# --- banc : deux sshd ---------------------------------------------------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Lab:
    """sshd A (clé `prod`) et B (clé `bastion`) sur 127.0.0.1, chacun ne connaissant que sa clé."""

    def __init__(self, d, keys):
        self.dir, self.user = d, getpass.getuser()
        self.ports, self.hostkeys, self.procs, self.logs = {}, {}, {}, {}
        for name, key in (("a", "prod"), ("b", "bastion")):
            sd = d / name
            sd.mkdir()
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(sd / "hostkey")], check=True)
            self.hostkeys[name] = " ".join((sd / "hostkey.pub").read_text().split()[:2])
            (sd / "authorized_keys").write_text(keys[key]["public"] + "\n")
            port = _free_port()
            (sd / "sshd_config").write_text(
                "Port %d\nListenAddress 127.0.0.1\nHostKey %s\nPidFile %s\nAuthorizedKeysFile %s\nStrictModes no\n"
                "UsePAM no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nPrintMotd no\n"
                "LogLevel VERBOSE\n" % (port, sd / "hostkey", sd / "sshd.pid", sd / "authorized_keys"))
            self.logs[name] = sd / "sshd.log"
            with open(str(self.logs[name]), "ab") as log:
                self.procs[name] = subprocess.Popen([SSHD, "-D", "-e", "-f", str(sd / "sshd_config")],
                                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                    stderr=log, start_new_session=True)
            self.ports[name] = port
        for name, port in self.ports.items():
            deadline = time.monotonic() + 10
            while True:
                with socket.socket() as s:
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        break
                assert time.monotonic() < deadline, "sshd %s ne répond pas : %s" % (name, self.logs[name].read_text())
                time.sleep(0.1)

    def log(self, name):
        return self.logs[name].read_text(errors="replace")

    def stop(self):
        """Chaque sshd arrêté (SIGTERM, puis SIGKILL s'il traîne), disparition vérifiée."""
        for p in self.procs.values():
            try:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(10)
            except ProcessLookupError:
                pass
        assert wait_gone([p.pid for p in self.procs.values()]), "sshd de test encore vivants"


@pytest.fixture(scope="module")
def lab(tmp_path_factory, keys):
    """Banc sshd ; les tests qui en dépendent sont ignorés sans ssh, sshd, ssh-agent ou ssh-add."""
    if not HAVE_LAB:
        pytest.skip("ssh, sshd, ssh-agent ou ssh-add absent")
    lb = Lab.__new__(Lab)
    lb.procs = {}
    try:
        lb.__init__(tmp_path_factory.mktemp("lab"), keys)
    except BaseException:
        lb.stop()
        raise
    try:
        yield lb
    finally:
        lb.stop()


def setup(bench, lab, tmp_path, hosts_b="b,bpc", known=("a", "b", "bpc"), generate=True):
    """Coffre : élément A (clé prod, hôte « a ») et B (clé bastion, « b,bpc ») ; ssh_config
    généré (coffre déverrouillé) ; config ssh de test : `b` derrière le rebond `a` par
    ProxyJump, `bpc` par ProxyCommand `ssh -W`. Renvoie le fichier de config de test."""
    bench.items = [ssh_item(ID_A, "Saut A", bench.keys["prod"], hosts="a"),
                   ssh_item(ID_B, "Cible B", bench.keys["bastion"], hosts=hosts_b)]
    bench.write_vault()
    kh = ["[127.0.0.1]:%d %s" % (lab.ports[n], lab.hostkeys[n]) for n in ("a", "b")]
    kh += ["%s %s" % (alias, lab.hostkeys["a" if alias == "a" else "b"]) for alias in known]
    bench.known_hosts.write_text("\n".join(kh) + "\n")
    bench.unlocked("keyring" if bench.ring else "file")
    if generate:
        r = bench.run("ssh-config")
        assert r.returncode == 0, r.stderr
    main = tmp_path / "ssh_config_de_test"
    main.write_text(
        'Include "%s"\n'
        "Host a\n    HostName 127.0.0.1\n    Port %d\n"
        "Host b\n    HostName 127.0.0.1\n    Port %d\n    ProxyJump a\n"
        "Host bpc\n    HostName 127.0.0.1\n    Port %d\n    ProxyCommand ssh -v -F %s -W %%h:%%p a\n"
        "Host *\n    User %s\n    UserKnownHostsFile %s\n    GlobalKnownHostsFile /dev/null\n"
        "    StrictHostKeyChecking yes\n    BatchMode yes\n    ConnectTimeout 10\n"
        % (bench.home / ".ssh" / "sshvault" / "config", lab.ports["a"], lab.ports["b"], lab.ports["b"], main,
           lab.user, bench.known_hosts))
    main.chmod(0o600)
    return main


def lock_vault(bench):
    r = bench.run("lock")
    assert r.returncode == 0, r.stderr


def ssh_argv(main, host, *opts, verbose=True):
    return [SSH, "-F", str(main)] + (["-v"] if verbose else []) + list(opts) + [host, "true"]


def env_of(bench, trace=True, **extra):
    e = dict(bench.env)
    if trace:
        e["SSHVAULT_TEST_TRACE"] = "1"
    e.update(extra)
    return e


def ssh_run(bench, main, host, *opts, trace=True, env=None, timeout=90):
    """ssh sans terminal de contrôle (session neuve, stdin /dev/null)."""
    e = env_of(bench, trace, **(env or {}))
    t0 = time.monotonic()
    r = subprocess.run(ssh_argv(main, host, *opts), env=e, capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL, start_new_session=True)
    r.duration = time.monotonic() - t0
    return r


def sv_lines(stderr):
    """Lignes de sshvault lui-même (pas l'enveloppe du banc « sshvault-test: »)."""
    return [l for l in stderr.splitlines() if l.startswith("sshvault:")]


def fins(stderr):
    return re.findall(r"^sshvault-test: fin ensure --id (\S+) rc=(\d+)$", stderr, re.M)


def loads(bench):
    """Chargements par ssh-add (`-t <durée> … -`) ; `-L`, `-d` et la vérification `-h` exclus."""
    return [a for _, a in bench.ssh_add_calls() if a.startswith("-t ")]


def bw_cmds(bench):
    return [[a for a in c["argv"] if a != "--nointeraction"][:2] for c in bench.calls()]


def offers(stderr):
    return re.findall(r"Offering public key: \S+ \S+ (SHA256:\S+)", stderr)


def fp(bench, name):
    return bench.keys[name]["fingerprint"]


def leftovers(bench):
    return processes_matching([ID_A, ID_B, FAKE_BW, str(bench.tmp)])


def no_leftovers(bench, timeout=10):
    deadline = time.monotonic() + timeout
    left = leftovers(bench)
    while left and time.monotonic() < deadline:
        time.sleep(0.2)
        left = leftovers(bench)
    return left


# --- unitaires ------------------------------------------------------------------------------

@pytest.mark.parametrize("args,expected", [
    (["-G", "b"], (True, "b")),
    (["-vG", "-F", "x", "b"], (True, "b")),
    (["-F", "-G", "b"], (False, "b")),  # « -G » argument de -F
    (["-Fcfg", "-G", "b"], (True, "b")),
    (["b", "-G"], (True, "b")),  # ssh relance getopt après la destination
    (["b", "ls", "-G"], (False, "b")),  # commande distante
    (["-W", "[127.0.0.1]:22", "a"], (False, "a")),
    (["-o", "ProxyCommand=x -G", "u@h"], (False, "u@h")),
    (["-P", "-G", "b"], (False, "b")),  # -P étiquette (OpenSSH récent) : prend un argument
    (["--", "-G"], (False, "-G")),
    ([], (False, None)),
])
def test_parse_ssh_args(args, expected):
    r = E.parse_ssh_args(args)
    assert (r["G"], r["dest"]) == expected


@pytest.mark.parametrize("args,ctl,batch", [
    (["-O", "check", "b"], True, False), (["-Ocheck", "b"], True, False), (["-vO", "exit", "b"], True, False),
    (["-o", "BatchMode=yes", "b"], False, True), (["-oBatchMode yes", "b"], False, True),
    (["-o", "batchmode = \"yes\"", "b"], False, True), (["-o", "BatchMode=no", "b"], False, False),
    (["b", "-o", "BatchMode=yes"], False, True), (["b", "echo", "-o", "BatchMode=yes"], False, False),
])
def test_parse_ssh_args_controle_et_batchmode(args, ctl, batch):
    r = E.parse_ssh_args(args)
    assert (r["O"], r["batch"]) == (ctl, batch)


def test_fraicheur_seuil():
    now = 1000.0
    e = lambda loaded, life: {"loaded": loaded, "lifetime": life}  # noqa: E731
    assert E.fresh(e(now, 3600), now) and not E.fresh(e(now - 3541, 3600), now)  # 59 s restantes
    assert E.fresh(e(now, 30), now), "key-ttl de 30 s : fraîche au chargement (seuil 15 s)"
    assert not E.fresh(e(now - 16, 30), now)
    assert E.fresh(e(0, 0), now), "durée illimitée"


def test_ensure_args():
    assert E.ensure_args(["ensure", "--id", "x"]) == ("x", False)
    assert E.ensure_args(["--nointeraction", "ensure", "--id=x"]) == ("x", True)
    assert E.ensure_args(["ensure", "--id", "x", "y"]) is None and E.ensure_args(["list"]) is None


@pytest.mark.parametrize("dest,label", [
    ("b", "b"), ("alice@b.example", "b.example"), ("ssh://alice@b.example:2222", "b.example"),
    ("ssh://[::1]:22", "::1"), ("x\x1b[31m", "x\\x1b[31m"), (None, None)])
def test_dest_label(dest, label):
    assert E.dest_label(dest) == label


def test_ligne_match_exec_quotee(tmp_path):
    exe = tmp_path / "dossier avec espace et %d" / "sshvault"
    line = sshconfig.ensure_command(str(exe), ID_A.upper())
    assert line == "'%s' ensure --id %s" % (str(exe).replace("%", "%%"), ID_A)
    for bad in ("/a'b/sshvault", '/a"b/sshvault', "/a\\b/sshvault", "/a${X}/sshvault", "relatif/sshvault",
                "/a\nb/sshvault"):
        with pytest.raises(sshconfig.SshConfigError):
            sshconfig.ensure_command(bad, ID_A)
    for bad_id in ("%h", "a b", ID_A + ";id", "", "11111111-1111-4111-8111-11111111111"):
        with pytest.raises(sshconfig.SshConfigError):
            sshconfig.ensure_command(str(exe), bad_id)


def test_build_id_non_uuid_sans_exec(bench, tmp_path):
    from sshvault.backend import SshKeyItem
    items = [SshKeyItem("pas-un-uuid", "X", bench.keys["prod"]["public"], "", ("x.example",)),
             SshKeyItem(ID_A, "A", bench.keys["bastion"]["public"], "", ("a",))]
    plan = sshconfig.build(items, sshconfig.Paths(str(tmp_path)), str(tmp_path / "s.sock"), "/opt/sshvault")
    text = plan.config.decode()
    assert text.count(" exec ") == 1 and "ensure --id %s\"" % ID_A in text
    assert any("pas-un-uuid" in w and "pas de chargement automatique" in w for w in plan.warnings)
    with pytest.raises(sshconfig.SshConfigError):
        sshconfig.build(items, sshconfig.Paths(str(tmp_path)), str(tmp_path / "s.sock"), "/opt/ss'hvault")


def _fake_exe(d, version):
    d.mkdir(parents=True, exist_ok=True)
    exe = d / "sshvault"
    exe.write_text("#!/bin/sh\necho 'sshvault %s'\n" % version)
    exe.chmod(0o755)
    return exe


def test_sshvault_exe(tmp_path):
    d1, d2, d3 = tmp_path / "d1", tmp_path / "d2", tmp_path / "d3"
    d1.mkdir()
    (d1 / "sshvault").write_text("pas exécutable")
    old = _fake_exe(d2, "0.3.0")  # sans `ensure` : écarté
    exe3 = _fake_exe(d3, "0.4.0")
    env = {"PATH": "relatif:%s:%s:%s" % (d1, d2, d3)}
    assert sshconfig.sshvault_exe("/x/__main__.py", env) == str(exe3)
    assert sshconfig.sshvault_exe(str(exe3), {"PATH": ""}) == str(exe3)
    with pytest.raises(sshconfig.SshConfigError, match="trop ancienne.*auto-load false"):
        sshconfig.sshvault_exe("/x/__main__.py", {"PATH": "%s:%s" % (d1, d2)})
    with pytest.raises(sshconfig.SshConfigError, match="introuvable"):
        sshconfig.sshvault_exe("/x/__main__.py", {"PATH": str(d1)})
    assert str(old) in sshconfig._exe_checked and sshconfig._exe_checked[str(old)] == (0, 3, 0), "version en cache"


def test_exe_warnings(tmp_path):
    paths = sshconfig.Paths(str(tmp_path))
    venv = _fake_exe(tmp_path / "proj" / ".venv" / "bin", "0.4.0")
    assert sshconfig.exe_warnings("/opt/sshvault", paths) == []
    os.makedirs(paths.dir)
    (pathlib_path := tmp_path / ".ssh" / "sshvault" / "config").write_text(
        "Match originalhost a exec \"'/autre/sshvault' ensure --id %s\"\n" % ID_A)
    pathlib_path.chmod(0o600)
    w = sshconfig.exe_warnings(str(venv), paths)
    assert len(w) == 2 and "/autre/sshvault → %s" % venv in w[0] and ".venv" in w[1]


SHELLS = ["/bin/bash", "/bin/sh"] + [shutil.which(x) or "/absent/" + x for x in ("zsh", "fish")]


@needs_ssh
@pytest.mark.parametrize("shell", SHELLS)
def test_exec_reel_chemin_avec_espace_et_pourcent(tmp_path, shell):
    """La commande générée passe par la config d'OpenSSH (guillemets, %%) puis par le shell de
    l'utilisateur ($SHELL : bash, dash, zsh et fish s'ils sont installés) : appelée telle
    quelle, avec l'id seul en argument."""
    if not os.access(shell, os.X_OK):
        pytest.skip("%s absent" % shell)
    exe = tmp_path / "a b%c" / "sshvault"
    exe.parent.mkdir()
    out = tmp_path / "argv"
    exe.write_text("#!/bin/sh\nprintf '%%s|' \"$0\" \"$@\" > '%s'\n" % out)
    exe.chmod(0o755)
    cfg = tmp_path / "cfg"
    cfg.write_text('Match originalhost foo,*.lab exec "%s"\nMatch originalhost foo,*.lab\n    IdentitiesOnly yes\n'
                   % sshconfig.ensure_command(str(exe), ID_A))
    env = dict(os.environ, SHELL=shell)
    r = subprocess.run([SSH, "-G", "-F", str(cfg), "x.LAB"], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=30, env=env)
    assert r.returncode == 0, r.stderr
    assert out.read_text() == "%s|ensure|--id|%s|" % (exe, ID_A)
    out.unlink()
    subprocess.run([SSH, "-G", "-F", str(cfg), "autre"], capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    assert not out.exists(), "originalhost ne correspond pas : commande non lancée"


# --- matrice --------------------------------------------------------------------------------

def test_proxyjump_un_ensure_par_saut(bench, lab, tmp_path):
    """ProxyJump A→B, agent vide, coffre déverrouillé : `ssh B` réussit ; un ensure par saut,
    chacun fini avant l'authentification de son saut ; une clé offerte par saut."""
    main = setup(bench, lab, tmp_path)
    before_a, before_b = len(lab.log("a")), len(lab.log("b"))
    r = ssh_run(bench, main, "b")
    assert r.returncode == 0, r.stderr
    err = r.stderr
    assert fins(err) == [(ID_B, "0"), (ID_A, "0")], "la cible d'abord, puis le saut, un appel chacun"
    i_b = err.index("sshvault-test: fin ensure --id %s" % ID_B)
    i_proxy = err.index("Executing proxy command")
    i_a = err.index("sshvault-test: fin ensure --id %s" % ID_A)
    i_conn_a = err.index("Connecting to 127.0.0.1 [127.0.0.1] port %d" % lab.ports["a"])
    i_auth_a = err.index("Authenticated to 127.0.0.1 ([127.0.0.1]:%d)" % lab.ports["a"])
    i_auth_b = err.index("Authenticated to 127.0.0.1 (via proxy)")
    assert i_b < i_proxy < i_a < i_conn_a < i_auth_a < i_auth_b
    assert offers(err) == [fp(bench, "prod"), fp(bench, "bastion")], "une seule clé offerte par saut"
    assert "Accepted publickey for %s" % lab.user in lab.log("a")[before_a:]
    assert fp(bench, "prod") in lab.log("a")[before_a:] and fp(bench, "bastion") in lab.log("b")[before_b:]
    assert sorted(bench.agent_keys()) == sorted([bench.blob("prod"), bench.blob("bastion")])
    assert len(loads(bench)) == 2
    assert bw_cmds(bench)[-2:] == [["get", "item"], ["get", "item"]], "un seul appel bw par clé chargée"
    assert sv_lines(err) == [], "silencieux en cas de succès"
    st = bench.agent_state()["keys"]
    assert {e["id"] for e in st.values()} == {ID_A, ID_B} and all(e["lifetime"] == 3600 for e in st.values())


def test_proxycommand_ssh_w(bench, lab, tmp_path):
    main = setup(bench, lab, tmp_path)
    r = ssh_run(bench, main, "bpc")
    assert r.returncode == 0, r.stderr
    err = r.stderr
    assert fins(err) == [(ID_B, "0"), (ID_A, "0")]
    assert err.index("fin ensure --id %s" % ID_B) < err.index("Executing proxy command: exec ssh -v")
    assert err.index("fin ensure --id %s" % ID_A) < err.index("Connecting to 127.0.0.1 [127.0.0.1] port %d"
                                                              % lab.ports["a"])
    assert offers(err) == [fp(bench, "prod"), fp(bench, "bastion")]
    assert len(loads(bench)) == 2 and sv_lines(err) == []


def test_cles_presentes_chemin_rapide(bench, lab, tmp_path):
    """Clés présentes (> 60 s restantes) : aucun appel bw, aucune sortie ; latence du chemin
    rapide mesurée sur 20 `ensure` (critère : médiane < 100 ms)."""
    main = setup(bench, lab, tmp_path)
    assert ssh_run(bench, main, "b").returncode == 0
    calls, n_loads = len(bench.calls()), len(loads(bench))
    r = ssh_run(bench, main, "b")
    assert r.returncode == 0, r.stderr
    assert fins(r.stderr) == [(ID_B, "0"), (ID_A, "0")] and sv_lines(r.stderr) == []
    times = []
    for i in range(20):
        t0 = time.monotonic()
        p = subprocess.run([sys.executable, "-m", "sshvault", "ensure", "--id", (ID_A, ID_B)[i % 2]],
                           env=bench.env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
        times.append(time.monotonic() - t0)
        assert (p.returncode, p.stdout, p.stderr) == (0, "", "")
    assert len(bench.calls()) == calls, "aucun bw lancé"
    assert len(loads(bench)) == n_loads, "aucun ssh-add de chargement"
    med, mx = statistics.median(times), max(times)
    print("\nchemin rapide, 20 ensure : médiane %.1f ms, max %.1f ms" % (med * 1000, mx * 1000))
    assert med < 0.100, times


def test_cle_presque_expiree_rechargee(bench, lab, tmp_path):
    setup(bench, lab, tmp_path)
    prog, _ = make_askpass(tmp_path)  # agent lancé avec un askpass utilisable (confirmation -c)
    assert bench.run("load", "--id", ID_A, "--confirm", "-t", "300",
                     env={"SSH_ASKPASS": prog, "DISPLAY": ":99"}).returncode == 0
    # 250 s écoulées (état vieilli) : 50 s restantes ≤ 60 s
    st = bench.runtime / "sshvault" / "agent.json"
    data = json.loads(st.read_text())
    for e in data["keys"].values():
        e["loaded"] -= 250
    st.write_text(json.dumps(data))
    n = len(loads(bench))
    r = bench.run("ensure", "--id", ID_A)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    assert len(loads(bench)) == n + 1 and loads(bench)[-1].startswith("-t 3600 -c "), \
        "rechargée (durée key-ttl), confirmation gardée"
    e = [e for e in bench.agent_state()["keys"].values() if e["id"] == ID_A][0]
    assert e["lifetime"] == 3600 and e["confirm"] is True
    # témoin : plus de 60 s restantes, rien rechargé
    assert bench.run("load", "--id", ID_B, "-t", "2m").returncode == 0
    n, calls = len(loads(bench)), len(bench.calls())
    assert bench.run("ensure", "--id", ID_B).returncode == 0
    assert len(loads(bench)) == n and len(bench.calls()) == calls


def test_coffre_verrouille_une_seule_invite_tty(bench, lab, tmp_path):
    """Terminal au premier plan, coffre verrouillé : une invite pour toute la connexion."""
    main = setup(bench, lab, tmp_path)
    lock_vault(bench)
    r = pty_run([ssh_argv(main, "b")], env_of(bench), answers=[PASSWORD], timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.prompts == 1, r.screen
    assert PASSWORD not in r.screen, "saisie non affichée"
    assert r.echo is True, "écho du terminal rétabli"
    assert fins(r.stderr) == [(ID_B, "0"), (ID_A, "0")] and sv_lines(r.stderr) == []
    assert bw_cmds(bench).count(["unlock", "--passwordenv"]) == 1
    assert sorted(bench.agent_keys()) == sorted([bench.blob("prod"), bench.blob("bastion")])


def test_mauvais_mot_de_passe_memorise(bench, lab, tmp_path):
    """Mauvais mot de passe : une ligne, puis échec rapide des sauts suivants de la même
    connexion, ssh en Permission denied ; une autre connexion n'est pas gênée (nouvelle
    invite), et `sshvault unlock` efface la mémoire."""
    main = setup(bench, lab, tmp_path)
    lock_vault(bench)
    calls = len(bench.calls())
    r = pty_run([ssh_argv(main, "b")], env_of(bench), answers=["mauvais"], timeout=60)
    assert r.returncode == 255
    assert r.prompts == 1, r.screen
    assert "mot de passe maître du coffre (clé pour b)" in r.screen, "l'invite dit ce qui la déclenche"
    lines = sv_lines(r.stderr)
    assert len(lines) == 2 and lines[0] == "sshvault: b : %s" % REFUSED, r.stderr
    m = re.fullmatch(r"sshvault: a : déverrouillage du coffre en échec il y a (\d+)s pour cette connexion : pas de "
                     r"nouvelle invite avant (\d+)s \(ou « sshvault unlock »\)", lines[1])
    assert m and int(m.group(1)) <= 2 and int(m.group(1)) + int(m.group(2)) == 30, lines[1]
    assert "Permission denied" in r.stderr
    assert [c for c in bw_cmds(bench)[calls:]] == [["status"], ["unlock", "--passwordenv"]], \
        "le saut suivant n'appelle pas bw"
    assert bench.agent_keys() == [] and loads(bench) == []
    fail = bench.runtime / "sshvault" / "unlock-failed"
    assert oct(fail.stat().st_mode & 0o777) == "0o600" and re.fullmatch(r"\d+ \d+:\d+\n", fail.read_text())
    # autre connexion dans les 30 s : pas gênée (nouvelle invite), succès, mémoire effacée
    r = pty_run([ssh_argv(main, "b")], env_of(bench), answers=[PASSWORD], timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.prompts == 1 and not fail.exists()
    # `sshvault unlock` réussi : mémoire effacée
    fail.write_text("%d 1:1\n" % time.time())
    assert bench.run("unlock").returncode == 0
    assert not fail.exists()


def test_askpass_annule_memorise_pour_la_connexion_seulement(bench, lab, tmp_path):
    """Askpass annulé (code 1) : mémorisé pour cette connexion (askpass appelé une fois, une
    ligne par saut), pas pour une autre connexion."""
    main = setup(bench, lab, tmp_path)
    lock_vault(bench)
    prog, ask_calls = make_askpass(tmp_path, rc=1)
    env = {"SSH_ASKPASS": prog, "SSH_ASKPASS_REQUIRE": "force"}
    r = ssh_run(bench, main, "b", env=env)
    assert r.returncode == 255
    assert len(ask_calls.read_text().splitlines()) == 1
    lines = sv_lines(r.stderr)
    assert lines[0] == "sshvault: b : coffre verrouillé : askpass annulé (code 1)", r.stderr
    assert lines[1].startswith("sshvault: a : déverrouillage du coffre en échec") and len(lines) == 2
    prog2, ok_calls = make_askpass(tmp_path, name="askpass-ok")
    r = ssh_run(bench, main, "b", env={"SSH_ASKPASS": prog2, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 0, r.stderr
    assert len(ok_calls.read_text().splitlines()) == 1


def test_askpass_non_executable_compte_comme_absent(bench, lab, tmp_path):
    main = setup(bench, lab, tmp_path)
    lock_vault(bench)
    calls = len(bench.calls())
    r = ssh_run(bench, main, "b", env={"SSH_ASKPASS": str(tmp_path / "absent"), "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 255
    assert all("aucune invite possible" in l for l in sv_lines(r.stderr)) and len(sv_lines(r.stderr)) == 2
    assert len(bench.calls()) == calls
    assert not (bench.runtime / "sshvault" / "unlock-failed").exists()


@pytest.mark.parametrize("askpass", [False, True])
def test_ssh_en_arriere_plan(bench, lab, tmp_path, askpass):
    """`ssh … &` (groupe en arrière-plan du terminal), coffre verrouillé : jamais d'invite sur le
    terminal ni d'arrêt par SIGTTIN ; askpass s'il est utilisable, sinon échec rapide."""
    main = setup(bench, lab, tmp_path)
    lock_vault(bench)
    extra = {}
    if askpass:
        prog, ask_calls = make_askpass(tmp_path)
        extra = {"SSH_ASKPASS": prog, "DISPLAY": ":99"}
    r = pty_run([ssh_argv(main, "b")], env_of(bench, **extra), answers=[PASSWORD], timeout=60, mode="bg")
    assert r.prompts == 0, "aucune invite sur le terminal : %r" % r.screen
    if askpass:
        assert r.rcs == [0], r.stderr
        assert len(ask_calls.read_text().splitlines()) == 1
        assert sorted(bench.agent_keys()) == sorted([bench.blob("prod"), bench.blob("bastion")])
    else:
        assert r.rcs == [255], r.stderr
        assert r.duration < 10
        lines = sv_lines(r.stderr)
        assert [l.split(" : ", 1)[0] for l in lines] == ["sshvault: b", "sshvault: a"], r.stderr
        assert all("aucune invite possible" in l for l in lines)
        assert loads(bench) == []


def test_sans_tty_ni_askpass(bench, lab, tmp_path):
    main = setup(bench, lab, tmp_path)
    lock_vault(bench)
    calls = len(bench.calls())
    r = ssh_run(bench, main, "b")
    assert r.returncode == 255
    assert sv_lines(r.stderr) == ["sshvault: %s : coffre verrouillé : aucune invite possible (ni /dev/tty, ni "
                                  "SSH_ASKPASS utilisable)" % h for h in ("b", "a")], r.stderr
    assert len(bench.calls()) == calls, "échec rapide : aucun bw"
    assert r.duration < 5 and "Permission denied" in r.stderr
    assert not (bench.runtime / "sshvault" / "unlock-failed").exists(), "invite impossible : pas un échec mémorisé"


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("opt", [["-G"], ["-O", "check"]])
def test_ssh_G_ne_demande_rien(bench, lab, tmp_path, shell, opt):
    """`ssh -G` et `ssh -O check` (même avec un terminal au premier plan), coffre verrouillé :
    ensure est lancé mais ne demande ni ne charge rien, code 0. /bin/sh (dash) garde un shell
    intermédiaire ; zsh et fish testés s'ils sont installés."""
    if not os.access(shell, os.X_OK):
        pytest.skip("%s absent" % shell)
    main = setup(bench, lab, tmp_path)
    lock_vault(bench)
    calls, n = len(bench.calls()), len(bench.ssh_add_calls())
    r = pty_run([[SSH] + opt + ["-F", str(main), "b"]], env_of(bench, SHELL=shell), answers=[PASSWORD], timeout=30)
    assert r.returncode == (0 if opt == ["-G"] else 255), r.stderr
    assert fins(r.stderr) == [(ID_B, "0")], "ensure appelé par ssh -G"
    assert r.prompts == 0 and sv_lines(r.stderr) == []
    assert len(bench.calls()) == calls and len(bench.ssh_add_calls()) == n, "ni bw ni ssh-add"
    assert not (bench.runtime / "sshvault" / "agent.sock").exists()


def test_deux_ssh_paralleles(bench, lab, tmp_path):
    """Deux ssh lancés ensemble au premier plan, coffre verrouillé : une seule invite, un seul
    ssh-add par clé (l'invite n'est tapée qu'une fois : une 2e resterait sans réponse)."""
    main = setup(bench, lab, tmp_path)
    lock_vault(bench)
    r = pty_run([ssh_argv(main, "b"), ssh_argv(main, "b")], env_of(bench), answers=[PASSWORD], timeout=90,
                mode="fg")
    assert r.rcs == [0, 0], r.stderr
    assert r.prompts == 1, r.screen
    assert len(loads(bench)) == 2, loads(bench)
    assert bw_cmds(bench).count(["unlock", "--passwordenv"]) == 1
    assert bw_cmds(bench).count(["get", "item"]) == 2, "état relu après le verrou : pas de bw pour une clé chargée"
    assert sorted(fins(r.stderr)) == sorted([(ID_A, "0"), (ID_A, "0"), (ID_B, "0"), (ID_B, "0")])


@pytest.mark.parametrize("mode", ["hang", "error"])
def test_backend_en_panne(bench, lab, tmp_path, mode):
    main = setup(bench, lab, tmp_path)
    r = ssh_run(bench, main, "b", env={"FAKE_BW_FAIL": "get=" + mode, "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 255 and "Permission denied" in r.stderr
    lines = sv_lines(r.stderr)
    if mode == "hang":
        assert lines == ["sshvault: %s : erreur bw : « bw get » sans réponse en 2s" % h for h in ("b", "a")], r.stderr
        assert 4 <= r.duration < 15
        pids = [int(p) for p in bench.pids.read_text().split()]
        assert wait_gone(pids), "bw bloqué et son enfant tués"
    else:
        assert lines == ["sshvault: %s : erreur bw (get item, code 1) : Unexpected error." % h for h in ("b", "a")]
        assert r.duration < 10
    assert loads(bench) == []
    assert no_leftovers(bench) == []


def test_auto_restrict_et_auto_confirm(bench, lab, tmp_path):
    main = setup(bench, lab, tmp_path)
    assert bench.run("config", "set", "auto-restrict", "true").returncode == 0
    r = ssh_run(bench, main, "b")
    assert r.returncode == 0, r.stderr
    kh = str(bench.known_hosts)
    assert loads(bench) == ["-t 3600 -H %s -h b -h bpc -" % kh, "-t 3600 -H %s -h a -" % kh]
    st = bench.agent_state()["keys"]
    assert all(e["restrict"] and not e["confirm"] for e in st.values())
    # auto-confirm, agent lancé sans askpass utilisable : refus en une ligne, rien chargé
    assert bench.run("agent", "purge").returncode == 0
    assert bench.run("config", "set", "auto-restrict", "false").returncode == 0
    assert bench.run("config", "set", "auto-confirm", "true").returncode == 0
    n = len(loads(bench))
    r = bench.run("ensure", "--id", ID_A)
    assert r.returncode == 4 and r.stderr.count("\n") == 1, r.stderr
    assert r.stderr.startswith("sshvault: %s : auto-confirm : l'agent dédié a été lancé sans askpass" % ID_A)
    assert len(loads(bench)) == n and bench.agent_keys() == []
    # agent relancé avec un askpass utilisable : -c
    assert bench.run("agent", "stop").returncode == 0
    prog, _ = make_askpass(tmp_path)
    r = bench.run("ensure", "--id", ID_A, env={"SSH_ASKPASS": prog, "DISPLAY": ":99"})
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    assert loads(bench)[-1] == "-t 3600 -c -"
    assert [e["confirm"] for e in bench.agent_state()["keys"].values()] == [True]


@pytest.mark.parametrize("case", ["absent-known-hosts", "non-litteral"])
def test_auto_restrict_refus(bench, lab, tmp_path, case):
    if case == "absent-known-hosts":
        main = setup(bench, lab, tmp_path, known=("a", "b"))
        cause = "hôte bpc absent de known_hosts (restriction -h) : rien chargé"
    else:
        main = setup(bench, lab, tmp_path, hosts_b="b,*.lab")
        cause = "auto-restrict : hôte « *.lab » de « Cible B » non littéral (motif, user@, >, :port) : rien chargé"
    assert bench.run("config", "set", "auto-restrict", "true").returncode == 0
    r = ssh_run(bench, main, "b")
    assert r.returncode == 255
    assert sv_lines(r.stderr) == ["sshvault: b : " + cause], r.stderr
    assert bench.blob("bastion") not in bench.agent_keys()
    assert not any("-h b" in a for a in loads(bench))


def test_auto_load_false(bench, lab, tmp_path):
    main = setup(bench, lab, tmp_path, generate=False)
    r = bench.run("config", "set", "auto-load", "false")
    assert r.returncode == 0 and r.stdout == ("auto-load false\npris en compte à la prochaine génération : lancer "
                                              "« sshvault ssh-config »\n")
    assert bench.run("ssh-config").returncode == 0
    text = (bench.home / ".ssh" / "sshvault" / "config").read_text()
    assert " exec " not in text and "Match originalhost b,bpc\n" in text
    r = ssh_run(bench, main, "b")
    assert r.returncode == 255 and fins(r.stderr) == [] and loads(bench) == []
    # retour au défaut : lignes ensure revenues
    assert bench.run("config", "unset", "auto-load").stdout.startswith("auto-load true (défaut)\n")
    assert bench.run("ssh-config", "--check").returncode == 1, "--check voit la différence"
    assert bench.run("ssh-config").returncode == 0
    assert ssh_run(bench, main, "b").returncode == 0


def test_ctrl_c_pendant_l_invite(bench, lab, tmp_path):
    """Ctrl-C tapé pendant l'invite : terminal restauré, rien de chargé, aucun processus restant."""
    main = setup(bench, lab, tmp_path)
    lock_vault(bench)
    r = pty_run([ssh_argv(main, "b")], env_of(bench), send_at_prompt=b"\x03", timeout=30)
    assert r.returncode != 0
    assert r.prompts == 1 and r.echo is True
    assert "sshvault: b : interrompu" in sv_lines(r.stderr), r.stderr
    assert "Traceback" not in r.stderr
    assert loads(bench) == [] and bench.agent_keys() == []
    assert no_leftovers(bench) == []
    assert not (bench.runtime / "sshvault" / "unlock-failed").exists(), "interruption : pas un échec mémorisé"


# --- chargement : coût mesuré, erreurs, robustesse ---------------------------------------------

def test_chemin_de_chargement_bw_lent(bench, lab, tmp_path):
    """Faux bw à 1,4 s par appel (coût mesuré du vrai) : `ssh b` avec agent vide et session
    rangée coûte un `bw get item` par saut."""
    main = setup(bench, lab, tmp_path)
    calls = len(bench.calls())
    r = ssh_run(bench, main, "b", env={"FAKE_BW_DELAY": "1.4"})
    assert r.returncode == 0, r.stderr
    assert bw_cmds(bench)[calls:] == [["get", "item"], ["get", "item"]]
    print("\nchargement des deux sauts, bw à 1,4 s : %.2f s" % r.duration)
    assert 2.8 <= r.duration < 2.8 + 4


def test_ensure_element_absent_et_id_invalide(bench, lab, tmp_path):
    setup(bench, lab, tmp_path)
    r = bench.run("ensure", "--id", "cccccccc-3333-4333-8333-cccccccccccc")
    assert r.returncode == 4
    assert r.stderr == ("sshvault: cccccccc-3333-4333-8333-cccccccccccc : élément "
                        "cccccccc-3333-4333-8333-cccccccccccc absent du coffre\n")
    r = bench.run("ensure", "--id", "%h;id")
    assert r.returncode == 2 and r.stderr.count("\n") == 1 and "UUID attendu" in r.stderr


def test_ensure_delai_global(bench, lab, tmp_path):
    """SSHVAULT_ENSURE_TIMEOUT borne tout l'appel (ici : verrou tenu par un autre ensure)."""
    setup(bench, lab, tmp_path)
    import fcntl
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(str(d / "ensure.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        t0 = time.monotonic()
        r = bench.run("ensure", "--id", ID_A, env={"SSHVAULT_ENSURE_TIMEOUT": "1"})
        assert time.monotonic() - t0 < 5
    finally:
        os.close(fd)
    assert r.returncode == 4
    assert r.stderr == ("sshvault: %s : délai de 1s dépassé (SSHVAULT_ENSURE_TIMEOUT) : clé non chargée\n" % ID_A)
    assert loads(bench) == []


def test_ensure_sigterm_pendant_bw(bench, lab, tmp_path):
    """SIGTERM pendant un bw bloqué : une ligne, bw et son enfant tués, pas de traceback."""
    setup(bench, lab, tmp_path)
    e = dict(bench.env, FAKE_BW_FAIL="get=hang")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "ensure", "--id", ID_A], env=e,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    deadline = time.monotonic() + 20
    while not (bench.pids.exists() and bench.pids.read_text().strip()) and time.monotonic() < deadline:
        time.sleep(0.05)
    p.terminate()
    out, err = p.communicate(timeout=20)
    assert p.returncode == 130 and err == "sshvault: %s : interrompu\n" % ID_A and out == ""
    assert wait_gone([int(x) for x in bench.pids.read_text().split()])


def test_ensure_ne_lit_jamais_stdin(bench, lab, tmp_path):
    """stdin est /dev/null sous Match exec : même un stdin qui répond n'est jamais lu."""
    setup(bench, lab, tmp_path)
    lock_vault(bench)
    p = subprocess.run([sys.executable, "-m", "sshvault", "ensure", "--id", ID_A], env=bench.env,
                       input=PASSWORD + "\n", capture_output=True, text=True, timeout=30, start_new_session=True)
    assert p.returncode == 3 and "aucune invite possible" in p.stderr
    assert loads(bench) == []


# --- revue : robustesse, contexte, cas ajoutés ------------------------------------------------

def fake_ssh(bench, item_id, *ssh_args, env=None, cmd_prefix=""):
    """`sshvault ensure` lancé par un faux parent nommé « ssh » (un sh dont argv[0] est ssh) :
    la ligne de commande vue dans /proc est `ssh -c <commande> <ssh_args…>`."""
    e = dict(bench.env)
    e.update(env or {})
    cmd = "%s'%s' -m sshvault ensure --id %s" % (cmd_prefix, sys.executable, item_id)
    return subprocess.Popen(["ssh", "-c", cmd] + list(ssh_args), executable="/bin/sh", env=e,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)


def slow_ssh_add(tmp_path, delay):
    """Enveloppe d'ssh-add qui attend `delay` s dans le même processus, puis exécute le vrai."""
    from bench import SSH_ADD
    w = tmp_path / "ssh-add-lent"
    w.write_text("#!%s\nimport os, sys, time\ntime.sleep(%s)\nos.execv(%r, [%r] + sys.argv[1:])\n"
                 % (sys.executable, delay, SSH_ADD, SSH_ADD))
    w.chmod(0o755)
    return str(w)


def test_point_d_entree_et_chemin_rapide_sans_cli(bench, lab, tmp_path):
    """pyproject : `sshvault = "sshvault.launch:main"` ; clé présente : réponse sans importer la CLI."""
    pyproject = open(os.path.join(os.path.dirname(SRC), "pyproject.toml")).read()
    assert re.search(r'^sshvault = "sshvault\.launch:main"$', pyproject, re.M)
    setup(bench, lab, tmp_path)
    assert bench.run("ensure", "--id", ID_A).returncode == 0
    code = ("import sys; sys.argv = ['sshvault', 'ensure', '--id', %r]; from sshvault.launch import main; "
            "rc = main(); print(rc, 'sshvault.cli' in sys.modules, 'sshvault.bw' in sys.modules)" % ID_A)
    r = subprocess.run([sys.executable, "-c", code], env=bench.env, capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL)
    assert r.stdout.split() == ["0", "False", "False"], r.stderr


def test_cle_tournee_rechargee(bench, lab, tmp_path):
    """Clé de l'élément changée dans le coffre (config régénérée) : l'ancienne, encore dans
    l'agent, ne compte plus ; la nouvelle est chargée."""
    setup(bench, lab, tmp_path)
    assert bench.run("ensure", "--id", ID_A).returncode == 0
    bench.items[0] = ssh_item(ID_A, "Saut A", bench.keys["perso"], hosts="a")
    bench.write_vault()
    assert bench.run("ssh-config").returncode == 0
    n = len(loads(bench))
    r = bench.run("ensure", "--id", ID_A)
    assert (r.returncode, r.stderr) == (0, "")
    assert len(loads(bench)) == n + 1 and bench.blob("perso") in bench.agent_keys()
    calls = len(bench.calls())
    assert bench.run("ensure", "--id", ID_A).returncode == 0 and len(bench.calls()) == calls, "puis chemin rapide"


def test_key_ttl_courte_reste_fraiche(bench, lab, tmp_path):
    setup(bench, lab, tmp_path)
    assert bench.run("config", "set", "key-ttl", "30").returncode == 0
    assert bench.run("ensure", "--id", ID_A).returncode == 0
    assert loads(bench)[-1].startswith("-t 30 ")
    calls = len(bench.calls())
    assert bench.run("ensure", "--id", ID_A).returncode == 0
    assert len(bench.calls()) == calls, "durée 30 s : seuil 15 s, pas de bw à chaque connexion"


def test_meme_cle_deux_elements(bench, lab, tmp_path):
    setup(bench, lab, tmp_path)
    id_c = "cccccccc-3333-4333-8333-cccccccccccc"
    bench.add_item(ssh_item(id_c, "Copie de A", bench.keys["prod"], hosts="c"))
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("ensure", "--id", ID_A).returncode == 0
    n, calls = len(loads(bench)), len(bench.calls())
    assert bench.run("ensure", "--id", id_c).returncode == 0
    assert len(loads(bench)) == n and len(bench.calls()) == calls + 1, "reconnue (un bw), pas rechargée"
    e = bench.agent_state()["keys"][fp(bench, "prod")]
    assert e["id"] == ID_A and e["also"] == [id_c]
    assert bench.run("ensure", "--id", id_c).returncode == 0 and len(bench.calls()) == calls + 1, "chemin rapide"


def test_agent_verrouille_avant_le_coffre(bench, lab, tmp_path):
    """Agent dédié verrouillé : code 3, une ligne, ni invite du coffre ni bw."""
    setup(bench, lab, tmp_path)
    assert bench.run("ensure", "--id", ID_A).returncode == 0
    prog, _ = make_askpass(tmp_path, reply="verrou")
    r = bench.run("agent", "lock", env={"SSH_ASKPASS": prog, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 0, r.stderr
    lock_vault(bench)
    calls = len(bench.calls())
    r = pty_run([[sys.executable, "-m", "sshvault", "ensure", "--id", ID_B]], bench.env, answers=[PASSWORD])
    assert r.returncode == 3 and r.prompts == 0
    assert r.stderr == "sshvault: %s : agent dédié verrouillé : lancer « sshvault agent unlock »\n" % ID_B
    assert len(bench.calls()) == calls


def test_nointeraction_et_batchmode(bench, lab, tmp_path):
    """--nointeraction, ou `-o BatchMode=yes` sur le ssh : aucune invite, échec immédiat."""
    main = setup(bench, lab, tmp_path)
    lock_vault(bench)
    calls = len(bench.calls())
    r = pty_run([[sys.executable, "-m", "sshvault", "--nointeraction", "ensure", "--id", ID_A]], bench.env,
                answers=[PASSWORD])
    assert r.returncode == 3 and r.prompts == 0
    assert r.stderr == "sshvault: %s : coffre verrouillé : aucune invite (--nointeraction)\n" % ID_A
    r = pty_run([ssh_argv(main, "b", "-o", "BatchMode=yes")], env_of(bench), answers=[PASSWORD], timeout=30)
    assert r.returncode == 255 and r.prompts == 0
    assert sv_lines(r.stderr) == ["sshvault: %s : coffre verrouillé : aucune invite (BatchMode=yes)" % h
                                  for h in ("b", "a")], r.stderr
    assert len(bench.calls()) == calls


def test_interruption_du_chemin_rapide(bench, lab, tmp_path):
    """SIGTERM pendant le chemin rapide (ssh-add -L lent) : code 130, l'hôte tapé dans le message."""
    setup(bench, lab, tmp_path)
    assert bench.run("ensure", "--id", ID_A).returncode == 0
    p = fake_ssh(bench, ID_A, "alice@hote-tape", env={"SSHVAULT_SSH_ADD": slow_ssh_add(tmp_path, 5)})
    time.sleep(1.5)
    os.killpg(p.pid, signal.SIGTERM)
    out, err = p.communicate(timeout=20)
    assert "sshvault: hote-tape : interrompu\n" == err, err
    assert no_leftovers(bench) == []


def test_sighup_pendant_bw(bench, lab, tmp_path):
    setup(bench, lab, tmp_path)
    e = dict(bench.env, FAKE_BW_FAIL="get=hang")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "ensure", "--id", ID_A], env=e, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    deadline = time.monotonic() + 20
    while not (bench.pids.exists() and bench.pids.read_text().strip()) and time.monotonic() < deadline:
        time.sleep(0.05)
    p.send_signal(signal.SIGHUP)
    out, err = p.communicate(timeout=20)
    assert p.returncode == 130 and err == "sshvault: %s : interrompu\n" % ID_A
    assert wait_gone([int(x) for x in bench.pids.read_text().split()])


def test_delai_global_pendant_l_invite(bench, lab, tmp_path):
    """Délai global court pendant l'invite : l'invite est bornée par le temps restant (fin avant
    le délai), écho rétabli, une ligne, aucun processus restant."""
    setup(bench, lab, tmp_path)
    lock_vault(bench)
    env = dict(bench.env, SSHVAULT_ENSURE_TIMEOUT="8", SSHVAULT_PROMPT_TIMEOUT="60")
    r = pty_run([[sys.executable, "-m", "sshvault", "ensure", "--id", ID_A]], env, timeout=30)
    assert r.prompts == 1 and r.echo is True
    assert r.returncode == 3 and r.duration < 8, (r.duration, r.stderr)
    assert r.stderr.startswith("sshvault: %s : coffre verrouillé : aucune saisie sur le terminal en " % ID_A)
    assert r.stderr.count("\n") == 1 and r.stragglers == []
    assert no_leftovers(bench) == []


def test_delai_global_invalide(bench, lab, tmp_path):
    setup(bench, lab, tmp_path)
    assert bench.run("ensure", "--id", ID_A).returncode == 0
    r = bench.run("ensure", "--id", ID_A, env={"SSHVAULT_ENSURE_TIMEOUT": "0"})
    assert r.returncode == 2 and "SSHVAULT_ENSURE_TIMEOUT invalide" in r.stderr and r.stderr.count("\n") == 1


@pytest.fixture
def chiffree_lab(bench, lab, tmp_path):
    main = setup(bench, lab, tmp_path)
    bench.add_item(ssh_item(ID_CHIFFREE, "clé chiffrée", bench.keys["chiffree"], hosts="secret"))
    assert bench.run("ssh-config").returncode == 0
    return main


def test_ensure_cle_chiffree_tty(bench, chiffree_lab):
    r = pty_run([[sys.executable, "-m", "sshvault", "ensure", "--id", ID_CHIFFREE]], bench.env,
                answers=[PASSPHRASE], trigger=rb"passphrase")
    assert r.returncode == 0, (r.stderr, r.screen)
    assert PASSPHRASE not in r.screen and r.echo is True
    assert bench.blob("chiffree") in bench.agent_keys()


def test_ensure_cle_chiffree_askpass_et_refus(bench, chiffree_lab, tmp_path):
    prog, calls = make_askpass(tmp_path, reply="mauvaise", name="askpass-faux")
    r = bench.run("ensure", "--id", ID_CHIFFREE, env={"SSH_ASKPASS": prog, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3 and "passphrase" in r.stderr and r.stderr.count("\n") == 1
    assert bench.blob("chiffree") not in bench.agent_keys()
    prog, calls = make_askpass(tmp_path, reply=PASSPHRASE)
    r = bench.run("ensure", "--id", ID_CHIFFREE, env={"SSH_ASKPASS": prog, "SSH_ASKPASS_REQUIRE": "force"})
    assert (r.returncode, r.stderr) == (0, "")
    assert "passphrase" in calls.read_text() and bench.blob("chiffree") in bench.agent_keys()


def test_load_cle_chiffree_en_arriere_plan(bench, chiffree_lab):
    """`sshvault load` d'une clé chiffrée en arrière-plan, sans askpass : code 3 rapide, aucune
    invite, rien chargé (jamais d'arrêt par SIGTTIN)."""
    r = pty_run([[sys.executable, "-m", "sshvault", "load", "--id", ID_CHIFFREE]], bench.env,
                answers=[PASSPHRASE], trigger=rb"passphrase", mode="bg", timeout=30)
    assert r.rcs == [3], (r.stderr, r.screen)
    assert r.prompts == 0 and r.duration < 10
    assert bench.blob("chiffree") not in bench.agent_keys()


def test_exec_apres_hosts_add_et_print(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("hosts", "add", "--id", ID_PERSO, "perso.example")
    assert r.returncode == 0, r.stderr
    text = (bench.home / ".ssh" / "sshvault" / "config").read_text()
    assert "Match originalhost perso.example exec \"'%s' ensure --id %s\"\n" % (bench.exe, ID_PERSO) in text
    r = bench.run("ssh-config", "--print")
    assert r.returncode == 0 and ("exec \"'%s' ensure --id %s\"" % (bench.exe, ID_PERSO)) in r.stdout


def test_config_booleens(bench, lab, tmp_path):
    f = bench.home / ".config" / "sshvault" / "config.json"
    for value, stored in (("yes", True), ("off", False), ("1", True), ("FALSE", False), ("on", True), ("0", False)):
        r = bench.run("config", "set", "auto-confirm", value)
        assert r.returncode == 0 and json.loads(f.read_text())["auto-confirm"] is stored, value
    before = f.read_bytes()
    r = bench.run("config", "set", "auto-load", "peut-être")
    assert r.returncode == 2 and "booléen invalide" in r.stderr and f.read_bytes() == before
    setup(bench, lab, tmp_path)
    f.write_text('{"auto-restrict": "yes"}')
    r = bench.run("config", "get")
    assert r.returncode == 2 and "auto-restrict invalide" in r.stderr
    r = bench.run("ensure", "--id", ID_A)
    assert r.returncode == 2 and r.stderr.startswith("sshvault: %s : " % ID_A) and "auto-restrict invalide" in r.stderr


def test_rechargement_cle_privee_differente(bench, lab, tmp_path):
    """Rechargement d'une clé presque expirée, mais la clé privée du coffre n'est plus celle de
    la clé publique : détecté malgré l'ancienne copie présente, la clé ajoutée est retirée."""
    setup(bench, lab, tmp_path)
    assert bench.run("ensure", "--id", ID_A).returncode == 0
    st = bench.runtime / "sshvault" / "agent.json"
    data = json.loads(st.read_text())
    for e in data["keys"].values():
        e["loaded"] -= 3560  # 40 s restantes
    st.write_text(json.dumps(data))
    wrong = dict(bench.keys["prod"], private=bench.keys["perso"]["private"])
    bench.items[0] = ssh_item(ID_A, "Saut A", wrong, hosts="a")
    bench.write_vault()
    r = bench.run("ensure", "--id", ID_A)
    assert r.returncode == 4 and "clé privée différente" in r.stderr and r.stderr.count("\n") == 1
    assert bench.agent_keys() == [bench.blob("prod")], "clé ajoutée retirée, ancienne copie gardée"

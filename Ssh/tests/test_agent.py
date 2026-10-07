"""Agent dédié (story 3) : vrais ssh-agent et ssh-add (OpenSSH du poste) sur des sockets de test,
clés de test servies par le faux bw. Une ligne de la matrice au moins par test ; l'agent de
l'utilisateur est remplacé par l'agent témoin (revérifié inchangé à la fin de chaque test,
fixture `bench`), et tout ssh-agent du dossier du test est arrêté et vérifié disparu."""
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time

import pytest

from bench import (HAVE_OPENSSH, ID_BASTION, ID_CHIFFREE, ID_PERSO, ID_PROD, PASSPHRASE, agent_list, agents_under,
                   make_askpass, proc_alive, ssh_item, start_agent, wait_gone)
from sshvault.agent import (Agent, AgentError, fingerprint, is_encrypted, literal_host, public_blob, resolve_dir)
from sshvault.agentstate import empty, entry, maybe_locked, reconcile, remaining
from sshvault.config import ConfigError, format_duration, parse_duration

pytestmark = pytest.mark.skipif(not HAVE_OPENSSH, reason="ssh-agent/ssh-add absents")
WATCH_BOUND = 8  # secondes : intervalle du surveillant (2 s) + arrêt de l'agent (SIGTERM, 5 s au pire)


def one_line_error(r):
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    assert len(lines) == 1, r.stderr
    assert "Traceback" not in r.stderr
    return lines[0]


def unlocked(bench):
    bench.unlocked("keyring" if bench.ring else "file")


def adds(bench):
    """Arguments des appels ssh-add qui chargent une clé (se terminent par « - »)."""
    return [a for s, a in bench.ssh_add_calls() if a.endswith(" -") or a == "-"]


def write_state(bench, data):
    p = bench.runtime / "sshvault" / "agent.json"
    fd = os.open(str(p) + ".t", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, json.dumps(data).encode())
    os.close(fd)
    os.replace(str(p) + ".t", str(p))


def no_private_key_under(*dirs, exclude=()):
    for d in dirs:
        for root, _, files in os.walk(str(d)):
            for f in files:
                p = os.path.join(root, f)
                if p in exclude or not os.path.isfile(p):
                    continue
                with open(p, "rb") as fh:
                    assert b"PRIVATE KEY" not in fh.read(), p


# --- premier load -------------------------------------------------------------------

def test_premier_load(bench):
    unlocked(bench)
    assert not bench.sock().exists()
    r = bench.run("load", "--host", "prod.example.com")
    assert r.returncode == 0, r.stderr
    fp = bench.keys["prod"]["fingerprint"]
    assert r.stdout == "chargée : Serveur Prod %s (durée 1h)\n" % fp
    assert bench.agent_keys() == [bench.blob("prod")]
    # critère d'acceptation : `SSH_AUTH_SOCK=<socket dédié> ssh-add -l` montre la clé
    env = dict(os.environ, SSH_AUTH_SOCK=str(bench.sock()))
    l = subprocess.run(["ssh-add", "-l"], env=env, capture_output=True, text=True)
    assert l.returncode == 0 and fp in l.stdout
    # tout appel ssh-add sur le socket dédié ; clé privée jamais en argument ; durée par défaut 1 h
    calls = bench.ssh_add_calls()
    assert calls and all(s == str(bench.sock()) for s, _ in calls)
    assert adds(bench) == ["-t 3600 -"]
    assert all("PRIVATE" not in a for _, a in calls)
    # socket, dossier et état
    d = bench.runtime / "sshvault"
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    assert stat.S_ISSOCK(bench.sock().lstat().st_mode)
    sp = d / "agent.json"
    assert stat.S_IMODE(sp.stat().st_mode) == 0o600
    st = bench.agent_state()
    assert st["keys"] == {fp: {"id": ID_PROD, "name": "Serveur Prod", "hosts": ["prod.example.com", "*.Lab.example"],
                               "loaded": st["keys"][fp]["loaded"], "lifetime": 3600, "confirm": False,
                               "restrict": False}}
    pid = st["agent"]["pid"]
    with open("/proc/%d/cmdline" % pid, "rb") as f:
        argv = f.read().split(b"\0")[:-1]
    assert os.path.basename(argv[0]) == b"ssh-agent" and b"-d" not in argv and b"-D" not in argv
    assert argv[argv.index(b"-a") + 1] == str(bench.sock()).encode()
    w = st["agent"]["watcher"]
    with open("/proc/%d/cmdline" % w, "rb") as f:
        wargv = f.read().split(b"\0")[:-1]
    assert wargv[1:5] == [b"-m", b"sshvault.watch", str(pid).encode(), str(bench.sock()).encode()]
    assert os.getsid(w) == w, "surveillant dans sa propre session"
    no_private_key_under(bench.runtime, bench.home, bench.tmp, exclude=(str(bench.vault_file),))


def test_load_sans_enveloppeur_ssh_add(bench):
    """ssh-add du PATH, sans l'enveloppeur du banc."""
    unlocked(bench)
    env = dict(bench.env)
    del env["SSHVAULT_SSH_ADD"]
    bench.env = env
    r = bench.run("load", "--id", ID_PERSO)
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == [bench.blob("perso")]


# --- clé déjà présente ------------------------------------------------------------

def test_load_cle_presente_puis_force(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    n_bw = len(bench.calls())
    r = bench.run("load", "--id", ID_PROD, "-t", "10m", "--confirm")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("déjà chargée : Serveur Prod ")
    assert adds(bench) == ["-t 3600 -"], "rien rechargé"
    assert not any(c["argv"][1:3] == ["get", "item"] for c in bench.calls()[n_bw:]), "clé privée non lue"
    r = bench.run("load", "--id", ID_PROD, "-t", "10m", "--confirm", "--force")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("chargée : Serveur Prod ") and "durée 10m, confirmation" in r.stdout
    assert adds(bench) == ["-t 3600 -", "-t 600 -c -"]
    e = bench.agent_state()["keys"][bench.keys["prod"]["fingerprint"]]
    assert (e["lifetime"], e["confirm"]) == (600, True)
    assert bench.agent_keys() == [bench.blob("prod")]


# --- --confirm / --restrict --------------------------------------------------------

def hostkey_line(bench, *names):
    return "%s %s\n" % (",".join(names), " ".join(bench.keys["bastion"]["public"].split()[:2]))


def test_load_confirm(bench):
    unlocked(bench)
    r = bench.run("load", "--id", ID_PERSO, "--confirm")
    assert r.returncode == 0, r.stderr
    assert "sans askpass utilisable" in one_line_error(r), "agent lancé sans DISPLAY ni SSH_ASKPASS"
    assert bench.agent_state()["agent"]["askpass"] is False
    assert adds(bench) == ["-t 3600 -c -"]
    assert bench.agent_state()["keys"][bench.keys["perso"]["fingerprint"]]["confirm"] is True
    s = bench.run("agent", "status")
    assert "\tconfirmation" in s.stdout


def literal_hosts_vault(bench):
    """prod sur un seul hôte littéral, bastion sur « Bastion,jump »."""
    bench.items = [ssh_item(ID_PROD, "Serveur Prod", bench.keys["prod"], hosts="prod.example.com"),
                   ssh_item(ID_BASTION, "Bastion RSA", bench.keys["bastion"], hosts="Bastion,jump")]
    bench.write_vault()


@pytest.mark.parametrize("hashed", [False, True])
def test_load_restrict(bench, hashed):
    unlocked(bench)
    bench.known_hosts.write_text(hostkey_line(bench, "Bastion") + hostkey_line(bench, "jump"))
    if hashed:  # mesuré : -h marche avec un known_hosts haché, sur le nom en minuscules
        subprocess.run(["ssh-keygen", "-H", "-f", str(bench.known_hosts)], check=True, capture_output=True)
        assert "Bastion" not in bench.known_hosts.read_text() and "|1|" in bench.known_hosts.read_text()
    r = bench.run("load", "--id", ID_BASTION, "--restrict")
    assert r.returncode == 0, r.stderr
    assert "restreinte à Bastion,jump" in r.stdout
    kh = str(bench.known_hosts)
    assert adds(bench)[-1] == "-t 3600 -H %s -h bastion -h jump -" % kh
    assert bench.agent_keys() == [bench.blob("bastion")]
    assert bench.agent_state()["keys"][bench.keys["bastion"]["fingerprint"]]["restrict"] is True


@pytest.mark.parametrize("host", ["*.Lab.example", "bob@srv.example", "a.example>b.example", "srv.example:2222",
                                  "srv?.example", "-oProxyCommand=x"])
def test_load_restrict_hote_non_litteral(bench, host):
    bench.items = [ssh_item(ID_PROD, "Serveur Prod", bench.keys["prod"], hosts="prod.example.com," + host)]
    bench.write_vault()
    unlocked(bench)
    bench.known_hosts.write_text(hostkey_line(bench, "prod.example.com"))
    r = bench.run("load", "--id", ID_PROD, "--restrict")
    assert r.returncode == 4
    assert "non littéral" in one_line_error(r)
    assert not bench.sock().exists() and not bench.ssh_add_calls()


def test_load_restrict_hote_absent(bench):
    literal_hosts_vault(bench)
    unlocked(bench)
    bench.known_hosts.write_text(hostkey_line(bench, "bastion"))
    r = bench.run("load", "--id", ID_BASTION, "--restrict")
    assert r.returncode == 4
    assert "hôte jump absent de known_hosts" in one_line_error(r)
    assert bench.agent_keys() == []
    assert not any(c["argv"][1:3] == ["get", "item"] for c in bench.calls()), "clé privée jamais lue"
    assert r.stdout == ""


def test_load_restrict_plusieurs_cles_rien_charge(bench):
    """Une clé dont un hôte manque : aucune des clés sélectionnées n'est chargée."""
    literal_hosts_vault(bench)
    unlocked(bench)
    bench.known_hosts.write_text(hostkey_line(bench, "prod.example.com", "bastion"))
    r = bench.run("load", "--all", "--restrict")
    assert r.returncode == 4
    assert "hôte jump absent" in one_line_error(r)
    assert bench.agent_keys() == []


def test_load_force_restrict(bench):
    literal_hosts_vault(bench)
    unlocked(bench)
    bench.known_hosts.write_text(hostkey_line(bench, "bastion", "jump"))
    assert bench.run("load", "--id", ID_BASTION).returncode == 0
    r = bench.run("load", "--id", ID_BASTION, "--restrict", "--force", "-t", "5m")
    assert r.returncode == 0, r.stderr
    kh = "-H %s -h bastion -h jump -" % bench.known_hosts
    assert adds(bench) == ["-t 3600 -", kh, "-t 300 " + kh], "vérification des hôtes, puis rechargement"
    e = bench.agent_state()["keys"][bench.keys["bastion"]["fingerprint"]]
    assert (e["restrict"], e["lifetime"]) == (True, 300)
    assert bench.agent_keys() == [bench.blob("bastion")]


def test_load_restrict_sans_hote(bench):
    unlocked(bench)
    r = bench.run("load", "--id", ID_PERSO, "--restrict")
    assert r.returncode == 4
    assert "aucun hôte associé" in one_line_error(r)
    assert not bench.sock().exists()


# --- sélection ---------------------------------------------------------------------

@pytest.mark.parametrize("args,expected", [
    (["prod.example.com", "--host"], ["prod"]),
    (["x.LAB.example", "--host"], ["prod"]),
    (["bastion", "--name"], ["bastion"]),
    (["PERSO", "--name"], ["perso"]),
    (["FP:perso", "--fingerprint"], ["perso"]),
    ([ID_BASTION, "--id"], ["bastion"]),
    (["jump"], ["bastion"]),
    (["--all"], ["bastion", "perso", "prod"]),
])
def test_load_selection(bench, args, expected):
    unlocked(bench)
    args = [bench.keys["perso"]["fingerprint"] if a == "FP:perso" else a for a in args]
    r = bench.run("load", *args)
    assert r.returncode == 0, r.stderr
    assert len(r.stdout.splitlines()) == len(expected), "une ligne par clé"
    assert sorted(bench.agent_keys()) == sorted(bench.blob(n) for n in expected)


@pytest.mark.parametrize("args", [["inconnu.example", "--host"], ["zzz", "--name"],
                                  ["SHA256:AAAA", "--fingerprint"], ["00000000-0000-4000-8000-000000000000", "--id"]])
def test_load_aucune(bench, args):
    unlocked(bench)
    r = bench.run("load", *args)
    assert r.returncode == 1
    assert "aucune clé" in one_line_error(r)
    assert r.stdout == ""
    assert not bench.sock().exists(), "aucun agent lancé"


@pytest.mark.parametrize("args", [["--host"], [""], ["  ", "--name"], ["-t", "1w", "x"], ["-t", "31d", "x"],
                                  ["-t", "-5", "x"], ["x", "--host", "--name"], [], ["--force"], ["x", "--all"]])
def test_load_usage(bench, args):
    r = bench.run("load", *args)
    assert r.returncode == 2
    line = one_line_error(r)
    if args in ([], ["--force"]):
        assert "préciser une sélection ou --all" in line
    assert not bench.calls() and not bench.sock().exists()


# --- coffre verrouillé ------------------------------------------------------------

def test_load_coffre_verrouille_invite(bench, tmp_path):
    bench.set_state(logged_in=True)
    askpass, calls = make_askpass(tmp_path)
    r = bench.run("load", "--id", ID_PROD, env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 0, r.stderr
    assert len(calls.read_text().splitlines()) == 1
    assert bench.agent_keys() == [bench.blob("prod")]


def test_load_coffre_verrouille_nointeraction(bench, tmp_path):
    bench.set_state(logged_in=True)
    askpass, calls = make_askpass(tmp_path)
    r = bench.run("--nointeraction", "load", "--id", ID_PROD,
                  env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3
    assert "verrouillé" in one_line_error(r)
    assert not calls.exists() and not bench.sock().exists()


def test_load_coffre_verrouille_refus(bench, tmp_path):
    bench.set_state(logged_in=True)
    askpass, _ = make_askpass(tmp_path, rc=1)
    r = bench.run("load", "--id", ID_PROD, env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3
    assert not bench.sock().exists()


# --- clé chiffrée par passphrase -----------------------------------------------------

@pytest.fixture
def chiffree(bench):
    bench.add_item(ssh_item(ID_CHIFFREE, "clé chiffrée", bench.keys["chiffree"], hosts="secret.example"))
    unlocked(bench)
    return bench


def test_load_chiffree_tty(chiffree):
    bench = chiffree
    r, tty = bench.run_tty("load", "--id", ID_CHIFFREE, answer=PASSPHRASE, trigger=b"passphrase")
    assert r.returncode == 0, (r.stderr, tty)
    assert "Enter passphrase" in tty and PASSPHRASE not in tty, "saisie par ssh-add, écho coupé"
    assert bench.agent_keys() == [bench.blob("chiffree")]


def test_load_chiffree_askpass(chiffree, tmp_path):
    bench = chiffree
    askpass, calls = make_askpass(tmp_path, reply=PASSPHRASE)
    r = bench.run("load", "--id", ID_CHIFFREE, env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 0, r.stderr
    assert "passphrase" in calls.read_text()
    assert bench.agent_keys() == [bench.blob("chiffree")]


def test_load_chiffree_refus(chiffree, tmp_path):
    bench = chiffree
    askpass, calls = make_askpass(tmp_path, rc=1)
    r = bench.run("load", "--id", ID_CHIFFREE, env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3
    assert "passphrase" in one_line_error(r)
    assert calls.exists()
    assert bench.agent_keys() == []
    assert bench.agent_state()["keys"] == {}


def test_load_chiffree_nointeraction(chiffree, tmp_path):
    bench = chiffree
    askpass, calls = make_askpass(tmp_path, reply=PASSPHRASE)
    r = bench.run("--nointeraction", "load", "--host", "*",
                  env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3
    assert "clé chiffrée" in one_line_error(r)
    assert adds(bench) == [], "ssh-add jamais lancé pour charger : rien chargé"
    assert bench.agent_keys() == [] and not calls.exists()


# --- agent status ---------------------------------------------------------------------

def test_status_agent_vivant(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    assert bench.run("load", "--id", ID_PERSO, "-t", "0", "--confirm").returncode == 0
    r = bench.run("agent", "status")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    pid = bench.agent_state()["agent"]["pid"]
    assert lines[:3] == ["agent : actif", "socket : %s" % bench.sock(), "pid : %d" % pid]
    rows = {l.split("\t")[0]: l.split("\t") for l in lines[3:]}
    prod = rows["Serveur Prod"]
    assert prod[1:3] == [bench.keys["prod"]["fingerprint"], "prod.example.com,*.Lab.example"]
    assert re.fullmatch(r"(1h00m00s|59m[0-5]\ds)", prod[3]) and prod[4] == "-"
    assert rows["clé perso"][2:] == ["-", "illimitée", "confirmation"]
    assert adds(bench)[-1] == "-c -", "0 = illimitée : pas de -t"


def test_status_agent_arrete(bench):
    r = bench.run("agent", "status")
    assert r.returncode == 3
    assert r.stdout.splitlines() == ["agent : arrêté", "socket : %s" % bench.sock()]
    assert not bench.sock().exists(), "status ne lance rien"


def test_status_cle_chargee_hors_sshvault(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    env = dict(os.environ, SSH_AUTH_SOCK=str(bench.sock()))
    subprocess.run(["ssh-add", "-q", "-"], input=bench.keys["bastion"]["private"], env=env, text=True, check=True)
    r = bench.run("agent", "status")
    assert "?\t%s\t-\t?\t?" % bench.keys["bastion"]["fingerprint"] in r.stdout.splitlines()


def test_cle_expiree_retiree_de_l_etat(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD, "-t", "2s").returncode == 0
    assert bench.run("load", "--id", ID_PERSO, "-t", "1h").returncode == 0
    assert adds(bench)[0] == "-t 2 -"
    time.sleep(3)
    assert bench.agent_keys() == [bench.blob("perso")], "durée posée dans l'agent"
    r = bench.run("agent", "status")
    assert "Serveur Prod" not in r.stdout and "clé perso" in r.stdout
    assert list(bench.agent_state()["keys"]) == [bench.keys["perso"]["fingerprint"]]


# --- purge, lock, unlock ------------------------------------------------------------

def test_purge(bench):
    unlocked(bench)
    assert bench.run("load", "--host", "*").returncode == 0
    assert len(bench.agent_keys()) == 2
    r = bench.run("agent", "purge")
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == []
    rc, _ = agent_list(bench.sock())
    assert rc == 1, "ssh-add -l vide"
    assert bench.agent_state()["keys"] == {}
    assert any(a == "-D" for _, a in bench.ssh_add_calls())


def test_purge_agent_arrete(bench):
    r = bench.run("agent", "purge")
    assert r.returncode == 0 and "rien à purger" in r.stdout
    assert not bench.sock().exists()


def test_lock_unlock(bench, tmp_path):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    askpass, calls = make_askpass(tmp_path, reply="verrou de test")
    ask = {"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"}
    r = bench.run("agent", "lock", env=ask)
    assert r.returncode == 0, r.stderr
    assert len(calls.read_text().splitlines()) == 2, "mot de passe saisi par ssh-add (deux fois)"
    assert bench.agent_keys() == [], "agent verrouillé : aucune clé visible"
    s = bench.run("agent", "status")
    assert s.returncode == 0 and "agent : actif, verrouillé" in s.stdout and "Serveur Prod" in s.stdout
    assert bench.agent_state()["locked"] is True
    r = bench.run("load", "--id", ID_PERSO)
    assert r.returncode == 3 and "agent unlock" in one_line_error(r)
    r = bench.run("agent", "purge")
    assert r.returncode == 3
    bad, _ = make_askpass(tmp_path, reply="faux", name="askpass-faux")
    r = bench.run("agent", "unlock", env={"SSH_ASKPASS": bad, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3
    assert bench.agent_keys() == []
    r = bench.run("agent", "unlock", env=ask)
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == [bench.blob("prod")]
    assert bench.agent_state()["locked"] is False
    assert [a for _, a in bench.ssh_add_calls() if a in ("-x", "-X")] == ["-x", "-X", "-X"]


def test_lock_unlock_tty_sans_echo(bench):
    """Saisie par ssh-add sur le terminal (stdin hors terminal, comme sous Match exec) : jamais affichée."""
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    r, tty = bench.run_tty("agent", "lock", answer=["verrou-tty", "verrou-tty"], trigger=rb"password: |Again: ")
    assert r.returncode == 0, (r.stderr, tty)
    assert "Again" in tty and "verrou-tty" not in tty
    assert bench.agent_keys() == []
    r, tty = bench.run_tty("agent", "unlock", answer="verrou-tty", trigger=rb"password: ")
    assert r.returncode == 0, (r.stderr, tty)
    assert "verrou-tty" not in tty
    assert bench.agent_keys() == [bench.blob("prod")]


def test_lock_sans_saisie_possible(bench, tmp_path):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    askpass, calls = make_askpass(tmp_path)
    r = bench.run("--nointeraction", "agent", "lock", env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3 and "--nointeraction" in one_line_error(r)
    r = bench.run("agent", "lock")  # ni tty, ni askpass
    assert r.returncode == 3 and "aucune saisie" in one_line_error(r)
    assert not calls.exists()
    assert bench.agent_keys() == [bench.blob("prod")], "agent non verrouillé"


def test_lock_agent_arrete(bench):
    r = bench.run("agent", "lock")
    assert r.returncode == 3 and "agent arrêté" in one_line_error(r)


# --- config key-ttl ----------------------------------------------------------------------

def test_config_ttl_puis_load(bench):
    unlocked(bench)
    r = bench.run("config", "set", "key-ttl", "2h")
    assert r.returncode == 0 and r.stdout == "key-ttl 2h\n"
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    assert adds(bench) == ["-t 7200 -"]
    assert bench.run("load", "--id", ID_PROD, "--force", "-t", "10m").returncode == 0, "-t prime"
    assert adds(bench)[-1] == "-t 600 -"
    cfg = bench.home / ".config" / "sshvault" / "config.json"
    before = cfg.read_bytes()
    r = bench.run("config", "set", "key-ttl", "31d")
    assert r.returncode == 2 and "durée invalide" in one_line_error(r)
    assert cfg.read_bytes() == before, "config inchangée"
    assert bench.run("config", "unset", "key-ttl").stdout == "key-ttl 1h (défaut)\n"
    assert bench.run("load", "--id", ID_PERSO).returncode == 0
    assert adds(bench)[-1] == "-t 3600 -"


def test_config_invalide_load_refuse(bench):
    unlocked(bench)
    d = bench.home / ".config" / "sshvault"
    d.mkdir(parents=True, mode=0o700)
    fd = os.open(str(d / "config.json"), os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(fd, b'{"key-ttl": "2h"}')
    os.close(fd)
    r = bench.run("load", "--id", ID_PROD)
    assert r.returncode == 2 and "key-ttl invalide" in one_line_error(r)
    assert not bench.sock().exists()
    assert bench.run("load", "--id", ID_PROD, "-t", "5m").returncode == 0, "-t n'a pas besoin de la config"


# --- agent stop, agent mort, agent tiers ---------------------------------------------------

def test_stop(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    pid = bench.agent_state()["agent"]["pid"]
    r = bench.run("agent", "stop")
    assert r.returncode == 0, r.stderr
    assert "pid %d" % pid in r.stdout
    assert wait_gone([pid]), "agent tué"
    assert not bench.sock().exists() and bench.agent_state() is None
    r = bench.run("agent", "stop")
    assert r.returncode == 0 and "déjà arrêté" in r.stdout


def test_stop_pid_reutilise(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    st = bench.agent_state()
    os.kill(st["agent"]["pid"], signal.SIGKILL)  # socket laissé, agent mort
    assert wait_gone([st["agent"]["pid"]])
    other = subprocess.Popen(["sleep", "600"], start_new_session=True)
    try:
        st["agent"]["pid"] = other.pid  # pid réutilisé par un autre processus
        write_state(bench, st)
        r = bench.run("agent", "stop")
        assert r.returncode == 0, r.stderr
        assert "pid %d n'est plus l'agent" % other.pid in r.stdout and "aucun signal" in r.stdout
        assert other.poll() is None and proc_alive(other.pid), "aucun signal envoyé"
        assert not bench.sock().exists() and bench.agent_state() is None
    finally:
        other.kill()
        other.wait()


def test_stop_pid_reutilise_agent_vivant_repris(bench):
    """Socket vivant, pid enregistré réutilisé : l'agent visant notre socket est repris et
    arrêté ; aucun signal au pid réutilisé."""
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    st = bench.agent_state()
    real = st["agent"]["pid"]
    other = subprocess.Popen(["sleep", "600"], start_new_session=True)
    try:
        st["agent"]["pid"] = other.pid
        write_state(bench, st)
        r = bench.run("agent", "stop")
        assert r.returncode == 0, r.stderr
        assert "pid %d" % real in r.stdout
        assert proc_alive(other.pid) and wait_gone([real]) and not bench.sock().exists()
    finally:
        other.kill()
        other.wait()


def test_agent_mort_relance(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    old = bench.agent_state()["agent"]["pid"]
    os.kill(old, signal.SIGKILL)
    assert wait_gone([old]) and bench.sock().exists(), "socket mort laissé"
    r = bench.run("agent", "status")
    assert r.returncode == 3 and "socket mort" in r.stdout
    r = bench.run("load", "--id", ID_PERSO)
    assert r.returncode == 0, r.stderr
    new = bench.agent_state()["agent"]["pid"]
    assert new != old and proc_alive(new)
    assert bench.agent_keys() == [bench.blob("perso")]
    assert list(bench.agent_state()["keys"]) == [bench.keys["perso"]["fingerprint"]], "état de l'ancien agent vidé"


def test_agent_tiers_sur_le_socket(bench):
    """Socket vivant servi par un agent dont la ligne de commande ne vise pas notre socket
    (lancé par un autre chemin) : refus, rien touché."""
    unlocked(bench)
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700)
    (bench.runtime / "lien").symlink_to(d)
    pid = start_agent(bench.runtime / "lien" / "agent.sock", bench.keys["bastion"]["private"])
    before = agent_list(bench.sock())
    for args in (["load", "--id", ID_PROD], ["agent", "stop"], ["agent", "purge"], ["agent", "status"],
                 ["agent", "lock"]):
        r = bench.run(*args)
        assert r.returncode == 4, args
        assert "non lancé par sshvault" in one_line_error(r)
    assert proc_alive(pid) and agent_list(bench.sock()) == before, "rien touché"
    assert not any(c["argv"][1:3] == ["get", "item"] for c in bench.calls())
    assert not (d / "agent.json").exists()


def test_socket_qui_n_est_pas_un_socket(bench):
    unlocked(bench)
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700)
    bench.sock().write_text("pas un socket")
    r = bench.run("load", "--id", ID_PROD)
    assert r.returncode == 4 and "n'est pas un socket" in one_line_error(r)
    assert bench.sock().read_text() == "pas un socket"


def test_socket_mort_sans_etat_nettoye(bench):
    unlocked(bench)
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700)
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(bench.sock()))
    s.close()  # socket orphelin : fichier présent, personne n'écoute
    r = bench.run("load", "--id", ID_PROD)
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == [bench.blob("prod")]


# --- socket et XDG_RUNTIME_DIR ------------------------------------------------------------

def test_xdg_runtime_hors_tmpfs_refuse(bench, tmp_path):
    unlocked(bench)
    disque = tmp_path / "run-disque"
    disque.mkdir(mode=0o700)
    for args in (["load", "--id", ID_PROD], ["agent", "status"], ["agent", "stop"]):
        r = bench.run(*args, env={"XDG_RUNTIME_DIR": str(disque), "SSHVAULT_KEYCTL": "/nonexistent/keyctl"})
        assert r.returncode == 4, args
        assert "tmpfs privé" in one_line_error(r)
    assert not (disque / "sshvault").exists()


def test_resolve_dir(runtime_dir, tmp_path):
    rt = str(runtime_dir)
    assert resolve_dir({"XDG_RUNTIME_DIR": rt}) == os.path.join(rt, "sshvault")
    # variable absente : repli sur <base>/<uid> s'il passe la même vérification
    base = runtime_dir / "user"
    base.mkdir()
    (base / "4242").mkdir(mode=0o700)
    assert resolve_dir({}, uid=4242, run_user=str(base)) == str(base / "4242" / "sshvault")
    os.chmod(str(base / "4242"), 0o755)
    with pytest.raises(AgentError, match="XDG_RUNTIME_DIR absent, repli refusé"):
        resolve_dir({}, uid=4242, run_user=str(base))
    with pytest.raises(AgentError, match="repli refusé"):
        resolve_dir({}, uid=4243, run_user=str(base))
    with pytest.raises(AgentError, match="chemin absolu"):
        resolve_dir({"XDG_RUNTIME_DIR": "run/user/1"})
    disque = tmp_path / "d"
    disque.mkdir(mode=0o700)
    with pytest.raises(AgentError, match="tmpfs privé"):
        resolve_dir({"XDG_RUNTIME_DIR": str(disque)})
    long = runtime_dir / ("x" * 100)
    long.mkdir(mode=0o700)
    with pytest.raises(AgentError, match="trop long"):
        resolve_dir({"XDG_RUNTIME_DIR": str(long)})
    # même base écrite autrement : même dossier
    (runtime_dir / "lien").symlink_to(runtime_dir)
    for spelled in (rt + "/", rt + "/./", str(runtime_dir / "lien")):
        assert resolve_dir({"XDG_RUNTIME_DIR": spelled}) == os.path.join(rt, "sshvault"), spelled


def test_resolve_dir_repli_reel():
    """Repli par défaut : /run/user/<uid> (lecture seule, rien n'est créé)."""
    d = "/run/user/%d" % os.getuid()
    if not os.path.isdir(d):
        pytest.skip("pas de /run/user/<uid>")
    assert resolve_dir({}) == os.path.join(d, "sshvault")


# --- unités ---------------------------------------------------------------------------------

def test_fingerprint_comme_ssh_keygen(keys):
    for k in keys.values():
        assert fingerprint(public_blob(k["public"])) == k["fingerprint"]
    assert public_blob("ssh-ed25519") is None and public_blob("ssh-ed25519 !!!") is None


def test_is_encrypted(keys, tmp_path):
    assert is_encrypted(keys["chiffree"]["private"].encode())
    for n in ("prod", "perso", "bastion"):
        assert not is_encrypted(keys[n]["private"].encode())
    for fmt, pw, expected in (("PEM", "x-pass", True), ("PKCS8", "x-pass", True), ("PEM", "", False)):
        p = tmp_path / ("k-%s-%d" % (fmt, bool(pw)))
        subprocess.run(["ssh-keygen", "-q", "-t", "rsa", "-b", "1024", "-m", fmt, "-N", pw, "-f", str(p)],
                       check=True, capture_output=True)
        assert is_encrypted(p.read_bytes()) is expected, (fmt, pw)
        p.unlink()


def test_pid_is_agent(runtime_dir):
    a = Agent(str(runtime_dir / "sshvault"))
    p = subprocess.Popen(["sleep", "600"])
    try:
        assert not a.pid_is_agent(p.pid)
        assert not a.pid_is_agent(1) and not a.pid_is_agent(0)
    finally:
        p.kill()
        p.wait()


def test_reconcile():
    d = empty()
    d["keys"] = {"A": entry("1", "a", [], 1000.0, 60, False, False), "B": entry("2", "b", [], 1000.0, 0, False, False)}
    assert reconcile(d, {"A", "B"}, 2000.0) is False
    # agent qui ne montre rien (verrou posé à la main ?) : seules les clés échues partent
    assert reconcile(d, set(), 1030.0) is False and maybe_locked(d, set())
    assert reconcile(d, {"B"}, 2000.0) is True and list(d["keys"]) == ["B"]
    d["locked"] = True
    d["keys"]["A"] = entry("1", "a", [], 1000.0, 60, False, False)
    assert reconcile(d, set(), 1030.0) is False, "verrouillé : rien n'est visible, rien retiré avant l'échéance"
    assert reconcile(d, set(), 1061.0) is True and list(d["keys"]) == ["B"]
    assert remaining(d["keys"]["B"], 5e9) is None


@pytest.mark.parametrize("text,value", [("0", 0), ("1", 1), ("90s", 90), ("15m", 900), ("2h", 7200), ("30d", 2592000),
                                        (" 1h ", 3600), ("0h", 0), ("2592000", 2592000)])
def test_parse_duration(text, value):
    assert parse_duration(text) == value


@pytest.mark.parametrize("text", ["", "abc", "-1", "1w", "1.5h", "31d", "2592001", "1H", "h", "1 h", "1e3"])
def test_parse_duration_invalide(text):
    with pytest.raises(ConfigError, match="durée invalide"):
        parse_duration(text)


def test_format_duration():
    assert [format_duration(v) for v in (0, 1, 90, 900, 7200, 86400, 90061)] == \
        ["0", "1s", "90s", "15m", "2h", "1d", "90061s"]


# --- aucune écriture hors état et socket (strace) ---------------------------------------------

def test_strace_load_n_ecrit_que_l_etat(bench):
    """Critère d'acceptation : strace -f sur un `load` (agent lancé compris) ; seules écritures :
    le fichier d'état (par son temporaire, renommé) et le socket (créé par bind, hors de ces appels)."""
    strace = shutil.which("strace")
    if not strace:
        pytest.skip("strace absent")
    unlocked(bench)
    env = dict(bench.env, PYTHONDONTWRITEBYTECODE="1")
    del env["SSHVAULT_SSH_ADD"]  # l'enveloppeur du banc écrit son journal
    del env["FAKE_BW_LOG"]  # journal du faux bw (banc)
    trace = bench.tmp / "strace.out"
    out = open(str(bench.tmp / "strace.stdout"), "w")
    calls = "openat,openat2,creat,rename,renameat,renameat2,truncate,ftruncate,memfd_create,prctl"
    p = subprocess.Popen([strace, "-f", "-I", "1", "-e", "trace=" + calls, "-o", str(trace),
                          sys.executable, "-m", "sshvault", "load", "--id", ID_PROD],
                         env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                         start_new_session=True)
    # strace -f suit aussi le ssh-agent lancé (démon) : on attend la fin de sshvault, puis
    # strace est arrêté (-I 1 : il se détache de l'agent, qui continue).
    deadline = time.monotonic() + 60
    main_pid, done = None, False
    try:
        while time.monotonic() < deadline and not done and p.poll() is None:
            time.sleep(0.1)
            if not trace.exists():
                continue
            text = trace.read_text(errors="replace")
            if main_pid is None and text:
                main_pid = text.split(None, 1)[0]
            done = main_pid is not None and re.search(r"^%s \+\+\+ exited with 0 \+\+\+$" % main_pid, text, re.M)
    finally:
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=30)
        out.close()
    assert done, (bench.tmp / "strace.stdout").read_text()
    assert bench.agent_keys() == [bench.blob("prod")]
    state = str(bench.runtime / "sshvault" / "agent.json")
    lines = trace.read_text(errors="replace").splitlines()
    # ssh-agent se rend non « dumpable » dès son démarrage (prctl) : strace ne lit plus ses
    # chaînes et affiche une adresse. Seul cas toléré : une ouverture O_RDWR sans création ni
    # troncature (fichier existant ; dans le source d'ssh-agent, stdfd_devnull : /dev/null).
    assert any(re.search(r"prctl\(PR_SET_DUMPABLE, (0|SUID_DUMP_DISABLE)\)", l) for l in lines), "prctl d'ssh-agent attendu"
    written = set()
    for line in lines:
        m = re.search(r'(openat2?|creat)\((?:AT_FDCWD|\d+), (0x[0-9a-f]+), ([A-Z_|]+)', line)
        if m and " = -1 " not in line and m.group(3) not in ("O_RDONLY", "O_RDONLY|O_CLOEXEC"):
            assert m.group(3) in ("O_RDWR", "O_RDWR|O_CLOEXEC"), line
        m = re.search(r'(openat2?|creat)\((?:AT_FDCWD|\d+), "([^"]*)", ([A-Z_|]+)', line)
        if m and re.search(r"O_WRONLY|O_RDWR|O_CREAT|O_TRUNC|O_APPEND", m.group(3)) and " = -1 " not in line:
            written.add(m.group(2))
        m = re.search(r'renameat2?\((?:AT_FDCWD|\d+), "([^"]*)", (?:AT_FDCWD|\d+), "([^"]*)"', line) or \
            re.search(r'rename\("([^"]*)", "([^"]*)"\)', line)
        if m and " = -1 " not in line:
            written.add(m.group(2))
        assert not re.search(r"\b(memfd_create|truncate|ftruncate|creat)\(", line), line
    written -= {"/dev/null", "/dev/tty"}
    assert written, "la trace ne voit aucune écriture : méthode à revoir"
    tmp = re.compile(re.escape(os.path.join(os.path.dirname(state), ".agent.json.")) + r"\d+\.tmp$")
    assert {w for w in written if not (w == state or tmp.match(w))} == set(), written
    assert state in written


# --- revue : cycle de vie, concurrence, identité, reprise, retour arrière -------------------

def _gone_within(pids, bound=WATCH_BOUND):
    return wait_gone(pids, timeout=bound)


def test_surveillant_socket_supprime(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    a = bench.agent_state()["agent"]
    assert proc_alive(a["watcher"])
    os.unlink(str(bench.sock()))
    assert _gone_within([a["pid"], a["watcher"]]), "agent et surveillant arrêtés"


def test_surveillant_runtime_supprime(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    a = bench.agent_state()["agent"]
    shutil.rmtree(str(bench.runtime))  # fin de session : le tmpfs est vidé
    assert _gone_within([a["pid"], a["watcher"]])


def test_surveillant_s_arrete_avec_l_agent(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    a = bench.agent_state()["agent"]
    os.kill(a["pid"], signal.SIGKILL)
    assert _gone_within([a["watcher"]])


def test_agent_stop_arrete_le_surveillant(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    a = bench.agent_state()["agent"]
    assert bench.run("agent", "stop").returncode == 0
    assert wait_gone([a["pid"], a["watcher"]], timeout=1)


def test_orphelin_d_un_run_precedent_arrete(bench):
    """ssh-agent visant notre socket, socket disparu (session précédente) : arrêté au prochain usage."""
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700)
    pid = start_agent(bench.sock())
    os.unlink(str(bench.sock()))
    r = bench.run("status")  # n'importe quelle commande
    assert r.returncode == 3  # coffre non connecté : sans rapport
    assert wait_gone([pid], timeout=1), "orphelin arrêté"


def test_orphelin_a_cote_de_l_agent_enregistre(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    a = bench.agent_state()["agent"]
    real = a["pid"]
    os.kill(a["watcher"], signal.SIGTERM)  # sinon il verrait le socket déplacé un instant
    assert wait_gone([a["watcher"]])
    other = bench.runtime / "autre"
    other.mkdir(mode=0o700)
    # second ssh-agent qui vise notre chemin sans servir le socket : lancé pendant que le socket
    # de l'agent enregistré est mis de côté, puis ce socket est remis en place
    os.rename(str(bench.sock()), str(other / "s"))
    orphan = start_agent(bench.sock())
    os.unlink(str(bench.sock()))
    os.rename(str(other / "s"), str(bench.sock()))
    r = bench.run("agent", "status")
    assert r.returncode == 0, r.stderr
    assert wait_gone([orphan], timeout=1) and proc_alive(real)
    assert bench.agent_keys() == [bench.blob("prod")]


def test_socket_supprime_a_la_main_agent_vivant(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    old = bench.agent_state()["agent"]
    os.unlink(str(bench.sock()))
    r = bench.run("load", "--id", ID_PERSO)
    assert r.returncode == 0, r.stderr
    assert wait_gone([old["pid"]], timeout=1), "ancien agent arrêté avant le nouveau"
    new = bench.agent_state()["agent"]["pid"]
    assert new != old["pid"] and bench.agent_keys() == [bench.blob("perso")]


def test_deux_load_simultanes(bench):
    unlocked(bench)
    procs = [subprocess.Popen([sys.executable, "-m", "sshvault", "load", "--id", i], env=bench.env,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, start_new_session=True)
             for i in (ID_PROD, ID_PERSO, ID_BASTION)]
    outs = [p.communicate(timeout=60) for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0], outs
    agents = [p for p in agents_under(bench.runtime) if b"ssh-agent" in open("/proc/%d/cmdline" % p, "rb").read()
              .split(b"\0")[0]]
    assert agents == [bench.agent_state()["agent"]["pid"]], "un seul agent"
    assert sorted(bench.agent_keys()) == sorted(bench.blob(n) for n in ("prod", "perso", "bastion"))
    assert len(bench.agent_state()["keys"]) == 3, "aucune ligne d'état perdue"


@pytest.mark.parametrize("damage", ["garbage", "future", "mode", "absent"])
def test_etat_perdu_agent_repris(bench, damage):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    pid = bench.agent_state()["agent"]["pid"]
    p = bench.runtime / "sshvault" / "agent.json"
    if damage == "garbage":
        p.write_text("{pas du json")
    elif damage == "future":
        d = json.loads(p.read_text())
        d["version"] = 99
        p.write_text(json.dumps(d))
    elif damage == "mode":
        os.chmod(str(p), 0o644)
    else:
        p.unlink()
    r = bench.run("agent", "status")
    assert r.returncode == 0, r.stderr
    assert "pid : %d" % pid in r.stdout
    r = bench.run("load", "--id", ID_PERSO)
    assert r.returncode == 0, r.stderr
    st = bench.agent_state()
    assert st["agent"]["pid"] == pid and bench.keys["perso"]["fingerprint"] in st["keys"]


def test_xdg_ecrit_autrement_meme_agent(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    pid = bench.agent_state()["agent"]["pid"]
    for spelled in (str(bench.runtime) + "/", str(bench.runtime) + "/./"):
        r = bench.run("agent", "status", env={"XDG_RUNTIME_DIR": spelled})
        assert r.returncode == 0 and "pid : %d" % pid in r.stdout, r.stderr


def test_agent_lance_a_la_main_sur_notre_socket_repris(bench):
    unlocked(bench)
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700)
    pid = start_agent(bench.sock())
    r = bench.run("load", "--id", ID_PROD)
    assert r.returncode == 0, r.stderr
    a = bench.agent_state()["agent"]
    assert a["pid"] == pid and proc_alive(a["watcher"])
    assert bench.agent_keys() == [bench.blob("prod")]


def test_cle_privee_differente_de_la_publique(bench):
    """Élément incohérent : clé publique de prod, clé privée de perso. Rien ne reste dans l'agent."""
    item = ssh_item(ID_PROD, "Serveur Prod", bench.keys["prod"], hosts="prod.example.com")
    item["sshKey"]["privateKey"] = bench.keys["perso"]["private"]
    bench.items = [item]
    bench.write_vault()
    unlocked(bench)
    r = bench.run("load", "--id", ID_PROD)
    assert r.returncode == 4
    assert "différente de la clé publique" in one_line_error(r)
    assert r.stdout == ""
    assert bench.agent_keys() == [], "clé réelle (perso) retirée"
    assert bench.agent_state()["keys"] == {}


def test_echec_sur_la_deuxieme_cle_retour_arriere(chiffree, tmp_path):
    bench = chiffree
    askpass, calls = make_askpass(tmp_path, rc=1)
    r = bench.run("load", "--host", "*", env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3
    assert calls.exists(), "la 2e clé (chiffrée) a été tentée"
    assert adds(bench)[0] == "-t 3600 -", "la 1re (Bastion RSA) chargée puis retirée"
    assert any(a == "-d -" for _, a in bench.ssh_add_calls())
    assert bench.agent_keys() == [] and bench.agent_state()["keys"] == {}
    assert "chargée" not in r.stdout


def test_cle_publique_illisible(bench):
    bad = ssh_item("88888888-8888-4888-8888-888888888888", "clé cassée", bench.keys["perso"])
    bad["sshKey"]["publicKey"] = "ssh-ed25519 !!!pas-du-base64"
    bench.add_item(bad)
    unlocked(bench)
    r = bench.run("load", "--name", "cl")  # clé cassée + clé perso
    assert r.returncode == 0, r.stderr
    assert "clé cassée" in one_line_error(r) and "ignorée" in r.stderr
    assert bench.agent_keys() == [bench.blob("perso")]
    r = bench.run("load", "--name", "cassée")
    assert r.returncode == 4 and "aucune clé chargeable" in r.stderr.splitlines()[-1]


def test_doublon_de_cle_charge_une_fois(bench):
    bench.add_item(ssh_item("99999999-9999-4999-8999-999999999999", "perso bis", bench.keys["perso"]))
    unlocked(bench)
    r = bench.run("load", "--name", "perso")
    assert r.returncode == 0, r.stderr
    assert len(r.stdout.splitlines()) == 1 and len(adds(bench)) == 1


def test_start_retour_arriere_si_l_etat_ne_s_ecrit_pas(runtime_dir, monkeypatch):
    """Écriture de l'état impossible au démarrage : agent et surveillant arrêtés, socket retiré,
    et le démarrage suivant marche."""
    from bench import kill_agents_under
    a = Agent(str(runtime_dir / "sshvault"))
    try:
        def boom(data):
            raise OSError(28, "No space left on device")
        monkeypatch.setattr(a.state, "save", boom)
        with pytest.raises(AgentError, match="écriture de l'état"):
            a.ensure_running()
        assert agents_under(runtime_dir) == [], "aucun agent ni surveillant laissé"
        assert not os.path.exists(a.socket)
        monkeypatch.undo()
        data, started = a.ensure_running()
        assert started and a.pid_is_agent(data["agent"]["pid"])
    finally:
        kill_agents_under(runtime_dir)


def test_start_retour_arriere_nom_inattendu(bench, tmp_path):
    """SSHVAULT_SSH_AGENT dont le processus ne s'appelle pas ssh-agent : arrêté quand même."""
    link = tmp_path / "bin" / "mon-agent"
    link.symlink_to(shutil.which("ssh-agent"))
    unlocked(bench)
    r = bench.run("load", "--id", ID_PROD, env={"SSHVAULT_SSH_AGENT": str(link)})
    assert r.returncode == 4 and "ligne de commande" in one_line_error(r)
    assert agents_under(bench.runtime) == [] and not bench.sock().exists()


def test_openssh_trop_ancien(bench, tmp_path):
    fake = tmp_path / "old"
    fake.mkdir()
    (fake / "ssh").write_text("#!/bin/sh\necho 'OpenSSH_8.2p1 Ubuntu' >&2\n")
    (fake / "ssh").chmod(0o755)
    (fake / "ssh-add").symlink_to(bench.ssh_add)
    unlocked(bench)
    r = bench.run("load", "--id", ID_PROD, env={"SSHVAULT_SSH_ADD": str(fake / "ssh-add")})
    assert r.returncode == 4 and "8.9 ou plus requis" in one_line_error(r)
    assert not bench.sock().exists()


def test_unlock_agent_non_verrouille(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    r = bench.run("agent", "unlock")
    assert r.returncode == 0 and "déjà déverrouillé" in r.stdout
    assert not any(a == "-X" for _, a in bench.ssh_add_calls())


def test_purge_cle_hors_sshvault(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    env = dict(os.environ, SSH_AUTH_SOCK=str(bench.sock()))
    subprocess.run(["ssh-add", "-q", "-"], input=bench.keys["bastion"]["private"], env=env, text=True, check=True)
    assert bench.run("agent", "purge").returncode == 0
    assert bench.agent_keys() == [] and bench.agent_state()["keys"] == {}


def test_drapeau_de_verrou_corrige(bench):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    st = bench.agent_state()
    st["locked"] = True
    write_state(bench, st)
    r = bench.run("agent", "status")
    assert r.returncode == 0 and r.stdout.splitlines()[0] == "agent : actif"
    assert bench.agent_state()["locked"] is False
    assert bench.run("load", "--id", ID_PERSO).returncode == 0


def test_verrou_pose_a_la_main_suppose(bench, tmp_path):
    unlocked(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    askpass, _ = make_askpass(tmp_path, reply="v")
    env = dict(os.environ, SSH_AUTH_SOCK=str(bench.sock()), SSH_ASKPASS=askpass, SSH_ASKPASS_REQUIRE="force")
    subprocess.run(["ssh-add", "-x"], env=env, stdin=subprocess.DEVNULL, capture_output=True, check=True,
                   start_new_session=True)
    r = bench.run("agent", "status")
    assert r.returncode == 0
    assert r.stdout.splitlines()[0] == "agent : actif, verrouillé ?" and "Serveur Prod" in r.stdout
    assert bench.keys["prod"]["fingerprint"] in bench.agent_state()["keys"], "ligne gardée"
    r = bench.run("agent", "unlock", env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 0 and r.stdout == "agent déverrouillé\n"
    assert bench.agent_keys() == [bench.blob("prod")]


def test_literal_host():
    assert all(literal_host(h) for h in ("prod.example.com", "Bastion", "10.0.0.1", "a-b_c"))
    assert not any(literal_host(h) for h in ("*.x", "a?b", "u@h", "a>b", "h:22", "", "-x", "[h]:22", "::1"))


# --- écho du terminal rétabli sur tous les chemins -------------------------------------------

def test_passphrase_refusee_echo_retabli(chiffree):
    bench = chiffree
    r, tty = bench.run_tty("load", "--id", ID_CHIFFREE, answer="", trigger=b"passphrase")
    assert r.returncode == 3, (r.stderr, tty)
    assert bench.tty_echo is True and bench.agent_keys() == []


def test_passphrase_delai_echo_retabli(chiffree):
    bench = chiffree
    t0 = time.monotonic()
    r, tty = bench.run_tty("load", "--id", ID_CHIFFREE, env={"SSHVAULT_PROMPT_TIMEOUT": "1"}, timeout=40)
    assert r.returncode == 3 and "aucune passphrase acceptée" in r.stderr, (r.stderr, tty)
    assert time.monotonic() - t0 < 30
    assert bench.tty_echo is True and bench.agent_keys() == []


def test_passphrase_sigterm_echo_retabli(chiffree):
    bench = chiffree
    r, tty = bench.run_tty("load", "--id", ID_CHIFFREE, trigger=b"passphrase", signal_at_prompt=signal.SIGTERM)
    assert r.returncode == 130, (r.stderr, tty)
    assert bench.tty_echo is True and bench.agent_keys() == []


def test_askpass_tue_avec_ssh_add_au_delai(chiffree, tmp_path):
    """Askpass qui ne répond pas : ssh-add et l'askpass (même groupe) tués au délai."""
    bench = chiffree
    script = tmp_path / "askpass-bloque"
    pidf = tmp_path / "askpass.pid"
    script.write_text("#!/bin/sh\necho $$ > '%s'\nexec sleep 600\n" % pidf)
    script.chmod(0o755)
    r = bench.run("load", "--id", ID_CHIFFREE, env={"SSH_ASKPASS": str(script), "SSH_ASKPASS_REQUIRE": "force",
                                                    "SSHVAULT_PROMPT_TIMEOUT": "1"}, timeout=60)
    assert r.returncode == 3
    assert wait_gone([int(pidf.read_text())], timeout=3), "askpass tué"

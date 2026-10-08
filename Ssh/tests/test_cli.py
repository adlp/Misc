"""CLI sur le faux bw : chaque cas de la matrice d'entrées et de cas limites (bw absent, non
connecté, verrouillé avec ou sans invite, session expirée, list, search, bw en erreur ou
bloqué, lock), plus les cas annexes."""
import json
import os
import pathlib
import stat
import subprocess
import sys
import time

import pytest

from bench import (EMAIL, ID_BASTION, ID_PERSO, ID_PROD, PASSWORD, make_askpass)


def one_line_error(r):
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    assert len(lines) == 1, r.stderr
    assert "Traceback" not in r.stderr
    return lines[0]


def no_private_key(text, bench):
    assert "PRIVATE KEY" not in text
    for k in bench.keys.values():
        body = "".join(k["private"].splitlines()[1:-1])
        assert body[:40] not in text.replace("\n", "")


# --- bw absent -------------------------------------------------------------------

def test_bw_absent_du_path(bench, tmp_path):
    empty = tmp_path / "vide"
    empty.mkdir()
    env = dict(bench.env)
    del env["SSHVAULT_BW"]
    env["PATH"] = str(empty)
    bench.env = env
    r = bench.run("list")
    assert r.returncode == 4
    line = one_line_error(r)
    assert "bw introuvable" in line and "~/.local/bin" in line
    assert "cherché dans le PATH" in line and "bw-path" in line, "message : chemin essayé et réglage"


def test_bw_absent_sshvault_bw(bench):
    r = bench.run("status", env={"SSHVAULT_BW": "/nonexistent/bw"})
    assert r.returncode == 4
    line = one_line_error(r)
    assert "bw introuvable" in line and "/nonexistent/bw" in line and "SSHVAULT_BW" in line


# --- non connecté -----------------------------------------------------------------

def test_non_connecte(bench):
    r = bench.run("list")
    assert r.returncode == 3
    assert "sshvault login" in one_line_error(r)
    assert r.stdout == ""


def test_non_connecte_aucune_invite(bench, tmp_path):
    askpass, calls = make_askpass(tmp_path)
    r = bench.run("list", env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3
    assert not calls.exists(), "pas d'invite si le compte n'est pas connecté"


# --- verrouillé, tty -----------------------------------------------------------

def test_verrouille_tty(bench):
    bench.set_state(logged_in=True)
    r, tty = bench.run_tty("list", answer=PASSWORD)
    assert r.returncode == 0, (r.stderr, tty)
    assert "mot de passe" in tty
    assert PASSWORD not in tty, "écho coupé pendant la saisie"
    assert "Serveur Prod" in r.stdout
    tok = bench.bw_session()
    assert tok and tok in bench.stored_session()
    # le mot de passe n'est passé que par --passwordenv, dans l'environnement de bw
    unlocks = [c for c in bench.calls() if c["argv"][1:2] == ["unlock"]]
    assert len(unlocks) == 1
    assert "--passwordenv" in unlocks[0]["argv"] and PASSWORD not in unlocks[0]["argv"]
    assert unlocks[0]["password_in_env"] == ["SSHVAULT_BW_MASTER_PASSWORD"]
    assert all(c["nointeraction"] for c in bench.calls())
    assert all(PASSWORD not in c["argv"] for c in bench.calls())
    # la session rangée sert à l'appel suivant : un seul appel bw, sans invite
    n = len(bench.calls())
    r2 = bench.run("list")
    assert r2.returncode == 0 and "Serveur Prod" in r2.stdout
    assert len(bench.calls()) == n + 1


def test_verrouille_tty_mauvais_mot_de_passe(bench):
    bench.set_state(logged_in=True)
    r, tty = bench.run_tty("list", answer="mauvais")
    assert r.returncode == 3
    assert one_line_error(r) == ("sshvault: mot de passe maître refusé par bw "
                                 "(Cryptography error, The decryption operation failed)")
    assert bench.stored_session() == (None, None)
    assert bench.bw_session() is None
    assert r.stdout == ""


def test_verrouille_tty_sans_saisie(bench):
    bench.set_state(logged_in=True)
    t0 = time.monotonic()
    r, _ = bench.run_tty("list", env={"SSHVAULT_PROMPT_TIMEOUT": "1"})
    assert r.returncode == 3
    assert "aucune saisie" in one_line_error(r)
    assert time.monotonic() - t0 < 15


def test_verrouille_session_dans_fichier_si_keyctl_echoue(bench):
    bench.set_state(logged_in=True)
    r, _ = bench.run_tty("list", answer=PASSWORD, env={"SSHVAULT_KEYCTL": "/nonexistent/keyctl"})
    assert r.returncode == 0, r.stderr
    f = bench.session_file()
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert f.read_text().split()[0] == bench.bw_session()


# --- verrouillé, sans invite -------------------------------------------------------

def test_verrouille_sans_tty_ni_askpass(bench):
    bench.set_state(logged_in=True)
    r = bench.run("list")
    assert r.returncode == 3
    line = one_line_error(r)
    assert "verrouillé" in line
    assert not any(c["argv"][1:2] == ["unlock"] for c in bench.calls())


def test_verrouille_nointeraction(bench, tmp_path):
    bench.set_state(logged_in=True)
    askpass, calls = make_askpass(tmp_path)
    r = bench.run("--nointeraction", "list", env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3
    assert "verrouillé" in one_line_error(r)
    assert not calls.exists()


def test_verrouille_nointeraction_avec_tty(bench):
    bench.set_state(logged_in=True)
    r, tty = bench.run_tty("--nointeraction", "list", answer=PASSWORD)
    assert r.returncode == 3
    assert "mot de passe" not in tty


def test_verrouille_askpass(bench, tmp_path):
    bench.set_state(logged_in=True)
    askpass, calls = make_askpass(tmp_path)
    r = bench.run("list", env={"SSH_ASKPASS": askpass, "DISPLAY": ":99"})
    assert r.returncode == 0, r.stderr
    assert len(calls.read_text().splitlines()) == 1


def test_verrouille_askpass_annule(bench, tmp_path):
    bench.set_state(logged_in=True)
    askpass, _ = make_askpass(tmp_path, rc=1)
    r = bench.run("list", env={"SSH_ASKPASS": askpass, "DISPLAY": ":99"})
    assert r.returncode == 3
    assert "askpass annulé" in one_line_error(r)


# --- session expirée ou invalidée ------------------------------------------------

@pytest.mark.parametrize("where", ["keyring", "file"])
def test_session_invalidee_purgee_puis_verrouille(bench, tmp_path, where):
    if where == "keyring" and not bench.ring:
        pytest.skip("pas de session keyring dédiée")
    bench.unlocked(where)
    bench.set_state(session="autre-session-AAAAAAAAAAAA")  # un unlock ailleurs l'a invalidée
    r = bench.run("list")
    assert r.returncode == 3
    assert "verrouillé" in one_line_error(r)
    assert bench.stored_session() == (None, None), "session refusée purgée"


def test_session_invalidee_puis_invite(bench, tmp_path):
    bench.unlocked("keyring" if bench.ring else "file")
    bench.set_state(session="autre-session-AAAAAAAAAAAA")
    askpass, calls = make_askpass(tmp_path)
    r = bench.run("list", env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 0, r.stderr
    assert "Serveur Prod" in r.stdout
    assert bench.bw_session() in bench.stored_session()


def test_session_expiree_keyring(bench):
    if not bench.ring:
        pytest.skip("pas de session keyring dédiée")
    tok = "c2Vzc2lvbi1kZS10ZXN0LTEyMzQ1Njc4OTA="
    bench.set_state(session=tok)
    bench.store_session(tok, "keyring", ttl=1)
    time.sleep(1.5)
    r = bench.run("list")
    assert r.returncode == 3
    assert "verrouillé" in one_line_error(r)


def test_session_expiree_fichier(bench):
    tok = "c2Vzc2lvbi1kZS10ZXN0LTEyMzQ1Njc4OTA="
    bench.set_state(session=tok)
    bench.store_session(tok, "file", ttl=-5)
    r = bench.run("list")
    assert r.returncode == 3
    assert not bench.session_file().exists(), "fichier expiré purgé à la lecture"
    # bw n'a pas été appelé avec la session expirée
    assert not any(c["session_env"] for c in bench.calls())


# --- list -------------------------------------------------------------------------

def test_list(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("list")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines == [
        "Bastion RSA\t%s\tBastion,jump" % bench.keys["bastion"]["fingerprint"],
        "clé perso\t%s\t-" % bench.keys["perso"]["fingerprint"],
        "Serveur Prod\t%s\tprod.example.com,*.Lab.example" % bench.keys["prod"]["fingerprint"],
    ]
    assert len(bench.calls()) == 1, "un seul appel bw par opération courante"


def test_list_json(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("list", "--json")
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert [d["id"] for d in data] == [ID_BASTION, ID_PERSO, ID_PROD]
    prod = data[2]
    assert set(prod) == {"id", "name", "fingerprint", "hosts", "forward", "publicKey"}
    assert prod["hosts"] == ["prod.example.com", "*.Lab.example"] and prod["forward"] == []
    assert prod["publicKey"] == bench.keys["prod"]["public"]
    assert data[1]["hosts"] == []


def test_list_aucune_cle_privee(bench):
    """Critère d'acceptation : stdout, stderr et fichiers créés sans clé privée."""
    before = {p for p in bench.tmp.rglob("*")}
    bench.unlocked("keyring" if bench.ring else "file")
    for args in (["list"], ["list", "--json"], ["search", "prod"], ["search", "--json", "x", "--name"]):
        r = bench.run(*args)
        no_private_key(r.stdout + r.stderr, bench)
    for p in bench.tmp.rglob("*"):
        if p.is_file() and p != bench.vault_file and p not in before:
            no_private_key(p.read_text(errors="replace"), bench)


def test_fichiers_et_dossiers_crees(bench):
    assert not (bench.home / ".local").exists()
    assert bench.run("status").returncode == 3  # crée le dossier de données de bw
    bench.set_state(logged_in=True)
    r, _ = bench.run_tty("unlock", answer=PASSWORD, env={"SSHVAULT_KEYCTL": "/nonexistent/keyctl"})
    assert r.returncode == 0, r.stderr
    for d in (bench.home / ".local", bench.home / ".local" / "share", bench.home / ".local" / "share" / "sshvault",
              bench.appdata, bench.runtime / "sshvault"):
        assert stat.S_IMODE(d.stat().st_mode) == 0o700, d
    assert stat.S_IMODE(bench.session_file().stat().st_mode) == 0o600


def test_donnees_bw_dediees(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("list", env={"BITWARDENCLI_APPDATA_DIR": "/tmp/perso", "BW_SESSION": "perso",
                               "BW_CLEANEXIT": "true", "BW_RAW": "true", "BITWARDENCLI_DEBUG": "true",
                               "BW_RESPONSE": "true", "BW_QUIET": "true", "BW_PRETTY": "true",
                               "BW_NOINTERACTION": "false"})
    assert r.returncode == 0
    c = bench.calls()[-1]
    assert c["bw_env"] == ["BITWARDENCLI_APPDATA_DIR", "BW_SESSION"]
    assert c["session_env"] and "perso" not in json.dumps(c)
    assert c["appdata"] == str(bench.appdata)
    xdg = bench.tmp / "xdg"
    bench.run("status", env={"XDG_DATA_HOME": str(xdg)})
    assert bench.calls()[-1]["appdata"] == str(xdg / "sshvault" / "bw")


# --- search -----------------------------------------------------------------------

@pytest.mark.parametrize("args,expected", [
    (["--host", "prod.example.com"], ["Serveur Prod"]),
    (["--host", "PROD.EXAMPLE.COM"], ["Serveur Prod"]),
    (["--host", "*.example.com"], ["Serveur Prod"]),
    (["--host", "*.lab.example"], ["Serveur Prod"]),
    (["--host", "x.LAB.example"], ["Serveur Prod"]),
    (["--host", "bastion"], ["Bastion RSA"]),
    (["--host", "j?mp"], ["Bastion RSA"]),
    (["--host", "*"], ["Bastion RSA", "Serveur Prod"]),
    (["--name", "PROD"], ["Serveur Prod"]),
    (["--name", "é perso"], ["clé perso"]),
    (["--name", "r"], ["Bastion RSA", "clé perso", "Serveur Prod"]),
])
def test_search(bench, args, expected):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("search", args[1], args[0])
    assert r.returncode == 0, r.stderr
    assert [l.split("\t")[0] for l in r.stdout.splitlines()] == expected


@pytest.mark.parametrize("prefix", ["SHA256:", "", "sha256:"])
def test_search_fingerprint(bench, prefix):
    bench.unlocked("keyring" if bench.ring else "file")
    fp = bench.keys["bastion"]["fingerprint"]
    r = bench.run("search", "--fingerprint", prefix + fp[len("SHA256:"):], "--json")
    assert r.returncode == 0, r.stderr
    assert [d["id"] for d in json.loads(r.stdout)] == [ID_BASTION]


def test_search_fingerprint_exacte(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    fp = bench.keys["bastion"]["fingerprint"]
    r = bench.run("search", "--fingerprint", fp[:-2])
    assert r.returncode == 1
    r = bench.run("search", "--fingerprint", fp.lower())
    assert r.returncode == 1 or fp.lower() == fp


def test_search_sans_mode(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("search", "jump")
    assert [l.split("\t")[0] for l in r.stdout.splitlines()] == ["Bastion RSA"]


@pytest.mark.parametrize("args", [["--host", "inconnu.example"], ["--name", "zzz"],
                                  ["--fingerprint", "SHA256:AAAA"]])
def test_search_aucun(bench, args):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("search", args[1], args[0])
    assert r.returncode == 1
    assert "aucune clé" in one_line_error(r)
    assert r.stdout == ""


def test_search_login_non_ssh_ignore(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("search", "--name", "web")
    assert r.returncode == 1


# --- bw en erreur ou bloqué --------------------------------------------------------

@pytest.mark.parametrize("mode", ["badjson", "error"])
def test_bw_erreur_list(bench, mode):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("list", env={"FAKE_BW_FAIL": "list=" + mode})
    assert r.returncode == 4
    assert "erreur bw" in one_line_error(r)
    assert r.stdout == ""
    assert any(bench.stored_session()), "une erreur du backend ne purge pas la session"


@pytest.mark.parametrize("mode", ["badjson", "error"])
def test_bw_erreur_status_pas_d_invite(bench, tmp_path, mode):
    """Une panne de `bw status` n'est pas lue comme « verrouillé » (pas d'invite sur une panne)."""
    bench.set_state(logged_in=True)
    askpass, calls = make_askpass(tmp_path)
    r = bench.run("list", env={"FAKE_BW_FAIL": "status=" + mode, "SSH_ASKPASS": askpass,
                               "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 4
    assert "erreur bw" in one_line_error(r)
    assert not calls.exists()
    r = bench.run("status", env={"FAKE_BW_FAIL": "status=" + mode})
    assert r.returncode == 4


def test_bw_bloque(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    t0 = time.monotonic()
    r = bench.run("list", env={"FAKE_BW_FAIL": "list=hang", "SSHVAULT_BW_TIMEOUT": "2"})
    dt = time.monotonic() - t0
    assert r.returncode == 4
    assert "sans réponse en 2s" in one_line_error(r)
    assert dt < 10
    pids = [int(x) for x in bench.pids.read_text().split()]
    deadline = time.monotonic() + 3
    alive = pids
    while alive and time.monotonic() < deadline:
        alive = [p for p in pids if os.path.exists("/proc/%d" % p)
                 and open("/proc/%d/stat" % p).read().split(")")[-1].split()[0] != "Z"]
        time.sleep(0.1)
    assert not alive, "bw et ses enfants tués"


def _alive(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


def _gone(pids):
    deadline = time.monotonic() + 3
    alive = pids
    while alive and time.monotonic() < deadline:
        alive = [p for p in pids if _alive(p)]
        time.sleep(0.1)
    return not alive


def test_sync_reessaie_une_connexion_bloquee(bench):
    """Mesuré sur le compte de test : une connexion neuve de bw peut rester bloquée
    (ClientHello jamais acquitté) ; sync, idempotent, est relancé dans le même délai total."""
    bench.unlocked("keyring" if bench.ring else "file")
    t0 = time.monotonic()
    r = bench.run("sync", env={"FAKE_BW_FAIL": "sync=hangonce", "SSHVAULT_BW_TIMEOUT": "4"})
    assert r.returncode == 0, r.stderr
    assert time.monotonic() - t0 < 8
    assert len([c for c in bench.calls() if c["argv"][1:] == ["sync"]]) == 2
    assert _gone([int(x) for x in bench.pids.read_text().split()])


def test_sync_bloque_deux_fois(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    t0 = time.monotonic()
    r = bench.run("sync", env={"FAKE_BW_FAIL": "sync=hang", "SSHVAULT_BW_TIMEOUT": "4"})
    assert r.returncode == 4
    assert "2 essais de 2s" in one_line_error(r)
    assert time.monotonic() - t0 < 10, "délai total inchangé"
    assert len([c for c in bench.calls() if c["argv"][1:] == ["sync"]]) == 2


def test_list_bloque_pas_de_nouvel_essai(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("list", env={"FAKE_BW_FAIL": "list=hang", "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 4
    assert len([c for c in bench.calls() if c["argv"][1:] == ["list", "items"]]) == 1


@pytest.mark.parametrize("name", ["SSHVAULT_BW_TIMEOUT", "SSHVAULT_PROMPT_TIMEOUT"])
@pytest.mark.parametrize("value", ["abc", "0", "-1", "86401", "1e9", "inf", "nan"])
def test_timeouts_invalides(bench, name, value):
    bench.set_state(logged_in=True)
    r = bench.run("list", env={name: value})
    assert r.returncode == 2
    assert name in one_line_error(r)
    assert not bench.calls(), "rien lancé"


def test_sigterm_pendant_bw_bloque(bench):
    import signal
    import subprocess
    import sys
    bench.unlocked("keyring" if bench.ring else "file")
    e = dict(bench.env, FAKE_BW_FAIL="list=hang", SSHVAULT_BW_TIMEOUT="60")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "list"], env=e, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    deadline = time.monotonic() + 20
    while not (bench.pids.exists() and len(bench.pids.read_text().split()) == 2) and time.monotonic() < deadline:
        time.sleep(0.1)
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=20)
    assert p.returncode == 130
    assert err.strip() == "sshvault: interrompu"
    assert _gone([int(x) for x in bench.pids.read_text().split()])


# --- lock --------------------------------------------------------------------------

def test_lock(bench):
    if bench.ring:
        bench.unlocked("keyring")
    tok = bench.unlocked("file")
    r = bench.run("lock")
    assert r.returncode == 0, r.stderr
    assert bench.bw_session() is None, "bw lock appelé"
    assert any(c["argv"][1:] == ["lock"] for c in bench.calls())
    assert bench.stored_session() == (None, None)
    assert tok


def test_lock_purge_meme_si_bw_echoue(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("lock", env={"FAKE_BW_FAIL": "lock=error"})
    assert r.returncode == 4
    assert bench.stored_session() == (None, None)


def test_lock_non_connecte(bench):
    r = bench.run("lock")
    assert r.returncode == 0


# --- autres commandes --------------------------------------------------------------

def test_status(bench):
    r = bench.run("status")
    assert r.returncode == 3 and "non connecté" in r.stdout
    bench.set_state(logged_in=True)
    r = bench.run("status")
    assert r.returncode == 3 and "verrouillé" in r.stdout and EMAIL in r.stdout
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("status")
    assert r.returncode == 0 and "déverrouillé" in r.stdout
    assert len([c for c in bench.calls() if c["argv"][1:] == ["status"]]) == 3


def test_status_session_refusee_purgee(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    bench.set_state(session="autre-session-AAAAAAAAAAAA")
    r = bench.run("status")
    assert r.returncode == 3
    assert bench.stored_session() == (None, None)


def test_unlock_ttl(bench):
    if not bench.ring:
        pytest.skip("pas de session keyring dédiée")
    bench.set_state(logged_in=True)
    r, _ = bench.run_tty("unlock", "--ttl", "3", answer=PASSWORD)
    t = time.monotonic()
    assert r.returncode == 0, r.stderr
    assert bench.stored_session()[0] == bench.bw_session()
    assert time.monotonic() - t < 2
    time.sleep(3.5)
    assert bench.stored_session() == (None, None), "expiration posée par le noyau"


def test_unlock_deja_deverrouille(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("unlock")
    assert r.returncode == 0, r.stderr
    assert not any(c["argv"][1:2] == ["unlock"] for c in bench.calls())


def test_unlock_sans_xdg_ni_keyring(bench):
    bench.set_state(logged_in=True)
    env = dict(bench.env)
    env.pop("XDG_RUNTIME_DIR")
    env["SSHVAULT_KEYCTL"] = "/nonexistent/keyctl"
    bench.env = env
    r, _ = bench.run_tty("unlock", answer=PASSWORD)
    assert r.returncode == 4
    assert "session" in one_line_error(r)


def test_list_sans_magasin_avertit(bench, tmp_path):
    bench.set_state(logged_in=True)
    askpass, _ = make_askpass(tmp_path)
    env = dict(bench.env)
    env.pop("XDG_RUNTIME_DIR")
    env.update(SSHVAULT_KEYCTL="/nonexistent/keyctl", SSH_ASKPASS=askpass, SSH_ASKPASS_REQUIRE="force")
    bench.env = env
    r = bench.run("list")
    assert r.returncode == 0
    assert "session non rangée" in one_line_error(r)


def test_sync(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("sync")
    assert r.returncode == 0, r.stderr
    assert bench.state()["lastSync"] != "2026-10-06T00:00:00.000Z"


def test_login_interactif(bench):
    """login délégué à bw : saisie interactive (pas de --nointeraction), session rangée."""
    import subprocess
    import sys
    e = dict(bench.env)
    p = subprocess.run([sys.executable, "-m", "sshvault", "login", "--server", "https://vw.example.test"],
                       env=e, input="%s\n%s\n" % (EMAIL, PASSWORD), capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert bench.state()["serverUrl"] == "https://vw.example.test"
    login = [c for c in bench.calls() if c["argv"][:1] == ["login"]]
    assert login and not login[0]["nointeraction"]
    assert bench.bw_session() in bench.stored_session()
    assert bench.bw_session() not in p.stdout + p.stderr


def test_login_apikey(bench):
    import subprocess
    import sys
    e = dict(bench.env, BW_CLIENTID="user.aaaa", BW_CLIENTSECRET="apisecret")
    p = subprocess.run([sys.executable, "-m", "sshvault", "login", "--apikey"], env=e, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "sshvault unlock" in p.stdout
    assert bench.stored_session() == (None, None)


def test_login_non_abouti(bench):
    """bw login peut finir en code 0 sans connexion (stdin fermé) : mesuré sur le vrai bw 2026.9.1."""
    r = bench.run("login", "--apikey")  # stdin /dev/null, ni BW_CLIENTID ni BW_CLIENTSECRET
    assert r.returncode == 3
    # stderr de bw transmis tel quel (login interactif) ; l'erreur de sshvault est la dernière ligne
    assert r.stderr.splitlines()[-1].startswith("sshvault: login non abouti")
    assert "Traceback" not in r.stderr


def test_login_refuse(bench):
    import subprocess
    import sys
    p = subprocess.run([sys.executable, "-m", "sshvault", "login"], env=bench.env,
                       input="%s\nmauvais\n" % EMAIL, capture_output=True, text=True, timeout=60)
    assert p.returncode == 3
    assert p.stderr.splitlines()[-1].startswith("sshvault: login refusé")
    bench.set_state(logged_in=True)
    p = subprocess.run([sys.executable, "-m", "sshvault", "login"], env=bench.env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 4 and "déjà connecté" in p.stderr.splitlines()[-1]


def test_search_motif_vide(bench):
    for motif in ("", "   "):
        r = bench.run("search", motif)
        assert r.returncode == 2
        assert "motif vide" in one_line_error(r)
    assert not bench.calls()


def test_search_sans_mode_nom_seul_et_empreinte_seule(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("search", "PERSO")  # nom seul (aucun hôte ni empreinte ne contient « perso »)
    assert [l.split("\t")[0] for l in r.stdout.splitlines()] == ["clé perso"]
    fp = bench.keys["perso"]["fingerprint"]
    r = bench.run("search", fp, "--json")  # empreinte seule
    assert [d["id"] for d in json.loads(r.stdout)] == [ID_PERSO]


def test_texte_du_coffre_nettoye(bench):
    from bench import ssh_item
    bench.items.append(ssh_item("66666666-6666-4666-8666-666666666666", "mal\tvenu\n\x1b]0;titre\x07",
                                bench.keys["perso"], hosts="a\x1b[31m,b\tc"))
    bench.write_vault()
    bench.unlocked("keyring" if bench.ring else "file")
    r = bench.run("search", "--name", "mal")
    assert r.returncode == 0
    assert "\x1b" not in r.stdout and r.stdout.count("\n") == 1 and r.stdout.count("\t") == 2
    assert r.stdout.startswith("mal\\x09venu\\x0a\\x1b]0;titre\\x07\t")
    assert "a\\x1b[31m,b\\x09c" in r.stdout
    r = bench.run("search", "--name", "mal", "--json")
    assert json.loads(r.stdout)[0]["name"] == "mal\tvenu\n\x1b]0;titre\x07", "JSON inchangé"


def test_sortie_fermee(bench):
    import subprocess
    import sys
    bench.unlocked("keyring" if bench.ring else "file")
    rfd, wfd = os.pipe()
    os.close(rfd)
    try:
        p = subprocess.run([sys.executable, "-m", "sshvault", "list"], env=bench.env, stdin=subprocess.DEVNULL,
                           stdout=wfd, stderr=subprocess.PIPE, text=True, timeout=60)
    finally:
        os.close(wfd)
    assert p.returncode == 0
    assert p.stderr == ""


def test_unlock_ttl_rafraichit_la_session(bench):
    tok = bench.unlocked("file")
    old_exp = int(bench.session_file().read_text().split()[1])
    env = {"SSHVAULT_KEYCTL": "/nonexistent/keyctl"}
    r = bench.run("unlock", "--ttl", "5000", env=env)
    assert r.returncode == 0, r.stderr
    assert "session 5000s, file" in r.stdout
    tok2, exp = bench.session_file().read_text().split()
    assert tok2 == tok and int(exp) > old_exp + 4000
    assert not any(c["argv"][1:2] == ["unlock"] for c in bench.calls())


def test_unlock_apres_session_invalidee(bench, tmp_path):
    bench.unlocked("keyring" if bench.ring else "file")
    bench.set_state(session="autre-session-AAAAAAAAAAAA")
    askpass, calls = make_askpass(tmp_path)
    r = bench.run("unlock", env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 0, r.stderr
    assert len(calls.read_text().splitlines()) == 1
    assert len([c for c in bench.calls() if c["argv"][1:2] == ["unlock"]]) == 1
    assert bench.bw_session() in bench.stored_session()


def test_unlock_session_rangee_mais_deconnecte(bench, tmp_path):
    bench.unlocked("keyring" if bench.ring else "file")
    bench.set_state(logged_in=False)
    askpass, calls = make_askpass(tmp_path)
    r = bench.run("unlock", env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3
    assert "sshvault login" in one_line_error(r)
    assert not calls.exists()
    assert bench.stored_session() == (None, None)


def test_list_session_rangee_mais_deconnecte(bench):
    bench.unlocked("keyring" if bench.ring else "file")
    bench.set_state(logged_in=False)
    r = bench.run("list")
    assert r.returncode == 3
    assert "sshvault login" in one_line_error(r)
    assert bench.stored_session() == (None, None)


def test_unlock_dit_ou_est_la_session(bench, tmp_path):
    bench.set_state(logged_in=True)
    askpass, _ = make_askpass(tmp_path)
    r = bench.run("unlock", env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force",
                                 "SSHVAULT_KEYCTL": "/nonexistent/keyctl"})
    assert r.returncode == 0 and "session 900s, file" in r.stdout


def test_runtime_pas_tmpfs_prive(bench, tmp_path):
    """Repli fichier refusé hors tmpfs privé : unlock code 4, list marche avec un avertissement."""
    bench.set_state(logged_in=True)
    askpass, _ = make_askpass(tmp_path)
    disque = tmp_path / "run-disque"
    disque.mkdir(mode=0o700)
    partage = bench.runtime / "partage"
    partage.mkdir(mode=0o750)
    for rt in (disque, partage):
        env = {"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force",
               "SSHVAULT_KEYCTL": "/nonexistent/keyctl", "XDG_RUNTIME_DIR": str(rt)}
        r = bench.run("unlock", env=env)
        assert r.returncode == 4
        assert "tmpfs privé" in one_line_error(r)
        assert not (rt / "sshvault").exists()
        r = bench.run("list", env=env)
        assert r.returncode == 0 and "session non rangée" in one_line_error(r)


def test_login_session_non_rangee(bench):
    import subprocess
    import sys
    env = dict(bench.env, SSHVAULT_KEYCTL="/nonexistent/keyctl")
    env.pop("XDG_RUNTIME_DIR")
    p = subprocess.run([sys.executable, "-m", "sshvault", "login"], env=env,
                       input="%s\n%s\n" % (EMAIL, PASSWORD), capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "connecté, coffre déverrouillé" in p.stdout
    # les invites de bw (sans fin de ligne) précèdent l'avertissement sur la même ligne
    assert "sshvault: session non rangée" in p.stderr.splitlines()[-1]


def test_login_tue_retablit_l_echo(bench):
    """bw tué pendant sa saisie masquée (écho coupé) : sshvault rétablit le terminal."""
    import pty
    import signal
    import subprocess
    import sys
    import termios
    master, slave = pty.openpty()
    name = os.ttyname(slave)

    def ctty():
        os.close(os.open(name, os.O_RDWR))

    e = dict(bench.env, FAKE_BW_FAIL="login=hangnoecho")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "login"], env=e, stdin=slave,
                         stdout=subprocess.PIPE, stderr=slave, start_new_session=True, preexec_fn=ctty)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not (termios.tcgetattr(slave)[3] & termios.ECHO) == 0:
            time.sleep(0.1)
        assert not termios.tcgetattr(slave)[3] & termios.ECHO, "le faux bw a coupé l'écho"
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=20)
        assert p.returncode == 130
        assert termios.tcgetattr(slave)[3] & termios.ECHO, "écho rétabli"
        bw_pid, sleep_pid = (int(x) for x in bench.pids.read_text().split())
        assert _gone([bw_pid]), "bw tué"
    finally:
        # le `sleep` enfant du faux bw (le vrai bw n'en a pas) : retiré par le test
        if bench.pids.exists():
            for pid in bench.pids.read_text().split()[1:]:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if p.poll() is None:
            p.kill()
            p.wait()
        os.close(master)
        os.close(slave)


def test_status_decrit_le_magasin(bench):
    r = bench.run("status")
    assert "magasin : keyring" in r.stdout and str(bench.runtime) in r.stdout


def test_usage(bench):
    for args in (["search"], ["inconnue"], ["unlock", "--ttl", "0"], ["unlock", "--ttl", "x"],
                 ["search", "a", "--host", "--name"], [], ["agent"], ["agent", "x"], ["config"],
                 ["config", "set", "key-ttl"], ["config", "get", "a", "b"], ["load", "-t"]):
        r = bench.run(*args)
        assert r.returncode == 2, args
        one_line_error(r)


def test_help():
    import subprocess
    import sys
    from bench import SRC
    r = subprocess.run([sys.executable, "-m", "sshvault", "--help"], env=dict(os.environ, PYTHONPATH=SRC),
                       capture_output=True, text=True)
    assert r.returncode == 0 and "search" in r.stdout


def test_jamais_bw_serve(bench, tmp_path):
    bench.set_state(logged_in=True)
    askpass, _ = make_askpass(tmp_path)
    env = {"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"}
    for args in (["status"], ["unlock"], ["list"], ["search", "x"], ["sync"], ["lock"]):
        bench.run(*args, env=env)
    assert bench.calls()
    assert not any("serve" in c["argv"] for c in bench.calls())


# --- config (story 3) ------------------------------------------------------------------

def config_file(bench):
    return bench.home / ".config" / "sshvault" / "config.json"


def test_config_get_set_unset(bench):
    r = bench.run("config", "get")
    assert r.returncode == 0 and r.stdout == ("key-ttl 1h (défaut)\nauto-load true (défaut)\n"
                                              "auto-restrict false (défaut)\nauto-confirm false (défaut)\n"
                                              "forward-confirm true (défaut)\nbw-path PATH (défaut)\n")
    assert not config_file(bench).exists(), "get n'écrit rien"
    for value, shown in (("90", "90s"), ("90s", "90s"), ("15m", "15m"), ("2h", "2h"), ("30d", "30d"),
                         ("120", "2m"), ("0", "0 (illimitée)")):
        r = bench.run("config", "set", "key-ttl", value)
        assert r.returncode == 0 and r.stdout == "key-ttl %s\n" % shown, value
        assert bench.run("config", "get", "key-ttl").stdout == "key-ttl %s\n" % shown
    f = config_file(bench)
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert json.loads(f.read_text()) == {"key-ttl": 0}
    r = bench.run("config", "unset", "key-ttl")
    assert r.returncode == 0 and r.stdout == "key-ttl 1h (défaut)\n"
    assert json.loads(f.read_text()) == {}
    assert not bench.calls(), "config n'appelle pas bw"


def test_config_xdg_config_home(bench):
    xdg = bench.tmp / "xdg-config"
    assert bench.run("config", "set", "key-ttl", "5m", env={"XDG_CONFIG_HOME": str(xdg)}).returncode == 0
    assert json.loads((xdg / "sshvault" / "config.json").read_text()) == {"key-ttl": 300}
    assert not config_file(bench).exists()


@pytest.mark.parametrize("value", ["abc", "-1", "1w", "31d", "2592001", "1.5h", "", "1H", "2 h"])
def test_config_duree_invalide(bench, value):
    assert bench.run("config", "set", "key-ttl", "2h").returncode == 0
    before = config_file(bench).read_bytes()
    r = bench.run("config", "set", "key-ttl", value)
    assert r.returncode == 2
    assert "durée invalide" in one_line_error(r)
    assert config_file(bench).read_bytes() == before


@pytest.mark.parametrize("args", [["get", "ttl"], ["set", "ttl", "1h"], ["unset", "ttl"]])
def test_config_cle_inconnue(bench, args):
    r = bench.run("config", *args)
    assert r.returncode == 2 and "clé de configuration inconnue" in one_line_error(r)
    assert not config_file(bench).exists()


@pytest.mark.parametrize("content,mode,msg", [(b"{pas du json", 0o600, "JSON invalide"),
                                              (b"[]", 0o600, "objet JSON attendu"),
                                              (b'{"key-ttl": 99999999}', 0o600, "key-ttl invalide"),
                                              (b'{"key-ttl": 60}', 0o644, "illisible")])
def test_config_fichier_invalide(bench, content, mode, msg):
    f = config_file(bench)
    f.parent.mkdir(parents=True, mode=0o700)
    f.write_bytes(content)
    os.chmod(str(f), mode)
    for args in (["get"], ["set", "key-ttl", "1h"]):
        r = bench.run("config", *args)
        assert r.returncode == 2, args
        assert msg in one_line_error(r)
    assert f.read_bytes() == content


def test_config_ecriture_impossible(bench):
    d = config_file(bench).parent.parent  # ~/.config sans droit d'écriture : sshvault/ impossible
    d.mkdir(parents=True, mode=0o700)
    os.chmod(str(d), 0o500)
    try:
        r = bench.run("config", "set", "key-ttl", "1h")
        assert r.returncode == 4 and "écriture de" in one_line_error(r)
    finally:
        os.chmod(str(d), 0o700)


# --- bw-path (story 9) : une ligne de test par ligne de la matrice ------------------------

def _trap(bench):
    """`bw` piège dans un dossier mis en tête du PATH : (dossier, fichier témoin de lancement)."""
    d = bench.tmp / "piege"
    marker = bench.tmp / "piege.log"
    bench.bw_wrapper(d / "bw", marker)
    return d, marker


def _unlock(bench):
    bench.unlocked("keyring" if bench.ring else "file")


def _write_config(bench, data):
    f = config_file(bench)
    f.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    content = (data if isinstance(data, bytes) else json.dumps(data).encode())
    f.write_bytes(content)
    os.chmod(str(f), 0o600)
    return content


def test_bw_path_set_get_unset(bench):
    bench.env = bench.env_without_bw()
    bw = str(bench.bw_wrapper(bench.safe() / "local" / "bin" / "bw", bench.tmp / "local.log"))
    r = bench.run("config", "set", "bw-path", bw)
    assert (r.returncode, r.stdout, r.stderr) == (0, "bw-path %s\n" % bw, "")
    assert json.loads(config_file(bench).read_text()) == {"bw-path": bw}
    assert bench.run("config", "get", "bw-path").stdout == "bw-path %s\n" % bw
    assert bench.run("config", "get").stdout.endswith("forward-confirm true (défaut)\nbw-path %s\n" % bw)
    r = bench.run("config", "unset", "bw-path")
    assert (r.returncode, r.stdout, r.stderr) == (0, "bw-path PATH (défaut)\n", "")
    assert json.loads(config_file(bench).read_text()) == {}
    assert not bench.calls() and not (bench.tmp / "local.log").exists(), "config ne lance pas bw"


def test_bw_path_avis_sshvault_bw(bench):
    """SSHVAULT_BW posé : `set` le dit prioritaire, `unset` le dit toujours utilisé."""
    bw = str(bench.bw_wrapper(bench.safe() / "local" / "bin" / "bw", bench.tmp / "local.log"))
    r = bench.run("config", "set", "bw-path", bw)
    assert r.returncode == 0
    assert r.stdout == "bw-path %s\nSSHVAULT_BW est posé : il reste prioritaire sur bw-path\n" % bw
    r = bench.run("config", "unset", "bw-path")
    assert r.returncode == 0
    assert r.stdout == "bw-path PATH (défaut)\nSSHVAULT_BW est posé : il reste utilisé\n"
    r = bench.run("config", "unset", "bw-path", env={"SSHVAULT_BW": ""})
    assert r.stdout == "bw-path PATH (défaut)\n"


def test_bw_path_lien_symbolique_garde_tel_quel(bench):
    """`~/.local/bin/bw` est souvent un lien vers une version installée à côté : accepté
    (cible ordinaire exécutable), enregistré sans résolution."""
    target = bench.bw_wrapper(bench.safe() / "opt" / "bw-2026.9.1", bench.tmp / "opt.log")
    link = bench.safe() / "lien" / "bw"
    link.parent.mkdir()
    link.symlink_to(target)
    r = bench.run("config", "set", "bw-path", str(link))
    assert r.returncode == 0, r.stderr
    assert json.loads(config_file(bench).read_text()) == {"bw-path": str(link)}


def _refused_paths(bench):
    d = bench.tmp / "refus"
    d.mkdir(exist_ok=True)
    d.chmod(0o755)
    plain = d / "bw-0644"
    plain.write_text("#!/bin/sh\nexit 0\n")
    plain.chmod(0o644)
    fifo = d / "fifo"
    os.mkfifo(str(fifo))
    os.chmod(str(fifo), 0o755)
    good = str(bench.bw)
    return {"relatif": ("bw", "« bw » (chemin absolu attendu)"),
            "relatif-point": ("./bin/bw", "« ./bin/bw » (chemin absolu attendu)"),
            "vide": ("", "« » (chemin absolu attendu)"),  # espaces regroupés par err()
            "absent": (str(d / "absent"), "« %s » (No such file" % (d / "absent")),
            "repertoire": (str(d), "« %s » (pas un fichier ordinaire)" % d),
            "fifo": (str(fifo), "(pas un fichier ordinaire)"),
            "non-executable": (str(plain), "(non exécutable par l'utilisateur)"),
            "controle-nl": (good + "\n", "« %s\\x0a » (caractère de contrôle)" % good),
            "controle-esc": ("/tmp/\x1b[31mbw", "« /tmp/\\x1b[31mbw » (caractère de contrôle)")}


@pytest.mark.parametrize("case", ["relatif", "relatif-point", "vide", "absent", "repertoire", "fifo",
                                  "non-executable", "controle-nl", "controle-esc"])
def test_bw_path_refuse(bench, case):
    value, msg = _refused_paths(bench)[case]
    # sans fichier de config : rien créé
    r = bench.run("config", "set", "bw-path", value)
    assert r.returncode == 2, r.stderr
    line = one_line_error(r)
    assert line.startswith("sshvault: bw-path refusé : ") and msg in line, line
    assert "\x1b" not in line
    assert not config_file(bench).exists()
    # réglage déjà posé : fichier inchangé
    assert bench.run("config", "set", "bw-path", str(bench.bw)).returncode == 0
    before = config_file(bench).read_bytes()
    r = bench.run("config", "set", "bw-path", value)
    assert r.returncode == 2 and msg in one_line_error(r)
    assert config_file(bench).read_bytes() == before
    assert not bench.calls()


def test_bw_path_utilise_sans_sshvault_bw(bench):
    """Réglage posé, PATH sans bw (piège en tête) : status, list et ensure lancent ce bw-là ;
    status le dit."""
    trap_dir, trap = _trap(bench)
    bench.env = bench.env_without_bw([trap_dir])
    used = bench.tmp / "local.log"
    bw = bench.bw_wrapper(bench.safe() / "local" / "bin" / "bw", used)
    assert bench.run("config", "set", "bw-path", str(bw)).returncode == 0
    _unlock(bench)
    r = bench.run("status")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("bw : %s (réglage bw-path)\n" % bw)
    r = bench.run("list")
    assert r.returncode == 0 and "Serveur Prod" in r.stdout, r.stderr
    r = bench.run("ensure", "--id", ID_PROD)
    assert (r.returncode, r.stderr) == (0, ""), r.stderr
    assert bench.agent_keys() == [bench.blob("prod")]
    assert len(used.read_text().splitlines()) == len(bench.calls()) >= 3
    assert not trap.exists(), "bw du PATH jamais lancé"


def test_bw_path_sans_reglage_bw_du_path(bench):
    """Sans réglage : bw du PATH (comportement 0.7.0) ; status dit lequel."""
    path_dir = bench.tmp / "pathbin"
    marker = bench.tmp / "pathbin.log"
    bench.bw_wrapper(path_dir / "bw", marker)
    bench.env = bench.env_without_bw([path_dir])
    _unlock(bench)
    r = bench.run("status")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("bw : %s (PATH)\n" % (path_dir / "bw"))
    assert marker.exists() and len(marker.read_text().splitlines()) == len(bench.calls())


def test_bw_path_autres_reglages_invalides_sans_effet(bench):
    """Un autre réglage invalide dans config.json ne touche pas les commandes qui lancent bw
    (seul bw-path est lu) : status, load -t, lock comme en 0.7.0."""
    path_dir = bench.tmp / "pathbin"
    marker = bench.tmp / "pathbin.log"
    bench.bw_wrapper(path_dir / "bw", marker)
    bench.env = bench.env_without_bw([path_dir])
    content = _write_config(bench, {"key-ttl": "2h"})
    _unlock(bench)
    r = bench.run("status")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("bw : %s (PATH)\n" % (path_dir / "bw"))
    r = bench.run("load", "--id", ID_PROD, "-t", "5m")
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == [bench.blob("prod")]
    r = bench.run("lock")
    assert r.returncode == 0, r.stderr
    assert any(c["argv"][1:] == ["lock"] for c in bench.calls()), "bw lock lancé"
    assert len(marker.read_text().splitlines()) == len(bench.calls())
    assert config_file(bench).read_bytes() == content
    # config, lui, valide tout le fichier
    r = bench.run("config", "get")
    assert r.returncode == 2 and "key-ttl invalide" in one_line_error(r)


def test_bw_path_sshvault_bw_prioritaire(bench):
    """SSHVAULT_BW et réglage posés : SSHVAULT_BW gagne, le bw du réglage n'est pas lancé."""
    marker = bench.tmp / "reglage.log"
    bw = bench.bw_wrapper(bench.tmp / "reglage" / "bw", marker)
    assert bench.run("config", "set", "bw-path", str(bw)).returncode == 0
    _unlock(bench)
    r = bench.run("status")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("bw : %s (SSHVAULT_BW)\n" % bench.bw)
    assert bench.calls() and not marker.exists()


@pytest.mark.parametrize("how,msg", [
    ("supprime", "bw introuvable ("),
    ("non-executable", "bw refusé (%s, réglage bw-path) : non exécutable par l'utilisateur"),
    ("repertoire", "bw refusé (%s, réglage bw-path) : pas un fichier ordinaire"),
    ("sans-shebang", "bw : format non exécutable ("),
    ("interpreteur-absent", "interpréteur ou chargeur de bw introuvable ("),
])
def test_bw_path_disparu(bench, how, msg):
    """Réglage posé puis fichier supprimé ou rendu inutilisable : code 4, une ligne qui cite le
    chemin et bw-path, avec le remède ; le bw du PATH n'est pas lancé."""
    trap_dir, trap = _trap(bench)
    bench.env = bench.env_without_bw([trap_dir])
    bw = bench.bw_wrapper(bench.safe() / "local" / "bin" / "bw", bench.tmp / "local.log")
    assert bench.run("config", "set", "bw-path", str(bw)).returncode == 0
    _unlock(bench)
    bw.unlink()
    if how == "non-executable":
        bw.write_text("#!/bin/sh\nexit 0\n")
        bw.chmod(0o644)
    elif how == "repertoire":
        bw.mkdir()
    elif how == "sans-shebang":
        bw.write_text("echo bw sans shebang\n")
        bw.chmod(0o755)
    elif how == "interpreteur-absent":
        bw.write_text("#!/nonexistent/interp\n")
        bw.chmod(0o755)
    want = msg % bw if "%s" in msg else msg
    for args in (["status"], ["list"], ["ensure", "--id", ID_PROD]):
        r = bench.run(*args)
        assert r.returncode == 4, (args, r.stderr)
        line = one_line_error(r)
        assert str(bw) in line and "bw-path" in line and want in line, line
        assert line.endswith("ou revenir au PATH par « sshvault config unset bw-path »"), line
    assert not trap.exists(), "bw du PATH jamais lancé"
    assert not bench.calls()


@pytest.mark.parametrize("how,reason", [("dossier-non-traversable", "Permission denied"),
                                        ("boucle-de-liens", "Too many levels of symbolic links")])
def test_bw_path_inaccessible_pas_introuvable(bench, how, reason):
    """EACCES ou ELOOP au lancement : « bw refusé » avec la cause, pas « introuvable » ; code
    4 ; le PATH n'est pas essayé."""
    trap_dir, trap = _trap(bench)
    bench.env = bench.env_without_bw([trap_dir])
    if how == "boucle-de-liens":
        target = bench.bw_wrapper(bench.safe() / "opt" / "bw", bench.tmp / "opt.log")
        bw = bench.safe() / "lien" / "bw"
        bw.parent.mkdir()
        bw.symlink_to(target)
    else:
        bw = bench.bw_wrapper(bench.safe() / "ferme" / "bin" / "bw", bench.tmp / "local.log")
    assert bench.run("config", "set", "bw-path", str(bw)).returncode == 0
    _unlock(bench)
    if how == "boucle-de-liens":
        bw.unlink()
        other = bw.parent / "autre"
        other.symlink_to(bw)
        bw.symlink_to(other)
    else:
        bw.parent.parent.chmod(0o000)
    try:
        r = bench.run("status")
    finally:
        if how != "boucle-de-liens":
            bw.parent.parent.chmod(0o755)
    assert r.returncode == 4
    line = one_line_error(r)
    assert line.startswith("sshvault: bw refusé (%s, réglage bw-path) : %s : corriger par" % (bw, reason)), line
    assert not trap.exists() and not bench.calls()


def test_status_bw_absent_dit_le_bw(bench, tmp_path):
    """status dit quel bw serait lancé avant de le lancer : visible même s'il manque."""
    empty = tmp_path / "vide"
    empty.mkdir()
    bench.env = dict(bench.env_without_bw(), PATH=str(empty))
    r = bench.run("status")
    assert r.returncode == 4
    assert r.stdout == "bw : bw (introuvable dans le PATH)\n"
    assert "bw introuvable (bw cherché dans le PATH" in one_line_error(r)


@pytest.mark.parametrize("content,mode,msg", [(b'{"key-ttl": "2h"}', 0o600, "key-ttl invalide"),
                                              (b'{"bw-path": "relatif"}', 0o600, "bw-path invalide"),
                                              (b"{pas du json", 0o600, "JSON invalide"),
                                              (b'{"key-ttl": 60}', 0o644, "illisible")])
def test_ensure_config_invalide(bench, content, mode, msg):
    """ensure (lit tout config.json) : code 2, une ligne `sshvault: <hôte> : …`, sans
    traceback ni bw lancé."""
    trap_dir, trap = _trap(bench)
    bench.env = bench.env_without_bw([trap_dir])
    _write_config(bench, content)
    os.chmod(str(config_file(bench)), mode)
    r = bench.run("ensure", "--id", ID_PROD)
    assert (r.returncode, r.stdout) == (2, "")
    line = one_line_error(r)
    assert line.startswith("sshvault: %s : " % ID_PROD) and msg in line, line
    assert not trap.exists() and not bench.calls()


_CHMOD = "corriger par « chmod g-w,o-w %s »"
_MOVE = "déplacer bw dans un dossier à vous non modifiable par d'autres"
_EXPOSED = {
    # cas : (mode du fichier, mode du dossier, raisons, remède) ; {f} fichier, {d} dossier
    "fichier-0775": (0o775, 0o755, "fichier {f} modifiable par le groupe ou les autres", _CHMOD % "{f}"),
    "dossier-0775": (0o755, 0o775, "dossier {d} modifiable par le groupe ou les autres", _CHMOD % "{d}"),
    "dossier-0777": (0o755, 0o777, "dossier {d} modifiable par le groupe ou les autres", _CHMOD % "{d}"),
    # sticky (type /tmp) : jamais de chmod proposé dessus
    "dossier-sticky": (0o755, 0o1777, "dossier {d} modifiable par le groupe ou les autres", _MOVE),
    "les-deux": (0o775, 0o775, "fichier {f} modifiable par le groupe ou les autres ; dossier {d} "
                              "modifiable par le groupe ou les autres", _CHMOD % "{f} {d}"),
}


def _exposed_line(bw, reasons, fix):
    return ("sshvault: avertissement : bw-path « %s » exposé à d'autres (%s) : ils pourraient remplacer bw et "
            "recevoir le mot de passe maître ; %s" % (bw, reasons, fix))


@pytest.mark.parametrize("case", sorted(_EXPOSED))
def test_bw_path_modifiable_par_d_autres_averti(bench, case):
    """bw-path exposé (fichier ou dossier ouvert au groupe ou aux autres, sticky compris) :
    accepté avec une ligne d'avertissement à `config set` et une seule par processus à
    l'usage ; codes de sortie et stdout inchangés ; le PATH n'est pas essayé."""
    fmode, dmode, reasons, fix = _EXPOSED[case]
    trap_dir, trap = _trap(bench)
    bench.env = bench.env_without_bw([trap_dir])
    used = bench.tmp / "local.log"
    bw = bench.bw_wrapper(bench.safe() / "partage" / "bw", used)
    bw.chmod(fmode)
    bw.parent.chmod(dmode)
    want = _exposed_line(bw, reasons.format(f=bw, d=bw.parent), fix.format(f=bw, d=bw.parent))
    r = bench.run("config", "set", "bw-path", str(bw))
    assert (r.returncode, r.stdout, r.stderr) == (0, "bw-path %s\n" % bw, want + "\n")
    assert json.loads(config_file(bench).read_text()) == {"bw-path": str(bw)}
    _unlock(bench)
    r = bench.run("status")
    assert r.returncode == 0
    assert r.stderr == want + "\n", "une seule ligne pour tous les appels de bw du processus"
    assert r.stdout.startswith("bw : %s (réglage bw-path)\n" % bw)
    r = bench.run("list")
    assert r.returncode == 0 and "Serveur Prod" in r.stdout and r.stderr == want + "\n"
    r = bench.run("list", env={"SSHVAULT_BW": str(bench.bw)})
    assert (r.returncode, r.stderr) == (0, ""), "SSHVAULT_BW : bw-path ni lu ni averti"
    assert r.stdout == bench.run("list").stdout, "stdout inchangé par l'avertissement"
    r = bench.run("ensure", "--id", ID_PROD)
    assert (r.returncode, r.stdout) == (0, "")
    assert r.stderr == "sshvault: %s : %s\n" % (ID_PROD, want[len("sshvault: "):])
    assert bench.agent_keys() == [bench.blob("prod")]
    assert used.exists() and not trap.exists()


def test_bw_path_lien_dans_un_dossier_ouvert(bench):
    """Lien dans un dossier 0775 (le ~/.local/bin courant) vers un fichier d'un dossier 0755 :
    le dossier du lien est nommé."""
    target = bench.bw_wrapper(bench.safe() / "opt" / "bw-2026.9.1", bench.tmp / "opt.log")
    link = bench.safe() / "bin" / "bw"
    link.parent.mkdir()
    link.symlink_to(os.path.relpath(str(target), str(link.parent)))  # lien relatif
    link.parent.chmod(0o775)
    r = bench.run("config", "set", "bw-path", str(link))
    assert r.returncode == 0
    assert r.stderr == _exposed_line(link, "dossier %s modifiable par le groupe ou les autres" % link.parent,
                                     _CHMOD % link.parent) + "\n"


def test_bw_path_parent_ouvert(bench):
    """Un dossier parent ouvert au groupe (renommer `bin`, y planter un autre bw) : averti."""
    bw = bench.bw_wrapper(bench.safe() / "haut" / "bin" / "bw", bench.tmp / "local.log")
    top = bw.parent.parent
    top.chmod(0o775)
    r = bench.run("config", "set", "bw-path", str(bw))
    assert r.returncode == 0
    assert r.stderr == _exposed_line(bw, "dossier %s modifiable par le groupe ou les autres" % top,
                                     _CHMOD % top) + "\n"


def test_bw_path_avertit_avant_le_premier_lancement(bench, tmp_path):
    """`unlock` avec un bw-path exposé : l'avertissement paraît avant le premier lancement de bw
    et avant l'invite du mot de passe (bw recevra le mot de passe maître)."""
    log = tmp_path / "ordre.log"
    bw = bench.safe() / "partage" / "bw"
    bw.parent.mkdir()
    bw.write_text("#!/bin/sh\necho BW-LANCE >> '%s'\nexec '%s' \"$@\"\n" % (log, bench.bw))
    bw.chmod(0o755)
    bw.parent.chmod(0o775)
    askpass = tmp_path / "askpass-ordre"
    askpass.write_text("#!/bin/sh\necho INVITE >> '%s'\nprintf '%%s\\n' '%s'\n" % (log, PASSWORD))
    askpass.chmod(0o755)
    bench.env = bench.env_without_bw()
    assert bench.run("config", "set", "bw-path", str(bw)).returncode == 0
    bench.set_state(logged_in=True)
    e = dict(bench.env, SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE="force")
    with open(str(log), "ab") as out:
        r = subprocess.run([sys.executable, "-m", "sshvault", "unlock"], env=e, stdout=subprocess.PIPE,
                           stderr=out, stdin=subprocess.DEVNULL, start_new_session=True, timeout=60)
    assert r.returncode == 0
    lines = log.read_text().splitlines()
    assert "INVITE" in lines and "BW-LANCE" in lines, lines
    warn = [i for i, l in enumerate(lines) if l.startswith("sshvault: avertissement : bw-path")]
    assert len(warn) == 1 and warn[0] < lines.index("BW-LANCE") and warn[0] < lines.index("INVITE"), lines


def test_bw_path_un_avertissement_par_processus(bench):
    """Commande qui lance bw plusieurs fois (hosts add) : une seule ligne d'avertissement."""
    bw = bench.bw_wrapper(bench.safe() / "partage" / "bw", bench.tmp / "local.log")
    bw.parent.chmod(0o775)
    bench.env = bench.env_without_bw()
    assert bench.run("config", "set", "bw-path", str(bw)).returncode == 0
    _unlock(bench)
    n = len(bench.calls())
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example")
    assert r.returncode == 0, r.stderr
    assert len(bench.calls()) - n >= 2
    assert [l for l in r.stderr.splitlines() if "avertissement : bw-path" in l] == [
        _exposed_line(bw, "dossier %s modifiable par le groupe ou les autres" % bw.parent, _CHMOD % bw.parent)]


def test_bw_path_proprietaire_etranger(bench, monkeypatch):
    """Fichier et dossiers à un autre utilisateur : « exposé », remède « déplacer », jamais de
    chmod sur ce qui n'est pas à l'utilisateur."""
    from sshvault import fsutil
    bw = bench.bw_wrapper(bench.safe() / "local" / "bin" / "bw", bench.tmp / "local.log")
    real = os.getuid()
    monkeypatch.setattr(fsutil.os, "getuid", lambda: real + 4242)
    line = fsutil.exposure_warning(str(bw))
    assert line.startswith("avertissement : bw-path « %s » exposé à d'autres (fichier %s à un autre utilisateur "
                           "(uid %d) ; dossier %s à un autre utilisateur (uid %d)" % (bw, bw, real, bw.parent, real))
    assert line.endswith(" ; " + _MOVE) and "chmod" not in line


def test_bw_path_systeme_root_sans_avertissement(bench):
    """Exécutable à root dans des dossiers à root non ouverts en écriture : ni refus ni
    avertissement."""
    exe = "/usr/bin/true"
    for p in (exe, "/usr/bin", "/usr", "/"):
        st = os.stat(p)
        if st.st_uid != 0 or st.st_mode & 0o022 or os.path.islink(p):
            pytest.skip("%s pas à root ou ouvert en écriture sur ce poste" % p)
    r = bench.run("config", "set", "bw-path", exe)
    assert (r.returncode, r.stderr) == (0, "")


@pytest.mark.parametrize("how,msg", [("sans-shebang", "bw : format non exécutable (bw cherché dans le PATH"),
                                     ("interpreteur-absent", "interpréteur ou chargeur de bw introuvable (bw "
                                                             "cherché dans le PATH")])
def test_bw_du_path_inutilisable(bench, how, msg):
    """Sans réglage : bw du PATH présent mais impossible à lancer, la cause dite."""
    d = bench.tmp / "pathbin"
    d.mkdir()
    (d / "bw").write_text("echo x\n" if how == "sans-shebang" else "#!/nonexistent/interp\n")
    (d / "bw").chmod(0o755)
    bench.env = bench.env_without_bw([d])
    r = bench.run("status")
    assert r.returncode == 4
    line = one_line_error(r)
    assert msg in line and "bw-path" in line, line


def test_bw_path_unset_retour_au_path(bench):
    path_dir = bench.tmp / "pathbin"
    in_path = bench.tmp / "pathbin.log"
    bench.bw_wrapper(path_dir / "bw", in_path)
    bench.env = bench.env_without_bw([path_dir])
    configured = bench.tmp / "local.log"
    bw = bench.bw_wrapper(bench.safe() / "local" / "bin" / "bw", configured)
    assert bench.run("config", "set", "bw-path", str(bw)).returncode == 0
    _unlock(bench)
    assert bench.run("status").returncode == 0
    assert configured.exists() and not in_path.exists()
    assert bench.run("config", "unset", "bw-path").returncode == 0
    n = len(configured.read_text().splitlines())
    assert bench.run("status").returncode == 0
    assert in_path.exists() and len(configured.read_text().splitlines()) == n


@pytest.mark.parametrize("value,msg", [
    ("bw", "bw-path invalide : « bw » (chemin absolu attendu)"),
    ("", "bw-path invalide : « » (chemin absolu attendu)"),  # espaces regroupés par err()
    (5, "bw-path invalide : 5 (chemin absolu attendu)"),
    (None, "bw-path invalide : null (chemin absolu attendu)"),
    (True, "bw-path invalide : true (chemin absolu attendu)"),
    (["/usr/bin/bw"], 'bw-path invalide : ["/usr/bin/bw"] (chemin absolu attendu)'),
    ("/tmp/b\nw", "bw-path invalide : « /tmp/b\\x0aw » (caractère de contrôle)")])
def test_bw_path_fichier_invalide(bench, value, msg):
    """config.json avec un bw-path qui n'est pas une chaîne absolue : code 2, à `config` comme
    à l'usage (sans SSHVAULT_BW) ; rien lancé, fichier inchangé."""
    trap_dir, trap = _trap(bench)
    bench.env = bench.env_without_bw([trap_dir])
    content = _write_config(bench, {"bw-path": value})
    for args in (["config", "get"], ["config", "set", "key-ttl", "1h"], ["status"], ["lock"]):
        r = bench.run(*args)
        assert r.returncode == 2, (args, r.stderr)
        assert msg in one_line_error(r)
    assert config_file(bench).read_bytes() == content
    assert not trap.exists() and not bench.calls()


@pytest.mark.parametrize("content,mode,msg", [(b"{pas du json", 0o600, "JSON invalide"),
                                              (b"[]", 0o600, "objet JSON attendu"),
                                              (b'{"bw-path": "/usr/bin/bw"}', 0o644, "illisible")])
def test_bw_path_illisible(bench, content, mode, msg):
    """Valeur de bw-path impossible à établir (fichier illisible, droits, JSON) : code 2, rien
    lancé."""
    trap_dir, trap = _trap(bench)
    bench.env = bench.env_without_bw([trap_dir])
    _write_config(bench, content)
    os.chmod(str(config_file(bench)), mode)
    r = bench.run("status")
    assert r.returncode == 2 and msg in one_line_error(r)
    assert not trap.exists() and not bench.calls()


def test_bw_path_lecture_paresseuse(bench):
    """bw-path invalide, sans SSHVAULT_BW : une commande qui ne lance pas bw ne le lit pas."""
    bench.env = bench.env_without_bw()
    _write_config(bench, {"bw-path": "relatif"})
    r = bench.run("agent", "status")
    assert r.returncode == 3, r.stderr
    assert "bw-path" not in r.stdout + r.stderr
    assert not bench.calls()


def test_bw_path_jamais_de_shell(bench):
    """Chemin avec espace, apostrophe et `$` : lancé tel quel (argv), sans shell."""
    d = bench.tmp / "un dossier$(touch PWNED) 'x'"
    marker = bench.tmp / "shell.log"
    bw = bench.bw_wrapper(d / "bw", marker)
    bench.env = bench.env_without_bw()
    assert bench.run("config", "set", "bw-path", str(bw)).returncode == 0
    _unlock(bench)
    r = bench.run("status")
    assert r.returncode == 0, r.stderr
    assert marker.exists()
    assert not list(bench.tmp.rglob("PWNED")) and not (pathlib.Path.cwd() / "PWNED").exists()


# --- hosts (CAP-4) : une ligne de test par ligne de la matrice de la story 4 ----------------

def _hosts_field(item):
    return [f for f in (item.get("fields") or []) if f.get("name") == "sshvault-hosts"]


def _edits(bench):
    return [c for c in bench.calls() if "edit" in c["argv"]]


def _assert_no_json_in_argv(bench):
    """Journal argv du faux bw : ni JSON, ni base64 de l'élément, ni clé privée."""
    for c in bench.calls():
        for a in c["argv"]:
            assert "{" not in a and "PRIVATE" not in a and len(a) < 80, c["argv"]
            for k in bench.keys.values():
                assert "".join(k["private"].splitlines()[1:2])[:20] not in a


def _unlocked(bench):
    bench.unlocked("keyring" if bench.ring else "file")


def test_hosts_add_cree_le_champ(bench):
    _unlocked(bench)
    before = bench.vault_item(ID_PERSO)
    r = bench.run("hosts", "add", "--id", ID_PERSO, "Perso.Example", "b.example,perso.example")
    assert r.returncode == 0, r.stderr
    assert "hôtes de « clé perso » : perso.example,b.example" in r.stdout
    after = bench.vault_item(ID_PERSO)
    assert _hosts_field(after) == [{"name": "sshvault-hosts", "value": "perso.example,b.example", "type": 0,
                                    "linkedId": None}]
    assert after["sshKey"] == before["sshKey"] and after["notes"] == before["notes"]
    edits = _edits(bench)
    assert len(edits) == 1 and edits[0]["argv"] == ["--nointeraction", "edit", "item", ID_PERSO]
    _assert_no_json_in_argv(bench)
    # relu après écriture, puis ssh-config régénéré
    assert [c["argv"][1:] for c in bench.calls()][-1] == ["get", "item", ID_PERSO]
    cfg = (bench.home / ".ssh" / "sshvault" / "config").read_text()
    assert "Match originalhost perso.example,b.example\n" in cfg
    assert "config : écrit" in r.stdout


def test_hosts_add_complete_en_minuscules_sans_doublon(bench):
    _unlocked(bench)
    before = bench.vault_item(ID_BASTION)
    r = bench.run("hosts", "add", "--name", "bastion", "JUMP", "Rebond.Example")
    assert r.returncode == 0, r.stderr
    after = bench.vault_item(ID_BASTION)
    assert _hosts_field(after)[0]["value"] == "bastion,jump,rebond.example"
    # autres champs, notes, clé conservés
    assert [f for f in after["fields"] if f["name"] == "note"] == [f for f in before["fields"] if f["name"] == "note"]
    assert after["sshKey"] == before["sshKey"]
    assert after["revisionDate"] != before["revisionDate"]


def test_hosts_add_rien_a_ajouter(bench):
    _unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_BASTION, "jump")
    assert r.returncode == 0, r.stderr
    assert "inchangés" in r.stdout
    assert not _edits(bench)


def test_hosts_selection_multiple(bench):
    _unlocked(bench)
    r = bench.run("hosts", "add", "--name", "e", "x.example")  # « Serveur Prod », « clé perso », …
    assert r.returncode == 2
    assert "préciser --id" in one_line_error(r)
    assert not _edits(bench)


def test_hosts_selection_aucune(bench):
    _unlocked(bench)
    r = bench.run("hosts", "add", "--name", "inconnu", "x.example")
    assert r.returncode == 1
    assert not _edits(bench)


def test_hosts_remove(bench):
    _unlocked(bench)
    r = bench.run("hosts", "remove", "--id", ID_PROD, "PROD.example.com")
    assert r.returncode == 0, r.stderr
    assert _hosts_field(bench.vault_item(ID_PROD))[0]["value"] == "*.lab.example"


def test_hosts_remove_dernier_hote_retire_le_champ(bench):
    _unlocked(bench)
    before = bench.vault_item(ID_BASTION)
    r = bench.run("hosts", "remove", "--id", ID_BASTION, "bastion,jump")
    assert r.returncode == 0, r.stderr
    after = bench.vault_item(ID_BASTION)
    assert not _hosts_field(after)
    assert after["fields"] == [f for f in before["fields"] if f["name"] != "sshvault-hosts"]


def test_hosts_remove_hote_absent(bench):
    _unlocked(bench)
    before = bench.vault_item(ID_BASTION)
    r = bench.run("hosts", "remove", "--id", ID_BASTION, "jump", "absent.example")
    assert r.returncode == 1
    assert "absent.example" in one_line_error(r)
    assert not _edits(bench) and bench.vault_item(ID_BASTION) == before


def test_hosts_set_et_list(bench):
    _unlocked(bench)
    r = bench.run("hosts", "set", "--id", ID_PROD, "a.example,B.example")
    assert r.returncode == 0, r.stderr
    assert _hosts_field(bench.vault_item(ID_PROD))[0]["value"] == "a.example,b.example"
    r = bench.run("hosts", "list", "--id", ID_PROD)
    assert r.returncode == 0 and r.stdout == "a.example\nb.example\n"
    r = bench.run("hosts", "set", "--id", ID_PROD, "")
    assert r.returncode == 0, r.stderr
    assert not _hosts_field(bench.vault_item(ID_PROD))
    r = bench.run("hosts", "list", "--id", ID_PROD)
    assert r.returncode == 0 and r.stdout == ""


@pytest.mark.parametrize("host", ["a b", "!neg", "50%", '"q"', "user@h", "h:22", "a/b", "ctl\x01", "é.example",
                                  "K.example"])
@pytest.mark.parametrize("cmd", ["add", "set"])
def test_hosts_invalide_rien_ecrit(bench, cmd, host):
    _unlocked(bench)
    before = bench.vault_item(ID_PROD)
    r = bench.run("hosts", cmd, "--id", ID_PROD, "ok.example", host)
    assert r.returncode == 2, r.stderr
    assert "hôte invalide" in one_line_error(r)
    assert not _edits(bench) and bench.vault_item(ID_PROD) == before


def test_hosts_hote_invalide_deja_dans_le_coffre(bench):
    """Saisi dans l'interface web : add refuse d'écrire la liste, remove permet de le retirer."""
    bench.items[0]["fields"][0]["value"] = "prod.example.com, mauvais hote"
    bench.write_vault()
    _unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example")
    assert r.returncode == 2 and "déjà dans" in one_line_error(r)
    assert not _edits(bench)
    r = bench.run("hosts", "remove", "--id", ID_PROD, "mauvais hote")
    assert r.returncode == 0, r.stderr
    assert _hosts_field(bench.vault_item(ID_PROD))[0]["value"] == "prod.example.com"


def test_hosts_champ_masque_garde_son_type(bench):
    bench.items[0]["fields"][0]["type"] = 1
    bench.write_vault()
    _unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example")
    assert r.returncode == 0, r.stderr
    assert _hosts_field(bench.vault_item(ID_PROD)) == [
        {"name": "sshvault-hosts", "value": "prod.example.com,*.lab.example,x.example", "type": 1, "linkedId": None}]


def test_hosts_edit_en_echec_rejoue_une_fois(bench):
    _unlocked(bench)
    before = bench.vault_item(ID_PROD)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example", env={"FAKE_BW_FAIL": "edit=error"})
    assert r.returncode == 4
    line = one_line_error(r)
    assert "deux fois" in line and "état relu : élément inchangé (hôtes : prod.example.com,*.lab.example)" in line
    argv = [c["argv"][1:] for c in bench.calls()]
    assert argv.count(["edit", "item", ID_PROD]) == 2
    # relecture de l'état réel (sync puis get) avant le rejeu
    i = argv.index(["edit", "item", ID_PROD])
    assert argv[i + 1:i + 3] == [["sync"], ["get", "item", ID_PROD]]
    assert bench.vault_item(ID_PROD) == before


def test_hosts_edit_en_echec_une_fois(bench):
    _unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example", env={"FAKE_BW_FAIL": "edit=erroronce"})
    assert r.returncode == 0, r.stderr
    assert len(_edits(bench)) == 2
    assert _hosts_field(bench.vault_item(ID_PROD))[0]["value"].endswith(",x.example")


def test_hosts_edit_bloque_sans_ecriture_rejoue(bench):
    _unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example",
                  env={"FAKE_BW_FAIL": "edit=hangonce", "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    assert len(_edits(bench)) == 2
    assert _hosts_field(bench.vault_item(ID_PROD))[0]["value"].endswith(",x.example")
    assert _gone([int(x) for x in bench.pids.read_text().split()]), "bw bloqué et son enfant tués"


@pytest.mark.parametrize("mode", ["hangafter", "errorafter"])
def test_hosts_edit_ecrit_puis_bloque_pas_de_rejeu(bench, mode):
    """La réponse se perd mais l'écriture est passée : la relecture le voit, rien n'est rejoué."""
    _unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example",
                  env={"FAKE_BW_FAIL": "edit=" + mode, "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    assert len(_edits(bench)) == 1
    assert _hosts_field(bench.vault_item(ID_PROD))[0]["value"].endswith(",x.example")


def test_hosts_element_change_entre_temps_pas_de_rejeu(bench):
    _unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example", env={"FAKE_BW_EDIT_RACE": "notes=autre client"})
    assert r.returncode == 4
    line = one_line_error(r)
    assert "out of date" in line and "a changé dans le coffre" in line and "rien rejoué" in line
    assert len(_edits(bench)) == 1
    item = bench.vault_item(ID_PROD)
    assert item["notes"] == "autre client" and not item["fields"][0]["value"].endswith("x.example")


def test_hosts_edit_reussi_mais_relu_different(bench):
    _unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example", env={"FAKE_BW_FAIL": "edit=silent"})
    assert r.returncode == 4
    assert "bw edit a réussi mais l'élément relu diffère (hôtes relus : prod.example.com,*.lab.example)" \
        in one_line_error(r)
    assert len(_edits(bench)) == 1, "pas de rejeu sur un succès annoncé"
    assert not (bench.home / ".ssh").exists(), "ssh-config non régénéré"


def test_hosts_relecture_impossible(bench):
    _unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example", env={"FAKE_BW_FAIL": "edit=error,sync=errorsecond"})
    assert r.returncode == 4
    assert "état inconnu" in one_line_error(r)
    assert len(_edits(bench)) == 1


@pytest.mark.parametrize("args", [["hosts", "add", "--id", ID_PROD, "x.example"], ["hosts", "list", "--id", ID_PROD],
                                  ["ssh-config"], ["ssh-config", "--check"]])
def test_hosts_et_ssh_config_verrouille(bench, args):
    bench.set_state(logged_in=True)
    r = bench.run("--nointeraction", *args)
    assert r.returncode == 3
    assert "verrouillé" in one_line_error(r)
    assert not (bench.home / ".ssh").exists()


def test_hosts_non_connecte(bench):
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example")
    assert r.returncode == 3 and "sshvault login" in one_line_error(r)


def test_hosts_coffre_verrouille_invite(bench):
    bench.set_state(logged_in=True)
    r, tty = bench.run_tty("hosts", "add", "--id", ID_PERSO, "perso.example", answer=PASSWORD)
    assert r.returncode == 0, (r.stderr, tty)
    assert _hosts_field(bench.vault_item(ID_PERSO))[0]["value"] == "perso.example"


# --- hosts : revue (sync, prérequis, succès partiel, interruption, --restrict, sélection) -----

def test_hosts_sync_avant_lecture(bench):
    _unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example")
    assert r.returncode == 0, r.stderr
    argv = [c["argv"][1:] for c in bench.calls()]
    assert argv[:2] == [["sync"], ["list", "items"]]
    r = bench.run("hosts", "list", "--id", ID_PROD)
    assert [c["argv"][1:] for c in bench.calls()][-1] == ["list", "items"], "list : cache local, sans sync"


def test_hosts_prerequis_verifies_avant_ecriture(bench, tmp_path):
    _unlocked(bench)
    d = tmp_path / "pas-tmpfs"
    d.mkdir(mode=0o700)
    before = bench.vault_item(ID_PROD)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example", env={"XDG_RUNTIME_DIR": str(d)})
    assert r.returncode == 4 and "XDG_RUNTIME_DIR" in one_line_error(r)
    assert not _edits(bench) and bench.vault_item(ID_PROD) == before


def test_hosts_chemin_inutilisable_verifie_avant_ecriture(bench, tmp_path):
    _unlocked(bench)
    home = tmp_path / 'gui"llemet'
    home.mkdir()
    before = bench.vault_item(ID_PROD)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example", env={"SSHVAULT_SSH_HOME": str(home)})
    assert r.returncode == 4 and "inutilisable dans un ssh_config" in one_line_error(r)
    assert not _edits(bench) and bench.vault_item(ID_PROD) == before
    assert not (home / ".ssh").exists()


def test_hosts_ecrits_mais_ssh_config_non_regenere(bench):
    """Échec après l'écriture (~/.ssh/sshvault est un fichier) : code 4, message, élément écrit."""
    _unlocked(bench)
    ssh = bench.home / ".ssh"
    ssh.mkdir(mode=0o700)
    (ssh / "sshvault").write_text("pas un dossier")
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example")
    assert r.returncode == 4
    assert "hôtes écrits dans le coffre, mais ssh_config non régénéré" in r.stderr
    assert "hôtes de « Serveur Prod » : prod.example.com,*.lab.example,x.example" in r.stdout
    assert _hosts_field(bench.vault_item(ID_PROD))[0]["value"].endswith(",x.example")
    assert (ssh / "sshvault").read_text() == "pas un dossier"


def test_hosts_sigterm_pendant_edit(bench):
    import signal
    import subprocess
    import sys
    _unlocked(bench)
    e = dict(bench.env, FAKE_BW_FAIL="edit=hang", SSHVAULT_BW_TIMEOUT="60")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "hosts", "add", "--id", ID_PROD, "x.example"], env=e,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    deadline = time.monotonic() + 20
    while not (bench.pids.exists() and len(bench.pids.read_text().split()) == 2) and time.monotonic() < deadline:
        time.sleep(0.1)
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=20)
    assert p.returncode == 130
    assert err.splitlines() == [
        "sshvault: interrompu",
        "sshvault: hôtes de « Serveur Prod » : écriture peut-être passée : vérifier par « sshvault sync » puis "
        "« sshvault hosts list --id %s »" % ID_PROD]
    assert _gone([int(x) for x in bench.pids.read_text().split()])


def test_hosts_avertit_cle_chargee_avec_restrict(bench):
    _unlocked(bench)
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700, exist_ok=True)
    state = {"version": 1, "agent": None, "locked": False, "keys": {bench.keys["prod"]["fingerprint"]: {
        "id": ID_PROD, "name": "Serveur Prod", "hosts": ["prod.example.com"], "loaded": time.time(),
        "lifetime": 0, "confirm": False, "restrict": True}}}
    fd = os.open(str(d / "agent.json"), os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(fd, json.dumps(state).encode())
    os.close(fd)
    r = bench.run("hosts", "add", "--id", ID_PROD, "x.example")
    assert r.returncode == 0, r.stderr
    assert "chargée avec --restrict" in r.stderr and "sshvault load --force --restrict --id %s" % ID_PROD in r.stderr
    r = bench.run("hosts", "add", "--id", ID_BASTION, "x.example")
    assert "--restrict" not in r.stderr


@pytest.mark.parametrize("args", [["--host", "JUMP"], ["--fingerprint", None]])
def test_hosts_selection_host_et_empreinte(bench, args):
    _unlocked(bench)
    if args[1] is None:
        args = ["--fingerprint", bench.keys["bastion"]["fingerprint"]]
    r = bench.run("hosts", "list", args[0], args[1])
    assert r.returncode == 0 and r.stdout == "Bastion\njump\n"


def test_hosts_list_aucun_element(bench):
    _unlocked(bench)
    r = bench.run("hosts", "list", "--name", "inconnu")
    assert r.returncode == 1 and "aucune clé ne correspond" in one_line_error(r)

"""CLI sur le faux bw : chaque cas de la matrice d'entrées et de cas limites (bw absent, non
connecté, verrouillé avec ou sans invite, session expirée, list, search, bw en erreur ou
bloqué, lock), plus les cas annexes."""
import json
import os
import stat
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


def test_bw_absent_sshvault_bw(bench):
    r = bench.run("status", env={"SSHVAULT_BW": "/nonexistent/bw"})
    assert r.returncode == 4
    assert "bw introuvable" in one_line_error(r)


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
    assert set(prod) == {"id", "name", "fingerprint", "hosts", "publicKey"}
    assert prod["hosts"] == ["prod.example.com", "*.Lab.example"]
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
    assert r.returncode == 0 and r.stdout == "key-ttl 1h (défaut)\n"
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

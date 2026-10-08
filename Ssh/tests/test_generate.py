"""`sshvault generate`, `pubkey` et `deploy` (story 7) sur le faux bw, avec le vrai `ssh-keygen`,
et pour `deploy` un sshd de test local (127.0.0.1, utilisateur courant) dont le HOME des sessions
est un dossier de test (`SetEnv HOME=`) : le vrai `~/.ssh` n'est jamais touché.

Une ligne de test par ligne de la matrice de la story, plus : argv surveillé (aucune clé ni
JSON en argument), aucune copie restante, orphelin récupéré, ordre des vérifications."""
import base64
import getpass
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import uuid

import pytest

from bench import HAVE_OPENSSH, ID_BASTION, ID_PERSO, ID_PROD, PASSWORD, ArgvWatch, b64_fragments, ssh_item, wait_gone
from test_import import DEFAULT_IDS, KEYGEN, creates, hosts_field, new_items, one_error, private_key_files

SSH = shutil.which("ssh")
SSHD = "/usr/sbin/sshd"
HAVE_LAB = bool(SSH and os.access(SSHD, os.X_OK))


def _unlocked(bench):
    bench.unlocked("keyring" if bench.ring else "file")


def leftovers(bench):
    """Dossiers de génération (ou d'import) restants dans le tmpfs privé."""
    d = bench.runtime / "sshvault"
    return sorted(p.name for p in d.iterdir() if p.name.startswith(("generate.", "import."))) if d.exists() else []


def keygen_wrapper(tmp_path, before=""):
    """Enveloppe de ssh-keygen : journalise chaque argument entre crochets, puis lance le vrai.
    `before` : commandes shell lancées avant (pid, attente…)."""
    log = tmp_path / "keygen.log"
    w = tmp_path / "kgbin" / "ssh-keygen"
    w.parent.mkdir(exist_ok=True)
    w.write_text("#!/bin/sh\nfor a in \"$@\"; do printf '[%%s]' \"$a\"; done >> '%s'\necho >> '%s'\n%s\n"
                 "exec '%s' \"$@\"\n" % (log, log, before, KEYGEN))
    w.chmod(0o755)
    return w, log


def keygen_calls(log):
    return log.read_text().splitlines() if log.exists() else []


def fingerprint_of(public_line):
    r = subprocess.run([KEYGEN, "-l", "-E", "sha256", "-f", "/dev/stdin"], input=public_line + "\n",
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()[1]


def public_of(private_text):
    r = subprocess.run([KEYGEN, "-y", "-f", "/dev/stdin"], input=private_text, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def no_key_outside_fixtures(bench, *allowed):
    found = private_key_files([bench.tmp, bench.runtime], [bench.vault_file.parent, bench.appdata, *allowed])
    assert not found, "fichiers de clé privée hors des fixtures : %s" % found


def gen(bench, *args, env=None, timeout=120):
    return bench.run("generate", *args, env=env, timeout=timeout)


def check_generated(bench, r, name, key_type="ssh-ed25519", bits=None, comment=None):
    """Élément créé et cohérent avec la seule ligne de stdout ; renvoie l'élément."""
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert len(lines) == 1 and r.stdout.endswith("\n"), "stdout = une seule ligne : %r" % r.stdout
    public = lines[0]
    [item] = new_items(bench)
    assert item["type"] == 5 and item["name"] == name
    key = item["sshKey"]
    assert set(key) == {"privateKey", "publicKey", "keyFingerprint"} and all(key.values()), "trois champs remplis"
    assert key["publicKey"] == public
    parts = public.split(None, 2)
    assert parts[0] == key_type
    assert parts[2] == (name if comment is None else comment)
    # empreinte = ssh-keygen -l de la clé publique affichée ; ssh-keygen -y de la privée = publique
    assert key["keyFingerprint"] == fingerprint_of(public)
    assert public_of(key["privateKey"]).split()[:2] == parts[:2]
    from sshvault.agent import is_encrypted
    assert key["privateKey"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert not is_encrypted(key["privateKey"].encode()), "sans passphrase"
    if bits:
        r2 = subprocess.run([KEYGEN, "-l", "-f", "/dev/stdin"], input=public + "\n", capture_output=True, text=True)
        assert r2.stdout.split()[0] == str(bits)
    assert "PRIVATE KEY" not in r.stderr and "PRIVATE KEY" not in r.stdout
    assert not leftovers(bench), "dossier de génération supprimé"
    return item


# --- generate : matrice ------------------------------------------------------------------------------

def test_generate_ed25519_par_defaut(bench, tmp_path):
    _unlocked(bench)
    w, log = keygen_wrapper(tmp_path)
    r = gen(bench, "--name", "web", env={"SSHVAULT_SSH_KEYGEN": str(w)})
    item = check_generated(bench, r, "web")
    assert not hosts_field(item)
    # sync (nom déjà pris : état du serveur), liste, création sur stdin, relecture
    assert [c["argv"] for c in bench.calls()] == [["--nointeraction", "sync"], ["--nointeraction", "list", "items"],
                                                  ["--nointeraction", "create", "item"],
                                                  ["--nointeraction", "get", "item", item["id"]]]
    [call] = keygen_calls(log)
    work = str(bench.runtime / "sshvault" / "generate.")
    assert call.startswith("[-t][ed25519][-q][-N][][-C][web][-f][%s" % work) and call.endswith("/key]"), call
    assert "clé Ed25519 générée dans le coffre : « web » %s (id %s)" % (item["sshKey"]["keyFingerprint"],
                                                                        item["id"]) in r.stderr
    assert not (bench.home / ".ssh").exists(), "sans hôte : rien écrit dans ~/.ssh"
    no_key_outside_fixtures(bench)


def test_generate_avec_hotes(bench):
    _unlocked(bench)
    r = gen(bench, "--name", "web", "--hosts", "Web.Example,b.example")
    item = check_generated(bench, r, "web")
    assert hosts_field(item) == ["web.example,b.example"]
    cfg = (bench.home / ".ssh" / "sshvault" / "config").read_text()
    assert "Match originalhost web.example,b.example\n" in cfg
    from sshvault.sshconfig import fp_filename
    pub = bench.home / ".ssh" / "sshvault" / "pub" / fp_filename(item["sshKey"]["keyFingerprint"])
    assert pub.read_text().split() == item["sshKey"]["publicKey"].split()[:2]
    assert "écrit" in r.stderr, "compte rendu de la régénération sur stderr, pas stdout"


@pytest.mark.parametrize("how", ["chemin", "runtime"])
def test_generate_prerequis_verifies_avant_ecriture(bench, tmp_path, how):
    """Prérequis de la régénération KO : code 4, rien généré ni créé (`chemin` : HOME inutilisable
    dans un ssh_config, vu par sshconfig.build après la lecture du coffre)."""
    _unlocked(bench)
    w, log = keygen_wrapper(tmp_path)
    env = {"SSHVAULT_SSH_KEYGEN": str(w)}
    if how == "chemin":
        home = tmp_path / 'gui"llemet'
        home.mkdir()
        env["SSHVAULT_SSH_HOME"] = str(home)
    else:
        d = tmp_path / "pas-tmpfs"
        d.mkdir(mode=0o700)
        env["XDG_RUNTIME_DIR"] = str(d)
    r = gen(bench, "--name", "web", "--hosts", "web.example", env=env)
    assert r.returncode == 4, r.stderr
    one_error(r)
    assert not r.stdout
    assert not keygen_calls(log), "rien généré"
    assert not bench.calls(), "prérequis vérifiés avant tout accès au coffre"
    assert not new_items(bench)


def test_generate_cree_mais_ssh_config_non_regenere(bench):
    _unlocked(bench)
    ssh = bench.home / ".ssh"
    ssh.mkdir(mode=0o700)
    (ssh / "sshvault").write_text("pas un dossier")
    r = gen(bench, "--name", "web", "--hosts", "web.example")
    assert r.returncode == 4
    [item] = new_items(bench)
    assert r.stdout == item["sshKey"]["publicKey"] + "\n", "clé créée : sa clé publique est affichée"
    assert "clé créée dans le coffre, mais ssh_config non régénéré" in r.stderr


@pytest.mark.parametrize("args, bits", [(["--type", "rsa", "--bits", "3072"], 3072), (["--type", "RSA"], 4096),
                                        (["--type", "rsa", "--bits", "4096"], 4096)])
def test_generate_rsa(bench, args, bits):
    _unlocked(bench)
    r = gen(bench, "--name", "rsa-web", *args)
    check_generated(bench, r, "rsa-web", "ssh-rsa", bits)
    assert "clé RSA %d générée" % bits in r.stderr


@pytest.mark.parametrize("args, words", [
    (["--type", "rsa", "--bits", "1024"], "1024 bits refusée"),
    (["--type", "rsa", "--bits", "2048"], "2048 bits refusée"),
    (["--type", "ecdsa"], "ECDSA"),
    (["--type", "dsa"], "refusé"),
    (["--type", "ed25519-sk"], "refusé"),
    (["--bits", "4096"], "--bits ne vaut que pour --type rsa"),
    (["--type", "rsa", "--bits", "x"], "--bits invalide"),
    (["--comment", "a\tb"], "imprimables"),
    (["--comment", "x" * 256], "trop long"),
    (["--hosts", "a b"], "hôte invalide"),
    (["--type", ""], "refusé"),
])
def test_generate_refus_avant_toute_generation(bench, tmp_path, args, words):
    _unlocked(bench)
    w, log = keygen_wrapper(tmp_path)
    r = gen(bench, "--name", "web", *args, env={"SSHVAULT_SSH_KEYGEN": str(w)})
    assert r.returncode == 2, r.stderr
    assert words in one_error(r)
    assert not r.stdout and not bench.calls() and not keygen_calls(log)


@pytest.mark.parametrize("args, words", [([], "--name"), (["--name", "  "], "--name vide"),
                                         (["--name", "a\x1bb"], "imprimables"),
                                         (["--name", "n" * 300], "préciser --comment")])
def test_generate_nom_usage(bench, args, words):
    _unlocked(bench)
    r = gen(bench, *args)
    assert r.returncode == 2 and words in one_error(r)
    assert not bench.calls()


def test_generate_commentaire_donne(bench):
    _unlocked(bench)
    r = gen(bench, "--name", "web", "--comment", "alice@poste 2026")
    check_generated(bench, r, "web", comment="alice@poste 2026")


def test_generate_nom_non_ascii(bench):
    """Nom (donc commentaire) non ASCII : la .pub générée est en UTF-8 (trouvé par l'intégration)."""
    _unlocked(bench)
    r = gen(bench, "--name", "clé générée « été »")
    check_generated(bench, r, "clé générée « été »")


def test_generate_nom_long_avec_commentaire(bench):
    _unlocked(bench)
    r = gen(bench, "--name", "n" * 300, "--comment", "court")
    check_generated(bench, r, "n" * 300, comment="court")


def test_generate_commentaire_vide(bench):
    _unlocked(bench)
    r = gen(bench, "--name", "web", "--comment", "")
    assert r.returncode == 0, r.stderr
    [item] = new_items(bench)
    assert len(r.stdout.split()) == 2 and item["sshKey"]["publicKey"] == r.stdout.strip()


def test_generate_nom_deja_pris_puis_force(bench, tmp_path):
    _unlocked(bench)
    w, log = keygen_wrapper(tmp_path)
    env = {"SSHVAULT_SSH_KEYGEN": str(w)}
    r = gen(bench, "--name", "  SERVEUR prod ", env=env)  # « Serveur Prod » existe (casse et blancs ignorés)
    assert r.returncode == 1
    line = one_error(r)
    assert "déjà pris" in line and "« Serveur Prod » %s" % ID_PROD in line and "--force" in line
    assert not r.stdout and not creates(bench) and not new_items(bench)
    assert not keygen_calls(log), "rien généré avant le contrôle du nom"
    r = gen(bench, "--name", "Serveur Prod", "--force", env=env)
    check_generated(bench, r, "Serveur Prod")
    assert "déjà pris" not in r.stderr


# --- bw create en échec ou bloqué -------------------------------------------------------------------------

def test_generate_create_bloque_sans_ecriture_rejoue(bench):
    _unlocked(bench)
    r = gen(bench, "--name", "web", env={"FAKE_BW_FAIL": "create=hangonce", "SSHVAULT_BW_TIMEOUT": "2"})
    check_generated(bench, r, "web")
    argv = [c["argv"][1:] for c in bench.calls()]
    i = argv.index(["create", "item"])
    assert argv[i + 1:i + 4] == [["sync"], ["list", "items"], ["create", "item"]], "sync et recherche avant le rejeu"
    assert len(creates(bench)) == 2
    assert wait_gone([int(x) for x in bench.pids.read_text().split()], timeout=10), "bw bloqué tué"


@pytest.mark.parametrize("mode", ["hangafter", "errorafter", "badjsonafter"])
def test_generate_create_passe_puis_echec_pas_de_doublon(bench, mode):
    _unlocked(bench)
    r = gen(bench, "--name", "web", "--hosts", "x.example",
            env={"FAKE_BW_FAIL": "create=" + mode, "SSHVAULT_BW_TIMEOUT": "2"})
    item = check_generated(bench, r, "web")
    assert len(creates(bench)) == 1, "trouvé par empreinte : rien rejoué"
    assert hosts_field(item) == ["x.example"]


@pytest.mark.parametrize("fail, words", [("create=error", "deux fois"), ("create=corrupt", "relu diffère"),
                                         ("create=silent", "relecture impossible")])
def test_generate_create_en_echec(bench, fail, words):
    _unlocked(bench)
    r = gen(bench, "--name", "web", env={"FAKE_BW_FAIL": fail})
    assert r.returncode == 4
    line = one_error(r)
    assert words in line and "jamais été écrite sur disque" in line and "perdue" in line, line
    assert not r.stdout, "pas de clé publique sans élément vérifié"
    assert "PRIVATE KEY" not in r.stderr
    assert not leftovers(bench)
    if fail == "create=error":
        assert len(creates(bench)) == 2 and not new_items(bench)
    no_key_outside_fixtures(bench)


# --- interruption -------------------------------------------------------------------------------------------

def _wait_for(pred, timeout=30):
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "attente dépassée"
        time.sleep(0.05)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_generate_interrompu_pendant_la_generation(bench, tmp_path, sig):
    _unlocked(bench)
    pidfile = tmp_path / "kg.pid"
    w, log = keygen_wrapper(tmp_path, before="echo $$ > '%s'\nsleep 30" % pidfile)
    e = dict(bench.env, SSHVAULT_SSH_KEYGEN=str(w))
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "generate", "--name", "web"], env=e,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    _wait_for(lambda: pidfile.exists() and pidfile.read_text().strip())
    assert [n for n in leftovers(bench) if n.startswith("generate.")], "dossier de génération créé"
    p.send_signal(sig)
    out, err = p.communicate(timeout=30)
    assert p.returncode == 130, err
    assert err.splitlines() == ["sshvault: interrompu"]
    assert not out and not leftovers(bench), "dossier supprimé malgré le signal"
    assert wait_gone([int(pidfile.read_text())], timeout=10), "ssh-keygen tué"
    assert not creates(bench)


def test_generate_sigterm_pendant_create(bench):
    _unlocked(bench)
    e = dict(bench.env, FAKE_BW_FAIL="create=hang", SSHVAULT_BW_TIMEOUT="60")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "generate", "--name", "web"], env=e,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    _wait_for(lambda: bench.pids.exists() and len(bench.pids.read_text().split()) == 2)
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=30)
    assert p.returncode == 130
    lines = err.splitlines()
    assert lines[0] == "sshvault: interrompu"
    assert len(lines) == 2 and lines[1].startswith("sshvault: « web » : création peut-être passée : vérifier par "
                                                   "« sshvault sync » puis « sshvault search --fingerprint SHA256:")
    assert not out and not leftovers(bench)
    assert wait_gone([int(x) for x in bench.pids.read_text().split()], timeout=10)


def test_generate_orphelin_recupere(bench):
    """Dossier d'une génération tuée (SIGKILL) : supprimé à la génération suivante."""
    _unlocked(bench)
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700, exist_ok=True)
    dead = subprocess.Popen(["true"])
    dead.wait()
    orphan = d / ("generate.%d.abc" % dead.pid)
    orphan.mkdir(mode=0o700)
    (orphan / ".lock").write_text("")
    (orphan / "key").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
    r = gen(bench, "--name", "web")
    check_generated(bench, r, "web")
    assert not orphan.exists()


# --- coffre, tmpfs ------------------------------------------------------------------------------------------

def test_generate_coffre_verrouille_sans_invite(bench, tmp_path):
    bench.set_state(logged_in=True)
    w, log = keygen_wrapper(tmp_path)
    r = bench.run("--nointeraction", "generate", "--name", "web", env={"SSHVAULT_SSH_KEYGEN": str(w)})
    assert r.returncode == 3 and "verrouillé" in one_error(r)
    assert not keygen_calls(log) and not creates(bench) and not r.stdout


def test_generate_coffre_verrouille_invite(bench):
    bench.set_state(logged_in=True)
    r, tty = bench.run_tty("generate", "--name", "web", answer=PASSWORD)
    assert r.returncode == 0, (r.stderr, tty)
    check_generated(bench, subprocess.CompletedProcess([], 0, r.stdout, r.stderr), "web")


def test_generate_non_connecte(bench, tmp_path):
    w, log = keygen_wrapper(tmp_path)
    r = gen(bench, "--name", "web", env={"SSHVAULT_SSH_KEYGEN": str(w)})
    assert r.returncode == 3 and "sshvault login" in one_error(r)
    assert not keygen_calls(log)


@pytest.mark.parametrize("how", ["pas-tmpfs", "ouvert", "relatif"])
def test_generate_tmpfs_indisponible(bench, tmp_path, how):
    """XDG_RUNTIME_DIR inutilisable : refus clair, code 4, avant le coffre et la génération."""
    _unlocked(bench)
    w, log = keygen_wrapper(tmp_path)
    if how == "pas-tmpfs":
        d = tmp_path / "pas-tmpfs"
        d.mkdir(mode=0o700)
        rt = str(d)
    elif how == "ouvert":
        d = bench.runtime / "ouvert"
        d.mkdir(mode=0o755)
        d.chmod(0o755)
        rt = str(d)
    else:
        rt = "relatif/run"
    r = gen(bench, "--name", "web", env={"XDG_RUNTIME_DIR": rt, "SSHVAULT_SSH_KEYGEN": str(w)})
    assert r.returncode == 4
    line = one_error(r)
    assert "XDG_RUNTIME_DIR" in line and "rien généré" in line, line
    assert not bench.calls() and not keygen_calls(log) and not r.stdout
    if how == "pas-tmpfs":
        assert not list(d.iterdir()), "rien écrit hors tmpfs"


def test_check_workspace_xdg_absent(monkeypatch, tmp_path):
    """XDG_RUNTIME_DIR absent et repli /run/user/<uid> inutilisable : refus (code 4)."""
    from sshvault import keyfile, runtime
    monkeypatch.setattr(keyfile, "resolve_dir",
                        lambda env=None: runtime.resolve_dir(env, run_user=str(tmp_path / "nulle-part")))
    from sshvault.runtime import AgentError
    with pytest.raises(AgentError, match="XDG_RUNTIME_DIR absent.*rien généré"):
        keyfile.check_workspace({})
    with pytest.raises(AgentError, match="XDG_RUNTIME_DIR absent"):
        keyfile.generate("ed25519", None, "x", env={})


def test_generate_ssh_keygen_introuvable(bench):
    _unlocked(bench)
    r = gen(bench, "--name", "web", env={"SSHVAULT_SSH_KEYGEN": "/nonexistent/kg"})
    assert r.returncode == 4 and "introuvable" in one_error(r)
    assert not creates(bench) and not leftovers(bench)


def test_generate_ssh_keygen_en_erreur(bench, tmp_path):
    _unlocked(bench)
    bad = tmp_path / "kg-faux"
    bad.write_text("#!/bin/sh\necho 'boom' >&2\nexit 1\n")
    bad.chmod(0o755)
    r = gen(bench, "--name", "web", env={"SSHVAULT_SSH_KEYGEN": str(bad)})
    assert r.returncode == 4 and "boom" in one_error(r)
    assert not creates(bench) and not leftovers(bench)


def test_generate_champ_de_test_et_attrape_tout(bench):
    from sshvault.sshconfig import CATCH_ALL_WARNING
    _unlocked(bench)
    r = gen(bench, "--name", "web", "--hosts", "*", env={"SSHVAULT_TEST_FIELD": "sshvault-test-run=abc"})
    item = check_generated(bench, r, "web")
    assert [(f["name"], f["value"]) for f in item["fields"]] == [("sshvault-hosts", "*"), ("sshvault-test-run", "abc")]
    assert r.stderr.count(CATCH_ALL_WARNING) == 1, "une seule fois"
    assert r.stderr.index(CATCH_ALL_WARNING) < r.stderr.index("générée dans le coffre"), "avant l'écriture"


def test_generate_attrape_tout_tu_si_nom_pris(bench):
    """Avertissement attrape-tout : après le contrôle du nom (nom pris : rien dit)."""
    from sshvault.sshconfig import CATCH_ALL_WARNING
    _unlocked(bench)
    r = gen(bench, "--name", "Serveur Prod", "--hosts", "*")
    assert r.returncode == 1 and CATCH_ALL_WARNING not in r.stderr


# --- rien en argument : ni clé ni JSON ----------------------------------------------------------------------

def test_generate_argv_sans_cle_ni_json(bench, tmp_path):
    """Toutes les lignes de commande relevées pendant la génération (/proc/<pid>/cmdline), le
    journal de bw et l'enveloppe de ssh-keygen : rien de la clé privée générée (contrôle après
    coup, la clé n'est connue qu'à la fin) ; `-N ""` est le seul « secret » en argument."""
    _unlocked(bench)
    w, log = keygen_wrapper(tmp_path)
    with ArgvWatch(uuid.uuid4().hex, [], heuristics=False, keep_all=True) as watch:
        r = gen(bench, "--name", "web", "--type", "rsa", "--bits", "3072", env={"SSHVAULT_SSH_KEYGEN": str(w)})
    item = check_generated(bench, r, "web", "ssh-rsa", 3072)
    private = item["sshKey"]["privateKey"]
    body = "".join(private.splitlines()[1:-1])
    secrets = [body[:40], body[-40:], body[200:240], body[1000:1040]] + b64_fragments(private)
    assert watch.all, "surveillance effective"
    assert any("generate" in a for argv in watch.all for a in argv), "sshvault vu par la surveillance"
    for argv in watch.all:
        for a in argv:
            assert "PRIVATE KEY" not in a and not any(s in a for s in secrets), argv[:4]
    [call] = keygen_calls(log)
    assert call.startswith("[-t][rsa][-b][3072][-q][-N][][-C][web][-f][")
    assert not any(s in call for s in secrets)
    for c in bench.calls():
        for a in c["argv"]:
            assert "{" not in a and "PRIVATE" not in a and len(a) < 80 and not any(s in a for s in secrets), c["argv"]
    assert [c["argv"] for c in creates(bench)] == [["--nointeraction", "create", "item"]]


# --- pubkey ----------------------------------------------------------------------------------------------------

def test_pubkey_selection_une_ligne_par_cle_sans_reseau(bench):
    _unlocked(bench)
    r = bench.run("pubkey", "--host", "*")
    assert r.returncode == 0, r.stderr
    keys = bench.keys
    # éléments triés par nom : « Bastion RSA », « Serveur Prod » (hôtes) ; « clé perso » n'a pas d'hôte
    assert r.stdout.splitlines() == [keys["bastion"]["public"], keys["prod"]["public"]]
    assert not r.stderr
    assert [c["argv"][1:] for c in bench.calls()] == [["list", "items"]], "cache local seulement, aucun sync"


def test_pubkey_id_et_all(bench):
    _unlocked(bench)
    r = bench.run("pubkey", "--id", ID_PERSO)
    assert r.returncode == 0 and r.stdout == bench.keys["perso"]["public"] + "\n"
    r = bench.run("pubkey", "--all")
    assert r.returncode == 0
    assert sorted(r.stdout.splitlines()) == sorted(bench.keys[k]["public"] for k in ("prod", "perso", "bastion"))


def test_pubkey_aucune(bench):
    _unlocked(bench)
    r = bench.run("pubkey", "inexistante")
    assert r.returncode == 1 and "aucune clé ne correspond" in one_error(r) and not r.stdout


@pytest.mark.parametrize("args", [[], ["--all", "x"], ["--id"], [" "]])
def test_pubkey_usage(bench, args):
    _unlocked(bench)
    r = bench.run("pubkey", *args)
    assert r.returncode == 2
    assert not bench.calls()


def test_pubkey_doublon_illisible_et_commentaire_nettoye(bench):
    """Deux éléments d'une même clé : une ligne ; clé publique illisible : message, code 4, les
    autres affichées ; commentaire avec caractère de contrôle : retiré de la ligne."""
    _unlocked(bench)
    k = dict(bench.keys["prod"])
    bench.items = [ssh_item(ID_PROD, "a prod", k), ssh_item(ID_PERSO, "b copie", k),
                   ssh_item(ID_BASTION, "c abimee", dict(k, public="ssh-ed25519 pas-du-base64 x"))]
    bad_comment = dict(bench.keys["perso"], public=bench.keys["perso"]["public"].split()[0] + " "
                       + bench.keys["perso"]["public"].split()[1] + " a\x1b[31mb")
    bench.items.append(ssh_item("66666666-6666-4666-8666-666666666666", "d esc", bad_comment))
    bench.write_vault()
    r = bench.run("pubkey", "--all")
    assert r.returncode == 4
    assert r.stdout.splitlines() == [k["public"], " ".join(bench.keys["perso"]["public"].split()[:2])]
    assert "« c abimee » (%s) : clé publique de l'élément illisible" % ID_BASTION in one_error(r)


# --- deploy : banc sshd ------------------------------------------------------------------------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Target:
    """sshd de test sur 127.0.0.1 (utilisateur courant) : authentification par une clé
    d'administration (`admin`) ; HOME des sessions = `rhome` (SetEnv), dont
    `.ssh/authorized_keys` est aussi lu par sshd : une clé déployée permet ensuite la connexion."""

    def __init__(self, d):
        self.dir, self.user, self.proc = d, getpass.getuser(), None
        self.rhome = d / "rhome"
        subprocess.run([KEYGEN, "-q", "-t", "ed25519", "-N", "", "-f", str(d / "hostkey")], check=True,
                       stdin=subprocess.DEVNULL)
        subprocess.run([KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", "admin", "-f", str(d / "admin")], check=True,
                       stdin=subprocess.DEVNULL)
        shutil.copy(str(d / "admin.pub"), str(d / "admin_keys"))
        self.port = _free_port()
        (d / "sshd_config").write_text(
            "Port %d\nListenAddress 127.0.0.1\nHostKey %s\nPidFile %s\nAuthorizedKeysFile %s %s\nStrictModes no\n"
            "UsePAM no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nPrintMotd no\n"
            "SetEnv HOME=%s\nLogLevel VERBOSE\n"
            % (self.port, d / "hostkey", d / "sshd.pid", d / "admin_keys", self.rhome / ".ssh" / "authorized_keys",
               self.rhome))
        hostkey = " ".join((d / "hostkey.pub").read_text().split()[:2])
        (d / "known_hosts").write_text("[127.0.0.1]:%d %s\n" % (self.port, hostkey))
        self.config = d / "ssh_config"
        common = ("    User %s\n    UserKnownHostsFile %s\n    GlobalKnownHostsFile /dev/null\n"
                  "    StrictHostKeyChecking yes\n    BatchMode yes\n    ConnectTimeout 10\n"
                  % (self.user, d / "known_hosts"))
        self.config.write_text("Host target\n    HostName 127.0.0.1\n    Port %d\n"
                               "Host *\n    IdentityFile %s\n    IdentitiesOnly yes\n    IdentityAgent none\n%s"
                               % (self.port, d / "admin", common))
        self.config.chmod(0o600)
        self.common = common
        self.log = d / "sshd.log"
        with open(str(self.log), "ab") as log:
            self.proc = subprocess.Popen([SSHD, "-D", "-e", "-f", str(d / "sshd_config")], stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
        deadline = time.monotonic() + 10
        while True:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    break
            assert time.monotonic() < deadline, "sshd de test muet : %s" % self.log.read_text()
            time.sleep(0.1)

    def reset(self):
        shutil.rmtree(str(self.rhome), ignore_errors=True)
        self.rhome.mkdir(mode=0o700)
        self.rhome.chmod(0o700)

    @property
    def authorized(self):
        return self.rhome / ".ssh" / "authorized_keys"

    def stop(self):
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(10)
        assert wait_gone([self.proc.pid]), "sshd de test encore vivant"


@pytest.fixture(scope="module")
def target(tmp_path_factory):
    if not HAVE_LAB:
        pytest.skip("ssh ou sshd absent")
    t = Target.__new__(Target)
    t.proc = None
    try:
        t.__init__(tmp_path_factory.mktemp("cible"))
    except BaseException:
        t.stop()
        raise
    try:
        yield t
    finally:
        t.stop()


@pytest.fixture
def tgt(target):
    target.reset()
    return target


def ssh_wrapper(tmp_path):
    """Enveloppe de ssh : journalise chaque argument entre crochets (une ligne par appel)."""
    log = tmp_path / "ssh.log"
    w = tmp_path / "sshbin" / "ssh"
    w.parent.mkdir(exist_ok=True)
    w.write_text("#!/bin/sh\nfor a in \"$@\"; do printf '[%%s]' \"$a\"; done >> '%s'\necho >> '%s'\n"
                 "exec '%s' \"$@\"\n" % (log, log, SSH))
    w.chmod(0o755)
    return w, log


def snap(path):
    st = os.stat(str(path))
    return path.read_bytes(), st.st_mtime_ns, stat.S_IMODE(st.st_mode), st.st_ino


def test_deploy_ajoute_une_fois_puis_deja_presente_puis_connexion(bench, tgt, tmp_path):
    _unlocked(bench)
    w, log = ssh_wrapper(tmp_path)
    env = {"SSHVAULT_SSH": str(w)}
    r = bench.run("deploy", "--id", ID_PROD, "%s@target" % tgt.user, "--", "-F", str(tgt.config), env=env)
    assert r.returncode == 0, r.stderr
    fp = bench.keys["prod"]["fingerprint"]
    assert r.stdout == "ajoutée : « Serveur Prod » %s → %s@target\n" % (fp, tgt.user)
    assert tgt.authorized.read_text() == bench.keys["prod"]["public"] + "\n"
    assert stat.S_IMODE(os.stat(str(tgt.rhome / ".ssh")).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(str(tgt.authorized)).st_mode) == 0o600
    from sshvault.deploy import REMOTE_COMMAND
    [call] = log.read_text().splitlines()
    assert call == "[-F][%s][-o][ConnectTimeout=30][--][%s@target][%s]" % (tgt.config, tgt.user, REMOTE_COMMAND), \
        "un seul ssh, argv fixe"
    assert [c["argv"][1:] for c in bench.calls()] == [["list", "items"]], "aucun appel réseau au coffre"
    before = snap(tgt.authorized)
    r = bench.run("deploy", "--id", ID_PROD, "target", "--", "-F", str(tgt.config), env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "déjà présente : « Serveur Prod » %s → target\n" % fp
    assert snap(tgt.authorized) == before, "second deploy : fichier inchangé"
    if HAVE_OPENSSH:
        # connexion avec la clé déployée, chargée dans l'agent dédié
        r = bench.run("--nointeraction", "load", "--id", ID_PROD)
        assert r.returncode == 0, r.stderr
        pub = tmp_path / "prod.pub"
        pub.write_text(bench.keys["prod"]["public"] + "\n")
        cfg = tmp_path / "ssh_config_cle"
        cfg.write_text("Host target\n    HostName 127.0.0.1\n    Port %d\n    IdentityFile %s\n"
                       "    IdentitiesOnly yes\n    IdentityAgent %s\n%s" % (tgt.port, pub, bench.sock(), tgt.common))
        cfg.chmod(0o600)
        c = subprocess.run([SSH, "-F", str(cfg), "target", "true"], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL, env=dict(bench.env))
        assert c.returncode == 0, c.stderr
        assert "Accepted publickey for %s" % tgt.user in tgt.log.read_text() and fp in tgt.log.read_text()


def test_deploy_plusieurs_cles_un_seul_ssh(bench, tgt, tmp_path):
    _unlocked(bench)
    w, log = ssh_wrapper(tmp_path)
    tgt.authorized.parent.mkdir(mode=0o700)
    # déjà présente (avec options), fichier sans fin de ligne, ligne commentée de l'autre clé
    tgt.authorized.write_text('# %s\nfrom="127.0.0.1" %s' % (bench.keys["bastion"]["public"], bench.keys["prod"]["public"]))
    r = bench.run("deploy", "--host", "*", "target", "--", "-F", str(tgt.config), env={"SSHVAULT_SSH": str(w)})
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "ajoutée : « Bastion RSA » %s → target" % bench.keys["bastion"]["fingerprint"],
        "déjà présente (avec options : la connexion peut être restreinte) : « Serveur Prod » %s → target"
        % bench.keys["prod"]["fingerprint"]]
    assert len(log.read_text().splitlines()) == 1, "un seul ssh pour toutes les clés"
    assert tgt.authorized.read_text().splitlines() == [
        "# %s" % bench.keys["bastion"]["public"], 'from="127.0.0.1" %s' % bench.keys["prod"]["public"],
        bench.keys["bastion"]["public"]]


def test_deploy_port(bench, tgt):
    _unlocked(bench)
    r = bench.run("deploy", "--id", ID_PERSO, "127.0.0.1", "-p", str(tgt.port), "--", "-F", str(tgt.config))
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("ajoutée : « clé perso »")
    assert tgt.authorized.read_text() == bench.keys["perso"]["public"] + "\n"


def test_deploy_ssh_en_echec(bench, tgt):
    _unlocked(bench)
    r = bench.run("deploy", "--id", ID_PERSO, "127.0.0.1", "-p", str(_free_port()), "--", "-F", str(tgt.config))
    assert r.returncode == 4
    line = one_error(r)
    assert "ssh vers 127.0.0.1 en échec (code 255)" in line and "refused" in line, line
    assert not r.stdout and not tgt.authorized.exists()


def test_deploy_cible_refuse_l_authentification(bench, tgt, tmp_path):
    _unlocked(bench)
    cfg = tmp_path / "sans_cle"
    # clé d'hôte de la cible comme identité : non autorisée
    cfg.write_text(tgt.config.read_text().replace("IdentityFile %s" % (tgt.dir / "admin"),
                                                  "IdentityFile %s" % (tgt.dir / "hostkey")))
    cfg.chmod(0o600)
    r = bench.run("deploy", "--id", ID_PERSO, "target", "--", "-F", str(cfg))
    assert r.returncode == 4 and "Permission denied" in one_error(r)
    assert not tgt.authorized.exists()


def test_deploy_nointeraction_batchmode(bench, tgt, tmp_path):
    _unlocked(bench)
    w, log = ssh_wrapper(tmp_path)
    r = bench.run("--nointeraction", "deploy", "--id", ID_PERSO, "target", "--", "-F", str(tgt.config),
                  env={"SSHVAULT_SSH": str(w)})
    assert r.returncode == 0, r.stderr
    assert log.read_text().startswith("[-o][BatchMode=yes][-F]")


def test_deploy_aucune_cle(bench, tgt, tmp_path):
    _unlocked(bench)
    w, log = ssh_wrapper(tmp_path)
    r = bench.run("deploy", "inexistante", "target", "--", "-F", str(tgt.config), env={"SSHVAULT_SSH": str(w)})
    assert r.returncode == 1 and "aucune clé ne correspond" in one_error(r)
    assert not log.exists()


@pytest.mark.parametrize("host", ["h;touch {x}", "$(touch {x})", "a b", "-oProxyCommand=touch {x}", "`touch {x}`",
                                  "u;touch {x}@target", "", "h|touch {x}", "h%h"])
def test_deploy_hote_piege_refuse(bench, tmp_path, host):
    _unlocked(bench)
    x = tmp_path / "PIEGE"
    w, log = ssh_wrapper(tmp_path)
    r = bench.run("deploy", "--id", ID_PERSO, host.format(x=x), env={"SSHVAULT_SSH": str(w)})
    assert r.returncode == 2 and "cible invalide" in one_error(r)
    assert not log.exists() and not x.exists() and not bench.calls()


@pytest.mark.parametrize("port", ["0", "65536", "22;x", "-1", "x"])
def test_deploy_port_invalide(bench, port):
    _unlocked(bench)
    r = bench.run("deploy", "--id", ID_PERSO, "h", "-p", port)
    assert r.returncode == 2 and not bench.calls()


@pytest.mark.parametrize("opts", [["autre-hote"], ["-v", "--", "x"], ["-i"], ["-Z"], ["-F", "c", "cmd"]])
def test_deploy_options_ssh_invalides(bench, tmp_path, opts):
    _unlocked(bench)
    w, log = ssh_wrapper(tmp_path)
    r = bench.run("deploy", "--id", ID_PERSO, "h", "--", *opts, env={"SSHVAULT_SSH": str(w)})
    assert r.returncode == 2 and "option ssh" in one_error(r)
    assert not log.exists() and not bench.calls()


def test_deploy_options_piegees_passees_telles_quelles(bench, tgt, tmp_path):
    """Options contenant ;, $(), espaces : passées à ssh en arguments séparés, jamais à un
    shell local ; la commande distante reste la commande fixe."""
    _unlocked(bench)
    x = tmp_path / "PIEGE"
    w, log = ssh_wrapper(tmp_path)
    trap = "SendEnv=PIEGE;touch %s $(touch %s) `touch %s`" % (x, x, x)
    r = bench.run("deploy", "--id", ID_PERSO, "target", "--", "-F", str(tgt.config), "-o", trap,
                  env={"SSHVAULT_SSH": str(w)})
    assert r.returncode == 0, r.stderr
    from sshvault.deploy import REMOTE_COMMAND
    assert log.read_text().splitlines() == ["[-F][%s][-o][%s][-o][ConnectTimeout=30][--][target][%s]"
                                            % (tgt.config, trap, REMOTE_COMMAND)]
    assert not x.exists(), "rien interprété par un shell (ni local, ni distant)"
    assert tgt.authorized.read_text() == bench.keys["perso"]["public"] + "\n"


def test_deploy_commentaire_de_controle_retire(bench, tgt):
    _unlocked(bench)
    k = bench.keys["perso"]
    bench.items = [ssh_item(ID_PERSO, "esc", dict(k, public=" ".join(k["public"].split()[:2]) + " a\nb\x1b[2J"))]
    bench.write_vault()
    r = bench.run("deploy", "--id", ID_PERSO, "target", "--", "-F", str(tgt.config))
    assert r.returncode == 0, r.stderr
    assert tgt.authorized.read_text() == " ".join(k["public"].split()[:2]) + "\n"


def test_deploy_cle_illisible(bench, tgt):
    _unlocked(bench)
    bench.items = [ssh_item(ID_PERSO, "abimee", dict(bench.keys["perso"], public="ssh-ed25519 !!!"))]
    bench.write_vault()
    r = bench.run("deploy", "--id", ID_PERSO, "target", "--", "-F", str(tgt.config))
    assert r.returncode == 4 and "illisible" in r.stderr
    assert not tgt.authorized.exists()


def test_generate_puis_deploy_puis_connexion(bench, tgt, tmp_path):
    """Bout à bout : clé générée dans le coffre, déployée par son id, puis connexion avec elle."""
    if not HAVE_OPENSSH:
        pytest.skip("ssh-agent/ssh-add absents")
    _unlocked(bench)
    r = gen(bench, "--name", "neuve")
    item = check_generated(bench, r, "neuve")
    public = r.stdout.strip()
    r = bench.run("deploy", "--id", item["id"], "target", "--", "-F", str(tgt.config))
    assert r.returncode == 0 and r.stdout.startswith("ajoutée : « neuve »"), r.stderr
    assert tgt.authorized.read_text() == public + "\n"
    r = bench.run("--nointeraction", "load", "--id", item["id"])
    assert r.returncode == 0, r.stderr
    pub = tmp_path / "neuve.pub"
    pub.write_text(public + "\n")
    cfg = tmp_path / "ssh_config_neuve"
    cfg.write_text("Host target\n    HostName 127.0.0.1\n    Port %d\n    IdentityFile %s\n    IdentitiesOnly yes\n"
                   "    IdentityAgent %s\n%s" % (tgt.port, pub, bench.sock(), tgt.common))
    cfg.chmod(0o600)
    c = subprocess.run([SSH, "-F", str(cfg), "target", "true"], capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL, env=dict(bench.env))
    assert c.returncode == 0, c.stderr
    assert item["sshKey"]["keyFingerprint"] in tgt.log.read_text()
    no_key_outside_fixtures(bench, tgt.dir)


# --- unitaires --------------------------------------------------------------------------------------------------

def test_split_ssh_options():
    from sshvault.cli import split_ssh_options
    assert split_ssh_options(["deploy", "s", "h", "--", "-v"]) == (["deploy", "s", "h"], ["-v"])
    assert split_ssh_options(["--nointeraction", "deploy", "s", "h", "--", "--", "x"]) == (
        ["--nointeraction", "deploy", "s", "h"], ["--", "x"])
    assert split_ssh_options(["search", "--", "-x"]) == (["search", "--", "-x"], [])
    assert split_ssh_options(["deploy", "s", "h"]) == (["deploy", "s", "h"], [])


def test_remote_command_fixe():
    from sshvault.deploy import REMOTE_COMMAND, SCRIPT, ssh_argv
    assert REMOTE_COMMAND == "exec sh -c '%s'" % SCRIPT
    assert "'" not in SCRIPT and "\n" not in SCRIPT and "umask 077" in SCRIPT
    assert "!" not in SCRIPT, "csh : historique"
    argv = ssh_argv("u@h", "2222", ["-o", "A=$(x)"], env={"SSHVAULT_SSH": "/x/ssh"})
    assert argv == ["/x/ssh", "-o", "A=$(x)", "-o", "ConnectTimeout=30", "-p", "2222", "--", "u@h", REMOTE_COMMAND]
    # IPv6 : crochets retirés (ssh 8.9 les garde dans le nom à résoudre) ; ConnectTimeout de l'utilisateur gardé
    for opts in (["-o", "ConnectTimeout=7"], ["-oconnecttimeout 7"], ["-o", "ConnectTimeout 7"]):
        argv = ssh_argv("u@[::1]", None, opts, env={"SSHVAULT_SSH": "/x/ssh"})
        assert argv == ["/x/ssh", *opts, "--", "u@::1", REMOTE_COMMAND]


@pytest.mark.parametrize("shell", ["sh", "dash", "bash", "zsh", "fish", "tcsh"])
def test_script_distant_shells(tmp_path, shell):
    """Le script fixe sous plusieurs shells de connexion (ceux absents du poste : ignorés) :
    idempotent, droits, fichier sans fin de ligne, CRLF, lignes commentées ignorées, clé
    présente seulement avec options, verrou libéré, ligne illisible refusée."""
    from sshvault.deploy import REMOTE_COMMAND
    if not shutil.which(shell):
        pytest.skip("%s absent" % shell)
    home = tmp_path / "h"
    home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    k1 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGg1 c1"
    k2 = "ssh-rsa AAAAB3NzaC1yc2E= c2 avec espaces"
    for want in ("added", "present"):
        r = subprocess.run([shell, "-c", REMOTE_COMMAND], input=k1 + "\n" + k2 + "\n", capture_output=True, text=True,
                           env=env)
        assert r.returncode == 0 and r.stdout == ("sshvault-deploy %s\n" % want) * 2, r.stderr
    f = home / ".ssh" / "authorized_keys"
    assert f.read_text() == k1 + "\n" + k2 + "\n"
    assert stat.S_IMODE(os.stat(str(home / ".ssh")).st_mode) == 0o700 and stat.S_IMODE(os.stat(str(f)).st_mode) == 0o600
    f.write_text("# " + k2 + "\n" + k1)  # commentée, sans fin de ligne
    r = subprocess.run([shell, "-c", REMOTE_COMMAND], input=k1 + "\n" + k2 + "\n", capture_output=True, text=True,
                       env=env)
    assert r.stdout == "sshvault-deploy present\nsshvault-deploy added\n"
    assert f.read_text() == "# " + k2 + "\n" + k1 + "\n" + k2 + "\n"
    # CRLF : reconnue ; avec options seulement : « present-options » ; avec options et nue : « present »
    # CRLF : blob en fin de ligne, sans commentaire (le « \r » colle au blob)
    f.write_text(" ".join(k1.split()[:2]) + "\r\n" + 'restrict,command="true" ' + k2 + "\r\n")
    before = f.read_bytes()
    r = subprocess.run([shell, "-c", REMOTE_COMMAND], input=k1 + "\n" + k2 + "\n", capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0 and r.stdout == "sshvault-deploy present\nsshvault-deploy present-options\n", r.stderr
    assert f.read_bytes() == before
    f.write_text('from="x" ' + k1 + "\n" + k1 + "\n")
    r = subprocess.run([shell, "-c", REMOTE_COMMAND], input=k1 + "\n", capture_output=True, text=True, env=env)
    assert r.stdout == "sshvault-deploy present\n"
    assert not (home / ".ssh" / ".sshvault-deploy.lock").exists(), "verrou libéré"
    r = subprocess.run([shell, "-c", REMOTE_COMMAND], input="pas une clé\n", capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "illisible" in r.stderr
    assert not (home / ".ssh" / ".sshvault-deploy.lock").exists(), "verrou libéré en erreur"


@pytest.mark.parametrize("target, ok", [("h", True), ("u@h.example", True), ("[::1]", True), ("::1", True),
                                        ("10.0.0.1", True), ("first.last@h", True), ("-x", False), ("u@-x", False),
                                        ("u@@h", False), ("h:22", False), ("é.example", False), ("cafe:22", False),
                                        ("[cafe:22]", False), ("u@[::1]", True), ("fe80::1", True), ("[h]", False)])
def test_check_target(target, ok):
    from sshvault.deploy import BadTarget, check_target
    if ok:
        check_target(target)
    else:
        with pytest.raises(BadTarget):
            check_target(target)


@pytest.mark.parametrize("comment", ["a\nb", "a\x00b", "x" * 256])
def test_keyfile_generate_refuse_commentaire(runtime_dir, comment):
    """Contrôle propre à keyfile.generate (la CLI vérifie aussi avant) : refus avant tout dossier."""
    from sshvault import keyfile
    with pytest.raises(keyfile.KeyRefused):
        keyfile.generate("ed25519", None, comment, env={"XDG_RUNTIME_DIR": str(runtime_dir)})
    assert not (runtime_dir / "sshvault").exists()



def test_script_distant_verrou_tenu(tmp_path):
    """Verrou d'un autre deploy en cours : attente (10 essais d'une seconde), puis refus, fichier
    intact ; le verrou d'autrui n'est pas supprimé."""
    from sshvault.deploy import REMOTE_COMMAND
    home = tmp_path / "h"
    (home / ".ssh" / ".sshvault-deploy.lock").mkdir(parents=True)
    r = subprocess.run(["sh", "-c", REMOTE_COMMAND], input="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGg1\n",
                       capture_output=True, text=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, timeout=60)
    assert r.returncode == 1 and "verrou" in r.stderr and not r.stdout
    assert (home / ".ssh" / ".sshvault-deploy.lock").is_dir()
    assert not (home / ".ssh" / "authorized_keys").exists()


@pytest.mark.parametrize("public, ok", [("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGg1", False),
                                        ("x-evil AAAA", False), ("ssh-ed25519\x1b AAAA", False),
                                        ("ssh-ed25519", False)])
def test_key_line_refus(public, ok):
    from sshvault.deploy import key_line
    assert (key_line(public) is not None) == ok


def test_key_line_type_inattendu_refuse(bench):
    """Blob d'un type étranger (son nom en tête du blob) : refusé localement, jamais envoyé."""
    from sshvault.deploy import key_line
    def s(b):
        return len(b).to_bytes(4, "big") + b
    blob = base64.b64encode(s(b"x-evil") + s(b"\x01" * 8)).decode()
    assert key_line("x-evil %s c" % blob) is None
    good = bench.keys["perso"]["public"]
    assert key_line(good) == good


@pytest.mark.parametrize("opts", [["-N"], ["-n"], ["-f"], ["-G"], ["-V"], ["-Q", "cipher"], ["-O", "check"],
                                  ["-W", "h:22"], ["-s"], ["-M"], ["-t"], ["-tt"], ["-vt"], ["-o", "RequestTTY=yes"],
                                  ["-oRemoteCommand=x"], ["-o", "LocalCommand x"], ["-o", "StdinNull=yes"],
                                  ["-o", "SessionType none"], ["-o", "forkafterauthentication=yes"],
                                  ["-o", "PermitLocalCommand=yes"], ["-oProxyUseFdpass=yes"]])
def test_deploy_options_ssh_qui_changent_le_mode_refusees(bench, tmp_path, opts):
    _unlocked(bench)
    w, log = ssh_wrapper(tmp_path)
    r = bench.run("deploy", "--id", ID_PERSO, "h", "--", *opts, env={"SSHVAULT_SSH": str(w)})
    assert r.returncode == 2 and "refusée" in one_error(r)
    assert not log.exists() and not bench.calls()


def ssh_stub(tmp_path, body):
    """Faux ssh (SSHVAULT_SSH) : lit stdin, puis `body` (shell) ; pid écrit dans stub.pid."""
    pidfile = tmp_path / "stub.pid"
    stub = tmp_path / "stubbin" / "ssh"
    stub.parent.mkdir(exist_ok=True)
    stub.write_text("#!/bin/sh\necho $$ > '%s'\n%s\n" % (pidfile, body))
    stub.chmod(0o755)
    return stub, pidfile


def _two_keys(bench):
    bench.items = [ssh_item(ID_PROD, "a prod", bench.keys["prod"]), ssh_item(ID_PERSO, "b perso", bench.keys["perso"])]
    bench.write_vault()


def test_deploy_echec_partiel_cles_deja_ajoutees_dites(bench, tmp_path):
    _unlocked(bench)
    _two_keys(bench)
    stub, _ = ssh_stub(tmp_path, "cat > /dev/null\necho 'sshvault-deploy added'\necho 'disque plein' >&2\nexit 1")
    r = bench.run("deploy", "--name", "p", "h", env={"SSHVAULT_SSH": str(stub)})
    assert r.returncode == 4
    assert r.stdout == "ajoutée : « a prod » %s → h\n" % bench.keys["prod"]["fingerprint"]
    assert "ssh vers h en échec (code 1) : disque plein" in one_error(r)


@pytest.mark.parametrize("answers, out", [("", ""), ("echo 'sshvault-deploy present'", "déjà présente : « a prod »")])
def test_deploy_reponse_absente_ou_incomplete(bench, tmp_path, answers, out):
    _unlocked(bench)
    _two_keys(bench)
    stub, _ = ssh_stub(tmp_path, "cat > /dev/null\n%s\nexit 0" % answers)
    r = bench.run("deploy", "--name", "p", "h", env={"SSHVAULT_SSH": str(stub)})
    assert r.returncode == 4 and "réponse inattendue" in one_error(r)
    assert r.stdout == ("" if not out else out + " %s → h\n" % bench.keys["prod"]["fingerprint"])


def test_deploy_sigterm_ssh_arrete(bench, tmp_path):
    _unlocked(bench)
    stub, pidfile = ssh_stub(tmp_path, "exec sleep 60")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "deploy", "--id", ID_PERSO, "h"],
                         env=dict(bench.env, SSHVAULT_SSH=str(stub)), stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    _wait_for(lambda: pidfile.exists() and pidfile.read_text().strip())
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=30)
    assert p.returncode == 130 and err.splitlines() == ["sshvault: interrompu"] and not out
    assert wait_gone([int(pidfile.read_text())], timeout=10), "ssh arrêté"


def test_deploy_delai_depasse(bench, tmp_path):
    _unlocked(bench)
    child = tmp_path / "child.pid"
    # TERM ignoré (KILL nécessaire), et un enfant qui garde les tubes ouverts (comme un ProxyCommand)
    stub, pidfile = ssh_stub(tmp_path, "trap '' TERM\nsleep 60 &\necho $! > '%s'\nwait" % child)
    t0 = time.monotonic()
    try:
        r = bench.run("deploy", "--id", ID_PERSO, "h", env={"SSHVAULT_SSH": str(stub), "SSHVAULT_DEPLOY_TIMEOUT": "2"})
        assert r.returncode == 4 and "sans réponse en 2s (SSHVAULT_DEPLOY_TIMEOUT)" in one_error(r)
        assert time.monotonic() - t0 < 30
        assert wait_gone([int(pidfile.read_text())], timeout=10), "ssh tué (TERM ignoré : KILL)"
    finally:
        if child.exists():
            try:
                os.kill(int(child.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("value", ["abc", "0", "-1"])
def test_deploy_delai_invalide(bench, value):
    _unlocked(bench)
    r = bench.run("deploy", "--id", ID_PERSO, "h", env={"SSHVAULT_DEPLOY_TIMEOUT": value})
    assert r.returncode == 2 and "SSHVAULT_DEPLOY_TIMEOUT" in one_error(r)


def test_deploy_ipv6_entre_crochets(bench, tmp_path):
    _unlocked(bench)
    w, log = ssh_wrapper(tmp_path)
    r = bench.run("deploy", "--id", ID_PERSO, "u@[::1]", "-p", str(_free_port()), "--", "-o", "BatchMode=yes",
                  env={"SSHVAULT_SSH": str(w)})
    assert r.returncode == 4
    assert "[--][u@::1][" in log.read_text(), "crochets retirés pour ssh"
    assert "Could not resolve" not in r.stderr


def test_deploy_une_lisible_une_illisible(bench, tgt):
    _unlocked(bench)
    bench.items = [ssh_item(ID_PROD, "a prod abimee", dict(bench.keys["prod"], public="x-evil AAAA")),
                   ssh_item(ID_PERSO, "b perso", bench.keys["perso"])]
    bench.write_vault()
    r = bench.run("deploy", "--name", "p", "target", "--", "-F", str(tgt.config))
    assert r.returncode == 4
    assert "« a prod abimee » (%s) : clé publique de l'élément illisible" % ID_PROD in r.stderr
    assert r.stdout.startswith("ajoutée : « b perso »")
    assert tgt.authorized.read_text() == bench.keys["perso"]["public"] + "\n"


# --- generate : contrôles de cohérence de la clé générée, messages après création ---------------------------

KG_TAMPER = r"""#!/usr/bin/env python3
import os, subprocess, sys
mode = %r
real = %r
args = sys.argv[1:]
if mode == "bits":
    args[args.index("-b") + 1] = "4096"
if mode == "comment":
    args[args.index("-C") + 1] = "autre"
subprocess.run([real] + args, check=True)
path = args[-1]
if mode == "pub":
    other = path + ".autre"
    subprocess.run([real, "-q", "-t", "ed25519", "-N", "", "-C", "web", "-f", other], check=True)
    os.replace(other + ".pub", path + ".pub")
    os.unlink(other)
if mode == "missing":
    os.unlink(path)
"""


@pytest.mark.parametrize("mode, args, words", [
    ("bits", ["--type", "rsa", "--bits", "3072"], "clé générée inattendue"),
    ("pub", [], "ne correspond pas"),
    ("comment", [], "commentaire"),
    ("missing", [], "clé privée générée illisible"),
])
def test_generate_coherence_de_la_cle_generee(bench, tmp_path, mode, args, words):
    _unlocked(bench)
    kg = tmp_path / "kg-altere"
    kg.write_text(KG_TAMPER % (mode, KEYGEN))
    kg.chmod(0o755)
    r = gen(bench, "--name", "web", *args, env={"SSHVAULT_SSH_KEYGEN": str(kg)})
    assert r.returncode == 4, r.stderr
    assert words in one_error(r)
    assert not r.stdout and not creates(bench) and not leftovers(bench)


def test_generate_session_refusee_a_la_creation(bench):
    _unlocked(bench)
    r = bench.run("--nointeraction", "generate", "--name", "web", env={"FAKE_BW_FAIL": "create=locked"})
    assert r.returncode == 3
    line = one_error(r)
    assert "verrouillé" in line and "perdue" in line, line
    assert not r.stdout and not new_items(bench) and not leftovers(bench)


def test_generate_sortie_fermee_apres_creation(bench):
    """stdout fermé (lecteur parti) : la clé est créée ; stderr le dit, avec le ssh_config non régénéré."""
    _unlocked(bench)
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "generate", "--name", "web", "--hosts", "x.example"],
                         env=dict(bench.env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    p.stdout.close()
    err = p.stderr.read()
    p.wait(60)
    [item] = new_items(bench)
    assert "clé créée : « web » %s ; ssh_config non régénéré : lancer « sshvault ssh-config »" % item["id"] in err, err
    assert not (bench.home / ".ssh" / "sshvault" / "config").exists()

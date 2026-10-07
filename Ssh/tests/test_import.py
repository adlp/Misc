"""`sshvault import` (story 6) sur le faux bw, avec de vraies clés générées par `ssh-keygen` :
une ligne de test par ligne de la matrice d'entrées et de cas limites, plus les cas annexes
(argv, copie temporaire, interruption, prérequis, champ de test)."""
import base64
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

import pytest

from bench import (HAVE_OPENSSH, ID_BASTION, ID_CHIFFREE, ID_LOGIN, ID_PERSO, ID_PROD, PASSPHRASE, PASSWORD, ArgvWatch,
                   b64_fragments, make_askpass, wait_gone)

DEFAULT_IDS = {ID_PROD, ID_PERSO, ID_BASTION, ID_LOGIN, ID_CHIFFREE, "55555555-5555-4555-8555-555555555555"}
KEYGEN = shutil.which("ssh-keygen") or "/usr/bin/ssh-keygen"


def _gen(d, name, typ, bits=None, passphrase="", fmt=None, comment=None):
    cmd = [KEYGEN, "-q", "-t", typ, "-N", passphrase, "-C", comment if comment is not None else "imp-" + name,
           "-f", str(d / name)]
    if bits:
        cmd[4:4] = ["-b", str(bits)]
    if fmt:
        cmd[4:4] = ["-m", fmt]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)


def _sk_key():
    """Clé OpenSSH « sk-ssh-ed25519@openssh.com » (structure seulement : aucune clé matérielle ici)."""
    def s(b):
        return len(b).to_bytes(4, "big") + b
    pub = s(b"sk-ssh-ed25519@openssh.com") + s(b"\x01" * 32) + s(b"ssh:")
    priv = (b"\x00\x00\x00\x01" * 2 + pub[:0] + s(b"sk-ssh-ed25519@openssh.com") + s(b"\x01" * 32) + s(b"ssh:")
            + b"\x01" + s(b"h") + s(b"") + s(b"c"))
    raw = b"openssh-key-v1\0" + s(b"none") + s(b"none") + s(b"") + (1).to_bytes(4, "big") + s(pub) + s(priv)
    body = base64.b64encode(raw).decode()
    return "-----BEGIN OPENSSH PRIVATE KEY-----\n%s\n-----END OPENSSH PRIVATE KEY-----\n" % "\n".join(
        body[i:i + 70] for i in range(0, len(body), 70))


@pytest.fixture(scope="session")
def ikeys(tmp_path_factory):
    """Clés de test (fichiers) : acceptées, chiffrées, refusées. Copiées dans chaque test."""
    d = tmp_path_factory.mktemp("ikeys")
    _gen(d, "ed", "ed25519")
    _gen(d, "rsa4096", "rsa", 4096, fmt="PKCS8")
    _gen(d, "rsa2048", "rsa", 2048)
    _gen(d, "edenc", "ed25519", passphrase=PASSPHRASE)
    _gen(d, "rsaenc", "rsa", 2048, passphrase=PASSPHRASE, fmt="PKCS8")
    _gen(d, "autre", "ed25519")
    _gen(d, "ecdsa", "ecdsa")
    _gen(d, "ecdsapk8", "ecdsa", fmt="PKCS8")
    _gen(d, "dsa", "dsa")
    _gen(d, "rsa1024", "rsa", 1024)
    _gen(d, "rsapem", "rsa", 2048, fmt="PEM")
    _gen(d, "rsapemenc", "rsa", 2048, passphrase=PASSPHRASE, fmt="PEM")
    _gen(d, "rsa1024pem", "rsa", 1024, fmt="PEM")
    _gen(d, "edpem", "ed25519", fmt="PEM")  # OpenSSH 8.9 : écrit au format OpenSSH (Ed25519 sans PEM)
    (d / "putty").write_text("PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: none\nComment: x\n"
                             "Public-Lines: 2\nAAAAC3NzaC1lZDI1NTE5AAAAIA\nAAAA\nPrivate-Lines: 1\nAAAA\n"
                             "Private-MAC: 00\n")
    (d / "texte").write_text("ceci n'est pas une clé\n")
    (d / "vide").write_text("")
    (d / "sk").write_text(_sk_key())
    for p in d.iterdir():
        p.chmod(0o600)
    out = {}
    for p in sorted(d.iterdir()):
        if p.suffix == ".pub":
            continue
        pub = d / (p.name + ".pub")
        info = {"path": p, "private": p.read_text()}
        if pub.exists():
            info["public"] = pub.read_text().strip()
            info["fingerprint"] = subprocess.run([KEYGEN, "-l", "-E", "sha256", "-f", str(pub)], capture_output=True,
                                                 text=True, check=True).stdout.split()[1]
        out[p.name] = info
    return out


def copy_key(ikeys, tmp_path, name, with_pub=True, as_name=None):
    d = tmp_path / "k"
    d.mkdir(mode=0o700, exist_ok=True)
    dst = d / (as_name or name)
    shutil.copy2(ikeys[name]["path"], dst)
    pub = ikeys[name]["path"].with_name(name + ".pub")
    if with_pub and pub.exists():
        shutil.copy2(pub, d / (dst.name + ".pub"))
    return dst


def snap(path):
    st = os.stat(path)
    return path.read_bytes(), st.st_mtime_ns, stat.S_IMODE(st.st_mode), st.st_ino


def _unlocked(bench):
    bench.unlocked("keyring" if bench.ring else "file")


def new_items(bench):
    return [i for i in json.loads(bench.vault_file.read_text())["items"] if i.get("id") not in DEFAULT_IDS]


def creates(bench):
    return [c for c in bench.calls() if c["argv"][1:2] == ["create"]]


def hosts_field(item):
    return [f["value"] for f in item.get("fields") or [] if f["name"] == "sshvault-hosts"]


def leftovers(bench):
    """Copies temporaires restantes dans le tmpfs privé."""
    d = bench.runtime / "sshvault"
    return sorted(p.name for p in d.iterdir() if p.name.startswith("import.")) if d.exists() else []


def private_key_files(roots, allowed):
    """Fichiers contenant « PRIVATE KEY » sous `roots`, hors `allowed` (dossiers ou fichiers)."""
    found = []
    for root in roots:
        for dirpath, dirs, files in os.walk(str(root)):
            if any(dirpath == str(a) or dirpath.startswith(str(a) + os.sep) for a in allowed):
                continue
            for f in files:
                p = os.path.join(dirpath, f)
                if p in {str(a) for a in allowed}:
                    continue
                try:
                    with open(p, "rb") as fh:
                        if b"PRIVATE KEY" in fh.read():
                            found.append(p)
                except OSError:
                    pass
    return found


def no_key_outside_fixtures(bench, keydir):
    found = private_key_files([bench.tmp, bench.runtime],
                              [keydir, bench.vault_file.parent, bench.appdata])
    assert not found, "fichiers de clé privée hors des fixtures : %s" % found


def one_error(r):
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    assert len(lines) == 1, r.stderr
    assert "Traceback" not in r.stderr
    return lines[0]


# --- clés acceptées ------------------------------------------------------------------------------

def test_import_ed25519_openssh_avec_hotes(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "ed")
    before, before_pub = snap(f), snap(f.with_name("ed.pub"))
    r = bench.run("import", str(f), "--hosts", "Prod.Example,b.example", "--hosts", "c.example")
    assert r.returncode == 0, r.stderr
    k = ikeys["ed"]
    assert "importée : imp-ed (%s)\n" % k["fingerprint"] in r.stdout
    [item] = new_items(bench)
    assert item["type"] == 5 and item["name"] == "imp-ed"
    assert item["sshKey"] == {"privateKey": k["private"], "publicKey": k["public"], "keyFingerprint": k["fingerprint"]}
    assert hosts_field(item) == ["prod.example,b.example,c.example"]
    # sync (état du serveur), liste, création sur stdin, relecture
    argv = [c["argv"] for c in bench.calls()]
    assert argv == [["--nointeraction", "sync"], ["--nointeraction", "list", "items"],
                    ["--nointeraction", "create", "item"], ["--nointeraction", "get", "item", item["id"]]]
    # ssh_config et .pub régénérés
    cfg = (bench.home / ".ssh" / "sshvault" / "config").read_text()
    assert "Match originalhost prod.example,b.example,c.example\n" in cfg
    from sshvault.sshconfig import fp_filename
    pub = bench.home / ".ssh" / "sshvault" / "pub" / fp_filename(k["fingerprint"])
    assert pub.read_text().split() == k["public"].split()[:2]
    assert snap(f) == before and snap(f.with_name("ed.pub")) == before_pub, "fichiers d'origine inchangés"
    r = bench.run("search", "--fingerprint", k["fingerprint"], "--json")
    assert r.returncode == 0 and json.loads(r.stdout)[0]["hosts"] == ["prod.example", "b.example", "c.example"]


def test_import_rsa4096_pkcs8(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "rsa4096")
    assert ikeys["rsa4096"]["private"].startswith("-----BEGIN PRIVATE KEY-----")
    before = snap(f)
    r = bench.run("import", str(f))
    assert r.returncode == 0, r.stderr
    k = ikeys["rsa4096"]
    [item] = new_items(bench)
    # PKCS#8 : pas de commentaire dans la clé, celui de la .pub voisine (qui correspond)
    assert item["name"] == "imp-rsa4096"
    assert item["sshKey"]["publicKey"] == k["public"] and item["sshKey"]["keyFingerprint"] == k["fingerprint"]
    # convertie au format OpenSSH (même clé)
    assert _is_openssh_clear(item["sshKey"]["privateKey"])
    assert _public_of(item["sshKey"]["privateKey"]) == k["public"].split()[:2]
    assert "PKCS#8 convertie au format OpenSSH" in r.stderr
    assert not leftovers(bench)
    assert "importée : imp-rsa4096 (%s)" % k["fingerprint"] in r.stdout
    assert not hosts_field(item)
    assert not (bench.home / ".ssh").exists(), "sans hôte : ssh_config non régénéré"
    assert snap(f) == before


def test_import_sans_pub_nom_du_fichier(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "rsa4096", with_pub=False, as_name="ma_cle_rsa")
    r = bench.run("import", str(f))
    assert r.returncode == 0, r.stderr
    [item] = new_items(bench)
    assert item["name"] == "ma_cle_rsa"
    assert item["sshKey"]["publicKey"] == " ".join(ikeys["rsa4096"]["public"].split()[:2])
    assert item["sshKey"]["keyFingerprint"] == ikeys["rsa4096"]["fingerprint"]


def test_import_nom_donne(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "ed")
    r = bench.run("import", str(f), "--name", "Mon serveur")
    assert r.returncode == 0, r.stderr
    assert [i["name"] for i in new_items(bench)] == ["Mon serveur"]
    assert new_items(bench)[0]["sshKey"]["publicKey"] == ikeys["ed"]["public"], "commentaire gardé dans la clé publique"


@pytest.mark.parametrize("args", [["--name", "x", "A", "B"], ["--name", " ", "A"]])
def test_import_nom_usage(bench, args):
    _unlocked(bench)
    r = bench.run("import", *args)
    assert r.returncode == 2 and "--name" in one_error(r)
    assert not bench.calls()


def test_import_edpem_est_openssh(bench, ikeys, tmp_path):
    """`ssh-keygen -m PEM` sur une Ed25519 (OpenSSH 8.9) écrit le format OpenSSH : importée."""
    _unlocked(bench)
    assert ikeys["edpem"]["private"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "edpem")))
    assert r.returncode == 0, r.stderr
    assert new_items(bench)[0]["sshKey"]["keyFingerprint"] == ikeys["edpem"]["fingerprint"]


# --- clé à passphrase ------------------------------------------------------------------------------

@pytest.mark.skipif(not HAVE_OPENSSH, reason="ssh-agent/ssh-add absents")
def test_import_chiffree_openssh_sans_decrypt_puis_load(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "edenc")
    before = snap(f)
    r = bench.run("--nointeraction", "import", str(f))  # aucune invite : clé publique de l'en-tête
    assert r.returncode == 0, r.stderr
    k = ikeys["edenc"]
    [item] = new_items(bench)
    assert item["sshKey"] == {"privateKey": k["private"], "publicKey": k["public"], "keyFingerprint": k["fingerprint"]}
    assert item["name"] == "imp-edenc", "commentaire de la .pub voisine (clé chiffrée)"
    assert "stockée chiffrée par sa passphrase" in r.stderr and "Bitwarden Desktop" in r.stderr
    assert snap(f) == before
    assert not leftovers(bench)
    # load demande ensuite la passphrase (0.2.0)
    r, tty = bench.run_tty("load", "--id", item["id"], answer=PASSPHRASE, trigger=b"passphrase")
    assert r.returncode == 0, (r.stderr, tty)
    assert bench.agent_keys() == [k["public"].split()[1]]


def test_import_decrypt_tty(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "edenc")
    before = snap(f)
    r, tty = bench.run_tty("import", "--decrypt", str(f), answer=PASSPHRASE, trigger=rb"passphrase")
    assert r.returncode == 0, (r.stderr, tty)
    assert PASSPHRASE not in tty, "écho coupé pendant la saisie"
    assert bench.tty_echo is True
    assert tty.count("passphrase") == 1, tty
    k = ikeys["edenc"]
    [item] = new_items(bench)
    priv = item["sshKey"]["privateKey"]
    from sshvault.agent import is_encrypted
    assert priv.startswith("-----BEGIN OPENSSH PRIVATE KEY-----") and not is_encrypted(priv.encode())
    assert item["sshKey"]["publicKey"] == k["public"] and item["sshKey"]["keyFingerprint"] == k["fingerprint"]
    assert item["name"] == "imp-edenc"
    # la clé déchiffrée est bien celle du fichier
    out = subprocess.run([KEYGEN, "-y", "-f", "/dev/stdin"], input=priv, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.split()[:2] == k["public"].split()[:2]
    assert "stockée chiffrée" not in r.stderr
    assert snap(f) == before, "fichier d'origine intact"
    assert not leftovers(bench), "copie tmpfs supprimée"
    no_key_outside_fixtures(bench, f.parent)


def test_import_decrypt_askpass(bench, ikeys, tmp_path):
    _unlocked(bench)
    askpass, calls = make_askpass(tmp_path, reply=PASSPHRASE)
    f = copy_key(ikeys, tmp_path, "edenc")
    r = bench.run("import", "--decrypt", str(f), env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 0, r.stderr
    assert len(calls.read_text().splitlines()) == 1
    from sshvault.agent import is_encrypted
    assert not is_encrypted(new_items(bench)[0]["sshKey"]["privateKey"].encode())
    assert not leftovers(bench)


def test_import_decrypt_passphrase_refusee(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "edenc")
    before = snap(f)
    r, tty = bench.run_tty("import", "--decrypt", str(f), answer="mauvaise", trigger=rb"passphrase")
    assert r.returncode == 3, (r.stderr, tty)
    assert "passphrase refusée" in r.stderr
    assert not creates(bench) and not new_items(bench)
    assert not leftovers(bench) and snap(f) == before
    assert bench.tty_echo is True


@pytest.mark.parametrize("glob", [[], ["--nointeraction"]])
def test_import_decrypt_sans_invite(bench, ikeys, tmp_path, glob):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "edenc")
    r = bench.run(*glob, "import", "--decrypt", str(f))
    assert r.returncode == 3, r.stderr
    assert ("--nointeraction" if glob else "aucune invite possible") in one_error(r)
    assert not bench.calls(), "refus local, avant tout accès au coffre"
    assert not leftovers(bench)


def test_import_decrypt_askpass_annule(bench, ikeys, tmp_path):
    _unlocked(bench)
    askpass, _ = make_askpass(tmp_path, reply="", rc=1)
    r = bench.run("import", "--decrypt", str(copy_key(ikeys, tmp_path, "edenc")),
                  env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3 and not new_items(bench) and not leftovers(bench)


def test_import_pkcs8_chiffree_sans_decrypt(bench, ikeys, tmp_path):
    """Invite seulement pour la clé publique ; la clé stockée reste chiffrée, telle quelle."""
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "rsaenc")
    assert ikeys["rsaenc"]["private"].startswith("-----BEGIN ENCRYPTED PRIVATE KEY-----")
    r, tty = bench.run_tty("import", str(f), answer=PASSPHRASE, trigger=rb"passphrase")
    assert r.returncode == 0, (r.stderr, tty)
    assert tty.count("passphrase") == 1 and PASSPHRASE not in tty
    k = ikeys["rsaenc"]
    [item] = new_items(bench)
    assert item["sshKey"] == {"privateKey": k["private"], "publicKey": k["public"], "keyFingerprint": k["fingerprint"]}
    assert "stockée chiffrée" in r.stderr
    assert not leftovers(bench)
    no_key_outside_fixtures(bench, f.parent)


def test_import_pkcs8_chiffree_decrypt_une_invite(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "rsaenc")
    before = snap(f)
    r, tty = bench.run_tty("import", "--decrypt", str(f), answer=PASSPHRASE, trigger=rb"passphrase")
    assert r.returncode == 0, (r.stderr, tty)
    assert tty.count("passphrase") == 1, "passphrase demandée une seule fois"
    [item] = new_items(bench)
    from sshvault.agent import is_encrypted
    assert not is_encrypted(item["sshKey"]["privateKey"].encode())
    assert item["sshKey"]["keyFingerprint"] == ikeys["rsaenc"]["fingerprint"]
    assert item["name"] == "imp-rsaenc"
    assert snap(f) == before and not leftovers(bench)


def test_import_pkcs8_chiffree_nointeraction(bench, ikeys, tmp_path):
    _unlocked(bench)
    r = bench.run("--nointeraction", "import", str(copy_key(ikeys, tmp_path, "rsaenc")))
    assert r.returncode == 3 and "--nointeraction" in one_error(r)
    assert not bench.calls(), "refus local, avant tout accès au coffre"


def test_import_decrypt_cle_en_clair_inchangee(bench, ikeys, tmp_path):
    """--decrypt sur une clé sans passphrase : importée telle quelle, sans invite ni copie."""
    _unlocked(bench)
    r = bench.run("--nointeraction", "import", "--decrypt", str(copy_key(ikeys, tmp_path, "ed")))
    assert r.returncode == 0, r.stderr
    assert new_items(bench)[0]["sshKey"]["privateKey"] == ikeys["ed"]["private"]


# --- doublon -------------------------------------------------------------------------------------------

def test_import_doublon_puis_force(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "ed")
    assert bench.run("import", str(f), "--name", "première").returncode == 0
    [first] = new_items(bench)
    r = bench.run("import", str(f))
    assert r.returncode == 1
    line = one_error(r)
    assert "déjà dans le coffre" in line and "« première » %s" % first["id"] in line and "--force" in line
    assert len(creates(bench)) == 1 and len(new_items(bench)) == 1
    r = bench.run("import", "--force", str(f))
    assert r.returncode == 0, r.stderr
    assert len(new_items(bench)) == 2


def test_import_doublon_chiffree_sans_invite(bench, ikeys, tmp_path):
    """Doublon d'une clé chiffrée OpenSSH : refusé avant toute invite de passphrase (--decrypt)."""
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "edenc")
    assert bench.run("import", str(f)).returncode == 0
    askpass, calls = make_askpass(tmp_path, reply=PASSPHRASE)
    r = bench.run("import", "--decrypt", str(f), env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 1 and "déjà dans le coffre" in one_error(r)
    assert not calls.exists(), "aucune invite pour un doublon"


def test_import_doublon_avec_hotes_indique_hosts_add(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "ed")
    assert bench.run("import", str(f)).returncode == 0
    [first] = new_items(bench)
    r = bench.run("import", str(f), "--hosts", "a.example,b.example")
    assert r.returncode == 1
    line = one_error(r)
    assert "sshvault hosts add --id %s a.example,b.example" % first["id"] in line and "--force" in line


# --- formats refusés -------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, words", [
    ("ecdsa", "ECDSA"), ("ecdsapk8", "ECDSA"), ("dsa", "DSA"), ("sk", "-sk"), ("putty", "PuTTY"),
    ("rsa1024", "1024 bits"), ("rsapemenc", "--decrypt"), ("texte", "pas une clé privée"),
    ("vide", "pas une clé privée"), ("ed.pub", "clé publique")])
def test_import_format_refuse(bench, ikeys, tmp_path, name, words):
    _unlocked(bench)
    if name == "ed.pub":
        f = copy_key(ikeys, tmp_path, "ed").with_name("ed.pub")
    else:
        f = copy_key(ikeys, tmp_path, name)
    r = bench.run("import", str(f))
    assert r.returncode == 2, r.stderr
    line = one_error(r)
    assert line.startswith("sshvault: %s : " % f) and words in line, line
    assert not bench.calls(), "refusé avant tout accès au coffre"


@pytest.mark.parametrize("what", ["absent", "dossier", "fifo"])
def test_import_fichier_inutilisable(bench, tmp_path, what):
    _unlocked(bench)
    p = tmp_path / what
    if what == "dossier":
        p.mkdir()
    elif what == "fifo":
        os.mkfifo(str(p))
    r = bench.run("import", str(p), timeout=20)
    assert r.returncode == 2
    assert ("illisible" if what == "absent" else "pas un fichier ordinaire") in one_error(r)


def test_import_pub_voisine_differente(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "ed")
    shutil.copy2(ikeys["autre"]["path"].with_name("autre.pub"), f.with_name("ed.pub"))
    before_pub = snap(f.with_name("ed.pub"))
    r = bench.run("import", str(f))
    assert r.returncode == 0, r.stderr
    assert "ed.pub ne correspond pas à la clé privée : ignorée" in r.stderr
    [item] = new_items(bench)
    assert item["sshKey"]["keyFingerprint"] == ikeys["ed"]["fingerprint"]
    assert item["sshKey"]["publicKey"] == ikeys["ed"]["public"]
    assert snap(f.with_name("ed.pub")) == before_pub


def test_import_pub_voisine_differente_pkcs8_nom_du_fichier(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "rsa4096")
    shutil.copy2(ikeys["autre"]["path"].with_name("autre.pub"), f.with_name("rsa4096.pub"))
    r = bench.run("import", str(f))
    assert r.returncode == 0, r.stderr
    assert "ne correspond pas" in r.stderr
    [item] = new_items(bench)
    assert item["name"] == "rsa4096" and item["sshKey"]["keyFingerprint"] == ikeys["rsa4096"]["fingerprint"]


# --- bw create en échec ou bloqué --------------------------------------------------------------------------

def _gone(pids):
    return wait_gone(pids, timeout=10)


def test_import_create_bloque_sans_ecriture_rejoue(bench, ikeys, tmp_path):
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")),
                  env={"FAKE_BW_FAIL": "create=hangonce", "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    argv = [c["argv"][1:] for c in bench.calls()]
    i = argv.index(["create", "item"])
    # sync puis recherche avant le rejeu
    assert argv[i + 1:i + 4] == [["sync"], ["list", "items"], ["create", "item"]]
    assert len(creates(bench)) == 2 and len(new_items(bench)) == 1
    assert _gone([int(x) for x in bench.pids.read_text().split()]), "bw bloqué et son enfant tués"


@pytest.mark.parametrize("mode", ["hangafter", "errorafter", "badjsonafter"])
def test_import_create_passe_puis_echec_pas_de_doublon(bench, ikeys, tmp_path, mode):
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), "--hosts", "x.example",
                  env={"FAKE_BW_FAIL": "create=" + mode, "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    assert len(creates(bench)) == 1, "trouvé par empreinte : rien rejoué"
    [item] = new_items(bench)
    assert hosts_field(item) == ["x.example"]
    assert "importée : imp-ed" in r.stdout
    assert (bench.home / ".ssh" / "sshvault" / "config").exists()


def test_import_create_toujours_absent(bench, ikeys, tmp_path):
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), env={"FAKE_BW_FAIL": "create=error"})
    assert r.returncode == 4
    line = one_error(r)
    assert "deux fois" in line and "absent du coffre" in line
    assert len(creates(bench)) == 2 and not new_items(bench)


def test_import_create_bloque_toujours(bench, ikeys, tmp_path):
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")),
                  env={"FAKE_BW_FAIL": "create=hang", "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 4 and "absent du coffre" in one_error(r)
    assert len(creates(bench)) == 2 and not new_items(bench)


def test_import_create_reussi_mais_relu_different(bench, ikeys, tmp_path):
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), env={"FAKE_BW_FAIL": "create=corrupt"})
    assert r.returncode == 4
    line = one_error(r)
    assert "relu diffère (privateKey)" in line
    [item] = new_items(bench)
    assert "supprimer l'élément %s" % item["id"] in line and "--force" in line
    assert "PRIVATE KEY" not in r.stderr
    assert len(creates(bench)) == 1


def test_import_create_silencieux_relecture_impossible(bench, ikeys, tmp_path):
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), env={"FAKE_BW_FAIL": "create=silent"})
    assert r.returncode == 4 and "relecture impossible" in one_error(r)
    assert len(creates(bench)) == 1


def test_import_force_rejeu_ne_confond_pas_l_existant(bench, ikeys, tmp_path):
    """--force, création bloquée avant écriture : l'élément déjà présent (même empreinte) n'est
    pas pris pour le nouveau ; rejeu, deux éléments au final."""
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "ed")
    assert bench.run("import", str(f)).returncode == 0
    r = bench.run("import", "--force", str(f), env={"FAKE_BW_FAIL": "create=hangonce", "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    assert len(new_items(bench)) == 2


def test_import_sigterm_pendant_create(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "ed")
    e = dict(bench.env, FAKE_BW_FAIL="create=hang", SSHVAULT_BW_TIMEOUT="60")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "import", str(f)], env=e, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    deadline = time.monotonic() + 20
    while not (bench.pids.exists() and len(bench.pids.read_text().split()) == 2) and time.monotonic() < deadline:
        time.sleep(0.1)
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=20)
    assert p.returncode == 130
    fp = ikeys["ed"]["fingerprint"]
    assert err.splitlines() == [
        "sshvault: interrompu",
        "sshvault: « imp-ed » : création peut-être passée : vérifier par « sshvault sync » puis "
        "« sshvault search --fingerprint %s »" % fp]
    assert _gone([int(x) for x in bench.pids.read_text().split()])


def test_import_sigterm_pendant_la_passphrase(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "edenc")
    before = snap(f)
    r, tty = bench.run_tty("import", "--decrypt", str(f), trigger=rb"passphrase", signal_at_prompt=signal.SIGTERM)
    assert r.returncode == 130, (r.stderr, tty)
    assert not leftovers(bench), "copie supprimée malgré le signal"
    assert bench.tty_echo is True
    assert not creates(bench) and snap(f) == before


def test_import_copie_orpheline_supprimee(bench, ikeys, tmp_path):
    """Sous-dossier laissé par un import tué (SIGKILL) : supprimé au prochain import qui copie."""
    _unlocked(bench)
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700, exist_ok=True)
    dead = subprocess.Popen(["true"])
    dead.wait()
    orphan = d / ("import.%d.abc" % dead.pid)
    orphan.mkdir(mode=0o700)
    (orphan / "key").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
    askpass, _ = make_askpass(tmp_path, reply=PASSPHRASE)
    r = bench.run("import", "--decrypt", str(copy_key(ikeys, tmp_path, "edenc")),
                  env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 0, r.stderr
    assert not orphan.exists() and not leftovers(bench)


def test_import_tmpfs_refuse(bench, ikeys, tmp_path):
    """--decrypt sans tmpfs privé : rien importé, aucune copie sur disque."""
    _unlocked(bench)
    d = tmp_path / "pas-tmpfs"
    d.mkdir(mode=0o700)
    askpass, calls = make_askpass(tmp_path, reply=PASSPHRASE)
    r = bench.run("import", "--decrypt", str(copy_key(ikeys, tmp_path, "edenc")),
                  env={"XDG_RUNTIME_DIR": str(d), "SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 4 and "XDG_RUNTIME_DIR" in one_error(r)
    assert not calls.exists() and not creates(bench)
    assert not list(d.iterdir())


# --- plusieurs fichiers, coffre, hôtes -------------------------------------------------------------------

def test_import_plusieurs_fichiers_pire_code(bench, ikeys, tmp_path):
    _unlocked(bench)
    ok = copy_key(ikeys, tmp_path, "ed")
    dup = copy_key(ikeys, tmp_path, "rsa2048")
    bad = copy_key(ikeys, tmp_path, "ecdsa")
    assert bench.run("import", str(dup)).returncode == 0
    r = bench.run("import", str(ok), str(dup), str(bad))
    assert r.returncode == 2
    assert r.stdout.splitlines() == ["importée : imp-ed (%s)" % ikeys["ed"]["fingerprint"]]
    err = [l for l in r.stderr.splitlines() if l.strip()]
    assert len(err) == 2
    assert err[0].startswith("sshvault: %s : type ECDSA refusé" % bad)
    assert err[1].startswith("sshvault: %s : déjà dans le coffre" % dup)
    assert len(new_items(bench)) == 2


def test_import_meme_cle_deux_fois_dans_la_commande(bench, ikeys, tmp_path):
    _unlocked(bench)
    a = copy_key(ikeys, tmp_path, "ed")
    b = copy_key(ikeys, tmp_path, "ed", as_name="copie")
    r = bench.run("import", str(a), str(b))
    assert r.returncode == 1 and "déjà dans le coffre" in r.stderr
    assert len(new_items(bench)) == 1


def test_import_coffre_verrouille_sans_invite(bench, ikeys, tmp_path):
    bench.set_state(logged_in=True)
    r = bench.run("--nointeraction", "import", str(copy_key(ikeys, tmp_path, "ed")))
    assert r.returncode == 3 and "verrouillé" in one_error(r)
    assert not creates(bench)


def test_import_coffre_verrouille_invite(bench, ikeys, tmp_path):
    bench.set_state(logged_in=True)
    r, tty = bench.run_tty("import", str(copy_key(ikeys, tmp_path, "ed")), answer=PASSWORD)
    assert r.returncode == 0, (r.stderr, tty)
    assert len(new_items(bench)) == 1


def test_import_non_connecte(bench, ikeys, tmp_path):
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")))
    assert r.returncode == 3 and "sshvault login" in one_error(r)


@pytest.mark.parametrize("host", ["a b", "user@h", "é.example"])
def test_import_hote_invalide(bench, ikeys, tmp_path, host):
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), "--hosts", "ok.example," + host)
    assert r.returncode == 2 and "hôte invalide" in one_error(r)
    assert not bench.calls()


def test_import_prerequis_verifies_avant_ecriture(bench, ikeys, tmp_path):
    _unlocked(bench)
    d = tmp_path / "pas-tmpfs"
    d.mkdir(mode=0o700)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), "--hosts", "x.example",
                  env={"XDG_RUNTIME_DIR": str(d)})
    assert r.returncode == 4 and "XDG_RUNTIME_DIR" in one_error(r)
    assert not creates(bench) and not new_items(bench)


def test_import_cree_mais_ssh_config_non_regenere(bench, ikeys, tmp_path):
    _unlocked(bench)
    ssh = bench.home / ".ssh"
    ssh.mkdir(mode=0o700)
    (ssh / "sshvault").write_text("pas un dossier")
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), "--hosts", "x.example")
    assert r.returncode == 4
    assert "importée : imp-ed" in r.stdout
    assert "mais ssh_config non régénéré" in r.stderr
    assert len(new_items(bench)) == 1


def test_import_champ_de_test(bench, ikeys, tmp_path):
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), "--hosts", "x.example",
                  env={"SSHVAULT_TEST_FIELD": "sshvault-test-run=abc"})
    assert r.returncode == 0, r.stderr
    [item] = new_items(bench)
    assert [(f["name"], f["value"]) for f in item["fields"]] == [("sshvault-hosts", "x.example"),
                                                                 ("sshvault-test-run", "abc")]


# --- rien en argument : ni JSON, ni clé, ni passphrase ------------------------------------------------------

def test_import_argv_sans_json_cle_ni_passphrase(bench, ikeys, tmp_path):
    """Journal de bw (argv), enveloppe de ssh-keygen (argv), et relevé de /proc/<pid>/cmdline
    pendant les imports : PKCS#8 en clair (ssh-keygen -y sur stdin), PKCS#8 chiffré et OpenSSH
    chiffré avec --decrypt (askpass)."""
    _unlocked(bench)
    log = tmp_path / "keygen.log"
    wrapper = tmp_path / "bin" / "ssh-keygen"
    wrapper.write_text("#!/bin/sh\nfor a in \"$@\"; do printf '[%%s]' \"$a\"; done >> '%s'\necho >> '%s'\n"
                       "exec '%s' \"$@\"\n" % (log, log, KEYGEN))
    wrapper.chmod(0o755)
    askpass, calls = make_askpass(tmp_path, reply=PASSPHRASE)
    env = {"SSHVAULT_SSH_KEYGEN": str(wrapper), "SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"}
    names = ("rsa4096", "rsaenc", "edenc", "rsapem", "rsapemenc")
    files = [copy_key(ikeys, tmp_path, n) for n in names]
    secrets = [PASSPHRASE]
    for n in names:
        body = "".join(ikeys[n]["private"].splitlines()[1:-1])
        secrets += [body[:40], body[-40:], body[200:240]] + b64_fragments(ikeys[n]["private"])
    with ArgvWatch(uuid.uuid4().hex, secrets, heuristics=False) as w:
        r = bench.run("import", "--decrypt", *map(str, files), env=env)
    assert r.returncode == 0, r.stderr
    assert len(new_items(bench)) == 5
    assert not w.suspect, "argument suspect dans /proc/<pid>/cmdline : %s" % w.suspect[:3]
    keygen = log.read_text().splitlines()
    assert len([l for l in keygen if l.startswith("[-p][-N][][-f][")]) == 3, keygen
    assert len([l for l in keygen if l.startswith("[-p][-P][][-N][][-f][")]) == 2, keygen
    assert len(keygen) == 5, keygen
    for l in keygen:
        assert PASSPHRASE not in l and "PRIVATE" not in l
        assert l.count("[-P]") == l.count("[-P][]"), "-P seulement avec une passphrase vide : %s" % l
    for c in bench.calls():
        for a in c["argv"]:
            assert "{" not in a and "PRIVATE" not in a and len(a) < 80, c["argv"]
            assert not any(s in a for s in secrets)
    assert [c["argv"] for c in creates(bench)] == [["--nointeraction", "create", "item"]] * 5
    assert len(calls.read_text().splitlines()) == 3, "une invite par clé chiffrée"
    assert not leftovers(bench)
    no_key_outside_fixtures(bench, files[0].parent)


def test_import_chemin_inutilisable_verifie_avant_ecriture(bench, ikeys, tmp_path):
    _unlocked(bench)
    home = tmp_path / 'gui"llemet'
    home.mkdir()
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), "--hosts", "x.example",
                  env={"SSHVAULT_SSH_HOME": str(home)})
    assert r.returncode == 4 and "inutilisable dans un ssh_config" in one_error(r)
    assert not creates(bench) and not new_items(bench)


@pytest.mark.parametrize("where", ["checkint", "clé publique"])
def test_import_openssh_incoherente(bench, ikeys, tmp_path, where):
    """Partie privée en clair qui ne correspond pas à l'en-tête : refusée (code 2)."""
    _unlocked(bench)
    text = ikeys["ed"]["private"]
    lines = text.splitlines()
    raw = bytearray(base64.b64decode("".join(lines[1:-1])))
    # en-tête : magic, « none », « none », « », 1, blob public (51 octets), longueur de la partie privée
    off = len(b"openssh-key-v1\0") + 8 + 8 + 4 + 4 + 4 + 51 + 4
    if where == "checkint":
        raw[off] ^= 1
    else:
        raw[off + 8 + 4 + 11 + 4 + 5] ^= 1  # un octet de la clé publique recopiée dans la partie privée
    body = base64.b64encode(bytes(raw)).decode()
    f = tmp_path / "abimee"
    f.write_text("%s\n%s\n%s\n" % (lines[0], "\n".join(body[i:i + 70] for i in range(0, len(body), 70)), lines[-1]))
    f.chmod(0o600)
    r = bench.run("import", str(f))
    assert r.returncode == 2 and "incohérente" in one_error(r)
    assert not bench.calls()


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl absent")
def test_import_ed25519_pkcs8_openssl_illisible_par_openssh(bench, tmp_path):
    """Mesuré (OpenSSH 8.9p1) : `ssh-keygen -y` ne lit pas une Ed25519 PKCS#8 (« invalid format ») :
    refusée, code 2, avec le message de ssh-keygen."""
    _unlocked(bench)
    f = tmp_path / "edossl"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(f)], check=True, capture_output=True)
    assert f.read_text().startswith("-----BEGIN PRIVATE KEY-----")
    r = bench.run("import", str(f))
    assert r.returncode == 2 and "clé illisible par ssh-keygen" in one_error(r)
    assert not bench.calls()


def test_import_decrypt_stdin_terminal(bench, ikeys, tmp_path):
    """stdin de sshvault = le terminal (usage interactif ordinaire) : ssh-keygen hérite de stdin
    et lit la passphrase sur le terminal, écho coupé, une invite."""
    from bench import pty_run
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "edenc")
    before = snap(f)
    r = pty_run([["sh", "-c", 'exec "$0" -m sshvault import --decrypt "$1" < /dev/tty', sys.executable, str(f)]],
                dict(bench.env), answers=PASSPHRASE, trigger=rb"passphrase")
    assert r.returncode == 0, (r.stderr, r.screen)
    assert r.prompts == 1 and PASSPHRASE not in r.screen and r.echo is True
    from sshvault.agent import is_encrypted
    assert not is_encrypted(new_items(bench)[0]["sshKey"]["privateKey"].encode())
    assert snap(f) == before and not leftovers(bench)


# --- RSA PEM PKCS#1 (décision utilisateur) --------------------------------------------------------------

def _is_openssh_clear(text):
    from sshvault.agent import is_encrypted
    return text.startswith("-----BEGIN OPENSSH PRIVATE KEY-----") and not is_encrypted(text.encode())


def _public_of(private_text):
    out = subprocess.run([KEYGEN, "-y", "-f", "/dev/stdin"], input=private_text, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.split()[:2]


def test_import_pkcs1_en_clair_convertie(bench, ikeys, tmp_path):
    _unlocked(bench)
    k = ikeys["rsapem"]
    assert k["private"].startswith("-----BEGIN RSA PRIVATE KEY-----")
    f = copy_key(ikeys, tmp_path, "rsapem")
    before, before_pub = snap(f), snap(f.with_name("rsapem.pub"))
    r = bench.run("--nointeraction", "import", str(f))
    assert r.returncode == 0, r.stderr
    assert "RSA PEM PKCS#1 convertie au format OpenSSH" in r.stderr and "fichier d'origine inchangé" in r.stderr
    [item] = new_items(bench)
    priv = item["sshKey"]["privateKey"]
    assert _is_openssh_clear(priv), "stockée au format OpenSSH"
    assert item["sshKey"]["keyFingerprint"] == k["fingerprint"], "empreinte = ssh-keygen -l de l'original"
    assert item["sshKey"]["publicKey"] == k["public"] and item["name"] == "imp-rsapem"
    assert _public_of(priv) == k["public"].split()[:2]
    assert "importée : imp-rsapem (%s)" % k["fingerprint"] in r.stdout
    assert snap(f) == before and snap(f.with_name("rsapem.pub")) == before_pub, "original intact"
    assert not leftovers(bench), "copie tmpfs supprimée"
    no_key_outside_fixtures(bench, f.parent)


def test_import_pkcs1_sans_pub_nom_du_fichier(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "rsapem", with_pub=False, as_name="vieille_rsa")
    r = bench.run("import", str(f))
    assert r.returncode == 0, r.stderr
    [item] = new_items(bench)
    assert item["name"] == "vieille_rsa" and item["sshKey"]["keyFingerprint"] == ikeys["rsapem"]["fingerprint"]


def test_import_pkcs1_chiffree_sans_decrypt_refusee(bench, ikeys, tmp_path):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "rsapemenc")
    assert "Proc-Type: 4,ENCRYPTED" in ikeys["rsapemenc"]["private"]
    before = snap(f)
    r = bench.run("import", str(f))
    assert r.returncode == 2
    assert "--decrypt" in one_error(r)
    assert not bench.calls() and not leftovers(bench) and snap(f) == before


def test_import_pkcs1_chiffree_decrypt(bench, ikeys, tmp_path):
    _unlocked(bench)
    k = ikeys["rsapemenc"]
    f = copy_key(ikeys, tmp_path, "rsapemenc")
    before = snap(f)
    r, tty = bench.run_tty("import", "--decrypt", str(f), answer=PASSPHRASE, trigger=rb"passphrase")
    assert r.returncode == 0, (r.stderr, tty)
    assert tty.count("passphrase") == 1 and PASSPHRASE not in tty and bench.tty_echo is True
    [item] = new_items(bench)
    assert _is_openssh_clear(item["sshKey"]["privateKey"])
    assert item["sshKey"]["keyFingerprint"] == k["fingerprint"] and item["sshKey"]["publicKey"] == k["public"]
    assert _public_of(item["sshKey"]["privateKey"]) == k["public"].split()[:2]
    assert snap(f) == before and not leftovers(bench)
    no_key_outside_fixtures(bench, f.parent)


def test_import_pkcs1_chiffree_decrypt_passphrase_refusee(bench, ikeys, tmp_path):
    _unlocked(bench)
    askpass, _ = make_askpass(tmp_path, reply="mauvaise")
    r = bench.run("import", "--decrypt", str(copy_key(ikeys, tmp_path, "rsapemenc")),
                  env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3 and "passphrase refusée" in r.stderr
    assert not creates(bench) and not leftovers(bench)


def test_import_pkcs1_rsa1024_refusee(bench, ikeys, tmp_path):
    _unlocked(bench)
    assert ikeys["rsa1024pem"]["private"].startswith("-----BEGIN RSA PRIVATE KEY-----")
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "rsa1024pem")))
    assert r.returncode == 2 and "1024 bits" in one_error(r)
    assert not bench.calls() and not leftovers(bench)


def test_import_pkcs1_illisible(bench, tmp_path):
    _unlocked(bench)
    f = tmp_path / "abimee"
    f.write_text("-----BEGIN RSA PRIVATE KEY-----\n%s\n-----END RSA PRIVATE KEY-----\n"
                 % base64.b64encode(b"\x30\x82pas du DER" * 8).decode())
    f.chmod(0o600)
    r = bench.run("import", str(f))
    assert r.returncode == 2 and "illisible par ssh-keygen" in one_error(r)
    assert not bench.calls() and not leftovers(bench)


def test_import_pkcs1_tmpfs_refuse(bench, ikeys, tmp_path):
    """Conversion sans tmpfs privé : rien copié, code 4."""
    _unlocked(bench)
    d = tmp_path / "pas-tmpfs"
    d.mkdir(mode=0o700)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "rsapem")), env={"XDG_RUNTIME_DIR": str(d)})
    assert r.returncode == 4 and "tmpfs privé" in one_error(r)
    assert not list(d.iterdir()) and not bench.calls()


# --- revue : pannes de création, ordre, invites, divers --------------------------------------------------

@pytest.mark.parametrize("fail, words", [
    ("create=corruptafter", "différent (privateKey)"),
    ("create=errorafter,sync=errorsecond", "état inconnu"),
    ("create=duperror", "2 éléments nouveaux"),
])
def test_import_creation_branches_sans_rejeu(bench, ikeys, tmp_path, fail, words):
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), env={"FAKE_BW_FAIL": fail})
    assert r.returncode == 4
    line = one_error(r)
    assert words in line, line
    assert len(creates(bench)) == 1, "rien rejoué"
    if fail == "create=corruptafter":
        [item] = new_items(bench)
        assert "supprimer l'élément %s" % item["id"] in line


@pytest.mark.skipif(not HAVE_OPENSSH, reason="ssh-agent/ssh-add absents")
def test_import_pkcs8_chiffree_puis_load(bench, ikeys, tmp_path):
    _unlocked(bench)
    askpass, _ = make_askpass(tmp_path, reply=PASSPHRASE)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "rsaenc")),
                  env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 0, r.stderr
    [item] = new_items(bench)
    assert item["sshKey"]["privateKey"] == ikeys["rsaenc"]["private"], "stockée chiffrée, telle quelle"
    assert "peut-être par d'autres clients Bitwarden" in r.stderr
    r, tty = bench.run_tty("load", "--id", item["id"], answer=PASSPHRASE, trigger=b"passphrase")
    assert r.returncode == 0, (r.stderr, tty)
    assert bench.agent_keys() == [ikeys["rsaenc"]["public"].split()[1]]


@pytest.mark.skipif(not HAVE_OPENSSH, reason="ssh-agent/ssh-add absents")
def test_import_crlf_normalisee_puis_load(bench, ikeys, tmp_path):
    """Fichier en CRLF : stocké en LF (ssh-add - refuse le CRLF, mesuré), puis chargeable."""
    _unlocked(bench)
    f = tmp_path / "crlf"
    f.write_bytes(ikeys["ed"]["private"].replace("\n", "\r\n").encode())
    f.chmod(0o600)
    before = snap(f)
    r = bench.run("import", str(f))
    assert r.returncode == 0, r.stderr
    [item] = new_items(bench)
    assert item["sshKey"]["privateKey"] == ikeys["ed"]["private"]
    assert snap(f) == before
    r = bench.run("--nointeraction", "load", "--id", item["id"])
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == [ikeys["ed"]["public"].split()[1]]


def test_import_askpass_sans_reponse_delai(bench, ikeys, tmp_path):
    _unlocked(bench)
    slow = tmp_path / "lent"
    pidfile = tmp_path / "lent.pid"
    slow.write_text("#!/bin/sh\necho $$ > '%s'\nexec sleep 60\n" % pidfile)
    slow.chmod(0o755)
    t0 = time.monotonic()
    r = bench.run("import", "--decrypt", str(copy_key(ikeys, tmp_path, "edenc")),
                  env={"SSH_ASKPASS": str(slow), "SSH_ASKPASS_REQUIRE": "force", "SSHVAULT_PROMPT_TIMEOUT": "1"})
    assert r.returncode == 3 and "aucune passphrase acceptée" in r.stderr
    assert time.monotonic() - t0 < 40
    assert not creates(bench) and not new_items(bench) and not leftovers(bench)
    assert _gone([int(pidfile.read_text())]), "askpass tué"


def test_import_ssh_keygen_introuvable(bench, ikeys, tmp_path):
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "rsapem")), env={"SSHVAULT_SSH_KEYGEN": "/nonexistent/kg"})
    assert r.returncode == 4 and "introuvable" in one_error(r)
    assert not bench.calls() and not leftovers(bench)


def test_import_attrape_tout_deux_avertissements(bench, ikeys, tmp_path):
    from sshvault.sshconfig import CATCH_ALL_WARNING
    _unlocked(bench)
    r = bench.run("import", str(copy_key(ikeys, tmp_path, "ed")), "--hosts", "*")
    assert r.returncode == 0, r.stderr
    assert r.stderr.count(CATCH_ALL_WARNING) == 2


@pytest.mark.parametrize("what", ["dossier", "mode000"])
def test_import_pub_voisine_inutilisable(bench, ikeys, tmp_path, what):
    _unlocked(bench)
    f = copy_key(ikeys, tmp_path, "ed", with_pub=False)
    pub = f.with_name("ed.pub")
    if what == "dossier":
        pub.mkdir()
    else:
        pub.write_text(ikeys["ed"]["public"] + "\n")
        pub.chmod(0)
    try:
        r = bench.run("import", str(f))
    finally:
        pub.chmod(0o700)
    assert r.returncode == 0, r.stderr
    assert "ed.pub illisible" in r.stderr and "ignorée" in r.stderr


def test_import_orphelin_pid_reutilise_supprime(bench, ikeys, tmp_path):
    """Sous-dossier d'un import tué dont le pid est réutilisé par un processus vivant : son
    verrou est libre, il est supprimé."""
    _unlocked(bench)
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700, exist_ok=True)
    live = subprocess.Popen(["sleep", "30"])
    try:
        orphan = d / ("import.%d.abc" % live.pid)
        orphan.mkdir(mode=0o700)
        (orphan / ".lock").write_text("")
        (orphan / "key").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
        r = bench.run("import", str(copy_key(ikeys, tmp_path, "rsapem")))
        assert r.returncode == 0, r.stderr
        assert not orphan.exists() and not leftovers(bench)
    finally:
        live.kill()
        live.wait()


def test_import_dossier_tenu_garde(bench, ikeys, tmp_path):
    """Sous-dossier d'un autre import en cours (verrou tenu) : jamais supprimé."""
    import fcntl
    _unlocked(bench)
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700, exist_ok=True)
    held = d / "import.1.tenu"
    held.mkdir(mode=0o700)
    fd = os.open(str(held / ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        r = bench.run("import", str(copy_key(ikeys, tmp_path, "rsapem")))
        assert r.returncode == 0, r.stderr
        assert held.exists()
    finally:
        os.close(fd)
        shutil.rmtree(str(held))


def test_import_askpass_prefer_avec_stdin_terminal(bench, ikeys, tmp_path):
    """SSH_ASKPASS_REQUIRE=prefer, DISPLAY, askpass utilisable, stdin terminal : ssh-keygen prend
    l'askpass (readpass.c) ; aucune invite sur le terminal, écho intact."""
    from bench import pty_run
    _unlocked(bench)
    askpass, calls = make_askpass(tmp_path, reply=PASSPHRASE)
    env = dict(bench.env, SSH_ASKPASS=askpass, SSH_ASKPASS_REQUIRE="prefer", DISPLAY=":99")
    f = copy_key(ikeys, tmp_path, "edenc")
    r = pty_run([["sh", "-c", 'exec "$0" -m sshvault import --decrypt "$1" < /dev/tty', sys.executable, str(f)]],
                env, trigger=rb"passphrase", timeout=30)
    assert r.returncode == 0, (r.stderr, r.screen)
    assert len(calls.read_text().splitlines()) == 1 and r.prompts == 0 and r.echo is True


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl absent")
def test_import_pkcs8_chiffree_ed25519_openssl_refusee(bench, tmp_path):
    _unlocked(bench)
    f = tmp_path / "edossle"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-aes256", "-pass", "pass:" + PASSPHRASE,
                    "-out", str(f)], check=True, capture_output=True)
    f.chmod(0o600)
    askpass, _ = make_askpass(tmp_path, reply=PASSPHRASE)
    r = bench.run("import", str(f), env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 2, r.stderr
    assert "RSA seulement" in r.stderr and not creates(bench) and not leftovers(bench)


def test_import_pire_code_garde_si_le_coffre_echoue(bench, ikeys, tmp_path):
    """Refus local à 4 (ssh-keygen introuvable), puis coffre verrouillé (3) : code 4."""
    bench.set_state(logged_in=True)
    r = bench.run("--nointeraction", "import", str(copy_key(ikeys, tmp_path, "rsapem")),
                  str(copy_key(ikeys, tmp_path, "ed")), env={"SSHVAULT_SSH_KEYGEN": "/nonexistent/kg"})
    assert r.returncode == 4
    assert "introuvable" in r.stderr and "verrouillé" in r.stderr


def test_import_sigterm_apres_une_creation_avec_hotes(bench, ikeys, tmp_path):
    _unlocked(bench)
    a, b = copy_key(ikeys, tmp_path, "ed"), copy_key(ikeys, tmp_path, "rsa2048")
    e = dict(bench.env, FAKE_BW_FAIL="create=hangsecond", SSHVAULT_BW_TIMEOUT="60")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "import", "--hosts", "x.example", str(a), str(b)], env=e,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    deadline = time.monotonic() + 30
    while not (bench.pids.exists() and len(bench.pids.read_text().split()) == 2) and time.monotonic() < deadline:
        time.sleep(0.1)
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=20)
    assert p.returncode == 130
    [item] = new_items(bench)
    assert "importée : imp-ed" in out
    assert "clés créées : « imp-ed » %s ; ssh_config non régénéré : lancer « sshvault ssh-config »" % item["id"] in err
    assert _gone([int(x) for x in bench.pids.read_text().split()])


@pytest.mark.parametrize("req, stdin_tty, fg, usable, want", [
    ("prefer", True, True, True, "askpass"),   # readpass.c : prefer + askpass permis → askpass
    ("force", True, True, True, "askpass"),
    ("", True, True, True, "stdin"),           # stdin terminal : le terminal
    ("", False, True, True, "askpass"),        # stdin /dev/null : askpass permis
    ("prefer", True, True, False, "stdin"),    # askpass inutilisable : le terminal
    ("", False, True, False, "tty"),
    ("", False, False, False, None),
])
def test_passphrase_mode_regles_readpass(monkeypatch, tmp_path, req, stdin_tty, fg, usable, want):
    from sshvault import keyfile
    askpass, _ = make_askpass(tmp_path)
    env = {"DISPLAY": ":99", "SSH_ASKPASS": askpass if usable else "/nonexistent/askpass", "PATH": "/usr/bin:/bin"}
    if req:
        env["SSH_ASKPASS_REQUIRE"] = req
    monkeypatch.setattr(keyfile, "tty_available", lambda: fg)
    monkeypatch.setattr(keyfile.os, "isatty", lambda fd: stdin_tty)
    assert keyfile.passphrase_mode(env) == want

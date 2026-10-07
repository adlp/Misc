"""ssh_config généré (CAP-5) et ligne Include : une ligne de test par ligne de la matrice de la
story 4, plus la validation réelle par l'OpenSSH du poste (`ssh -G -F <config de test>`, et
`ssh -v` arrêté avant l'authentification pour voir le `.pub` réellement chargé)."""
import os
import pathlib
import shutil
import stat
import subprocess

import pytest

from bench import ID_BASTION, ID_PERSO, ID_PROD
from sshvault import sshconfig
from sshvault.backend import SshKeyItem

SSH = shutil.which("ssh")
needs_ssh = pytest.mark.skipif(SSH is None, reason="client ssh absent")


def _ssh_version():
    if SSH is None:
        return ""
    r = subprocess.run([SSH, "-V"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return (r.stderr + r.stdout).strip()


#: Témoins d'une mesure faite sur cette version précise (comportement d'OpenSSH, pas de sshvault).
measured_89 = pytest.mark.skipif("OpenSSH_8.9p1" not in _ssh_version(),
                                 reason="mesure propre à OpenSSH 8.9p1 (%s)" % (_ssh_version() or "ssh absent"))


def mode(p):
    return stat.S_IMODE(os.lstat(str(p)).st_mode)


def one_line_error(r):
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    assert len(lines) == 1, r.stderr
    return lines[0]


def unlocked(bench):
    bench.unlocked("keyring" if bench.ring else "file")


def sv_dir(bench):
    return bench.home / ".ssh" / "sshvault"


def pub_name(bench, key):
    return sshconfig.fp_filename(bench.keys[key]["fingerprint"])


def rehome(bench, name):
    """HOME de test au nom donné (espace, %…), dans le dossier du test."""
    h = bench.tmp / name
    h.mkdir()
    bench.home = h
    bench.appdata = h / ".local" / "share" / "sshvault" / "bw"
    bench.env["HOME"] = bench.env["SSHVAULT_SSH_HOME"] = str(h)


def reruntime(bench, prefix):
    """XDG_RUNTIME_DIR de test au préfixe donné (tmpfs privé exigé) ; l'ancien est supprimé."""
    shutil.rmtree(str(bench.runtime), ignore_errors=True)
    import tempfile
    d = tempfile.mkdtemp(prefix=prefix, dir="/dev/shm")
    os.chmod(d, 0o700)
    bench.runtime = pathlib.Path(d)
    bench.env["XDG_RUNTIME_DIR"] = d


def ssh_G(tmp_path, host, include, after="", opts=()):
    """`ssh -G -F <fichier de test qui inclut la config>` : [(clé, valeur)]. `after` : config
    de l'utilisateur placée après la ligne Include."""
    main = tmp_path / "ssh_config_de_test"
    main.write_text('Include "%s"\n%s' % (include, after))
    main.chmod(0o600)
    r = subprocess.run([SSH, "-G", "-F", str(main), *opts, host], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=30)
    assert r.returncode == 0, r.stderr
    return [tuple(l.split(" ", 1)) for l in r.stdout.splitlines()]


def ssh_loaded_identities(tmp_path, host, proxy_opt=True):
    """Fichiers d'identité que ssh charge vraiment (chemins développés), par `ssh -vvv` dont
    la connexion s'arrête aussitôt (ProxyCommand true) : [(chemin, type)]. Sans `proxy_opt`,
    le ProxyCommand vient du fichier de test (sauts ProxyJump : -vvv et -F sont transmis)."""
    main = tmp_path / "ssh_config_de_test"
    r = subprocess.run([SSH, "-vvv", "-F", str(main)] + (["-o", "ProxyCommand=true"] if proxy_opt else [])
                       + ["-o", "BatchMode=yes", "-o", "UserKnownHostsFile=/dev/null",
                          "-o", "GlobalKnownHostsFile=/dev/null", host],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
    out = []
    for l in r.stderr.splitlines():
        if l.startswith("debug1: identity file ") and not l.split(" type ")[0].endswith("-cert"):
            path, typ = l[len("debug1: identity file "):].rsplit(" type ", 1)
            out.append((path, int(typ)))
    return out


def values(conf, key):
    return [v for k, v in conf if k == key]


# --- unitaires ----------------------------------------------------------------------------

def test_fp_filename_base64url():
    assert sshconfig.fp_filename("SHA256:ab/c+d") == "SHA256:ab_c-d.pub"


@pytest.mark.parametrize("path,expected", [("/a b/c%d", '"/a b/c%%d"'), ("/x/y", '"/x/y"')])
def test_quote_path(path, expected):
    assert sshconfig.quote_path(path, "x") == expected


@pytest.mark.parametrize("path", ['/a"b', "/a\\b", "/a${HOME}", "/a\nb", "relatif"])
def test_quote_path_refuse(path):
    with pytest.raises(sshconfig.SshConfigError):
        sshconfig.quote_path(path, "x")


def test_build_ordre_et_forme(keys, tmp_path):
    paths = sshconfig.Paths(str(tmp_path))
    items = [SshKeyItem("b", "beta", keys["perso"]["public"], "", ("b.example",)),
             SshKeyItem("a2", "Alpha", keys["prod"]["public"], "", ("A.example", "a.example", "*.lab")),
             SshKeyItem("a1", "alpha", keys["bastion"]["public"], "", ("x.example",)),
             SshKeyItem("z", "sans hôte", keys["perso"]["public"], "", ())]
    plan = sshconfig.build(items, paths, "/run/s/agent.sock")
    text = plan.config.decode()
    assert [l for l in text.splitlines() if l.startswith("Match ")] == [
        "Match originalhost x.example", "Match originalhost a.example,*.lab", "Match originalhost b.example"]
    assert plan.blocks == 3 and len(plan.pubs) == 3 and not plan.warnings
    assert text.startswith(sshconfig.HEADER)
    assert ('    IdentityAgent "/run/s/agent.sock"\n    IdentityFile "%s/.ssh/sshvault/pub/%s"\n'
            "    IdentitiesOnly yes\n" % (tmp_path, sshconfig.fp_filename(keys["bastion"]["fingerprint"]))) in text
    assert plan.pubs[sshconfig.fp_filename(keys["prod"]["fingerprint"])] == \
        (" ".join(keys["prod"]["public"].split()[:2]) + "\n").encode()


def test_build_jamais_de_topologie_ni_match_exec(keys, tmp_path):
    items = [SshKeyItem("a", "a", keys["prod"]["public"], "", ("a.example",))]
    text = sshconfig.build(items, sshconfig.Paths(str(tmp_path)), "/run/s/agent.sock").config.decode()
    for word in ("Host", "HostName", "User", "Port", "ProxyJump", "ProxyCommand"):
        assert not any(l.split()[:1] == [word] for l in text.splitlines()), word
    matches = [l for l in text.splitlines() if l.startswith("Match")]
    assert matches == ["Match originalhost a.example"] and "exec" not in text


def test_build_nom_de_l_element_nettoye(keys, tmp_path):
    items = [SshKeyItem("a", "x\nHost *\n  ProxyCommand evil", keys["prod"]["public"], "", ("a.example",))]
    text = sshconfig.build(items, sshconfig.Paths(str(tmp_path)), "/run/s/agent.sock").config.decode()
    assert [l for l in text.splitlines() if not l.startswith("#")] == [
        "", "Match originalhost a.example", '    IdentityAgent "/run/s/agent.sock"',
        '    IdentityFile "%s/.ssh/sshvault/pub/%s"' % (tmp_path, sshconfig.fp_filename(keys["prod"]["fingerprint"])),
        "    IdentitiesOnly yes"]
    assert "# x\\x0aHost *\\x0a  ProxyCommand evil a\n" in text


def test_build_cle_publique_illisible(keys, tmp_path):
    items = [SshKeyItem("a", "a", "pas une clé", "", ("a.example",)),
             SshKeyItem("b", "b", keys["prod"]["public"], "", ("b.example",))]
    plan = sshconfig.build(items, sshconfig.Paths(str(tmp_path)), "/run/s/agent.sock")
    assert plan.blocks == 1 and "clé publique illisible" in plan.warnings[0]


# --- génération par la CLI ----------------------------------------------------------------

def test_ssh_config_genere(bench):
    unlocked(bench)
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    d = sv_dir(bench)
    sock = bench.runtime / "sshvault" / "agent.sock"
    exe = bench.exe
    assert (d / "config").read_text() == (
        sshconfig.HEADER
        + "\n# Bastion RSA %s\nMatch originalhost bastion,jump exec \"'%s' ensure --id %s\"\n"
          "Match originalhost bastion,jump\n    IdentityAgent \"%s\"\n    IdentityFile \"%s\"\n"
          "    IdentitiesOnly yes\n" % (ID_BASTION, exe, ID_BASTION, sock, d / "pub" / pub_name(bench, "bastion"))
        + "\n# Serveur Prod %s\nMatch originalhost prod.example.com,*.lab.example exec \"'%s' ensure --id %s\"\n"
          "Match originalhost prod.example.com,*.lab.example\n    IdentityAgent \"%s\"\n"
          "    IdentityFile \"%s\"\n    IdentitiesOnly yes\n" % (ID_PROD, exe, ID_PROD, sock,
                                                                d / "pub" / pub_name(bench, "prod")))
    assert sorted(os.listdir(d / "pub")) == sorted([pub_name(bench, "bastion"), pub_name(bench, "prod")])
    assert (d / "pub" / pub_name(bench, "prod")).read_text().split() == bench.keys["prod"]["public"].split()[:2]
    assert mode(bench.home / ".ssh") == 0o700 and mode(d) == 0o700 and mode(d / "pub") == 0o700
    assert mode(d / "config") == 0o600
    assert all(mode(d / "pub" / n) == 0o600 for n in os.listdir(d / "pub"))
    assert "PRIVATE" not in "".join(p.read_text() for p in d.rglob("*") if p.is_file())
    assert "écrit (2 blocs)" in r.stdout and "2 écrites" in r.stdout
    # ~/.ssh/config absent : on prévient seulement
    assert "n'inclut pas" in r.stderr and "ssh-config install" in r.stderr
    assert not (bench.home / ".ssh" / "config").exists()
    # aucune écriture dans le coffre, une seule lecture
    assert [c["argv"][1:] for c in bench.calls()] == [["list", "items"]]


def test_ssh_config_sans_changement_rien_reecrit(bench):
    unlocked(bench)
    assert bench.run("ssh-config").returncode == 0
    files = [p for p in sv_dir(bench).rglob("*")]
    before = {p: (os.lstat(p).st_ino, os.lstat(p).st_mtime_ns) for p in files}
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    assert "inchangé (2 blocs)" in r.stdout and "clés publiques" not in r.stdout
    assert {p: (os.lstat(p).st_ino, os.lstat(p).st_mtime_ns) for p in sv_dir(bench).rglob("*")} == before


def test_ssh_config_reecrit_un_fichier_aux_mauvais_droits(bench):
    unlocked(bench)
    assert bench.run("ssh-config").returncode == 0
    (sv_dir(bench) / "config").chmod(0o644)
    r = bench.run("ssh-config")
    assert "config : écrit" in r.stdout and mode(sv_dir(bench) / "config") == 0o600


def test_ssh_config_aucun_element_associe(bench):
    for it in bench.items:
        it["fields"] = None
    bench.write_vault()
    unlocked(bench)
    pub = sv_dir(bench) / "pub"
    pub.mkdir(parents=True)
    (pub / "SHA256:ancienne.pub").write_text("ssh-ed25519 AAAA\n")
    (pub / ".config.123.tmp").write_text("reste")
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    assert (sv_dir(bench) / "config").read_text() == sshconfig.HEADER
    assert os.listdir(pub) == []
    assert "0 écrite, 2 supprimées" in r.stdout


def test_ssh_config_purge_apres_hosts_remove(bench):
    unlocked(bench)
    assert bench.run("ssh-config").returncode == 0
    r = bench.run("hosts", "remove", "--id", ID_BASTION, "bastion", "jump")
    assert r.returncode == 0, r.stderr
    assert os.listdir(sv_dir(bench) / "pub") == [pub_name(bench, "prod")]
    assert "bastion" not in (sv_dir(bench) / "config").read_text().lower()


def test_ssh_config_hote_invalide_dans_le_coffre(bench):
    bench.items[2]["fields"][1]["value"] = "Bastion, mauvais hote"
    bench.write_vault()
    unlocked(bench)
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    assert "« Bastion RSA » (%s) : hôte invalide « mauvais hote » : élément sauté" % ID_BASTION in r.stderr
    text = (sv_dir(bench) / "config").read_text()
    assert "Match originalhost prod.example.com,*.lab.example\n" in text
    assert "bastion" not in text.lower()
    assert os.listdir(sv_dir(bench) / "pub") == [pub_name(bench, "prod")]


@needs_ssh
def test_ssh_config_hote_dans_deux_elements(bench, tmp_path):
    bench.items[1]["fields"] = [{"name": "sshvault-hosts", "value": "PROD.example.com", "type": 0, "linkedId": None}]
    bench.write_vault()
    unlocked(bench)
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    assert "hôte « prod.example.com » porté par 2 éléments" in r.stderr
    text = (sv_dir(bench) / "config").read_text()
    blocks = [l for l in text.splitlines() if l.startswith("Match ") and " exec " not in l]
    assert sum(l.count("prod.example.com") for l in blocks) == 2
    pub = sv_dir(bench) / "pub"
    for host in ("prod.example.com", "Prod.Example.COM"):
        conf = ssh_G(tmp_path, host, sv_dir(bench) / "config")
        # blocs triés par nom : « clé perso » avant « Serveur Prod »
        assert values(conf, "identityfile") == [str(pub / pub_name(bench, "perso")),
                                                str(pub / pub_name(bench, "prod"))]


def test_ssh_config_print_n_ecrit_rien(bench):
    unlocked(bench)
    r = bench.run("ssh-config", "--print")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith(sshconfig.HEADER) and "Match originalhost bastion,jump\n" in r.stdout
    assert not (bench.home / ".ssh").exists()


def test_ssh_config_check(bench):
    unlocked(bench)
    r = bench.run("ssh-config", "--check")
    assert r.returncode == 1 and "config : absent" in r.stdout and "n'inclut pas" in r.stdout
    assert not (bench.home / ".ssh").exists()
    assert bench.run("ssh-config").returncode == 0
    r = bench.run("ssh-config", "--check")
    lines = r.stdout.splitlines()
    assert r.returncode == 1 and len(lines) == 1 and "n'inclut pas" in lines[0]
    assert bench.run("ssh-config", "install").returncode == 0
    r = bench.run("ssh-config", "--check")
    assert r.returncode == 0, r.stdout
    assert r.stdout.startswith("à jour")
    (sv_dir(bench) / "pub" / "SHA256:en-trop.pub").write_text("x")
    r = bench.run("ssh-config", "--check")
    assert r.returncode == 1 and "en trop" in r.stdout
    assert (sv_dir(bench) / "pub" / "SHA256:en-trop.pub").exists(), "--check n'écrit rien"


def test_ssh_config_install_exclut_check(bench):
    r = bench.run("ssh-config", "install", "--check")
    assert r.returncode == 2


# --- validation réelle par OpenSSH --------------------------------------------------------

@needs_ssh
def test_ssh_G_agent_dedie_une_seule_cle(bench, tmp_path):
    """Critère : identityagent = socket dédié, une seule identityfile, identitiesonly yes ;
    chemins avec espace et % (HOME et XDG_RUNTIME_DIR)."""
    rehome(bench, "ho me%h")
    reruntime(bench, "sshvault-test-run-a b%c-")
    unlocked(bench)
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    cfg = sv_dir(bench) / "config"
    assert "%%" in cfg.read_text()
    sock = str(bench.runtime / "sshvault" / "agent.sock")
    for host, key in (("prod.example.com", "prod"), ("x.lab.example", "prod"), ("jump", "bastion")):
        conf = ssh_G(tmp_path, host, cfg)
        assert values(conf, "identityagent") == [sock]
        pub = str(sv_dir(bench) / "pub" / pub_name(bench, key))
        # ssh -G affiche IdentityFile tel qu'écrit (développé au chargement) : %% attendu
        assert values(conf, "identityfile") == [pub.replace("%", "%%")]
        assert values(conf, "identitiesonly") == ["yes"]
        # chargé pour de vrai : chemin développé, clé lue (type ≠ -1)
        loaded = ssh_loaded_identities(tmp_path, host)
        assert len(loaded) == 1 and loaded[0][0] == pub and loaded[0][1] != -1, loaded
    conf = ssh_G(tmp_path, "autre.example", cfg)
    assert values(conf, "identitiesonly") == ["no"] and not values(conf, "identityagent")


@needs_ssh
@pytest.mark.parametrize("host,key", [("prod.example.com", "prod"), ("PROD.EXAMPLE.COM", "prod"),
                                      ("Prod.Example.Com", "prod"), ("X.LAB.Example", "prod"),
                                      ("JUMP", "bastion"), ("Jump", "bastion"), ("bAsTiOn", "bastion")])
def test_ssh_G_casse_indifferente(bench, tmp_path, host, key):
    """Mesuré (OpenSSH 8.9p1) : `Host foo` ne s'applique pas à `ssh FOO` ; `Match originalhost`
    compare le nom tapé sans tenir compte de la casse, motif glob compris."""
    unlocked(bench)
    assert bench.run("ssh-config").returncode == 0
    conf = ssh_G(tmp_path, host, sv_dir(bench) / "config")
    assert values(conf, "identityfile") == [str(sv_dir(bench) / "pub" / pub_name(bench, key))]
    assert values(conf, "identitiesonly") == ["yes"]
    assert values(conf, "identityagent") == [str(bench.runtime / "sshvault" / "agent.sock")]


@needs_ssh
@measured_89
def test_ssh_G_host_serait_sensible_a_la_casse(tmp_path):
    """Témoin de la mesure qui a fait choisir `Match originalhost` : la forme `Host` échoue."""
    inc = tmp_path / "host_form"
    inc.write_text("Host prod.example.com\n    IdentitiesOnly yes\n")
    inc.chmod(0o600)
    assert values(ssh_G(tmp_path, "prod.example.com", inc), "identitiesonly") == ["yes"]
    assert values(ssh_G(tmp_path, "PROD.example.com", inc), "identitiesonly") == ["no"]


@needs_ssh
def test_ssh_G_nom_tape_pas_le_hostname(bench, tmp_path):
    """Un bloc de l'utilisateur avec HostName, après la ligne Include : notre bloc s'applique
    au nom tapé (originalhost), pas à l'adresse."""
    unlocked(bench)
    assert bench.run("ssh-config").returncode == 0
    user = "Host jump\n    HostName 10.0.0.5\n    User alice\n"
    pub = str(sv_dir(bench) / "pub" / pub_name(bench, "bastion"))
    conf = ssh_G(tmp_path, "jump", sv_dir(bench) / "config", user)
    assert values(conf, "hostname") == ["10.0.0.5"] and values(conf, "user") == ["alice"]
    assert values(conf, "identityfile") == [pub] and values(conf, "identitiesonly") == ["yes"]
    conf = ssh_G(tmp_path, "10.0.0.5", sv_dir(bench) / "config", user)
    assert values(conf, "identitiesonly") == ["no"] and pub not in values(conf, "identityfile")
    # HostName déjà connu avant notre bloc (-o) : `Match host` comparerait 10.0.0.5, originalhost « jump »
    conf = ssh_G(tmp_path, "jump", sv_dir(bench) / "config", opts=["-o", "HostName=10.0.0.5"])
    assert values(conf, "hostname") == ["10.0.0.5"] and values(conf, "identityfile") == [pub]


@needs_ssh
def test_ssh_G_saut_proxyjump(bench, tmp_path):
    """Saut ProxyJump nommé en casse mélangée : `ssh -G` du saut, puis le vrai sous-processus
    du saut (`ssh -W … Jump`, -F et -vvv transmis) charge la clé du bastion."""
    unlocked(bench)
    assert bench.run("ssh-config").returncode == 0
    pub = str(sv_dir(bench) / "pub" / pub_name(bench, "bastion"))
    user = "Host cible\n    ProxyJump Jump\nHost *\n    ProxyCommand true\n"
    conf = ssh_G(tmp_path, "cible", sv_dir(bench) / "config", user)
    assert values(conf, "proxyjump") == ["Jump"] and values(conf, "identitiesonly") == ["no"]
    conf = ssh_G(tmp_path, "Jump", sv_dir(bench) / "config", user)
    assert values(conf, "identityfile") == [pub] and values(conf, "identitiesonly") == ["yes"]
    loaded = ssh_loaded_identities(tmp_path, "cible", proxy_opt=False)
    assert (pub, 0) in loaded, loaded  # bastion : RSA, type 0


@needs_ssh
@measured_89
def test_ssh_G_premiere_valeur_l_emporte(bench, tmp_path):
    """Défauts de l'utilisateur (`Host *`) après la ligne Include : IdentityAgent et
    IdentitiesOnly de sshvault l'emportent ; IdentityFile, lui, se cumule (mesuré)."""
    unlocked(bench)
    assert bench.run("ssh-config").returncode == 0
    user = "Host *\n    IdentitiesOnly no\n    IdentityAgent /tmp/autre.sock\n"
    conf = ssh_G(tmp_path, "Prod.Example.Com", sv_dir(bench) / "config", user)
    assert values(conf, "identitiesonly") == ["yes"]
    assert values(conf, "identityagent") == [str(bench.runtime / "sshvault" / "agent.sock")]
    assert values(conf, "identityfile") == [str(sv_dir(bench) / "pub" / pub_name(bench, "prod"))]
    conf = ssh_G(tmp_path, "autre.example", sv_dir(bench) / "config", user)
    assert values(conf, "identityagent") == ["/tmp/autre.sock"] and values(conf, "identitiesonly") == ["no"]
    # IdentityFile de l'utilisateur pour tous les hôtes : ajouté après le nôtre
    conf = ssh_G(tmp_path, "prod.example.com", sv_dir(bench) / "config", "Host *\n    IdentityFile /k/id_user\n")
    assert values(conf, "identityfile") == [str(sv_dir(bench) / "pub" / pub_name(bench, "prod")), "/k/id_user"]


def test_ssh_config_chemin_inutilisable(bench):
    rehome(bench, 'gui"llemet')
    unlocked(bench)
    r = bench.run("ssh-config")
    assert r.returncode == 4
    assert "inutilisable dans un ssh_config" in one_line_error(r)
    assert not (bench.home / ".ssh").exists()


def test_ssh_config_sans_xdg_runtime_prive(bench, tmp_path):
    unlocked(bench)
    d = tmp_path / "pas-tmpfs"
    d.mkdir(mode=0o700)
    r = bench.run("ssh-config", env={"XDG_RUNTIME_DIR": str(d)})
    assert r.returncode == 4 and "XDG_RUNTIME_DIR" in r.stderr
    assert not (bench.home / ".ssh" / "sshvault" / "config").exists()


# --- ligne Include (ssh-config install) ---------------------------------------------------

def include(bench):
    return 'Include "%s"' % (sv_dir(bench) / "config")


def test_install_config_absent(bench):
    r = bench.run("ssh-config", "install")
    assert r.returncode == 0, r.stderr
    cfg = bench.home / ".ssh" / "config"
    assert cfg.read_text() == include(bench) + "\n"
    assert mode(cfg) == 0o600 and mode(bench.home / ".ssh") == 0o700
    assert not (bench.home / ".ssh" / "config.sshvault.bak").exists()
    assert "n'existe pas encore" in r.stderr
    assert not bench.calls(), "install n'appelle pas le coffre"


def test_install_sans_include(bench):
    ssh = bench.home / ".ssh"
    ssh.mkdir(mode=0o755)
    ssh.chmod(0o755)
    cfg = ssh / "config"
    orig = "Host *\n    ServerAliveInterval 30\n# fin sans retour à la ligne"
    cfg.write_text(orig)
    cfg.chmod(0o644)
    r = bench.run("ssh-config", "install")
    assert r.returncode == 0, r.stderr
    assert "ajoutée" in r.stdout
    assert cfg.read_text() == include(bench) + "\n" + orig
    assert mode(cfg) == 0o644, "mode conservé"
    assert mode(ssh) == 0o755, "~/.ssh existant non modifié"
    bak = ssh / "config.sshvault.bak"
    assert bak.read_text() == orig and mode(bak) == 0o600
    assert sorted(os.listdir(ssh)) == ["config", "config.sshvault.bak"]


@pytest.mark.parametrize("line", ['Include "{cfg}"', "  include {tilde}", "Include={cfg} # commentaire",
                                  "Include sshvault/config"])
def test_install_include_plus_bas_deplace(bench, line):
    ssh = bench.home / ".ssh"
    ssh.mkdir(mode=0o700)
    cfg = ssh / "config"
    line = line.format(cfg=sv_dir(bench) / "config", tilde="~/.ssh/sshvault/config")
    orig = "# en-tête\nServerAliveInterval 30\n%s\nHost b\n    Port 2222\n" % line
    cfg.write_text(orig)
    cfg.chmod(0o600)
    r = bench.run("ssh-config", "install")
    assert r.returncode == 0, r.stderr
    assert "déplacée" in r.stdout
    assert cfg.read_text() == include(bench) + "\n# en-tête\nServerAliveInterval 30\nHost b\n    Port 2222\n"
    assert (ssh / "config.sshvault.bak").read_text() == orig


def test_install_idempotent(bench):
    assert bench.run("ssh-config", "install").returncode == 0
    cfg = bench.home / ".ssh" / "config"
    cfg.write_text(cfg.read_text() + "Host z\n    User y\n")
    st = os.stat(cfg)
    r = bench.run("ssh-config", "install")
    assert r.returncode == 0 and "déjà en tête" in r.stdout
    st2 = os.stat(cfg)
    assert (st2.st_ino, st2.st_mtime_ns) == (st.st_ino, st.st_mtime_ns)
    assert not (bench.home / ".ssh" / "config.sshvault.bak").exists()


def test_install_include_en_tete_sous_une_autre_forme(bench):
    ssh = bench.home / ".ssh"
    ssh.mkdir(mode=0o700)
    (ssh / "config").write_text("Include ~/.ssh/sshvault/config\nHost a\n")
    r = bench.run("ssh-config", "install")
    assert r.returncode == 0 and "déjà en tête" in r.stdout


def test_install_lien_symbolique_refuse(bench, tmp_path):
    ssh = bench.home / ".ssh"
    ssh.mkdir(mode=0o700)
    target = tmp_path / "dotfiles-config"
    target.write_text("Host a\n")
    (ssh / "config").symlink_to(target)
    r = bench.run("ssh-config", "install")
    assert r.returncode == 4
    assert "lien symbolique" in one_line_error(r)
    assert target.read_text() == "Host a\n" and os.path.islink(ssh / "config")
    assert sorted(os.listdir(ssh)) == ["config"]


def test_install_chemin_avec_pourcent_refuse(bench):
    rehome(bench, "ho%me")
    r = bench.run("ssh-config", "install")
    assert r.returncode == 4 and "inutilisable" in one_line_error(r)
    assert not (bench.home / ".ssh").exists()


def test_hosts_et_ssh_config_previennent_si_include_mal_place(bench):
    unlocked(bench)
    ssh = bench.home / ".ssh"
    ssh.mkdir(mode=0o700)
    (ssh / "config").write_text("User x\n" + include(bench) + "\n")
    r = bench.run("ssh-config")
    assert r.returncode == 0 and "pas en tête" in r.stderr
    r = bench.run("hosts", "add", "--id", ID_PERSO, "perso.example")
    assert r.returncode == 0 and "pas en tête" in r.stderr
    assert (ssh / "config").read_text() == "User x\n" + include(bench) + "\n", "jamais modifié sans install"
    assert bench.run("ssh-config", "install").returncode == 0
    r = bench.run("ssh-config")
    assert r.returncode == 0 and r.stderr == ""


def test_rien_ecrit_hors_du_home_de_test(bench):
    """Critère : aucun fichier écrit hors des HOME de test (le ~/.ssh réel est comparé)."""
    real = pathlib.Path(os.path.expanduser("~")) / ".ssh"

    def snap():
        if not real.exists():
            return None
        return {p.name: (os.lstat(p).st_ino, os.lstat(p).st_mtime_ns, os.lstat(p).st_size) for p in real.iterdir()}
    before = snap()
    unlocked(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("ssh-config", "install").returncode == 0
    assert bench.run("hosts", "add", "--id", ID_PERSO, "perso.example").returncode == 0
    assert snap() == before
    written = {str(p.relative_to(bench.tmp)) for p in bench.tmp.rglob("*") if p.is_file()}
    assert {w for w in written if not w.startswith("home/")} <= {
        "server/vault.json", "bw.log", "bin/bw", "bin/ssh-add", "known_hosts", "exe/sshvault"}


# --- revue : fichiers non ordinaires, verrou, prérequis, Include, chemins, --check ----------

import socket as _socket  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from bench import ssh_item, start_agent, wait_gone  # noqa: E402


def _ssh_dir(bench):
    d = bench.home / ".ssh"
    d.mkdir(mode=0o700, exist_ok=True)
    return d


@pytest.mark.parametrize("kind", ["fifo", "dir"])
def test_config_utilisateur_non_ordinaire(bench, kind):
    """FIFO ou dossier à ~/.ssh/config : jamais bloqué ; install refuse (rc 4), ssh-config et
    hosts préviennent seulement."""
    unlocked(bench)
    cfg = _ssh_dir(bench) / "config"
    os.mkfifo(cfg) if kind == "fifo" else cfg.mkdir()
    r = bench.run("ssh-config", "install", timeout=20)
    assert r.returncode == 4 and "n'est pas un fichier ordinaire" in one_line_error(r)
    r = bench.run("ssh-config", timeout=20)
    assert r.returncode == 0 and "n'est pas un fichier ordinaire" in r.stderr
    r = bench.run("hosts", "add", "--id", ID_PERSO, "perso.example", timeout=20)
    assert r.returncode == 0 and "n'est pas un fichier ordinaire" in r.stderr
    r = bench.run("ssh-config", "--check", timeout=20)
    assert r.returncode == 1 and "n'est pas un fichier ordinaire" in r.stdout
    assert _kind(cfg) == kind


def _kind(p):
    m = os.lstat(p).st_mode
    return "fifo" if stat.S_ISFIFO(m) else "dir" if stat.S_ISDIR(m) else "file"


@pytest.mark.parametrize("kind", ["fifo", "dir"])
@pytest.mark.parametrize("target", ["config", "pub"])
def test_chemin_genere_non_ordinaire(bench, kind, target):
    unlocked(bench)
    d = sv_dir(bench)
    (d / "pub").mkdir(parents=True)
    p = d / "config" if target == "config" else d / "pub" / pub_name(bench, "prod")
    os.mkfifo(p) if kind == "fifo" else p.mkdir()
    r = bench.run("ssh-config", "--check", timeout=20)
    assert r.returncode == 1 and "%s : pas un fichier ordinaire" % p in r.stdout
    r = bench.run("ssh-config", timeout=20)
    assert r.returncode == 4 and "n'est pas un fichier ordinaire" in one_line_error(r)
    assert _kind(p) == kind


def test_regenerations_simultanees_verrou(keys, tmp_path, monkeypatch):
    """Deux apply() en même temps : sans verrou, la purge de l'un supprimait le temporaire de
    l'autre (même processus ici : le temporaire n'est pas « d'un autre vivant »)."""
    from sshvault import fsutil
    paths = sshconfig.Paths(str(tmp_path))
    items_a = [SshKeyItem("a", "a", keys["prod"]["public"], "", ("a.example",))]
    items_b = [SshKeyItem("b", "b", keys["perso"]["public"], "", ("b.example",))]
    real = fsutil.write_private
    entered = threading.Event()

    def slow(path, data):
        if path.endswith(sshconfig.fp_filename(keys["prod"]["fingerprint"])):
            tmp = os.path.join(os.path.dirname(path), ".%s.%d.tmp" % (os.path.basename(path), os.getpid()))
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            entered.set()
            time.sleep(0.5)
            os.unlink(tmp)  # le vrai write_private recrée son temporaire
        return real(path, data)
    monkeypatch.setattr(sshconfig, "write_private", slow)
    errors = []

    def run(items):
        try:
            sshconfig.apply(sshconfig.build(items, paths, "/run/s/agent.sock"), paths)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    ta = threading.Thread(target=run, args=(items_a,))
    ta.start()
    assert entered.wait(5)
    tb = threading.Thread(target=run, args=(items_b,))
    tb.start()
    time.sleep(0.1)
    assert tb.is_alive(), "le second attend le verrou"
    ta.join(10)
    tb.join(10)
    assert not errors
    # le dernier passé (b) gagne, sans temporaire restant
    assert os.listdir(paths.pub) == [sshconfig.fp_filename(keys["perso"]["fingerprint"])]
    assert "Match originalhost b.example" in open(paths.config).read()


def test_regenerations_simultanees_cli(bench):
    unlocked(bench)
    import subprocess as sp
    env = dict(bench.env)
    for _ in range(3):
        shutil.rmtree(str(sv_dir(bench)), ignore_errors=True)
        ps = [sp.Popen([sys.executable, "-m", "sshvault", "ssh-config"], env=env, stdout=sp.PIPE, stderr=sp.PIPE,
                       stdin=sp.DEVNULL, text=True) for _ in range(4)]
        outs = [p.communicate(timeout=60) for p in ps]
        assert [p.returncode for p in ps] == [0] * 4, outs
        assert sorted(os.listdir(sv_dir(bench) / "pub")) == sorted([pub_name(bench, "bastion"), pub_name(bench, "prod")])
        assert not [n for n in os.listdir(sv_dir(bench)) if n.endswith(".tmp")]


def test_live_tmp_d_un_autre_garde(tmp_path, keys):
    """Purge : un temporaire `.x.<pid>.tmp` d'un autre processus vivant n'est pas supprimé."""
    paths = sshconfig.Paths(str(tmp_path))
    pub = tmp_path / ".ssh" / "sshvault" / "pub"
    pub.mkdir(parents=True)
    other = subprocess.Popen(["sleep", "30"])
    try:
        (pub / (".a.pub.%d.tmp" % other.pid)).write_text("x")
        (pub / ".a.pub.999999999.tmp").write_text("x")
        res = sshconfig.apply(sshconfig.build([], paths, "/run/s/agent.sock"), paths)
        assert os.listdir(pub) == [".a.pub.%d.tmp" % other.pid]
        assert res.pubs_removed == [".a.pub.999999999.tmp"]
    finally:
        other.kill()
        other.wait()


# --- chemins : répertoire de passwd ---------------------------------------------------------

def test_default_paths_passwd_pas_home(monkeypatch):
    import pwd
    home = pwd.getpwuid(os.getuid()).pw_dir
    assert sshconfig.default_paths({"HOME": "/tmp/ailleurs"}).home == os.path.normpath(home)
    assert sshconfig.default_paths({"HOME": ""}).home == os.path.normpath(home)
    assert sshconfig.default_paths({sshconfig.HOME_ENV: "/x/y"}).home == "/x/y"


@pytest.mark.parametrize("pw_dir", ["", "/", "relatif", None])
def test_default_paths_home_inconnu(monkeypatch, pw_dir):
    import pwd

    def getpwuid(uid):
        if pw_dir is None:
            raise KeyError(uid)
        return type("P", (), {"pw_dir": pw_dir})()
    monkeypatch.setattr(pwd, "getpwuid", getpwuid)
    with pytest.raises(sshconfig.SshConfigError, match="répertoire personnel inconnu"):
        sshconfig.default_paths({})


# --- Include : en tête, conditionnel, formes --------------------------------------------------

def test_include_en_tete_apres_commentaires(bench):
    unlocked(bench)
    cfg = _ssh_dir(bench) / "config"
    cfg.write_text("# mes réglages\n\n   # indenté\n%s\nHost a\n" % include(bench))
    st = os.stat(cfg)
    r = bench.run("ssh-config", "install")
    assert r.returncode == 0 and "déjà en tête" in r.stdout
    assert os.stat(cfg).st_mtime_ns == st.st_mtime_ns
    r = bench.run("ssh-config")
    assert r.returncode == 0 and r.stderr == ""


@pytest.mark.parametrize("block", ["Host a", "Match user alice"])
def test_include_conditionnel_non_deplace(bench, block):
    unlocked(bench)
    cfg = _ssh_dir(bench) / "config"
    orig = "User x\n%s\n    %s\n" % (block, include(bench))
    cfg.write_text(orig)
    r = bench.run("ssh-config")
    assert r.returncode == 0 and "ligne 3 : Include conditionnel" in r.stderr
    r = bench.run("ssh-config", "install")
    assert r.returncode == 4 and "Include conditionnel" in one_line_error(r) and "non déplacée" in r.stderr
    assert cfg.read_text() == orig and not (cfg.parent / "config.sshvault.bak").exists()
    r = bench.run("ssh-config", "--check")
    assert r.returncode == 1 and "conditionnel" in r.stdout


def test_include_parmi_plusieurs_fichiers(bench):
    """`Include a.conf <le nôtre>` en tête : reconnu ; plus bas : ligne gardée (ssh ignore le
    doublon d'IdentityFile, mesuré), la nôtre ajoutée en tête."""
    unlocked(bench)
    cfg = _ssh_dir(bench) / "config"
    cfg.write_text("Include a.conf %s\nHost a\n" % (sv_dir(bench) / "config"))
    r = bench.run("ssh-config", "install")
    assert "déjà en tête" in r.stdout
    cfg.write_text("User x\nInclude a.conf ~/.ssh/sshvault/config\n")
    r = bench.run("ssh-config", "install")
    assert r.returncode == 0 and "ajoutée" in r.stdout
    assert cfg.read_text() == include(bench) + "\nUser x\nInclude a.conf ~/.ssh/sshvault/config\n"


def test_include_formes_reconnues(bench, tmp_path):
    unlocked(bench)
    ssh = _ssh_dir(bench)
    link = tmp_path / "lien-ssh"
    link.symlink_to(ssh)
    for spelling in ("~/.ssh/../.ssh/sshvault/config", "%s/sshvault/config" % link, "~/.ssh/sshvault/*",
                     "sshvault/./config"):
        (ssh / "config").write_text("Include %s\n" % spelling)
        r = bench.run("ssh-config", "install")
        assert "déjà en tête" in r.stdout, spelling


def test_lignes_coupees_sur_lf_seulement(bench):
    """\\x0c, \\x85, U+2028 ne coupent pas une ligne pour ssh : « Host a<FF>Include … » n'est pas
    un Include."""
    unlocked(bench)
    cfg = _ssh_dir(bench) / "config"
    for sep in ("\x0c", "\x85", " ", "\x1e"):
        cfg.write_text("Host a%s%s\n" % (sep, include(bench)))
        r = bench.run("ssh-config")
        assert "n'inclut pas" in r.stderr, repr(sep)


def test_install_course_a_la_creation(bench, monkeypatch, tmp_path):
    """~/.ssh/config créé par un autre entre l'examen et la création : pas écrasé."""
    paths = sshconfig.Paths(str(tmp_path))
    os.mkdir(paths.ssh_dir, 0o700)
    real = sshconfig._create

    def racing(path, data, mode):
        if path == paths.user_config and not os.path.exists(path):
            with open(path, "w") as f:
                f.write("Host z\n    User y\n")
        return real(path, data, mode)
    monkeypatch.setattr(sshconfig, "_create", racing)
    msg = sshconfig.install(paths)
    assert "ajoutée" in msg
    assert open(paths.user_config).read() == 'Include "%s"\nHost z\n    User y\n' % paths.config


def test_install_sauvegarde_jamais_ecrasee(bench):
    cfg = _ssh_dir(bench) / "config"
    cfg.write_text("User a\n")
    assert bench.run("ssh-config", "install").returncode == 0
    cfg.write_text("User b\n")
    r = bench.run("ssh-config", "install")
    assert r.returncode == 0 and "config.sshvault.bak.1" in r.stdout
    assert (cfg.parent / "config.sshvault.bak").read_text() == "User a\n"
    assert (cfg.parent / "config.sshvault.bak.1").read_text() == "User b\n"


def test_replace_garde_expect(tmp_path):
    p = tmp_path / "f"
    p.write_text("avant")
    st = os.stat(p)
    p.write_text("modifié ailleurs")
    with pytest.raises(sshconfig.SshConfigError, match="modifié pendant l'installation"):
        sshconfig._replace(str(p), b"nouveau", 0o600, os.getuid(), os.getgid(),
                           expect=(st.st_ino, st.st_size - 1, st.st_mtime_ns))
    assert p.read_text() == "modifié ailleurs" and os.listdir(tmp_path) == ["f"]


def test_install_conserve_le_proprietaire(tmp_path, monkeypatch):
    """Propriétaire (groupe) différent : fchown du temporaire vers celui du fichier."""
    paths = sshconfig.Paths(str(tmp_path))
    os.mkdir(paths.ssh_dir, 0o700)
    with open(paths.user_config, "w") as f:
        f.write("User x\n")
    st = os.stat(paths.user_config)
    calls = []
    real_getgid, real_fchown = os.getgid, os.fchown
    monkeypatch.setattr(os, "getgid", lambda: real_getgid() + 4242)
    monkeypatch.setattr(os, "fchown", lambda fd, u, g: (calls.append((u, g)), real_fchown(fd, u, g)))
    sshconfig.install(paths)
    assert (st.st_uid, st.st_gid) in calls
    assert (os.stat(paths.user_config).st_uid, os.stat(paths.user_config).st_gid) == (st.st_uid, st.st_gid)


def test_include_state_illisible(bench):
    unlocked(bench)
    cfg = _ssh_dir(bench) / "config"
    cfg.write_text("User x\n")
    cfg.chmod(0)
    try:
        r = bench.run("ssh-config")
        assert r.returncode == 0 and "illisible : ligne Include de sshvault non vérifiée" in r.stderr
    finally:
        cfg.chmod(0o600)


# --- --check aligné sur apply ---------------------------------------------------------------

def _generated(bench):
    unlocked(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("ssh-config", "install").returncode == 0
    r = bench.run("ssh-config", "--check")
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("damage,expected", [
    (lambda d, b: (d / "config").write_text((d / "config").read_text() + "# ajout\n"), "config : à réécrire"),
    (lambda d, b: (d / "config").chmod(0o644), "config : à réécrire"),
    (lambda d, b: (d / "pub" / pub_name(b, "prod")).unlink(), ".pub : absente"),
    (lambda d, b: (d / "pub").chmod(0o755), "pub : droits 0755 au lieu de 0700"),
    (lambda d, b: d.chmod(0o750), "sshvault : droits 0750 au lieu de 0700"),
    (lambda d, b: (shutil.rmtree(str(d / "pub")), (d / "pub").write_text("x")), "pub : pas un dossier"),
])
def test_check_differences(bench, damage, expected):
    _generated(bench)
    damage(sv_dir(bench), bench)
    r = bench.run("ssh-config", "--check")
    assert r.returncode == 1 and expected in r.stdout, r.stdout


def test_check_pub_illisible(bench):
    _generated(bench)
    pub = sv_dir(bench) / "pub"
    pub.chmod(0)
    try:
        r = bench.run("ssh-config", "--check")
        assert r.returncode == 1 and "pub : illisible" in r.stdout and "Traceback" not in r.stderr
    finally:
        pub.chmod(0o700)


def test_check_sous_dossier_de_pub_signale_pas_compte(bench):
    _generated(bench)
    (sv_dir(bench) / "pub" / "perso").mkdir(mode=0o700)
    r = bench.run("ssh-config", "--check")
    assert r.returncode == 0 and "dossier inattendu" in r.stderr
    r = bench.run("ssh-config")
    assert r.returncode == 0 and "dossier inattendu" in r.stderr


# --- motifs attrape-tout, recouvrements, clé partagée --------------------------------------------

@pytest.mark.parametrize("pattern", ["*", "*.*", "?*"])
def test_motif_attrape_tout_averti(bench, pattern):
    unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PERSO, pattern)
    assert r.returncode == 0, r.stderr
    assert r.stderr.count(sshconfig.CATCH_ALL_WARNING) == 2, "à l'écriture et à la génération"
    r = bench.run("ssh-config")
    assert sshconfig.CATCH_ALL_WARNING in r.stderr


def test_motifs_qui_se_recouvrent(bench):
    unlocked(bench)
    r = bench.run("hosts", "add", "--id", ID_PERSO, "x.lab.example")
    assert r.returncode == 0, r.stderr
    assert "motifs « x.lab.example »" in r.stderr and "« *.lab.example »" in r.stderr and "se recouvrent" in r.stderr


def test_deux_elements_meme_cle(bench):
    bench.add_item(ssh_item("88888888-8888-4888-8888-888888888888", "Prod copie", bench.keys["prod"],
                            hosts="copie.example"))
    unlocked(bench)
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    text = (sv_dir(bench) / "config").read_text()
    assert text.count(str(sv_dir(bench) / "pub" / pub_name(bench, "prod"))) == 2
    assert sorted(os.listdir(sv_dir(bench) / "pub")) == sorted([pub_name(bench, "bastion"), pub_name(bench, "prod")])


# --- ForwardAgent (décision : laissé à la config de l'utilisateur) ---------------------------

SSHD = "/usr/sbin/sshd"


def _free_port():
    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@needs_ssh
@pytest.mark.skipif(not os.access(SSHD, os.X_OK), reason="sshd absent")
def test_forwardagent_transfere_l_agent_dedie(bench, tmp_path):
    """Mesuré (sshd de test sur 127.0.0.1, utilisateur courant) : avec `ForwardAgent yes` de
    l'utilisateur, c'est l'agent dédié (IdentityAgent) qui est transféré, pas SSH_AUTH_SOCK."""
    assert bench.witness, "agent témoin requis (SSH_AUTH_SOCK de l'utilisateur)"
    unlocked(bench)
    assert bench.run("ssh-config").returncode == 0
    (bench.runtime / "sshvault").mkdir(mode=0o700, exist_ok=True)
    start_agent(bench.sock(), bench.keys["prod"]["private"])
    lab = tmp_path / "sshd"
    lab.mkdir()
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(lab / "hostkey")], check=True)
    (lab / "authorized_keys").write_text(bench.keys["prod"]["public"] + "\n")
    port = _free_port()
    (lab / "sshd_config").write_text(
        "Port %d\nListenAddress 127.0.0.1\nHostKey %s\nPidFile %s\nAuthorizedKeysFile %s\nStrictModes no\n"
        "UsePAM no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nAllowAgentForwarding yes\n"
        "PrintMotd no\nLogLevel ERROR\n" % (port, lab / "hostkey", lab / "sshd.pid", lab / "authorized_keys"))
    sshd = subprocess.Popen([SSHD, "-D", "-e", "-f", str(lab / "sshd_config")], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with _socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        main = tmp_path / "ssh_config_de_test"
        main.write_text('Include "%s"\nHost prod.example.com\n    HostName 127.0.0.1\n    Port %d\n'
                        "    ForwardAgent yes\n" % (sv_dir(bench) / "config", port))
        main.chmod(0o600)
        env = dict(bench.env)
        env["SSH_AUTH_SOCK"] = bench.witness["sock"]
        r = subprocess.run([SSH, "-F", str(main), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                            "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", "prod.example.com",
                            "ssh-add -L"], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           timeout=30)
        assert r.returncode == 0, r.stderr
        listed = [l.split()[1] for l in r.stdout.splitlines() if l.startswith("ssh-")]
        assert listed == [bench.blob("prod")], "agent dédié transféré, pas l'agent de l'utilisateur"
        assert bench.blob("perso") not in r.stdout
    finally:
        sshd.terminate()
        sshd.wait(10)
        assert wait_gone([sshd.pid])

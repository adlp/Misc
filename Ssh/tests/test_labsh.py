"""`lab/lab.sh` (story 20) sans docker ni maquette : un faux `docker` en tête du PATH (script du banc) journalise ses appels et
échoue sur demande. Gardes testées : `leftovers` (un échec de docker n'est jamais « rien ne reste »), `down` en échec,
fichier de clés publiques (CR, options, lignes invalides écartées, comptées et dites), `chpasswd` en échec (aucun fichier
`password`), dossier d'état par défaut (emplacement, modes, suppression par `down`), `status`.

Faux docker, par l'environnement : FAKE_DOCKER_LOG (journal : une ligne par appel, ses arguments), FAKE_DOCKER_FAIL (verbes qui
échouent, séparés par « , » : `ps`, `network ls`, `volume ls`, `compose up`, `compose exec`, `compose down`, `compose ps`),
FAKE_DOCKER_PS / FAKE_DOCKER_NETWORKS / FAKE_DOCKER_VOLUMES (ce que rendent les listes), FAKE_DOCKER_STDIN (fichier où `compose
exec` écrit son entrée standard, le mot de passe de P posé par `chpasswd`)."""
import os
import re
import shutil
import subprocess

import pytest

from bench import HERE

LAB_SH = os.path.join(os.path.dirname(HERE), "lab", "lab.sh")

FAKE_DOCKER = r'''#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
case $1 in
    compose)
        shift
        while [ $# -gt 0 ]; do
            case $1 in
                -p|-f|--profile) shift 2 ;;
                *) break ;;
            esac
        done
        verb="compose $1" ;;
    ps) verb=ps ;;
    network|volume) verb="$1 $2" ;;
    *) verb=$1 ;;
esac
case ",${FAKE_DOCKER_FAIL:-}," in
    *",$verb,"*) echo "faux docker : $verb en échec" >&2; exit 1 ;;
esac
case $verb in
    ps) printf '%s' "${FAKE_DOCKER_PS:-}" ;;
    "network ls") printf '%s' "${FAKE_DOCKER_NETWORKS:-}" ;;
    "volume ls") printf '%s' "${FAKE_DOCKER_VOLUMES:-}" ;;
    "compose exec") cat > "${FAKE_DOCKER_STDIN:-/dev/null}" ;;
    "compose ps") echo "NAME   SERVICE   STATUS"; echo "projet-c-1   c   running" ;;
esac
exit 0
'''

ED25519 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
RSA = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7vbqajDw4o6gJy8UtmDcXfK/+Ih6a=="
ECDSA = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSE="


class Fake:
    """Environnement d'un `lab.sh` branché sur le faux docker."""

    def __init__(self, tmp_path, **env):
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        docker = self.bin / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o755)
        self.log = tmp_path / "docker.log"
        self.stdin = tmp_path / "docker.stdin"
        self.state = tmp_path / "etat"
        base = {k: v for k, v in os.environ.items() if not k.startswith(("SSHVAULT_", "FAKE_DOCKER", "XDG_RUNTIME_DIR"))}
        base.update(PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), FAKE_DOCKER_LOG=str(self.log),
                    FAKE_DOCKER_STDIN=str(self.stdin), SSHVAULT_LAB_PROJECT="sshvault-lab-labsh", SSHVAULT_LAB_DIR=str(self.state))
        base.update(env)
        self.env = base
        # le faux docker est bien celui que lab.sh trouvera : jamais le vrai
        assert shutil.which("docker", path=self.env["PATH"]) == str(docker)

    def run(self, *args, **env):
        e = dict(self.env, **env)
        for k in [k for k, v in e.items() if v is None]:
            del e[k]
        return subprocess.run([LAB_SH, *args], env=e, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


@pytest.fixture
def fake(tmp_path):
    return Fake(tmp_path)


def leftovers(fake, **env):
    """(code, sortie) de la fonction `leftovers` de lab.sh (extraite du script et évaluée seule)."""
    script = 'PROJECT=%s; eval "$(sed -n \'/^leftovers() {/,/^}/p\' "$LAB_SH")"; leftovers; echo "rc=$?"' % fake.env["SSHVAULT_LAB_PROJECT"]
    r = subprocess.run(["sh", "-c", script], env=dict(fake.env, LAB_SH=LAB_SH, **env), capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
    m = re.search(r"^rc=(\d+)$", r.stdout, re.M)
    assert r.returncode == 0 and m, (r.stdout, r.stderr)
    return int(m.group(1)), r.stdout[:m.start()].strip()


def keys_file(tmp_path, text):
    p = tmp_path / "cles.pub"
    p.write_bytes(text.encode())
    return str(p)


# --- leftovers ------------------------------------------------------------------------------------

def test_leftovers_rien_ne_reste(fake):
    assert leftovers(fake) == (0, "")
    assert [c.split()[0] for c in fake.calls()] == ["ps", "network", "volume"]
    assert all("label=com.docker.compose.project=sshvault-lab-labsh" in c for c in fake.calls()), fake.calls()


@pytest.mark.parametrize("verbe", ["ps", "network ls", "volume ls"])
def test_leftovers_docker_en_echec_rend_2(fake, verbe):
    """Un échec de docker n'est jamais pris pour « rien ne reste »."""
    rc, out = leftovers(fake, FAKE_DOCKER_FAIL=verbe)
    assert rc == 2 and "a échoué" in out, (rc, out)


def test_leftovers_reste_quelque_chose_rend_1(fake):
    rc, out = leftovers(fake, FAKE_DOCKER_PS="abc123\n", FAKE_DOCKER_VOLUMES="vol1\n")
    assert rc == 1 and "abc123" in out and "vol1" in out and "réseaux : aucun" in out, (rc, out)


# --- down -------------------------------------------------------------------------------------------

def test_down_propre(fake):
    r = fake.run("up", keys_file(fake.tmp, ED25519 + "\n"))
    assert r.returncode == 0, r.stderr
    r = fake.run("down")
    assert r.returncode == 0 and "maquette détruite (projet sshvault-lab-labsh)" in r.stdout, (r.stdout, r.stderr)
    assert any("--profile client down -v --remove-orphans" in c for c in fake.calls()), "le client C est supprimé aussi : %s" % fake.calls()
    assert not fake.state.exists(), "dossier d'état supprimé"


@pytest.mark.parametrize("verbe", ["ps", "network ls", "volume ls"])
def test_down_docker_en_echec(fake, verbe):
    """`leftovers` rend 2 (docker muet) : `down` échoue et ne dit jamais « maquette détruite »."""
    assert fake.run("up", keys_file(fake.tmp, ED25519 + "\n")).returncode == 0
    r = fake.run("down", FAKE_DOCKER_FAIL=verbe)
    assert r.returncode != 0 and "maquette détruite" not in r.stdout + r.stderr, (r.stdout, r.stderr)
    assert "a échoué" in r.stderr, r.stderr


def test_down_compose_en_echec(fake):
    assert fake.run("up", keys_file(fake.tmp, ED25519 + "\n")).returncode == 0
    r = fake.run("down", FAKE_DOCKER_FAIL="compose down")
    assert r.returncode != 0 and "maquette détruite" not in r.stdout + r.stderr, (r.stdout, r.stderr)
    # le mot de passe et les clés admises sont effacés quand même
    assert not (fake.state / "password").exists() and not (fake.state / "keys" / "authorized_keys").exists()


def test_down_reste_du_projet(fake):
    assert fake.run("up", keys_file(fake.tmp, ED25519 + "\n")).returncode == 0
    r = fake.run("down", FAKE_DOCKER_NETWORKS="reseau-oublie\n")
    assert r.returncode != 0 and "reseau-oublie" in r.stderr and "maquette détruite" not in r.stdout + r.stderr, (r.stdout, r.stderr)


# --- up : fichier de clés -------------------------------------------------------------------------------

def test_cles_cr_options_et_lignes_invalides(fake):
    lignes = [
        ED25519 + " lab@poste\r",                      # CRLF : CR retiré, ligne gardée
        "# commentaire",                              # écartée
        "",                                           # écartée
        'command="id" ' + ED25519,                    # options : non gérées, écartée
        RSA,                                          # gardée
        "n'importe quoi",                             # écartée
        "ssh-ed25519 pas*du*base64",                  # écartée
        ECDSA + " autre",                             # gardée
    ]
    f = keys_file(fake.tmp, "\n".join(lignes) + "\n")
    r = fake.run("up", f)
    assert r.returncode == 0, r.stderr
    kept = (fake.state / "keys" / "authorized_keys").read_bytes().decode()  # octets : read_text() traduirait les CR
    assert kept == "\n".join([ED25519 + " lab@poste", RSA, ECDSA + " autre"]) + "\n", repr(kept)
    assert re.search(r"5 ligne\(s\) de %s écartée\(s\)" % re.escape(f), r.stderr) and "3 clé(s) admise(s)" in r.stderr, r.stderr
    assert "maquette démarrée" in r.stdout
    assert os.stat(fake.state / "keys" / "authorized_keys").st_mode & 0o777 == 0o600


def test_cles_toutes_valides_rien_a_dire(fake):
    r = fake.run("up", keys_file(fake.tmp, ED25519 + "\n" + RSA))  # dernière ligne sans fin de ligne
    assert r.returncode == 0, r.stderr
    assert len((fake.state / "keys" / "authorized_keys").read_text().splitlines()) == 2
    assert "écartée" not in r.stderr


def test_cles_aucune_valide_refus_avant_docker(fake):
    r = fake.run("up", keys_file(fake.tmp, "# rien\r\n\r\nhello world\n"))
    assert r.returncode == 1 and "aucune clé publique" in r.stderr, (r.returncode, r.stderr)
    assert fake.calls() == [], "docker jamais appelé : %s" % fake.calls()
    assert not (fake.state / "password").exists() and not (fake.state / "password.new").exists()


def test_cles_fichier_illisible(fake):
    r = fake.run("up", str(fake.tmp / "absent.pub"))
    assert r.returncode == 1 and "illisible" in r.stderr and fake.calls() == [], (r.stderr, fake.calls())


def test_sans_fichier_de_cles_aucune_cle_admise(fake):
    r = fake.run("up")
    assert r.returncode == 0 and "aucune clé publique donnée" in r.stderr, (r.returncode, r.stderr)
    assert (fake.state / "keys" / "authorized_keys").read_text() == ""


# --- up : mot de passe de P ----------------------------------------------------------------------------

def test_mot_de_passe_pose_par_stdin(fake):
    r = fake.run("up", keys_file(fake.tmp, ED25519 + "\n"))
    assert r.returncode == 0, r.stderr
    raw = (fake.state / "password").read_text()
    pw = raw.strip()
    assert re.fullmatch(r"[A-Za-z0-9]{20,24}", pw), "mot de passe aléatoire alphanumérique"
    assert os.stat(fake.state / "password").st_mode & 0o777 == 0o600
    assert fake.stdin.read_text() == "labpw:" + raw, "posé par stdin (chpasswd), le même que le fichier"
    assert not (fake.state / "password.new").exists()
    log = "\n".join(fake.calls())
    assert "exec -T p chpasswd -c sha512" in log and pw not in log, "jamais en argv"
    assert fake.run("password").stdout.strip() == pw


def test_chpasswd_en_echec_aucun_fichier_password(fake):
    r = fake.run("up", keys_file(fake.tmp, ED25519 + "\n"), FAKE_DOCKER_FAIL="compose exec")
    assert r.returncode != 0 and "mot de passe de P non posé" in r.stderr and "maquette démarrée" not in r.stdout, (r.stdout, r.stderr)
    assert not (fake.state / "password").exists() and not (fake.state / "password.new").exists()
    assert fake.run("password").returncode == 1, "lab.sh password : pas de mot de passe"


def test_demarrage_en_echec_aucun_fichier_password(fake):
    r = fake.run("up", keys_file(fake.tmp, ED25519 + "\n"), FAKE_DOCKER_FAIL="compose up")
    assert r.returncode != 0 and "démarrage de la maquette échoué" in r.stderr, (r.stdout, r.stderr)
    assert not (fake.state / "password").exists() and not (fake.state / "password.new").exists()
    assert "chpasswd" not in "\n".join(fake.calls()), "mot de passe jamais posé sur une maquette non démarrée"


def test_up_efface_le_perime(fake):
    """Mot de passe et known_hosts d'un `up` précédent : supprimés dès le début."""
    fake.state.mkdir(mode=0o700)
    (fake.state / "known_hosts").write_text("vieux\n")
    (fake.state / "password").write_text("ancien\n")
    r = fake.run("up", keys_file(fake.tmp, ED25519 + "\n"))
    assert r.returncode == 0, r.stderr
    assert not (fake.state / "known_hosts").exists()
    assert (fake.state / "password").read_text().strip() != "ancien"


# --- dossier d'état par défaut ------------------------------------------------------------------------

def test_dossier_d_etat_par_defaut(tmp_path):
    """SSHVAULT_LAB_DIR absent : `$XDG_RUNTIME_DIR/sshvault-lab` (projet par défaut), 0700 ; `keys/` 0700 ; fichiers 0600 ;
    supprimé par `down` (le XDG_RUNTIME_DIR de l'utilisateur, lui, reste)."""
    xdg = tmp_path / "xdg"
    xdg.mkdir(mode=0o700)
    fake = Fake(tmp_path, XDG_RUNTIME_DIR=str(xdg))
    del fake.env["SSHVAULT_LAB_DIR"], fake.env["SSHVAULT_LAB_PROJECT"]
    state = xdg / "sshvault-lab"
    r = fake.run("up", keys_file(tmp_path, ED25519 + "\n"))
    assert r.returncode == 0, r.stderr
    assert os.stat(state).st_mode & 0o777 == 0o700 and os.stat(state / "keys").st_mode & 0o777 == 0o700
    for name in ("password", os.path.join("keys", "authorized_keys")):
        assert os.stat(state / name).st_mode & 0o777 == 0o600, name
    assert "-p sshvault-lab " in fake.calls()[0] + " ", "projet par défaut : sshvault-lab : %s" % fake.calls()[0]
    assert [p.name for p in xdg.iterdir()] == ["sshvault-lab"], "rien d'autre créé dans XDG_RUNTIME_DIR"
    assert fake.run("password").returncode == 0
    r = fake.run("down")
    assert r.returncode == 0, r.stderr
    assert not state.exists() and xdg.is_dir(), "dossier d'état supprimé par down"


def test_dossier_d_etat_par_defaut_autre_projet(tmp_path):
    xdg = tmp_path / "xdg"
    xdg.mkdir(mode=0o700)
    fake = Fake(tmp_path, XDG_RUNTIME_DIR=str(xdg))
    del fake.env["SSHVAULT_LAB_DIR"]
    r = fake.run("up", keys_file(tmp_path, ED25519 + "\n"))
    assert r.returncode == 0, r.stderr
    assert (xdg / "sshvault-lab" / "sshvault-lab-labsh" / "password").is_file(), "projet autre que le défaut : sous-dossier"
    assert os.stat(xdg / "sshvault-lab" / "sshvault-lab-labsh").st_mode & 0o777 == 0o700
    assert fake.run("down").returncode == 0
    assert not (xdg / "sshvault-lab" / "sshvault-lab-labsh").exists()
    assert not (xdg / "sshvault-lab").exists(), "dossier commun vide : retiré aussi (rmdir)"
    assert xdg.is_dir(), "mais jamais XDG_RUNTIME_DIR"


def test_down_garde_le_dossier_commun_d_un_autre_projet(tmp_path):
    """Le dossier commun `$XDG_RUNTIME_DIR/sshvault-lab` n'est retiré que vide : le dossier d'un autre projet le garde."""
    xdg = tmp_path / "xdg"
    xdg.mkdir(mode=0o700)
    fake = Fake(tmp_path, XDG_RUNTIME_DIR=str(xdg))
    del fake.env["SSHVAULT_LAB_DIR"]
    autre = xdg / "sshvault-lab" / "autre-projet"
    autre.mkdir(parents=True, mode=0o700)
    (autre / "password").write_text("x\n")
    r = fake.run("up", keys_file(tmp_path, ED25519 + "\n"))
    assert r.returncode == 0, r.stderr
    assert fake.run("down").returncode == 0
    assert not (xdg / "sshvault-lab" / "sshvault-lab-labsh").exists()
    assert (autre / "password").read_text() == "x\n", "projet voisin intact"


def test_sans_dossier_d_etat_ni_xdg_runtime_dir(tmp_path):
    fake = Fake(tmp_path)
    del fake.env["SSHVAULT_LAB_DIR"]
    r = fake.run("up", keys_file(tmp_path, ED25519 + "\n"))
    assert r.returncode == 1 and "XDG_RUNTIME_DIR absent" in r.stderr and fake.calls() == [], (r.stderr, fake.calls())


@pytest.mark.parametrize("echecs,code", [(1, 0), (2, 1)])
def test_up_refait_mkdir_une_fois(tmp_path, echecs, code):
    """Un `mkdir -p` du dossier d'état qui échoue une fois (le `down` d'un autre projet a retiré le dossier commun entre ses
    deux étapes) : `up` le refait (exactement deux essais) ; deux échecs de suite : refus net, docker jamais appelé. Le faux
    `mkdir` n'échoue que pour le dossier d'état et compte ses appels."""
    fake = Fake(tmp_path)
    count = tmp_path / "mkdir.count"
    wrapper = fake.bin / "mkdir"
    wrapper.write_text('#!/bin/sh\ncase "$*" in\n*"%s"*)\n    echo x >> "%s"\n    [ "$(wc -l < "%s")" -gt %d ] || exit 1 ;;\nesac\nexec "%s" "$@"\n'
                       % (fake.state, count, count, echecs, shutil.which("mkdir")))
    wrapper.chmod(0o755)
    r = fake.run("up", keys_file(tmp_path, ED25519 + "\n"))
    assert r.returncode == code, (r.returncode, r.stderr)
    assert len(count.read_text().splitlines()) == 2, "deux essais exactement (pas un de plus, pas un de moins)"
    assert "création de %s impossible, nouvel essai" % fake.state in r.stderr, r.stderr
    if code:
        assert r.stderr.rstrip().endswith("création de %s impossible" % fake.state) and fake.calls() == [], (r.stderr, fake.calls())
    else:
        assert "maquette démarrée" in r.stdout


def test_down_avec_dossier_d_etat_donne_ne_touche_pas_au_parent(tmp_path):
    """`SSHVAULT_LAB_DIR` donné : `down` retire ce dossier (vide) mais jamais son parent, même vide."""
    parent = tmp_path / "parent"
    parent.mkdir()
    fake = Fake(tmp_path, SSHVAULT_LAB_DIR=str(parent / "etat"))
    assert fake.run("up", keys_file(tmp_path, ED25519 + "\n")).returncode == 0
    assert (parent / "etat" / "password").is_file()
    assert fake.run("down").returncode == 0
    assert not (parent / "etat").exists() and parent.is_dir(), "parent intact"


# --- status -----------------------------------------------------------------------------------------------

def test_status_liste_le_projet_et_le_client(fake):
    r = fake.run("status")
    assert r.returncode == 0 and re.search(r"^\S+\s+c\s+running$", r.stdout, re.M), (r.stdout, r.stderr)
    assert fake.calls() == ["compose -p sshvault-lab-labsh -f %s --profile client ps -a"
                            % os.path.join(os.path.dirname(LAB_SH), "compose.yaml")], fake.calls()


def test_status_en_echec(fake):
    r = fake.run("status", FAKE_DOCKER_FAIL="compose ps")
    assert r.returncode != 0, "le code de docker compose est rendu"

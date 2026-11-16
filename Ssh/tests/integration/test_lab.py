"""Maquette de test à conteneurs ssh (story 20) : série opt-in `lab` (`pytest -m lab`).

Une maquette Docker Compose (`lab/`, lancée par `lab/lab.sh`, projet Compose unique par run) :
A (bastion, OpenSSH 9.2), B (hôte interne, 9.3, qui n'admet que l'adresse de A, sur un réseau
interne), P (mot de passe seul, 10.0) et D (cible de deploy, 10.0). Ports publiés sur 127.0.0.1.

- `test_maquette_a_la_main` : sans coffre ni sshvault. `lab.sh config` (hôtes, puis bloc
  `Host svlab-*` : known_hosts à part, `accept-new`) inclus dans un ssh_config : `ssh svlab-a`,
  `svlab-b` par A, B refusé sans A, versions serveur, mot de passe de P (askpass quelconque, dont
  le rebond A→P), clés refusées par P, `deploy` (module `sshvault.deploy`) idempotent qui garde les
  lignes existantes, contraintes des conteneurs (ports, capacités, montages, secrets).
- `test_cles_d_hote_neuves` : la clé d'hôte d'un conteneur Debian en marche n'est pas celle de son image.
- `test_dossier_d_etat_refuse` : `lab.sh` refuse un dossier d'état relatif ou contenant `:`, `%`, `"`.
- `test_sshvault_sur_la_maquette` : vrai `bw`, compte de test, fixtures de l'intégration
  (`itbase.py`) : rebond réel par clé (CAP-7), B en direct refusé, transfert restreint (CAP-8),
  mot de passe d'hôte par `sshvault-askpass` (CAP-11, dont le rebond A→P), `generate` puis
  `deploy` puis connexion avec la clé déployée.
- `test_sshvault_depuis_le_client_openssh_recent` (story 21) : les mêmes scénarios depuis un conteneur
  client C (Debian 13 : OpenSSH 10.0, Python 3.13) attaché à `front` seulement ; sshvault (source du dépôt) et
  le vrai `bw` y sont montés en lecture seule, HOME et XDG_RUNTIME_DIR sont des tmpfs, le login est tapé sous
  un pty (`docker exec -it`), la session est rangée dans un fichier du tmpfs (keyring refusé par le profil
  seccomp par défaut), B est injoignable (ni nom, ni route). Sauté si le serveur du compte est sur la boucle locale.
- `test_client_sans_coffre` (story 23) : le conteneur client sans compte de test ni vrai `bw` (un exécutable ELF quelconque
  monté à sa place) : contraintes du conteneur (partagées avec le test du coffre), règle « bloc pour tous les hôtes » avec OpenSSH 10.0, `lab.sh status` le liste, `lab.sh down` le
  supprime (rien ne reste). Ni compte ni `bw` exigés.
- `test_interruption` : SIGINT, pendant le démarrage ou après, puis SIGTERM : conteneurs,
  réseaux et volumes du projet supprimés (sonde `labenv.py sonde`).

Fin de série, même en échec ou interruption : `docker compose down -v` du projet, contrôle qu'il ne
reste ni conteneur, ni réseau, ni volume, ni fichier d'état (`labenv.running`), éléments marqués
purgés, `bw logout`. Série sautée sans docker (avec compose) ou sans OpenSSH du poste ; sans le compte
de test ou sans `bw`, seul le test du coffre est sauté. Jamais le vrai ~/.ssh : HOME temporaire,
`ssh -F` explicite, aucune identité par défaut.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
import warnings
import ipaddress
import socket
from urllib.parse import urlsplit

import pytest

from bench import HAVE_OPENSSH, RUN_ID, ArgvWatch, agent_list, write_askpass
from itbase import ALIAS, MARK, RUN, TAG, Report, Scrub, check, home, ssh_keys, sv, sv_login, vault  # noqa: F401
from test_sshconfig import ALL_HOSTS, NOT_ALL_HOSTS  # témoins 8.9 de la story 22 : mêmes formes et mêmes sondes
from labenv import (CLIENT_BW, CLIENT_CA, COMPOSE, LAB_SH, UP_TIMEOUT, ClientUnavailable, LabError, LabTimeout, docker_available,
                    elf_machine, running)

pytestmark = pytest.mark.lab

MARKER_ENV = {"SSHVAULT_TEST_FIELD": "%s=%s" % (MARK, RUN)}
ENSURE_END = re.compile(r"^sshvault-test: fin ensure --account %s --id (\S+) rc=(\d+)$" % ALIAS, re.M)
OFFERED = re.compile(r"Offering public key: \S+ \S+ (SHA256:\S+)")
REMOTE_VERSION = re.compile(r"remote software version OpenSSH_(\d+\.\d+)")
#: OpenSSH serveur de chaque rôle (images de lab/images)
VERSIONS = {"svlab-a": "9.2", "svlab-b": "9.3", "svlab-p": "10.0", "svlab-d": "10.0"}


@pytest.fixture(scope="module")
def report():
    """Rapport de la série (SSHVAULT_IT_REPORT + « .lab »), sans valeur à masquer : les tests sans coffre
    n'ont pas besoin des comptes de test. `scrubbed` y branche les comptes pour le test du coffre."""
    rep = Report(Scrub([]))
    yield rep
    rep.flush(".lab")


@pytest.fixture(scope="module")
def scrubbed(report, accounts):
    """Valeurs de tous les comptes de test masquées dans le rapport (demandé avant `vault` par le test
    du coffre, seul à dépendre des comptes)."""
    report.account = Scrub(accounts)
    for w in getattr(accounts, "warnings", ()):
        report.add("fichier des comptes", note="avertissement : " + w)
    return report


@pytest.fixture(scope="module", autouse=True)
def prerequis():
    """Docker (avec compose) et OpenSSH du poste, pour toute la série ; le compte de test et `bw` ne sont
    exigés (sauts) que par le test du coffre."""
    if not docker_available():
        pytest.skip("docker (avec compose) indisponible")
    if not (HAVE_OPENSSH and shutil.which("ssh") and shutil.which("ssh-keygen")):
        pytest.skip("ssh, ssh-keygen, ssh-agent ou ssh-add absent")


@pytest.fixture(scope="module")
def lab(ssh_keys, prerequis):
    """Maquette démarrée, clé `hotes` admise sur A, B et D ; détruite et contrôlée à la fin."""
    with running(ssh_keys["hotes"]["public"]) as lab:
        yield lab


# --- assistants -----------------------------------------------------------------------------

def write_private(path, text, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


#: après `lab.sh config` (qui pose déjà UserKnownHostsFile et StrictHostKeyChecking accept-new)
LAB_OPTIONS = ("Host svlab-*\n"
               "    GlobalKnownHostsFile /dev/null\n"
               "    ConnectTimeout 20\n")


def ssh_run(argv_tail, env, config, batch=True, timeout=300):
    argv = ["ssh", "-F", config] + (["-o", "BatchMode=yes"] if batch else []) + list(argv_tail)
    return subprocess.run(argv, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout,
                          start_new_session=True)


def key_fp(public):
    return subprocess.run(["ssh-keygen", "-l", "-E", "sha256", "-f", "/dev/stdin"], input=public + "\n",
                          capture_output=True, text=True, check=True).stdout.split()[1]


def files_with(secret, roots):
    """Fichiers ordinaires (jusqu'à 8 Mo) sous `roots` qui contiennent `secret`."""
    needle, found = secret.encode(), []
    for root in roots:
        for d, _, names in os.walk(root):
            for n in names:
                p = os.path.join(d, n)
                try:
                    if os.path.islink(p) or not os.path.isfile(p) or os.path.getsize(p) > 8 << 20:
                        continue
                    with open(p, "rb") as f:
                        if needle in f.read():
                            found.append(p)
                except OSError:
                    continue
    return found


def accepted_in(log, user, fp):
    return re.search(r"Accepted publickey for %s from \S+ port \d+ ssh2: \S+ %s" % (user, re.escape(fp)), log)


def asker(directory, name, password):
    """SSH_ASKPASS de test (hors sshvault) : une ligne dans `<chemin>.log` par appel (texte de l'invite),
    puis le mot de passe donné sur sa sortie."""
    path = os.path.join(directory, "ask-" + name)
    write_private(path, "#!/bin/sh\nprintf '%%s\\n' \"$1\" >> '%s.log'\nprintf '%%s\\n' '%s'\n" % (path, password), 0o700)
    return path


def asker_calls(path):
    try:
        with open(path + ".log") as f:
            return [l.rstrip("\n") for l in f]
    except OSError:
        return []


# --- 1. la maquette à la main (ni coffre ni sshvault) ---------------------------------------------

def test_maquette_a_la_main(lab, ssh_keys, tmp_path, report):
    keyfile = write_private(str(tmp_path / "hotes"), ssh_keys["hotes"]["private"])
    cfg = str(tmp_path / "ssh_config")
    write_private(cfg, lab.config + "\n" + LAB_OPTIONS
                  + "    IdentityFile %s\n    IdentitiesOnly yes\n    IdentityAgent none\n" % keyfile)
    # HOME et XDG_* temporaires (ssh et sshvault.deploy en processus) : jamais ceux de l'utilisateur
    fake_home = tmp_path / "home"
    fake_run = tmp_path / "run"
    for d in (fake_home / ".ssh", fake_home / ".config", fake_home / ".local" / "share", fake_home / ".cache", fake_run):
        d.mkdir(parents=True, mode=0o700, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SSH_", "SSHVAULT_", "XDG_"))}
    env.update(HOME=str(fake_home), XDG_CONFIG_HOME=str(fake_home / ".config"),
               XDG_DATA_HOME=str(fake_home / ".local" / "share"), XDG_CACHE_HOME=str(fake_home / ".cache"),
               XDG_RUNTIME_DIR=str(fake_run))
    fp = ssh_keys["hotes"]["fingerprint"]
    client = subprocess.run(["ssh", "-V"], capture_output=True, text=True, env=env).stderr.strip()
    report.add("client ssh du poste (ssh -V)", note=client)  # écrit si SSHVAULT_IT_REPORT est défini

    # config : les sept hôtes (topologie), puis le bloc des clés d'hôte (known_hosts à part, jamais ~/.ssh)
    names = re.findall(r"^Host (\S+)$", lab.config, re.M)
    assert names == ["svlab-a", "svlab-b", "svlab-b-direct", "svlab-p", "svlab-pj", "svlab-d", "svlab-dg", "svlab-*"]
    assert "ProxyJump svlab-a" in lab.config
    assert 'UserKnownHostsFile "%s"' % os.path.join(lab.state, "known_hosts") in lab.config
    assert "StrictHostKeyChecking accept-new" in lab.config

    # A, puis B par A ; versions des serveurs
    off_b = len(lab.logs("b"))
    for host, name in (("svlab-a", "a"), ("svlab-b", "b"), ("svlab-d", "d")):
        r = ssh_run(["-v", host, "uname -n"], env, cfg)
        assert r.returncode == 0 and r.stdout == name + "\n", r.stderr[-2000:]
        seen = REMOTE_VERSION.findall(r.stderr)
        assert seen[-1] == VERSIONS[host], "%s : OpenSSH %s attendu, vu %s" % (host, VERSIONS[host], seen)
    report.add("maquette à la main : A, B par A, D", note="versions=%s" % VERSIONS)
    log_b = lab.logs("b")[off_b:]
    assert accepted_in(log_b, "lab", fp), "B a admis la clé (venue de A) : %s" % log_b[-1500:]
    m = re.search(r"Accepted publickey for lab from (\S+) ", log_b)
    assert m, "aucune connexion admise dans le journal de B : %s" % log_b[-1500:]
    got = lab.exec("b", "getent", "hosts", "a").stdout.split()
    assert got, "getent hosts a (depuis B) : sortie vide"
    assert m.group(1) == got[0], "connexion vue de B : l'adresse de A"

    # B sans A : l'adresse de B est joignable, mais refusée (AllowUsers limité à A)
    off_b = len(lab.logs("b"))
    r = ssh_run(["-v", "svlab-b-direct", "uname -n"], env, cfg)
    assert r.returncode != 0 and r.stdout == "" and "Permission denied" in r.stderr
    assert fp in OFFERED.findall(r.stderr), "la clé admise a bien été offerte : refus par B, pas faute de clé"
    assert "not allowed because not listed in AllowUsers" in lab.logs("b")[off_b:]
    report.add("maquette à la main : B en direct", note="refusé (AllowUsers)")

    # P : mot de passe seul (askpass quelconque), direct puis par A ; jamais par clé ; mot de passe voisin refusé
    good = asker(str(tmp_path), "bon", lab.password)
    pw_env = dict(env, SSH_ASKPASS=good, SSH_ASKPASS_REQUIRE="force")
    for host in ("svlab-p", "svlab-pj"):
        r = ssh_run(["-v", host, "uname -n"], pw_env, cfg, batch=False)
        assert r.returncode == 0 and r.stdout == "p\n", r.stderr[-2000:]
        assert REMOTE_VERSION.findall(r.stderr)[-1] == VERSIONS["svlab-p"]
    assert len(asker_calls(good)) == 2, "askpass appelé une fois par connexion : %s" % asker_calls(good)
    # P n'annonce que le mot de passe : la clé admise ailleurs est inutile, la seule méthode est `password`
    r = ssh_run(["-v", "-o", "PreferredAuthentications=publickey", "-o", "BatchMode=yes", "svlab-p", "true"], env, cfg)
    methods = re.findall(r"Authentications that can continue: (\S+)", r.stderr)
    assert r.returncode != 0 and "Permission denied" in r.stderr, r.stderr[-1500:]
    assert methods and set(methods) == {"password"}, "méthodes annoncées par P : %s" % methods
    near = asker(str(tmp_path), "voisin", lab.password[:8] + "x" * 16)  # mêmes 8 premiers caractères (DES tronque)
    r = ssh_run(["-v", "-o", "NumberOfPasswordPrompts=1", "svlab-p", "true"],
                dict(env, SSH_ASKPASS=near, SSH_ASKPASS_REQUIRE="force"), cfg, batch=False)
    assert r.returncode != 0 and "Permission denied" in r.stderr, r.stderr[-1500:]
    assert len(asker_calls(near)) == 1, "l'askpass du mot de passe voisin a bien été appelé : %s" % asker_calls(near)
    assert set(re.findall(r"Authentications that can continue: (\S+)", r.stderr)) == {"password"}
    report.add("maquette à la main : P", note="mot de passe direct et par A, clés refusées")

    # deploy (module sshvault.deploy) : ajout, puis « présente » ; connexion par la clé déployée
    from sshvault import deploy as D
    new = str(tmp_path / "nouvelle")
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "lab-deploy", "-f", new], check=True)
    line = D.key_line(open(new + ".pub").read())
    opts = ["-F", cfg, "-o", "BatchMode=yes"]
    authorized = "/home/lab/.ssh/authorized_keys"
    before = lab.exec("d", "cat", authorized).stdout
    assert before.strip(), "D admet déjà la clé de départ"
    answers, _ = D.deploy([line], "svlab-d", None, opts, env=env)
    assert answers == ["added"]
    after = lab.exec("d", "cat", authorized).stdout
    assert after == before + line + "\n", "lignes existantes gardées, seule la clé déployée ajoutée"
    answers, _ = D.deploy([line], "svlab-d", None, opts, env=env)
    assert answers == ["present"]
    assert lab.exec("d", "cat", authorized).stdout == after, "second passage : rien écrit"
    r = ssh_run(["-o", "IdentitiesOnly=yes", "-i", new, "svlab-dg", "uname -n"], env, cfg)
    assert r.returncode == 0 and r.stdout == "d\n", r.stderr[-2000:]
    assert accepted_in(lab.logs("d"), "lab", key_fp(line)), "D a admis la clé déployée"
    report.add("maquette à la main : deploy", note="added puis present, connexion par la clé déployée")

    # contraintes des conteneurs
    ports = lab.service_ports()
    assert not ports["b"], "B n'est pas publié : %s" % ports
    published = {k: v for k, v in ports.items() if v}
    assert sorted(published) == ["a", "d", "p"], ports
    assert all(len(v) == 1 and v[0][0] == "127.0.0.1" for v in published.values()), ports
    keys_dir = os.path.realpath(os.path.join(lab.state, "keys"))
    for c in lab.inspect():
        hc = c["HostConfig"]
        svc = c["Config"]["Labels"]["com.docker.compose.service"]
        assert not hc.get("Privileged") and not hc.get("CapAdd"), "%s : privilège ou capacité ajoutée" % svc
        if svc == "c":  # client (story 21, démarré par son seul test) : montages vérifiés par ce test
            continue
        want = [] if svc == "p" else [(keys_dir, "/keys", False)]
        assert [(os.path.realpath(m["Source"]), m["Destination"], m["RW"]) for m in c["Mounts"]] == want, \
            "%s : montages %s" % (svc, c["Mounts"])
        assert all(m["Type"] == "bind" for m in c["Mounts"])
    text = lab.inspect_text()
    for secret in (lab.password, ssh_keys["hotes"]["private"].splitlines()[1], open(new).read().splitlines()[1]):
        assert secret not in text, "secret dans docker inspect"
    for n in ("a", "b", "d"):
        assert "PRIVATE KEY" not in lab.logs(n)
    st = os.stat(os.path.join(lab.state, "password"))
    assert st.st_mode & 0o777 == 0o600 and os.stat(lab.state).st_mode & 0o777 == 0o700
    assert open(os.path.join(lab.state, "password")).read().strip() == lab.password
    assert os.path.isfile(os.path.join(lab.state, "known_hosts")), "clés d'hôte écrites dans le known_hosts de la maquette"
    report.add("maquette à la main : contraintes", note="ports 127.0.0.1, sans privilège ni capacité, montage /keys seul")


# --- 2. sshvault, vrai bw, sur la maquette --------------------------------------------------

def test_sshvault_sur_la_maquette(scrubbed, account, bw_exe, vault, ssh_keys, home, report, lab):
    pop, session = vault["_reader"]
    h = home["env"]["HOME"]
    fp_hotes, fp_fwd = ssh_keys["hotes"]["fingerprint"], ssh_keys["sans-hotes"]["fingerprint"]
    sock = os.path.join(home["runtime"], "sshvault", "agent.sock")

    r = sv(home, "account", "add", ALIAS, "--server", account.server, "--email", account.email)
    check(account, r, 0, "account add")
    sv_login(home, account, report)

    # coffre : hôtes de la clé admise (A, B, B en direct, D), clé transférée vers A, clé générée pour D (autre
    # nom, même machine), mot de passe de P (direct et par A) ; mot de passe sur stdin, jamais en argument
    r = sv(home, "--nointeraction", "hosts", "add", "--id", vault["hotes"], "svlab-a", "svlab-b", "svlab-b-direct",
           "svlab-d")
    report.add("sshvault hosts add (maquette)", r)
    check(account, r, 0, "hosts add")
    r = sv(home, "--nointeraction", "forward", "add", "--id", vault["sans-hotes"], "svlab-a")
    check(account, r, 0, "forward add")
    r = sv(home, "config", "set", "forward-confirm", "false")  # pas d'askpass de confirmation ici
    check(account, r, 0, "config set forward-confirm")
    gen_name = "sshvault-lab %s générée" % TAG
    r = sv(home, "--nointeraction", "generate", "--name", gen_name, "--hosts", "svlab-dg", env=MARKER_ENV)
    report.add("sshvault generate (maquette)", r)
    check(account, r, 0, "generate")
    public = r.stdout.splitlines()[0]
    assert public.startswith("ssh-ed25519 ")
    fp_gen = key_fp(public)
    pw_name = "sshvault-lab %s mot de passe" % TAG
    with ArgvWatch(home["env"]["SSHVAULT_BW"], [lab.password], heuristics=False) as w:
        r = sv(home, "--nointeraction", "password", "add", pw_name, "--host", "labpw@svlab-p", "--host",
               "labpw@svlab-pj", env=MARKER_ENV, input=lab.password + "\n")
    report.add("sshvault password add (maquette)", r)
    check(account, r, 0, "password add")
    assert not w.suspect, "mot de passe en argument : %s" % w.suspect[:3]
    r = sv(home, "--nointeraction", "ssh-config")
    check(account, r, 0, "ssh-config")
    text = open(os.path.join(h, ".ssh", "sshvault", "config")).read()
    m = re.search(r'^Match originalhost (\S+) exec "[^"\n]* --id %s"$' % vault["hotes"], text, re.M)
    assert m and {"svlab-a", "svlab-b", "svlab-b-direct", "svlab-d"} <= set(m.group(1).split(",")), text

    # ~/.ssh/config du HOME de test : Include de sshvault en tête, puis la maquette (lab.sh config)
    main = os.path.join(h, ".ssh", "config")
    write_private(main, 'Include "%s"\n\n%s\n%s    IdentityFile /nonexistent/sshvault-lab-aucune-identite\n'
                  % (os.path.join(h, ".ssh", "sshvault", "config"), lab.config, LAB_OPTIONS))
    env = dict(home["env"], SSHVAULT_TEST_TRACE="1")
    ask_log = os.path.join(home["tmp"], "askpass.log")
    askdir = os.path.join(home["tmp"], "askbin")
    ask = str(write_askpass(askdir))  # `sshvault-askpass` du banc (SSH_ASKPASS)

    def stop_agent():
        check(account, sv(home, "agent", "stop"), 0, "agent stop")

    # --- rebond réel par clé (CAP-7) ---
    stop_agent()
    off_b = len(lab.logs("b"))  # seul le journal de B écrit à partir d'ici compte
    t0 = time.monotonic()
    r = ssh_run(["-v", "svlab-b", "uname -n"], env, main)
    report.add("ssh svlab-b (rebond par A, agent vide, vrai bw)", note="rc=%d durée=%.2fs" % (r.returncode,
                                                                                         time.monotonic() - t0))
    if r.returncode != 0:
        raise AssertionError(account.scrub("ssh svlab-b : code %d ; stderr : %s" % (r.returncode, r.stderr[-3000:])))
    assert r.stdout == "b\n", "commande exécutée sur B"
    assert [rc for _, rc in ENSURE_END.findall(r.stderr)] and all(rc == "0" for _, rc in ENSURE_END.findall(r.stderr))
    assert {i for i, _ in ENSURE_END.findall(r.stderr)} == {vault["hotes"]}
    assert set(OFFERED.findall(r.stderr)) == {fp_hotes}, "une seule clé offerte : %s" % OFFERED.findall(r.stderr)
    assert not [l for l in r.stderr.splitlines() if l.startswith("sshvault:")], "ensure silencieux"
    assert "PRIVATE KEY" not in r.stdout + r.stderr
    log_b = lab.logs("b")[off_b:]
    assert accepted_in(log_b, "lab", fp_hotes), "B a admis la clé, venue de A : %s" % log_b[-1500:]
    rc, listing = agent_list(sock)
    assert rc == 0 and [l.split()[1] for l in listing] == [ssh_keys["hotes"]["public"].split()[1]]
    stop_agent()

    # --- B en direct : refusé ---
    off_b = len(lab.logs("b"))
    r = ssh_run(["-v", "svlab-b-direct", "uname -n"], env, main)
    report.add("ssh svlab-b-direct (sans A)", note="rc=%d" % r.returncode)
    assert r.returncode != 0 and r.stdout == "", "aucune session"
    assert "Permission denied" in r.stderr
    assert fp_hotes in OFFERED.findall(r.stderr), "clé offerte : refusée par B, pas faute de clé"
    log_b = lab.logs("b")[off_b:]
    assert "not listed in AllowUsers" in log_b, log_b[-1500:]
    assert not accepted_in(log_b, "lab", fp_hotes), "B n'a rien admis"
    stop_agent()

    # --- transfert restreint (CAP-8) : sur A, `ssh-add -l` ne liste que la clé transférée ---
    r = ssh_run(["-A", "svlab-a", "ssh-add -l"], env, main)
    report.add("ssh -A svlab-a 'ssh-add -l' (transfert restreint)", note="rc=%d" % r.returncode)
    if r.returncode != 0:
        raise AssertionError(account.scrub("ssh -A : code %d ; stdout %r ; stderr : %s" % (
            r.returncode, r.stdout, r.stderr[-3000:])))
    seen = [l.split()[1] for l in r.stdout.splitlines() if re.match(r"\d+ SHA256:", l)]
    assert seen == [fp_fwd], "seule la clé transférée : %s" % r.stdout
    assert fp_hotes not in r.stdout and "PRIVATE KEY" not in r.stdout + r.stderr
    assert not [l for l in r.stderr.splitlines() if l.startswith("sshvault:")], account.scrub(r.stderr)
    stop_agent()

    # --- mot de passe d'hôte par sshvault-askpass (CAP-11), direct puis par le rebond A→P ---
    pw_env = dict(env, SSH_ASKPASS=ask, SSH_ASKPASS_REQUIRE="force", SSHVAULT_TEST_ASKPASS_LOG=ask_log)
    with ArgvWatch(home["env"]["SSHVAULT_BW"], [lab.password], heuristics=False) as w:
        for host, prompt_host in (("svlab-p", "127.0.0.1"), ("svlab-pj", "p")):
            before = len(open(ask_log).read().splitlines()) if os.path.exists(ask_log) else 0
            r = ssh_run([host, "uname -n"], pw_env, main, batch=False)
            report.add("ssh %s (mot de passe par sshvault-askpass)" % host, note="rc=%d" % r.returncode)
            if r.returncode != 0:
                raise AssertionError(account.scrub("ssh %s : code %d ; stderr : %s" % (host, r.returncode,
                                                                                         r.stderr[-3000:])))
            assert r.stdout == "p\n", "commande exécutée sur P"
            prompts = [l.rstrip() for l in open(ask_log).read().splitlines()[before:]]
            assert prompts == ["labpw@%s's password:" % prompt_host], \
                "une seule invite, de mot de passe : %s" % prompts
            assert lab.password not in r.stdout + r.stderr
            stop_agent()
    assert not w.suspect, "mot de passe en argument : %s" % w.suspect[:3]
    assert not files_with(lab.password, [h, home["runtime"]]), "mot de passe écrit sur disque"
    assert lab.password not in lab.inspect_text()

    # --- generate puis deploy (D, par la clé admise) puis connexion avec la clé déployée ---
    authorized = "/home/lab/.ssh/authorized_keys"
    before = lab.exec("d", "cat", authorized).stdout
    r = sv(home, "--nointeraction", "deploy", "--fingerprint", fp_gen, "svlab-d", "--", "-F", main)
    report.add("sshvault deploy (maquette)", r)
    check(account, r, 0, "deploy")
    assert r.stdout.startswith("ajoutée : « %s » %s → svlab-d" % (gen_name, fp_gen)), r.stdout
    after = lab.exec("d", "cat", authorized).stdout
    assert after.startswith(before), "lignes existantes de D gardées"
    added = after[len(before):].splitlines()
    assert len(added) == 1 and added[0].split()[:2] == public.split()[:2], "seule la clé déployée est ajoutée : %s" % added
    r = sv(home, "--nointeraction", "deploy", "--fingerprint", fp_gen, "svlab-d", "--", "-F", main)
    check(account, r, 0, "deploy relancé")
    assert r.stdout.startswith("déjà présente : "), r.stdout
    assert lab.exec("d", "cat", authorized).stdout == after, "second passage : rien écrit"
    stop_agent()
    r = ssh_run(["-v", "svlab-dg", "uname -n"], env, main)
    report.add("ssh svlab-dg (clé générée puis déployée)", note="rc=%d" % r.returncode)
    if r.returncode != 0:
        raise AssertionError(account.scrub("ssh svlab-dg : code %d ; stderr : %s" % (r.returncode, r.stderr[-3000:])))
    assert r.stdout == "d\n"
    assert set(OFFERED.findall(r.stderr)) == {fp_gen}, "seule la clé générée est offerte"
    assert accepted_in(lab.logs("d"), "lab", fp_gen), "D a admis la clé déployée"
    stop_agent()

    # --- relecture par un autre client bw : la clé générée est dans le coffre, jamais sur disque ---
    assert pop.sync(session).returncode == 0
    found = [it for it in json.loads(pop.ok("list", "items", session=session).stdout)
             if (it.get("sshKey") or {}).get("keyFingerprint") == fp_gen]
    assert len(found) == 1 and found[0]["sshKey"]["publicKey"] == public
    assert not files_with("BEGIN OPENSSH PRIVATE KEY", [h, home["runtime"]]), "clé privée écrite sur disque"


# --- 2 bis. le même, depuis un client OpenSSH 10.0 en conteneur (story 21) -----------------------

#: ~/.ssh/config du conteneur client avant `sshvault ssh-config install` (qui y met sa ligne `Include`, en tête) : la maquette vue de C
#: (réseau `front` seulement : A, P et D par leur nom de service ; B seulement par A). Noms d'hôtes propres au
#: client pour les éléments créés ici (`svlab-cp`, `svlab-cpj`, `svlab-cdg`) : ceux du test précédent, dans le même
#: coffre, n'y gênent pas ; `svlab-a`, `svlab-b`, `svlab-b-direct` et `svlab-d` sont ceux des hôtes de la clé admise.
CLIENT_CONFIG = """Host svlab-a
    HostName a
    User lab

Host svlab-b
    HostName b
    User lab
    ProxyJump svlab-a

# nom absolu : jamais complété par un domaine de recherche
Host svlab-b-direct
    HostName b.
    User lab

Host svlab-cp
    HostName p
    User labpw

Host svlab-cpj
    HostName p
    User labpw
    ProxyJump svlab-a

Host svlab-d
    HostName d
    User lab

Host svlab-cdg
    HostName d
    User lab

Host svlab-*
    UserKnownHostsFile %(home)s/.ssh/known_hosts
    StrictHostKeyChecking accept-new
    GlobalKnownHostsFile /dev/null
    ConnectTimeout 20
    IdentityFile /nonexistent/sshvault-lab-aucune-identite
"""


class ClientBw:
    """`bw` brut du conteneur client (monté), sur les données de sshvault du compte : `logout` d'un login bloqué."""

    def __init__(self, client):
        self.client = client

    def run(self, *args):
        """Comme `Bw.run` : un `bw` sans réponse ne lève rien, code 124 (toute autre erreur est levée). `logout` arrête
        d'abord les logins en cours ; le logout a lieu même si cet arrêt échoue (l'échec est levé ensuite)."""
        data = "%s/.local/share/sshvault/accounts/%s/bw" % (self.client.home, ALIAS)
        argv = [CLIENT_BW, "--nointeraction", *args]
        stop_error = None
        if args and args[0] == "logout":
            try:
                self.client.stop_logins()
            except LabError as e:
                stop_error = e
        try:
            r = self.client.run(argv, env={"BITWARDENCLI_APPDATA_DIR": data}, timeout=90)
        except LabTimeout as e:
            r = subprocess.CompletedProcess(argv, 124, "", str(e))
        if stop_error is not None:
            raise stop_error
        return r


def client_files_with(client, secret, roots):
    """Fichiers (tous, sans limite de taille ; binaires lus comme du texte) sous `roots`, dans le conteneur, qui
    contiennent `secret` (lu sur stdin par grep : jamais en argv). Code de grep lu : 0 (trouvé) ou 1 (rien) ; 2 n'est
    toléré que si chaque erreur est « fichier disparu pendant la recherche », sinon LabError (une erreur de lecture
    n'est pas « rien »)."""
    r = client.run(["grep", "-rlFa", "-D", "skip", "-f", "-", "--", *roots], input=secret + "\n")
    if r.returncode == 2:
        errors = [l for l in r.stderr.splitlines() if l.strip()]
        if errors and all("No such file or directory" in l for l in errors):
            return r.stdout.split()
    if r.returncode not in (0, 1):
        raise LabError("grep dans le conteneur : code %d : %s" % (r.returncode, r.stderr.strip()[-500:]))
    return r.stdout.split()


def client_scan_control(client, roots):
    """Témoin de `client_files_with` : un fichier posé dans chaque racine (HOME, XDG_RUNTIME_DIR, /tmp) avec un marqueur
    neuf est trouvé par la recherche."""
    marker = "sshvault-lab-temoin-" + uuid.uuid4().hex
    paths = [root + "/.scan-control" for root in roots]
    try:
        for path in paths:
            client.write(path, marker + "\n")
        found = client_files_with(client, marker, roots)
        assert sorted(found) == sorted(paths), "la recherche de secrets ne voit pas ses témoins : %s" % found
    finally:
        client.run(["rm", "-f", *paths])


def client_ssh(client, argv_tail, env=None, batch=True, timeout=300):
    argv = ["ssh", "-F", client.home + "/.ssh/config"] + (["-o", "BatchMode=yes"] if batch else []) + list(argv_tail)
    return client.run(argv, env=env, timeout=timeout)


def local_address(a):
    """Adresse de la boucle locale du poste ou non spécifiée (0.0.0.0, ::), IPv4 mappée en IPv6 comprise."""
    ip = ipaddress.ip_address(a.split("%")[0])
    mapped = getattr(ip, "ipv4_mapped", None)
    return any(x.is_loopback or x.is_unspecified for x in ((ip, mapped) if mapped else (ip,)))


def server_is_loopback(server):
    """Le serveur du compte est-il sur la boucle locale du poste (une des adresses du nom, résolu, en est une) ?"""
    host = urlsplit(server).hostname or ""
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except OSError:
        return host in ("localhost",)  # non résolu : bw en dira l'erreur ; « localhost » seul est certain
    return any(local_address(a) for a in addrs)


def check_client_container(client, lab, bw_path, ca, scrub, report):
    """Le conteneur client C tel que la maquette le monte (sans coffre ni compte de test, partagé par le test du coffre et
    par `test_client_sans_coffre`) : OpenSSH 10.0, Python 3.13, uid et gid de l'utilisateur, ni privilège ni capacité (toutes
    retirées) ni port, système de fichiers en lecture seule, profil seccomp par défaut (keyring refusé), réseau `front` seul
    (B inconnu), montages en lecture seule (source du dépôt, `bw_path`, certificat `ca` ou /dev/null), HOME, /tmp et
    XDG_RUNTIME_DIR sur des tmpfs. `scrub` : masque les valeurs secrètes des messages (compte de test)."""
    r = client.run(["ssh", "-V"])
    assert r.returncode == 0 and re.match(r"OpenSSH_10\.0", r.stderr), "client OpenSSH 10.0 attendu : %r" % r.stderr
    report.add("client ssh du conteneur (ssh -V)", note=r.stderr.strip())
    home, runtime = client.home, client.runtime
    assert client.run(["id", "-u"]).stdout.strip() == str(os.getuid()) and client.run(["id", "-g"]).stdout.strip() == str(os.getgid())
    assert client.run(["python3", "-c", "import sys; print('%d.%d' % sys.version_info[:2])"]).stdout.strip() == "3.13"
    c = [x for x in lab.inspect() if x["Config"]["Labels"]["com.docker.compose.service"] == "c"]
    assert len(c) == 1, "un seul conteneur client"
    hc = c[0]["HostConfig"]
    assert not hc.get("Privileged") and not hc.get("CapAdd") and not hc.get("PortBindings"), "ni privilège, ni capacité ajoutée, ni port"
    assert hc.get("ReadonlyRootfs") is True, "système de fichiers du conteneur en lecture seule"
    assert [x.upper() for x in (hc.get("CapDrop") or [])] == ["ALL"], "toutes les capacités retirées : %s" % hc.get("CapDrop")
    opts = hc.get("SecurityOpt") or []
    assert any(o in ("no-new-privileges:true", "no-new-privileges=true", "no-new-privileges") for o in opts), \
        scrub("no-new-privileges : %s" % opts)
    assert not [o for o in opts if "seccomp" in o], scrub("profil seccomp par défaut : %s" % opts)
    assert set(c[0]["NetworkSettings"]["Networks"]) == {lab.project + "_front"}, "C n'est que sur front"
    want = {("/src", True), (CLIENT_BW, True), (CLIENT_CA, True)}
    got = {(m["Destination"], not m["RW"]) for m in c[0]["Mounts"]}
    assert got == want, scrub("montages en lecture seule : %s" % c[0]["Mounts"])
    src = {m["Destination"]: os.path.realpath(m["Source"]) for m in c[0]["Mounts"]}
    repo_src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
    sources_ok = (src["/src"] == os.path.realpath(repo_src) and src[CLIENT_BW] == os.path.realpath(bw_path)
                  and src[CLIENT_CA] == (os.path.realpath(ca) if ca else "/dev/null"))
    assert sources_ok, "sources des montages : le dépôt (src), bw, et le certificat (ou /dev/null)"
    assert set(hc["Tmpfs"]) == {home, runtime, "/tmp"}, "HOME, /tmp et XDG_RUNTIME_DIR sur des tmpfs : %s" % hc["Tmpfs"]
    mounts = client.read("/proc/self/mounts")
    assert all(re.search(r"^tmpfs %s tmpfs " % re.escape(d), mounts, re.M) for d in (home, runtime, "/tmp"))
    r = client.run(["keyctl", "padd", "user", "sshvault-lab-sonde", "@u"], input="x")
    assert r.returncode != 0 and "Operation not permitted" in r.stderr, "keyring refusé dans le conteneur : %s" % r
    # B injoignable depuis C au niveau réseau : ni nom (absolu ou non), ni route
    assert client.run(["getent", "hosts", "b"]).returncode == 2, "le nom de B n'est pas résolu depuis C"
    assert client.run(["getent", "hosts", "b."]).returncode == 2, "le nom absolu de B n'est pas résolu depuis C"

    check_read_only_root(client)


def check_read_only_root(client):
    """Système de fichiers en lecture seule : témoin négatif, une écriture hors des tmpfs échoue (EROFS)."""
    r = client.run(["sh", "-c", "echo x > /usr/lib/sshvault-lab-ecriture 2>&1"])
    assert r.returncode != 0 and "Read-only file system" in r.stdout + r.stderr, "écriture hors tmpfs refusée : %s" % r
    assert client.run(["test", "-e", "/usr/lib/sshvault-lab-ecriture"]).returncode != 0, "rien n'a été écrit"


def test_sshvault_depuis_le_client_openssh_recent(request, scrubbed, account, bw_exe, vault, ssh_keys, report, lab):
    """Les scénarios du test précédent, rejoués depuis C (Debian 13 : OpenSSH 10.0, Python 3.13), qui n'est que sur
    `front` : sshvault et le vrai `bw` y tournent (source du dépôt et `bw` montés en lecture seule, système de
    fichiers en lecture seule, HOME, /tmp et XDG_RUNTIME_DIR sur des tmpfs), le login est tapé sous un pty
    (`docker exec -it`), la session est rangée dans un fichier du tmpfs (keyring refusé par le profil seccomp par
    défaut de docker)."""
    if server_is_loopback(account.server):
        pytest.skip("serveur du compte de test sur la boucle locale du poste : injoignable depuis un conteneur")
    ca = account.extra_env.get("NODE_EXTRA_CA_CERTS") or None
    try:
        client = lab.client_up(bw_exe, ca, RUN_ID)
    except ClientUnavailable as e:
        pytest.skip(account.scrub(str(e)))
    except LabError as e:
        raise AssertionError(account.scrub(str(e))) from None
    home, runtime = client.home, client.runtime
    uid = os.getuid()
    fp_hotes, fp_fwd = ssh_keys["hotes"]["fingerprint"], ssh_keys["sans-hotes"]["fingerprint"]
    sock = runtime + "/sshvault/agent.sock"
    main = home + "/.ssh/config"
    tenv = {"SSHVAULT_TEST_TRACE": "1"}
    cbw = ClientBw(client)

    def final_logout():
        """bw déconnecté à la fin quoi qu'il arrive (logins en cours arrêtés d'abord), comme la fixture `home` ; un
        échec est écrit dans le rapport et en avertissement."""
        try:
            r = cbw.run("logout")
            # « You are not logged in. » : déjà déconnecté (par le `sshvault logout` du test), pas un échec
            ok = r.returncode == 0 or "You are not logged in" in r.stderr
            problem = None if ok else "code %d : %s" % (r.returncode, r.stderr.strip()[-300:])
        except LabError as e:
            problem = str(e)
        if problem:
            report.add("bw logout (client) en échec", note=account.scrub(problem))
            warnings.warn("bw logout (client) en échec : " + account.scrub(problem))

    request.addfinalizer(final_logout)

    def sv(*args, **kw):
        return client.sv(*args, **kw)

    def stop_agent():
        check(account, sv("agent", "stop"), 0, "agent stop")

    def bw_seen(w, *words):
        """Lignes de commande de `bw` (monté) relevées par `w` qui contiennent chacun de `words`."""
        return [a for a in w.seen if a[0] == CLIENT_BW and all(x in a for x in words)]

    # --- le client : version, utilisateur, montages, réseau, privilèges (contrôles partagés avec le test sans coffre) ---
    check_client_container(client, lab, bw_exe, ca, account.scrub, report)

    # --- témoin de la lecture des environnements : un processus planté avec un jeton neuf en est le détenteur ---
    token = "sshvault-lab-plant-" + uuid.uuid4().hex
    client.plant_environ(token)
    holders = []
    for _ in range(50):
        holders, _readable = client.environ_holders(token)
        if holders:
            break
        time.sleep(0.2)
    assert holders, "la lecture des environnements du conteneur ne voit pas son témoin"
    client.run(["sh", "-c", 'kill "$@"', "sh", *holders])

    # --- compte, login sous pty (docker exec -it), session rangée dans le tmpfs ---
    r = sv("account", "add", ALIAS, "--server", account.server, "--email", account.email)
    check(account, r, 0, "account add (client)")
    chome = {"login_argv": client.login_argv(), "login_env": client.login_env(), "bw": cbw}
    with ArgvWatch(CLIENT_BW, [account.password], heuristics=False) as w:
        sv_login(chome, account, report)
    assert not w.suspect, "mot de passe du compte en argument : %s" % w.suspect[:3]
    assert bw_seen(w, "login"), account.scrub("le relevé ne voit pas le `bw login` du conteneur : %s" % sorted(w.seen)[:3])
    # environnement des processus du conteneur : pas de mot de passe (relevé juste après le login, pas pendant
    # l'exécution de bw)
    holders, readable = client.environ_holders(account.password)
    assert readable >= 1 and not holders, "mot de passe du compte dans l'environnement de processus du conteneur : %s" % holders
    r = sv("status")
    check(account, r, 0, "status (client)")
    assert re.search(r"^coffre : déverrouillé$", r.stdout, re.M) and re.search(r"^session : file$", r.stdout, re.M), \
        account.scrub(r.stdout)
    session_file = "%s/sshvault/sessions/%s" % (runtime, ALIAS)
    st = client.run(["stat", "-c", "%a %u %F", session_file])
    assert st.returncode == 0 and st.stdout.strip() == "600 %d regular file" % uid, \
        "session en fichier ordinaire 0600 de l'utilisateur dans le tmpfs : %s %s" % (st.stdout, st.stderr)
    report.add("sshvault login (client, docker exec -it)", note="session rangée dans %s" % session_file)

    # --- coffre : mêmes réglages que le test précédent (hôtes de la clé admise, transfert, générée, mot de passe) ---
    r = sv("--nointeraction", "hosts", "add", "--id", vault["hotes"], "svlab-a", "svlab-b", "svlab-b-direct", "svlab-d")
    check(account, r, 0, "hosts add (client)")
    r = sv("--nointeraction", "forward", "add", "--id", vault["sans-hotes"], "svlab-a")
    check(account, r, 0, "forward add (client)")
    check(account, sv("config", "set", "forward-confirm", "false"), 0, "config set forward-confirm")
    gen_name = "sshvault-lab %s générée (client)" % TAG
    r = sv("--nointeraction", "generate", "--name", gen_name, "--hosts", "svlab-cdg", env=MARKER_ENV)
    check(account, r, 0, "generate (client)")
    public = r.stdout.splitlines()[0]
    assert public.startswith("ssh-ed25519 ")
    fp_gen = key_fp(public)
    pw_name = "sshvault-lab %s mot de passe (client)" % TAG
    with ArgvWatch(CLIENT_BW, [lab.password, account.password], heuristics=False) as w:
        r = sv("--nointeraction", "password", "add", pw_name, "--host", "labpw@svlab-cp", "--host", "labpw@svlab-cpj",
               env=MARKER_ENV, input=lab.password + "\n")
    check(account, r, 0, "password add (client)")
    assert not w.suspect, "mot de passe en argument : %s" % w.suspect[:3]
    assert bw_seen(w, "create"), "le relevé voit le `bw create` du conteneur : %s" % sorted(a[:4] for a in w.seen)[:3]
    # ~/.ssh/config : la maquette seule ; sshvault y met lui-même sa ligne Include (lue ensuite par le client 10.0)
    client.write(main, CLIENT_CONFIG % {"home": home}, "600")
    generated = home + "/.ssh/sshvault/config"
    # `install` ne régénère pas (mesuré : « n'existe pas encore » s'il manque) : elle doit déjà exister, écrite par
    # les commandes d'écriture du coffre (hosts add, generate…)
    assert client.run(["test", "-s", generated]).returncode == 0, "config générée par les écritures du coffre"
    r = sv("--nointeraction", "ssh-config", "install")
    check(account, r, 0, "ssh-config install (client)")
    assert "avertissement" not in (r.stdout + r.stderr).lower(), account.scrub("avertissement de install : " + r.stdout + r.stderr)
    assert client.read(main).splitlines()[0] == 'Include "~/.ssh/sshvault/config"', client.read(main)[:200]
    text = client.read(generated)
    m = re.search(r'^Match originalhost (\S+) exec "[^"\n]* --id %s"$' % vault["hotes"], text, re.M)
    assert m and {"svlab-a", "svlab-b", "svlab-b-direct", "svlab-d"} <= set(m.group(1).split(",")), text
    # le client 10.0 lit la ligne `Include` de sshvault : la config générée s'applique (agent dédié de l'hôte)
    r = client.run(["ssh", "-G", "-F", main, "svlab-a"])
    assert r.returncode == 0 and "identityagent %s" % sock in r.stdout.lower(), r.stderr[-1000:]
    # la forme sans guillemets est lue de même par le client 10.0
    bare = home + "/.ssh/config-sans-guillemets"
    client.write(bare, "Include ~/.ssh/sshvault/config\n", "600")
    r = client.run(["ssh", "-G", "-F", bare, "svlab-a"])
    assert r.returncode == 0 and "identityagent %s" % sock in r.stdout.lower(), r.stderr[-1000:]

    # --- rebond réel par clé (CAP-7) : A puis B par `ensure`, agent vide ---
    stop_agent()
    off_b = len(lab.logs("b"))
    t0 = time.monotonic()
    r = client_ssh(client, ["-v", "svlab-b", "uname -n"], tenv)
    report.add("client : ssh svlab-b (rebond par A, agent vide, vrai bw)", note="rc=%d durée=%.2fs" % (
        r.returncode, time.monotonic() - t0))
    if r.returncode != 0:
        raise AssertionError(account.scrub("ssh svlab-b : code %d ; stderr : %s" % (r.returncode, r.stderr[-3000:])))
    assert r.stdout == "b\n", "commande exécutée sur B"
    ends = ENSURE_END.findall(r.stderr)
    assert ends and all(rc == "0" for _, rc in ends) and {i for i, _ in ends} == {vault["hotes"]}, ends
    assert set(OFFERED.findall(r.stderr)) == {fp_hotes}, "une seule clé offerte : %s" % OFFERED.findall(r.stderr)
    assert not [l for l in r.stderr.splitlines() if l.startswith("sshvault:")], "ensure silencieux"
    assert "PRIVATE KEY" not in r.stdout + r.stderr
    assert "OpenSSH_10.0" in r.stderr.splitlines()[0], "client 10.0 : %s" % r.stderr.splitlines()[0]
    log_b = lab.logs("b")[off_b:]
    assert accepted_in(log_b, "lab", fp_hotes), "B a admis la clé, venue de A : %s" % log_b[-1500:]
    r = client.run(["ssh-add", "-L"], env={"SSH_AUTH_SOCK": sock})
    assert r.returncode == 0 and [l.split()[1] for l in r.stdout.splitlines()] == [ssh_keys["hotes"]["public"].split()[1]]
    stop_agent()

    # --- B en direct : ni nom ni route depuis C, aucune connexion jusqu'à B ---
    off_b = len(lab.logs("b"))
    r = client_ssh(client, ["-v", "svlab-b-direct", "uname -n"], tenv)
    report.add("client : ssh svlab-b-direct (sans A)", note="rc=%d" % r.returncode)
    assert r.returncode != 0 and r.stdout == "", "aucune session"
    assert "Could not resolve hostname b." in r.stderr and "Connecting to" not in r.stderr \
        and "Connection established" not in r.stderr, "aucune connexion ne part du laboratoire : %s" % r.stderr[-1000:]
    b_ip = [x for x in lab.inspect() if x["Config"]["Labels"]["com.docker.compose.service"] == "b"][0][
        "NetworkSettings"]["Networks"][lab.project + "_back"]["IPAddress"]
    r = client.run(["ssh", "-F", "/dev/null", "-v", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                    "-o", "StrictHostKeyChecking=no", "lab@" + b_ip, "uname -n"], timeout=60)
    assert r.returncode != 0 and r.stdout == "" and "Connection established" not in r.stderr, r.stderr[-1000:]
    assert re.search(r"connect to host %s port 22: (Connection timed out|No route to host)" % re.escape(b_ip), r.stderr), \
        "aucune connexion n'arrive jusqu'à B (paquets perdus) : %s" % r.stderr[-500:]
    log_b = lab.logs("b")[off_b:]
    assert "Connection from" not in log_b and "AllowUsers" not in log_b, "B n'a vu aucune connexion : %s" % log_b[-500:]

    # --- transfert restreint (CAP-8) : sur A, `ssh-add -l` ne liste que la clé transférée ---
    r = client_ssh(client, ["-A", "svlab-a", "ssh-add -l"], tenv)
    report.add("client : ssh -A svlab-a 'ssh-add -l' (transfert restreint)", note="rc=%d" % r.returncode)
    if r.returncode != 0:
        raise AssertionError(account.scrub("ssh -A : code %d ; stdout %r ; stderr : %s" % (
            r.returncode, r.stdout, r.stderr[-3000:])))
    seen = [l.split()[1] for l in r.stdout.splitlines() if re.match(r"\d+ SHA256:", l)]
    assert seen == [fp_fwd], "seule la clé transférée : %s" % r.stdout
    assert fp_hotes not in r.stdout and "PRIVATE KEY" not in r.stdout + r.stderr
    assert not [l for l in r.stderr.splitlines() if l.startswith("sshvault:")], account.scrub(r.stderr)
    stop_agent()

    # --- mot de passe d'hôte par sshvault-askpass (CAP-11), direct puis par le rebond A→P ---
    ask_log = home + "/askpass.log"
    pw_env = dict(tenv, SSH_ASKPASS="/usr/local/bin/sshvault-askpass", SSH_ASKPASS_REQUIRE="force",
                  SSHVAULT_TEST_ASKPASS_LOG=ask_log)
    with ArgvWatch(CLIENT_BW, [lab.password, account.password], heuristics=False) as w:
        for host in ("svlab-cp", "svlab-cpj"):
            before = len(client.run(["cat", ask_log]).stdout.splitlines())
            r = client_ssh(client, [host, "uname -n"], pw_env, batch=False)
            report.add("client : ssh %s (mot de passe par sshvault-askpass)" % host, note="rc=%d" % r.returncode)
            if r.returncode != 0:
                raise AssertionError(account.scrub("ssh %s : code %d ; stderr : %s" % (host, r.returncode, r.stderr[-3000:])))
            assert r.stdout == "p\n", "commande exécutée sur P"
            prompts = [l.rstrip() for l in client.read(ask_log).splitlines()[before:]]
            assert prompts == ["labpw@p's password:"], "une seule invite, de mot de passe : %s" % prompts
            assert lab.password not in r.stdout + r.stderr
            stop_agent()
    assert not w.suspect, "mot de passe en argument : %s" % w.suspect[:3]
    assert bw_seen(w), "le relevé voit un `bw` du conteneur pendant les connexions par mot de passe : %s" % sorted(
        a[:4] for a in w.seen)[:3]
    holders, readable = client.environ_holders(lab.password)
    assert readable >= 1 and not holders, "mot de passe de P dans l'environnement de processus du conteneur : %s" % holders
    roots = [home, runtime, "/tmp"]
    client_scan_control(client, roots)
    assert not client_files_with(client, lab.password, roots), "mot de passe de P écrit dans le conteneur"
    assert not client_files_with(client, account.password, roots), "mot de passe du compte écrit dans le conteneur"

    # --- generate puis deploy (D, par la clé admise) puis connexion avec la clé déployée ---
    authorized = "/home/lab/.ssh/authorized_keys"
    before = lab.exec("d", "cat", authorized).stdout
    r = sv("--nointeraction", "deploy", "--fingerprint", fp_gen, "svlab-d", "--", "-F", main)
    check(account, r, 0, "deploy (client)")
    assert r.stdout.startswith("ajoutée : « %s » %s → svlab-d" % (gen_name, fp_gen)), r.stdout
    after = lab.exec("d", "cat", authorized).stdout
    assert after.startswith(before), "lignes existantes de D gardées"
    added = after[len(before):].splitlines()
    assert len(added) == 1 and added[0].split()[:2] == public.split()[:2], "seule la clé déployée est ajoutée : %s" % added
    r = sv("--nointeraction", "deploy", "--fingerprint", fp_gen, "svlab-d", "--", "-F", main)
    check(account, r, 0, "deploy relancé (client)")
    assert r.stdout.startswith("déjà présente : "), r.stdout
    assert lab.exec("d", "cat", authorized).stdout == after, "second passage : rien écrit"
    stop_agent()
    r = client_ssh(client, ["-v", "svlab-cdg", "uname -n"], tenv)
    report.add("client : ssh svlab-cdg (clé générée puis déployée)", note="rc=%d" % r.returncode)
    if r.returncode != 0:
        raise AssertionError(account.scrub("ssh svlab-cdg : code %d ; stderr : %s" % (r.returncode, r.stderr[-3000:])))
    assert r.stdout == "d\n"
    assert set(OFFERED.findall(r.stderr)) == {fp_gen}, "seule la clé générée est offerte"
    assert accepted_in(lab.logs("d"), "lab", fp_gen), "D a admis la clé déployée"
    stop_agent()

    # --- rien de secret dans le conteneur ni dans `docker inspect` ; coffre relu par un autre client bw ---
    assert not client_files_with(client, "BEGIN OPENSSH PRIVATE KEY", roots), "clé privée écrite dans le conteneur"
    text = lab.inspect_text()
    for secret in (lab.password, account.password, ssh_keys["hotes"]["private"].splitlines()[1],
                   ssh_keys["sans-hotes"]["private"].splitlines()[1]):
        assert secret not in text, "secret dans docker inspect"
    pop, session = vault["_reader"]
    assert pop.sync(session).returncode == 0
    found = [it for it in json.loads(pop.ok("list", "items", session=session).stdout)
             if (it.get("sshKey") or {}).get("keyFingerprint") == fp_gen]
    assert len(found) == 1 and found[0]["sshKey"]["publicKey"] == public
    check(account, sv("logout", "--account", ALIAS), 0, "logout (client)")
    check_read_only_root(client)  # encore vrai après les scénarios (rien n'a remonté le système de fichiers)


# --- 2 ter. le conteneur client sans coffre, `lab.sh status` et `down` (story 23) -----------------------

def elf_like_the_host():
    """Chemin réel d'un exécutable ELF quelconque de l'architecture du poste (le conteneur client le reçoit en guise de
    `bw`, comme le contrôle de `client_up` l'exige ; il ne sert qu'à faire démarrer C : rien ne vérifie qu'il n'est pas lancé)."""
    host = elf_machine(os.path.realpath(sys.executable))
    for name in ("true", "sleep", "cat", "ls"):
        found = shutil.which(name)
        if found and host is not None and elf_machine(os.path.realpath(found)) == host:
            return os.path.realpath(found)
    pytest.skip("aucun exécutable ELF de l'architecture du poste sous la main")


STATUS_HEADER = ["NAME", "IMAGE", "COMMAND", "SERVICE", "CREATED", "STATUS", "PORTS"]


def status_rows(text):
    """{service : {colonne : texte}} de `lab.sh status` (`docker compose ps -a`, colonnes alignées sous l'en-tête
    complet NAME IMAGE COMMAND SERVICE CREATED STATUS PORTS : découpées d'après les positions de l'en-tête)."""
    lines = [l for l in text.splitlines() if l.strip()]
    assert lines and lines[0].split() == STATUS_HEADER, "en-tête de `docker compose ps` : %r" % text[:200]
    starts = [lines[0].index(h) for h in STATUS_HEADER]
    assert starts == sorted(starts)
    rows = {}
    for l in lines[1:]:
        cols = {h: l[a:b].strip() for h, a, b in zip(STATUS_HEADER, starts, starts[1:] + [len(l) + 1])}
        assert cols["SERVICE"] and cols["NAME"] and cols["STATUS"], "ligne de `docker compose ps` : %r" % l
        rows[cols["SERVICE"]] = cols
    return rows


def client_user_for(client, text, host, opts=(), name="bloc"):
    """Valeurs de `user` de `ssh -G -F <config `text`> <opts> <host>` dans le conteneur client (config écrite dans son HOME)."""
    path = "%s/.ssh-%s" % (client.home, name)
    client.write(path, text, "600")
    r = client.run(["ssh", "-G", "-F", path, *opts, host])
    assert r.returncode == 0, "ssh -G (client) : code %d : %s" % (r.returncode, r.stderr.strip()[-500:])
    return [l.split(" ", 1)[1] for l in r.stdout.splitlines() if l.split(" ", 1)[0] == "user"]


def check_all_hosts_rule(client):
    """Règle « bloc qui vaut pour tous les hôtes » (story 22) avec le client OpenSSH 10.0 : mêmes formes et mêmes sondes que
    les témoins 8.9 de `test_sshconfig.py` (`ALL_HOSTS`, `NOT_ALL_HOSTS`), mêmes verdicts. Positifs : le bloc s'applique à
    l'hôte `a` (une lettre, sans point) ; négatifs : il ne s'applique pas à leur sonde."""
    for block in ALL_HOSTS:
        assert client_user_for(client, "%s\n    User temoin\n" % block, "a") == ["temoin"], "10.0 : %s doit s'appliquer à a" % block
    for block, host, opts in NOT_ALL_HOSTS:
        assert client_user_for(client, "%s\n    User temoin\n" % block, host, opts) != ["temoin"], \
            "10.0 : %s ne doit pas s'appliquer à %s %s" % (block, host, " ".join(opts))


def test_client_sans_coffre(ssh_keys, report):
    """Le conteneur client C sans compte de test ni vrai `bw` (un exécutable ELF quelconque monté à sa place) : mêmes contraintes
    que dans le test du coffre (`check_client_container`) ; `lab.sh status` liste C ; `lab.sh down` le supprime, avec le reste du
    projet (contrôle « rien ne reste » : conteneurs, réseaux, volumes). Maquette propre à ce test (le `down` détruit tout)."""
    bw = elf_like_the_host()
    with running(ssh_keys["hotes"]["public"]) as lab:
        try:
            client = lab.client_up(bw, None, RUN_ID)
        except ClientUnavailable as e:
            pytest.skip(str(e))
        check_client_container(client, lab, bw, None, lambda text: text, report)
        check_all_hosts_rule(client)
        report.add("client sans coffre : blocs « tous les hôtes » (ssh -G, 10.0)",
                   note="%d formes positives, %d négatives, mêmes verdicts qu'en 8.9" % (len(ALL_HOSTS), len(NOT_ALL_HOSTS)))
        rows = status_rows(lab.sh("status").stdout)
        assert sorted(rows) == ["a", "b", "c", "d", "p"], "lab.sh status liste chaque service, C compris : %s" % sorted(rows)
        assert rows["c"]["IMAGE"] == "sshvault-lab/c" and rows["c"]["STATUS"].startswith("Up"), rows["c"]
        assert all(r["STATUS"].startswith("Up") for r in rows.values()), rows
        report.add("client sans coffre : lab.sh status", note="services=%s" % sorted(rows))
        # le premier `down`, seul (sans le nouvel essai de `Lab.down`) : code 0, rien ne reste
        r = lab.sh("down", check=False, timeout=300)
        assert r.returncode == 0 and "maquette détruite" in r.stdout, (r.returncode, r.stdout, r.stderr[-500:])
        left = lab.left()  # un seul relevé : le même pour l'assertion et son message
        assert left == {}, "rien ne reste du projet après le premier down : %s" % left
        assert lab.container_ids() == [], "client et maquette supprimés"
        assert status_rows(lab.sh("status").stdout) == {}, "lab.sh status ne liste plus rien"
        report.add("client sans coffre : lab.sh down", note="C supprimé, rien ne reste")


# --- 3. interruption ------------------------------------------------------------------------

def project_left(project):
    f = "label=com.docker.compose.project=" + project
    out = {}
    for k, c in (("conteneurs", ["docker", "ps", "-a", "-q"]), ("réseaux", ["docker", "network", "ls", "-q"]),
                 ("volumes", ["docker", "volume", "ls", "-q"])):
        r = subprocess.run(c + ["--filter", f], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, "%s : code %d : %s" % (" ".join(c), r.returncode, r.stderr.strip())
        out[k] = r.stdout.split()
    return out


@pytest.mark.parametrize("quand,sig", [("pendant le démarrage", signal.SIGINT), ("après le démarrage", signal.SIGINT),
                                       ("après le démarrage", signal.SIGTERM)])
def test_interruption(quand, sig, ssh_keys, tmp_path, report):
    """SIGINT (ou SIGTERM) au groupe de la sonde (comme Ctrl-C au terminal), pendant `lab.sh up` (dès que
    le premier conteneur du projet existe, `PRET` pas encore écrit) ou quand la maquette est prête : plus
    aucun conteneur, réseau ni volume du projet, et le dossier d'état de la sonde (mot de passe, clés) a
    disparu."""
    pub = tmp_path / "pub"
    pub.write_text(ssh_keys["hotes"]["public"] + "\n")
    probe_tmp = tmp_path / "sonde-tmp"  # TMPDIR de la sonde : son dossier d'état (mkdtemp) y est créé
    probe_tmp.mkdir()
    here = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.Popen([sys.executable, "-I", os.path.join(here, "labenv.py"), "sonde", str(pub)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
                         stdin=subprocess.DEVNULL, cwd=str(tmp_path), env=dict(os.environ, TMPDIR=str(probe_tmp)))
    project = None
    try:
        line = p.stdout.readline()
        assert line.startswith("PROJET "), (line, p.stderr.read() if p.poll() is not None else "")
        project = line.split()[1]
        if quand == "pendant le démarrage":
            # le signal doit tomber pendant `lab.sh up` : attendre le premier conteneur du projet (la
            # construction des images, la première fois, précède sa création)
            deadline = time.monotonic() + UP_TIMEOUT
            while not project_left(project)["conteneurs"]:
                assert p.poll() is None, "la sonde s'est arrêtée avant de démarrer la maquette : %s" % p.stderr.read()
                assert time.monotonic() < deadline, "aucun conteneur du projet %s en %d s" % (project, UP_TIMEOUT)
                time.sleep(0.1)
        else:
            assert p.stdout.readline().strip() == "PRET", p.stderr.read()
        os.killpg(p.pid, sig)
        out, err = p.communicate(timeout=300)
        assert p.returncode == 0, (out, err[-2000:])
        assert out.strip().splitlines()[-1] == "DETRUIT", out
        if quand == "pendant le démarrage":
            assert "PRET" not in out, "le signal est arrivé après le démarrage : %s" % out
        assert [n for n in os.listdir(str(probe_tmp)) if n.startswith("sshvault-lab-state-")] == [], \
            "dossier d'état de la sonde (mot de passe, clés) non supprimé"
    finally:
        try:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            # nettoyage de secours : sonde tuée ou sortie en échec avec le projet encore là
            if project:
                fallback_cleanup(project, probe_tmp)
        finally:
            shutil.rmtree(str(probe_tmp), ignore_errors=True)  # dossier d'état de la sonde (mot de passe, clés)
    assert project and not any(project_left(project).values()), project_left(project)
    report.add("interruption %s (%s)" % (quand, signal.Signals(sig).name), note="projet détruit")


def fallback_cleanup(project, probe_tmp):
    """`docker compose down -v` du projet de la sonde s'il en reste quelque chose (liste d'arguments, fichier
    Compose explicite, délai, code vérifié) ; l'appelant retire ensuite le dossier d'état de la sonde."""
    if any(project_left(project).values()):
        env = dict(os.environ, SSHVAULT_LAB_KEYS=os.path.join(str(probe_tmp), "inexistant"))
        r = subprocess.run(["docker", "compose", "-p", project, "-f", COMPOSE, "down", "-v", "--remove-orphans",
                            "--timeout", "5"], capture_output=True, text=True, timeout=300, env=env,
                           stdin=subprocess.DEVNULL)
        assert r.returncode == 0, "nettoyage de secours du projet %s : code %d : %s" % (
            project, r.returncode, r.stderr.strip()[-1000:])


# --- 4. clés d'hôte neuves, dossier d'état refusé ---------------------------------------------

def host_pub(text):
    """Blob base64 d'une clé publique (`type blob [commentaire]`)."""
    return text.split()[1]


def test_cles_d_hote_neuves(lab):
    """La clé d'hôte d'un conteneur Debian (A, D) en marche n'est pas celle cuite dans son image
    (`ssh-keygen -A` ne remplace pas une clé existante : l'entrée les retire d'abord)."""
    path = "/etc/ssh/ssh_host_ed25519_key.pub"
    for svc in ("a", "d"):
        baked = subprocess.run(["docker", "run", "--rm", "--entrypoint", "cat", "sshvault-lab/" + svc, path],
                               capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
        assert baked.returncode == 0 and baked.stdout.strip(), "clé cuite dans l'image %s : %s" % (svc, baked.stderr)
        running_key = lab.exec(svc, "cat", path).stdout
        assert host_pub(running_key) != host_pub(baked.stdout), "%s : la clé d'hôte de l'image est réutilisée" % svc


@pytest.mark.parametrize("dossier", ["relatif/dossier", "/tmp/a:b", "/tmp/a%b", '/tmp/a"b'])
def test_dossier_d_etat_refuse(dossier):
    """`lab.sh` refuse un dossier d'état relatif, ou contenant « : », « % » ou « \" » (avant tout appel à docker)."""
    env = dict(os.environ, SSHVAULT_LAB_DIR=dossier, SSHVAULT_LAB_PROJECT="sshvault-lab-refus")
    r = subprocess.run([LAB_SH, "password"], env=env, capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 1 and "dossier d'état" in r.stderr, (r.returncode, r.stderr)
    assert not os.path.exists(dossier), "rien n'est créé"

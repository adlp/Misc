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

import pytest

from bench import HAVE_OPENSSH, ArgvWatch, agent_list, write_askpass
from itbase import ALIAS, MARK, RUN, TAG, Report, Scrub, check, home, ssh_keys, sv, sv_login, vault  # noqa: F401
from labenv import COMPOSE, LAB_SH, UP_TIMEOUT, docker_available, running

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

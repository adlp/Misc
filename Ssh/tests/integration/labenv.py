"""Maquette de test à conteneurs ssh (story 20) : cycle de vie du projet Compose, partagé par
`test_lab.py` et par son sonde d'interruption (`python labenv.py sonde`).

Tout passe par `lab/lab.sh` (le même chemin que l'usage manuel) avec un nom de projet unique par
run et un dossier d'état temporaire :

    with running(public_keys) as lab:     # lab.sh up
        ...                               # lab.password, lab.config, lab.exec(...), lab.logs(...)
        client = lab.client_up(bw)        # conteneur client OpenSSH 10.0 (story 21) : client.run(...), client.sv(...)
    # sortie, même par exception, SIGINT ou SIGTERM : lab.sh down (nouvel essai une fois), puis
    # contrôle qu'aucun conteneur (client compris), réseau ni volume du projet ne reste (LabLeft sinon)
"""
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB_DIR = os.path.join(ROOT, "lab")
LAB_SH = os.path.join(LAB_DIR, "lab.sh")
COMPOSE = os.path.join(LAB_DIR, "compose.yaml")
PREFIX = "sshvault-lab-"
UP_TIMEOUT = 1200  # construction des images comprise (première fois)


class LabError(AssertionError):
    pass


class LabTimeout(LabError):
    """Commande du conteneur client sans réponse dans le délai."""


class ClientUnavailable(LabError):
    """Le conteneur client ne peut pas être monté avec ce `bw` (la série saute son test)."""


class LabLeft(LabError):
    """Conteneurs, réseaux ou volumes du projet restant après `down`."""


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=30).returncode == 0 \
            and subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def elf_machine(path):
    """`e_machine` de l'ELF `path` (None : pas un ELF lisible)."""
    try:
        with open(path, "rb") as f:
            head = f.read(20)
    except OSError:
        return None
    if len(head) < 20 or head[:4] != b"\x7fELF":
        return None
    return int.from_bytes(head[18:20], "little" if head[5] == 1 else "big")


class Lab:
    def __init__(self, project: str, state: str):
        self.project, self.state = project, state
        self.env = dict(os.environ, SSHVAULT_LAB_PROJECT=project, SSHVAULT_LAB_DIR=state)
        self.password = None
        self.config = None

    # --- lab.sh et docker compose ------------------------------------------------------------

    def sh(self, *args, timeout=UP_TIMEOUT, check=True):
        r = subprocess.run([LAB_SH, *args], env=self.env, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        if check and r.returncode != 0:
            raise LabError("lab.sh %s : code %d : %s" % (" ".join(args[:1]), r.returncode,
                                                         (r.stderr or r.stdout).strip()[-3000:]))
        return r

    def compose(self, *args, input=None, timeout=120, env=None):
        env = dict(self.env, SSHVAULT_LAB_KEYS=os.path.join(self.state, "keys"), **(env or {}))
        return subprocess.run(["docker", "compose", "-p", self.project, "-f", COMPOSE, *args], env=env,
                              capture_output=True, text=True, timeout=timeout, input=input,
                              **({} if input is not None else {"stdin": subprocess.DEVNULL}))

    def exec(self, service, *argv, input=None):
        """Commande dans un conteneur du projet ; LabError (avec stderr) si son code n'est pas 0."""
        r = self.compose("exec", "-T", service, *argv, input=input)
        if r.returncode != 0:
            raise LabError("exec %s %s : code %d : %s" % (service, " ".join(argv), r.returncode, r.stderr.strip()[-1000:]))
        return r

    def logs(self, service) -> str:
        """Journal du conteneur (stdout et stderr fondus : une longueur prise avant une action permet de ne
        lire ensuite que ce que l'action a écrit)."""
        env = dict(self.env, SSHVAULT_LAB_KEYS=os.path.join(self.state, "keys"))
        r = subprocess.run(["docker", "compose", "-p", self.project, "-f", COMPOSE, "logs", "--no-color",
                            "--no-log-prefix", service], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=120, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise LabError("docker compose logs %s : code %d : %s" % (service, r.returncode, r.stdout.strip()[-1000:]))
        return r.stdout

    def container_ids(self):
        r = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "label=com.docker.compose.project=" + self.project],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise LabError("docker ps : code %d : %s" % (r.returncode, r.stderr.strip()[-1000:]))
        return r.stdout.split()

    def inspect(self):
        """`docker inspect` de chaque conteneur du projet (liste de dictionnaires)."""
        ids = self.container_ids()
        if not ids:
            return []
        return json.loads(self.inspect_text())

    def inspect_text(self) -> str:
        ids = self.container_ids()
        if not ids:
            return ""
        r = subprocess.run(["docker", "inspect", *ids], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise LabError("docker inspect : code %d : %s" % (r.returncode, r.stderr.strip()[-1000:]))
        return r.stdout

    def left(self) -> dict:
        """Conteneurs, réseaux et volumes du projet encore présents."""
        f = "label=com.docker.compose.project=" + self.project
        out = {}
        for kind, cmd in (("conteneurs", ["docker", "ps", "-a", "-q"]), ("réseaux", ["docker", "network", "ls", "-q"]),
                          ("volumes", ["docker", "volume", "ls", "-q"])):
            r = subprocess.run(cmd + ["--filter", f], capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise LabError("%s : code %d : %s" % (" ".join(cmd), r.returncode, r.stderr.strip()))
            out[kind] = r.stdout.split()
        return {k: v for k, v in out.items() if v}

    def service_ports(self) -> dict:
        """{service: [(ip de l'hôte, port)]} publiés, d'après `docker inspect`."""
        out = {}
        for c in self.inspect():
            svc = c["Config"]["Labels"]["com.docker.compose.service"]
            out[svc] = [(b["HostIp"], int(b["HostPort"])) for binds in (c["NetworkSettings"]["Ports"] or {}).values()
                        for b in (binds or [])]
        return out

    def client_up(self, bw, ca=None, run_id=""):
        """Démarre le conteneur client C (profil Compose `client`, image `sshvault-lab/c` construite au besoin) :
        source du dépôt, `bw` (`bw` : son chemin) et le certificat `ca` (NODE_EXTRA_CA_CERTS, s'il y en a un)
        montés en lecture seule, uid et gid de l'utilisateur courant ; `run_id` : SSHVAULT_TEST_RUN des processus du
        conteneur (bench.RUN_ID). `ca` vide : absent. Supprimé par `lab.sh down` (même projet)."""
        ca = ca or None
        real_bw = os.path.realpath(bw)
        real_ca = os.path.realpath(ca) if ca else None
        # chemins de montage : « : » et « , » casseraient la syntaxe ; un fichier absent serait créé en dossier (root) par docker
        for what, p in (("bw", real_bw), ("certificat", real_ca)):
            if p and (":" in p or "," in p):
                raise LabError("chemin de %s refusé pour un montage (« : » ou « , ») : %s" % (what, p))
        if real_ca and not os.path.isfile(real_ca):
            raise LabError("certificat de NODE_EXTRA_CA_CERTS : fichier ordinaire absent : %s" % real_ca)
        try:
            with open(real_bw, "rb") as f:
                magic = f.read(4)
        except OSError as e:
            raise LabError("bw illisible : %s : %s" % (real_bw, e.strerror or e)) from None
        machine, host_machine = elf_machine(real_bw), elf_machine(os.path.realpath(sys.executable))
        if magic != b"\x7fELF" or (host_machine is not None and machine != host_machine):
            raise ClientUnavailable("bw n'est pas un exécutable ELF autonome de l'architecture du poste (%s) : il ne "
                                    "tournerait pas monté seul dans le conteneur client (il faut la version autonome de "
                                    "bw, sans Node)" % real_bw)
        env = {"SSHVAULT_TEST_RUN": run_id, "SSHVAULT_LAB_UID": str(os.getuid()), "SSHVAULT_LAB_GID": str(os.getgid()),
               "SSHVAULT_LAB_BW": real_bw}
        if real_ca:
            env["SSHVAULT_LAB_CA"] = real_ca
        r = self.compose("--profile", "client", "up", "-d", "--build", "--wait", "--wait-timeout", "300", "c",
                         env=env, timeout=UP_TIMEOUT)
        if r.returncode != 0:
            raise LabError("docker compose up c : code %d : %s" % (r.returncode, r.stderr.strip()[-3000:]))
        r = self.compose("--profile", "client", "ps", "-q", "c")
        cid = r.stdout.strip()
        if r.returncode != 0 or not cid:
            raise LabError("conteneur client introuvable : code %d : %s" % (r.returncode, r.stderr.strip()[-1000:]))
        return Client(self, cid, ca is not None)

    def down(self):
        """`lab.sh down` (code ignoré : le contrôle qui suit fait foi), nouvel essai une fois."""
        r = self.sh("down", check=False, timeout=300)
        left = self.left()
        if left:
            time.sleep(3)
            r = self.sh("down", check=False, timeout=300)
            left = self.left()
        return r, left


#: certificat du serveur dans le conteneur client (monté depuis NODE_EXTRA_CA_CERTS du compte, s'il est défini)
CLIENT_CA = "/lab/ca.pem"
CLIENT_HOME = "/home/lab"
CLIENT_BW = "/opt/bw/bw"


class Client:
    """Conteneur client C (story 21) : OpenSSH 10.0, sshvault de la source du dépôt, vrai `bw`. Toute commande passe
    par `docker exec` (jamais de secret en argv ni en variable d'environnement : un mot de passe passe par stdin
    ou sous le pty de `login_argv`). Variables propres au conteneur (HOME, XDG_RUNTIME_DIR, SSHVAULT_BW…) :
    celles de son environnement Compose."""

    def __init__(self, lab, cid, with_ca):
        self.lab, self.cid, self.with_ca = lab, cid, with_ca
        self.runtime = "/run/user/%d" % os.getuid()
        self.home = CLIENT_HOME

    def _env(self, env=None):
        e = {"NODE_EXTRA_CA_CERTS": CLIENT_CA} if self.with_ca else {}
        e.update(env or {})
        return e

    def argv(self, argv, env=None, stdin=False, tty=False):
        """Ligne de commande `docker exec` de `argv` dans le conteneur (stdin ouvert si `stdin`, pty si `tty`)."""
        out = ["docker", "exec"] + (["-i"] if stdin and not tty else []) + (["-it"] if tty else [])
        for k, v in self._env(env).items():
            out += ["-e", "%s=%s" % (k, v)]
        return out + [self.cid] + list(argv)

    def run(self, argv, env=None, input=None, timeout=300):
        """Commande dans le conteneur : CompletedProcess (texte), stdin /dev/null ou `input` ; sans réponse en
        `timeout` secondes : LabError (le processus du conteneur n'est pas tué : le conteneur est détruit à la fin)."""
        io = {"stdin": subprocess.DEVNULL} if input is None else {"input": input}
        try:
            return subprocess.run(self.argv(argv, env, stdin=input is not None), capture_output=True, text=True,
                                  timeout=timeout, **io)
        except subprocess.TimeoutExpired:
            raise LabTimeout("%s : sans réponse en %d s" % (" ".join(argv[:3]), timeout)) from None

    def sv(self, *args, env=None, input=None, timeout=600):
        return self.run(["sshvault", *args], env=env, input=input, timeout=timeout)

    def read(self, path):
        r = self.run(["cat", path])
        if r.returncode != 0:
            raise LabError("cat %s : code %d : %s" % (path, r.returncode, r.stderr.strip()[-500:]))
        return r.stdout

    def write(self, path, text, mode="600"):
        """`path` (dossiers parents créés en 0700) écrit avec `text`, droits `mode`."""
        r = self.run(["sh", "-c", 'umask 077 && mkdir -p "$(dirname "$1")" && cat > "$1" && chmod "$2" "$1"', "sh", path,
                      mode], input=text)
        if r.returncode != 0:
            raise LabError("écriture de %s : code %d : %s" % (path, r.returncode, r.stderr.strip()[-500:]))

    def stop_logins(self):
        """Arrête dans le conteneur les `sshvault login` et `bw login` encore en cours (un login bloqué, dont le client
        `docker exec` du poste a été interrompu, continuerait pendant le nouvel essai), puis vérifie qu'il n'en reste
        aucun (sinon LabError). Sans procps : lecture de /proc."""
        script = ("import os, signal, sys, time\n"
                  "me = os.getpid()\n"
                  "def pids():\n"
                  "    out = []\n"
                  "    for d in os.listdir('/proc'):\n"
                  "        if not d.isdigit() or int(d) == me:\n"
                  "            continue\n"
                  "        try:\n"
                  "            a = open('/proc/%s/cmdline' % d, 'rb').read().decode(errors='replace').split('\\0')\n"
                  "        except OSError:\n"
                  "            continue\n"
                  "        if 'login' in a[1:] and (os.path.basename(a[0]) == 'bw' or 'sshvault' in ' '.join(a[:3])):\n"
                  "            out.append(int(d))\n"
                  "    return out\n"
                  "for sig in (signal.SIGTERM, signal.SIGKILL):\n"
                  "    for p in pids():\n"
                  "        try:\n"
                  "            os.kill(p, sig)\n"
                  "        except OSError:\n"
                  "            pass\n"
                  "    time.sleep(0.5)\n"
                  "left = pids()\n"
                  "if left:\n"
                  "    print('login encore en cours :', *left)\n"
                  "    sys.exit(1)\n")
        r = self.run(["python3", "-c", script], timeout=60)
        if r.returncode != 0:
            raise LabError("arrêt des logins du conteneur : code %d : %s" % (r.returncode, (r.stdout + r.stderr).strip()[-500:]))

    def plant_environ(self, token):
        """Lance dans le conteneur un `sleep` dont l'environnement porte `token` (témoin de `environ_holders`)."""
        r = subprocess.run(["docker", "exec", "-d", "-e", "SSHVAULT_LAB_PLANT=" + token, self.cid, "sleep", "60"],
                           capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise LabError("docker exec -d : code %d : %s" % (r.returncode, r.stderr.strip()[-500:]))

    def environ_holders(self, secret):
        """(pids dont l'environnement contient `secret`, nombre d'environnements lisibles) parmi les processus du
        conteneur ; `secret` passe par stdin."""
        script = ("import os, sys\n"
                  "s = sys.stdin.read().rstrip('\\n').encode()\n"
                  "hit, readable = [], 0\n"
                  "for d in os.listdir('/proc'):\n"
                  "    if not d.isdigit() or int(d) == os.getpid():\n"
                  "        continue\n"
                  "    try:\n"
                  "        e = open('/proc/%s/environ' % d, 'rb').read()\n"
                  "    except OSError:\n"
                  "        continue\n"
                  "    readable += 1\n"
                  "    if s in e:\n"
                  "        hit.append(d)\n"
                  "print(readable, *hit)\n")
        r = self.run(["python3", "-c", script], input=secret + "\n", timeout=60)
        if r.returncode != 0:
            raise LabError("lecture des environnements : code %d : %s" % (r.returncode, r.stderr.strip()[-500:]))
        out = r.stdout.split()
        return out[1:], int(out[0])

    def login_argv(self):
        """Commande (pour `itbase.pty_login`) : `sshvault login` du conteneur sous un pty (`docker exec -it`), mot de
        passe tapé au terminal du poste, jamais en argv ni dans l'environnement."""
        return self.argv(["sshvault", "login"], tty=True)

    def login_env(self):
        """Environnement du client docker lancé par `login_argv` (rien du coffre : ni BW_*, ni SSHVAULT_IT*)."""
        return {k: v for k, v in os.environ.items() if not k.startswith(("BW_", "BITWARDENCLI_", "SSHVAULT_"))}


@contextlib.contextmanager
def running(public_keys: str, announce=None):
    """Maquette démarrée par `lab.sh up` (clés publiques `public_keys`, texte), détruite à la sortie.
    `announce(lab)` : appelé juste avant le démarrage (le projet existe déjà de nom)."""
    state = tempfile.mkdtemp(prefix="sshvault-lab-state-")
    os.chmod(state, 0o700)
    keys = os.path.join(state, "authorized.pub")
    with open(keys, "w") as f:
        f.write(public_keys.rstrip("\n") + "\n")
    lab = Lab(PREFIX + uuid.uuid4().hex[:10], os.path.join(state, "lab"))

    def interrupted(signum, frame):
        raise KeyboardInterrupt("signal %d" % signum)

    previous = {s: signal.signal(s, interrupted) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        try:
            if announce:
                announce(lab)
            lab.sh("up", keys)
            lab.password = lab.sh("password").stdout.strip()
            lab.config = lab.sh("config").stdout
            yield lab
        finally:
            # le nettoyage n'est pas interrompu par un second signal
            for s in previous:
                signal.signal(s, signal.SIG_IGN)
            try:
                r, left = lab.down()
                # `down` efface le mot de passe de P, le known_hosts et les clés admises (avant le rmtree final)
                for name in ("password", "known_hosts", os.path.join("keys", "authorized_keys")):
                    if os.path.exists(os.path.join(lab.state, name)):
                        left["fichier d'état " + name] = ["non effacé par lab.sh down"]
            finally:
                shutil.rmtree(state, ignore_errors=True)
            if left:
                raise LabLeft("reste du projet %s après down : %s ; %s" % (
                    lab.project, left, (r.stderr or r.stdout).strip()[-500:]))
    finally:
        for s, h in previous.items():
            signal.signal(s, h if h is not None else signal.SIG_DFL)


def probe():
    """Sonde de l'interruption : `python labenv.py sonde <fichier de clé publique>` démarre la maquette, écrit
    `PROJET <nom>` puis `PRET` sur stdout, et attend un signal (SIGINT ou SIGTERM). Code 0 si la
    maquette est détruite et plus rien du projet ne reste (`DETRUIT`), 1 sinon (`RESTE …` : il reste
    quelque chose ; `ERREUR …` : démarrage ou commande en échec)."""
    with open(sys.argv[2]) as f:
        pub = f.read()
    try:
        with running(pub, announce=lambda lab: print("PROJET " + lab.project, flush=True)):
            print("PRET", flush=True)
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    except LabLeft as e:
        print("RESTE " + str(e), flush=True)
        return 1
    except LabError as e:
        print("ERREUR " + str(e), flush=True)
        return 1
    print("DETRUIT", flush=True)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "sonde":
        sys.exit(probe())
    sys.exit("usage : labenv.py sonde <fichier de clé publique>")

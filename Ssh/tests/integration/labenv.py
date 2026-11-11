"""Maquette de test à conteneurs ssh (story 20) : cycle de vie du projet Compose, partagé par
`test_lab.py` et par son sonde d'interruption (`python labenv.py sonde`).

Tout passe par `lab/lab.sh` (le même chemin que l'usage manuel) avec un nom de projet unique par
run et un dossier d'état temporaire :

    with running(public_keys) as lab:     # lab.sh up
        ...                               # lab.password, lab.config, lab.exec(...), lab.logs(...)
    # sortie, même par exception, SIGINT ou SIGTERM : lab.sh down (nouvel essai une fois), puis
    # contrôle qu'aucun conteneur, réseau ni volume du projet ne reste (LabLeft sinon)
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

    def compose(self, *args, input=None, timeout=120):
        env = dict(self.env, SSHVAULT_LAB_KEYS=os.path.join(self.state, "keys"))
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

    def down(self):
        """`lab.sh down` (code ignoré : le contrôle qui suit fait foi), nouvel essai une fois."""
        r = self.sh("down", check=False, timeout=300)
        left = self.left()
        if left:
            time.sleep(3)
            r = self.sh("down", check=False, timeout=300)
            left = self.left()
        return r, left


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

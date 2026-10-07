"""`sshvault ensure --id ID` : charge à la demande la clé d'un élément dans l'agent dédié (CAP-7).

Appelé par ssh via la ligne `Match originalhost <motifs> exec "'<sshvault>' ensure --id <id>"`
du ssh_config généré, pour la cible comme pour chaque saut ProxyJump/ProxyCommand (le
sous-processus ssh du saut relit la config ; mesuré : la cible d'abord, puis le saut). Le
Match ne porte aucune directive : le code de sortie ne change rien à la connexion ; après
un échec, ssh continue et l'authentification échoue proprement.

- `ssh -G` (lecture de config sans connexion ; ssh parent lu dans /proc, en remontant le
  shell intermédiaire) : rien demandé, rien chargé, code 0.
- Chemin rapide : clé de l'élément dans l'agent dédié (état `agent.json` + `ssh-add -L`)
  avec plus de FRESH_MIN s restantes : ni bw ni réseau, rien affiché.
- Sinon, sous un verrou `flock` par utilisateur (`ensure.lock` à côté du socket) : état
  relu, puis chargement comme `load` (un seul `bw get item` avec la session rangée, sinon
  invite de déverrouillage ; agent démarré s'il le faut ; `ssh-add [-t key-ttl] [-c] [-h …] -`,
  clé par stdin ; tout ou rien ; état enregistré). Deux ssh parallèles : une invite, un
  `ssh-add` par clé.
- L'agent est vérifié avant le coffre : démarré s'il le faut (OpenSSH ≥ 8.9 vérifié),
  verrouillé → échec sans invite ni bw.
- Invite : /dev/tty seulement au premier plan du terminal, sinon askpass (exécutable) selon
  les règles de ssh, sinon échec rapide ; aucune sous `--nointeraction` ou si un ssh de la
  chaîne a `-o BatchMode=yes`. Jamais stdin (/dev/null sous Match exec). Délai de l'invite
  borné par le temps restant du délai global.
- Échec de déverrouillage (mot de passe refusé par bw, invite annulée ou sans réponse)
  mémorisé FAIL_MEMORY s dans `unlock-failed` (horodatage et identité de la connexion : pid
  et date de démarrage du ssh le plus haut) : pendant ce délai, les autres sauts de la même
  connexion échouent aussitôt, sans invite ni bw ; une autre connexion n'est pas gênée.
  Effacé par un déverrouillage réussi (ensure ou `sshvault unlock`).
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import signal
import stat
import time
from typing import Mapping, Optional

from . import fastpath
from .agent import (CMD_TIMEOUT as AGENT_TIMEOUT, Agent, AgentError, AgentLocked, PassphraseRefused,
                    askpass_rules, fingerprint, is_encrypted, literal_host, public_blob, resolve_dir,
                    tty_available)
from .agentstate import entry as state_entry, reconcile
from .backend import PasswordRefused, VaultBackend, VaultLocked
from .fastpath import clean, fresh, owns
from .fsutil import ensure_dir, read_private, write_private
from .prompt import UNAVAILABLE, PromptError, PromptUnavailable, ask_password, available, prompt_timeout
from .session import SessionStore

#: Durée (s) pendant laquelle un échec de déverrouillage empêche toute nouvelle invite.
FAIL_MEMORY = 30
#: Délai global d'un `ensure` (s), chemin rapide et attente du verrou compris (SSHVAULT_ENSURE_TIMEOUT).
DEFAULT_TIMEOUT = fastpath.DEFAULT_TIMEOUT
#: Marge (s) laissée au déverrouillage par bw après la fin d'une invite, dans le délai global.
PROMPT_MARGIN = 5.0
LOCK_NAME = "ensure.lock"
FAIL_NAME = "unlock-failed"
_GUARDED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM)


class Deadline(BaseException):
    """Délai global d'ensure dépassé (SIGALRM) ; BaseException : jamais avalée par un
    `except Exception` en chemin."""


class Context:
    """Ce que l'appel sait de son contexte : connexion (ssh le plus haut), hôte tapé, invite
    permise, échéance du délai global (time.monotonic) ou None."""

    def __init__(self, conn: Optional[str] = None, host: Optional[str] = None, interactive: bool = True,
                 deadline_at: Optional[float] = None, why_not: str = ""):
        self.conn, self.host, self.interactive = conn, host, interactive
        self.deadline_at, self.why_not = deadline_at, why_not

    def cap(self, timeout: float) -> float:
        """`timeout` borné par le temps restant (moins la marge du déverrouillage)."""
        if self.deadline_at is None:
            return timeout
        return max(1.0, min(timeout, self.deadline_at - time.monotonic() - PROMPT_MARGIN))


@contextlib.contextmanager
def signals_blocked():
    """Ctrl-C, SIGTERM, SIGHUP et le délai global retenus le temps d'un nettoyage."""
    old = signal.pthread_sigmask(signal.SIG_BLOCK, _GUARDED)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


# --- verrou et mémoire d'échec ---------------------------------------------------------------

@contextlib.contextmanager
def user_lock(directory: str):
    """`flock` exclusif sur `<dossier de l'agent>/ensure.lock` (fichier vide, 0600). L'attente
    est bornée par le délai global (SIGALRM interrompt flock)."""
    try:
        ensure_dir(directory)
        fd = os.open(os.path.join(directory, LOCK_NAME),
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600)
    except OSError as e:
        raise AgentError("verrou %s : %s" % (os.path.join(directory, LOCK_NAME), e.strerror or e)) from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            raise AgentError("verrou %s : pas un fichier ordinaire à l'utilisateur" % os.path.join(directory, LOCK_NAME))
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def recent_failure(directory: str, now: float, conn: Optional[str]) -> Optional[int]:
    """Âge (s) du dernier échec de déverrouillage de **cette** connexion s'il date de moins de
    FAIL_MEMORY s, sinon None (hors ssh, `conn` None : jamais)."""
    if conn is None:
        return None
    raw = read_private(os.path.join(directory, FAIL_NAME))
    if raw is None:
        return None
    try:
        ts, who = raw.decode().split()
        age = now - float(ts)
    except (ValueError, UnicodeDecodeError):
        return None
    return int(age) if who == conn and 0 <= age < FAIL_MEMORY else None


def record_failure(directory: str, conn: Optional[str]) -> None:
    if conn is None:
        return
    try:
        write_private(os.path.join(directory, FAIL_NAME), ("%d %s\n" % (int(time.time()), conn)).encode())
    except OSError:
        pass


def clear_failure(directory: str) -> None:
    try:
        os.unlink(os.path.join(directory, FAIL_NAME))
    except OSError:
        pass


def failed_message(age: int) -> str:
    return ("déverrouillage du coffre en échec il y a %ds pour cette connexion : pas de nouvelle invite avant %ds "
            "(ou « sshvault unlock »)" % (age, FAIL_MEMORY - age))


class UnlockPrompt:
    """Invite du mot de passe maître pour le backend : refusée pendant FAIL_MEMORY s après un
    échec de la même connexion ; une invite annulée ou sans réponse compte comme un échec, une
    invite impossible (ni terminal au premier plan, ni askpass exécutable) non."""

    def __init__(self, directory: str, env: Mapping[str, str], ctx: Context):
        self.dir, self.env, self.ctx, self.answered = directory, env, ctx, False

    def __call__(self, text: str) -> str:
        age = recent_failure(self.dir, time.time(), self.ctx.conn)
        if age is not None:
            raise VaultLocked(failed_message(age))
        if self.ctx.host:
            text = text.replace("mot de passe maître du coffre",
                                "mot de passe maître du coffre (clé pour %s)" % self.ctx.host, 1)
        try:
            pw = ask_password(text, self.env, timeout=self.ctx.cap(prompt_timeout(self.env)))
        except PromptUnavailable as e:
            raise VaultLocked("coffre verrouillé : %s" % e) from None
        except PromptError as e:
            record_failure(self.dir, self.ctx.conn)
            raise VaultLocked("coffre verrouillé : %s" % e) from None
        self.answered = True
        return pw


# --- chargement ----------------------------------------------------------------------------

def present_fresh(agent: Agent, item_id: str) -> bool:
    """Chemin rapide (le même que celui du point d'entrée) : ni bw, ni réseau, ni écriture."""
    return fastpath.present_fresh(agent.dir, item_id, agent.env)


def running_unlocked(agent: Agent) -> dict:
    """Agent à sshvault vivant (démarré s'il le faut, OpenSSH ≥ 8.9 vérifié au démarrage) et
    pas verrouillé ; sinon AgentLocked (code 3) ou l'erreur de l'agent (code 4)."""
    adata, _ = agent.ensure_running()
    if adata.get("locked"):
        if not agent.keys():
            raise AgentLocked("agent dédié verrouillé : lancer « sshvault agent unlock »")
        agent.update(lambda d: d.update(locked=False))  # l'agent montre des clés : pas verrouillé
        adata["locked"] = False
    return adata


def ensure(item_id: str, backend: VaultBackend, store: SessionStore, settings: dict,
           env: Optional[Mapping[str, str]] = None, agent: Optional[Agent] = None,
           ctx: Optional[Context] = None) -> str:
    """Clé de l'élément `item_id` (UUID en minuscules) présente dans l'agent dédié, chargée s'il
    le faut. `settings` : key-ttl, auto-confirm, auto-restrict. Renvoie "present" ou "loaded" ;
    toute impossibilité lève l'erreur à afficher (une ligne)."""
    env = os.environ if env is None else env
    ctx = ctx or Context()
    agent = agent or Agent(resolve_dir(env), env=env)
    if present_fresh(agent, item_id):
        return "present"
    with user_lock(agent.dir):
        if present_fresh(agent, item_id):  # chargée par un ensure parallèle pendant l'attente
            return "present"
        running_unlocked(agent)  # avant toute invite ou appel à bw
        if not store.get():
            # sans session rangée, il faudrait une invite : échec immédiat, sans bw, si elle est
            # interdite, impossible, ou si cette connexion vient d'échouer à déverrouiller
            age = recent_failure(agent.dir, time.time(), ctx.conn)
            if age is not None:
                raise VaultLocked(failed_message(age))
            if not ctx.interactive:
                raise VaultLocked("coffre verrouillé : aucune invite (%s)" % ctx.why_not)
            if not available(env):
                raise VaultLocked("coffre verrouillé : %s" % UNAVAILABLE)
        prompt = UnlockPrompt(agent.dir, env, ctx) if ctx.interactive else None
        try:
            item, key = backend.get_ssh_key(item_id, prompt)
        except PasswordRefused:
            record_failure(agent.dir, ctx.conn)
            raise
        if prompt is not None and prompt.answered:
            clear_failure(agent.dir)
        try:
            return load(agent, item, key, settings, env, ctx)
        finally:
            del key


def load(agent: Agent, item, key: bytes, settings: dict, env: Mapping[str, str],
         ctx: Optional[Context] = None) -> str:
    """Chargement d'une clé comme `load` : agent démarré s'il le faut, tout ou rien, état enregistré."""
    ctx = ctx or Context()
    blob = public_blob(item.public_key)
    if blob is None:
        raise AgentError("« %s » : clé publique de l'élément illisible : rien chargé" % clean(item.name))
    fp = fingerprint(blob)
    iid = item.id.lower()
    adata = running_unlocked(agent)
    keys = agent.keys()
    e = adata["keys"].get(fp)
    if fp in {k.fingerprint for k in keys} and e is not None and fresh(e, time.time()):
        # même clé enregistrée pour un autre élément : celui-ci y est ajouté (chemin rapide)
        if not owns(e, iid):
            def also(d):
                x = d["keys"].get(fp)
                if x is not None and not owns(x, iid):
                    x["also"] = [a for a in (x.get("also") or []) if isinstance(a, str)] + [item.id]
            agent.update(also)
        return "present"
    lifetime = settings["key-ttl"]
    # une clé rechargée garde ses protections (-c, -h) si elle les avait
    confirm = bool(settings["auto-confirm"] or (e and e["confirm"]))
    restrict = bool(settings["auto-restrict"] or (e and e["restrict"]))
    if confirm and (adata.get("agent") or {}).get("askpass") is False:
        raise AgentError("auto-confirm : l'agent dédié a été lancé sans askpass utilisable (DISPLAY, SSH_ASKPASS) : "
                         "la confirmation serait toujours refusée ; rien chargé (« sshvault agent stop », puis "
                         "se connecter depuis une session graphique)")
    hosts = [h.lower() for h in item.hosts]
    if restrict:
        if not hosts:
            raise AgentError("auto-restrict : « %s » n'a aucun hôte associé : rien chargé" % clean(item.name))
        bad = [h for h in hosts if not literal_host(h)]
        if bad:
            raise AgentError("auto-restrict : hôte « %s » de « %s » non littéral (motif, user@, >, :port) : "
                             "rien chargé" % (clean(bad[0]), clean(item.name)))
        agent.check_hosts(sorted(set(hosts)))
    enc = is_encrypted(key)
    if enc and not (ctx.interactive and (tty_available() or askpass_rules(agent.env)[1])):
        raise PassphraseRefused("« %s » : clé chiffrée par passphrase, saisie impossible (ni terminal au premier "
                                "plan, ni askpass) : rien chargé" % clean(item.name))
    before = {k.blob for k in keys}
    added = {}
    t = time.time()
    try:
        try:
            agent.add(key, lifetime, confirm, hosts if restrict else (), enc, enc,
                      ctx.cap(prompt_timeout(env) + 10) if enc else AGENT_TIMEOUT)
        finally:
            after = {k.blob: k for k in agent.keys()}
            added = {b: k for b, k in after.items() if b not in before}
        # la clé attendue est là, et rien d'autre n'est apparu (une clé privée différente
        # s'ajouterait à côté d'une ancienne copie de la bonne)
        if (blob not in after or any(b != blob for b in added)) and not (lifetime and time.time() - t >= lifetime):
            raise AgentError("« %s » : clé privée différente de la clé publique de l'élément : rien chargé"
                             % clean(item.name))

        def record(d):
            reconcile(d, {k.fingerprint for k in agent.keys()}, time.time())
            d["keys"][fp] = state_entry(item.id, item.name, item.hosts, t, lifetime, confirm, restrict)
        agent.update(record)  # en échec : clé retirée, jamais une clé chargée sans état
    except BaseException:
        with signals_blocked():
            for k in added.values():
                try:
                    agent.remove(k)
                except AgentError:
                    pass
        raise
    return "loaded"

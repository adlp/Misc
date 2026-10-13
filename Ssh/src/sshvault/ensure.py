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

Plusieurs comptes (CAP-10) : l'élément est désigné par (compte, id) ; session, invite (qui nomme
l'alias) et mémoire d'échec (`unlock-failed.<alias>`) sont propres au compte : un échec sur un
compte ne bloque pas les autres. Une connexion qui touche plusieurs comptes : au plus une invite
par compte.

`sshvault ensure --forward FID --id ID…` (CAP-8, `ensure_forward`) : même chose pour le
sous-agent de transfert `fwd/<fid>.sock`, jamais pour l'agent dédié (dont l'état est seulement
lu : verrouillé par `agent lock` → refus). Clés `ssh-add [-t key-ttl] [-c] -` (`-c` selon
`forward-confirm`, défaut oui : sans askpass utilisable pour le sous-agent, refus), jamais
`-h` ; tout ou rien ; clés en trop (élément retiré, clé changée, chargée à la main) retirées.
Même verrou `ensure.lock`, même invite unique et même mémoire d'échec que `--id`.
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
                    askpass_rules, fingerprint, forward_agent, forward_id, is_encrypted, literal_host, public_blob,
                    resolve_dir, tty_available)
from .agentstate import entry as state_entry, reconcile
from .backend import NotLoggedIn, PasswordRefused, VaultBackend, VaultLocked
from .fastpath import clean, forward_wanted, fresh, owns
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
def user_lock(directory: str, on_wait=None):
    """`flock` exclusif sur `<dossier de l'agent>/ensure.lock` (fichier vide, 0600). L'attente
    est bornée par le délai global (SIGALRM interrompt flock). `on_wait` : appelé une fois si le
    verrou est déjà tenu, avant d'attendre."""
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
        if on_wait is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                on_wait()
                fcntl.flock(fd, fcntl.LOCK_EX)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def fail_path(directory: str, account: Optional[str] = None) -> str:
    """Mémoire d'échec du compte `account` (`unlock-failed.<alias>`), `unlock-failed` sans compte."""
    return os.path.join(directory, FAIL_NAME + ("." + account if account else ""))


def recent_failure(directory: str, now: float, conn: Optional[str], account: Optional[str] = None) -> Optional[int]:
    """Âge (s) du dernier échec de déverrouillage du compte pour **cette** connexion s'il date de
    moins de FAIL_MEMORY s, sinon None (hors ssh, `conn` None : jamais)."""
    if conn is None:
        return None
    raw = read_private(fail_path(directory, account))
    if raw is None:
        return None
    try:
        ts, who = raw.decode().split()
        age = now - float(ts)
    except (ValueError, UnicodeDecodeError):
        return None
    return int(age) if who == conn and 0 <= age < FAIL_MEMORY else None


def record_failure(directory: str, conn: Optional[str], account: Optional[str] = None) -> None:
    if conn is None:
        return
    try:
        write_private(fail_path(directory, account), ("%d %s\n" % (int(time.time()), conn)).encode())
    except OSError:
        pass


def clear_failure(directory: str, account: Optional[str] = None) -> None:
    try:
        os.unlink(fail_path(directory, account))
    except OSError:
        pass


def failed_message(age: int, account: Optional[str] = None, hint: str = "") -> str:
    """Compte nommé seulement s'il y en a plusieurs (`hint` : « --account <alias> »)."""
    account = account if hint else None
    return ("déverrouillage du coffre%s en échec il y a %ds pour cette connexion : pas de nouvelle invite avant %ds "
            "(ou « sshvault unlock%s »)" % (" « %s »" % account if account else "", age, FAIL_MEMORY - age, hint))


class UnlockPrompt:
    """Invite du mot de passe maître pour le backend : refusée pendant FAIL_MEMORY s après un
    échec de la même connexion ; une invite annulée ou sans réponse compte comme un échec, une
    invite impossible (ni terminal au premier plan, ni askpass exécutable) non."""

    def __init__(self, directory: str, env: Mapping[str, str], ctx: Context, account: Optional[str] = None,
                 hint: str = ""):
        self.dir, self.env, self.ctx, self.answered = directory, env, ctx, False
        self.account, self.hint = account, hint

    def __call__(self, text: str) -> str:
        age = recent_failure(self.dir, time.time(), self.ctx.conn, self.account)
        if age is not None:
            raise VaultLocked(failed_message(age, self.account, self.hint))
        if self.ctx.host:
            if text.endswith(" : "):
                text = text[:-3] + ", clé pour %s : " % self.ctx.host
            else:
                text += " (clé pour %s)" % self.ctx.host
        try:
            pw = ask_password(text, self.env, timeout=self.ctx.cap(prompt_timeout(self.env)))
        except PromptUnavailable as e:
            raise VaultLocked("coffre verrouillé : %s" % e) from None
        except PromptError as e:
            record_failure(self.dir, self.ctx.conn, self.account)
            raise VaultLocked("coffre verrouillé : %s" % e) from None
        self.answered = True
        return pw


# --- chargement ----------------------------------------------------------------------------

def present_fresh(agent: Agent, item_id: str, account: Optional[str] = None) -> bool:
    """Chemin rapide (le même que celui du point d'entrée) : ni bw, ni réseau, ni écriture."""
    return fastpath.present_fresh(agent.dir, item_id, agent.env, account=account)


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


AGENT_LOCKED = "agent verrouillé : lancer « sshvault agent unlock »"


def probed_locked(agent: Agent) -> bool:
    """Agent verrouillé, par sshvault ou hors de sshvault (`ssh-add -x`) ? Agent qui ne liste
    aucune clé, quel que soit son état (état vide compris : seul compte déconnecté, puis
    `ssh-add -x`) : verdict de `ssh-add -D` (`Agent.probe_locked`). À appeler sous
    `ensure.lock`, compte déconnecté seulement. Agent qui liste une clé : False."""
    if agent.state.load().get("locked"):
        return True
    if agent.keys():
        return False
    return agent.probe_locked()


def _unlock_possible(directory: str, store: SessionStore, env: Mapping[str, str], ctx: Context,
                     account: Optional[str] = None, hint: str = "", agent: Optional[Agent] = None) -> None:
    """Sans session rangée, il faudrait une invite : échec immédiat, sans bw, si elle est
    interdite, impossible, ou si cette connexion vient d'échouer à déverrouiller ce compte.
    Compte déconnecté (marqueur) : « agent verrouillé » d'abord si la sonde de `agent` le dit."""
    if store.get():
        return
    if fastpath.logged_out(account, env):
        if agent is not None and probed_locked(agent):
            raise AgentLocked(AGENT_LOCKED)
        raise NotLoggedIn(fastpath.logged_out_message(account))
    age = recent_failure(directory, time.time(), ctx.conn, account)
    if age is not None:
        raise VaultLocked(failed_message(age, account, hint))
    which = " « %s »" % account if account and hint else ""  # compte nommé s'il y en a plusieurs
    if not ctx.interactive:
        raise VaultLocked("coffre%s verrouillé : aucune invite (%s)" % (which, ctx.why_not))
    if not available(env):
        raise VaultLocked("coffre%s verrouillé : %s" % (which, UNAVAILABLE))


def _hint(backend) -> str:
    return getattr(backend, "hint", "") or ""


def ensure(item_id: str, backend: VaultBackend, store: SessionStore, settings: dict,
           env: Optional[Mapping[str, str]] = None, agent: Optional[Agent] = None,
           ctx: Optional[Context] = None, account: Optional[str] = None) -> str:
    """Clé de l'élément (`account`, `item_id` en minuscules) présente dans l'agent dédié, chargée
    s'il le faut. `settings` : key-ttl, auto-confirm, auto-restrict. Renvoie "present" ou
    "loaded" ; toute impossibilité lève l'erreur à afficher (une ligne)."""
    env = os.environ if env is None else env
    ctx = ctx or Context()
    agent = agent or Agent(resolve_dir(env), env=env)
    if present_fresh(agent, item_id, account):
        return "present"
    with user_lock(agent.dir):
        if present_fresh(agent, item_id, account):  # chargée par un ensure parallèle pendant l'attente
            return "present"
        running_unlocked(agent)  # avant toute invite ou appel à bw
        _unlock_possible(agent.dir, store, env, ctx, account, _hint(backend), agent)
        prompt = UnlockPrompt(agent.dir, env, ctx, account, _hint(backend)) if ctx.interactive else None
        try:
            item, key = backend.get_ssh_key(item_id, prompt)
        except PasswordRefused:
            record_failure(agent.dir, ctx.conn, account)
            raise
        if prompt is not None and prompt.answered:
            clear_failure(agent.dir, account)
        try:
            return load(agent, item, key, settings, env, ctx, account)
        finally:
            del key


def load(agent: Agent, item, key: bytes, settings: dict, env: Mapping[str, str],
         ctx: Optional[Context] = None, account: Optional[str] = None) -> str:
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
        if not owns(e, iid, account):
            def also(d):
                x = d["keys"].get(fp)
                if x is not None and not owns(x, iid, account):
                    x["also"] = [a for a in (x.get("also") or []) if isinstance(a, str)] + [
                        "%s:%s" % (account, item.id) if account else item.id]
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
            d["keys"][fp] = state_entry(item.id, item.name, item.hosts, t, lifetime, confirm, restrict, account)
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


# --- transfert d'agent restreint (CAP-8) ------------------------------------------------------

FORWARD_LOCKED = ("agent dédié verrouillé : transfert d'agent refusé (« sshvault agent unlock » ; « sshvault agent "
                  "stop » s'il ne répond plus)")
STALE_PUB = ("élément %s : clé du coffre différente de celle du ssh_config généré : rien transféré "
             "(lancer « sshvault ssh-config »)")
NO_ASKPASS = ("forward-confirm : aucun askpass utilisable pour le sous-agent de transfert (DISPLAY, SSH_ASKPASS) : "
              "la confirmation serait toujours refusée ; rien chargé (se connecter depuis une session graphique, ou "
              "« sshvault config set forward-confirm false »)")


def forward_ready(sub: Agent, confirm: bool) -> dict:
    """Sous-agent vivant (démarré s'il le faut). Avec `confirm` : il doit avoir été lancé avec
    un askpass utilisable ; sinon relancé si cet environnement en a un (un sous-agent se
    recharge à la demande), refusé s'il n'en a pas (AgentError, rien démarré)."""
    if confirm:
        usable = askpass_rules(sub._agent_env())[1]
        with sub.locked():
            kind, data = sub.probe()
            # askpass inconnu (None : sous-agent repris, enregistrement reconstruit) compté comme absent
            if kind == "ours" and (data.get("agent") or {}).get("askpass") is not True:
                # refusé ou non, ce sous-agent (clés peut-être sans -c) ne doit plus servir
                try:
                    sub.purge()
                except AgentError:
                    pass
                sub.stop()
                if not usable:
                    raise AgentError(NO_ASKPASS)
            elif kind != "ours" and kind != "foreign" and not usable:
                raise AgentError(NO_ASKPASS)
    return running_unlocked(sub)


def drop_extras(sub: Agent, ids, env: Mapping[str, str]) -> list:
    """Retire du sous-agent toute clé qui n'est pas autorisée pour `ids` (clé d'un élément
    retiré du transfert, clé changée dans le coffre, clé chargée à la main), et de son état
    toute entrée absente de l'agent ou non autorisée. Renvoie les empreintes retirées."""
    allowed, _ = forward_wanted(sub.state.load(), ids, env, time.time())
    gone = [k for k in sub.keys() if k.fingerprint not in allowed]
    for k in gone:
        sub.remove(k)
    present = {k.fingerprint for k in sub.keys()}

    def prune(d):
        d["keys"] = {fp: e for fp, e in d["keys"].items() if fp in present and fp in allowed}
    sub.update(prune)
    return [k.fingerprint for k in gone]


def _rollback(sub: Agent, before: set) -> None:
    """Retire les clés apparues depuis `before` (blobs) et leurs entrées d'état."""
    try:
        for k in sub.keys():
            if k.blob not in before:
                sub.remove(k)
        present = {k.fingerprint for k in sub.keys()}
        sub.update(lambda d: d.update(keys={fp: e for fp, e in d["keys"].items() if fp in present}))
    except AgentError:
        pass


def ensure_forward(fid: str, ids, backend: Optional[VaultBackend], store: Optional[SessionStore], settings: dict,
                   env: Optional[Mapping[str, str]] = None, ctx: Optional[Context] = None,
                   directory: Optional[str] = None, accounts: Optional[Mapping] = None) -> str:
    """Clés des éléments `ids` (UUID en minuscules, ou couples (compte, UUID)), et elles seules,
    dans le sous-agent de transfert `fid`, chargées s'il le faut. `accounts` : {alias : (backend,
    magasin de session)} des comptes de `ids` ; sans lui, `backend` et `store` pour tous. Au plus
    une invite par compte ; un échec de déverrouillage est mémorisé pour son seul compte.
    `settings` : key-ttl, forward-confirm. Renvoie "present" ou "loaded" ; toute impossibilité
    lève l'erreur à afficher (une ligne), rien chargé (tout ou rien). L'agent dédié n'est
    jamais contacté."""
    env = os.environ if env is None else env
    ctx = ctx or Context()
    base = directory or resolve_dir(env)
    ids = [fastpath._pair(i) for i in ids]

    def access(a):
        return accounts[a] if accounts is not None else (backend, store)
    sub = forward_agent(base, fid, env)
    if fastpath.forward_fresh(base, fid, ids, env):
        return "present"
    with user_lock(base):
        if fastpath.forward_fresh(base, fid, ids, env):  # chargé par un ensure parallèle
            return "present"
        if fastpath.main_locked(base):
            raise AgentLocked(FORWARD_LOCKED)
        confirm = bool(settings["forward-confirm"])
        forward_ready(sub, confirm)  # avant toute invite ou appel à bw
        drop_extras(sub, ids, env)
        todo = _missing(sub, ids, env, need_fresh=True)
        if not todo:
            return "present"
        groups = {}  # compte -> [ids], dans l'ordre
        for a, i in todo:
            groups.setdefault(a, []).append(i)
        for a in groups:  # toute invite impossible dite avant la première invite
            _unlock_possible(base, access(a)[1], env, ctx, a, _hint(access(a)[0]))
        got = []
        try:
            for a, iids in groups.items():
                b = access(a)[0]
                prompt = UnlockPrompt(base, env, ctx, a, _hint(b)) if ctx.interactive else None
                try:
                    for i in iids:
                        got.append((a,) + tuple(b.get_ssh_key(i, prompt)))
                except PasswordRefused:
                    record_failure(base, ctx.conn, a)
                    raise
                if prompt is not None and prompt.answered:
                    clear_failure(base, a)
            for acct, item, _ in got:
                # le coffre fait foi : une clé dont l'élément ne déclare plus ce transfert n'est
                # pas chargée (config générée périmée)
                if not any(forward_id(p) == fid for p in item.forward):
                    raise AgentError("« %s » n'est plus déclarée pour ce transfert dans le coffre : rien chargé "
                                     "(lancer « sshvault ssh-config »)" % clean(item.name))
                # clé du coffre différente du `.pub` généré (clé changée, config non régénérée) :
                # elle serait retirée aussitôt ; refus avant tout chargement
                pub = fastpath.pub_fingerprint(item.id.lower(), env, acct)
                blob = public_blob(item.public_key)
                if pub is not None and blob is not None and fingerprint(blob) != pub:
                    raise AgentError(STALE_PUB % item.id.lower())
            if fastpath.main_locked(base):
                # `agent lock` posé pendant la lecture du coffre (il attend ensure.lock, mais un
                # verrou posé autrement passerait) : rien chargé
                raise AgentLocked(FORWARD_LOCKED)
            fset = {"key-ttl": settings["key-ttl"], "auto-confirm": confirm, "auto-restrict": False}
            before = {k.blob for k in sub.keys()}
            try:
                for a, item, key in got:
                    load(sub, item, key, fset, env, ctx, a)
                drop_extras(sub, ids, env)
                missing = _missing(sub, ids, env, need_fresh=False)
                if missing:
                    # clé chargée puis retirée (filet : contrôle préalable ci-dessus)
                    raise AgentError(STALE_PUB % missing[0][1])
            except BaseException:
                with signals_blocked():
                    _rollback(sub, before)
                raise
        finally:
            got.clear()
    return "loaded"


def _missing(sub: Agent, ids, env: Mapping[str, str], need_fresh: bool) -> list:
    """Éléments de `ids` sans clé autorisée présente dans le sous-agent (fraîche si `need_fresh`,
    égale au `.pub` de la config générée s'il y en a un)."""
    have = {k.fingerprint for k in sub.keys()}
    data = sub.state.load()
    now = time.time()
    out = []
    for x in ids:
        a, i = fastpath._pair(x)
        ok = {fp for fp, e in data["keys"].items()
              if owns(e, i, a) and fp in have and (not need_fresh or fresh(e, now))}
        pub = fastpath.pub_fingerprint(i, env, a)
        if pub is not None:
            ok &= {pub}
        if not ok:
            out.append((a, i))
    return out


def forward_socket_only(fid: str, env: Optional[Mapping[str, str]] = None, directory: Optional[str] = None) -> str:
    """Saut `ssh -W` (ProxyJump, ProxyCommand `ssh -W`) : aucun canal de session, rien n'est
    transféré, mais `-W` impose ExitOnForwardFailure (mesuré, 8.9p1) : un socket de
    `ForwardAgent` absent arrête le saut. Le sous-agent est lancé (vide) s'il manque ; ni
    coffre, ni clé, ni invite. Renvoie "present" ou "started"."""
    env = os.environ if env is None else env
    sub = forward_agent(directory or resolve_dir(env), fid, env)
    if os.path.exists(sub.socket):
        return "present"
    _, started = sub.ensure_running()
    return "started" if started else "present"

"""Commande `sshvault`.

Codes de sortie :
  0  succès
  1  aucun résultat (search, load)
  2  usage (option ou argument invalide ; load sans sélection ni --all ; durée invalide ;
     config.json invalide, illisible ou aux droits inattendus)
  3  non connecté au coffre, ou coffre verrouillé (aucune invite possible, mot de passe refusé) ;
     agent dédié arrêté ou verrouillé ; passphrase d'une clé refusée ou impossible à saisir
  4  erreur du backend (bw absent, en erreur, réponse illisible, délai dépassé), de l'agent
     dédié (XDG_RUNTIME_DIR relatif, non privé ou hors tmpfs, chemin du socket trop long,
     agent tiers, OpenSSH < 8.9, --restrict : élément sans hôte, hôte non littéral ou absent
     de known_hosts ; clé publique illisible ou différente de la clé privée), écriture de
     config.json impossible, ou erreur interne
  130 interrompu (Ctrl-C, SIGTERM, SIGHUP)
`status` : 0 si le coffre est déverrouillé, 3 s'il est verrouillé ou non connecté, 4 en erreur.
`agent status` : 0 si l'agent dédié tourne, 3 s'il est arrêté, 4 en erreur ou agent tiers.
Toute erreur donne une seule ligne sur stderr, jamais de traceback.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from typing import Optional

from . import __version__
from .agent import (CMD_TIMEOUT as AGENT_TIMEOUT, Agent, AgentError, AgentLocked, AgentStopped,
                    PassphraseRefused, askpass_rules, fingerprint, is_encrypted, literal_host, public_blob,
                    resolve_dir, tty_available)
from .agentstate import entry as state_entry, maybe_locked, reconcile, remaining
from .backend import BackendError, NotLoggedIn, SshKeyItem, VaultBackend, VaultError, VaultLocked
from .bw import BwBackend
from .config import Config, ConfigError, ConfigWriteError, describe_duration, parse_duration
from .prompt import DEFAULT_TIMEOUT as PROMPT_TIMEOUT, PromptError, ask_password, prompt_timeout
from .bw import DEFAULT_TIMEOUT as BW_TIMEOUT
from .session import DEFAULT_TTL, SessionStore, SessionStoreError
from .settings import seconds

RC_OK, RC_NONE, RC_USAGE, RC_LOCKED, RC_BACKEND, RC_INTERRUPTED = 0, 1, 2, 3, 4, 130


class UsageError(Exception):
    pass


class Interrupted(BaseException):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):  # une ligne, code 2
        raise UsageError(message)


def err(msg: str) -> None:
    print("sshvault: %s" % " ".join(str(msg).split()), file=sys.stderr, flush=True)


def make_prompt(args):
    if args.nointeraction:
        return None

    def prompt(text: str) -> str:
        try:
            return ask_password(text)
        except PromptError as e:
            raise VaultLocked("coffre verrouillé : %s" % e) from None
    return prompt


def ttl_arg(s: str) -> int:
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("durée de vie invalide : %r (secondes, entier > 0)" % s)
    if v < 1:
        raise argparse.ArgumentTypeError("durée de vie invalide : %r (secondes, entier > 0)" % s)
    return v


def duration_arg(s: str) -> int:
    try:
        return parse_duration(s)
    except ConfigError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def build_parser() -> Parser:
    p = Parser(prog="sshvault", description="Clés SSH du coffre Vaultwarden (via bw).",
               epilog="Codes de sortie : 0 ok, 1 aucun résultat, 2 usage, "
                      "3 non connecté ou verrouillé (coffre ou agent, passphrase refusée), "
                      "4 erreur backend ou agent, 130 interrompu. "
                      "status : 0 déverrouillé, 3 sinon ; agent status : 0 actif, 3 arrêté.")
    p.add_argument("--version", action="version", version="sshvault " + __version__)
    p.add_argument("--nointeraction", action="store_true",
                   help="ne jamais rien demander : mot de passe du coffre, passphrase d'une clé, "
                        "mot de passe de verrouillage de l'agent (code 3)")
    sub = p.add_subparsers(dest="cmd", metavar="COMMANDE", parser_class=Parser)
    sub.required = True
    sub.add_parser("status", help="état du coffre et de la session")
    s = sub.add_parser("login", help="connexion au coffre (interactive, déléguée à bw)")
    s.add_argument("--server", metavar="URL", help="URL du serveur Vaultwarden (bw config server)")
    s.add_argument("--apikey", action="store_true", help="connexion par clé API (BW_CLIENTID/BW_CLIENTSECRET)")
    s = sub.add_parser("unlock", help="déverrouille le coffre et garde la session")
    s.add_argument("--ttl", type=ttl_arg, default=DEFAULT_TTL, metavar="SECONDES",
                   help="durée de vie de la session (défaut %d)" % DEFAULT_TTL)
    sub.add_parser("lock", help="verrouille le coffre et oublie la session")
    sub.add_parser("sync", help="resynchronise le coffre depuis le serveur")
    s = sub.add_parser("list", help="liste les clés SSH du coffre")
    s.add_argument("--json", action="store_true", help="sortie JSON")
    s = sub.add_parser("search", help="cherche des clés par hôte, nom ou empreinte")
    s.add_argument("pattern", metavar="MOTIF")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--host", dest="by", action="store_const", const="host",
                   help="motif glob d'hôte (insensible à la casse)")
    g.add_argument("--name", dest="by", action="store_const", const="name",
                   help="sous-chaîne du nom (insensible à la casse)")
    g.add_argument("--fingerprint", dest="by", action="store_const", const="fingerprint",
                   help="empreinte exacte, avec ou sans « SHA256: »")
    s.add_argument("--json", action="store_true", help="sortie JSON")

    s = sub.add_parser("load", help="charge des clés du coffre dans l'agent dédié")
    s.add_argument("pattern", metavar="MOTIF", nargs="?", help="comme search (ou --all)")
    s.add_argument("--all", action="store_true", help="toutes les clés SSH du coffre")
    g = s.add_mutually_exclusive_group()
    for flag, what in (("host", "motif glob d'hôte"), ("name", "sous-chaîne du nom"),
                       ("fingerprint", "empreinte exacte"), ("id", "id exact de l'élément")):
        g.add_argument("--" + flag, dest="by", action="store_const", const=flag, help=what)
    s.add_argument("-t", dest="lifetime", type=duration_arg, metavar="DURÉE",
                   help="durée de vie : N, Ns, Nm, Nh, Nd, 0 = illimitée (défaut : config key-ttl, sinon 1h)")
    s.add_argument("--confirm", action="store_true", help="confirmation à chaque usage (ssh-add -c)")
    s.add_argument("--restrict", action="store_true",
                   help="restreinte aux hôtes de l'élément (ssh-add -h, hôtes dans known_hosts)")
    s.add_argument("--force", action="store_true", help="recharge une clé déjà présente (nouvelles options)")

    s = sub.add_parser("agent", help="agent dédié : état, purge, verrou, arrêt")
    asub = s.add_subparsers(dest="agent_cmd", metavar="ACTION", parser_class=Parser)
    asub.required = True
    asub.add_parser("status", help="socket, pid et clés chargées (code 3 si arrêté)")
    asub.add_parser("purge", help="retire toutes les clés (ssh-add -D)")
    asub.add_parser("lock", help="verrouille l'agent (ssh-add -x, mot de passe saisi par ssh-add)")
    asub.add_parser("unlock", help="déverrouille l'agent (ssh-add -X)")
    asub.add_parser("stop", help="arrête l'agent, supprime socket et état")

    s = sub.add_parser("config", help="réglages (key-ttl : durée de vie par défaut des clés)")
    csub = s.add_subparsers(dest="config_cmd", metavar="ACTION", parser_class=Parser)
    csub.required = True
    c = csub.add_parser("get", help="affiche un réglage, ou tous")
    c.add_argument("key", metavar="CLÉ", nargs="?")
    c = csub.add_parser("set", help="fixe un réglage")
    c.add_argument("key", metavar="CLÉ")
    c.add_argument("value", metavar="VALEUR")
    c = csub.add_parser("unset", help="revient à la valeur par défaut")
    c.add_argument("key", metavar="CLÉ")
    return p


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean(text: str) -> str:
    """Texte venu du coffre, pour un terminal : caractères de contrôle (tabulation, fin de
    ligne, séquences ANSI/OSC) remplacés par leur échappement \\xNN."""
    return _CONTROL.sub(lambda m: "\\x%02x" % ord(m.group()), text)


def print_items(items: list, as_json: bool) -> None:
    if as_json:
        print(json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=1))
        return
    for i in items:
        print("%s\t%s\t%s" % (clean(i.name), clean(i.fingerprint or "-"),
                              ",".join(clean(h) for h in i.hosts) or "-"))


def match(item: SshKeyItem, pattern: str, by: Optional[str]) -> bool:
    if by == "host":
        return item.match_host(pattern)
    if by == "name":
        return item.match_name(pattern)
    if by == "fingerprint":
        return item.match_fingerprint(pattern)
    if by == "id":
        return item.id == pattern.strip()
    return item.match_name(pattern) or item.match_host(pattern) or item.match_fingerprint(pattern)


def run(args, backend: VaultBackend) -> int:
    prompt = make_prompt(args)
    if args.cmd == "search" and not args.pattern.strip():
        raise UsageError("motif vide")
    if args.cmd == "status":
        st = backend.status()
        label = {"unauthenticated": "non connecté", "locked": "verrouillé",
                 "unlocked": "déverrouillé"}[st.state]
        info = backend.info()
        print("coffre : %s" % label)
        print("serveur : %s" % clean(st.server or "-"))
        print("compte : %s" % clean(st.user or "-"))
        session = info["session"] if st.state == "unlocked" else None
        print("session : %s" % (session or "aucune"))
        print("magasin : %s" % info["store"])
        print("données : %s" % info["data"])
        return RC_OK if st.state == "unlocked" else RC_LOCKED
    if args.cmd == "login":
        try:
            state = backend.login(server=args.server, apikey=args.apikey)
        except VaultError:
            # l'invite de bw reste sans fin de ligne si la saisie est interrompue
            sys.stderr.write("\n")
            raise
        if state == "unlocked":
            print("connecté, coffre déverrouillé")
        else:
            print("connecté ; lancer « sshvault unlock » pour déverrouiller")
        return RC_OK
    if args.cmd == "unlock":
        backend.unlock(prompt, ttl=args.ttl)
        where = backend.info()["session"]
        print("coffre déverrouillé (%s)" % ("session %ds, %s" % (args.ttl, where) if where
                                            else "session non rangée"))
        return RC_OK
    if args.cmd == "lock":
        backend.lock()
        print("coffre verrouillé, session oubliée")
        return RC_OK
    if args.cmd == "sync":
        backend.sync(prompt)
        print("synchronisé")
        return RC_OK
    if args.cmd == "list":
        print_items(backend.list_ssh_keys(prompt), args.json)
        return RC_OK
    if args.cmd == "search":
        found = [i for i in backend.list_ssh_keys(prompt) if match(i, args.pattern, args.by)]
        if not found:
            err("aucune clé ne correspond à « %s »" % args.pattern)
            return RC_NONE
        print_items(found, args.json)
        return RC_OK
    if args.cmd == "load":
        return run_load(args, backend, prompt)
    if args.cmd == "agent":
        return run_agent(args)
    if args.cmd == "config":
        return run_config(args)
    raise UsageError("commande inconnue : %s" % args.cmd)


# --- agent dédié ---------------------------------------------------------------------

def make_agent() -> Agent:
    return Agent(resolve_dir())


def _hosts(hosts) -> str:
    return ",".join(clean(h) for h in hosts) or "-"


def _options(confirm: bool, restrict: bool) -> list:
    return (["confirmation"] if confirm else []) + (["restreinte"] if restrict else [])


def fmt_remaining(secs: int) -> str:
    h, rest = divmod(secs, 3600)
    m, s = divmod(rest, 60)
    if h:
        return "%dh%02dm%02ds" % (h, m, s)
    if m:
        return "%dm%02ds" % (m, s)
    return "%ds" % s


def _sync_lock_flag(agent: Agent, data: dict, keys: list) -> None:
    """L'agent montre des clés : il n'est pas verrouillé, quoi qu'en dise l'état."""
    if data["locked"] and keys:
        data["locked"] = False
        agent.update(lambda d: d.update(locked=False))


def _rollback(agent: Agent, added: dict) -> None:
    """Retire de l'agent les clés apparues pendant ce `load` (clés publiques seulement)."""
    for k in added.values():
        try:
            agent.remove(k)
        except AgentError as e:
            err("retrait de %s impossible : %s" % (k.fingerprint, e))


def run_load(args, backend: VaultBackend, prompt) -> int:
    if args.pattern is not None and not args.pattern.strip():
        raise UsageError("motif vide")
    if args.pattern is None and args.by:
        raise UsageError("--%s demande un MOTIF" % args.by)
    if args.pattern is None and not args.all:
        raise UsageError("préciser une sélection ou --all")
    if args.pattern is not None and args.all:
        raise UsageError("--all exclut un MOTIF")
    agent = make_agent()
    lifetime = args.lifetime if args.lifetime is not None else Config().key_ttl()
    kind, data = agent.probe()
    if kind == "foreign":
        raise agent.foreign()
    present = set()
    if kind == "ours":
        current = agent.keys()
        _sync_lock_flag(agent, data, current)
        if data["locked"]:
            raise AgentLocked("agent verrouillé : lancer « sshvault agent unlock »")
        present = {k.blob for k in current}

    found = [i for i in backend.list_ssh_keys(prompt) if args.all or match(i, args.pattern, args.by)]
    if not found:
        err("aucune clé ne correspond à « %s »" % args.pattern if args.pattern is not None
            else "aucune clé SSH dans le coffre")
        return RC_NONE
    todo, seen, skipped, already = [], set(), 0, 0
    for i in found:
        blob = public_blob(i.public_key)
        if blob is None:
            err("« %s » : clé publique de l'élément illisible : ignorée" % clean(i.name))
            skipped += 1
            continue
        if blob in seen:  # deux éléments pour la même clé : un seul chargement
            continue
        seen.add(blob)
        if blob in present and not args.force:
            print("déjà chargée : %s %s (--force pour recharger)" % (clean(i.name), fingerprint(blob)))
            already += 1
        else:
            todo.append((i, blob))
    if not todo:
        if skipped and not already:
            raise AgentError("aucune clé chargeable (clé publique illisible)")
        return RC_OK
    if args.restrict:
        for i, _ in todo:
            if not i.hosts:
                raise AgentError("--restrict : « %s » n'a aucun hôte associé : rien chargé" % clean(i.name))
            bad = [h for h in i.hosts if not literal_host(h)]
            if bad:
                raise AgentError("--restrict : hôte « %s » de « %s » non littéral (motif, user@, >, :port) : "
                                 "rien chargé" % (clean(bad[0]), clean(i.name)))

    adata, _ = agent.ensure_running()
    if args.confirm and (adata.get("agent") or {}).get("askpass") is False:
        err("avertissement : l'agent a été lancé sans askpass utilisable (DISPLAY, SSH_ASKPASS) : "
            "chaque usage d'une clé --confirm sera refusé ; « sshvault agent stop » puis load depuis "
            "une session graphique")
    if args.restrict:
        agent.check_hosts(sorted({h.lower() for i, _ in todo for h in i.hosts}))
    interactive = not args.nointeraction
    keys, added, done = {}, {}, []
    try:
        # Toutes les clés lues avant le premier chargement.
        for i, _ in todo:
            keys[i.id] = backend.get_private_key(i.id, prompt)
            if not interactive and is_encrypted(keys[i.id]):
                raise PassphraseRefused("« %s » : clé chiffrée par passphrase, saisie impossible "
                                        "(--nointeraction) : rien chargé" % clean(i.name))
        timeout = prompt_timeout(os.environ) + 10
        for i, blob in todo:
            key = keys.pop(i.id)
            enc = is_encrypted(key)
            before = {k.blob for k in agent.keys()}
            t = time.time()
            try:
                agent.add(key, lifetime, args.confirm, i.hosts if args.restrict else (), interactive, enc,
                          timeout if enc else AGENT_TIMEOUT)
            finally:
                del key
                after = {k.blob: k for k in agent.keys()}
                added.update({b: k for b, k in after.items() if b not in before})
            if blob not in after and not (lifetime and time.time() - t >= lifetime):
                raise AgentError("« %s » : clé privée différente de la clé publique de l'élément : "
                                 "rien chargé" % clean(i.name))
            done.append((i, blob, t))
    except BaseException:
        keys.clear()
        _rollback(agent, added)
        raise
    now = time.time()

    def record(d):
        reconcile(d, {k.fingerprint for k in agent.keys()}, now)
        for i, blob, t in done:
            d["keys"][fingerprint(blob)] = state_entry(i.id, i.name, i.hosts, t, lifetime, args.confirm,
                                                       args.restrict)
    agent.update(record)
    for i, blob, _ in done:
        opts = ", ".join(["durée " + describe_duration(lifetime)] + _options(args.confirm, False)
                         + (["restreinte à " + _hosts(i.hosts)] if args.restrict else []))
        print("chargée : %s %s (%s)" % (clean(i.name), fingerprint(blob), opts))
    return RC_OK


def _need_prompt(args, agent: Agent, what: str) -> None:
    """Saisie possible pour `ssh-add -x/-X` (règles de readpass.c 8.9) ?"""
    if args.nointeraction:
        raise AgentLocked("%s : saisie du mot de passe impossible (--nointeraction)" % what)
    try:
        stdin_tty = os.isatty(0)
    except OSError:
        stdin_tty = False
    if not (stdin_tty or tty_available() or askpass_rules(agent.env)[1]):
        raise AgentLocked("%s : aucune saisie possible (ni terminal, ni askpass utilisable)" % what)


def run_agent(args) -> int:
    agent = make_agent()
    cmd = args.agent_cmd
    if cmd == "stop":
        print(agent.stop())
        return RC_OK
    if cmd == "status":
        with agent.locked(create=False):
            kind, data = agent.probe()
            if kind == "foreign":
                raise agent.foreign()
            if kind != "ours":
                print("agent : arrêté%s" % (" (socket mort)" if kind == "dead" else ""))
                print("socket : %s" % agent.socket)
                return RC_LOCKED
            keys = agent.keys()
            _sync_lock_flag(agent, data, keys)
            now = time.time()
            present = {k.fingerprint for k in keys}
            if reconcile(data, present, now):
                agent.save(data)
        guess = maybe_locked(data, present)
        print("agent : actif%s" % (", verrouillé" if data["locked"] else ", verrouillé ?" if guess else ""))
        print("socket : %s" % agent.socket)
        print("pid : %d" % data["agent"]["pid"])
        rows = [(k.fingerprint, data["keys"].get(k.fingerprint)) for k in keys]
        if data["locked"] or guess:
            rows = list(data["keys"].items())
        for fp, e in rows:
            if e is None:  # chargée hors de sshvault
                print("?\t%s\t-\t?\t?" % fp)
                continue
            left = remaining(e, now)
            print("%s\t%s\t%s\t%s\t%s" % (clean(e["name"]), fp, _hosts(e["hosts"]),
                                          "illimitée" if left is None else fmt_remaining(left),
                                          ",".join(_options(e["confirm"], e["restrict"])) or "-"))
        if not rows:
            print("clés : aucune")
        return RC_OK
    if cmd == "purge":
        with agent.locked(create=False):
            try:
                data = agent.running()
            except AgentStopped:
                print("agent arrêté : rien à purger")
                return RC_OK
            _sync_lock_flag(agent, data, agent.keys())
            if data["locked"]:
                raise AgentLocked("agent verrouillé : lancer « sshvault agent unlock »")
            agent.purge()
            agent.update(lambda d: d.update(keys={}))
        print("agent vidé")
        return RC_OK
    if cmd in ("lock", "unlock"):
        data = agent.running()
        keys = agent.keys()
        _sync_lock_flag(agent, data, keys)
        if cmd == "unlock" and not data["locked"] and (keys or not data["keys"]):
            print("agent déjà déverrouillé")
            return RC_OK
        _need_prompt(args, agent, "agent " + cmd)
        timeout = 2 * prompt_timeout(os.environ) + AGENT_TIMEOUT
        agent.set_locked(cmd == "lock", timeout)
        agent.update(lambda d: d.update(locked=cmd == "lock"))
        print("agent verrouillé" if cmd == "lock" else "agent déverrouillé")
        return RC_OK
    raise UsageError("action inconnue : agent %s" % cmd)


def reap_orphans_quietly() -> None:
    """À chaque lancement : arrête les agents sshvault orphelins (socket disparu). Silencieux."""
    try:
        Agent(resolve_dir()).reap_orphans()
    except Exception:
        pass


def run_config(args) -> int:
    cfg = Config()
    if args.config_cmd == "get":
        for line in cfg.lines(args.key):
            print(line)
    elif args.config_cmd == "set":
        cfg.set(args.key, args.value)
        print(cfg.lines(args.key)[0])
    elif args.config_cmd == "unset":
        cfg.unset(args.key)
        print(cfg.lines(args.key)[0])
    else:
        raise UsageError("action inconnue : config %s" % args.config_cmd)
    return RC_OK


def _on_signal(signum, frame):
    raise Interrupted(signum)


def main(argv=None) -> int:
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _on_signal)
    backend = None
    try:
        try:
            args = build_parser().parse_args(argv)
        except UsageError as e:
            err("%s (voir sshvault --help)" % e)
            return RC_USAGE
        for name, default in (("SSHVAULT_PROMPT_TIMEOUT", PROMPT_TIMEOUT), ("SSHVAULT_BW_TIMEOUT", BW_TIMEOUT)):
            try:
                seconds(os.environ, name, default)
            except ValueError as e:
                err(e)
                return RC_USAGE
        reap_orphans_quietly()
        store = SessionStore()
        backend = BwBackend(store=store)
        rc = run(args, backend)
    except UsageError as e:
        err("%s (voir sshvault --help)" % e)
        rc = RC_USAGE
    except (NotLoggedIn, VaultLocked) as e:
        err(e)
        rc = RC_LOCKED
    except BackendError as e:
        err(e)
        rc = RC_BACKEND
    except SessionStoreError as e:
        err("magasin de session : %s" % e)
        rc = RC_BACKEND
    except ConfigWriteError as e:
        err(e)
        rc = RC_BACKEND
    except ConfigError as e:
        err(e)
        rc = RC_USAGE
    except (AgentStopped, AgentLocked, PassphraseRefused) as e:
        err(e)
        rc = RC_LOCKED
    except AgentError as e:
        err(e)
        rc = RC_BACKEND
    except VaultError as e:
        err(e)
        rc = RC_BACKEND
    except (KeyboardInterrupt, Interrupted):
        err("interrompu")
        rc = RC_INTERRUPTED
    except BrokenPipeError:
        # sortie fermée (sshvault list | head) : rien à dire
        _stdout_to_devnull()
        rc = RC_OK
    except Exception as e:  # filet : jamais de traceback
        err("erreur interne : %s: %s" % (type(e).__name__, e))
        rc = RC_BACKEND
    if backend is not None:
        for w in backend.warnings:
            err(w)
    try:
        sys.stdout.flush()
    except (BrokenPipeError, OSError):
        _stdout_to_devnull()
    return rc


def _stdout_to_devnull() -> None:
    """Recette de la doc Python (SIGPIPE) : stdout redirigé au niveau du descripteur, sinon
    l'interpréteur affiche « Exception ignored … BrokenPipeError » en sortant."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except (OSError, ValueError):
        pass


if __name__ == "__main__":
    sys.exit(main())

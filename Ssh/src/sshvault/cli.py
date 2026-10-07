"""Commande `sshvault`.

Codes de sortie :
  0  succès
  1  aucun résultat (search)
  2  usage (option ou argument invalide)
  3  non connecté au coffre, ou coffre verrouillé (aucune invite possible, mot de passe refusé)
  4  erreur du backend (bw absent, en erreur, réponse illisible, délai dépassé) ou erreur interne
  130 interrompu (Ctrl-C, SIGTERM, SIGHUP)
`status` : 0 si le coffre est déverrouillé, 3 s'il est verrouillé ou non connecté, 4 en erreur.
Toute erreur donne une seule ligne sur stderr, jamais de traceback.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
from typing import Optional

from . import __version__
from .backend import BackendError, NotLoggedIn, SshKeyItem, VaultBackend, VaultError, VaultLocked
from .bw import BwBackend
from .prompt import DEFAULT_TIMEOUT as PROMPT_TIMEOUT, PromptError, ask_password
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


def build_parser() -> Parser:
    p = Parser(prog="sshvault", description="Clés SSH du coffre Vaultwarden (via bw).",
               epilog="Codes de sortie : 0 ok, 1 aucun résultat, 2 usage, "
                      "3 non connecté ou verrouillé, 4 erreur backend, 130 interrompu. "
                      "status : 0 déverrouillé, 3 sinon.")
    p.add_argument("--version", action="version", version="sshvault " + __version__)
    p.add_argument("--nointeraction", action="store_true",
                   help="ne jamais demander le mot de passe (coffre verrouillé : code 3)")
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
    raise UsageError("commande inconnue : %s" % args.cmd)


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

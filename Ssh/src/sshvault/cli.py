"""Commande `sshvault`.

Codes de sortie :
  0  succès
  1  aucun résultat (search, load, hosts, forward, pubkey, deploy : sélection sans élément) ;
     hosts/forward remove : hôte absent de l'élément (rien écrit) ; import : clé déjà dans le coffre (rien
     créé) ; generate : nom déjà pris par une clé du coffre, sans --force (rien généré) ;
     ssh-config --check : pas à jour (contenu, droits, fichier en trop ou non ordinaire) ou
     ligne Include absente, conditionnelle ou pas en tête
  2  usage (option ou argument invalide ; load sans sélection ni --all ; durée invalide ;
     config.json invalide, illisible ou aux droits inattendus ; hôte invalide ; sélection
     de hosts ou forward qui désigne plusieurs éléments ; import : fichier refusé — illisible, pas une
     clé privée, type ou format non accepté — ou --name avec plusieurs fichiers ; generate :
     type, bits, nom ou commentaire refusés ; deploy : cible, port ou options ssh invalides)
  3  non connecté au coffre, ou coffre verrouillé (aucune invite possible, mot de passe refusé) ;
     agent dédié arrêté ou verrouillé (ensure --forward compris) ; passphrase d'une clé
     refusée ou impossible à saisir (load, import)
  4  erreur du backend (bw absent, en erreur, réponse illisible, délai dépassé), de l'agent
     dédié (XDG_RUNTIME_DIR relatif, non privé ou hors tmpfs, chemin du socket trop long,
     agent tiers, OpenSSH < 8.9, --restrict : élément sans hôte, hôte non littéral ou absent
     de known_hosts ; clé publique illisible ou différente de la clé privée), écriture de
     config.json impossible, écriture des hôtes ou des transferts dans le coffre non aboutie
     ou non vérifiée (y compris écrits mais ssh_config non régénéré), sous-agent de transfert
     en erreur (ensure --forward : forward-confirm sans askpass, agent tiers…), création d'un élément par import
     non aboutie ou non vérifiée (y compris clé importée mais ssh_config non régénéré), copie
     impossible dans un tmpfs privé (import --decrypt, generate), ssh-keygen absent ou en
     erreur, création d'un élément par generate non aboutie ou non vérifiée (y compris clé
     créée mais ssh_config non régénéré), deploy : ssh absent, en échec ou sans réponse
     (SSHVAULT_DEPLOY_TIMEOUT), réponse inattendue, échec partiel (clés déjà ajoutées dites),
     ssh_config généré impossible à écrire (chemin avec « " », « \\ », « ${ », fichier non
     ordinaire, droits), répertoire
     personnel inconnu, ssh-config install refusé (~/.ssh/config lien symbolique ou non
     ordinaire, Include de sshvault dans un bloc Host/Match, chemin personnel avec %, $ ou
     joker de glob), ou erreur interne
  130 interrompu (Ctrl-C, SIGTERM, SIGHUP)
`ensure` (appelé par ssh, Match exec) : 0 si la clé est présente ou chargée, et pour `ssh -G` ;
sinon le code de l'erreur, sans effet sur ssh (le Match ne porte aucune directive).
`status` : 0 si le coffre est déverrouillé, 3 s'il est verrouillé ou non connecté, 4 en erreur.
`import` de plusieurs fichiers : le pire des codes rencontrés (0 < 1 < 2 < 3 < 4).
`agent status` : 0 si l'agent dédié tourne, 3 s'il est arrêté, 4 en erreur ou agent tiers ;
`agent status|stop|purge|lock` : 4 si un sous-agent de transfert est en erreur (agent tiers sur
son socket…), sinon le code de l'agent dédié.
`ensure --forward` : comme `ensure` (0 si les clés sont présentes ou chargées ; pour un saut
`ssh -W`, 0 dès que le socket du sous-agent existe, lancé vide au besoin) ; un échec laisse la
connexion se faire, sans clé transférée.
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
from .agent import (CMD_TIMEOUT as AGENT_TIMEOUT, FID_RE, Agent, AgentError, AgentLocked, AgentStopped,
                    PassphraseRefused, askpass_rules, fingerprint, forward_agent, forward_agents, forward_fids,
                    is_encrypted, literal_host, public_blob, resolve_dir, tty_available)
from .agentstate import entry as state_entry, maybe_locked, reconcile, remaining
from .backend import (FORWARD_FIELD, HOSTS_FIELD, BackendError, InvalidHost, NotLoggedIn, SshKeyItem, VaultBackend, VaultError,
                      VaultLocked, WriteFailed, normalize_hosts, valid_host)
from .bw import BwBackend
from .config import Config, ConfigError, ConfigWriteError, describe_duration, parse_duration
from . import deploy as deploy_mod
from . import ensure as ensure_mod
from . import fastpath
from . import keyfile
from .ensure import Deadline
from .prompt import DEFAULT_TIMEOUT as PROMPT_TIMEOUT, PromptError, ask_password, prompt_timeout
from .bw import DEFAULT_TIMEOUT as BW_TIMEOUT
from .session import DEFAULT_TTL, SessionStore, SessionStoreError
from .settings import seconds
from . import sshconfig

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


def bits_arg(s: str) -> int:
    try:
        return int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("--bits invalide : %r (3072 ou 4096)" % s) from None


def _selection_flags(parser) -> None:
    g = parser.add_mutually_exclusive_group()
    for flag, what in (("host", "motif glob d'hôte"), ("name", "sous-chaîne du nom"),
                       ("fingerprint", "empreinte exacte"), ("id", "id exact de l'élément")):
        g.add_argument("--" + flag, dest="by", action="store_const", const=flag, help=what)


def duration_arg(s: str) -> int:
    try:
        return parse_duration(s)
    except ConfigError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def build_parser() -> Parser:
    p = Parser(prog="sshvault", description="Clés SSH du coffre Vaultwarden (via bw).",
               epilog="Codes de sortie : 0 ok, 1 aucun résultat (hosts remove : hôte absent ; "
                      "ssh-config --check : pas à jour ; import : déjà dans le coffre ; generate : nom "
                      "déjà pris), 2 usage (hôte invalide, sélection ambiguë, import : fichier refusé, "
                      "generate : type ou commentaire refusé, deploy : cible invalide), "
                      "3 non connecté ou verrouillé (coffre ou agent, passphrase refusée), "
                      "4 erreur backend ou agent, écriture ou ssh_config impossible, install refusé, "
                      "ssh-keygen ou ssh en échec, "
                      "130 interrompu. "
                      "status : 0 déverrouillé, 3 sinon ; agent status : 0 actif, 3 arrêté, 4 sous-agent de "
                      "transfert en erreur.")
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

    s = sub.add_parser("agent", help="agent dédié et sous-agents de transfert : état, purge, verrou, arrêt")
    asub = s.add_subparsers(dest="agent_cmd", metavar="ACTION", parser_class=Parser)
    asub.required = True
    asub.add_parser("status", help="socket, pid et clés chargées, sous-agents de transfert compris (code 3 si "
                                   "l'agent dédié est arrêté)")
    asub.add_parser("purge", help="retire toutes les clés (ssh-add -D), sous-agents de transfert compris")
    asub.add_parser("lock", help="vide et arrête les sous-agents de transfert, puis verrouille l'agent dédié "
                                 "(ssh-add -x, mot de passe saisi par ssh-add)")
    asub.add_parser("unlock", help="déverrouille l'agent (ssh-add -X)")
    asub.add_parser("stop", help="arrête l'agent dédié et les sous-agents de transfert, supprime sockets et états")

    for cmd, what_cmd in (("hosts", "hôtes associés à une clé (champ sshvault-hosts de l'élément)"),
                          ("forward", "hôtes vers lesquels la clé est transférée par un sous-agent restreint "
                                      "(champ sshvault-forward de l'élément)")):
        s = sub.add_parser(cmd, help=what_cmd)
        hsub = s.add_subparsers(dest="hosts_cmd", metavar="ACTION", parser_class=Parser)
        hsub.required = True
        for name, what, nargs in (("add", "ajoute des hôtes", "+"), ("remove", "retire des hôtes", "+"),
                                  ("set", "remplace la liste (\"\" : la vide)", "+"),
                                  ("list", "affiche les hôtes", None)):
            h = hsub.add_parser(name, help=what)
            h.add_argument("pattern", metavar="SÉLECTION", help="un seul élément, choisi comme pour load")
            g = h.add_mutually_exclusive_group()
            for flag, sel in (("host", "motif glob d'hôte"), ("name", "sous-chaîne du nom"),
                              ("fingerprint", "empreinte exacte"), ("id", "id exact de l'élément")):
                g.add_argument("--" + flag, dest="by", action="store_const", const=flag, help=sel)
            if nargs:
                h.add_argument("hosts", metavar="HÔTE", nargs=nargs,
                               help="motif de ligne Host (lettres, chiffres, . - _ * ?), ou liste à virgules")

    s = sub.add_parser("import", help="importe des clés privées existantes dans le coffre (fichiers d'origine "
                                      "jamais modifiés)")
    s.add_argument("files", metavar="FICHIER", nargs="+",
                   help="clé privée Ed25519 ou RSA (≥ 2048 bits), format OpenSSH, PKCS#8 (RSA seulement avec "
                        "OpenSSH 8.9) ou RSA PEM PKCS#1 ; PEM en clair converti au format OpenSSH ; PKCS#1 "
                        "chiffrée : avec --decrypt seulement")
    s.add_argument("--name", metavar="NOM", help="nom de l'élément (un seul FICHIER ; défaut : commentaire de la "
                                                  "clé, sinon nom du fichier)")
    s.add_argument("--hosts", metavar="HÔTES", action="append", default=[],
                   help="hôtes associés, liste à virgules (comme hosts add) ; ssh_config régénéré")
    s.add_argument("--force", action="store_true",
                   help="importe même si l'empreinte est déjà dans le coffre (second élément)")
    s.add_argument("--decrypt", action="store_true",
                   help="clé à passphrase : stockée déchiffrée (passphrase demandée une fois) ; défaut : "
                        "stockée chiffrée, telle quelle")

    s = sub.add_parser("generate", help="génère une nouvelle clé directement dans le coffre (clé publique "
                                        "seule sur stdout ; clé privée jamais écrite sur disque)")
    s.add_argument("--name", required=True, metavar="NOM", help="nom de l'élément (obligatoire)")
    s.add_argument("--type", default="ed25519", metavar="TYPE", help="ed25519 (défaut) ou rsa")
    s.add_argument("--bits", type=bits_arg, metavar="BITS", help="RSA seulement : 3072 ou 4096 (défaut 4096)")
    s.add_argument("--comment", metavar="TEXTE",
                   help="commentaire de la clé (imprimable, 255 caractères au plus ; défaut : le nom)")
    s.add_argument("--hosts", metavar="HÔTES", action="append", default=[],
                   help="hôtes associés, liste à virgules (comme hosts add) ; ssh_config régénéré")
    s.add_argument("--force", action="store_true", help="crée l'élément même si une clé du coffre porte déjà ce nom")

    s = sub.add_parser("pubkey", help="affiche les clés publiques sélectionnées, une ligne chacune (cache local "
                                      "de bw, aucun appel réseau)")
    s.add_argument("pattern", metavar="SÉLECTION", nargs="?", help="comme load (ou --all)")
    s.add_argument("--all", action="store_true", help="toutes les clés SSH du coffre")
    _selection_flags(s)

    s = sub.add_parser("deploy", help="ajoute les clés publiques sélectionnées à ~/.ssh/authorized_keys d'une "
                                      "cible, par un seul ssh (idempotent)",
                       usage="sshvault deploy [-h] [--host | --name | --fingerprint | --id] [-p PORT] "
                             "SÉLECTION [UTILISATEUR@]HÔTE [-- OPTIONS_SSH…]")
    s.add_argument("pattern", metavar="SÉLECTION", help="comme load")
    s.add_argument("target", metavar="[UTILISATEUR@]HÔTE", help="cible (lettres, chiffres, . - _ ; IPv6 entre crochets)")
    s.add_argument("-p", dest="port", metavar="PORT", help="port de la cible")
    _selection_flags(s)

    s = sub.add_parser("ssh-config", help="génère ~/.ssh/sshvault/config et les clés publiques ; "
                                          "install : ligne Include en tête de ~/.ssh/config")
    s.add_argument("action", nargs="?", choices=["install"], metavar="install",
                   help="insère la ligne Include en tête de ~/.ssh/config (sauvegarde faite)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--print", dest="print_only", action="store_true",
                   help="affiche la config générée sans rien écrire")
    g.add_argument("--check", action="store_true",
                   help="code 0 si tout est à jour et la ligne Include en tête, 1 sinon ; n'écrit rien")

    s = sub.add_parser("ensure", help="charge à la demande la clé d'un élément (appelé par ssh : ligne "
                                      "Match exec du ssh_config généré)")
    s.add_argument("--id", required=True, action="append", metavar="ID",
                   help="id (UUID) de l'élément ; plusieurs avec --forward")
    s.add_argument("--forward", metavar="FID", action="append",
                   help="sous-agent de transfert (16 chiffres hexadécimaux) : y charge les clés des --id, et elles "
                        "seules")

    s = sub.add_parser("config", help="réglages : key-ttl (durée de vie par défaut des clés), auto-load, "
                                      "auto-restrict, auto-confirm (chargement automatique), forward-confirm "
                                      "(sous-agents de transfert)")
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
        _clear_unlock_failure()
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
    if args.cmd in ("hosts", "forward"):
        return run_hosts(args, backend, prompt)
    if args.cmd == "ssh-config":
        return run_ssh_config(args, backend, prompt)
    if args.cmd == "import":
        return run_import(args, backend, prompt)
    if args.cmd == "generate":
        return run_generate(args, backend, prompt)
    if args.cmd == "pubkey":
        return run_pubkey(args, backend, prompt)
    if args.cmd == "deploy":
        return run_deploy(args, backend, prompt)
    raise UsageError("commande inconnue : %s" % args.cmd)


def _clear_unlock_failure() -> None:
    """Coffre déverrouillé à la main : l'échec mémorisé par `ensure` ne bloque plus rien."""
    try:
        ensure_mod.clear_failure(resolve_dir())
    except Exception:
        pass


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


def _forward_label(fid: str, patterns: dict) -> str:
    return "%s (%s)" % (clean(patterns.get(fid, "?")), fid)


def _forward_patterns() -> dict:
    """{fid : motif} lus dans le ssh_config généré ; {} s'il est illisible."""
    try:
        return sshconfig.forward_map(sshconfig.default_paths())
    except Exception:
        return {}


def _each_forward(base: str, fn) -> int:
    """`fn(sous-agent, étiquette)` pour chaque sous-agent de transfert connu ; une erreur est
    dite (une ligne) sans arrêter les autres. Renvoie RC_BACKEND si l'un a échoué, sinon RC_OK."""
    patterns = _forward_patterns()
    rc = RC_OK
    for sub in forward_agents(base):
        label = _forward_label(sub.fid, patterns)
        try:
            fn(sub, label)
        except AgentError as e:
            err("transfert %s : %s" % (label, e))
            rc = RC_BACKEND
    return rc


def _forward_status(sub: Agent, label: str) -> None:
    now = time.time()
    with sub.locked(create=False):
        kind, data = sub.probe()
        if kind == "foreign":
            raise sub.foreign()
        if kind != "ours":
            print("transfert %s : arrêté%s" % (label, " (socket mort)" if kind == "dead" else ""))
            return
        keys = sub.keys()
        if reconcile(data, {k.fingerprint for k in keys}, now):
            sub.save(data)
    print("transfert %s : actif, pid %d, socket %s" % (label, data["agent"]["pid"], sub.socket))
    for k in keys:
        e = data["keys"].get(k.fingerprint)
        if e is None:  # chargée hors de sshvault
            print("  ?\t%s\t?\t?" % k.fingerprint)
            continue
        left = remaining(e, now)
        print("  %s\t%s\t%s\t%s" % (clean(e["name"]), k.fingerprint,
                                   "illimitée" if left is None else fmt_remaining(left),
                                   ",".join(_options(e["confirm"], e["restrict"])) or "-"))
    if not keys:
        print("  clés : aucune")


def _forward_purge(sub: Agent, label: str) -> None:
    with sub.locked(create=False):
        try:
            sub.running()
        except AgentStopped:
            return
        sub.purge()
        sub.update(lambda d: d.update(keys={}))
    print("transfert %s : vidé" % label)


def _forward_stop(sub: Agent, label: str, purge: bool = False) -> None:
    if purge:
        with sub.locked(create=False):
            try:
                sub.running()
                sub.purge()
            except AgentStopped:
                pass
            except AgentError as e:  # vidage refusé (verrouillé à la main…) : l'arrêt suit quand même
                err("transfert %s : vidage impossible (%s) : arrêté quand même" % (label, e))
    print("transfert %s : %s" % (label, sub.stop()))


def _ensure_lock(base: str):
    """`ensure.lock` (celui d'`ensure --id`/`--forward`) si le dossier existe : un `ensure
    --forward` en cours finit avant l'arrêt des sous-agents, aucun ne les relance pendant. S'il
    est tenu, une ligne le dit avant d'attendre."""
    import contextlib
    if not os.path.isdir(base):
        return contextlib.nullcontext()
    return ensure_mod.user_lock(base, on_wait=lambda: err("attente d'un chargement en cours (ensure)…"))


def stop_all_forward(base: str) -> int:
    """Arrête tous les sous-agents de transfert (sous ensure.lock) ; renvoie leur nombre."""
    n = 0
    with _ensure_lock(base):
        for sub in forward_agents(base):
            try:
                sub.stop()
                n += 1
            except AgentError as e:
                err("avertissement : sous-agent de transfert %s : %s" % (sub.fid, e))
    return n


def run_agent(args) -> int:
    agent = make_agent()
    base = agent.dir
    cmd = args.agent_cmd
    if cmd == "stop":
        with _ensure_lock(base):
            rc = _each_forward(base, _forward_stop)
            print(agent.stop())
        return rc
    if cmd == "status":
        with agent.locked(create=False):
            kind, data = agent.probe()
            if kind == "foreign":
                raise agent.foreign()
            if kind == "ours":
                keys = agent.keys()
                _sync_lock_flag(agent, data, keys)
                now = time.time()
                present = {k.fingerprint for k in keys}
                if reconcile(data, present, now):
                    agent.save(data)
        if kind != "ours":
            print("agent : arrêté%s" % (" (socket mort)" if kind == "dead" else ""))
            print("socket : %s" % agent.socket)
            return max(RC_LOCKED, _each_forward(base, _forward_status))
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
        return _each_forward(base, _forward_status)
    if cmd == "purge":
        rc = _each_forward(base, _forward_purge)
        with agent.locked(create=False):
            try:
                data = agent.running()
            except AgentStopped:
                print("agent arrêté : rien à purger")
                return rc
            _sync_lock_flag(agent, data, agent.keys())
            if data["locked"]:
                raise AgentLocked("agent verrouillé : lancer « sshvault agent unlock »")
            agent.purge()
            agent.update(lambda d: d.update(keys={}))
        print("agent vidé")
        return rc
    if cmd in ("lock", "unlock"):
        import contextlib
        rc = RC_OK
        # lock : ensure.lock tenu de l'arrêt des sous-agents jusqu'à l'état « verrouillé »
        # enregistré : aucun `ensure --forward` ne les relance entre-temps
        with _ensure_lock(base) if cmd == "lock" else contextlib.nullcontext():
            if cmd == "lock":
                # d'abord, quoi qu'il arrive ensuite : sous-agents vidés et arrêtés (rechargés par le
                # premier ssh après « agent unlock »)
                rc = _each_forward(base, lambda sub, label: _forward_stop(sub, label, purge=True))
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
        return rc
    raise UsageError("action inconnue : agent %s" % cmd)


def reap_orphans_quietly() -> None:
    """À chaque lancement : arrête les agents sshvault orphelins (socket disparu), agent dédié
    et sous-agents de transfert. Silencieux."""
    try:
        base = resolve_dir()
        Agent(base).reap_orphans()
        for sub in forward_agents(base):
            sub.reap_orphans()
    except Exception:
        pass


def forward_upkeep(plan, socket: str, out=None) -> None:
    """Après une régénération : arrête chaque sous-agent de transfert que le ssh_config ne
    référence plus, ou qui garde une clé dont l'élément n'est plus autorisé pour ce motif
    (rechargé au prochain ssh). Une erreur est dite en avertissement."""
    base = os.path.dirname(socket)
    fids = forward_fids(base)
    if not fids:
        return
    with _ensure_lock(base):  # un ensure --forward en cours finit d'abord
        for fid in fids:
            try:
                sub = forward_agent(base, fid)
                ref = plan.forward.get(fid)
                if ref is None:
                    why = "%s, plus référencé" % fid
                else:
                    ids = ref[1]
                    if all(any(fastpath.owns(e, i) for i in ids) for e in sub.state.load()["keys"].values()):
                        continue
                    why = "%s (%s), clé retirée du transfert" % (clean(ref[0]), fid)
                print("sous-agent de transfert %s : %s" % (why, sub.stop()), file=out or sys.stdout, flush=True)
            except AgentError as e:
                err("avertissement : sous-agent de transfert %s : %s" % (fid, e))


def warn_forwardagent(items: list, plan, paths) -> None:
    """`ssh-config` seulement : hôtes d'identité littéraux sans transfert déclaré pour lesquels
    `ssh -G` montre `forwardagent yes` (l'agent dédié entier y serait transféré). Durée totale
    bornée (SSH_G_BUDGET) ; au-delà, un avertissement dit que le contrôle est incomplet."""
    try:
        budget = seconds(os.environ, sshconfig.SSH_G_BUDGET_VAR, sshconfig.SSH_G_BUDGET)
    except ValueError:
        budget = sshconfig.SSH_G_BUDGET
    found, cut = sshconfig.forwardagent_yes(sshconfig.unforwarded_literal_hosts(items, plan), paths, budget=budget)
    for h in found:
        err("avertissement : hôte « %s » : %s" % (h, sshconfig.FORWARD_YES_WARNING % h))
    if cut:
        err("avertissement : contrôle ForwardAgent (ssh -G) interrompu après %gs : hôtes restants non vérifiés"
            % budget)


# --- hôtes et ssh_config généré --------------------------------------------------------

def _select_one(items: list, args, forward: bool = False) -> Optional[SshKeyItem]:
    """L'élément désigné par la sélection ; None (message dit) si aucun ; UsageError si plusieurs.
    `forward` : `--host` et la sélection par défaut couvrent aussi les motifs de transfert."""
    if not args.pattern.strip():
        raise UsageError("sélection vide")
    found = [i for i in items if match(i, args.pattern, args.by)
             or (forward and args.by in (None, "host") and i.match_forward(args.pattern))]
    if not found:
        err("aucune clé ne correspond à « %s »" % args.pattern)
        return None
    if len(found) > 1:
        raise UsageError("« %s » désigne %d éléments (%s) : préciser --id"
                         % (args.pattern, len(found), ", ".join("%s %s" % (clean(i.name), i.id) for i in found)))
    return found[0]


def _split(values) -> list:
    return [h.strip() for v in values for h in v.split(",") if h.strip()]


def ensure_exe(paths) -> Optional[str]:
    """Chemin de sshvault pour les lignes `Match exec` (avertissements sur stderr), ou None si
    `auto-load` est faux."""
    if not Config().get("auto-load"):
        return None
    exe = sshconfig.sshvault_exe()
    for w in sshconfig.exe_warnings(exe, paths):
        err("avertissement : %s" % w)
    return exe


_RESOLVE = object()  # regenerate : chemin de sshvault à résoudre (None : pas de Match exec)


def regenerate(items: list, paths=None, socket: Optional[str] = None, exe=_RESOLVE, out=None,
               skip_catch_all: bool = False) -> None:
    """Réécrit ce qui a changé dans ~/.ssh/sshvault/ ; avertissements sur stderr, compte rendu
    sur `out` (défaut stdout ; stderr pour generate, dont stdout ne porte que la clé publique)."""
    paths = paths or sshconfig.default_paths()
    socket = socket or make_agent().socket
    plan = sshconfig.build(items, paths, socket, ensure_exe(paths) if exe is _RESOLVE else exe)
    for w in plan.warnings:
        if not (skip_catch_all and (sshconfig.CATCH_ALL_WARNING in w
                                    or sshconfig.FORWARD_CATCH_ALL_WARNING in w)):  # déjà dit par l'appelant
            err("avertissement : %s" % w)
    res = sshconfig.apply(plan, paths)
    for w in res.warnings:
        err("avertissement : %s" % w)
    print("%s : %s (%d bloc%s)" % (paths.config, "écrit" if res.config_written else "inchangé", plan.blocks,
                                   "s" if plan.blocks > 1 else ""), file=out or sys.stdout, flush=True)
    if res.pubs_written or res.pubs_removed:
        print("clés publiques (%s) : %d écrite%s, %d supprimée%s"
              % (paths.pub, len(res.pubs_written), "s" if len(res.pubs_written) > 1 else "",
                 len(res.pubs_removed), "s" if len(res.pubs_removed) > 1 else ""), file=out or sys.stdout, flush=True)
    w = sshconfig.include_warning(paths)
    if w:
        err("avertissement : %s" % w)
    forward_upkeep(plan, socket, out)
    return plan


def run_hosts(args, backend: VaultBackend, prompt) -> int:
    """`hosts` (champ sshvault-hosts) et `forward` (champ sshvault-forward) : mêmes règles."""
    fwd = args.cmd == "forward"
    of = (lambda i: i.forward) if fwd else (lambda i: i.hosts)
    what, one = ("transferts", "le transfert vers") if fwd else ("hôtes", "l'hôte")
    cmd = args.hosts_cmd
    if cmd != "list":
        given = _split(args.hosts)
        if cmd in ("add", "set"):
            new = normalize_hosts(given)  # InvalidHost (code 2) avant tout accès au coffre
            if cmd == "add" and not new:
                raise UsageError("aucun hôte à ajouter")
        elif not given:
            raise UsageError("aucun hôte à retirer")
        # écriture : partir de l'état du serveur, pas d'un cache local périmé (interface web)
        backend.sync(prompt)
    items = backend.list_ssh_keys(prompt)
    item = _select_one(items, args, forward=fwd)
    if item is None:
        return RC_NONE
    if cmd == "list":
        for h in of(item):
            print(clean(h))
        return RC_OK
    current = []
    for h in of(item):
        if h.lower() not in current:
            current.append(h.lower())
    if cmd == "add":
        want = current + [h for h in new if h not in current]
    elif cmd == "set":
        want = list(new)
    else:
        targets = [h.lower() for h in given]
        missing = [h for h in targets if h not in current]
        if missing:
            err("« %s » n'a pas %s « %s » : rien écrit" % (clean(item.name), one, clean(missing[0])))
            return RC_NONE
        want = [h for h in current if h not in targets]
    bad = [h for h in want if not valid_host(h)]
    if bad:
        raise InvalidHost("hôte invalide « %s » déjà dans « %s » : le retirer (%s remove) ou remplacer la liste "
                          "(%s set) ; rien écrit" % (clean(bad[0]), clean(item.name), args.cmd, args.cmd))
    # Prérequis de la régénération (chemins, socket de l'agent) vérifiés avant d'écrire
    # dans le coffre : SshConfigError ou AgentError ici, rien n'est écrit.
    paths = sshconfig.default_paths()
    socket = make_agent().socket
    exe = ensure_exe(paths)
    sshconfig.build(items, paths, socket, exe)
    if want == current:
        print("%s de « %s » inchangés : %s" % (what, clean(item.name), _hosts(of(item))))
        updated = item
    else:
        for h in want:
            if sshconfig.is_catch_all(h):
                err("avertissement : motif « %s » : %s"
                    % (h, sshconfig.FORWARD_CATCH_ALL_WARNING if fwd else sshconfig.CATCH_ALL_WARNING))
        updated = (backend.set_forward if fwd else backend.set_hosts)(item.id, want, prompt)
        print("%s de « %s » : %s" % (what, clean(updated.name), _hosts(of(updated))))
        if not fwd:
            _warn_restricted(updated)
    items = [updated if i.id == updated.id else i for i in items]
    try:
        regenerate(items, paths, socket, exe, skip_catch_all=fwd)
    except (sshconfig.SshConfigError, AgentError) as e:
        err("%s écrits dans le coffre, mais ssh_config non régénéré : %s" % (what, e))
        return RC_BACKEND
    return RC_OK


def _warn_restricted(item: SshKeyItem) -> None:
    """Clé de l'élément chargée avec --restrict : ses contraintes -h gardent les anciens hôtes."""
    try:
        keys = make_agent().state.load()["keys"]
    except Exception:
        return
    if any(e.get("id") == item.id and e.get("restrict") for e in keys.values()):
        err("avertissement : clé « %s » chargée avec --restrict : elle reste limitée aux anciens hôtes ; relancer "
            "« sshvault load --force --restrict --id %s »" % (clean(item.name), item.id))


def run_ssh_config(args, backend: VaultBackend, prompt) -> int:
    paths = sshconfig.default_paths()
    if args.action == "install":
        if args.print_only or args.check:
            raise UsageError("install exclut --print et --check")
        print(sshconfig.install(paths))
        if not os.path.exists(paths.config):
            err("avertissement : %s n'existe pas encore : lancer « sshvault ssh-config »" % paths.config)
        return RC_OK
    items = backend.list_ssh_keys(prompt)
    if not (args.print_only or args.check):
        warn_forwardagent(items, regenerate(items, paths), paths)
        return RC_OK
    plan = sshconfig.build(items, paths, make_agent().socket, ensure_exe(paths))
    for w in plan.warnings:
        err("avertissement : %s" % w)
    if args.print_only:
        sys.stdout.write(plan.config.decode())
        return RC_OK
    diffs, notes = sshconfig.check(plan, paths)
    for w in notes:
        err("avertissement : %s" % w)
    warn_forwardagent(items, plan, paths)
    w = sshconfig.include_warning(paths)
    if w:
        diffs.append(w)
    for d in diffs:
        print(d)
    if diffs:
        return RC_NONE
    print("à jour : %s (%d bloc%s), ligne Include en tête de %s"
          % (paths.config, plan.blocks, "s" if plan.blocks > 1 else "", paths.user_config))
    return RC_OK


# --- import d'une clé existante ----------------------------------------------------------

TEST_FIELD_ENV = "SSHVAULT_TEST_FIELD"


def _test_fields() -> list:
    """Tests seulement : `SSHVAULT_TEST_FIELD=NOM=VALEUR` ajoute un champ texte aux éléments
    importés (marqueur que le nettoyage des tests d'intégration exige)."""
    raw = os.environ.get(TEST_FIELD_ENV) or ""
    if not raw:
        return []
    name, sep, value = raw.partition("=")
    if not sep or not name or name in (HOSTS_FIELD, FORWARD_FIELD):
        raise ConfigError("%s invalide : NOM=VALEUR attendu" % TEST_FIELD_ENV)
    return [(name, value)]


def _passphrase_mode(args) -> str:
    """Invite de passphrase possible pour ssh-keygen ? Sinon PassphraseRefused (code 3)."""
    if args.nointeraction:
        raise PassphraseRefused("clé chiffrée par passphrase, saisie impossible (--nointeraction) : rien importé")
    mode = keyfile.passphrase_mode(os.environ)
    if mode is None:
        raise PassphraseRefused("clé chiffrée par passphrase : aucune invite possible (ni terminal au premier plan, "
                                "ni askpass utilisable) : rien importé")
    return mode


def _notice(label: str):
    return lambda: err("%s : passphrase de la clé (demandée par ssh-keygen)" % label)


def _needs_prompt(args, kf) -> bool:
    """Passphrase indispensable : clé publique inconnue sans elle, ou déchiffrement demandé."""
    return kf.blob is None or (args.decrypt and kf.encrypted)


def _import_one(args, backend: VaultBackend, prompt, kf, hosts, items: list, extra) -> Optional[SshKeyItem]:
    """Un fichier analysé : doublon (None, message dit), sinon élément créé et relu."""
    label = clean(kf.path)
    if kf.blob is None:  # PKCS#8 (ou PKCS#1) chiffré : la clé publique exige la passphrase
        mode = _passphrase_mode(args)
        kf = (keyfile.decrypt if args.decrypt else keyfile.public_from_encrypted)(kf, mode, notice=_notice(label))
    for w in kf.warnings:
        err("avertissement : %s" % w)
    fp = kf.fingerprint
    same = [i for i in items if i.match_fingerprint(fp)]
    if same and not args.force:
        hint = ("pour lui associer les hôtes : « sshvault hosts add --id %s %s » ; --force pour créer un second "
                "élément" % (same[0].id, ",".join(hosts)) if hosts else "--force pour l'importer quand même")
        err("%s : déjà dans le coffre (%s) : %s ; %s"
            % (label, fp, ", ".join("« %s » %s" % (clean(i.name), i.id) for i in same), hint))
        return None
    if args.decrypt and kf.encrypted:
        kf = keyfile.decrypt(kf, _passphrase_mode(args), notice=_notice(label))
    name = args.name.strip() if args.name is not None else kf.default_name()
    item = backend.create_ssh_key(name, kf.data.decode("ascii"), kf.public_key, fp, hosts, prompt,
                                  existing=[i.id for i in same], extra_fields=extra)
    print("importée : %s (%s)" % (clean(item.name), fp))
    if kf.encrypted:
        err("avertissement : « %s » stockée chiffrée par sa passphrase : demandée à chaque chargement, et "
            "inutilisable par l'agent de Bitwarden Desktop, peut-être par d'autres clients Bitwarden "
            "(--decrypt : stockée déchiffrée)" % clean(item.name))
    return item


def run_import(args, backend: VaultBackend, prompt) -> int:
    """Chaque fichier traité à part (une ligne de résultat chacun) ; code : le pire rencontré."""
    if args.name is not None:
        if not args.name.strip():
            raise UsageError("--name vide")
        if len(args.files) > 1:
            raise UsageError("--name ne vaut que pour un seul FICHIER")
    hosts = normalize_hosts(_split(args.hosts))  # InvalidHost (code 2) avant tout accès
    extra = _test_fields()
    worst = RC_OK

    def failed(path, e):
        nonlocal worst
        rc, msg = classify(e)
        err("%s : %s" % (clean(path), msg) if path is not None else msg)
        worst = max(worst, rc)

    todo = []
    for path in args.files:  # lecture, analyse et refus locaux, sans invite ni accès au coffre
        try:
            kf = keyfile.analyze(path, decrypt=args.decrypt)
            if _needs_prompt(args, kf):
                _passphrase_mode(args)  # --nointeraction, ou ni terminal ni askpass : refus ici
            todo.append(kf)
        except Exception as e:
            failed(path, e)
    if not todo:
        return worst
    try:
        if hosts:
            # Prérequis de la régénération vérifiés avant toute écriture (comme hosts).
            paths = sshconfig.default_paths()
            socket = make_agent().socket
            exe = ensure_exe(paths)
            for h in hosts:
                if sshconfig.is_catch_all(h):
                    err("avertissement : motif « %s » : %s" % (h, sshconfig.CATCH_ALL_WARNING))
        # doublons : état du serveur, pas un cache local périmé
        backend.sync(prompt)
        items = backend.list_ssh_keys(prompt)
        if hosts:
            sshconfig.build(items, paths, socket, exe)
    except Exception as e:  # le pire code reste, avec les refus déjà dits
        failed(None, e)
        return worst
    created = []
    try:
        for kf in todo:
            try:
                item = _import_one(args, backend, prompt, kf, hosts, items, extra)
            except Exception as e:
                failed(kf.path, e)
                continue
            if item is None:
                worst = max(worst, RC_NONE)
                continue
            items.append(item)
            created.append(item)
    except BaseException:
        # Ctrl-C, SIGTERM… : les éléments déjà créés restent ; la config n'est pas régénérée
        if hosts and created:
            err("clés créées : %s ; ssh_config non régénéré : lancer « sshvault ssh-config »"
                % ", ".join("« %s » %s" % (clean(i.name), i.id) for i in created))
        raise
    if hosts and created:
        try:
            regenerate(items, paths, socket, exe)
        except (sshconfig.SshConfigError, AgentError) as e:
            err("clé importée dans le coffre, mais ssh_config non régénéré : %s" % e)
            worst = max(worst, RC_BACKEND)
    return worst


# --- génération d'une clé dans le coffre (story 7) -----------------------------------------------

def run_generate(args, backend: VaultBackend, prompt) -> int:
    """Clé générée par ssh-keygen dans le tmpfs privé, créée dans le coffre par le chemin
    d'`import` (create_ssh_key : stdin, reprise sans doublon, relecture). stdout : la seule clé
    publique (une ligne) ; tout le reste sur stderr. Ordre : refus d'usage (2), tmpfs privé (4),
    prérequis de la régénération (4), coffre (3/4), nom déjà pris (1), puis seulement la
    génération et la création."""
    name = args.name.strip()
    if not name:
        raise UsageError("--name vide")
    if not name.isprintable():
        raise UsageError("--name : caractères imprimables seulement")
    key_type, bits = keyfile.gen_spec(args.type, args.bits)  # KeyRefused (code 2)
    if args.comment is not None:
        comment = keyfile.check_comment(args.comment)
    else:
        try:
            comment = keyfile.check_comment(name)
        except keyfile.KeyRefused as e:
            raise keyfile.KeyRefused("nom inutilisable comme commentaire de la clé (%s) : préciser --comment" % e) \
                from None
    hosts = normalize_hosts(_split(args.hosts))  # InvalidHost (code 2) avant tout accès
    extra = _test_fields()
    # Prérequis, avant tout accès au coffre : tmpfs privé et son dossier sshvault/ (code 4),
    # puis chemins, socket et sshvault du ssh_config (contrôle sans éléments : build([])).
    keyfile.check_workspace()
    if hosts:
        paths = sshconfig.default_paths()
        socket = make_agent().socket
        exe = ensure_exe(paths)
        sshconfig.build([], paths, socket, exe)
    backend.sync(prompt)  # nom déjà pris : état du serveur, pas un cache local périmé
    items = backend.list_ssh_keys(prompt)
    taken = [i for i in items if i.name.strip().casefold() == name.casefold()]
    if taken and not args.force:
        err("nom « %s » déjà pris par %s : rien généré ; --force pour créer quand même un élément de ce nom"
            % (clean(name), ", ".join("« %s » %s" % (clean(i.name), clean(i.id)) for i in taken)))
        return RC_NONE
    if hosts:
        sshconfig.build(items, paths, socket, exe)
        for h in hosts:  # une seule fois (la régénération le tait), avant la génération et l'écriture
            if sshconfig.is_catch_all(h):
                err("avertissement : motif « %s » : %s" % (h, sshconfig.CATCH_ALL_WARNING))
    gen = keyfile.generate(args.type, args.bits, comment)
    try:
        item = backend.create_ssh_key(name, gen.private_key, gen.public_key, gen.fingerprint, hosts, prompt,
                                      existing=[], extra_fields=extra)
    except VaultError as e:
        # WriteFailed, mais aussi session refusée (VaultLocked, NotLoggedIn…) : même classe, code inchangé
        raise e.__class__("%s ; la clé générée n'a jamais été écrite sur disque : sans élément valide dans le "
                          "coffre, elle est perdue (relancer « sshvault generate »)" % e) from None
    public, fp = gen.public_key, gen.fingerprint
    del gen
    regenerated = False
    try:
        print(public, flush=True)
        err("clé %s générée dans le coffre : « %s » %s (id %s)"
            % ("Ed25519" if key_type == "ssh-ed25519" else "RSA %d" % bits, clean(item.name), fp, clean(item.id)))
        if hosts:
            try:
                regenerate(items + [item], paths, socket, exe, out=sys.stderr, skip_catch_all=True)
            except (sshconfig.SshConfigError, AgentError) as e:
                err("clé créée dans le coffre, mais ssh_config non régénéré : %s" % e)
                return RC_BACKEND
            regenerated = True
    except BaseException:
        # Ctrl-C, SIGTERM, sortie fermée… après la création : la clé existe, on le dit
        note = "clé créée : « %s » %s" % (clean(item.name), clean(item.id))
        if hosts and not regenerated:
            note += " ; ssh_config non régénéré : lancer « sshvault ssh-config »"
        try:
            err(note)
        except (OSError, ValueError):
            pass
        raise
    return RC_OK


# --- clés publiques : affichage et déploiement (story 7) --------------------------------------------

def _public_lines(args, backend: VaultBackend, prompt, allow_all: bool):
    """(éléments, lignes de clé publique, code) de la sélection, une ligne par clé (deux éléments
    d'une même clé : une seule) ; (None, None, RC_NONE) si rien ne correspond (message dit). Clé
    publique illisible : message, ignorée, code RC_BACKEND."""
    if args.pattern is not None and not args.pattern.strip():
        raise UsageError("sélection vide")
    if allow_all:
        if args.pattern is None and args.by:
            raise UsageError("--%s demande une SÉLECTION" % args.by)
        if args.pattern is None and not args.all:
            raise UsageError("préciser une sélection ou --all")
        if args.pattern is not None and args.all:
            raise UsageError("--all exclut une SÉLECTION")
    every = allow_all and args.all
    found = [i for i in backend.list_ssh_keys(prompt) if every or match(i, args.pattern, args.by)]
    if not found:
        err("aucune clé ne correspond à « %s »" % clean(args.pattern) if args.pattern is not None
            else "aucune clé SSH dans le coffre")
        return None, None, RC_NONE
    rc, out, seen = RC_OK, [], set()
    for i in found:
        line = deploy_mod.key_line(i.public_key)
        if line is None:
            err("« %s » (%s) : clé publique de l'élément illisible : ignorée" % (clean(i.name), clean(i.id)))
            rc = RC_BACKEND
            continue
        blob = line.split()[1]
        if blob in seen:
            continue
        seen.add(blob)
        out.append((i, line))
    return [i for i, _ in out], [l for _, l in out], rc


def run_pubkey(args, backend: VaultBackend, prompt) -> int:
    """Une ligne de clé publique par clé sélectionnée, rien d'autre sur stdout. Lecture du
    cache local de bw (list items) : aucun appel réseau."""
    items, lines, rc = _public_lines(args, backend, prompt, allow_all=True)
    for line in lines or []:
        print(line)
    return rc


# Options de `ssh` (OpenSSH 8.9, ssh.c) : sans argument, puis avec argument ; refusées : celles
# qui changent le mode de ssh (pas de commande, stdin coupé, arrière-plan, terminal, sous-système,
# contrôle de connexion, transfert -W, affichage seul) ; mots-clés -o de même effet.
_SSH_FLAGS = set("1246afgknqstvxyACGKMNTVXY")
_SSH_WITH_ARG = set("bceilmopBDEFIJLOPQRSWw")
_SSH_REFUSED = set("NnfGVQOWsMt")
_SSH_REFUSED_KEYWORDS = {"requesttty", "stdinnull", "sessiontype", "forkafterauthentication", "remotecommand",
                         "localcommand", "permitlocalcommand", "proxyusefdpass"}


def split_ssh_options(argv: list):
    """`deploy … -- OPTIONS_SSH…` : les options de ssh, séparées avant argparse (dont la prise en
    charge de « -- » dans une sous-commande varie selon la version de Python). Seulement pour
    la commande deploy ; ailleurs, argv inchangé."""
    cmd = next((n for n, a in enumerate(argv) if not a.startswith("-")), None)
    if cmd is None or argv[cmd] != "deploy" or "--" not in argv[cmd:]:
        return argv, []
    cut = argv.index("--", cmd)
    return argv[:cut], argv[cut + 1:]


def check_ssh_options(options: list) -> None:
    """Chaque élément doit être une option de ssh ou l'argument d'une option : ni cible ni
    commande glissée par erreur (la cible et la commande distante sont fixées par deploy)."""
    n = 0
    while n < len(options):
        a = options[n]
        if a == "--" or not a.startswith("-") or len(a) < 2:
            raise deploy_mod.BadTarget("option ssh inattendue %r : seulement des options après « -- » (la cible "
                                       "se donne avant)" % a)
        k = 1
        while k < len(a):
            c = a[k]
            if c in _SSH_REFUSED:
                raise deploy_mod.BadTarget("option ssh -%s refusée : elle change le mode de ssh (deploy envoie les "
                                           "clés sur stdin et lance une commande fixe)" % c)
            if c in _SSH_WITH_ARG:
                if k == len(a) - 1:
                    n += 1
                    if n >= len(options):
                        raise deploy_mod.BadTarget("option ssh -%s sans argument" % c)
                    value = options[n]
                else:
                    value = a[k + 1:]
                if c == "o":
                    key = re.split(r"[\s=]", value.strip(), 1)[0].lower()
                    if key in _SSH_REFUSED_KEYWORDS:
                        raise deploy_mod.BadTarget("option ssh -o %s refusée : elle change le mode de ssh"
                                                   % clean(key))
                break
            if c not in _SSH_FLAGS:
                raise deploy_mod.BadTarget("option ssh inconnue -%s" % c)
            k += 1
        n += 1


def run_deploy(args, backend: VaultBackend, prompt) -> int:
    """Un seul `ssh` vers la cible pour toutes les clés sélectionnées (voir deploy.py) ; une
    ligne par clé sur stdout : « ajoutée » ou « déjà présente »."""
    deploy_mod.check_target(args.target)  # BadTarget (code 2) avant tout accès
    port = deploy_mod.check_port(args.port) if args.port is not None else None
    options = list(getattr(args, "ssh_options", []) or [])
    check_ssh_options(options)
    if args.nointeraction:
        options = ["-o", "BatchMode=yes"] + options  # première valeur lue : elle l'emporte
    items, lines, rc = _public_lines(args, backend, prompt, allow_all=False)
    if not lines:
        if items is not None and rc == RC_BACKEND:
            raise deploy_mod.DeployError("aucune clé déployable (clé publique illisible)")
        return rc
    try:
        answers, notes = deploy_mod.deploy(lines, args.target, port, options)
    except deploy_mod.DeployError as e:
        _report_deployed(items, lines, e.answers, args.target)  # clés traitées avant l'échec
        raise
    for note in notes:
        err("ssh : %s" % note)
    _report_deployed(items, lines, answers, args.target)
    return rc


_ANSWERS = {"added": "ajoutée", "present": "déjà présente",
            "present-options": "déjà présente (avec options : la connexion peut être restreinte)"}


def _report_deployed(items, lines, answers, target) -> None:
    for i, line, ans in zip(items, lines, answers):
        print("%s : « %s » %s → %s" % (_ANSWERS[ans], clean(i.name), fingerprint(line.split()[1]), target),
              flush=True)


def run_config(args) -> int:
    cfg = Config()
    if args.config_cmd == "get":
        for line in cfg.lines(args.key):
            print(line)
    elif args.config_cmd in ("set", "unset"):
        before = cfg.get(args.key) if args.key == "forward-confirm" else None
        if args.config_cmd == "set":
            cfg.set(args.key, args.value)
        else:
            cfg.unset(args.key)
        print(cfg.lines(args.key)[0])
        if args.key == "auto-load":
            print("pris en compte à la prochaine génération : lancer « sshvault ssh-config »")
        elif args.key == "forward-confirm" and cfg.get(args.key) != before:
            # les clés déjà chargées garderaient l'ancienne option (-c ou non) jusqu'à expiration
            try:
                base = resolve_dir()
            except AgentError:
                base = None
            if base is not None and stop_all_forward(base):
                print("sous-agents de transfert arrêtés : rechargés au prochain ssh")
    else:
        raise UsageError("action inconnue : config %s" % args.config_cmd)
    return RC_OK


def _on_signal(signum, frame):
    raise Interrupted(signum)


# --- chargement à la demande (Match exec) ----------------------------------------------------

def _ensure_settings() -> dict:
    cfg = Config()
    return {k: cfg.get(k) for k in ("key-ttl", "auto-confirm", "auto-restrict", "forward-confirm")}


def _quiet() -> None:
    """Plus d'interruption ni de délai : le résultat est acquis, il ne reste qu'à le dire."""
    signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM))
    signal.setitimer(signal.ITIMER_REAL, 0)


def run_ensure(args) -> int:
    """`ensure --id ID` : silencieux en cas de succès (sauf avertissements du backend, une
    ligne chacun) ; sinon une ligne `sshvault: <hôte ou id> : <cause>`. Jamais de lecture de
    stdin ni de traceback ; délai global borné (compté depuis le démarrage du processus) ;
    terminal restauré et sous-processus tués sur tout chemin (finally des couches basses), y
    compris Ctrl-C, SIGTERM, SIGHUP et le délai global."""
    ids = [(i or "").strip().lower() for i in args.id]
    item_id = ids[0]
    fids = args.forward or []
    fid = fids[0] if fids else None
    label = clean(item_id) or "?"
    what = "transfert d'agent : " if fid is not None else ""
    backend = None
    try:
        c = fastpath.caller()
        if c.no_connect:
            return RC_OK  # ssh -G, ssh -O : lecture de la config, aucune connexion
        label = c.host or label
        # Jamais arrêté par le terminal : en arrière-plan, une lecture ou un réglage de /dev/tty
        # échoue (EIO) au lieu de stopper le processus (aucune n'est tentée : premier plan vérifié).
        for sig in (signal.SIGTTIN, signal.SIGTTOU):
            signal.signal(sig, signal.SIG_IGN)
        if not all(fastpath.ITEM_ID_RE.fullmatch(i) for i in ids):
            raise UsageError("--id : UUID attendu")
        if fid is None and len(ids) != 1:
            raise UsageError("une seule --id sans --forward")
        if len(fids) > 1:
            raise UsageError("--forward : une seule fois")
        if fid is not None and not FID_RE.fullmatch(fid):
            raise UsageError("--forward : 16 chiffres hexadécimaux attendus")
        if fid is not None and c.no_session:
            # ssh -W (ProxyJump, ProxyCommand) ou -N : aucun canal de session, rien à transférer ;
            # le socket du sous-agent doit seulement exister (-W impose ExitOnForwardFailure, même
            # avec -a). Avant réglages, délais et coffre : un échec là laisserait le saut sans socket.
            ensure_mod.forward_socket_only(fid)
            return RC_OK
        if fid is not None and c.no_forward:
            return RC_OK  # ssh -a, -o ForwardAgent=no : aucun agent transféré, rien à faire
        try:
            for name, default in (("SSHVAULT_PROMPT_TIMEOUT", PROMPT_TIMEOUT), ("SSHVAULT_BW_TIMEOUT", BW_TIMEOUT)):
                seconds(os.environ, name, default)
            total = fastpath.ensure_timeout(os.environ)
        except ValueError as e:
            raise ConfigError(str(e)) from None

        def on_alarm(signum, frame):
            raise Deadline(total)
        signal.signal(signal.SIGALRM, on_alarm)
        left = fastpath.time_left(total)
        if left <= 0:
            raise Deadline(total)
        signal.setitimer(signal.ITIMER_REAL, left)
        why = "--nointeraction" if args.nointeraction else "BatchMode=yes" if c.batch else ""
        ctx = ensure_mod.Context(conn=c.conn, host=c.host, interactive=not why, why_not=why,
                                 deadline_at=time.monotonic() + left)
        settings = _ensure_settings()
        store = SessionStore()
        backend = BwBackend(store=store)
        if fid is not None:
            ensure_mod.ensure_forward(fid, ids, backend, store, settings, ctx=ctx)
        else:
            ensure_mod.ensure(item_id, backend, store, settings, ctx=ctx)
        _quiet()  # clé présente ou chargée : un délai ou un signal tardif n'y change plus rien
        rc = RC_OK
    except (Exception, KeyboardInterrupt, Interrupted, Deadline) as e:
        _quiet()
        rc, msg = classify(e)
        try:
            err("%s : %s%s" % (label, what, msg))
        except (OSError, ValueError):
            pass
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    for w in (backend.warnings if backend is not None else []):
        try:
            err("%s : %s" % (label, w))
        except (OSError, ValueError):
            pass
    return rc


def classify(e: BaseException):
    """(code de sortie, message d'une ligne) d'une erreur."""
    if isinstance(e, UsageError):
        return RC_USAGE, "%s (voir sshvault --help)" % e
    if isinstance(e, (NotLoggedIn, VaultLocked)):
        return RC_LOCKED, str(e)
    if isinstance(e, SessionStoreError):
        return RC_BACKEND, "magasin de session : %s" % e
    if isinstance(e, (BackendError, ConfigWriteError, sshconfig.SshConfigError)):
        return RC_BACKEND, str(e)
    if isinstance(e, deploy_mod.DeployError):
        return RC_BACKEND, str(e)
    if isinstance(e, (InvalidHost, ConfigError, keyfile.KeyRefused, deploy_mod.BadTarget)):
        return RC_USAGE, str(e)
    if isinstance(e, (AgentStopped, AgentLocked, PassphraseRefused)):
        return RC_LOCKED, str(e)
    if isinstance(e, (AgentError, VaultError)):
        return RC_BACKEND, str(e)
    if isinstance(e, (KeyboardInterrupt, Interrupted)):
        return RC_INTERRUPTED, "interrompu"
    if isinstance(e, Deadline):
        return RC_BACKEND, "délai de %gs dépassé (SSHVAULT_ENSURE_TIMEOUT) : clé non chargée" % e.args[0]
    return RC_BACKEND, "erreur interne : %s: %s" % (type(e).__name__, e)


def main(argv=None) -> int:
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _on_signal)
    backend = None
    try:
        try:
            argv, ssh_options = split_ssh_options(sys.argv[1:] if argv is None else list(argv))
            args = build_parser().parse_args(argv)
            if args.cmd == "deploy":
                args.ssh_options = ssh_options
        except UsageError as e:
            err("%s (voir sshvault --help)" % e)
            return RC_USAGE
        if args.cmd == "ensure":
            return run_ensure(args)
        for name, default in (("SSHVAULT_PROMPT_TIMEOUT", PROMPT_TIMEOUT), ("SSHVAULT_BW_TIMEOUT", BW_TIMEOUT),
                              (deploy_mod.TIMEOUT_VAR, deploy_mod.DEFAULT_TIMEOUT)):
            try:
                seconds(os.environ, name, default)
            except ValueError as e:
                err(e)
                return RC_USAGE
        reap_orphans_quietly()
        store = SessionStore()
        backend = BwBackend(store=store)
        rc = run(args, backend)
    except BrokenPipeError:
        # sortie fermée (sshvault list | head) : rien à dire
        _stdout_to_devnull()
        rc = RC_OK
    except (Exception, KeyboardInterrupt, Interrupted, Deadline) as e:  # filet : jamais de traceback
        rc, msg = classify(e)
        err(msg)
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

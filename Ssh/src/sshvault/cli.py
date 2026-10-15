"""Commande `sshvault`.

Codes de sortie :
  0  succès
  1  aucun résultat (search, load, hosts, forward, pubkey, deploy : sélection sans élément) ;
     hosts/forward remove : hôte absent de l'élément (rien écrit) ; import : clé déjà dans le coffre (rien
     créé) ; generate : nom déjà pris par une clé du coffre, sans --force (rien généré) ;
     ssh-config --check : pas à jour (contenu, droits, fichier en trop ou non ordinaire) ou
     ligne Include absente, conditionnelle ou pas en tête
  2  usage (option ou argument invalide ; load sans sélection ni --all ; durée invalide ;
     config.json invalide, illisible ou aux droits inattendus ; config set bw-path : chemin
     relatif, absent, avec un caractère de contrôle, ou pas un fichier ordinaire exécutable ;
     hôte invalide ; sélection de hosts ou forward qui désigne plusieurs éléments ; import :
     fichier refusé — illisible, pas une clé privée, type ou format non accepté — ou --name
     avec plusieurs fichiers ; generate : type, bits, nom ou commentaire refusés ; deploy :
     cible, port ou options ssh invalides ; comptes : alias inconnu ou invalide, alias ou
     couple serveur + e-mail déjà enregistré, serveur ou e-mail invalide, écriture, login ou
     logout sans --account alors que plusieurs comptes sont possibles, logout ou account set
     avec un bw-path invalide (rien fait), aucun compte par défaut,
     account rename vers un alias déjà pris, account add : dossier accounts/<alias> existant,
     account set sans --server ni --email, ou registre refusé après la déconnexion : ce qui
     est déjà fait est dit)
  3  non connecté au coffre, aucun compte enregistré, ou coffre verrouillé (aucune invite
     possible, mot de passe refusé) ;
     agent dédié arrêté ou verrouillé (ensure --forward compris) ; passphrase d'une clé
     refusée ou impossible à saisir (load, import)
  4  erreur du backend (bw absent, non exécutable ou impossible à lancer, au chemin du réglage
     bw-path compris ; bw en erreur, réponse illisible, délai dépassé), de l'agent dédié
     (XDG_RUNTIME_DIR relatif, non privé ou hors tmpfs, chemin du socket trop long, agent
     tiers, OpenSSH < 8.9, --restrict : élément sans hôte, hôte non littéral ou absent de known_hosts ; clé publique
     illisible ou différente de la clé privée), écriture de config.json impossible,
     écriture des hôtes ou des transferts dans le coffre non aboutie ou non vérifiée
     (y compris écrits mais ssh_config non régénéré), sous-agent de transfert
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
     joker de glob), ssh-config uninstall refusé (~/.ssh/config lien symbolique ou non
     ordinaire, ~/.ssh/sshvault, sa config ou pub/ d'un type inattendu : rien modifié),
     adoption de l'installation 0.8.0 impossible (rien modifié ; account add
     refusé tant qu'elle n'est pas faite), account rename : destination existante ou
     déplacement impossible, account remove : données impossibles à supprimer, magasin de
     session ou agent en erreur (clés laissées), lock --unload : agent verrouillé ou en erreur
     (coffre verrouillé quand même, clés laissées), logout et account set : agent verrouillé ou
     en erreur (rien modifié, ou état partiel dit) ou bw logout en échec ou sans réponse (compte
     toujours connecté, ou état inconnu ; set : registre inchangé), account set : registre
     non écrit après la déconnexion, ou erreur interne
  130 interrompu (Ctrl-C, SIGTERM, SIGHUP)
`ensure` (appelé par ssh, Match exec) : 0 si la clé est présente ou chargée, et pour `ssh -G` ;
sinon le code de l'erreur, sans effet sur ssh (le Match ne porte aucune directive).
`status` : 0 si le coffre de chaque compte affiché est déverrouillé, 3 si l'un est verrouillé ou
non connecté (ou aucun compte), 4 en erreur.
Plusieurs comptes (lecture, unlock, lock, sync) : l'erreur d'un compte est dite (`<alias> : …`),
les autres sont traités ; code : le pire.
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
import shlex
import signal
import sys
import time
from typing import Optional

from . import __version__
from .agent import (CMD_TIMEOUT as AGENT_TIMEOUT, FID_RE, Agent, AgentError, AgentLocked, AgentStopped,
                    PassphraseRefused, askpass_rules, fingerprint, forward_agent, forward_agents, forward_fids,
                    is_encrypted, literal_host, public_blob, resolve_dir, tty_available)
from .agentstate import entry as state_entry, maybe_locked, reconcile, remaining
from . import accounts as accounts_mod
from .accounts import (AccountError, AccountIOError, Accounts, AdoptError, NoAccount, adopt_legacy,
                       pending_message, tag)
from .backend import (FORWARD_FIELD, HOSTS_FIELD, BackendError, InvalidHost, ItemNotFound, LogoutUnknown, NotLoggedIn, SshKeyItem, VaultBackend, VaultError,
                      VaultLocked, WriteFailed, normalize_hosts, valid_host)
from .bw import EXE_VAR as BW_EXE_VAR, BwBackend, account_dir, reset_process_state
from .config import (ACCOUNTS, BW_PATH, DEFAULT_ACCOUNTS, PATH_KEYS, DEFAULT_SERVER, Config, ConfigError, ConfigWriteError, check_alias,
                     describe_duration, normalize_email, normalize_server, parse_duration)
from . import deploy as deploy_mod
from . import ensure as ensure_mod
from . import fastpath
from .fsutil import exposure_warning
from . import keyfile
from .ensure import Deadline
from .prompt import DEFAULT_TIMEOUT as PROMPT_TIMEOUT, PromptError, ask_password, prompt_timeout
from .bw import DEFAULT_TIMEOUT as BW_TIMEOUT
from .session import DEFAULT_TTL, SessionStore, SessionStoreError
from .settings import logged_out_path, seconds, set_logged_out
from .text import clean  # texte venu du coffre, pour un terminal
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


def account_arg(s: str) -> str:
    try:
        return check_alias(s)
    except ConfigError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _account_flag(parser, what: str = "compte visé (plusieurs fois : plusieurs comptes) ; défaut : comptes par "
                                      "défaut") -> None:
    parser.add_argument("--account", metavar="ALIAS", action="append", type=account_arg, help=what)


_ONE = "compte visé (un seul) ; défaut : le compte par défaut s'il est unique"


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
                      "generate : type ou commentaire refusé, deploy : cible invalide, config set bw-path : "
                      "chemin refusé ; comptes : alias inconnu, invalide ou pris, --account requis, "
                      "account set sans option ou registre refusé après la déconnexion, logout/set : "
                      "bw-path invalide), "
                      "3 aucun compte, non connecté ou verrouillé (coffre ou agent, passphrase refusée), "
                      "4 erreur backend ou agent (lock --unload : clés non retirées), écriture ou ssh_config "
                      "impossible, install ou uninstall refusé, "
                      "adoption 0.8.0 impossible, account rename/remove/set ou logout en échec, "
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
    s = sub.add_parser("status", help="état du coffre et de la session de chaque compte")
    _account_flag(s, "compte affiché (plusieurs fois possible) ; défaut : tous")
    s = sub.add_parser("login", help="connexion d'un compte au coffre (interactive, déléguée à bw : bw login <e-mail>)")
    _account_flag(s, "compte à connecter (obligatoire s'il y a plusieurs comptes)")
    s.add_argument("--apikey", action="store_true", help="connexion par clé API (BW_CLIENTID/BW_CLIENTSECRET)")
    s = sub.add_parser("logout", help="déconnecte un compte (bw logout), oublie sa session et retire ses clés des "
                                      "agents ; compte et ssh_config gardés")
    _account_flag(s, "compte à déconnecter (obligatoire s'il y a plusieurs comptes)")
    s = sub.add_parser("unlock", help="déverrouille le coffre et garde la session (une invite par compte)")
    _account_flag(s)
    s.add_argument("--ttl", type=ttl_arg, default=DEFAULT_TTL, metavar="SECONDES",
                   help="durée de vie de la session (défaut %d)" % DEFAULT_TTL)
    s = sub.add_parser("lock", help="verrouille le coffre et oublie la session (--unload : retire aussi les clés "
                                    "des agents)")
    _account_flag(s, "compte à verrouiller (plusieurs fois possible) ; défaut : tous")
    s.add_argument("--unload", action="store_true",
                   help="retire aussi des agents (dédié et sous-agents de transfert) les clés des comptes "
                        "verrouillés ; une clé partagée avec un compte non verrouillé reste, attribuée à lui")
    s = sub.add_parser("sync", help="resynchronise le coffre depuis le serveur")
    _account_flag(s)
    s = sub.add_parser("list", help="liste les clés SSH du coffre")
    _account_flag(s)
    s.add_argument("--json", action="store_true", help="sortie JSON")
    s = sub.add_parser("password", help="mots de passe d'hôte : éléments identifiant reliés à leurs hôtes par URI "
                                        "ssh://[user@]hôte[:port] (list)")
    psub = s.add_subparsers(dest="password_cmd", metavar="ACTION", parser_class=Parser)
    psub.required = True
    a = psub.add_parser("list", help="éléments identifiant à URI ssh:// : alias, nom, hôtes ([user@]hôte), jamais le "
                                     "mot de passe")
    _account_flag(a)
    a.add_argument("--json", action="store_true", help="sortie JSON")
    s = sub.add_parser("account", help="comptes du coffre : add, list, remove, default, rename, set")
    asub = s.add_subparsers(dest="account_cmd", metavar="ACTION", parser_class=Parser)
    asub.required = True
    a = asub.add_parser("add", help="enregistre un compte (alias → serveur + e-mail) ; puis « sshvault login »")
    a.add_argument("alias", metavar="ALIAS", type=account_arg)
    a.add_argument("--server", metavar="URL", required=True, help="URL du serveur Vaultwarden")
    a.add_argument("--email", metavar="E", required=True, help="e-mail du compte")
    asub.add_parser("list", help="comptes enregistrés (alias, serveur, e-mail, défaut)")
    a = asub.add_parser("remove", help="verrouille le compte, supprime ses données locales de bw, retire ses clés "
                                       "des agents et régénère le ssh_config (rien n'est modifié dans le coffre)")
    a.add_argument("alias", metavar="ALIAS", type=account_arg)
    a = asub.add_parser("default", help="remplace la liste des comptes par défaut")
    a.add_argument("aliases", metavar="ALIAS", nargs="+", type=account_arg)
    a = asub.add_parser("set", help="change le serveur ou l'e-mail d'un compte : déconnecté s'il l'était, ses clés "
                                    "retirées des agents et ses blocs du ssh_config, puis « sshvault login » ; sauf si "
                                    "bw y est déjà connecté (registre seul corrigé)")
    a.add_argument("alias", metavar="ALIAS", type=account_arg)
    a.add_argument("--server", metavar="URL", help="nouvelle URL du serveur Vaultwarden")
    a.add_argument("--email", metavar="E", help="nouvel e-mail du compte")
    a = asub.add_parser("rename", help="renomme un compte (données, état des agents, ssh_config)")
    a.add_argument("old", metavar="ANCIEN", type=account_arg)
    a.add_argument("new", metavar="NOUVEAU", type=account_arg)
    s = sub.add_parser("search", help="cherche des clés par hôte, nom ou empreinte")
    _account_flag(s)
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
    _account_flag(s)
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
            _account_flag(h, "comptes lus (list) ; compte écrit (add, remove, set : un seul)")
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
    _account_flag(s, _ONE)
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
    _account_flag(s, _ONE)
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
    _account_flag(s)
    _selection_flags(s)

    s = sub.add_parser("deploy", help="ajoute les clés publiques sélectionnées à ~/.ssh/authorized_keys d'une "
                                      "cible, par un seul ssh (idempotent)",
                       usage="sshvault deploy [-h] [--host | --name | --fingerprint | --id] [-p PORT] [--account ALIAS] "
                             "SÉLECTION [UTILISATEUR@]HÔTE [-- OPTIONS_SSH…]")
    s.add_argument("pattern", metavar="SÉLECTION", help="comme load")
    s.add_argument("target", metavar="[UTILISATEUR@]HÔTE", help="cible (lettres, chiffres, . - _ ; IPv6 entre crochets)")
    s.add_argument("-p", dest="port", metavar="PORT", help="port de la cible")
    _account_flag(s)
    _selection_flags(s)

    s = sub.add_parser("ssh-config", help="génère ~/.ssh/sshvault/config et les clés publiques ; "
                                          "install : ligne Include en tête de ~/.ssh/config ; uninstall : retire "
                                          "la ligne Include, la config générée et les clés publiques")
    s.add_argument("action", nargs="?", choices=["install", "uninstall"], metavar="install|uninstall",
                   help="install : insère la ligne Include en tête de ~/.ssh/config (sauvegarde faite) ; "
                        "uninstall : retire la ligne Include (sauvegarde faite), ~/.ssh/sshvault/config et "
                        "~/.ssh/sshvault/pub/ (agents, comptes, sessions et données de bw gardés)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--print", dest="print_only", action="store_true",
                   help="affiche la config générée sans rien écrire")
    g.add_argument("--check", action="store_true",
                   help="code 0 si tout est à jour et la ligne Include en tête, 1 sinon ; n'écrit rien")

    s = sub.add_parser("ensure", help="charge à la demande la clé d'un élément (appelé par ssh : ligne "
                                      "Match exec du ssh_config généré)")
    s.add_argument("--account", metavar="ALIAS", action="append", help="compte de l'élément")
    s.add_argument("--id", required=True, action="append", metavar="ID",
                   help="id (UUID) de l'élément ; avec --forward : <alias>:<UUID>, plusieurs")
    s.add_argument("--forward", metavar="FID", action="append",
                   help="sous-agent de transfert (16 chiffres hexadécimaux) : y charge les clés des --id, et elles "
                        "seules")
    s.add_argument("--password", action="store_true",
                   help="mot de passe d'hôte (CAP-11) : enregistre le ssh appelant pour sshvault-askpass et "
                        "déverrouille le compte au besoin (avec --account, une --id et --host)")
    s.add_argument("--host", metavar="HÔTE", action="append", help="avec --password : hôte tapé (littéral)")

    s = sub.add_parser("config", help="réglages : key-ttl (durée de vie par défaut des clés), auto-load, "
                                      "auto-restrict, auto-confirm (chargement automatique), forward-confirm "
                                      "(sous-agents de transfert), bw-path (chemin absolu de bw ; défaut : PATH)")
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


def print_items(items: list, as_json: bool) -> None:
    """Texte : `alias⇥nom⇥empreinte⇥hôtes` (alias toujours en première colonne) ; JSON : clé `account`."""
    if as_json:
        print(json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=1))
        return
    for i in items:
        print("%s\t%s\t%s\t%s" % (clean(i.account or "-"), clean(i.name), clean(i.fingerprint or "-"),
                                  ",".join(clean(h) for h in i.hosts) or "-"))


def run_password(args, accts: Accounts, prompt) -> int:
    """`password list` : éléments identifiant à URI ssh:// des comptes lus (une invite au plus par
    compte) ; texte `alias⇥nom⇥hôtes` ou JSON (comme `list`) ; URI ignorées dites sur stderr."""
    aliases = accts.read_set(args.account)
    logins, rc, failed = [], RC_OK, 0
    for a in aliases:
        try:
            logins += tag(a, accts.backend(a).list_logins(prompt))
        except (VaultError, SessionStoreError) as e:
            if len(aliases) == 1:
                raise
            code, msg = classify(e)
            err("%s : %s" % (a, msg))
            rc, failed = max(rc, code), failed + 1
    if aliases and failed == len(aliases):
        raise _Reported(rc)
    for w in sshconfig.login_warnings(logins):
        err("avertissement : %s" % w)
    shown = [i for i in logins if i.hosts]
    if args.json:
        print(json.dumps([i.to_dict() for i in shown], ensure_ascii=False, indent=1))
    else:
        for i in shown:
            print("%s\t%s\t%s" % (clean(i.account or "-"), clean(i.name), ",".join(clean(x) for x in i.labels())))
    return rc


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


def collect(accts: Accounts, aliases: list, prompt) -> tuple:
    """(éléments de ces comptes, alias en tête, code) : une invite au plus par compte. Un seul
    compte : son erreur est levée telle quelle. Plusieurs : l'erreur d'un compte est dite (une
    ligne, `<alias> : …`) et les autres sont lus, code le pire ; tous en échec : _Reported."""
    if len(aliases) == 1:
        a = aliases[0]
        return tag(a, accts.backend(a).list_ssh_keys(prompt)), RC_OK
    items, rc, failed = [], RC_OK, 0
    for a in aliases:
        try:
            items += tag(a, accts.backend(a).list_ssh_keys(prompt))
        except (VaultError, SessionStoreError) as e:
            code, msg = classify(e)
            err("%s : %s" % (a, msg))
            rc, failed = max(rc, code), failed + 1
    if failed == len(aliases):
        raise _Reported(rc)  # aucun compte lu : erreurs déjà dites
    return items, rc


class _Reported(Exception):
    """Erreur déjà dite (une ligne par compte) : seulement le code de sortie."""

    def __init__(self, rc: int):
        super().__init__("")
        self.rc = rc


def _per_account(accts: Accounts, aliases: list, fn) -> int:
    """`fn(alias, backend)` pour chaque compte ; un seul compte : erreur levée telle quelle ;
    plusieurs : erreur dite (`<alias> : …`), les autres traités, code le pire."""
    if len(aliases) == 1:
        fn(aliases[0], accts.backend(aliases[0]))
        return RC_OK
    rc = RC_OK
    for a in aliases:
        try:
            fn(a, accts.backend(a))
        except (VaultError, SessionStoreError, AgentError) as e:
            code, msg = classify(e)
            err("%s : %s" % (a, msg))
            rc = max(rc, code)
    return rc


def run(args, accts: Accounts) -> int:
    prompt = make_prompt(args)
    if args.cmd == "search" and not args.pattern.strip():
        raise UsageError("motif vide")
    if args.cmd == "account":
        return run_account(args, accts, prompt)
    if args.cmd == "status":
        return run_status(args, accts)
    if args.cmd == "login":
        if not args.account and len(accts.registry) > 1:
            raise AccountError("login : préciser --account ALIAS (comptes : %s)" % ", ".join(accts.registry))
        alias = accts.write_one(args.account, "login") if (args.account or not accts.registry) \
            else next(iter(accts.registry))
        b = accts.backend(alias)
        try:
            state = b.login(apikey=args.apikey)
        except VaultError:
            # l'invite de bw reste sans fin de ligne si la saisie est interrompue
            sys.stderr.write("\n")
            raise
        who = "compte %s : " % alias
        if state == "unlocked":
            print(who + "connecté, coffre déverrouillé")
        else:
            print(who + "connecté ; lancer « %s » pour déverrouiller" % b.cmd("unlock"))
        return _regen_after_login()
    if args.cmd == "logout":
        return run_logout(args, accts)
    if args.cmd == "unlock":
        def unlock(a, b):
            b.unlock(prompt, ttl=args.ttl)
            _clear_unlock_failure(a)
            where = b.info()["session"]
            print("coffre déverrouillé%s (%s)" % (" : " + a if accts.multi else "",
                                                  "session %ds, %s" % (args.ttl, where) if where
                                                  else "session non rangée"))
        return _per_account(accts, accts.read_set(args.account), unlock)
    if args.cmd == "lock":
        def lock(a, b):
            b.lock()
            print("coffre verrouillé, session oubliée%s" % (" : " + a if accts.multi else ""))
        accts.need_some()  # aucun compte : NoAccount (code 3), comme unlock et sync
        if args.unload:
            return run_lock_unload(accts, accts.all(args.account))
        return _per_account(accts, accts.all(args.account), lock)
    if args.cmd == "sync":
        def sync(a, b):
            b.sync(prompt)
            print("synchronisé%s" % (" : " + a if accts.multi else ""))
        return _per_account(accts, accts.read_set(args.account), sync)
    if args.cmd == "list":
        items, rc = collect(accts, accts.read_set(args.account), prompt)
        print_items(items, args.json)
        return rc
    if args.cmd == "password":
        return run_password(args, accts, prompt)
    if args.cmd == "search":
        items, rc = collect(accts, accts.read_set(args.account), prompt)
        found = [i for i in items if match(i, args.pattern, args.by)]
        if not found:
            err("aucune clé ne correspond à « %s »" % args.pattern)
            return max(rc, RC_NONE)
        print_items(found, args.json)
        return rc
    if args.cmd == "load":
        return run_load(args, accts, prompt)
    if args.cmd == "agent":
        return run_agent(args)
    if args.cmd == "config":
        return run_config(args)
    if args.cmd in ("hosts", "forward"):
        return run_hosts(args, accts, prompt)
    if args.cmd == "ssh-config":
        return run_ssh_config(args, accts, prompt)
    if args.cmd == "import":
        return run_import(args, accts, prompt)
    if args.cmd == "generate":
        return run_generate(args, accts, prompt)
    if args.cmd == "pubkey":
        return run_pubkey(args, accts, prompt)
    if args.cmd == "deploy":
        return run_deploy(args, accts, prompt)
    raise UsageError("commande inconnue : %s" % args.cmd)


def run_status(args, accts: Accounts) -> int:
    """Tous les comptes (ou ceux de --account) : 0 s'ils sont tous déverrouillés, 3 sinon, 4 en
    erreur (le pire)."""
    describe = BwBackend(bw_path=configured_bw_path, warn=err)
    print("bw : %s" % describe.describe_exe(), flush=True)  # avant le lancement : dit même si bw manque
    aliases = accts.all(args.account)
    if not aliases:
        pending = pending_message(accts.cfg, "aucun compte utilisable pour l'instant")
        print("comptes : aucun (%s)" % (pending or "« sshvault account add ALIAS --server URL --email E »"))
        return RC_LOCKED
    rc = RC_OK
    for n, a in enumerate(aliases):
        b = accts.backend(a)
        reg = accts.registry[a]
        if n:
            print()
        print("alias : %s%s" % (a, " (défaut)" if a in accts.defaults else ""), flush=True)
        try:
            st = b.status()
        except (VaultError, SessionStoreError) as e:
            code, msg = classify(e)
            if len(aliases) == 1:
                raise
            err("%s : %s" % (a, msg))
            rc = max(rc, code)
            continue
        label = {"unauthenticated": "non connecté", "locked": "verrouillé",
                 "unlocked": "déverrouillé"}[st.state]
        info = b.info()
        print("coffre : %s" % label)
        # connecté : serveur de bw (`serverUrl` nul = serveur par défaut, comme l'avertissement)
        print("serveur : %s" % clean(_bw_server(st)[0] if st.state != "unauthenticated" else st.server or reg["server"]))
        print("compte : %s" % clean(st.user or reg["email"]))
        session = info["session"] if st.state == "unlocked" else None
        print("session : %s" % (session or "aucune"))
        print("magasin : %s" % info["store"])
        print("données : %s" % info["data"])
        diffs, want = [], {}
        if st.state != "unauthenticated":
            raw, srv = _bw_server(st)  # `serverUrl` nul : serveur par défaut, comme `account set`
            if (srv or raw) != reg["server"]:
                diffs.append("au serveur %s, le registre dit %s" % (clean(raw), reg["server"]))
                want["--server"] = srv
        if st.user and st.user.strip().lower() != reg["email"]:
            diffs.append("comme %s, le registre dit %s" % (clean(st.user), reg["email"]))
            try:
                want["--email"] = normalize_email(st.user)
            except ConfigError:
                want["--email"] = None
        if diffs:
            err("avertissement : %sbw est connecté %s : %s"
                % (accts.prefix(a), " et ".join(diffs), _status_remedy(a, want, reg, accts.registry)))
        if st.state != "unlocked":
            rc = max(rc, RC_LOCKED)
    return rc


def _status_remedy(alias: str, want: dict, reg: dict, registry: dict) -> str:
    """Remède d'un écart entre bw et le registre (`want` : {option : valeur de bw normalisée, ou
    None si invalide}) : corriger le registre par un seul `account set` (valeurs de bw, citées
    pour le shell ; invalide : à saisir), sinon reconnecter (`logout`, `login`). Couple de bw
    déjà enregistré sous un autre alias : reconnecter seulement."""
    again = "« sshvault logout --account %s » puis « sshvault login --account %s »" % (alias, alias)
    pair = (want.get("--server", reg["server"]), want.get("--email", reg["email"]))
    if None not in pair:
        other = [x for x, v in registry.items() if x != alias and (v["server"], v["email"]) == pair]
        if other:
            return "ce compte est celui de l'alias « %s » : reconnecter : %s" % (other[0], again)
    opts = " ".join("%s %s" % (f, clean(shlex.quote(v)) if v is not None else {"--email": "E", "--server": "URL"}[f])
                    for f, v in want.items())
    fix = "« sshvault account set %s %s »" % (alias, opts)
    if None in want.values():
        fix += " puis « sshvault login --account %s »" % alias
    return "registre à corriger : %s, sinon reconnecter : %s" % (fix, again)


def _clear_unlock_failure(alias: Optional[str] = None) -> None:
    """Coffre déverrouillé à la main : l'échec mémorisé par `ensure` ne bloque plus rien."""
    try:
        ensure_mod.clear_failure(resolve_dir(), alias)
    except Exception:
        pass


# --- comptes du coffre (CAP-10) ------------------------------------------------------------

def run_account(args, accts: Accounts, prompt) -> int:
    cfg = accts.cfg
    cmd = args.account_cmd
    if cmd == "list":
        if not accts.registry:
            print("aucun compte (« sshvault account add ALIAS --server URL --email E »)")
            return RC_OK
        for a, reg in accts.registry.items():
            print("%s\t%s\t%s\t%s" % (a, reg["server"], reg["email"], "défaut" if a in accts.defaults else "-"))
        return RC_OK
    if cmd == "add":
        server, email = normalize_server(args.server), normalize_email(args.email)
        pending = pending_message(cfg, "rien ajouté (un compte ajouté maintenant empêcherait l'adoption)")
        if pending:
            # l'adoption a été tentée au lancement et remise (bw illisible)
            raise AdoptError(pending)
        d_acct = account_dir(args.alias)
        if os.path.lexists(d_acct):
            raise AccountError("%s existe déjà (données d'un ancien compte ?) : rien ajouté ; le déplacer ou le "
                               "supprimer d'abord" % d_acct)

        def add(d):
            reg = d.setdefault(ACCOUNTS, {})
            if args.alias in reg:
                raise AccountError("compte « %s » déjà enregistré (%s, %s) : rien changé"
                                   % (args.alias, reg[args.alias]["server"], reg[args.alias]["email"]))
            same = [a for a, v in reg.items() if (v["server"], v["email"]) == (server, email)]
            if same:
                raise AccountError("%s sur %s déjà enregistré sous l'alias « %s » : rien changé" % (email, server, same[0]))
            reg[args.alias] = {"server": server, "email": email}
            if not d.get(DEFAULT_ACCOUNTS) and len(reg) == 1:
                d[DEFAULT_ACCOUNTS] = [args.alias]  # premier compte : compte par défaut
        data = cfg.update(add)
        n = len(data[ACCOUNTS])
        if server.startswith("http://"):
            err("avertissement : %s en http : mot de passe maître et coffre passent en clair sur le réseau" % server)
        print("compte %s ajouté : %s, %s%s" % (args.alias, server, email,
                                              ", compte par défaut" if args.alias in data.get(DEFAULT_ACCOUNTS, []) else ""))
        print("lancer « sshvault login%s »" % (" --account %s" % args.alias if n > 1 else ""))
        return RC_OK
    if cmd == "default":
        want = []
        for a in args.aliases:
            accts.check(a)
            if a not in want:
                want.append(a)

        def setdef(d):
            for a in want:  # revérifié sous le verrou : un `account remove` concurrent
                if a not in d.get(ACCOUNTS, {}):
                    raise AccountError("compte « %s » inconnu : rien changé" % a)
            d[DEFAULT_ACCOUNTS] = want
        cfg.update(setdef)
        print("comptes par défaut : %s" % ", ".join(want))
        return RC_OK
    if cmd == "rename":
        return account_rename(args, accts)
    if cmd == "remove":
        return account_remove(args, accts)
    if cmd == "set":
        return account_set(args, accts)
    raise UsageError("action inconnue : account %s" % cmd)


def _agents_with_ensure_lock():
    """(dossier de l'agent dédié, agent dédié, sous-agents) ; dossier None si XDG_RUNTIME_DIR refusé."""
    try:
        base = resolve_dir()
    except AgentError:
        return None, None, []
    return base, Agent(base), forward_agents(base)


def _states(base, main, subs):
    """Agents dont l'état existe : agent dédié puis sous-agents de transfert."""
    return [a for a in [main] + list(subs) if a is not None and os.path.exists(a.state.path)]


def _locked_or_null(base):
    import contextlib
    return _ensure_lock(base) if base is not None else contextlib.nullcontext()


def account_rename(args, accts: Accounts) -> int:
    """Données de bw déplacées, registre, comptes par défaut, session (déplacée sous le nouvel
    alias, durée restante gardée), état des agents et ssh_config ; sous ensure.lock. Rien dans le
    coffre. Alias pris : code 2 ; destination existante ou déplacement impossible : code 4."""
    old, new = args.old, args.new
    accts.check(old)
    if new in accts.registry:
        raise AccountError("alias « %s » déjà pris : rien changé" % new)
    src_dir, dst_dir = account_dir(old), account_dir(new)
    if os.path.lexists(dst_dir):
        raise AccountIOError("%s existe déjà : rien changé" % dst_dir)
    base, main, subs = _agents_with_ensure_lock()
    session_note = None
    with _locked_or_null(base):
        moved = False
        if os.path.lexists(src_dir):
            try:
                os.rename(src_dir, dst_dir)
                moved = True
            except OSError as e:
                raise AccountIOError("déplacement de %s vers %s impossible (%s) : rien changé"
                                     % (src_dir, dst_dir, e.strerror or e)) from None

        def ren(d):
            reg = d.get(ACCOUNTS, {})
            if old not in reg or new in reg:  # revérifié sous le verrou
                raise AccountError("compte « %s » absent ou alias « %s » pris entre-temps : rien changé" % (old, new))
            reg[new] = reg.pop(old)
            d[DEFAULT_ACCOUNTS] = [new if a == old else a for a in d.get(DEFAULT_ACCOUNTS, [])]
        try:
            accts.cfg.update(ren)
        except BaseException:
            if moved:
                try:
                    os.rename(dst_dir, src_dir)
                except OSError:
                    pass
            raise
        try:
            SessionStore(alias=old).move_to(SessionStore(alias=new))
        except SessionStoreError as e:
            session_note = str(e)
            for a in (old, new):
                try:
                    SessionStore(alias=a).clear()
                except SessionStoreError:
                    pass
        if base is not None:
            _clear_unlock_failure(old)

            def relabel(d):
                for e in d["keys"].values():
                    if e.get("account") == old:
                        e["account"] = new
                    if e.get("also"):
                        e["also"] = ["%s:%s" % (new, x.split(":", 1)[1]) if isinstance(x, str) and x.startswith(old + ":")
                                     else x for x in e["also"]]
            for a in _states(base, main, subs):
                try:
                    a.update(relabel)
                except AgentError as e:
                    err("avertissement : état de l'agent %s : %s" % (a.state.path, e))
    multi = len(accts.registry) > 1
    print("compte %s renommé en %s" % (old, new))
    if session_note is not None:
        err("avertissement : session de %s non déplacée (%s) : oubliée, déverrouillage à refaire (« sshvault unlock%s »)"
            % (old, session_note, " --account %s" % new if multi else ""))
    return _regen_after_registry_change(renamed={old: new})


def _owner_refs(e: dict, alias: str, ids: set):
    """(entrée au compte `alias` ?, autres détenteurs de la clé : références `also` d'autres
    comptes, dans l'ordre)."""
    def is_mine(acct, iid):
        return acct == alias or (acct is None and iid.lower() in ids)
    mine = is_mine(e.get("account"), e["id"])
    others = []
    for x in e.get("also") or []:
        if not isinstance(x, str):
            continue
        a, i = fastpath._pair(x)
        if not is_mine(a, i):
            others.append(x)
    return mine, others


def _drop_account(dd: dict, alias: str, ids: set, known: Optional[dict] = None) -> set:
    """Entrées de l'état sans le compte `alias` : sa clé gardée et promue au détenteur suivant
    si un autre compte la partage (`also` ; nom et hôtes du nouveau détenteur pris dans `known`
    {(compte, id) : (nom, hôtes)}, sinon inconnus : « ? », aucun hôte), sinon entrée retirée.
    Renvoie les empreintes à retirer de l'agent."""
    unload = set()
    for fp, e in list(dd["keys"].items()):
        mine, others = _owner_refs(e, alias, ids)
        if mine and not others:
            del dd["keys"][fp]
            unload.add(fp)
            continue
        if mine:
            a, i = fastpath._pair(others[0])
            e["id"] = i
            if a:
                e["account"] = a
            else:
                e.pop("account", None)
            name, hosts = (known or {}).get((a, i), ("?", []))
            e["name"], e["hosts"] = name, list(hosts)
        if mine or e.get("also"):
            rest = others[1:] if mine else others
            if rest:
                e["also"] = rest
            else:
                e.pop("also", None)
    return unload


def _known_items() -> dict:
    """{(compte, id) : (nom, hôtes)} des blocs du ssh_config généré ({} sans fichier)."""
    try:
        paths = sshconfig.default_paths()
        return {(i.account, i.id): (i.name, list(i.hosts)) for i in sshconfig.kept_items(paths, lambda a: True,
                                                                                     known=Config().accounts())}
    except Exception:
        return {}


def _account_ids(b) -> tuple:
    """(ids des éléments du compte, connus ?) : lus sans invite si le compte est déverrouillé,
    pour les entrées d'état sans compte (chargées avant la 0.9.0)."""
    try:
        if b.store.get():
            return {i.id.lower() for i in b.list_ssh_keys(None)}, True
    except (VaultError, SessionStoreError, ConfigError):
        pass
    return set(), False


def _mine_candidate(e: dict, alias: str) -> bool:
    """Entrée d'état qui peut être au compte `alias` (à lui, sans compte, ou référence `also` à
    lui ou sans compte), avant toute lecture du coffre."""
    if e.get("account") in (None, "", alias):
        return True
    return any(isinstance(x, str) and fastpath._pair(x)[0] in (None, alias) for x in e.get("also") or [])


def _check_agents(alias: str, agents, kept: str, retry: str, fail=None):
    """Avant tout appel à bw et tout effet : état de chaque agent (dédié, sous-agents) lu, et
    ceux qui portent une clé possible du compte listés et contrôlés non verrouillés (agent qui
    ne liste rien alors qu'une clé possible du compte n'est pas échue : verdict de la sonde
    `ssh-add -D`). Renvoie [(agent, état, clés listées)] ; None si un agent est verrouillé ou
    en erreur (une ligne : `kept`, ce qui reste ; `retry`, commande à relancer ; `fail` :
    remplace `_agents_failed`)."""
    base, main, subs = agents
    if base is None:
        return []
    out, now = [], time.time()
    for a in _states(base, main, subs):
        try:
            data = a.state.load()
            present = {}
            cand = [fp for fp, e in data["keys"].items() if _mine_candidate(e, alias)]
            if cand and os.path.exists(a.socket):
                present = {k.fingerprint: k for k in a.keys()}
                live = [fp for fp in cand if remaining(data["keys"][fp], now) != 0]
                if live and (data.get("locked") or (maybe_locked(data, set(present)) and a.probe_locked())):
                    raise AgentLocked("agent verrouillé")
            out.append((a, data, present))
        except AgentError as e:
            (fail or _agents_failed)(alias, a, e, kept, retry)
            return None
    return out


def _agents_failed(alias: str, a, e, what: str, retry: str) -> None:
    err("clés de %s dans l'agent %s non retirées (%s) : %s ; « sshvault agent unlock » puis relancer « %s »"
        % (alias, a.socket, e, what, retry))


def _unload_account(alias: str, accts: Accounts, b, checked: list, kept: str, retry: str, fail=None):
    """Clés du compte `alias` retirées des agents vérifiés par `_check_agents` ; une clé partagée
    avec un autre compte reste, promue à l'autre détenteur. À appeler sous ensure.lock. `bw
    list` seulement pour des entrées sans compte (chargées avant la 0.9.0). Renvoie (clés
    retirées, empreintes chargées avant la 0.9.0 laissées, état d'un agent modifié ?) ; None si
    un retrait échoue : une ligne (`kept` si rien n'a encore été modifié, sinon l'état partiel,
    agent en cours nommé ; `retry` : commande à relancer ; `fail` : remplace `_agents_failed`)."""
    removed, legacy_left, changed = 0, set(), []
    legacy = any(not e.get("account") or any(isinstance(x, str) and fastpath._pair(x)[0] is None
                                             for x in e.get("also") or [])
                 for _, data, _ in checked for e in data["keys"].values())
    ids, ids_known = _account_ids(b) if legacy else (set(), True)
    known = _known_items()
    now = time.time()
    plans = []
    for a, data, present in checked:  # 1) plan, rien retiré
        if not ids_known:
            # entrées d'avant la 0.9.0 sans compte, que rien n'attribue à un autre compte
            legacy_left |= {fp for fp, e in data["keys"].items() if not e.get("account") and not any(
                fastpath._pair(x)[0] in accts.registry and fastpath._pair(x)[0] != alias
                for x in e.get("also") or [] if isinstance(x, str))}
        copy = dict(data, keys={k: dict(v) for k, v in data["keys"].items()})
        unload = _drop_account(copy, alias, ids, known)
        if copy != data:
            plans.append((a, data, unload, present))
    for a, data, unload, present in plans:  # 2) retrait
        here = 0
        try:
            for fp in unload:
                if fp not in present:
                    continue
                try:
                    a.remove(present[fp])
                    here += 1  # vrais retraits seulement
                except AgentError:
                    # clé partie entre les deux passes (durée de vie écoulée, ssh-add -d) : retirée ;
                    # mais un agent qui ne liste plus rien alors que la clé vit encore est peut-être
                    # verrouillé : la sonde `ssh-add -D` tranche (vide et déverrouillé : partie ;
                    # verrouillé : entrée gardée, code 4)
                    listed = {k.fingerprint for k in a.keys()}
                    if fp in listed:
                        raise
                    if data.get("locked") or (not listed and remaining(data["keys"][fp], now) != 0
                                              and a.probe_locked()):
                        raise AgentLocked("agent verrouillé") from None
                removed += 1
            late = set()

            def drop_planned(dd):
                # état frais : une clé du compte arrivée pendant la commande (load hors verrou)
                # n'était pas au plan ; elle reste chargée : son entrée est gardée
                before = {k: dict(v) for k, v in dd["keys"].items()}
                for fp in _drop_account(dd, alias, ids, known) - set(unload):
                    dd["keys"][fp] = before[fp]
                    late.add(fp)
            a.update(drop_planned)
            changed.append(a)
            if late:
                err("avertissement : %d clé%s de %s chargée%s pendant la commande laissée%s dans l'agent %s "
                    "(« sshvault agent purge » ou relancer « %s »)"
                    % (len(late), "s" if len(late) > 1 else "", alias, "s" if len(late) > 1 else "",
                       "s" if len(late) > 1 else "", a.socket, retry))
        except AgentError as e:
            if removed or changed:
                parts = [_keys_removed(removed)]
                if changed:
                    parts.append("agent%s %s déjà mis à jour" % ("s" if len(changed) > 1 else "",
                                                                 ", ".join(x.socket for x in changed)))
                if here:
                    parts.append("agent %s partiellement modifié" % a.socket)
                what = "état partiel : " + ", ".join(parts)
            else:
                what = kept
            (fail or _agents_failed)(alias, a, e, what, retry)
            return None
    return removed, legacy_left, bool(changed)


def _session_state(b) -> Optional[bool]:
    """Session rangée du compte ? None : magasin de session en erreur."""
    try:
        return b.store.get() is not None
    except SessionStoreError:
        return None


def _forget_session(b) -> None:
    """Session oubliée sans bw (compte non connecté) ; échec : avertissement de fin de commande."""
    try:
        b.store.clear()
    except SessionStoreError as e:
        b.warnings.append("session non oubliée : %s" % e)


def _forgot(b, had: Optional[bool]) -> bool:
    return had is True and _session_state(b) is False


def _set_logged_out_marker(alias: str, b=None) -> None:
    """Pose le marqueur `logged-out` du compte (dans son dossier persistant, lu par ensure),
    seulement si ce dossier existe ; il est retiré par le backend dès que bw est vu connecté.
    Un avertissement « non retiré » du backend `b` dans la même commande est retiré (la
    commande pose le marqueur). Échec (chemin occupé, droits…) : avertissement."""
    if b is not None:
        b.marker_cleared = False
        if b.marker_warning in b.warnings:
            b.warnings.remove(b.marker_warning)
    try:
        set_logged_out(alias)
    except OSError as e:
        err("avertissement : marqueur %s non posé (%s) : « sshvault ensure » ne proposera pas de relancer "
            "« sshvault login »" % (logged_out_path(alias), e.strerror or e))


def _legacy_left_warning(alias: str, legacy_left: set) -> None:
    if legacy_left:
        n = len(legacy_left)
        err("avertissement : %d clé%s chargée%s avant la 0.9.0 (compte inconnu, %s verrouillé) laissée%s dans les "
            "agents (« sshvault agent purge » pour les retirer)"
            % (n, "s" if n > 1 else "", "s" if n > 1 else "", alias, "s" if n > 1 else ""))


def _keys_removed(n: int) -> str:
    return "%d clé%s retirée%s des agents" % (n, "s" if n > 1 else "", "s" if n > 1 else "")


def account_remove(args, accts: Accounts) -> int:
    """Sous ensure.lock, dans cet ordre : clés du compte retirées des agents (dédié et
    sous-agents ; une clé partagée avec un autre compte reste, promue), puis compte verrouillé
    (session oubliée), données locales de bw supprimées, compte retiré du registre ; ensuite
    ssh_config régénéré. Agents en erreur ou verrouillés : arrêt avant toute suppression, état
    gardé, une ligne, code 4. Rien n'est modifié dans le coffre."""
    import shutil
    alias = accts.check(args.alias)
    rc = RC_OK
    b = accts.backend(alias)
    d = account_dir(alias)
    agents = _agents_with_ensure_lock()
    kept, again = "compte gardé, rien supprimé", "sshvault account remove %s" % alias
    with _locked_or_null(agents[0]):
        checked = _check_agents(alias, agents, kept, again)
        done = None if checked is None else _unload_account(alias, accts, b, checked, kept, again)
        if done is None:
            return RC_BACKEND
        removed, legacy_left, _ = done
        _clear_unlock_failure(alias)
        try:
            b.lock()
        except (VaultError, SessionStoreError, ConfigError) as e:
            err("avertissement : verrouillage de %s : %s" % (alias, classify(e)[1]))
            try:
                SessionStore(alias=alias).clear()
            except SessionStoreError as e2:
                err("magasin de session : %s" % e2)
                rc = RC_BACKEND
        try:
            if os.path.lexists(d):
                shutil.rmtree(d)
        except OSError as e:
            raise AccountIOError("suppression de %s impossible (%s) : compte gardé, relancer « sshvault account remove "
                                 "%s »" % (d, e.strerror or e, alias)) from None

        def drop(dd):
            dd[ACCOUNTS].pop(alias, None)
            dd[DEFAULT_ACCOUNTS] = [a for a in dd.get(DEFAULT_ACCOUNTS, []) if a != alias]
        accts.cfg.update(drop)
    _legacy_left_warning(alias, legacy_left)
    print("compte %s retiré : session oubliée, données locales supprimées, %s ; rien n'est modifié dans le coffre"
          % (alias, _keys_removed(removed)))
    return max(rc, _regen_after_registry_change())


def _logout_failed(alias: str, b, e: BaseException, removed: int, had: Optional[bool], again: str,
                   extra: str = "") -> int:
    """`bw logout` en échec : une ligne qui dit ce qui reste et ce qui est fait, code 4. État
    inconnu (LogoutUnknown) : marqueur posé (retiré dès que bw sera vu connecté)."""
    if isinstance(e, LogoutUnknown):
        _set_logged_out_marker(alias, b)
    after = _session_state(b)
    done = [_keys_removed(removed)]
    if had:
        done.append("session oubliée" if after is False else "session non oubliée (magasin de session en erreur)")
    state = ("état de connexion inconnu, données de bw sous l'alias %s (%s)" if isinstance(e, LogoutUnknown)
             else "données de bw toujours connectées sous l'alias %s (%s)") % (alias, b.appdata)
    err("bw logout en échec (%s) : %s ; %s%s ; relancer « %s »" % (classify(e)[1], state, ", ".join(done), extra, again))
    return RC_BACKEND


def _on_logout_interrupted(alias: str, b):
    """`bw logout` interrompu (`logout`, `account set`) : appelé signaux retenus, état relu ;
    marqueur `logged-out` posé si bw est déconnecté ou si son état est inconnu (retiré dès que
    bw sera vu connecté), mémoire d'échec de déverrouillage effacée. L'interruption suit
    (« interrompu », code 130)."""
    def done(gone: Optional[bool]) -> None:
        _clear_unlock_failure(alias)
        if gone is not False:
            _set_logged_out_marker(alias, b)
    return done


def _probe(b):
    """État du compte dans bw, sans effet sur la session rangée ; None si ses données sont
    absentes (bw jamais lancé : il les créerait)."""
    return b.status(forget=False) if os.path.isdir(b.appdata) else None


def run_logout(args, accts: Accounts) -> int:
    """`logout [--account ALIAS]` : `bw-path` vérifié d'abord (code 2, rien fait). Sous
    ensure.lock : état lu dans bw (sans effet sur la session), puis chaque agent vérifié
    (lisible, non verrouillé) avant toute liste du coffre, clés du compte retirées (clé
    partagée avec un autre compte gardée, promue), `bw logout` s'il est connecté ou si son état est illisible,
    session oubliée, marqueur `logged-out` posé dans le dossier du compte (ensure propose
    `login`). Compte gardé au registre, blocs du ssh_config gardés. Plusieurs comptes :
    --account obligatoire (code 2). Rien du tout à faire (non connecté, ni clé, ni état
    d'agent, absence de session sûre) : une ligne, code 0, rien touché. Agent verrouillé ou en
    erreur, `bw logout` en échec ou état inconnu : une ligne, code 4."""
    if not args.account and len(accts.registry) > 1:
        raise AccountError("logout : préciser --account ALIAS (comptes : %s)" % ", ".join(accts.registry))
    alias = accts.write_one(args.account, "logout") if (args.account or not accts.registry) \
        else next(iter(accts.registry))
    b = accts.backend(alias)
    b.exe  # bw-path invalide : ConfigError (code 2) avant tout changement, même sans données de bw
    again = "sshvault logout --account %s" % alias
    agents = _agents_with_ensure_lock()
    with _locked_or_null(agents[0]):
        had = _session_state(b)
        # sonde d'abord : `bw status` sans effet sur la session (seul appel à bw avant le contrôle
        # des agents ; aucun `bw list` avant lui)
        try:
            st = _probe(b)
        except VaultError as e:  # état illisible : bw logout tenté quand même
            st, unknown = None, e
        else:
            unknown = None
        checked = _check_agents(alias, agents, "rien modifié", again)
        done = None if checked is None else _unload_account(alias, accts, b, checked, "rien modifié", again)
        if done is None:
            return RC_BACKEND
        removed, legacy_left, changed = done
        connected = unknown is not None or (st is not None and st.state != "unauthenticated")
        if connected:
            try:
                connected = b.logout(_on_logout_interrupted(alias, b))  # False : bw n'était pas (plus) connecté
            except VaultError as e:
                if unknown is not None and not getattr(e, "reread_connected", False):
                    a1, a2 = classify(unknown)[1], classify(e)[1]
                    e = LogoutUnknown("bw status et bw logout : %s" % a1 if a1 == a2
                                      else "bw status : %s ; bw logout : %s" % (a1, a2))
                _clear_unlock_failure(alias)
                return _logout_failed(alias, b, e, removed, had, again)
        elif had is not False:
            _forget_session(b)
        forgot = _forgot(b, had)
        nothing = not connected and not changed and had is False
        if not nothing:  # « rien à faire » : rien touché, mémoire d'échec de déverrouillage comprise
            _clear_unlock_failure(alias)
            _set_logged_out_marker(alias, b)
        elif b.marker_cleared:
            # la sonde a vu bw connecté (marqueur retiré), puis bw s'est dit non connecté : reposé
            _set_logged_out_marker(alias, b)
    _legacy_left_warning(alias, legacy_left)
    if nothing:
        print("compte %s non connecté : rien à faire" % alias)
        return RC_OK
    print("compte %s %s : %s ; compte et blocs du ssh_config gardés ; reconnecter : « sshvault login --account %s »"
          % (alias, "déconnecté" if connected else "non connecté",
             ", ".join((["session oubliée"] if forgot else []) + [_keys_removed(removed)]), alias))
    return RC_OK


def run_lock_unload(accts: Accounts, aliases: list) -> int:
    """`lock --unload` : sous ensure.lock, compte après compte (une clé partagée par deux comptes
    verrouillés part avec le second) : agents vérifiés, clés du compte retirées des agents (clé
    partagée avec un autre compte gardée, promue), puis coffre verrouillé (`b.lock()` après le
    retrait : la session sert aux entrées d'avant la 0.9.0). Agent verrouillé ou en erreur : le
    coffre est verrouillé quand même (un `lock` n'est jamais empêché), une ligne dit les clés non
    retirées, code 4. Erreur de verrouillage : une ligne (plusieurs comptes : `<alias> : …`), les
    clés retirées sont dites quand même, les autres comptes traités ; code : le pire (agent et
    verrouillage compris)."""
    agents = _agents_with_ensure_lock()
    rc = RC_OK
    with _locked_or_null(agents[0]):
        for a in aliases:
            b = accts.backend(a)
            retry = "sshvault lock --unload%s" % (" --account %s" % a if accts.multi else "")
            fails = []

            def note(*failure):
                fails.append(failure)
            done = None
            checked = _check_agents(a, agents, "clés gardées", retry, fail=note)
            if checked is not None:
                done = _unload_account(a, accts, b, checked, "clés gardées", retry, fail=note)
            lock_error = None
            try:
                b.lock()
            except (VaultError, SessionStoreError, ConfigError) as e:
                lock_error = e
            # `b.lock()` oublie la session même si bw échoue ; SessionStoreError : bw a verrouillé,
            # session non oubliée. État de la session : relu dans le magasin
            vault_locked = lock_error is None or isinstance(lock_error, SessionStoreError)
            for alias, ag, e, what, again in fails:
                _agents_failed(alias, ag, e, "%s, %s" % (what, "coffre verrouillé quand même" if vault_locked
                                                         else "coffre non verrouillé (ci-dessous)"), again)
            if fails:
                rc = max(rc, RC_BACKEND)
            if lock_error is not None:
                code, msg = classify(lock_error)
                err("%s%s" % (accts.prefix(a), msg))
                rc = max(rc, code)
            if done is not None:
                _legacy_left_warning(a, done[1])
            print("%s, %s%s%s" % ("coffre verrouillé" if vault_locked else "coffre non verrouillé (erreur ci-dessus)",
                                  "session oubliée" if _session_state(b) is False else "session non oubliée",
                                  " : " + a if accts.multi else "",
                                  ", " + _keys_removed(done[0]) if done is not None
                                  else ", clés non retirées des agents"))
    return rc


def _bw_server(st) -> tuple:
    """(serveur de bw tel qu'affiché, normalisé ou None si invalide) ; `serverUrl` nul = serveur
    par défaut de bw. Même règle pour `status` et `account set`."""
    raw = st.server or DEFAULT_SERVER
    try:
        return raw, normalize_server(raw)
    except ConfigError:
        return raw, None


def _bw_pair(st) -> Optional[tuple]:
    """(serveur, e-mail) normalisés du compte connecté dans bw, ou None."""
    try:
        return _bw_server(st)[1], normalize_email(st.user or "")
    except ConfigError:
        return None


def account_set(args, accts: Accounts) -> int:
    """`account set ALIAS [--server URL] [--email E]` : validé comme `account add` (au moins une
    option ; couple unique, code 2 ; valeurs identiques : rien fait, code 0 ; `bw-path` vérifié
    avant tout changement, code 2). bw déjà connecté avec exactement ces serveur et e-mail
    (seul le registre se trompait) : registre corrigé, rien d'autre. Sinon, sous ensure.lock :
    clés du compte retirées des agents, `bw logout` (compte connecté), session oubliée,
    registre mis à jour ; ensuite ssh_config régénéré sans les blocs du compte (ils visaient
    l'ancien). Alias et comptes par défaut gardés. Agent verrouillé ou en erreur, `bw logout`
    en échec : une ligne, registre inchangé, code 4 ; registre refusé après la déconnexion :
    une ligne qui dit ce qui est fait (code 2, 4 si l'écriture échoue)."""
    alias = accts.check(args.alias)
    if args.server is None and args.email is None:
        raise UsageError("account set : préciser --server URL et/ou --email E")
    old = accts.registry[alias]
    server = normalize_server(args.server) if args.server is not None else old["server"]
    email = normalize_email(args.email) if args.email is not None else old["email"]
    if (server, email) == (old["server"], old["email"]):
        print("compte %s inchangé (%s, %s) : rien fait" % (alias, server, email))
        return RC_OK

    def same_pair(reg):
        return [a for a, v in reg.items() if a != alias and (v["server"], v["email"]) == (server, email)]
    dup = same_pair(accts.registry)
    if dup:
        raise AccountError("%s sur %s déjà enregistré sous l'alias « %s » : rien changé" % (email, server, dup[0]))
    b = accts.backend(alias)
    b.exe  # bw-path invalide : ConfigError (code 2) avant tout changement, même sans données de bw
    if server != old["server"] and server.startswith("http://"):
        err("avertissement : %s en http : mot de passe maître et coffre passent en clair sur le réseau" % server)

    def setreg(d):
        reg = d.get(ACCOUNTS, {})
        if alias not in reg:  # revérifié sous le verrou : un `account remove` concurrent
            raise AccountError("compte « %s » retiré entre-temps" % alias)
        dup = same_pair(reg)
        if dup:
            raise AccountError("%s sur %s déjà enregistré sous l'alias « %s »" % (email, server, dup[0]))
        reg[alias] = {"server": server, "email": email}
    again = "sshvault account set %s%s%s" % (alias, " --server %s" % shlex.quote(server) if args.server is not None else "",
                                              " --email %s" % shlex.quote(email) if args.email is not None else "")
    changed = "%s, %s (avant : %s, %s)" % (server, email, old["server"], old["email"])
    agents = _agents_with_ensure_lock()
    with _locked_or_null(agents[0]):
        had = _session_state(b)
        try:  # sonde d'abord (sans effet sur la session) : le registre seul ne dépend pas des agents
            st = _probe(b)
        except VaultError as e:  # état inconnu : ni registre corrigé à l'aveugle, ni déconnexion
            code, msg = classify(e)
            err("%s : état de connexion de bw inconnu : rien fait ; relancer « %s »" % (msg, again))
            return code
        connected = st is not None and st.state != "unauthenticated"
        if connected and _bw_pair(st) == (server, email):
            # seul le registre se trompait : bw est déjà connecté à ce compte
            try:
                accts.cfg.update(setreg)
            except AccountError as e:
                raise AccountError("%s : rien changé" % e) from None
            print("compte %s : registre corrigé : %s ; bw y est déjà connecté : ni déconnexion, ni clé ni bloc retiré"
                  % (alias, changed))
            return RC_OK
        checked = _check_agents(alias, agents, "registre inchangé", again)  # avant tout `bw list`
        if checked is None:
            return RC_BACKEND
        done = _unload_account(alias, accts, b, checked, "registre inchangé", again)
        if done is None:
            return RC_BACKEND
        removed, legacy_left, _ = done
        _clear_unlock_failure(alias)
        if connected:
            try:
                connected = b.logout(_on_logout_interrupted(alias, b))  # False : déconnecté entre-temps
            except VaultError as e:
                return _logout_failed(alias, b, e, removed, had, again, ", registre inchangé")
            if connected or b.marker_cleared:  # déconnecté, ou vu connecté puis plus : marqueur (re)posé
                _set_logged_out_marker(alias, b)
        else:
            _forget_session(b)
        what = ", ".join((["déconnecté de l'ancien compte"] if connected else [])
                         + (["session oubliée"] if _forgot(b, had) else []) + [_keys_removed(removed)])
        try:
            accts.cfg.update(setreg)
        except ConfigError as e:  # ConfigWriteError comprise
            err("registre non mis à jour (%s) : déjà fait : %s ; registre inchangé ; relancer « %s »"
                % (e, what, again))
            return classify(e)[0]
        except AccountError as e:
            err("registre non mis à jour (%s) : déjà fait : %s ; registre inchangé" % (e, what))
            return RC_USAGE
    _legacy_left_warning(alias, legacy_left)
    print("compte %s modifié : %s ; %s" % (alias, changed, what))
    rc = _regen_after_registry_change(fresh={alias: []})
    print("lancer « sshvault login --account %s »" % alias)
    return rc


def _regen_after_login() -> int:
    """Après un login : ssh_config régénéré s'il existe (tous les comptes, comptes illisibles
    gardés), sinon la commande à lancer est dite."""
    try:
        paths = sshconfig.default_paths()
    except sshconfig.SshConfigError:
        return RC_OK
    if not os.path.exists(paths.config):
        print("lancer « sshvault ssh-config » pour générer la config ssh")
        return RC_OK
    return _regen_after_registry_change()


def _regen_after_registry_change(renamed: Optional[dict] = None, fresh: Optional[dict] = None) -> int:
    """ssh_config régénéré après un changement du registre (comptes lus sans invite : blocs des
    comptes verrouillés gardés ; `fresh` {alias : éléments} : comptes pris tels quels, sans
    lecture — `account set` : [], blocs retirés). Pas de ssh_config généré : rien à faire."""
    try:
        paths = sshconfig.default_paths()
    except sshconfig.SshConfigError:
        return RC_OK
    if not os.path.exists(paths.config):
        return RC_OK
    accts = Accounts(bw_path=configured_bw_path, warn=err)
    try:
        # `fresh` : comptes pris sans lecture (`account set` : blocs retirés), éléments identifiant compris
        src = gather(accts, paths, fresh or {}, None, renamed, fresh_logins={a: [] for a in fresh or {}})
        regenerate(src.items, paths, kept=src.kept, notes=src.notes, logins=src.logins)
    except (sshconfig.SshConfigError, AgentError, ConfigError) as e:
        err("ssh_config non régénéré : %s (lancer « sshvault ssh-config »)" % e)
        return RC_BACKEND
    finally:
        _ACCOUNTS_SEEN.append(accts)
    return RC_OK


#: Contextes de comptes créés pendant la commande (avertissements des backends en fin de commande).
_ACCOUNTS_SEEN: list = []


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


def run_load(args, accts: Accounts, prompt) -> int:
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
            raise AgentLocked(ensure_mod.AGENT_LOCKED)
        present = {k.blob for k in current}
    lock_wait = None
    if args.nointeraction:  # attente d'ensure.lock bornée (interactif : sans limite, Ctrl-C)
        try:
            lock_wait = fastpath.ensure_timeout(os.environ)
        except ValueError as e:
            raise ConfigError(str(e)) from None

    items, rc_read = collect(accts, accts.read_set(args.account), prompt)
    found = [i for i in items if args.all or match(i, args.pattern, args.by)]
    if not found:
        err("aucune clé ne correspond à « %s »" % args.pattern if args.pattern is not None
            else "aucune clé SSH dans le coffre")
        return max(rc_read, RC_NONE)
    todo, seen, skipped, already = [], set(), 0, []
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
            already.append((i, blob))
        else:
            todo.append((i, blob))
    if not todo:
        if skipped and not already:
            raise AgentError("aucune clé chargeable (clé publique illisible)")
        return rc_read
    if args.restrict:
        for i, _ in todo:
            _restrict_hosts(i)

    agent.ensure_running()  # dossier de l'agent (et d'ensure.lock) créé ; relu sous le verrou
    if args.restrict:
        agent.check_hosts(sorted({h.lower() for i, _ in todo for h in i.hosts}))
    interactive = not args.nointeraction
    keys, added, done, back = {}, {}, [], set()
    try:
        # Toutes les clés lues avant le premier chargement, hors du verrou (invites du coffre).
        for i, _ in todo:
            keys[i.account, i.id] = accts.backend(i.account).get_private_key(i.id, prompt)
            if not interactive and is_encrypted(keys[i.account, i.id]):
                raise PassphraseRefused("« %s » : clé chiffrée par passphrase, saisie impossible "
                                        "(--nointeraction) : rien chargé" % clean(i.name))
        # Ajouts, retour arrière et état sous ensure.lock (puis le verrou d'état de l'agent, pris
        # par chaque lecture-écriture, comme ensure et logout) : une sonde `ssh-add -D` (logout,
        # lock --unload, ensure, agent unlock) ne retire jamais une clé en cours de chargement.
        # La passphrase d'une clé chiffrée se tape sous ce verrou, comme pour ensure.
        with _ensure_lock(agent.dir, lock_wait):
            # relu sous le verrou : agent verrouillé (agent lock), arrêté puis relancé, ou clé
            # chargée (ensure) pendant l'attente
            adata, _ = agent.ensure_running()
            current = agent.keys()
            _sync_lock_flag(agent, adata, current)
            if adata["locked"]:
                raise AgentLocked(ensure_mod.AGENT_LOCKED)
            if args.confirm and (adata.get("agent") or {}).get("askpass") is False:
                err("avertissement : l'agent a été lancé sans askpass utilisable (DISPLAY, SSH_ASKPASS) : "
                    "chaque usage d'une clé --confirm sera refusé ; « sshvault agent stop » puis load depuis "
                    "une session graphique")
            present = {k.blob for k in current}
            if not args.force:
                for i, blob in [t for t in todo if t[1] in present]:
                    print("déjà chargée : %s %s (--force pour recharger)" % (clean(i.name), fingerprint(blob)))
                    keys.pop((i.account, i.id), None)
                todo = [t for t in todo if t[1] not in present]
            # comptes revus : logout, lock, account remove, rename ou set pendant l'attente : rien chargé
            opened = sorted({i.account for i, _ in todo})
            _accounts_still_open(accts, opened)
            # « déjà chargée » au départ mais retirée de l'agent pendant l'attente : rechargée avec
            # les options de cette commande. Pour chacune : compte revu (une fois par compte),
            # --restrict (échec : rien chargé, code 4), relecture sans invite du coffre ; compte
            # fermé, relecture en échec ou clé chiffrée sans saisie possible : sautée (une ligne)
            verdict = {a: None for a in opened}
            for i, blob in [t for t in already if t[1] not in present]:
                if i.account not in verdict:
                    verdict[i.account] = _account_gone(accts, i.account)
                why = verdict[i.account]
                if why is None and args.restrict:
                    _restrict_hosts(i)
                    agent.check_hosts(sorted({h.lower() for h in i.hosts}))
                if why is None:
                    try:
                        keys[i.account, i.id] = accts.backend(i.account).get_private_key(i.id, None)
                    except (VaultError, SessionStoreError) as e:
                        why = "relecture du coffre : %s" % classify(e)[1]
                if why is None and not interactive and is_encrypted(keys[i.account, i.id]):
                    why = "clé chiffrée par passphrase, saisie impossible (--nointeraction)"
                if why:
                    keys.pop((i.account, i.id), None)
                    err("%s%s %s non rechargée : %s" % (accts.prefix(i.account), clean(i.name), fingerprint(blob), why))
                    continue
                todo.append((i, blob))
                back.add(blob)
            timeout = prompt_timeout(os.environ) + 10
            try:
                for i, blob in todo:
                    key = keys.pop((i.account, i.id))
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
            if done:
                now = time.time()

                def record(d):
                    reconcile(d, {k.fingerprint for k in agent.keys()}, now)
                    for i, blob, t in done:
                        d["keys"][fingerprint(blob)] = state_entry(i.id, i.name, i.hosts, t, lifetime, args.confirm,
                                                                   args.restrict, i.account)
                agent.update(record)
    except ensure_mod.LockBusy:
        raise AgentError("verrou d'ensure tenu : rien chargé (attente bornée par SSHVAULT_ENSURE_TIMEOUT, "
                         "--nointeraction)") from None
    finally:
        keys.clear()
    for i, blob, _ in done:
        opts = ", ".join(["durée " + describe_duration(lifetime)] + _options(args.confirm, False)
                         + (["restreinte à " + _hosts(i.hosts)] if args.restrict else []))
        print("%s : %s%s %s (%s)" % ("rechargée (retirée pendant l'attente)" if blob in back else "chargée",
                                     accts.prefix(i.account), clean(i.name), fingerprint(blob), opts))
    return rc_read


def _restrict_hosts(i: SshKeyItem) -> None:
    """--restrict : la clé a des hôtes, tous littéraux ; sinon AgentError (code 4, rien chargé)."""
    if not i.hosts:
        raise AgentError("--restrict : « %s » n'a aucun hôte associé : rien chargé" % clean(i.name))
    bad = [h for h in i.hosts if not literal_host(h)]
    if bad:
        raise AgentError("--restrict : hôte « %s » de « %s » non littéral (motif, user@, >, :port) : "
                         "rien chargé" % (clean(bad[0]), clean(i.name)))


def _accounts_still_open(accts: Accounts, aliases: list) -> None:
    """Sous ensure.lock, avant tout ajout de `load` : chaque compte toujours enregistré (même
    serveur, même e-mail), bw connecté et coffre déverrouillé, lu comme `status` (session rangée,
    sans invite). Sinon (logout, lock, account remove, rename ou set pendant l'attente) : VaultLocked
    (code 3), une ligne qui nomme le compte ; bw en erreur : son code."""
    now = accts.cfg.accounts()
    for a in aliases:
        try:
            why = _account_change(accts, a, now)
        except (VaultError, SessionStoreError) as e:
            code, msg = classify(e)
            raise (BackendError if code == RC_BACKEND else VaultLocked)(
                "compte « %s » : état relu sous le verrou d'ensure : %s : rien chargé" % (a, msg)) from None
        if why:
            raise VaultLocked("compte « %s » %s pendant l'attente du verrou d'ensure : rien chargé" % (a, why))


def _account_change(accts: Accounts, a: str, now: dict) -> Optional[str]:
    """Pourquoi le compte `a` n'est plus lisible sous ensure.lock (None : toujours enregistré à
    l'identique, bw connecté, coffre déverrouillé, lu comme `status`) ; bw en erreur : levée."""
    if a not in now:
        return "retiré ou renommé (account remove ou rename)"
    if now[a] != accts.registry.get(a):
        return "modifié (account set)"
    st = accts.backend(a).status()
    if st.state == "unauthenticated":
        return "déconnecté"
    if st.state != "unlocked":
        return "verrouillé"
    return None


def _account_gone(accts: Accounts, a: str) -> Optional[str]:
    """Comme `_accounts_still_open` pour une clé à recharger (`load`) : la raison de la sauter
    (compte changé pendant l'attente, ou bw en erreur), sans rien lever."""
    try:
        why = _account_change(accts, a, accts.cfg.accounts())
    except (VaultError, SessionStoreError) as e:
        return "compte « %s » : état relu sous le verrou d'ensure : %s" % (a, classify(e)[1])
    return "compte « %s » %s pendant l'attente du verrou d'ensure" % (a, why) if why else None


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
            print("  ?\t?\t%s\t?\t?" % k.fingerprint)
            continue
        left = remaining(e, now)
        print("  %s\t%s\t%s\t%s\t%s" % (clean(e.get("account") or "?"), clean(e["name"]), k.fingerprint,
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


def _ensure_lock(base: str, timeout: Optional[float] = None):
    """`ensure.lock` (celui d'`ensure --id`/`--forward`) si le dossier existe : un `ensure
    --forward` en cours finit avant l'arrêt des sous-agents, aucun ne les relance pendant. S'il
    est tenu, une ligne le dit avant d'attendre. `timeout` : attente bornée (LockBusy)."""
    import contextlib
    if not os.path.isdir(base):
        return contextlib.nullcontext()
    return ensure_mod.user_lock(base, on_wait=lambda: err("attente d'un chargement en cours (ensure)…"),
                                timeout=timeout)


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
                print("?\t?\t%s\t-\t?\t?" % fp)
                continue
            left = remaining(e, now)
            print("%s\t%s\t%s\t%s\t%s\t%s" % (clean(e.get("account") or "?"), clean(e["name"]), fp, _hosts(e["hosts"]),
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
        rc = RC_OK
        # lock : ensure.lock tenu de l'arrêt des sous-agents jusqu'à l'état « verrouillé »
        # enregistré : aucun `ensure --forward` ne les relance entre-temps ; unlock : liste, sonde
        # `ssh-add -D` et déverrouillage sous ensure.lock (la sonde ne vide jamais une clé qu'un
        # `ensure` parallèle viendrait de charger)
        with _ensure_lock(base):
            if cmd == "lock":
                # d'abord, quoi qu'il arrive ensuite : sous-agents vidés et arrêtés (rechargés par le
                # premier ssh après « agent unlock »)
                rc = _each_forward(base, lambda sub, label: _forward_stop(sub, label, purge=True))
            data = agent.running()
            keys = agent.keys()
            _sync_lock_flag(agent, data, keys)
            # aucune clé listée, état non marqué verrouillé : vide, ou verrouillé hors de sshvault
            # (`ssh-add -x`) ; la sonde `ssh-add -D` tranche
            if cmd == "unlock" and not data["locked"] and (keys or not agent.probe_locked()):
                if not keys and data["keys"]:
                    # agent prouvé vide (vidé à la main) : entrées d'état périmées retirées
                    agent.update(lambda d: d.update(keys={}))
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
                    if all(any(fastpath.owns(e, i, a) for a, i in ids) for e in sub.state.load()["keys"].values()):
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

def _select_one(items: list, args, forward: bool = False, multi: bool = False,
                account: Optional[str] = None) -> Optional[SshKeyItem]:
    """L'élément désigné par la sélection ; None (message dit) si aucun ; UsageError si plusieurs.
    `forward` : `--host` et la sélection par défaut couvrent aussi les motifs de transfert.
    `multi` : plusieurs comptes (l'alias est dit, --account suggéré)."""
    if not args.pattern.strip():
        raise UsageError("sélection vide")
    found = [i for i in items if match(i, args.pattern, args.by)
             or (forward and args.by in (None, "host") and i.match_forward(args.pattern))]
    if not found:
        if account:  # écriture, plusieurs comptes : dire où l'on a cherché
            err("aucune clé ne correspond à « %s » dans le compte %s (autre compte : --account ALIAS)"
                % (args.pattern, account))
        else:
            err("aucune clé ne correspond à « %s »" % args.pattern)
        return None
    if len(found) > 1:
        accounts = {i.account for i in found}
        raise UsageError("« %s » désigne %d éléments (%s) : préciser --id%s"
                         % (args.pattern, len(found),
                            ", ".join("%s%s %s" % ("%s " % i.account if multi and i.account else "", clean(i.name), i.id)
                                      for i in found),
                            " et --account" if multi and len(accounts) > 1 else ""))
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


class Sources:
    """Éléments de tous les comptes pour une régénération : `items` (relus dans le coffre, ou
    gardés tels quels du fichier actuel pour un compte illisible), `kept` ((compte, id) gardés),
    `notes` (avertissements : comptes illisibles), `read` (comptes lus)."""

    def __init__(self):
        self.items, self.kept, self.notes, self.read, self.unreadable = [], frozenset(), [], [], []
        #: éléments identifiant (CAP-11) de tous les comptes (gardés du fichier pour un compte illisible)
        self.logins: list = []
        self.errors: dict = {}  # alias illisible -> erreur
        self.rc = RC_OK  # pire code des comptes illisibles


def gather(accts: Accounts, paths, fresh: dict, prompt, renamed: Optional[dict] = None,
           fresh_logins: Optional[dict] = None) -> Sources:
    """Sources d'une régénération (CAP-10 : toujours tous les comptes) : `fresh` {alias :
    éléments déjà lus} ; les autres comptes lus avec `prompt` (None : sans invite). Un compte
    illisible (verrouillé sans invite possible, non connecté, bw en erreur) garde ses blocs
    actuels, relus dans le fichier généré, avec un avertissement ; un bloc d'ancienne forme (sans
    compte) n'est gardé que si un compte est illisible et que son élément n'a pas été relu.
    Éléments identifiant : `fresh_logins` {alias : éléments} pris tels quels ; sinon ceux de la
    même lecture du coffre (aucun appel de plus), relus sans invite au besoin ; illisibles : blocs
    à mot de passe gardés du fichier."""
    src = Sources()
    fresh_logins = fresh_logins or {}
    no_logins = []  # comptes lus dont les éléments identifiant n'ont pu l'être

    def logins_of(a):
        if a in fresh_logins:
            src.logins.extend(fresh_logins[a])
            return
        try:
            src.logins.extend(tag(a, accts.backend(a).list_logins(None)))
        except (VaultError, SessionStoreError, ConfigError):
            no_logins.append(a)
    for a in accts.registry:
        if a in fresh:
            src.items += fresh[a]
            src.read.append(a)
            logins_of(a)
            continue
        try:
            src.items += tag(a, accts.backend(a).list_ssh_keys(prompt))
            src.read.append(a)
            logins_of(a)
        except (VaultError, SessionStoreError, ConfigError) as e:  # ConfigError : bw-path invalide
            src.unreadable.append(a)
            src.errors[a] = e
            src.rc = max(src.rc, classify(e)[0])
            if isinstance(e, NotLoggedIn):  # une seule forme de login dans la ligne
                src.notes.append("compte %s non connecté : ses blocs du ssh_config sont gardés tels quels (« sshvault "
                                 "login --account %s » puis « sshvault ssh-config »)" % (a, a))
            else:
                src.notes.append("compte %s illisible (%s) : ses blocs du ssh_config sont gardés tels quels (« sshvault "
                                 "unlock%s » puis « sshvault ssh-config »)" % (a, e, accts.hint(a)))
    if src.unreadable:
        bad = set(src.unreadable)
        have = {i.id.lower() for i in src.items}
        known = set(accts.registry) | set(renamed or ())
        kept = [i for i in sshconfig.kept_items(paths, lambda a: a in bad or a is None, renamed, known, src.notes)
                if i.account is not None or i.id not in have]
        src.items += kept
        src.kept = frozenset((i.account, i.id) for i in kept)
    bad_logins = set(src.unreadable) | set(no_logins)
    if bad_logins:
        kept_l = sshconfig.kept_logins(paths, lambda a: a in bad_logins, renamed)
        src.logins += kept_l
        src.kept |= frozenset((i.account, i.id) for i in kept_l)
    return src


def password_exe(paths, logins, exe: Optional[str]) -> Optional[str]:
    """Chemin de sshvault des lignes `ensure --password` (CAP-11) : celui des clés, sinon (auto-load
    false) résolu ici ; None sans élément identifiant à hôte."""
    if not any(i.hosts for i in logins):
        return None
    if exe is not None:
        return exe
    exe = sshconfig.sshvault_exe()
    for w in sshconfig.exe_warnings(exe, paths):
        err("avertissement : %s" % w)
    return exe


def regenerate(items: list, paths=None, socket: Optional[str] = None, exe=_RESOLVE, out=None,
               skip_catch_all: bool = False, kept: frozenset = frozenset(), notes=(), logins=(),
               pw_exe=_RESOLVE) -> None:
    """Réécrit ce qui a changé dans ~/.ssh/sshvault/ ; avertissements sur stderr, compte rendu
    sur `out` (défaut stdout ; stderr pour generate, dont stdout ne porte que la clé publique)."""
    paths = paths or sshconfig.default_paths()
    socket = socket or make_agent().socket
    for w in notes:
        err("avertissement : %s" % w)
    exe = ensure_exe(paths) if exe is _RESOLVE else exe
    pw_exe = password_exe(paths, logins, exe) if pw_exe is _RESOLVE else pw_exe
    plan = sshconfig.build(items, paths, socket, exe, kept, logins, pw_exe)
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
    for w in sshconfig.include_warnings(paths):
        err("avertissement : %s" % w)
    forward_upkeep(plan, socket, out)
    return plan


def run_hosts(args, accts: Accounts, prompt) -> int:
    """`hosts` (champ sshvault-hosts) et `forward` (champ sshvault-forward) : mêmes règles. `list`
    lit les comptes par défaut (ou --account) ; une écriture vise un seul compte."""
    fwd = args.cmd == "forward"
    of = (lambda i: i.forward) if fwd else (lambda i: i.hosts)
    what, one = ("transferts", "le transfert vers") if fwd else ("hôtes", "l'hôte")
    cmd = args.hosts_cmd
    if cmd == "list":
        if not args.pattern.strip():
            raise UsageError("sélection vide")
        items, rc = collect(accts, accts.read_set(args.account), prompt)
        item = _select_one(items, args, forward=fwd, multi=accts.multi)
        if item is None:
            return max(rc, RC_NONE)
        for h in of(item):
            print(clean(h))
        return rc
    given = _split(args.hosts)
    if cmd in ("add", "set"):
        new = normalize_hosts(given)  # InvalidHost (code 2) avant tout accès au coffre
        if cmd == "add" and not new:
            raise UsageError("aucun hôte à ajouter")
    elif not given:
        raise UsageError("aucun hôte à retirer")
    if not args.pattern.strip():
        raise UsageError("sélection vide")
    alias = accts.write_one(args.account, "%s %s" % (args.cmd, cmd))  # code 2 avant tout accès
    backend = accts.backend(alias)
    # écriture : partir de l'état du serveur, pas d'un cache local périmé (interface web)
    backend.sync(prompt)
    mine = tag(alias, backend.list_ssh_keys(prompt))
    item = _select_one(mine, args, forward=fwd, account=alias if accts.multi else None)
    if item is None:
        return RC_NONE
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
        raise InvalidHost("hôte invalide « %s » déjà dans « %s » : le retirer (%s remove%s) ou remplacer la liste "
                          "(%s set%s) ; rien écrit" % (clean(bad[0]), clean(item.name), args.cmd, accts.hint(alias),
                                                       args.cmd, accts.hint(alias)))
    # Prérequis de la régénération (chemins, socket de l'agent) vérifiés avant d'écrire
    # dans le coffre : SshConfigError ou AgentError ici, rien n'est écrit. Les autres comptes
    # sont lus sans invite (verrouillés : leurs blocs actuels gardés).
    paths = sshconfig.default_paths()
    socket = make_agent().socket
    exe = ensure_exe(paths)
    src = gather(accts, paths, {alias: mine}, None)
    pw_exe = password_exe(paths, src.logins, exe)
    sshconfig.build(src.items, paths, socket, exe, src.kept, src.logins, pw_exe)
    if want == current:
        print("%s de « %s » inchangés : %s" % (what, clean(item.name), _hosts(of(item))))
        updated = item
    else:
        for h in want:
            if sshconfig.is_catch_all(h):
                err("avertissement : motif « %s » : %s"
                    % (h, sshconfig.FORWARD_CATCH_ALL_WARNING if fwd else sshconfig.CATCH_ALL_WARNING))
        updated = (backend.set_forward if fwd else backend.set_hosts)(item.id, want, prompt)
        updated = tag(alias, [updated])[0]
        print("%s de « %s » : %s" % (what, clean(updated.name), _hosts(of(updated))))
        if not fwd:
            _warn_restricted(updated, accts)
    items = [updated if (i.account, i.id) == (updated.account, updated.id) else i for i in src.items]
    try:
        regenerate(items, paths, socket, exe, skip_catch_all=fwd, kept=src.kept, notes=src.notes, logins=src.logins,
                   pw_exe=pw_exe)
    except (sshconfig.SshConfigError, AgentError) as e:
        err("%s écrits dans le coffre, mais ssh_config non régénéré : %s" % (what, e))
        return RC_BACKEND
    return RC_OK


def _warn_restricted(item: SshKeyItem, accts: Accounts) -> None:
    """Clé de l'élément chargée avec --restrict : ses contraintes -h gardent les anciens hôtes."""
    try:
        keys = make_agent().state.load()["keys"]
    except Exception:
        return
    if any(e.get("id") == item.id and e.get("account") in (None, item.account) and e.get("restrict")
           for e in keys.values()):
        err("avertissement : clé « %s » chargée avec --restrict : elle reste limitée aux anciens hôtes ; relancer "
            "« sshvault load --force --restrict%s --id %s »" % (clean(item.name), accts.hint(item.account), item.id))


def run_ssh_config(args, accts: Accounts, prompt) -> int:
    """Régénération à partir des éléments de **tous** les comptes (une invite au plus par compte
    verrouillé) ; un compte illisible garde ses blocs actuels (avertissement). Tous illisibles :
    erreur, rien écrit."""
    if args.action in ("install", "uninstall") and (args.print_only or args.check):
        raise UsageError("%s exclut --print et --check" % args.action)
    paths = sshconfig.default_paths()
    if args.action == "install":
        res = sshconfig.install(paths)
        print(res.message)
        for w in res.warnings:
            err("avertissement : %s" % w)
        if not os.path.exists(paths.config):
            err("avertissement : %s n'existe pas encore : lancer « sshvault ssh-config »" % paths.config)
        return RC_OK
    if args.action == "uninstall":
        # ni coffre ni agent : seuls ~/.ssh/config et ce qu'écrit la régénération
        res = sshconfig.uninstall(paths)
        for w in res.warnings:
            err("avertissement : %s" % w)
        for line in res.done:
            print(line)
        if not res.done:
            print("rien d'autre à faire" if res.kept or res.warnings
                  else "rien à faire : sshvault n'est pas installé dans %s" % paths.ssh_dir)
            return RC_OK
        if res.kept:
            print("ligne%s Include gardée%s : %s inclu%s toujours %s ; la prochaine régénération (hosts, forward, "
                  "import, generate, ssh-config) rendra sshvault de nouveau actif"
                  % ("s" if len(res.kept) > 1 else "", "s" if len(res.kept) > 1 else "",
                     "elles" if len(res.kept) > 1 else "elle", "ent" if len(res.kept) > 1 else "t", paths.config))
        else:
            print("ssh n'utilise plus sshvault ; agents, comptes, sessions et données de bw gardés ; réinstaller : "
                  "« sshvault ssh-config » puis « sshvault ssh-config install »")
        return RC_OK
    if not accts.registry:
        # jamais de config régénérée sans compte : elle perdrait tous les blocs (installation
        # 0.8.0 pas encore adoptée, par exemple)
        pending = pending_message(accts.cfg, "ssh_config non régénéré, rien écrit")
        if pending:
            raise NoAccount(pending)
        raise NoAccount("aucun compte du coffre : ssh_config non régénéré, rien écrit (« sshvault account add ALIAS "
                        "--server URL --email E »)")
    # --check d'une config générée : un compte **déconnecté** (bw non connecté, après `logout`)
    # garde ses blocs tels quels, même s'il est seul : « à jour » si le fichier correspond. Un
    # compte verrouillé ou un bw en erreur garde la règle d'avant (seul : son code ; tous
    # illisibles : le pire code)
    keep_out = args.check and os.path.exists(paths.config)
    if len(accts.registry) == 1 and not keep_out:
        a = next(iter(accts.registry))
        src = gather(accts, paths, {a: tag(a, accts.backend(a).list_ssh_keys(prompt))}, prompt)
    else:
        src = gather(accts, paths, {}, prompt)
        others = [a for a in src.unreadable if not (keep_out and isinstance(src.errors[a], NotLoggedIn))]
        if len(accts.registry) == 1 and others:
            raise src.errors[others[0]]  # seul compte, pas déconnecté : son erreur, comme avant
        if accts.registry and not src.read and others:
            for w in src.notes:
                err(w)
            raise _Reported(src.rc)
    items = src.items
    for w in sshconfig.login_warnings(src.logins):
        err("avertissement : %s" % w)
    if not (args.print_only or args.check):
        warn_forwardagent(items, regenerate(items, paths, kept=src.kept, notes=src.notes, logins=src.logins), paths)
        return RC_OK
    for w in src.notes:
        err("avertissement : %s" % w)
    exe = ensure_exe(paths)
    plan = sshconfig.build(items, paths, make_agent().socket, exe, src.kept, src.logins,
                           password_exe(paths, src.logins, exe))
    for w in plan.warnings:
        err("avertissement : %s" % w)
    if args.print_only:
        sys.stdout.write(plan.config.decode())
        return RC_OK
    diffs, notes = sshconfig.check(plan, paths)
    for w in notes:
        err("avertissement : %s" % w)
    warn_forwardagent(items, plan, paths)
    diffs += sshconfig.include_warnings(paths)
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


def _import_one(args, backend: VaultBackend, prompt, kf, hosts, items: list, extra, alias: str,
                hint: str = "") -> Optional[SshKeyItem]:
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
        hint = ("pour lui associer les hôtes : « sshvault hosts add%s --id %s %s » ; --force pour créer un second "
                "élément" % (hint, same[0].id, ",".join(hosts)) if hosts else "--force pour l'importer quand même")
        err("%s : déjà dans le coffre (%s) : %s ; %s"
            % (label, fp, ", ".join("« %s » %s" % (clean(i.name), i.id) for i in same), hint))
        return None
    if args.decrypt and kf.encrypted:
        kf = keyfile.decrypt(kf, _passphrase_mode(args), notice=_notice(label))
    name = args.name.strip() if args.name is not None else kf.default_name()
    item = backend.create_ssh_key(name, kf.data.decode("ascii"), kf.public_key, fp, hosts, prompt,
                                  existing=[i.id for i in same], extra_fields=extra)
    item = tag(alias, [item])[0]
    print("importée : %s (%s)%s" % (clean(item.name), fp, " dans %s" % alias if hint else ""))
    if kf.encrypted:
        err("avertissement : « %s » stockée chiffrée par sa passphrase : demandée à chaque chargement, et "
            "inutilisable par l'agent de Bitwarden Desktop, peut-être par d'autres clients Bitwarden "
            "(--decrypt : stockée déchiffrée)" % clean(item.name))
    return item


def run_import(args, accts: Accounts, prompt) -> int:
    """Chaque fichier traité à part (une ligne de résultat chacun) ; code : le pire rencontré.
    Un seul compte écrit (--account, sinon le compte par défaut s'il est unique)."""
    if args.name is not None:
        if not args.name.strip():
            raise UsageError("--name vide")
        if len(args.files) > 1:
            raise UsageError("--name ne vaut que pour un seul FICHIER")
    hosts = normalize_hosts(_split(args.hosts))  # InvalidHost (code 2) avant tout accès
    extra = _test_fields()
    alias = accts.write_one(args.account, "import")  # code 2 avant tout accès
    backend = accts.backend(alias)
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
        items = tag(alias, backend.list_ssh_keys(prompt))
        if hosts:
            src = gather(accts, paths, {alias: items}, None)
            pw_exe = password_exe(paths, src.logins, exe)
            sshconfig.build(src.items, paths, socket, exe, src.kept, src.logins, pw_exe)
    except Exception as e:  # le pire code reste, avec les refus déjà dits
        failed(None, e)
        return worst
    created = []
    try:
        for kf in todo:
            try:
                item = _import_one(args, backend, prompt, kf, hosts, items, extra, alias, accts.hint(alias))
            except Exception as e:
                failed(kf.path, e)
                continue
            if item is None:
                worst = max(worst, RC_NONE)
                continue
            items.append(item)
            created.append(item)
            if hosts:
                src.items.append(item)
    except BaseException:
        # Ctrl-C, SIGTERM… : les éléments déjà créés restent ; la config n'est pas régénérée
        if hosts and created:
            err("clés créées : %s ; ssh_config non régénéré : lancer « sshvault ssh-config »"
                % ", ".join("« %s » %s" % (clean(i.name), i.id) for i in created))
        raise
    if hosts and created:
        try:
            regenerate(src.items, paths, socket, exe, kept=src.kept, notes=src.notes, logins=src.logins, pw_exe=pw_exe)
        except (sshconfig.SshConfigError, AgentError) as e:
            err("clé importée dans le coffre, mais ssh_config non régénéré : %s" % e)
            worst = max(worst, RC_BACKEND)
    return worst


# --- génération d'une clé dans le coffre (story 7) -----------------------------------------------

def run_generate(args, accts: Accounts, prompt) -> int:
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
    alias = accts.write_one(args.account, "generate")  # code 2 avant tout accès
    backend = accts.backend(alias)
    # Prérequis, avant tout accès au coffre : tmpfs privé et son dossier sshvault/ (code 4),
    # puis chemins, socket et sshvault du ssh_config (contrôle sans éléments : build([])).
    keyfile.check_workspace()
    if hosts:
        paths = sshconfig.default_paths()
        socket = make_agent().socket
        exe = ensure_exe(paths)
        sshconfig.build([], paths, socket, exe)
    backend.sync(prompt)  # nom déjà pris : état du serveur, pas un cache local périmé
    items = tag(alias, backend.list_ssh_keys(prompt))
    taken = [i for i in items if i.name.strip().casefold() == name.casefold()]
    if taken and not args.force:
        err("nom « %s » déjà pris par %s : rien généré ; --force pour créer quand même un élément de ce nom"
            % (clean(name), ", ".join("« %s » %s" % (clean(i.name), clean(i.id)) for i in taken)))
        return RC_NONE
    if hosts:
        src = gather(accts, paths, {alias: items}, None)
        pw_exe = password_exe(paths, src.logins, exe)
        sshconfig.build(src.items, paths, socket, exe, src.kept, src.logins, pw_exe)
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
                          "coffre, elle est perdue (relancer « sshvault generate%s »)" % (e, accts.hint(alias))) from None
    public, fp = gen.public_key, gen.fingerprint
    del gen
    item = tag(alias, [item])[0]
    regenerated = False
    try:
        print(public, flush=True)
        err("clé %s générée dans le coffre%s : « %s » %s (id %s)"
            % ("Ed25519" if key_type == "ssh-ed25519" else "RSA %d" % bits,
               " %s" % alias if accts.multi else "", clean(item.name), fp, clean(item.id)))
        if hosts:
            try:
                regenerate(src.items + [item], paths, socket, exe, out=sys.stderr, skip_catch_all=True, kept=src.kept,
                           notes=src.notes, logins=src.logins, pw_exe=pw_exe)
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

def _public_lines(args, accts: Accounts, prompt, allow_all: bool):
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
    items, rc = collect(accts, accts.read_set(args.account), prompt)
    found = [i for i in items if every or match(i, args.pattern, args.by)]
    if not found:
        err("aucune clé ne correspond à « %s »" % clean(args.pattern) if args.pattern is not None
            else "aucune clé SSH dans le coffre")
        return None, None, max(rc, RC_NONE)
    out, seen = [], set()
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


def run_pubkey(args, accts: Accounts, prompt) -> int:
    """Une ligne de clé publique par clé sélectionnée, rien d'autre sur stdout. Lecture du
    cache local de bw (list items) : aucun appel réseau."""
    items, lines, rc = _public_lines(args, accts, prompt, allow_all=True)
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


def run_deploy(args, accts: Accounts, prompt) -> int:
    """Un seul `ssh` vers la cible pour toutes les clés sélectionnées (voir deploy.py) ; une
    ligne par clé sur stdout : « ajoutée » ou « déjà présente »."""
    deploy_mod.check_target(args.target)  # BadTarget (code 2) avant tout accès
    port = deploy_mod.check_port(args.port) if args.port is not None else None
    options = list(getattr(args, "ssh_options", []) or [])
    check_ssh_options(options)
    if args.nointeraction:
        options = ["-o", "BatchMode=yes"] + options  # première valeur lue : elle l'emporte
    items, lines, rc = _public_lines(args, accts, prompt, allow_all=False)
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


def configured_bw_path():
    """Réglage `bw-path` seul (None : non posé), lu par BwBackend au premier appel de bw
    seulement ; les autres réglages, même invalides, n'y changent rien."""
    return Config().bw_path()


def run_config(args) -> int:
    cfg = Config()
    if args.config_cmd == "get":
        for line in cfg.lines(args.key):
            print(line)
    elif args.config_cmd in ("set", "unset"):
        before = cfg.get(args.key) if args.key == "forward-confirm" else None
        if args.config_cmd == "set":
            v = cfg.set(args.key, args.value)
            warning = exposure_warning(v, args.key) if args.key in PATH_KEYS else None
            if warning:
                err(warning)  # accepté (choix de l'utilisateur), mais dit
        else:
            cfg.unset(args.key)
        print(cfg.lines(args.key)[0])
        if args.key == "auto-load":
            print("pris en compte à la prochaine génération : lancer « sshvault ssh-config »")
        elif args.key == BW_PATH and os.environ.get(BW_EXE_VAR):
            print("%s est posé : %s" % (BW_EXE_VAR, "il reste prioritaire sur " + BW_PATH
                                         if args.config_cmd == "set" else "il reste utilisé"))
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


#: Lectures de l'ancienne forme d'`ensure` dans ce processus : ("status" | "ids", alias) -> résultat.
_LEGACY_CACHE: dict = {}


def _legacy_account(item_id: str, accts: Accounts) -> str:
    """Compte d'un élément désigné par son seul id (ligne `Match exec` d'une config générée par la
    0.8.0, avant régénération) : le seul compte ; sinon l'état de l'agent (entrée ou référence
    `also` qui porte ce compte) ; sinon les comptes déverrouillés, lus sans invite (une fois par
    compte et par processus) ; sinon le seul compte connecté verrouillé. Introuvable : une ligne."""
    names = list(accts.registry)
    if not names:
        raise NoAccount("aucun compte du coffre : %s" % "« sshvault account add ALIAS --server URL --email E »")
    if len(names) == 1:
        return names[0]
    try:
        for e in make_agent().state.load()["keys"].values():
            if e["id"].lower() == item_id and e.get("account") in accts.registry:
                return e["account"]
            for x in e.get("also") or []:
                if isinstance(x, str):
                    a, i = fastpath._pair(x)
                    if i == item_id and a in accts.registry:
                        return a
    except Exception:
        pass
    locked = []
    for a in names:
        b = accts.backend(a)
        try:
            has = b.store.get()
        except SessionStoreError:
            has = None
        if not has:
            if ("status", a) not in _LEGACY_CACHE:
                try:
                    _LEGACY_CACHE["status", a] = b.status().state
                except (VaultError, SessionStoreError, ConfigError):
                    _LEGACY_CACHE["status", a] = "error"
            st = _LEGACY_CACHE["status", a]
            if st in ("unauthenticated", "error"):
                continue  # non connecté ou bw en erreur : ni lu, ni candidat « seul verrouillé »
            if st != "unlocked":
                locked.append(a)
                continue
        if ("ids", a) not in _LEGACY_CACHE:
            try:
                _LEGACY_CACHE["ids", a] = {i.id.lower() for i in b.list_ssh_keys(None)}
            except (VaultError, SessionStoreError, ConfigError):
                _LEGACY_CACHE["ids", a] = None
        ids = _LEGACY_CACHE["ids", a]
        if ids is None:
            continue  # lecture en erreur : pas candidat
        if item_id in ids:
            return a
    if len(locked) == 1:
        return locked[0]
    raise ItemNotFound("élément %s introuvable dans les comptes déverrouillés%s : lancer « sshvault "
                       "ssh-config » (config générée par une version précédente)"
                       % (item_id, " (verrouillés : %s)" % ", ".join(locked) if locked else ""))


def _check_password_args(args, refs, fids) -> None:
    """`ensure --password --account ALIAS --id UUID --host HÔTE` : chacun une fois, sans --forward."""
    from .backend import LOGIN_HOST_RE
    if not args.password:
        raise UsageError("--host : seulement avec --password")
    if fids:
        raise UsageError("--password exclut --forward")
    if len(args.account or []) != 1 or len(refs) != 1 or refs[0] is None or refs[0][0] is not None:
        raise UsageError("--password : --account ALIAS et une --id <UUID>, une fois chacun")
    if len(args.host or []) != 1 or not LOGIN_HOST_RE.fullmatch(args.host[0] or ""):
        raise UsageError("--password : --host HÔTE, une fois (lettres, chiffres, « . », « - », « _ »)")


def run_ensure(args) -> int:
    """`ensure --account ALIAS --id ID` (ou `--forward FID --id ALIAS:ID…`) : silencieux en cas de
    succès (sauf avertissements du backend, une ligne chacun) ; sinon une ligne `sshvault: <hôte
    ou id> : <cause>`. Ancienne forme sans compte (`--id ID`) : compte cherché par l'id. Jamais
    de lecture de stdin ni de traceback ; délai global borné (compté depuis le démarrage du
    processus) ; terminal restauré et sous-processus tués sur tout chemin (finally des couches
    basses), y compris Ctrl-C, SIGTERM, SIGHUP et le délai global."""
    reset_process_state()
    _ACCOUNTS_SEEN.clear()
    _LEGACY_CACHE.clear()
    accounts_mod.DEFERRED.clear()
    refs = [fastpath.parse_ref(i) for i in args.id]
    raw0 = (args.id[0] or "").strip().lower()
    item_id = refs[0][1] if refs[0] else raw0
    fids = args.forward or []
    fid = fids[0] if fids else None
    label = clean(item_id) or "?"
    what = "transfert d'agent : " if fid is not None else ""
    accts = None
    try:
        c = fastpath.caller()
        if c.no_connect:
            return RC_OK  # ssh -G, ssh -O : lecture de la config, aucune connexion
        label = c.host or label
        # Jamais arrêté par le terminal : en arrière-plan, une lecture ou un réglage de /dev/tty
        # échoue (EIO) au lieu de stopper le processus (aucune n'est tentée : premier plan vérifié).
        for sig in (signal.SIGTTIN, signal.SIGTTOU):
            signal.signal(sig, signal.SIG_IGN)
        if args.password or args.host:
            _check_password_args(args, refs, fids)
        if any(r is None for r in refs):
            raise UsageError("--id : UUID attendu (ou <alias>:<UUID> avec --forward)")
        if fid is None and len(refs) != 1:
            raise UsageError("une seule --id sans --forward")
        if len(fids) > 1:
            raise UsageError("--forward : une seule fois")
        if fid is not None and not FID_RE.fullmatch(fid):
            raise UsageError("--forward : 16 chiffres hexadécimaux attendus")
        accounts_arg = args.account or []
        if len(accounts_arg) > 1 or (accounts_arg and (fid is not None or refs[0][0] is not None)):
            raise UsageError("--account : une fois, avec une seule --id <UUID>, sans --forward")
        if accounts_arg:
            check_alias(accounts_arg[0])
            refs = [(accounts_arg[0], refs[0][1])]
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
        if args.password:
            label = args.host[0].lower()  # hôte tapé, celui du bloc (la destination de ssh peut être un saut)
        ctx = ensure_mod.Context(conn=c.conn, host=label if args.password else c.host, interactive=not why, why_not=why,
                                 deadline_at=time.monotonic() + left)
        settings = _ensure_settings()

        def warn(text, label=label):
            try:
                err("%s : %s" % (label, text))
            except (OSError, ValueError):
                pass
        cfg = Config()
        adopt_legacy(cfg, warn, configured_bw_path, warn)
        accts = Accounts(cfg, configured_bw_path, warn)
        refs = [(a if a is not None else _legacy_account(i, accts), i) for a, i in refs]
        for a, _ in refs:
            accts.check(a)
        if args.password:
            a, i = refs[0]
            b = accts.backend(a)
            ensure_mod.ensure_password(a, i, args.host[0].lower(), b, b.store, ctx=ctx, nearest=c.nearest)
        elif fid is not None:
            accounts = {a: (accts.backend(a), accts.backend(a).store) for a, _ in refs}
            ensure_mod.ensure_forward(fid, refs, None, None, settings, ctx=ctx, accounts=accounts)
        else:
            a, i = refs[0]
            b = accts.backend(a)
            ensure_mod.ensure(i, b, b.store, settings, ctx=ctx, account=a)
        _quiet()  # clé présente ou chargée : un délai ou un signal tardif n'y change plus rien
        rc = RC_OK
    except (Exception, KeyboardInterrupt, Interrupted, Deadline) as e:
        _quiet()
        rc, msg = classify(e)
        try:
            err("%s : %s%s" % (label, what, msg))
        except (OSError, ValueError):
            pass
        if getattr(args, "password", False) and rc != RC_USAGE:
            rc = RC_OK  # ligne sans directive : l'échec est dit, ssh continue (l'askpass relaiera)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    for a, b in (accts.backends() if accts is not None else []):
        for w in b.warnings:
            try:
                err("%s : %s%s" % (label, accts.prefix(a), w))
            except (OSError, ValueError):
                pass
    return rc


def classify(e: BaseException):
    """(code de sortie, message d'une ligne) d'une erreur."""
    if isinstance(e, _Reported):
        return e.rc, ""
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
    if isinstance(e, NoAccount):
        return RC_LOCKED, str(e)
    if isinstance(e, (AdoptError, AccountIOError)):
        return RC_BACKEND, str(e)
    if isinstance(e, (InvalidHost, ConfigError, keyfile.KeyRefused, deploy_mod.BadTarget, AccountError)):
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


def _without_vault(args) -> bool:
    """Commandes qui ne lisent ni n'écrivent aucun compte : une adoption 0.8.0 impossible ne les
    bloque pas (avertissement)."""
    return (args.cmd in ("config", "agent") or (args.cmd == "account" and args.account_cmd == "list")
            or (args.cmd == "ssh-config" and args.action in ("install", "uninstall")))


def main(argv=None) -> int:
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _on_signal)
    reset_process_state()
    _ACCOUNTS_SEEN.clear()
    _LEGACY_CACHE.clear()
    accounts_mod.DEFERRED.clear()
    accts = None
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
        cfg = Config()
        try:
            adopt_legacy(cfg, err, configured_bw_path, err)
        except AdoptError as e:
            if not _without_vault(args):
                raise
            err("avertissement : %s" % e)  # commande qui ne touche pas au coffre : elle se fait
        accts = Accounts(cfg, configured_bw_path, err)
        rc = run(args, accts)
    except BrokenPipeError:
        # sortie fermée (sshvault list | head) : rien à dire
        _stdout_to_devnull()
        rc = RC_OK
    except (Exception, KeyboardInterrupt, Interrupted, Deadline) as e:  # filet : jamais de traceback
        rc, msg = classify(e)
        if msg:
            err(msg)
    for ac in ([accts] if accts is not None else []) + _ACCOUNTS_SEEN:
        for a, b in ac.backends():
            for w in b.warnings:
                err("%s%s" % (ac.prefix(a), w))
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

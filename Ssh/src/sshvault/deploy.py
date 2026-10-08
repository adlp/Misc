"""`sshvault deploy` : ajoute des clés publiques à `~/.ssh/authorized_keys` d'une cible, par un
seul `ssh` (story 7).

- `ssh` est lancé en liste d'arguments, sans shell local : options de l'utilisateur, `-p PORT`,
  `--`, puis la cible `[user@]hôte` (validée : rien qu'un shell, ou un `%h`/`%r` d'un
  `ProxyCommand` de l'utilisateur, puisse interpréter), puis la commande distante.
- La commande distante est **fixe** (`REMOTE_COMMAND`) : `exec sh -c '<script POSIX>'`, sans
  aucune donnée de l'utilisateur. Le script est d'une seule ligne, sans apostrophe : il passe
  tel quel par le shell de connexion distant (sh, bash, zsh, fish, csh).
- Les clés publiques (une ligne `type base64 [commentaire]` chacune) vont sur **stdin**.
- Le script, sous `umask 077` : crée `~/.ssh` (0700) s'il manque, n'ajoute une ligne à
  `authorized_keys` (créé en 0600) que si la clé (type + base64) n'y est pas déjà, hors lignes
  de commentaire ; répond une ligne `sshvault-deploy added|present` par clé, dans l'ordre.
  Idempotent : un second passage n'écrit rien.
- L'authentification vers la cible est celle de `ssh` (agent, clés, mot de passe sur le terminal).
"""
from __future__ import annotations

import base64
import ipaddress
import os
import re
import signal
import subprocess
from typing import Optional

from .keyfile import describe_blob
from .settings import seconds

SCRIPT = (
    "umask 077 || exit 1; "
    "cd || { echo \"sshvault-deploy: HOME inaccessible\" >&2; exit 1; }; "
    "[ -d .ssh ] || mkdir .ssh || exit 1; "
    "f=.ssh/authorized_keys; lk=.ssh/.sshvault-deploy.lock; i=0; "
    "until mkdir \"$lk\" 2>/dev/null; do "
    "i=$((i+1)); "
    "if [ \"$i\" -ge 10 ]; then echo \"sshvault-deploy: verrou $HOME/$lk tenu (à supprimer si aucun deploy "
    "ne tourne)\" >&2; exit 1; fi; "
    "sleep 1; "
    "done; "
    "trap \"rmdir $lk 2>/dev/null\" 0; trap \"exit 1\" 1 2 15; "
    "cr=$(printf \"\\r\"); "
    "set -f; "
    "while IFS= read -r line || [ -n \"$line\" ]; do "
    "set -- $line; t=${1-}; b=${2-}; "
    "case $t in ssh-?*|ecdsa-?*|sk-?*) ;; "
    "*) echo \"sshvault-deploy: ligne de clé illisible\" >&2; exit 1;; esac; "
    "if [ -z \"$b\" ] || [ -n \"$(printf \"%s\" \"$b\" | tr -d \"A-Za-z0-9+/=\")\" ]; then "
    "echo \"sshvault-deploy: ligne de clé illisible\" >&2; exit 1; fi; "
    "found=; "
    "if [ -f \"$f\" ]; then "
    "while IFS= read -r l || [ -n \"$l\" ]; do "
    "l=${l%\"$cr\"}; "
    "set -- $l; "
    "case ${1-} in \"#\"*) continue;; esac; "
    "n=$#; "
    "while [ $# -ge 2 ]; do "
    "if [ \"$1\" = \"$t\" ] && [ \"$2\" = \"$b\" ]; then "
    "if [ $# -eq $n ]; then found=plain; else found=${found:-options}; fi; break; fi; "
    "shift; "
    "done; "
    "if [ \"$found\" = plain ]; then break; fi; "
    "done < \"$f\"; "
    "fi; "
    "if [ \"$found\" = plain ]; then echo \"sshvault-deploy present\"; continue; fi; "
    "if [ -n \"$found\" ]; then echo \"sshvault-deploy present-options\"; continue; fi; "
    "if [ -s \"$f\" ] && [ -n \"$(tail -c 1 \"$f\")\" ]; then echo >> \"$f\" || exit 1; fi; "
    "printf \"%s\\n\" \"$line\" >> \"$f\" || exit 1; "
    "echo \"sshvault-deploy added\"; "
    "done; "
    "if command -v restorecon >/dev/null 2>&1; then restorecon -F .ssh \"$f\" >/dev/null 2>&1 || :; fi"
)
assert "'" not in SCRIPT and "\n" not in SCRIPT and "!" not in SCRIPT
REMOTE_COMMAND = "exec sh -c '%s'" % SCRIPT

ANSWER = re.compile(r"sshvault-deploy (added|present|present-options)")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Cible : `[user@]hôte` sans rien qu'un shell ou un ProxyCommand (%h, %r) puisse interpréter
# (OpenSSH 9.6 refuse de même les métacaractères dans le nom d'hôte ; 8.9 ne le fait pas).
_USER = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._-]*", re.ASCII)
_HOST = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*", re.ASCII)
_KEY_TYPE = re.compile(r"(?:ssh-|ecdsa-|sk-)[A-Za-z0-9@._+-]+", re.ASCII)
CONNECT_TIMEOUT = 30
DEFAULT_TIMEOUT = 120.0
TIMEOUT_VAR = "SSHVAULT_DEPLOY_TIMEOUT"


class DeployError(Exception):
    """`ssh` absent, en échec, sans réponse, ou réponse inattendue de la cible (code 4).
    `answers` : réponses déjà reçues (clés traitées avant l'échec), dans l'ordre."""

    def __init__(self, msg: str, answers=()):
        super().__init__(msg)
        self.answers = list(answers)


class BadTarget(ValueError):
    """Cible, port ou options ssh refusés (code 2)."""


def _clean(text: str) -> str:
    return _CONTROL.sub(lambda m: "\\x%02x" % ord(m.group()), text)


def ssh_exe(env=None) -> str:
    env = os.environ if env is None else env
    return env.get("SSHVAULT_SSH") or "ssh"


def deploy_timeout(env=None) -> float:
    return seconds(os.environ if env is None else env, TIMEOUT_VAR, DEFAULT_TIMEOUT)


def _ipv6(text: str) -> bool:
    if text.count(":") < 2:
        return False
    try:
        ipaddress.IPv6Address(text)
    except ValueError:
        return False
    return True


def ssh_target(target: str) -> str:
    """Cible telle que `ssh` la reçoit : `[user@]hôte`, IPv6 sans crochets (ssh 8.9 les garde
    dans le nom à résoudre, mesuré : « Could not resolve hostname [::1] »). BadTarget (code 2)
    si la cible est refusée : nom d'hôte de lettres, chiffres, `.`, `-`, `_` (pas de `-` en tête),
    ou adresse IPv6 valide (au moins deux « : »), entre crochets ou non."""
    user, sep, host = target.rpartition("@")
    if host.startswith("[") and host.endswith("]") and _ipv6(host[1:-1]):
        host = host[1:-1]
    elif not (_HOST.fullmatch(host) or _ipv6(host)):
        host = ""
    if not host or (sep and not _USER.fullmatch(user)):
        raise BadTarget("cible invalide %r : [utilisateur@]hôte attendu (lettres, chiffres, « . », « - », « _ » ; "
                        "ou adresse IPv6)" % target)
    return user + sep + host


def check_target(target: str) -> None:
    ssh_target(target)


def check_port(port: str) -> str:
    if not re.fullmatch(r"[0-9]{1,5}", port or "", re.ASCII) or not 1 <= int(port) <= 65535:
        raise BadTarget("port invalide %r : entier de 1 à 65535" % port)
    return str(int(port))


def key_line(public_key: str) -> Optional[str]:
    """`type base64 [commentaire]` d'une clé publique, vérifiée (type `ssh-*`, `ecdsa-*` ou
    `sk-*` sans caractère de contrôle, base64 valide, type annoncé = type du blob) ; commentaire
    gardé seulement s'il est imprimable (sinon retiré : la ligne va sur un terminal, ou dans
    authorized_keys). None si illisible : le script distant n'a jamais à refuser une ligne."""
    parts = (public_key or "").strip().split(None, 2)
    if len(parts) < 2 or not _KEY_TYPE.fullmatch(parts[0]):
        return None
    try:
        raw = base64.b64decode(parts[1], validate=True)
        kind = describe_blob(raw)[0]
    except (ValueError, UnicodeDecodeError):
        return None
    if kind != parts[0]:
        return None
    comment = parts[2].strip() if len(parts) > 2 else ""
    if comment and not comment.isprintable():
        comment = ""
    return "%s %s%s" % (parts[0], parts[1], " " + comment if comment else "")


def _has_option(options, name: str) -> bool:
    """`-o NOM=…`, `-oNOM …`, `-o "NOM valeur"` parmi les options de l'utilisateur ?"""
    name = name.lower()
    for n, a in enumerate(options):
        if a == "-o" and n + 1 < len(options):
            value = options[n + 1]
        elif a.startswith("-o") and len(a) > 2:
            value = a[2:]
        else:
            continue
        if re.split(r"[\s=]", value.strip(), 1)[0].lower() == name:
            return True
    return False


def ssh_argv(target: str, port: Optional[str], options, env=None) -> list:
    """argv de `ssh` : options de l'utilisateur telles quelles, `-o ConnectTimeout` (sauf s'il
    l'a donné), `-p`, `--`, cible, commande fixe."""
    argv = [ssh_exe(env), *options]
    if not _has_option(options, "ConnectTimeout"):
        argv += ["-o", "ConnectTimeout=%d" % CONNECT_TIMEOUT]
    if port is not None:
        argv += ["-p", port]
    return argv + ["--", ssh_target(target), REMOTE_COMMAND]


def _stop(p) -> None:
    """ssh arrêté : SIGTERM, puis SIGKILL s'il traîne."""
    try:
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    except ProcessLookupError:
        pass


def deploy(lines, target: str, port: Optional[str], options, env=None) -> tuple:
    """Un seul `ssh` : `lines` sur stdin ; renvoie (réponses « added »/« present »/
    « present-options » dans l'ordre, lignes de stderr de ssh). DeployError si ssh échoue, reste
    sans réponse (SSHVAULT_DEPLOY_TIMEOUT), ou si la réponse est incomplète ; ses `answers`
    disent les clés déjà traitées."""
    timeout = deploy_timeout(env)
    argv = ssh_argv(target, port, options, env)
    data = "".join(l + "\n" for l in lines).encode()
    try:
        p = subprocess.Popen(argv, env=dict(os.environ if env is None else env), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise DeployError("ssh introuvable (%s) : installer openssh-client" % argv[0]) from None
    except OSError as e:
        raise DeployError("lancement de %s : %s" % (argv[0], e.strerror or e)) from None
    done = False
    try:
        try:
            out, err = p.communicate(input=data, timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop(p)
            try:  # un enfant de ssh (ProxyCommand…) peut garder les tubes ouverts : lecture bornée
                out, err = p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                out = b""
            answers = _answers(out)
            raise DeployError("ssh vers %s sans réponse en %gs (%s) : arrêté" % (target, timeout, TIMEOUT_VAR),
                              answers) from None
        done = True
    finally:
        if not done and p.poll() is None:  # Ctrl-C, SIGTERM… : ssh ne reste pas derrière
            _stop(p)
    notes = [_clean(l.strip()) for l in err.decode(errors="replace").splitlines() if l.strip()]
    answers = _answers(out)
    if p.returncode != 0:
        why = " ".join(notes)[-300:] or "aucun message"
        raise DeployError("ssh vers %s en échec (code %d) : %s" % (target, p.returncode, why), answers)
    if len(answers) != len(lines):
        raise DeployError("réponse inattendue de %s : %d réponse(s) pour %d clé(s) ; vérifier ~/.ssh/authorized_keys "
                          "de la cible" % (target, len(answers), len(lines)), answers)
    return answers, notes


def _answers(out: bytes) -> list:
    return [m.group(1) for m in (ANSWER.fullmatch(l.strip()) for l in out.decode(errors="replace").splitlines())
            if m]

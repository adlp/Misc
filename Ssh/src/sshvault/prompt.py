"""Invite du mot de passe maître : terminal ou askpass, selon les règles de ssh.

Choix (lecture de `read_passphrase()`, readpass.c d'OpenSSH 8.9, et `man ssh`) :
  - askpass « permis » si DISPLAY ou WAYLAND_DISPLAY est non vide ;
  - SSH_ASKPASS_REQUIRE (insensible à la casse) :
      force  : askpass, même sans DISPLAY ;
      prefer : askpass plutôt que le terminal, si permis ;
      never  : jamais d'askpass ;
  - sinon le terminal (`/dev/tty`, pas stdin : sous `Match exec`, stdin est /dev/null),
    seulement si le processus est au premier plan du terminal (`tcgetpgrp == getpgrp`) :
    en arrière-plan (`ssh … &`), lire `/dev/tty` arrêterait le processus (SIGTTIN) ;
    sans terminal au premier plan, askpass si permis ;
  - askpass suppose SSH_ASKPASS défini (`man ssh`) ; s'il manque, repli sur le terminal.

L'askpass de sshvault (`sshvault-askpass`, CAP-11), posé dans le shell avec
`SSH_ASKPASS_REQUIRE=force`, ne sert jamais aux invites de sshvault ni à ses enfants (ssh-add,
ssh-keygen, ssh-agent) : `internal_env` remplace SSH_ASKPASS par le réglage `askpass-fallback`
(absent : retiré) et retire `SSH_ASKPASS_REQUIRE=force` (comme si l'utilisateur ne l'avait pas
posé : `prefer` enverrait les invites à l'askpass graphique dès que DISPLAY est défini) ; les
règles ci-dessus jugent sur cet environnement (le terminal d'abord, sinon l'askpass graphique
s'il est permis).

Chaque invite a un délai borné. Le descripteur de `/dev/tty` est fermé et l'écho
restauré sur tous les chemins ; un askpass est tué avec tout son groupe.
"""
from __future__ import annotations

import os
import select
import shutil
import signal
import subprocess
import termios
from dataclasses import dataclass
from typing import Mapping, Optional

from .settings import seconds

DEFAULT_TIMEOUT = 60.0
TTY_PATH = "/dev/tty"
#: Nom de l'askpass de sshvault (commande installée, [project.scripts]).
ASKPASS_NAME = "sshvault-askpass"


class PromptError(Exception):
    """Invite impossible, annulée ou sans réponse."""


class PromptUnavailable(PromptError):
    """Ni terminal, ni askpass utilisable."""


@dataclass(frozen=True)
class Plan:
    use_askpass: bool
    askpass: Optional[str]  # programme à lancer si use_askpass


def plan(env: Mapping[str, str], have_tty: bool) -> Optional[Plan]:
    """Décide de la méthode d'invite ; None si aucune n'est possible."""
    allow = bool(env.get("DISPLAY")) or bool(env.get("WAYLAND_DISPLAY"))
    use = False
    require = (env.get("SSH_ASKPASS_REQUIRE") or "").lower()
    if require == "force":
        use = allow = True
    elif require == "prefer":
        use = allow
    elif require == "never":
        allow = False
    if not use and not have_tty:
        use = True
    askpass = env.get("SSH_ASKPASS") or None
    if use and allow and askpass:
        return Plan(True, askpass)
    if have_tty:
        return Plan(False, None)
    return None


def open_tty(path: str = TTY_PATH) -> Optional[int]:
    try:
        return os.open(path, os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return None


def is_foreground(fd: int) -> bool:
    """Le processus est-il dans le groupe de premier plan du terminal `fd` ?"""
    try:
        return os.tcgetpgrp(fd) == os.getpgrp()
    except OSError:
        return False


def open_foreground_tty(path: str = TTY_PATH) -> Optional[int]:
    """Descripteur de `/dev/tty` si le processus y est au premier plan, sinon None."""
    fd = open_tty(path)
    if fd is not None and not is_foreground(fd):
        os.close(fd)
        return None
    return fd


def prompt_tty(fd: int, text: str, timeout: float) -> str:
    try:
        old = termios.tcgetattr(fd)
    except (OSError, termios.error) as e:
        raise PromptUnavailable("terminal inutilisable : %s" % e) from None
    new = list(old)
    # Écho coupé, mode canonique imposé (un tty laissé en raw rendrait une lecture partielle).
    new[3] = (new[3] & ~(termios.ECHO | termios.ECHONL)) | termios.ICANON
    try:
        os.write(fd, b"\r")
        # TCSAFLUSH comme readpassphrase : une saisie tapée avant l'invite est jetée.
        termios.tcsetattr(fd, termios.TCSAFLUSH, new)
        os.write(fd, text.encode())
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            raise PromptError("aucune saisie sur le terminal en %gs" % timeout)
        data = os.read(fd, 4096)
    except (OSError, termios.error) as e:  # termios.error n'est pas un OSError
        raise PromptError("terminal inutilisable : %s" % e) from None
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSANOW, old)
            os.write(fd, b"\n")
        except (OSError, termios.error):
            pass
    if not data:
        raise PromptError("saisie annulée (fin de fichier)")
    return data.decode(errors="replace").rstrip("\r\n")


def prompt_askpass(prog: str, text: str, timeout: float) -> str:
    try:
        p = subprocess.Popen([prog, text], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             start_new_session=True)
    except OSError as e:
        raise PromptError("askpass %s : %s" % (prog, e.strerror or e)) from None
    try:
        try:
            out, _ = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise PromptError("askpass sans réponse en %gs" % timeout) from None
    finally:
        # Sur tout chemin (délai, Ctrl-C, signal) : tout le groupe, un askpass shell
        # laissant sinon un petit-fils qui tient le tube.
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        if p.returncode is None:
            p.kill()
            p.wait()
        if p.stdout:
            p.stdout.close()
    if p.returncode != 0:
        raise PromptError("askpass annulé (code %d)" % p.returncode)
    return out.decode(errors="replace").rstrip("\r\n")


def own_askpass(prog: Optional[str], env: Optional[Mapping[str, str]] = None) -> bool:
    """`prog` (valeur de SSH_ASKPASS) est-il l'askpass de sshvault ? Nom `sshvault-askpass`,
    écrit ou au bout des liens symboliques (cherché dans le PATH s'il n'a pas de `/`)."""
    if not prog:
        return False
    env = os.environ if env is None else env
    if os.path.basename(prog) == ASKPASS_NAME:
        return True
    path = prog if "/" in prog else (shutil.which(prog, path=env.get("PATH")) or "")
    return bool(path) and os.path.basename(os.path.realpath(path)) == ASKPASS_NAME


def askpass_fallback(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Askpass de relais : le réglage `askpass-fallback` (config.json de `env`), sinon
    /usr/bin/ssh-askpass s'il est exécutable et que DISPLAY est défini ; jamais l'askpass de
    sshvault ; None : aucun. Réglage illisible : le défaut."""
    env = os.environ if env is None else env
    from .config import DEFAULT_ASKPASS, Config, ConfigError, default_path
    try:
        v = Config(default_path(env)).askpass_fallback()
    except ConfigError:
        v = None
    if v is None and env.get("DISPLAY") and os.path.isfile(DEFAULT_ASKPASS) and os.access(DEFAULT_ASKPASS, os.X_OK):
        v = DEFAULT_ASKPASS
    if v and own_askpass(v, env):
        return None
    return v or None


def internal_env(env: Mapping[str, str]) -> Mapping[str, str]:
    """Environnement des invites de sshvault et de ses enfants : si SSH_ASKPASS est l'askpass de
    sshvault, il devient `askpass-fallback` (absent : retiré) et SSH_ASKPASS_REQUIRE=force est
    retiré (terminal d'abord, comme sans le réglage). Sinon `env` tel quel. Idempotent."""
    if not own_askpass(env.get("SSH_ASKPASS") or "", env):
        return env
    out = dict(env)
    fb = askpass_fallback(env)
    if fb:
        out["SSH_ASKPASS"] = fb
    else:
        out.pop("SSH_ASKPASS", None)
    if (out.get("SSH_ASKPASS_REQUIRE") or "").lower() == "force":
        del out["SSH_ASKPASS_REQUIRE"]
    return out


UNAVAILABLE = "aucune invite possible (ni /dev/tty, ni SSH_ASKPASS utilisable)"


def _usable_env(env: Mapping[str, str]) -> Mapping[str, str]:
    """`env` sans SSH_ASKPASS si ce programme n'est pas un fichier exécutable (cherché dans le
    PATH s'il n'a pas de `/`) : un askpass absent compte comme « pas d'askpass », pas comme une
    invite annulée."""
    prog = env.get("SSH_ASKPASS") or ""
    if not prog:
        return env
    path = prog if "/" in prog else (shutil.which(prog, path=env.get("PATH")) or "")
    if path and os.path.isfile(path) and os.access(path, os.X_OK):
        return env
    return {k: v for k, v in env.items() if k != "SSH_ASKPASS"}


def available(env: Optional[Mapping[str, str]] = None, tty_path: str = TTY_PATH) -> bool:
    """Une invite serait-elle possible (terminal au premier plan, ou askpass utilisable) ?"""
    env = internal_env(os.environ if env is None else env)
    fd = open_foreground_tty(tty_path)
    if fd is not None:
        os.close(fd)
    return plan(_usable_env(env), fd is not None) is not None


def ask_password(text: str, env: Optional[Mapping[str, str]] = None,
                 timeout: Optional[float] = None, tty_path: str = TTY_PATH) -> str:
    env = internal_env(os.environ if env is None else env)
    if timeout is None:
        timeout = prompt_timeout(env)
    fd = open_foreground_tty(tty_path)
    try:
        p = plan(_usable_env(env), fd is not None)
        if p is None:
            raise PromptUnavailable(UNAVAILABLE)
        if p.use_askpass:
            return prompt_askpass(p.askpass, text, timeout)
        return prompt_tty(fd, text, timeout)
    finally:
        if fd is not None:
            os.close(fd)


def prompt_timeout(env: Mapping[str, str]) -> float:
    try:
        return seconds(env, "SSHVAULT_PROMPT_TIMEOUT", DEFAULT_TIMEOUT)
    except ValueError as e:
        raise PromptError(str(e)) from None

"""Invite du mot de passe maître : terminal ou askpass, selon les règles de ssh.

Choix (lecture de `read_passphrase()`, readpass.c d'OpenSSH 8.9, et `man ssh`) :
  - askpass « permis » si DISPLAY ou WAYLAND_DISPLAY est non vide ;
  - SSH_ASKPASS_REQUIRE (insensible à la casse) :
      force  : askpass, même sans DISPLAY ;
      prefer : askpass plutôt que le terminal, si permis ;
      never  : jamais d'askpass ;
  - sinon le terminal (`/dev/tty`, pas stdin : sous `Match exec`, stdin est /dev/null) ;
    sans terminal, askpass si permis ;
  - askpass suppose SSH_ASKPASS défini (`man ssh`) ; s'il manque, repli sur le terminal.

Chaque invite a un délai borné. Le descripteur de `/dev/tty` est fermé et l'écho
restauré sur tous les chemins ; un askpass est tué avec tout son groupe.
"""
from __future__ import annotations

import os
import select
import signal
import subprocess
import termios
from dataclasses import dataclass
from typing import Mapping, Optional

from .settings import seconds

DEFAULT_TIMEOUT = 60.0
TTY_PATH = "/dev/tty"


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


def ask_password(text: str, env: Optional[Mapping[str, str]] = None,
                 timeout: Optional[float] = None, tty_path: str = TTY_PATH) -> str:
    env = os.environ if env is None else env
    if timeout is None:
        timeout = prompt_timeout(env)
    fd = open_tty(tty_path)
    try:
        p = plan(env, fd is not None)
        if p is None:
            raise PromptUnavailable("aucune invite possible (ni /dev/tty, ni SSH_ASKPASS utilisable)")
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

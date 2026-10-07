"""Surveillant de l'agent dédié : `python -m sshvault.watch <pid> <socket> <st_dev> <st_ino>`.

Lancé détaché (sa propre session) par sshvault avec l'agent. Toutes les WATCH_INTERVAL
secondes : si le socket n'est plus celui créé par l'agent (supprimé, remplacé) ou si
XDG_RUNTIME_DIR a disparu (fin de session : le tmpfs est vidé), il arrête l'agent (pid
vérifié avant chaque signal) puis se termine ; si l'agent est mort, il se termine.
Il n'écrit rien. N'utilise pas `ssh-agent -D` (interdit par la story) : l'agent reste un
démon ordinaire, suivi par son pid.
"""
from __future__ import annotations

import os
import signal
import stat
import sys
import time

from .agent import Agent

WATCH_INTERVAL = 2.0


def socket_gone(sock: str, dev: int, ino: int) -> bool:
    try:
        st = os.lstat(sock)
    except OSError:
        return True
    return not stat.S_ISSOCK(st.st_mode) or (st.st_dev, st.st_ino) != (dev, ino)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        pid, sock, dev, ino = int(argv[0]), argv[1], int(argv[2]), int(argv[3])
    except (IndexError, ValueError):
        return 2
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    agent = Agent(os.path.dirname(sock), env={})
    runtime = os.path.dirname(os.path.dirname(sock))
    while agent.pid_is_agent(pid):
        if socket_gone(sock, dev, ino) or not os.path.isdir(runtime):
            try:
                # SIGKILL : sur SIGTERM, ssh-agent supprimerait le chemin du socket, peut-être
                # déjà repris par un nouvel agent
                agent._kill(pid, agent.pid_is_agent, hard=True)
            except Exception:
                return 1
            return 0
        time.sleep(WATCH_INTERVAL)
    return 0


if __name__ == "__main__":
    sys.exit(main())

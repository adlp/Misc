#!/usr/bin/env python3
"""Chef de session des tests (`bench.pty_run`) : `ptylead.py fg|bg <tty> <commandes en JSON>`.

Lancé dans une session neuve : il ouvre <tty>, qui devient son terminal de contrôle, avec son
groupe au premier plan. Puis il lance chaque commande (stdin /dev/null, stdout et stderr
hérités) : « fg » dans son propre groupe (au premier plan, comme deux commandes lancées en
même temps par un script), « bg » chacune dans un groupe neuf (en arrière-plan, comme
`cmd &` d'un shell interactif). Il attend tout, écrit « ptylead-rc: [codes] » sur stdout et
sort avec le plus grand code.
"""
import json
import os
import subprocess
import sys


def main():
    mode, tty, cmds = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
    os.close(os.open(tty, os.O_RDWR))
    procs = []
    for argv in cmds:
        procs.append(subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                      preexec_fn=(lambda: os.setpgid(0, 0)) if mode == "bg" else None))
    rcs = [p.wait() for p in procs]
    sys.stdout.write("ptylead-rc: %s\n" % json.dumps(rcs))
    sys.stdout.flush()
    sys.exit(max(rcs) if max(rcs) >= 0 else 128 - min(rcs))


if __name__ == "__main__":
    main()

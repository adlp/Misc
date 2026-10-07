"""Point d'entrée de la commande `sshvault` : le chemin rapide d'`ensure` d'abord (sans charger
la CLI), puis la CLI complète. Ctrl-C pendant un import : une ligne, code 130, pas de traceback."""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from .fastpath import try_fast
        rc = try_fast(sys.argv[1:])
        if rc is not None:
            return rc
        from .cli import main as cli_main
    except KeyboardInterrupt:
        try:
            sys.stderr.write("sshvault: interrompu\n")
        except (OSError, ValueError):
            pass
        return 130
    return cli_main()

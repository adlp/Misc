#!/usr/bin/env python3
"""Maintient un fichier geo-map nginx local listant les IP bannies, et
déclenche un reload nginx quand ce fichier change.

ban/unban ne dépendent pas de fail2ban : ils lisent/modifient/réécrivent
`map_file` directement (I/O locale uniquement, idempotent — pas d'écriture
ni de reload si rien ne change). Seule l'action `start` interroge
`fail2ban-client status <jail>` pour régénérer le fichier en entier
depuis fail2ban (bootstrap / resynchro complète).

Indépendant de sophos_fw_block.py (pas d'import croisé) : script
autonome sans dépendance externe (stdlib uniquement), déployable seul.
"""

__version__ = "1.2.1"

import argparse
import configparser
import fcntl
import hashlib
import ipaddress
import logging
import logging.handlers
import os
import subprocess
import sys
import time
from contextlib import contextmanager

DEFAULT_CONFIG_PATH = "/usr/local/etc/nginx-fw-block/config.conf"
DEFAULT_FAIL2BAN_CLIENT = "fail2ban-client"
DEFAULT_MAP_FILE = "/etc/nginx/banned_ips.conf"
DEFAULT_RELOAD_CMD = "nginx -s reload"
LOCK_DIR = "/run/nginx-fw-block"

DEBUG_TIMING = False


def setup_logging(debug=False, debug_timing=False):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if (debug or debug_timing) else logging.INFO)
    try:
        syslog = logging.handlers.SysLogHandler(address="/dev/log")
        syslog.setFormatter(logging.Formatter("nginx-fw-block: %(message)s"))
        logger.addHandler(syslog)
    except OSError:
        pass
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(stderr)


def parse_jails(raw):
    """Découpe une valeur `jail` (config ou --jail) en tuple de noms de
    jails, séparés par des virgules, espaces superflus tolérés, doublons
    supprimés (ordre de première apparition conservé). Tuple vide si
    `raw` est vide/None."""
    if not raw:
        return ()
    return tuple(dict.fromkeys(j.strip() for j in raw.split(",") if j.strip()))


def load_config(path):
    cp = configparser.ConfigParser()
    if not cp.read(path):
        raise SystemExit(f"config introuvable ou illisible: {path}")
    try:
        sec = cp["nginx"]
        cfg = {
            "jail": parse_jails(sec.get("jail", fallback=None)),
            "fail2ban_client": sec.get(
                "fail2ban_client", fallback=DEFAULT_FAIL2BAN_CLIENT
            ),
            "map_file": sec.get("map_file", fallback=DEFAULT_MAP_FILE),
            "reload_cmd": sec.get("reload_cmd", fallback=DEFAULT_RELOAD_CMD),
        }
    except KeyError as exc:
        raise SystemExit(f"clé manquante dans {path}: {exc}")
    return cfg


def validate_ip(ip):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise SystemExit(f"IP invalide: {ip}")
    return ip


def _get_banned_ips_for_jail(cfg, jail):
    cmd = [cfg["fail2ban_client"], "status", jail]
    t0 = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        raise RuntimeError(f"{cfg['fail2ban_client']} introuvable (PATH ?)")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"fail2ban-client status {jail} : timeout")
    finally:
        if DEBUG_TIMING:
            logging.debug(
                "[timing] fail2ban-client status %s : %.3fs", jail, time.monotonic() - t0
            )
    if result.returncode != 0:
        raise RuntimeError(
            f"fail2ban-client status {jail} a échoué (jail inconnue ?): "
            f"{result.stderr.strip()}"
        )
    for line in result.stdout.splitlines():
        if "Banned IP list:" in line:
            _, _, rest = line.partition("Banned IP list:")
            return rest.split()
    raise RuntimeError(
        f"'Banned IP list' introuvable dans la sortie de fail2ban-client "
        f"pour la jail {jail} (format de sortie inattendu)"
    )


def get_banned_ips(cfg):
    """IP actuellement bannies, union de toutes les jails configurées, via
    fail2ban-client.

    Même logique/format attendu que sophos_fw_block.py (dupliqué
    volontairement — script autonome sans dépendance croisée, voir
    docstring du module). Une jail interrogée par appel ; une IP bannie
    dans plusieurs jails n'apparaît qu'une fois (union, ordre de première
    apparition conservé).
    """
    if not cfg["jail"]:
        raise SystemExit("jail requis dans la config (ou --jail) pour interroger fail2ban")
    ips = {}
    for jail in cfg["jail"]:
        for ip in _get_banned_ips_for_jail(cfg, jail):
            ips[ip] = None
    return list(ips)


def write_map_file(cfg, ips):
    """Écrit le fichier geo-map complet (une IP par ligne, syntaxe geo/map
    nginx), en remplaçant tout le contenu — écriture atomique
    (temp + rename) pour ne jamais laisser nginx lire un fichier tronqué."""
    lines = "".join(f"{ip} 1;\n" for ip in ips)
    directory = os.path.dirname(cfg["map_file"]) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{cfg['map_file']}.tmp{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(lines)
    os.replace(tmp, cfg["map_file"])
    logging.info("%s écrit (%d IP)", cfg["map_file"], len(ips))


def reload_nginx(cfg):
    t0 = time.monotonic()
    result = subprocess.run(
        cfg["reload_cmd"], shell=True, capture_output=True, text=True, timeout=15
    )
    if DEBUG_TIMING:
        logging.debug(
            "[timing] reload_cmd (%s) : %.3fs", cfg["reload_cmd"], time.monotonic() - t0
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"reload nginx échoué ({cfg['reload_cmd']}): {result.stderr.strip()}"
        )
    logging.info("nginx rechargé (%s)", cfg["reload_cmd"])


def push_from_fail2ban(cfg, ips):
    write_map_file(cfg, ips)
    reload_nginx(cfg)
    return ips


def read_map_file(cfg):
    """Lit les IP actuellement dans `map_file` (pas fail2ban).

    Format attendu : une IP en premier token par ligne ("1.2.3.4 1;").
    Fichier absent -> liste vide (premier ban avant tout `start`).
    """
    if not os.path.exists(cfg["map_file"]):
        return []
    ips = []
    with open(cfg["map_file"]) as f:
        for line in f:
            line = line.strip()
            if line:
                ips.append(line.split()[0])
    return ips


@contextmanager
def _ip_activity_lock(cfg, ip):
    """Verrou non-bloquant par IP : yield True si acquis, False sinon.

    Même logique que sophos_fw_block.py 2.3.1 : si un ban/unban est déjà
    en cours pour cette IP, l'appelant abandonne immédiatement plutôt que
    d'attendre ou de déclencher un reload en double. Fichier de verrou
    jamais supprimé (tmpfs /run, nettoyé au reboot — évite un TOCTOU
    unlink-vs-flock).
    """
    os.makedirs(LOCK_DIR, exist_ok=True)
    digest = hashlib.sha256(cfg["map_file"].encode()).hexdigest()[:16]
    path = f"{LOCK_DIR}/inprogress-{digest}-{ip.replace(':', '_')}.lock"
    fd = open(path, "a+")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        yield False
        return
    try:
        yield True
    finally:
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        fd.close()


def ban(cfg, ip):
    """Ajoute `ip` à `map_file` si absent — ne dépend pas de fail2ban.

    Lit/modifie/réécrit le fichier local uniquement (I/O locale, pas
    d'appel `fail2ban-client`). Idempotent : si déjà présent, aucune
    écriture ni reload.
    """
    with _ip_activity_lock(cfg, ip) as acquired:
        if not acquired:
            logging.info("ban %s : déjà en cours (autre appel), abandonné", ip)
            return
        ips = read_map_file(cfg)
        if ip in ips:
            logging.info("%s déjà présent dans %s, rien à faire", ip, cfg["map_file"])
            return
        ips.append(ip)
        write_map_file(cfg, ips)
        reload_nginx(cfg)


def unban(cfg, ip):
    """Retire `ip` de `map_file` si présent — ne dépend pas de fail2ban."""
    with _ip_activity_lock(cfg, ip) as acquired:
        if not acquired:
            logging.info("unban %s : déjà en cours (autre appel), abandonné", ip)
            return
        ips = read_map_file(cfg)
        if ip not in ips:
            logging.info("%s absent de %s, rien à faire", ip, cfg["map_file"])
            return
        ips = [x for x in ips if x != ip]
        write_map_file(cfg, ips)
        reload_nginx(cfg)


def start(cfg):
    """Régénère le fichier complet depuis fail2ban et recharge nginx.

    Seule action qui interroge fail2ban (`get_banned_ips`) — ban/unban ne
    lisent/écrivent que le fichier local. À lancer au démarrage du
    service, ou après toute intervention manuelle sur le fichier / la
    jail (resynchro complète, source de vérité = fail2ban pour cette
    action précise).
    """
    ips = get_banned_ips(cfg)
    push_from_fail2ban(cfg, ips)


def list_banned(cfg):
    """Affiche le contenu actuel du fichier local (pas d'appel réseau)."""
    if not os.path.exists(cfg["map_file"]):
        print(f"{cfg['map_file']} : introuvable (jamais généré)")
        return
    with open(cfg["map_file"]) as f:
        content = f.read()
    if not content.strip():
        print(f"{cfg['map_file']} : vide")
        return
    print(content, end="")


CONFIG_HELP = f"""\
Fichier de config attendu (section [nginx]), défaut: {DEFAULT_CONFIG_PATH}

  [nginx]
  jail            = sshd                       # requis seulement pour start
                                                #   plusieurs jails : séparées
                                                #   par des virgules, ex
                                                #   "sshd,nginx-http-auth"
                                                #   (union des IP bannies)
  fail2ban_client = fail2ban-client             # optionnel, idem
  map_file        = {DEFAULT_MAP_FILE}
  reload_cmd      = {DEFAULT_RELOAD_CMD}        # ex Docker: docker exec <container> nginx -s reload

ban/unban ne lisent/écrivent que `map_file` (idempotent, pas d'appel
fail2ban-client) : `jail` n'est nécessaire que pour `start`.

Le fichier `map_file` généré est au format geo/map nginx (une IP par
ligne, "1.2.3.4 1;") — à inclure dans la conf nginx :

  geo $remote_addr $is_banned {{
      default 0;
      include {DEFAULT_MAP_FILE};
  }}

  # global (server{{}}) ou ciblé (dans une location{{}}) :
  if ($is_banned) {{ return 403; }}

Si le trafic est proxysé (IP réelle dans un header, pas $remote_addr),
configurer ngx_http_realip_module en amont (set_real_ip_from,
real_ip_header) pour que $remote_addr reflète la vraie IP cliente.

Exemples:
  nginx_fw_block.py ban 203.0.113.5
  nginx_fw_block.py unban 203.0.113.5
  nginx_fw_block.py list
  nginx_fw_block.py start
  nginx_fw_block.py ban 203.0.113.5 --jail sshd --map-file /tmp/test.conf --reload-cmd "true" --debug-timing
  nginx_fw_block.py start --jail sshd,nginx-http-auth,nginx-botsearch
"""


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=CONFIG_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "action",
        choices=["ban", "unban", "list", "start"],
        help="ban/unban une IP (push depuis fail2ban), list le contenu "
        "actuel du fichier, start (régénère tout depuis fail2ban)",
    )
    parser.add_argument(
        "ip", nargs="?", help="requis pour ban/unban, ignoré pour list/start"
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"chemin fichier config (défaut: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--jail",
        help="surcharge la/les jail(s) fail2ban définie(s) dans la config "
        "(une ou plusieurs, séparées par des virgules)",
    )
    parser.add_argument(
        "--map-file", help="surcharge le fichier cible défini dans la config"
    )
    parser.add_argument(
        "--reload-cmd", help="surcharge la commande de reload définie dans la config"
    )
    parser.add_argument(
        "--debug", action="store_true", help="log détaillé"
    )
    parser.add_argument(
        "--debug-timing",
        action="store_true",
        help="log la durée de fail2ban-client et de la commande de reload",
    )
    args = parser.parse_args()

    if args.action in ("ban", "unban") and not args.ip:
        parser.error(f"argument ip requis pour l'action '{args.action}'")

    setup_logging(args.debug, args.debug_timing)
    global DEBUG_TIMING
    DEBUG_TIMING = args.debug_timing

    ip = validate_ip(args.ip) if args.ip else None
    cfg = load_config(args.config)
    if args.jail:
        cfg["jail"] = parse_jails(args.jail)
    if args.map_file:
        cfg["map_file"] = args.map_file
    if args.reload_cmd:
        cfg["reload_cmd"] = args.reload_cmd

    t0 = time.monotonic()
    try:
        if args.action == "ban":
            ban(cfg, ip)
        elif args.action == "unban":
            unban(cfg, ip)
        elif args.action == "start":
            start(cfg)
        else:
            list_banned(cfg)
    except Exception as exc:
        logging.error("%s%s: %s", args.action, f" {ip}" if ip else "", exc)
        sys.exit(1)
    finally:
        if DEBUG_TIMING:
            logging.debug(
                "[timing] action %s : %.3fs au total", args.action, time.monotonic() - t0
            )


if __name__ == "__main__":
    main()

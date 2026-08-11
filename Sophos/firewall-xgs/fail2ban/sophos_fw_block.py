#!/usr/bin/env python3
"""Ajoute/retire une IP d'un IPHostGroup et/ou d'une IP list Sophos
Firewall (XGS) via API XML.

Appelé par fail2ban (actionban/actionunban) pour bloquer/débloquer des IP
via une règle firewall existante référençant le groupe et/ou l'IP list.
"""

__version__ = "1.4.2"

import argparse
import configparser
import ipaddress
import logging
import logging.handlers
import sys
import warnings
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

# requests (paquet apt, ancien) vérifie la version d'urllib3/chardet au
# chargement et émet ce warning si une version plus récente est installée
# par ailleurs (pip --user) ; sans impact sur le fonctionnement du script.
warnings.filterwarnings(
    "ignore", message=r".*doesn't match a supported version.*"
)

import requests  # noqa: E402
from urllib3.exceptions import InsecureRequestWarning  # noqa: E402

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

DEFAULT_CONFIG_PATH = "/etc/sophos-fw/api.conf"
DEFAULT_PREFIX = "f2b_"

# Session HTTP réutilisée pour tous les appels API d'une même invocation :
# évite un handshake TCP/TLS neuf à chaque appel. Sûr en usage concurrent
# ici (threads dans ban()/unban()/list_group()) car aucun état mutable de
# la session n'est touché par requête (auth transite dans le corps XML,
# pas en cookie/en-tête de session). Pool dimensionné pour encaisser les
# requêtes parallèles (jusqu'à MAX_PARALLEL_REQUESTS) sans recréer de
# connexion à chaque lot.
MAX_PARALLEL_REQUESTS = 10

_session = requests.Session()
_session.mount(
    "https://",
    requests.adapters.HTTPAdapter(
        pool_connections=MAX_PARALLEL_REQUESTS, pool_maxsize=MAX_PARALLEL_REQUESTS
    ),
)


def setup_logging(debug=False):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    try:
        syslog = logging.handlers.SysLogHandler(address="/dev/log")
        syslog.setFormatter(logging.Formatter("sophos-fw-block: %(message)s"))
        logger.addHandler(syslog)
    except OSError:
        pass
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(stderr)


def load_config(path):
    cp = configparser.ConfigParser()
    if not cp.read(path):
        raise SystemExit(f"config introuvable ou illisible: {path}")
    try:
        sec = cp["api"]
        cfg = {
            "host": sec["host"],
            "port": sec.getint("port", fallback=4444),
            "username": sec["username"],
            "password": sec["password"],
            "verify_ssl": sec.getboolean("verify_ssl", fallback=False),
            "group": sec.get("group", fallback=None) or None,
            "iplist": sec.get("iplist", fallback=None) or None,
            "prefix": sec.get("prefix", fallback=DEFAULT_PREFIX),
        }
    except KeyError as exc:
        raise SystemExit(f"clé manquante dans {path}: {exc}")
    if not cfg["group"] and not cfg["iplist"]:
        raise SystemExit(f"{path}: au moins une des clés group/iplist requise")
    return cfg


def validate_ip(ip):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise SystemExit(f"IP invalide: {ip}")
    return ip


def host_name_for_ip(ip, prefix=DEFAULT_PREFIX):
    return prefix + ip.replace(".", "_").replace(":", "_")


def api_call(cfg, body_xml):
    url = f"https://{cfg['host']}:{cfg['port']}/webconsole/APIController"
    login = (
        f"<Login><Username>{escape(cfg['username'])}</Username>"
        f"<Password>{escape(cfg['password'])}</Password></Login>"
    )
    xml = f"<Request>{login}{body_xml}</Request>"
    logging.debug("requête XML: %s", xml.replace(escape(cfg["password"]), "***"))
    resp = _session.post(
        url, data={"reqxml": xml}, verify=cfg["verify_ssl"], timeout=15
    )
    resp.raise_for_status()
    logging.debug("réponse XML: %s", resp.text)
    root = ET.fromstring(resp.text)
    check_login(root)
    return root


def check_login(root):
    login = root.find("Login")
    if login is not None:
        status = login.findtext("status", "")
        if "Successful" not in status:
            raise RuntimeError(f"échec authentification API Sophos: {status}")


def parse_status(root, tag):
    """Retourne (code, texte) du <Status> sous `tag`.

    Certaines erreurs API renvoient un format sans <Status> (ex: <Error>
    <Message>). On retombe alors sur ce message, ou à défaut sur le XML
    brut du nœud pour ne pas perdre l'info en cas de schéma imprévu.
    """
    el = root.find(f".//{tag}/Status")
    if el is not None:
        return el.attrib.get("code"), (el.text or "").strip()
    msg = root.find(f".//{tag}//Message")
    if msg is not None and msg.text:
        return None, msg.text.strip()
    node = root.find(f".//{tag}")
    if node is not None:
        return None, ET.tostring(node, encoding="unicode").strip()
    return None, ET.tostring(root, encoding="unicode").strip()


def get_group_hosts(cfg):
    body = (
        "<Get><IPHostGroup><Filter>"
        f'<key name="Name" criteria="=">{escape(cfg["group"])}</key>'
        "</Filter></IPHostGroup></Get>"
    )
    root = api_call(cfg, body)
    grp = root.find(".//IPHostGroup")
    if grp is None:
        raise RuntimeError(f"groupe {cfg['group']} introuvable sur le firewall")
    hostlist = grp.find("HostList")
    if hostlist is None:
        return []
    return [h.text for h in hostlist.findall("Host") if h.text]


def get_iphost_address(cfg, name):
    body = (
        "<Get><IPHost><Filter>"
        f'<key name="Name" criteria="=">{escape(name)}</key>'
        "</Filter></IPHost></Get>"
    )
    root = api_call(cfg, body)
    host = root.find(".//IPHost")
    if host is None:
        return None
    return host.findtext("IPAddress")


def list_group(cfg):
    """Retourne [(nom_objet, ip)] pour chaque membre du groupe configuré.

    `ip` vaut None si l'objet IPHost référencé dans le groupe n'existe
    plus (référence orpheline). Un Get par membre est nécessaire (l'API
    ne renvoie pas les IP dans le Get du groupe) — ces lookups sont
    indépendants les uns des autres, donc lancés en parallèle plutôt que
    séquentiellement (dominant le temps de `list` sur un groupe non trivial).
    """
    names = get_group_hosts(cfg)
    if not names:
        return []
    with ThreadPoolExecutor(max_workers=min(len(names), MAX_PARALLEL_REQUESTS)) as pool:
        ips = list(pool.map(lambda n: get_iphost_address(cfg, n), names))
    return list(zip(names, ips))


def set_group_hosts(cfg, hosts):
    host_xml = "".join(f"<Host>{escape(h)}</Host>" for h in hosts)
    body = (
        '<Set operation="update"><IPHostGroup>'
        f"<Name>{escape(cfg['group'])}</Name>"
        f"<HostList>{host_xml}</HostList>"
        "</IPHostGroup></Set>"
    )
    root = api_call(cfg, body)
    code, text = parse_status(root, "IPHostGroup")
    if code != "200":
        raise RuntimeError(f"mise à jour groupe {cfg['group']} échouée: {code} {text}")
    logging.info("groupe %s mis à jour (%d hôtes)", cfg["group"], len(hosts))


def create_iphost(cfg, name, ip):
    body = (
        '<Set operation="add"><IPHost>'
        f"<Name>{escape(name)}</Name>"
        "<IPFamily>IPv4</IPFamily><HostType>IP</HostType>"
        f"<IPAddress>{escape(ip)}</IPAddress>"
        "</IPHost></Set>"
    )
    root = api_call(cfg, body)
    code, text = parse_status(root, "IPHost")
    if code == "200":
        logging.info("IPHost %s créé", name)
    elif code and "already exist" in (text or "").lower():
        logging.info("IPHost %s existe déjà", name)
    else:
        raise RuntimeError(f"création IPHost {name} échouée: {code} {text}")


def delete_iphost(cfg, name):
    body = f"<Remove><IPHost><Name>{escape(name)}</Name></IPHost></Remove>"
    root = api_call(cfg, body)
    code, text = parse_status(root, "IPHost")
    if code == "200":
        logging.info("IPHost %s supprimé", name)
    elif code and any(
        s in (text or "").lower() for s in ("not exist", "not found")
    ):
        logging.info("IPHost %s: %s", name, text)
    else:
        logging.warning("suppression IPHost %s non confirmée: %s %s", name, code, text)


def get_iplist_addresses(cfg):
    body = (
        "<Get><IPHost><Filter>"
        f'<key name="Name" criteria="=">{escape(cfg["iplist"])}</key>'
        "</Filter></IPHost></Get>"
    )
    root = api_call(cfg, body)
    host = root.find(".//IPHost")
    if host is None:
        raise RuntimeError(f"IP list {cfg['iplist']} introuvable sur le firewall")
    raw = host.findtext("ListOfIPAddresses") or ""
    return [ip.strip() for ip in raw.split(",") if ip.strip()]


def set_iplist_addresses(cfg, ips):
    body = (
        '<Set operation="update"><IPHost>'
        f"<Name>{escape(cfg['iplist'])}</Name>"
        "<HostType>IPList</HostType>"
        f"<ListOfIPAddresses>{escape(','.join(ips))}</ListOfIPAddresses>"
        "</IPHost></Set>"
    )
    root = api_call(cfg, body)
    code, text = parse_status(root, "IPHost")
    if code != "200":
        raise RuntimeError(f"mise à jour IP list {cfg['iplist']} échouée: {code} {text}")
    logging.info("IP list %s mise à jour (%d IP)", cfg["iplist"], len(ips))


def _run_parallel(*funcs):
    """Exécute des callables sans argument, en parallèle si plusieurs.

    group et iplist sont deux objets indépendants sur le firewall : les
    traiter dans des threads séparés évite d'attendre séquentiellement
    les allers-retours API de l'un puis de l'autre. Lève une exception
    combinée si au moins un callable échoue (les autres vont à leur terme).
    """
    if not funcs:
        return
    if len(funcs) == 1:
        funcs[0]()
        return
    with ThreadPoolExecutor(max_workers=len(funcs)) as pool:
        futures = [pool.submit(f) for f in funcs]
        errors = []
        for f in futures:
            try:
                f.result()
            except Exception as exc:
                errors.append(str(exc))
    if errors:
        raise RuntimeError("; ".join(errors))


def ban(cfg, ip):
    def do_group():
        name = host_name_for_ip(ip, cfg["prefix"])
        # create_iphost (nouvel objet) et get_group_hosts (lecture du
        # groupe) portent sur deux objets distincts : indépendants,
        # lancés en parallèle plutôt que l'un après l'autre.
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_create = pool.submit(create_iphost, cfg, name, ip)
            f_hosts = pool.submit(get_group_hosts, cfg)
            f_create.result()
            hosts = f_hosts.result()
        if name not in hosts:
            hosts.append(name)
            set_group_hosts(cfg, hosts)
        else:
            logging.info("%s déjà présent dans %s", name, cfg["group"])

    def do_iplist():
        ips = get_iplist_addresses(cfg)
        if ip not in ips:
            ips.append(ip)
            set_iplist_addresses(cfg, ips)
        else:
            logging.info("%s déjà présent dans %s", ip, cfg["iplist"])

    tasks = []
    if cfg["group"]:
        tasks.append(do_group)
    if cfg["iplist"]:
        tasks.append(do_iplist)
    _run_parallel(*tasks)


def unban(cfg, ip):
    def do_group():
        name = host_name_for_ip(ip, cfg["prefix"])

        def update_group():
            hosts = get_group_hosts(cfg)
            if name in hosts:
                hosts.remove(name)
                set_group_hosts(cfg, hosts)
            else:
                logging.info("%s absent de %s", name, cfg["group"])

        # retrait du groupe (get+set) et suppression de l'objet IPHost
        # portent sur deux objets distincts : indépendants, en parallèle.
        _run_parallel(update_group, lambda: delete_iphost(cfg, name))

    def do_iplist():
        ips = get_iplist_addresses(cfg)
        if ip in ips:
            ips = [x for x in ips if x != ip]
            set_iplist_addresses(cfg, ips)
        else:
            logging.info("%s absent de %s", ip, cfg["iplist"])

    tasks = []
    if cfg["group"]:
        tasks.append(do_group)
    if cfg["iplist"]:
        tasks.append(do_iplist)
    _run_parallel(*tasks)


CONFIG_HELP = f"""\
Fichier de config attendu (section [api]), défaut: {DEFAULT_CONFIG_PATH}

  [api]
  host        = 192.168.1.1      # IP/nom du firewall XGS
  port        = 4444             # port admin API (défaut: 4444)
  username    = apiuser          # compte avec accès API activé
  password    = ***
  verify_ssl  = false            # true si cert firewall vérifiable
  group       = Fail2Ban-Block   # optionnel, IPHostGroup déjà créé,
                                  #   référencé par une règle Deny
  iplist      = Fail2Ban-List    # optionnel, IPHost de type "IP list"
                                  #   déjà créé (onglet IP Host, type
                                  #   "IP list"), référencé par une règle
  prefix      = f2b_             # optionnel, préfixe des IPHost créés
                                  #   (utilisé seulement avec group)

Au moins une des deux clés group/iplist est requise. Les deux peuvent
être renseignées ensemble : l'IP est alors ajoutée/retirée des deux
objets à chaque ban/unban.

Exemples:
  sophos_fw_block.py ban 203.0.113.5
  sophos_fw_block.py unban 203.0.113.5
  sophos_fw_block.py list
  sophos_fw_block.py ban 203.0.113.5 --group Fail2Ban-Test --debug
  sophos_fw_block.py ban 203.0.113.5 --iplist Fail2Ban-List
"""


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=CONFIG_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "action",
        choices=["ban", "unban", "list"],
        help="ban/unban une IP, ou list les IP actuellement bloquées",
    )
    parser.add_argument("ip", nargs="?", help="requis pour ban/unban, ignoré pour list")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"chemin fichier config API (défaut: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--debug", action="store_true", help="log les requêtes/réponses XML brutes"
    )
    parser.add_argument(
        "--group", help="surcharge le groupe (IPHostGroup) défini dans la config"
    )
    parser.add_argument(
        "--iplist", help="surcharge l'IP list (IPHost type IP list) définie dans la config"
    )
    parser.add_argument(
        "--prefix",
        help="surcharge le préfixe des noms IPHost défini dans la config"
        f" (défaut config: {DEFAULT_PREFIX})",
    )
    args = parser.parse_args()

    if args.action in ("ban", "unban") and not args.ip:
        parser.error(f"argument ip requis pour l'action '{args.action}'")

    setup_logging(args.debug)
    ip = validate_ip(args.ip) if args.ip else None
    cfg = load_config(args.config)
    if args.group:
        cfg["group"] = args.group
    if args.iplist:
        cfg["iplist"] = args.iplist
    if args.prefix:
        cfg["prefix"] = args.prefix

    try:
        if args.action == "ban":
            ban(cfg, ip)
        elif args.action == "unban":
            unban(cfg, ip)
        else:
            if cfg["group"]:
                for name, host_ip in list_group(cfg):
                    print(f"{host_ip or '?':<15} {name}")
            if cfg["iplist"]:
                for host_ip in get_iplist_addresses(cfg):
                    print(f"{host_ip:<15} {cfg['iplist']}")
    except Exception as exc:
        logging.error("%s%s: %s", args.action, f" {ip}" if ip else "", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

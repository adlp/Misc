#!/usr/bin/env python3
"""Ajoute/retire une IP d'un IPHostGroup Sophos Firewall (XGS) via API XML.

Appelé par fail2ban (actionban/actionunban) pour bloquer/débloquer des IP
via une règle firewall existante référençant le groupe cible.
"""

__version__ = "1.0.1"

import argparse
import configparser
import ipaddress
import logging
import logging.handlers
import sys
import warnings
import xml.etree.ElementTree as ET
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
        return {
            "host": sec["host"],
            "port": sec.getint("port", fallback=4444),
            "username": sec["username"],
            "password": sec["password"],
            "verify_ssl": sec.getboolean("verify_ssl", fallback=False),
            "group": sec["group"],
        }
    except KeyError as exc:
        raise SystemExit(f"clé manquante dans {path}: {exc}")


def validate_ip(ip):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise SystemExit(f"IP invalide: {ip}")
    return ip


def host_name_for_ip(ip):
    return "f2b_" + ip.replace(".", "_").replace(":", "_")


def api_call(cfg, body_xml):
    url = f"https://{cfg['host']}:{cfg['port']}/webconsole/APIController"
    login = (
        f"<Login><Username>{escape(cfg['username'])}</Username>"
        f"<Password>{escape(cfg['password'])}</Password></Login>"
    )
    xml = f"<Request>{login}{body_xml}</Request>"
    logging.debug("requête XML: %s", xml.replace(escape(cfg["password"]), "***"))
    resp = requests.post(
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


def ban(cfg, ip):
    name = host_name_for_ip(ip)
    create_iphost(cfg, name, ip)
    hosts = get_group_hosts(cfg)
    if name not in hosts:
        hosts.append(name)
        set_group_hosts(cfg, hosts)
    else:
        logging.info("%s déjà présent dans %s", name, cfg["group"])


def unban(cfg, ip):
    name = host_name_for_ip(ip)
    hosts = get_group_hosts(cfg)
    if name in hosts:
        hosts = [h for h in hosts if h != name]
        set_group_hosts(cfg, hosts)
    else:
        logging.info("%s absent de %s", name, cfg["group"])
    delete_iphost(cfg, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["ban", "unban"])
    parser.add_argument("ip")
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH, help="chemin fichier config API"
    )
    parser.add_argument(
        "--debug", action="store_true", help="log les requêtes/réponses XML brutes"
    )
    args = parser.parse_args()

    setup_logging(args.debug)
    ip = validate_ip(args.ip)
    cfg = load_config(args.config)

    try:
        if args.action == "ban":
            ban(cfg, ip)
        else:
            unban(cfg, ip)
    except Exception as exc:
        logging.error("%s %s: %s", args.action, ip, exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

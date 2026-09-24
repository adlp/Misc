#!/usr/bin/env python3
"""Liste les baux du serveur DHCP d'un Sophos Firewall (XGS) via l'API XML.

Utilise le même fichier de config que sophos_fw_block.py (section [api] :
host, port, username, password, verify_ssl). Ordre de recherche :
--config, puis ~/.sophos-fw-block.conf (home de l'utilisateur), puis
/usr/local/etc/sophos-fw-block.conf.

IMPORTANT : le nom exact de l'entité API portant les baux n'a pas pu être
vérifié depuis l'environnement de développement (pas d'accès au firewall).
Le script interroge `--entity` (défaut : DHCPLease). Si le firewall répond
"entité inconnue"/vide, lancer avec --raw pour voir la réponse XML brute, et
essayer un autre nom d'entité avec --entity.
"""

__version__ = "1.1.0"

import argparse
import configparser
import csv
import json
import os
import sys
import warnings
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

warnings.filterwarnings("ignore", message=r".*doesn't match a supported version.*")

import requests  # noqa: E402
from urllib3.exceptions import InsecureRequestWarning  # noqa: E402

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

DEFAULT_CONFIG_PATH = "/usr/local/etc/sophos-fw-block.conf"
DEFAULT_ENTITY = "DHCPLease"


HOME_CONFIG_PATH = os.path.expanduser("~/.sophos-fw-block.conf")


def resolve_config_path(explicit):
    """--config explicite > ~/.sophos-fw-block.conf (si présent) > défaut système."""
    if explicit:
        return explicit
    if os.path.isfile(HOME_CONFIG_PATH):
        return HOME_CONFIG_PATH
    return DEFAULT_CONFIG_PATH


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
        }
    except KeyError as exc:
        raise SystemExit(f"clé manquante dans {path}: {exc}")


def api_get(cfg, entity):
    url = f"https://{cfg['host']}:{cfg['port']}/webconsole/APIController"
    xml = (
        "<Request><Login>"
        f"<Username>{escape(cfg['username'])}</Username>"
        f"<Password>{escape(cfg['password'])}</Password>"
        f"</Login><Get><{entity}></{entity}></Get></Request>"
    )
    resp = requests.post(
        url, data={"reqxml": xml}, verify=cfg["verify_ssl"], timeout=20
    )
    resp.raise_for_status()
    return resp.text


def flatten(node, prefix=""):
    """{champ: texte} pour un noeud, sous-éléments aplatis en a.b."""
    out = {}
    for child in node:
        key = f"{prefix}{child.tag}"
        if len(child):
            out.update(flatten(child, prefix=f"{key}."))
        else:
            out[key] = (child.text or "").strip()
    return out


def parse_leases(xml_text, entity):
    root = ET.fromstring(xml_text)
    login = root.find("Login")
    if login is not None and "Successful" not in login.findtext("status", ""):
        raise SystemExit(f"échec authentification API: {login.findtext('status', '')}")
    status = root.find(f".//{entity}/Status")
    if status is not None and status.attrib.get("code") not in (None, "200"):
        raise SystemExit(
            f"erreur API {status.attrib.get('code')}: {(status.text or '').strip()}"
        )
    return [flatten(n) for n in root.findall(f".//{entity}")]


def print_table(rows, columns):
    widths = {c: max(len(c), *(len(r.get(c, "")) for r in rows)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for r in rows:
        print("  ".join(r.get(c, "").ljust(widths[c]) for c in columns))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", help=f"fichier config API (défaut: {HOME_CONFIG_PATH} s'il existe, sinon {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--entity", default=DEFAULT_ENTITY,
                        help=f"nom de l'entité API à interroger (défaut: {DEFAULT_ENTITY})")
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="sortie JSON")
    fmt.add_argument("--csv", action="store_true", help="sortie CSV")
    fmt.add_argument("--raw", action="store_true",
                     help="affiche la réponse XML brute (diagnostic)")
    parser.add_argument("--filter", metavar="TEXTE",
                        help="ne garde que les baux dont un champ contient TEXTE "
                        "(insensible à la casse)")
    args = parser.parse_args()

    try:
        cfg = load_config(resolve_config_path(args.config))
        text = api_get(cfg, args.entity)
        if args.raw:
            print(text)
            return
        rows = parse_leases(text, args.entity)
    except (requests.RequestException, ET.ParseError, SystemExit) as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.filter:
        needle = args.filter.lower()
        rows = [r for r in rows if any(needle in v.lower() for v in r.values())]

    if not rows:
        print(
            f"aucun résultat pour l'entité {args.entity} (essayer --raw, ou un "
            "autre --entity)",
            file=sys.stderr,
        )
        sys.exit(2)

    columns = list(dict.fromkeys(k for r in rows for k in r))
    if args.json:
        json.dump(rows, sys.stdout, indent=2, ensure_ascii=False)
        print()
    elif args.csv:
        w = csv.DictWriter(sys.stdout, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    else:
        print_table(rows, columns)


if __name__ == "__main__":
    main()

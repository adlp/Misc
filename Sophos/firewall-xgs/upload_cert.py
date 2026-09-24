#!/usr/bin/env python3
"""Dépose (ou met à jour) un certificat sur un Sophos Firewall (XGS) via l'API XML.

Utilise le même fichier de config que sophos_fw_block.py (section [api] :
host, port, username, password, verify_ssl). Ordre de recherche :
--config, puis ~/.sophos-fw-block.conf (home de l'utilisateur), puis
/usr/local/etc/sophos-fw-block.conf.

Formats :
  pem     : --cert cert.pem --key key.pem  (chaîne éventuelle dans cert.pem)
  pkcs12  : --cert bundle.p12 [--cert-password ...]

Comportement : par défaut, ajout (operation="add"). Avec --update, mise à jour
d'un certificat existant du même nom (operation="update"). Avec --upsert, le
script cherche d'abord le nom sur le firewall (Get) et choisit add/update.

IMPORTANT : la syntaxe exacte de l'upload (balises Certificate/Action,
nom du champ multipart des fichiers) et le support de operation="update"
n'ont pas pu être vérifiés depuis l'environnement de développement (pas
d'accès au firewall). Tester d'abord avec --dry-run puis sur un certificat de
test ; en cas d'erreur, la réponse brute de l'API est affichée (--debug
ajoute la requête XML, mot de passe masqué).
"""

__version__ = "1.1.0"

import argparse
import configparser
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


def _login_xml(cfg):
    return (
        f"<Login><Username>{escape(cfg['username'])}</Username>"
        f"<Password>{escape(cfg['password'])}</Password></Login>"
    )


def _post(cfg, body_xml, files=None, debug=False):
    url = f"https://{cfg['host']}:{cfg['port']}/webconsole/APIController"
    xml = f"<Request>{_login_xml(cfg)}{body_xml}</Request>"
    if debug:
        masked = xml.replace(escape(cfg["password"]), "***")
        print(f"requête XML: {masked}", file=sys.stderr)
    resp = requests.post(
        url, data={"reqxml": xml}, files=files, verify=cfg["verify_ssl"], timeout=60
    )
    resp.raise_for_status()
    if debug:
        print(f"réponse XML: {resp.text}", file=sys.stderr)
    root = ET.fromstring(resp.text)
    login = root.find("Login")
    if login is not None and "Successful" not in login.findtext("status", ""):
        raise RuntimeError(f"échec authentification API: {login.findtext('status', '')}")
    return root


def certificate_exists(cfg, name, debug=False):
    body = (
        "<Get><Certificate><Filter>"
        f'<key name="Name" criteria="=">{escape(name)}</key>'
        "</Filter></Certificate></Get>"
    )
    root = _post(cfg, body, debug=debug)
    return root.find(".//Certificate/Name") is not None


def upload(cfg, name, cert_path, key_path, fmt, cert_password, update, debug=False):
    cert_file = os.path.basename(cert_path)
    parts = [
        f"<Name>{escape(name)}</Name>",
        "<Action>UploadCertificate</Action>",
        f"<CertificateFormat>{fmt}</CertificateFormat>",
    ]
    if cert_password:
        parts.append(f"<Password>{escape(cert_password)}</Password>")
    parts.append(f"<CertificateFile>{escape(cert_file)}</CertificateFile>")
    files = [("file", (cert_file, open(cert_path, "rb")))]
    if fmt == "pem":
        key_file = os.path.basename(key_path)
        parts.append(f"<PrivateKeyFile>{escape(key_file)}</PrivateKeyFile>")
        files.append(("file", (key_file, open(key_path, "rb"))))
    op = "update" if update else "add"
    body = f'<Set operation="{op}"><Certificate>{"".join(parts)}</Certificate></Set>'
    try:
        root = _post(cfg, body, files=files, debug=debug)
    finally:
        for _, (_, fh) in files:
            fh.close()
    node = root.find(".//Certificate/Status")
    if node is None:
        node = root.find(".//Status")
    code = node.attrib.get("code") if node is not None else None
    text = (node.text or "").strip() if node is not None else ET.tostring(root, encoding="unicode")
    return code, text


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", help=f"fichier config API (défaut: {HOME_CONFIG_PATH} s'il existe, sinon {DEFAULT_CONFIG_PATH})")
    p.add_argument("--name", required=True, help="nom du certificat sur le firewall")
    p.add_argument("--cert", required=True, help="fichier certificat (pem) ou bundle (p12)")
    p.add_argument("--key", help="clé privée (requise pour le format pem)")
    p.add_argument("--format", choices=["pem", "pkcs12"], default="pem")
    p.add_argument("--cert-password", help="mot de passe du bundle pkcs12 / de la clé")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true",
                      help="met à jour un certificat existant (operation=update)")
    mode.add_argument("--upsert", action="store_true",
                      help="update si le nom existe déjà sur le firewall, sinon add")
    p.add_argument("--dry-run", action="store_true",
                   help="vérifie les fichiers et affiche l'action, sans appeler l'API d'upload")
    p.add_argument("--debug", action="store_true", help="affiche requêtes/réponses XML")
    args = p.parse_args()

    try:
        if not os.path.isfile(args.cert):
            raise SystemExit(f"fichier introuvable: {args.cert}")
        if args.format == "pem":
            if not args.key:
                raise SystemExit("--key requis pour le format pem")
            if not os.path.isfile(args.key):
                raise SystemExit(f"fichier introuvable: {args.key}")
        cfg = load_config(resolve_config_path(args.config))

        update = args.update
        if args.upsert:
            update = certificate_exists(cfg, args.name, debug=args.debug)
            print(f"{args.name}: {'existe -> update' if update else 'absent -> add'}")
        if args.dry_run:
            print(f"dry-run: {'update' if update else 'add'} de {args.name} "
                  f"({args.format}) non exécuté")
            return

        code, text = upload(cfg, args.name, args.cert, args.key, args.format,
                            args.cert_password, update, debug=args.debug)
        print(f"{code}: {text}")
        if code != "200":
            sys.exit(1)
    except (requests.RequestException, ET.ParseError, RuntimeError, SystemExit) as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

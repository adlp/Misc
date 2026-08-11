#!/usr/bin/env python3
"""Ajoute/retire une IP d'un IPHostGroup et/ou d'une IP list Sophos
Firewall (XGS) via API XML.

Appelé par fail2ban (actionban/actionunban) pour bloquer/débloquer des IP
via une règle firewall existante référençant le groupe et/ou l'IP list.
"""

__version__ = "1.6.1"

import argparse
import configparser
import fcntl
import ipaddress
import logging
import logging.handlers
import sys
import time
import warnings
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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
LOCK_PATH = "/run/lock/sophos-fw-block.lock"

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

# Activé par --debug-timing : log la durée de chaque appel API, la durée
# de l'établissement de connexion TCP+TLS (une seule fois par connexion
# du pool, réutilisée ensuite), et la durée totale de l'action.
DEBUG_TIMING = False


def _patch_connection_timing():
    """Instrumente urllib3 pour logger le temps de connexion TCP+TLS.

    Une connexion HTTPS n'est établie qu'une fois par connexion mise en
    pool (réutilisée pour les appels suivants sur ce thread) : si ce
    temps n'apparaît qu'une ou deux fois dans les logs alors que le
    goulot persiste, la lenteur vient du traitement côté firewall, pas
    du réseau.
    """
    from urllib3.connection import HTTPSConnection

    if getattr(HTTPSConnection.connect, "_sophos_timed", False):
        return
    orig_connect = HTTPSConnection.connect

    def timed_connect(self):
        t0 = time.monotonic()
        orig_connect(self)
        logging.debug(
            "[timing] connexion TCP+TLS vers %s:%s établie en %.3fs",
            self.host, self.port, time.monotonic() - t0,
        )

    timed_connect._sophos_timed = True
    HTTPSConnection.connect = timed_connect


@contextmanager
def locked(exclusive):
    """Verrou inter-process sur LOCK_PATH (flock, libéré même sur crash).

    ban/unban prennent un verrou partagé (plusieurs peuvent tourner en
    même temps, cas normal avec fail2ban). vacuum prend un verrou
    exclusif : il calcule "IPHost avec ce préfixe absents du groupe" puis
    supprime — si un ban est en cours entre la création de l'IPHost et
    son ajout au groupe, vacuum verrait cet IPHost comme orphelin et le
    supprimerait à tort (race condition). L'exclusivité empêche ça.
    """
    with open(LOCK_PATH, "a+") as fd:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)


def setup_logging(debug=False, debug_timing=False):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if (debug or debug_timing) else logging.INFO)
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


def ip_from_host_name(name, prefix):
    """Inverse de host_name_for_ip(), quand c'est possible sans appel API.

    Ne fonctionne que pour un nom généré par ce script (préfixe connu,
    IPv4 — les ":" d'une IPv6 seraient ambigus avec les "_" du séparateur
    de champs). Retourne None si le nom ne correspond pas à ce format
    (objet créé manuellement, IPv6, etc.) : l'appelant doit alors
    retomber sur un Get IPHost classique pour ce membre.
    """
    if not name.startswith(prefix):
        return None
    candidate = name[len(prefix):].replace("_", ".")
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


def api_call(cfg, body_xml):
    url = f"https://{cfg['host']}:{cfg['port']}/webconsole/APIController"
    login = (
        f"<Login><Username>{escape(cfg['username'])}</Username>"
        f"<Password>{escape(cfg['password'])}</Password></Login>"
    )
    xml = f"<Request>{login}{body_xml}</Request>"
    logging.debug("requête XML: %s", xml.replace(escape(cfg["password"]), "***"))
    t0 = time.monotonic()
    resp = _session.post(
        url, data={"reqxml": xml}, verify=cfg["verify_ssl"], timeout=15
    )
    dt = time.monotonic() - t0
    if DEBUG_TIMING:
        label = sys._getframe(1).f_code.co_name
        http_version = {10: "1.0", 11: "1.1"}.get(resp.raw.version, resp.raw.version)
        logging.debug(
            "[timing] appel API [%s] : %.3fs (HTTP/%s %s, %d octets, Connection: %s)",
            label, dt, http_version, resp.status_code, len(resp.content),
            resp.headers.get("Connection", "<absent>"),
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
    plus (référence orpheline).

    L'API ne renvoie pas les IP dans le Get du groupe, mais le nom d'un
    objet créé par ce script encode déjà l'IP (host_name_for_ip) : pour
    ces membres-là, aucun Get supplémentaire n'est nécessaire. Seuls les
    membres au nom non reconnu (objet ajouté manuellement, etc.) déclenchent
    un Get IPHost — en parallèle s'il y en a plusieurs. Sur un groupe
    entièrement géré par ce script, ça ramène `list` de N+1 appels API à 1
    seul (le Get du groupe), l'API Sophos observée sérialisant les
    requêtes côté serveur (le parallélisme client n'y change rien).
    """
    names = get_group_hosts(cfg)
    if not names:
        return []

    resolved = {}
    unresolved = []
    for name in names:
        ip = ip_from_host_name(name, cfg["prefix"])
        if ip is not None:
            resolved[name] = ip
        else:
            unresolved.append(name)

    if unresolved:
        with ThreadPoolExecutor(max_workers=min(len(unresolved), MAX_PARALLEL_REQUESTS)) as pool:
            fetched = list(pool.map(lambda n: get_iphost_address(cfg, n), unresolved))
        resolved.update(zip(unresolved, fetched))

    return [(name, resolved[name]) for name in names]


def set_group_hosts(cfg, hosts):
    """Remplace toute la HostList du groupe par `hosts`.

    Toujours passer par un Get (get_group_hosts) puis ce Set avec la liste
    complète : `operation="add"` sur un IPHostGroup existant échoue (501,
    sémantique "create"), et `<Remove><IPHostGroup>...<HostList>...` pour
    retirer un membre précis est CONFIRMÉ dangereux — testé en réel, il vide
    tout le groupe au lieu du seul membre visé et laisse l'objet dans un état
    où même ce Set échoue ensuite (500). Ne jamais utiliser Remove sur un
    IPHostGroup avec une HostList (voir test_group_merge.py).
    """
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


def add_to_group(cfg, name):
    """Ajoute `name` au groupe (get_group_hosts + set_group_hosts).

    `operation="add"` sur un IPHostGroup déjà existant échoue TOUJOURS,
    confirmé deux fois en conditions réelles : avec un host fictif (501
    "Configuration parameters validation failed") et avec un host réel
    (502 "Entity having same name already exists" — l'entité en conflit
    est le GROUPE lui-même, pas le membre : ce message ne veut donc PAS
    dire "membre déjà présent"). Un précédent code interprétait ce texte
    comme "déjà présent" et s'arrêtait là sans jamais ajouter le membre —
    bug silencieux (IPHost créé mais jamais bloqué). Ne plus tenter ce
    chemin : toujours get+set (voir set_group_hosts pour le détail des
    opérations confirmées dangereuses/non fonctionnelles sur IPHostGroup).
    """
    hosts = get_group_hosts(cfg)
    if name not in hosts:
        hosts.append(name)
        set_group_hosts(cfg, hosts)
    else:
        logging.warning("%s déjà présent dans %s", name, cfg["group"])


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
        logging.warning("IPHost %s existe déjà", name)
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
        logging.warning("IPHost %s: %s", name, text)
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

    def timed(f):
        t0 = time.monotonic()
        f()
        if DEBUG_TIMING:
            logging.debug(
                "[timing] tâche parallèle [%s] : %.3fs", f.__name__, time.monotonic() - t0
            )

    with ThreadPoolExecutor(max_workers=len(funcs)) as pool:
        futures = [pool.submit(timed, f) for f in funcs]
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
        create_iphost(cfg, name, ip)
        add_to_group(cfg, name)

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
                logging.warning("%s absent de %s", name, cfg["group"])

        def do_delete():
            delete_iphost(cfg, name)

        # retrait du groupe (get+set) et suppression de l'objet IPHost
        # portent sur deux objets distincts : indépendants, en parallèle.
        _run_parallel(update_group, do_delete)

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


def get_all_iphost_names(cfg, prefix):
    """Retourne tous les noms d'IPHost du firewall commençant par `prefix`.

    Pas de Filter côté API (syntaxe "like" non confirmée pour ce champ) :
    Get sans filtre puis filtrage côté client sur le nom. Un seul appel.
    """
    root = api_call(cfg, "<Get><IPHost></IPHost></Get>")
    names = []
    for host in root.findall(".//IPHost"):
        name = host.findtext("Name")
        if name and name.startswith(prefix):
            names.append(name)
    return names


def vacuum_candidates(cfg):
    """IPHost préfixés par ce script mais absents du groupe configuré.

    Ne couvre que l'usage via le groupe géré par ce script — un IPHost
    préfixé référencé directement par une autre règle firewall (sans
    passer par ce groupe) ne serait pas détecté comme utilisé et serait
    supprimé à tort. Cas non couvert : vacuum n'est prévu que pour
    nettoyer les objets orphelins issus du flux ban/unban de ce script.
    """
    prefix = cfg["prefix"]
    if not prefix:
        raise SystemExit("vacuum nécessite un prefix non vide (config ou --prefix)")
    if not cfg["group"]:
        raise SystemExit(
            "vacuum nécessite `group` configuré (les IPHost créés par ban "
            "ne sont utilisés que via ce groupe)"
        )
    all_names = set(get_all_iphost_names(cfg, prefix))
    used = set(get_group_hosts(cfg))
    return sorted(all_names - used)


def vacuum(cfg, dry_run=False):
    candidates = vacuum_candidates(cfg)
    if not candidates:
        logging.info("vacuum: rien à supprimer (préfixe %s)", cfg["prefix"])
        return
    if dry_run:
        for name in candidates:
            print(name)
        logging.info("vacuum (dry-run): %d objet(s) seraient supprimés", len(candidates))
        return
    for name in candidates:
        delete_iphost(cfg, name)
    logging.info("vacuum: %d objet(s) supprimés", len(candidates))


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

vacuum supprime les IPHost <prefix>* du groupe qui ne sont plus membres du
groupe (orphelins, ex: après un unban interrompu). Nécessite `group`
configuré (config ou --group) et un prefix non vide.

Exemples:
  sophos_fw_block.py ban 203.0.113.5
  sophos_fw_block.py unban 203.0.113.5
  sophos_fw_block.py list
  sophos_fw_block.py ban 203.0.113.5 --group Fail2Ban-Test --debug
  sophos_fw_block.py ban 203.0.113.5 --iplist Fail2Ban-List
  sophos_fw_block.py vacuum --dry-run
  sophos_fw_block.py vacuum
"""


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=CONFIG_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "action",
        choices=["ban", "unban", "list", "vacuum"],
        help="ban/unban une IP, list les IP bloquées, ou vacuum "
        "(supprime les IPHost <prefix>* orphelins du groupe)",
    )
    parser.add_argument(
        "ip", nargs="?", help="requis pour ban/unban, ignoré pour list/vacuum"
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"chemin fichier config API (défaut: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--debug", action="store_true", help="log les requêtes/réponses XML brutes"
    )
    parser.add_argument(
        "--debug-timing",
        action="store_true",
        help="log la durée de chaque appel API (dont connexion TCP+TLS), "
        "des tâches parallèles, et le temps total de l'action",
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="vacuum uniquement : affiche les IPHost qui seraient supprimés, sans agir",
    )
    args = parser.parse_args()

    if args.action in ("ban", "unban") and not args.ip:
        parser.error(f"argument ip requis pour l'action '{args.action}'")

    setup_logging(args.debug, args.debug_timing)
    global DEBUG_TIMING
    DEBUG_TIMING = args.debug_timing
    if DEBUG_TIMING:
        _patch_connection_timing()
    ip = validate_ip(args.ip) if args.ip else None
    cfg = load_config(args.config)
    if args.group:
        cfg["group"] = args.group
    if args.iplist:
        cfg["iplist"] = args.iplist
    if args.prefix:
        cfg["prefix"] = args.prefix

    t0 = time.monotonic()
    try:
        if args.action == "ban":
            with locked(exclusive=False):
                ban(cfg, ip)
        elif args.action == "unban":
            with locked(exclusive=False):
                unban(cfg, ip)
        elif args.action == "vacuum":
            with locked(exclusive=True):
                vacuum(cfg, dry_run=args.dry_run)
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
    finally:
        if DEBUG_TIMING:
            logging.debug("[timing] action %s : %.3fs au total", args.action, time.monotonic() - t0)


if __name__ == "__main__":
    main()

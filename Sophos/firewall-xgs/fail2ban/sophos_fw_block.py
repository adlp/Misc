#!/usr/bin/env python3
"""Pousse la liste des IP bannies d'une jail fail2ban vers un IPHostGroup
et/ou une IP list Sophos Firewall (XGS) via API XML.

fail2ban est la source de vérité : ban/unban interrogent `fail2ban-client
status <jail>` puis écrasent l'état XGS avec cette liste (aucune lecture
de l'état XGS actuel pendant ce push). `list`/`vacuum`/`sync` lisent
l'XGS pour inspection/nettoyage/comparaison, mais ne participent pas au
push.
"""

__version__ = "2.2.1"

import argparse
import configparser
import fcntl
import ipaddress
import logging
import logging.handlers
import subprocess
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
DEFAULT_FAIL2BAN_CLIENT = "fail2ban-client"
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
            "jail": sec.get("jail", fallback=None) or None,
            "fail2ban_client": sec.get(
                "fail2ban_client", fallback=DEFAULT_FAIL2BAN_CLIENT
            ),
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


def get_banned_ips(cfg):
    """IP actuellement bannies dans la jail configurée, via fail2ban-client.

    Source de vérité pour ban/unban/sync : ne reflète que ce que fail2ban
    connaît (pas l'état XGS). "Banned IP list:" est le format de sortie de
    `fail2ban-client status <jail>` sur les versions testées ; si le format
    change, l'erreur explicite ci-dessous permet de le repérer vite.
    """
    if not cfg["jail"]:
        raise SystemExit("jail requis dans la config (ou --jail) pour interroger fail2ban")
    cmd = [cfg["fail2ban_client"], "status", cfg["jail"]]
    t0 = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        raise RuntimeError(f"{cfg['fail2ban_client']} introuvable (PATH ?)")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"fail2ban-client status {cfg['jail']} : timeout")
    finally:
        if DEBUG_TIMING:
            logging.debug(
                "[timing] fail2ban-client status %s : %.3fs", cfg["jail"], time.monotonic() - t0
            )
    if result.returncode != 0:
        raise RuntimeError(
            f"fail2ban-client status {cfg['jail']} a échoué (jail inconnue ?): "
            f"{result.stderr.strip()}"
        )
    for line in result.stdout.splitlines():
        if "Banned IP list:" in line:
            _, _, rest = line.partition("Banned IP list:")
            return rest.split()
    raise RuntimeError(
        f"'Banned IP list' introuvable dans la sortie de fail2ban-client "
        f"pour la jail {cfg['jail']} (format de sortie inattendu)"
    )


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


def push_from_fail2ban(cfg, ips=None):
    """Écrase l'état XGS (group et/ou iplist) avec la liste fail2ban.

    Aucune lecture de l'état XGS actuel : on pousse la liste calculée,
    point. group -> HostList complète (noms dérivés des IP) ; iplist ->
    ListOfIPAddresses complète (IP brutes). Utilisé par ban/unban/start :
    la différence, c'est que fail2ban a déjà mis à jour sa propre liste
    avant l'appel (ip en plus pour ban, en moins pour unban, liste
    complète pour start), donc ce même push produit le bon résultat.

    `ips` : liste déjà récupérée à passer pour éviter un second appel à
    fail2ban-client (utilisé par start, qui a besoin de la liste avant
    de créer les IPHost manquants). None -> la récupère elle-même.
    """
    if ips is None:
        ips = get_banned_ips(cfg)
    if cfg["group"]:
        hosts = [host_name_for_ip(ip, cfg["prefix"]) for ip in ips]
        set_group_hosts(cfg, hosts)
    if cfg["iplist"]:
        set_iplist_addresses(cfg, ips)
    return ips


def ban(cfg, ip):
    if cfg["group"]:
        name = host_name_for_ip(ip, cfg["prefix"])
        create_iphost(cfg, name, ip)
    push_from_fail2ban(cfg)


def unban(cfg, ip):
    logging.info("unban %s : resync depuis fail2ban (jail %s)", ip, cfg["jail"])
    push_from_fail2ban(cfg)


def start(cfg):
    """Comme ban, mais pour toutes les IP actuellement bannies par fail2ban.

    Utile au démarrage (service qui vient de (re)démarrer, jail avec des
    bans déjà en cours) : crée l'IPHost manquant pour CHAQUE IP bannie
    (idempotent, pas seulement la dernière comme ban) avant de pousser la
    liste complète — comble le vide documenté dans les limites connues
    (une IP déjà bannie avant le premier ban n'a pas d'IPHost).
    """
    ips = get_banned_ips(cfg)
    if cfg["group"]:
        for ip in ips:
            name = host_name_for_ip(ip, cfg["prefix"])
            create_iphost(cfg, name, ip)
    push_from_fail2ban(cfg, ips=ips)


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


def flush(cfg, dry_run=False):
    """Vide entièrement le groupe puis vacuum — sans interroger fail2ban.

    N'agit que sur `group` (pas `iplist`). Le verrou exclusif (posé par
    l'appelant, voir main()) couvre les deux étapes : sinon un ban
    concurrent pourrait créer un IPHost entre le vidage du groupe et le
    scan de vacuum, qui le verrait comme orphelin et le supprimerait à
    tort.
    """
    if not cfg["group"]:
        raise SystemExit("flush nécessite `group` configuré (config ou --group)")
    prefix = cfg["prefix"]
    if not prefix:
        raise SystemExit("flush nécessite un prefix non vide (config ou --prefix), requis par vacuum")

    if dry_run:
        logging.info("flush (dry-run): groupe %s serait vidé", cfg["group"])
        # une fois le groupe vide, tout IPHost <prefix>* devient orphelin
        candidates = sorted(get_all_iphost_names(cfg, prefix))
        if not candidates:
            logging.info("vacuum (dry-run): rien à supprimer (préfixe %s)", prefix)
        else:
            for name in candidates:
                print(name)
            logging.info("vacuum (dry-run): %d objet(s) seraient supprimés", len(candidates))
        return

    set_group_hosts(cfg, [])
    logging.info("groupe %s vidé", cfg["group"])
    vacuum(cfg, dry_run=False)


def _print_sync_diff(label, fail2ban_ips, xgs_ips):
    common = sorted(fail2ban_ips & xgs_ips)
    only_fail2ban = sorted(fail2ban_ips - xgs_ips)
    only_xgs = sorted(xgs_ips - fail2ban_ips)
    print(f"\n--- {label} ---")
    print(f"communes ({len(common)}):")
    for ip in common:
        print(f"  = {ip}")
    print(
        f"seulement fail2ban, absentes de {label} ({len(only_fail2ban)}) "
        "— seraient ajoutées au prochain ban/unban:"
    )
    for ip in only_fail2ban:
        print(f"  + {ip}")
    print(
        f"seulement {label}, absentes de fail2ban ({len(only_xgs)}) "
        "— seraient retirées au prochain ban/unban:"
    )
    for ip in only_xgs:
        print(f"  - {ip}")


def sync_report(cfg):
    """Compare l'état fail2ban (source de vérité) à l'état XGS actuel.

    Lecture seule — ne modifie rien. Sert à voir ce qu'un prochain
    ban/unban changerait (puisque ban/unban écrasent l'XGS avec la liste
    fail2ban sans jamais la lire au préalable), et à détecter une dérive
    (ex: premier déploiement avec des bans déjà existants dans la jail,
    objet supprimé manuellement sur le firewall, etc.).
    """
    fail2ban_ips = set(get_banned_ips(cfg))
    print(f"fail2ban (jail {cfg['jail']}): {len(fail2ban_ips)} IP bannie(s)")

    if cfg["group"]:
        xgs_ips = {ip for _, ip in list_group(cfg) if ip}
        _print_sync_diff(f"groupe {cfg['group']}", fail2ban_ips, xgs_ips)

    if cfg["iplist"]:
        xgs_ips = set(get_iplist_addresses(cfg))
        _print_sync_diff(f"iplist {cfg['iplist']}", fail2ban_ips, xgs_ips)


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
  jail        = sshd             # requis pour ban/unban/sync : jail
                                  #   fail2ban interrogée via fail2ban-client
  fail2ban_client = fail2ban-client  # optionnel, chemin/nom du binaire

Au moins une des deux clés group/iplist est requise. Les deux peuvent
être renseignées ensemble : l'IP est alors ajoutée/retirée des deux
objets à chaque ban/unban.

ban/unban interrogent `fail2ban-client status <jail>` et écrasent
l'état XGS (group et/ou iplist) avec cette liste complète — aucune
lecture de l'état XGS actuel avant d'écrire. fail2ban est donc la seule
source de vérité ; ban crée en plus l'IPHost pour la nouvelle IP avant
de pousser (nécessaire pour que le groupe puisse la référencer).

vacuum supprime les IPHost <prefix>* qui ne sont plus membres du groupe
configuré (orphelins, ex: après un ban créant l'objet mais échouant
avant le push). Nécessite `group` configuré (config ou --group) et un
prefix non vide.

sync compare, sans rien modifier, la liste fail2ban (jail configurée) à
l'état XGS actuel (group et/ou iplist) : IP communes, seulement dans
fail2ban (seraient ajoutées au prochain ban/unban), seulement sur XGS
(seraient retirées). Utile pour détecter une dérive avant qu'un
ban/unban n'écrase silencieusement l'état XGS.

flush vide entièrement `group` puis lance vacuum, sans interroger
fail2ban. N'agit pas sur `iplist`. Mêmes prérequis que vacuum (group +
prefix non vide).

start fait comme ban mais pour TOUTES les IP actuellement bannies par
fail2ban (pas d'IP en argument) : crée l'IPHost manquant pour chacune
avant de pousser la liste complète. À lancer au démarrage du service ou
manuellement si la jail avait déjà des bans avant le premier ban/sync.

Exemples:
  sophos_fw_block.py ban 203.0.113.5
  sophos_fw_block.py unban 203.0.113.5
  sophos_fw_block.py list
  sophos_fw_block.py sync
  sophos_fw_block.py start
  sophos_fw_block.py ban 203.0.113.5 --group Fail2Ban-Test --jail sshd --debug
  sophos_fw_block.py ban 203.0.113.5 --iplist Fail2Ban-List
  sophos_fw_block.py vacuum --dry-run
  sophos_fw_block.py vacuum
  sophos_fw_block.py flush --dry-run
  sophos_fw_block.py flush
"""


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=CONFIG_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "action",
        choices=["ban", "unban", "list", "vacuum", "sync", "flush", "start"],
        help="ban/unban une IP (push depuis fail2ban), list les IP "
        "bloquées sur XGS, vacuum (supprime les IPHost <prefix>* "
        "orphelins), sync (compare fail2ban et XGS sans rien modifier), "
        "flush (vide le groupe puis vacuum, sans interroger fail2ban), "
        "start (comme ban mais pour toutes les IP bannies, sans IP en argument)",
    )
    parser.add_argument(
        "ip",
        nargs="?",
        help="requis pour ban/unban, ignoré pour list/vacuum/sync/flush/start",
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
        "--jail", help="surcharge la jail fail2ban définie dans la config"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="vacuum/flush uniquement : affiche les IPHost qui seraient "
        "supprimés (et, pour flush, que le groupe serait vidé), sans agir",
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
    if args.jail:
        cfg["jail"] = args.jail

    t0 = time.monotonic()
    try:
        if args.action == "ban":
            with locked(exclusive=False):
                ban(cfg, ip)
        elif args.action == "unban":
            with locked(exclusive=False):
                unban(cfg, ip)
        elif args.action == "start":
            with locked(exclusive=False):
                start(cfg)
        elif args.action == "vacuum":
            with locked(exclusive=True):
                vacuum(cfg, dry_run=args.dry_run)
        elif args.action == "flush":
            with locked(exclusive=True):
                flush(cfg, dry_run=args.dry_run)
        elif args.action == "sync":
            sync_report(cfg)
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

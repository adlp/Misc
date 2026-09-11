#!/usr/bin/env python3
"""Pousse la liste des IP bannies d'une jail fail2ban vers un IPHostGroup
et/ou une IP list Sophos Firewall (XGS) via API XML.

fail2ban est la source de vérité : ban/unban interrogent `fail2ban-client
status <jail>` puis écrasent l'état XGS avec cette liste (aucune lecture
de l'état XGS actuel pendant ce push). `list`/`vacuum`/`sync` lisent
l'XGS pour inspection/nettoyage/comparaison, mais ne participent pas au
push.
"""

__version__ = "2.6.2"

import argparse
import configparser
import fcntl
import hashlib
import ipaddress
import json
import logging
import logging.handlers
import os
import smtplib
import socket
import subprocess
import sys
import time
import warnings
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from email.message import EmailMessage
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

DEFAULT_CONFIG_PATH = "/usr/local/etc/sophos-fw-block.conf"
DEFAULT_PREFIX = "f2b_"
DEFAULT_FAIL2BAN_CLIENT = "fail2ban-client"
DEFAULT_SMTP_HOST = "localhost"
DEFAULT_SMTP_PORT = 25
LOCK_PATH = "/run/lock/sophos-fw-block.lock"
CACHE_DIR = "/run/sophos-fw-block"
# État des IP list shardées : doit survivre à un reboot (contrairement aux
# verrous/cache de /run) — c'est la seule trace de "quelle IP est dans
# quelle liste", nécessaire pour qu'unban cible la bonne liste sans
# interroger Sophos ni toutes les relire.
SHARD_STATE_DIR = "/var/lib/sophos-fw-block"
IPLIST_HARD_CAP = 1000  # limite Sophos réelle, jamais dépassable

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


def _target_digest(cfg):
    """Identifiant court propre à cette config (host, group, iplist,
    iplist_prefix, jail) — évite qu'une config vise un mauvais verrou/état
    si plusieurs api.conf distincts tournent sur la même machine
    (plusieurs firewalls/jails)."""
    key = (
        f"{cfg['host']}|{cfg['group']}|{cfg['iplist']}|"
        f"{cfg['iplist_prefix']}|{','.join(cfg['jail'])}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


@contextmanager
def _ip_activity_lock(cfg, ip):
    """Verrou non-bloquant par IP : yield True si acquis, False sinon.

    Si un ban/unban est déjà en cours pour cette IP (autre process pas
    encore terminé — cas typique : push précédent lent, fail2ban rappelle
    l'action pour la même IP), l'appelant doit abandonner immédiatement
    plutôt qu'attendre ou repousser en double. C'est la SEULE protection
    contre les appels redondants (pas de cache d'état séparé, retiré en
    2.4.0) : hors collision en vol sur la même IP, chaque ban/unban
    repousse toujours la liste complète — plus simple, et corrige
    gratuitement toute dérive (modification manuelle sur le firewall,
    etc.) à chaque appel au lieu de la laisser filer silencieusement.

    Le fichier de verrou n'est jamais supprimé (accepté : /run est un
    tmpfs, nettoyé au reboot, coût négligeable même avec des milliers
    d'IP distinctes) — le supprimer introduirait un TOCTOU classique
    (unlink pendant qu'un autre process vient d'ouvrir/flock le même
    chemin juste avant la suppression).

    Compromis à connaître : si un ban(X) est en vol et qu'un unban(X)
    arrive entre-temps (IP réhabilitée très vite), cet unban est abandonné
    sans repousser — l'état fail2ban le plus récent ne sera reflété
    qu'au prochain événement sur cette IP, ou via `sync`/`start` manuel.
    Jugé négligeable en pratique : l'écart ban→unban dépasse largement la
    durée d'un push (~5-8s), et un ban qui suit rapidement un unban sur la
    même IP fait de toute façon office de resync.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = f"{CACHE_DIR}/inprogress-{_target_digest(cfg)}-{ip.replace(':', '_')}.lock"
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
            "jail": parse_jails(sec.get("jail", fallback=None)),
            "fail2ban_client": sec.get(
                "fail2ban_client", fallback=DEFAULT_FAIL2BAN_CLIENT
            ),
            "iplist_prefix": sec.get("iplist_prefix", fallback=None) or None,
            "iplist_seed_ip": sec.get("iplist_seed_ip", fallback=None) or None,
            "iplist_max_entries": sec.getint(
                "iplist_max_entries", fallback=IPLIST_HARD_CAP
            ),
            "alert_email": sec.get("alert_email", fallback=None) or None,
            "smtp_host": sec.get("smtp_host", fallback=DEFAULT_SMTP_HOST),
            "smtp_port": sec.getint("smtp_port", fallback=DEFAULT_SMTP_PORT),
            "smtp_from": sec.get(
                "smtp_from", fallback=f"sophos-fw-block@{socket.gethostname()}"
            ),
        }
    except KeyError as exc:
        raise SystemExit(f"clé manquante dans {path}: {exc}")
    if not cfg["group"] and not cfg["iplist"] and not cfg["iplist_prefix"]:
        raise SystemExit(
            f"{path}: au moins une des clés group/iplist/iplist_prefix requise"
        )
    if cfg["iplist"] and cfg["iplist_prefix"]:
        raise SystemExit(
            f"{path}: iplist et iplist_prefix sont mutuellement exclusifs "
            "(liste unique vs listes shardées)"
        )
    if cfg["iplist_prefix"]:
        if not cfg["iplist_seed_ip"]:
            raise SystemExit(
                f"{path}: iplist_seed_ip requis avec iplist_prefix (IP "
                "placeholder pour pouvoir créer une liste vide)"
            )
        try:
            ipaddress.ip_address(cfg["iplist_seed_ip"])
        except ValueError:
            raise SystemExit(f"{path}: iplist_seed_ip invalide: {cfg['iplist_seed_ip']}")
        if not 1 <= cfg["iplist_max_entries"] <= IPLIST_HARD_CAP:
            raise SystemExit(
                f"{path}: iplist_max_entries doit être entre 1 et {IPLIST_HARD_CAP}"
            )
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

    Source de vérité pour ban/unban/sync : ne reflète que ce que fail2ban
    connaît (pas l'état XGS). Une jail interrogée par appel (pas de
    `status` multi-jail côté fail2ban-client) ; une IP bannie dans
    plusieurs jails n'apparaît qu'une fois dans le résultat (union,
    ordre de première apparition conservé). "Banned IP list:" est le
    format de sortie de `fail2ban-client status <jail>` sur les versions
    testées ; si le format change, l'erreur explicite dans
    `_get_banned_ips_for_jail` permet de le repérer vite.
    """
    if not cfg["jail"]:
        raise SystemExit("jail requis dans la config (ou --jail) pour interroger fail2ban")
    ips = {}
    for jail in cfg["jail"]:
        for ip in _get_banned_ips_for_jail(cfg, jail):
            ips[ip] = None
    return list(ips)


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


def _api_error_hint(code, text):
    """Message d'aide pour les erreurs API connues sur un Set groupe/IP
    list — vide si le code/texte ne correspond à rien de reconnu.

    Ajouté au message d'exception (RuntimeError), donc remonte
    automatiquement dans le log d'erreur main() -> logging.error() ->
    syslog (voir setup_logging(), handler SysLogHandler déjà en place) :
    pas de plomberie syslog séparée à ajouter ici.
    """
    text_l = (text or "").lower()
    if code == "500" and "entity" in text_l:
        return (
            " -- probable IPHost manquant référencé (supprimé par vacuum "
            "alors que fail2ban le considère encore banni, ou groupe dans "
            "un état corrompu suite à un ancien Remove ciblé sur un membre "
            "— voir README) : lancer 'start' pour recréer les IPHost "
            "manquants et resynchroniser depuis fail2ban"
        )
    return ""


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
        raise RuntimeError(
            f"mise à jour groupe {cfg['group']} échouée: {code} {text}"
            f"{_api_error_hint(code, text)}"
        )
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


def set_iplist_addresses(cfg, ips, name=None):
    """Remplace toute la ListOfIPAddresses de l'IP list `name` par `ips`
    (défaut : `cfg['iplist']` — liste unique historique).

    Seule méthode qui fonctionne sur une liste déjà existante :
    `operation="add"` échoue (502 "Entity having same name already
    exists", même comportement que sur IPHostGroup — voir
    set_group_hosts() et test_iplist_add.py). ~5-8s observés en réel pour
    cet appel, y compris quand `ips` est identique au contenu actuel : le
    coût vient de l'application de la config sur un objet référencé par
    une règle active, pas de la taille du diff ni du type d'opération.
    """
    name = name or cfg["iplist"]
    body = (
        '<Set operation="update"><IPHost>'
        f"<Name>{escape(name)}</Name>"
        "<HostType>IPList</HostType>"
        f"<ListOfIPAddresses>{escape(','.join(ips))}</ListOfIPAddresses>"
        "</IPHost></Set>"
    )
    root = api_call(cfg, body)
    code, text = parse_status(root, "IPHost")
    if code != "200":
        raise RuntimeError(f"mise à jour IP list {name} échouée: {code} {text}")
    logging.info("IP list %s mise à jour (%d IP)", name, len(ips))


def create_iplist(cfg, name, ips):
    """Crée une nouvelle IP list (`operation="add"`, fonctionne car
    l'objet n'existe pas encore — contrairement à un Set sur une liste
    déjà existante, voir set_iplist_addresses). `ips` ne doit jamais être
    vide : Sophos exige au moins une adresse pour créer l'objet."""
    body = (
        '<Set operation="add"><IPHost>'
        f"<Name>{escape(name)}</Name>"
        "<IPFamily>IPv4</IPFamily><HostType>IPList</HostType>"
        f"<ListOfIPAddresses>{escape(','.join(ips))}</ListOfIPAddresses>"
        "</IPHost></Set>"
    )
    root = api_call(cfg, body)
    code, text = parse_status(root, "IPHost")
    if code == "200":
        logging.info("IP list %s créée (%d IP)", name, len(ips))
    elif code and "already exist" in (text or "").lower():
        logging.warning("IP list %s existe déjà", name)
    else:
        raise RuntimeError(f"création IP list {name} échouée: {code} {text}")


def _shard_state_path(cfg):
    return f"{SHARD_STATE_DIR}/shards-{_target_digest(cfg)}.json"


def _load_shard_state(cfg):
    """{"active": nom_liste_courante|None, "lists": {nom: [ip, ...]}}.

    Seule trace de "quelle IP est dans quelle liste" : nécessaire pour
    qu'unban cible directement la bonne liste sans interroger Sophos.
    Persistant (/var/lib, pas /run) — une perte de cet état est
    récupérable via `start` (reconstruit depuis fail2ban, voir
    shard_start), mais rare/évitable en le gardant hors tmpfs.
    """
    try:
        with open(_shard_state_path(cfg)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"active": None, "lists": {}}


def _save_shard_state(cfg, state):
    os.makedirs(SHARD_STATE_DIR, exist_ok=True)
    path = _shard_state_path(cfg)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _send_alert_email(cfg, list_name, count):
    """Envoie un mail d'alerte (nouvelle IP list créée). Non fatal : un
    échec d'envoi (pas de relai SMTP local, etc.) ne doit pas faire
    échouer le ban en cours — juste loggé en warning."""
    if not cfg["alert_email"]:
        logging.warning(
            "nouvelle IP list %s créée mais alert_email non configuré, pas de mail envoyé",
            list_name,
        )
        return
    msg = EmailMessage()
    msg["Subject"] = f"[sophos-fw-block] nouvelle IP list créée : {list_name}"
    msg["From"] = cfg["smtp_from"]
    msg["To"] = cfg["alert_email"]
    msg.set_content(
        f"La liste précédente a atteint le seuil configuré "
        f"({cfg['iplist_max_entries']} entrées).\n"
        f"Nouvelle liste créée automatiquement : {list_name}\n\n"
        f"Si une règle firewall doit référencer explicitement chaque IP "
        f"list (plutôt qu'un groupe les englobant toutes), pensez à "
        f"l'ajouter à la règle correspondante sur le Sophos."
    )
    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=10) as smtp:
            smtp.send_message(msg)
        logging.info("mail d'alerte envoyé à %s (%s)", cfg["alert_email"], list_name)
    except OSError as exc:
        logging.warning("échec d'envoi du mail d'alerte (%s): %s", list_name, exc)


def _create_new_shard(cfg, state, alert):
    """Crée la prochaine IP list de la famille (préfixe + numéro suivant),
    seedée avec `iplist_seed_ip` (Sophos exige >= 1 adresse à la création),
    l'enregistre dans `state`. `alert=True` envoie le mail (vrai
    dépassement de seuil) ; `alert=False` pour la toute première création
    (bootstrap normal, pas un événement à notifier)."""
    n = len(state["lists"]) + 1
    name = f"{cfg['iplist_prefix']}{n}"
    seed = cfg["iplist_seed_ip"]
    create_iplist(cfg, name, [seed])
    state["lists"][name] = [seed]
    logging.warning("nouvelle IP list shardée créée: %s (seed %s)", name, seed)
    if alert:
        _send_alert_email(cfg, name, len(state["lists"][name]))
    return name


def _shard_for_new_entry(cfg, state):
    """Retourne le nom de la liste où ajouter une nouvelle IP, en créant
    une nouvelle liste si besoin (bootstrap sans alerte, dépassement de
    seuil avec alerte)."""
    active = state.get("active")
    if active is None:
        active = _create_new_shard(cfg, state, alert=False)
    elif len(state["lists"][active]) >= cfg["iplist_max_entries"]:
        active = _create_new_shard(cfg, state, alert=True)
    state["active"] = active
    return active


def shard_ban(cfg, ip):
    """Ajoute `ip` à la liste shardée active, sans toucher aux autres.

    Ne rebalance jamais (pas de "décalage" en cas de trou dans une liste
    précédente) : une fois la liste active pleine (iplist_max_entries),
    une nouvelle liste est créée et devient l'active ; les listes
    précédentes ne reçoivent plus jamais de nouvelle IP, seulement des
    retraits (shard_unban) — minimise les écritures par ban/unban à 1 API
    call sur 1 seule liste, jamais plus.
    """
    state = _load_shard_state(cfg)
    for name, members in state["lists"].items():
        if ip in members:
            logging.warning("%s déjà présent dans %s, rien à faire", ip, name)
            return

    active = _shard_for_new_entry(cfg, state)
    members = state["lists"][active]
    members.append(ip)
    set_iplist_addresses(cfg, members, name=active)
    _save_shard_state(cfg, state)


def shard_unban(cfg, ip):
    """Retire `ip` de la liste shardée qui la contient — jamais les autres."""
    state = _load_shard_state(cfg)
    for name, members in state["lists"].items():
        if ip in members:
            members.remove(ip)
            set_iplist_addresses(cfg, members, name=name)
            _save_shard_state(cfg, state)
            return
    logging.warning("%s absente de toutes les IP list shardées, rien à faire", ip)


def shard_start(cfg):
    """Crée la/les listes shardées si besoin et resynchronise depuis
    fail2ban (source de vérité pour cette action précise uniquement).

    Contrairement à ban/unban (1 seule liste touchée par appel), start
    peut réécrire plusieurs listes : c'est une resynchro explicite/rare
    (bootstrap, perte de `_shard_state_path`, dérive), pas le chemin
    critique en fréquence — cohérent avec le comportement déjà accepté
    pour `group` (une création d'IPHost par IP bannie, sans y chercher à
    optimiser davantage).
    """
    state = _load_shard_state(cfg)
    if not state["lists"]:
        _shard_for_new_entry(cfg, state)
        _save_shard_state(cfg, state)

    fail2ban_ips = set(get_banned_ips(cfg))
    seed = cfg["iplist_seed_ip"]
    tracked = {
        ip for members in state["lists"].values() for ip in members if ip != seed
    }

    to_remove = sorted(tracked - fail2ban_ips)
    to_add = sorted(fail2ban_ips - tracked)

    for ip in to_remove:
        for name, members in state["lists"].items():
            if ip in members:
                members.remove(ip)
                set_iplist_addresses(cfg, members, name=name)
                break

    for ip in to_add:
        active = _shard_for_new_entry(cfg, state)
        state["lists"][active].append(ip)
        set_iplist_addresses(cfg, state["lists"][active], name=active)

    _save_shard_state(cfg, state)


def push_from_fail2ban(cfg, ips):
    """Écrase l'état XGS (group et/ou iplist) avec la liste fail2ban.

    Aucune lecture de l'état XGS actuel : on pousse la liste calculée,
    point. group -> HostList complète (noms dérivés des IP) ; iplist ->
    ListOfIPAddresses complète (IP brutes). Utilisé par ban/unban/start :
    la différence, c'est que fail2ban a déjà mis à jour sa propre liste
    avant l'appel (ip en plus pour ban, en moins pour unban, liste
    complète pour start), donc ce même push produit le bon résultat.

    Toujours exécuté (pas de cache d'état) — voir _ip_activity_lock()
    pour la seule protection contre les appels redondants (collision en
    vol sur la même IP). Un push "inutile" (contenu identique au
    précédent) corrige au passage toute dérive éventuelle côté XGS.
    """
    if cfg["group"]:
        hosts = [host_name_for_ip(ip, cfg["prefix"]) for ip in ips]
        set_group_hosts(cfg, hosts)
    if cfg["iplist"]:
        set_iplist_addresses(cfg, ips)
    return ips


def ban(cfg, ip):
    with _ip_activity_lock(cfg, ip) as acquired:
        if not acquired:
            logging.info("ban %s : déjà en cours (autre appel), abandonné", ip)
            return
        if cfg["group"] or cfg["iplist"]:
            ips = get_banned_ips(cfg)
            if cfg["group"]:
                name = host_name_for_ip(ip, cfg["prefix"])
                create_iphost(cfg, name, ip)
            push_from_fail2ban(cfg, ips)
        if cfg["iplist_prefix"]:
            shard_ban(cfg, ip)


def unban(cfg, ip):
    with _ip_activity_lock(cfg, ip) as acquired:
        if not acquired:
            logging.info("unban %s : déjà en cours (autre appel), abandonné", ip)
            return
        logging.info("unban %s : resync depuis fail2ban (jail %s)", ip, ",".join(cfg["jail"]))
        if cfg["group"] or cfg["iplist"]:
            ips = get_banned_ips(cfg)
            push_from_fail2ban(cfg, ips)
        if cfg["iplist_prefix"]:
            shard_unban(cfg, ip)


def start(cfg):
    """Comme ban, mais pour toutes les IP actuellement bannies par fail2ban.

    Utile au démarrage (service qui vient de (re)démarrer, jail avec des
    bans déjà en cours) : crée l'IPHost manquant pour CHAQUE IP bannie
    (idempotent, pas seulement la dernière comme ban) avant de pousser la
    liste complète — comble le vide documenté dans les limites connues
    (une IP déjà bannie avant le premier ban n'a pas d'IPHost). Avec
    `iplist_prefix` : crée aussi la/les listes shardées si besoin (voir
    shard_start).
    """
    if cfg["group"] or cfg["iplist"]:
        ips = get_banned_ips(cfg)
        if cfg["group"]:
            for ip in ips:
                name = host_name_for_ip(ip, cfg["prefix"])
                create_iphost(cfg, name, ip)
        push_from_fail2ban(cfg, ips)
    if cfg["iplist_prefix"]:
        shard_start(cfg)


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
    """IPHost préfixés par ce script, absents du groupe ET plus bannis
    par fail2ban.

    "Absent du groupe" seul ne suffit pas à qualifier un orphelin : si un
    `ban` a créé l'IPHost puis échoué avant de l'ajouter au groupe (blip
    réseau, XGS temporairement occupé...), fail2ban considère toujours
    l'IP bannie mais son IPHost n'est pas (encore) dans le groupe — le
    supprimer casserait le prochain ban/unban (le Set du groupe
    référencerait un IPHost inexistant -> 500 "Operation could not be
    performed on Entity", confirmé en réel, voir CHANGELOG). Un IPHost
    n'est donc candidat que s'il est absent du groupe ET que son IP n'est
    plus dans `get_banned_ips(cfg)`.

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
    banned_names = {host_name_for_ip(ip, prefix) for ip in get_banned_ips(cfg)}
    return sorted(all_names - used - banned_names)


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

    IMPORTANT : ne touche PAS à l'état de fail2ban. Si des IP sont encore
    bannies côté fail2ban au moment du flush, leurs IPHost sont supprimés
    (vacuum) mais fail2ban continue de les considérer bannies. Un `ban`
    normal qui suit ne recrée l'IPHost QUE pour la nouvelle IP (pas pour
    celles déjà bannies), donc le Set du groupe référence alors des noms
    d'IPHost inexistants -> échec 500 "Operation could not be performed
    on Entity" côté XGS (confirmé en réel, voir CHANGELOG). TOUJOURS
    lancer `start` juste après un `flush` pour recréer les IPHost
    manquants et resynchroniser proprement avant de reprendre ban/unban.
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


def list_shards(cfg):
    """Affiche l'état local suivi des listes shardées (pas d'appel Sophos
    — reflète ce que ce script croit avoir poussé, pas une lecture live
    de l'XGS ; en cas de doute, `start` resynchronise depuis fail2ban)."""
    state = _load_shard_state(cfg)
    if not state["lists"]:
        print(f"aucune IP list shardée (préfixe {cfg['iplist_prefix']}) — lancer `start`")
        return
    for name, members in sorted(state["lists"].items()):
        marker = " (active)" if name == state.get("active") else ""
        print(f"{name}{marker}: {len(members)} entrée(s)")
        for ip in members:
            tag = " [seed]" if ip == cfg["iplist_seed_ip"] else ""
            print(f"  {ip}{tag}")


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
    print(f"fail2ban (jail(s) {','.join(cfg['jail'])}): {len(fail2ban_ips)} IP bannie(s)")

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
  jail        = sshd             # requis pour ban/unban/sync : jail(s)
                                  #   fail2ban interrogée(s) via
                                  #   fail2ban-client. Plusieurs jails :
                                  #   séparées par des virgules, ex
                                  #   "sshd,nginx-http-auth" — une IP
                                  #   bannie dans au moins une des jails
                                  #   est incluse (union), une seule
                                  #   requête fail2ban-client par jail
  fail2ban_client = fail2ban-client  # optionnel, chemin/nom du binaire

  # alternative à iplist : familles de listes shardées (limite Sophos :
  # 1000 IP par IP list). Mutuellement exclusif avec iplist.
  iplist_prefix      = Fail2Ban-List-  # optionnel, active le sharding
  iplist_seed_ip     = 192.0.2.1       # requis avec iplist_prefix : IP
                                        #   placeholder (Sophos exige >=1
                                        #   adresse pour créer une liste)
  iplist_max_entries = 1000            # optionnel, défaut 1000 (max
                                        #   Sophos), seuil de création
                                        #   d'une nouvelle liste
  alert_email        = admin@ex.com    # optionnel, mail à la création
                                        #   d'une nouvelle liste shardée
  smtp_host          = localhost       # optionnel, défaut localhost
  smtp_port          = 25              # optionnel, défaut 25

Au moins une des clés group/iplist/iplist_prefix est requise. group et
iplist(_prefix) sont indépendants et peuvent être renseignés ensemble :
l'IP est alors ajoutée/retirée des deux à chaque ban/unban. iplist et
iplist_prefix sont mutuellement exclusifs entre eux.

Mode shardé (iplist_prefix) : chaque ban/unban ne touche qu'UNE seule
liste (celle qui contient l'IP pour unban ; la liste "active" — la plus
récente non pleine — pour ban), jamais les autres : pas de décalage en
cascade quand une IP est retirée d'une liste antérieure. Une fois la
liste active à `iplist_max_entries`, une nouvelle liste est créée
(seedée avec `iplist_seed_ip`, qui y reste en permanence) et un mail est
envoyé à `alert_email` si configuré (sinon juste un warning loggé).
`start` crée aussi la/les listes shardées si absentes et resynchronise
depuis fail2ban (source de vérité pour cette action précise).

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
  sophos_fw_block.py start --jail sshd,nginx-http-auth,nginx-botsearch
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
        "flush (vide le groupe puis vacuum, sans interroger fail2ban -- "
        "TOUJOURS suivre d'un start), "
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
        "--jail",
        help="surcharge la/les jail(s) fail2ban définie(s) dans la config "
        "(une ou plusieurs, séparées par des virgules)",
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

    ip = None
    t0 = time.monotonic()
    try:
        ip = validate_ip(args.ip) if args.ip else None
        cfg = load_config(args.config)
        if args.group:
            cfg["group"] = args.group
        if args.iplist:
            cfg["iplist"] = args.iplist
        if args.prefix:
            cfg["prefix"] = args.prefix
        if args.jail:
            cfg["jail"] = parse_jails(args.jail)

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
            if cfg["iplist_prefix"]:
                list_shards(cfg)
    except (Exception, SystemExit) as exc:
        # SystemExit inclus : plusieurs fonctions (validate_ip, load_config,
        # vacuum/flush) lèvent `raise SystemExit("message")` pour un arrêt
        # propre avec message clair — SystemExit hérite de BaseException,
        # pas Exception, donc `except Exception` seul le laisserait passer
        # sans jamais toucher logging.error()/syslog. KeyboardInterrupt
        # reste volontairement non capté ici (Ctrl-C ne doit pas logguer).
        logging.error("%s%s: %s", args.action, f" {ip}" if ip else "", exc)
        sys.exit(1)
    finally:
        if DEBUG_TIMING:
            logging.debug("[timing] action %s : %.3fs au total", args.action, time.monotonic() - t0)


if __name__ == "__main__":
    main()

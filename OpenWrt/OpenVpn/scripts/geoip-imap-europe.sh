#!/bin/sh
# Route le trafic IMAP (143/993) selon l'origine géographique via 2 port
# forwards conditionnels (UCI firewall "ipset" + "redirect", nativement
# supporté par fw4 — vérifié dans redirect.uc du paquet firewall4) :
#   - IP d'Europe (UE27+EEE+UK+CH)  -> serveur mail réel
#   - reste du monde                -> serveur tarpit (faux banner + silence)
# + overrides manuels (manual_allow/manual_block, jamais touchés par ce
#   script une fois créés — éditables ensuite en CLI ou LuCI > Firewall > IP Sets).
# Remplace l'ancienne approche banIP (bloquait via forward-drop après DNAT,
# incompatible avec un tarpit : le drop aurait aussi tué le trafic vers le
# serveur tarpit). Idempotent, sauf les ipsets manuels (créés vides une
# seule fois, jamais réinitialisés).

set -e

EU_CODES="at be bg hr cy cz dk ee fi fr de gr hu ie it lv lt lu mt nl pl pt ro sk si es se is li no gb ch"
IPDENY_V4="https://www.ipdeny.com/ipblocks/data/aggregated/"
IMAP_PORTS="143 993"

# --- À RENSEIGNER avant exécution ---
REAL_MAIL_IP="CHANGEME_ip_lan_serveur_mail_reel"
TARPIT_IP="CHANGEME_ip_lan_serveur_tarpit"
DEST_ZONE="lan"
# -------------------------------------

if [ "$REAL_MAIL_IP" = "CHANGEME_ip_lan_serveur_mail_reel" ] || [ "$TARPIT_IP" = "CHANGEME_ip_lan_serveur_tarpit" ]; then
    echo "Erreur : renseigner REAL_MAIL_IP et TARPIT_IP en tête de script avant de lancer." >&2
    exit 1
fi

# 0. Neutralise l'ancienne config banIP (feed "country" + custom.feeds) si
#    présente — un reliquat bloquerait aussi le trafic vers le tarpit,
#    puisqu'il matche sur le port sans savoir que la destination a changé.
if [ -f /etc/banip/banip.custom.feeds ] && grep -q '"country"' /etc/banip/banip.custom.feeds 2>/dev/null; then
    rm -f /etc/banip/banip.custom.feeds
fi
if uci -q get banip.global.ban_feed 2>/dev/null | grep -q country; then
    uci -q delete banip.global.ban_feed
    uci -q delete banip.global.ban_country
    uci commit banip
    /etc/init.d/banip reload 2>/dev/null || true
fi
sed -i '\#/etc/init.d/banip reload#d' /etc/crontabs/root 2>/dev/null || true

# 1. CIDR IPv4 des pays européens (recalculé à chaque run, set "léger" —
#    32 pays seulement, pas 180+).
ALL_CIDR=""
for c in $EU_CODES; do
    ZONE=$(curl -fsS "${IPDENY_V4}${c}-aggregated.zone") || {
        echo "Attention : échec récupération zone '$c' (ignoré)" >&2
        continue
    }
    ALL_CIDR="$ALL_CIDR $ZONE"
done

if [ -z "$ALL_CIDR" ]; then
    echo "Erreur : aucune donnée CIDR récupérée (réseau ?)" >&2
    exit 1
fi

# 2. Ipset "eu_v4" : entièrement recalculé à chaque run.
uci set firewall.geoimap_eu_v4=ipset
uci set firewall.geoimap_eu_v4.name='geoimap_eu_v4'
uci set firewall.geoimap_eu_v4.family='ipv4'
uci set firewall.geoimap_eu_v4.storage='hash'
uci set firewall.geoimap_eu_v4.match='src_net'
uci set firewall.geoimap_eu_v4.maxelem='65536'
uci -q delete firewall.geoimap_eu_v4.entry
for cidr in $ALL_CIDR; do
    uci add_list firewall.geoimap_eu_v4.entry="$cidr"
done

# 3. Ipsets manuels : créés vides une seule fois, jamais réinitialisés
#    (overrides persistants — LuCI > Firewall > IP Sets, ou uci add_list).
for name in geoimap_manual_allow_v4 geoimap_manual_block_v4; do
    if ! uci -q get firewall."$name" >/dev/null 2>&1; then
        uci set firewall."$name"=ipset
        uci set firewall."$name".name="$name"
        uci set firewall."$name".family='ipv4'
        uci set firewall."$name".storage='hash'
        uci set firewall."$name".match='src_ip'
        uci set firewall."$name".maxelem='1024'
    fi
done

# 4. Règles par port (ordre = priorité fw4 : manual_allow avant noneu,
#    sinon un override sur une IP non-EU serait quand même tarpitté).
for PORT in $IMAP_PORTS; do
    # blocage manuel — filter, indépendant du NAT, toujours actif
    R="geoimap_block_$PORT"
    uci set firewall."$R"=rule
    uci set firewall."$R".name="GeoIMAP block manuel $PORT"
    uci set firewall."$R".src='wan'
    uci set firewall."$R".proto='tcp'
    uci set firewall."$R".dest_port="$PORT"
    uci set firewall."$R".ipset='geoimap_manual_block_v4 src'
    uci set firewall."$R".target='DROP'

    # override manuel -> serveur réel (doit précéder la règle "reste du monde")
    R="geoimap_allow_$PORT"
    uci set firewall."$R"=redirect
    uci set firewall."$R".name="GeoIMAP allow manuel $PORT"
    uci set firewall."$R".src='wan'
    uci set firewall."$R".src_dport="$PORT"
    uci set firewall."$R".proto='tcp'
    uci set firewall."$R".ipset='geoimap_manual_allow_v4 src'
    uci set firewall."$R".dest="$DEST_ZONE"
    uci set firewall."$R".dest_ip="$REAL_MAIL_IP"
    uci set firewall."$R".dest_port="$PORT"
    uci set firewall."$R".target='DNAT'

    # Europe -> serveur réel
    R="geoimap_eu_$PORT"
    uci set firewall."$R"=redirect
    uci set firewall."$R".name="GeoIMAP Europe $PORT"
    uci set firewall."$R".src='wan'
    uci set firewall."$R".src_dport="$PORT"
    uci set firewall."$R".proto='tcp'
    uci set firewall."$R".ipset='geoimap_eu_v4 src'
    uci set firewall."$R".dest="$DEST_ZONE"
    uci set firewall."$R".dest_ip="$REAL_MAIL_IP"
    uci set firewall."$R".dest_port="$PORT"
    uci set firewall."$R".target='DNAT'

    # reste du monde -> tarpit
    R="geoimap_noneu_$PORT"
    uci set firewall."$R"=redirect
    uci set firewall."$R".name="GeoIMAP non-Europe $PORT"
    uci set firewall."$R".src='wan'
    uci set firewall."$R".src_dport="$PORT"
    uci set firewall."$R".proto='tcp'
    uci set firewall."$R".ipset='!geoimap_eu_v4 src'
    uci set firewall."$R".dest="$DEST_ZONE"
    uci set firewall."$R".dest_ip="$TARPIT_IP"
    uci set firewall."$R".dest_port="$PORT"
    uci set firewall."$R".target='DNAT'
done

uci commit firewall
/etc/init.d/firewall reload

# 5. Cron quotidien : rafraîchit uniquement le set "eu_v4" (les CIDR bougent
#    dans le temps) — relance ce script, qui ne touche jamais les ipsets
#    manuels une fois créés.
#    IMPORTANT : /tmp est un tmpfs (vidé au reboot) — le script doit tourner
#    depuis un chemin persistant (/usr/bin) pour que ce cron survive un reboot.
SCRIPT_PATH="/usr/bin/geoip-imap-europe.sh"
if [ "$(readlink -f "$0" 2>/dev/null)" != "$SCRIPT_PATH" ]; then
    echo "Attention : script pas lancé depuis $SCRIPT_PATH — copie-le là pour que le cron persiste au reboot (cp $0 $SCRIPT_PATH && chmod +x $SCRIPT_PATH)." >&2
fi
CRON_LINE="0 4 * * * $SCRIPT_PATH"
CRONTAB="/etc/crontabs/root"
touch "$CRONTAB"
if ! grep -qF "$SCRIPT_PATH" "$CRONTAB"; then
    echo "$CRON_LINE" >> "$CRONTAB"
    /etc/init.d/cron restart
fi

echo "OK : $(echo $ALL_CIDR | wc -w) CIDR européens dans geoimap_eu_v4."
echo "Vérifier : nft list set inet fw4 geoimap_eu_v4"
echo "Overrides : uci add_list firewall.geoimap_manual_allow_v4.entry='1.2.3.4' ; uci add_list firewall.geoimap_manual_block_v4.entry='5.6.7.8' ; uci commit firewall ; /etc/init.d/firewall reload"

#!/bin/sh
# Restreint l'accès IMAP (143/993, forward DNAT inclus) aux IP d'Europe
# (UE27 + EEE + UK + CH) via banIP. Bloque tous les autres pays.
# Idempotent : peut être relancé sans risque (recalcule et réécrit la conf).

set -e

EU_CODES="at be bg hr cy cz dk ee fi fr de gr hu ie it lv lt lu mt nl pl pt ro sk si es se is li no gb ch"
IPDENY_INDEX="https://www.ipdeny.com/ipblocks/data/aggregated/"
CUSTOM_FEEDS="/etc/banip/banip.custom.feeds"
IMAP_PORTS="143 993"

# 1. banIP (+ WUI LuCI) installé ?
if ! opkg list-installed | grep -q "^banip "; then
    echo "Installation banIP..."
    opkg update
    opkg install banip
fi
if ! opkg list-installed | grep -q "^luci-app-banip "; then
    echo "Installation luci-app-banip..."
    opkg install luci-app-banip
fi

# 2. Liste complète des codes pays connus d'ipdeny (source de données banIP)
ALL_CODES=$(curl -fsS "$IPDENY_INDEX" | grep -oE '[a-z]{2}-aggregated\.zone' | sed 's/-aggregated\.zone//' | sort -u)

if [ -z "$ALL_CODES" ]; then
    echo "Erreur : impossible de récupérer la liste des pays ipdeny (réseau ?)" >&2
    exit 1
fi

# 3. Pays non-européens = tous - EU_CODES
NON_EU=""
for c in $ALL_CODES; do
    case " $EU_CODES " in
        *" $c "*) ;;
        *) NON_EU="$NON_EU $c" ;;
    esac
done

# 4. Feed "country" custom, restreint aux ports IMAP.
#    ATTENTION : banip.custom.feeds REMPLACE tout banip.feeds (pas de merge),
#    donc on doit répéter tous les champs de l'entrée d'origine, pas juste "flag".
mkdir -p /etc/banip
cat > "$CUSTOM_FEEDS" <<EOF
{
    "country": {
        "url_4": "https://www.ipdeny.com/ipblocks/data/aggregated/",
        "url_6": "https://www.ipdeny.com/ipv6/ipaddresses/aggregated/",
        "rule": "feed 1",
        "chain": "in",
        "flag": "tcp $IMAP_PORTS",
        "descr": "country blocks (IMAP Europe allow-list)"
    }
}
EOF

# 5. Config banIP : blocklist = tous les pays non-européens
uci set banip.global=banip
uci set banip.global.ban_enabled='1'
uci -q delete banip.global.ban_feed
uci add_list banip.global.ban_feed='country'
uci -q delete banip.global.ban_country
for c in $NON_EU; do
    uci add_list banip.global.ban_country="$c"
done
uci commit banip

# 6. Application
/etc/init.d/banip enable
/etc/init.d/banip reload

echo "OK : $(echo $NON_EU | wc -w) pays non-européens bloqués sur ports $IMAP_PORTS."
echo "Vérifier : nft list set inet banIP country"
echo "Logs     : logread | grep -i banip"

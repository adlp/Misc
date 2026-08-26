# GeoIP : router IMAP Europe / reste du monde vers 2 destinations

## Contexte

Trafic IMAP (143/993) entrant sur le WAN du routeur OpenWRT
(MsConceptAtelier). Objectif : les connexions depuis l'Europe (UE27 + EEE +
UK + CH) sont forwardées vers le vrai serveur mail interne ; toutes les
autres vers un serveur tarpit (faux banner IMAP puis silence, sur une
machine LAN dédiée — voir sous-projet Mail). Plus overrides manuels
(IP toujours autorisées / toujours bloquées, indépendants du pays).

## Historique : pourquoi pas banIP

Une première version (voir git log) utilisait banIP pour bloquer (`drop`)
tout le trafic IMAP non-européen après DNAT vers le serveur réel. Ça
fonctionnait pour un simple blocage, mais **incompatible avec un tarpit** :
banIP filtre au stade *forward* (après que le NAT ait déjà choisi la
destination), donc si le NAT envoie le trafic non-EU vers le serveur
tarpit, la règle banIP le droppe quand même avant qu'il n'atteigne le
tarpit — le tarpit ne recevrait jamais rien.

Abandonné au profit d'un routage conditionnel **au niveau du NAT
lui-même** (prerouting), qui choisit la destination selon la source —
pas de conflit possible avec un filtre après-coup.

## Architecture retenue

Vérifié dans les sources réelles de `firewall4` (pas supposé) :
`config redirect` (le "Port Forward" standard OpenWrt/LuCI) supporte
nativement une option `ipset`, avec inversion (`!nomset`) — exactement
comme `config rule` (déjà utilisé par des outils comme banIP). Donc tout
se fait en UCI standard, sans nftables écrit à la main :

- `firewall.geoimap_eu_v4` (`config ipset`) : CIDR IPv4 des 32 pays
  européens retenus (UE27+EEE+UK+CH), recalculés à chaque exécution du
  script depuis ipdeny.com. Set volontairement **petit** (32 pays, pas
  ~180+) — contrainte explicite du besoin ("alléger le système").
- `firewall.geoimap_eu_<port>` (`config redirect`, `ipset='geoimap_eu_v4
  src'`) : DNAT vers le serveur mail réel.
- `firewall.geoimap_noneu_<port>` (`config redirect`, `ipset
  ='!geoimap_eu_v4 src'`, inversé) : DNAT vers le serveur tarpit.
- `firewall.geoimap_manual_allow_v4` / `geoimap_manual_block_v4`
  (`config ipset`, vides à la création, **jamais réinitialisés** par le
  script) : overrides persistants.
  - `geoimap_manual_allow_<port>` (`config redirect`, priorité avant
    `geoimap_noneu_<port>` — l'ordre des sections UCI = ordre
    d'évaluation fw4) : une IP non-européenne explicitement autorisée
    part quand même vers le serveur réel.
  - `geoimap_block_<port>` (`config rule`, `target='DROP'`) : filtre
    indépendant du NAT (stade forward), bloque une IP donnée quel que
    soit le pays — pas de contrainte d'ordre avec les redirects (hooks
    différents : NAT en prerouting, ce rule en forward).

Une seule règle par port par catégorie (boucle `for PORT in 143 993`) —
évite de parier sur le support d'une liste de ports dans `src_dport`
d'un `redirect` (non vérifié, donc pas utilisé).

## Installation

```sh
scp scripts/geoip-imap-europe.sh root@MsConceptAtelier:/usr/bin/
ssh root@MsConceptAtelier 'chmod +x /usr/bin/geoip-imap-europe.sh'
```

Éditer en tête du script avant le premier lancement :
- `REAL_MAIL_IP` — IP LAN du serveur mail réel
- `TARPIT_IP` — IP LAN du serveur tarpit (sous-projet Mail)
- `DEST_ZONE` — zone firewall de destination (`lan` par défaut)

```sh
ssh root@MsConceptAtelier '/usr/bin/geoip-imap-europe.sh'
```

Idempotent — sauf les ipsets manuels (créés vides une seule fois, jamais
réinitialisés, donc relancer le script ne perd pas les overrides ajoutés
entre-temps).

**Important** : lancer depuis `/usr/bin`, pas `/tmp` (tmpfs, vidé au
reboot) — sinon le cron installé pointerait vers un fichier qui
disparaît au redémarrage.

## Overrides manuels

```sh
# Toujours autoriser une IP (même hors Europe) vers le serveur réel
uci add_list firewall.geoimap_manual_allow_v4.entry='203.0.113.5'
uci commit firewall && /etc/init.d/firewall reload

# Toujours bloquer une IP (même si en Europe)
uci add_list firewall.geoimap_manual_block_v4.entry='198.51.100.9'
uci commit firewall && /etc/init.d/firewall reload
```

Éditables aussi en LuCI : Network → Firewall → IP Sets.

## Vérification

```sh
# Contenu du set européen
nft list set inet fw4 geoimap_eu_v4

# Règles de redirection effectivement posées
nft list chain inet fw4 dstnat | grep -i geoimap

# Logs firewall
logread | grep -i fw4
```

Tester depuis une IP hors Europe (VPN, proxy) que la connexion IMAP part
bien vers le tarpit (faux banner puis silence), et depuis une IP
européenne qu'elle atteint bien le vrai serveur.

## Mise à jour régulière

- **CIDR européens** (`geoimap_eu_v4`) : recalculés chaque jour via cron
  installé par le script (`0 4 * * * /usr/bin/geoip-imap-europe.sh`,
  ~32 requêtes HTTP vers ipdeny). Rejoue tout le script (idempotent),
  ne touche jamais les ipsets/overrides manuels.
- **Périmètre "Europe"** (`EU_CODES` dans le script) : quasi statique,
  ajuster manuellement le script si le périmètre change, puis relancer.
- **Overrides manuels** : jamais touchés automatiquement, gérés à la main
  (CLI ou LuCI) indéfiniment.

## Limites connues

- IPv4 uniquement (décision explicite — IPv6 jugé non pertinent sur ce WAN).
- Premier run : ~32 requêtes HTTP séquentielles vers ipdeny (léger,
  quelques secondes à quelques dizaines de secondes).
- Le tarpit lui-même (faux banner IMAP + silence) est un composant du
  sous-projet Mail, pas de celui-ci — le routeur ne fait que le routage
  conditionnel par source.

## Rollback

```sh
for PORT in 143 993; do
    for R in block allow eu noneu; do
        uci -q delete firewall.geoimap_${R}_${PORT}
    done
done
uci -q delete firewall.geoimap_eu_v4
uci -q delete firewall.geoimap_manual_allow_v4
uci -q delete firewall.geoimap_manual_block_v4
uci commit firewall
/etc/init.d/firewall reload
sed -i '\#geoip-imap-europe.sh#d' /etc/crontabs/root
/etc/init.d/cron restart
```

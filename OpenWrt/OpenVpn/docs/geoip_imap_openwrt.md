# GeoIP : restreindre IMAP à l'Europe sur OpenWRT

## Contexte

Trafic IMAP (143/993) forwardé (DNAT) depuis le WAN du routeur OpenWRT
(MsConceptAtelier) vers un serveur mail interne. Objectif : bloquer toute
connexion IMAP entrante qui ne vient pas d'Europe (UE27 + EEE + UK + CH),
sans toucher aux autres services exposés (OpenVPN, admin, etc.).

## Choix technique : banIP + feed custom scopé port

**Vérifié sur les sources réelles du paquet** (openwrt/packages,
`net/banip/files/`), pas supposé :

- `ban_country` est **exclusivement une blocklist**. Il n'existe **aucune**
  option `ban_country_allow` ou équivalent pour en faire une allow-list.
  → Pour "n'autoriser que l'Europe", on liste tous les pays **non**
  européens en blocklist (résultat identique).
- Le feed `country` par défaut n'a pas de restriction de port : il
  s'applique à tout le trafic entrant (input WAN + forward WAN, donc les
  flux DNAT aussi). Pour le limiter aux ports IMAP, il faut redéfinir le
  feed via `/etc/banip/banip.custom.feeds` avec un champ `"flag": "tcp 143
  993"`.
- **Piège** : `banip.custom.feeds` **remplace entièrement**
  `banip.feeds` (`f_getfeed()` charge l'un ou l'autre, jamais les deux —
  pas de merge). Il faut donc réécrire l'entrée `country` au complet
  (`url_4`, `url_6`, `rule`, `chain`, `descr`) et pas seulement ajouter
  `flag`, sous peine de casser le feed silencieusement (= IMAP resterait
  ouvert à tous, échec silencieux).
- Les données pays viennent de ipdeny.com (`{code}-aggregated.zone`), un
  fichier par code ISO 3166-1 alpha-2. Pas d'agrégat "continent" dans ce
  flux → la liste "non-Europe" est calculée dynamiquement depuis l'index
  ipdeny (pas de liste figée qui pourrait devenir incomplète/obsolète).

## Périmètre "Europe" retenu

UE27 + EEE (Islande, Norvège, Liechtenstein) + Royaume-Uni + Suisse (32
codes). Exclut volontairement Russie, Turquie, Ukraine, Balkans hors-UE.
Codes dans `EU_CODES` en tête du script — à ajuster si le périmètre doit
changer.

## Installation

```sh
scp scripts/geoip-imap-europe.sh root@MsConceptAtelier:/tmp/
ssh root@MsConceptAtelier '/tmp/geoip-imap-europe.sh'
```

Le script :
1. Installe `banip` + `luci-app-banip` (WUI) si absents.
2. Récupère la liste des codes pays connus d'ipdeny.
3. Calcule "tous les pays sauf Europe".
4. Écrit `/etc/banip/banip.custom.feeds` (feed `country` scopé `tcp 143 993`).
5. Configure `/etc/config/banip` (`ban_feed=country`, `ban_country=<non-EU>`).
6. Active et recharge banIP.

Idempotent, relançable sans risque (recalcule tout à chaque exécution).

## Vérification

```sh
# Set nftables peuplé ?
nft list set inet banIP country

# Règle limitée aux bons ports ?
nft list chain inet banIP wan-forward | grep -i "143\|993"

# Logs banIP
logread | grep -i banip
```

Tester depuis une IP hors Europe (VPN, proxy) que la connexion IMAP est
bien refusée, et depuis une IP européenne qu'elle passe toujours.

## Accès WUI (LuCI)

`luci-app-banip` installé par le script → Services → banIP dans LuCI.
Vérifié sur les sources réelles de `luci-app-banip` :

- Visible/éditable en WUI : `ban_enabled`, `ban_feed`, `ban_country` (onglet
  Countries). ~180 pays cochés = liste longue mais fonctionnelle.
- **Pas** visible/éditable en WUI : le contenu de
  `/etc/banip/banip.custom.feeds` (restriction port 143/993). La WUI lit ce
  fichier uniquement pour peupler la liste des feeds disponibles, elle ne
  propose aucun éditeur pour son contenu (`flag`, `url_4`, etc.) et ne le
  réécrit jamais → aucun risque qu'un save WUI écrase l'override du script.
  Toute modification du scope port reste CLI (relancer le script après
  avoir ajusté `IMAP_PORTS`).

## Limites connues

- Premier sync = ~180 requêtes HTTP (une par pays non-EU) vers ipdeny :
  peut être lent sur routeur contraint, prévoir plusieurs minutes.
- Si ipdeny est indisponible lors d'un refresh banIP planifié, ce pays
  garde ses anciennes données (pas de coupure du service, mais IP
  potentiellement obsolètes) — surveiller les logs.
- Périmètre "Europe" codé en dur (`EU_CODES`) : pas d'ajustement
  automatique si un pays change de statut (ex. adhésion/sortie UE).

## Rollback

```sh
uci -q delete banip.global.ban_country
uci -q delete banip.global.ban_feed
rm -f /etc/banip/banip.custom.feeds
uci commit banip
/etc/init.d/banip reload
# ou complètement désactiver :
/etc/init.d/banip stop
/etc/init.d/banip disable
```

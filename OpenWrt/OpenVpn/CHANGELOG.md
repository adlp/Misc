# Changelog

## geoip-imap-europe — 2026-08-26

Refonte complète de l'approche GeoIP IMAP — abandon de banIP au profit
d'un routage conditionnel au niveau NAT.

### Changed
- `scripts/geoip-imap-europe.sh` réécrit : au lieu de bloquer (`drop`)
  le trafic non-européen après DNAT via banIP, pose désormais **2 port
  forwards conditionnels** — Europe → serveur mail réel, reste du monde
  → serveur tarpit (LAN, sous-projet Mail). Mécanisme : `config redirect`
  supporte nativement l'option `ipset` (avec inversion `!nom`), vérifié
  dans les sources réelles de `firewall4` (`redirect.uc`) — donc 100%
  UCI standard, LuCI-éditable (Firewall > Port Forwards + IP Sets), sans
  nftables écrit à la main.
- Raison de l'abandon de banIP (documentée dans
  `docs/geoip_imap_openwrt.md`) : banIP filtre au stade *forward*, après
  que le NAT a déjà choisi la destination — si le NAT envoie le trafic
  non-EU vers un serveur tarpit, banIP le droppe quand même avant qu'il
  n'atteigne ce tarpit. Le routage conditionnel au stade NAT
  (prerouting) élimine ce conflit par construction.
- Set européen volontairement réduit à 32 pays (UE27+EEE+UK+CH) au lieu
  de lister ~180+ pays non-européens comme dans la version banIP — plus
  léger (moins de requêtes ipdeny, set plus petit), motivé par
  l'hypothèse qu'il y a plus d'IP non-EU que EU dans le monde.

### Added
- Overrides manuels persistants : `geoimap_manual_allow_v4` /
  `geoimap_manual_block_v4` (ipsets vides à la création, jamais
  réinitialisés par le script) — une IP ajoutée à `manual_allow` part
  vers le serveur réel même si non-européenne (redirect positionné avant
  la règle générique "reste du monde" — l'ordre des sections UCI fait la
  priorité fw4) ; une IP dans `manual_block` est droppée quel que soit
  le pays (`config rule` côté forward, indépendant du NAT donc pas de
  contrainte d'ordre avec les redirects).
- Garde-fou : le script neutralise automatiquement l'ancienne config
  banIP (feed `country` + `banip.custom.feeds`) si présente, et retire
  l'ancien cron `banip reload` — sinon la règle banIP resterait active
  et casserait silencieusement le trafic vers le tarpit.
- Détection du chemin d'exécution : avertit si lancé hors `/usr/bin`
  (le cron installé pointerait vers un fichier disparaissant au reboot
  si laissé sous `/tmp`, qui est un tmpfs).

### Removed
- Dépendance à `banip`/`luci-app-banip` pour cette fonctionnalité (les
  paquets peuvent rester installés pour un autre usage, mais ne sont
  plus requis ni configurés par ce script).

## geoip-imap-europe — 2026-08-25 (2)

### Added
- `scripts/geoip-imap-europe.sh` : ajout d'un cron quotidien
  (`/etc/crontabs/root`, 4h) qui appelle `/etc/init.d/banip reload` —
  banIP n'installe aucun cron lui-même (vérifié dans le README officiel),
  et seul `reload` retélécharge réellement les feeds (check ETag,
  `start`/`restart` ne font que restaurer le cache). Idempotent (n'ajoute
  la ligne que si absente). `docs/geoip_imap_openwrt.md` : nouvelle
  section distinguant la fréquence de mise à jour des plages IP par pays
  (quotidienne, via ce cron) de celle du périmètre pays "Europe" dans
  `EU_CODES` (quasi statique, réexécution manuelle du script suffisante).

## geoip-imap-europe — 2026-08-25

### Added
- `scripts/geoip-imap-europe.sh` : installe `banip` + `luci-app-banip`,
  puis restreint le trafic IMAP (143/993, y compris forward DNAT vers le
  serveur mail interne) aux IP d'Europe (UE27+EEE+UK+CH). Idempotent.
  Approche : `ban_country` de banIP est une blocklist pure (pas d'option
  allow-list pour les pays, vérifié sur les sources réelles du paquet) —
  le script calcule donc dynamiquement "tous les pays sauf Europe" depuis
  l'index ipdeny (pas de liste figée qui pourrait devenir incomplète) et
  les passe en blocklist, résultat équivalent à un allow-list Europe.
  Le scope port (143/993 uniquement, pas tout le WAN) est obtenu en
  redéfinissant le feed `country` dans `/etc/banip/banip.custom.feeds`
  avec `"flag": "tcp 143 993"` — ce fichier **remplace entièrement**
  `banip.feeds` (pas de merge, confirmé dans `banip-functions.sh`), donc
  l'entrée `country` y est réécrite au complet (`url_4`/`url_6`/`rule`/
  `chain`) plutôt que d'ajouter seulement `flag`, pour éviter de casser
  silencieusement le feed (= IMAP resterait ouvert à tous sans erreur
  visible).
- `docs/geoip_imap_openwrt.md` : contexte, justification technique
  (vérifications faites sur le code source banIP), installation,
  vérification, accès WUI LuCI (quoi est éditable en WUI vs CLI-only),
  limites connues, rollback.

## Initialisation du projet — 2026-08-25

Premier changelog du sous-projet — documente l'état déjà en place avant
cette date (pas de nouveaux fichiers).

### Added
- `docs/openvpn_openwrt_setup.md` : installation serveur OpenVPN sur
  OpenWRT 23.05.3 (paquets, réseau/firewall UCI, PKI via `openssl` direct
  — easy-rsa 3.0.8 buggé avec OpenSSL 3.x —, config serveur, génération
  `.ovpn` client).
- `docs/openvpn_auth_doc.md` : authentification mixte — groupe admin
  (certificat individuel + login/mot de passe) et groupe user (certificat
  partagé + login/mot de passe), limitation des connexions simultanées.
- `scripts/openvpn_client_manager.sh` (`ovpn-client`) : gestion des
  clients (création admin/partagés, ajout utilisateurs, génération
  `.ovpn`, listing).
- `scripts/check-auth.sh` : `auth-user-pass-verify` OpenVPN — vérifie
  login/mot de passe (hash SHA256) et, pour le groupe admin, la
  correspondance certificat/CN.
- `scripts/client-connect.sh` : `client-connect` OpenVPN — limite le
  nombre de connexions simultanées par utilisateur via `openvpn-status.log`.

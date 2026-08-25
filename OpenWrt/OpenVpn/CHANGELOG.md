# Changelog

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

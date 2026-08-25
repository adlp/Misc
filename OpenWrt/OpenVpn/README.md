# OpenVpn (OpenWRT)

Serveur OpenVPN sur routeur OpenWRT 23.05.3 (MsConceptAtelier) : setup,
authentification mixte certificat+login, gestion des clients, et durcissement
réseau des services exposés (GeoIP).

## Structure

- `docs/openvpn_openwrt_setup.md` — installation complète du serveur OpenVPN
  sur OpenWRT (paquets, firewall, PKI OpenSSL, config serveur, génération
  `.ovpn` client).
- `docs/openvpn_auth_doc.md` — authentification mixte : groupe **admin**
  (certificat individuel + login/mot de passe) et groupe **user** (certificat
  partagé + login/mot de passe), limitation des connexions simultanées.
- `docs/geoip_imap_openwrt.md` — restriction GeoIP du port IMAP (143/993,
  forward DNAT) à l'Europe via banIP, indépendant d'OpenVPN mais hébergé sur
  le même routeur.
- `scripts/openvpn_client_manager.sh` (`ovpn-client`) — gestion des clients :
  création (certificats admin/partagés), ajout d'utilisateurs, génération des
  `.ovpn`, listing.
- `scripts/check-auth.sh` — script `auth-user-pass-verify` OpenVPN : vérifie
  login/mot de passe (SHA256) et, pour le groupe admin, la correspondance
  certificat/CN.
- `scripts/client-connect.sh` — script `client-connect` OpenVPN : limite le
  nombre de connexions simultanées par utilisateur.
- `scripts/geoip-imap-europe.sh` — installe/configure banIP + luci-app-banip
  pour bloquer sur les ports IMAP tout trafic hors Europe (UE27+EEE+UK+CH).

## Infrastructure

Voir `CLAUDE.md` (non commité) pour les chemins/config détaillés du routeur.

## Limitations connues

- easy-rsa 3.0.8 buggé avec OpenSSL 3.x → PKI gérée directement via `openssl`.
- `stty` absent sur OpenWRT → saisies masquées via `read -s`.
- `/usr/local/bin` inexistant → scripts installés dans `/usr/bin`.

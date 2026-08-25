# OpenVPN - Authentification mixte et limitation des connexions

## Vue d'ensemble

Ce document décrit la configuration d'une authentification mixte combinant :
- **Groupe admin** : certificat individuel + mot de passe (double auth)
- **Groupe user** : certificat partagé + mot de passe (auth simple)

```
Groupe admin :  [certificat individuel] + [login/mot de passe]  → sécurité maximale
Groupe user  :  [certificat partagé]   + [login/mot de passe]  → gestion simplifiée
```

---

## 1. Configuration serveur OpenVPN

Modifier `/etc/openvpn/server.conf` :

```conf
port 1194
proto udp
dev tun

ca   /etc/easy-rsa/pki/ca.crt
cert /etc/easy-rsa/pki/issued/server.crt
key  /etc/easy-rsa/pki/private/server.key
dh   /etc/easy-rsa/pki/dh.pem
tls-auth /etc/easy-rsa/pki/ta.key 0

server 10.8.0.0 255.255.255.0

push "route 192.168.1.0 255.255.255.0"
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 192.168.1.1"

keepalive 10 120
cipher AES-256-GCM
persist-key
persist-tun

# Certificat optionnel : obligatoire pour admins, partagé pour users
verify-client-cert optional

# Authentification par login/mot de passe pour tous
auth-user-pass-verify /etc/openvpn/check-auth.sh via-file
script-security 2

# Utiliser le username comme identifiant de session
username-as-common-name

# Autoriser plusieurs connexions avec le même certificat (pour le certificat partagé)
duplicate-cn

# Limitation des connexions simultanées
client-connect /etc/openvpn/client-connect.sh

# Gestion des clients
client-config-dir /etc/openvpn/ccd
crl-verify /etc/easy-rsa/pki/crl.pem

status /tmp/openvpn-status.log
status-version 2
log    /tmp/openvpn.log
verb 3
```

---

## 2. Script de vérification des credentials

Créer `/etc/openvpn/check-auth.sh` :

```bash
#!/bin/sh
# OpenVPN transmet un fichier temporaire contenant :
# ligne 1 : username
# ligne 2 : password

CREDENTIALS_FILE=$1
USERS_FILE="/etc/openvpn/users"
LOG="/tmp/openvpn-auth.log"

USERNAME=$(sed -n '1p' "$CREDENTIALS_FILE")
PASSWORD=$(sed -n '2p' "$CREDENTIALS_FILE")

# Vérifier que l'utilisateur existe
LINE=$(grep "^${USERNAME}:" "$USERS_FILE")

if [ -z "$LINE" ]; then
    echo "$(date) Auth FAILED (unknown user): $USERNAME" >> "$LOG"
    exit 1
fi

HASH=$(echo "$LINE"  | cut -d: -f2)
GROUP=$(echo "$LINE" | cut -d: -f3)

# Vérifier le mot de passe (hash SHA256)
INPUT_HASH=$(echo -n "$PASSWORD" | openssl dgst -sha256 | cut -d' ' -f2)

if [ "$INPUT_HASH" != "$HASH" ]; then
    echo "$(date) Auth FAILED (wrong password): $USERNAME" >> "$LOG"
    exit 1
fi

# Vérification supplémentaire pour le groupe admin :
# le CN du certificat présenté doit correspondre au username
if [ "$GROUP" = "admin" ]; then
    if [ "$common_name" != "$USERNAME" ]; then
        echo "$(date) Auth FAILED (cert mismatch): $USERNAME presented CN=$common_name" >> "$LOG"
        exit 1
    fi
    echo "$(date) Auth OK (admin+cert): $USERNAME" >> "$LOG"
else
    echo "$(date) Auth OK (user+shared cert): $USERNAME" >> "$LOG"
fi

exit 0
```

```bash
chmod 700 /etc/openvpn/check-auth.sh
```

---

## 3. Script de limitation des connexions simultanées

Créer `/etc/openvpn/client-connect.sh` :

```bash
#!/bin/sh
# Appelé par OpenVPN à chaque nouvelle connexion
# $username est fourni par OpenVPN via l'environnement

MAX_CONNECTIONS=1       # Nombre max de connexions simultanées par utilisateur
STATUS_FILE="/tmp/openvpn-status.log"
LOG="/tmp/openvpn-connect.log"

# Compter les connexions actives pour cet utilisateur
COUNT=$(grep "^CLIENT_LIST,${username}," "$STATUS_FILE" 2>/dev/null | wc -l)

if [ "$COUNT" -ge "$MAX_CONNECTIONS" ]; then
    echo "$(date) REFUSED: $username already has $COUNT connection(s)" >> "$LOG"
    exit 1
fi

echo "$(date) ALLOWED: $username ($COUNT active connection(s))" >> "$LOG"
exit 0
```

```bash
chmod 700 /etc/openvpn/client-connect.sh
```

---

## 4. Fichier des utilisateurs

Format : `username:hash_sha256:groupe`

Géré via le script `ovpn-client`, mais voici les opérations manuelles :

```bash
# Ajouter un admin (doit avoir un certificat individuel)
HASH=$(echo -n "motdepasse" | openssl dgst -sha256 | cut -d' ' -f2)
echo "alice:$HASH:admin" >> /etc/openvpn/users

# Ajouter un user (utilise le certificat partagé)
HASH=$(echo -n "motdepasse" | openssl dgst -sha256 | cut -d' ' -f2)
echo "bob:$HASH:user" >> /etc/openvpn/users

# Modifier un mot de passe
NEW_HASH=$(echo -n "nouveaumotdepasse" | openssl dgst -sha256 | cut -d' ' -f2)
sed -i "s|^alice:.*:admin|alice:$NEW_HASH:admin|" /etc/openvpn/users

# Supprimer un utilisateur
sed -i "/^bob:/d" /etc/openvpn/users

# Sécuriser le fichier
chmod 600 /etc/openvpn/users
```

---

## 5. Gestion via le script ovpn-client

### Admins (certificat individuel + mot de passe)

```bash
# 1. Créer le certificat individuel et générer le .ovpn
ovpn-client create alice

# 2. Créer l'utilisateur dans le groupe admin
ovpn-client adduser alice admin

# Récupérer le .ovpn
scp root@IP_OPENWRT:/tmp/ovpn-clients/alice.ovpn .
```

### Users (certificat partagé + mot de passe)

```bash
# 1. Créer le certificat partagé (une seule fois)
ovpn-client shared-create

# 2. Ajouter un utilisateur dans le groupe user
ovpn-client adduser bob user

# 3. Générer le .ovpn partagé pour cet utilisateur
ovpn-client shared-ovpn bob

# Récupérer le .ovpn
scp root@IP_OPENWRT:/tmp/ovpn-clients/bob-shared.ovpn .
```

### Autres opérations

```bash
# Changer le mot de passe d'un utilisateur
ovpn-client passwd alice

# Supprimer un utilisateur
ovpn-client deluser bob

# Lister les utilisateurs
ovpn-client listusers

# Lister les clients et connexions actives
ovpn-client list
```

---

## 6. Fichiers .ovpn générés

### Admin (alice.ovpn) - certificat individuel

```conf
client
dev tun
proto udp
remote TON_IP 1194
auth-user-pass          ← demande login/mdp à la connexion

<ca>...</ca>
<cert>CERTIFICAT_INDIVIDUEL_ALICE</cert>
<key>CLE_INDIVIDUELLE_ALICE</key>
<tls-auth>...</tls-auth>
```

### User (bob-shared.ovpn) - certificat partagé

```conf
client
dev tun
proto udp
remote TON_IP 1194
auth-user-pass          ← demande login/mdp à la connexion

<ca>...</ca>
<cert>CERTIFICAT_PARTAGE</cert>    ← même pour tous les users
<key>CLE_PARTAGE</key>             ← même pour tous les users
<tls-auth>...</tls-auth>
```

---

## 7. Variables OpenVPN disponibles dans les scripts

| Variable | Description | Disponible dans |
|---|---|---|
| `$common_name` | CN du certificat ou username (avec username-as-common-name) | check-auth, client-connect |
| `$username` | Login fourni par le client | check-auth, client-connect |
| `$trusted_ip` | IP réelle du client | client-connect |
| `$trusted_port` | Port du client | client-connect |
| `$ifconfig_pool_remote_ip` | IP VPN attribuée | client-connect |
| `$bytes_received` | Octets reçus | client-disconnect uniquement |
| `$bytes_sent` | Octets envoyés | client-disconnect uniquement |

---

## 8. Récapitulatif des fichiers

| Fichier | Rôle |
|---|---|
| `/etc/openvpn/server.conf` | Configuration serveur OpenVPN |
| `/etc/openvpn/check-auth.sh` | Vérification login/mot de passe + groupe |
| `/etc/openvpn/client-connect.sh` | Limitation des connexions simultanées |
| `/etc/openvpn/users` | Base des utilisateurs (username:hash:groupe) |
| `/etc/openvpn/ccd/` | Config par client (blocage temporaire) |
| `/etc/easy-rsa/pki/issued/shared.crt` | Certificat partagé (groupe user) |
| `/tmp/ovpn-clients/` | Fichiers .ovpn générés |
| `/tmp/openvpn-auth.log` | Log des authentifications |
| `/tmp/openvpn-connect.log` | Log des connexions/refus |
| `/tmp/openvpn-status.log` | Connexions actives |

---

## 9. Appliquer les changements

```bash
# Vérifier la configuration
openvpn --config /etc/openvpn/server.conf --test

# Redémarrer OpenVPN
service openvpn restart

# Surveiller les logs
tail -f /tmp/openvpn-auth.log
tail -f /tmp/openvpn-connect.log
cat /tmp/openvpn-status.log
```

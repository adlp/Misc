# OpenVPN Serveur sur OpenWRT 23.05.3

## 1. Installation des paquets

```bash
opkg update
opkg install openvpn-openssl
opkg install luci-app-openvpn
opkg install luci-i18n-openvpn-fr
opkg install openssh-sftp-server
```

## 2. Configuration réseau et firewall

```bash
# Interface réseau VPN
uci set network.vpn01="interface"
uci set network.vpn01.device="tun0"
uci set network.vpn01.proto="none"
uci set network.vpn01.auto="1"
uci commit network

# Règle firewall : autoriser OpenVPN depuis WAN
uci add firewall rule
uci set firewall.@rule[-1].name="Autoriser-OpenVPN"
uci set firewall.@rule[-1].target="ACCEPT"
uci set firewall.@rule[-1].src="wan"
uci set firewall.@rule[-1].proto="udp"
uci set firewall.@rule[-1].dest_port="1194"

# Zone VPN
uci add firewall zone
uci set firewall.@zone[-1].name="vpn"
uci set firewall.@zone[-1].input="ACCEPT"
uci set firewall.@zone[-1].forward="REJECT"
uci set firewall.@zone[-1].output="ACCEPT"
uci set firewall.@zone[-1].masq="1"
uci set firewall.@zone[-1].network="vpn01"

# Forwarding VPN → WAN (accès internet depuis VPN)
uci add firewall forwarding
uci set firewall.@forwarding[-1].src="vpn"
uci set firewall.@forwarding[-1].dest="wan"

# Forwarding VPN → LAN (accès réseau local depuis VPN)
uci add firewall forwarding
uci set firewall.@forwarding[-1].src="vpn"
uci set firewall.@forwarding[-1].dest="lan"

uci commit firewall

# Recharger
/etc/init.d/network reload
/etc/init.d/firewall reload
```

## 3. Génération des certificats

> **Note** : Easy-RSA 3.0.8 est disponible via `/usr/bin/easyrsa` mais présente
> un bug avec OpenSSL 3.x. On utilise donc OpenSSL directement.

```bash
# Définir le répertoire PKI
export PKI="/etc/easy-rsa/pki"

# Initialiser la PKI
easyrsa init-pki
```

### CA

```bash
# Générer la clé CA
openssl genrsa -out $PKI/private/ca.key 2048

# Créer le certificat CA
openssl req -new -x509 \
    -days 3650 \
    -key $PKI/private/ca.key \
    -out $PKI/ca.crt \
    -subj "/CN=MsConceptAtelier-CA/O=MsConceptAtelier/C=FR"
```

### Certificat serveur

```bash
# Générer la clé serveur
openssl genrsa -out $PKI/private/server.key 2048

# Créer le CSR
openssl req -new \
    -key $PKI/private/server.key \
    -out $PKI/reqs/server.csr \
    -subj "/CN=server/O=MsConceptAtelier/C=FR"

# Fichier d'extensions serveur
cat > /tmp/server-ext.cnf << EOF
extendedKeyUsage=serverAuth
keyUsage=digitalSignature,keyEncipherment
EOF

# Signer avec la CA
openssl x509 -req \
    -in $PKI/reqs/server.csr \
    -CA $PKI/ca.crt \
    -CAkey $PKI/private/ca.key \
    -CAcreateserial \
    -out $PKI/issued/server.crt \
    -days 3650 -sha256 \
    -extfile /tmp/server-ext.cnf
```

### Certificat client

```bash
# Générer la clé client
openssl genrsa -out $PKI/private/client1.key 2048

# Créer le CSR
openssl req -new \
    -key $PKI/private/client1.key \
    -out $PKI/reqs/client1.csr \
    -subj "/CN=client1/O=MsConceptAtelier/C=FR"

# Fichier d'extensions client
cat > /tmp/client-ext.cnf << EOF
extendedKeyUsage=clientAuth
keyUsage=digitalSignature
EOF

# Signer avec la CA
openssl x509 -req \
    -in $PKI/reqs/client1.csr \
    -CA $PKI/ca.crt \
    -CAkey $PKI/private/ca.key \
    -CAcreateserial \
    -out $PKI/issued/client1.crt \
    -days 3650 -sha256 \
    -extfile /tmp/client-ext.cnf
```

### Diffie-Hellman et clé TLS

```bash
# Générer les paramètres DH (peut prendre plusieurs minutes)
openssl dhparam -out $PKI/dh.pem 2048

# Générer la clé TLS
openvpn --genkey secret $PKI/ta.key
```

## 4. Configuration OpenVPN serveur

```bash
cat > /etc/openvpn/server.conf << EOF
port 1194
proto udp
dev tun

ca   /root/easyrsaovpn/pki/ca.crt
cert /root/easyrsaovpn/pki/issued/server.crt
key  /root/easyrsaovpn/pki/private/server.key
dh   /root/easyrsaovpn/pki/dh.pem
tls-auth /root/easyrsaovpn/pki/ta.key 0

server 10.8.0.0 255.255.255.0

push "route 192.168.1.0 255.255.255.0"
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 192.168.1.1"

keepalive 10 120
cipher AES-256-GCM
persist-key
persist-tun

status /tmp/openvpn-status.log
log    /tmp/openvpn.log
verb 3
EOF

# Enregistrer dans UCI
uci set openvpn.myvpn=openvpn
uci set openvpn.myvpn.enabled=1
uci set openvpn.myvpn.config=/etc/openvpn/server.conf
uci commit openvpn
```

## 5. Démarrer OpenVPN

```bash
service openvpn enable
service openvpn start

# Vérifier
service openvpn status
cat /tmp/openvpn.log
```

## 6. Générer le fichier client .ovpn

```bash
PKI="/root/easyrsaovpn/pki"
SERV_IP="TON_IP_PUBLIQUE_OU_DDNS"

cat > /tmp/client1.ovpn << EOF
client
dev tun
proto udp
remote $SERV_IP 1194

resolv-retry infinite
nobind
persist-key
persist-tun
cipher AES-256-GCM
verb 3
key-direction 1

<ca>
$(cat $PKI/ca.crt)
</ca>
<cert>
$(cat $PKI/issued/client1.crt)
</cert>
<key>
$(cat $PKI/private/client1.key)
</key>
<tls-auth>
$(cat $PKI/ta.key)
</tls-auth>
EOF

echo "Fichier client généré : /tmp/client1.ovpn"
```

Récupérer le fichier via SCP :
```bash
scp root@IP_OPENWRT:/tmp/client1.ovpn .
```

## Récapitulatif des fichiers

| Fichier | Rôle |
|---|---|
| `$PKI/ca.crt` | Certificat CA |
| `$PKI/private/ca.key` | Clé privée CA |
| `$PKI/issued/server.crt` | Certificat serveur |
| `$PKI/private/server.key` | Clé privée serveur |
| `$PKI/issued/client1.crt` | Certificat client |
| `$PKI/private/client1.key` | Clé privée client |
| `$PKI/dh.pem` | Paramètres Diffie-Hellman |
| `$PKI/ta.key` | Clé TLS auth |

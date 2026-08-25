#!/bin/sh
# =============================================================================
# Gestionnaire de clients OpenVPN pour OpenWRT
# Supporte : certificats individuels (admins) et partagés (users)
#            authentification par login/mot de passe
#            limitation des connexions simultanées
# Usage: ./ovpn-client.sh <action> [options]
# =============================================================================

PKI="/etc/easy-rsa/pki"
OVPN_DIR="/etc/openvpn"
OUTPUT_DIR="/tmp/ovpn-clients"
SERV_IP="TON_IP_PUBLIQUE_OU_DDNS"
SERV_PORT="1194"
BLOCKED_LIST="$OVPN_DIR/blocked-clients.txt"
CRL_FILE="$PKI/crl.pem"
STATUS_FILE="/tmp/openvpn-status.log"
USERS_FILE="$OVPN_DIR/users"
SHARED_CERT_NAME="shared"   # Nom du certificat partagé pour les users

# =============================================================================
# Fonctions utilitaires
# =============================================================================

usage() {
    echo "Usage: $0 <action> [arguments]"
    echo ""
    echo "=== Gestion des certificats ==="
    echo "  create   <nom_client>          : Créer un client admin (certificat individuel)"
    echo "  revoke   <nom_client>          : Révoquer définitivement le certificat d'un client"
    echo "  renew    <nom_client>          : Régénérer le certificat d'un client"
    echo "  block    <nom_client>          : Bloquer temporairement un client"
    echo "  unblock  <nom_client>          : Débloquer un client"
    echo "  ovpn     <nom_client>          : Régénérer le fichier .ovpn d'un client"
    echo ""
    echo "=== Gestion des utilisateurs ==="
    echo "  adduser  <username> <groupe>   : Ajouter un utilisateur (groupe: admin|user)"
    echo "  deluser  <username>            : Supprimer un utilisateur"
    echo "  passwd   <username>            : Changer le mot de passe d'un utilisateur"
    echo "  listusers                      : Lister les utilisateurs et leur groupe"
    echo ""
    echo "=== Gestion du certificat partagé ==="
    echo "  shared-create                  : Créer le certificat partagé (groupe user)"
    echo "  shared-ovpn <username>         : Générer un .ovpn partagé pour un utilisateur"
    echo ""
    echo "=== Listing ==="
    echo "  list                           : Lister tous les clients et leur statut"
    exit 1
}

check_client_name() {
    if [ -z "$CLIENT" ]; then
        echo "Erreur: le nom du client est obligatoire"
        usage
    fi
    echo "$CLIENT" | grep -qE '^[a-zA-Z0-9_-]+$' || {
        echo "Erreur: le nom du client ne peut contenir que des lettres, chiffres, - et _"
        exit 1
    }
}

check_pki() {
    if [ ! -f "$PKI/ca.crt" ] || [ ! -f "$PKI/private/ca.key" ]; then
        echo "Erreur: PKI non initialisée dans $PKI"
        exit 1
    fi
}

reload_openvpn() {
    echo "Rechargement d'OpenVPN..."
    service openvpn restart
}

hash_password() {
    echo -n "$1" | openssl dgst -sha256 | cut -d' ' -f2
}

read_password() {
    printf "Mot de passe: "
    read -s PASSWORD 2>/dev/null || read PASSWORD
    echo ""
    printf "Confirmer: "
    read -s PASSWORD2 2>/dev/null || read PASSWORD2
    echo ""

    if [ "$PASSWORD" != "$PASSWORD2" ]; then
        echo "Erreur: les mots de passe ne correspondent pas"
        exit 1
    fi

    if [ -z "$PASSWORD" ]; then
        echo "Erreur: le mot de passe ne peut pas être vide"
        exit 1
    fi
}

# =============================================================================
# Génération de certificat (commun admin et shared)
# =============================================================================

generate_cert() {
    local name=$1

    # Générer la clé privée
    echo "Génération de la clé privée..."
    openssl genrsa -out "$PKI/private/${name}.key" 2048

    # Créer le CSR
    echo "Création du CSR..."
    openssl req -new \
        -key "$PKI/private/${name}.key" \
        -out "$PKI/reqs/${name}.csr" \
        -subj "/CN=${name}/O=MsConceptAtelier/C=FR"

    # Extensions client
    cat > /tmp/client-ext.cnf << EOF
extendedKeyUsage=clientAuth
keyUsage=digitalSignature
EOF

    # Signer avec la CA
    echo "Signature du certificat..."
    openssl x509 -req \
        -in "$PKI/reqs/${name}.csr" \
        -CA "$PKI/ca.crt" \
        -CAkey "$PKI/private/ca.key" \
        -CAcreateserial \
        -out "$PKI/issued/${name}.crt" \
        -days 3650 -sha256 \
        -extfile /tmp/client-ext.cnf
}

# =============================================================================
# Génération du fichier .ovpn (admin : certificat individuel)
# =============================================================================

generate_ovpn() {
    local name=$1
    mkdir -p "$OUTPUT_DIR"

    cat > "$OUTPUT_DIR/${name}.ovpn" << EOF
client
dev tun
proto udp
remote $SERV_IP $SERV_PORT

resolv-retry infinite
nobind
persist-key
persist-tun
cipher AES-256-GCM
verb 3
key-direction 1

# Authentification par login/mot de passe
auth-user-pass

<ca>
$(cat "$PKI/ca.crt")
</ca>
<cert>
$(cat "$PKI/issued/${name}.crt")
</cert>
<key>
$(cat "$PKI/private/${name}.key")
</key>
<tls-auth>
$(cat "$PKI/ta.key")
</tls-auth>
EOF

    chmod 600 "$OUTPUT_DIR/${name}.ovpn"
    echo "✓ Fichier .ovpn généré : $OUTPUT_DIR/${name}.ovpn"
}

# =============================================================================
# Génération du fichier .ovpn partagé (user : certificat partagé)
# =============================================================================

generate_shared_ovpn() {
    local username=$1
    mkdir -p "$OUTPUT_DIR"

    if [ ! -f "$PKI/issued/${SHARED_CERT_NAME}.crt" ]; then
        echo "Erreur: le certificat partagé n'existe pas"
        echo "Utilisez 'shared-create' pour le créer"
        exit 1
    fi

    # Vérifier que l'utilisateur existe et est bien dans le groupe user
    local group=$(grep "^${username}:" "$USERS_FILE" | cut -d: -f3)
    if [ "$group" != "user" ]; then
        echo "Erreur: '$username' n'existe pas ou n'est pas dans le groupe 'user'"
        exit 1
    fi

    cat > "$OUTPUT_DIR/${username}-shared.ovpn" << EOF
client
dev tun
proto udp
remote $SERV_IP $SERV_PORT

resolv-retry infinite
nobind
persist-key
persist-tun
cipher AES-256-GCM
verb 3
key-direction 1

# Authentification par login/mot de passe
auth-user-pass

<ca>
$(cat "$PKI/ca.crt")
</ca>
<cert>
$(cat "$PKI/issued/${SHARED_CERT_NAME}.crt")
</cert>
<key>
$(cat "$PKI/private/${SHARED_CERT_NAME}.key")
</key>
<tls-auth>
$(cat "$PKI/ta.key")
</tls-auth>
EOF

    chmod 600 "$OUTPUT_DIR/${username}-shared.ovpn"
    echo "✓ Fichier .ovpn partagé généré : $OUTPUT_DIR/${username}-shared.ovpn"
}

# =============================================================================
# Création du certificat partagé
# =============================================================================

create_shared_cert() {
    echo "=== Création du certificat partagé ==="

    if [ -f "$PKI/issued/${SHARED_CERT_NAME}.crt" ]; then
        echo "Erreur: le certificat partagé existe déjà"
        exit 1
    fi

    generate_cert "$SHARED_CERT_NAME"
    echo "✓ Certificat partagé créé"
    echo "  Utilisez 'shared-ovpn <username>' pour générer un .ovpn pour chaque utilisateur"
}

# =============================================================================
# Création d'un client admin (certificat individuel)
# =============================================================================

create_client() {
    echo "=== Création du client admin : $CLIENT ==="

    if [ -f "$PKI/issued/${CLIENT}.crt" ]; then
        echo "Erreur: le client '$CLIENT' existe déjà"
        echo "Utilisez 'renew' pour régénérer son certificat"
        exit 1
    fi

    generate_cert "$CLIENT"
    generate_ovpn "$CLIENT"

    echo "✓ Client admin '$CLIENT' créé avec succès"
    echo "✓ Fichier .ovpn disponible : $OUTPUT_DIR/${CLIENT}.ovpn"
    echo ""
    echo "N'oubliez pas d'ajouter l'utilisateur avec :"
    echo "  $0 adduser $CLIENT admin"
}

# =============================================================================
# Révocation définitive d'un client
# =============================================================================

revoke_client() {
    echo "=== Révocation du client : $CLIENT ==="

    if [ ! -f "$PKI/issued/${CLIENT}.crt" ]; then
        echo "Erreur: le client '$CLIENT' n'existe pas"
        exit 1
    fi

    cat > /tmp/ca.cnf << EOF
[ ca ]
default_ca = CA_default

[ CA_default ]
dir               = $PKI
database          = $PKI/index.txt
new_certs_dir     = $PKI/issued
certificate       = $PKI/ca.crt
private_key       = $PKI/private/ca.key
crl               = $PKI/crl.pem
crlnumber         = $PKI/crlnumber
default_crl_days  = 3650
default_md        = sha256
policy            = policy_anything

[ policy_anything ]
countryName             = optional
stateOrProvinceName     = optional
localityName            = optional
organizationName        = optional
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional
EOF

    [ ! -f "$PKI/index.txt" ] && touch "$PKI/index.txt"
    [ ! -f "$PKI/crlnumber" ] && echo "01" > "$PKI/crlnumber"

    openssl ca \
        -revoke "$PKI/issued/${CLIENT}.crt" \
        -keyfile "$PKI/private/ca.key" \
        -cert "$PKI/ca.crt" \
        -config /tmp/ca.cnf

    openssl ca \
        -gencrl \
        -keyfile "$PKI/private/ca.key" \
        -cert "$PKI/ca.crt" \
        -out "$CRL_FILE" \
        -config /tmp/ca.cnf

    rm -f "$PKI/issued/${CLIENT}.crt"
    rm -f "$PKI/private/${CLIENT}.key"
    rm -f "$PKI/reqs/${CLIENT}.csr"
    rm -f "$OUTPUT_DIR/${CLIENT}.ovpn"

    if ! grep -q "crl-verify" "$OVPN_DIR/server.conf" 2>/dev/null; then
        echo "crl-verify $CRL_FILE" >> "$OVPN_DIR/server.conf"
    fi

    reload_openvpn

    echo "✓ Client '$CLIENT' révoqué définitivement"
    echo "  Pensez aussi à supprimer l'utilisateur avec :"
    echo "  $0 deluser $CLIENT"
}

# =============================================================================
# Régénération du certificat d'un client
# =============================================================================

renew_client() {
    echo "=== Régénération du certificat du client : $CLIENT ==="

    if [ ! -f "$PKI/issued/${CLIENT}.crt" ]; then
        echo "Erreur: le client '$CLIENT' n'existe pas"
        exit 1
    fi

    cp "$PKI/issued/${CLIENT}.crt" "$PKI/issued/${CLIENT}.crt.bak"
    echo "Ancien certificat sauvegardé : $PKI/issued/${CLIENT}.crt.bak"

    rm -f "$PKI/issued/${CLIENT}.crt"
    rm -f "$PKI/reqs/${CLIENT}.csr"

    generate_cert "$CLIENT"
    generate_ovpn "$CLIENT"

    echo "✓ Certificat du client '$CLIENT' régénéré avec succès"
    echo "⚠ L'ancien fichier .ovpn ne fonctionnera plus"
}

# =============================================================================
# Blocage temporaire d'un client
# =============================================================================

block_client() {
    echo "=== Blocage temporaire du client : $CLIENT ==="

    if [ ! -f "$PKI/issued/${CLIENT}.crt" ]; then
        echo "Erreur: le client '$CLIENT' n'existe pas"
        exit 1
    fi

    touch "$BLOCKED_LIST"
    if grep -q "^${CLIENT}$" "$BLOCKED_LIST" 2>/dev/null; then
        echo "Le client '$CLIENT' est déjà bloqué"
        exit 0
    fi

    echo "$CLIENT" >> "$BLOCKED_LIST"

    mkdir -p "$OVPN_DIR/ccd"
    echo "disable" > "$OVPN_DIR/ccd/${CLIENT}"

    if ! grep -q "client-config-dir" "$OVPN_DIR/server.conf" 2>/dev/null; then
        echo "client-config-dir $OVPN_DIR/ccd" >> "$OVPN_DIR/server.conf"
    fi

    reload_openvpn

    echo "✓ Client '$CLIENT' bloqué temporairement"
    echo "  Utilisez 'unblock $CLIENT' pour le débloquer"
}

# =============================================================================
# Déblocage d'un client
# =============================================================================

unblock_client() {
    echo "=== Déblocage du client : $CLIENT ==="

    if ! grep -q "^${CLIENT}$" "$BLOCKED_LIST" 2>/dev/null; then
        echo "Le client '$CLIENT' n'est pas bloqué"
        exit 0
    fi

    sed -i "/^${CLIENT}$/d" "$BLOCKED_LIST"
    rm -f "$OVPN_DIR/ccd/${CLIENT}"

    reload_openvpn

    echo "✓ Client '$CLIENT' débloqué"
}

# =============================================================================
# Gestion des utilisateurs
# =============================================================================

add_user() {
    local username=$1
    local group=$2

    if [ -z "$username" ] || [ -z "$group" ]; then
        echo "Usage: $0 adduser <username> <groupe>"
        echo "Groupes disponibles: admin, user"
        exit 1
    fi

    if [ "$group" != "admin" ] && [ "$group" != "user" ]; then
        echo "Erreur: le groupe doit être 'admin' ou 'user'"
        exit 1
    fi

    touch "$USERS_FILE"
    if grep -q "^${username}:" "$USERS_FILE" 2>/dev/null; then
        echo "Erreur: l'utilisateur '$username' existe déjà"
        exit 1
    fi

    # Vérification supplémentaire pour les admins
    if [ "$group" = "admin" ] && [ ! -f "$PKI/issued/${username}.crt" ]; then
        echo "Attention: aucun certificat individuel trouvé pour '$username'"
        echo "Créez d'abord le certificat avec : $0 create $username"
    fi

    read_password
    HASH=$(hash_password "$PASSWORD")
    echo "${username}:${HASH}:${group}" >> "$USERS_FILE"
    chmod 600 "$USERS_FILE"

    echo "✓ Utilisateur '$username' ajouté (groupe: $group)"
}

del_user() {
    local username=$1

    if [ -z "$username" ]; then
        echo "Usage: $0 deluser <username>"
        exit 1
    fi

    if ! grep -q "^${username}:" "$USERS_FILE" 2>/dev/null; then
        echo "Erreur: l'utilisateur '$username' n'existe pas"
        exit 1
    fi

    sed -i "/^${username}:/d" "$USERS_FILE"
    echo "✓ Utilisateur '$username' supprimé"
}

change_password() {
    local username=$1

    if [ -z "$username" ]; then
        echo "Usage: $0 passwd <username>"
        exit 1
    fi

    if ! grep -q "^${username}:" "$USERS_FILE" 2>/dev/null; then
        echo "Erreur: l'utilisateur '$username' n'existe pas"
        exit 1
    fi

    read_password
    HASH=$(hash_password "$PASSWORD")
    GROUP=$(grep "^${username}:" "$USERS_FILE" | cut -d: -f3)
    sed -i "s|^${username}:.*|${username}:${HASH}:${GROUP}|" "$USERS_FILE"

    echo "✓ Mot de passe de '$username' modifié"
}

list_users() {
    echo "=== Liste des utilisateurs ==="
    echo ""
    printf "%-20s %-10s\n" "USERNAME" "GROUPE"
    printf "%-20s %-10s\n" "--------" "------"

    if [ ! -f "$USERS_FILE" ]; then
        echo "Aucun utilisateur configuré"
        return
    fi

    while IFS=: read -r username hash group; do
        printf "%-20s %-10s\n" "$username" "$group"
    done < "$USERS_FILE"
}

# =============================================================================
# Liste des clients et leur statut
# =============================================================================

get_client_vpn_ip() {
    local name=$1
    if [ -f "$STATUS_FILE" ]; then
        grep "^CLIENT_LIST,${name}," "$STATUS_FILE" 2>/dev/null | cut -d',' -f4
    fi
}

list_clients() {
    echo "=== Liste des clients OpenVPN ==="
    echo ""
    printf "%-20s %-10s %-12s %-16s %-30s\n" "CLIENT" "GROUPE" "STATUT" "IP VPN" "EXPIRATION"
    printf "%-20s %-10s %-12s %-16s %-30s\n" "------" "------" "------" "------" "----------"

    touch "$BLOCKED_LIST"

    for cert in "$PKI/issued/"*.crt; do
        [ -f "$cert" ] || continue
        name=$(basename "$cert" .crt)
        [ "$name" = "server" ] && continue

        # Déterminer le groupe
        if [ "$name" = "$SHARED_CERT_NAME" ]; then
            group="shared"
        else
            group=$(grep "^${name}:" "$USERS_FILE" 2>/dev/null | cut -d: -f3)
            [ -z "$group" ] && group="-"
        fi

        # Vérifier si bloqué
        if grep -q "^${name}$" "$BLOCKED_LIST" 2>/dev/null; then
            status="BLOQUÉ"
        else
            status="ACTIF"
        fi

        # IP VPN si connecté
        vpn_ip=$(get_client_vpn_ip "$name")
        if [ -n "$vpn_ip" ]; then
            status="CONNECTÉ"
        else
            vpn_ip="-"
        fi

        expiry=$(openssl x509 -enddate -noout -in "$cert" 2>/dev/null | cut -d= -f2)

        printf "%-20s %-10s %-12s %-16s %-30s\n" "$name" "$group" "$status" "$vpn_ip" "$expiry"
    done

    echo ""
    if [ -f "$PKI/index.txt" ]; then
        revoked=$(grep "^R" "$PKI/index.txt" | awk '{print $5}' | sed 's|.*/CN=||')
        if [ -n "$revoked" ]; then
            echo "Clients révoqués définitivement:"
            echo "$revoked" | while read r; do
                group=$(grep "^${r}:" "$USERS_FILE" 2>/dev/null | cut -d: -f3)
                [ -z "$group" ] && group="-"
                printf "  %-20s %-10s %-12s\n" "$r" "$group" "RÉVOQUÉ"
            done
        fi
    fi
}

# =============================================================================
# Main
# =============================================================================

ACTION=$1
CLIENT=$2

case "$ACTION" in
    create)
        check_client_name
        check_pki
        create_client
        ;;
    revoke)
        check_client_name
        check_pki
        revoke_client
        ;;
    renew)
        check_client_name
        check_pki
        renew_client
        ;;
    block)
        check_client_name
        check_pki
        block_client
        ;;
    unblock)
        check_client_name
        check_pki
        unblock_client
        ;;
    ovpn)
        check_client_name
        check_pki
        if [ ! -f "$PKI/issued/${CLIENT}.crt" ]; then
            echo "Erreur: le client '$CLIENT' n'existe pas"
            exit 1
        fi
        generate_ovpn "$CLIENT"
        ;;
    shared-create)
        check_pki
        create_shared_cert
        ;;
    shared-ovpn)
        check_pki
        generate_shared_ovpn "$CLIENT"
        ;;
    adduser)
        add_user "$2" "$3"
        ;;
    deluser)
        del_user "$2"
        ;;
    passwd)
        change_password "$2"
        ;;
    listusers)
        list_users
        ;;
    list)
        list_clients
        ;;
    *)
        usage
        ;;
esac

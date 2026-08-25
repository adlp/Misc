#!/bin/sh
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

# Vérifier le mot de passe
INPUT_HASH=$(echo -n "$PASSWORD" | openssl dgst -sha256 | cut -d' ' -f2)

if [ "$INPUT_HASH" != "$HASH" ]; then
    echo "$(date) Auth FAILED (wrong password): $USERNAME" >> "$LOG"
    exit 1
fi

# Vérification certificat pour les admins
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

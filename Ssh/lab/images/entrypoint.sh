#!/bin/sh
# Entrée commune des quatre rôles (sh POSIX : dash et busybox ash).
# Environnement (aucun secret) :
#   LAB_USER        compte distant (lab, labpw)
#   LAB_AUTH        key (clé seule) | password (mot de passe seul, clés refusées)
#   LAB_ALLOW_FROM  nom d'un hôte : seul le compte venant de son adresse (résolue ici) est admis
# Clés publiques admises : /keys/authorized_keys (monté en lecture seule), copiées dans
# ~/.ssh/authorized_keys (propriété du compte : `sshvault deploy` y écrit).
set -eu

user=$LAB_USER
auth=$LAB_AUTH

# clés d'hôte neuves au premier démarrage du conteneur (celles que l'image aurait déjà, Debian à l'installation,
# sont retirées : `ssh-keygen -A` ne remplace pas les clés existantes) ; un redémarrage du conteneur garde ses
# clés (repère dans le système de fichiers du conteneur), pour que le known_hosts de la maquette reste valable
if [ ! -e /etc/ssh/.lab-hostkeys ]; then
    rm -f /etc/ssh/ssh_host_*
    ssh-keygen -A >/dev/null
    : > /etc/ssh/.lab-hostkeys
fi

home=$(getent passwd "$user" | cut -d: -f6)
if [ "$auth" = key ]; then
    mkdir -p "$home/.ssh"
    if [ -f /keys/authorized_keys ]; then
        cat /keys/authorized_keys > "$home/.ssh/authorized_keys"
    else
        : > "$home/.ssh/authorized_keys"
    fi
    chmod 700 "$home/.ssh"
    chmod 600 "$home/.ssh/authorized_keys"
    chown -R "$user:$(id -gn "$user")" "$home/.ssh"
fi

{
    echo "Port 22"
    echo "HostKey /etc/ssh/ssh_host_ed25519_key"
    echo "PidFile /run/sshd.pid"
    echo "LogLevel VERBOSE"
    [ -e /etc/pam.d/sshd ] && echo "UsePAM no"
    echo "PermitRootLogin no"
    echo "PrintMotd no"
    echo "StrictModes yes"
    echo "AllowAgentForwarding yes"
    echo "AllowTcpForwarding yes"
    echo "KbdInteractiveAuthentication no"
    if [ "$auth" = key ]; then
        echo "PasswordAuthentication no"
        echo "PubkeyAuthentication yes"
        echo "AuthenticationMethods publickey"
    else
        echo "PasswordAuthentication yes"
        echo "PubkeyAuthentication no"
        echo "AuthenticationMethods password"
    fi
    if [ -n "${LAB_ALLOW_FROM:-}" ]; then
        # adresse de l'hôte autorisé, telle que ce conteneur la voit (réseau partagé) : attente
        # que son nom soit résolu (démarrage en parallèle)
        n=0
        ip=
        while [ -z "$ip" ]; do
            ip=$(getent hosts "$LAB_ALLOW_FROM" | awk 'NR == 1 { print $1 }') || ip=
            [ -n "$ip" ] && break
            n=$((n + 1))
            if [ "$n" -ge 60 ]; then
                echo "entrypoint: $LAB_ALLOW_FROM introuvable" >&2
                exit 1
            fi
            sleep 1
        done
        echo "AllowUsers $user@$ip"
    else
        echo "AllowUsers $user"
    fi
} > /etc/ssh/sshd_config

exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config

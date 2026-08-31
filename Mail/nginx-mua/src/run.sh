#!/bin/bash
set -e
cd /
export DEBIAN_FRONTEND=noninteractive

# /opt/apt-cache et /opt/apt-lists : cache persistant pour le mode buildless
# (voir README, section "Mode buildless"). Ne touche jamais /opt/tgz, réservé
# au squelette embarqué par le mode build (Dockerfile-pf) — ne pas monter tout
# /opt en volume, seulement ces deux sous-dossiers, sous peine de masquer
# /opt/tgz baké dans l'image.
mkdir -p /opt/apt-cache/partial /opt/apt-lists/partial
APT_OPTS=(-o Dir::Cache::Archives=/opt/apt-cache -o Dir::State::Lists=/opt/apt-lists)

if ! command -v postfix >/dev/null 2>&1; then
    # mode buildless : image stock, postfix pas encore installé dans ce conteneur
    echo "Postfix absent de ce conteneur (mode buildless) : installation"
    if [ ! -e /opt/apt-lists/.populated ] || [ "${FORCE_APT_UPDATE:-0}" = "1" ]; then
        echo "apt-get update (réseau nécessaire) -- alimente /opt/apt-lists pour les prochains démarrages"
        apt-get update "${APT_OPTS[@]}"
        touch /opt/apt-lists/.populated
    else
        echo "Réutilisation des listes/paquets déjà en cache (/opt) -- pas d'accès réseau nécessaire"
    fi
    apt-get install -y --no-install-recommends "${APT_OPTS[@]}" postfix
    grep -q '^maillog_file' /etc/postfix/main.cf || echo 'maillog_file = /dev/stdout' >>/etc/postfix/main.cf
elif [ ! -e /etc/postfix/master.cf ] || [ ! -e /var/spool/postfix/private/smtp ]; then
    # mode build (Dockerfile-pf) : postfix déjà installé dans l'image, mais un
    # ou les deux volumes sont neufs -- restaure le squelette capturé au build
    echo "Postfix déjà installé (image buildée), volume(s) neuf(s) : restauration du squelette"
    test -e /etc/postfix/master.cf || tar xzf /opt/tgz/etc+postfix.tgz
    test -e /var/spool/postfix/private/smtp || tar xzf /opt/tgz/var+spool+postfix.tgz
else
    echo "Postfix déjà installé et configuré, rien à faire"
fi

test -e /etc/mailname || echo "Creating /etc/mailname"
test -e /etc/mailname || /usr/bin/hostname >/etc/mailname

echo Compiling
/usr/bin/newaliases

echo "Starting periodic queue flush every ${QUEUE_FLUSH_INTERVAL:-300}s"
( while true; do sleep "${QUEUE_FLUSH_INTERVAL:-300}"; /usr/sbin/postqueue -f; done ) &

echo Running
exec /usr/sbin/postfix start-fg

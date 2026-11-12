#!/bin/sh
# Maquette ssh de sshvault (story 20) : up | down | status | config | password.
#
#   lab.sh up [CLES_PUBLIQUES]   construit les images, démarre A, B, P, D ; CLES_PUBLIQUES : fichier
#                                de clés publiques admises sur A, B et D (une par ligne)
#   lab.sh down                  détruit conteneurs (le client C de la série de tests compris), réseaux et volumes du projet,
#                                efface mot de passe et known_hosts (images gardées)
#   lab.sh status                état et ports publiés (127.0.0.1)
#   lab.sh config                extrait de ssh_config (Host, HostName, Port, User, ProxyJump, known_hosts à part) à inclure
#   lab.sh password              mot de passe de P (compte labpw), nouveau à chaque `up`
#
# Environnement : SSHVAULT_LAB_PROJECT (nom du projet Compose, défaut sshvault-lab),
# SSHVAULT_LAB_DIR (dossier d'état 0700, défaut $XDG_RUNTIME_DIR/sshvault-lab, et pour un autre
# projet $XDG_RUNTIME_DIR/sshvault-lab/<projet>). Ne lit ni n'écrit jamais ~/.ssh.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
PROJECT=${SSHVAULT_LAB_PROJECT:-sshvault-lab}

die() {
    echo "lab.sh: $*" >&2
    exit 1
}

usage() {
    echo "usage : lab.sh up [CLES_PUBLIQUES] | down | status | config | password" >&2
    exit 2
}

case $PROJECT in
    [a-z0-9]*) ;;
    *) die "nom de projet invalide : $PROJECT" ;;
esac
case $PROJECT in
    *[!a-z0-9_-]*) die "nom de projet invalide : $PROJECT (minuscules, chiffres, - et _)" ;;
esac

if [ -n "${SSHVAULT_LAB_DIR:-}" ]; then
    DIR=$SSHVAULT_LAB_DIR
elif [ -n "${XDG_RUNTIME_DIR:-}" ]; then
    DIR=$XDG_RUNTIME_DIR/sshvault-lab
    [ "$PROJECT" = sshvault-lab ] || DIR=$DIR/$PROJECT
else
    die "XDG_RUNTIME_DIR absent : définir SSHVAULT_LAB_DIR (dossier d'état)"
fi
# le dossier est monté (sous-dossier keys/) par `docker compose` : « src:dest:mode » exige un chemin
# absolu sans « : »
case $DIR in
    /*) ;;
    *) die "dossier d'état à chemin absolu exigé : $DIR" ;;
esac
# (« % » et « " » : le chemin est aussi écrit dans `UserKnownHostsFile "…"` par `config`, où ssh développe « % »)
case $DIR in
    *[:%\"]*) die "« : », « % » et « \" » interdits dans le dossier d'état : $DIR" ;;
esac
# dossier des clés publiques admises : seul dossier monté dans les conteneurs (lecture seule)
SSHVAULT_LAB_KEYS=$DIR/keys
export SSHVAULT_LAB_KEYS

dc() {
    docker compose -p "$PROJECT" -f "$HERE/compose.yaml" "$@"
}

# dossier d'état : 0700, à l'utilisateur
prepare() {
    (umask 077 && mkdir -p "$DIR" "$DIR/keys") || die "création de $DIR impossible"
    for d in "$DIR" "$DIR/keys"; do
        [ -d "$d" ] && [ -O "$d" ] || die "$d n'est pas un dossier à vous"
        chmod 700 "$d"
    done
}

# conteneurs, réseaux et volumes restant du projet : code 0 si rien ne reste, 1 s'il reste quelque
# chose, 2 si docker n'a pas pu répondre (jamais « rien » faute de réponse) ; une ligne affichée
leftovers() {
    f=label=com.docker.compose.project=$PROJECT
    c=$(docker ps -a -q --filter "$f") || { echo "docker ps a échoué"; return 2; }
    n=$(docker network ls -q --filter "$f") || { echo "docker network ls a échoué"; return 2; }
    v=$(docker volume ls -q --filter "$f") || { echo "docker volume ls a échoué"; return 2; }
    if [ -z "$c$n$v" ]; then
        return 0
    fi
    echo "conteneurs : ${c:-aucun} ; réseaux : ${n:-aucun} ; volumes : ${v:-aucun}"
    return 1
}

published() {
    # $1 : service ; affiche le port publié sur 127.0.0.1
    out=$(dc port "$1" 22 2>/dev/null) || out=
    [ -n "$out" ] || die "service $1 non démarré (lab.sh up)"
    echo "${out##*:}"
}

cmd_up() {
    [ $# -le 1 ] || usage
    prepare
    # mot de passe et known_hosts d'un `up` précédent : périmés dès maintenant (les clés d'hôte changent à chaque
    # `up` ; `accept-new` refuserait l'ancienne)
    rm -f "$DIR/password" "$DIR/password.new" "$DIR/known_hosts"
    keys=$DIR/keys/authorized_keys
    if [ $# -eq 1 ]; then
        [ -f "$1" ] && [ -r "$1" ] || die "fichier de clés publiques illisible : $1"
        # seules les lignes de clé sont gardées (fins de ligne CR retirées ; ni commentaire ni ligne étrangère)
        (umask 077 && tr -d '\r' < "$1" \
            | grep -E '^(ssh-|ecdsa-|sk-)[^ ]* [A-Za-z0-9+/=]+( .*)?$' > "$keys") || true
        [ -s "$keys" ] || die "aucune clé publique dans $1"
        total=$(grep -c '' "$1") || total=0
        kept=$(grep -c '' "$keys") || kept=0
        if [ "$total" -gt "$kept" ]; then
            echo "lab.sh: $((total - kept)) ligne(s) de $1 écartée(s) (commentaires, lignes vides, clés précédées d'options — non gérées —, ou autres lignes) ; $kept clé(s) admise(s)" >&2
        fi
    else
        (umask 077 && : > "$keys")
        echo "lab.sh: aucune clé publique donnée : A, B et D n'admettent aucune clé (lab.sh up FICHIER)" >&2
    fi
    # mot de passe de P : nouveau à chaque démarrage, fichier 0600 (jamais en argument ni dans l'environnement) ;
    # publié sous son nom (`lab.sh password`) seulement une fois posé sur P
    (umask 077 && head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-24 > "$DIR/password.new")
    [ "$(wc -c < "$DIR/password.new")" -ge 20 ] || { rm -f "$DIR/password.new"; die "mot de passe non généré"; }
    if ! dc up -d --build --force-recreate --remove-orphans --wait --wait-timeout 300 >&2; then
        rm -f "$DIR/password.new"
        die "démarrage de la maquette échoué (lab.sh down pour nettoyer)"
    fi
    # posé par stdin : ni argv ni environnement du conteneur
    if ! { printf 'labpw:'; cat "$DIR/password.new"; } | dc exec -T p chpasswd -c sha512; then
        rm -f "$DIR/password.new"
        die "mot de passe de P non posé (lab.sh down pour nettoyer)"
    fi
    mv -f "$DIR/password.new" "$DIR/password"
    echo "maquette démarrée (projet $PROJECT) : lab.sh config, lab.sh password, lab.sh down"
}

cmd_down() {
    [ $# -eq 0 ] || usage
    rc=0
    # --profile client : le conteneur client de la série de tests (story 21, jamais démarré par `up`) est supprimé aussi
    dc --profile client down -v --remove-orphans --timeout 5 >&2 || rc=1
    rm -f "$DIR/password" "$DIR/password.new" "$DIR/known_hosts" "$DIR/keys/authorized_keys"
    rmdir "$DIR/keys" "$DIR" 2>/dev/null || true
    left=$(leftovers) || { echo "lab.sh: projet $PROJECT : $left" >&2; rc=1; }
    [ $rc -eq 0 ] && echo "maquette détruite (projet $PROJECT)"
    return $rc
}

cmd_status() {
    [ $# -eq 0 ] || usage
    dc --profile client ps -a
}

cmd_config() {
    [ $# -eq 0 ] || usage
    pa=$(published a)
    pp=$(published p)
    pd=$(published d)
    bid=$(dc ps -q b)
    [ -n "$bid" ] || die "service b non démarré (lab.sh up)"
    bip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$bid")
    [ -n "$bip" ] || die "adresse de b introuvable"
    cat <<CFG
# maquette sshvault (projet $PROJECT) : à inclure dans un ssh_config (lab.sh n'écrit jamais dans ~/.ssh)
Host svlab-a
    HostName 127.0.0.1
    Port $pa
    User lab

# B : hôte interne, joignable par A seulement
Host svlab-b
    HostName b
    User lab
    ProxyJump svlab-a

# B sans A : refusé (B n'admet que l'adresse de A)
Host svlab-b-direct
    HostName $bip
    User lab

# P : mot de passe seul (lab.sh password) ; directement, puis par A
Host svlab-p
    HostName 127.0.0.1
    Port $pp
    User labpw

Host svlab-pj
    HostName p
    User labpw
    ProxyJump svlab-a

# D : cible de deploy ; svlab-dg : même machine, pour une autre clé
Host svlab-d
    HostName 127.0.0.1
    Port $pd
    User lab

Host svlab-dg
    HostName 127.0.0.1
    Port $pd
    User lab

# clés d'hôte neuves à chaque \`up\` : known_hosts à part (supprimé par \`down\`), jamais ~/.ssh/known_hosts
Host svlab-*
    UserKnownHostsFile "$DIR/known_hosts"
    StrictHostKeyChecking accept-new
CFG
}

cmd_password() {
    [ $# -eq 0 ] || usage
    [ -f "$DIR/password" ] || die "pas de mot de passe (maquette non démarrée : lab.sh up)"
    cat "$DIR/password"
}

[ $# -ge 1 ] || usage
cmd=$1
shift
case $cmd in
    up) cmd_up "$@" ;;
    down) cmd_down "$@" ;;
    status) cmd_status "$@" ;;
    config) cmd_config "$@" ;;
    password) cmd_password "$@" ;;
    *) usage ;;
esac

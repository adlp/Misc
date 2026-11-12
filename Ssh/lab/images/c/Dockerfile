# C : client de la maquette (story 21) : OpenSSH 10.0 et Python 3.13 (Debian 13). sshvault y tourne depuis
# la source du dépôt montée en lecture seule (/src), avec le vrai `bw` monté lui aussi (/opt/bw/bw) ; aucun
# serveur, aucun secret dans l'image. keyutils : `keyctl` existe, pour que le refus du keyring par le profil
# seccomp par défaut de docker (repli fichier de la session) soit celui du vrai poste, pas une commande absente.
# L'utilisateur a l'uid et le gid de celui qui lance la série (arguments de construction) : la ligne de
# commande des processus du conteneur est relevée côté poste (même uid).
FROM debian:trixie-slim
ARG LAB_UID=1000
ARG LAB_GID=1000
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssh-client python3 keyutils \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -o -g "$LAB_GID" lab \
 && useradd -o -m -u "$LAB_UID" -g "$LAB_GID" -s /bin/sh lab
COPY sshvault sshvault-askpass /usr/local/bin/
RUN chmod 755 /usr/local/bin/sshvault /usr/local/bin/sshvault-askpass
USER lab
WORKDIR /home/lab

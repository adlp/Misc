# P : hôte à mot de passe (OpenSSH 10.0, Alpine 3.22) ; mot de passe seul, clés refusées.
# Le compte est créé verrouillé : le mot de passe est posé au démarrage par `chpasswd` sur stdin.
FROM alpine:3.22
RUN apk add --no-cache openssh \
 && adduser -D -s /bin/sh labpw \
 && mkdir -p /run/sshd
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]

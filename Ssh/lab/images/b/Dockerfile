# B : hôte interne (OpenSSH 9.3, Alpine 3.18) ; clé seule, connexions de A seulement.
FROM alpine:3.18
RUN apk add --no-cache openssh \
 && adduser -D -s /bin/sh lab \
 && sed -i 's/^lab:!:/lab:*:/' /etc/shadow \
 && mkdir -p /run/sshd
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]

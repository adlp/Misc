# Tools

Petits outils d'administration indépendants, sous licence GPL v3.

| Outil | Langage | Version | Description |
|---|---|---|---|
| `checkssl` | bash | 1.3 | État d'un certificat TLS (serveur ou fichier) et jours restants avant expiration |
| `cronMutt` | Python 3 | 0.24.2 | Lance une commande (ou lit un pipe) et envoie sa sortie par mail (mutt) et/ou sur Nextcloud, selon le résultat |
| `sleepUntil` | bash | 1.1 | Comme `at`, mais bloquant : attend une heure donnée puis lance une commande |
| `whosshkey` | bash | 1.2 | Comme `last`, avec en plus la clef SSH utilisée pour chaque connexion |

Voir `CHANGELOG.md` pour l'historique des versions.

## checkssl

```bash
checkssl -u <url> [-i <ip>] [-t <jours>] [-d] [-V]
```

| Option | Rôle |
|---|---|
| `-u` | `https://`, `imap://` / `pop3://` / `smtp://` (STARTTLS), `imaps://`, `pop3s://`, `smtps://` (port par défaut du protocole, ou `hôte:port`), ou `file:///chemin/cert.pem` |
| `-i` | IP (v4 ou v6) à contacter à la place de la résolution DNS ; le SNI garde le nom de l'URL |
| `-t` | Seuil en jours (entier positif), 15 par défaut |
| `-d` | Debug (`set -x`) |
| `-V` | Version |

Ports par défaut : https 443, imap 143, imaps 993, pop3 110, pop3s 995, smtp 25 (MX ; `smtp://hôte:587` pour la
soumission), smtps 465.

Les serveurs restés en TLS 1.0 / 1.1 sont lus aussi : checkssl lit le certificat, il ne juge pas la connexion.

Affiche le CN, les SAN, la date de fin et les jours restants (négatifs si le certificat a expiré). Code retour : `0`
OK, `2` expiration dans `-t` jours ou moins (certificat expiré compris), `1` erreur (message sur stderr : URL sans
protocole, fichier absent ou sans certificat PEM, serveur injoignable ou muet plus de 30 s). Dépend de `openssl` et
`timeout` (coreutils).

## cronMutt

```bash
cronMutt [options] -e "commande"      # cronMutt lance la commande
commande | cronMutt [options]         # mode pipe : cronMutt lit stdin
```

Pensé pour cron : un mail seulement quand c'est utile, sujet marqué en cas d'échec, mails d'une même tâche regroupés en
fil. cronMutt rend le code retour de la commande (128+signal si elle est tuée par un signal).

### Options

| Option | Rôle | Défaut |
|---|---|---|
| `-e cmd` | Commande lancée par `/bin/sh -c` (stdin `/dev/null`) | mode pipe |
| `-s sujet` | Sujet ; préfixé de `*** ` si la commande échoue | `//cron//cronMutt` |
| `-d adresse` | Destinataire(s), séparés par des virgules | `$LOGNAME` |
| `-o adresse` | Destinataire quand la commande réussit (à la place de `-d`) ; en échec, ajouté à `-d`. `-o no` : aucun mail quand tout va bien | — |
| `-E` | Envoie aussi quand la sortie est vide | — |
| `-X` | Ne préfixe pas le sujet en cas d'échec | — |
| `-f from` | Expéditeur (`nom <adresse>` ou `adresse`) | valeur de `-r` |
| `-r adresse` | `Reply-To` (et `From` par défaut) | `$LOGNAME` |
| `-i id` | `In-Reply-To` / `References` : identifiant du fil, complété en `<id@cronMutt>` | md5 du sujet |
| `-m id` | `Message-ID`, complété en `<id@hôte>` | unique à chaque mail |
| `-c` | N'écrit pas la commande dans l'en-tête `X-cronMuttCmd` | — |
| `-t type` | `content_type=text/<type>` (ex. `html`) | `text/plain` |
| `-p encodage` | Encodage de la sortie lue (octets invalides remplacés) | `utf-8` |
| `-T` | Mode tee : affiche aussi la sortie à l'écran (stderr préfixé `[STDERR]:`) | actif si stdin est un terminal |
| `-n url` | URL WebDAV Nextcloud, nom de fichier compris, où déposer la sortie | — |
| `-N login:motdepasse` | Identifiants Nextcloud (le mot de passe peut contenir `:`) | — |
| `-D` | Debug | — |
| `-V` / `-h`, `--help` | Version / aide | — |

`-n` et `-N` vont ensemble : un seul des deux ⇒ avertissement sur stderr, traité comme un dépôt en échec.

### Quand un mail part-il ?

Règles appliquées dans l'ordre, la première qui s'applique décide :

1. Dépôt Nextcloud en échec ⇒ **mail** à `-d` et `-o` (sauf `no`), voir ci-dessous.
2. Commande en échec ⇒ **mail** à `-d` (+ `-o`, sauf `no`), sujet `*** …`, `X-Priority: 1`.
3. `-o no` ⇒ **pas de mail**.
4. Dépôt Nextcloud réussi ⇒ **mail** seulement avec `-E` ou `-o` (la sortie est déjà sur Nextcloud).
5. Sans Nextcloud ⇒ **mail** si la sortie n'est pas vide, ou avec `-E`.

Le corps contient stdout puis, s'il y en a, stderr après une ligne de `=`.

### Dépôt Nextcloud en échec

Échec = Nextcloud injoignable, pas de connexion en 15 s, pas de réponse en 120 s, réponse HTTP autre que
200/201/204, ou `-n`/`-N` incomplet. L'output n'étant sauvé nulle part :

- le mail part à tous les destinataires (`-d` et `-o`, sauf `no`), même si la commande a réussi ou avec `-o no` ;
- le sujet est préfixé de `**Output non sauvé** ` (avant l'éventuel `*** `), `X-Priority: 1` ;
- le corps commence par la raison de l'échec ;
- l'output (ce qui aurait été déposé : stdout, puis stderr s'il y en a) est joint sous le nom du fichier de l'URL `-n`
  (`…/rapport%20du%20jour.txt` ⇒ `rapport du jour.txt` ; `cronMutt-output.txt` sans `-n`).

### En-têtes ajoutés

`X-cronMutt` (version), `X-cronMuttStart`, `X-cronMuttHost`, `X-cronMuttCmd` (sauf `-c`), `X-cronMuttExitCode`, et
`Message-ID`, `In-Reply-To`, `References`, `Reply-To` (avec `-r`). Les valeurs sont échappées pour mutt (`;`, `#`,
`` ` ``, `$`, `\`).

### Exemples

```bash
# crontab : mail seulement si la sauvegarde échoue ou écrit quelque chose
0 3 * * * cronMutt -s "backup srv1" -d admin@example.com -e "/usr/local/bin/backup"

# sortie toujours déposée sur Nextcloud, mail seulement en cas d'échec
0 4 * * * cronMutt -s "rapport" -o no -n https://nc.example.com/remote.php/dav/files/bot/rapport.txt -N bot:secret -e "rapport.sh"

# mode pipe
df -h | cronMutt -s "disques" -d admin@example.com
```

Dépendances : Python ≥ 3.6, `requests`, `mutt` configuré pour envoyer.

## sleepUntil

```bash
sleepUntil HH:MM[:SS] [commande [arguments...]]
sleepUntil -h | -V
```

Attend l'heure donnée (aujourd'hui) puis lance la commande et rend son code retour (`0` sans commande). Heure déjà
passée ou invalide : message sur stderr et code retour `1`, la commande n'est pas lancée.

- Plusieurs arguments : commande et arguments transmis tels quels (`sleepUntil 10:00 touch "a b"` crée `a b`).
- Un seul argument : ligne de commande passée à `/bin/sh -c` (`sleepUntil 10:00 "backup && rapport > log"`).
- L'horloge est relue au moins toutes les 60 s : le réveil se fait à la bonne heure même après une mise en veille ou un
  changement d'heure système.

## whosshkey

```bash
whosshkey [-H hôte] [-w secondes] [-V] [options de last…]
```

Sortie de `last -Fiw`, avec une colonne de plus : le commentaire de la clef SSH utilisée, retrouvé en croisant les
`Accepted publickey` de sshd (`/var/log/auth.log` et ses rotations, compressées comprises, sinon `journalctl`) avec
les fichiers de clefs de tous les comptes (`AuthorizedKeysFile` de `sshd -T`, à défaut `.ssh/authorized_keys` et
`.ssh/authorized_keys2`). Clef absente de ces fichiers : `clef inconnue (empreinte)` ; clef sans commentaire :
`no comment`. Fonctionne avec gawk comme avec mawk.

| Option | Rôle | Défaut |
|---|---|---|
| `-H hôte` | Lance l'analyse sur un hôte distant via `ssh` + `sudo` (qui peut demander son mot de passe) | local |
| `-w secondes` | Écart maximal entre le log sshd et l'heure de `last` | 10 |
| `-V` | Version | — |

Doit tourner en root (ou sudo) pour lire les logs et les `authorized_keys` des autres comptes.

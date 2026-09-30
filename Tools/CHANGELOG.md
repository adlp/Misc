# Changelog — Tools

## checkssl 1.3 — serveurs en TLS 1.0 / 1.1 — 2026-09-30

- **Serveur en TLS ancien** : OpenSSL 3 refuse par défaut les connexions en dessous de TLS 1.2 ; face à un serveur
  resté en TLS 1.0 (ex. `smtp://mail3.francecreation.com`, STARTTLS port 25), `s_client` échouait avant de recevoir le
  certificat (« unsupported protocol ») et checkssl répondait « Impossible de récupérer le certificat ». `s_client`
  reçoit `-cipher 'DEFAULT:@SECLEVEL=0' -min_protocol TLSv1` : le but est de lire le certificat, pas de juger la
  connexion. Les serveurs récents négocient toujours TLS 1.2 / 1.3 (vérifié : Gmail en TLS 1.3). Vaut pour tous les
  protocoles.

## checkssl 1.2 — SMTP — 2026-09-30

- **`smtp://`** : certificat présenté en STARTTLS par un serveur SMTP, port 25 par défaut (MX), `smtp://hôte:587`
  pour la soumission.
- **`smtps://`** : TLS direct, port 465.
- Vérifié sur `smtp.gmail.com:587`, `smtps://smtp.gmail.com` et le MX `gmail-smtp-in.l.google.com` (port 25).

## whosshkey 1.2 — mawk, fichiers de clefs, logs tournés, -H avec mot de passe sudo — 2026-09-30

Premier numéro de version : 1.0 = version initiale (2024-10-01), 1.1 = analyse distante `-H` (2026-09-23) ; `-V`
l'affiche.

Corrections :

- **mawk** : les expressions régulières utilisaient des répétitions `{4}` que mawk 1.3.4 20200120 (awk par défaut de
  Debian et Ubuntu serveur) ne comprend pas : aucun horodatage reconnu, toutes les lignes sortaient en `-`. Classes
  écrites en entier ; résultat identique avec gawk et mawk.
- **Arrêt silencieux** : un `authorized_keys` vide (ou seulement des commentaires) faisait échouer un `grep` et, avec
  `set -e` + `pipefail`, le script sortait en code 1 sans rien afficher. Une apostrophe dans le commentaire d'une clef
  (« alice's laptop ») faisait échouer `xargs`, même effet. Fichiers lus ligne à ligne, commentaire extrait par `sed`.
- **Clefs avec options** (`from=…,command="ssh-agent …"`) : un `sed` gourmand découpait la ligne au dernier mot
  ressemblant à un type de clef, y compris dans les options ou le commentaire. La ligne entière est passée à
  `ssh-keygen`, qui comprend les options. Une ligne par appel : sur un fichier entier, `ssh-keygen -l` donne à une clef
  sans commentaire le commentaire de la précédente (OpenSSH 8.9).
- **Fichiers de clefs** : seul `.ssh/authorized_keys` était lu ; une clef de `.ssh/authorized_keys2` (défaut Debian)
  sortait en « clef inconnue ». Chemins pris dans `AuthorizedKeysFile` (`sshd -T`, `%h`, `%u`), à défaut les deux
  fichiers par défaut.
- **Logs tournés** : seuls `auth.log` et `auth.log.1` étaient lus, alors que `last` couvre souvent plus ; les
  connexions plus anciennes sortaient en `-`. Tous les `auth.log*` sont lus, compressés compris (`zcat -f`), y compris
  le nommage `auth.log-AAAAMMJJ.gz`.
- **Changement d'année** : les horodatages syslog n'ont pas d'année, `date` prenait l'année courante ; un log de
  décembre lu en janvier tombait dans le futur. Une date à plus d'un jour dans le futur est ramenée d'un an.
- **Date illisible** : `getline` en échec gardait l'horodatage de la ligne précédente ; la ligne est ignorée.
- **`-H`** : le script passait sur le stdin de ssh, donc `sudo` ne pouvait pas demander de mot de passe (« a terminal
  is required ») et `-t` ne servait à rien. Le script voyage dans la commande (base64), stdin reste le terminal. Les
  options de `last` passées à distance gardent leurs espaces (`-t "2026-09-30 12:00"`).
- **Options** : `-H` ou `-w` sans valeur donnaient « unbound variable » ; `-w abc` était accepté. Messages clairs.

Code retiré ou renommé : `sed` de découpe des options et `grep` de filtrage (remplacés par ssh-keygen et la lecture
ligne à ligne), `xargs`, variable `TMPDIR` écrasée (renommée `WORKDIR`, elle était héritée par toutes les commandes
lancées), commentaires qui annonçaient un epoch par ligne de `last` jamais calculé.

## sleepUntil 1.1 — arguments intacts, heure invalide signalée, réveil fiable — 2026-09-30

Premier numéro de version : 1.0 = version initiale (2024-10-08), `-V` l'affiche.

Corrections :

- **Arguments de la commande** : regroupés dans une chaîne puis relancés sans guillemets, ils étaient redécoupés et
  leurs jokers développés : `touch "a b"` créait `a` et `b`, `echo '*'` listait le répertoire. Plusieurs arguments
  sont maintenant transmis tels quels (`exec "$@"`).
- **Commande en un seul argument** : elle était découpée sur les espaces (donc `"cmd1 && cmd2"` ou une redirection ne
  marchaient pas). Elle passe maintenant par `/bin/sh -c`, comme `-e` de cronMutt ; `"ls -l"` marche toujours.
- **Heure invalide** (`abc`, `25:00`) : erreur de `date` puis « déjà passée pour aujourd'hui ». Message
  « Heure invalide » ; code retour `1` inchangé.
- **`-h`** était pris pour une heure (« déjà passée ») : il affiche l'aide ; `-V` ajouté.
- **Réveil en retard** : un seul `sleep` de la durée totale ne compte pas le temps de mise en veille et ignore un
  changement d'heure système. Attente par tranches de 60 s au plus en relisant l'horloge.
- « Déjà passée » et « Heure invalide » vont sur stderr ; coquilles de l'aide corrigées.

Code mort retiré : `command="exit 0"` exécuté comme commande quand aucune n'était donnée, `exit $?` final
inatteignable dans ce cas, variable `current_seconds` lue une seule fois.

## checkssl 1.1 — sans eval, SNI partout, erreurs fiables — 2026-09-30

Premier numéro de version : 1.0 = version initiale (2024-10-08), `-V` l'affiche.

Corrections :

- **Injection de commande** : la commande openssl était construite en texte puis passée à `eval` ; un `;` dans l'URL
  exécutait la suite (`-u "https://x;touch F;"` créait `F`). Arguments passés en tableau, plus d'`eval`.
- **SNI** : envoyé seulement en `https`. En `imap`, `pop3`, `imaps`, `pop3s`, un serveur à plusieurs certificats
  renvoyait son certificat par défaut, pas celui du nom demandé. `-servername` est passé pour tous les protocoles.
- **`file://` avec OpenSSL ≥ 1.1** : le CN restait vide (sujet écrit `CN = x`, le script cherchait `CN=`). Sujet lu en
  RFC 2253, identique pour toutes les versions ; les SAN sont aussi affichés en `file://`.
- **Fichier qui n'est pas un certificat** : `date -d ""` donnait minuit aujourd'hui, d'où « Jours restants : 0 » et
  code `2` au lieu d'une erreur. Sans date de fin lisible : message et code `1`.
- **Serveur muet** : sans délai, openssl pouvait attendre indéfiniment (constaté sur un port IMAP filtré). Délai de
  30 s, puis erreur code `1`.
- **URL sans protocole** : `sed: no previous regular expression` puis « Protocole non supporté ». Message explicite.
  Le protocole s'arrête au premier `://` (une URL contenant `https://` dans sa requête était refusée) et accepte les
  majuscules (`HTTPS://`).
- **`-t`** : `-t abc` valait 0 sans prévenir, un seuil négatif laissait passer un certificat expiré. Entier positif
  exigé.
- **`-i` en IPv6** : mis entre crochets pour `-connect`.
- Messages d'erreur sur stderr ; commentaire « code 2 si moins de 15 jours » faux avec `-t`, corrigé.

Code mort ou en double retiré : `sed` qui retirait une seconde fois `file://`, ligne `cert_info` commentée, traitement
et affichage du certificat écrits deux fois (fichier et serveur) regroupés dans `report_cert`, protocole non supporté
testé deux fois, variable `exit_code`.

## cronMutt 0.24.2 — commentaires et docstrings — 2026-09-30

- Docstring de module (rôle de cronMutt) et de chaque fonction (paramètres, valeur rendue, pourquoi : pas d'exception
  qui remonte de `nextcloudUpload`, caractères interprétés par mutt dans `escapeMuttValue`, threads de `readStream`).
- Code découpé en sections (fonctions, options, valeurs dérivées, capture, dépôt Nextcloud, mail), valeurs par défaut
  annotées de leur option, commentaires sur les points non évidents (fil calculé avant le marquage du sujet, stdin
  `/dev/null`, `errors='replace'`, `--` avant les destinataires, ordre des règles d'envoi, code retour).
- Sans changement de comportement : arbre syntaxique identique à la 0.24.1 hors docstrings et numéro de version.

## cronMutt 0.24.1 — noms explicites — 2026-09-30

- Variables et fonctions renommées, sans changement de comportement : `subprosend` → `sendMail`, `nextcloudput` →
  `nextcloudUpload`, `read_stream` → `readStream`, `muttEscape` → `escapeMuttValue`, `usage`/`version` →
  `printUsage`/`printVersion` ; `dest`/`destok` → `recipients`/`recipientsIfOk`, `datas` → `output`, `muttcmd` →
  `muttCommand`, `retstd` → `capturedOutput`, `ps` → `commandProcess`, `exitCode` → `commandExitCode`, `emptySend` →
  `sendEvenIfEmpty`, `exitReact` → `markSubjectOnError`, `cmdCache` → `hideCommandHeader`, `nextcloud`/`nextauth` →
  `nextcloudUrl`/`nextcloudCredentials`, `sendit` → `mustSendMail`, etc.
- Vérifié : 27 scénarios (pipe, `-e`, `-o`, `-E`, `-X`, Nextcloud OK / en échec / incomplet, signal, encodage, aide)
  donnent les mêmes arguments mutt, corps, pièces jointes, sorties et codes retour qu'en 0.24.

## cronMutt 0.24 — dépôt Nextcloud en échec : « Output non sauvé » et pièce jointe — 2026-09-30

Quand le dépôt Nextcloud échoue — injoignable, pas de connexion en 15 s, pas de réponse en 120 s (délai de connexion
distinct, 120 s partout avant), erreur HTTP, ou `-n`/`-N` incomplet :

- le mail part à **tous** les destinataires, `-d` et `-o` (sauf `no`), même quand la commande a réussi (avant : `-o`
  seul) ;
- sujet préfixé de `**Output non sauvé** `, `X-Priority: 1` ;
- le corps commence par la raison de l'échec (HTTP 507, timeout, etc.) ;
- l'output qui aurait dû être déposé est joint au mail, sous le nom du fichier de l'URL `-n` (décodé :
  `rapport%20du%20jour.txt` ⇒ `rapport du jour.txt`), `cronMutt-output.txt` sans `-n`. Fichier temporaire supprimé
  après l'envoi.

## Tools — README.md — 2026-09-30

- Création du `README.md` de Tools : tableau des outils, options et codes retour de `checkssl`, `sleepUntil`,
  `whosshkey`, et pour `cronMutt` les options, les règles d'envoi du mail, les en-têtes et des exemples.

## cronMutt 0.23 — en-tête References — 2026-09-30

- **References** : ajouté, même valeur que `In-Reply-To` (`<md5@cronMutt>` ou `-i`). Thunderbird et Gmail regroupent
  les fils d'abord par `References` ; sans lui, certains clients ne rangeaient pas les mails d'un même sujet ensemble.

## cronMutt 0.22 — In-Reply-To au format RFC — 2026-09-30

- **In-Reply-To** : le md5 du sujet partait nu (`098f6bcd…`), hors format RFC 5322, et certains clients l'ignoraient
  pour regrouper les mails en fils. Il devient `<md5@cronMutt>` ; la partie droite fixe (pas l'hôte) garde un fil
  commun à toutes les machines pour un même sujet. `-i` est complété de la même façon : `-i foo` → `<foo@cronMutt>`,
  `-i foo@bar` → `<foo@bar>`. Les mails reçus avant la 0.22 ne sont plus dans le même fil que les nouveaux.

## cronMutt 0.21 — Message-ID unique, `-n` sans `-N` signalé — 2026-09-30

- **Message-ID** : par défaut la constante `cronMutt`, identique pour tous les mails et hors format RFC 5322 (certains
  serveurs, Gmail notamment, suppriment les doublons de Message-ID). Il est maintenant unique à chaque mail :
  `<AAAAMMJJhhmmss.pid.aléa.cronMutt@hôte>`. Un `-m` sans `<…>` est complété : `-m foo` → `<foo@hôte>`,
  `-m foo@bar` → `<foo@bar>` ; un `-m` fixe reste fixe (choix de l'utilisateur).
- **`-n` sans `-N`** (ou l'inverse) : le dépôt Nextcloud était ignoré sans rien dire. Avertissement sur stderr et envoi
  par mail comme pour un dépôt en échec, sortie vide comprise.

## cronMutt 0.20 — mode pipe réparé, en-têtes mutt échappés, logique d'envoi Nextcloud restaurée — 2026-09-30

Corrections :

- **Mode pipe** (`commande | cronMutt …`) : stdin n'était plus lu depuis la 0.15 (passage aux threads), aucun mail ne
  partait jamais (ou un mail vide avec `-E`). stdin est relu, décodé selon `-p`.
- **Indentation** : chaque ligne était `strip()`ée, les espaces de début disparaissaient du mail. Seule la fin de ligne
  est retirée (`\r` compris).
- **En-têtes mutt** : mutt interprète la valeur d'un `my_hdr` — `;` et `#` la coupent (le reste part comme commande
  mutt), `` ` `` exécute une commande (la commande `-e` pouvait donc tourner une seconde fois, lancée par mutt), `$`
  expanse une variable d'environnement. `X-cronMuttCmd`, `From`, `In-Reply-To`, `Message-ID` et `Reply-To` sont
  échappés, sauts de ligne remplacés par un espace.
- **Envoi avec Nextcloud** : la réécriture de la 0.17.3 envoyait le mail dès qu'il y avait des données, même quand le
  dépôt Nextcloud avait réussi. Retour au comportement 0.16 / 0.17.1 : Nextcloud OK et commande OK ⇒ mail seulement
  avec `-E` ou `-o`.
- **`-o no`** : si le dépôt Nextcloud échouait alors que la commande avait réussi, le mail partait à l'adresse « no ».
  Il part maintenant à `-d`.
- **Nextcloud** : un mot de passe contenant `:` était tronqué (`split(':',2)`) ; une erreur réseau faisait planter
  cronMutt sans mail ni code retour de la commande. L'erreur est affichée sur stderr et le mail part en secours ;
  délai d'attente de 120 s par opération réseau.
- **`-e`** : le stdin de la commande était un tube jamais fermé — une commande qui lit stdin bloquait indéfiniment. Il
  est maintenant `/dev/null`.
- **Décodage** : un octet invalide pour l'encodage `-p` tuait le thread de lecture (sortie perdue, commande pouvant
  bloquer sur un tube plein). Les octets invalides sont remplacés.
- **Code retour** : commande tuée par un signal ⇒ cronMutt rend 128+signal (comme le shell) au lieu d'un code négatif
  tronqué (-9 donnait 247).
- **`-r`** : documenté « ReplyTo » mais ne posait aucun en-tête `Reply-To` (ne servait que de `From` par défaut).
  Donné explicitement, il pose maintenant `Reply-To`.
- **`--help`** : déclaré mais ignoré, il affiche l'aide.
- **mutt en échec** : son code retour et son stderr étaient jetés ; l'échec est signalé sur stderr.
- Message de debug Nextcloud : `$` parasite retiré.

Code mort retiré : `sys.exit(2)` inatteignable après `usage()`, `errs`, `inf`, `global teeMode`, blocs commentés
d'avant la 0.15, variable `tmp` du sujet.

## cronMutt — historique antérieur

- 0.19 — en-tête de licence GPL.
- 0.18.3 — correction UTF-8 sur la poussée des données vers Nextcloud.
- 0.18.2 — coquille sur les stderr par mail.
- 0.18.1 — initialisation des variables déplacée.
- 0.18 — correctif en l'absence d'environnement.
- 0.17.4 — points de debug.
- 0.17.3 — `-o no` : pas de mail quand tout va bien.
- 0.17.2 — debug des envois vides ou non.
- 0.17.1 — `-o` force le mail malgré Nextcloud.
- 0.17 — `-o` : destinataires du mail quand tout va bien.
- 0.16 — dépôt Nextcloud (`-n`, `-N`) ; mail si erreur, échec Nextcloud ou `-E`.
- 0.15 — affichage stdout en direct (threads).
- 0.14 — code retour de la commande exécutée.
- 0.13 — hostname dans les en-têtes.
- 0.12 — autodétection du mode tee.
- 0.11 — caractères espace Microsoft.
- 0.10 — mode pipe fonctionnel (flush).
- 0.9 — en-têtes date de début, commande, code retour.
- 0.8.1 — en-tête `X-cronMutt`.
- 0.7 — priorité.
- 0.6 — `From` embelli.
- 0.5 — mode tee sans saut de ligne.
- 0.4 — `-X`, changement du `From`, mode tee.
- 0.3 — traitement des erreurs.
- 0.2 — versionnage.
- 0.1 — première version.

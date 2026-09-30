# Changelog — Tools

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

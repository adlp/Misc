# Changelog

## 1.3.0
  * Ajoute le fichier de configuration optionnel `~/.signal-spam.fr.rc` (INI,
    clés `login`/`password`/`directory`/`hide_ip`), avec section `[default]`
    utilisée sans argument et surchargeable par section (`[default]` sert de
    fallback à chaque profil) et par ligne de commande
  * Ajoute `--profile NOM` pour choisir une section du fichier de config
  * Avertit si le fichier de config est lisible par d'autres utilisateurs

## 1.2.0
  * Ajoute `--hide-ip` : retire des en-têtes `Received` l'IP d'un relais interne
    avant envoi, pour faire apparaître la véritable origine du spam
  * Ajoute `--dump-headers` (avec `--dry-run`) : affiche la transformation des
    en-têtes `Received` sans envoyer
  * Ajoute `.gitignore` (`*.eml`, `*.eml.done`, `__pycache__/`)

## 1.1.0
  * Ajoute un compteur de progression `[x/y]` devant chaque ligne OK/FAIL

## 1.0.2
  * Masque le `RequestsDependencyWarning` (urllib3/chardet Debian trop
    récents vs requests) au lancement

## 1.0.1
  * Corrige le signalement : le contenu du mail doit être encodé en base64
    et envoyé comme champ de formulaire classique, pas comme fichier
    multipart brut (sinon HTTP 200 mais mail non pris en compte côté
    signal-spam.fr)
  * HTTP 200 accepté comme succès en plus de 202

## 1.0.0
  * Version initiale : signalement en masse de mails `.eml` à signal-spam.fr
  * Renommage automatique en `.eml.done` après signalement réussi
  * Options `--dry-run`, `--delay`, `--version`

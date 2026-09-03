# Changelog

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

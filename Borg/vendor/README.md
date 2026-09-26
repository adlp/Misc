# vendor/

Code tiers vendorisé (spec-push-vendoring) — `pywebpush`/`py_vapid`/`http_ece` ne sont des paquets
d'aucun dépôt apt Ubuntu (PyPI-only), contrairement à leurs propres dépendances lourdes
(`aiohttp`/`requests`/`cryptography`, toutes dans les dépôts apt). Objectif : notifications push
fonctionnelles en production sans `pip`/`venv` — `apt install python3-aiohttp python3-requests
python3-cryptography` + `git pull` suffisent.

Contenu, **copie strictement fidèle** des wheels PyPI (aucune modification — vérifié `diff -rq` vide
lors du vendoring) :

| Paquet | Version | Licence | Fichier licence |
|--------|---------|---------|------------------|
| `pywebpush` | 2.5.0 | MPL-2.0 | `pywebpush-LICENSE` |
| `py_vapid` | 1.9.4 | MPL-2.0 | `py_vapid-LICENSE` |
| `http_ece` | 1.2.1 | MIT | `http_ece-LICENSE` |

`borgHelperWWW` ajoute ce dossier à `sys.path` avant ses imports optionnels `pywebpush`/`py_vapid`
(voir `_generate_and_store_vapid_keys`/import en tête de fichier) — mêmes conditions d'usage que
l'`import try/except` déjà en place : absent ou cassé, `borgHelperWWW` démarre quand même,
notifications désactivées.

**Mise à jour** : manuelle uniquement, sur CVE ou bug rapporté — jamais automatique. Pour mettre à
jour un paquet : télécharger la nouvelle version (`pip download --no-deps <paquet>`), remplacer les
`.py` de ce dossier par ceux du nouveau wheel (hors `tests/`/`__pycache__`), mettre à jour ce tableau
et `CHANGELOG.md`.

# Changelog — zimLocAccZam

## 1.0.4 — 2026-08-07

- Audit complet post-1.0.3 (tests avec LDAP/Zammad stubbés : création, exclusion, clôture, recréation de ticket) pour vérifier l'absence d'autres régressions du même type que le fix `EXCLUDE_REGEXES`.
- Fix trouvé pendant cet audit : une réponse Zammad non-JSON (proxy cassé, page d'erreur HTML — cas réaliste de panne d'accès) fait lever `response.json()` une erreur de décodage JSON qui n'était pas interceptée par `except requests.exceptions.RequestException`, et tombait donc en "Erreur inattendue" (exit 1) au lieu d'"Erreur d'accès Zammad" (exit 3). Le type d'exception exact dépend même de l'environnement (`simplejson` vs `json` stdlib selon ce qui est installé). Handler élargi à `ValueError` (classe commune aux deux implémentations) pour capturer ce cas de façon portable.

## 1.0.3 — 2026-08-07

- Fix régression introduite en 1.0.2 : `EXCLUDE_REGEXES` était devenue une variable locale à `main()` lors du passage du code principal dans une fonction, alors que `is_excluded()` (au niveau module) y accède en tant que globale → `NameError: name 'EXCLUDE_REGEXES' is not defined` à chaque exécution (capturé par le nouveau handler générique, d'où le message "Erreur inattendue"). Ajout de `global EXCLUDE_REGEXES` dans `main()`.

## 1.0.2 — 2026-08-05

- Plus de stack trace en cas de problème d'accès Zimbra/LDAP ou Zammad. Logique principale déplacée dans `main()`, appelée sous `try/except` :
  - `ldap.LDAPError` / `RuntimeError` (échec `zmlocalconfig`, bind LDAP, recherche LDAP) → message clair sur stderr, exit code `2`.
  - `requests.exceptions.RequestException` (Zammad injoignable/timeout) → message clair sur stderr, exit code `3`.
  - `configparser.Error` / `FileNotFoundError` (config invalide/absente) → message clair sur stderr, exit code `1`.
  - Toute autre exception inattendue → message clair sur stderr, exit code `1` (jamais de traceback brut).

## 1.0.1 — 2026-08-05

Corrections de bugs :

- `close()` : typo `reponse` → `response` (NameError sur échec de fermeture de ticket).
- Argument `-C/--config` : n'utilise plus `action='append'` (provoquait un `TypeError`, `os.path.expanduser` recevait une liste au lieu d'un `str`).
- `Zammad._groupNCo` : attributs de classe par défaut passés de `""` à `None` — la détection "group/customer_id/organization_id manquant" ne se déclenchait jamais.
- `exclude_regexes` vide ne produit plus une regex vide (qui matchait tous les comptes silencieusement).
- Unification du contenu des tickets : les deux chemins de création (nouveau compte / recréation) utilisent désormais le même filtre d'attributs (`filter_infos`), au lieu d'un chemin filtré et l'autre en dump complet.
- Suppression d'un appel API Zammad redondant dans la boucle de détection des comptes débloqués.
- `create()` : accepte aussi le code HTTP `201` (réponse normale de l'API Zammad à la création), pas seulement `200`.
- `Zammad.__init__` lève désormais une `ValueError` explicite si `url`/`token` sont vides, au lieu de retourner silencieusement un objet à moitié initialisé.
- Suppression des imports inutilisés (`time`, `sys`, `ldap.filter`).

## 1.0.0 — 2026-08-05

Version initiale versionnée (commit `5d02937`, "1er round"). Ajout sentry optionnel, filtrage `whatToDump` des attributs LDAP dumpés dans le ticket.

## 0.4 — 2025-09-30

- Boucle "comptes débloqués" : vérifie l'état réel du ticket (`tick`) avant de le clore — gère le cas où le ticket a disparu côté Zammad, et n'essaie plus de fermer un ticket déjà fermé.
- Log explicite si le ticket attendu n'existe plus.

## 0.3 — 2025-09-11

- Ajout de l'option `-n/--no-create` (dry-run : détecte sans créer de ticket).
- Ajout du commentaire d'en-tête décrivant la commande `zmaccts` remplacée.

## 0.2 — 2025-09-08

- Ajout des liens directs vers le ticket (`{ZAMMAD_URL}/#ticket/zoom/{ticket_id}`) dans les messages de création/clôture.
- Ajout d'une note Zammad ("Cloture") avant fermeture du ticket.
- Fix logique : `if not args.silent or args.always` → `and` (le flag `--always` n'aurait sinon jamais eu d'effet réel sur le silence).

## 0.1 — 2025-09-04

Première version connue (pré-git).

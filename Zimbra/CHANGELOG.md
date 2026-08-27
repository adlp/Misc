# Changelog — zimLocAccZam

## fail2ban/ — 2026-08-27 (fix regex audit.log, autres protocoles)

Test du filtre `zimbra-audit.conf` contre les formats imap/pop3/soap (via wiki.zimbra.com "Understanding And Troubleshooting Authentication Log Events" et forums.zimbra.org, pas de log réel disponible pour ces protocoles). Découverte : en imap derrière proxy, `ip=` (IP proxy) et `oip=` (IP réelle) coexistent dans le MÊME bloc avec `oip=` APRÈS `ip=` (`[ip=<proxy>;oip=<réelle>;via=...;ua=...;]`) — l'ancienne regex, qui exigeait `oip=` en tout début de bloc (calée sur le seul cas http_dav observé, où `oip=` est seul), ne matchait donc jamais ce format. Regex réécrite pour chercher `oip=`/`ip=` n'importe où dans la ligne (plus d'ancrage sur la position/l'ordre des champs), avec `\b` pour ne pas confondre `ip=` et le `ip=` interne à `oip=`. Revérifié : http_dav réel, imap avec/sans proxy, succès d'auth (ne doit pas matcher, pas de `error=`) — tous corrects.

## fail2ban/ — 2026-08-27 (fix regex scanners web)

Fix regex suite à test sur une vraie ligne `nginx.access.log` de prod, qui ne matchait pas : `93.123.109.228:44188 - - [27/Aug/2026:00:58:43 +0200]  "GET http://MAUVAISNDD/.env.production HTTP/1.1" 302 338 "-" "l9explore/1.2.2" "-" "100.96.47.2:80"`. Deux problèmes : le format Zimbra logue `IP:port` (l'ancrage `^<HOST> -` ne matchait donc jamais), et la requête peut être en URI absolue (`GET http://host/chemin`) plutôt qu'en chemin relatif. Regex corrigée pour absorber le port après l'IP et matcher le badpath n'importe où dans la cible de requête, chemin relatif ou URI absolue. Revérifié : ancien format (sans port, chemin relatif) toujours détecté, et les 3 chemins Zimbra légitimes (`/principals/`, `/service/soap/AuthRequest`, `/Microsoft-Server-ActiveSync`) toujours 0 faux positif.

## fail2ban/ — 2026-08-25 (scanners web)

Ajout d'un second jail : `zimbra-nginx-scanners`, sur `nginx.access.log`, pour bannir les scans de chemins hors-sujet (WordPress, phpMyAdmin, `.env`/`.git`, exploits Laravel/Symfony/Spring, tout `.php` — Zimbra n'en sert jamais). `maxretry=2` volontairement bas. Nécessite le module `realip` de nginx configuré côté Zimbra (prérequis distinct de `zimbraMailTrustedIP` utilisé pour `audit.log`). Voir `README.md`.

## fail2ban/ — 2026-08-25

Fix regex suite à test sur une vraie ligne `audit.log` de prod : le format réel n'a pas de paire `ip=...;oip=...`, juste `oip=` seul (précédé d'un bloc `[thread:url]` sans rapport). L'ancienne regex `ip=\S+;oip=<HOST>;` ne matchait donc jamais. Corrigé pour chercher `oip=<HOST>` n'importe où dans la ligne, avec fallback sur `ip=<HOST>` seul si `oip=` absent (cas sans trusted proxy configuré).

## fail2ban/ — 2026-08-19

Ajout (non lié au versionnage du script) : filtre + jail fail2ban ciblant les échecs d'authentification dans `/opt/zimbra/log/audit.log`, avec gestion du cas reverse proxy (`ip=` vs `oip=`, cf. `zimbraMailTrustedIP`). Voir `README.md` section "fail2ban".

## 1.0.7 — 2026-08-19

- Filtre LDAP inversé : au lieu de chercher spécifiquement `zimbraAccountStatus=lockout` (fragile — rate tout compte dans un autre état non actif, ou si la valeur exacte diffère), recherche désormais tout compte (`objectClass=zimbraAccount`) dont `zimbraAccountStatus` est renseigné et différent de `active`. Trouvé suite à un cas réel : un compte volontairement bloqué n'était pas détecté (0 résultat confirmé y compris en `ldapsearch` direct avec l'ancien filtre).

## 1.0.6 — 2026-08-19

- Flag `-d/--debug` rendu réellement fonctionnel (jusqu'ici parsé mais jamais utilisé). Affiche sur stderr : config utilisée, `exclude_regexes`, taille du cache chargé, récupération du mot de passe LDAP, bind LDAP OK, nombre de comptes lockout trouvés, et pour chaque compte traité (dans les deux boucles) : exclusion, nouveau/déjà connu, création/recréation de ticket, id du ticket créé, clôture de ticket, écriture finale du cache.

## 1.0.5 — 2026-08-07

- Les messages d'erreur affichés par les handlers top-level (`main()`) incluent désormais le contexte connu au moment de l'exception — compte et/ou numéro de ticket en cours de traitement — quand cette info est disponible. Ex : `Erreur d'accès Zammad : ... [compte=bob@example.org, ticket=5]`. Rien n'est affiché si aucun contexte n'est encore connu (erreur avant la boucle de traitement).

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

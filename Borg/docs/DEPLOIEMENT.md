# Déploiement et installation

Ce document couvre l'installation et le premier démarrage de `borgHelper` (CLI) et `borgHelperWWW`
(API HTTP). Pour l'usage courant une fois en place, voir [USAGE.md](USAGE.md) ; pour l'architecture,
les bases SQLite et l'API en détail, voir [TECHNIQUE.md](TECHNIQUE.md).

## 1. Prérequis système

`borgHelper` (CLI) est **stdlib-only** — aucune dépendance Python externe. Il lui faut seulement
`borg` lui-même dans le `PATH` (ou `BORG_EXE` réglé dans la conf).

`borgHelperWWW` (API HTTP, optionnelle) ajoute :

```bash
pip install fastapi uvicorn pydantic
```

Pour les **notifications push** (optionnelles) :

```bash
apt install python3-aiohttp python3-requests python3-cryptography
```

`pywebpush`/`py_vapid`/`http_ece` eux-mêmes ne sont packagés dans aucun dépôt apt (PyPI-only) — ils
sont **vendorisés** dans `vendor/` (voir `vendor/README.md`), donc **aucun `pip install`/venv requis
pour eux** : un `git pull`/déploiement du dépôt complet suffit une fois les trois paquets apt
ci-dessus installés. Si l'admin ne fait pas cet `apt install`, `borgHelperWWW` démarre quand même —
les notifications push sont simplement désactivées (avertissement au démarrage).

⚠️ **Déployer `vendor/` avec `borgHelperWWW`** (même répertoire) — une copie manuelle limitée à
`borgHelperWWW` et au HTML l'oublie facilement. Le `[WARN]` de démarrage dit exactement ce qui manque
(≥ 1.20.1) : dossier `vendor/` introuvable, module vendorisé absent de `vendor/`, ou paquet apt à
installer — jamais un `pip install`.

## 2. Récupérer le projet

Déployer l'arborescence `Borg/` complète (y compris `vendor/`) à l'emplacement choisi, par exemple
`/opt/borghelper/`. Fichiers/dossiers dont dépend l'exécution :

- `borgHelper` — CLI, exécutable seul.
- `borgHelperWWW` + `borgHelperWWW_ui.html` + `borgHelperWWW_sw.js` + `vendor/` — API HTTP, seulement
  si utilisée. `vendor/` contient aussi Chart.js (graphiques, servi localement : aucun accès Internet
  requis côté navigateur).
- `favicon.ico` (optionnel) — à côté de `borgHelperWWW_ui.html`, servi sur `/favicon.ico`.
- `borgHelperWWW.py` — symlink vers `borgHelperWWW`, **requis uniquement** pour
  `uvicorn borgHelperWWW:app` (uvicorn importe le module par son nom et échoue sans l'extension
  `.py` — inutile en exécution directe `python3 borgHelperWWW ...`).

## 3. Configurer borgHelper (CLI)

Copier [`docs/borghelperrc.example`](borghelperrc.example) — fichier `.borghelperrc` complet et
commenté, une section par nick (= un dépôt borg / une machine sauvegardée) — vers l'emplacement de
votre choix (ex. `/etc/borghelperrc`), puis l'adapter : `BORG_REPO`/`BORG_PASSPHRASE`, `EXCLUDE`
(obligatoire), `KEEP_*` (rétention). `demo.borghelperrc` (à la racine du dépôt) est un second exemple
fonctionnel — dépôts locaux jetables sous `/tmp`, pratique pour vérifier une installation sans toucher
à de vraies données, mais pas pensé comme référence commentée (voir `docs/borghelperrc.example` pour
ça).

**Permissions obligatoires** : `chmod 600` sur le fichier de conf — il contient les passphrases en
clair. `borgHelper` avertit (sans bloquer) si le fichier reste accessible au groupe/autres.

## 4. Premier lancement — borgHelper

```bash
# Vérifie que l'installation elle-même est saine (aucune conf requise) :
borgHelper -c CodecSelfTest

# Initialise un dépôt borg pour un nick (une fois par nick, si le dépôt n'existe pas déjà) :
borgHelper -C /etc/borghelperrc -c Init -n mon-serveur

# Premier backup :
borgHelper -C /etc/borghelperrc -c Bkp -n mon-serveur

# Vérifie l'état sans toucher au réseau :
borgHelper -C /etc/borghelperrc -c Status -n mon-serveur
```

`CodecSelfTest` doit afficher `OK` pour tous les contrôles (300+, code de sortie 0) — sinon
l'installation elle-même (permissions, version Python, `borg` introuvable...) a un problème à
corriger avant d'aller plus loin.

## 5. Configurer et lancer borgHelperWWW (optionnel)

Deux façons de fournir ses réglages, au choix :

- **Fichier séparé** `borghelperwww.conf.example` (racine du dépôt, déjà complet et commenté) —
  adapter au minimum `cfgfile` (le `.borghelperrc` **dédié à l'API**, généralement distinct de celui
  de l'admin CLI) et `api_key`, puis lancer avec `--conf`/`BORGHELPERWWW_CONF`.
- **Fichier unique** (borgHelperWWW ≥ 1.18.6) — poser les mêmes réglages directement dans une section
  `[_borgHelperWWW]` (préfixe `_` réservé — `borgHelper` ignore silencieusement toute section dont le
  nom commence ainsi lors de l'énumération des nicks, `-n ALL` inclus) du `.borghelperrc` dédié à
  l'API (voir [`docs/borghelperrc.example`](borghelperrc.example)) : pas de second fichier à gérer.
  Dernier repli (priorité : CLI > env > `borghelperwww.conf` > cette section > défauts) —
  `borghelperwww.conf`, quand présent, garde la main.

⚠️ **Jamais** une clé `BORGHELPERWWW_*` (majuscule, préfixée) posée nue dans `[DEFAULT]` du
`.borghelperrc` — piège réel constaté (RBAC silencieusement inactif, accès total pour tout
`X-API-Key` valide) : `borgHelperWWW` ≥ 1.18.3 avertit (`[WARN]` au démarrage) si ça arrive, mais
n'active jamais le réglage pour autant. Utiliser `[_borgHelperWWW]` ci-dessus à la place — clés en
minuscule, sans préfixe `BORGHELPERWWW_` (`groups_header`, pas `BORGHELPERWWW_GROUPS_HEADER`).

⚠️ **Un commentaire va toujours sur sa propre ligne**, jamais après une valeur sur la même ligne —
`configparser` ne le coupe jamais (piège réel constaté, voir `docs/borghelperrc.example` en tête de
fichier). `borgHelperWWW` ≥ 1.18.5 refuse de démarrer si `groups_header` n'est pas un nom de header
HTTP valide, plutôt que de planter sur la première requête.

Réglages les plus importants pour un premier déploiement :

| Réglage (fichier conf / variable env / option CLI) | Rôle |
|---|---|
| `cfgfile` / `BORGHELPERWWW_CFGFILE` / `-C` | `.borghelperrc` dédié à l'API |
| `api_key` / `BORGHELPERWWW_API_KEY` / `-K` | Clé attendue dans `X-API-Key` — absente : générée aléatoirement au démarrage (affichée sur stderr, perdue au redémarrage) |
| `host`/`port` | Adresse d'écoute (défaut `127.0.0.1:8000`, exécution directe uniquement) |
| `allow_destructive` / `--allow-destructive` | Autorise `Prune`/`DelBkp` (irréversible) — **interdit par défaut** |
| `allow_downloads` / `--allow-downloads` | Autorise `/download/file`/`/download/tar` — **autorisé par défaut** |
| `groups_header` / `--groups-header` | Active le RBAC par groupes (voir [TECHNIQUE.md](TECHNIQUE.md#auth--rbac)) — désactivé par défaut, `X-API-Key` seul fait foi |
| `push_db` / `--push-db` | Fichier SQLite dédié aux clés VAPID/abonnements push — **jamais reconstructible**, à sauvegarder comme une vraie donnée |
| `push_prefs` / `--push-prefs` | Fichier JSON des préférences de notification (défaut à côté de `push_db`) — éditable à la main, à sauvegarder avec `push_db` |

**Notifications dans le navigateur** : bouton 🔔 de l'UI. **HTTPS obligatoire** (ou `localhost`) —
les navigateurs refusent le push sur une page HTTP. Déployer `borgHelperWWW_sw.js` à côté de
`borgHelperWWW_ui.html` (servi sur `/sw.js`) : absent, le bouton n'apparaît pas. Derrière un reverse
proxy avec préfixe, `/sw.js` doit rester joignable à la racine de l'origine, comme `/`.

Lancement, deux méthodes équivalentes :

```bash
# Exécution directe (lit les options CLI ci-dessus) :
python3 borgHelperWWW --conf /etc/borghelperwww.conf

# Via uvicorn (production — requiert borgHelperWWW.py, le symlink) :
BORGHELPERWWW_CONF=/etc/borghelperwww.conf uvicorn borgHelperWWW:app --host 0.0.0.0 --port 8000
```

Vérification du démarrage :

```bash
curl -s http://127.0.0.1:8000/healthz   # liveness, non protégé
curl -s http://127.0.0.1:8000/version   # versions + postures de sécurité chargées, non protégé
python3 borgHelperWWW -C /etc/borghelperrc-www -K <api_key> --selftest   # contrôles internes push (VAPID/CRUD/expiration), 0 si tout OK
```

## 6. Derrière un reverse proxy (production)

`borgHelperWWW` lie par défaut `127.0.0.1` — pour un accès distant, le placer derrière un reverse
proxy (nginx, Caddy...) qui gère TLS. Réglage `trusted_proxies`/`--trusted-proxies` pour que l'IP
client réelle (`X-Forwarded-For`) remonte correctement dans les logs — défaut `127.0.0.1`, même
comportement qu'`uvicorn` lui-même sans ce réglage.

## 7. RBAC par groupes — restreindre l'accès à un répertoire (ex. restaurations)

`groups_header` (voir tableau ci-dessus) active le RBAC par groupes : un reverse proxy OIDC/
`auth_request` en amont pose un header (ex. `X-Groups`) listant les groupes de l'utilisateur, chaque
nick du `.borghelperrc` porte `GROUPS_ADMIN`/`GROUPS_WRITE`/`GROUPS_READ` (quelles routes/commandes)
et, orthogonalement, un périmètre de chemin **scindé lecture/restauration** (`spec-
groups-paths-restore`, restriction jamais un tier de plus) : `GROUPS_PATHS` pour la lecture
(`Search`/`TreeFind`/`FileHist`/...), `GROUPS_PATHS_RESTORE` pour la restauration/téléchargement
(`Restore`/`DownloadFile`/`DownloadTar`) — un groupe sans entrée dans `GROUPS_PATHS_RESTORE` reprend
simplement son entrée `GROUPS_PATHS` (repli rétro-compatible).

**Sans tier (borgHelperWWW ≥ 1.20.0)** : inutile de mettre un groupe dans
`GROUPS_ADMIN`/`GROUPS_WRITE`/`GROUPS_READ` (= accès à tout le nick) pour ensuite le restreindre. Cité
**seulement** dans `GROUPS_PATHS`, il lit ses chemins (sans téléchargement) ; cité dans
`GROUPS_PATHS_RESTORE`, il peut aussi les télécharger. Exemple `[dbserver01]` dans
[`docs/borghelperrc.example`](borghelperrc.example).

Cas d'usage type : un fileserver sauvegardé en un seul dépôt, où plusieurs groupes doivent pouvoir
chercher/restaurer chacun **uniquement dans son propre périmètre**, sans voir le reste du serveur —
les admins IT gardant, eux, un accès complet. Exemple complet et commenté (nick fictif
`[fileserver01]`) illustrant la diversité de syntaxe possible : un groupe borné à un seul répertoire
(`AD-Borg-Restore-RH`), un groupe borné à plusieurs répertoires à la fois (`AD-Borg-Restore-Direction`,
`|`), deux groupes distincts partageant le même répertoire (`AD-Borg-Restore-Compta`/
`AD-Borg-Restore-Audit`), et un groupe avec une lecture large mais une restauration restreinte
(`AD-Borg-Restore-Audit` peut chercher partout sous `/srv/data/compta` mais ne restaure que depuis
`/srv/data/compta/archives`) : [`docs/borghelperrc.example`](borghelperrc.example), section
« EXEMPLE COMPLET » en bas de fichier.

Le périmètre de chemin est vérifié **côté serveur** à chaque requête (`_resolve_path_scope`,
`TECHNICAL.md`) — jamais une simple restriction d'affichage côté UI, un `Restore` visant un chemin
hors périmètre est refusé même en connaissant le chemin exact. **Aucune permission UNIX de l'host
sauvegardé n'intervient jamais** dans cette décision — être dans le périmètre RBAC suffit strictement
(voir `docs/TECHNIQUE.md`, section Auth, pour la preuve détaillée).

⚠️ Le header n'est vérifié que pour sa **valeur**, pas sa provenance — ce mécanisme suppose que
`borgHelperWWW` n'est atteignable QUE via le reverse proxy de confiance qui pose ce header (bind
`127.0.0.1` + reverse proxy local, ou pare-feu équivalent), même hypothèse que pour
`X-Forwarded-For` (§6).

## Voir aussi

- [TECHNIQUE.md](TECHNIQUE.md) — architecture, bases SQLite, référence API.
- [USAGE.md](USAGE.md) — commandes CLI du quotidien.
- `README.md` (racine du dépôt) — référence exhaustive CLI + API HTTP.
- `TECHNICAL.md` (racine du dépôt) — mécanique interne détaillée, historique des décisions.

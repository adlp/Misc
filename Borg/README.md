# borgHelper  `v1.0.6`

Script Python 3 d'aide à la gestion des sauvegardes [BorgBackup](https://www.borgbackup.org/).  
Centralise la configuration de plusieurs dépôts/serveurs dans un fichier INI et expose des commandes haut niveau.  
Utilisable comme CLI ou comme **librairie Python** — voir [LIBRARY.md](LIBRARY.md).

> Fonctionnement interne et schémas de base de données → [TECHNICAL.md](TECHNICAL.md)

---

## Prérequis

- Python 3.8+
- `borg` dans le PATH
- `prettytable` (`pip install prettytable`) — requis pour `Report` et les commandes d'index

---

## Installation

```bash
cp borgHelper /usr/local/bin/borgHelper
chmod +x /usr/local/bin/borgHelper
```

---

## Fichier de configuration

Par défaut : `~/.borghelperrc`  
Surchargeable avec `-C /autre/chemin`.

Format INI — une section par dépôt enregistré :

```ini
[mon-serveur]
BORG_REPO        = user@repo01:/mnt/borg/mon-serveur
BORG_PASSPHRASE  = motdepasse-du-repo
SER_NAME         = mon-serveur.domaine.com
SER_LOGIN        = root
GLOB_ARCH        = mon-serveur-root-*
MOUNTPOINT       = /mnt/borg/mon-serveur

# Rétention (au moins une clef requise pour Prune)
KEEP_DAILY       = 7
KEEP_WEEKLY      = 4
KEEP_MONTHLY     = 6
KEEP_YEARLY      = 2

# Backup
EXCLUDE          = --exclude /proc --exclude /sys --exclude /dev --exclude /tmp --exclude /run
EXCLUDE_NEXT     = --exclude /var/cache          # exclusions complémentaires optionnelles
BORG_ARCHNAME    = root                          # partie centrale du nom d'archive
BORG_ROOTBKP     = /                             # répertoire racine sauvegardé

# Affichage rapport
MAX_AGE_BKP      = 25                            # alerte si dernière sauvegarde > N heures (défaut 25)
DISPLAY_BKP      = 5                             # nombre de sauvegardes affichées dans Report

# SSH avancé (backup distant)
SSH_REPO         = repo01:/mnt/borg/mon-serveur  # BORG_REPO côté serveur sauvegardé
SSH_REMFO        = 8022:localhost:22             # tunnel inverse SSH
SSH_KEY          = /root/.ssh/id_borg

# Identifiant SQLite (optionnel — surcharge le nick dans le nom des fichiers DB)
DB_NAME          = mon-serveur-home              # → borghelperrc-mon-serveur-home-cache.db

# Désactiver l'indexation pour ce dépôt (Search/FileHist/DuIdx non disponibles)
NOIDX            = 1

# Filtres d'indexation (séparés par espaces)
# Préfixe plain : /home/, /etc  → startswith
# Pattern glob  : *.bak, /home/*/.bash_history  → * matche tout y compris /
IDX_INCLUDE      = /etc /home /root              # liste blanche — seuls ces chemins indexés
IDX_EXCLUDE      = /proc /sys /tmp /var/log *.bak /home/*/.bash_history  # liste noire

# Parallélisation de l'indexation (nombre de borg diff simultanés, défaut 4)
IDX_WORKERS      = 4

# Limiter la taille de diff_index : conserver seulement les N dernières paires indexées
# Non défini = pas de limite (tout l'historique conservé)
DIFF_KEEP        = 30

# Clef explicite (keyfile mode, utile si plusieurs nicks partagent le même dépôt)
BORG_KEY_FILE    = /root/.config/borg/keys/abcdef123456

# Chemin de l'exécutable borg (défaut : 'borg' dans le PATH)
BORG_EXE                    = /usr/local/bin/borg1

# Borg divers
BORG_REMOTE_PATH            = borg1
BORG_RSH                    = ssh -p 2222
BORG_SHOW_SYSINFO           = no
BORG_RELOCATED_REPO_ACCESS_IS_OK = yes
```

Le nickname (nom de section) sert d'identifiant partout avec `-n`.

Répertoire de cache configurable via la clé `CACHE_DIR` dans la section `[DEFAULT]` :

```ini
[DEFAULT]
CACHE_DIR = /data/borgcache
```

---

## Utilisation

```
borgHelper -c <commande> [options]
borgHelper -H <commande>    # aide détaillée d'une commande
borgHelper -h               # aide générale
borgHelper -v               # version
```

Options communes :

| Option | Description |
|--------|-------------|
| `-n <nickname>` | Dépôt cible (défaut : hostname) |
| `-n ALL` | Tous les dépôts du fichier de conf |
| `-d` | Mode debug (cumulable : `-dd`) |
| `-C <fichier>` | Fichier de conf alternatif |

---

## Commandes

### `Stats`
Affiche l'état de montage de chaque dépôt enregistré.

```bash
borgHelper -c Stats
borgHelper -c Stats -n mon-serveur
```

---

### `Login`
Enregistre un dépôt dans `~/.borghelperrc`. Importe optionnellement une clef borg.

```bash
borgHelper -c Login -n mon-serveur -s mon-serveur.domaine.com \
           -p motdepasse -r user@repo:/mnt/borg/srv
borgHelper -c Login -n mon-serveur -p motdepasse -r /mnt/borg/local -k /root/borg.key
```

| Option | Description |
|--------|-------------|
| `-n` | Nickname (section INI) |
| `-s` | Nom du serveur (SER_NAME) |
| `-p` | Passphrase |
| `-r` | Chemin du dépôt |
| `-m` | Mountpoint (défaut : `/mnt/borg/<nick>`) |
| `-k` | Fichier de clef à importer |

---

### `Bkp`
Lance une sauvegarde selon la configuration du dépôt.  
Par défaut, capture les fichiers modifiés pendant le backup (`--list`) et indexe automatiquement dans le SQLite (`diff_index` + snapshot).

```bash
borgHelper -c Bkp -n mon-serveur        # backup + indexation automatique
borgHelper -c Bkp -n mon-serveur -I     # backup seul, sans indexation
```

Nécessite : `EXCLUDE`, `SER_LOGIN`, `SER_NAME`.  
Code retour 0 si succès ou warnings, 2 si erreur borg.

> `-I` désactive `--list` et toute écriture SQLite — utile si l'indexation est gérée séparément via `Index`.

> **Priorité sur Index :** `Bkp` pose un lock sur le dépôt borg (`BORG_REPO`). Si `Index` tourne en parallèle sur n'importe quel nick pointant le même dépôt, il s'interrompt et `Bkp` attend la fin des `borg diff` en cours avant de lancer `borg create` — évite le timeout de verrou borg.

**Sortie stdout (JSON)** — si exit 0, le JSON borg est enrichi de deux clefs borgHelper :

```json
{
  "archive": {
    "name": "mon-serveur-root-2026-06-05T02:00:04",
    "start": "2026-06-05T02:00:04.000000",
    "duration": 42.3,
    "stats": { "nfiles": 183241, "original_size": 9871234560, "...": "..." }
  },
  "cache": { "...": "..." },
  "borgHelper_file_counts": {
    "added": 12,
    "modified": 3,
    "removed": 1
  }
}
```

En mode debug (`-d`), `borgHelper_files` s'ajoute avec la liste complète des fichiers touchés.

---

### `Prune`
Supprime les anciennes archives selon les règles `KEEP_*`.  
**Opération destructive.**

```bash
borgHelper -c Prune -n mon-serveur
borgHelper -c Prune -n ALL
```

Requiert au moins une clef `KEEP_*` dans la conf.  
Enchaîne automatiquement `borg compact`, invalide le cache SQLite, et purge les entrées orphelines du `diff.db`.

---

### `Report`
Rapport sur l'état des sauvegardes — texte (prettytable) ou HTML.

```bash
borgHelper -c Report -n mon-serveur
borgHelper -c Report -n ALL
borgHelper -c Report -n ALL -l              # sortie HTML
borgHelper -c Report -n mon-serveur -N 5    # 5 dernières archives (surcharge DISPLAY_BKP)
borgHelper -c Report -n ALL -j             # sortie JSON
borgHelper -c Report -n ALL -o             # mode offline : stats depuis diff.db, aucun appel borg
borgHelper -c Report -n ALL -o -j          # offline + JSON
borgHelper -c Report -n ALL -o -N 10       # offline + 10 dernières archives
```

Code retour 1 si un dépôt dépasse `MAX_AGE_BKP` heures depuis la dernière sauvegarde.  
Code retour 2 si un dépôt est inaccessible.

**Statistiques de mouvement** (si l'index SQLite est disponible) :
- Colonnes `+ajouté`, `-supprimé`, `=présent` par archive
- Format : `N (P%) · SIZE` — nombre, pourcentage relatif au backup précédent, taille
- `—` si l'archive n'est pas encore indexée

**Mode offline** (`-o`) — rapport sans appel borg, depuis `diff.db` uniquement :
- `taille` et `nfiles` disponibles si `archive_stats` est peuplée (après `Bkp` ou `Index`)
- Combinable avec `-j`, `-l`, `-N <n>`

---

### `LstBkp`
Liste les archives disponibles.

```bash
borgHelper -c LstBkp -n mon-serveur
```

---

### `LstBkpFls`
Liste les fichiers d'une archive.

```bash
borgHelper -c LstBkpFls -n mon-serveur
borgHelper -c LstBkpFls -n mon-serveur -b mon-serveur-root-2025-04-02T21:30:04
```

---

### `DiffBkp`
Différences entre deux archives — un fichier par ligne.

```bash
borgHelper -c DiffBkp -n mon-serveur                          # 2 dernières archives
borgHelper -c DiffBkp -n mon-serveur -b archive-ancienne      # vs dernière
borgHelper -c DiffBkp -n mon-serveur -b archive-1,archive-2   # entre deux précises
```

Première colonne : `+` ajouté, `-` supprimé, `=` présent dans les deux archives (modifié, permissions, type).  
La taille est affichée en fin de ligne : taille finale pour `+`, initiale pour `-`, `avant → après` pour `=`.

```
mon-serveur-root-2026-06-04T02:00:01 → mon-serveur-root-2026-06-05T02:00:01
+ /etc/newfile                    42.3 KB
- /var/log/oldlog                 1.2 MB
= /etc/nginx/nginx.conf           8.5 KB → 9.1 KB
= /etc/hosts                      [C]

+ 1  - 1  = 2
```

Source : index SQLite si la paire est indexée, sinon `borg diff` + stockage automatique.

---

### `Restore`
Restaure un fichier ou une arborescence depuis une archive.

```bash
borgHelper -c Restore -n mon-serveur -b archive-id \
           -f etc/nginx/nginx.conf -w /tmp/restauration
borgHelper -c Restore -n mon-serveur -f etc/nginx/nginx.conf \
           -w /tmp/restauration          # archive auto depuis SQLite
borgHelper -c Restore -n mon-serveur -f 'etc/nginx/*.conf' \
           -w /tmp/backup.tar            # glob → tar avec arborescence
borgHelper -c Restore -n mon-serveur -f 'home/user/*.log' \
           -W /tmp/logs.tgz             # glob → tgz plat
borgHelper -c Restore -n mon-serveur -f 'etc/nginx/*.conf' -L          # liste les droits
borgHelper -c Restore -n mon-serveur -f 'home/user' -w - | tar -tvf -  # tar vers stdout
borgHelper -c Restore -n mon-serveur -f 'home/user' -w - \
           | ssh autre "tar -xf - -C /restore"                          # pipe vers hôte distant
```

| Option | Description |
|--------|-------------|
| `-b` | Nom de l'archive — si absent : dernière archive SQLite contenant `-f` |
| `-f` | Chemin exact ou glob (`*`, `?`) |
| `-w <dest>` | Restauration avec sous-répertoires (répertoire ou `.tar`/`.tgz`) |
| `-w -` | Tar non-compressé vers stdout (pipeable) |
| `-W <dest>` | Restauration plate — fichiers à la racine |
| `-W -` | Tar plat non-compressé vers stdout |
| `-L` | Affiche droits/propriétaires sans restaurer |

> **Priorité sur Index :** `Restore` pose un lock sur le dépôt borg et attend la fin des `borg diff` actifs — même comportement que `Bkp`, même portée inter-nicks.

---

### `Mount` / `UMount`
Monte/démonte les archives via FUSE.  
**Le dépôt ne peut pas être sauvegardé tant qu'il est monté.**

```bash
borgHelper -c Mount -n mon-serveur               # toutes les archives
borgHelper -c Mount -n mon-serveur -b last       # dernière archive
borgHelper -c Mount -n mon-serveur -b archive-id
borgHelper -c UMount -n mon-serveur
```

---

### `Key`
Exporte la clef du dépôt en format papier.

```bash
borgHelper -c Key -n mon-serveur
borgHelper -c Key -n ALL
```

---

### `DelBkp`
Supprime une archive précise. **Opération destructive.**

```bash
borgHelper -c DelBkp -n mon-serveur -b archive-id
```

---

### `Init`
Initialise un nouveau dépôt borg (chiffrement `repokey`).

```bash
borgHelper -c Init -n mon-serveur
```

---

### `Index`
Indexe les diffs entre archives consécutives dans `diff.db`.  
Incrémental — paires déjà traitées ignorées. Met à jour le snapshot de la dernière archive à la fin.

```bash
borgHelper -c Index -n mon-serveur           # diffs + snapshot
borgHelper -c Index -n ALL
borgHelper -c Index -n mon-serveur -F        # force la réindexation complète
borgHelper -c Index -n mon-serveur -S        # snapshot seul
borgHelper -c Index -n mon-serveur -S -F     # force le snapshot seul
```

| Option | Description |
|--------|-------------|
| `-F` | Supprime et recalcule toutes les paires existantes |
| `-S` | Snapshot seul — indexe uniquement le listing de la dernière archive |

Types d'événements : `added`, `removed`, `modified`, `C` (permissions), `B` (lien cassé), `T` (type changé).

> **Interruptible :** si `Bkp` ou `Restore` démarre pendant `Index`, l'indexation s'arrête proprement après les diffs en cours et affiche le nombre de paires restantes. Relancer `Index` reprend là où c'était arrêté (incrémental).

---

### `Search`
Cherche par nom de fichier dans l'index des diffs et dans le snapshot.

```bash
borgHelper -c Search -f passwd -n mon-serveur
borgHelper -c Search -f '*.conf' -n ALL
borgHelper -c Search -f '/etc/nginx*' -n mon-serveur
```

Plage : `-b <archive>` (depuis), `-B <archive>` (jusqu'à), `-b ALL` (tout), sans les deux (dernière paire).

---

### `FileHist`
Historique complet des changements pour un chemin exact.

```bash
borgHelper -c FileHist -f /etc/nginx/nginx.conf -n mon-serveur
borgHelper -c FileHist -f /var/lib/postgresql -n ALL
```

---

### `DuIdx`
Résumé `du -sh`-like depuis le SQLite.

```bash
borgHelper -c DuIdx -n mon-serveur                         # résumé global par type
borgHelper -c DuIdx -f '*' -n mon-serveur                  # détail par répertoire racine
borgHelper -c DuIdx -f 'home/*' -n mon-serveur             # détail sous home/
borgHelper -c DuIdx -f '*.log' -n ALL                      # résumé global sur les .log
borgHelper -c DuIdx -f '*' -s présent:desc -n mon-serveur  # trié par taille présent desc
borgHelper -c DuIdx -f '*' -j -n mon-serveur               # sortie JSON
```

---

### `CacheInfo` / `CacheClean`

```bash
borgHelper -c CacheInfo
borgHelper -c CacheInfo -n mon-serveur
borgHelper -c CacheClean
borgHelper -c CacheClean -n mon-serveur
```

`CacheClean` vérifie le `last_modified` courant et supprime les entrées périmées ou pour des nicks absents de la conf.

---

## Codes retour

| Code | Signification |
|------|---------------|
| 0 | Succès |
| 1 | Avertissement (rapport : sauvegarde trop ancienne) |
| 2 | Erreur borg |
| 3 | État incohérent (déjà monté, serveur inconnu…) |

---

## Exemples de crontab

```cron
# Backup quotidien à 2h
0 2 * * *  borgHelper -c Bkp -n mon-serveur

# Index diff + snapshot après le backup
5 2 * * *  borgHelper -c Index -n mon-serveur

# Prune hebdomadaire le dimanche à 3h
0 3 * * 0  borgHelper -c Prune -n mon-serveur

# Rapport HTML envoyé par mail
30 6 * * *  borgHelper -c Report -n ALL -l | mail -s "Borg $(date +\%F)" admin@domaine.com
```

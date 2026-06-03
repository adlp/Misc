# borgHelper

Script Python 3 d'aide à la gestion des sauvegardes [BorgBackup](https://www.borgbackup.org/).  
Centralise la configuration de plusieurs dépôts/serveurs dans un fichier INI et expose des commandes haut niveau.

---

## Prérequis

- Python 3.8+
- `borg` dans le PATH
- `prettytable` (`pip install prettytable`) — requis pour `Report` en mode texte

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

# Borg divers
BORG_REMOTE_PATH            = borg1
BORG_RSH                    = ssh -p 2222
BORG_SHOW_SYSINFO           = no
BORG_RELOCATED_REPO_ACCESS_IS_OK = yes
```

Le nickname (nom de section) sert d'identifiant partout avec `-n`.

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

```bash
borgHelper -c Bkp -n mon-serveur
```

Nécessite : `EXCLUDE`, `SER_LOGIN`, `SER_NAME`.  
Écrit le rapport JSON dans `/tmp/borgHelper-bkp-<nick>.json`.  
Code retour 0 si succès ou warnings, 2 si erreur borg.

---

### `Prune`
Supprime les anciennes archives selon les règles `KEEP_*`.  
**Opération destructive.**

```bash
borgHelper -c Prune -n mon-serveur
borgHelper -c Prune -n ALL
```

Requiert au moins une clef `KEEP_*` dans la conf.  
Enchaîne automatiquement `borg compact`.

---

### `Report`
Rapport sur l'état des sauvegardes — texte (prettytable) ou HTML.

```bash
borgHelper -c Report -n mon-serveur
borgHelper -c Report -n ALL
borgHelper -c Report -n ALL -l              # sortie HTML
borgHelper -c Report -n mon-serveur -b 5   # afficher 5 dernières archives
```

Code retour 1 si un dépôt dépasse `MAX_AGE_BKP` heures depuis la dernière sauvegarde.

Colonnes : nom, durée, depuis (heures), taille dernière, taille totale, récupérable, espace disque restant.

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
Différences entre deux archives (fichiers modifiés/ajoutés/supprimés).

```bash
borgHelper -c DiffBkp -n mon-serveur                          # 2 dernières archives
borgHelper -c DiffBkp -n mon-serveur -b archive-ancienne      # vs dernière
borgHelper -c DiffBkp -n mon-serveur -b archive-1,archive-2   # entre deux précises
```

---

### `Restore`
Restaure un fichier ou une arborescence depuis une archive.

```bash
borgHelper -c Restore -n mon-serveur -b archive-id \
           -f etc/nginx/nginx.conf -w /tmp/restauration
```

| Option | Description |
|--------|-------------|
| `-b` | Nom de l'archive (ou `last`) |
| `-f` | Chemin relatif à restaurer |
| `-w` | Répertoire de destination |

---

### `Mount` / `UMount`
Monte/démonte une archive via FUSE.  
**Le dépôt ne peut pas être sauvegardé tant qu'il est monté.**

```bash
borgHelper -c Mount -n mon-serveur               # dernière archive
borgHelper -c Mount -n mon-serveur -b archive-id
borgHelper -c Mount -n mon-serveur -b ALL        # toutes les archives
borgHelper -c UMount -n mon-serveur
```

Le répertoire `MOUNTPOINT` doit exister et être vide avant le montage.

---

### `Key`
Exporte la clef du dépôt en format papier (à stocker hors ligne).

```bash
borgHelper -c Key -n mon-serveur
borgHelper -c Key -n ALL
```

---

### `DelBkp`
Supprime une archive précise.  
**Opération destructive.**

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

## Cache

Les appels `borg info --json` coûteux sont mis en cache dans `/tmp/borgsql.db` (SQLite).  
La clef de cache est `(nick, last_modified)` — invalidé automatiquement à chaque nouvelle sauvegarde.

---

## Sentry

Intégration optionnelle pour remonter les erreurs.  
DSN lu dans l'ordre :

1. Variable d'environnement `BORGHELPERC_SENTRY_DSN`
2. Fichier pointé par `BORGHELPERC_SENTRY_FILE`
3. Fichier `/usr/local/etc/borghelper-sentry`

---

### `Index`
Indexe les diffs entre archives consécutives dans `~/.borghelper-diff.db`.  
Incrémental : paires déjà traitées ignorées. À relancer après chaque `Bkp`.

```bash
borgHelper -c Index -n mon-serveur
borgHelper -c Index -n ALL
```

Types d'événements stockés : `added`, `removed`, `modified`, `C` (permissions/proprio), `B` (lien cassé), `T` (type changé).

---

### `Search`
Cherche par nom de fichier dans l'index des diffs.  
Pattern libre (sous-chaîne) ou glob avec `*` et `?`.

```bash
borgHelper -c Search -f passwd -n mon-serveur         # sous-chaîne
borgHelper -c Search -f '*.conf' -n ALL               # glob
borgHelper -c Search -f '/etc/nginx*' -n mon-serveur  # préfixe
```

Colonnes : nick, date, archive, type, chemin, taille avant, taille après.

---

### `FileHist`
Historique complet des changements pour un chemin **exact**.

```bash
borgHelper -c FileHist -f /etc/nginx/nginx.conf -n mon-serveur
borgHelper -c FileHist -f /var/lib/postgresql -n ALL
```

Colonnes : nick, date, archive avant, archive après, type, taille avant, taille après.

---

## Base de données diff

Fichier : `~/.borghelper-diff.db` (SQLite)

Tables :
- `diff_index` — un enregistrement par fichier modifié par paire d'archives
- `diff_indexed_pairs` — sentinel des paires déjà traitées (évite le ré-indexage)

Schéma `diff_index` :

| Colonne | Type | Description |
|---------|------|-------------|
| nick | TEXT | Dépôt borgHelper |
| archive_old | TEXT | Archive source du diff |
| archive_new | TEXT | Archive cible du diff |
| archive_new_date | TEXT | Date ISO de archive_new |
| change_type | TEXT | added / removed / modified / C / B / T |
| path | TEXT | Chemin absolu du fichier |
| size_before | INTEGER | Taille avant en octets (NULL si added) |
| size_after | INTEGER | Taille après en octets (NULL si removed) |

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

# Prune hebdomadaire le dimanche à 3h
0 3 * * 0  borgHelper -c Prune -n mon-serveur

# Rapport HTML envoyé par mail
30 6 * * *  borgHelper -c Report -n ALL -l | mail -s "Borg $(date +\%F)" admin@domaine.com
```

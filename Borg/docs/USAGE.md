# Usage courant — borgHelper (CLI)

Guide par tâche pour un usage quotidien de `borgHelper`. Pour l'installation, voir
[DEPLOIEMENT.md](DEPLOIEMENT.md) ; pour la référence exhaustive de toutes les commandes, voir
`README.md` (racine). Toutes les commandes ci-dessous prennent `-C <fichier .borghelperrc>` si ce
n'est pas celui par défaut, et `-n <nick>` pour cibler un nick précis (`-n ALL` pour tous les nicks
configurés, sur les commandes qui le supportent).

## Lancer un backup

```bash
borgHelper -C /etc/borghelperrc -c Bkp -n mon-serveur
```

Lance le backup avec les réglages du `.borghelperrc` (`KEEP_*`, `EXCLUDE`...). Indexe automatiquement
après coup (sauf `-I` pour désactiver l'indexation, ou `NOIDX=1` réglé en permanence sur ce nick).

## Vérifier l'état, rapidement

```bash
borgHelper -C /etc/borghelperrc -c Status -n mon-serveur      # un nick
borgHelper -C /etc/borghelperrc -c Status -n ALL              # tous les nicks configurés
borgHelper -C /etc/borghelperrc -c Status -n mon-serveur -j   # JSON
```

Affiche, sans jamais appeler `borg` (donc rapide, fonctionne même si le dépôt distant est injoignable)
: le dernier backup connu et son âge, si un backup est en cours (depuis quand), si une opération
prioritaire (`Restore` ou `Prune`) tourne. C'est la commande à utiliser pour un coup d'œil rapide —
`Report`/`LstBkp` ci-dessous font un vrai appel réseau, plus lent.

## Lister les sauvegardes disponibles

```bash
borgHelper -C /etc/borghelperrc -c ListBkp -n mon-serveur
```

Liste les identifiants d'archives (`backupid`) disponibles dans le dépôt — utile pour retrouver
l'archive exacte à passer à `Restore -b`.

## Chercher un fichier ou un répertoire

Deux commandes selon ce qu'on cherche :

```bash
# Par NOM (dernier segment du chemin), insensible à la casse, récursif depuis un préfixe :
borgHelper -C /etc/borghelperrc -c TreeFind -n mon-serveur -m 'nginx.conf'
borgHelper -C /etc/borghelperrc -c TreeFind -n mon-serveur -f /etc -m '*.conf'

# Par SOUS-CHAÎNE dans le CHEMIN COMPLET, à travers l'historique des diffs indexés :
borgHelper -C /etc/borghelperrc -c Search -f 'nginx' -n mon-serveur
```

`TreeFind` répond « où est ce fichier/dossier maintenant (ou juste avant sa suppression) », insensible
à la casse (`nginx` trouve aussi bien `Nginx`/`NGINX`) — `Search` répond « à quels moments ce chemin a
changé », plus utile pour retrouver un fichier supprimé il y a longtemps.

## Voir l'historique complet d'un fichier

```bash
borgHelper -C /etc/borghelperrc -c FileHist -f /etc/nginx/nginx.conf -n mon-serveur
```

Liste tous les changements connus (ajouté/modifié/supprimé) pour ce chemin **exact**, à travers
toutes les archives indexées — pratique pour savoir quand un fichier a changé de taille ou disparu.

## Restaurer

```bash
# Lister d'abord les droits (sans rien restaurer) :
borgHelper -C /etc/borghelperrc -c Restore -n mon-serveur -f /etc/nginx/nginx.conf -L

# Restaurer un fichier vers une destination précise :
borgHelper -C /etc/borghelperrc -c Restore -n mon-serveur -f /etc/nginx/nginx.conf -w /tmp/restauration

# Restaurer depuis une archive précise plutôt que la plus récente :
borgHelper -C /etc/borghelperrc -c Restore -n mon-serveur -b <backupid> -f /etc/nginx -w /tmp/restauration
```

`-w <dest>` restaure en gardant l'arborescence des sous-répertoires sous `<dest>` ; `-W <dest>`
restaure à plat (tous les fichiers directement dans `<dest>`, sans sous-dossiers). `-f` accepte un
chemin exact ou un motif glob.

## Voir aussi

- [DEPLOIEMENT.md](DEPLOIEMENT.md) — installer/configurer avant de pouvoir lancer ces commandes.
- [TECHNIQUE.md](TECHNIQUE.md) — comment ces commandes s'appuient sur les bases SQLite.
- `README.md` (racine) — référence exhaustive : toutes les commandes, tous les flags, sortie JSON de chacune.

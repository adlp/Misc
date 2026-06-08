# Git — Cheat Sheet

## Flux Git

```mermaid
sequenceDiagram
    box Local Repo
        participant WT as working tree
        participant IDX as index / staging area
        participant LB as local branch<br/>(ex: master)
        participant RT as remote-tracking ref<br/>(ex: origin/master)
    end
    box Remote Repo
        participant RB as remote branch
    end

    WT->>IDX: git add
    IDX->>WT: git restore --staged
    IDX->>LB: git commit
    LB->>IDX: git reset HEAD~1
    LB->>RB: git push
    RB->>RT: git fetch
    RB->>WT: git pull
    LB->>WT: git checkout
    RT->>WT: git merge / rebase
```


## Branches

### Visuel — historique

```mermaid
gitGraph
   commit id: "A"
   commit id: "B"
   branch feature
   checkout feature
   commit id: "C"
   commit id: "D"
   checkout main
   commit id: "E"
   merge feature id: "merge"
   branch hotfix
   checkout hotfix
   commit id: "fix"
   checkout main
   merge hotfix
```

### Commandes correspondantes

```bash
# — commits A, B sur main —
git checkout -b feature   # créer et basculer sur feature
# — commits C, D sur feature —
git checkout main         # revenir sur main
# — commit E sur main —
git merge feature         # merger feature → main
git branch -d feature     # supprimer la branche mergée

git checkout -b hotfix    # créer et basculer sur hotfix
# — commit fix —
git checkout main
git merge hotfix
git branch -d hotfix
```

### Référence rapide

```bash
git branch                        # lister les branches locales
git branch -a                     # lister local + remote
git branch <nom>                  # créer une branche
git checkout -b <nom>             # créer et basculer
git switch <nom>                  # basculer (git >= 2.23)
git merge <branche>               # merger dans la branche courante
git rebase <branche>              # rebaser sur <branche>
git branch -d <nom>               # supprimer (si mergée)
git branch -D <nom>               # supprimer (force)
git branch -m <ancien> <nouveau>  # renommer
```

## Remotes

```bash
git remote add <nom> <url>          # ajouter un remote
git remote remove <nom>             # supprimer un remote (nettoie aussi les refs)
git remote -v                       # lister les remotes
```

## Fetch / Push

```bash
git fetch <remote>                  # récupérer sans merger
git push <remote> <branche>         # push vers un remote
git push <remote> <branche> --force # force push (écrase l'historique remote)
```

## Upstream — ne plus préciser la cible à chaque push

```bash
git branch --set-upstream-to=<remote>/<branche> <branche>
# ex : git branch --set-upstream-to=AdlpGiteaMisc/main main
# ensuite : git push   suffit
```

## Historiques sans ancêtre commun

Si deux dépôts ont des historiques distincts (remote initialisé séparément) :

```bash
# Option A — local gagne (destructif pour le remote)
git push <remote> <branche> --force

# Option B — conserver les deux histoires
git merge <remote>/<branche> --allow-unrelated-histories
git push <remote> <branche>
```
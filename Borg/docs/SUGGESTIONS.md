# Suggestions

> **Propositions uniquement.** Rien ici n'est implémenté, validé, ni même formellement spécifié.
> Idées issues de la rédaction de [DEPLOIEMENT.md](DEPLOIEMENT.md), [TECHNIQUE.md](TECHNIQUE.md) et
> [USAGE.md](USAGE.md) — à trier, prioriser ou rejeter, jamais à traiter comme de la doc établie.

## Déploiement / exploitation

- **Fichier(s) unit systemd d'exemple** — un `borghelperww.service` (et éventuellement un
  `borghelper-bkp@.timer`/`.service` pour planifier `Bkp` par nick via `systemd-timer` plutôt que
  cron). *Problème* : aucun exemple de lancement en tant que service n'existe actuellement, chaque
  admin réinvente son propre unit file. *Effort* : petit.
- **Rotation des logs** — `borgHelperWWW` écrit sur stdout/stderr (watcher, erreurs), rien ne couvre
  la rotation si lancé hors systemd (qui la gère nativement via journald). *Problème* : logs illimités
  en déploiement non-systemd (ex. simple `nohup`). *Effort* : petit (doc seule, ou intégration
  `logging.handlers.RotatingFileHandler`).
- **Sauvegarde de `push.db`** — documenté comme non-reconstructible, mais aucune commande/rappel ne
  pousse à le sauvegarder réellement (contrairement à `BORG_REPO` qui EST la sauvegarde). *Problème*
  : un admin peut perdre tous les abonnements push sans s'en rendre compte avant la prochaine panne
  disque. *Effort* : petit (doc + éventuellement un avertissement au démarrage si `push.db` n'a pas
  de copie détectée ailleurs — plus complexe).
- **Commande de validation de configuration** (`borgHelper -c ConfigCheck -n <nick>` ou similaire) —
  vérifie qu'un `.borghelperrc` est cohérent (EXCLUDE présent, BORG_REPO accessible, permissions
  600...) sans lancer de vraie commande. *Problème* : aujourd'hui, une conf invalide n'est détectée
  qu'au moment d'une vraie commande (`Bkp` échoue en plein milieu). *Effort* : moyen.

## Observabilité / monitoring

- **`Status -j` consommé par un check monitoring** (Nagios/Zabbix/Prometheus textfile) — un exemple
  de script wrapper (`borgHelper -c Status -n ALL -j` → sortie compatible) documentant comment
  détecter "aucun backup depuis Xh" ou "backup en échec". *Problème* : `Status` existe (ajouté cette
  session) mais aucun exemple d'intégration monitoring n'est fourni. *Effort* : petit (juste un
  exemple documenté, la commande existe déjà).
- **Endpoint `/healthz` enrichi** — actuellement liveness pure (process répond). Une variante
  `/healthz?deep=true` qui vérifie l'accessibilité effective d'au moins un dépôt/`diff.db` donnerait
  un signal plus utile derrière un load-balancer. *Problème* : `/healthz` actuel ne détecte pas une
  config cassée (mauvais `BORGHELPER_BIN`, `.borghelperrc` illisible). *Effort* : moyen.
- **Logging structuré (JSON) optionnel pour `borgHelperWWW`** — actuellement `print()`/`printer()`
  texte libre vers stdout/stderr. Un mode JSON (une ligne = un événement) faciliterait l'ingestion par
  un stack de logs centralisé. *Effort* : moyen (retouche de tous les points de log existants).

## API / intégration

- **Route `/status`** — exposer la commande `Status` (100% locale, rapide) en HTTP pour un dashboard
  web qui veut un état multi-nick sans lancer N commandes lourdes (`/lstbkp`, `/report`...).
  Explicitement noté hors périmètre de la story `Status` d'origine (CLI-only, décision utilisateur) —
  mais la demande d'un dashboard consommant cette info reviendra probablement. *Effort* : petit (la
  logique existe déjà côté `borgHelper`, juste un nouveau `@router.get` à câbler).
- **Pagination sur `/lstbkpfls`/`/search`** — pour un dépôt avec des dizaines de milliers de fichiers
  par archive, ces routes renvoient potentiellement une réponse énorme en un bloc. *Problème* :
  latence/mémoire côté client sur un gros dépôt. *Effort* : moyen à grand (change le contrat JSON).

## Documentation

- **Générer `docs/borghelperrc.example`/`borghelperwww.conf.example` automatiquement depuis le code**
  (un petit script qui grep les `cfg.get(...)` avec leurs défauts) — évite que ces exemples dérivent
  du code réel avec le temps, comme cela a déjà été noté pour `README.md` (section `Report` obsolète,
  `AGENTS.md`). *Effort* : moyen.

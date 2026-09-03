# SignalSpam

Script Python pour signaler en masse des mails (fichiers `.eml`) à [signal-spam.fr](https://www.signal-spam.fr/) via son API non-officielle.

## Usage

```
python3 signal_spam_report -u ton@email.fr /chemin/vers/mails
```

Mot de passe demandé de façon interactive (ou `-p`).

Options :
  * `--dry-run` — liste les fichiers qui seraient signalés, sans envoyer de requête
  * `--delay N` — délai en secondes entre deux signalements (défaut : 1.0)
  * `--hide-ip IP` — retire des en-têtes `Received` l'IP d'un relais interne avant envoi
    (répétable), pour laisser apparaître l'IP d'origine réelle du spam plutôt que celle
    du dernier relais qui l'a transmis
  * `--dump-headers` — avec `--dry-run` et `--hide-ip` : affiche la transformation des
    en-têtes `Received` (supprimé / révélé) sans rien envoyer
  * `--profile NOM` — section de `~/.signal-spam.fr.rc` à utiliser (défaut : section `[default]`)
  * `--version` — affiche la version

## Fichier de configuration `~/.signal-spam.fr.rc` (optionnel)

Format INI, une section par profil. Toute clé absente d'un profil est complétée par la
section `[default]` (surcharge par section). Toute clé fournie en ligne de commande
prend le pas sur la config, quel que soit le profil. Exemple : `signal-spam.fr.rc.example`
(à copier vers `~/.signal-spam.fr.rc`).

Sans `--profile`, la section `[default]` est utilisée telle quelle — c'est elle qui
permet l'appel sans aucun paramètre (`python3 signal_spam_report`). Avec
`--profile travail`, `login` et `directory` sont ceux de `[travail]`, `password` et
`hide_ip` sont hérités de `[default]`.

Toutes les clés sont optionnelles et individuellement surchargeables en ligne de
commande (`-u`, `-p`, `directory` positionnel, `--hide-ip`). Le fichier lui-même est
optionnel : sans lui, `-u`/le répertoire redeviennent obligatoires en ligne de commande.

Le fichier peut contenir un mot de passe en clair : `chmod 600 ~/.signal-spam.fr.rc`
(un avertissement est affiché sinon).

### Exemple : masquer un relais interne

Si un mail passe par un relais interne (ex. `8.8.8.8`) avant d'arriver sur le serveur
final, signal-spam.fr peut identifier ce relais comme étant le spammeur au lieu de la
véritable origine. `--hide-ip` retire l'en-tête `Received` correspondant à ce relais,
ce qui fait apparaître l'en-tête `Received` suivant (l'IP réelle) en tête de chaîne :

```
python3 signal_spam_report --dry-run --dump-headers --hide-ip 8.8.8.8 -u ton@email.fr /chemin/vers/mails
```

Une fois la transformation vérifiée, relancer sans `--dry-run --dump-headers` pour
envoyer réellement (le `--hide-ip` reste actif).

Chaque mail signalé avec succès (HTTP 200 ou 202) voit son fichier renommé de `.eml` en `.eml.done`, ce qui permet de relancer le script sans re-signaler les mêmes mails.

## API signal-spam.fr

Non documentée officiellement (reverse-engineering du plugin Thunderbird) :
  * `POST https://www.signal-spam.fr/api/signaler`
  * Auth Basic avec login/mot de passe du compte signal-spam.fr
  * Corps formulaire, champ `message` = contenu du `.eml` encodé en base64
  * Succès = HTTP 200 ou 202

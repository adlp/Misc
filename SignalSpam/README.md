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
  * `--version` — affiche la version

Chaque mail signalé avec succès (HTTP 202) voit son fichier renommé de `.eml` en `.eml.done`, ce qui permet de relancer le script sans re-signaler les mêmes mails.

## API signal-spam.fr

Non documentée officiellement (reverse-engineering du plugin Thunderbird) :
  * `POST https://www.signal-spam.fr/api/signaler`
  * Auth Basic avec login/mot de passe du compte signal-spam.fr
  * Corps `multipart/form-data`, champ `message` = contenu brut du `.eml`
  * Succès = HTTP 202

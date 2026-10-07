# Changelog — sshvault

## sshvault 0.1.0 — Squelette et lecture du coffre via bw — 2026-10-06

- CLI `sshvault` (Python ≥ 3.10, bibliothèque standard seule) installable par
  `uv tool install` : `status`, `login [--server URL] [--apikey]`, `unlock [--ttl]`,
  `lock`, `sync`, `list [--json]`, `search MOTIF [--host|--name|--fingerprint] [--json]`,
  option globale `--nointeraction`.
- Interface `VaultBackend` et première implémentation `BwBackend` (CLI `bw` en
  sous-processus, données dédiées dans `${XDG_DATA_HOME:-~/.local/share}/sshvault/bw`,
  `--nointeraction`, délai borné, mot de passe par `--passwordenv`).
- Éléments « SSH key » (type 5) seuls ; hôtes dans le champ personnalisé
  `sshvault-hosts` (virgules, insensible à la casse).
- Distinction « non connecté », « verrouillé » (code 3) et « erreur du backend »
  (code 4) : une panne de `bw` ne déclenche pas d'invite.
- Session dans le keyring `@u` avec expiration noyau, repli fichier 0600 dans
  `$XDG_RUNTIME_DIR/sshvault/` ; session refusée par `bw` purgée.
- `sync` relancé une fois si `bw` reste bloqué (connexion TLS neuve jamais acquittée,
  mesurée) : deux essais de `SSHVAULT_BW_TIMEOUT`/2 par passage.
- Délais `SSHVAULT_BW_TIMEOUT` et `SSHVAULT_PROMPT_TIMEOUT` validés (0 < v ≤ 86400,
  sinon code 2) ; repli fichier de la session seulement sur un tmpfs privé ; texte du
  coffre nettoyé des caractères de contrôle en sortie texte ; motif vide refusé ;
  écho du terminal rétabli si `bw login` est interrompu.
- Invite `/dev/tty` ou askpass selon `SSH_ASKPASS_REQUIRE` (`man ssh`), délai borné.
- Tests : faux `bw` fidèle (messages mesurés sur le vrai bw 2026.9.1), matrice des
  entrées et cas limites ; intégration (marqueur `integration`) sur le compte de test dédié par défaut,
  éléments marqués `sshvault-test-run` et supprimés en fin de test ; mode conteneur
  Vaultwarden 1.37.4 en option.

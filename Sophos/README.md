# Sophos

Scripts d'administration d'environnements Sophos.

## Scope actuel

- **Sophos Firewall (XGS)** — scripts d'administration via API (règles, VPN, monitoring)

D'autres produits Sophos (Central, etc.) pourront être ajoutés par la suite.

## Structure

- `firewall-xgs/fail2ban/` — action fail2ban qui bloque/débloque des IP sur
  un Sophos Firewall XGS via son API XML (voir README du sous-dossier)
- `firewall-xgs/dhcp_leases.py` — liste les baux du serveur DHCP du XGS via
  l'API (`--json`, `--csv`, `--filter`, `--raw` ; nom d'entité API `DHCPLease`
  à valider sur le firewall, voir `--entity`)
- `firewall-xgs/upload_cert.py` — dépose (`--upsert`/`--update` pour mettre à
  jour) un certificat PEM ou PKCS12 via l'API (syntaxe d'upload à valider sur
  le firewall, `--dry-run`/`--debug` disponibles)

Ces deux scripts lisent la même config `[api]` que `sophos_fw_block.py`, dans
l'ordre : `--config`, `~/.sophos-fw-block.conf` (home de l'utilisateur, à
protéger en `chmod 600`), puis `/usr/local/etc/sophos-fw-block.conf`.

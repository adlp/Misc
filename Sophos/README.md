# Sophos

Scripts d'administration d'environnements Sophos.

## Scope actuel

- **Sophos Firewall (XGS)** — scripts d'administration via API (règles, VPN, monitoring)

D'autres produits Sophos (Central, etc.) pourront être ajoutés par la suite.

## Structure

- `firewall-xgs/fail2ban/` — action fail2ban qui bloque/débloque des IP sur
  un Sophos Firewall XGS via son API XML (voir README du sous-dossier)

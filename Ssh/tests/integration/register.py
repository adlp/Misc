"""Inscription d'un compte Vaultwarden par l'API, pour les tests d'intégration seulement.

`bw` n'a pas de commande `register` : ce script fait la crypto d'inscription
Bitwarden (dépendance de test `cryptography`, absente de sshvault).

- clé maître = PBKDF2-SHA256(mot de passe, sel = e-mail en minuscules, N itérations, 32 o) ;
- hash d'authentification = PBKDF2-SHA256(clé maître, sel = mot de passe, 1 itération) ;
- clé maître étirée = HKDF-Expand(clé maître, "enc") ‖ HKDF-Expand(clé maître, "mac") ;
- clé utilisateur aléatoire (64 o), chiffrée par la clé étirée (EncString type 2 :
  AES-256-CBC + HMAC-SHA256) ;
- paire RSA-2048 : clé publique SPKI DER, clé privée PKCS#8 DER chiffrée par la clé utilisateur.

Flux Vaultwarden 1.37.4 (identity.rs) : `register/send-verification-email` renvoie
le jeton dans la réponse quand le courrier est désactivé, puis `register/finish`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.request

from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KDF_PBKDF2 = 0
ITERATIONS = 600_000


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hkdf_expand(prk: bytes, info: bytes, length: int = 32) -> bytes:
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:length]


def enc_string(data: bytes, enc_key: bytes, mac_key: bytes) -> str:
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    enc = Cipher(algorithms.AES(enc_key), modes.CBC(iv)).encryptor()
    ct = enc.update(padded) + enc.finalize()
    mac = hmac.new(mac_key, iv + ct, hashlib.sha256).digest()
    return "2.%s|%s|%s" % (b64(iv), b64(ct), b64(mac))


def registration_body(email: str, password: str, token: str, iterations: int = ITERATIONS) -> dict:
    salt = email.strip().lower()
    master_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations, 32)
    auth_hash = b64(hashlib.pbkdf2_hmac("sha256", master_key, password.encode(), 1, 32))
    stretched_enc = hkdf_expand(master_key, b"enc")
    stretched_mac = hkdf_expand(master_key, b"mac")
    user_key = os.urandom(64)
    protected_user_key = enc_string(user_key, stretched_enc, stretched_mac)
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_der = priv.public_key().public_bytes(serialization.Encoding.DER,
                                              serialization.PublicFormat.SubjectPublicKeyInfo)
    priv_der = priv.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
    # Format « ancien » de RegisterData (RegisterDataOld), toujours accepté par la 1.37.4.
    return {
        "email": salt,
        "name": "sshvault-test",
        "emailVerificationToken": token,
        "masterPasswordHash": auth_hash,
        "masterPasswordHint": None,
        "key": protected_user_key,
        "kdf": KDF_PBKDF2,
        "kdfIterations": iterations,
        "keys": {"publicKey": b64(pub_der),
                 "encryptedPrivateKey": enc_string(priv_der, user_key[:32], user_key[32:])},
    }


def _post(url: str, body: dict, accept: str = "application/json") -> bytes:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": accept,
                                          "Bitwarden-Client-Name": "cli", "Bitwarden-Client-Version": "2026.9.1",
                                          "Device-Type": "8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def register(base_url: str, email: str, password: str) -> None:
    base = base_url.rstrip("/")
    raw = _post(base + "/identity/accounts/register/send-verification-email",
                {"email": email, "name": "sshvault-test"}).decode().strip()
    token = json.loads(raw) if raw.startswith('"') else raw
    if not token:
        raise RuntimeError("Vaultwarden n'a pas renvoyé de jeton d'inscription (courrier activé ?)")
    _post(base + "/identity/accounts/register/finish", registration_body(email, password, token))


if __name__ == "__main__":
    import sys
    # usage : SSHVAULT_IT_PASSWORD=… python register.py <url> <e-mail>
    register(sys.argv[1], sys.argv[2], os.environ["SSHVAULT_IT_PASSWORD"])
    print("compte créé : %s" % sys.argv[2])

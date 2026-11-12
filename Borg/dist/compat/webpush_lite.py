#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""webpush_lite : Web Push autonome (stdlib seule) pour Python 3.10+.

Ce module remplace ``pywebpush`` + ``py_vapid`` + ``http_ece`` pour l'usage
qu'en fait ``borgHelperWWW`` : envoyer une notification Web Push chiffrée
(RFC 8291 / RFC 8188, encodage ``aes128gcm``) avec authentification VAPID
(RFC 8292).  Il est conçu pour être embarqué tel quel dans un fichier généré
puis enregistré dans ``sys.modules`` sous les deux noms ``pywebpush`` et
``py_vapid`` (un seul objet module pour les deux)::

    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid

Dépendances
-----------
* Au niveau module : uniquement la bibliothèque standard, plus un
  ``import cryptography`` *optionnel* (``try/except``).
* Deux backends pour les primitives (ECDH P-256, ECDSA P-256/SHA-256,
  AES-128-GCM) :

  1. ``cryptography`` si elle est importable et opérationnelle (plus sûr,
     temps constant, plus rapide) ;
  2. repli en Python pur (arithmétique P-256 en coordonnées jacobiennes,
     ECDSA à nonce déterministe RFC 6979, AES-128 à tables + GCM).  Ce repli
     n'est **pas** en temps constant : Python ne le permet pas.  Il suffit
     pour des clés VAPID/éphémères de notification, pas pour un usage
     cryptographique général.

  ``_FORCE_PURE = True`` (ou ``_use_pure(True)``) force le repli, ce que
  font les tests.

Écarts volontaires par rapport à pywebpush 2.5
----------------------------------------------
* Seul l'encodage ``aes128gcm`` est pris en charge (pas ``aesgcm``) ;
  tout autre ``content_encoding`` lève ``WebPushException``, même sans données.
* ``requests_session`` est accepté mais **ignoré** (pas de ``requests``) ;
  il n'y a pas de ``webpush_async`` ni de ``WebPusher``.
* Transport : ``urllib.request`` (``HTTPS_PROXY``/``NO_PROXY`` de
  l'environnement respectés, contexte TLS par défaut).  Les redirections
  HTTP ne sont **pas** suivies (une 3xx est traitée comme un échec) afin de
  ne jamais renvoyer l'en-tête ``Authorization`` vers un autre hôte.
* ``timeout=None`` vaut 30 s (pywebpush : 10000 s).
* ``vapid_claims`` n'est jamais modifié (copie), contrairement à pywebpush.
* ``sub`` est exigé (non vide) mais son format (``mailto:``/``https:``)
  n'est pas contraint.
* Les erreurs de clé VAPID sont des ``WebPushException``
  (``VapidException`` en est une sous-classe).
* Les erreurs réseau (``URLError``, délai dépassé, TLS) remontent telles
  quelles (sous-classes d'``OSError``).
* ``curl=True`` renvoie une commande décrite par une chaîne ; aucun fichier
  ``encrypted.data`` n'est écrit (le corps est passé en base64).
* Un corps de plus de 3993 octets (plafond des services Push : 4096 octets
  au total) lève ``WebPushException("Data too large")``.
"""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

try:  # TLS : absent sur de rares builds minimaux, l'HTTP clair reste utilisable
    import ssl as _ssl
except Exception:  # pragma: no cover
    _ssl = None

__version__ = "1.0"

__all__ = [
    "WebPushException", "VapidException", "Vapid", "Vapid01", "Vapid02",
    "webpush", "generate_raw_keys", "b64urlencode", "b64urldecode",
    "num_to_bytes", "ece_encrypt_aes128gcm", "ece_decrypt_aes128gcm",
    "es256_sign_jwt", "es256_verify_jwt",
]

# --------------------------------------------------------------------------
# Backend « cryptography » optionnel
# --------------------------------------------------------------------------

_FORCE_PURE = False
"""Si vrai, le repli en Python pur est utilisé même si ``cryptography`` est là."""

_HAVE_CRYPTO = False
try:  # ImportError, mais aussi toute autre erreur (binaire cassé, etc.)
    from cryptography.exceptions import InvalidTag as _InvalidTag
    from cryptography.hazmat.primitives import hashes as _c_hashes
    from cryptography.hazmat.primitives.asymmetric import ec as _c_ec
    from cryptography.hazmat.primitives.asymmetric import utils as _c_utils
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM

    # Auto-test minimal : on n'active le backend que s'il fonctionne vraiment.
    _k = _c_ec.derive_private_key(1, _c_ec.SECP256R1())
    _c_utils.decode_dss_signature(
        _k.sign(b"x", _c_ec.ECDSA(_c_hashes.SHA256())))
    _AESGCM(b"\0" * 16).decrypt(
        b"\0" * 12, _AESGCM(b"\0" * 16).encrypt(b"\0" * 12, b"x", None), None)
    _k.exchange(_c_ec.ECDH(), _k.public_key())
    del _k
    _HAVE_CRYPTO = True
except Exception:  # noqa: BLE001 - voulu : n'importe quel échec => repli pur
    _HAVE_CRYPTO = False


def _use_pure(flag=True):
    """Force (``True``) ou libère (``False``) le repli en Python pur."""
    global _FORCE_PURE
    _FORCE_PURE = bool(flag)


def _crypto_active():
    """Vrai si le backend ``cryptography`` est utilisé pour les appels courants."""
    return _HAVE_CRYPTO and not _FORCE_PURE


# --------------------------------------------------------------------------
# Utilitaires base64url / entiers
# --------------------------------------------------------------------------

def b64urlencode(data):
    """Encode des octets en base64url **sans** padding (renvoie une ``str``)."""
    return base64.urlsafe_b64encode(bytes(data)).decode("ascii").rstrip("=")


def b64urldecode(data):
    """Décode du base64url (``str`` ou ``bytes``), padding facultatif.

    Les caractères ``+`` et ``/`` du base64 standard sont aussi tolérés, ainsi
    que les espaces et retours à la ligne.
    """
    if isinstance(data, str):
        data = data.encode("ascii")
    data = bytes(data)
    data = b"".join(data.split()).replace(b"+", b"-").replace(b"/", b"_")
    data = data.rstrip(b"=")
    if len(data) % 4 == 1:
        raise ValueError("base64 invalide (longueur)")
    data += b"=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("base64 invalide : %s" % exc) from None


def num_to_bytes(n, size):
    """Entier -> ``size`` octets big-endian (``OverflowError`` si trop grand)."""
    return int(n).to_bytes(size, "big")


# --------------------------------------------------------------------------
# Exceptions et réponse HTTP
# --------------------------------------------------------------------------

class WebPushException(Exception):
    """Échec Web Push ; peut contenir la réponse HTTP du service Push."""

    def __init__(self, message, response=None):
        super().__init__(message)
        self.message = message
        self.response = response

    def __str__(self):
        extra = ""
        if self.response is not None:
            try:
                extra = ", Response {}".format(self.response.text)
            except AttributeError:
                extra = ", Response {}".format(self.response)
        return "WebPushException: {}{}".format(self.message, extra)

    @property
    def status_code(self):
        """Statut HTTP de la réponse (``status_code`` puis ``status``), ou None."""
        if self.response is None:
            return None
        return getattr(self.response, "status_code",
                       getattr(self.response, "status", None))

    @property
    def retry_after(self):
        """En-tête ``Retry-After`` de la réponse (secondes ou date HTTP), ou None."""
        headers = getattr(self.response, "headers", None) or {}
        return headers.get("Retry-After", None)


class VapidException(WebPushException):
    """Erreur de clé ou de revendications VAPID."""


class CaseInsensitiveDict(dict):
    """Dictionnaire à clés ``str`` insensibles à la casse (clés stockées en minuscules)."""

    def __init__(self, data=None, **kwargs):
        super().__init__()
        if data:
            self.update(data)
        if kwargs:
            self.update(kwargs)

    @staticmethod
    def _k(key):
        return key.lower() if isinstance(key, str) else key

    def __contains__(self, key):
        return dict.__contains__(self, self._k(key))

    def __setitem__(self, key, value):
        dict.__setitem__(self, self._k(key), value)

    def __getitem__(self, key):
        return dict.__getitem__(self, self._k(key))

    def __delitem__(self, key):
        dict.__delitem__(self, self._k(key))

    def get(self, key, default=None):
        return dict.get(self, self._k(key), default)

    def pop(self, key, *default):
        return dict.pop(self, self._k(key), *default)

    def setdefault(self, key, default=None):
        return dict.setdefault(self, self._k(key), default)

    def update(self, data=(), **kwargs):
        items = data.items() if hasattr(data, "items") else data
        for key, value in items:
            self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def copy(self):
        return CaseInsensitiveDict(self)


class _Response:
    """Réponse HTTP minimale, compatible avec l'usage de ``requests.Response``."""

    def __init__(self, status_code, reason, content, headers, url):
        self.status_code = int(status_code)
        self.reason = reason
        self.content = content
        self.headers = headers
        self.url = url

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return json.loads(self.text)

    def __repr__(self):
        return "<Response [%d]>" % self.status_code


# --------------------------------------------------------------------------
# Repli Python pur : courbe P-256 (secp256r1 / prime256v1)
# --------------------------------------------------------------------------

_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
_GX = 0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296
_GY = 0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5
_G = (_GX, _GY)
_INF = (0, 1, 0)  # point à l'infini en coordonnées jacobiennes (Z == 0)


def _jac_double(pt):
    x1, y1, z1 = pt
    if z1 == 0 or y1 == 0:
        return _INF
    p = _P
    delta = z1 * z1 % p
    gamma = y1 * y1 % p
    beta = x1 * gamma % p
    alpha = 3 * (x1 - delta) * (x1 + delta) % p  # a = -3
    x3 = (alpha * alpha - 8 * beta) % p
    z3 = ((y1 + z1) ** 2 - gamma - delta) % p
    y3 = (alpha * (4 * beta - x3) - 8 * gamma * gamma) % p
    return (x3, y3, z3)


def _jac_add(p1, p2):
    x1, y1, z1 = p1
    x2, y2, z2 = p2
    if z1 == 0:
        return p2
    if z2 == 0:
        return p1
    p = _P
    z1z1 = z1 * z1 % p
    z2z2 = z2 * z2 % p
    u1 = x1 * z2z2 % p
    u2 = x2 * z1z1 % p
    s1 = y1 * z2 * z2z2 % p
    s2 = y2 * z1 * z1z1 % p
    h = (u2 - u1) % p
    if h == 0:
        if s1 == s2:
            return _jac_double(p1)
        return _INF
    i = (2 * h) ** 2 % p
    j = h * i % p
    r = 2 * (s2 - s1) % p
    v = u1 * i % p
    x3 = (r * r - j - 2 * v) % p
    y3 = (r * (v - x3) - 2 * s1 * j) % p
    z3 = (((z1 + z2) ** 2 - z1z1 - z2z2) * h) % p
    return (x3, y3, z3)


def _to_affine(pt):
    x, y, z = pt
    if z == 0:
        return None
    zi = pow(z, -1, _P)
    zi2 = zi * zi % _P
    return (x * zi2 % _P, y * zi2 * zi % _P)


def _on_curve(x, y):
    return (0 <= x < _P and 0 <= y < _P
            and (y * y - (x * x * x - 3 * x + _B)) % _P == 0)


def _mul_jac(k, point):
    """k * point (point affine) par échelle de Montgomery ; résultat jacobien.

    L'échelle effectue la même suite d'opérations (addition + doublement) quel
    que soit le bit du scalaire ; en Python on ne peut pas garantir mieux.
    """
    r0 = _INF
    r1 = (point[0], point[1], 1)
    for i in range(k.bit_length() - 1, -1, -1):
        if (k >> i) & 1:
            r0 = _jac_add(r0, r1)
            r1 = _jac_double(r1)
        else:
            r1 = _jac_add(r0, r1)
            r0 = _jac_double(r0)
    return r0


def _mul(k, point):
    """k * point -> point affine (ou ``None`` pour l'infini)."""
    return _to_affine(_mul_jac(k % _N if k >= _N else k, point))


def _decode_point(data):
    """Décode et valide un point non compressé (65 octets) -> ``(x, y)``."""
    data = bytes(data)
    if len(data) != 65 or data[0] != 4:
        raise ValueError("point P-256 : 65 octets non compressés (0x04) attendus")
    x = int.from_bytes(data[1:33], "big")
    y = int.from_bytes(data[33:], "big")
    if not _on_curve(x, y):
        raise ValueError("point P-256 invalide (hors courbe)")
    return (x, y)


def _encode_point(pt):
    return b"\x04" + pt[0].to_bytes(32, "big") + pt[1].to_bytes(32, "big")


def _pure_pub_from_priv(d):
    return _encode_point(_mul(d, _G))


def _pure_ecdh(d, pub):
    q = _decode_point(pub)
    shared = _mul(d, q)
    if shared is None:  # impossible pour d dans [1, n-1] et q d'ordre n
        raise ValueError("ECDH : point résultat à l'infini")
    return shared[0].to_bytes(32, "big")


def _rfc6979_candidates(d, h1):
    """Générateur des nonces candidats de la RFC 6979 (HMAC-SHA256, P-256)."""
    x = d.to_bytes(32, "big")
    h = (int.from_bytes(h1, "big") % _N).to_bytes(32, "big")  # bits2octets
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        cand = int.from_bytes(v, "big")
        if 1 <= cand < _N:
            yield cand
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def _pure_ecdsa_sign(d, msg):
    """ECDSA P-256/SHA-256 à nonce déterministe (RFC 6979) -> ``(r, s)``."""
    h1 = hashlib.sha256(msg).digest()
    z = int.from_bytes(h1, "big")
    for k in _rfc6979_candidates(d, h1):
        pt = _mul(k, _G)
        r = pt[0] % _N
        if r == 0:
            continue
        s = pow(k, -1, _N) * (z + r * d) % _N
        if s == 0:
            continue
        return r, s


def _pure_ecdsa_verify(pub, msg, r, s):
    """Vérification ECDSA P-256/SHA-256 en Python pur (``pub`` : 65 octets)."""
    if not (1 <= r < _N and 1 <= s < _N):
        return False
    q = _decode_point(pub)
    z = int.from_bytes(hashlib.sha256(msg).digest(), "big")
    w = pow(s, -1, _N)
    pt = _to_affine(_jac_add(_mul_jac(z * w % _N, _G),
                             _mul_jac(r * w % _N, q)))
    return pt is not None and pt[0] % _N == r


# --------------------------------------------------------------------------
# Repli Python pur : AES-128 (chiffrement de bloc) + GCM
# --------------------------------------------------------------------------

def _build_aes_tables():
    sbox = [0] * 256
    p = q = 1
    while True:  # inverses dans GF(2^8) par parcours du groupe multiplicatif
        p = (p ^ (p << 1) ^ (0x1B if p & 0x80 else 0)) & 0xFF
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q
        for sh in (1, 2, 3, 4):
            x ^= ((q << sh) | (q >> (8 - sh))) & 0xFF
        sbox[p] = x ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    te0 = []
    for s in sbox:
        s2 = ((s << 1) ^ 0x1B) & 0xFF if s & 0x80 else s << 1
        s3 = s2 ^ s
        te0.append((s2 << 24) | (s << 16) | (s << 8) | s3)

    def ror(w, n):
        return ((w >> n) | (w << (32 - n))) & 0xFFFFFFFF

    te1 = [ror(w, 8) for w in te0]
    te2 = [ror(w, 16) for w in te0]
    te3 = [ror(w, 24) for w in te0]
    return sbox, te0, te1, te2, te3


_SBOX, _TE0, _TE1, _TE2, _TE3 = _build_aes_tables()


def _aes128_expand_key(key):
    if len(key) != 16:
        raise ValueError("AES-128 : clé de 16 octets requise")
    w = list(struct.unpack(">4I", key))
    sb = _SBOX
    rcon = 1
    for i in range(4, 44):
        t = w[i - 1]
        if i % 4 == 0:
            t = ((t << 8) & 0xFFFFFFFF) | (t >> 24)
            t = ((sb[t >> 24] << 24) | (sb[(t >> 16) & 255] << 16)
                 | (sb[(t >> 8) & 255] << 8) | sb[t & 255])
            t ^= rcon << 24
            rcon = ((rcon << 1) ^ 0x11B) if rcon & 0x80 else rcon << 1
        w.append(w[i - 4] ^ t)
    return w


def _aes128_block(rk, s0, s1, s2, s3):
    """Chiffre un bloc donné en 4 mots de 32 bits ; renvoie 4 mots."""
    t0, t1, t2, t3 = _TE0, _TE1, _TE2, _TE3
    s0 ^= rk[0]
    s1 ^= rk[1]
    s2 ^= rk[2]
    s3 ^= rk[3]
    for r in range(4, 40, 4):
        n0 = (t0[s0 >> 24] ^ t1[(s1 >> 16) & 255] ^ t2[(s2 >> 8) & 255]
              ^ t3[s3 & 255] ^ rk[r])
        n1 = (t0[s1 >> 24] ^ t1[(s2 >> 16) & 255] ^ t2[(s3 >> 8) & 255]
              ^ t3[s0 & 255] ^ rk[r + 1])
        n2 = (t0[s2 >> 24] ^ t1[(s3 >> 16) & 255] ^ t2[(s0 >> 8) & 255]
              ^ t3[s1 & 255] ^ rk[r + 2])
        n3 = (t0[s3 >> 24] ^ t1[(s0 >> 16) & 255] ^ t2[(s1 >> 8) & 255]
              ^ t3[s2 & 255] ^ rk[r + 3])
        s0, s1, s2, s3 = n0, n1, n2, n3
    sb = _SBOX
    o0 = ((sb[s0 >> 24] << 24) | (sb[(s1 >> 16) & 255] << 16)
          | (sb[(s2 >> 8) & 255] << 8) | sb[s3 & 255]) ^ rk[40]
    o1 = ((sb[s1 >> 24] << 24) | (sb[(s2 >> 16) & 255] << 16)
          | (sb[(s3 >> 8) & 255] << 8) | sb[s0 & 255]) ^ rk[41]
    o2 = ((sb[s2 >> 24] << 24) | (sb[(s3 >> 16) & 255] << 16)
          | (sb[(s0 >> 8) & 255] << 8) | sb[s1 & 255]) ^ rk[42]
    o3 = ((sb[s3 >> 24] << 24) | (sb[(s0 >> 16) & 255] << 16)
          | (sb[(s1 >> 8) & 255] << 8) | sb[s2 & 255]) ^ rk[43]
    return o0, o1, o2, o3


def _aes128_encrypt_block(key, block):
    """Chiffre un bloc de 16 octets (ECB, un seul bloc) ; utile aux tests."""
    out = _aes128_block(_aes128_expand_key(key), *struct.unpack(">4I", block))
    return struct.pack(">4I", *out)


_GCM_R = 0xE1 << 120


def _gf_mulx(v):
    return (v >> 1) ^ _GCM_R if v & 1 else v >> 1


def _build_rem():
    rem = []
    for r in range(16):
        z = r
        for _ in range(4):
            z = _gf_mulx(z)
        rem.append(z)
    return rem


_GCM_REM = _build_rem()


def _ghash_table(h):
    """Table de Shoup (4 bits) : T[i] = (i placé en tête) * H dans GF(2^128)."""
    t = [0] * 16
    t[8] = h
    t[4] = _gf_mulx(t[8])
    t[2] = _gf_mulx(t[4])
    t[1] = _gf_mulx(t[2])
    for i in (3, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15):
        low = i & -i
        t[i] = t[low] ^ t[i ^ low]
    return t


def _ghash(table, data):
    """GHASH sans AAD sur ``data`` (chiffré), longueur incluse."""
    rem = _GCM_REM
    y = 0
    n = len(data)
    padded = data + b"\x00" * (-n % 16)
    blocks = [int.from_bytes(padded[i:i + 16], "big")
              for i in range(0, len(padded), 16)]
    blocks.append(n * 8)  # bloc de longueurs : len(A)=0 || len(C) en bits
    for blk in blocks:
        x = y ^ blk
        z = table[x & 15]
        x >>= 4
        for _ in range(31):
            z = (z >> 4) ^ rem[z & 15] ^ table[x & 15]
            x >>= 4
        y = z
    return y


def _gcm_ctr(rk, nonce, data, first_counter):
    n0, n1, n2 = struct.unpack(">3I", nonce)
    nblocks = (len(data) + 15) // 16
    ks = b"".join(
        struct.pack(">4I", *_aes128_block(rk, n0, n1, n2,
                                          (first_counter + i) & 0xFFFFFFFF))
        for i in range(nblocks))
    if not data:
        return b""
    x = int.from_bytes(data, "big") ^ (
        int.from_bytes(ks[:len(data)], "big"))
    return x.to_bytes(len(data), "big")


def _gcm_tag(rk, nonce, ciphertext):
    h = int.from_bytes(struct.pack(">4I", *_aes128_block(rk, 0, 0, 0, 0)), "big")
    s = _ghash(_ghash_table(h), ciphertext)
    n0, n1, n2 = struct.unpack(">3I", nonce)
    ek = int.from_bytes(struct.pack(">4I", *_aes128_block(rk, n0, n1, n2, 1)),
                        "big")
    return (s ^ ek).to_bytes(16, "big")


def _pure_aesgcm_encrypt(key, nonce, plaintext):
    if len(nonce) != 12:
        raise ValueError("GCM : nonce de 12 octets requis")
    rk = _aes128_expand_key(key)
    ct = _gcm_ctr(rk, nonce, plaintext, 2)
    return ct + _gcm_tag(rk, nonce, ct)


def _pure_aesgcm_decrypt(key, nonce, data):
    if len(nonce) != 12:
        raise ValueError("GCM : nonce de 12 octets requis")
    if len(data) < 16:
        raise ValueError("GCM : données trop courtes")
    rk = _aes128_expand_key(key)
    ct, tag = data[:-16], data[-16:]
    if not hmac.compare_digest(tag, _gcm_tag(rk, nonce, ct)):
        raise ValueError("Déchiffrement impossible (tag d'authentification invalide)")
    return _gcm_ctr(rk, nonce, ct, 2)


# --------------------------------------------------------------------------
# Répartiteur de backend
# --------------------------------------------------------------------------

def _coerce_scalar(key):
    """Clé privée -> entier dans [1, n-1] (int, 32 octets, ou base64url)."""
    if isinstance(key, str):
        key = b64urldecode(key)
    if isinstance(key, (bytes, bytearray, memoryview)):
        key = bytes(key)
        if len(key) != 32:
            raise ValueError("clé privée P-256 : 32 octets attendus")
        key = int.from_bytes(key, "big")
    if not isinstance(key, int) or isinstance(key, bool):
        raise ValueError("type de clé privée non pris en charge")
    if not 1 <= key < _N:
        raise ValueError("clé privée P-256 hors de l'intervalle [1, n-1]")
    return key


def _new_scalar():
    return secrets.randbelow(_N - 1) + 1


def _pub_from_priv(d):
    """Clé publique (65 octets non compressés) d'un scalaire privé."""
    if _crypto_active():
        pub = _c_ec.derive_private_key(d, _c_ec.SECP256R1()).public_key()
        return _c_pub_bytes(pub)
    return _pure_pub_from_priv(d)


def _c_pub_bytes(pub):
    from cryptography.hazmat.primitives import serialization
    return pub.public_bytes(serialization.Encoding.X962,
                            serialization.PublicFormat.UncompressedPoint)


def _ecdh(d, pub):
    """Secret ECDH (coordonnée x, 32 octets) ; ``ValueError`` si ``pub`` invalide."""
    if _crypto_active():
        priv = _c_ec.derive_private_key(d, _c_ec.SECP256R1())
        peer = _c_ec.EllipticCurvePublicKey.from_encoded_point(
            _c_ec.SECP256R1(), bytes(pub))
        return priv.exchange(_c_ec.ECDH(), peer)
    return _pure_ecdh(d, pub)


def _ecdsa_sign(d, msg):
    """Signature ECDSA P-256/SHA-256 de ``msg`` -> ``(r, s)``."""
    if _crypto_active():
        priv = _c_ec.derive_private_key(d, _c_ec.SECP256R1())
        der = priv.sign(msg, _c_ec.ECDSA(_c_hashes.SHA256()))
        return _c_utils.decode_dss_signature(der)
    return _pure_ecdsa_sign(d, msg)


def _aesgcm_encrypt(key, nonce, plaintext):
    if _crypto_active():
        return _AESGCM(key).encrypt(nonce, plaintext, None)
    return _pure_aesgcm_encrypt(key, nonce, plaintext)


def _aesgcm_decrypt(key, nonce, data):
    if _crypto_active():
        try:
            return _AESGCM(key).decrypt(nonce, data, None)
        except _InvalidTag:
            raise ValueError(
                "Déchiffrement impossible (tag d'authentification invalide)"
            ) from None
    return _pure_aesgcm_decrypt(key, nonce, data)


# --------------------------------------------------------------------------
# HKDF et chiffrement de contenu aes128gcm (RFC 8188 / RFC 8291)
# --------------------------------------------------------------------------

def _hkdf_extract(salt, ikm):
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def _hkdf_expand(prk, info, length):
    out = b""
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]),
                         hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def _ece_derive(secret, auth_secret, ua_pub, as_pub, salt):
    """Dérive (CEK, nonce de base) selon RFC 8291 §3.3-3.4 et RFC 8188 §2.2."""
    prk_key = _hkdf_extract(auth_secret, secret)
    ikm = _hkdf_expand(prk_key, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    prk = _hkdf_extract(salt, ikm)
    cek = _hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    return cek, nonce


def _record_nonce(base, seq):
    return (int.from_bytes(base, "big") ^ seq).to_bytes(12, "big")


def ece_encrypt_aes128gcm(plaintext, receiver_pub, auth_secret, *,
                          salt=None, sender_private=None, rs=4096):
    """Chiffre ``plaintext`` en corps ``aes128gcm`` complet (RFC 8188 + 8291).

    Renvoie ``salt(16) | rs(4) | idlen(1) | keyid = clé publique émettrice (65)``
    suivis des enregistrements chiffrés.

    :param receiver_pub: clé publique ``p256dh`` du navigateur (65 octets).
    :param auth_secret: secret d'authentification ``auth`` du navigateur.
    :param salt: 16 octets ; aléatoire si omis (ne le fixer que pour les tests).
    :param sender_private: clé privée éphémère (entier ou 32 octets) ; générée
        si omise (ne la fixer que pour rejouer des vecteurs de test).
    :param rs: taille d'enregistrement (au moins 18).  L'enregistrement final
        est toujours strictement plus court que ``rs``.
    """
    plaintext = bytes(plaintext)
    receiver_pub = bytes(receiver_pub)
    auth_secret = bytes(auth_secret)
    if not isinstance(rs, int) or rs < 18 or rs > 0xFFFFFFFF:
        raise ValueError("rs invalide (entier >= 18 attendu)")
    if salt is None:
        salt = os.urandom(16)
    salt = bytes(salt)
    if len(salt) != 16:
        raise ValueError("le sel doit faire 16 octets")
    d = _new_scalar() if sender_private is None else _coerce_scalar(sender_private)
    as_pub = _pub_from_priv(d)
    secret = _ecdh(d, receiver_pub)  # valide aussi receiver_pub
    cek, base_nonce = _ece_derive(secret, auth_secret, receiver_pub, as_pub, salt)

    size = rs - 17  # octets de clair par enregistrement plein (1 pour le délimiteur)
    out = [salt + struct.pack(">IB", rs, len(as_pub)) + as_pub]
    pos = 0
    seq = 0
    while True:
        rest = len(plaintext) - pos
        if rest >= size:  # enregistrement plein, non final
            record = plaintext[pos:pos + size] + b"\x01"
            pos += size
            last = False
        else:
            record = plaintext[pos:] + b"\x02"
            last = True
        out.append(_aesgcm_encrypt(cek, _record_nonce(base_nonce, seq), record))
        if last:
            break
        seq += 1
    return b"".join(out)


def ece_decrypt_aes128gcm(body, receiver_private, auth_secret):
    """Déchiffre un corps ``aes128gcm`` (pour les tests ; côté « navigateur »).

    :param receiver_private: clé privée du récepteur (entier ou 32 octets).
    :raises ValueError: corps mal formé ou authentification échouée.
    """
    body = bytes(body)
    auth_secret = bytes(auth_secret)
    d = _coerce_scalar(receiver_private)
    if len(body) < 21:
        raise ValueError("corps aes128gcm trop court")
    salt = body[:16]
    rs, idlen = struct.unpack(">IB", body[16:21])
    if rs < 18:
        raise ValueError("rs invalide dans l'en-tête")
    if idlen != 65 or len(body) < 21 + idlen:
        raise ValueError("keyid : clé publique de 65 octets attendue")
    as_pub = body[21:21 + idlen]
    data = body[21 + idlen:]
    if not data:
        raise ValueError("aucun enregistrement")
    secret = _ecdh(d, as_pub)
    ua_pub = _pub_from_priv(d)
    cek, base_nonce = _ece_derive(secret, auth_secret, ua_pub, as_pub, salt)

    out = []
    seq = 0
    for start in range(0, len(data), rs):
        chunk = data[start:start + rs]
        last = start + rs >= len(data)
        if len(chunk) < 17:
            raise ValueError("enregistrement trop court")
        plain = _aesgcm_decrypt(cek, _record_nonce(base_nonce, seq), chunk)
        stripped = plain.rstrip(b"\x00")
        if not stripped:
            raise ValueError("délimiteur de bourrage absent")
        delim = stripped[-1]
        if delim == 2 and last:
            pass
        elif delim == 1 and not last:
            pass
        else:
            raise ValueError("délimiteur d'enregistrement invalide ou flux tronqué")
        out.append(stripped[:-1])
        seq += 1
    return b"".join(out)


# --------------------------------------------------------------------------
# JWT ES256 et clés VAPID
# --------------------------------------------------------------------------

_JWT_HEADER = b64urlencode(b'{"typ":"JWT","alg":"ES256"}')


def es256_sign_jwt(claims, private_raw):
    """Signe ``claims`` (dict) en JWT ES256 compact (RFC 7519/7518).

    ``private_raw`` : clé privée brute (32 octets, entier, ou base64url).
    La signature est ``r || s`` sur 64 octets.  Les revendications sont
    sérialisées triées et compactes (certains services l'exigent).
    """
    d = _coerce_scalar(private_raw)
    payload = b64urlencode(json.dumps(
        claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = "{}.{}".format(_JWT_HEADER, payload)
    r, s = _ecdsa_sign(d, signing_input.encode("ascii"))
    return "{}.{}".format(
        signing_input, b64urlencode(num_to_bytes(r, 32) + num_to_bytes(s, 32)))


def es256_verify_jwt(token, public_raw):
    """Vérifie un JWT ES256 en Python pur ; renvoie les revendications (dict).

    :param public_raw: clé publique (65 octets, ou base64url).
    :raises ValueError: JWT mal formé ou signature invalide.
    """
    if isinstance(public_raw, str):
        public_raw = b64urldecode(public_raw)
    try:
        head, payload, sig = token.split(".")
        signature = b64urldecode(sig)
        if len(signature) != 64:
            raise ValueError("signature de 64 octets attendue")
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        ok = _pure_ecdsa_verify(public_raw, (head + "." + payload).encode("ascii"),
                                r, s)
        if json.loads(b64urldecode(head)).get("alg") != "ES256":
            raise ValueError("alg != ES256")
        claims = json.loads(b64urldecode(payload).decode("utf-8"))
    except (UnicodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError("JWT mal formé : %s" % exc) from None
    if not ok:
        raise ValueError("signature JWT invalide")
    return claims


# -- lecture minimale de clés EC en DER / PEM (sans cryptography) ---------

_OID_EC_PUBLIC_KEY = bytes.fromhex("2a8648ce3d0201")
_OID_PRIME256V1 = bytes.fromhex("2a8648ce3d030107")


def _der_tlv(buf, pos):
    """Lit un TLV DER à ``pos`` -> ``(tag, début_valeur, fin_valeur)``."""
    if pos + 2 > len(buf):
        raise ValueError("DER tronqué")
    tag = buf[pos]
    length = buf[pos + 1]
    pos += 2
    if length & 0x80:
        nbytes = length & 0x7F
        if nbytes == 0 or nbytes > 4 or pos + nbytes > len(buf):
            raise ValueError("longueur DER invalide")
        length = int.from_bytes(buf[pos:pos + nbytes], "big")
        pos += nbytes
    if pos + length > len(buf):
        raise ValueError("DER tronqué")
    return tag, pos, pos + length


def _ec_der_to_scalar(der):
    """Extrait le scalaire privé P-256 d'un DER SEC1 (``EC PRIVATE KEY``) ou PKCS#8."""
    tag, s, e = _der_tlv(der, 0)
    if tag != 0x30:
        raise ValueError("DER : SEQUENCE attendue")
    tag, vs, ve = _der_tlv(der, s)
    if tag != 0x02:
        raise ValueError("DER : version attendue")
    version = int.from_bytes(der[vs:ve], "big")
    pos = ve
    if version == 0:  # PKCS#8 : AlgorithmIdentifier puis OCTET STRING (SEC1)
        tag, as_, ae = _der_tlv(der, pos)
        if tag != 0x30:
            raise ValueError("PKCS#8 : AlgorithmIdentifier attendu")
        t1, o1s, o1e = _der_tlv(der, as_)
        if t1 != 0x06 or der[o1s:o1e] != _OID_EC_PUBLIC_KEY:
            raise ValueError("clé non EC")
        t2, o2s, o2e = _der_tlv(der, o1e)
        if t2 != 0x06 or der[o2s:o2e] != _OID_PRIME256V1:
            raise ValueError("courbe non P-256")
        tag, ks, ke = _der_tlv(der, ae)
        if tag != 0x04:
            raise ValueError("PKCS#8 : OCTET STRING attendue")
        return _ec_der_to_scalar(der[ks:ke])
    if version != 1:
        raise ValueError("version de clé EC inconnue")
    tag, ks, ke = _der_tlv(der, pos)
    if tag != 0x04 or ke - ks != 32:
        raise ValueError("SEC1 : clé privée de 32 octets attendue")
    scalar = int.from_bytes(der[ks:ke], "big")
    pos = ke
    if pos < e:  # [0] paramètres : si présents, doivent désigner P-256
        tag, ps, pe = _der_tlv(der, pos)
        if tag == 0xA0:
            t, os_, oe = _der_tlv(der, ps)
            if t != 0x06 or der[os_:oe] != _OID_PRIME256V1:
                raise ValueError("courbe non P-256")
    return _coerce_scalar(scalar)


_PEM_RE = re.compile(
    rb"-----BEGIN ([A-Z0-9 ]+)-----(.*?)-----END \1-----", re.DOTALL)


_RAW_KEY_RE = re.compile(rb"[A-Za-z0-9_-]{43}=?")


def _parse_key_material(data):
    """Octets d'une clé (PEM, DER, ou base64url texte) -> scalaire privé."""
    data = bytes(data).strip()
    # Clé brute base64url (32 octets : 43 caractères, `=` final toléré — format de push_vapid_keys) reconnue AVANT tout
    # test DER/PEM : le caractère « 0 » vaut l'octet 0x30 (SEQUENCE DER), une clé brute en « 0… » partait en lecture DER.
    if _RAW_KEY_RE.fullmatch(data):
        return _coerce_scalar(b64urldecode(data))
    if b"-----BEGIN" in data:
        for label, body in _PEM_RE.findall(data):
            if label in (b"EC PRIVATE KEY", b"PRIVATE KEY"):
                if b"Proc-Type" in body or b"DEK-Info" in body:
                    raise ValueError("PEM chiffré non pris en charge")
                return _ec_der_to_scalar(b64urldecode(body))
            if label == b"ENCRYPTED PRIVATE KEY":
                raise ValueError("PEM chiffré non pris en charge")
        raise ValueError("aucune clé privée EC trouvée dans le PEM")
    if data[:1] == b"\x30":  # DER binaire
        return _ec_der_to_scalar(data)
    raw = b64urldecode(data)
    if len(raw) == 32:
        return _coerce_scalar(raw)
    return _ec_der_to_scalar(raw)  # DER encodé en base64


def _load_private(private_key):
    """Chemin de fichier, texte (brut b64url / PEM / DER b64) ou octets -> scalaire."""
    try:
        if isinstance(private_key, str):
            text = private_key.strip()
            if text and "\n" not in text and len(text) < 4096 \
                    and "\x00" not in text and os.path.isfile(text):
                with open(text, "rb") as fh:
                    return _parse_key_material(fh.read())
            return _parse_key_material(text.encode("utf-8"))
        if isinstance(private_key, (bytes, bytearray, memoryview)):
            private_key = bytes(private_key)
            if len(private_key) == 32:
                return _coerce_scalar(private_key)
            return _parse_key_material(private_key)
        if isinstance(private_key, int) and not isinstance(private_key, bool):
            return _coerce_scalar(private_key)
    except (ValueError, OSError, UnicodeError, IndexError) as exc:
        raise VapidException("Clé privée VAPID invalide : %s" % exc) from None
    raise VapidException("Clé privée VAPID : type non pris en charge")


class Vapid:
    """Clé VAPID (RFC 8292) minimale : charge une clé et signe des JWT."""

    def __init__(self, private_key=None):
        self._d = None if private_key is None else _load_private(private_key)

    # -- construction -------------------------------------------------
    @classmethod
    def from_string(cls, private_key):
        """Depuis une clé brute base64url (32 octets), un PEM/DER, ou un chemin."""
        if private_key is None:
            raise VapidException("Clé privée VAPID absente")
        return cls(private_key)

    from_raw = from_string

    @classmethod
    def from_pem(cls, private_key):
        return cls(private_key)

    @classmethod
    def from_der(cls, private_key):
        return cls(private_key)

    @classmethod
    def from_file(cls, private_key_file):
        try:
            with open(private_key_file, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise VapidException("Lecture de la clé VAPID impossible : %s" % exc) \
                from None
        return cls(data)

    def generate_keys(self):
        """Génère une nouvelle paire P-256 dans cet objet."""
        self._d = _new_scalar()

    # -- accès ----------------------------------------------------------
    def _need_key(self):
        if self._d is None:
            raise VapidException("Aucune clé privée : appeler generate_keys()")
        return self._d

    @property
    def private_key_raw(self):
        """Clé privée brute (32 octets)."""
        return num_to_bytes(self._need_key(), 32)

    @property
    def public_key_raw(self):
        """Clé publique (65 octets, point non compressé)."""
        return _pub_from_priv(self._need_key())

    # -- signature ------------------------------------------------------
    def sign(self, claims, crypto_key=None):
        """Renvoie ``{"Authorization": "vapid t=<jwt>,k=<clé publique>"}``.

        ``claims`` doit contenir ``sub`` et ``aud`` ; ``exp`` vaut +12 h s'il
        manque.  Le dict reçu n'est pas modifié.  ``crypto_key`` est ignoré
        (ancien schéma VAPID draft-01 non pris en charge).
        """
        d = self._need_key()
        claims = dict(claims or {})
        if not claims.get("sub"):
            raise VapidException(
                "Revendication 'sub' manquante (adresse « mailto: » de contact).")
        aud = claims.get("aud")
        if not aud or not re.match(r"^https?://[^/]+$", str(aud), re.IGNORECASE):
            raise VapidException(
                "Revendication 'aud' manquante ou invalide "
                "(schéma://hôte[:port] du service Push).")
        if not claims.get("exp"):
            claims["exp"] = int(time.time()) + 12 * 3600
        token = es256_sign_jwt(claims, d)
        return {"Authorization": "vapid t={},k={}".format(
            token, b64urlencode(self.public_key_raw))}


Vapid01 = Vapid02 = Vapid  # alias de compatibilité avec py_vapid


def generate_raw_keys():
    """Nouvelle paire P-256 -> ``(privée, publique)`` en base64url sans padding.

    Privée : entier de 32 octets big-endian (43 caractères) ; publique : point
    non compressé de 65 octets (87 caractères).
    """
    d = _new_scalar()
    return b64urlencode(num_to_bytes(d, 32)), b64urlencode(_pub_from_priv(d))


# --------------------------------------------------------------------------
# Abonnement, transport HTTP et fonction webpush()
# --------------------------------------------------------------------------

_MAX_DATA = 3993  # 4096 (plafond des services Push) - 86 - 16 - 1
_DEFAULT_TIMEOUT = 30.0
_MAX_RESPONSE = 1 << 20


def _parse_subscription(info, need_keys):
    """Valide ``subscription_info`` -> ``(endpoint, p256dh|None, auth|None)``."""
    if not hasattr(info, "get") or "endpoint" not in info:
        raise WebPushException("subscription_info missing endpoint URL")
    endpoint = info["endpoint"]
    if isinstance(endpoint, bytes):
        endpoint = endpoint.decode("utf-8", "replace")
    parts = urllib.parse.urlsplit(endpoint) if isinstance(endpoint, str) else None
    if parts is None or parts.scheme not in ("http", "https") or not parts.netloc:
        raise WebPushException(
            "subscription_info : endpoint http(s) invalide : %r" % (endpoint,))
    receiver = auth = None
    if "keys" in info and info["keys"] is not None:
        keys = info["keys"]
        for name in ("p256dh", "auth"):
            if not hasattr(keys, "get") or keys.get(name) is None:
                raise WebPushException("Missing keys value: %s" % name)
        try:
            receiver = b64urldecode(keys["p256dh"])
            auth = b64urldecode(keys["auth"])
        except (ValueError, TypeError, UnicodeError) as exc:
            raise WebPushException("Clés d'abonnement invalides : %s" % exc) from None
        if len(receiver) != 65 or receiver[0] != 4:
            raise WebPushException("Invalid p256dh key specified")
        try:
            _decode_point(receiver)
        except ValueError:
            raise WebPushException("Invalid p256dh key specified") from None
        if not auth:
            raise WebPushException("Missing keys value: auth")
    elif need_keys:
        raise WebPushException("No keys specified in subscription info")
    return endpoint, receiver, auth


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse de suivre les redirections (la 3xx remonte comme une erreur)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_SSL_CTX = None


def _build_opener():
    global _SSL_CTX
    handlers = [_NoRedirect()]
    if _ssl is not None:
        if _SSL_CTX is None:
            _SSL_CTX = _ssl.create_default_context()
        handlers.append(urllib.request.HTTPSHandler(context=_SSL_CTX))
    # build_opener ajoute ProxyHandler (variables d'environnement) par défaut.
    return urllib.request.build_opener(*handlers)


def _make_response(raw, status, reason, url):
    headers = CaseInsensitiveDict()
    for key, value in raw.headers.items():
        headers[key] = value if key not in headers else headers[key] + ", " + value
    try:
        content = raw.read(_MAX_RESPONSE)
    except Exception:  # noqa: BLE001 - corps illisible : on garde le statut
        content = b""
    return _Response(status, reason, content, headers, url)


def _http_post(endpoint, body, headers, timeout):
    """POST ``body`` ; renvoie une ``_Response`` (y compris pour 4xx/5xx)."""
    req = urllib.request.Request(
        endpoint, data=body if body is not None else b"",
        headers={k: str(v) for k, v in headers.items()}, method="POST")
    opener = _build_opener()
    try:
        raw = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            return _make_response(exc, exc.code, exc.reason, exc.url or endpoint)
        finally:
            exc.close()
    try:
        return _make_response(raw, raw.status, raw.reason, raw.geturl())
    finally:
        raw.close()


def _as_curl(endpoint, body, headers):
    lines = ["-H '{}: {}'".format(k, v) for k, v in headers.items()]
    cmd = "curl -vX POST '{}' \\\n  {}".format(endpoint, " \\\n  ".join(lines))
    if body:
        cmd = ("printf %s '{}' | base64 -d | {} \\\n  --data-binary @-"
               .format(base64.b64encode(body).decode("ascii"), cmd))
    return cmd


def webpush(subscription_info, data=None, vapid_private_key=None,
            vapid_claims=None, content_encoding="aes128gcm", curl=False,
            timeout=None, ttl=0, verbose=False, headers=None,
            requests_session=None):
    """Chiffre ``data`` et l'envoie au service Push de ``subscription_info``.

    Même sémantique que ``pywebpush.webpush`` (2.5), voir l'en-tête du module
    pour les écarts.

    :param subscription_info: ``{"endpoint": ..., "keys": {"p256dh", "auth"}}``.
    :param data: charge utile (``str`` UTF-8 ou ``bytes``), 3993 octets max.
    :param vapid_private_key: instance ``Vapid``, clé brute base64url, PEM/DER
        ou chemin de fichier.  Requise si ``vapid_claims`` est fourni.
    :param vapid_claims: dict de revendications (``sub`` requis ; ``aud`` et
        ``exp`` complétés si absents).  Non modifié.
    :param curl: si vrai, renvoie une ``str`` décrivant la commande curl.
    :param timeout: secondes (``None`` -> 30 s).
    :param ttl: durée de vie du message, en secondes.
    :param requests_session: ignoré (pas de ``requests`` dans la version autonome).
    :returns: réponse (``status_code``, ``reason``, ``text``, ``content``,
        ``headers``, ``url``) ; ``WebPushException`` si le statut est > 202.
    """
    if content_encoding != "aes128gcm":
        raise WebPushException(
            "Encodage de contenu %r non pris en charge par la version autonome "
            "(seul « aes128gcm » est disponible)." % (content_encoding,))

    if isinstance(data, str):
        data = data.encode("utf-8")
    elif data is not None and not isinstance(data, (bytes, bytearray, memoryview)):
        raise WebPushException("data doit être de type str ou bytes")
    data = bytes(data) if data else None

    endpoint, receiver, auth = _parse_subscription(subscription_info, bool(data))
    out_headers = CaseInsensitiveDict(headers or {})

    if vapid_claims:
        claims = dict(vapid_claims)  # copie : l'appelant garde son dict intact
        if not claims.get("aud"):
            parts = urllib.parse.urlsplit(endpoint)
            claims["aud"] = "{}://{}".format(parts.scheme, parts.netloc)
        try:
            exp = int(claims.get("exp") or 0)
        except (TypeError, ValueError):
            exp = 0
        if not exp or exp < int(time.time()):
            claims["exp"] = int(time.time()) + 12 * 60 * 60
            if verbose:
                logging.info("Setting VAPID expiry to %s...", claims["exp"])
        if not vapid_private_key:
            raise WebPushException("VAPID dict missing 'private_key'")
        if isinstance(vapid_private_key, Vapid):
            vv = vapid_private_key
        else:
            vv = Vapid.from_string(vapid_private_key)
        if verbose:
            logging.info("\t claims: %s", claims)
        out_headers.update(vv.sign(claims))

    body = None
    if data:
        if len(data) > _MAX_DATA:
            raise WebPushException("Data too large")
        if verbose:
            logging.info("Encrypting to aes128gcm...")
        body = ece_encrypt_aes128gcm(data, receiver, auth)
        out_headers["content-encoding"] = "aes128gcm"
        out_headers.setdefault("content-type", "application/octet-stream")
        out_headers["content-length"] = str(len(body))
    if "ttl" not in out_headers or ttl:
        out_headers["ttl"] = str(ttl or 0)
    out_headers.setdefault("user-agent", "webpush_lite/" + __version__)

    if curl:
        return _as_curl(endpoint, body, out_headers)

    if verbose:
        logging.info("Sending request to %s (headers: %s)", endpoint,
                     sorted(out_headers))
    response = _http_post(endpoint, body, out_headers,
                          _DEFAULT_TIMEOUT if timeout is None else timeout)
    if verbose:
        logging.info("Response: code %s, body %s", response.status_code,
                     response.text or "Empty")
    if response.status_code > 202:
        raise WebPushException(
            "Push failed: {} {}\nResponse body:{}".format(
                response.status_code, response.reason, response.text),
            response=response)
    return response

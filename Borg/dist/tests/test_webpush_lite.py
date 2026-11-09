#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests de ``compat/webpush_lite.py`` (unittest, stdlib seule).

Exécution :  ``python3 test_webpush_lite.py``  ou  ``python3 -I -S test_webpush_lite.py``
(dans ce dernier cas ``cryptography`` est absente : seul le repli en Python
pur est testé et les tests inter-backends sont sautés).
"""

import contextlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ``python3 -I`` retire le dossier du script de sys.path : on l'ajoute nous-mêmes.
_COMPAT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       os.pardir, "compat")
sys.path.insert(0, os.path.normpath(_COMPAT))

import webpush_lite as wl  # noqa: E402

HAVE_CRYPTO = wl._HAVE_CRYPTO
NEED_CRYPTO = unittest.skipUnless(
    HAVE_CRYPTO, "module « cryptography » absent : test inter-backends sauté")

b64d = wl.b64urldecode
b64e = wl.b64urlencode


@contextlib.contextmanager
def backend(pure):
    """Force le backend (pur Python si ``pure``) le temps du bloc."""
    old = wl._FORCE_PURE
    wl._use_pure(pure)
    try:
        yield
    finally:
        wl._use_pure(old)


def backends():
    """Liste des valeurs de ``pure`` à tester (pur Python toujours, puis cryptography)."""
    return [True, False] if HAVE_CRYPTO else [True]


# -- Vecteurs RFC 8291 §5 (exemple) -----------------------------------------
RFC_PLAINTEXT = b"When I grow up, I want to be a watermelon"
RFC_AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
RFC_AS_PUBLIC = ("BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmY"
                 "WAmS6TlzAC8wEqKK6PBru3jl7A8")
RFC_UA_PUBLIC = ("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4"
                 "bjyPjs7Vd8pZGH6SRpkNtoIAiw4")
RFC_UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
RFC_AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_SALT = "DGv6ra1nlYgDCS1FRnbzlw"
# Corps complet de la RFC 8291 §5 (calculé ici ; les valeurs intermédiaires
# ecdh_secret / PRK_key / IKM / PRK / CEK / NONCE concordent avec la RFC).
RFC_BODY = ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlm"
            "lMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4"
            "Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")

# -- Clé VAPID fixe, dans plusieurs formats ---------------------------------
KEY_RAW = "vMQ9pOnw_TVIYuA81R91jFPd6mzR0eKZsUX4gPnmOGY"
KEY_PUB = ("BGTasrtqzM6TlzOrpVZ4Bu7Pwqfp3e5URqf6efvk9T6NgeYJsEA7Z_9oPjo4ZbvDnmqj"
           "87zqc3KscO591nTJU9E")
KEY_PEM_SEC1 = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEILzEPaTp8P01SGLgPNUfdYxT3eps0dHimbFF+ID55jhmoAoGCCqGSM49
AwEHoUQDQgAEZNqyu2rMzpOXM6ulVngG7s/Cp+nd7lRGp/p5++T1Po2B5gmwQDtn
/2g+Ojhlu8OeaqPzvOpzcqxw7n3WdMlT0Q==
-----END EC PRIVATE KEY-----
"""
KEY_PEM_PKCS8 = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgvMQ9pOnw/TVIYuA8
1R91jFPd6mzR0eKZsUX4gPnmOGahRANCAARk2rK7aszOk5czq6VWeAbuz8Kn6d3u
VEan+nn75PU+jYHmCbBAO2f/aD46OGW7w55qo/O86nNyrHDufdZ0yVPR
-----END PRIVATE KEY-----
"""


def make_subscription(endpoint="http://127.0.0.1:1/push", d=None, auth=None):
    """Abonnement factice ; renvoie ``(subscription_info, clé privée du récepteur, auth)``."""
    d = wl._new_scalar() if d is None else d
    auth = os.urandom(16) if auth is None else auth
    info = {"endpoint": endpoint,
            "keys": {"p256dh": b64e(wl._pub_from_priv(d)), "auth": b64e(auth)}}
    return info, d, auth


class PrimitivesTest(unittest.TestCase):
    """Briques de base en Python pur, avec vecteurs publiés indépendants."""

    def test_aes128_fips197(self):
        key = bytes(range(16))
        blk = bytes.fromhex("00112233445566778899aabbccddeeff")
        self.assertEqual(wl._aes128_encrypt_block(key, blk).hex(),
                         "69c4e0d86a7b0430d8cdb78070b4c55a")

    def test_gcm_vecteurs_nist(self):
        # Cas de test 2 de « The Galois/Counter Mode of Operation » (McGrew/Viega)
        out = wl._pure_aesgcm_encrypt(b"\0" * 16, b"\0" * 12, b"\0" * 16)
        self.assertEqual(out.hex(), "0388dace60b6a392f328c2b971b2fe78"
                                    "ab6e47d42cec13bdf53a67b21257bddf")
        # Cas de test 3 : plusieurs blocs, sans AAD
        key = bytes.fromhex("feffe9928665731c6d6a8f9467308308")
        iv = bytes.fromhex("cafebabefacedbaddecaf888")
        pt = bytes.fromhex(
            "d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
            "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b391aafd255")
        out = wl._pure_aesgcm_encrypt(key, iv, pt)
        self.assertEqual(out[:-16].hex(),
                         "42831ec2217774244b7221b784d0d49ce3aa212f2c02a4e035c17e2329aca12e"
                         "21d514b25466931c7d8f6a5aac84aa051ba30b396a0aac973d58e091473f5985")
        self.assertEqual(out[-16:].hex(), "4d5c2af327cd64a62cf35abd2ba6fab4")
        self.assertEqual(wl._pure_aesgcm_decrypt(key, iv, out), pt)

    def test_gcm_tag_altere(self):
        out = bytearray(wl._pure_aesgcm_encrypt(b"k" * 16, b"n" * 12, b"secret"))
        out[0] ^= 1
        with self.assertRaises(ValueError):
            wl._pure_aesgcm_decrypt(b"k" * 16, b"n" * 12, bytes(out))

    @NEED_CRYPTO
    def test_gcm_pur_vs_cryptography(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        for n in (0, 1, 15, 16, 17, 31, 32, 33, 100, 1000, 4079):
            key, nonce, pt = os.urandom(16), os.urandom(12), os.urandom(n)
            ref = AESGCM(key).encrypt(nonce, pt, None)
            self.assertEqual(wl._pure_aesgcm_encrypt(key, nonce, pt), ref, n)
            self.assertEqual(wl._pure_aesgcm_decrypt(key, nonce, ref), pt, n)

    def test_rfc6979_a25(self):
        """RFC 6979 A.2.5 : P-256 / SHA-256, message « sample »."""
        x = int("C9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721", 16)
        h1 = wl.hashlib.sha256(b"sample").digest()
        k = next(wl._rfc6979_candidates(x, h1))
        self.assertEqual(
            k, int("A6E3C57DD01ABE90086538398355DD4C3B17AA873382B0F24D6129493D8AAD60", 16))
        r, s = wl._pure_ecdsa_sign(x, b"sample")
        self.assertEqual(
            r, int("EFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716", 16))
        self.assertEqual(
            s, int("F7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8", 16))
        # clé publique du même vecteur (Ux, Uy)
        pub = wl._pure_pub_from_priv(x)
        self.assertEqual(
            pub[1:33].hex().upper(),
            "60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6")
        self.assertTrue(wl._pure_ecdsa_verify(pub, b"sample", r, s))
        self.assertFalse(wl._pure_ecdsa_verify(pub, b"Sample", r, s))

    def test_points_invalides(self):
        good = wl._pure_pub_from_priv(12345)
        bad = good[:-1] + bytes([good[-1] ^ 1])
        with self.assertRaises(ValueError):
            wl._decode_point(bad)
        with self.assertRaises(ValueError):
            wl._decode_point(b"\x04" + b"\0" * 64)  # (0, 0) hors courbe
        with self.assertRaises(ValueError):
            wl._decode_point(b"\x02" + good[1:33])
        with self.assertRaises(ValueError):
            wl._pure_ecdh(5, bad)

    def test_ordre_de_la_courbe(self):
        self.assertIsNone(wl._to_affine(wl._mul_jac(wl._N, wl._G)))  # n*G = infini
        self.assertEqual(wl._mul(wl._N - 1, wl._G)[0], wl._GX)

    def test_helpers_base64(self):
        self.assertEqual(b64d("AQI"), b"\x01\x02")
        self.assertEqual(b64d(b"AQI="), b"\x01\x02")
        self.assertEqual(b64d("-_8"), b"\xfb\xff")
        self.assertEqual(b64e(b"\xfb\xff"), "-_8")
        self.assertEqual(wl.num_to_bytes(258, 4), b"\0\0\x01\x02")
        with self.assertRaises(ValueError):
            b64d("A")


class RfcVectorsTest(unittest.TestCase):
    """Annexe / section 5 de la RFC 8291, sur chaque backend et en croisé."""

    def encrypt(self):
        return wl.ece_encrypt_aes128gcm(
            RFC_PLAINTEXT, b64d(RFC_UA_PUBLIC), b64d(RFC_AUTH),
            salt=b64d(RFC_SALT), sender_private=RFC_AS_PRIVATE)

    def decrypt(self, body):
        return wl.ece_decrypt_aes128gcm(body, RFC_UA_PRIVATE, b64d(RFC_AUTH))

    def test_cles_publiques_derivees(self):
        for pure in backends():
            with self.subTest(pure=pure), backend(pure):
                self.assertEqual(
                    b64e(wl._pub_from_priv(wl._coerce_scalar(RFC_AS_PRIVATE))),
                    RFC_AS_PUBLIC)
                self.assertEqual(
                    b64e(wl._pub_from_priv(wl._coerce_scalar(RFC_UA_PRIVATE))),
                    RFC_UA_PUBLIC)

    def test_valeurs_intermediaires(self):
        for pure in backends():
            with self.subTest(pure=pure), backend(pure):
                secret = wl._ecdh(wl._coerce_scalar(RFC_AS_PRIVATE), b64d(RFC_UA_PUBLIC))
                self.assertEqual(b64e(secret), "kyrL1jIIOHEzg3sM2ZWRHDRB62YACZhhSlknJ672kSs")
                cek, nonce = wl._ece_derive(
                    secret, b64d(RFC_AUTH), b64d(RFC_UA_PUBLIC),
                    b64d(RFC_AS_PUBLIC), b64d(RFC_SALT))
                self.assertEqual(b64e(cek), "oIhVW04MRdy2XN9CiKLxTg")
                self.assertEqual(b64e(nonce), "4h_95klXJ5E_qnoN")

    def test_chiffrement(self):
        for pure in backends():
            with self.subTest(pure=pure), backend(pure):
                self.assertEqual(b64e(self.encrypt()), RFC_BODY)

    def test_dechiffrement(self):
        for pure in backends():
            with self.subTest(pure=pure), backend(pure):
                self.assertEqual(self.decrypt(b64d(RFC_BODY)), RFC_PLAINTEXT)

    def test_croise(self):
        if not HAVE_CRYPTO:
            self.skipTest("module « cryptography » absent : test inter-backends sauté")
        for enc_pure, dec_pure in ((True, False), (False, True)):
            with self.subTest(chiffre_pur=enc_pure):
                with backend(enc_pure):
                    body = self.encrypt()
                with backend(dec_pure):
                    self.assertEqual(self.decrypt(body), RFC_PLAINTEXT)

    def test_croise_aleatoire_multi_enregistrements(self):
        if not HAVE_CRYPTO:
            self.skipTest("module « cryptography » absent : test inter-backends sauté")
        d = wl._new_scalar()
        pub, auth = wl._pub_from_priv(d), os.urandom(16)
        for n, rs in ((0, 4096), (1, 4096), (4078, 4096), (4079, 4096),
                      (300, 64), (47, 64), (48, 64), (95, 64)):
            pt = os.urandom(n)
            for enc_pure in (True, False):
                with backend(enc_pure):
                    body = wl.ece_encrypt_aes128gcm(pt, pub, auth, rs=rs)
                with backend(not enc_pure):
                    self.assertEqual(wl.ece_decrypt_aes128gcm(body, d, auth), pt, (n, rs))

    def test_multi_enregistrements_pur(self):
        d = wl._new_scalar()
        pub, auth = wl._pub_from_priv(d), os.urandom(16)
        with backend(True):
            for n in (0, 1, 46, 47, 48, 100, 500):
                pt = os.urandom(n)
                body = wl.ece_encrypt_aes128gcm(pt, pub, auth, rs=64)
                self.assertEqual(wl.ece_decrypt_aes128gcm(body, d, auth), pt, n)
                # l'enregistrement final est strictement plus court que rs
                self.assertLess(len(body[86:]) % 64 or 63, 64)

    def test_corps_altere_ou_tronque(self):
        body = bytearray(b64d(RFC_BODY))
        for pure in backends():
            with self.subTest(pure=pure), backend(pure):
                bad = bytes(body[:-1]) + bytes([body[-1] ^ 1])
                with self.assertRaises(ValueError):
                    self.decrypt(bad)
                with self.assertRaises(ValueError):
                    self.decrypt(bytes(body[:50]))
                with self.assertRaises(ValueError):
                    self.decrypt(b"")
                with self.assertRaises(ValueError):  # mauvais secret d'authentification
                    wl.ece_decrypt_aes128gcm(bytes(body), RFC_UA_PRIVATE, b"\0" * 16)

    def test_troncature_multi_enregistrements(self):
        d = wl._new_scalar()
        pub, auth = wl._pub_from_priv(d), os.urandom(16)
        with backend(True):
            body = wl.ece_encrypt_aes128gcm(os.urandom(200), pub, auth, rs=64)
            # retirer l'enregistrement final : le flux n'est plus terminé par 0x02
            cut = body[:86 + 64 * 3]
            with self.assertRaises(ValueError):
                wl.ece_decrypt_aes128gcm(cut, d, auth)

    def test_parametres_invalides(self):
        pub, auth = wl._pub_from_priv(7), b"a" * 16
        with self.assertRaises(ValueError):
            wl.ece_encrypt_aes128gcm(b"x", pub, auth, rs=17)
        with self.assertRaises(ValueError):
            wl.ece_encrypt_aes128gcm(b"x", pub, auth, salt=b"court")
        with self.assertRaises(ValueError):
            wl.ece_encrypt_aes128gcm(b"x", pub[:-1] + b"\0", auth)


class SignatureTest(unittest.TestCase):

    def test_jwt_pur_verifie_par_cryptography(self):
        if not HAVE_CRYPTO:
            self.skipTest("module « cryptography » absent : test inter-backends sauté")
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        claims = {"aud": "https://push.example", "exp": 1999999999, "sub": "mailto:a@b.c"}
        pub = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), b64d(KEY_PUB))
        for _ in range(5):
            with backend(True):
                tok = wl.es256_sign_jwt(claims, KEY_RAW)
            head, payload, sig = tok.split(".")
            self.assertEqual(json.loads(b64d(head)), {"typ": "JWT", "alg": "ES256"})
            self.assertEqual(json.loads(b64d(payload)), claims)
            raw = b64d(sig)
            self.assertEqual(len(raw), 64)
            der = utils.encode_dss_signature(
                int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
            pub.verify(der, (head + "." + payload).encode(), ec.ECDSA(hashes.SHA256()))
            with self.assertRaises(InvalidSignature):
                pub.verify(der, b"autre", ec.ECDSA(hashes.SHA256()))

    def test_jwt_cryptography_verifie_par_pur(self):
        if not HAVE_CRYPTO:
            self.skipTest("module « cryptography » absent : test inter-backends sauté")
        claims = {"aud": "https://push.example", "exp": 1999999999, "sub": "mailto:a@b.c"}
        with backend(False):
            tok = wl.es256_sign_jwt(claims, KEY_RAW)
        self.assertEqual(wl.es256_verify_jwt(tok, KEY_PUB), claims)

    def test_jwt_pur_verifie_par_pur(self):
        claims = {"aud": "https://push.example", "exp": 1999999999, "sub": "mailto:a@b.c"}
        with backend(True):
            tok = wl.es256_sign_jwt(claims, KEY_RAW)
        self.assertEqual(wl.es256_verify_jwt(tok, KEY_PUB), claims)
        head, payload, sig = tok.split(".")
        forged = ".".join([head, b64e(b'{"aud":"https://evil"}'), sig])
        with self.assertRaises(ValueError):
            wl.es256_verify_jwt(forged, KEY_PUB)
        with self.assertRaises(ValueError):
            wl.es256_verify_jwt("n.importe.quoi", KEY_PUB)

    def test_ecdsa_pur_deterministe(self):
        with backend(True):
            a = wl.es256_sign_jwt({"sub": "x"}, KEY_RAW)
            b = wl.es256_sign_jwt({"sub": "x"}, KEY_RAW)
        self.assertEqual(a, b)


class KeysTest(unittest.TestCase):

    @NEED_CRYPTO
    def test_ecdh_pur_vs_cryptography(self):
        for _ in range(5):
            a, b = wl._new_scalar(), wl._new_scalar()
            with backend(True):
                pa, pb = wl._pub_from_priv(a), wl._pub_from_priv(b)
                s_pure = wl._ecdh(a, pb)
                self.assertEqual(s_pure, wl._ecdh(b, pa))
            with backend(False):
                self.assertEqual(wl._pub_from_priv(a), pa)
                self.assertEqual(wl._pub_from_priv(b), pb)
                self.assertEqual(wl._ecdh(a, pb), s_pure)

    def test_cle_publique_vecteur_fixe(self):
        for pure in backends():
            with self.subTest(pure=pure), backend(pure):
                self.assertEqual(b64e(wl._pub_from_priv(wl._coerce_scalar(KEY_RAW))), KEY_PUB)

    def test_generate_raw_keys(self):
        for pure in backends():
            with self.subTest(pure=pure), backend(pure):
                priv, pub = wl.generate_raw_keys()
                self.assertEqual((len(priv), len(pub)), (43, 87))
                self.assertNotIn("=", priv + pub)
                v = wl.Vapid.from_string(priv)
                self.assertEqual(b64e(v.public_key_raw), pub)
                self.assertEqual(len(v.public_key_raw), 65)
                self.assertEqual(v.public_key_raw[0], 4)
                self.assertNotEqual(wl.generate_raw_keys()[0], priv)

    def test_vapid_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            pem_path = os.path.join(tmp, "k.pem")
            with open(pem_path, "w") as fh:
                fh.write(KEY_PEM_PKCS8)
            der_b64 = "".join(KEY_PEM_SEC1.splitlines()[1:-1])
            cas = {
                "brute": KEY_RAW,
                "brute+padding": KEY_RAW + "=",
                "PEM SEC1": KEY_PEM_SEC1,
                "PEM PKCS8": KEY_PEM_PKCS8,
                "PEM en bytes": KEY_PEM_PKCS8.encode(),
                "DER base64 (SEC1)": der_b64,
                "chemin de fichier": pem_path,
                "32 octets": b64d(KEY_RAW),
            }
            for nom, valeur in cas.items():
                with self.subTest(nom):
                    self.assertEqual(
                        b64e(wl.Vapid.from_string(valeur).public_key_raw), KEY_PUB)
            self.assertEqual(
                b64e(wl.Vapid.from_file(pem_path).public_key_raw), KEY_PUB)

    def test_vapid_cles_invalides(self):
        for mauvais in ("", "pas une clé", "AAAA", b64e(b"\0" * 32),
                        b64e(b"\xff" * 32), b64e(b"x" * 33),
                        "-----BEGIN EC PRIVATE KEY-----\nAAAA\n-----END EC PRIVATE KEY-----",
                        "/chemin/inexistant/k.pem", 3.14, None):
            with self.subTest(repr(mauvais)):
                with self.assertRaises(wl.WebPushException):
                    wl.Vapid.from_string(mauvais)

    def test_sign_authorization(self):
        v = wl.Vapid.from_string(KEY_RAW)
        claims = {"sub": "mailto:admin@example.org", "aud": "https://push.example",
                  "exp": 1999999999}
        before = dict(claims)
        hdr = v.sign(claims)
        self.assertEqual(claims, before)
        self.assertEqual(list(hdr), ["Authorization"])
        scheme, rest = hdr["Authorization"].split(" ", 1)
        self.assertEqual(scheme, "vapid")
        t, k = rest.split(",")
        self.assertTrue(t.startswith("t=") and k == "k=" + KEY_PUB)
        self.assertEqual(wl.es256_verify_jwt(t[2:], KEY_PUB), claims)
        with self.assertRaises(wl.WebPushException):
            v.sign({"aud": "https://push.example"})  # sub manquant
        with self.assertRaises(wl.WebPushException):
            v.sign({"sub": "mailto:a@b.c"})  # aud manquant
        claims.pop("exp")
        exp = wl.es256_verify_jwt(v.sign(claims)["Authorization"].split("t=")[1].split(",")[0],
                                  KEY_PUB)["exp"]
        self.assertGreater(exp, time.time() + 11 * 3600)


class ExceptionTest(unittest.TestCase):

    def test_str_et_proprietes(self):
        e = wl.WebPushException("oups")
        self.assertEqual(str(e), "WebPushException: oups")
        self.assertEqual((e.message, e.response, e.status_code, e.retry_after),
                         ("oups", None, None, None))

        class Rep:
            status_code = 429
            text = "trop vite"
            headers = wl.CaseInsensitiveDict({"retry-after": "12"})

        e = wl.WebPushException("x", response=Rep())
        self.assertEqual(str(e), "WebPushException: x, Response trop vite")
        self.assertEqual((e.status_code, e.retry_after), (429, "12"))

        class Async:  # style aiohttp : ``status``, pas de ``text``
            status = 503
            headers = {}

            def __repr__(self):
                return "<async>"

        e = wl.WebPushException("y", response=Async())
        self.assertEqual(str(e), "WebPushException: y, Response <async>")
        self.assertEqual((e.status_code, e.retry_after), (503, None))


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        srv = self.server
        srv.requests.append({"path": self.path, "headers": dict(self.headers.items()),
                             "body": body, "method": "POST"})
        status, extra = srv.status, getattr(srv, "extra_headers", {})
        payload = srv.reply
        self.send_response(status)
        for k, v in extra.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence
        pass


class WebPushEndToEndTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._env = {k: os.environ.get(k) for k in
                    ("NO_PROXY", "no_proxy", "HTTP_PROXY", "http_proxy",
                     "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")}
        for k in cls._env:
            os.environ.pop(k, None)
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.srv.daemon_threads = True
        cls.srv.requests = []
        cls.srv.status, cls.srv.reply = 201, b""
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.srv.server_address[1]
        cls.origin = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def setUp(self):
        self.srv.requests.clear()
        self.srv.status, self.srv.reply = 201, b""
        self.srv.extra_headers = {}

    def sub(self):
        return make_subscription(self.origin + "/push/abc")

    def test_envoi_complet(self):
        claims = {"sub": "mailto:admin@example.org"}
        for pure in backends():
            with self.subTest(pure=pure), backend(pure):
                self.srv.requests.clear()
                info, d, auth = self.sub()
                resp = wl.webpush(info, data="Bonjour é€ 🎉", vapid_private_key=KEY_RAW,
                                  vapid_claims=claims, ttl=60,
                                  headers={"Urgency": "high"})
                self.assertEqual(resp.status_code, 201)
                self.assertEqual(len(self.srv.requests), 1)
                req = self.srv.requests[0]
                h = {k.lower(): v for k, v in req["headers"].items()}
                self.assertEqual(req["path"], "/push/abc")
                self.assertEqual(h["content-encoding"], "aes128gcm")
                self.assertEqual(h["content-type"], "application/octet-stream")
                self.assertEqual(h["ttl"], "60")
                self.assertEqual(h["urgency"], "high")
                self.assertEqual(int(h["content-length"]), len(req["body"]))
                # corps déchiffrable par le « navigateur »
                self.assertEqual(wl.ece_decrypt_aes128gcm(req["body"], d, auth),
                                 "Bonjour é€ 🎉".encode("utf-8"))
                self.assertEqual(req["body"][16:20], (4096).to_bytes(4, "big"))
                # VAPID
                scheme, rest = h["authorization"].split(" ", 1)
                self.assertEqual(scheme, "vapid")
                t, k = rest.split(",")
                self.assertEqual(k, "k=" + KEY_PUB)
                got = wl.es256_verify_jwt(t[2:], KEY_PUB)
                self.assertEqual(got["aud"], self.origin)
                self.assertEqual(got["sub"], "mailto:admin@example.org")
                self.assertGreater(got["exp"], time.time() + 11 * 3600)
                self.assertLessEqual(got["exp"], time.time() + 12 * 3600 + 5)
        # l'appelant garde son dict intact
        self.assertEqual(claims, {"sub": "mailto:admin@example.org"})

    def test_jwt_verifie_par_cryptography(self):
        if not HAVE_CRYPTO:
            self.skipTest("module « cryptography » absent : test inter-backends sauté")
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        info, _, _ = self.sub()
        with backend(True):
            wl.webpush(info, data=b"x", vapid_private_key=KEY_RAW,
                       vapid_claims={"sub": "mailto:a@b.c"})
        t = self.srv.requests[0]["headers"]["Authorization"].split("t=")[1].split(",")[0]
        head, payload, sig = t.split(".")
        raw = b64d(sig)
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64d(KEY_PUB))
        pub.verify(utils.encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                              int.from_bytes(raw[32:], "big")),
                   (head + "." + payload).encode(), ec.ECDSA(hashes.SHA256()))

    def test_claims_fournies_conservees_et_exp_perime_remplacee(self):
        info, _, _ = self.sub()
        claims = {"sub": "mailto:a@b.c", "aud": "https://autre.example",
                  "exp": int(time.time()) - 10}
        snapshot = dict(claims)
        wl.webpush(info, data="x", vapid_private_key=KEY_RAW, vapid_claims=claims)
        self.assertEqual(claims, snapshot)
        t = self.srv.requests[0]["headers"]["Authorization"].split("t=")[1].split(",")[0]
        got = wl.es256_verify_jwt(t, KEY_PUB)
        self.assertEqual(got["aud"], "https://autre.example")
        self.assertGreater(got["exp"], time.time())
        # exp encore valide : conservé tel quel
        claims = {"sub": "mailto:a@b.c", "exp": int(time.time()) + 600}
        wl.webpush(info, data="x", vapid_private_key=KEY_RAW, vapid_claims=claims)
        t = self.srv.requests[1]["headers"]["Authorization"].split("t=")[1].split(",")[0]
        self.assertEqual(wl.es256_verify_jwt(t, KEY_PUB)["exp"], claims["exp"])

    def test_headers_appelant_non_mutes(self):
        info, _, _ = self.sub()
        hdrs = {"Urgency": "low"}
        wl.webpush(info, data="x", vapid_private_key=KEY_RAW,
                   vapid_claims={"sub": "mailto:a@b.c"}, headers=hdrs)
        self.assertEqual(hdrs, {"Urgency": "low"})

    def test_sans_donnees(self):
        info, _, _ = self.sub()
        resp = wl.webpush(info)
        self.assertEqual(resp.status_code, 201)
        req = self.srv.requests[0]
        h = {k.lower(): v for k, v in req["headers"].items()}
        self.assertEqual(req["body"], b"")
        self.assertNotIn("content-encoding", h)
        self.assertNotIn("authorization", h)
        self.assertEqual(h["ttl"], "0")
        # abonnement sans clés accepté sans données, refusé avec
        wl.webpush({"endpoint": self.origin + "/p"})
        with self.assertRaises(wl.WebPushException):
            wl.webpush({"endpoint": self.origin + "/p"}, data="x")

    def test_statuts_erreur(self):
        info, _, _ = self.sub()
        for status in (400, 404, 410, 413, 429, 500, 503):
            with self.subTest(status=status):
                self.srv.status = status
                self.srv.reply = b"detail %d" % status
                self.srv.extra_headers = {"Retry-After": "30"}
                with self.assertRaises(wl.WebPushException) as cm:
                    wl.webpush(info, data="x")
                exc = cm.exception
                self.assertEqual(exc.status_code, status)
                self.assertEqual(exc.retry_after, "30")
                self.assertEqual(exc.response.text, "detail %d" % status)
                self.assertIn("Push failed: %d" % status, str(exc))
                self.assertIn("detail %d" % status, str(exc))
                self.assertEqual(exc.response.headers.get("RETRY-AFTER"), "30")
                self.assertTrue(exc.response.url.startswith(self.origin))

    def test_statuts_succes(self):
        info, _, _ = self.sub()
        for status in (200, 201, 202):
            self.srv.status = status
            self.assertEqual(wl.webpush(info, data="x").status_code, status)
        self.srv.status = 204
        with self.assertRaises(wl.WebPushException):  # > 202 est un échec (comme pywebpush)
            wl.webpush(info, data="x")

    def test_redirection_non_suivie(self):
        info, _, _ = self.sub()
        self.srv.status = 307
        self.srv.extra_headers = {"Location": "http://127.0.0.1:1/ailleurs"}
        with self.assertRaises(wl.WebPushException) as cm:
            wl.webpush(info, data="x")
        self.assertEqual(cm.exception.status_code, 307)
        self.assertEqual(len(self.srv.requests), 1)

    def test_payload_trop_grand(self):
        info, _, _ = self.sub()
        with self.assertRaises(wl.WebPushException) as cm:
            wl.webpush(info, data=b"a" * 3994)
        self.assertIn("Data too large", str(cm.exception))
        self.assertEqual(self.srv.requests, [])
        # la limite elle-même passe, et tient dans 4096 octets
        wl.webpush(info, data=b"a" * 3993)
        self.assertEqual(len(self.srv.requests[0]["body"]), 4096)

    def test_content_encoding_non_supporte(self):
        info, _, _ = self.sub()
        with self.assertRaises(wl.WebPushException) as cm:
            wl.webpush(info, data="x", content_encoding="aesgcm")
        self.assertIn("non pris en charge par la version autonome", str(cm.exception))
        self.assertEqual(self.srv.requests, [])

    def test_vapid_sans_cle_ou_cle_invalide(self):
        info, _, _ = self.sub()
        with self.assertRaises(wl.WebPushException):
            wl.webpush(info, data="x", vapid_claims={"sub": "mailto:a@b.c"})
        with self.assertRaises(wl.WebPushException):
            wl.webpush(info, data="x", vapid_private_key="n'importe quoi",
                       vapid_claims={"sub": "mailto:a@b.c"})
        with self.assertRaises(wl.WebPushException):  # sub manquant
            wl.webpush(info, data="x", vapid_private_key=KEY_RAW,
                       vapid_claims={"aud": self.origin})
        self.assertEqual(self.srv.requests, [])

    def test_instance_vapid(self):
        info, _, _ = self.sub()
        wl.webpush(info, data="x", vapid_private_key=wl.Vapid.from_string(KEY_RAW),
                   vapid_claims={"sub": "mailto:a@b.c"})
        self.assertIn("k=" + KEY_PUB, self.srv.requests[0]["headers"]["Authorization"])

    def test_abonnements_invalides(self):
        good, _, _ = self.sub()
        k = good["keys"]
        cas = [
            {},
            {"endpoint": ""},
            {"endpoint": "file:///etc/passwd", "keys": k},
            {"endpoint": "ftp://x/y", "keys": k},
            {"endpoint": good["endpoint"], "keys": {"auth": k["auth"]}},
            {"endpoint": good["endpoint"], "keys": {"p256dh": k["p256dh"]}},
            {"endpoint": good["endpoint"], "keys": {"p256dh": b64e(b"\x04" + b"\0" * 10),
                                                    "auth": k["auth"]}},
            {"endpoint": good["endpoint"],
             "keys": {"p256dh": b64e(b"\x02" + wl._pub_from_priv(5)[1:]), "auth": k["auth"]}},
            {"endpoint": good["endpoint"],
             "keys": {"p256dh": b64e(wl._pub_from_priv(5)[:-1] + b"\x00"), "auth": k["auth"]}},
            {"endpoint": good["endpoint"], "keys": {"p256dh": "!!!", "auth": k["auth"]}},
        ]
        for i, bad in enumerate(cas):
            with self.subTest(i=i):
                with self.assertRaises(wl.WebPushException):
                    wl.webpush(bad, data="x")
        self.assertEqual(self.srv.requests, [])

    def test_cles_avec_ou_sans_padding_et_bytes(self):
        info, d, auth = self.sub()
        k = info["keys"]
        variantes = [
            {"p256dh": k["p256dh"] + "=", "auth": k["auth"] + "=="},
            {"p256dh": k["p256dh"].encode(), "auth": k["auth"].encode()},
        ]
        for keys in variantes:
            self.srv.requests.clear()
            wl.webpush({"endpoint": info["endpoint"], "keys": keys}, data=b"\x00\x01bin")
            self.assertEqual(
                wl.ece_decrypt_aes128gcm(self.srv.requests[0]["body"], d, auth),
                b"\x00\x01bin")

    def test_curl(self):
        info, _, _ = self.sub()
        out = wl.webpush(info, data="x", vapid_private_key=KEY_RAW,
                         vapid_claims={"sub": "mailto:a@b.c"}, curl=True)
        self.assertIsInstance(out, str)
        self.assertIn("curl", out)
        self.assertIn("authorization: vapid t=", out)
        self.assertEqual(self.srv.requests, [])

    def test_requests_session_ignore(self):
        info, _, _ = self.sub()
        self.assertEqual(wl.webpush(info, data="x", requests_session=object()).status_code, 201)

    def test_erreur_reseau_remonte_telle_quelle(self):
        # port fermé : on réserve un port puis on le libère
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        info, _, _ = make_subscription("http://127.0.0.1:%d/x" % port)
        with self.assertRaises(urllib.error.URLError) as cm:
            wl.webpush(info, data="x", timeout=5)
        self.assertNotIsInstance(cm.exception, wl.WebPushException)
        self.assertIsInstance(cm.exception, OSError)

    def test_delai_depasse(self):
        import socket
        silent = socket.socket()
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)  # accepte les connexions (backlog) mais ne répond jamais
        try:
            info, _, _ = make_subscription(
                "http://127.0.0.1:%d/x" % silent.getsockname()[1])
            t0 = time.time()
            with self.assertRaises(OSError) as cm:  # TimeoutError ou URLError(timeout)
                wl.webpush(info, data="x", timeout=0.5)
            self.assertNotIsInstance(cm.exception, wl.WebPushException)
            self.assertLess(time.time() - t0, 5)
        finally:
            silent.close()


class RegistrationTest(unittest.TestCase):
    """Le module doit pouvoir être enregistré sous deux noms (pywebpush / py_vapid)."""

    def test_double_nom(self):
        saved = {n: sys.modules.get(n) for n in ("pywebpush", "py_vapid")}
        try:
            sys.modules["pywebpush"] = sys.modules["py_vapid"] = wl
            from pywebpush import webpush, WebPushException  # noqa: F401
            from py_vapid import Vapid
            self.assertIs(webpush, wl.webpush)
            self.assertIs(Vapid, wl.Vapid)
        finally:
            for n, m in saved.items():
                if m is None:
                    sys.modules.pop(n, None)
                else:
                    sys.modules[n] = m

    def test_stdlib_seule_hors_cryptography(self):
        import ast
        with open(wl.__file__.replace(".pyc", ".py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        stdlib = getattr(sys, "stdlib_module_names", None)
        if stdlib is None:
            self.skipTest("sys.stdlib_module_names indisponible")
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                self.assertTrue(top in stdlib or top == "cryptography", name)


if __name__ == "__main__":
    print("webpush_lite : backend cryptography %s"
          % ("disponible" if HAVE_CRYPTO else "ABSENT (repli pur Python seul)"))
    unittest.main(verbosity=2)

"""Magasin de session (Q1) : keyring dédié, repli fichier, expiration, purge."""
import os
import stat
import time

import pytest

from sshvault.session import SessionStore, SessionStoreError

from bench import keyring_session

TOK = "dGVzdC1zZXNzaW9uLWtleS0wMTIzNDU2Nzg5"


@pytest.fixture
def rt(runtime_dir):
    return runtime_dir


def keyctl_wrapper(tmp_path, fail_on):
    """keyctl qui échoue sur une sous-commande donnée."""
    w = tmp_path / "keyctl"
    w.write_text("#!/bin/sh\n[ \"$1\" = '%s' ] && { echo 'keyctl_set_timeout: Permission denied' >&2; exit 1; }\n"
                 "exec keyctl \"$@\"\n" % fail_on)
    w.chmod(0o755)
    return str(w)


def test_keyring(ring, rt):
    if not ring:
        pytest.skip("pas de session keyring dédiée")
    s = SessionStore(keyring=ring, runtime_dir=str(rt))
    assert s.get() is None
    assert s.put(TOK, 60) == "keyring"
    assert keyring_session(ring, None) == TOK
    assert s.get() == TOK and s.last_backend == "keyring"
    assert not (rt / "sshvault" / "session").exists(), "aucun fichier quand le keyring marche"
    s.clear()
    assert keyring_session(ring, None) is None and s.get() is None


def test_keyring_expiration_noyau(ring, rt):
    if not ring:
        pytest.skip("pas de session keyring dédiée")
    s = SessionStore(keyring=ring, runtime_dir=str(rt))
    s.put(TOK, 1)
    time.sleep(1.5)
    assert s.get() is None


def test_keyring_timeout_refuse_repli_fichier(ring, rt, tmp_path):
    """keyctl timeout refusé (session non liée à @u) : clé retirée, repli fichier."""
    if not ring:
        pytest.skip("pas de session keyring dédiée")
    s = SessionStore(keyring=ring, keyctl=keyctl_wrapper(tmp_path, "timeout"), runtime_dir=str(rt))
    assert s.put(TOK, 60) == "file"
    assert keyring_session(ring, None) is None, "pas de clé sans délai laissée dans l'anneau"
    f = rt / "sshvault" / "session"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert s.get() == TOK and s.last_backend == "file"


def test_fichier_expire_a_la_lecture(rt):
    now = [1000.0]
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt), clock=lambda: now[0])
    assert s.put(TOK, 10) == "file"
    now[0] += 9
    assert s.get() == TOK
    now[0] += 2
    assert s.get() is None
    assert not (rt / "sshvault" / "session").exists()


def test_fichier_permissions_etrangeres_ignore(rt):
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt))
    s.put(TOK, 60)
    f = rt / "sshvault" / "session"
    os.chmod(f, 0o644)
    assert s.get() is None


def test_fichier_lien_ignore(rt, tmp_path):
    other = tmp_path / "autre"
    other.write_text("%s %d\n" % (TOK, time.time() + 60))
    os.chmod(other, 0o600)
    (rt / "sshvault").mkdir(mode=0o700)
    (rt / "sshvault" / "session").symlink_to(other)
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt))
    assert s.get() is None


def test_fichier_corrompu(rt):
    (rt / "sshvault").mkdir(mode=0o700)
    f = rt / "sshvault" / "session"
    f.write_text("n'importe quoi")
    os.chmod(f, 0o600)
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt))
    assert s.get() is None


def test_ni_keyring_ni_runtime():
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir="")
    with pytest.raises(SessionStoreError):
        s.put(TOK, 60)
    assert s.get() is None
    s.clear()


@pytest.mark.parametrize("ttl", [0, -1, 1.5, "60"])
def test_ttl_invalide(rt, ttl):
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt))
    with pytest.raises(SessionStoreError):
        s.put(TOK, ttl)


@pytest.mark.parametrize("tok", ["", "court", "avec espace dedans", "a\nb" * 10])
def test_jeton_invalide(rt, tok):
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt))
    with pytest.raises(SessionStoreError):
        s.put(tok, 60)


def test_clear_vide_les_deux(ring, rt):
    if not ring:
        pytest.skip("pas de session keyring dédiée")
    SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt)).put(TOK, 60)
    s = SessionStore(keyring=ring, runtime_dir=str(rt))
    s._keyring_put(TOK, 60)
    s.clear()
    assert keyring_session(ring, None) is None
    assert not (rt / "sshvault" / "session").exists()


def test_put_keyring_retire_fichier_perime(ring, rt):
    if not ring:
        pytest.skip("pas de session keyring dédiée")
    SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt)).put("ancienne-session-xxxx", 60)
    s = SessionStore(keyring=ring, runtime_dir=str(rt))
    assert s.put(TOK, 60) == "keyring"
    assert not (rt / "sshvault" / "session").exists()



def test_jeton_avec_fin_de_ligne_refuse():
    from sshvault.session import valid_token
    assert valid_token(TOK)
    assert not valid_token(TOK + "\n")


def test_put_dit_ou(ring, rt):
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt))
    assert s.last_backend is None
    s.put(TOK, 60)
    assert s.last_backend == "file"
    s.clear()
    assert s.last_backend is None
    if ring:
        s = SessionStore(keyring=ring, runtime_dir=str(rt))
        s.put(TOK, 60)
        assert s.last_backend == "keyring"
        s.clear()


def test_clear_fichier_impossible(rt):
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt))
    s.put(TOK, 60)
    d = rt / "sshvault"
    os.chmod(d, 0o500)
    try:
        with pytest.raises(SessionStoreError, match="impossible de supprimer"):
            s.clear()
    finally:
        os.chmod(d, 0o700)


def test_runtime_hors_tmpfs_refuse(tmp_path):
    d = tmp_path / "run"
    d.mkdir(mode=0o700)
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(d))
    with pytest.raises(SessionStoreError, match="tmpfs privé"):
        s.put(TOK, 60)
    assert not (d / "sshvault").exists()


def test_runtime_droits_groupe_refuse(rt):
    sub = rt / "partage"
    sub.mkdir(mode=0o700)
    os.chmod(sub, 0o710)
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(sub))
    with pytest.raises(SessionStoreError, match="tmpfs privé"):
        s.put(TOK, 60)


def test_session_par_compte(ring, rt):
    """CAP-10 : une session par alias (clé `sshvault:session:<alias>`, repli `sessions/<alias>`),
    indépendantes entre elles et de celle de la 0.8.0."""
    kw = {"keyring": ring} if ring else {"keyctl": "/nonexistent/keyctl"}
    a = SessionStore(runtime_dir=str(rt), alias="perso", **kw)
    b = SessionStore(runtime_dir=str(rt), alias="boulot", **kw)
    legacy = SessionStore(runtime_dir=str(rt), **kw)
    where = a.put(TOK, 60)
    assert where == ("keyring" if ring else "file")
    assert a.get() == TOK and b.get() is None and legacy.get() is None
    if ring:
        assert keyring_session(ring, "perso") == TOK and keyring_session(ring, None) is None
    else:
        f = rt / "sshvault" / "sessions" / "perso"
        assert stat.S_IMODE(f.stat().st_mode) == 0o600 and stat.S_IMODE(f.parent.stat().st_mode) == 0o700
        assert not (rt / "sshvault" / "session").exists()
    b.put("autre-session-%s" % TOK, 60)
    a.clear()
    assert a.get() is None and b.get() == "autre-session-%s" % TOK
    assert "sessions/perso" in a.describe() and "sessions/boulot" in b.describe()


def test_move_to_keyring_garde_la_duree(ring, rt):
    """Compte renommé : jeton déplacé sous la nouvelle clé avec sa durée restante (arrondie
    vers le bas par /proc/keys), pas la durée par défaut ; ancienne clé retirée."""
    if not ring:
        pytest.skip("pas de session keyring dédiée")
    old = SessionStore(keyring=ring, runtime_dir=str(rt), alias="boulot")
    new = SessionStore(keyring=ring, runtime_dir=str(rt), alias="travail")
    old.put(TOK, 3000)
    assert old.move_to(new) == "keyring"
    assert old.get() is None and keyring_session(ring, "boulot") is None
    assert new.get() == TOK
    ttl = new._keyring_ttl()
    assert ttl is not None and 2800 <= ttl <= 3000, ttl


def test_move_to_fichier_garde_l_expiration(rt):
    old = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt), alias="boulot")
    new = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt), alias="travail")
    old.put(TOK, 500)
    exp = (rt / "sshvault" / "sessions" / "boulot").read_text().split()[1]
    assert old.move_to(new) == "file"
    assert not (rt / "sshvault" / "sessions" / "boulot").exists()
    assert (rt / "sshvault" / "sessions" / "travail").read_text().split() == [TOK, exp]
    assert new.get() == TOK and old.get() is None


def test_move_to_refuse_garde_l_ancienne(ring, rt, tmp_path):
    """Nouvelle clé refusée (keyctl padd en échec) : SessionStoreError, ancienne session intacte."""
    if not ring:
        pytest.skip("pas de session keyring dédiée")
    old = SessionStore(keyring=ring, runtime_dir=str(rt), alias="boulot")
    new = SessionStore(keyring=ring, keyctl=keyctl_wrapper(tmp_path, "padd"), runtime_dir=str(rt), alias="travail")
    old.put(TOK, 600)
    with pytest.raises(SessionStoreError):
        old.move_to(new)
    assert old.get() == TOK and keyring_session(ring, "travail") is None


def test_move_to_sans_session(rt):
    old = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt), alias="boulot")
    assert old.move_to(SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt), alias="travail")) is None

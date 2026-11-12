"""Magasin de session (Q1) : keyring dédié, repli fichier, expiration, purge."""
import errno
import os
import stat
import time

import pytest

from sshvault import session as session_mod
from sshvault.session import SessionStore, SessionStoreError

from bench import PASSWORD, keyring_session

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


# --- story 22 : erreurs de keyctl classées ------------------------------------------------------

def fake_keyctl(tmp_path, sub, behaviour, name="keyctl-faux", desc=None, log=None):
    """keyctl de test : la sous-commande `sub` échoue (`behaviour` : message d'erreur sur stderr, ou
    « sleep » pour ne jamais répondre), pour la clé `desc` seulement s'il est donné (sinon pour toutes) ;
    les autres vont au vrai keyctl (celui du PATH). `log` : fichier où chaque appel est noté (une ligne)."""
    w = tmp_path / name
    if behaviour == "sleep":
        action = "exec sleep 30"
    else:
        action = "echo 'keyctl_%s: %s' >&2; exit 1" % (sub, behaviour)
    cond = "[ \"$1\" = '%s' ]" % sub
    if desc:
        cond += " && [ \"$4\" = '%s' ]" % desc
    note = "echo \"$1\" >> '%s'\n" % log if log else ""
    w.write_text("#!/bin/sh\n%sif %s; then %s; fi\nexec keyctl \"$@\"\n" % (note, cond, action))
    w.chmod(0o755)
    return str(w)


def file_session(rt, alias=None):
    """Session rangée dans le fichier de repli (sans keyring) : le jeton."""
    SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt), alias=alias).put(TOK, 60)
    return TOK


UNREADABLE = ["Permission denied", "Disk quota exceeded", "Interrupted system call"]
#: mesuré (anneau jetable) : `search` d'une clé révoquée ou expirée le dit comme `pipe`
NO_SESSION = ["Required key not available", "Key has expired", "Key has been revoked"]
REFUSED = ["Operation not permitted", "Function not implemented"]


def pipe_keyctl(tmp_path, why, name="keyctl-pipe"):
    """keyctl dont `search` trouve une clé et dont `pipe` échoue avec `why`."""
    w = tmp_path / name
    w.write_text("#!/bin/sh\n[ \"$1\" = search ] && { echo 12345; exit 0; }\n"
                 "echo 'keyctl_read_alloc: %s' >&2; exit 1\n" % why)
    w.chmod(0o755)
    return str(w)


@pytest.mark.parametrize("why", UNREADABLE)
def test_keyctl_pipe_en_panne_sans_fichier_session_illisible(rt, tmp_path, why):
    s = SessionStore(keyctl=pipe_keyctl(tmp_path, why), runtime_dir=str(rt))
    with pytest.raises(SessionStoreError, match="^session illisible : keyctl .*%s" % why):
        s.get()


@pytest.mark.parametrize("why", NO_SESSION + REFUSED)
def test_keyctl_pipe_cle_partie_ou_keyring_refuse_pas_de_session(rt, tmp_path, why):
    """`pipe <notre clé>` : révoquée, expirée, absente, refusée = pas de session (jamais « illisible »)."""
    s = SessionStore(keyctl=pipe_keyctl(tmp_path, why), runtime_dir=str(rt))
    assert s.get() is None and s.last_backend is None
    file_session(rt)
    assert s.get() == TOK and s.last_backend == "file"


@pytest.mark.parametrize("why", UNREADABLE)
@pytest.mark.parametrize("sub", ["search"])
def test_keyctl_en_panne_sans_fichier_session_illisible(rt, tmp_path, sub, why):
    """Autre erreur que « clé absente » ou « keyring refusé » : pas « pas de session »."""
    s = SessionStore(keyctl=fake_keyctl(tmp_path, sub, why), runtime_dir=str(rt))
    with pytest.raises(SessionStoreError, match="^session illisible : keyctl .*%s" % why):
        s.get()
    assert s.last_backend is None


@pytest.mark.parametrize("why", UNREADABLE)
def test_keyctl_en_panne_session_du_fichier_utilisee(rt, tmp_path, why):
    """Le fichier de repli est lu d'abord : keyctl en panne ne l'empêche pas, et n'est même pas appelé."""
    file_session(rt)
    log = tmp_path / "appels"
    s = SessionStore(keyctl=fake_keyctl(tmp_path, "search", why, log=str(log)), runtime_dir=str(rt))
    assert s.get() == TOK and s.last_backend == "file"
    assert (rt / "sshvault" / "session").exists() and not log.exists()


@pytest.mark.parametrize("why", NO_SESSION + REFUSED)
def test_keyctl_pas_de_session_ou_keyring_refuse_pas_d_erreur(rt, tmp_path, why):
    s = SessionStore(keyctl=fake_keyctl(tmp_path, "search", why), runtime_dir=str(rt))
    assert s.get() is None and s.last_backend is None
    file_session(rt)  # repli fichier silencieux
    assert s.get() == TOK and s.last_backend == "file"


def test_keyctl_absent_repli_fichier_silencieux(rt):
    s = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(rt))
    assert s.get() is None
    file_session(rt)
    assert s.get() == TOK


def test_keyctl_inexecutable_repli_fichier_silencieux(rt, tmp_path):
    w = tmp_path / "keyctl-vide"
    w.write_text("")
    w.chmod(0o644)
    s = SessionStore(keyctl=str(w), runtime_dir=str(rt))
    assert s.get() is None


def test_keyctl_delai_depasse_session_illisible(rt, tmp_path, monkeypatch):
    """Matrice : `search` en délai dépassé, pas de fichier : « session illisible : keyctl … »."""
    monkeypatch.setattr(session_mod, "KEYCTL_TIMEOUT", 0.5)
    s = SessionStore(keyctl=fake_keyctl(tmp_path, "search", "sleep"), runtime_dir=str(rt))
    with pytest.raises(SessionStoreError, match="^session illisible : keyctl délai dépassé"):
        s.get()
    file_session(rt)
    assert s.get() == TOK and s.last_backend == "file"


def test_keyctl_en_panne_session_rangee_intacte(ring, rt, tmp_path):
    """La session du keyring n'est ni effacée ni réécrite par un get() qui échoue."""
    if not ring:
        pytest.skip("pas de session keyring dédiée")
    real = SessionStore(keyring=ring, runtime_dir=str(rt))
    assert real.put(TOK, 60) == "keyring"
    ttl = real._keyring_ttl()
    for sub, why in (("search", "Permission denied"), ("pipe", "Permission denied")):
        s = SessionStore(keyring=ring, keyctl=fake_keyctl(tmp_path, sub, why), runtime_dir=str(rt))
        with pytest.raises(SessionStoreError, match="session illisible"):
            s.get()
        assert keyring_session(ring, None) == TOK
    assert real.get() == TOK and real._keyring_ttl() <= ttl
    assert not (rt / "sshvault" / "session").exists()


def test_keyctl_en_panne_clear_dit_l_echec_et_vide_le_fichier(rt, tmp_path):
    file_session(rt)
    s = SessionStore(keyctl=fake_keyctl(tmp_path, "search", "Permission denied"), runtime_dir=str(rt))
    with pytest.raises(SessionStoreError, match="session illisible : keyctl"):
        s.clear()
    assert not (rt / "sshvault" / "session").exists()
    # keyring refusé : rien à retirer du keyring, pas d'erreur
    s = SessionStore(keyctl=fake_keyctl(tmp_path, "search", "Operation not permitted", "k2"), runtime_dir=str(rt))
    s.clear()


def test_keyctl_en_panne_move_to(rt, tmp_path):
    old = SessionStore(keyctl=fake_keyctl(tmp_path, "search", "Permission denied"), runtime_dir=str(rt), alias="a")
    new = SessionStore(keyctl=old.keyctl, runtime_dir=str(rt), alias="b")
    with pytest.raises(SessionStoreError, match="session illisible"):
        old.move_to(new)
    file_session(rt, alias="a")
    assert old.move_to(new) == "file" and new.get() == TOK


def test_keyctl_delai_depasse_list_et_ensure(bench, tmp_path):
    """Critère d'acceptation : keyctl qui dépasse le délai : `list --nointeraction` puis `ensure` ne
    disent ni « verrouillé » ni ne touchent à la session rangée ; les deux disent « session illisible »."""
    from bench import ID_PROD
    if not bench.ring:
        pytest.skip("pas de session keyring dédiée")
    tok = bench.unlocked("keyring")
    env = {"SSHVAULT_KEYCTL": fake_keyctl(tmp_path, "search", "sleep")}
    calls = len(bench.calls())
    for args in (("--nointeraction", "list"), ("--nointeraction", "ensure", "--id", ID_PROD)):
        r = bench.run(*args, env=env, timeout=120)
        assert r.returncode == 4, (args, r.stdout, r.stderr)
        assert "session illisible : keyctl" in r.stderr and "verrouillé" not in r.stderr, r.stderr
    assert bench.stored_session() == (tok, None), "session rangée intacte"
    assert len(bench.calls()) == calls, "aucun appel à bw"
    # keyctl rétabli : la session sert toujours
    r = bench.run("--nointeraction", "list")
    assert r.returncode == 0, r.stderr


# --- relecture de la revue de la story 22 ---------------------------------------------------------

@pytest.mark.parametrize("code,usable", [(errno.ENOENT, False), (errno.EACCES, False), (errno.ENOEXEC, False),
                                         (errno.ENOTDIR, False), (errno.ELOOP, False), (errno.ENAMETOOLONG, False),
                                         (errno.EAGAIN, True), (errno.ENOMEM, True), (errno.EMFILE, True)])
def test_keyctl_echec_de_lancement_classe_par_errno(rt, monkeypatch, code, usable):
    """Seuls ENOENT, EACCES, ENOEXEC, ENOTDIR, ELOOP et ENAMETOOLONG disent « keyctl inutilisable » (repli fichier) ; une erreur
    transitoire du système (EAGAIN, ENOMEM…) n'est pas « pas de session » : keyring illisible."""
    def boom(*a, **k):
        raise OSError(code, os.strerror(code))
    monkeypatch.setattr(session_mod.subprocess, "run", boom)
    s = SessionStore(keyctl="keyctl", runtime_dir=str(rt))
    if not usable:
        assert s.get() is None
        return
    with pytest.raises(SessionStoreError, match="^session illisible : keyctl %s" % os.strerror(code)):
        s.get()
    file_session(rt)
    assert s.get() == TOK


def test_keyctl_illisible_retenu_par_instance(rt, tmp_path, monkeypatch):
    """Une fois le keyring vu illisible, les lectures suivantes de cette instance ne rappellent pas
    keyctl (pas de nouveau délai à chaque lecture, `ensure` tourne à chaque connexion)."""
    monkeypatch.setenv(session_mod.TIMEOUT_VAR, "0.4")
    log = tmp_path / "appels"
    s = SessionStore(keyctl=fake_keyctl(tmp_path, "search", "sleep", log=str(log)), runtime_dir=str(rt))
    assert s.timeout == 0.4
    t = time.monotonic()
    for _ in range(5):
        with pytest.raises(SessionStoreError, match="session illisible"):
            s.get()
    assert time.monotonic() - t < 3
    assert log.read_text().split() == ["search"], "un seul appel à keyctl"
    # une autre instance (autre commande) relit
    with pytest.raises(SessionStoreError):
        SessionStore(keyctl=s.keyctl, runtime_dir=str(rt)).get()
    assert log.read_text().split() == ["search", "search"]


def test_keyctl_delai_depuis_l_environnement(monkeypatch):
    for raw, want in (("0.25", 0.25), ("3", 3.0), ("600", 600.0), ("", 10.0)):
        monkeypatch.setenv(session_mod.TIMEOUT_VAR, raw)
        assert SessionStore(keyctl="keyctl", runtime_dir="").timeout == want, raw
    monkeypatch.delenv(session_mod.TIMEOUT_VAR)
    assert SessionStore(keyctl="keyctl", runtime_dir="").timeout == 10.0
    for raw in ("nan", "inf", "-inf", "0", "-1", "601", "abc"):
        monkeypatch.setenv(session_mod.TIMEOUT_VAR, raw)
        with pytest.raises(ValueError, match="^SSHVAULT_KEYCTL_TIMEOUT invalide : %r" % raw):
            SessionStore(keyctl="keyctl", runtime_dir="")


@pytest.mark.parametrize("raw", ["nan", "inf", "0", "601"])
@pytest.mark.parametrize("args", [("list",), ("status",), ("ensure", "--id", "11111111-1111-4111-8111-111111111111")])
def test_keyctl_delai_invalide_code_2(bench, raw, args):
    """Comme les autres délais : valeur invalide = code 2 (message d'une ligne), rien d'autre fait."""
    r = bench.run(*args, env={"SSHVAULT_KEYCTL_TIMEOUT": raw})
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "SSHVAULT_KEYCTL_TIMEOUT invalide : %r (secondes, entre 0 exclu et 600)" % raw in r.stderr, r.stderr
    assert len(bench.calls()) == 0, "bw jamais lancé"


def test_put_apres_keyring_illisible_ecrit_le_fichier_seul(rt, tmp_path):
    """Keyring vu illisible : `put` ne touche pas au keyring et n'efface pas le fichier (sinon la
    lecture suivante serait « illisible ») ; le fichier porte la nouvelle session. Aucun appel qui
    atteindrait le vrai @u : la lecture échoue avant, `padd` ne doit jamais être lancé."""
    log = tmp_path / "appels"
    s = SessionStore(keyctl=fake_keyctl(tmp_path, "search", "Permission denied", log=str(log)), runtime_dir=str(rt))
    with pytest.raises(SessionStoreError, match="session illisible"):
        s.get()
    assert s.keyring_unreadable
    old = file_session(rt)
    new = "bm91dmVsbGUtc2Vzc2lvbi0wMTIzNDU2Nzg5"
    assert s.put(new, 60) == "file" and s.last_backend == "file"
    assert (rt / "sshvault" / "session").exists() and s.get() == new != old
    assert log.read_text().split() == ["search"], "keyring non écrit"


def test_put_apres_keyring_illisible_sans_fichier_possible(tmp_path):
    s = SessionStore(keyctl=fake_keyctl(tmp_path, "search", "Permission denied"), runtime_dir="")
    with pytest.raises(SessionStoreError):
        s.get()
    with pytest.raises(SessionStoreError, match="keyring illisible .*session illisible.*repli fichier impossible"):
        s.put(TOK, 60)


# --- CLI : lock, logout, unlock, deux comptes ----------------------------------------------------

def broken_search(tmp_path, desc=None, name="keyctl-search"):
    return fake_keyctl(tmp_path, "search", "Permission denied", name=name, desc=desc)


def test_cli_lock_keyctl_en_panne(bench, tmp_path):
    """`lock` : keyctl ne dit pas où est la session : « la session peut rester dans le keyring », code 4 ;
    la session rangée est intacte, bw est verrouillé quand même."""
    if not bench.ring:
        pytest.skip("pas de session keyring dédiée")
    tok = bench.unlocked("keyring")
    r = bench.run("lock", env={"SSHVAULT_KEYCTL": broken_search(tmp_path)})
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "session illisible : keyctl" in r.stderr and "la session peut rester dans le keyring" in r.stderr, r.stderr
    assert "session oubliée" not in r.stdout
    assert bench.stored_session() == (tok, None)


def test_cli_logout_keyctl_en_panne(bench, tmp_path):
    """`logout` : bw est déconnecté, mais la session n'a pas pu être retirée : dit, code 4."""
    if not bench.ring:
        pytest.skip("pas de session keyring dédiée")
    tok = bench.unlocked("keyring")
    r = bench.run("logout", env={"SSHVAULT_KEYCTL": broken_search(tmp_path)})
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "session non oubliée" in r.stderr and "la session peut rester dans le keyring" in r.stderr, r.stderr
    assert "session oubliée" not in r.stdout
    assert bench.stored_session() == (tok, None)
    r = bench.run("status")  # keyctl rétabli
    assert "bw" in r.stdout


def test_cli_unlock_keyctl_en_panne_range_dans_le_fichier(bench, tmp_path):
    """`unlock` avec un keyring illisible et aucune session dans le fichier : déverrouille quand même
    (session rangée dans le fichier), au lieu de « session illisible » jusqu'à l'expiration de la clé."""
    if not bench.ring:
        pytest.skip("pas de session keyring dédiée")  # jamais le @u réel
    bench.set_state(logged_in=True)
    env = {"SSHVAULT_KEYCTL": broken_search(tmp_path), "SSHVAULT_KEYRING": bench.ring}
    r, tty = bench.run_tty("unlock", answer=PASSWORD, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr, tty)
    assert "coffre déverrouillé" in r.stdout and "session non rangée" not in r.stdout, r.stdout
    assert "session 900s, file, keyring illisible" in r.stdout, r.stdout
    k, f = bench.stored_session()
    assert k is None and f is not None, "fichier seul, keyring non écrit"
    # keyctl rétabli : la session du fichier sert (aucune invite)
    r = bench.run("--nointeraction", "list")
    assert r.returncode == 0, r.stderr


def test_cli_deux_comptes_un_keyctl_casse(bench, tmp_path):
    """Un compte dont la lecture du keyring échoue ne bloque pas l'autre : `lock` verrouille alice et
    dit l'erreur de boulot (code 4, sa session reste) ; `list` dit « session illisible » pour boulot."""
    from bench import ssh_item
    if not bench.ring:
        pytest.skip("pas de session keyring dédiée")
    tok_a = bench.unlocked("keyring")
    items = [ssh_item("bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb", "Cible B", bench.keys["bastion"], hosts="b,bpc")]
    bench.add_account("boulot", "bob@example.test", items=items, unlocked=True, where="keyring", default=True)
    tok_b = bench.stored_session("boulot")[0]
    assert tok_a and tok_b
    env = {"SSHVAULT_KEYCTL": broken_search(tmp_path, desc="sshvault:session:boulot")}
    r = bench.run("--nointeraction", "list", env=env)
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "boulot : magasin de session : session illisible : keyctl" in r.stderr, r.stderr
    assert "Serveur Prod" in r.stdout, "les clés d'alice sont listées"
    assert "verrouillé" not in r.stderr
    r = bench.run("lock", env=env)
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "boulot : magasin de session : session illisible : keyctl" in r.stderr
    assert "la session peut rester dans le keyring" in r.stderr
    assert r.stdout.count("coffre verrouillé, session oubliée") == 1 and "alice" not in r.stderr
    assert bench.stored_session("alice") == (None, None)
    assert bench.stored_session("boulot") == (tok_b, None), "session de boulot intacte"


def test_cli_unlock_keyring_illisible_vieille_cle_ne_masque_pas_la_session_neuve(bench, tmp_path):
    """Une vieille clé du keyring (session que bw refuse désormais) ne passe pas devant la session neuve
    du fichier : la lecture suivante sert la neuve, rien n'est purgé."""
    if not bench.ring:
        pytest.skip("pas de session keyring dédiée")
    old = bench.unlocked("keyring")
    env = {"SSHVAULT_KEYCTL": broken_search(tmp_path)}
    r, tty = bench.run_tty("unlock", answer=PASSWORD, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr, tty)
    k, f = bench.stored_session()
    assert k == old and f and f != old, "vieille clé gardée dans le keyring, session neuve dans le fichier"
    assert bench.bw_session() == f, "bw ne connaît que la neuve"
    r = bench.run("--nointeraction", "list")  # keyctl rétabli : le fichier d'abord
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert bench.stored_session() == (old, f), "session neuve toujours là, rien purgé"

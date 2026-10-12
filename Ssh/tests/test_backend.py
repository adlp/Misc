"""Modèle SshKeyItem, hôtes (champ sshvault-hosts), recherche par hôte/nom/empreinte,
lecture des éléments bw, get_private_key et lock."""
import pytest

from sshvault.backend import BackendError

from sshvault.backend import ItemNotFound, SshKeyItem, normalize_fingerprint, parse_hosts
from sshvault.bw import BwBackend, last_line, one_line


@pytest.mark.parametrize("value,expected", [
    ("a,b", ("a", "b")),
    (" a , B ,, c ,", ("a", "B", "c")),
    ("", ()),
    (None, ()),
    ("Host,host,HOST", ("Host",)),
])
def test_parse_hosts(value, expected):
    assert parse_hosts(value) == expected


def item(**kw):
    d = dict(id="1", name="Serveur Prod", public_key="ssh-ed25519 AAAA", fingerprint="SHA256:Ab/c+d",
             hosts=("prod.example.com", "*.Lab.example"))
    d.update(kw)
    return SshKeyItem(**d)


def test_match_host():
    i = item()
    assert i.match_host("PROD.example.com")
    assert i.match_host("prod.*")
    assert i.match_host("*.lab.example")
    assert i.match_host("x.LAB.example"), "hôte associé en glob : couvre le nom cherché"
    assert not i.match_host("x.lab.example.org")
    lit = item(hosts=("h[1]",))
    assert not lit.match_host("h1"), "un hôte littéral avec [ n'est pas un motif"
    assert item(hosts=("h?.lab",)).match_host("h1.lab")
    assert not i.match_host("prod")
    assert not item(hosts=()).match_host("*")


def test_match_name():
    assert item().match_name("prod")
    assert item().match_name("SERVEUR P")
    assert not item().match_name("web")


def test_match_fingerprint():
    i = item()
    assert i.match_fingerprint("SHA256:Ab/c+d")
    assert i.match_fingerprint("Ab/c+d")
    assert i.match_fingerprint("sha256:Ab/c+d")
    assert not i.match_fingerprint("ab/c+d")
    assert not i.match_fingerprint("Ab/c+")
    assert not i.match_fingerprint("")
    assert normalize_fingerprint(" SHA256:x ") == "x"


def test_to_dict_sans_cle_privee():
    assert set(item().to_dict()) == {"account", "id", "name", "fingerprint", "hosts", "forward", "publicKey"}


def test_item_bw():
    d = {"id": "x", "type": 5, "name": "n",
         "sshKey": {"privateKey": "PRIV", "publicKey": "PUB", "keyFingerprint": "SHA256:f"},
         "fields": [{"name": "sshvault-hosts", "value": "a, b", "type": 0},
                    {"name": "sshvault-hosts", "value": "B,c", "type": 1},
                    {"name": "sshvault-hosts", "value": "lien", "type": 3},
                    {"name": "autre", "value": "z", "type": 0}]}
    it = BwBackend._item(d)
    assert it == SshKeyItem("x", "n", "PUB", "SHA256:f", ("a", "b", "c"))
    assert "PRIV" not in repr(it)


@pytest.mark.parametrize("d", [
    {"type": 1, "name": "login"},
    {"type": 5, "name": "sans sshKey"},
    {"type": 5, "sshKey": None},
    "pas un dict",
    None,
])
def test_item_bw_ignore(d):
    assert BwBackend._item(d) is None


def test_one_line():
    err = ('Could not find dir, "/x"; creating it instead.\n'
           '\x1b[91mVault is locked.\x1b[39m\n')
    assert one_line(err) == "Vault is locked."
    assert len(one_line("x" * 1000)) == 300


def test_last_line_mauvais_mot_de_passe_mesure():
    err = ("ERROR bitwarden_crypto::keys::master_key: error=The decryption operation failed\n\n"
           "ERROR bitwarden_core::client::internal: error=Cryptography error, The decryption operation failed\n\n"
           "Cryptography error, The decryption operation failed")
    assert last_line(err) == "Cryptography error, The decryption operation failed"
    assert last_line("") == ""


@pytest.fixture
def backend(bench, monkeypatch):
    from sshvault.session import SessionStore
    for k, v in bench.env.items():
        if k.startswith(("FAKE_BW_", "SSHVAULT_KEYCTL", "SSHVAULT_KEYRING")):
            monkeypatch.setenv(k, v)
    bench.unlocked("file")
    from bench import ALIAS
    store = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(bench.runtime), alias=ALIAS)
    return BwBackend(store=store, exe=str(bench.bw), appdata=str(bench.appdata), timeout=30)


def test_get_private_key(bench, backend):
    from bench import ID_LOGIN, ID_PROD, ssh_item
    assert backend.get_private_key(ID_PROD) == bench.keys["prod"]["private"].encode()
    with pytest.raises(ItemNotFound, match="absent"):
        backend.get_private_key("99999999-9999-4999-8999-999999999999")
    with pytest.raises(ItemNotFound, match="pas une clé SSH"):
        backend.get_private_key(ID_LOGIN)
    vide = dict(bench.keys["perso"], private="")
    bench.items.append(ssh_item("77777777-7777-4777-8777-777777777777", "vide", vide))
    bench.write_vault()
    with pytest.raises(BackendError, match="sans clé privée") as e:
        backend.get_private_key("77777777-7777-4777-8777-777777777777")
    assert not isinstance(e.value, ItemNotFound)


def test_lock_garde_la_premiere_erreur(bench, backend, monkeypatch):
    from sshvault.bw import BwTimeout
    from sshvault.session import SessionStoreError

    def run(*a, **k):
        raise BwTimeout("erreur bw : « bw lock » sans réponse en 1s")

    def clear():
        raise SessionStoreError("magasin en panne")
    monkeypatch.setattr(backend, "_run", run)
    monkeypatch.setattr(backend.store, "clear", clear)
    with pytest.raises(BwTimeout):
        backend.lock()


# --- hôtes : validation, normalisation, champ réécrit (story 4) ----------------------------

from sshvault.backend import InvalidHost, normalize_hosts, valid_host  # noqa: E402
from sshvault.bw import hosts_of, with_hosts  # noqa: E402


@pytest.mark.parametrize("host", ["a", "Prod.Example.COM", "*.lab", "h?st", "a_b-c.d", "*", "10.0.0.1"])
def test_valid_host(host):
    assert valid_host(host)


@pytest.mark.parametrize("host", ["a b", "a,b", "!a", "a%h", 'a"', "u@h", "h:22", "a/b", "a\tb", "a\x00",
                                  "é", "K", "[a]", "", " "])
def test_invalid_host(host):
    assert not valid_host(host)


def test_normalize_hosts():
    assert normalize_hosts(["B.example, a.example", "b.EXAMPLE", "", " c "]) == ("b.example", "a.example", "c")
    assert normalize_hosts([""]) == ()
    with pytest.raises(InvalidHost, match="'a b'"):
        normalize_hosts(["ok", "a b"])


def _item(fields):
    return {"id": "x", "type": 5, "name": "n", "notes": None, "revisionDate": "2026-10-06T10:00:00.000Z",
            "fields": fields, "sshKey": {"privateKey": "PRIV", "publicKey": "ssh-ed25519 AAAA", "keyFingerprint": "SHA256:x"}}


def test_with_hosts_cree_le_champ():
    it = _item(None)
    new = with_hosts(it, ("a", "b"))
    assert new["fields"] == [{"name": "sshvault-hosts", "value": "a,b", "type": 0, "linkedId": None}]
    assert it["fields"] is None, "original non modifié"
    assert {k: v for k, v in new.items() if k != "fields"} == {k: v for k, v in it.items() if k != "fields"}


def test_with_hosts_vide_retire_le_champ_et_garde_une_liste():
    it = _item([{"name": "sshvault-hosts", "value": "a", "type": 0, "linkedId": None}])
    assert with_hosts(it, ())["fields"] == [], "null ferait garder les anciens champs à bw"
    assert with_hosts(_item(None), ()) == _item(None)


def test_with_hosts_fusionne_et_garde_le_reste():
    other = {"name": "note", "value": "v", "type": 0, "linkedId": None}
    boolean = {"name": "sshvault-hosts", "value": "true", "type": 2, "linkedId": None}
    it = _item([{"name": "sshvault-hosts", "value": "A", "type": 1, "linkedId": None}, other,
                {"name": "sshvault-hosts", "value": "b", "type": 0, "linkedId": None}, boolean])
    assert hosts_of(it) == ("a", "b")
    new = with_hosts(it, ("a", "c"))
    assert new["fields"] == [{"name": "sshvault-hosts", "value": "a,c", "type": 1, "linkedId": None}, other, boolean]
    assert hosts_of(new) == ("a", "c")


def test_with_hosts_identique_rien_a_ecrire():
    it = _item([{"name": "sshvault-hosts", "value": "a,b", "type": 0, "linkedId": None}])
    assert with_hosts(it, ("a", "b")) == it


def test_set_hosts_renvoie_l_element_relu(bench, backend):
    from bench import ID_PROD
    got = backend.set_hosts(ID_PROD, ["x.example", "Prod.Example.com"])
    assert got.id == ID_PROD and got.hosts == ("x.example", "prod.example.com")
    with pytest.raises(InvalidHost):
        backend.set_hosts(ID_PROD, ["a b"])
    assert not [c for c in bench.calls() if "edit" in c["argv"][1:2]][1:], "un seul edit"


# --- set_hosts : interruption, relecture en échec après edit, null et "" ---------------------

def test_set_hosts_interrompu_entre_edit_et_relecture(bench, backend, monkeypatch):
    from bench import ID_PROD
    real = backend.get_item
    n = {"get": 0}

    def get_item(iid, prompt=None):
        n["get"] += 1
        if n["get"] == 2:
            raise KeyboardInterrupt
        return real(iid, prompt)
    monkeypatch.setattr(backend, "get_item", get_item)
    with pytest.raises(KeyboardInterrupt):
        backend.set_hosts(ID_PROD, ["x.example"])
    assert backend.warnings == ["hôtes de « Serveur Prod » : écriture peut-être passée : vérifier par "
                                "« sshvault sync » puis « sshvault hosts list --id %s »" % ID_PROD]
    assert [c["argv"][1] for c in bench.calls()].count("edit") == 1


def test_set_hosts_relecture_impossible_apres_edit(bench, backend, monkeypatch):
    from bench import ID_PROD
    from sshvault.backend import WriteFailed
    real = backend.get_item
    n = {"get": 0}

    def get_item(iid, prompt=None):
        n["get"] += 1
        if n["get"] == 2:
            raise BackendError("erreur bw (get item, code 1) : Unexpected error.")
        return real(iid, prompt)
    monkeypatch.setattr(backend, "get_item", get_item)
    with pytest.raises(WriteFailed, match="bw edit a réussi, relecture impossible .* état inconnu, vérifier par"):
        backend.set_hosts(ID_PROD, ["x.example"])


def test_is_written_null_et_vide_confondus():
    from sshvault.bw import _is_written
    before = _item([{"name": "note", "value": None, "type": 0, "linkedId": None}])
    after = with_hosts(_item([{"name": "note", "value": "", "type": 0, "linkedId": None}]), ("a",))
    after["notes"] = ""
    assert _is_written(after, before, ("a",))


# --- logout (story 11) -------------------------------------------------------------------

def _store_has(backend):
    return backend.store.get() is not None


def test_logout_deconnecte_et_oublie_la_session(bench, backend):
    assert _store_has(backend)
    assert backend.logout() is True
    assert not bench.state().get("userId") and not _store_has(backend) and backend.warnings == []


def test_logout_dossier_absent_bw_non_lance(bench, backend, monkeypatch, tmp_path):
    backend.appdata = str(tmp_path / "absent" / "bw")
    monkeypatch.setattr(backend, "_run", lambda *a, **k: pytest.fail("bw lancé"))
    assert backend.logout() is False
    assert not (tmp_path / "absent").exists() and not _store_has(backend)


def test_logout_non_connecte(bench, backend):
    bench.set_state(logged_in=False)
    assert backend.logout() is False
    assert not _store_has(backend)


def test_logout_bw_en_erreur(bench, backend, monkeypatch):
    monkeypatch.setenv("FAKE_BW_FAIL", "logout=error")
    with pytest.raises(BackendError, match="logout"):
        backend.logout()
    assert bench.state().get("userId") and not _store_has(backend)
    assert backend.warnings == []


def test_logout_exception_de_run_session_oubliee(bench, backend, monkeypatch):
    def run(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(backend, "_run", run)
    with pytest.raises(KeyboardInterrupt):
        backend.logout()
    assert not _store_has(backend)


def test_logout_magasin_en_panne_avertissement(bench, backend, monkeypatch):
    from sshvault.session import SessionStoreError

    def clear():
        raise SessionStoreError("magasin en panne")
    monkeypatch.setattr(backend.store, "clear", clear)
    assert backend.logout() is True
    assert backend.warnings == ["session non oubliée : magasin en panne"]


def test_logout_magasin_en_panne_et_bw_en_erreur_sans_avertissement(bench, backend, monkeypatch):
    from sshvault.session import SessionStoreError

    def clear():
        raise SessionStoreError("magasin en panne")
    monkeypatch.setattr(backend.store, "clear", clear)
    monkeypatch.setenv("FAKE_BW_FAIL", "logout=error")
    with pytest.raises(BackendError):
        backend.logout()
    assert backend.warnings == [], "une seule ligne : l'appelant dit l'état de la session"


@pytest.mark.parametrize("after,expect", [("unauthenticated", True), ("locked", "timeout"), ("error", "unknown")])
def test_logout_delai_etat_relu(bench, backend, monkeypatch, after, expect):
    """bw tué sur délai : l'état relu tranche (déconnecté quand même, toujours connecté, inconnu)."""
    from sshvault.backend import VaultStatus
    from sshvault.bw import BwTimeout, LogoutUnknown

    def run(*a, **k):
        raise BwTimeout("erreur bw : « bw logout » sans réponse en 1s")

    def status(session, timeout=None):
        assert timeout is not None and timeout <= 10, "relecture à délai court"
        if after == "error":
            raise BackendError("erreur bw (status, code 1) : Unexpected error.")
        return VaultStatus(after, None, None, None)
    monkeypatch.setattr(backend, "_run", run)
    monkeypatch.setattr(backend, "_bw_status", status)
    if expect is True:
        assert backend.logout() is True
    elif expect == "timeout":
        with pytest.raises(BwTimeout) as e:
            backend.logout()
        assert not isinstance(e.value, LogoutUnknown)
    else:
        with pytest.raises(LogoutUnknown, match="état relu impossible"):
            backend.logout()
    assert not _store_has(backend)


def test_login_apikey_autre_compte_oublie_la_session(bench, monkeypatch):
    """`login --apikey` avec la clé API d'un autre compte : déconnecté, session existante oubliée."""
    from bench import ALIAS
    from sshvault.session import SessionStore
    for k, v in bench.env.items():
        if k.startswith(("FAKE_BW_", "SSHVAULT_KEYCTL", "SSHVAULT_KEYRING")):
            monkeypatch.setenv(k, v)
    monkeypatch.setenv("BW_CLIENTID", "user.aaaa")
    monkeypatch.setenv("BW_CLIENTSECRET", "apisecret")
    bench.set_state(logged_in=False)
    store = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(bench.runtime), alias=ALIAS)
    store.put("c2Vzc2lvbi1hbmNpZW5uZS0xMjM0NTY3ODkw", 900)
    assert store.get()
    b = BwBackend(store=store, exe=str(bench.bw), appdata=str(bench.appdata), timeout=30,
                  email="bob@example.test", label="boulot")
    with pytest.raises(BackendError, match="pas de bob@example.test.*déconnecté"):
        b.login(apikey=True)
    assert not bench.state().get("userId") and store.get() is None


def test_logout_interrompu_pendant_la_relecture(bench, backend, monkeypatch):
    """Interruption pendant la relecture d'état après un délai : session oubliée quand même."""
    from sshvault.bw import BwTimeout

    def run(*a, **k):
        raise BwTimeout("erreur bw : « bw logout » sans réponse en 1s")

    def status(session, timeout=None):
        raise KeyboardInterrupt
    monkeypatch.setattr(backend, "_run", run)
    monkeypatch.setattr(backend, "_bw_status", status)
    with pytest.raises(KeyboardInterrupt):
        backend.logout()
    assert not _store_has(backend)

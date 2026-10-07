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
    assert set(item().to_dict()) == {"id", "name", "fingerprint", "hosts", "publicKey"}


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
    store = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(bench.runtime))
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

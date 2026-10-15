"""Fichier des comptes de test d'intégration (`tests/integration/accounts.py`) : lecture et
contrôles, sans réseau ni vrai fichier (HOME et chemins temporaires). Aucune valeur du fichier
(serveur, e-mail, mot de passe) ne doit apparaître dans un message d'erreur."""
import errno
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "integration"))
import accounts as it  # noqa: E402

SECRETS = ("https://Vault-ZQX.example.org", "Zorglub.Secret@Example.org", "mot-de-passe-KJH42",
           "https://autre-WVB.example.net/", "second-PMN@example.net", "passe-deux-TRE",
           "ca-RTY.pem", "vault-zqx", "autre-wvb")
#: certificat commun : fichier créé par la fixture `ca` (HOME de test)
VALID = '''
node_extra_ca_certs = "~/ca-RTY.pem"

[[account]]
server = "https://Vault-ZQX.example.org"
email = "Zorglub.Secret@Example.org"
password = "mot-de-passe-KJH42"

[[account]]
server = "https://Vault-ZQX.example.org"
email = "second-PMN@example.net"
password = "passe-deux-TRE"

[[account]]
server = "https://autre-WVB.example.net/"
email = "Zorglub.Secret@Example.org"
password = "mot-de-passe-KJH42"
'''


@pytest.fixture(autouse=True)
def ca(tmp_path, monkeypatch):
    """HOME de test avec le certificat de VALID (`~/ca-RTY.pem`, `~` développé par le lecteur)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    f = tmp_path / "ca-RTY.pem"
    f.write_text("-----BEGIN CERTIFICATE-----\n")
    return str(f)


def error_of(text):
    with pytest.raises(it.AccountsError) as e:
        it.parse(text)
    msg = str(e.value)
    for s in SECRETS:
        assert s.lower() not in msg.lower(), "valeur du fichier dans le message"
    return msg


def test_trois_comptes_valides(ca):
    """Matrice : 3 [[account]] valides → it, it2, it3 dans l'ordre du fichier ; certificat commun
    (`~` développé)."""
    found, extra = it.parse(VALID.encode())
    assert [a["email"] for a in found] == ["Zorglub.Secret@Example.org", "second-PMN@example.net",
                                           "Zorglub.Secret@Example.org"]
    assert found[2] == {"server": "https://autre-WVB.example.net/", "email": "Zorglub.Secret@Example.org",
                        "password": "mot-de-passe-KJH42"}
    assert extra == {"NODE_EXTRA_CA_CERTS": ca}
    assert [it.alias(n) for n in range(len(found))] == ["it", "it2", "it3"]


def test_un_compte_sans_certificat():
    found, extra = it.parse('[[account]]\nserver = " https://s.example "\nemail = " e@x.example "\n'
                            'password = " p "\n')
    assert found == [{"server": "https://s.example", "email": "e@x.example", "password": " p "}], \
        "serveur et e-mail sans espaces autour, mot de passe intact"
    assert extra == {}


@pytest.mark.parametrize("server2,email2", [
    ("https://Vault-ZQX.example.org", "zorglub.secret@example.ORG"),  # matrice : e-mail en casse différente
    ("HTTPS://VAULT-ZQX.EXAMPLE.ORG/", "Zorglub.Secret@Example.org"),  # serveur : casse et / final
    ("https://vault-zqx.example.org:443", " Zorglub.Secret@Example.org "),  # port par défaut, espaces
])
def test_doublon(server2, email2):
    """Matrice : même serveur (sans / final, insensible à la casse) et même e-mail (insensible
    à la casse) : échec, numéros des deux comptes, aucune valeur affichée."""
    text = VALID + '\n[[account]]\nserver = "%s"\nemail = "%s"\npassword = "x"\n' % (server2, email2)
    msg = error_of(text)
    assert "comptes 1 et 4" in msg and "doublon" in msg, msg


def test_champ_manquant():
    """Matrice : compte 2 sans password : « compte 2 : password »."""
    text = VALID.replace('password = "passe-deux-TRE"\n', "")
    msg = error_of(text)
    assert "compte 2 : password manquant" in msg, msg
    assert "compte 1" not in msg and "compte 3" not in msg


@pytest.mark.parametrize("old,new,want", [
    ('password = "passe-deux-TRE"', 'password = "   "', "compte 2 : password vide"),
    ('password = "passe-deux-TRE"', "password = 42", "compte 2 : password : chaîne attendue"),
    ('email = "second-PMN@example.net"', 'email = ["second-PMN@example.net"]', "compte 2 : email : chaîne attendue"),
    ('password = "passe-deux-TRE"', 'password = "passe-deux-TRE"\npasword = "mot-de-passe-KJH42"',
     "compte 2 : clé inconnue : pasword"),
    ('node_extra_ca_certs = "~/ca-RTY.pem"', "node_extra_ca_certs = true", "node_extra_ca_certs : chaîne attendue"),
    ('node_extra_ca_certs = "~/ca-RTY.pem"', 'node_extra_ca_certs = ""', "node_extra_ca_certs : vide"),
    ('node_extra_ca_certs = "~/ca-RTY.pem"', 'node_extra_ca_certs = "~/absent-ca-RTY.pem"',
     "node_extra_ca_certs : fichier ordinaire absent"),
    ('node_extra_ca_certs = "~/ca-RTY.pem"', 'node_extra_ca_certs = "~"', "node_extra_ca_certs : fichier ordinaire absent"),
    ('node_extra_ca_certs = "~/ca-RTY.pem"', 'serveur = "https://Vault-ZQX.example.org"',
     "clé inconnue au premier niveau : serveur"),
    ('server = "https://autre-WVB.example.net/"', 'server = "ftp://autre-WVB.example.net/"',
     "compte 3 : server invalide"),
    ('server = "https://autre-WVB.example.net/"', 'server = "https://user@autre-WVB.example.net/"',
     "compte 3 : server invalide"),
    ('email = "second-PMN@example.net"', 'email = "second-PMN example.net"', "compte 2 : email invalide"),
])
def test_cle_inconnue_vide_type_faux(old, new, want):
    assert old in VALID
    msg = error_of(VALID.replace(old, new, 1))
    assert want in msg, msg


@pytest.mark.parametrize("text", ["", 'node_extra_ca_certs = "~/ca-RTY.pem"\n', "account = []\n",
                                  'account = "Zorglub.Secret@Example.org"\n', "account = [1, 2]\n"])
def test_aucun_compte(text):
    msg = error_of(text)
    assert "aucun compte" in msg or "tableau de tables" in msg, msg


@pytest.mark.parametrize("text", [
    '[[account]]\nserver = "https://Vault-ZQX.example.org"\nemail = "Zorglub.Secret@Example.org"\n'
    'password = "mot-de-passe-KJH42\n',  # chaîne non fermée
    '[[account]]\nserver = https://Vault-ZQX.example.org\n',  # valeur sans guillemets
    '[[account]]\nserver = "https://Vault-ZQX.example.org"\nserver = "https://autre-WVB.example.net/"\n',  # clé doublée
])
def test_toml_illisible_ligne_et_colonne_seulement(text):
    """Matrice : TOML illisible : ligne et colonne seulement, jamais le message du lecteur
    (qui peut citer le texte)."""
    msg = error_of(text)
    assert re.fullmatch(r"fichier des comptes : TOML illisible \(ligne \d+, colonne \d+\)", msg), msg


def test_utf8_invalide():
    msg = error_of(b'[[account]]\nserver = "\xff"\n')
    assert "UTF-8" in msg


def test_position_sans_attributs():
    """Python 3.11-3.13 : TOMLDecodeError sans lineno/colno : position lue dans le suffixe."""
    assert it._position(ValueError('Invalid value "x" (at line 3, column 9)')) == "ligne 3, colonne 9"
    assert it._position(ValueError("Unclosed array (at end of document)")) == "position inconnue"


def test_fichier_absent_saute(tmp_path):
    path, why = it.locate({}, str(tmp_path))
    assert path is None and str(tmp_path / ".config" / "sshvault-test" / "accounts.toml") in why
    assert "account.env" not in why


def test_fichier_absent_account_env_present(tmp_path):
    """Matrice : accounts.toml absent, account.env présent (ancien format, jamais lu) :
    intégration sautée, message vers accounts.toml."""
    d = tmp_path / ".config" / "sshvault-test"
    d.mkdir(parents=True)
    (d / "account.env").write_text("SSHVAULT_IT_PASSWORD=mot-de-passe-KJH42\n")
    path, why = it.locate({}, str(tmp_path))
    assert path is None
    assert "account.env" in why and "n'est plus lu" in why and "accounts.toml" in why
    assert it.EXAMPLE in why and "mot-de-passe" not in why


def test_chemin_par_variable(tmp_path):
    f = tmp_path / "ailleurs.toml"
    f.write_text(VALID)
    assert it.locate({"SSHVAULT_IT_ACCOUNTS": str(f)}, str(tmp_path)) == (str(f), None)
    d = tmp_path / ".config" / "sshvault-test"
    d.mkdir(parents=True)
    (d / "accounts.toml").write_text(VALID)
    assert it.locate({}, str(tmp_path)) == (str(d / "accounts.toml"), None)
    os.chmod(str(d / "accounts.toml"), 0o600)
    found, extra, notes = it.load(str(d / "accounts.toml"))
    assert len(found) == 3 and notes == []


KINDS = {"absent": "absent", "dossier": "pas un fichier ordinaire", "fifo": "pas un fichier ordinaire",
         "lien-casse": "lien cassé", "interdit": os.strerror(errno.EACCES)}


def _make(target, kind):
    """Chemin `target` de la sorte `kind` ; « interdit » : fichier dans un dossier 0000."""
    if kind == "dossier":
        target.mkdir()
    elif kind == "fifo":
        os.mkfifo(str(target))
    elif kind == "lien-casse":
        target.symlink_to(target.parent / "nulle-part.toml")
    elif kind == "interdit":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(VALID)
        target.parent.chmod(0)


@pytest.mark.parametrize("kind", list(KINDS))
def test_chemin_par_variable_invalide_echoue(tmp_path, kind):
    """SSHVAULT_IT_ACCOUNTS vers un chemin absent, un lien cassé, autre chose qu'un fichier
    ordinaire ou un chemin illisible : échec de la session (AccountsError : chemin et vraie
    raison nommés, aucune valeur), jamais un saut, même si le fichier par défaut existe ;
    variable absente (ou vide) et fichier par défaut absent : saut."""
    d = tmp_path / ".config" / "sshvault-test"
    d.mkdir(parents=True)
    (d / "accounts.toml").write_text(VALID)
    target = tmp_path / "sous" / "cible.toml" if kind == "interdit" else tmp_path / "cible.toml"
    _make(target, kind)
    try:
        if kind == "interdit" and os.access(str(target), os.R_OK):
            pytest.skip("lisible malgré 0000 (root)")
        with pytest.raises(it.AccountsError) as e:
            it.locate({"SSHVAULT_IT_ACCOUNTS": str(target)}, str(tmp_path))
    finally:
        if kind == "interdit":
            target.parent.chmod(0o700)
    msg = str(e.value)
    assert str(target) in msg and "SSHVAULT_IT_ACCOUNTS" in msg and KINDS[kind] in msg, msg
    assert sum(r in msg for r in set(KINDS.values())) == 1, msg
    assert not any(v.lower() in msg.lower() for v in SECRETS), msg
    os.unlink(str(d / "accounts.toml"))
    for env in ({}, {"SSHVAULT_IT_ACCOUNTS": ""}):
        path, why = it.locate(env, str(tmp_path))
        assert path is None and str(d / "accounts.toml") in why


def test_chemin_par_variable_tilde(tmp_path):
    """`~` de SSHVAULT_IT_ACCOUNTS développé (HOME de test) ; absent : le chemin développé est nommé."""
    f = tmp_path / "comptes.toml"
    f.write_text(VALID)
    assert it.locate({"SSHVAULT_IT_ACCOUNTS": "~/comptes.toml"}, str(tmp_path)) == (str(f), None)
    with pytest.raises(it.AccountsError) as e:
        it.locate({"SSHVAULT_IT_ACCOUNTS": "~/autre.toml"}, str(tmp_path))
    assert str(tmp_path / "autre.toml") in str(e.value) and "absent" in str(e.value)


@pytest.mark.parametrize("kind", ["dossier", "fifo", "lien-casse", "interdit"])
def test_fichier_par_defaut_inutilisable_echoue(tmp_path, kind):
    """Fichier par défaut présent sans être un fichier ordinaire utilisable : échec (chemin et
    raison nommés), jamais un saut « absent »."""
    target = tmp_path / ".config" / "sshvault-test" / "accounts.toml"
    target.parent.mkdir(parents=True)
    _make(target, kind)
    try:
        if kind == "interdit" and os.access(str(target), os.R_OK):
            pytest.skip("lisible malgré 0000 (root)")
        with pytest.raises(it.AccountsError) as e:
            it.locate({}, str(tmp_path))
    finally:
        if kind == "interdit":
            target.parent.chmod(0o700)
    msg = str(e.value)
    assert str(target) in msg and KINDS[kind] in msg and "absent" not in msg, msg


def test_sshvault_it_env_echoue(tmp_path):
    """SSHVAULT_IT_ENV défini (ancien format) : échec qui nomme SSHVAULT_IT_ACCOUNTS, même si
    accounts.toml existe ; le fichier désigné n'est pas lu."""
    d = tmp_path / ".config" / "sshvault-test"
    d.mkdir(parents=True)
    (d / "accounts.toml").write_text(VALID)
    with pytest.raises(it.AccountsError) as e:
        it.locate({"SSHVAULT_IT_ENV": str(tmp_path / "account.env")}, str(tmp_path))
    assert "SSHVAULT_IT_ACCOUNTS" in str(e.value) and "SSHVAULT_IT_ENV" in str(e.value)


def test_fichier_illisible(tmp_path):
    f = tmp_path / "accounts.toml"
    f.write_text(VALID)
    f.chmod(0)
    try:
        if os.access(str(f), os.R_OK):
            pytest.skip("lisible malgré 0000 (root)")
        with pytest.raises(it.AccountsError, match="illisible"):
            it.load(str(f))
    finally:
        f.chmod(0o600)


def test_scrub_de_tous_les_comptes():
    """Valeurs de tous les comptes réunies, la plus longue d'abord : l'e-mail court du compte 1,
    contenu dans celui du compte 2, ne laisse pas ce dernier à moitié visible."""
    a1 = it.Account("https://un.example", "a@x.example", "pw-un")
    a2 = it.Account("https://deux.example", "ba@x.example", "pw-deux")
    s = it.Scrub([a1, a2])
    out = s.scrub("1 a@x.example 2 ba@x.example pw-un pw-deux")
    assert out == "1 <email> 2 <email> <password> <password>", out


def test_scrub_nom_d_hote_seul():
    """bw/Node disent `getaddrinfo ENOTFOUND <hôte>` : le nom d'hôte seul est masqué aussi."""
    a = it.Account("https://Vault-ZQX.example.org:8443/vw", "e@x.example", "pw")
    out = a.scrub("request to https://vault-zqx.example.org:8443/vw failed, reason: getaddrinfo ENOTFOUND "
                  "vault-zqx.example.org")
    assert "vault-zqx" not in out.lower() and out.endswith("ENOTFOUND <server-host>"), out


def test_certificat_relatif_rendu_absolu(tmp_path, monkeypatch):
    """Chemin relatif : rendu absolu (bw tourne depuis un autre dossier)."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "ca.pem").write_text("x")
    monkeypatch.chdir(tmp_path)
    _, extra = it.parse(VALID.replace("~/ca-RTY.pem", "sub/ca.pem"))
    assert extra == {"NODE_EXTRA_CA_CERTS": str(tmp_path / "sub" / "ca.pem")}


def test_certificat_illisible(ca):
    os.chmod(ca, 0)
    try:
        if os.access(ca, os.R_OK):
            pytest.skip("lisible malgré 0000 (root)")
        msg = error_of(VALID)
        assert "node_extra_ca_certs : fichier illisible" in msg, msg
    finally:
        os.chmod(ca, 0o600)


def test_exemple_fourni_valide():
    """`accounts.example.toml` (valeurs factices) passe les contrôles : 2 comptes au moins."""
    example = os.path.join(os.path.dirname(os.path.abspath(__file__)), "integration", "accounts.example.toml")
    found, extra, _ = it.load(example)
    assert len(found) >= 2
    assert all(a["email"].endswith(".invalid") or "example" in a["email"] for a in found)


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o620])
def test_droits_trop_ouverts_avertissement(tmp_path, mode):
    """Fichier lisible par le groupe ou les autres : avertissement seul (sans valeur), lecture
    faite."""
    f = tmp_path / "accounts.toml"
    f.write_text(VALID)
    os.chmod(str(f), mode)
    found, extra, notes = it.load(str(f))
    assert len(found) == 3 and len(notes) == 1
    assert "%04o" % mode in notes[0] and "ouvert au groupe ou aux autres" in notes[0] and "chmod 600" in notes[0]
    assert not any(v.lower() in notes[0].lower() for v in SECRETS)


def test_proprietaire_autre_avertissement(tmp_path):
    f = tmp_path / "accounts.toml"
    f.write_text(VALID)
    os.chmod(str(f), 0o600)
    st = os.stat(str(f))
    assert it.mode_warning(st, str(f)) is None

    class Other:
        st_mode, st_uid = st.st_mode, os.getuid() + 1
    w = it.mode_warning(Other, str(f))
    assert w and "propriétaire uid %d" % (os.getuid() + 1) in w


def test_scrub_serveur_normalise_et_certificat(ca):
    """sshvault affiche le serveur normalisé (hôte en minuscules, sans / final ni port par
    défaut) : masqué aussi, comme le chemin du certificat."""
    a = it.Account("HTTPS://Vault-ZQX.Example.org:443/", "Zorglub.Secret@Example.org", "mot-de-passe-KJH42",
                   {"NODE_EXTRA_CA_CERTS": ca})
    text = ("serveur : https://vault-zqx.example.org ; brut : HTTPS://Vault-ZQX.Example.org:443/ ; "
            "e-mail : zorglub.secret@example.org ; mdp : mot-de-passe-KJH42 ; ca : %s" % ca)
    out = a.scrub(text)
    for v in ("vault-zqx", "Vault-ZQX", "zorglub", "Zorglub", "KJH42", "ca-RTY"):
        assert v not in out, out
    assert repr(a) == "<Account masqué>"

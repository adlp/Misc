"""Plusieurs comptes Vaultwarden (story 10, CAP-10) : une ligne de test par ligne de la matrice
de la story, sur le faux bw multi-serveurs (FAKE_BW_VAULTS : un coffre par compte), les vrais
ssh-agent/ssh-add, et pour les connexions de vrais `ssh` vers trois sshd de test (a, b, c).

Comptes du banc : `alice` (compte par défaut, alice@example.test sur vault.example.test),
`boulot` (même serveur, bob@example.test), `client` (autre serveur, carol@client.test)."""
import json
import os
import shutil
import stat
import subprocess
import sys
import time

import pytest

from bench import (ALIAS, EMAIL, HAVE_OPENSSH, ID_BASTION, ID_PERSO, ID_PROD, PASSWORD, SERVER, make_askpass,
                   pty_run, ssh_item)
from sshvault import sshconfig

ID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
ID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
ID_C = "cccccccc-3333-4333-8333-cccccccccccc"
OTHER = "https://vault.client.test"
SSH = shutil.which("ssh")
SSHD = "/usr/sbin/sshd"
HAVE_LAB = bool(SSH and os.access(SSHD, os.X_OK) and HAVE_OPENSSH)


def one_line_error(r):
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    assert len(lines) == 1, r.stderr
    assert "Traceback" not in r.stderr
    return lines[0]


def where(bench):
    return "keyring" if bench.ring else "file"


def two_accounts(bench, boulot_items=None, unlocked=True, default=True):
    """alice (coffre du banc) et boulot (même serveur), déverrouillés ; tous deux par défaut."""
    bench.unlocked(where(bench))
    items = boulot_items if boulot_items is not None else [
        ssh_item(ID_B, "Cible B", bench.keys["bastion"], hosts="b,bpc")]
    return bench.add_account("boulot", "bob@example.test", items=items, unlocked=unlocked, where=where(bench),
                             default=default)


def config_text(bench):
    return (bench.home / ".ssh" / "sshvault" / "config").read_text()


def registry(bench):
    return json.loads(bench.config_file().read_text())


# --- registre ---------------------------------------------------------------------------

def test_account_add_list_default(bench):
    r = bench.run("account", "add", "perso", "--server", "HTTPS://Vault.X.test/", "--email", " Alice@X.test ")
    assert r.returncode == 0, r.stderr
    assert "compte perso ajouté : https://vault.x.test, alice@x.test, compte par défaut" in r.stdout
    assert "« sshvault login »" in r.stdout, "un seul compte : pas de --account"
    r = bench.run("account", "add", "boulot", "--server", "https://vault.x.test", "--email", "bob@x.test")
    assert r.returncode == 0 and "« sshvault login --account boulot »" in r.stdout, r.stdout
    assert "compte par défaut" not in r.stdout
    r = bench.run("account", "list")
    assert r.stdout.splitlines() == ["boulot\thttps://vault.x.test\tbob@x.test\t-",
                                     "perso\thttps://vault.x.test\talice@x.test\tdéfaut"]
    reg = registry(bench)
    assert reg["accounts"]["perso"] == {"server": "https://vault.x.test", "email": "alice@x.test"}
    assert reg["default-accounts"] == ["perso"]
    assert stat.S_IMODE(bench.config_file().stat().st_mode) == 0o600
    r = bench.run("account", "default", "boulot", "perso", "boulot")
    assert r.returncode == 0 and "comptes par défaut : boulot, perso" in r.stdout
    assert registry(bench)["default-accounts"] == ["boulot", "perso"]
    assert not bench.calls(), "le registre ne lance pas bw"


@pytest.mark.parametrize("args,msg", [
    (["account", "add", "perso", "--server", "https://vault.x.test", "--email", "autre@x.test"], "déjà enregistré"),
    (["account", "add", "autre", "--server", "https://VAULT.x.test/", "--email", "ALICE@x.test"],
     "déjà enregistré sous l'alias « perso »"),
    (["account", "add", "Perso", "--server", "https://vault.x.test", "--email", "z@x.test"], "alias invalide"),
    (["account", "add", "-x", "--server", "https://vault.x.test", "--email", "z@x.test"], ""),
    (["account", "add", "a" * 33, "--server", "https://vault.x.test", "--email", "z@x.test"], "alias invalide"),
    (["account", "add", "z", "--server", "ftp://vault.x.test", "--email", "z@x.test"], "serveur invalide"),
    (["account", "add", "z", "--server", "https://vault.x.test", "--email", "pas-un-email"], "e-mail invalide"),
    (["account", "default", "inconnu"], "compte « inconnu » inconnu"),
    (["account", "remove", "inconnu"], "compte « inconnu » inconnu"),
    (["account", "rename", "perso", "Mauvais"], "alias invalide"),
    (["list", "--account", "inconnu"], "compte « inconnu » inconnu"),
])
def test_account_refus(bench, args, msg):
    """Même alias ajouté deux fois, même couple (serveur, e-mail), alias ou URL invalide, alias
    inconnu : code 2, une ligne, registre inchangé."""
    assert bench.run("account", "add", "perso", "--server", "https://vault.x.test",
                     "--email", "alice@x.test").returncode == 0
    before = bench.config_file().read_bytes()
    r = bench.run(*args)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert msg in one_line_error(r)
    assert bench.config_file().read_bytes() == before


def test_sans_compte(bench):
    """Aucun compte : lecture et login disent comment en ajouter un (code 3, comme non connecté)."""
    for args in (["list"], ["login"], ["unlock"], ["load", "--all"]):
        r = bench.run(*args)
        assert r.returncode == 3, (args, r.stderr)
        assert "account add" in one_line_error(r)
    assert not bench.calls()


# --- lecture : comptes par défaut et --account -------------------------------------------

def test_deux_comptes_meme_serveur_list(bench):
    """Deux comptes sur un serveur, e-mails différents : clés indépendantes, alias en première
    colonne ; --json : clé account."""
    two_accounts(bench)
    r = bench.run("list")
    assert r.returncode == 0, r.stderr
    rows = [l.split("\t") for l in r.stdout.splitlines()]
    # compte par compte (ordre des comptes par défaut), puis par nom
    assert [(a, n) for a, n, *_ in rows] == [("alice", "Bastion RSA"), ("alice", "clé perso"), ("alice", "Serveur Prod"),
                                            ("boulot", "Cible B")]
    data = json.loads(bench.run("list", "--json").stdout)
    assert {(d["account"], d["id"]) for d in data} == {("alice", ID_BASTION), ("alice", ID_PERSO), ("alice", ID_PROD),
                                                       ("boulot", ID_B)}
    # données de bw séparées
    apps = {c["appdata"] for c in bench.calls()}
    assert apps == {str(bench.appdata), str(bench.appdata_of("boulot"))}


def test_account_default_change_list(bench):
    """Critère d'acceptation : comptes par défaut changés par `account default` → la liste
    suivante ne montre que leurs éléments, avec l'alias."""
    two_accounts(bench)
    r = bench.run("account", "default", "boulot")
    assert r.returncode == 0, r.stderr
    r = bench.run("list")
    assert r.returncode == 0 and [l.split("\t")[:2] for l in r.stdout.splitlines()] == [["boulot", "Cible B"]]
    assert all(c["appdata"] == str(bench.appdata_of("boulot")) for c in bench.calls()[-1:])
    r = bench.run("account", "default", "alice")
    r = bench.run("list")
    assert {l.split("\t")[0] for l in r.stdout.splitlines()} == {"alice"}


def test_list_account_remplace_les_defauts(bench):
    two_accounts(bench, default=False)
    bench.add_account("client", "carol@client.test", server=OTHER, unlocked=True, where=where(bench),
                      items=[ssh_item(ID_C, "Client C", bench.keys["perso"], hosts="c")])
    r = bench.run("list", "--account", "client")
    assert r.returncode == 0 and [l.split("\t")[:2] for l in r.stdout.splitlines()] == [["client", "Client C"]]
    r = bench.run("search", "--account", "client", "--account", "boulot", "--host", "*")
    assert sorted(l.split("\t")[0] for l in r.stdout.splitlines()) == ["boulot", "client"]


def test_lecture_un_compte_verrouille(bench):
    """Deux comptes par défaut, l'un verrouillé sans invite : l'autre est listé, une ligne pour le
    verrouillé (alias en tête, --account cité), code 3."""
    two_accounts(bench, unlocked=False)
    r = bench.run("--nointeraction", "list")
    assert r.returncode == 3
    assert {l.split("\t")[0] for l in r.stdout.splitlines()} == {"alice"}
    line = one_line_error(r)
    assert line.startswith("sshvault: boulot : coffre verrouillé") and "sshvault unlock --account boulot" in line


# --- écriture : un seul compte ------------------------------------------------------------

def test_ecriture_plusieurs_defauts_exige_account(bench, tmp_path):
    """`hosts add` sans --account, défauts alice et boulot : rien écrit, code 2, une ligne."""
    two_accounts(bench)
    before = {a: bench.account_vault(a).read_text() for a in ("alice", "boulot")}
    for args in (["hosts", "add", "--id", ID_PERSO, "x.example"], ["forward", "set", "--id", ID_PERSO, "x"],
                 ["generate", "--name", "n"], ["import", str(tmp_path / "absent")]):
        r = bench.run(*args)
        assert r.returncode == 2, (args, r.stderr)
        line = one_line_error(r)
        assert "préciser --account" in line and "alice, boulot" in line, line
    assert not bench.calls(), "rien lancé"
    assert {a: bench.account_vault(a).read_text() for a in before} == before
    # avec --account : écrit dans ce compte seul
    r = bench.run("hosts", "add", "--account", "alice", "--id", ID_PERSO, "x.example")
    assert r.returncode == 0, r.stderr
    assert bench.account_vault("boulot").read_text() == before["boulot"]
    assert "x.example" in json.dumps(bench.vault_item(ID_PERSO))


def test_ecriture_un_seul_defaut(bench):
    two_accounts(bench, default=False)
    r = bench.run("hosts", "add", "--id", ID_PERSO, "y.example")  # défaut : alice seul
    assert r.returncode == 0, r.stderr
    r = bench.run("hosts", "add", "--id", ID_B, "z.example")
    assert r.returncode == 1 and "aucune clé" in one_line_error(r), "boulot n'est pas écrit sans --account"
    r = bench.run("hosts", "add", "--account", "boulot", "--account", "alice", "--id", ID_B, "z.example")
    assert r.returncode == 2 and "un seul compte" in one_line_error(r)


# --- session, verrou, unlock ---------------------------------------------------------------

def test_lock_sans_account_verrouille_tout(bench):
    two_accounts(bench)
    bench.add_account("client", "carol@client.test", server=OTHER, unlocked=True, where=where(bench))
    assert all(bench.stored_session(a) != (None, None) for a in ("alice", "boulot", "client"))
    r = bench.run("lock")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("coffre verrouillé, session oubliée") == 3
    assert all(bench.stored_session(a) == (None, None) for a in ("alice", "boulot", "client"))
    locks = {c["appdata"] for c in bench.calls() if c["argv"][1:] == ["lock"]}
    assert locks == {str(bench.appdata_of(a)) for a in ("alice", "boulot", "client")}


def test_lock_account_un_seul(bench):
    two_accounts(bench)
    assert bench.run("lock", "--account", "boulot").returncode == 0
    assert bench.stored_session("boulot") == (None, None) and bench.stored_session("alice") != (None, None)


def test_unlock_une_invite_par_compte_nommee(bench):
    """unlock sans --account : comptes par défaut, une invite par compte, qui nomme l'alias."""
    bench.set_state(logged_in=True)
    bench.add_account("boulot", "bob@example.test", unlocked=False, default=True)
    r, tty = bench.run_tty("unlock", answer=[PASSWORD, PASSWORD])
    assert r.returncode == 0, (r.stderr, tty)
    assert tty.count("mot de passe maître du coffre") == 2
    assert "« alice »" in tty and "« boulot »" in tty
    assert bench.stored_session("alice")[0 if bench.ring else 1] and bench.stored_session("boulot")[0 if bench.ring else 1]


def test_status_tous_les_comptes(bench):
    two_accounts(bench, unlocked=False, default=False)
    r = bench.run("status")
    assert r.returncode == 3, "un compte verrouillé"
    assert "alias : alice (défaut)" in r.stdout and "alias : boulot\n" in r.stdout
    assert r.stdout.count("coffre : ") == 2 and "bob@example.test" in r.stdout
    r = bench.run("status", "--account", "alice")
    assert r.returncode == 0 and "boulot" not in r.stdout


@pytest.mark.parametrize("default", [True, False])
def test_login_plusieurs_comptes_exige_account(bench, default):
    """Plusieurs comptes : `login` exige --account, même avec un seul compte par défaut."""
    two_accounts(bench, default=default)
    n = len(bench.calls())
    r = bench.run("login")
    assert r.returncode == 2
    line = one_line_error(r)
    assert "préciser --account" in line and "alice, boulot" in line
    assert len(bench.calls()) == n


def test_login_second_compte_meme_serveur(bench):
    """login --account : `bw login <e-mail du compte>` dans ses propres données ; coffre propre."""
    bench.unlocked(where(bench))
    bench.add_account("boulot", "bob@example.test", logged_in=False,
                      items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], hosts="b")])
    p = subprocess.run([sys.executable, "-m", "sshvault", "login", "--account", "boulot"], env=bench.env, input="%s\n" % PASSWORD, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "compte boulot : connecté, coffre déverrouillé" in p.stdout
    login = [c for c in bench.calls() if c["argv"][:1] == ["login"]]
    assert login[0]["argv"][-2:] == ["--", "bob@example.test"] and login[0]["appdata"] == str(bench.appdata_of("boulot"))
    r = bench.run("list", "--account", "boulot")
    assert r.returncode == 0 and r.stdout.startswith("boulot\tCible B\t"), r.stderr


# --- régénération sur tous les comptes -------------------------------------------------------

def test_regeneration_compte_verrouille_blocs_gardes(bench):
    """`hosts add --account alice`, boulot verrouillé sans invite : blocs de boulot gardés tels
    quels, avertissement ; config générée sur les deux comptes."""
    two_accounts(bench)
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    text = config_text(bench)
    assert "# Cible B boulot %s\n" % ID_B in text and "ensure --account boulot --id %s\"" % ID_B in text
    assert "# Serveur Prod alice %s\n" % ID_PROD in text
    boulot_block = text[text.index("# Cible B boulot"):]
    boulot_block = boulot_block[:boulot_block.index("\n\n") + 1 if "\n\n" in boulot_block else len(boulot_block)]
    assert bench.run("lock", "--account", "boulot").returncode == 0
    r = bench.run("--nointeraction", "hosts", "add", "--account", "alice", "--id", ID_PERSO, "perso.example")
    assert r.returncode == 0, r.stderr
    assert "compte boulot illisible" in r.stderr and "gardés tels quels" in r.stderr
    text2 = config_text(bench)
    assert boulot_block in text2, "bloc de boulot gardé à l'identique"
    assert "# clé perso alice %s\nMatch originalhost perso.example exec" % ID_PERSO in text2
    # ssh-config --check : à jour malgré le compte verrouillé (blocs gardés)
    r = bench.run("--nointeraction", "ssh-config", "--check")
    assert "ssh_config généré" not in r.stdout and "à réécrire" not in r.stdout, r.stdout


def test_ssh_config_tous_illisibles_rien_ecrit(bench):
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    before = config_text(bench)
    assert bench.run("lock").returncode == 0
    r = bench.run("--nointeraction", "ssh-config")
    assert r.returncode == 3
    assert config_text(bench) == before


def test_trois_comptes_ssh_config(bench):
    """Trois comptes, deux serveurs : le ssh_config couvre les trois (une ligne Match exec
    `--account` par élément, tri par nom)."""
    two_accounts(bench)
    bench.add_account("client", "carol@client.test", server=OTHER, unlocked=True, where=where(bench),
                      items=[ssh_item(ID_C, "Client C", bench.keys["perso"], hosts="c")])
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    text = config_text(bench)
    for alias, iid in (("alice", ID_PROD), ("boulot", ID_B), ("client", ID_C)):
        assert "ensure --account %s --id %s\"" % (alias, iid) in text
    assert text.index("# Client C client") < text.index("# Serveur Prod alice")


def test_forward_ids_alias(bench):
    """Bloc de transfert qui mêle deux comptes : `--id <alias>:<uuid>` pour chacun."""
    items = [dict(ssh_item(ID_B, "Cible B", bench.keys["bastion"], hosts="b"))]
    items[0]["fields"].append({"name": "sshvault-forward", "value": "relais", "type": 0, "linkedId": None})
    two_accounts(bench, boulot_items=items)
    prod = next(i for i in bench.items if i.get("id") == ID_PROD)
    prod["fields"].append({"name": "sshvault-forward", "value": "relais", "type": 0, "linkedId": None})
    bench.write_vault()
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    line = [l for l in config_text(bench).splitlines() if "--forward" in l][0]
    assert line.endswith(" --id boulot:%s --id alice:%s\"" % (ID_B, ID_PROD)) or \
        line.endswith(" --id alice:%s --id boulot:%s\"" % (ID_PROD, ID_B)), line


# --- adoption d'une installation 0.8.0 -----------------------------------------------------

def legacy_install(bench, session=True):
    """Installation 0.8.0 : données de bw dans sshvault/bw (connecté), pas de registre."""
    d = bench.home / ".local" / "share" / "sshvault" / "bw"
    d.mkdir(parents=True, mode=0o700)
    tok = "c2Vzc2lvbi1sZWdhY3ktMTIzNDU2Nzg5MA=="
    (d / "data.json").write_text(json.dumps({
        "stateVersion": 85, "serverUrl": SERVER, "userId": "aaaaaaaa-0000-4000-8000-000000000001",
        "userEmail": EMAIL, "lastSync": "2026-10-06T00:00:00.000Z", "session": tok if session else None}))
    if session:
        bench.store_session(tok, where(bench), alias=None)
    return d


def test_adoption_installation_existante(bench):
    legacy = legacy_install(bench)
    r = bench.run("status")
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("sshvault: installation 0.8.0 adoptée : compte « alice » "), r.stderr
    assert "compte par défaut" in lines[0] and "account rename alice" in lines[0]
    assert not legacy.exists() and (bench.appdata / "data.json").exists(), "données déplacées"
    reg = registry(bench)
    assert reg["accounts"] == {"alice": {"server": SERVER, "email": EMAIL}} and reg["default-accounts"] == ["alice"]
    assert bench.stored_session(None) == (None, None), "ancienne session oubliée"
    assert r.returncode == 3 and "coffre : verrouillé" in r.stdout, "déverrouillage à refaire"
    r = bench.run("status")
    assert "adoptée" not in r.stderr, "une seule fois"


def test_adoption_alias_deduit_de_l_email(bench):
    legacy_install(bench, session=False)
    st = json.loads((bench.home / ".local/share/sshvault/bw/data.json").read_text())
    st["userEmail"] = "Jean.Dupont+ssh@Example.test"
    (bench.home / ".local/share/sshvault/bw/data.json").write_text(json.dumps(st))
    r = bench.run("account", "list")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("jean-dupont-ssh\t%s\tjean.dupont+ssh@example.test\tdéfaut" % SERVER)
    r = bench.run("account", "rename", "jean-dupont-ssh", "jean")
    assert r.returncode == 0, r.stderr
    assert (bench.home / ".local/share/sshvault/accounts/jean/bw/data.json").exists()
    assert registry(bench)["default-accounts"] == ["jean"]


def test_adoption_deplacement_impossible(bench):
    """Déplacement impossible : rien modifié, code 4."""
    legacy = legacy_install(bench)
    root = legacy.parent
    os.chmod(str(root), 0o500)
    try:
        r = bench.run("list")
    finally:
        os.chmod(str(root), 0o700)
    assert r.returncode == 4
    assert "rien modifié" in one_line_error(r)
    assert (legacy / "data.json").exists() and not (root / "accounts").exists()
    assert not bench.config_file().exists()
    assert bench.stored_session(None) != (None, None), "ancienne session gardée"


def test_adoption_non_connecte(bench):
    """sshvault/bw présent mais non connecté : rien à reprendre, registre vide, dossier laissé."""
    d = bench.home / ".local" / "share" / "sshvault" / "bw"
    d.mkdir(parents=True, mode=0o700)
    r = bench.run("list")
    assert r.returncode == 3 and "account add" in one_line_error(r)
    assert registry(bench) == {"accounts": {}} and d.exists()


def test_ancienne_config_ensure_id(bench):
    """Ancienne config générée (ligne `ensure --id <uuid>`) : clé chargée, compte trouvé par l'id ;
    id introuvable : une ligne."""
    legacy_install(bench)
    bench.items = [ssh_item(ID_A, "Saut A", bench.keys["prod"], hosts="a")]
    bench.write_vault()
    from sshvault.backend import SshKeyItem
    paths = sshconfig.Paths(str(bench.home))
    it = SshKeyItem(ID_A, "Saut A", bench.keys["prod"]["public"], bench.keys["prod"]["fingerprint"], ("a",))
    plan = sshconfig.build([it], paths, str(bench.sock()), str(bench.exe))
    assert "ensure --id %s\"" % ID_A in plan.config.decode(), "ancienne forme"
    sshconfig.apply(plan, paths)
    askpass, calls = make_askpass(bench.tmp)
    env = {"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"}
    r = bench.run("ensure", "--id", ID_A, env=env)
    assert r.returncode == 0, r.stderr
    assert "adoptée" in r.stderr
    assert bench.agent_keys() == [bench.blob("prod")]
    assert bench.agent_state()["keys"][bench.keys["prod"]["fingerprint"]]["account"] == "alice"
    assert "« alice »" in calls.read_text(), "l'invite nomme l'alias"
    # chemin rapide pour l'ancienne forme : clé reconnue par son id
    n = len(bench.calls())
    assert bench.run("ensure", "--id", ID_A).returncode == 0 and len(bench.calls()) == n
    r = bench.run("ensure", "--id", "dddddddd-4444-4444-8444-dddddddddddd", env=env)
    assert r.returncode == 4 and "absent du coffre" in one_line_error(r)


def test_ancienne_config_plusieurs_comptes(bench):
    """Ancienne forme, plusieurs comptes : l'id est cherché dans les comptes déverrouillés."""
    two_accounts(bench)
    r = bench.run("ensure", "--id", ID_B)
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == [bench.blob("bastion")]
    e = bench.agent_state()["keys"][bench.keys["bastion"]["fingerprint"]]
    assert e["account"] == "boulot" and e["id"] == ID_B
    r = bench.run("ensure", "--id", "dddddddd-4444-4444-8444-dddddddddddd")
    assert r.returncode == 4 and "introuvable dans les comptes déverrouillés" in one_line_error(r)


def test_ensure_compte_par_compte(bench):
    """Nouvelle forme : `ensure --account boulot --id` lit le coffre de boulot seulement ; un id de
    boulot demandé sur alice : absent."""
    two_accounts(bench)
    r = bench.run("ensure", "--account", "boulot", "--id", ID_B)
    assert r.returncode == 0, r.stderr
    assert {c["appdata"] for c in bench.calls()} == {str(bench.appdata_of("boulot"))}
    r = bench.run("ensure", "--account", "alice", "--id", ID_B)
    assert r.returncode == 4 and "absent" in one_line_error(r)
    r = bench.run("ensure", "--account", "inconnu", "--id", ID_B)
    assert r.returncode == 2 and "inconnu" in one_line_error(r)


# --- account remove / rename -----------------------------------------------------------------

def test_account_remove(bench):
    """Compte avec clés chargées : session, données locales et clés retirées, blocs retirés ;
    coffre intact."""
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    r = bench.run("load", "--account", "boulot", "--id", ID_B)
    assert r.returncode == 0, r.stderr
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    vault_before = bench.account_vault("boulot").read_text()
    r = bench.run("account", "remove", "boulot")
    assert r.returncode == 0, r.stderr
    assert "compte boulot retiré" in r.stdout and "1 clé retirée" in r.stdout
    assert bench.agent_keys() == [bench.blob("prod")], "seule la clé de boulot retirée"
    assert not bench.appdata_of("boulot").parent.exists(), "données locales supprimées"
    assert bench.stored_session("boulot") == (None, None)
    assert "boulot" not in registry(bench)["accounts"] and "boulot" not in registry(bench)["default-accounts"]
    text = config_text(bench)
    assert ID_B not in text and "# Serveur Prod alice" in text, "blocs de boulot retirés"
    assert bench.account_vault("boulot").read_text() == vault_before, "rien modifié dans le coffre"
    assert all(e.get("account") != "boulot" for e in bench.agent_state()["keys"].values())


def test_account_rename(bench):
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    r = bench.run("account", "rename", "boulot", "travail")
    assert r.returncode == 0, r.stderr
    assert "renommé en travail" in r.stdout
    assert "illisible" not in r.stderr, "session déplacée : compte lu à la régénération"
    assert bench.stored_session("boulot") == (None, None) and bench.stored_session("travail") != (None, None)
    assert bench.appdata_of("travail").exists() and not bench.appdata_of("boulot").parent.exists()
    reg = registry(bench)
    assert "travail" in reg["accounts"] and "boulot" not in reg["accounts"] and "travail" in reg["default-accounts"]
    text = config_text(bench)
    assert "# Cible B travail %s" % ID_B in text and "--account travail --id %s" % ID_B in text
    assert "boulot" not in text
    e = bench.agent_state()["keys"][bench.keys["bastion"]["fingerprint"]]
    assert e["account"] == "travail"
    # clé toujours reconnue par le chemin rapide sous le nouvel alias
    n = len(bench.calls())
    assert bench.run("ensure", "--account", "travail", "--id", ID_B).returncode == 0 and len(bench.calls()) == n
    # session déplacée : lecture sans invite ni unlock
    r = bench.run("--nointeraction", "list", "--account", "travail")
    assert r.returncode == 0 and r.stdout.startswith("travail\tCible B\t"), r.stderr
    assert not any(c["argv"][1:2] == ["unlock"] for c in bench.calls())


# --- connexions réelles : trois sshd -------------------------------------------------------

def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Lab3:
    """sshd a (clé prod), b (clé bastion), c (clé perso) sur 127.0.0.1."""

    def __init__(self, d, keys):
        import getpass
        import socket
        self.user = getpass.getuser()
        self.ports, self.hostkeys, self.procs, self.logs = {}, {}, {}, {}
        for name, key in (("a", "prod"), ("b", "bastion"), ("c", "perso")):
            sd = d / name
            sd.mkdir()
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(sd / "hostkey")], check=True)
            self.hostkeys[name] = " ".join((sd / "hostkey.pub").read_text().split()[:2])
            (sd / "authorized_keys").write_text(keys[key]["public"] + "\n")
            port = _free_port()
            (sd / "sshd_config").write_text(
                "Port %d\nListenAddress 127.0.0.1\nHostKey %s\nPidFile %s\nAuthorizedKeysFile %s\nStrictModes no\n"
                "UsePAM no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nPrintMotd no\n"
                % (port, sd / "hostkey", sd / "sshd.pid", sd / "authorized_keys"))
            self.logs[name] = sd / "sshd.log"
            with open(str(self.logs[name]), "ab") as log:
                self.procs[name] = subprocess.Popen([SSHD, "-D", "-e", "-f", str(sd / "sshd_config")],
                                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                    stderr=log, start_new_session=True)
            self.ports[name] = port
        for name, port in self.ports.items():
            deadline = time.monotonic() + 10
            while True:
                with socket.socket() as s:
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        break
                assert time.monotonic() < deadline, "sshd %s ne répond pas" % name
                time.sleep(0.1)

    def stop(self):
        from bench import wait_gone
        for p in self.procs.values():
            try:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(10)
            except ProcessLookupError:
                pass
        assert wait_gone([p.pid for p in self.procs.values()]), "sshd de test encore vivants"


@pytest.fixture(scope="module")
def lab3(tmp_path_factory, keys):
    if not HAVE_LAB:
        pytest.skip("ssh, sshd, ssh-agent ou ssh-add absent")
    lb = Lab3.__new__(Lab3)
    lb.procs = {}
    try:
        lb.__init__(tmp_path_factory.mktemp("lab3"), keys)
    except BaseException:
        lb.stop()
        raise
    try:
        yield lb
    finally:
        lb.stop()


def lab_setup(bench, lab, tmp_path, owners):
    """`owners` : {hôte : compte} des éléments A (a, prod), B (b, bastion), C (c, perso).
    Comptes connectés et déverrouillés, ssh_config généré, puis tous verrouillés, agent vide.
    Config ssh de test : `b` derrière le rebond `a` (ProxyJump)."""
    spec = {"a": (ID_A, "Saut A", "prod"), "b": (ID_B, "Cible B", "bastion"), "c": (ID_C, "Client C", "perso")}
    per = {}
    for h, acct in owners.items():
        iid, name, key = spec[h]
        per.setdefault(acct, []).append(ssh_item(iid, name, bench.keys[key], hosts=h))
    bench.items = per.get(ALIAS, [])
    bench.write_vault()
    bench.unlocked(where(bench))
    servers = {"boulot": (SERVER, "bob@example.test"), "client": (OTHER, "carol@client.test")}
    for acct, items in per.items():
        if acct != ALIAS:
            srv, mail = servers[acct]
            bench.add_account(acct, mail, server=srv, items=items, unlocked=True, where=where(bench))
    kh = ["[127.0.0.1]:%d %s" % (lab.ports[n], lab.hostkeys[n]) for n in ("a", "b", "c")]
    bench.known_hosts.write_text("\n".join(kh) + "\n")
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    assert bench.run("lock").returncode == 0
    main = tmp_path / "ssh_config_de_test"
    main.write_text(
        'Include "%s"\n'
        "Host a\n    HostName 127.0.0.1\n    Port %d\n"
        "Host b\n    HostName 127.0.0.1\n    Port %d\n    ProxyJump a\n"
        "Host c\n    HostName 127.0.0.1\n    Port %d\n"
        "Host *\n    User %s\n    UserKnownHostsFile %s\n    GlobalKnownHostsFile /dev/null\n"
        "    StrictHostKeyChecking yes\n    BatchMode yes\n    ConnectTimeout 10\n"
        % (bench.home / ".ssh" / "sshvault" / "config", lab.ports["a"], lab.ports["b"], lab.ports["c"],
           lab.user, bench.known_hosts))
    main.chmod(0o600)
    return main


def ssh_argv(main, host):
    return [SSH, "-F", str(main), host, "true"]


def test_trois_comptes_ssh_vers_chacun(bench, lab3, tmp_path):
    """Critère d'acceptation : trois comptes (deux sur un serveur, un sur un autre), ssh_config
    généré, agent vide, coffres verrouillés : `ssh` vers un hôte de chacun charge sa clé, avec une
    invite par compte (qui nomme l'alias)."""
    main = lab_setup(bench, lab3, tmp_path, {"a": "alice", "b": "boulot", "c": "client"})
    assert bench.agent_keys() == []
    for host, acct, key in (("a", "alice", "prod"), ("c", "client", "perso")):
        r = pty_run([ssh_argv(main, host)], dict(bench.env), answers=[PASSWORD], timeout=60)
        assert r.returncode == 0, (host, r.stderr, r.screen)
        assert r.prompts == 1 and "« %s »" % acct in r.screen, r.screen
        assert bench.blob(key) in bench.agent_keys()
    # b derrière a (clé de a déjà chargée) : une invite, celle de boulot
    r = pty_run([ssh_argv(main, "b")], dict(bench.env), answers=[PASSWORD], timeout=60)
    assert r.returncode == 0, (r.stderr, r.screen)
    assert r.prompts == 1 and "« boulot »" in r.screen, r.screen
    assert sorted(bench.agent_keys()) == sorted(bench.blob(k) for k in ("prod", "bastion", "perso"))
    accounts = {e["account"] for e in bench.agent_state()["keys"].values()}
    assert accounts == {"alice", "boulot", "client"}


def test_rebond_multi_comptes_une_invite_par_compte(bench, lab3, tmp_path):
    """A (compte boulot) puis B (compte alice), coffres verrouillés : une invite par compte,
    nommée ; un refus sur alice (cible, demandée d'abord) ne bloque pas boulot (le saut)."""
    main = lab_setup(bench, lab3, tmp_path, {"a": "boulot", "b": "alice"})
    r = pty_run([ssh_argv(main, "b")], dict(bench.env), answers=[PASSWORD, PASSWORD], timeout=90)
    assert r.returncode == 0, (r.stderr, r.screen)
    assert r.prompts == 2, r.screen
    assert "« alice »" in r.screen and "« boulot »" in r.screen
    assert sorted(bench.agent_keys()) == sorted([bench.blob("prod"), bench.blob("bastion")])
    # refus sur alice : boulot pas bloqué
    assert bench.run("lock").returncode == 0
    assert bench.run("agent", "purge").returncode == 0
    r = pty_run([ssh_argv(main, "b")], dict(bench.env), answers=["mauvais", PASSWORD], timeout=90)
    assert r.returncode == 255
    assert r.prompts == 2, r.screen
    assert bench.agent_keys() == [bench.blob("prod")], "clé du saut (boulot) chargée malgré le refus sur alice"
    assert (bench.runtime / "sshvault" / "unlock-failed.alice").exists()
    assert not (bench.runtime / "sshvault" / "unlock-failed.boulot").exists()


def test_forward_multi_comptes_puis_remove(bench):
    """Sous-agent de transfert qui mêle deux comptes : `ensure --forward <fid> --id
    alice:<id> --id boulot:<id>` charge les deux clés ; `account remove boulot` retire la sienne
    du sous-agent, la clé d'alice reste."""
    import hashlib
    from bench import agent_list
    fwd = {"name": "sshvault-forward", "value": "relais", "type": 0, "linkedId": None}
    items = [ssh_item(ID_B, "Cible B", bench.keys["bastion"], extra_fields=[fwd])]
    two_accounts(bench, boulot_items=items)
    prod = next(i for i in bench.items if i.get("id") == ID_PROD)
    prod["fields"].append(dict(fwd))
    bench.write_vault()
    assert bench.run("config", "set", "forward-confirm", "false").returncode == 0
    assert bench.run("ssh-config").returncode == 0, "ssh_config"
    f = hashlib.sha256(b"relais").hexdigest()[:16]
    sock = bench.runtime / "sshvault" / "fwd" / (f + ".sock")
    r = bench.run("ensure", "--forward", f, "--id", "alice:%s" % ID_PROD, "--id", "boulot:%s" % ID_B)
    assert r.returncode == 0, r.stderr
    blobs = lambda: sorted(l.split()[1] for l in agent_list(sock)[1])  # noqa: E731
    assert blobs() == sorted([bench.blob("prod"), bench.blob("bastion")])
    st = json.loads((bench.runtime / "sshvault" / "fwd" / (f + ".json")).read_text())
    assert {e["account"] for e in st["keys"].values()} == {"alice", "boulot"}
    r = bench.run("account", "remove", "boulot")
    assert r.returncode == 0, r.stderr
    assert bench.blob("bastion") not in (blobs() if sock.exists() else [])
    assert "--id boulot:" not in config_text(bench) and "--id alice:%s" % ID_PROD in config_text(bench)


def test_adoption_bw_absent_retentee(bench):
    """bw introuvable au premier lancement : avertissement, rien modifié, la commande se fait
    (config set bw-path reste possible) ; adoption au lancement suivant."""
    legacy = legacy_install(bench, session=False)
    r = bench.run("config", "get", "key-ttl", env={"SSHVAULT_BW": "/nonexistent/bw"})
    assert r.returncode == 0 and r.stdout == "key-ttl 1h (défaut)\n"
    assert "installation 0.8.0 non adoptée" in one_line_error(r) and "bw introuvable" in r.stderr
    assert legacy.exists() and not bench.config_file().exists()
    r = bench.run("account", "list")
    assert r.returncode == 0 and "adoptée" in r.stderr and r.stdout.startswith("alice\t")
    assert not legacy.exists()


# --- relecture de la revue ---------------------------------------------------------------

def write_agent_state(bench, keys):
    """agent.json sans agent vivant (clés non chargées) : entrées données."""
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700, exist_ok=True)
    p = d / "agent.json"
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, json.dumps({"version": 1, "agent": None, "locked": False, "keys": keys}).encode())
    os.close(fd)


def entry(iid, account=None, also=None, name="x"):
    e = {"id": iid, "name": name, "hosts": [], "loaded": time.time(), "lifetime": 3600, "confirm": False,
         "restrict": False}
    if account:
        e["account"] = account
    if also is not None:
        e["also"] = also
    return e


def edit_agent_state(bench, fn):
    p = bench.runtime / "sshvault" / "agent.json"
    data = json.loads(p.read_text())
    fn(data)
    p.write_text(json.dumps(data))


def askpass_env(bench, name="askpass"):
    prog, calls = make_askpass(bench.tmp, name=name)
    return {"SSH_ASKPASS": prog, "SSH_ASKPASS_REQUIRE": "force"}, calls


def test_ssh_config_sans_registre_rien_ecrit(bench):
    """Registre vide (aucun compte) : ssh-config n'écrit rien, code 3, une ligne."""
    cfg = bench.home / ".ssh" / "sshvault" / "config"
    r = bench.run("ssh-config")
    assert r.returncode == 3 and "rien écrit" in one_line_error(r) and "account add" in r.stderr
    assert not cfg.exists()


def test_adoption_remise_ssh_config_et_account_add(bench):
    """Adoption remise (bw illisible) : le ssh_config 0.8.0 n'est pas réécrit (code 3, une ligne
    qui cite l'ancien dossier), `account add` est refusé (code 4) ; tout reprend une fois bw là."""
    legacy = legacy_install(bench, session=False)
    cfg = bench.home / ".ssh" / "sshvault" / "config"
    cfg.parent.mkdir(parents=True, mode=0o700)
    cfg.write_text("# bloc 0.8.0\n")
    cfg.chmod(0o600)
    nobw = {"SSHVAULT_BW": "/nonexistent/bw"}
    r = bench.run("ssh-config", env=nobw)
    assert r.returncode == 3
    assert "non adoptée" in r.stderr and "pas encore adoptée (%s)" % legacy in r.stderr and "rien écrit" in r.stderr
    assert cfg.read_text() == "# bloc 0.8.0\n"
    r = bench.run("account", "add", "x", "--server", "https://v.test", "--email", "x@v.test", env=nobw)
    assert r.returncode == 4 and str(legacy) in r.stderr.splitlines()[-1]
    assert not bench.config_file().exists() and legacy.exists()
    r = bench.run("account", "list")
    assert r.returncode == 0 and r.stdout.startswith("alice\t") and not legacy.exists()


@pytest.mark.parametrize("cmd,rc", [(["config", "get", "key-ttl"], 0), (["agent", "status"], 3),
                                    (["account", "list"], 0), (["ssh-config", "install"], 0),
                                    (["list"], 4), (["status"], 4)])
def test_adoption_impossible_commandes_sans_coffre(bench, cmd, rc):
    """Adoption impossible (code 4) : seules les commandes qui touchent au coffre échouent ; les
    autres se font avec une ligne d'avertissement."""
    legacy = legacy_install(bench, session=False)
    (bench.home / ".local" / "share" / "sshvault" / "accounts" / "alice").mkdir(parents=True)  # destination prise
    r = bench.run(*cmd)
    assert r.returncode == rc, r.stderr
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    assert "adoption de l'installation 0.8.0 impossible" in lines[0] and "Traceback" not in r.stderr
    if rc != 4:
        assert lines[0].startswith("sshvault: avertissement : ")
    assert (legacy / "data.json").exists() and not bench.config_file().exists()


def test_adoption_impossible_ensure(bench):
    legacy = legacy_install(bench, session=False)
    (bench.home / ".local" / "share" / "sshvault" / "accounts" / "alice").mkdir(parents=True)
    r = bench.run("ensure", "--id", ID_PROD)
    assert r.returncode == 4 and "adoption de l'installation 0.8.0 impossible" in one_line_error(r)
    assert (legacy / "data.json").exists() and not bench.config_file().exists()
    assert not bench.sock().exists(), "agent pas démarré"


def test_ancienne_forme_seul_compte_verrouille(bench):
    """Ancienne forme, plusieurs comptes : alice déverrouillée sans l'élément, client non connecté
    (pas candidat), boulot verrouillé : boulot, invite qui le nomme, clé chargée."""
    bench.unlocked(where(bench))
    bench.add_account("boulot", "bob@example.test", unlocked=False,
                      items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], hosts="b")])
    bench.add_account("client", "carol@client.test", server=OTHER, logged_in=False)
    env, calls = askpass_env(bench)
    r = bench.run("ensure", "--id", ID_B, env=env)
    assert r.returncode == 0, r.stderr
    assert "« boulot »" in calls.read_text() and len(calls.read_text().splitlines()) == 1
    assert bench.agent_keys() == [bench.blob("bastion")]
    assert bench.agent_state()["keys"][bench.keys["bastion"]["fingerprint"]]["account"] == "boulot"
    lists = [c for c in bench.calls() if c["argv"][1:3] == ["list", "items"]]
    assert [c["appdata"] for c in lists] == [str(bench.appdata)], "alice lue une fois, sans invite"


def test_ancienne_forme_compte_par_l_etat_de_l_agent(bench):
    """Ancienne forme, deux comptes verrouillés : le compte vient de la référence `also` de l'état
    de l'agent (pas du compte de l'entrée)."""
    bench.set_state(logged_in=True)
    bench.add_account("boulot", "bob@example.test", unlocked=False,
                      items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], hosts="b")])
    write_agent_state(bench, {bench.keys["prod"]["fingerprint"]: entry(ID_PROD, "alice", ["boulot:%s" % ID_B])})
    env, calls = askpass_env(bench)
    r = bench.run("ensure", "--id", ID_B, env=env)
    assert r.returncode == 0, r.stderr
    assert "« boulot »" in calls.read_text() and "« alice »" not in calls.read_text()
    assert bench.agent_keys() == [bench.blob("bastion")]


def test_ensure_id_alias_sans_account(bench):
    """`ensure --id <alias>:<uuid>` sans --account : le compte de la référence, chemin rapide
    compris (clé du même id dans un autre compte : pas prise pour elle)."""
    two_accounts(bench, boulot_items=[ssh_item(ID_PROD, "Autre Prod", bench.keys["bastion"], hosts="b")])
    assert bench.run("ensure", "--account", "alice", "--id", ID_PROD).returncode == 0
    assert bench.agent_keys() == [bench.blob("prod")]
    r = bench.run("ensure", "--id", "boulot:%s" % ID_PROD)
    assert r.returncode == 0, r.stderr
    assert sorted(bench.agent_keys()) == sorted([bench.blob("prod"), bench.blob("bastion")])
    n = len(bench.calls())
    assert bench.run("ensure", "--id", "boulot:%s" % ID_PROD).returncode == 0 and len(bench.calls()) == n


def test_remove_cle_partagee_reste(bench):
    """Clé partagée par alice et boulot (`also`) : `account remove alice` la garde chargée, l'entrée
    passe à boulot."""
    two_accounts(bench, boulot_items=[ssh_item(ID_B, "Copie", bench.keys["prod"], hosts="b")])
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("ensure", "--account", "alice", "--id", ID_PROD).returncode == 0
    assert bench.run("ensure", "--account", "boulot", "--id", ID_B).returncode == 0
    e = bench.agent_state()["keys"][bench.keys["prod"]["fingerprint"]]
    assert e["account"] == "alice" and e["also"] == ["boulot:%s" % ID_B]
    r = bench.run("account", "remove", "alice")
    assert r.returncode == 0, r.stderr
    assert "0 clé retirée" in r.stdout and bench.agent_keys() == [bench.blob("prod")]
    e = bench.agent_state()["keys"][bench.keys["prod"]["fingerprint"]]
    assert (e["account"], e["id"], e.get("also")) == ("boulot", ID_B, None)
    assert (e["name"], e["hosts"]) == ("Copie", ["b"]), "nom et hôtes du nouveau détenteur (ssh_config)"
    n = len(bench.calls())
    assert bench.run("ensure", "--account", "boulot", "--id", ID_B).returncode == 0 and len(bench.calls()) == n


def test_remove_agent_verrouille_etat_garde(bench):
    """Agent verrouillé : clés de boulot impossibles à retirer : arrêt avant toute suppression
    (état, données, session et registre gardés), une ligne, code 4."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    env, _ = askpass_env(bench)
    assert bench.run("agent", "lock", env=env).returncode == 0
    before = bench.agent_state()["keys"]
    r = bench.run("account", "remove", "boulot")
    assert r.returncode == 4
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    assert len(lines) == 1 and "non retirées" in lines[0] and "compte gardé, rien supprimé" in lines[0]
    assert bench.agent_state()["keys"] == before
    assert "boulot" in registry(bench)["accounts"] and bench.appdata_of("boulot").exists()
    assert bench.stored_session("boulot") != (None, None)
    assert bench.run("agent", "unlock", env=env).returncode == 0
    assert bench.agent_keys() == [bench.blob("bastion")], "clé toujours là"


def test_remove_agent_en_erreur_etat_garde(bench):
    """Agent qui ne répond plus (socket présent, ssh-add en erreur) : état gardé, code 4."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    fake = bench.tmp / "ssh-add-casse"
    fake.write_text("#!/bin/sh\necho 'error fetching identities: communication with agent failed' >&2\nexit 2\n")
    fake.chmod(0o755)
    before = bench.agent_state()["keys"]
    r = bench.run("account", "remove", "boulot", env={"SSHVAULT_SSH_ADD": str(fake)})
    assert r.returncode == 4
    assert len([l for l in r.stderr.splitlines() if "non retirées" in l]) == 1
    assert bench.agent_state()["keys"] == before
    assert "boulot" in registry(bench)["accounts"] and bench.appdata_of("boulot").exists()


@pytest.mark.parametrize("unlocked", [True, False])
def test_remove_entree_d_avant_0_9(bench, unlocked):
    """Entrée d'état sans compte (chargée avant la 0.9.0) : compte déverrouillé → clé retirée ;
    verrouillé → laissée, une ligne d'avertissement."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    edit_agent_state(bench, lambda d: [e.pop("account", None) for e in d["keys"].values()])
    if not unlocked:
        assert bench.run("lock", "--account", "boulot").returncode == 0
    r = bench.run("account", "remove", "boulot")
    assert r.returncode == 0, r.stderr
    if unlocked:
        assert bench.agent_keys() == [] and "1 clé retirée" in r.stdout
        assert "laissée" not in r.stderr
    else:
        assert bench.agent_keys() == [bench.blob("bastion")]
        assert len([l for l in r.stderr.splitlines() if "avant la 0.9.0" in l and "laissée" in l]) == 1


def test_account_add_dossier_existant(bench):
    d = bench.home / ".local" / "share" / "sshvault" / "accounts" / "perso"
    d.mkdir(parents=True)
    r = bench.run("account", "add", "perso", "--server", "https://v.test", "--email", "p@v.test")
    assert r.returncode == 2 and str(d) in one_line_error(r)
    assert not bench.config_file().exists()


def test_account_add_http_et_ports_par_defaut(bench):
    from sshvault.config import normalize_server
    assert normalize_server("HTTPS://V.test:443/x/") == "https://v.test/x"
    assert normalize_server("http://v.test:80") == "http://v.test"
    assert normalize_server("https://v.test:8443") == "https://v.test:8443"
    assert normalize_server("http://v.test:443") == "http://v.test:443"
    r = bench.run("account", "add", "a", "--server", "https://v.test:443", "--email", "a@v.test")
    assert r.returncode == 0 and r.stderr == "" and "https://v.test," in r.stdout
    r = bench.run("account", "add", "b", "--server", "https://v.test", "--email", "a@v.test")
    assert r.returncode == 2 and "déjà enregistré sous l'alias « a »" in one_line_error(r)
    r = bench.run("account", "add", "c", "--server", "http://w.test", "--email", "c@w.test")
    assert r.returncode == 0 and "en clair" in one_line_error(r) and "avertissement" in r.stderr


def test_status_serveur_different_averti(bench):
    bench.unlocked(where(bench))
    st = json.loads(bench.state_file().read_text())
    st["serverUrl"] = "https://autre.example.test"
    bench.state_file().write_text(json.dumps(st))
    r = bench.run("status")
    line = one_line_error(r)
    assert "avertissement" in line and "autre.example.test" in line and SERVER in line
    st["serverUrl"] = SERVER + ":443/"
    bench.state_file().write_text(json.dumps(st))
    assert bench.run("status").stderr == "", "même serveur, écrit autrement"


def test_lock_sans_compte(bench):
    r = bench.run("lock")
    assert r.returncode == 3 and "aucun compte" in one_line_error(r)
    assert not bench.calls()


def test_kept_items_auto_load_false_nom_termine_par_un_mot_d_alias(bench):
    """Config 0.8.0 en auto-load false, élément « Clé web » (« web » a l'allure d'un alias) :
    bloc d'ancienne forme gardé quand un compte est illisible, jamais pris pour un compte « web »."""
    from sshvault.backend import SshKeyItem
    two_accounts(bench, unlocked=False)
    paths = sshconfig.Paths(str(bench.home))
    it = SshKeyItem(ID_C, "Clé web", bench.keys["perso"]["public"], "", ("web.example",))
    plan = sshconfig.build([it], paths, str(bench.sock()), None)
    sshconfig.apply(plan, paths)
    assert "# Clé web %s\n" % ID_C in config_text(bench)
    assert bench.run("config", "set", "auto-load", "false").returncode == 0
    r = bench.run("--nointeraction", "ssh-config")
    assert r.returncode == 0, r.stderr
    assert "compte boulot illisible" in r.stderr
    assert "# Clé web %s\n" % ID_C in config_text(bench), "bloc 0.8.0 gardé, nom intact"
    kept = sshconfig.kept_items(paths, lambda a: True, known={"alice", "boulot"})
    assert [(i.account, i.name) for i in kept if i.id == ID_C] == [(None, "Clé web")]
    kept = sshconfig.kept_items(paths, lambda a: True, known={"web"})
    assert [(i.account, i.name) for i in kept if i.id == ID_C] == [("web", "Clé")], "alias du registre"


def test_remove_bw_path_invalide(bench):
    """bw-path invalide (ConfigError au lancement de bw) pendant `account remove` : compte retiré,
    une ligne, code 4, ssh_config inchangé (jamais régénéré à moitié)."""
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    before = config_text(bench)
    data = json.loads(bench.config_file().read_text())
    data["bw-path"] = "relatif"
    bench.config_file().write_text(json.dumps(data))
    r = bench.run("account", "remove", "boulot")
    assert r.returncode == 4 and "ssh_config non régénéré" in r.stderr and "Traceback" not in r.stderr
    assert "boulot" not in registry(bench)["accounts"] and not bench.appdata_of("boulot").parent.exists()
    assert config_text(bench) == before


def test_forward_deux_comptes_un_verrouille(bench):
    """`ensure --forward` sur deux comptes, boulot verrouillé : --nointeraction → code 3, une
    ligne qui nomme boulot, aucun `bw get`, sous-agent vide ; mot de passe refusé → mémoire
    d'échec de boulot seulement."""
    import hashlib
    from bench import agent_list
    fwd = {"name": "sshvault-forward", "value": "relais", "type": 0, "linkedId": None}
    two_accounts(bench, boulot_items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], extra_fields=[fwd])],
                 unlocked=False)
    prod = next(i for i in bench.items if i.get("id") == ID_PROD)
    prod["fields"].append(dict(fwd))
    bench.write_vault()
    assert bench.run("config", "set", "forward-confirm", "false").returncode == 0
    f = hashlib.sha256(b"relais").hexdigest()[:16]
    sock = bench.runtime / "sshvault" / "fwd" / (f + ".sock")
    args = ["ensure", "--forward", f, "--id", "alice:%s" % ID_PROD, "--id", "boulot:%s" % ID_B]
    n = len(bench.calls())
    r = bench.run("--nointeraction", *args)
    assert r.returncode == 3
    line = one_line_error(r)
    assert "coffre « boulot » verrouillé : aucune invite" in line, line
    assert not [c for c in bench.calls()[n:] if c["argv"][1:2] == ["get"]]
    assert (agent_list(sock)[1] if sock.exists() else []) == []
    # sous un ssh (connexion connue) : mot de passe de boulot refusé → mémoire d'échec de boulot seule
    fakessh = bench.tmp / "fakessh"
    fakessh.mkdir()
    os.symlink("/bin/sh", str(fakessh / "ssh"))
    bad, _ = make_askpass(bench.tmp, reply="mauvais", name="askpass-faux")
    cmd = '"%s" -m sshvault %s; exit $?' % (sys.executable, " ".join(args))
    r = subprocess.run([str(fakessh / "ssh"), "-c", cmd], env=dict(bench.env, SSH_ASKPASS=bad, SSH_ASKPASS_REQUIRE="force"),
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, start_new_session=True)
    assert r.returncode == 3, r.stderr
    rt = bench.runtime / "sshvault"
    assert (rt / "unlock-failed.boulot").exists() and not (rt / "unlock-failed.alice").exists()
    assert (agent_list(sock)[1] if sock.exists() else []) == []


def test_kept_blocs_de_transfert_d_un_compte_verrouille(bench):
    """`hosts add --account alice`, boulot verrouillé : son bloc de transfert garde `--id
    boulot:<id>`, pas d'avertissement « clé publique illisible », sous-agent pas arrêté."""
    import hashlib
    fwd = {"name": "sshvault-forward", "value": "relais", "type": 0, "linkedId": None}
    two_accounts(bench, boulot_items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], extra_fields=[fwd])])
    assert bench.run("config", "set", "forward-confirm", "false").returncode == 0
    assert bench.run("ssh-config").returncode == 0
    f = hashlib.sha256(b"relais").hexdigest()[:16]
    r = bench.run("ensure", "--forward", f, "--id", "boulot:%s" % ID_B)
    assert r.returncode == 0, r.stderr
    sock = bench.runtime / "sshvault" / "fwd" / (f + ".sock")
    assert sock.exists()
    assert bench.run("lock", "--account", "boulot").returncode == 0
    r = bench.run("--nointeraction", "hosts", "add", "--account", "alice", "--id", ID_PERSO, "p.example")
    assert r.returncode == 0, r.stderr
    assert "clé publique illisible" not in r.stderr and "sous-agent de transfert" not in r.stdout
    assert "ensure --forward %s --id boulot:%s\"" % (f, ID_B) in config_text(bench)
    assert sock.exists()


def test_exe_warnings_ligne_account(bench, tmp_path):
    paths = sshconfig.Paths(str(bench.home))
    d = bench.home / ".ssh" / "sshvault"
    d.mkdir(parents=True, mode=0o700)
    (d / "config").write_text('Match originalhost a exec "\'/autre/sshvault\' ensure --account alice --id %s"\n' % ID_A)
    (d / "config").chmod(0o600)
    w = sshconfig.exe_warnings("/nouveau/sshvault", paths)
    assert len(w) == 1 and "/autre/sshvault → /nouveau/sshvault" in w[0]


@pytest.mark.parametrize("reg", [
    {"accounts": {"../x": {"server": SERVER, "email": "a@b.test"}}},
    {"accounts": {"Alice": {"server": SERVER, "email": "a@b.test"}}},
    {"accounts": {"a": {"server": "https://Vault.example.test/", "email": "a@b.test"}}},
    {"accounts": {"a": {"server": SERVER, "email": "A@b.test"}}},
    {"accounts": {"a": {"server": SERVER, "email": "a@b.test"}, "b": {"server": SERVER, "email": "a@b.test"}}},
    {"accounts": {"a": {"server": SERVER, "email": "a@b.test"}}, "default-accounts": ["z"]},
    {"accounts": {"a": {"server": SERVER, "email": "a@b.test"}}, "default-accounts": ["a", "a"]},
    {"accounts": []},
])
def test_registre_invalide(bench, reg):
    f = bench.config_file()
    f.parent.mkdir(parents=True, mode=0o700)
    f.write_text(json.dumps(reg))
    f.chmod(0o600)
    for args in (["list"], ["account", "list"], ["status"]):
        r = bench.run(*args)
        assert r.returncode == 2, (args, r.stderr)
        assert "invalide" in one_line_error(r)
    assert not bench.calls(), "bw jamais lancé"


def test_login_apikey_d_un_autre_compte(bench):
    """`login --apikey --account boulot` avec la clé API d'alice : code 4, boulot déconnecté,
    aucune session rangée."""
    bench.unlocked(where(bench))
    bench.add_account("boulot", "bob@example.test", logged_in=False)
    r = bench.run("login", "--apikey", "--account", "boulot",
                  env={"BW_CLIENTID": "user.aaaa", "BW_CLIENTSECRET": "apisecret"})
    assert r.returncode == 4 and "pas de bob@example.test" in r.stderr.splitlines()[-1]
    st = json.loads((bench.appdata_of("boulot") / "data.json").read_text())
    assert not st.get("userId"), "déconnecté"
    assert bench.stored_session("boulot") == (None, None)


def test_rename_also_puis_ensure_sans_bw(bench):
    two_accounts(bench, boulot_items=[ssh_item(ID_B, "Copie", bench.keys["prod"], hosts="b")])
    assert bench.run("ensure", "--account", "alice", "--id", ID_PROD).returncode == 0
    assert bench.run("ensure", "--account", "boulot", "--id", ID_B).returncode == 0
    assert bench.run("account", "rename", "boulot", "travail").returncode == 0
    e = bench.agent_state()["keys"][bench.keys["prod"]["fingerprint"]]
    assert e["also"] == ["travail:%s" % ID_B]
    n = len(bench.calls())
    r = bench.run("ensure", "--account", "travail", "--id", ID_B)
    assert r.returncode == 0 and len(bench.calls()) == n, r.stderr


def test_bw_path_expose_une_ligne(bench):
    """bw-path exposé, deux comptes : `list` dit l'avertissement une fois ; deux `main()` dans un
    même processus : une fois chacun."""
    used = bench.tmp / "used.log"
    bench.env = bench.env_without_bw()
    bw = bench.bw_wrapper(bench.safe() / "partage" / "bw", used)
    bw.parent.chmod(0o775)
    two_accounts(bench)
    assert bench.run("config", "set", "bw-path", str(bw)).returncode == 0
    r = bench.run("list")
    assert r.returncode == 0, r.stderr
    assert len([l for l in r.stderr.splitlines() if "exposé à d'autres" in l]) == 1
    code = "from sshvault.cli import main; main(['list']); main(['list'])"
    p = subprocess.run([sys.executable, "-c", code], env=bench.env, capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL, start_new_session=True)
    assert len([l for l in p.stderr.splitlines() if "exposé à d'autres" in l]) == 2, p.stderr


# --- deuxième relecture ------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [["status"], ["list"], ["lock"]])
def test_adoption_remise_dite_avec_sa_cause(bench, cmd):
    """Installation 0.8.0 en attente (bw illisible) : status, list et lock disent l'attente et sa
    cause au lieu de suggérer `account add`."""
    legacy = legacy_install(bench, session=False)
    r = bench.run(*cmd, env={"SSHVAULT_BW": "/nonexistent/bw"})
    assert r.returncode == 3
    out = r.stdout + r.stderr
    assert "pas encore adoptée (%s) : " % legacy in out and "bw introuvable" in out
    assert "account add" not in out.replace("non adoptée", "")


def test_login_regenere_le_ssh_config(bench):
    """login réussi : ssh_config existant régénéré (le compte connecté y entre) ; sans ssh_config,
    la commande à lancer est dite."""
    bench.unlocked(where(bench))
    bench.add_account("boulot", "bob@example.test", logged_in=False,
                      items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], hosts="b")])
    p = subprocess.run([sys.executable, "-m", "sshvault", "login", "--account", "boulot"], env=bench.env,
                       input="%s\n" % PASSWORD, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and "lancer « sshvault ssh-config »" in p.stdout, p.stderr
    assert bench.run("ssh-config").returncode == 0
    assert "--account boulot --id %s" % ID_B in config_text(bench)
    assert bench.run("account", "remove", "boulot").returncode == 0
    bench.add_account("boulot", "bob@example.test", logged_in=False,
                      items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], hosts="b")])
    assert ID_B not in config_text(bench)
    p = subprocess.run([sys.executable, "-m", "sshvault", "login", "--account", "boulot"], env=bench.env,
                       input="%s\n" % PASSWORD, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "--account boulot --id %s" % ID_B in config_text(bench), "régénéré au login"


def test_ecriture_aucune_cle_nomme_le_compte(bench):
    two_accounts(bench)
    r = bench.run("hosts", "add", "--account", "alice", "--id", ID_B, "x.example")
    assert r.returncode == 1
    line = one_line_error(r)
    assert "dans le compte alice" in line and "--account" in line


def test_pub_fingerprint_par_compte(bench):
    """Même id dans deux comptes, clés différentes : le `.pub` de chaque compte, avec et sans
    ligne exec ; sans compte : le premier bloc."""
    from sshvault import fastpath
    from sshvault.backend import SshKeyItem
    paths = sshconfig.Paths(str(bench.home))
    items = [SshKeyItem(ID_PROD, "Prod", bench.keys["prod"]["public"], "", ("a",), account="alice"),
             SshKeyItem(ID_PROD, "Prod", bench.keys["bastion"]["public"], "", ("b",), account="boulot")]
    env = dict(bench.env)
    for exe in (str(bench.exe), None):
        sshconfig.apply(sshconfig.build(items, paths, str(bench.sock()), exe), paths)
        assert fastpath.pub_fingerprint(ID_PROD, env, "alice") == bench.keys["prod"]["fingerprint"]
        assert fastpath.pub_fingerprint(ID_PROD, env, "boulot") == bench.keys["bastion"]["fingerprint"]
        assert fastpath.pub_fingerprint(ID_PROD, env, "autre") is None
        assert fastpath.pub_fingerprint(ID_PROD, env) == bench.keys["prod"]["fingerprint"]
    # ancienne forme (sans compte) : vaut pour tout compte
    sshconfig.apply(sshconfig.build([SshKeyItem(ID_PROD, "Prod", bench.keys["prod"]["public"], "", ("a",))],
                                    paths, str(bench.sock()), str(bench.exe)), paths)
    assert fastpath.pub_fingerprint(ID_PROD, env, "boulot") == bench.keys["prod"]["fingerprint"]


def test_agent_status_alias_en_premiere_colonne(bench):
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    edit_agent_state(bench, lambda d: d["keys"][bench.keys["prod"]["fingerprint"]].pop("account"))
    r = bench.run("agent", "status")
    assert r.returncode == 0, r.stderr
    rows = [l.split("\t") for l in r.stdout.splitlines() if "\t" in l]
    assert sorted((c[0], c[1]) for c in rows) == [("?", "Serveur Prod"), ("boulot", "Cible B")]


def test_email_commencant_par_un_tiret(bench):
    r = bench.run("account", "add", "x", "--server", "https://v.test", "--email=-o@v.test")
    assert r.returncode == 2 and "e-mail invalide" in one_line_error(r)


def test_login_apikey_logout_en_echec(bench):
    bench.unlocked(where(bench))
    bench.add_account("boulot", "bob@example.test", logged_in=False)
    r = bench.run("login", "--apikey", "--account", "boulot",
                  env={"BW_CLIENTID": "user.aaaa", "BW_CLIENTSECRET": "apisecret", "FAKE_BW_FAIL": "logout=error"})
    assert r.returncode == 4
    last = r.stderr.splitlines()[-1]
    assert "restent sous cet alias" in last and "déconnecté" not in last
    assert bench.stored_session("boulot") == (None, None)


def test_kept_items_pub_absente_avertie(bench):
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("lock", "--account", "boulot").returncode == 0
    pub = bench.home / ".ssh" / "sshvault" / "pub" / sshconfig.fp_filename(bench.keys["bastion"]["fingerprint"])
    pub.unlink()
    r = bench.run("--nointeraction", "hosts", "add", "--account", "alice", "--id", ID_PERSO, "p.example")
    assert r.returncode == 0, r.stderr
    lines = [l for l in r.stderr.splitlines() if "non gardé" in l]
    assert len(lines) == 1 and "Cible B" in lines[0] and "boulot" in lines[0]


def test_ancienne_forme_compte_en_erreur_pas_candidat(bench):
    """Ancienne forme : un compte dont bw est en erreur n'est ni lu ni candidat « seul
    verrouillé » : boulot (verrouillé) reste le seul candidat."""
    bench.unlocked(where(bench))
    bench.add_account("boulot", "bob@example.test", unlocked=False,
                      items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], hosts="b")])
    bench.add_account("client", "carol@client.test", server=OTHER)
    (bench.appdata_of("client") / "data.json").write_text("{pas du json")
    env, calls = askpass_env(bench)
    r = bench.run("ensure", "--id", ID_B, env=env)
    assert r.returncode == 0, r.stderr
    assert "« boulot »" in calls.read_text() and bench.agent_keys() == [bench.blob("bastion")]


def test_normalize_server_ports():
    from sshvault.config import normalize_server
    assert normalize_server("https://v.test:0443") == "https://v.test"
    assert normalize_server("https://v.test:") == "https://v.test"
    assert normalize_server("https://[::1]:443/") == "https://[::1]"
    assert normalize_server("http://V.test:080") == "http://v.test"


def test_rename_compte_verrouille_blocs_gardes(bench):
    """Compte verrouillé renommé après ssh-config : ses blocs gardés sous le nouvel alias,
    avertissement ; `ssh-config --check` à jour."""
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("lock", "--account", "boulot").returncode == 0
    r = bench.run("account", "rename", "boulot", "travail")
    assert r.returncode == 0, r.stderr
    assert "compte travail illisible" in r.stderr
    text = config_text(bench)
    assert "# Cible B travail %s\n" % ID_B in text and "ensure --account travail --id %s\"" % ID_B in text
    assert "boulot" not in text
    r = bench.run("--nointeraction", "ssh-config", "--check")
    assert "à réécrire" not in r.stdout and "en trop" not in r.stdout and "absent" not in r.stdout, r.stdout


def test_rename_avec_sous_agent_de_transfert(bench):
    import hashlib
    from bench import agent_list
    fwd = {"name": "sshvault-forward", "value": "relais", "type": 0, "linkedId": None}
    two_accounts(bench, boulot_items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], extra_fields=[fwd])])
    assert bench.run("config", "set", "forward-confirm", "false").returncode == 0
    assert bench.run("ssh-config").returncode == 0
    f = hashlib.sha256(b"relais").hexdigest()[:16]
    assert bench.run("ensure", "--forward", f, "--id", "boulot:%s" % ID_B).returncode == 0
    sock = bench.runtime / "sshvault" / "fwd" / (f + ".sock")
    r = bench.run("account", "rename", "boulot", "travail")
    assert r.returncode == 0, r.stderr
    assert "clé retirée" not in r.stdout and sock.exists()
    st = json.loads((bench.runtime / "sshvault" / "fwd" / (f + ".json")).read_text())
    assert {e["account"] for e in st["keys"].values()} == {"travail"}
    assert agent_list(sock)[1], "clé toujours dans le sous-agent"
    n = len(bench.calls())
    r = bench.run("ensure", "--forward", f, "--id", "travail:%s" % ID_B)
    assert r.returncode == 0 and len(bench.calls()) == n, r.stderr


@pytest.mark.parametrize("cmd", [["load", "--all"], ["pubkey", "--all"]])
def test_deux_defauts_un_verrouille(bench, cmd):
    two_accounts(bench, unlocked=False)
    r = bench.run("--nointeraction", *cmd)
    assert r.returncode == 3
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("sshvault: boulot : "), r.stderr
    if cmd[0] == "load":
        assert sorted(bench.agent_keys()) == sorted(bench.blob(k) for k in ("prod", "perso", "bastion"))
    else:
        assert len(r.stdout.splitlines()) == 3 and bench.keys["prod"]["public"].split()[1] in r.stdout


def test_status_email_different_une_ligne(bench):
    bench.unlocked(where(bench))
    st = json.loads(bench.state_file().read_text())
    st["userEmail"] = EMAIL.upper()
    bench.state_file().write_text(json.dumps(st))
    assert bench.run("status").stderr == "", "casse seule : pas d'avertissement"
    st["userEmail"] = "autre@example.test"
    bench.state_file().write_text(json.dumps(st))
    r = bench.run("status")
    line = one_line_error(r)
    assert "autre@example.test" in line and EMAIL in line


def test_rename_refus(bench):
    two_accounts(bench)
    before = bench.config_file().read_bytes()
    r = bench.run("account", "rename", "boulot", "alice")
    assert r.returncode == 2 and "déjà pris" in one_line_error(r)
    assert bench.config_file().read_bytes() == before
    d = bench.home / ".local" / "share" / "sshvault" / "accounts" / "travail"
    d.mkdir()
    r = bench.run("account", "rename", "boulot", "travail")
    assert r.returncode == 4 and str(d) in one_line_error(r)
    assert bench.config_file().read_bytes() == before and bench.appdata_of("boulot").exists()
    assert bench.stored_session("boulot") != (None, None)

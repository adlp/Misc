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


# --- story 11 : logout et account set ----------------------------------------------------

ID_D = "dddddddd-4444-4444-8444-dddddddddddd"


def bw_state(bench, alias):
    p = bench.appdata_of(alias) / "data.json"
    return json.loads(p.read_text()) if p.exists() else {}


def extra_vault(bench, name, email, server=SERVER, items=()):
    """Coffre du faux serveur sans compte au registre (cible d'un `account set`)."""
    vf = bench.tmp / "server" / ("vault-%s.json" % name)
    vf.write_text(json.dumps({"server": server, "email": email, "password": PASSWORD,
                              "userId": "aaaaaaaa-0000-4000-8000-0000000000%02d" % (90 + len(name)),
                              "clientId": "user.%s" % name, "clientSecret": "apisecret-%s" % name,
                              "items": list(items)}))
    bench.env["FAKE_BW_VAULTS"] = ":".join([p for p in bench.env.get("FAKE_BW_VAULTS", "").split(":") if p]
                                           + [str(vf)])
    return vf


def login(bench, alias):
    return subprocess.run([sys.executable, "-m", "sshvault", "login", "--account", alias], env=bench.env,
                          input="%s\n" % PASSWORD, capture_output=True, text=True, timeout=60)


def test_logout_un_compte(bench):
    """Un compte connecté, clés chargées : `logout` sans --account le vise ; bw déconnecté,
    session oubliée, clés retirées ; compte et blocs gardés, ssh-config --check à jour."""
    bench.unlocked(where(bench))
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    before = config_text(bench)
    reg_before = bench.config_file().read_bytes()
    vault_before = bench.vault_file.read_text()
    r = bench.run("logout")
    assert r.returncode == 0, r.stderr
    assert "compte alice déconnecté" in r.stdout and "1 clé retirée" in r.stdout
    assert "« sshvault login --account alice »" in r.stdout
    assert not bench.state().get("userId"), "bw déconnecté"
    assert bench.stored_session() == (None, None)
    assert bench.agent_keys() == [] and bench.agent_state()["keys"] == {}
    assert config_text(bench) == before and bench.config_file().read_bytes() == reg_before
    assert bench.vault_file.read_text() == vault_before, "rien modifié dans le coffre"
    assert any(c["argv"][1:2] == ["logout"] for c in bench.calls())
    # seul compte, déconnecté : ses blocs gardés tels quels, --check à jour (avertissement)
    assert bench.run("ssh-config", "install").returncode == 0
    r = bench.run("--nointeraction", "ssh-config", "--check")
    assert r.returncode == 0 and "à jour" in r.stdout, (r.stdout, r.stderr)
    assert "compte alice non connecté : ses blocs" in one_line_error(r)
    r = bench.run("status")
    assert r.returncode == 3 and "coffre : non connecté" in r.stdout


def test_logout_plusieurs_comptes_exige_account(bench):
    two_accounts(bench)
    n = len(bench.calls())
    r = bench.run("logout")
    assert r.returncode == 2
    line = one_line_error(r)
    assert "préciser --account" in line and "alice, boulot" in line
    assert len(bench.calls()) == n and bench.stored_session("boulot") != (None, None)


def test_logout_sans_compte(bench):
    r = bench.run("logout")
    assert r.returncode == 3 and "account add" in one_line_error(r)


def test_logout_un_seul_des_comptes(bench):
    """`logout --account boulot` : seules ses clés retirées ; alice intacte ; un ensure de boulot
    échoue ensuite en une ligne qui propose `login --account boulot`."""
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    r = bench.run("logout", "--account", "boulot")
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == [bench.blob("prod")]
    assert not bw_state(bench, "boulot").get("userId") and bench.state().get("userId")
    assert bench.stored_session("boulot") == (None, None) and bench.stored_session() != (None, None)
    assert "boulot" in registry(bench)["accounts"] and "boulot" in registry(bench)["default-accounts"]
    assert "--account boulot --id %s" % ID_B in config_text(bench), "blocs gardés"
    assert bench.run("ssh-config", "install").returncode == 0
    r = bench.run("--nointeraction", "ssh-config", "--check")
    assert r.returncode == 0 and "à jour" in r.stdout, (r.stdout, r.stderr)
    # invite possible (cas de ssh) : bw dit « non connecté » avant toute invite
    env, calls = askpass_env(bench)
    r = bench.run("ensure", "--account", "boulot", "--id", ID_B, env=env)
    assert r.returncode == 3
    line = one_line_error(r)
    assert "déconnecté" in line and "sshvault login --account boulot" in line
    assert not calls.exists() or calls.read_text() == "", "aucune invite"
    assert bench.agent_keys() == [bench.blob("prod")]


def test_logout_cle_partagee_gardee(bench):
    """Clé de alice aussi dans boulot : `logout --account alice` la garde, attribuée à boulot."""
    two_accounts(bench, boulot_items=[ssh_item(ID_B, "Copie", bench.keys["prod"], hosts="b")])
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("ensure", "--account", "alice", "--id", ID_PROD).returncode == 0
    assert bench.run("ensure", "--account", "boulot", "--id", ID_B).returncode == 0
    r = bench.run("logout", "--account", "alice")
    assert r.returncode == 0, r.stderr
    assert "0 clé retirée" in r.stdout and bench.agent_keys() == [bench.blob("prod")]
    e = bench.agent_state()["keys"][bench.keys["prod"]["fingerprint"]]
    assert (e["account"], e["id"], e.get("also")) == ("boulot", ID_B, None)
    assert (e["name"], e["hosts"]) == ("Copie", ["b"])


def test_logout_non_connecte(bench):
    """Compte déjà déconnecté : rien, code 0, une ligne ; données de bw absentes : idem, sans
    lancer bw ni créer son dossier."""
    two_accounts(bench)
    bench.add_account("client", "carol@client.test", server=OTHER, logged_in=False)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    assert bench.run("logout", "--account", "boulot").returncode == 0
    state = bench.agent_state()
    n = len(bench.calls())
    r = bench.run("logout", "--account", "boulot")
    assert r.returncode == 0 and r.stdout == "compte boulot non connecté : rien à faire\n" and r.stderr == ""
    assert not any(c["argv"][1:2] == ["logout"] for c in bench.calls()[n:])
    assert bench.agent_state() == state
    n = len(bench.calls())
    r = bench.run("logout", "--account", "client")
    assert r.returncode == 0 and r.stdout == "compte client non connecté : rien à faire\n" and r.stderr == ""
    assert len(bench.calls()) == n and not bench.appdata_of("client").exists()


@pytest.mark.parametrize("cmd", [["logout", "--account", "boulot"],
                                 ["account", "set", "boulot", "--email", "dan@example.test"]])
def test_logout_set_agent_verrouille(bench, cmd):
    """Agent verrouillé : rien modifié (état, connexion, session, registre), une ligne, code 4."""
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    env, _ = askpass_env(bench)
    assert bench.run("agent", "lock", env=env).returncode == 0
    before = bench.agent_state()["keys"]
    reg_before, cfg_before = bench.config_file().read_bytes(), config_text(bench)
    r = bench.run(*cmd)
    assert r.returncode == 4
    line = one_line_error(r)
    assert "non retirées" in line and ("relancer « sshvault %s »" % " ".join(cmd)) in line, line
    assert bench.agent_state()["keys"] == before
    assert bw_state(bench, "boulot").get("userId") and bench.stored_session("boulot") != (None, None)
    assert bench.config_file().read_bytes() == reg_before and config_text(bench) == cfg_before
    assert not any(c["argv"][1:2] == ["logout"] for c in bench.calls())


@pytest.mark.parametrize("cmd", [["logout", "--account", "boulot"],
                                 ["account", "set", "boulot", "--email", "dan@example.test"]])
def test_logout_set_bw_logout_en_echec(bench, cmd):
    """`bw logout` en échec : code 4, une ligne qui dit ce qui reste ; registre inchangé."""
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    reg_before, cfg_before = bench.config_file().read_bytes(), config_text(bench)
    r = bench.run(*cmd, env={"FAKE_BW_FAIL": "logout=error"})
    assert r.returncode == 4
    line = one_line_error(r)
    assert "bw logout en échec" in line and "toujours connectées sous l'alias boulot" in line
    assert str(bench.appdata_of("boulot")) in line
    assert "1 clé retirée des agents, session oubliée" in line, line
    assert bench.stored_session("boulot") == (None, None) and bench.agent_keys() == []
    assert bw_state(bench, "boulot").get("userId"), "toujours connecté"
    assert bench.config_file().read_bytes() == reg_before and config_text(bench) == cfg_before
    assert ("registre inchangé" in line) == (cmd[0] == "account")
    assert not marker(bench, "boulot").exists(), "toujours connecté : pas de marqueur"


def test_account_set_email_compte_connecte(bench):
    """`account set boulot --email` sur un compte connecté, clés chargées : logout, clés retirées,
    blocs retirés, registre mis à jour ; alias et comptes par défaut gardés ; coffre intact."""
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    vault_before = bench.account_vault("boulot").read_text()
    r = bench.run("account", "set", "boulot", "--email", " Dan@Example.test ")
    assert r.returncode == 0, r.stderr
    assert "compte boulot modifié : %s, dan@example.test (avant : %s, bob@example.test)" % (SERVER, SERVER) in r.stdout
    assert "déconnecté de l'ancien compte" in r.stdout and "1 clé retirée" in r.stdout
    assert r.stdout.splitlines()[-1] == "lancer « sshvault login --account boulot »"
    reg = registry(bench)
    assert reg["accounts"]["boulot"] == {"server": SERVER, "email": "dan@example.test"}
    assert reg["default-accounts"] == ["alice", "boulot"]
    assert not bw_state(bench, "boulot").get("userId") and bench.stored_session("boulot") == (None, None)
    assert bench.agent_keys() == [bench.blob("prod")]
    text = config_text(bench)
    assert ID_B not in text and "boulot" not in text and "# Serveur Prod alice" in text
    assert "illisible" not in r.stderr, "blocs de boulot retirés, pas gardés"
    assert bench.account_vault("boulot").read_text() == vault_before
    assert bench.run("ssh-config", "install").returncode == 0
    r = bench.run("--nointeraction", "ssh-config", "--check")
    assert r.returncode == 0 and "à jour" in r.stdout, (r.stdout, r.stderr)


def test_account_set_puis_login(bench):
    """Login après set : connexion au nouveau serveur et au nouvel e-mail, blocs régénérés."""
    two_accounts(bench)
    extra_vault(bench, "neuf", "dan@client.test", server=OTHER,
                items=[ssh_item(ID_D, "Cible D", bench.keys["bastion"], hosts="d")])
    assert bench.run("ssh-config").returncode == 0
    r = bench.run("account", "set", "boulot", "--server", OTHER + "/", "--email", "dan@client.test")
    assert r.returncode == 0, r.stderr
    assert registry(bench)["accounts"]["boulot"] == {"server": OTHER, "email": "dan@client.test"}
    p = login(bench, "boulot")
    assert p.returncode == 0, p.stderr
    st = bw_state(bench, "boulot")
    assert st["userEmail"] == "dan@client.test" and st["serverUrl"] == OTHER
    text = config_text(bench)
    assert "# Cible D boulot %s" % ID_D in text and ID_B not in text
    r = bench.run("status", "--account", "boulot")
    assert r.returncode == 0 and r.stderr == "", r.stderr


def test_account_set_compte_non_connecte(bench):
    """Compte jamais connecté (données absentes) : registre mis à jour, bw jamais lancé."""
    bench.unlocked(where(bench))
    bench.add_account("client", "carol@client.test", server=OTHER, logged_in=False)
    n = len(bench.calls())
    r = bench.run("account", "set", "client", "--email", "carole@client.test")
    assert r.returncode == 0, r.stderr
    assert "déconnecté" not in r.stdout and "0 clé retirée" in r.stdout
    assert registry(bench)["accounts"]["client"] == {"server": OTHER, "email": "carole@client.test"}
    assert len(bench.calls()) == n and not bench.appdata_of("client").exists()


def test_account_set_rien_de_neuf(bench):
    """Valeurs identiques (écrites autrement) : rien fait, code 0, une ligne ; toujours connecté."""
    two_accounts(bench)
    before = bench.config_file().read_bytes()
    n = len(bench.calls())
    r = bench.run("account", "set", "boulot", "--email", "BOB@example.test", "--server", SERVER + ":443/")
    assert r.returncode == 0 and r.stderr == ""
    assert r.stdout == "compte boulot inchangé (%s, bob@example.test) : rien fait\n" % SERVER
    assert bench.config_file().read_bytes() == before and len(bench.calls()) == n
    assert bench.stored_session("boulot") != (None, None)


@pytest.mark.parametrize("args,msg", [
    (["account", "set", "boulot", "--email", "alice@example.test"], "déjà enregistré sous l'alias « alice »"),
    (["account", "set", "boulot"], "préciser --server URL et/ou --email E"),
    (["account", "set", "boulot", "--email=-o@v.test"], "e-mail invalide"),
    (["account", "set", "boulot", "--server", "ftp://v.test"], "serveur invalide"),
    (["account", "set", "inconnu", "--email", "x@v.test"], "compte « inconnu » inconnu"),
])
def test_account_set_refus(bench, args, msg):
    """Doublon, aucune option, valeur invalide, alias inconnu : code 2, une ligne, rien changé."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    before = bench.config_file().read_bytes()
    n = len(bench.calls())
    r = bench.run(*args)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert msg in one_line_error(r)
    assert bench.config_file().read_bytes() == before and len(bench.calls()) == n
    assert bench.agent_keys() == [bench.blob("bastion")] and bench.stored_session("boulot") != (None, None)


def test_account_set_http_averti(bench):
    bench.unlocked(where(bench))
    bench.add_account("client", "carol@client.test", server=OTHER, logged_in=False)
    r = bench.run("account", "set", "client", "--server", "http://w.test")
    assert r.returncode == 0
    assert "en clair" in one_line_error(r) and "avertissement" in r.stderr
    assert registry(bench)["accounts"]["client"]["server"] == "http://w.test"


def test_status_email_different_puis_set_registre_seul(bench):
    """Critère d'acceptation (décision : seul le registre se trompait) : `status` signale un
    e-mail différent et propose `account set` (valeur de bw) ou `logout` ; `account set
    --email <valeur de bw>` corrige le registre seul (ni déconnexion, ni clé ni bloc retiré) ;
    `status` ne signale plus rien."""
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    bench.accounts["boulot"] = (SERVER, "bobby@example.test")
    bench.write_registry()
    r = bench.run("status", "--account", "boulot")
    line = one_line_error(r)
    assert "bob@example.test" in line and "bobby@example.test" in line
    assert "« sshvault account set boulot --email bob@example.test »," in line, line
    assert "« sshvault logout --account boulot » puis « sshvault login --account boulot »" in line
    before = config_text(bench)
    n = len(bench.calls())
    r = bench.run("account", "set", "boulot", "--email", "bob@example.test")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["compte boulot : registre corrigé : %s, bob@example.test (avant : %s, "
                                     "bobby@example.test) ; bw y est déjà connecté : ni déconnexion, ni clé ni bloc "
                                     "retiré" % (SERVER, SERVER)]
    assert not any(c["argv"][1:2] == ["logout"] for c in bench.calls()[n:])
    assert bw_state(bench, "boulot").get("userId") and bench.stored_session("boulot") != (None, None)
    assert bench.agent_keys() == [bench.blob("bastion")] and config_text(bench) == before
    assert registry(bench)["accounts"]["boulot"]["email"] == "bob@example.test"
    r = bench.run("status")
    assert r.returncode == 0 and r.stderr == "", r.stderr


def test_status_email_different_set_vers_un_autre_puis_login(bench):
    """Registre et bw tous deux faux : `account set --email <bon>` déconnecte, `login` connecte
    le bon compte ; `status` ne signale plus rien."""
    two_accounts(bench)
    extra_vault(bench, "dan", "dan@example.test", items=[ssh_item(ID_D, "Cible D", bench.keys["bastion"], hosts="d")])
    bench.accounts["boulot"] = (SERVER, "bobby@example.test")
    bench.write_registry()
    assert "avertissement" in one_line_error(bench.run("status", "--account", "boulot"))
    r = bench.run("account", "set", "boulot", "--email", "dan@example.test")
    assert r.returncode == 0 and "déconnecté de l'ancien compte" in r.stdout, r.stderr
    p = login(bench, "boulot")
    assert p.returncode == 0, p.stderr
    r = bench.run("status")
    assert r.returncode == 0 and r.stderr == "", r.stderr


def test_status_serveur_different_propose_set(bench):
    bench.unlocked(where(bench))
    st = json.loads(bench.state_file().read_text())
    st["serverUrl"] = "https://autre.example.test:443/"
    bench.state_file().write_text(json.dumps(st))
    line = one_line_error(bench.run("status"))
    assert "« sshvault account set alice --server https://autre.example.test »" in line
    assert "« sshvault logout --account alice »" in line


# --- story 11, revue ---------------------------------------------------------------------

def test_logout_bw_deja_deconnecte_cles_retirees(bench):
    """bw déconnecté hors de sshvault, clé encore chargée et session rangée : `logout` retire la
    clé et oublie la session (bw logout non lancé)."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    st = bw_state(bench, "boulot")
    (bench.appdata_of("boulot") / "data.json").write_text(json.dumps(
        {"stateVersion": 85, "serverUrl": st["serverUrl"]}))
    n = len(bench.calls())
    r = bench.run("logout", "--account", "boulot")
    assert r.returncode == 0, r.stderr
    assert "compte boulot non connecté : session oubliée, 1 clé retirée des agents" in r.stdout
    assert bench.agent_keys() == [] and bench.stored_session("boulot") == (None, None)
    assert not any(c["argv"][1:2] == ["logout"] for c in bench.calls()[n:])


def test_logout_puis_ensure_sans_invite_propose_login(bench):
    """Après `logout`, `ensure` sans invite possible dit de relancer `login --account` ; après
    `login`, le marqueur est retiré et la clé se charge."""
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("logout", "--account", "boulot").returncode == 0
    assert (bench.appdata_of("boulot").parent / "logged-out").exists()
    r = bench.run("--nointeraction", "ensure", "--account", "boulot", "--id", ID_B)
    assert r.returncode == 3
    line = one_line_error(r)
    assert "déconnecté" in line and "« sshvault login --account boulot »" in line, line
    p = login(bench, "boulot")
    assert p.returncode == 0, p.stderr
    assert not (bench.appdata_of("boulot").parent / "logged-out").exists()
    r = bench.run("--nointeraction", "ensure", "--account", "boulot", "--id", ID_B)
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == [bench.blob("bastion")]


def test_account_set_pose_le_marqueur(bench):
    two_accounts(bench)
    assert bench.run("account", "set", "boulot", "--email", "dan@example.test").returncode == 0
    r = bench.run("--nointeraction", "ensure", "--account", "boulot", "--id", ID_B)
    assert r.returncode == 3 and "« sshvault login --account boulot »" in one_line_error(r)


def test_account_set_registre_refuse_apres_logout(bench):
    """Registre refusé après la déconnexion (un autre alias a pris le couple entre-temps) : une
    ligne qui dit ce qui est déjà fait, registre inchangé, code 2."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    cfg = bench.config_file()
    wrapper = bench.tmp / "bw-course"
    wrapper.write_text(
        "#!/bin/sh\ncase \"$*\" in *logout*) '%s' -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); "
        "d[\"accounts\"][\"zz\"]={\"server\":\"%s\",\"email\":\"dan@example.test\"}; open(p,\"w\").write(json.dumps(d))' "
        "'%s';; esac\nexec '%s' \"$@\"\n" % (sys.executable, SERVER, cfg, bench.bw))
    wrapper.chmod(0o755)
    r = bench.run("account", "set", "boulot", "--email", "dan@example.test", env={"SSHVAULT_BW": str(wrapper)})
    assert r.returncode == 2, r.stderr
    line = one_line_error(r)
    assert "registre non mis à jour" in line and "« zz »" in line and "registre inchangé" in line
    assert "déjà fait : déconnecté de l'ancien compte, session oubliée, 1 clé retirée des agents" in line, line
    assert registry(bench)["accounts"]["boulot"]["email"] == "bob@example.test"
    assert not bw_state(bench, "boulot").get("userId") and bench.agent_keys() == []


def test_account_set_bw_path_invalide_code_2(bench):
    two_accounts(bench)
    data = json.loads(bench.config_file().read_text())
    data["bw-path"] = "relatif"
    bench.config_file().write_text(json.dumps(data))
    before = bench.config_file().read_bytes()
    bench.env = bench.env_without_bw()  # bw-path lu : SSHVAULT_BW retiré
    r = bench.run("account", "set", "boulot", "--email", "dan@example.test")
    assert r.returncode == 2 and "bw-path" in one_line_error(r), r.stderr
    assert bench.config_file().read_bytes() == before


def test_status_serveur_et_email_differents_un_remede(bench):
    """Serveur et e-mail différents : une ligne, un seul `account set` avec les deux options."""
    bench.unlocked(where(bench))
    st = json.loads(bench.state_file().read_text())
    st.update(serverUrl="https://autre.example.test", userEmail="o'brien@example.test")
    bench.state_file().write_text(json.dumps(st))
    line = one_line_error(bench.run("status"))
    assert ("« sshvault account set alice --server https://autre.example.test --email "
            "'o'\"'\"'brien@example.test' »") in line, line
    assert line.count("account set") == 1


def test_status_couple_d_un_autre_alias(bench):
    """bw de boulot connecté au compte d'alice : seulement « logout » puis « login »."""
    two_accounts(bench)
    st = bw_state(bench, "boulot")
    st["userEmail"] = EMAIL
    (bench.appdata_of("boulot") / "data.json").write_text(json.dumps(st))
    line = one_line_error(bench.run("status", "--account", "boulot"))
    assert "account set" not in line and "l'alias « alice »" in line
    assert "« sshvault logout --account boulot » puis « sshvault login --account boulot »" in line


def test_status_valeur_de_bw_invalide(bench):
    """Valeurs de bw invalides : `--server URL`/`--email E` à saisir, puis login."""
    bench.unlocked(where(bench))
    st = json.loads(bench.state_file().read_text())
    st.update(serverUrl="ftp://autre.example.test", userEmail="pas-un-email")
    bench.state_file().write_text(json.dumps(st))
    line = one_line_error(bench.run("status"))
    assert "« sshvault account set alice --server URL --email E » puis « sshvault login --account alice »" in line


def _forward_setup(bench):
    import hashlib
    fwd = {"name": "sshvault-forward", "value": "relais", "type": 0, "linkedId": None}
    two_accounts(bench, boulot_items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], extra_fields=[fwd])])
    prod = next(i for i in bench.items if i.get("id") == ID_PROD)
    prod["fields"].append(dict(fwd))
    bench.write_vault()
    assert bench.run("config", "set", "forward-confirm", "false").returncode == 0
    assert bench.run("ssh-config").returncode == 0
    f = hashlib.sha256(b"relais").hexdigest()[:16]
    r = bench.run("ensure", "--forward", f, "--id", "alice:%s" % ID_PROD, "--id", "boulot:%s" % ID_B)
    assert r.returncode == 0, r.stderr
    return f, bench.runtime / "sshvault" / "fwd" / (f + ".sock")


@pytest.mark.parametrize("cmd", [["logout", "--account", "boulot"],
                                 ["account", "set", "boulot", "--email", "dan@example.test"]])
def test_logout_set_sous_agent_vide_de_la_cle(bench, cmd):
    from bench import agent_list
    f, sock = _forward_setup(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    r = bench.run(*cmd)
    assert r.returncode == 0, r.stderr
    assert "2 clés retirées des agents" in r.stdout, r.stdout
    assert [l.split()[1] for l in agent_list(sock)[1]] == [bench.blob("prod")]
    assert bench.agent_keys() == []
    st = json.loads((bench.runtime / "sshvault" / "fwd" / (f + ".json")).read_text())
    assert {e["account"] for e in st["keys"].values()} == {"alice"}


@pytest.mark.parametrize("cmd", [["logout", "--account", "boulot"],
                                 ["account", "set", "boulot", "--email", "dan@example.test"]])
def test_logout_set_sous_agent_verrouille_rien_retire(bench, cmd):
    """Agent dédié en ordre, sous-agent verrouillé : rien retiré nulle part, une ligne, code 4."""
    from bench import agent_list
    f, sock = _forward_setup(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    p = bench.runtime / "sshvault" / "fwd" / (f + ".json")
    st = json.loads(p.read_text())
    st["locked"] = True
    p.write_text(json.dumps(st))
    main_before = bench.agent_state()["keys"]
    r = bench.run(*cmd)
    assert r.returncode == 4
    line = one_line_error(r)
    assert "non retirées" in line and str(sock) in line
    assert bench.agent_keys() == [bench.blob("bastion")] and bench.agent_state()["keys"] == main_before
    assert sorted(l.split()[1] for l in agent_list(sock)[1]) == sorted([bench.blob("prod"), bench.blob("bastion")])
    assert bw_state(bench, "boulot").get("userId")


def test_logout_compte_verrouille_entree_d_avant_0_9(bench):
    """Compte verrouillé, entrée sans compte (avant la 0.9.0) : laissée, une ligne d'avertissement."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    edit_agent_state(bench, lambda d: [e.pop("account", None) for e in d["keys"].values()])
    assert bench.run("lock", "--account", "boulot").returncode == 0
    r = bench.run("logout", "--account", "boulot")
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == [bench.blob("bastion")]
    assert len([l for l in r.stderr.splitlines() if "avant la 0.9.0" in l and "laissée" in l]) == 1
    assert "compte boulot déconnecté" in r.stdout and "session oubliée" not in r.stdout



# --- story 11, revue 2 -------------------------------------------------------------------

def marker(bench, alias):
    """Marqueur `logged-out` du compte : dans son dossier persistant, à côté des données de bw."""
    return bench.appdata_of(alias).parent / "logged-out"


def external_login(bench, alias, email, server=SERVER):
    """bw reconnecté hors de sshvault (verrouillé, aucune session rangée)."""
    st = bw_state(bench, alias)
    st.update(userId="aaaaaaaa-0000-4000-8000-000000000002", userEmail=email, serverUrl=server,
              lastSync="2026-10-06T00:00:00.000Z")
    st.pop("session", None)
    if alias == ALIAS:
        st["vault"] = str(bench.vault_file)
    else:
        st["vault"] = str(bench.account_vault(alias))
    (bench.appdata_of(alias) / "data.json").write_text(json.dumps(st))


def test_check_apres_logout_seul_compte_a_jour(bench):
    """Critère : après `logout` du seul compte, `ssh-config --check` à jour (blocs gardés)."""
    bench.unlocked(where(bench))
    assert bench.run("ssh-config").returncode == 0 and bench.run("ssh-config", "install").returncode == 0
    assert bench.run("logout").returncode == 0
    r = bench.run("--nointeraction", "ssh-config", "--check")
    assert r.returncode == 0 and "à jour" in r.stdout, (r.stdout, r.stderr)
    line = one_line_error(r)
    assert "« sshvault login --account alice »" in line and "unlock" not in line, line


def test_check_seul_compte_verrouille_code_3(bench):
    """Compte seulement verrouillé (pas déconnecté) : `--check` comme avant la story, code 3."""
    bench.unlocked(where(bench))
    assert bench.run("ssh-config").returncode == 0 and bench.run("ssh-config", "install").returncode == 0
    assert bench.run("lock").returncode == 0
    r = bench.run("--nointeraction", "ssh-config", "--check")
    assert r.returncode == 3 and "verrouillé" in one_line_error(r) and r.stdout == ""


@pytest.mark.parametrize("broken", [{"SSHVAULT_BW": "/nonexistent/bw"}, {"FAKE_BW_FAIL": "status=error"}])
def test_check_bw_casse_jamais_a_jour(bench, broken):
    """bw absent ou en erreur, compte déconnecté : `--check` rend le code de l'erreur, jamais 0."""
    bench.unlocked(where(bench))
    assert bench.run("ssh-config").returncode == 0 and bench.run("ssh-config", "install").returncode == 0
    assert bench.run("logout").returncode == 0
    r = bench.run("--nointeraction", "ssh-config", "--check", env=broken)
    assert r.returncode == 4 and "à jour" not in r.stdout, (r.stdout, r.stderr)


def test_check_deux_comptes_un_deconnecte_un_verrouille(bench):
    """Tous illisibles, l'un déconnecté, l'autre verrouillé : code 3 (le verrouillé), comme avant."""
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0 and bench.run("ssh-config", "install").returncode == 0
    assert bench.run("logout", "--account", "boulot").returncode == 0
    assert bench.run("lock", "--account", "alice").returncode == 0
    r = bench.run("--nointeraction", "ssh-config", "--check")
    assert r.returncode == 3 and "à jour" not in r.stdout, (r.stdout, r.stderr)
    assert bench.run("unlock", "--account", "alice", env=askpass_env(bench)[0]).returncode == 0
    r = bench.run("--nointeraction", "ssh-config", "--check")
    assert r.returncode == 0 and "à jour" in r.stdout, (r.stdout, r.stderr)


def test_logout_agent_verrouille_session_perimee_gardee(bench):
    """Agent verrouillé, session rangée que bw refuse (périmée) : code 4 « rien modifié », la
    session rangée n'est pas touchée (sonde de l'état sans effet)."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    assert bench.run("agent", "lock", env=askpass_env(bench)[0]).returncode == 0
    st = bw_state(bench, "boulot")
    st["session"] = "c2Vzc2lvbi1hdXRyZS0xMjM0NTY3ODkwMTI="  # bw ne reconnaît plus la session rangée
    (bench.appdata_of("boulot") / "data.json").write_text(json.dumps(st))
    before = bench.stored_session("boulot")
    assert before != (None, None)
    for cmd in (["logout", "--account", "boulot"], ["account", "set", "boulot", "--email", "dan@example.test"]):
        r = bench.run(*cmd)
        assert r.returncode == 4 and "non retirées" in one_line_error(r)
        assert bench.stored_session("boulot") == before, cmd


def test_marqueur_retire_par_unlock_et_status(bench):
    """bw reconnecté hors de sshvault : `unlock` réussi, ou `status` qui voit bw connecté,
    retirent le marqueur."""
    two_accounts(bench)
    for cmd in (["unlock", "--account", "boulot"], ["status", "--account", "boulot"]):
        assert bench.run("logout", "--account", "boulot").returncode == 0
        assert marker(bench, "boulot").exists()
        external_login(bench, "boulot", "bob@example.test")
        r = bench.run(*cmd, env=askpass_env(bench)[0])
        assert not marker(bench, "boulot").exists(), (cmd, r.stderr)


def test_marqueur_retire_par_set_registre_seul(bench):
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    external_login(bench, "boulot", "bob@example.test")
    bench.accounts["boulot"] = (SERVER, "bobby@example.test")
    bench.write_registry()
    r = bench.run("account", "set", "boulot", "--email", "bob@example.test")
    assert r.returncode == 0 and "registre corrigé" in r.stdout, r.stderr
    assert not marker(bench, "boulot").exists()


def test_marqueur_suit_rename_et_part_avec_remove(bench):
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    assert bench.run("account", "rename", "boulot", "travail").returncode == 0
    assert marker(bench, "travail").exists() and not marker(bench, "boulot").exists()
    r = bench.run("--nointeraction", "ensure", "--account", "travail", "--id", ID_B)
    assert r.returncode == 3 and "« sshvault login --account travail »" in one_line_error(r)
    assert bench.run("account", "remove", "travail").returncode == 0
    assert not marker(bench, "travail").exists()
    bench.add_account("travail", "bob@example.test", logged_in=False)
    r = bench.run("--nointeraction", "ensure", "--account", "travail", "--id", ID_B)
    assert "sshvault logout" not in r.stderr, "ancien marqueur parti avec le compte"


def test_marqueur_persistant_hors_du_runtime(bench):
    """Le marqueur survit à un dossier runtime vidé (redémarrage) : ensure propose toujours login."""
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    assert marker(bench, "boulot").exists() and not list(bench.runtime.rglob("logged-out*"))
    shutil.rmtree(str(bench.runtime / "sshvault"), ignore_errors=True)
    r = bench.run("--nointeraction", "ensure", "--account", "boulot", "--id", ID_B)
    assert r.returncode == 3 and "« sshvault login --account boulot »" in one_line_error(r)


def test_marqueur_lu_par_le_chemin_rapide(bench):
    """Le chemin rapide dit la ligne sans charger la CLI (délai d'invite invalide : la CLI
    refuserait en code 2)."""
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    r = bench.run("--nointeraction", "ensure", "--account", "boulot", "--id", ID_B,
                  env={"SSHVAULT_PROMPT_TIMEOUT": "invalide"})
    assert r.returncode == 3, r.stderr
    assert "« sshvault login --account boulot »" in one_line_error(r)


def test_marqueur_lu_par_ensure_cli(bench, monkeypatch):
    """`ensure._unlock_possible` (CLI) : sans session, marqueur présent → « lancer login »."""
    from sshvault import ensure as ensure_mod
    from sshvault.backend import NotLoggedIn
    from sshvault.session import SessionStore
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    monkeypatch.setenv("HOME", str(bench.home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    store = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(bench.runtime), alias="boulot")
    with pytest.raises(NotLoggedIn, match="sshvault login --account boulot"):
        ensure_mod._unlock_possible(str(bench.runtime / "sshvault"), store, dict(os.environ),
                                    ensure_mod.Context(interactive=False, why_not="--nointeraction"), "boulot")


def test_logout_rien_a_faire_aucun_marqueur(bench):
    """Compte jamais connecté : « rien à faire », ni marqueur, ni dossier du compte ou runtime créé."""
    bench.unlocked(where(bench))
    bench.add_account("client", "carol@client.test", server=OTHER, logged_in=False)
    shutil.rmtree(str(bench.runtime / "sshvault"), ignore_errors=True)
    r = bench.run("logout", "--account", "client")
    assert r.stdout == "compte client non connecté : rien à faire\n"
    assert not bench.appdata_of("client").parent.exists() and not marker(bench, "client").exists()
    assert not (bench.runtime / "sshvault").exists(), "aucun dossier runtime créé"
    # mémoire d'échec de déverrouillage : pas touchée non plus
    (bench.runtime / "sshvault").mkdir(mode=0o700)
    failed = bench.runtime / "sshvault" / "unlock-failed.client"
    failed.write_text("%d 1:2\n" % int(time.time()))
    failed.chmod(0o600)
    r = bench.run("logout", "--account", "client")
    assert r.stdout == "compte client non connecté : rien à faire\n" and failed.exists()
    # données de bw présentes mais déconnectées, ni clé ni session : rien écrit non plus
    bench.add_account("dani", "dani@client.test", server=OTHER)
    (bench.appdata_of("dani") / "data.json").write_text(json.dumps({"stateVersion": 85, "serverUrl": OTHER}))
    r = bench.run("logout", "--account", "dani")
    assert r.stdout == "compte dani non connecté : rien à faire\n" and not marker(bench, "dani").exists()


def test_logout_marqueur_non_pose_averti(bench):
    two_accounts(bench)
    marker(bench, "boulot").mkdir()
    r = bench.run("logout", "--account", "boulot")
    assert r.returncode == 0 and "compte boulot déconnecté" in r.stdout
    line = one_line_error(r)
    assert "avertissement : marqueur" in line and "non posé" in line
    # un dossier n'est pas un marqueur : ensure ne propose pas login (ce que l'avertissement dit)
    r = bench.run("--nointeraction", "ensure", "--account", "boulot", "--id", ID_B)
    assert "sshvault logout" not in r.stderr, r.stderr


def bw_wrapper_script(bench, name, on_logout):
    w = bench.tmp / name
    w.write_text("#!/bin/sh\ncase \"$*\" in *logout*) %s;; esac\nexec '%s' \"$@\"\n" % (on_logout, bench.bw))
    w.chmod(0o755)
    return {"SSHVAULT_BW": str(w)}


def test_logout_bw_deja_deconnecte_entre_temps(bench):
    """bw dit « You are not logged in. » au logout (course) : « non connecté », pas « déconnecté »."""
    two_accounts(bench)
    env = bw_wrapper_script(bench, "bw-plus", "echo 'You are not logged in.' >&2; exit 1")
    r = bench.run("logout", "--account", "boulot", env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("compte boulot non connecté : session oubliée")


def test_login_apikey_logout_etat_inconnu(bench, monkeypatch):
    from bench import ALIAS as A
    from sshvault.backend import BackendError, LogoutUnknown
    from sshvault.bw import BwBackend
    from sshvault.session import SessionStore
    for k, v in bench.env.items():
        if k.startswith(("FAKE_BW_", "SSHVAULT_KEYCTL", "SSHVAULT_KEYRING")):
            monkeypatch.setenv(k, v)
    monkeypatch.setenv("BW_CLIENTID", "user.aaaa")
    monkeypatch.setenv("BW_CLIENTSECRET", "apisecret")
    bench.set_state(logged_in=False)
    b = BwBackend(store=SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(bench.runtime), alias=A),
                  exe=str(bench.bw), appdata=str(bench.appdata), timeout=30, email="bob@example.test", label="boulot")

    def unknown():
        raise LogoutUnknown("bw sans réponse")
    monkeypatch.setattr(b, "logout", unknown)
    with pytest.raises(BackendError, match="état de connexion inconnu"):
        b.login(apikey=True)


def test_status_serveur_nul_serveur_par_defaut(bench):
    """`serverUrl` nul = serveur par défaut de bw, pour `status` comme pour `account set` : le
    remède proposé corrige le registre seul."""
    bench.unlocked(where(bench))
    assert bench.run("ssh-config").returncode == 0
    st = json.loads(bench.state_file().read_text())
    st["serverUrl"] = None
    bench.state_file().write_text(json.dumps(st))
    r = bench.run("status")
    line = one_line_error(r)
    assert "« sshvault account set alice --server https://vault.bitwarden.com »" in line, line
    assert "serveur : https://vault.bitwarden.com\n" in r.stdout, r.stdout
    before = config_text(bench)
    r = bench.run("account", "set", "alice", "--server", "https://vault.bitwarden.com")
    assert r.returncode == 0 and "registre corrigé" in r.stdout, r.stderr
    assert bench.stored_session() != (None, None) and config_text(bench) == before
    r = bench.run("status")
    assert r.returncode == 0 and r.stderr == "", r.stderr


def test_status_serveur_different_puis_set_registre_seul(bench):
    two_accounts(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    st = json.loads(bench.state_file().read_text())
    st["serverUrl"] = "https://autre.example.test:443/"
    bench.state_file().write_text(json.dumps(st))
    before = config_text(bench)
    n = len(bench.calls())
    r = bench.run("account", "set", "alice", "--server", "https://autre.example.test")
    assert r.returncode == 0 and "registre corrigé" in r.stdout, r.stderr
    assert not any(c["argv"][1:2] == ["logout"] for c in bench.calls()[n:])
    assert bench.agent_keys() == [bench.blob("prod")] and config_text(bench) == before
    assert bench.stored_session() != (None, None)


def test_logout_cle_disparue_entre_les_passes(bench):
    """`ssh-add -d` qui échoue parce que la clé est déjà partie, l'agent listant encore une autre
    clé (pas verrouillé) : comptée comme retirée."""
    two_accounts(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    from bench import SSH_ADD
    w = bench.tmp / "ssh-add-course"
    w.write_text("#!/bin/sh\nif [ \"$1\" = -d ]; then '%s' \"$@\" >/dev/null 2>&1; echo 'agent refused' >&2; exit 1; fi\n"
                 "exec '%s' \"$@\"\n" % (SSH_ADD, SSH_ADD))
    w.chmod(0o755)
    r = bench.run("logout", "--account", "boulot", env={"SSHVAULT_SSH_ADD": str(w)})
    assert r.returncode == 0, r.stderr
    assert bench.agent_keys() == [bench.blob("prod")]
    assert list(bench.agent_state()["keys"]) == [bench.keys["prod"]["fingerprint"]]
    assert "1 clé retirée des agents" in r.stdout, r.stdout


def test_logout_etat_partiel_dit(bench):
    """Agent dédié mis à jour puis sous-agent en erreur au retrait : la ligne dit l'état partiel."""
    from bench import SSH_ADD
    f, sock = _forward_setup(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    w = bench.tmp / "ssh-add-fwd"
    w.write_text("#!/bin/sh\ncase \"$SSH_AUTH_SOCK:$1\" in *fwd/*:-d) echo 'agent refused' >&2; exit 1;; esac\n"
                 "exec '%s' \"$@\"\n" % SSH_ADD)
    w.chmod(0o755)
    r = bench.run("logout", "--account", "boulot", env={"SSHVAULT_SSH_ADD": str(w)})
    assert r.returncode == 4
    line = one_line_error(r)
    assert "état partiel : 1 clé retirée des agents" in line and str(bench.sock()) in line, line
    assert "compte toujours connecté" not in line


def test_logout_non_connecte_cle_partagee_promue_pas_rien_a_faire(bench):
    two_accounts(bench, boulot_items=[ssh_item(ID_B, "Copie", bench.keys["prod"], hosts="b")])
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("ensure", "--account", "alice", "--id", ID_PROD).returncode == 0
    assert bench.run("ensure", "--account", "boulot", "--id", ID_B).returncode == 0
    assert bench.run("lock", "--account", "alice").returncode == 0
    bench.set_state(logged_in=False)
    r = bench.run("logout", "--account", "alice")
    assert r.returncode == 0, r.stderr
    assert "rien à faire" not in r.stdout and "0 clé retirée" in r.stdout
    assert bench.agent_state()["keys"][bench.keys["prod"]["fingerprint"]]["account"] == "boulot"


def test_logout_sans_entree_d_avant_0_9_aucun_bw_list(bench):
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    n = len(bench.calls())
    assert bench.run("logout", "--account", "boulot").returncode == 0
    assert not [c for c in bench.calls()[n:] if c["argv"][1:3] == ["list", "items"]]


@pytest.mark.parametrize("reread,msg", [(None, "toujours connectées sous l'alias boulot"),
                                        ("status=errorsecond", "état de connexion inconnu")])
def test_logout_bw_sans_reponse(bench, reread, msg):
    """`bw logout` bloqué : tué au délai, état relu ; toujours connecté, ou inconnu si la
    relecture échoue. Code 4, une ligne, session oubliée, aucun bw restant."""
    two_accounts(bench)
    fail = "logout=hang" + ("," + reread if reread else "")
    r = bench.run("logout", "--account", "boulot", env={"FAKE_BW_FAIL": fail, "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 4, r.stderr
    line = one_line_error(r)
    assert "bw logout en échec" in line and msg in line and "session oubliée" in line, line
    assert bench.stored_session("boulot") == (None, None)
    assert marker(bench, "boulot").exists() == (reread is not None), "état inconnu : marqueur posé"
    pids = [int(x) for x in bench.pids.read_text().split()] if bench.pids.exists() else []
    from bench import wait_gone
    assert wait_gone(pids), "bw tué"


def test_logout_bw_path_invalide_code_2(bench):
    two_accounts(bench)
    data = json.loads(bench.config_file().read_text())
    data["bw-path"] = "relatif"
    bench.config_file().write_text(json.dumps(data))
    bench.env = bench.env_without_bw()
    r = bench.run("logout", "--account", "boulot")
    assert r.returncode == 2 and "bw-path" in one_line_error(r), r.stderr
    assert bw_state(bench, "boulot").get("userId")


def test_account_set_sans_donnees_bw_path_invalide_code_2(bench):
    bench.unlocked(where(bench))
    bench.add_account("client", "carol@client.test", server=OTHER, logged_in=False)
    data = json.loads(bench.config_file().read_text())
    data["bw-path"] = "relatif"
    bench.config_file().write_text(json.dumps(data))
    before = bench.config_file().read_bytes()
    bench.env = bench.env_without_bw()
    r = bench.run("account", "set", "client", "--email", "carole@client.test")
    assert r.returncode == 2 and "bw-path" in one_line_error(r), r.stderr
    assert bench.config_file().read_bytes() == before


def test_account_set_ecriture_du_registre_impossible_code_4(bench):
    """Écriture de config.json impossible après la déconnexion (temporaire de sshvault occupé) :
    une ligne qui dit ce qui est fait, registre inchangé, code 4."""
    two_accounts(bench)
    cfg = bench.config_file()
    env = bw_wrapper_script(bench, "bw-bloque", "mkdir '%s/.config.json.'$PPID'.tmp'" % cfg.parent)
    r = bench.run("account", "set", "boulot", "--email", "dan@example.test", env=env)
    assert r.returncode == 4, r.stderr
    line = one_line_error(r)
    assert "registre non mis à jour" in line and "déjà fait : déconnecté de l'ancien compte" in line, line
    assert "registre inchangé" in line
    assert registry(bench)["accounts"]["boulot"]["email"] == "bob@example.test"


def test_logout_sans_donnees_session_oubliee_dossier_non_cree(bench):
    """Données de bw absentes mais session rangée : session oubliée ; le marqueur n'est pas
    posé (aucun dossier du compte créé)."""
    bench.unlocked(where(bench))
    bench.add_account("client", "carol@client.test", server=OTHER, logged_in=False)
    bench.store_session("c2Vzc2lvbi1jbGllbnQtMTIzNDU2Nzg5MA==", where(bench), alias="client")
    r = bench.run("logout", "--account", "client")
    assert r.returncode == 0 and r.stdout.startswith("compte client non connecté : session oubliée"), (r.stdout, r.stderr)
    assert bench.stored_session("client") == (None, None)
    assert not bench.appdata_of("client").parent.exists()



# --- story 11, revue 3 -------------------------------------------------------------------

def _ssh_add_script(bench, name, body):
    w = bench.tmp / name
    w.write_text("#!/bin/sh\n%s\n" % body)
    w.chmod(0o755)
    return {"SSHVAULT_SSH_ADD": str(w)}


def test_logout_echec_dans_le_premier_agent_etat_partiel(bench):
    """Agent dédié seul, deux clés du compte : la 1re retirée, la 2e refusée (toujours listée) :
    la ligne dit l'état partiel et nomme l'agent en cours, pas « rien modifié »."""
    from bench import SSH_ADD
    two_accounts(bench, boulot_items=[ssh_item(ID_B, "Cible B", bench.keys["bastion"], hosts="b"),
                                      ssh_item(ID_D, "Cible D", bench.keys["perso"], hosts="d")])
    assert bench.run("load", "--account", "boulot", "--all").returncode == 0
    flag = bench.tmp / "un-retrait"
    env = _ssh_add_script(bench, "ssh-add-un", "if [ \"$1\" = -d ]; then if [ -e '%s' ]; then echo 'agent refused' >&2; "
                                               "exit 1; fi; touch '%s'; fi\nexec '%s' \"$@\"" % (flag, flag, SSH_ADD))
    r = bench.run("logout", "--account", "boulot", env=env)
    assert r.returncode == 4
    line = one_line_error(r)
    assert "état partiel : 1 clé retirée des agents, agent %s partiellement modifié" % bench.sock() in line, line
    assert "rien modifié" not in line
    assert len(bench.agent_keys()) == 1


def test_logout_bw_path_invalide_sans_donnees_rien_fait(bench):
    """`bw-path` invalide, pas de données de bw, session rangée et clé chargée : code 2, rien fait."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    shutil.rmtree(str(bench.appdata_of("boulot")))
    data = json.loads(bench.config_file().read_text())
    data["bw-path"] = "relatif"
    bench.config_file().write_text(json.dumps(data))
    session = bench.stored_session("boulot")
    state = bench.agent_state()["keys"]
    bench.env = bench.env_without_bw()
    r = bench.run("logout", "--account", "boulot")
    assert r.returncode == 2 and "bw-path" in one_line_error(r), r.stderr
    assert bench.stored_session("boulot") == session and bench.agent_keys() == [bench.blob("bastion")]
    assert bench.agent_state()["keys"] == state


def test_login_deja_connecte_retire_le_marqueur(bench):
    """bw reconnecté hors de sshvault : `login` échoue « déjà connecté » mais retire le marqueur."""
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    external_login(bench, "boulot", "bob@example.test")
    p = login(bench, "boulot")
    assert p.returncode == 4 and "déjà connecté" in p.stderr, p.stderr
    assert not marker(bench, "boulot").exists()


def test_deverrouillage_par_invite_retire_le_marqueur(bench):
    """Session rangée refusée par bw (verrouillé), `list` déverrouille par l'invite : le
    marqueur est retiré par ce déverrouillage (sans `bw status`)."""
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    external_login(bench, "boulot", "bob@example.test")
    bench.store_session("c2Vzc2lvbi1wZXJpbWVlLTEyMzQ1Njc4OTA=", where(bench), alias="boulot")
    n = len(bench.calls())
    r = bench.run("list", "--account", "boulot", env=askpass_env(bench)[0])
    assert r.returncode == 0, r.stderr
    assert not [c for c in bench.calls()[n:] if c["argv"][1:2] == ["status"]], "pas de bw status sur ce chemin"
    assert not marker(bench, "boulot").exists()


def test_chemin_rapide_agent_verrouille_laisse_la_cli(bench):
    """Marqueur présent, agent dédié verrouillé : pas de ligne « déconnecté » du chemin rapide ;
    la CLI dit l'agent verrouillé."""
    two_accounts(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    assert bench.run("logout", "--account", "boulot").returncode == 0
    assert bench.run("agent", "lock", env=askpass_env(bench)[0]).returncode == 0
    r = bench.run("--nointeraction", "ensure", "--account", "boulot", "--id", ID_B)
    line = one_line_error(r)
    assert "déconnecté" not in line and "verrouillé" in line, line


def test_logout_agent_verrouille_entre_les_passes(bench):
    """Agent verrouillé entre la vérification et le retrait (ne liste plus rien) : la clé n'est
    pas prise pour « partie » ; code 4, entrée d'état gardée."""
    from bench import SSH_ADD
    two_accounts(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    prog, _ = make_askpass(bench.tmp, name="askpass-verrou")
    env = _ssh_add_script(bench, "ssh-add-verrou",
                          "if [ \"$1\" = -d ]; then SSH_ASKPASS='%s' SSH_ASKPASS_REQUIRE=force '%s' -x </dev/null "
                          ">/dev/null 2>&1; echo 'agent refused operation' >&2; exit 1; fi\nexec '%s' \"$@\""
                          % (prog, SSH_ADD, SSH_ADD))
    r = bench.run("logout", "--account", "boulot", env=env)
    assert r.returncode == 4
    line = one_line_error(r)
    assert "agent verrouillé" in line, line
    assert bench.keys["bastion"]["fingerprint"] in bench.agent_state()["keys"], "entrée gardée"


def test_logout_entree_d_avant_0_9_agent_verrouille_aucun_bw(bench):
    """Entrée sans compte, agent verrouillé, session rangée périmée : arrêt avant tout `bw list`
    (seule la sonde `bw status`, sans session), session rangée intacte."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    edit_agent_state(bench, lambda d: [e.pop("account", None) for e in d["keys"].values()])
    assert bench.run("agent", "lock", env=askpass_env(bench)[0]).returncode == 0
    st = bw_state(bench, "boulot")
    st["session"] = "c2Vzc2lvbi1hdXRyZS0xMjM0NTY3ODkwMTI="
    (bench.appdata_of("boulot") / "data.json").write_text(json.dumps(st))
    before = bench.stored_session("boulot")
    n = len(bench.calls())
    r = bench.run("logout", "--account", "boulot")
    assert r.returncode == 4 and "rien modifié" in one_line_error(r)
    calls = bench.calls()[n:]
    assert [c["argv"] for c in calls] == [["--nointeraction", "status"]] and not calls[0]["session_env"], calls
    assert bench.stored_session("boulot") == before


def test_logout_bw_status_en_erreur_logout_tente(bench):
    """`bw status` en erreur : clés retirées, session oubliée, `bw logout` tenté ; réussi : déconnecté."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    r = bench.run("logout", "--account", "boulot", env={"FAKE_BW_FAIL": "status=error"})
    assert r.returncode == 0, r.stderr
    assert "compte boulot déconnecté : session oubliée, 1 clé retirée des agents" in r.stdout
    assert not bw_state(bench, "boulot").get("userId") and marker(bench, "boulot").exists()


def test_logout_bw_status_et_logout_en_erreur_etat_inconnu(bench):
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    r = bench.run("logout", "--account", "boulot", env={"FAKE_BW_FAIL": "status=error,logout=error"})
    assert r.returncode == 4
    line = one_line_error(r)
    assert "état de connexion inconnu" in line and "1 clé retirée des agents, session oubliée" in line, line
    assert bench.agent_keys() == [] and bench.stored_session("boulot") == (None, None)
    assert marker(bench, "boulot").exists(), "état inconnu : marqueur posé"


def test_account_set_bw_status_en_erreur_rien_fait(bench):
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    before = bench.config_file().read_bytes()
    session = bench.stored_session("boulot")
    r = bench.run("account", "set", "boulot", "--email", "dan@example.test", env={"FAKE_BW_FAIL": "status=error"})
    assert r.returncode == 4
    line = one_line_error(r)
    assert "état de connexion de bw inconnu : rien fait" in line, line
    assert bench.config_file().read_bytes() == before and bench.agent_keys() == [bench.blob("bastion")]
    assert bench.stored_session("boulot") == session and bw_state(bench, "boulot").get("userId")


def test_logout_magasin_de_session_en_erreur_pas_rien_a_faire(bench, monkeypatch, capsys):
    """Magasin de session en erreur : l'absence de session n'est pas sûre, pas « rien à faire »."""
    from sshvault import cli
    from sshvault.session import SessionStore, SessionStoreError
    bench.unlocked(where(bench))
    bench.add_account("client", "carol@client.test", server=OTHER, logged_in=False)
    for k in list(os.environ):
        if k.startswith(("SSHVAULT_", "FAKE_BW_", "XDG_")):
            monkeypatch.delenv(k, raising=False)
    for k, v in bench.env.items():
        monkeypatch.setenv(k, v)

    def broken(self):
        raise SessionStoreError("magasin en panne")
    monkeypatch.setattr(SessionStore, "get", broken)
    monkeypatch.setattr(SessionStore, "clear", broken)
    rc = cli.main(["logout", "--account", "client"])
    out, errs = capsys.readouterr()
    assert rc == 0 and "rien à faire" not in out and out.startswith("compte client non connecté : 0 clé"), (out, errs)
    assert "session non oubliée : magasin en panne" in errs


# --- story 11, revue 4 -------------------------------------------------------------------

def test_login_apikey_autre_compte_marqueur_garde(bench):
    """`logout` (marqueur), puis `login --apikey` avec la clé d'un autre compte : bw vu connecté
    (à l'autre compte) puis déconnecté ; le compte finit avec son marqueur."""
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    assert marker(bench, "boulot").exists()
    r = bench.run("login", "--apikey", "--account", "boulot",
                  env={"BW_CLIENTID": "user.aaaa", "BW_CLIENTSECRET": "apisecret"})
    assert r.returncode == 4 and "pas de bob@example.test" in r.stderr.splitlines()[-1]
    assert not bw_state(bench, "boulot").get("userId")
    assert marker(bench, "boulot").exists(), "marqueur reposé"


def test_account_set_registre_seul_agent_verrouille(bench):
    """Paire déjà connectée (registre seul faux), agent verrouillé : registre corrigé, code 0."""
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    assert bench.run("agent", "lock", env=askpass_env(bench)[0]).returncode == 0
    bench.accounts["boulot"] = (SERVER, "bobby@example.test")
    bench.write_registry()
    r = bench.run("account", "set", "boulot", "--email", "bob@example.test")
    assert r.returncode == 0 and "registre corrigé" in r.stdout, r.stderr
    assert registry(bench)["accounts"]["boulot"]["email"] == "bob@example.test"


def test_logout_agent_du_seul_compte_verrouille_entre_les_passes(bench):
    """Agent qui ne porte que les clés du compte, verrouillé entre les passes : code 4, entrée
    gardée (aucune info sûre = tout garder)."""
    from bench import SSH_ADD
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    prog, _ = make_askpass(bench.tmp, name="askpass-verrou-seul")
    env = _ssh_add_script(bench, "ssh-add-verrou-seul",
                          "if [ \"$1\" = -d ]; then SSH_ASKPASS='%s' SSH_ASKPASS_REQUIRE=force '%s' -x </dev/null "
                          ">/dev/null 2>&1; echo 'agent refused operation' >&2; exit 1; fi\nexec '%s' \"$@\""
                          % (prog, SSH_ADD, SSH_ADD))
    r = bench.run("logout", "--account", "boulot", env=env)
    assert r.returncode == 4 and "agent verrouillé" in one_line_error(r), r.stderr
    assert bench.keys["bastion"]["fingerprint"] in bench.agent_state()["keys"], "entrée gardée"


def test_logout_cle_expiree_partie_comptee(bench):
    """Clé dont la durée de vie est écoulée (état), partie au retrait, agent vide : comptée partie."""
    from bench import SSH_ADD
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    edit_agent_state(bench, lambda d: [e.update(loaded=time.time() - 7200, lifetime=3600)
                                       for e in d["keys"].values()])
    env = _ssh_add_script(bench, "ssh-add-expiree", "if [ \"$1\" = -d ]; then '%s' \"$@\" >/dev/null 2>&1; "
                                                   "echo 'agent refused' >&2; exit 1; fi\nexec '%s' \"$@\""
                          % (SSH_ADD, SSH_ADD))
    r = bench.run("logout", "--account", "boulot", env=env)
    assert r.returncode == 0, r.stderr
    assert "1 clé retirée des agents" in r.stdout and bench.agent_state()["keys"] == {}


def test_logout_cle_chargee_pendant_la_commande_avertie(bench):
    """Entrée du compte apparue dans l'état pendant le retrait (load hors verrou) : laissée,
    entrée gardée, une ligne d'avertissement."""
    from bench import SSH_ADD
    two_accounts(bench)
    assert bench.run("load", "--account", "boulot", "--id", ID_B).returncode == 0
    state = bench.runtime / "sshvault" / "agent.json"
    late = entry(ID_D, "boulot", name="Arrivée")
    adder = bench.tmp / "ajoute.py"
    adder.write_text("import json,sys\np=sys.argv[1]\nd=json.load(open(p))\nd['keys'][%r]=%r\nopen(p,'w').write(json.dumps(d))\n"
                     % (bench.keys["perso"]["fingerprint"], late))
    env = _ssh_add_script(bench, "ssh-add-course-load", "if [ \"$1\" = -d ]; then '%s' '%s' '%s'; fi\nexec '%s' \"$@\""
                          % (sys.executable, adder, state, SSH_ADD))
    r = bench.run("logout", "--account", "boulot", env=env)
    assert r.returncode == 0, r.stderr
    line = one_line_error(r)
    assert "1 clé de boulot chargée pendant la commande laissée" in line and "agent purge" in line, line
    assert bench.keys["perso"]["fingerprint"] in bench.agent_state()["keys"], "entrée gardée"


@pytest.mark.parametrize("cmd", [["logout", "--account", "boulot"],
                                 ["account", "set", "boulot", "--email", "dan@example.test"]])
def test_sonde_connecte_puis_logout_non_connecte_marqueur_repose(bench, cmd):
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    external_login(bench, "boulot", "bob@example.test")
    env = bw_wrapper_script(bench, "bw-plus-connecte", "echo 'You are not logged in.' >&2; exit 1")
    r = bench.run(*cmd, env=env)
    assert r.returncode == 0, r.stderr
    assert marker(bench, "boulot").exists(), "vu connecté puis non connecté : marqueur reposé"


def test_logout_status_en_erreur_relecture_connecte_pas_inconnu(bench):
    """`bw status` en erreur, `bw logout` sans réponse, relecture : toujours connecté. La ligne
    dit « toujours connectées », pas « inconnu » ; aucun marqueur."""
    two_accounts(bench)
    r = bench.run("logout", "--account", "boulot",
                  env={"FAKE_BW_FAIL": "status=erroronce,logout=hang", "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 4
    line = one_line_error(r)
    assert "toujours connectées sous l'alias boulot" in line and "inconnu" not in line, line
    assert not marker(bench, "boulot").exists()


def test_logout_bw_introuvable_remede_une_fois(bench):
    two_accounts(bench)
    r = bench.run("logout", "--account", "boulot", env={"SSHVAULT_BW": "/nonexistent/bw"})
    assert r.returncode == 4
    line = one_line_error(r)
    assert "état de connexion inconnu" in line and line.count("bw introuvable") == 1, line


def test_marqueur_non_retire_averti_une_fois(bench):
    """Marqueur impossible à retirer (dossier du compte en lecture seule) : un seul avertissement
    pour `unlock` (bw status puis déverrouillage)."""
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    external_login(bench, "boulot", "bob@example.test")
    d = bench.appdata_of("boulot").parent
    d.chmod(0o500)
    try:
        r = bench.run("unlock", "--account", "boulot", env=askpass_env(bench)[0])
        assert r.returncode == 0, r.stderr
        assert r.stderr.count("non retiré") == 1, r.stderr
    finally:
        d.chmod(0o700)


def test_marqueur_pas_d_avertissement_non_retire_quand_la_commande_pose(bench):
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    external_login(bench, "boulot", "bob@example.test")
    d = bench.appdata_of("boulot").parent
    d.chmod(0o500)  # la sonde ne peut pas retirer ; la pose (dossier ramené à 0700) réussit
    try:
        r = bench.run("logout", "--account", "boulot")
    finally:
        d.chmod(0o700)
    assert r.returncode == 0, r.stderr
    assert "non retiré" not in r.stderr and marker(bench, "boulot").exists()


def test_check_une_seule_forme_de_login(bench):
    bench.unlocked(where(bench))
    assert bench.run("ssh-config").returncode == 0 and bench.run("ssh-config", "install").returncode == 0
    assert bench.run("logout").returncode == 0
    r = bench.run("--nointeraction", "ssh-config", "--check")
    assert r.returncode == 0 and r.stderr.count("sshvault login") == 1, r.stderr
    assert "« sshvault login --account alice »" in r.stderr and "unlock" not in r.stderr, r.stderr


def test_login_branche_d_echec_retire_le_marqueur(bench):
    """Sonde d'avant le login : non connecté (marqueur gardé) ; bw se connecte pendant le login
    puis échoue : la relecture de la branche d'échec voit bw connecté et retire le marqueur."""
    two_accounts(bench)
    assert bench.run("logout", "--account", "boulot").returncode == 0
    connected = bench.tmp / "boulot-connecte.json"
    st = bw_state(bench, "boulot")
    st.update(userId="aaaaaaaa-0000-4000-8000-000000000002", userEmail="bob@example.test",
              lastSync="2026-10-06T00:00:00.000Z", vault=str(bench.account_vault("boulot")))
    connected.write_text(json.dumps(st))
    w = bench.tmp / "bw-login-tue"
    w.write_text("#!/bin/sh\ncase \"$*\" in *login*) cp '%s' '%s'; echo 'interrompu' >&2; exit 1;; esac\n"
                 "exec '%s' \"$@\"\n" % (connected, bench.appdata_of("boulot") / "data.json", bench.bw))
    w.chmod(0o755)
    calls = len(bench.calls())
    p = subprocess.run([sys.executable, "-m", "sshvault", "login", "--account", "boulot"],
                       env=dict(bench.env, SSHVAULT_BW=str(w)), input="%s\n" % PASSWORD, capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 4 and "déjà connecté" in p.stderr, p.stderr
    status_calls = [c for c in bench.calls()[calls:] if c["argv"][-1:] == ["status"]]
    assert len(status_calls) == 2, "sonde d'avant (non connecté) puis relecture de la branche d'échec"
    assert not marker(bench, "boulot").exists()


def test_chemin_rapide_agent_verrouille_hors_sshvault(bench):
    """Marqueur, agent verrouillé par `ssh-add -x` hors sshvault (état avec clés, agent qui n'en
    liste aucune) : le chemin rapide ne répond pas, la CLI tranche."""
    from bench import SSH_ADD
    two_accounts(bench)
    assert bench.run("load", "--id", ID_PROD).returncode == 0
    assert bench.run("logout", "--account", "boulot").returncode == 0
    prog, _ = make_askpass(bench.tmp, name="askpass-x")
    r = subprocess.run([SSH_ADD, "-x"], env=dict(bench.env, SSH_AUTH_SOCK=str(bench.sock()), SSH_ASKPASS=prog,
                                                SSH_ASKPASS_REQUIRE="force"),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert not bench.agent_state().get("locked")
    # délai d'invite invalide : seule la CLI le refuse (code 2) ; le chemin rapide n'a pas répondu
    r = bench.run("--nointeraction", "ensure", "--account", "boulot", "--id", ID_B,
                  env={"SSHVAULT_PROMPT_TIMEOUT": "invalide"})
    assert r.returncode == 2 and "SSHVAULT_PROMPT_TIMEOUT" in one_line_error(r), r.stderr

"""Mots de passe d'hôte fournis par l'askpass de sshvault (story 17, CAP-11).

- Éléments « identifiant » (type 1) reliés à leurs hôtes par URI `ssh://[user@]hôte[:port]` :
  lecture (faux bw), `password list`, blocs `Match originalhost <hôte> exec "… ensure
  --password …"` du ssh_config généré (après les blocs d'identité, gardés avec auto-load false
  et pour un compte illisible).
- `ensure --password` : enregistrement `pw/<pid du ssh>.json` (aucun secret) sous le ssh le plus
  proche, déverrouillage du compte (une invite au plus), code 0 sauf usage.
- `sshvault-askpass` : mot de passe donné une fois par ssh et par élément, seulement à une invite
  de mot de passe mesurée dont l'utilisateur est l'attendu ; toute autre invite relayée
  (terminal, askpass-fallback, sinon code 1).
- Invites internes de sshvault (déverrouillage, passphrase) : jamais par son askpass, même sous
  `SSH_ASKPASS_REQUIRE=force` (aucune régression de CAP-6/CAP-7).
- Bout en bout : deux serveurs SSH paramiko locaux (A : mot de passe, B : keyboard-interactive,
  derrière A par ProxyJump), un vrai `ssh`, l'askpass du banc, HOME temporaire ; argv de tous les
  processus relevés pendant la connexion, fichiers du HOME et du runtime relus.
"""
import json
import os
import pathlib
import re
import shutil
import socket
import stat
import subprocess
import sys

import pytest

from bench import (ALIAS, ID_LOGIN, ID_PROD, ID_CHIFFREE, PASSPHRASE, PASSWORD, PWSERVER, ArgvWatch,
                   login_item, pty_run, ssh_item, wait_gone)
from sshvault import askpass as A
from sshvault import sshconfig
from sshvault.backend import LoginItem, parse_ssh_uri
from sshvault.bw import BwBackend
from sshvault.prompt import internal_env, own_askpass

SSH = shutil.which("ssh")
ID_PA = "a0a0a0a0-1111-4111-8111-a0a0a0a0a0a0"
ID_PB = "b0b0b0b0-2222-4222-8222-b0b0b0b0b0b0"
ID_PC = "c0c0c0c0-3333-4333-8333-c0c0c0c0c0c0"
PW_A = "mdp-du-saut-A-7f3c9e"
PW_B = "mdp-de-la-cible-B-91d2aa"


def pw_items():
    """A : utilisateur de l'élément (« juser ») ; B : utilisateur de l'URI (« tuser »), port ignoré."""
    return [login_item(ID_PA, "Saut A (mdp)", "juser", PW_A, ["ssh://pa", "https://web.example/pa"]),
            login_item(ID_PB, "Cible B (mdp)", "autre", PW_B, ["ssh://tuser@PB:2222"])]


def setup_pw(bench, items=None, generate=True):
    bench.items = bench.items + (pw_items() if items is None else items)
    bench.write_vault()
    bench.unlocked("keyring" if bench.ring else "file")
    if generate:
        r = bench.run("ssh-config")
        assert r.returncode == 0, r.stderr
        return r


def fake_ssh_bin(tmp_path):
    """`ssh` factice : lien nommé « ssh » vers /bin/sh (argv[0] « ssh » dans /proc)."""
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    link = d / "ssh"
    if not link.exists():
        link.symlink_to("/bin/sh")
    return str(link)


def ensure_cmd(iid=ID_PA, host="pa", account=ALIAS):
    return "'%s' -m sshvault ensure --password --account %s --id %s --host %s" % (sys.executable, account, iid, host)


def askpass_cmd(n=1):
    """`n` appels de l'askpass du banc avec l'invite $1, code de chacun affiché."""
    return "; ".join(["\"$SSHVAULT_TEST_ASKPASS\" \"$1\"; echo \"rc=$?\""] * n)


def under_fake_ssh(bench, tmp_path, script, prompt="", env=None, tty=False, answers=None, trigger=rb"password: ",
                   timeout=60, ssh_args=("ssh",)):
    """`script` (sh) lancé par un faux parent « ssh » : `ensure --password` et l'askpass en sont
    les enfants, comme sous un vrai ssh. Avec `tty` : terminal de contrôle (pty), `answers` tapées
    à chaque `trigger`. `ssh_args` : arguments vus dans la ligne de commande du faux ssh après
    `-c <script>` ($0 du script ; l'invite est le dernier). Renvoie (code, stdout, stderr, écran)."""
    e = dict(bench.env)
    e["SSHVAULT_TEST_ASKPASS"] = str(bench.askpass)
    e.update(env or {})
    argv = [fake_ssh_bin(tmp_path), "-c", script] + list(ssh_args) + [prompt]
    if tty:
        r = pty_run([argv], e, answers=answers, trigger=trigger, timeout=timeout)
        return r.returncode, r.stdout, r.stderr, r.screen
    p = subprocess.run(argv, env=e, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                       start_new_session=True)
    return p.returncode, p.stdout, p.stderr, ""


def records(bench):
    d = bench.runtime / "sshvault" / A.PW_DIR
    return {p.name: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))} if d.exists() else {}


# --- URI ssh:// et élément identifiant --------------------------------------------------------

@pytest.mark.parametrize("uri,want", [
    ("ssh://pa", ("pa", None)),
    ("ssh://Root@Host.Example:22", ("host.example", "Root")),
    ("SSH://h_1", ("h_1", None)),
    ("ssh://us%40er@h", ("h", "us@er")),
    ("ssh://h:65535", ("h", None)),
    (" ssh://h ", ("h", None)),
    ("ssh://h/", None), ("ssh://h/chemin", None), ("ssh://h:0", None), ("ssh://h:70000", None), ("ssh://h:x", None),
    ("ssh://*.lab", None), ("ssh://h?", None), ("ssh://-oProxyCommand=x", None), ("ssh://", None),
    ("ssh://u:secret@h", None), ("ssh://a b", None), ("ssh://u@", None), ("https://h", None), ("h", None),
    ("ssh://[::1]", None), ("ssh://u%0a@h", None), ("ssh://h?x=1", None), ("ssh://h#f", None),
])
def test_uri_ssh(uri, want):
    assert parse_ssh_uri(uri) == want


def test_element_identifiant_lu_par_bw():
    d = login_item(ID_PA, "n", "admin", "SECRET", ["ssh://h1", "ssh://root@H2:2222", "https://web", "ssh://h1",
                                                   "ssh://bad host", "ssh://root@h1"])
    it = BwBackend._login(d)
    assert it == LoginItem(ID_PA, "n", (("h1", "admin"), ("h2", "root"), ("h1", "root")),
                           ("https://web", "ssh://bad host"))
    assert "SECRET" not in repr(it) and "SECRET" not in json.dumps(it.to_dict())
    assert it.host_names() == ("h1", "h2") and it.users("h1") == ("admin", "root")
    assert it.to_dict()["hosts"] == ["admin@h1", "root@h2", "root@h1"]
    # sans utilisateur nulle part : hôte seul
    assert BwBackend._login(login_item(ID_PA, "n", None, "x", ["ssh://h"])).hosts == (("h", None),)
    # aucune URI ssh:// : pas un élément de sshvault (ID_LOGIN du banc), rien signalé
    assert BwBackend._login(login_item(ID_PA, "n", "u", "x", ["https://web"])) is None
    assert BwBackend._login(login_item(ID_PA, "n", "u", "x", [])) is None
    # URI ssh:// toutes invalides : sans hôte, seules les URI ssh signalées
    it = BwBackend._login(login_item(ID_PA, "n", "u", "x", ["ssh://*.lab", "https://web"]))
    assert it.hosts == () and it.ignored == ("ssh://*.lab",)
    # mot de passe dans une URI ignorée : masqué partout où elle est montrée
    it = BwBackend._login(login_item(ID_PA, "n", "u", "x", ["ssh://h", "ftp://u:motdepasse@w"]))
    assert "motdepasse" not in json.dumps(it.to_dict())
    for bad in ({"type": 5}, {"type": 1, "login": None}, "x", {"type": 1, "login": {"uris": "ssh://h"}}):
        assert BwBackend._login(bad) is None


# --- invite --------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,user,ok", [
    ("juser@127.0.0.1's password: ", "juser", True),
    ("(tuser@hka) Password: ", "tuser", True),
    ("u@x@h's password: ", "u@x", True),
    ("u@x@h's password: ", "u", False),
    ("root@h's password: ", "admin", False),
    ("juser@h's password:", "juser", False),
    ("juser@h's Password: ", "juser", False),
    ("(juser@h) password: ", "juser", False),
    ("juser@'s password: ", "juser", False),
    ("juser@h h's password: ", "juser", False),
    ("Enter passphrase for key 'x': ", "juser", False),
    ("juser@h's password: \n", "juser", False),
    ("(juser@h) Verification code: ", "juser", False),
    ("juser@h's password: ", None, False),
])
def test_forme_de_l_invite(text, user, ok):
    assert A.prompt_matches(text, user) is ok


def test_question_de_cle_d_hote():
    assert A.host_key_question("Are you sure you want to continue connecting (yes/no/[fingerprint])? ")
    assert A.host_key_question("Please type 'yes', 'no' or the fingerprint: ")
    assert not A.host_key_question("u@h's password: ")


# --- environnement des invites internes ---------------------------------------------------------

def test_environnement_interne(tmp_path):
    ours = tmp_path / "bin" / "sshvault-askpass"
    ours.parent.mkdir()
    ours.write_text("#!/bin/sh\nexit 1\n")
    ours.chmod(0o755)
    link = tmp_path / "bin" / "mon-askpass"
    link.symlink_to(ours)
    other = tmp_path / "bin" / "graphique"
    other.write_text("#!/bin/sh\nexit 0\n")
    other.chmod(0o755)
    cfg = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "PATH": str(ours.parent)}
    assert own_askpass(str(ours), cfg) and own_askpass(str(link), cfg) and own_askpass("sshvault-askpass", cfg)
    assert not own_askpass(str(other), cfg) and not own_askpass("", cfg)
    # notre askpass + force, sans fallback (ni réglage, ni DISPLAY) : tous deux retirés
    env = dict(cfg, SSH_ASKPASS=str(ours), SSH_ASKPASS_REQUIRE="force", AUTRE="x")
    out = internal_env(env)
    assert "SSH_ASKPASS" not in out and "SSH_ASKPASS_REQUIRE" not in out and out["AUTRE"] == "x"
    assert env["SSH_ASKPASS"] == str(ours), "environnement d'origine intact"
    assert internal_env(out) == out, "idempotent"
    # réglage askpass-fallback : il remplace notre askpass
    d = tmp_path / "cfg" / "sshvault"
    d.mkdir(parents=True, mode=0o700)
    (d / "config.json").write_text(json.dumps({"askpass-fallback": str(other)}))
    (d / "config.json").chmod(0o600)
    out = internal_env(dict(env, SSH_ASKPASS=str(link)))
    assert out["SSH_ASKPASS"] == str(other) and "SSH_ASKPASS_REQUIRE" not in out
    # prefer ou never posés par l'utilisateur : gardés (seul force est retiré)
    assert internal_env(dict(env, SSH_ASKPASS_REQUIRE="prefer"))["SSH_ASKPASS_REQUIRE"] == "prefer"
    # un autre askpass : rien ne change (force compris)
    env2 = dict(cfg, SSH_ASKPASS=str(other), SSH_ASKPASS_REQUIRE="force")
    assert internal_env(env2) == env2
    # askpass_rules : notre askpass n'est utilisable que si son relais l'est
    from sshvault.agent import askpass_rules
    (d / "config.json").write_text("{}")
    assert askpass_rules(dict(cfg, SSH_ASKPASS=str(ours), SSH_ASKPASS_REQUIRE="force"))[1] is False
    (d / "config.json").write_text(json.dumps({"askpass-fallback": str(other)}))
    assert askpass_rules(dict(cfg, SSH_ASKPASS=str(ours), SSH_ASKPASS_REQUIRE="force", DISPLAY=":0"))[1] is True


def test_environnement_interne_defaut_display(tmp_path, monkeypatch):
    """Sans réglage : /usr/bin/ssh-askpass (remplacé ici par un exécutable du test) seulement avec
    DISPLAY ; force retiré : `plan` choisit le terminal d'abord, même avec DISPLAY."""
    from sshvault import config
    from sshvault.prompt import plan
    default = tmp_path / "ssh-askpass"
    default.write_text("#!/bin/sh\nexit 0\n")
    default.chmod(0o755)
    monkeypatch.setattr(config, "DEFAULT_ASKPASS", str(default))
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "SSH_ASKPASS": "/x/sshvault-askpass", "SSH_ASKPASS_REQUIRE": "force"}
    out = internal_env(dict(env, DISPLAY=":0"))
    assert out["SSH_ASKPASS"] == str(default) and "SSH_ASKPASS_REQUIRE" not in out and out["DISPLAY"] == ":0"
    p = plan(out, True)
    assert not p.use_askpass, "terminal d'abord (prefer aurait choisi l'askpass graphique)"
    assert plan(out, False).askpass == str(default), "sans terminal : l'askpass graphique"
    out = internal_env(env)
    assert "SSH_ASKPASS" not in out and "SSH_ASKPASS_REQUIRE" not in out, "sans DISPLAY : aucun askpass"


def test_force_display_deverrouillage_au_terminal(bench, tmp_path):
    """DISPLAY et un askpass graphique (askpass-fallback) : le mot de passe maître est demandé au
    terminal, ni par l'askpass de sshvault ni par le graphique."""
    graph_log = tmp_path / "graphique.calls"
    graph = tmp_path / "graphique"
    graph.write_text("#!/bin/sh\necho \"$1\" >> '%s'\nexit 1\n" % graph_log)
    graph.chmod(0o755)
    assert bench.run("config", "set", "askpass-fallback", str(graph)).returncode == 0
    bench.set_state()  # connecté, verrouillé
    calls = tmp_path / "askpass.calls"
    env = {"SSH_ASKPASS": str(bench.askpass), "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": ":0",
           "SSHVAULT_TEST_ASKPASS_LOG": str(calls)}
    r, tty = bench.run_tty("ensure", "--id", ID_PROD, answer=PASSWORD, env=env)
    assert r.returncode == 0, (r.stderr, tty)
    assert "mot de passe maître" in tty
    assert not calls.exists() and not graph_log.exists()
    assert bench.agent_keys() == [bench.blob("prod")]


def test_config_askpass_fallback(bench, tmp_path):
    other = tmp_path / "graphique"
    other.write_text("#!/bin/sh\nexit 0\n")
    other.chmod(0o755)
    r = bench.run("config", "get", "askpass-fallback")
    assert r.returncode == 0 and r.stdout.startswith("askpass-fallback ") and "(défaut)" in r.stdout
    r = bench.run("config", "set", "askpass-fallback", str(other))
    assert r.returncode == 0, r.stderr
    assert bench.run("config", "get", "askpass-fallback").stdout.strip() == "askpass-fallback %s" % other
    for bad in ("relatif", str(tmp_path / "absent"), str(bench.askpass)):
        r = bench.run("config", "set", "askpass-fallback", bad)
        assert r.returncode == 2, (bad, r.stderr)
    assert "askpass de sshvault" in bench.run("config", "set", "askpass-fallback", str(bench.askpass)).stderr
    assert bench.run("config", "unset", "askpass-fallback").returncode == 0
    # dossier modifiable par le groupe : accepté, avertissement propre à l'askpass
    gw = tmp_path / "partage"
    gw.mkdir()
    gw.chmod(0o775)
    exposed = gw / "graphique"
    exposed.write_text("#!/bin/sh\nexit 0\n")
    exposed.chmod(0o755)
    r = bench.run("config", "set", "askpass-fallback", str(exposed))
    assert r.returncode == 0, r.stderr
    line = [l for l in r.stderr.splitlines() if "exposé à d'autres" in l]
    assert len(line) == 1 and "askpass-fallback « %s »" % exposed in line[0], r.stderr
    assert "dossier %s modifiable par le groupe ou les autres" % gw in line[0]
    assert "ils pourraient remplacer l'askpass et recevoir les mots de passe et passphrases saisis" in line[0]
    assert "bw" not in line[0].split("exposé à d'autres")[1].split(";", 1)[1], "pas le texte de bw-path"


# --- password list -------------------------------------------------------------------------------

def test_password_list(bench):
    setup_pw(bench, generate=False)
    r = bench.run("password", "list")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["%s\tCible B (mdp)\ttuser@pb" % ALIAS, "%s\tSaut A (mdp)\tjuser@pa" % ALIAS]
    assert "URI ignorée « https://web.example/pa »" in r.stderr and "Saut A (mdp)" in r.stderr
    assert PW_A not in r.stdout + r.stderr and PW_B not in r.stdout + r.stderr
    j = json.loads(bench.run("password", "list", "--json").stdout)
    assert j == [{"account": ALIAS, "id": ID_PB, "name": "Cible B (mdp)", "hosts": ["tuser@pb"], "ignored": []},
                 {"account": ALIAS, "id": ID_PA, "name": "Saut A (mdp)", "hosts": ["juser@pa"],
                  "ignored": ["https://web.example/pa"]}]
    # élément identifiant sans URI ssh:// (ID_LOGIN) : ni dans password list, ni dans list/search
    assert ID_LOGIN not in bench.run("password", "list", "--json").stdout
    out = bench.run("list", "--json").stdout
    assert ID_PA not in out and ID_PB not in out and ID_LOGIN not in out
    assert bench.run("search", "pa").returncode == 1
    # bw : un seul « list items » pour la liste
    n = len(bench.calls())
    bench.run("--nointeraction", "password", "list")
    assert [c["argv"][1:] for c in bench.calls()[n:]] == [["list", "items"]]


def test_password_list_uri_ssh_invalide_signalee(bench):
    setup_pw(bench, items=[login_item(ID_PC, "Mal écrit", "u", "x", ["ssh://*.lab"])], generate=False)
    r = bench.run("password", "list")
    assert r.returncode == 0 and r.stdout == ""
    assert "« Mal écrit »" in r.stderr and "ssh://*.lab" in r.stderr and "ssh://[user@]hôte[:port]" in r.stderr


def test_password_list_deux_comptes_un_verrouille(bench):
    setup_pw(bench, generate=False)
    bench.add_account("bob", "bob@example.test", items=[login_item(ID_PC, "Chez Bob", "bob", "x", ["ssh://pc"])],
                      default=True)  # connecté, verrouillé
    r = bench.run("--nointeraction", "password", "list")
    assert r.returncode == 3, r.stderr
    assert r.stdout.splitlines() == ["%s\tCible B (mdp)\ttuser@pb" % ALIAS, "%s\tSaut A (mdp)\tjuser@pa" % ALIAS]
    bob = [l for l in r.stderr.splitlines() if "bob" in l]
    assert len(bob) == 1 and bob[0].startswith("sshvault: bob : ") and "verrouillé" in bob[0], r.stderr


def test_password_list_verrouille(bench):
    setup_pw(bench, generate=False)
    bench.set_state(session=None)
    r = bench.run("--nointeraction", "password", "list")
    assert r.returncode == 3 and "verrouillé" in r.stderr


# --- blocs du ssh_config -----------------------------------------------------------------------

def block(iid, name, hosts, exe, account=ALIAS):
    out = "\n# %s %s %s mot de passe\n" % (name, account, iid)
    for h in hosts:
        out += 'Match originalhost %s exec "\'%s\' ensure --password --account %s --id %s --host %s"\n' % (
            h, exe, account, iid, h)
    return out


def test_build_blocs_mot_de_passe(tmp_path):
    paths = sshconfig.Paths(str(tmp_path))
    from sshvault.backend import SshKeyItem
    pub = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGq2c4Z9pZqY4b8yS6n7Uq1rTq3dQ7Zl0yL6kY2hM8xF"
    keys = [SshKeyItem(ID_PROD, "Clé", pub, "", ("k",), account=ALIAS)]
    logins = [LoginItem(ID_PB, "Zed", (("pb", "tuser"),), account=ALIAS),
              LoginItem(ID_PA, "Alpha", (("pa", "juser"), ("pa2", "juser"), ("pa", "root")), account=ALIAS)]
    plan = sshconfig.build(keys, paths, str(tmp_path / "s.sock"), "/opt/sshvault", logins=logins)
    text = plan.config.decode()
    ident = text.index("# Clé %s %s" % (ALIAS, ID_PROD))
    a, b = text.index(block(ID_PA, "Alpha", ["pa", "pa2"], "/opt/sshvault")), \
        text.index(block(ID_PB, "Zed", ["pb"], "/opt/sshvault"))
    assert ident < a < b, "après les blocs d'identité, par nom"
    assert text.count("--password") == 3 and plan.blocks == 3
    assert not any("mot de passe" in w for w in plan.warnings), plan.warnings
    # auto-load false : aucune ligne exec pour les clés, celles des mots de passe gardées (pw_exe)
    plan = sshconfig.build(keys, paths, str(tmp_path / "s.sock"), None, logins=logins, pw_exe="/opt/sshvault")
    text = plan.config.decode()
    assert "ensure --account" not in text and text.count("--password") == 3
    # chemin de sshvault inconnu : pas de ligne, avertissement
    plan = sshconfig.build([], paths, str(tmp_path / "s.sock"), None, logins=logins)
    assert "--password" not in plan.config.decode() and any("Alpha" in w for w in plan.warnings)
    # même hôte et même utilisateur dans deux éléments : avertissement, le premier gagne
    dup = logins + [LoginItem(ID_PC, "Beta", (("PA", "juser"),), account=ALIAS)]
    plan = sshconfig.build([], paths, str(tmp_path / "s.sock"), "/opt/sshvault", logins=dup)
    w = [x for x in plan.warnings if "juser@pa" in x]
    assert len(w) == 1 and w[0].index("Alpha") < w[0].index("Beta") and "premier" in w[0]
    # sans utilisateur : avertissement (mot de passe jamais donné), bloc quand même
    plan = sshconfig.build([], paths, str(tmp_path / "s.sock"), "/opt/sshvault",
                           logins=[LoginItem(ID_PC, "Sans", (("h", None),), account=ALIAS)])
    assert "--host h\"" in plan.config.decode() and any("utilisateur" in x for x in plan.warnings)
    # id ou compte inattendu : sauté
    plan = sshconfig.build([], paths, str(tmp_path / "s.sock"), "/opt/sshvault",
                           logins=[LoginItem("pas-un-uuid", "X", (("h", "u"),), account=ALIAS),
                                   LoginItem(ID_PC, "Y", (("h", "u"),), account=None)])
    assert "--password" not in plan.config.decode() and len(plan.warnings) == 2
    with pytest.raises(sshconfig.SshConfigError):
        sshconfig.password_command("/opt/sshvault", ID_PA, ALIAS, "h*")
    with pytest.raises(sshconfig.SshConfigError):
        sshconfig.password_command("/opt/ss'hvault", ID_PA, ALIAS, "h")


def test_blocs_relus_et_reconnus(tmp_path):
    """kept_logins relit les blocs à mot de passe ; kept_items, pub_fingerprint et forward_map
    les ignorent ; exe_warnings voit leur chemin."""
    paths = sshconfig.Paths(str(tmp_path))
    logins = [LoginItem(ID_PA, "Saut A (mdp)", (("pa", "juser"), ("pa2", None)), account=ALIAS),
              LoginItem(ID_PB, "transfert d'agent x", (("pb", "u"),), account="autre")]
    plan = sshconfig.build([], paths, str(tmp_path / "s.sock"), "/opt/sshvault", logins=logins)
    os.makedirs(paths.dir, mode=0o700)
    pathlib.Path(paths.config).write_bytes(plan.config)
    os.chmod(paths.config, 0o600)
    got = sshconfig.kept_logins(paths, lambda a: True)
    assert [(i.account, i.id, i.name, i.host_names()) for i in got] == [
        (ALIAS, ID_PA, "Saut A (mdp)", ("pa", "pa2")), ("autre", ID_PB, "transfert d'agent x", ("pb",))]
    assert [i.account for i in sshconfig.kept_logins(paths, lambda a: a == "neuf", renamed={"autre": "neuf"})] == ["neuf"]
    again = sshconfig.build([], paths, str(tmp_path / "s.sock"), "/opt/sshvault", logins=got,
                            kept=frozenset((i.account, i.id) for i in got))
    assert again.config == plan.config, "blocs refaits à l'identique"
    assert sshconfig.kept_items(paths, lambda a: True) == []
    assert sshconfig.forward_map(paths) == {}
    from sshvault.fastpath import pub_fingerprint
    assert pub_fingerprint(ID_PA, {"SSHVAULT_SSH_HOME": str(tmp_path)}, ALIAS) is None
    assert sshconfig.exe_warnings("/autre/sshvault", paths) == ["chemin de sshvault des lignes Match exec changé : "
                                                                 "/opt/sshvault → /autre/sshvault"]


def test_ssh_config_blocs_mot_de_passe(bench):
    r = setup_pw(bench)
    text = (bench.home / ".ssh" / "sshvault" / "config").read_text()
    assert block(ID_PA, "Saut A (mdp)", ["pa"], str(bench.exe)) in text
    assert block(ID_PB, "Cible B (mdp)", ["pb"], str(bench.exe)) in text
    assert ID_LOGIN not in text
    assert text.index("# Serveur Prod ") < text.index("mot de passe\n")
    assert "URI ignorée « https://web.example/pa »" in r.stderr
    assert bench.run("ssh-config", "install").returncode == 0
    r = bench.run("ssh-config", "--check")
    assert r.returncode == 0 and r.stdout.startswith("à jour"), r.stdout
    # auto-load false : lignes des mots de passe gardées
    assert bench.run("config", "set", "auto-load", "false").returncode == 0
    assert bench.run("ssh-config").returncode == 0
    text = (bench.home / ".ssh" / "sshvault" / "config").read_text()
    assert "ensure --account" not in text and block(ID_PA, "Saut A (mdp)", ["pa"], str(bench.exe)) in text
    # élément retiré du coffre : bloc retiré
    bench.items = [i for i in bench.items if i.get("id") != ID_PB]
    bench.write_vault()
    assert bench.run("ssh-config").returncode == 0
    assert ID_PB not in (bench.home / ".ssh" / "sshvault" / "config").read_text()


def test_ssh_config_compte_illisible_garde_ses_blocs(bench):
    setup_pw(bench)
    bench.add_account("bob", "bob@example.test", items=[login_item(ID_PC, "Chez Bob", "bob", "x", ["ssh://pc"])],
                      unlocked=True, where="keyring" if bench.ring else "file")
    assert bench.run("ssh-config").returncode == 0
    path = bench.home / ".ssh" / "sshvault" / "config"
    assert block(ID_PC, "Chez Bob", ["pc"], str(bench.exe), account="bob") in path.read_text()
    assert bench.run("ssh-config", "install").returncode == 0
    before = path.read_bytes()
    # bob verrouillé : ses blocs gardés tels quels (régénération par alice), --check à jour
    st = json.loads(bench.appdata_of("bob").joinpath("data.json").read_text())
    st["session"] = None
    bench.appdata_of("bob").joinpath("data.json").write_text(json.dumps(st))
    r = bench.run("--nointeraction", "ssh-config")
    assert r.returncode == 0, r.stderr
    assert "compte bob illisible" in r.stderr
    assert path.read_bytes() == before
    assert bench.run("--nointeraction", "ssh-config", "--check").returncode == 0


def test_account_set_retire_les_blocs_mot_de_passe(bench):
    """`account set` : les blocs à mot de passe du compte modifié partent avec ses autres blocs ;
    ceux des autres comptes restent."""
    setup_pw(bench)
    bench.add_account("bob", "bob@example.test", items=[login_item(ID_PC, "Chez Bob", "bob", "x", ["ssh://pc"])],
                      unlocked=True, where="keyring" if bench.ring else "file")
    assert bench.run("ssh-config").returncode == 0
    path = bench.home / ".ssh" / "sshvault" / "config"
    assert block(ID_PC, "Chez Bob", ["pc"], str(bench.exe), account="bob") in path.read_text()
    r = bench.run("account", "set", "bob", "--email", "dan@example.test")
    assert r.returncode == 0, r.stderr
    text = path.read_text()
    assert ID_PC not in text and "ensure --password --account bob" not in text and "bob" not in text
    assert block(ID_PA, "Saut A (mdp)", ["pa"], str(bench.exe)) in text
    assert "illisible" not in r.stderr


def test_hosts_add_garde_les_blocs_mot_de_passe(bench):
    """Une écriture (hosts add) régénère avec les éléments identifiant, sans appel bw de plus."""
    setup_pw(bench)
    path = bench.home / ".ssh" / "sshvault" / "config"
    n = len(bench.calls())
    r = bench.run("hosts", "add", "--id", ID_PROD, "nouveau.example")
    assert r.returncode == 0, r.stderr
    text = path.read_text()
    assert block(ID_PA, "Saut A (mdp)", ["pa"], str(bench.exe)) in text and "nouveau.example" in text
    assert sum(1 for c in bench.calls()[n:] if c["argv"][1:] == ["list", "items"]) == 1


# --- ensure --password ------------------------------------------------------------------------

def test_ensure_password_enregistre_le_ssh_parent(bench, tmp_path):
    setup_pw(bench)
    rc, out, err, _ = under_fake_ssh(bench, tmp_path, ensure_cmd() + "; " + ensure_cmd(ID_PB, "pb")
                                     + "; " + ensure_cmd() + "; echo pid=$$")
    assert (rc, err) == (0, ""), err
    pid = int(re.search(r"pid=(\d+)", out).group(1))
    d = bench.runtime / "sshvault" / A.PW_DIR
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    f = d / ("%d.json" % pid)
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    rec = json.loads(f.read_text())
    assert rec["pid"] == pid and rec["given"] == [] and isinstance(rec["start"], str)
    assert rec["entries"] == [{"account": ALIAS, "id": ID_PA, "host": "pa"}, {"account": ALIAS, "id": ID_PB, "host": "pb"}]
    assert PW_A not in f.read_text() and PW_B not in f.read_text()
    assert not any(c["argv"][1:3] == ["get", "item"] for c in bench.calls()), "aucun mot de passe lu par ensure"
    # le ssh est fini : enregistrement retiré au prochain ensure --password
    assert wait_gone([pid])
    rc, out, _, _ = under_fake_ssh(bench, tmp_path, ensure_cmd() + "; echo pid=$$")
    assert rc == 0 and list(records(bench)) == ["%s.json" % re.search(r"pid=(\d+)", out).group(1)]


def test_ensure_password_ssh_G_et_usage(bench, tmp_path):
    setup_pw(bench)
    # ssh -G : rien, chemin rapide (sans la CLI)
    e = dict(bench.env)
    code = ("import sys; sys.argv = ['sshvault'] + sys.argv[1:]; from sshvault.launch import main; rc = main(); "
            "print(rc, 'sshvault.cli' in sys.modules)")
    script = "'%s' -c \"%s\" ensure --password --account %s --id %s --host pa" % (sys.executable, code, ALIAS, ID_PA)
    p = subprocess.run([fake_ssh_bin(tmp_path), "-c", script, "ssh", "-G", "pa"], env=e, capture_output=True,
                       text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert p.stdout.split() == ["0", "False"], p.stderr
    assert records(bench) == {}
    for args in (["--host", "pa"], ["--account", ALIAS, "--host", "pa"], ["--account", ALIAS, "--id", ID_PA],
                 ["--account", ALIAS, "--id", ID_PA, "--host", "*.lab"],
                 ["--account", ALIAS, "--id", "pas-un-uuid", "--host", "pa"],
                 ["--account", ALIAS, "--id", ID_PA, "--host", "pa", "--forward", "0123456789abcdef"],
                 ["--account", ALIAS, "--id", "%s:%s" % (ALIAS, ID_PA), "--host", "pa"]):
        r = bench.run("ensure", "--password", *args)
        assert r.returncode == 2, (args, r.stderr)
    assert bench.run("ensure", "--host", "pa", "--id", ID_PA).returncode == 2, "--host sans --password"


def test_ensure_password_deverrouille_une_fois(bench, tmp_path):
    setup_pw(bench)
    bench.set_state(session=None)  # verrouillé (session rangée refusée)
    script = ensure_cmd() + "; echo rc=$?; " + ensure_cmd(ID_PB, "pb") + "; echo rc=$?"
    rc, out, err, screen = under_fake_ssh(bench, tmp_path, script, tty=True, answers=[PASSWORD],
                                          trigger=rb"mot de passe ma")
    assert out.split() == ["rc=0", "rc=0"], (out, err, screen)
    assert screen.count("mot de passe maître") == 1 and "pour le mot de passe d'hôte de pa : " in screen
    assert bench.bw_session(), "session rangée"
    assert len(next(iter(records(bench).values()))["entries"]) == 2


def test_ensure_password_sans_invite_code_0(bench, tmp_path):
    setup_pw(bench)
    bench.set_state(session=None)
    rc, out, err, _ = under_fake_ssh(bench, tmp_path, ensure_cmd() + "; echo rc=$?")
    assert out.split() == ["rc=0"] and "aucune invite possible" in err, err
    # BatchMode=yes en argument du ssh : aucune invite, même sous un terminal
    rc, out, err, screen = under_fake_ssh(bench, tmp_path, ensure_cmd() + "; echo rc=$?", ssh_args=("-o",),
                                          prompt="BatchMode=yes", tty=True, trigger=rb"mot de passe ma")
    assert out.split() == ["rc=0"] and "aucune invite (BatchMode=yes)" in err + screen, (err, screen)
    assert "mot de passe maître" not in screen
    assert len(next(iter(records(bench).values()))["entries"]) == 1, "enregistré quand même"
    r = bench.run("--nointeraction", "ensure", "--password", "--account", ALIAS, "--id", ID_PA, "--host", "pa")
    assert r.returncode == 0 and "aucune invite (--nointeraction)" in r.stderr


# --- askpass ---------------------------------------------------------------------------------

def test_askpass_donne_le_mot_de_passe_une_fois(bench, tmp_path):
    setup_pw(bench)
    script = ensure_cmd() + "; " + askpass_cmd(2)
    rc, out, err, screen = under_fake_ssh(bench, tmp_path, script, prompt="juser@127.0.0.1's password: ", tty=True,
                                          answers=["saisi-au-terminal"])
    lines = out.split()
    assert lines[:2] == [PW_A, "rc=0"], (out, err, screen)
    assert lines[2:] == ["saisi-au-terminal", "rc=0"], "2e invite : relais au terminal"
    assert "mot de passe du coffre refusé pour juser@pa (Saut A (mdp))" in err + screen
    assert PW_A not in screen and "saisi-au-terminal" not in screen, "écho coupé au terminal"
    rec = next(iter(records(bench).values()))
    assert rec["given"] == [{"account": ALIAS, "id": ID_PA, "user": "juser", "host": "pa", "name": "Saut A (mdp)"}]
    assert PW_A not in json.dumps(rec)
    assert sum(1 for c in bench.calls() if c["argv"][1:3] == ["get", "item"]) == 1, "2e invite : sans bw"


def test_askpass_keyboard_interactive_et_utilisateur_de_l_uri(bench, tmp_path):
    setup_pw(bench)
    rc, out, err, _ = under_fake_ssh(bench, tmp_path, ensure_cmd(ID_PB, "pb") + "; " + askpass_cmd(),
                                     prompt="(tuser@hka) Password: ")
    assert out.split() == [PW_B, "rc=0"], err


@pytest.mark.parametrize("prompt", ["root@127.0.0.1's password: ", "autre@127.0.0.1's password: ",
                                    "Enter passphrase for key '/x': ", "(juser@h) Verification code: "])
def test_askpass_autre_invite_relayee(bench, tmp_path, prompt):
    """Utilisateur différent (root, ou login.username remplacé par l'URI), autre question : relais."""
    setup_pw(bench)
    host = "pb" if prompt.startswith("autre") else "pa"
    iid = ID_PB if host == "pb" else ID_PA
    rc, out, err, screen = under_fake_ssh(bench, tmp_path, ensure_cmd(iid, host) + "; " + askpass_cmd(),
                                          prompt=prompt, tty=True, answers=["tape"], trigger=re.escape(prompt.encode()))
    assert out.split() == ["tape", "rc=0"], (out, err, screen)
    assert PW_A not in out + err + screen and PW_B not in out + err + screen
    assert next(iter(records(bench).values()))["given"] == []
    said = [l for l in (err + screen).splitlines() if "aucun élément du coffre ne correspond" in l]
    if A.password_form(prompt):
        who = prompt.split("'s password")[0]
        want = "tuser@pb" if host == "pb" else "juser@pa"
        assert len(said) == 1 and "invite pour %s :" % who in said[0] and "attendu : %s" % want in said[0], (err, screen)
    else:
        assert said == [], "autre question : relais sans message"


def test_askpass_hote_retire_de_l_element(bench, tmp_path):
    """Enregistré pour « pa », mais l'élément n'a plus cette URI quand l'invite arrive : une ligne,
    relais, jamais le mot de passe."""
    setup_pw(bench)
    script = ensure_cmd() + "; sleep 0.3; " + askpass_cmd()
    bench.items = [i for i in bench.items if i.get("id") != ID_PA] + [
        login_item(ID_PA, "Saut A (mdp)", "juser", PW_A, ["ssh://ailleurs"])]
    bench.write_vault()
    rc, out, err, _ = under_fake_ssh(bench, tmp_path, script, prompt="juser@127.0.0.1's password: ")
    assert out.split() == ["rc=1"], (out, err)
    assert "invite pour juser@127.0.0.1 : aucun élément du coffre ne correspond" in err
    assert "« Saut A (mdp) » : aucun utilisateur pour pa" in err and PW_A not in out + err


def test_askpass_premier_element_gagne(bench, tmp_path):
    """Même hôte et même utilisateur dans deux éléments : le mot de passe du premier (nom, compte,
    id), quel que soit l'ordre des lignes Match exec."""
    setup_pw(bench, items=[login_item(ID_PC, "Beta", "juser", "mdp-beta", ["ssh://pa"]),
                           login_item(ID_PA, "Alpha", "juser", "mdp-alpha", ["ssh://pa"])])
    script = ensure_cmd(ID_PC, "pa") + "; " + ensure_cmd(ID_PA, "pa") + "; " + askpass_cmd()
    rc, out, err, _ = under_fake_ssh(bench, tmp_path, script, prompt="juser@127.0.0.1's password: ")
    assert out.split() == ["mdp-alpha", "rc=0"], err
    assert [g["id"] for g in next(iter(records(bench).values()))["given"]] == [ID_PA]


def test_askpass_parent_inconnu_relaie(bench, tmp_path):
    """ssh sans enregistrement (pas de ligne Match exec pour cet hôte) : relais, sans bw."""
    setup_pw(bench)
    rc, out, err, screen = under_fake_ssh(bench, tmp_path, askpass_cmd(), prompt="juser@127.0.0.1's password: ",
                                          tty=True, answers=["tape"])
    assert out.split() == ["tape", "rc=0"], (out, err)
    assert not any(c["argv"][1:3] == ["get", "item"] for c in bench.calls())


def test_askpass_question_de_cle_d_hote_avec_echo(bench, tmp_path):
    setup_pw(bench)
    q = ("The authenticity of host '[127.0.0.1]:2222' can't be established.\n"
         "Are you sure you want to continue connecting (yes/no/[fingerprint])? ")
    rc, out, err, screen = under_fake_ssh(bench, tmp_path, ensure_cmd() + "; " + askpass_cmd(), prompt=q, tty=True,
                                          answers=["yes"], trigger=rb"\(yes/no")
    assert out.split() == ["yes", "rc=0"] and "yes" in screen.split("[fingerprint])?")[-1], (out, screen)
    # sans terminal ni fallback : code 1 (ssh : « Host key verification failed. »)
    rc, out, err, _ = under_fake_ssh(bench, tmp_path, ensure_cmd() + "; " + askpass_cmd(), prompt=q)
    assert out.split() == ["rc=1"]


def test_askpass_sans_terminal_ni_fallback(bench, tmp_path):
    setup_pw(bench)
    rc, out, err, _ = under_fake_ssh(bench, tmp_path, askpass_cmd(), prompt="root@h's password: ")
    assert out.split() == ["rc=1"], err


def test_askpass_fallback_meme_argv_et_environnement(bench, tmp_path):
    """Sans terminal : askpass-fallback, mêmes arguments et environnement ; confirmation d'un
    agent (SSH_ASKPASS_PROMPT=confirm) : relais seul, même avec un enregistrement."""
    setup_pw(bench)
    log = tmp_path / "fallback.log"
    fb = tmp_path / "graphique"
    fb.write_text("#!/bin/sh\nprintf '%%s|%%s|%%s\\n' \"$#\" \"$1\" \"$SSH_ASKPASS_PROMPT\" >> '%s'\necho reponse\n"
                  "exit 7\n" % log)
    fb.chmod(0o755)
    assert bench.run("config", "set", "askpass-fallback", str(fb)).returncode == 0
    rc, out, err, _ = under_fake_ssh(bench, tmp_path, ensure_cmd() + "; " + askpass_cmd(),
                                     prompt="Allow use of key x?", env={"SSH_ASKPASS_PROMPT": "confirm"})
    assert out.split() == ["reponse", "rc=7"], err
    assert log.read_text() == "1|Allow use of key x?|confirm\n"
    rc, out, err, _ = under_fake_ssh(bench, tmp_path, ensure_cmd() + "; " + askpass_cmd(),
                                     prompt="juser@h's password: ", env={"SSH_ASKPASS_PROMPT": "confirm"})
    assert out.split() == ["reponse", "rc=7"] and PW_A not in out
    # fallback qui désigne l'askpass de sshvault (réglage écrit à la main) : jamais lancé
    cfg = json.loads(bench.config_file().read_text())
    cfg["askpass-fallback"] = str(bench.askpass)
    bench.config_file().write_text(json.dumps(cfg))
    rc, out, err, _ = under_fake_ssh(bench, tmp_path, askpass_cmd(), prompt="x@h's password: ",
                                     env={"SSHVAULT_TEST_ASKPASS_LOG": str(tmp_path / "calls")})
    assert out.split() == ["rc=1"] and len((tmp_path / "calls").read_text().splitlines()) == 1


def test_askpass_coffre_verrouille_relaie(bench, tmp_path):
    setup_pw(bench)
    rc, _, err, _ = under_fake_ssh(bench, tmp_path, ensure_cmd())
    assert (rc, err) == (0, ""), err
    bench.set_state(session=None)
    rc, out, err, screen = under_fake_ssh(bench, tmp_path, ensure_cmd() + "; " + askpass_cmd(),
                                          prompt="juser@h's password: ", tty=True, answers=["tape"],
                                          env={"SSHVAULT_PROMPT_TIMEOUT": "1"})
    assert out.split() == ["tape", "rc=0"], (out, err, screen)
    assert "coffre « %s » verrouillé : mot de passe du coffre non donné" % ALIAS in err + screen
    assert "mot de passe maître" not in screen.split("password: ")[-1], "jamais d'invite du mot de passe maître"


def test_askpass_module_leger(bench):
    """Sans enregistrement : réponse sans importer bw ni la CLI."""
    code = ("import sys; from sshvault.askpass import main; rc = main(['u@h\\'s password: ']); "
            "print(rc, 'sshvault.bw' in sys.modules, 'sshvault.cli' in sys.modules)")
    r = subprocess.run([sys.executable, "-c", code], env=bench.env, capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL, start_new_session=True)
    assert r.stdout.split() == ["1", "False", "False"], r.stderr
    # enregistrement présent, mais question de clé d'hôte : toujours sans bw
    setup_pw(bench, generate=False)
    probe = bench.tmp / "sonde.py"
    probe.write_text("import sys\nfrom sshvault.askpass import main\nrc = main(sys.argv[1:])\n"
                     "print(rc, 'sshvault.bw' in sys.modules, 'sshvault.cli' in sys.modules)\n")
    q = "Are you sure you want to continue connecting (yes/no/[fingerprint])? "
    script = ensure_cmd() + "; '%s' '%s' \"$1\"; echo fin" % (sys.executable, probe)
    p = subprocess.run([fake_ssh_bin(bench.tmp), "-c", script, "ssh", q], env=bench.env, capture_output=True,
                       text=True, timeout=60, stdin=subprocess.DEVNULL, start_new_session=True)
    assert p.stdout.split() == ["1", "False", "False", "fin"], p.stderr
    assert len(records(bench)) == 1, "enregistrement présent pendant l'invite"
    pyproject = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml")).read()
    assert re.search(r'^sshvault-askpass = "sshvault\.askpass:main"$', pyproject, re.M)


def test_enregistrement_d_un_autre_processus_ignore(bench, tmp_path):
    """Même pid, autre date de début (pid réutilisé) : enregistrement ignoré, puis remplacé."""
    setup_pw(bench)
    d = bench.runtime / "sshvault" / A.PW_DIR
    d.mkdir(parents=True, mode=0o700, exist_ok=True)
    script = "echo pid=$$; sleep 0.5; " + askpass_cmd()
    e = dict(bench.env, SSHVAULT_TEST_ASKPASS=str(bench.askpass))
    p = subprocess.Popen([fake_ssh_bin(tmp_path), "-c", script, "ssh", "juser@h's password: "], env=e,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    pid = int(p.stdout.readline().split("=")[1])
    f = d / ("%d.json" % pid)
    f.write_text(json.dumps({"pid": pid, "start": "1", "entries": [{"account": ALIAS, "id": ID_PA, "host": "pa"}],
                             "given": []}))
    f.chmod(0o600)
    out, err = p.communicate(timeout=60)
    assert out.split() == ["rc=1"] and PW_A not in out, err
    assert not any(c["argv"][1:3] == ["get", "item"] for c in bench.calls()), "ignoré sans lire le coffre"
    # register() sur un enregistrement périmé (même pid, autre date de début) : remplacé
    d2 = tmp_path / "rt"
    (d2 / A.PW_DIR).mkdir(parents=True, mode=0o700)
    me = os.getpid()
    stale = d2 / A.PW_DIR / ("%d.json" % me)
    stale.write_text(json.dumps({"pid": me, "start": "1", "entries": [{"account": "x", "id": ID_PB, "host": "old"}],
                                 "given": [{"account": "x", "id": ID_PB, "user": "u", "host": "old", "name": "n"}]}))
    stale.chmod(0o600)
    start = A.proc_start(me)
    A.register(str(d2), me, start, ALIAS, ID_PA, "pa")
    assert json.loads(stale.read_text()) == {"pid": me, "start": start, "given": [],
                                             "entries": [{"account": ALIAS, "id": ID_PA, "host": "pa"}]}
    assert stat.S_IMODE(stale.stat().st_mode) == 0o600


# --- invites internes : jamais par l'askpass de sshvault (CAP-6, CAP-7) -------------------------

def test_force_deverrouillage_au_terminal(bench, tmp_path):
    bench.set_state()  # connecté, verrouillé
    calls = tmp_path / "askpass.calls"
    env = {"SSH_ASKPASS": str(bench.askpass), "SSH_ASKPASS_REQUIRE": "force", "SSHVAULT_TEST_ASKPASS_LOG": str(calls)}
    r, tty = bench.run_tty("ensure", "--id", ID_PROD, answer=PASSWORD, env=env)
    assert r.returncode == 0, (r.stderr, tty)
    assert "mot de passe maître" in tty and PASSWORD not in tty
    assert not calls.exists(), "askpass de sshvault jamais appelé"
    assert bench.agent_keys() == [bench.blob("prod")]
    st = bench.agent_state()["agent"]
    assert st["askpass"] is False, "agent lancé sans l'askpass de sshvault (aucun relais utilisable)"


def test_force_passphrase_au_terminal(bench, tmp_path):
    bench.add_item(ssh_item(ID_CHIFFREE, "clé chiffrée", bench.keys["chiffree"], hosts="secret.example"))
    bench.unlocked("keyring" if bench.ring else "file")
    calls = tmp_path / "askpass.calls"
    spy = tmp_path / "ssh-add-espion"
    spy.write_text("#!/bin/sh\nprintf '%%s|%%s\\n' \"${SSH_ASKPASS:--}\" \"${SSH_ASKPASS_REQUIRE:--}\" >> '%s'\n"
                   "exec '%s' \"$@\"\n" % (tmp_path / "ssh-add.env", bench.ssh_add))
    spy.chmod(0o755)
    env = {"SSH_ASKPASS": str(bench.askpass), "SSH_ASKPASS_REQUIRE": "force", "SSHVAULT_TEST_ASKPASS_LOG": str(calls),
           "SSHVAULT_SSH_ADD": str(spy)}
    r, tty = bench.run_tty("load", "--id", ID_CHIFFREE, answer=PASSPHRASE, trigger=b"passphrase", env=env)
    assert r.returncode == 0, (r.stderr, tty)
    assert "Enter passphrase" in tty and PASSPHRASE not in tty
    assert not calls.exists(), "ssh-add n'a pas vu l'askpass de sshvault"
    assert bench.agent_keys() == [bench.blob("chiffree")]
    seen = [l.split("|") for l in (tmp_path / "ssh-add.env").read_text().splitlines()]
    # SSH_ASKPASS retiré partout ; force retiré (« never » : appels sans saisie, listes et retraits)
    assert seen and all(a == "-" and r in ("-", "never") for a, r in seen), seen
    assert ["-", "-"] in seen, "l'ajout de la clé chiffrée : ni askpass ni force (terminal) : %s" % seen


def test_force_ssh_keygen_au_terminal(bench, tmp_path):
    """import --decrypt (ssh-keygen demande la passphrase) sous force : au terminal."""
    bench.unlocked("keyring" if bench.ring else "file")
    f = tmp_path / "cle-chiffree"
    f.write_text(bench.keys["chiffree"]["private"])
    f.chmod(0o600)
    calls = tmp_path / "askpass.calls"
    env = {"SSH_ASKPASS": str(bench.askpass), "SSH_ASKPASS_REQUIRE": "force", "SSHVAULT_TEST_ASKPASS_LOG": str(calls)}
    r, tty = bench.run_tty("import", "--decrypt", str(f), answer=PASSPHRASE, trigger=rb"passphrase", env=env)
    assert r.returncode == 0, (r.stderr, tty)
    assert tty.count("passphrase") == 1 and PASSPHRASE not in tty, tty
    assert not calls.exists(), "ssh-keygen n'a pas vu l'askpass de sshvault"
    created = [i for i in json.loads(bench.vault_file.read_text())["items"]
               if (i.get("sshKey") or {}).get("keyFingerprint") == bench.keys["chiffree"]["fingerprint"]]
    assert len(created) == 1


# --- bout en bout : vrai ssh, serveurs paramiko -------------------------------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PwLab:
    """A (mot de passe, utilisateur « juser ») et B (keyboard-interactive, « tuser ») sur 127.0.0.1."""

    def __init__(self, d, good):
        self.dir, self.ports, self.hostkeys, self.procs, self.logs = d, {}, {}, {}, {}
        for name, method, user in (("a", "password", "juser"), ("b", "keyboard-interactive", "tuser")):
            sd = d / name
            sd.mkdir()
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(sd / "hostkey")], check=True)
            self.hostkeys[name] = " ".join((sd / "hostkey.pub").read_text().split()[:2])
            port = _free_port()
            self.logs[name] = sd / "auth.log"
            p = subprocess.Popen([sys.executable, PWSERVER, str(port), method, user, str(sd / "hostkey"),
                                  str(self.logs[name])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=open(str(sd / "server.err"), "ab"), start_new_session=True, text=True)
            self.procs[name] = p
            p.stdin.write(good[name] + "\n")
            p.stdin.close()
            assert p.stdout.readline().strip() == "ready", (sd / "server.err").read_text()
            self.ports[name] = port

    def log(self, name):
        return self.logs[name].read_text() if self.logs[name].exists() else ""

    def stop(self):
        for p in self.procs.values():
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(10)
        assert wait_gone([p.pid for p in self.procs.values()]), "serveurs de test encore vivants"


@pytest.fixture
def pwlab(tmp_path, request):
    pytest.importorskip("paramiko")
    if SSH is None:
        pytest.skip("client ssh absent")
    good = getattr(request, "param", None) or {"a": PW_A, "b": PW_B}
    lab = PwLab.__new__(PwLab)
    lab.procs = {}
    d = tmp_path / "pwlab"
    d.mkdir()
    try:
        lab.__init__(d, good)
        yield lab
    finally:
        lab.stop()


def e2e_config(bench, lab, tmp_path, known=("a", "b")):
    kh = tmp_path / "pw_known_hosts"
    kh.write_text("".join("[127.0.0.1]:%d %s\n" % (lab.ports[n], lab.hostkeys[n]) for n in known))
    cfg = tmp_path / "ssh_config_mdp"
    cfg.write_text(
        'Include "%s"\n'
        "Host pa\n    HostName 127.0.0.1\n    Port %d\n    User juser\n"
        "Host pb\n    HostName 127.0.0.1\n    Port %d\n    User tuser\n    ProxyJump pa\n"
        "Host *\n    UserKnownHostsFile %s\n    GlobalKnownHostsFile /dev/null\n    StrictHostKeyChecking ask\n"
        "    PubkeyAuthentication no\n    IdentityAgent none\n    PreferredAuthentications keyboard-interactive,password\n"
        "    ConnectTimeout 10\n    ControlMaster no\n    ControlPath none\n    UpdateHostKeys no\n"
        % (bench.home / ".ssh" / "sshvault" / "config", lab.ports["a"], lab.ports["b"], kh))
    return str(cfg)


def e2e_env(bench, tmp_path):
    e = dict(bench.env)
    e.update(SSH_ASKPASS=str(bench.askpass), SSH_ASKPASS_REQUIRE="force",
             SSHVAULT_TEST_ASKPASS_LOG=str(tmp_path / "askpass.calls"))
    return e


def files_with(roots, secrets):
    out = []
    for root in roots:
        for dirpath, dirs, files in os.walk(str(root)):
            for n in files:
                p = os.path.join(dirpath, n)
                try:
                    if not stat.S_ISREG(os.lstat(p).st_mode):
                        continue
                    data = open(p, "rb").read()
                except OSError:
                    continue
                out += [(p, s) for s in secrets if s.encode() in data]
    return out


def test_bout_en_bout_saut_et_cible_a_mot_de_passe(bench, pwlab, tmp_path):
    setup_pw(bench)
    cfg = e2e_config(bench, pwlab, tmp_path)
    with ArgvWatch(ID_PA, [PW_A, PW_B], heuristics=False) as w:
        r = pty_run([[SSH, "-F", cfg, "pb", "echo", "bonjour"]], e2e_env(bench, tmp_path), trigger=rb"assword",
                    timeout=90)
    assert r.returncode == 0, (r.stdout, r.stderr, r.screen)
    assert r.stdout.strip() == "OK port=%d cmd=echo bonjour" % pwlab.ports["b"]
    assert "assword" not in r.screen, "aucune invite au terminal"
    assert "port=%d password user=juser ok=True" % pwlab.ports["a"] in pwlab.log("a")
    assert "ok=False" not in pwlab.log("a") + pwlab.log("b")
    assert "port=%d keyboard-interactive user=tuser ok=True" % pwlab.ports["b"] in pwlab.log("b")
    assert any("--password" in " ".join(a) for a in w.seen), "relevé des argv effectif : %s" % w.seen
    assert not w.suspect, "mot de passe vu dans un argv : %s" % w.suspect
    calls = (tmp_path / "askpass.calls").read_text().splitlines()
    assert calls == ["juser@127.0.0.1's password: ", "(tuser@127.0.0.1) Password: "], calls
    roots = [bench.home, bench.runtime] + [p for p in tmp_path.iterdir() if p.name != "server"]
    assert files_with(roots, [PW_A, PW_B]) == []
    assert records(bench) == {} or all(r["given"] for r in records(bench).values())


@pytest.mark.parametrize("pwlab", [{"a": PW_A, "b": "change-sur-le-serveur"}], indirect=True)
def test_bout_en_bout_mot_de_passe_refuse(bench, pwlab, tmp_path):
    setup_pw(bench)
    cfg = e2e_config(bench, pwlab, tmp_path)
    r = pty_run([[SSH, "-F", cfg, "pb", "echo", "bonjour"]], e2e_env(bench, tmp_path),
                answers=["change-sur-le-serveur"], trigger=rb"Password: ", timeout=90)
    assert r.returncode == 0, (r.stdout, r.stderr, r.screen)
    assert "mot de passe du coffre refusé pour tuser@pb (Cible B (mdp))" in r.stderr + r.screen
    assert pwlab.log("b").count("ok=False") == 1, "mot de passe du coffre donné une seule fois"
    assert "change-sur-le-serveur" not in r.screen


@pytest.mark.parametrize("pwlab", [None], indirect=True)
def test_bout_en_bout_cle_d_hote_relayee(bench, pwlab, tmp_path):
    setup_pw(bench)
    cfg = e2e_config(bench, pwlab, tmp_path, known=())
    r = pty_run([[SSH, "-F", cfg, "pa", "echo", "x"]], e2e_env(bench, tmp_path), answers=["yes"],
                trigger=rb"\(yes/no", timeout=90)
    assert r.returncode == 0, (r.stdout, r.stderr, r.screen)
    assert "yes" in r.screen.split("(yes/no")[-1], "réponse visible au terminal"
    assert "ok=True" in pwlab.log("a")


def test_bout_en_bout_elements_crees_par_password_add(bench, pwlab, tmp_path):
    """Story 18 : éléments créés par `password add` (mot de passe sur stdin), puis `ssh B` via A :
    l'askpass donne ces mots de passe, sans saisie ; aucun argv ni fichier ne les porte."""
    setup_pw(bench, items=[], generate=False)
    with ArgvWatch("password", [PW_A, PW_B], heuristics=False) as w:
        r = bench.run("password", "add", "Saut A", "--host", "pa", "--user", "juser", input=PW_A + "\n")
        assert r.returncode == 0, r.stderr
        r = bench.run("password", "add", "Cible B", "--host", "tuser@pb", input=PW_B + "\n")
        assert r.returncode == 0, r.stderr
    assert any("add" in a for a in w.seen) and not w.suspect, w.suspect
    cfg = e2e_config(bench, pwlab, tmp_path)
    with ArgvWatch("--password", [PW_A, PW_B], heuristics=False) as w:
        r = pty_run([[SSH, "-F", cfg, "pb", "echo", "bonjour"]], e2e_env(bench, tmp_path), trigger=rb"assword",
                    timeout=90)
    assert r.returncode == 0, (r.stdout, r.stderr, r.screen)
    assert r.stdout.strip() == "OK port=%d cmd=echo bonjour" % pwlab.ports["b"]
    assert "assword" not in r.screen, "aucune invite au terminal"
    assert "port=%d password user=juser ok=True" % pwlab.ports["a"] in pwlab.log("a")
    assert "port=%d keyboard-interactive user=tuser ok=True" % pwlab.ports["b"] in pwlab.log("b")
    assert w.seen and not w.suspect, w.suspect
    roots = [bench.home, bench.runtime] + [p for p in tmp_path.iterdir() if p.name != "server"]
    assert files_with(roots, [PW_A, PW_B]) == []

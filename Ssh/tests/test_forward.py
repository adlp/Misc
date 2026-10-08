"""Transfert d'agent restreint par hôte (story 8, CAP-8) : champ `sshvault-forward`, commande
`sshvault forward`, blocs de transfert du ssh_config généré, `sshvault ensure --forward`,
sous-agents (`$XDG_RUNTIME_DIR/sshvault/fwd/<fid>.sock`) et `agent status/purge/lock/stop`.

Une ligne de test par ligne de la matrice et par critère d'acceptation, avec les vrais
`ssh-agent`/`ssh-add`, le faux `bw`, l'OpenSSH du poste (`ssh -G`) et, de bout en bout, un
sshd de test sur 127.0.0.1 (utilisateur courant, `PermitUserRC no`) : `ssh a 'ssh-add -L'`
liste ce que voit l'hôte distant."""
import getpass
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

import pytest

from bench import (HAVE_OPENSSH, ID_BASTION, ID_PROD, agent_list, agents_under, make_askpass, proc_alive,
                   ssh_item, start_agent, wait_gone)
from sshvault import sshconfig
from sshvault.agent import AgentError, forward_id, forward_paths
from sshvault.backend import FORWARD_FIELD, SshKeyItem
from sshvault.bw import BwBackend, hosts_of, with_hosts

SSH = shutil.which("ssh")
SSHD = "/usr/sbin/sshd"
HAVE_LAB = bool(SSH and os.access(SSHD, os.X_OK) and HAVE_OPENSSH)
needs_ssh = pytest.mark.skipif(SSH is None, reason="client ssh absent")
needs_openssh = pytest.mark.skipif(not HAVE_OPENSSH, reason="ssh-agent/ssh-add absents")

ID_K1 = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
ID_K2 = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
ID_K3 = "cccccccc-3333-4333-8333-cccccccccccc"


def fid(pattern):
    return hashlib.sha256(pattern.lower().encode()).hexdigest()[:16]


def fwd_field(value):
    return {"name": FORWARD_FIELD, "value": value, "type": 0, "linkedId": None}


def unlocked(bench):
    bench.unlocked("keyring" if bench.ring else "file")


def one_line_error(r):
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    assert len(lines) == 1, r.stderr
    assert "Traceback" not in r.stderr
    return lines[0]


def fwd_dir(bench):
    return bench.runtime / "sshvault" / "fwd"


def fwd_sock(bench, pattern):
    return fwd_dir(bench) / (fid(pattern) + ".sock")


def fwd_state(bench, pattern):
    p = fwd_dir(bench) / (fid(pattern) + ".json")
    return json.loads(p.read_text()) if p.exists() else None


def fwd_keys(bench, pattern):
    rc, lines = agent_list(fwd_sock(bench, pattern))
    return [l.split()[1] for l in lines]


def ensure_fwd(bench, pattern, *ids, env=None):
    args = ["ensure", "--forward", fid(pattern)]
    for i in ids:
        args += ["--id", i]
    return bench.run(*args, env=env)


def no_confirm(bench):
    r = bench.run("config", "set", "forward-confirm", "false")
    assert r.returncode == 0, r.stderr


def forward_vault(bench, k2_forward="a", k3_forward=None):
    """K1 (clé prod) : identité de « a » ; K2 (clé bastion) : transférée vers `k2_forward` ;
    K3 (clé perso) : transférée vers `k3_forward` s'il est donné."""
    bench.items = [ssh_item(ID_K1, "K1 identité", bench.keys["prod"], hosts="a"),
                   ssh_item(ID_K2, "K2 transférée", bench.keys["bastion"],
                            extra_fields=[fwd_field(k2_forward)] if k2_forward else ())]
    if k3_forward:
        bench.items.append(ssh_item(ID_K3, "K3 transférée", bench.keys["perso"], extra_fields=[fwd_field(k3_forward)]))
    bench.write_vault()


def lock_main(bench):
    """Agent dédié vivant (vrai ssh-agent sur le socket dédié), état « verrouillé » enregistré."""
    d = bench.runtime / "sshvault"
    d.mkdir(mode=0o700, exist_ok=True)
    pid = start_agent(bench.sock())
    st = os.stat(str(bench.sock()))
    rec = {"pid": pid, "socket": str(bench.sock()), "dev": st.st_dev, "ino": st.st_ino}
    p = d / "agent.json"
    fd = os.open(str(p) + ".t", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, json.dumps({"version": 1, "agent": rec, "locked": True, "keys": {}}).encode())
    os.close(fd)
    os.replace(str(p) + ".t", str(p))
    return pid


def loads(bench, sock=None):
    """Chargements par ssh-add (`… -`, sans la vérification -h), sur `sock` si donné."""
    return [a for s, a in bench.ssh_add_calls() if a.startswith("-t ") and (sock is None or s == str(sock))]


# --- fid, chemins -------------------------------------------------------------------------

def test_fid_et_chemins(tmp_path):
    assert forward_id("Bastion") == forward_id(" bastion ") == hashlib.sha256(b"bastion").hexdigest()[:16]
    assert forward_id("*.dmz") != forward_id("*.DMZ.x")
    d, sock, state = forward_paths("/run/user/1000/sshvault", fid("a"))
    assert (d, sock, state) == ("/run/user/1000/sshvault/fwd", "/run/user/1000/sshvault/fwd/%s.sock" % fid("a"),
                                "/run/user/1000/sshvault/fwd/%s.json" % fid("a"))
    for bad in ("", "ABCDEF0123456789", "0123", "../../../../etc/x", fid("a") + "0"):
        with pytest.raises(AgentError):
            forward_paths("/run/user/1000/sshvault", bad)
    with pytest.raises(AgentError, match="trop long"):
        forward_paths("/" + "x" * 80 + "/sshvault", fid("a"))


# --- coffre : champ sshvault-forward -------------------------------------------------------

def test_champ_forward_lu_et_ecrit_seul():
    it = {"type": 5, "name": "n", "sshKey": {"publicKey": "ssh-ed25519 AAAA", "privateKey": "x", "keyFingerprint": "f"},
          "fields": [{"name": "sshvault-hosts", "value": "a,b", "type": 0, "linkedId": None},
                     {"name": "sshvault-forward", "value": " Bastion , *.dmz", "type": 1, "linkedId": None}]}
    item = BwBackend._item(it)
    assert item.hosts == ("a", "b") and item.forward == ("Bastion", "*.dmz")
    assert hosts_of(it, FORWARD_FIELD) == ("bastion", "*.dmz") and hosts_of(it) == ("a", "b")
    new = with_hosts(it, ("x",), FORWARD_FIELD)
    assert new["fields"][0] == it["fields"][0], "sshvault-hosts inchangé"
    assert new["fields"][1] == {"name": "sshvault-forward", "value": "x", "type": 1, "linkedId": None}, "type gardé"
    assert with_hosts(it, (), FORWARD_FIELD)["fields"] == [it["fields"][0]], "champ retiré s'il devient vide"
    assert with_hosts(it, ("y",))["fields"][1] == it["fields"][1], "set_hosts ne touche pas au transfert"


def test_cli_forward_add_remove_set_list(bench):
    unlocked(bench)
    r = bench.run("forward", "add", "--id", ID_BASTION, "Saut.DMZ", "*.lab")
    assert r.returncode == 0, r.stderr
    assert "transferts de « Bastion RSA » : saut.dmz,*.lab" in r.stdout
    item = bench.vault_item(ID_BASTION)
    fields = [(f["name"], f["value"]) for f in item["fields"]]
    assert ("sshvault-forward", "saut.dmz,*.lab") in fields
    assert ("sshvault-hosts", "Bastion,jump") in fields and ("note", "rebond") in fields, "le reste inchangé"
    assert len([c for c in bench.calls() if c["argv"][1:3] == ["edit", "item"]]) == 1
    # ssh_config régénéré : blocs de transfert
    text = (bench.home / ".ssh" / "sshvault" / "config").read_text()
    assert "# transfert d'agent saut.dmz %s\n" % fid("saut.dmz") in text
    assert "Match originalhost *.lab\n    ForwardAgent \"%s\"\n" % fwd_sock(bench, "*.lab") in text
    r = bench.run("forward", "list", "--id", ID_BASTION)
    assert r.returncode == 0 and r.stdout == "saut.dmz\n*.lab\n"
    r = bench.run("forward", "remove", "--id", ID_BASTION, "absent.example")
    assert r.returncode == 1 and "n'a pas le transfert vers « absent.example » : rien écrit" in one_line_error(r)
    r = bench.run("forward", "add", "--id", ID_BASTION, "a b")
    assert r.returncode == 2
    r = bench.run("forward", "add", "--host", "*", "x")  # plusieurs éléments
    assert r.returncode == 2 and "préciser --id" in r.stderr
    r = bench.run("forward", "add", "--id", ID_BASTION, "*")
    assert r.returncode == 0 and "toutes les connexions ssh" in r.stderr, "avertissement attrape-tout"
    r = bench.run("forward", "remove", "--id", ID_BASTION, "*", "*.lab")
    assert r.returncode == 0, r.stderr
    r = bench.run("forward", "set", "--id", ID_BASTION, "")
    assert r.returncode == 0 and "transferts de « Bastion RSA » : -" in r.stdout
    assert "sshvault-forward" not in [f["name"] for f in bench.vault_item(ID_BASTION)["fields"]]
    assert "transfert d'agent" not in (bench.home / ".ssh" / "sshvault" / "config").read_text()


# --- ssh_config généré ---------------------------------------------------------------------

def _items(keys):
    return [SshKeyItem(ID_K1, "K1", keys["prod"]["public"], "", ("a", "web.example"), ()),
            SshKeyItem(ID_K2, "K2", keys["bastion"]["public"], "", (), ("a", "*.dmz", "Saut.DMZ", "x.dmz.*")),
            SshKeyItem(ID_K3, "K3", keys["perso"]["public"], "", ("k3.example",), ("a",))]


def test_build_blocs_de_transfert(keys, tmp_path):
    paths = sshconfig.Paths(str(tmp_path / "h"))
    sock = "/run/user/1000/sshvault/agent.sock"
    plan = sshconfig.build(_items(keys), paths, sock, "/opt/sshvault")
    text = plan.config.decode()
    fsock = lambda p: "/run/user/1000/sshvault/fwd/%s.sock" % fid(p)  # noqa: E731
    exe = "'/opt/sshvault' ensure --forward"
    block = lambda p, m, ids: ("\n# transfert d'agent %s %s\nMatch originalhost %s exec \"%s %s%s\"\n"  # noqa: E731
                               "Match originalhost %s\n    ForwardAgent \"%s\"\n"
                               % (p, fid(p), m, exe, fid(p), "".join(" --id " + i for i in ids), p, fsock(p)))
    # littéraux d'abord, puis motifs à joker du plus précis au moins précis ; la ligne exec
    # exclut les motifs des blocs précédents
    fwd_text = (block("a", "a", [ID_K2, ID_K3]) + block("saut.dmz", "saut.dmz,!a", [ID_K2])
                + block("x.dmz.*", "x.dmz.*,!a,!saut.dmz", [ID_K2])
                + block("*.dmz", "*.dmz,!a,!saut.dmz,!x.dmz.*", [ID_K2]))
    assert text.startswith(sshconfig.HEADER + fwd_text), text
    # blocs d'identité ensuite, sans ForwardAgent
    ident = text[len(sshconfig.HEADER + fwd_text):]
    assert ident.startswith("\n# K1 %s\n" % ID_K1) and "ForwardAgent" not in ident
    assert plan.forward == {fid("a"): ("a", [ID_K2, ID_K3]), fid("saut.dmz"): ("saut.dmz", [ID_K2]),
                            fid("x.dmz.*"): ("x.dmz.*", [ID_K2]), fid("*.dmz"): ("*.dmz", [ID_K2])}
    assert plan.blocks == 6
    assert any("« saut.dmz » et « *.dmz » se recouvrent" in w and "seul le premier bloc (« saut.dmz »)" in w
               for w in plan.warnings), plan.warnings
    assert "%h" not in text and "%n" not in text


def test_build_transfert_avertissements(keys, tmp_path):
    paths = sshconfig.Paths(str(tmp_path / "h"))
    sock = "/run/user/1000/sshvault/agent.sock"
    items = [SshKeyItem("pas-un-uuid", "X", keys["prod"]["public"], "", (), ("a",)),
             SshKeyItem(ID_K2, "K2", keys["bastion"]["public"], "", (), ("a", "b c", "*")),
             SshKeyItem(ID_K3, "K3", "illisible", "", (), ("a",))]
    plan = sshconfig.build(items, paths, sock, "/opt/sshvault")
    text = plan.config.decode()
    w = "\n".join(plan.warnings)
    assert "pas-un-uuid" in w and "pas de transfert de cette clé vers « a »" in w
    assert "K3" in w and "clé publique illisible" in w
    assert "motif de transfert invalide « b c »" in w and "b c" not in text
    assert "motif de transfert « * » : %s" % sshconfig.FORWARD_CATCH_ALL_WARNING in w
    assert "--forward %s --id %s\"\n" % (fid("a"), ID_K2) in text, "seul l'id valide dans la commande"
    assert text.index("originalhost a ") < text.index("originalhost *,!a exec"), "attrape-tout en dernier"
    # auto-load false : sans Match exec, le socket n'existerait jamais (un saut ssh -W par cet
    # hôte s'arrêterait) : ForwardAgent no, avertissement ; jamais l'agent dédié
    plan = sshconfig.build(items, paths, sock, None)
    text = plan.config.decode()
    assert " exec " not in text and "Match originalhost a\n    ForwardAgent no\n" in text
    assert "fwd/" not in text and any("auto-load false" in x for x in plan.warnings)
    assert plan.forward[fid("a")] == ("a", []), "sans Match exec : aucune clé autorisée (sous-agent arrêté)"
    # clé seule et invalide : ForwardAgent no, dit
    plan = sshconfig.build(items[:1], paths, sock, "/opt/sshvault")
    assert " exec " not in plan.config.decode() and "ForwardAgent no" in plan.config.decode()
    assert "aucune clé transférable" in "\n".join(plan.warnings)
    # socket de transfert trop long : refus
    with pytest.raises(sshconfig.SshConfigError, match="trop long"):
        sshconfig.build(items, paths, "/" + "x" * 80 + "/sshvault/agent.sock", "/opt/sshvault")


def test_forward_command_refus(tmp_path):
    ok = sshconfig.forward_command("/a b%c/sshvault", fid("a"), [ID_K2.upper(), ID_K3])
    assert ok == "'/a b%%%%c/sshvault' ensure --forward %s --id %s --id %s" % (fid("a"), ID_K2, ID_K3)
    for exe, f, ids in (("/a'b/sshvault", fid("a"), [ID_K2]), ("relatif", fid("a"), [ID_K2]),
                        ("/opt/sshvault", "%h", [ID_K2]), ("/opt/sshvault", fid("a"), []),
                        ("/opt/sshvault", fid("a"), [ID_K2 + ";id"]), ("/opt/sshvault", fid("a"), ["%n"])):
        with pytest.raises(sshconfig.SshConfigError):
            sshconfig.forward_command(exe, f, ids)


def _ssh_G(tmp_path, gen, host, after="", opts=()):
    main = tmp_path / "ssh_config_de_test"
    main.write_text('Include "%s"\n%s' % (gen, after))
    main.chmod(0o600)
    r = subprocess.run([SSH, "-G", "-F", str(main), *opts, host], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=30)
    assert r.returncode == 0, r.stderr
    return [v for k, v in (l.split(" ", 1) for l in r.stdout.splitlines()) if k == "forwardagent"]


@needs_ssh
def test_ssh_G_premiere_valeur_gagnante(keys, tmp_path):
    """OpenSSH du poste : le chemin du sous-agent l'emporte sur un `ForwardAgent yes` de la
    config de l'utilisateur placé après l'Include et sur `ssh -A` ; un hôte d'identité sans
    transfert ne reçoit aucune directive (la config de l'utilisateur décide)."""
    paths = sshconfig.Paths(str(tmp_path / "h"))
    sock = "/run/sshvault-test-absent/sshvault/agent.sock"  # court : socket jamais ouvert par ssh -G
    plan = sshconfig.build(_items(keys), paths, sock, "/bin/true")
    gen = tmp_path / "gen"
    gen.write_bytes(plan.config)
    gen.chmod(0o600)
    yes = "Host *\n    ForwardAgent yes\n"
    fsock = lambda p: os.path.join(os.path.dirname(sock), "fwd", fid(p) + ".sock")  # noqa: E731
    assert _ssh_G(tmp_path, gen, "a", yes) == [fsock("a")]
    assert _ssh_G(tmp_path, gen, "A", yes, ("-A",)) == [fsock("a")], "ssh -A : le chemin de config gagne"
    assert _ssh_G(tmp_path, gen, "a", "", ("-o", "ForwardAgent=yes")) == [fsock("a")]
    assert _ssh_G(tmp_path, gen, "saut.dmz", yes) == [fsock("saut.dmz")], "premier bloc gagne (recouvrement)"
    assert _ssh_G(tmp_path, gen, "y.dmz", yes) == [fsock("*.dmz")]
    assert _ssh_G(tmp_path, gen, "web.example", yes) == ["yes"], "hôte d'identité : config de l'utilisateur"
    assert _ssh_G(tmp_path, gen, "web.example", "") == ["no"]


def test_ssh_config_avertit_forwardagent_yes(bench):
    """Critère : hôte sshvault sans transfert et `ForwardAgent yes` dans la config de
    l'utilisateur : `ssh-config` le signale pour cet hôte (littéral), pas pour un motif ni pour
    un hôte dont le transfert est déclaré, et n'écrit aucune directive ForwardAgent pour lui."""
    unlocked(bench)
    bench.items[2]["fields"].append(fwd_field("jump"))  # Bastion RSA : transfert vers jump
    bench.write_vault()
    user = bench.home / ".ssh" / "config"
    user.parent.mkdir(mode=0o700)
    user.write_text('Include "%s"\nHost *\n    ForwardAgent yes\n' % (bench.home / ".ssh" / "sshvault" / "config"))
    user.chmod(0o600)
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    warned = re.findall(r"^sshvault: avertissement : hôte « ([^»]+) » : ForwardAgent yes", r.stderr, re.M)
    assert warned == ["bastion", "prod.example.com"], r.stderr
    assert "l'agent dédié entier" in r.stderr
    text = (bench.home / ".ssh" / "sshvault" / "config").read_text()
    assert text.count("ForwardAgent") == 1 and "Match originalhost jump\n    ForwardAgent" in text
    r = bench.run("ssh-config", "--check")
    assert re.findall(r"hôte « ([^»]+) » : ForwardAgent yes", r.stderr) == ["bastion", "prod.example.com"]
    # ForwardAgent no (ou absent) : rien à dire
    user.write_text('Include "%s"\n' % (bench.home / ".ssh" / "sshvault" / "config"))
    r = bench.run("ssh-config")
    assert r.returncode == 0 and "ForwardAgent yes" not in r.stderr


def test_config_forward_confirm(bench):
    r = bench.run("config", "get", "forward-confirm")
    assert r.returncode == 0 and r.stdout == "forward-confirm true (défaut)\n"
    r = bench.run("config", "set", "forward-confirm", "no")
    assert r.returncode == 0 and r.stdout.startswith("forward-confirm false\n")
    assert bench.run("config", "set", "forward-confirm", "peut-être").returncode == 2


# --- ensure --forward ---------------------------------------------------------------------

@needs_openssh
def test_ensure_forward_nominal_et_chemin_rapide(bench):
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    r = ensure_fwd(bench, "a", ID_K2)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", ""), r.stderr
    assert fwd_keys(bench, "a") == [bench.blob("bastion")], "K2 seule dans le sous-agent"
    assert not bench.sock().exists(), "agent dédié jamais lancé ni touché"
    calls = bench.ssh_add_calls()
    assert calls and all(s == str(fwd_sock(bench, "a")) for s, _ in calls), "SSH_AUTH_SOCK = socket du sous-agent"
    assert loads(bench) == ["-t 3600 -"], "durée key-ttl, sans -c (forward-confirm false), jamais -h"
    st = fwd_state(bench, "a")
    e = st["keys"][bench.keys["bastion"]["fingerprint"]]
    assert e["id"] == ID_K2 and e["confirm"] is False and e["restrict"] is False and st["agent"]["pid"] > 1
    assert oct((fwd_dir(bench)).stat().st_mode & 0o777) == "0o700"
    assert oct((fwd_dir(bench) / (fid("a") + ".json")).stat().st_mode & 0o777) == "0o600"
    # chemin rapide : ni bw ni ssh-add de chargement
    n = len(bench.calls())
    r = ensure_fwd(bench, "a", ID_K2)
    assert (r.returncode, r.stderr) == (0, "") and len(bench.calls()) == n and len(loads(bench)) == 1
    # jamais de clé privée dans le dossier d'exécution
    for p in bench.runtime.rglob("*"):
        if p.is_file():
            assert b"PRIVATE KEY" not in p.read_bytes(), p


@needs_openssh
def test_ensure_forward_cle_en_trop_retiree(bench):
    """Une clé non autorisée dans le sous-agent (chargée à la main, ou d'un élément retiré)
    est retirée ; le chemin rapide ne l'accepte pas."""
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    env = {k: v for k, v in os.environ.items() if k not in ("SSH_AUTH_SOCK", "SSH_AGENT_PID")}
    env["SSH_AUTH_SOCK"] = str(fwd_sock(bench, "a"))
    subprocess.run(["ssh-add", "-q", "-"], input=bench.keys["prod"]["private"], env=env, text=True, check=True,
                   capture_output=True)
    assert sorted(fwd_keys(bench, "a")) == sorted([bench.blob("bastion"), bench.blob("prod")])
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 0, r.stderr
    assert fwd_keys(bench, "a") == [bench.blob("bastion")]


@needs_openssh
def test_ensure_forward_plusieurs_cles_tout_ou_rien(bench):
    unlocked(bench)
    forward_vault(bench, k3_forward="a")
    no_confirm(bench)
    absent = "dddddddd-4444-4444-8444-dddddddddddd"
    r = ensure_fwd(bench, "a", ID_K2, absent)
    assert r.returncode == 4 and "transfert d'agent" in one_line_error(r)
    assert fwd_keys(bench, "a") == [], "rien chargé"
    r = ensure_fwd(bench, "a", ID_K2, ID_K3)
    assert r.returncode == 0, r.stderr
    assert sorted(fwd_keys(bench, "a")) == sorted([bench.blob("bastion"), bench.blob("perso")])
    assert len(loads(bench)) == 2


@needs_openssh
def test_ensure_forward_coffre_fait_foi(bench):
    """Config générée périmée : l'élément ne déclare plus ce transfert : rien chargé."""
    unlocked(bench)
    forward_vault(bench, k2_forward="autre")
    no_confirm(bench)
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 4 and "n'est plus déclarée pour ce transfert" in one_line_error(r)
    assert fwd_keys(bench, "a") == []


@needs_openssh
def test_ensure_forward_confirm_sans_askpass(bench):
    """forward-confirm (défaut oui) sans askpass utilisable : une ligne, code 4, aucun
    sous-agent lancé, aucun appel bw."""
    unlocked(bench)
    forward_vault(bench)
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 4 and "forward-confirm" in one_line_error(r) and "askpass" in r.stderr
    assert not fwd_sock(bench, "a").exists() and not agents_under(bench.runtime)
    assert not [c for c in bench.calls() if c["argv"][1:3] == ["get", "item"]]


@needs_openssh
def test_ensure_forward_confirm_avec_askpass(bench, tmp_path):
    unlocked(bench)
    forward_vault(bench)
    askpass, _ = make_askpass(tmp_path, reply="yes")
    ask = {"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"}
    r = ensure_fwd(bench, "a", ID_K2, env=ask)
    assert r.returncode == 0, r.stderr
    assert loads(bench) == ["-t 3600 -c -"]
    st = fwd_state(bench, "a")
    assert st["agent"]["askpass"] is True and st["keys"][bench.keys["bastion"]["fingerprint"]]["confirm"] is True
    # sous-agent lancé sans askpass (forward-confirm false), puis forward-confirm true : relancé
    assert bench.run("agent", "stop").returncode == 0
    no_confirm(bench)
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    old = fwd_state(bench, "a")["agent"]["pid"]
    assert fwd_state(bench, "a")["agent"]["askpass"] is False
    r = bench.run("config", "set", "forward-confirm", "true")
    assert r.returncode == 0 and "sous-agents de transfert arrêtés : rechargés au prochain ssh" in r.stdout
    assert wait_gone([old], timeout=10) and not fwd_sock(bench, "a").exists(), "clés sans -c plus transférées"
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 4 and "forward-confirm" in one_line_error(r)
    assert not fwd_sock(bench, "a").exists(), "refusé sans askpass : rien lancé"
    r = ensure_fwd(bench, "a", ID_K2, env=ask)
    assert r.returncode == 0, r.stderr
    assert fwd_state(bench, "a")["agent"]["askpass"] is True
    assert loads(bench)[-1] == "-t 3600 -c -"


@needs_openssh
def test_ensure_forward_agent_dedie_verrouille(bench):
    """`agent lock` posé : le transfert est refusé (code 3), rien lancé ; l'agent dédié n'est
    que lu (état), jamais contacté."""
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    pid = lock_main(bench)
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 3 and "agent dédié verrouillé" in one_line_error(r)
    assert not fwd_sock(bench, "a").exists() and bench.ssh_add_calls() == []
    # agent dédié mort, état « verrouillé » resté : ne bloque plus rien
    os.kill(pid, signal.SIGKILL)
    assert wait_gone([pid], timeout=10)
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 0, r.stderr
    assert fwd_keys(bench, "a") == [bench.blob("bastion")]


@needs_openssh
def test_ensure_forward_coffre_verrouille_sans_invite(bench):
    """Matrice « sous-agent impossible » : une ligne, code ≠ 0 ; le sous-agent reste vide."""
    forward_vault(bench)
    no_confirm(bench)
    bench.set_state(session=None)
    r = bench.run("--nointeraction", "ensure", "--forward", fid("a"), "--id", ID_K2)
    assert r.returncode == 3 and "coffre verrouillé" in one_line_error(r)
    assert fwd_keys(bench, "a") == []


@needs_openssh
def test_ensure_forward_cle_expiree_rechargee(bench):
    """Matrice « clé expirée en session » : `key-ttl` écoulé, le sous-agent est vide ; la
    connexion suivante recharge."""
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    assert bench.run("config", "set", "key-ttl", "2s").returncode == 0
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    assert loads(bench) == ["-t 2 -"]
    deadline = time.monotonic() + 10
    while fwd_keys(bench, "a") and time.monotonic() < deadline:
        time.sleep(0.2)
    assert fwd_keys(bench, "a") == [], "clé expirée : agent vide"
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    assert len(loads(bench)) == 2


@needs_openssh
def test_ensure_forward_usage(bench):
    for args in (["ensure", "--forward", "zz", "--id", ID_K2], ["ensure", "--id", ID_K1, "--id", ID_K2],
                 ["ensure", "--forward", fid("a"), "--id", "x"]):
        r = bench.run(*args)
        assert r.returncode == 2, args
        one_line_error(r)


# --- agent status / purge / lock / stop -----------------------------------------------------

def _two_subagents(bench):
    """Sous-agents « a » (K2) et « b » (K3) chargés, agent dédié avec K1 ; ssh_config généré."""
    unlocked(bench)
    bench.items = [ssh_item(ID_K1, "K1 identité", bench.keys["prod"], hosts="a"),
                   ssh_item(ID_K2, "K2 transférée", bench.keys["bastion"], extra_fields=[fwd_field("a")]),
                   ssh_item(ID_K3, "K3 transférée", bench.keys["perso"], extra_fields=[fwd_field("b")])]
    bench.write_vault()
    no_confirm(bench)
    assert bench.run("ssh-config").returncode == 0
    assert bench.run("load", "--id", ID_K1).returncode == 0
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    assert ensure_fwd(bench, "b", ID_K3).returncode == 0
    return [fwd_state(bench, p)["agent"] for p in ("a", "b")]


@needs_openssh
def test_agent_status_purge(bench):
    _two_subagents(bench)
    r = bench.run("agent", "status")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "transfert a (%s) : actif, pid " % fid("a") in out and "transfert b (%s) : actif" % fid("b") in out
    assert re.search(r"^  K2 transférée\t%s\t(59m\d\ds|1h00m00s)\t-$" % re.escape(bench.keys["bastion"]["fingerprint"]),
                     out, re.M), out
    assert "  K3 transférée\t%s\t" % bench.keys["perso"]["fingerprint"] in out
    assert out.index("K1 identité") < out.index("transfert a"), "agent dédié d'abord"
    r = bench.run("agent", "purge")
    assert r.returncode == 0, r.stderr
    assert fwd_keys(bench, "a") == [] and fwd_keys(bench, "b") == [] and bench.agent_keys() == []
    assert fwd_state(bench, "a")["keys"] == {}
    r = bench.run("agent", "status")
    assert r.stdout.count("  clés : aucune") == 2


@needs_openssh
def test_agent_stop_tout_arrete(bench):
    """Critère : après `agent stop`, aucun ssh-agent de sshvault ne reste et `fwd/` est vide."""
    subs = _two_subagents(bench)
    main = bench.agent_state()["agent"]
    r = bench.run("agent", "stop")
    assert r.returncode == 0, r.stderr
    pids = [main["pid"], main["watcher"]] + [x for a in subs for x in (a["pid"], a["watcher"])]
    assert wait_gone(pids, timeout=10), "agents et surveillants arrêtés"
    assert agents_under(bench.runtime) == []
    assert os.listdir(str(fwd_dir(bench))) == []
    r = bench.run("agent", "status")
    assert r.returncode == 3 and "transfert" not in r.stdout


@needs_openssh
def test_agent_lock_arrete_les_sous_agents_puis_rechargement(bench, tmp_path):
    """Critère : `agent lock` vide et arrête les sous-agents ; pendant le verrou, le transfert
    est refusé ; après `unlock`, le ssh suivant (ensure --forward) les recharge."""
    subs = _two_subagents(bench)
    askpass, _ = make_askpass(tmp_path, reply="verrou de test")
    ask = {"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"}
    r = bench.run("agent", "lock", env=ask)
    assert r.returncode == 0, r.stderr
    assert wait_gone([a["pid"] for a in subs], timeout=10) and not fwd_sock(bench, "a").exists()
    purges = [s for s, a in bench.ssh_add_calls() if a == "-D"]
    assert sorted(purges) == sorted([str(fwd_sock(bench, "a")), str(fwd_sock(bench, "b"))]), "vidés avant l'arrêt"
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 3 and "agent dédié verrouillé" in one_line_error(r)
    assert not fwd_sock(bench, "a").exists()
    assert bench.run("agent", "unlock", env=ask).returncode == 0
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 0, r.stderr
    assert fwd_keys(bench, "a") == [bench.blob("bastion")]


@needs_openssh
def test_ssh_config_arrete_les_sous_agents_non_references(bench):
    """Matrice « transfert retiré » : bloc retiré, sous-agent arrêté ; une clé retirée d'un
    motif encore déclaré arrête aussi son sous-agent (rechargé sans elle)."""
    subs = _two_subagents(bench)
    r = bench.run("forward", "remove", "--id", ID_K3, "b")
    assert r.returncode == 0, r.stderr
    assert "sous-agent de transfert %s, plus référencé : agent arrêté" % fid("b") in r.stdout
    assert wait_gone([subs[1]["pid"]], timeout=10) and not fwd_sock(bench, "b").exists()
    assert proc_alive(subs[0]["pid"]), "sous-agent encore référencé gardé"
    assert "transfert d'agent b " not in (bench.home / ".ssh" / "sshvault" / "config").read_text()
    # K3 ajoutée puis retirée de « a » : le sous-agent de « a » est arrêté s'il la garde
    assert bench.run("forward", "add", "--id", ID_K3, "a").returncode == 0
    assert ensure_fwd(bench, "a", ID_K2, ID_K3).returncode == 0
    assert len(fwd_keys(bench, "a")) == 2
    r = bench.run("forward", "remove", "--id", ID_K3, "a")
    assert r.returncode == 0, r.stderr
    assert "a (%s), clé retirée du transfert : agent arrêté" % fid("a") in r.stdout
    assert not fwd_sock(bench, "a").exists()


@needs_openssh
def test_sous_agent_surveillant_et_orphelin(bench):
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    a = fwd_state(bench, "a")["agent"]
    with open("/proc/%d/cmdline" % a["watcher"], "rb") as f:
        assert f.read().split(b"\0")[1:5] == [b"-m", b"sshvault.watch", str(a["pid"]).encode(),
                                               str(fwd_sock(bench, "a")).encode()]
    os.unlink(str(fwd_sock(bench, "a")))
    assert wait_gone([a["pid"], a["watcher"]], timeout=8), "surveillant : socket disparu, sous-agent arrêté"
    # orphelin (socket disparu, sans surveillant) : arrêté au prochain lancement de sshvault
    pid = start_agent(fwd_sock(bench, "a"))
    os.unlink(str(fwd_sock(bench, "a")))
    bench.run("status")
    assert wait_gone([pid], timeout=10), "orphelin arrêté"


# --- de bout en bout : sshd de test -----------------------------------------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Lab:
    """sshd « a » (n'accepte que la clé prod) et « b » (bastion), sur 127.0.0.1 ; agent
    transféré permis, `~/.ssh/rc` réel jamais exécuté (PermitUserRC no)."""

    def __init__(self, d, keys):
        self.user, self.ports, self.hostkeys, self.procs, self.logs = getpass.getuser(), {}, {}, {}, {}
        for name, key in (("a", "prod"), ("b", "bastion")):
            sd = d / name
            sd.mkdir()
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(sd / "hostkey")], check=True)
            self.hostkeys[name] = " ".join((sd / "hostkey.pub").read_text().split()[:2])
            (sd / "authorized_keys").write_text(keys[key]["public"] + "\n")
            port = _free_port()
            (sd / "sshd_config").write_text(
                "Port %d\nListenAddress 127.0.0.1\nHostKey %s\nPidFile %s\nAuthorizedKeysFile %s\nStrictModes no\n"
                "UsePAM no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nPrintMotd no\n"
                "AllowAgentForwarding yes\nPermitUserRC no\nLogLevel VERBOSE\n"
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
                assert time.monotonic() < deadline, "sshd %s muet : %s" % (name, self.logs[name].read_text())
                time.sleep(0.1)

    def stop(self):
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
def lab(tmp_path_factory, keys):
    if not HAVE_LAB:
        pytest.skip("ssh, sshd, ssh-agent ou ssh-add absent")
    lb = Lab.__new__(Lab)
    lb.procs = {}
    try:
        lb.__init__(tmp_path_factory.mktemp("lab-fwd"), keys)
    except BaseException:
        lb.stop()
        raise
    try:
        yield lb
    finally:
        lb.stop()


def lab_setup(bench, lab, tmp_path, user_forward="yes"):
    """ssh_config généré (coffre déverrouillé) puis config ssh de test : « a » direct, « b »
    derrière le rebond « a » ; `ForwardAgent <user_forward>` pour tous les hôtes, après l'Include."""
    kh = ["[127.0.0.1]:%d %s" % (lab.ports[n], lab.hostkeys[n]) for n in ("a", "b")]
    kh += ["a %s" % lab.hostkeys["a"], "b %s" % lab.hostkeys["b"]]
    bench.known_hosts.write_text("\n".join(kh) + "\n")
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    main = tmp_path / "ssh_config_de_test"
    main.write_text(
        'Include "%s"\nHost a\n    HostName 127.0.0.1\n    Port %d\nHost b\n    HostName 127.0.0.1\n    Port %d\n'
        "    ProxyJump a\nHost *\n    User %s\n    UserKnownHostsFile %s\n    GlobalKnownHostsFile /dev/null\n"
        "    StrictHostKeyChecking yes\n    BatchMode yes\n    ConnectTimeout 10\n    ForwardAgent %s\n"
        % (bench.home / ".ssh" / "sshvault" / "config", lab.ports["a"], lab.ports["b"], lab.user, bench.known_hosts,
           user_forward))
    main.chmod(0o600)
    return main


def ssh_remote(bench, main, host, command, *opts, env=None):
    e = dict(bench.env, SSHVAULT_TEST_TRACE="1")
    e.update(env or {})
    return subprocess.run([SSH, "-F", str(main), *opts, host, command], env=e, capture_output=True, text=True,
                          timeout=90, stdin=subprocess.DEVNULL, start_new_session=True)


def remote_blobs(stdout):
    return [l.split()[1] for l in stdout.splitlines() if l.startswith("ssh-")]


def test_bout_en_bout_seule_k2_transferee(bench, lab, tmp_path):
    """Critère : K1 (hôte a) et K2 (transfert vers a) : `ssh a 'ssh-add -L'` ne liste que K2,
    même avec `ForwardAgent yes` dans la config de l'utilisateur et avec `ssh -A`. L'agent
    dédié (K1) n'est pas visible sur l'hôte distant."""
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    main = lab_setup(bench, lab, tmp_path)
    for opts in ((), ("-A",)):
        r = ssh_remote(bench, main, "a", "ssh-add -L", *opts)
        assert r.returncode == 0, r.stderr
        assert remote_blobs(r.stdout) == [bench.blob("bastion")], (opts, r.stdout, r.stderr)
        assert not [l for l in r.stderr.splitlines() if l.startswith("sshvault:")], r.stderr
    assert bench.agent_keys() == [bench.blob("prod")], "K1 dans l'agent dédié (authentification)"
    calls = re.findall(r"^sshvault-test: fin (ensure --\S+ \S+)", r.stderr, re.M)
    assert calls == ["ensure --forward %s" % fid("a"), "ensure --id %s" % ID_K1], "bloc de transfert d'abord"


def test_bout_en_bout_saut_proxyjump_sans_transfert(bench, lab, tmp_path):
    """Le rebond (`ssh -W a`, ProxyJump) n'ouvre aucun canal de session : `ensure --forward`
    n'y charge rien. Mais `-W` impose ExitOnForwardFailure (mesuré, 8.9p1) : sans socket, le
    saut s'arrêterait ; le sous-agent est lancé vide."""
    unlocked(bench)
    bench.items = [ssh_item(ID_K1, "K1 identité", bench.keys["prod"], hosts="a"),
                   ssh_item(ID_K2, "K2 cible", bench.keys["bastion"], hosts="b"),
                   ssh_item(ID_K3, "K3 transférée", bench.keys["perso"], extra_fields=[fwd_field("a")])]
    bench.write_vault()
    no_confirm(bench)
    main = lab_setup(bench, lab, tmp_path, user_forward="no")
    n_bw = len(bench.calls())
    r = ssh_remote(bench, main, "b", "true")
    assert r.returncode == 0, r.stderr
    assert "fin ensure --forward %s --id %s rc=0" % (fid("a"), ID_K3) in r.stderr
    # -W impose ExitOnForwardFailure (mesuré) : le socket doit exister, sous-agent lancé vide
    assert "Cannot forward agent socket path" not in r.stderr
    assert fwd_keys(bench, "a") == [], "aucune clé chargée pour un saut"
    assert loads(bench, fwd_sock(bench, "a")) == []
    assert [c["argv"][1:3] for c in bench.calls()[n_bw:]].count(["get", "item"]) == 2, "K2 et K1, pas K3"
    # 2e connexion : socket présent, chemin rapide
    r = ssh_remote(bench, main, "b", "true")
    assert r.returncode == 0, r.stderr


def test_bout_en_bout_confirmation_askpass(bench, lab, tmp_path):
    """Critère : forward-confirm à oui ; une clé transférée sert depuis l'hôte distant
    (`ssh-add -T`, signature) : l'agent demande la confirmation sur le poste (askpass)."""
    unlocked(bench)
    forward_vault(bench)
    askpass, calls = make_askpass(tmp_path, reply="yes")
    ask = {"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"}
    main = lab_setup(bench, lab, tmp_path)
    pub = tmp_path / "k2.pub"
    pub.write_text(bench.keys["bastion"]["public"] + "\n")
    r = ssh_remote(bench, main, "a", "ssh-add -T %s && echo signature-ok" % pub, env=ask)
    assert r.returncode == 0 and "signature-ok" in r.stdout, r.stderr
    prompts = calls.read_text()
    assert "Allow use of key" in prompts and bench.keys["bastion"]["fingerprint"] in prompts, prompts
    no, ncalls = make_askpass(tmp_path, reply="no", rc=1, name="askpass-non")
    assert bench.run("agent", "stop").returncode == 0
    r = ssh_remote(bench, main, "a", "ssh-add -T %s && echo signature-ok" % pub,
                   env={"SSH_ASKPASS": no, "SSH_ASKPASS_REQUIRE": "force"})
    assert "signature-ok" not in r.stdout, "confirmation refusée : pas de signature"
    assert "Allow use of key" in ncalls.read_text()


# --- revue : appelant ssh (-a, -N, -W, ForwardAgent=no), chemin rapide, verrous ---------------

def fake_ssh(bench, script, *ssh_args, env=None):
    """`script` (commande shell) lancé par un faux parent nommé « ssh » (un sh dont argv[0] est
    ssh) : la ligne de commande vue dans /proc est `ssh -c <script> <ssh_args…>`."""
    e = dict(bench.env)
    e.update(env or {})
    return subprocess.run(["ssh", "-c", script + "; exit $?"] + list(ssh_args), executable="/bin/sh", env=e,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
                          start_new_session=True)


def sv_cmd(*args, entry="launch"):
    """Commande shell : `python -m sshvault …` (point d'entrée, chemin rapide compris) ou la
    CLI complète seule (`entry="cli"`)."""
    if entry == "cli":
        return "'%s' -c 'import sys; from sshvault.cli import main; sys.exit(main(sys.argv[1:]))' %s" % (
            sys.executable, " ".join(args))
    return "'%s' -m sshvault %s" % (sys.executable, " ".join(args))


def fwd_args(pattern, *ids):
    return ["ensure", "--forward", fid(pattern)] + [x for i in ids for x in ("--id", i)]


@pytest.mark.parametrize("args,no_session,no_forward", [
    (["-a", "h"], False, True), (["-A", "-a", "h"], False, True), (["-a", "-A", "h"], False, False),
    (["-o", "ForwardAgent=no", "h"], False, True), (["-oForwardAgent=no", "h"], False, True),
    (["-o", "forwardagent no", "h"], False, True), (["-o", 'FORWARDAGENT = "No"', "h"], False, True),
    (["-o", "ForwardAgent=false", "h"], False, True), (["-o", "ForwardAgent=yes", "-a", "h"], False, True),
    (["-A", "-o", "ForwardAgent=no", "h"], False, False), (["-o", "ForwardAgent=/x.sock", "h"], False, False),
    (["h", "ssh-add", "-a"], False, False), (["-N", "h"], True, False), (["-W", "x:1", "h"], True, False),
    (["-aW", "x:1", "h"], True, True), (["-vN", "h"], True, False), ([], False, False),
])
def test_appelant_sans_transfert(args, no_session, no_forward):
    from sshvault import fastpath
    c = fastpath.Caller([(os.getpid(), ["ssh"] + args)])
    assert (c.no_session, c.no_forward) == (no_session, no_forward)


@needs_openssh
@pytest.mark.parametrize("entry", ["launch", "cli"])
@pytest.mark.parametrize("opts", [["-a"], ["-oForwardAgent=no"], ["-o", "ForwardAgent=no"]])
def test_ensure_forward_ssh_a_ne_fait_rien(bench, entry, opts):
    """ssh -a / -o ForwardAgent=no : rien n'est transféré : ni coffre, ni sous-agent, code 0."""
    unlocked(bench)
    forward_vault(bench)
    r = fake_ssh(bench, sv_cmd(*fwd_args("a", ID_K2), entry=entry), *opts, "a")
    assert (r.returncode, r.stderr) == (0, ""), r.stderr
    assert not fwd_dir(bench).exists() and bench.calls() == [] and bench.ssh_add_calls() == []


@needs_openssh
@pytest.mark.parametrize("entry", ["launch", "cli"])
@pytest.mark.parametrize("opts", [["-N"], ["-W", "127.0.0.1:22"], ["-a", "-W", "127.0.0.1:22"]])
def test_ensure_forward_sans_session_socket_seul(bench, entry, opts):
    """ssh -N, -W (même avec -a : -W impose ExitOnForwardFailure) : sous-agent vide lancé,
    ni coffre ni clé, code 0."""
    unlocked(bench)
    forward_vault(bench)
    r = fake_ssh(bench, sv_cmd(*fwd_args("a", ID_K2), entry=entry), *opts, "a")
    assert (r.returncode, r.stderr) == (0, ""), r.stderr
    assert fwd_sock(bench, "a").exists() and fwd_keys(bench, "a") == []
    assert bench.calls() == [] and loads(bench) == []


@needs_openssh
def test_ensure_forward_saut_w_config_invalide_socket_quand_meme(bench):
    """Saut -W : réglages, délais et coffre ne sont pas lus avant le socket : config.json
    invalide, délai invalide, bw absent → socket créé, code 0."""
    forward_vault(bench)
    cfg = bench.home / ".config" / "sshvault" / "config.json"
    cfg.parent.mkdir(parents=True, mode=0o700)
    cfg.write_text("{pas du json")
    cfg.chmod(0o600)
    env = {"SSHVAULT_ENSURE_TIMEOUT": "abc", "SSHVAULT_BW": "/nonexistent/bw"}
    r = fake_ssh(bench, sv_cmd(*fwd_args("a", ID_K2)), "-W", "127.0.0.1:22", "a", env=env)
    assert (r.returncode, r.stderr) == (0, ""), r.stderr
    assert fwd_sock(bench, "a").exists()


def _fast_probe(bench, tmp_path, pattern, *ids):
    code = tmp_path / "probe.py"
    code.write_text("import sys\nsys.argv = %r\nfrom sshvault.launch import main\nrc = main()\n"
                    "print(rc, 'sshvault.cli' in sys.modules, 'sshvault.bw' in sys.modules)\n"
                    % (["sshvault"] + fwd_args(pattern, *ids)))
    return "'%s' '%s'" % (sys.executable, code)


@needs_openssh
def test_ensure_forward_chemin_rapide_sans_cli(bench, tmp_path):
    """Clé fraîche dans le sous-agent : réponse sans importer la CLI ni bw ; de même pour un
    saut -W dont le socket existe, et pour ssh -a."""
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    probe = _fast_probe(bench, tmp_path, "a", ID_K2)
    r = subprocess.run(["/bin/sh", "-c", probe], env=bench.env, capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL)
    assert r.stdout.split() == ["0", "False", "False"], r.stderr
    for opts in (["-W", "127.0.0.1:22"], ["-a"]):
        r = fake_ssh(bench, probe, *opts, "a")
        assert r.stdout.split() == ["0", "False", "False"], (opts, r.stderr)
    # clé absente du sous-agent : la CLI prend la suite
    assert bench.run("agent", "purge").returncode == 0
    r = subprocess.run(["/bin/sh", "-c", probe], env=bench.env, capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL)
    assert r.stdout.split() == ["0", "True", "True"], r.stderr


@needs_ssh
def test_exec_exclut_les_motifs_precedents(keys, tmp_path):
    """Motifs recouvrants : seule la ligne exec du premier bloc qui couvre l'hôte est lancée
    (OpenSSH du poste, `ssh -G` exécute les Match exec)."""
    log = tmp_path / "exec.log"
    exe = tmp_path / "bin" / "sshvault"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\necho \"$@\" >> '%s'\nexit 0\n" % log)
    exe.chmod(0o755)
    plan = sshconfig.build(_items(keys), sshconfig.Paths(str(tmp_path / "h")),
                           "/run/sshvault-test-absent/sshvault/agent.sock", str(exe))
    gen = tmp_path / "gen"
    gen.write_bytes(plan.config)
    gen.chmod(0o600)

    def forwards(host):
        if log.exists():
            log.unlink()
        _ssh_G(tmp_path, gen, host)
        return [l.split()[2] for l in log.read_text().splitlines() if "--forward" in l] if log.exists() else []
    assert forwards("saut.dmz") == [fid("saut.dmz")], "*.dmz couvre aussi saut.dmz : sa ligne exec n'est pas lancée"
    assert forwards("y.dmz") == [fid("*.dmz")]
    assert forwards("x.dmz.lab") == [fid("x.dmz.*")]
    assert forwards("autre") == []


def test_forwardagent_yes_duree_bornee(tmp_path):
    paths = sshconfig.Paths(str(tmp_path))
    slow = tmp_path / "ssh-lent"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    t0 = time.monotonic()
    found, cut = sshconfig.forwardagent_yes(["h1", "h2", "h3"], paths, {"SSHVAULT_SSH": str(slow),
                                                                       "SSHVAULT_SSH_HOME": str(tmp_path)}, budget=1)
    assert (found, cut) == ([], True) and time.monotonic() - t0 < 4
    fast = tmp_path / "ssh-oui"
    fast.write_text("#!/bin/sh\necho 'user x'\necho 'forwardagent yes'\n")
    fast.chmod(0o755)
    assert sshconfig.forwardagent_yes(["h1", "h2"], paths, {"SSHVAULT_SSH": str(fast),
                                                            "SSHVAULT_SSH_HOME": str(tmp_path)}) == (["h1", "h2"], False)


def test_regeneration_hors_ssh_config_sans_ssh_G(bench, tmp_path):
    """Le contrôle `ssh -G` n'est fait que par `sshvault ssh-config` : `forward add` n'en lance pas."""
    unlocked(bench)
    marker = tmp_path / "ssh-G.log"
    fake = tmp_path / "ssh-faux"
    fake.write_text("#!/bin/sh\necho \"$@\" >> '%s'\necho 'forwardagent yes'\n" % marker)
    fake.chmod(0o755)
    env = {"SSHVAULT_SSH": str(fake)}
    r = bench.run("forward", "add", "--id", ID_BASTION, "jump", env=env)
    assert r.returncode == 0 and not marker.exists() and "ForwardAgent yes" not in r.stderr
    r = bench.run("ssh-config", env=env)
    assert r.returncode == 0 and marker.exists()
    assert re.findall(r"hôte « ([^»]+) » : ForwardAgent yes", r.stderr) == ["bastion", "prod.example.com"]


def test_list_json_et_selection_par_motif_de_transfert(bench):
    unlocked(bench)
    forward_vault(bench, k2_forward="bastion.dmz")
    data = json.loads(bench.run("list", "--json").stdout)
    assert {d["id"]: d["forward"] for d in data} == {ID_K1: [], ID_K2: ["bastion.dmz"]}
    assert bench.run("list").stdout.splitlines()[1].split("\t")[2] == "-", "colonnes texte inchangées"
    r = bench.run("forward", "list", "--host", "bastion.dmz")
    assert (r.returncode, r.stdout) == (0, "bastion.dmz\n"), r.stderr
    r = bench.run("forward", "list", "*.dmz")  # sélection par défaut, motif glob
    assert (r.returncode, r.stdout) == (0, "bastion.dmz\n"), r.stderr
    r = bench.run("hosts", "list", "--host", "bastion.dmz")
    assert r.returncode == 1, "hosts : motifs de transfert hors sélection"
    r = bench.run("forward", "remove", "bastion.dmz", "bastion.dmz")
    assert r.returncode == 0, r.stderr
    assert "sshvault-forward" not in [f["name"] for f in bench.vault_item(ID_K2)["fields"] or []]


def test_champ_nom_non_texte_ignore():
    it = {"type": 5, "name": "n", "sshKey": {"publicKey": "p", "privateKey": "x", "keyFingerprint": "f"},
          "fields": [{"name": ["sshvault-hosts"], "value": "x"}, {"name": {"a": 1}, "value": "y"}, {"name": None},
                     {"name": "sshvault-forward", "value": "a", "type": 0}]}
    item = BwBackend._item(it)
    assert item.hosts == () and item.forward == ("a",)


def test_forward_edit_en_echec_une_fois(bench):
    unlocked(bench)
    r = bench.run("forward", "add", "--id", ID_PROD, "x.dmz", env={"FAKE_BW_FAIL": "edit=erroronce"})
    assert r.returncode == 0, r.stderr
    assert "transferts de « Serveur Prod » : x.dmz" in r.stdout
    assert [c["argv"][1:] for c in bench.calls()].count(["edit", "item", ID_PROD]) == 2
    fields = {f["name"]: f["value"] for f in bench.vault_item(ID_PROD)["fields"]}
    assert fields == {"sshvault-hosts": " prod.example.com , *.Lab.example,", "sshvault-forward": "x.dmz"}


def test_forward_edit_en_echec_rejoue_une_fois(bench):
    unlocked(bench)
    before = bench.vault_item(ID_PROD)
    r = bench.run("forward", "add", "--id", ID_PROD, "x.dmz", env={"FAKE_BW_FAIL": "edit=error"})
    assert r.returncode == 4
    line = one_line_error(r)
    assert "transferts de « Serveur Prod » : écriture en échec" in line
    assert "deux fois" in line and "état relu : élément inchangé (transferts : aucun)" in line
    assert [c["argv"][1:] for c in bench.calls()].count(["edit", "item", ID_PROD]) == 2
    assert bench.vault_item(ID_PROD) == before


@needs_openssh
def test_sans_match_exec_sous_agent_arrete(bench):
    """auto-load false : bloc sans Match exec, aucune clé autorisée : le sous-agent qui en
    garde est arrêté par ssh-config."""
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    pid = fwd_state(bench, "a")["agent"]["pid"]
    assert bench.run("config", "set", "auto-load", "false").returncode == 0
    r = bench.run("ssh-config")
    assert r.returncode == 0, r.stderr
    assert "a (%s), clé retirée du transfert : agent arrêté" % fid("a") in r.stdout
    assert wait_gone([pid], timeout=10) and not fwd_sock(bench, "a").exists()
    assert "Match originalhost a\n    ForwardAgent no\n" in (bench.home / ".ssh" / "sshvault" / "config").read_text()


@needs_openssh
def test_ensure_forward_pub_perime(bench):
    """Clé changée dans le coffre sans `ssh-config` : la clé chargée diffère du `.pub` généré,
    retirée ; une ligne, code 4, et non « chargée »."""
    unlocked(bench)
    no_confirm(bench)
    bench.items = [ssh_item(ID_K2, "K2", bench.keys["bastion"], hosts="x", extra_fields=[fwd_field("a")])]
    bench.write_vault()
    assert bench.run("ssh-config").returncode == 0
    bench.items = [ssh_item(ID_K2, "K2", bench.keys["perso"], hosts="x", extra_fields=[fwd_field("a")])]
    bench.write_vault()
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 4 and "sshvault ssh-config" in one_line_error(r)
    assert fwd_keys(bench, "a") == []
    assert bench.run("ssh-config").returncode == 0
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0 and fwd_keys(bench, "a") == [bench.blob("perso")]


def _write_fwd_state(bench, pattern, data):
    p = fwd_dir(bench) / (fid(pattern) + ".json")
    tmp = str(p) + ".t"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, json.dumps(data).encode())
    os.close(fd)
    os.replace(tmp, str(p))


@needs_openssh
def test_forward_confirm_askpass_inconnu(bench, tmp_path):
    """Sous-agent repris (askpass inconnu, None) : traité comme sans askpass."""
    unlocked(bench)
    forward_vault(bench)
    askpass, _ = make_askpass(tmp_path, reply="yes")
    ask = {"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"}
    assert ensure_fwd(bench, "a", ID_K2, env=ask).returncode == 0
    assert bench.run("agent", "purge").returncode == 0
    st = fwd_state(bench, "a")
    old = st["agent"]["pid"]
    st["agent"]["askpass"] = None
    _write_fwd_state(bench, "a", st)
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 4 and "forward-confirm" in one_line_error(r)
    assert wait_gone([old], timeout=10) and not fwd_sock(bench, "a").exists(), "refus : sous-agent arrêté"
    r = ensure_fwd(bench, "a", ID_K2, env=ask)
    assert r.returncode == 0, r.stderr
    assert fwd_state(bench, "a")["agent"]["askpass"] is True


@needs_openssh
def test_verrou_pose_pendant_la_lecture_du_coffre(bench):
    """Entrelacement : `agent lock` enregistré pendant que `ensure --forward` lit le coffre :
    rien n'est chargé (AgentLocked)."""
    from sshvault import ensure as ensure_mod
    from sshvault.agent import AgentLocked
    unlocked(bench)
    key = bench.keys["bastion"]

    class Backend:
        def get_ssh_key(self, iid, prompt):
            lock_main(bench)
            return SshKeyItem(ID_K2, "K2", key["public"], key["fingerprint"], (), ("a",)), key["private"].encode()

    class Store:
        def get(self):
            return "session"

    with pytest.raises(AgentLocked):
        ensure_mod.ensure_forward(fid("a"), [ID_K2], Backend(), Store(), {"key-ttl": 3600, "forward-confirm": False},
                                  env=bench.env)
    assert fwd_keys(bench, "a") == [] and loads(bench) == []


@needs_openssh
def test_agent_stop_attend_ensure_lock(bench):
    """`agent stop` prend ensure.lock : un ensure --forward en cours (simulé : verrou tenu)
    finit d'abord ; l'arrêt suit."""
    import fcntl
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    pid = fwd_state(bench, "a")["agent"]["pid"]
    fd = os.open(str(bench.runtime / "sshvault" / "ensure.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        p = subprocess.Popen([sys.executable, "-m", "sshvault", "agent", "stop"], env=dict(bench.env),
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True)
        seen = wait_stderr(p, "attente d'un chargement en cours (ensure)")
        assert "attente d'un chargement en cours (ensure)…" in seen, seen
        assert p.poll() is None and proc_alive(pid), "agent stop attend le verrou"
    finally:
        os.close(fd)
    out, err = p.communicate(timeout=30)
    assert p.returncode == 0, err
    assert wait_gone([pid], timeout=10)


@needs_openssh
def test_agent_lock_vidage_impossible_arrete_quand_meme(bench, tmp_path):
    subs = _two_subagents(bench)
    askpass, _ = make_askpass(tmp_path, reply="verrou de test")
    ask = {"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"}
    env = {k: v for k, v in os.environ.items() if k not in ("SSH_AUTH_SOCK", "SSH_AGENT_PID")}
    env.update(ask, SSH_AUTH_SOCK=str(fwd_sock(bench, "a")))
    subprocess.run(["ssh-add", "-x"], env=env, check=True, capture_output=True, stdin=subprocess.DEVNULL,
                   start_new_session=True)  # sous-agent verrouillé à la main : ssh-add -D refusé
    r = bench.run("agent", "lock", env=ask)
    assert r.returncode == 0, r.stderr
    assert "transfert a (%s) : vidage impossible" % fid("a") in r.stderr
    assert wait_gone([a["pid"] for a in subs], timeout=10) and not fwd_sock(bench, "a").exists()


@needs_openssh
def test_agent_status_agent_dedie_arrete(bench):
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    assert bench.run("ssh-config").returncode == 0
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    r = bench.run("agent", "status")
    assert r.returncode == 3, r.stderr
    assert "agent : arrêté" in r.stdout and "transfert a (%s) : actif" % fid("a") in r.stdout
    assert "  K2 transférée\t%s\t" % bench.keys["bastion"]["fingerprint"] in r.stdout


@needs_openssh
def test_agent_lock_agent_dedie_arrete(bench, tmp_path):
    """Transfert seul (agent dédié arrêté) : sous-agents vidés et arrêtés, puis code 3."""
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    pid = fwd_state(bench, "a")["agent"]["pid"]
    askpass, _ = make_askpass(tmp_path, reply="verrou de test")
    r = bench.run("agent", "lock", env={"SSH_ASKPASS": askpass, "SSH_ASKPASS_REQUIRE": "force"})
    assert r.returncode == 3 and "agent arrêté" in r.stderr
    assert [s for s, a in bench.ssh_add_calls() if a == "-D"] == [str(fwd_sock(bench, "a"))], "vidé"
    assert wait_gone([pid], timeout=10) and not fwd_sock(bench, "a").exists()


@needs_openssh
def test_orphelin_sans_etat_ni_socket(bench):
    """ssh-agent sur un `fwd/<fid>.sock` inconnu (ni état, ni socket) : trouvé par /proc, arrêté
    au prochain lancement de sshvault."""
    fwd_dir(bench).mkdir(parents=True, mode=0o700)
    sock = fwd_sock(bench, "inconnu.example")
    pid = start_agent(sock)
    os.unlink(str(sock))
    assert os.listdir(str(fwd_dir(bench))) == []
    bench.run("status")
    assert wait_gone([pid], timeout=10), "orphelin arrêté"


# --- revue 2 -----------------------------------------------------------------------------------

def wait_stderr(p, text, timeout=10):
    """Lit le stderr (octets) de `p` jusqu'à voir `text` (ou délai, ou fin) ; renvoie ce qui a été lu.
    Le descripteur redevient bloquant ensuite (communicate)."""
    fd = p.stderr.fileno()
    os.set_blocking(fd, False)
    buf, deadline = b"", time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                chunk = None
            if chunk:
                buf += chunk
                if text.encode() in buf:
                    break
            elif chunk == b"" or p.poll() is not None:
                break
            else:
                time.sleep(0.05)
    finally:
        os.set_blocking(fd, True)
    return buf.decode(errors="replace")


@needs_openssh
def test_config_forward_confirm_arrete_les_sous_agents(bench):
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    pid = fwd_state(bench, "a")["agent"]["pid"]
    r = bench.run("config", "set", "forward-confirm", "no")  # même valeur : rien arrêté
    assert r.returncode == 0 and "arrêtés" not in r.stdout and proc_alive(pid)
    r = bench.run("config", "unset", "forward-confirm")  # false → true (défaut)
    assert r.returncode == 0 and "sous-agents de transfert arrêtés : rechargés au prochain ssh" in r.stdout
    assert "agent purge" not in r.stdout
    assert wait_gone([pid], timeout=10) and not fwd_sock(bench, "a").exists()


@needs_openssh
def test_ensure_forward_pub_perime_deux_cles_rien_charge(bench):
    """Deux clés, l'une avec un `.pub` généré périmé : refus avant tout ssh-add ; sous-agent et
    état vides."""
    unlocked(bench)
    no_confirm(bench)
    bench.items = [ssh_item(ID_K2, "K2", bench.keys["bastion"], extra_fields=[fwd_field("a")]),
                   ssh_item(ID_K3, "K3", bench.keys["prod"], hosts="x", extra_fields=[fwd_field("a")])]
    bench.write_vault()
    assert bench.run("ssh-config").returncode == 0
    bench.items[1] = ssh_item(ID_K3, "K3", bench.keys["perso"], hosts="x", extra_fields=[fwd_field("a")])
    bench.write_vault()
    r = ensure_fwd(bench, "a", ID_K2, ID_K3)
    assert r.returncode == 4 and "sshvault ssh-config" in one_line_error(r)
    assert fwd_keys(bench, "a") == [] and fwd_state(bench, "a")["keys"] == {}
    assert loads(bench) == [], "aucun ssh-add de chargement"


@needs_openssh
def test_ensure_forward_rollback_chargement_partiel(bench):
    """K2 en clair, K3 chiffrée sous --nointeraction : K3 refusée (code 3) après le chargement de
    K2, qui est retirée ; état vide."""
    unlocked(bench)
    no_confirm(bench)
    bench.items = [ssh_item(ID_K2, "K2", bench.keys["bastion"], extra_fields=[fwd_field("a")]),
                   ssh_item(ID_K3, "K3", bench.keys["chiffree"], extra_fields=[fwd_field("a")])]
    bench.write_vault()
    r = bench.run("--nointeraction", *fwd_args("a", ID_K2, ID_K3))
    assert r.returncode == 3, r.stderr
    one_line_error(r)
    assert len(loads(bench)) == 1, "K2 chargée d'abord"
    assert fwd_keys(bench, "a") == [] and fwd_state(bench, "a")["keys"] == {}


@needs_openssh
def test_forward_confirm_refus_arrete_le_sous_agent(bench):
    """forward-confirm activé hors CLI (fichier), clé sans -c bientôt échue : le refus (pas
    d'askpass) vide et arrête le sous-agent au lieu de le laisser transférer."""
    unlocked(bench)
    forward_vault(bench)
    cfg = bench.home / ".config" / "sshvault" / "config.json"
    cfg.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    for value in (False, True):
        cfg.write_text(json.dumps({"forward-confirm": value}))
        cfg.chmod(0o600)
        if not value:
            assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    st = fwd_state(bench, "a")
    pid = st["agent"]["pid"]
    for e in st["keys"].values():
        e["loaded"] = time.time() - 3590  # 10 s restantes : plus fraîche, encore dans l'agent
    _write_fwd_state(bench, "a", st)
    assert fwd_keys(bench, "a") == [bench.blob("bastion")]
    r = ensure_fwd(bench, "a", ID_K2)
    assert r.returncode == 4 and "forward-confirm" in one_line_error(r)
    assert wait_gone([pid], timeout=10) and not fwd_sock(bench, "a").exists()


@needs_openssh
def test_sous_agent_tiers_code_4(bench):
    """Socket de sous-agent servi par un tiers : `agent status` et `agent stop` disent l'erreur
    (une ligne) et sortent en 4."""
    fwd_dir(bench).mkdir(parents=True, mode=0o700)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(str(fwd_sock(bench, "a")))
        srv.listen(5)
        for cmd in ("status", "stop"):
            r = bench.run("agent", cmd)
            assert r.returncode == 4, (cmd, r.stdout, r.stderr)
            assert "agent non lancé par sshvault" in r.stderr and fid("a") in r.stderr
        assert fwd_sock(bench, "a").exists(), "rien touché"
    finally:
        srv.close()


def test_forwardagent_yes_tue_le_groupe(tmp_path):
    pidfile = tmp_path / "enfant.pid"
    fake = tmp_path / "ssh-lent"
    fake.write_text("#!/bin/sh\nsleep 60 &\necho $! > '%s'\nwait\n" % pidfile)
    fake.chmod(0o755)
    found, cut = sshconfig.forwardagent_yes(["h"], sshconfig.Paths(str(tmp_path)),
                                            {"SSHVAULT_SSH": str(fake), "SSHVAULT_SSH_HOME": str(tmp_path)},
                                            budget=1)
    assert (found, cut) == ([], True)
    assert wait_gone([int(pidfile.read_text())], timeout=10), "enfant de ssh -G (Match exec) tué aussi"


def test_ensure_forward_deux_fois_refuse(bench):
    r = bench.run("ensure", "--forward", fid("a"), "--forward", fid("b"), "--id", ID_K2)
    assert r.returncode == 2 and "une seule fois" in one_line_error(r)


def test_avertissement_attrape_tout_une_fois(bench):
    unlocked(bench)
    r = bench.run("forward", "add", "--id", ID_BASTION, "*")
    assert r.returncode == 0, r.stderr
    assert r.stderr.count(sshconfig.FORWARD_CATCH_ALL_WARNING) == 1, r.stderr


@needs_openssh
def test_agent_lock_attend_ensure_lock(bench, tmp_path):
    import fcntl
    subs = _two_subagents(bench)
    askpass, _ = make_askpass(tmp_path, reply="verrou de test")
    env = dict(bench.env, SSH_ASKPASS=askpass, SSH_ASKPASS_REQUIRE="force")
    fd = os.open(str(bench.runtime / "sshvault" / "ensure.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        p = subprocess.Popen([sys.executable, "-m", "sshvault", "agent", "lock"], env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        seen = wait_stderr(p, "attente d'un chargement en cours (ensure)")
        assert "attente d'un chargement en cours (ensure)…" in seen, seen
        assert p.poll() is None and all(proc_alive(a["pid"]) for a in subs), "sous-agents intacts pendant l'attente"
    finally:
        os.close(fd)
    out, err = p.communicate(timeout=60)
    assert p.returncode == 0, err
    assert wait_gone([a["pid"] for a in subs], timeout=10)
    assert bench.agent_state()["locked"] is True


@needs_openssh
def test_generate_arrete_un_sous_agent_perime(bench):
    """generate régénère le ssh_config : un sous-agent plus référencé est arrêté, dit sur stderr ;
    stdout = la seule clé publique."""
    unlocked(bench)
    forward_vault(bench)
    no_confirm(bench)
    assert ensure_fwd(bench, "a", ID_K2).returncode == 0
    pid = fwd_state(bench, "a")["agent"]["pid"]
    forward_vault(bench, k2_forward=None)  # transfert retiré dans le coffre, ssh_config pas régénéré
    r = bench.run("generate", "--name", "neuve", "--hosts", "neuve.example")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert len(lines) == 1 and lines[0].startswith("ssh-ed25519 "), r.stdout
    assert "sous-agent de transfert %s, plus référencé : agent arrêté" % fid("a") in r.stderr
    assert wait_gone([pid], timeout=10)


def test_ssh_config_controle_interrompu(bench, tmp_path):
    unlocked(bench)
    slow = tmp_path / "ssh-lent"
    slow.write_text("#!/bin/sh\nsleep 30\n")
    slow.chmod(0o755)
    t0 = time.monotonic()
    r = bench.run("ssh-config", env={"SSHVAULT_SSH": str(slow), "SSHVAULT_SSH_G_BUDGET": "1"})
    assert r.returncode == 0, r.stderr
    assert "contrôle ForwardAgent (ssh -G) interrompu après 1s" in r.stderr
    assert time.monotonic() - t0 < 20

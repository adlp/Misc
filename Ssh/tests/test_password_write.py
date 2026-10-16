"""Écriture des éléments identifiant (story 18, CAP-11) : `password add`, `password hosts
add|remove|set|list`.

- Mot de passe : saisi deux fois au terminal (masqué) si stdin en est un, sinon une ligne sur
  stdin ; jamais en argv (`bench.calls()`, relevé de /proc), ni dans une sortie ; élément sur stdin
  de `bw create`/`bw edit`.
- Création relue et comparée ; échec ou blocage : `sync`, recherche (même nom, mêmes URI), rejeu
  unique. Édition : seules les URI `ssh://` visées changent ; rejeu unique si l'élément n'a pas
  changé.
- Doublon hôte + utilisateur attendu porté par un autre élément : code 2 sauf `--force`.
- `remove`/`set` : URI perdues dites, puis confirmation au terminal, `--yes` sinon (code 2).
"""
import json
import signal
import subprocess
import sys
import time

import pytest

from bench import ALIAS, ArgvWatch, login_item, wait_gone
from sshvault.backend import InvalidHost, login_uri, parse_login_host, parse_ssh_uri
from sshvault.bw import with_login_uris

ID_X = "d0d0d0d0-4444-4444-8444-d0d0d0d0d0d0"
ID_Y = "e0e0e0e0-5555-4555-8555-e0e0e0e0e0e0"
PW = "mdp-de-db-5c1e7a"


def unlocked(bench, items=()):
    bench.items = bench.items + list(items)
    bench.write_vault()
    bench.unlocked("keyring" if bench.ring else "file")


def vault_items(bench):
    return json.loads(bench.vault_file.read_text())["items"]


def logins_named(bench, name):
    return [i for i in vault_items(bench) if i.get("type") == 1 and i.get("name") == name]


def uris(item):
    return [u["uri"] for u in item["login"]["uris"]]


def argvs(bench):
    return [c["argv"][1:] for c in bench.calls()]


def count(bench, *cmd):
    return sum(1 for a in argvs(bench) if a == list(cmd))


def no_secret_in_argv(bench, *secrets):
    for c in bench.calls():
        for a in c["argv"]:
            assert not any(s in a for s in secrets), "secret en argument de bw : %s" % c["argv"]


def config_text(bench):
    p = bench.home / ".ssh" / "sshvault" / "config"
    return p.read_text() if p.exists() else ""


def x_item():
    """Élément identifiant X : deux URI ssh:// valides (dont une avec port), une web, une ssh
    invalide ; notes, champ, TOTP."""
    it = login_item(ID_X, "Base X", "admin", "mdp-de-x", ["ssh://db", "https://web.example/x", "ssh://root@db:22",
                                                           "ssh://h/chemin"],
                    fields=[{"name": "note", "value": "garde", "type": 0, "linkedId": None}])
    it["notes"] = "notes de X"
    it["login"]["totp"] = "JBSWY3DPEHPK3PXP"
    return it


def kept_part(item):
    """Ce qu'une écriture des hôtes ne doit pas changer."""
    login = item["login"]
    return (item["name"], item.get("notes"), item.get("fields"), login.get("username"), login.get("password"),
            login.get("totp"), [u for u in uris(item) if parse_ssh_uri(u) is None])


# --- analyse des hôtes et URI ---------------------------------------------------------------

@pytest.mark.parametrize("spec,want", [
    ("db", ("db", None)), ("Root@DB.Example", ("db.example", "Root")), ("a@b@h", ("h", "a@b")), (" h_1 ", ("h_1", None)),
])
def test_hote_ecrit(spec, want):
    assert parse_login_host(spec) == want
    uri = login_uri(*want)
    assert parse_ssh_uri(uri) == want and ":" not in uri[len("ssh://"):], "jamais de port"


@pytest.mark.parametrize("spec", ["", "h:22", "*.lab", "-oProxy", "u:p@h", "u r@h", "@h", "u\x01@h", "h/x", "[::1]"])
def test_hote_refuse(spec):
    with pytest.raises(InvalidHost):
        parse_login_host(spec)


def test_with_login_uris_garde_le_reste():
    it = x_item()
    new = with_login_uris(it, ["ssh://root@db:22", "ssh://db", "ssh://web"])  # réordonnées : à la place de la première
    assert uris(new) == ["ssh://root@db:22", "ssh://db", "ssh://web", "https://web.example/x", "ssh://h/chemin"]
    assert kept_part(new) == kept_part(it) and uris(it)[0] == "ssh://db", "original intact"
    assert with_login_uris(it, ["ssh://db", "ssh://root@db:22"]) == it
    # gardées dans l'ordre, puis nouvelles : chacune à sa place, nouvelles après la dernière
    assert uris(with_login_uris(it, ["ssh://db", "ssh://root@db:22", "ssh://n"])) == [
        "ssh://db", "https://web.example/x", "ssh://root@db:22", "ssh://n", "ssh://h/chemin"]
    assert uris(with_login_uris(it, ["ssh://root@db:22", "ssh://w"])) == ["https://web.example/x", "ssh://root@db:22",
                                                                          "ssh://w", "ssh://h/chemin"]
    assert uris(with_login_uris(it, [])) == ["https://web.example/x", "ssh://h/chemin"]
    only_web = login_item(ID_Y, "w", "u", "p", ["https://w"])
    assert uris(with_login_uris(only_web, ["ssh://a"])) == ["https://w", "ssh://a"]


# --- password add ---------------------------------------------------------------------------

def test_password_add_stdin(bench):
    unlocked(bench)
    with ArgvWatch("password", [PW], heuristics=False) as w:
        r = bench.run("password", "add", "db", "--host", "db", "--host", "root@db2", "--user", "admin",
                      input=PW + "\n")
    assert r.returncode == 0, r.stderr
    [it] = logins_named(bench, "db")
    assert it["login"]["username"] == "admin" and it["login"]["password"] == PW
    assert uris(it) == ["ssh://db", "ssh://root@db2"]
    assert r.stdout.splitlines()[0] == "élément « db » créé (id %s)" % it["id"]
    assert PW not in r.stdout + r.stderr
    assert not w.suspect, w.suspect
    no_secret_in_argv(bench, PW)
    a = argvs(bench)
    assert a.count(["create", "item"]) == 1 and a.count(["get", "item", it["id"]]) == 1, "créé sur stdin, relu"
    assert a.index(["sync"]) < a.index(["create", "item"]), "état du serveur avant l'écriture"
    text = config_text(bench)
    assert "--id %s --host db\"" % it["id"] in text and "--id %s --host db2\"" % it["id"] in text
    r = bench.run("password", "list")
    assert "%s\tdb\tadmin@db,root@db2" % ALIAS in r.stdout.splitlines()
    assert files_without(bench, PW)


def files_without(bench, secret):
    import os
    for root in (bench.home, bench.runtime):
        for d, _, files in os.walk(str(root)):
            for n in files:
                try:
                    if secret.encode() in open(os.path.join(d, n), "rb").read():
                        return False
                except OSError:
                    pass
    return True


@pytest.mark.parametrize("data,ok", [("s\n", "s"), ("s", "s"), ("a b é\n", "a b é"), ("", None), ("\n", None),
                                     ("a\nb", None), ("a\nb\n", None), ("a\r\n", None), ("a\rb\n", None),
                                     ("s\n\n", None)])
def test_password_add_stdin_une_ligne(bench, data, ok):
    unlocked(bench)
    r = bench.run("password", "add", "db", "--host", "db", input=data)
    if ok is None:
        assert r.returncode == 2, r.stderr
        assert not logins_named(bench, "db") and count(bench, "create", "item") == 0
        assert not bench.calls(), "refusé avant tout accès au coffre"
        assert "rien créé" in r.stderr
    else:
        assert r.returncode == 0, r.stderr
        assert logins_named(bench, "db")[0]["login"]["password"] == ok


def test_password_add_stdin_non_utf8(bench):
    unlocked(bench)
    e = dict(bench.env)
    p = subprocess.run([sys.executable, "-m", "sshvault", "password", "add", "db", "--host", "db"], env=e,
                       input=b"\xff\xfe\n", capture_output=True, timeout=60, start_new_session=True)
    assert p.returncode == 2 and b"UTF-8" in p.stderr and not bench.calls()


@pytest.mark.parametrize("args", [
    ["password", "add", "db"],                                  # aucun --host
    ["password", "add", "db", "--host", "h:22"],                # port
    ["password", "add", "db", "--host", "*.lab"],               # motif
    ["password", "add", "db", "--host", "u r@h"],               # blanc dans l'utilisateur
    ["password", "add", "db", "--host", "h", "--user", "a:b"],  # « : »
    ["password", "add", "db", "--host", "h", "--user", ""],
    ["password", "add", " ", "--host", "h"],                    # nom vide
])
def test_password_add_usage_avant_le_coffre(bench, args):
    unlocked(bench)
    r = bench.run(*args, input="s\n")
    assert r.returncode == 2, r.stderr
    assert not bench.calls()


def test_password_add_terminal(bench):
    unlocked(bench)
    r, screen = bench.run_tty("password", "add", "db", "--host", "db", "--user", "admin", answer=[PW, PW],
                              trigger=rb"mot de passe de", stdin_tty=True)
    assert r.returncode == 0, (r.stderr, screen)
    assert logins_named(bench, "db")[0]["login"]["password"] == PW
    assert PW not in screen and PW not in r.stdout + r.stderr, "saisie masquée"
    assert screen.count("mot de passe de « db »") == 2
    no_secret_in_argv(bench, PW)


def test_password_add_terminal_vide_puis_ok(bench):
    unlocked(bench)
    r, screen = bench.run_tty("password", "add", "db", "--host", "db", answer=["", PW, PW],
                              trigger=rb"mot de passe de", stdin_tty=True)
    assert r.returncode == 0, (r.stderr, screen)
    assert "mot de passe vide" in r.stderr
    assert logins_named(bench, "db")[0]["login"]["password"] == PW


def test_password_add_terminal_saisies_differentes(bench):
    unlocked(bench)
    r, screen = bench.run_tty("password", "add", "db", "--host", "db", answer=["a1", "b1", "a2", "b2", "a3", "b3"],
                              trigger=rb"mot de passe de", stdin_tty=True)
    assert r.returncode == 2, (r.stderr, screen)
    assert r.stderr.count("les deux saisies diffèrent") == 3 and "3 essais" in r.stderr
    assert not logins_named(bench, "db") and count(bench, "create", "item") == 0
    for s in ("a1", "b1", "a3"):
        assert s not in screen


def test_password_add_terminal_nointeraction(bench):
    unlocked(bench)
    r, _ = bench.run_tty("--nointeraction", "password", "add", "db", "--host", "db", stdin_tty=True)
    assert r.returncode == 2 and "--nointeraction" in r.stderr
    assert not bench.calls()


def test_password_add_doublon(bench):
    unlocked(bench, [login_item(ID_Y, "Autre", "admin", "x", ["ssh://root@DB", "ssh://web"])])
    r = bench.run("password", "add", "db", "--host", "root@db", input="s\n")
    assert r.returncode == 2, r.stderr
    assert "root@db" in r.stderr and "« Autre »" in r.stderr and ID_Y in r.stderr and "--force" in r.stderr
    assert count(bench, "create", "item") == 0 and not logins_named(bench, "db")
    # utilisateur attendu par login.username de l'autre élément (ssh://web, admin) et --user
    r = bench.run("password", "add", "db", "--host", "web", "--user", "admin", input="s\n")
    assert r.returncode == 2 and "admin@web" in r.stderr
    # autre utilisateur, ou hôte sans utilisateur : pas un doublon
    assert bench.run("password", "add", "db", "--host", "autre@db", input="s\n").returncode == 0
    r = bench.run("password", "add", "db2", "--host", "root@db", "--force", input="s\n")
    assert r.returncode == 0, r.stderr
    assert "avertissement" in r.stderr and "« Autre »" in r.stderr
    assert len(logins_named(bench, "db2")) == 1


def test_password_add_doublon_autre_compte(bench):
    unlocked(bench)
    bench.add_account("bob", "bob@example.test", items=[login_item(ID_Y, "Chez Bob", "bob", "x", ["ssh://pc"])],
                      unlocked=True, where="keyring" if bench.ring else "file")
    r = bench.run("password", "add", "db", "--host", "pc", "--user", "bob", "--account", ALIAS, input="s\n")
    assert r.returncode == 2 and "« Chez Bob »" in r.stderr and "compte bob" in r.stderr, r.stderr
    # plusieurs comptes, aucun par défaut unique : --account obligatoire
    bench.defaults.append("bob")
    bench.write_registry()
    r = bench.run("password", "add", "db", "--host", "x", input="s\n")
    assert r.returncode == 2 and "--account" in r.stderr


@pytest.mark.parametrize("mode", ["errorafter", "hangafter", "badjsonafter"])
def test_password_add_ecrit_puis_echec_pas_de_doublon(bench, mode):
    unlocked(bench)
    r = bench.run("password", "add", "db", "--host", "db", input="s\n",
                  env={"FAKE_BW_FAIL": "create=" + mode, "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    assert len(logins_named(bench, "db")) == 1 and count(bench, "create", "item") == 1, "trouvé : rien rejoué"
    a = argvs(bench)
    i = a.index(["create", "item"])
    assert a[i + 1:i + 3] == [["sync"], ["list", "items"]]


@pytest.mark.parametrize("mode", ["erroronce", "hangonce"])
def test_password_add_rejeu_unique(bench, mode):
    unlocked(bench)
    r = bench.run("password", "add", "db", "--host", "db", input=PW + "\n",
                  env={"FAKE_BW_FAIL": "create=" + mode, "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    [it] = logins_named(bench, "db")
    assert it["login"]["password"] == PW and count(bench, "create", "item") == 2
    no_secret_in_argv(bench, PW)
    assert PW not in r.stdout + r.stderr


def test_password_add_meme_nom_deja_la_pas_pris_pour_le_nouveau(bench):
    """Un élément de même nom et mêmes URI existait avant : la recherche après échec l'ignore."""
    unlocked(bench, [login_item(ID_Y, "db", None, "ancien", ["ssh://db"])])
    r = bench.run("password", "add", "db", "--host", "db", input="neuf\n",
                  env={"FAKE_BW_FAIL": "create=erroronce", "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    got = logins_named(bench, "db")
    assert len(got) == 2 and sorted(i["login"]["password"] for i in got) == ["ancien", "neuf"]


@pytest.mark.parametrize("fail,words", [("create=error", "deux fois"), ("create=corrupt", "relu diffère (mot de passe)"),
                                        ("create=silent", "relecture impossible")])
def test_password_add_echec(bench, fail, words):
    unlocked(bench)
    r = bench.run("password", "add", "db", "--host", "db", input=PW + "\n", env={"FAKE_BW_FAIL": fail})
    assert r.returncode == 4, r.stderr
    assert words in r.stderr, r.stderr
    assert PW not in r.stderr + r.stdout and PW[:-1] not in r.stderr
    if fail == "create=error":
        assert count(bench, "create", "item") == 2 and not logins_named(bench, "db")


def test_password_add_sigterm_pendant_create(bench):
    unlocked(bench)
    e = dict(bench.env, FAKE_BW_FAIL="create=hang", SSHVAULT_BW_TIMEOUT="60")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "password", "add", "db", "--host", "db"], env=e,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    p.stdin.write("s\n")
    p.stdin.close()
    p.stdin = None  # communicate() ne le touche plus
    try:
        deadline = time.monotonic() + 30
        while not (bench.pids.exists() and len(bench.pids.read_text().split()) == 2):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=30)
    finally:
        stop_all(p, bench)
    assert p.returncode == 130, err
    lines = err.splitlines()
    assert lines[0] == "sshvault: interrompu"
    assert len(lines) == 2 and lines[1].startswith("sshvault: « db » : création peut-être passée : vérifier par "
                                                   "« sshvault sync » puis « sshvault password list »"), lines
    assert not out
    assert wait_gone([int(x) for x in bench.pids.read_text().split()], timeout=10)


# --- password hosts ---------------------------------------------------------------------------

def test_password_hosts_list(bench):
    unlocked(bench, [x_item()])
    r = bench.run("password", "hosts", "list", "Base")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["admin@db", "root@db"]
    assert bench.run("password", "hosts", "list", "--host", "db").stdout == r.stdout
    assert bench.run("password", "hosts", "list", "--id", ID_X).stdout == r.stdout
    assert bench.run("password", "hosts", "list", "rien").returncode == 1
    assert bench.run("password", "hosts", "list", "Serveur Prod").returncode == 1, "pas un identifiant à ssh://"


def test_password_hosts_add(bench):
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r = bench.run("password", "hosts", "add", "--id", ID_X, "web", "u@w2")
    assert r.returncode == 0, r.stderr
    it = bench.vault_item(ID_X)
    assert uris(it) == ["ssh://db", "https://web.example/x", "ssh://root@db:22", "ssh://web", "ssh://u@w2",
                        "ssh://h/chemin"]
    assert kept_part(it) == kept_part(before)
    assert "hôtes de « Base X » : admin@db,root@db,admin@web,u@w2" in r.stdout
    assert "--id %s --host w2\"" % ID_X in config_text(bench)
    # paire déjà présente (port ignoré) : rien écrit
    n = count(bench, "edit", "item", ID_X)
    r = bench.run("password", "hosts", "add", "--id", ID_X, "root@db")
    assert r.returncode == 0 and "root@db déjà présent" in r.stdout
    assert count(bench, "edit", "item", ID_X) == n


def test_password_hosts_remove_exact_confirme(bench):
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r, screen = bench.run_tty("password", "hosts", "remove", "--id", ID_X, "root@db", answer="o",
                              trigger=rb"confirmer \? \[o/N\]")
    assert r.returncode == 0, (r.stderr, screen)
    it = bench.vault_item(ID_X)
    assert uris(it) == ["ssh://db", "https://web.example/x", "ssh://h/chemin"], "seule la paire exacte"
    assert kept_part(it) == kept_part(before)
    assert "ssh://root@db:22" in r.stderr and "« Base X »" in r.stderr, "URI complète listée"
    tail = screen.split("[o/N]")[-1]
    assert tail.lstrip(" ").startswith("o"), "réponse visible : %r" % tail
    assert bench.tty_echo, "écho du terminal rendu"
    text = config_text(bench)
    assert "--id %s --host db\"" % ID_X in text


def test_password_hosts_remove_refuse(bench):
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r, screen = bench.run_tty("password", "hosts", "remove", "--id", ID_X, "root@db", answer="n",
                              trigger=rb"confirmer \? \[o/N\]")
    assert r.returncode == 1, (r.stderr, screen)
    assert bench.vault_item(ID_X) == before and count(bench, "edit", "item", ID_X) == 0
    # paire absente (autre utilisateur, ou sans utilisateur alors que l'URI en a un) : code 1
    for spec in ("autre@db", "web"):
        r = bench.run("password", "hosts", "remove", "--id", ID_X, spec, "--yes")
        assert r.returncode == 1 and "rien écrit" in r.stderr
    assert bench.vault_item(ID_X) == before


def test_password_hosts_sans_terminal(bench):
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r = bench.run("password", "hosts", "set", "--id", ID_X, "web")
    assert r.returncode == 2, r.stderr
    assert "ssh://db" in r.stderr and "ssh://root@db:22" in r.stderr and "--yes" in r.stderr
    assert bench.vault_item(ID_X) == before and count(bench, "edit", "item", ID_X) == 0
    r, _ = bench.run_tty("--nointeraction", "password", "hosts", "set", "--id", ID_X, "web")
    assert r.returncode == 2 and bench.vault_item(ID_X) == before
    r = bench.run("password", "hosts", "set", "--id", ID_X, "web", "root@db", "--yes")
    assert r.returncode == 0, r.stderr
    it = bench.vault_item(ID_X)
    assert uris(it) == ["ssh://web", "ssh://root@db:22", "https://web.example/x", "ssh://h/chemin"], \
        "dans l'ordre donné ; URI de la même paire gardée telle quelle"
    assert kept_part(it) == kept_part(before)
    # set "" : toutes les URI ssh:// valides retirées, bloc retiré
    r = bench.run("password", "hosts", "set", "--id", ID_X, "", "--yes")
    assert r.returncode == 0, r.stderr
    it = bench.vault_item(ID_X)
    assert uris(it) == ["https://web.example/x", "ssh://h/chemin"] and kept_part(it) == kept_part(before)
    assert ID_X not in config_text(bench)
    # set sans perte : pas de question, sans terminal
    r = bench.run("password", "hosts", "set", "--id", ID_X, "db")
    assert r.returncode == 0, r.stderr
    assert uris(bench.vault_item(ID_X))[-1] == "ssh://db"


def test_password_hosts_set_doublon(bench):
    unlocked(bench, [x_item(), login_item(ID_Y, "Autre", "root", "x", ["ssh://w"])])
    r = bench.run("password", "hosts", "add", "--id", ID_X, "root@w")
    assert r.returncode == 2 and "« Autre »" in r.stderr
    r = bench.run("password", "hosts", "set", "--id", ID_X, "db", "root@db", "root@w", "--yes")
    assert r.returncode == 2 and count(bench, "edit", "item", ID_X) == 0
    r = bench.run("password", "hosts", "set", "--id", ID_X, "db", "root@db", "root@w", "--yes", "--force")
    assert r.returncode == 0 and "ssh://root@w" in uris(bench.vault_item(ID_X))
    # l'élément lui-même ne compte pas comme doublon
    assert bench.run("password", "hosts", "set", "--id", ID_X, "root@db", "db", "root@w", "--force").returncode == 0


def test_password_hosts_selection(bench):
    unlocked(bench, [x_item(), login_item(ID_Y, "Base Y", "u", "x", ["ssh://y"])])
    r = bench.run("password", "hosts", "add", "Base", "z")
    assert r.returncode == 2 and ID_X in r.stderr and ID_Y in r.stderr
    assert bench.run("password", "hosts", "add", "rien", "z").returncode == 1
    assert bench.run("password", "hosts", "add", "--fingerprint", "x", "z").returncode == 2
    assert bench.run("password", "hosts", "add", "--host", "y", "z").returncode == 0
    assert "ssh://z" in uris(bench.vault_item(ID_Y))


@pytest.mark.parametrize("mode", ["errorafter", "hangafter"])
def test_password_hosts_ecrit_puis_echec(bench, mode):
    unlocked(bench, [x_item()])
    r = bench.run("password", "hosts", "add", "--id", ID_X, "web",
                  env={"FAKE_BW_FAIL": "edit=" + mode, "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    assert count(bench, "edit", "item", ID_X) == 1, "écrit malgré l'erreur : rien rejoué"
    assert "ssh://web" in uris(bench.vault_item(ID_X))


@pytest.mark.parametrize("mode", ["erroronce", "hangonce"])
def test_password_hosts_rejeu_unique(bench, mode):
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r = bench.run("password", "hosts", "add", "--id", ID_X, "web",
                  env={"FAKE_BW_FAIL": "edit=" + mode, "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    assert count(bench, "edit", "item", ID_X) == 2
    it = bench.vault_item(ID_X)
    assert uris(it).count("ssh://web") == 1 and kept_part(it) == kept_part(before)


def test_password_hosts_echec_deux_fois(bench):
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r = bench.run("password", "hosts", "add", "--id", ID_X, "web", env={"FAKE_BW_FAIL": "edit=error"})
    assert r.returncode == 4 and "deux fois" in r.stderr
    assert count(bench, "edit", "item", ID_X) == 2 and bench.vault_item(ID_X) == before


def test_password_hosts_element_change_pas_de_rejeu(bench):
    """Un autre client écrit pendant l'échec : l'élément relu a changé, rien rejoué."""
    unlocked(bench, [x_item()])
    r = bench.run("password", "hosts", "add", "--id", ID_X, "web", env={"FAKE_BW_EDIT_RACE": "notes=autre client"})
    assert r.returncode == 4 and "a changé" in r.stderr, r.stderr
    assert count(bench, "edit", "item", ID_X) == 1


def test_password_hosts_silent_diffère(bench):
    unlocked(bench, [x_item()])
    r = bench.run("password", "hosts", "add", "--id", ID_X, "web", env={"FAKE_BW_FAIL": "edit=silent"})
    assert r.returncode == 4 and "diffère" in r.stderr
    assert "mdp-de-x" not in r.stderr + r.stdout
    assert not any("mdp-de-x" in a for c in bench.calls() for a in c["argv"])


# --- revue 1 -------------------------------------------------------------------------------------

@pytest.mark.parametrize("data,rc", [("x" * 4096 + "\n", 0), ("x" * 4096, 0), ("x" * 4097, 2), ("x" * 4097 + "\n", 2)])
def test_password_add_stdin_longueur(bench, data, rc):
    unlocked(bench)
    r = bench.run("password", "add", "db", "--host", "db", input=data)
    assert r.returncode == rc, r.stderr
    if rc:
        assert "4096" in r.stderr and not bench.calls()
    else:
        assert logins_named(bench, "db")[0]["login"]["password"] == "x" * 4096


def test_password_add_stdin_tube_muet_ouvert(bench):
    """Tube gardé ouvert sans rien écrire : délai SSHVAULT_PROMPT_TIMEOUT, code 2."""
    unlocked(bench)
    e = dict(bench.env, SSHVAULT_PROMPT_TIMEOUT="1")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "password", "add", "db", "--host", "db"], env=e,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True)
    try:
        rc = p.wait(timeout=30)
        err = p.stderr.read().decode()
    finally:
        p.stdin.close()
        if p.poll() is None:
            p.kill()
        p.stdout.close()
        p.stderr.close()
    assert rc == 2 and "rien lu sur stdin en 1s" in err, err
    assert not bench.calls()


def web_and_ssh_item():
    return login_item(ID_Y, "Seul ssh", "admin", "mdp-y", ["ssh://db", "ssh://root@db2", "https://web.example/y"])


def test_password_hosts_id_apres_set_vide(bench):
    unlocked(bench, [web_and_ssh_item()])
    assert bench.run("ssh-config").returncode == 0
    assert ID_Y in config_text(bench)
    r = bench.run("password", "hosts", "set", "--id", ID_Y, "", "--yes")
    assert r.returncode == 0, r.stderr
    assert uris(bench.vault_item(ID_Y)) == ["https://web.example/y"] and ID_Y not in config_text(bench)
    assert bench.run("password", "hosts", "list", "Seul").returncode == 1, "plus dans password list"
    r = bench.run("password", "hosts", "list", "--id", ID_Y)
    assert r.returncode == 0 and r.stdout == ""
    r = bench.run("password", "hosts", "add", "--id", ID_Y, "db")
    assert r.returncode == 0, r.stderr
    assert uris(bench.vault_item(ID_Y)) == ["https://web.example/y", "ssh://db"]
    assert "--id %s --host db\"" % ID_Y in config_text(bench), "bloc revenu"
    # id d'une clé SSH : pas un identifiant
    from bench import ID_PROD
    r = bench.run("password", "hosts", "add", "--id", ID_PROD, "z")
    assert r.returncode == 1 and "aucun élément identifiant" in r.stderr


def test_password_hosts_paire_attendue(bench):
    """x_item : ssh://db avec l'utilisateur de l'élément « admin » : admin@db est déjà là."""
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r = bench.run("password", "hosts", "add", "--id", ID_X, "admin@db")
    assert r.returncode == 0, r.stderr
    assert "admin@db déjà présent (ssh://db)" in r.stdout
    assert "Base X" not in r.stderr and "déjà porté" not in r.stderr, "l'élément n'est pas son propre doublon"
    assert bench.vault_item(ID_X) == before and count(bench, "edit", "item", ID_X) == 0
    # set : db et admin@db = une seule URI
    r = bench.run("password", "hosts", "set", "--id", ID_X, "db", "admin@db", "root@db", "--yes")
    assert r.returncode == 0, r.stderr
    assert [u for u in uris(bench.vault_item(ID_X)) if parse_ssh_uri(u)] == ["ssh://db", "ssh://root@db:22"]


def test_password_hosts_remove_paires_absentes(bench):
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r = bench.run("password", "hosts", "remove", "--id", ID_X, "admin@db", "autre@db", "--yes")
    assert r.returncode == 1, r.stderr
    lines = r.stderr.splitlines()
    assert any("ssh://admin@db" in l and "ssh://db" in l and "utilisateur de l'élément" in l and "« db »" in l
               for l in lines), r.stderr
    assert any("ssh://autre@db" in l for l in lines), "chaque paire absente dite"
    assert "rien écrit" in r.stderr and bench.vault_item(ID_X) == before


def test_password_add_paire_attendue_une_fois(bench):
    unlocked(bench)
    r = bench.run("password", "add", "db", "--host", "db", "--host", "admin@db", "--user", "admin", input="s\n")
    assert r.returncode == 0, r.stderr
    assert uris(logins_named(bench, "db")[0]) == ["ssh://db"]
    # utilisateur de l'URI ≠ --user : deux paires
    r = bench.run("password", "add", "db2", "--host", "dbx,root@dbx", "--user", "admin", input="s\n")
    assert r.returncode == 0, r.stderr
    assert uris(logins_named(bench, "db2")[0]) == ["ssh://dbx", "ssh://root@dbx"]


def test_password_listes_a_virgules(bench):
    unlocked(bench, [x_item()])
    r = bench.run("password", "add", "v", "--host", "a, u@b", "--host", "c", input="s\n")
    assert r.returncode == 0, r.stderr
    assert uris(logins_named(bench, "v")[0]) == ["ssh://a", "ssh://u@b", "ssh://c"]
    r = bench.run("password", "hosts", "add", "--id", ID_X, "w1,w2", "w3")
    assert r.returncode == 0, r.stderr
    assert [u for u in uris(bench.vault_item(ID_X)) if u.startswith("ssh://w")] == ["ssh://w1", "ssh://w2", "ssh://w3"]


def test_password_force_dit_apres_confirmation(bench):
    unlocked(bench, [x_item(), login_item(ID_Y, "Autre", "root", "x", ["ssh://w"])])
    before = bench.vault_item(ID_X)
    r, screen = bench.run_tty("password", "hosts", "set", "--id", ID_X, "root@w", "--force", answer="n",
                              trigger=rb"confirmer \? \[o/N\]")
    assert r.returncode == 1, (r.stderr, screen)
    assert "écrit quand même" not in r.stderr and bench.vault_item(ID_X) == before
    r, screen = bench.run_tty("password", "hosts", "set", "--id", ID_X, "root@w", "--force", answer="oui",
                              trigger=rb"confirmer \? \[o/N\]")
    assert r.returncode == 0, (r.stderr, screen)
    assert "écrit quand même" in r.stderr and "« Autre »" in r.stderr
    assert [u for u in uris(bench.vault_item(ID_X)) if parse_ssh_uri(u)] == ["ssh://root@w"]
    assert kept_part(bench.vault_item(ID_X)) == kept_part(before)


def test_password_add_force_dit_avant_creation_seulement(bench):
    """Saisie au terminal ratée : rien créé, pas d'annonce « écrit quand même »."""
    unlocked(bench, [login_item(ID_Y, "Autre", "root", "x", ["ssh://w"])])
    r, screen = bench.run_tty("password", "add", "db", "--host", "root@w", "--force", answer=["a", "b"] * 3,
                              trigger=rb"mot de passe de", stdin_tty=True)
    assert r.returncode == 2, (r.stderr, screen)
    assert "écrit quand même" not in r.stderr and not logins_named(bench, "db")


def test_password_hosts_confirmation_delai(bench):
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r, screen = bench.run_tty("password", "hosts", "remove", "--id", ID_X, "root@db",
                              env={"SSHVAULT_PROMPT_TIMEOUT": "1"}, trigger=rb"confirmer")
    assert r.returncode == 1, (r.stderr, screen)
    assert "pas de confirmation" in r.stderr and count(bench, "edit", "item", ID_X) == 0
    assert bench.vault_item(ID_X) == before
    assert screen.endswith("\n") or screen.endswith("\r\n"), "fin de ligne après l'invite sans réponse : %r" % screen[-40:]


def test_password_hosts_sigterm_a_la_confirmation(bench):
    """La liste des URI perdues est sur stderr quand la question apparaît."""
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r, screen = bench.run_tty("password", "hosts", "remove", "--id", ID_X, "root@db", trigger=rb"confirmer",
                              signal_at_prompt=signal.SIGTERM)
    assert r.returncode == 130, (r.stderr, screen)
    assert "ssh://root@db:22" in r.stderr and "« Base X »" in r.stderr
    assert bench.vault_item(ID_X) == before and count(bench, "edit", "item", ID_X) == 0


def test_password_hosts_set_confirme_au_terminal(bench):
    unlocked(bench, [x_item()])
    r, screen = bench.run_tty("password", "hosts", "set", "--id", ID_X, "web", answer="YES",
                              trigger=rb"confirmer \? \[o/N\]")
    assert r.returncode == 0, (r.stderr, screen)
    assert [u for u in uris(bench.vault_item(ID_X)) if parse_ssh_uri(u)] == ["ssh://web"]
    assert "ssh://db" in r.stderr and "ssh://root@db:22" in r.stderr


def test_password_ecrit_mais_ssh_config_non_regenere(bench):
    unlocked(bench, [x_item()])
    ssh = bench.home / ".ssh"
    ssh.mkdir(mode=0o700)
    (ssh / "sshvault").write_text("pas un dossier")
    r = bench.run("password", "add", "db", "--host", "db", input="s\n")
    assert r.returncode == 4, r.stderr
    assert "élément créé dans le coffre, mais ssh_config non régénéré" in r.stderr
    assert r.stdout.startswith("élément « db » créé (id ") and len(logins_named(bench, "db")) == 1
    r = bench.run("password", "hosts", "add", "--id", ID_X, "web")
    assert r.returncode == 4, r.stderr
    assert "hôtes écrits dans le coffre, mais ssh_config non régénéré" in r.stderr
    assert "ssh://web" in uris(bench.vault_item(ID_X))
    assert (ssh / "sshvault").read_text() == "pas un dossier"


def stop_all(p, bench):
    """Échec du test : sshvault (son groupe) et le faux bw bloqué (avec son `sleep`) tués et attendus."""
    import os
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.wait(10)
    pids = [int(x) for x in bench.pids.read_text().split()] if bench.pids.exists() else []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert wait_gone(pids, timeout=10)


def test_password_hosts_sigterm_pendant_edit(bench):
    unlocked(bench, [x_item()])
    e = dict(bench.env, FAKE_BW_FAIL="edit=hang", SSHVAULT_BW_TIMEOUT="60")
    p = subprocess.Popen([sys.executable, "-m", "sshvault", "password", "hosts", "add", "--id", ID_X, "web"], env=e,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        while not (bench.pids.exists() and len(bench.pids.read_text().split()) == 2):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=30)
    finally:
        stop_all(p, bench)
    assert p.returncode == 130, err
    lines = err.splitlines()
    assert lines[0] == "sshvault: interrompu"
    assert any("hôtes de « Base X » : écriture peut-être passée" in l and "sshvault password hosts list --id %s" % ID_X
               in l for l in lines), lines
    assert wait_gone([int(x) for x in bench.pids.read_text().split()], timeout=10)


def test_password_hosts_deux_comptes(bench):
    unlocked(bench, [x_item()])
    bench.add_account("bob", "bob@example.test", items=[login_item(ID_Y, "Chez Bob", "bob", "x", ["ssh://pc"])],
                      unlocked=True, where="keyring" if bench.ring else "file", default=True)
    r = bench.run("password", "hosts", "add", "--id", ID_X, "z")
    assert r.returncode == 2 and "--account" in r.stderr and not any(a[:1] == ["edit"] for a in argvs(bench))
    r = bench.run("password", "hosts", "add", "--id", ID_X, "z", "--account", "bob")
    assert r.returncode == 1 and "dans le compte bob" in r.stderr
    r = bench.run("password", "hosts", "add", "--id", ID_X, "z", "--account", ALIAS)
    assert r.returncode == 0, r.stderr
    r = bench.run("password", "hosts", "list", "--id", ID_Y)
    assert r.returncode == 0 and r.stdout == "bob@pc\n"


def test_password_add_meme_nom_autres_uri(bench):
    """Élément de même nom mais d'autres URI : pas pris pour le nouveau après un échec."""
    unlocked(bench, [login_item(ID_Y, "db", None, "ancien", ["ssh://autre"])])
    r = bench.run("password", "add", "db", "--host", "db", input="neuf\n",
                  env={"FAKE_BW_FAIL": "create=errorafter", "SSHVAULT_BW_TIMEOUT": "2"})
    assert r.returncode == 0, r.stderr
    got = {i["id"]: i for i in logins_named(bench, "db")}
    assert len(got) == 2 and got[ID_Y]["login"]["password"] == "ancien"
    assert count(bench, "create", "item") == 1


@pytest.fixture
def backend(bench, monkeypatch):
    from sshvault.bw import BwBackend
    from sshvault.session import SessionStore
    for k, v in bench.env.items():
        if k.startswith(("FAKE_BW_", "SSHVAULT_KEYCTL", "SSHVAULT_KEYRING")):
            monkeypatch.setenv(k, v)
    bench.items = bench.items + [x_item()]
    bench.write_vault()
    bench.unlocked("file")
    store = SessionStore(keyctl="/nonexistent/keyctl", runtime_dir=str(bench.runtime), alias=ALIAS)
    return BwBackend(store=store, exe=str(bench.bw), appdata=str(bench.appdata), timeout=30)


def test_set_login_uris_pas_un_identifiant(bench, backend):
    from bench import ID_PROD
    from sshvault.backend import ItemNotFound
    with pytest.raises(ItemNotFound):
        backend.set_login_uris(ID_PROD, ["ssh://z"])
    assert not any(a[:1] == ["edit"] for a in argvs(bench))
    from sshvault.backend import BackendError
    with pytest.raises(BackendError):
        backend.set_login_uris(ID_X, ["ssh://z:22/x"])  # URI refusée avant tout appel


def test_relecture_compare_le_reste_de_l_element():
    """passkeys, match des autres URI, dossier, favori, reprompt : relus et comparés."""
    from sshvault.bw import _login_written
    it = x_item()
    it["login"]["fido2Credentials"] = [{"credentialId": "c1"}]
    want = ["ssh://db", "ssh://root@db:22"]
    assert _login_written(json.loads(json.dumps(it)), it, want)
    for change in (lambda d: d["login"].__setitem__("fido2Credentials", []),
                   lambda d: d["login"]["uris"][1].__setitem__("match", 3),
                   lambda d: d.__setitem__("folderId", "f"),
                   lambda d: d.__setitem__("favorite", True),
                   lambda d: d.__setitem__("reprompt", 1)):
        after = json.loads(json.dumps(it))
        change(after)
        assert not _login_written(after, it, want)


def test_faux_bw_edit_garde_les_passkeys(bench):
    it = x_item()
    it["login"]["fido2Credentials"] = [{"credentialId": "c1"}]
    unlocked(bench, [it])
    r = bench.run("password", "hosts", "add", "--id", ID_X, "web")
    assert r.returncode == 0, r.stderr
    assert bench.vault_item(ID_X)["login"]["fido2Credentials"] == [{"credentialId": "c1"}]


# --- revue 2 -------------------------------------------------------------------------------------

def db_item(uris_):
    return login_item(ID_Y, "Base Y", "admin", "mdp-y", list(uris_) + ["https://web.example/y"])


def test_password_hosts_set_garde_l_uri_de_la_paire_attendue(bench):
    unlocked(bench, [db_item(["ssh://db"])])
    before = bench.vault_item(ID_Y)
    r = bench.run("password", "hosts", "set", "--id", ID_Y, "admin@db")  # sans terminal ni --yes
    assert r.returncode == 0, r.stderr
    assert "retirée" not in r.stderr and "inchangés" in r.stdout
    assert bench.vault_item(ID_Y) == before and count(bench, "edit", "item", ID_Y) == 0


def test_password_hosts_add_repetition_dans_la_commande(bench):
    unlocked(bench, [db_item(["ssh://autre"])])
    r = bench.run("password", "hosts", "add", "--id", ID_Y, "db", "admin@db")
    assert r.returncode == 0, r.stderr
    assert "déjà présent" not in r.stdout
    assert [u for u in uris(bench.vault_item(ID_Y)) if parse_ssh_uri(u)] == ["ssh://autre", "ssh://db"]


@pytest.mark.parametrize("uri,spec,how", [("ssh://admin@db", "db", "son utilisateur"),
                                          ("ssh://db", "admin@db", "l'utilisateur de l'élément")])
def test_password_hosts_remove_indice_selon_l_uri(bench, uri, spec, how):
    unlocked(bench, [db_item([uri])])
    r = bench.run("password", "hosts", "remove", "--id", ID_Y, spec, "--yes")
    assert r.returncode == 1, r.stderr
    assert "(%s porte admin@db par %s" % (uri, how) in r.stderr, r.stderr


def test_password_force_ecriture_en_echec(bench):
    unlocked(bench, [x_item(), login_item(ID_Y, "Autre", "root", "x", ["ssh://w"])])
    r = bench.run("password", "add", "db", "--host", "root@w", "--force", input="s\n",
                  env={"FAKE_BW_FAIL": "create=error"})
    assert r.returncode == 4, r.stderr
    assert "écrit quand même" not in r.stderr and not logins_named(bench, "db")
    r = bench.run("password", "hosts", "add", "--id", ID_X, "root@w", "--force", env={"FAKE_BW_FAIL": "edit=error"})
    assert r.returncode == 4, r.stderr
    assert "écrit quand même" not in r.stderr
    r = bench.run("password", "hosts", "add", "--id", ID_X, "root@w", "--force")
    assert r.returncode == 0 and "écrit quand même" in r.stderr


def test_password_hosts_confirmation_fin_de_saisie(bench):
    from bench import pty_run
    unlocked(bench, [x_item()])
    before = bench.vault_item(ID_X)
    r = pty_run([[sys.executable, "-m", "sshvault", "password", "hosts", "remove", "--id", ID_X, "root@db"]],
                dict(bench.env), trigger=rb"confirmer \? \[o/N\] ", send_at_prompt=b"\x04")
    assert r.returncode == 1, (r.stderr, r.screen)
    assert "pas de confirmation" in r.stderr and "rien écrit" in r.stderr
    assert bench.vault_item(ID_X) == before and count(bench, "edit", "item", ID_X) == 0
    assert r.screen.split("[o/N] ")[-1].startswith(("\n", "\r\n")), "fin de ligne : %r" % r.screen[-30:]


@pytest.mark.parametrize("data", ["a" * 3000 + "\n" + "b" * 2000, "x" * 4096 + "\r\n", "x" * 4000 + "\n" + "y" * 200 + "\n"],
                         ids=["deux-lignes", "4096-crlf", "deux-lignes-fin"])
def test_password_add_stdin_plusieurs_lignes_longues(bench, data):
    unlocked(bench)
    r = bench.run("password", "add", "db", "--host", "db", input=data)
    assert r.returncode == 2 and "une seule ligne" in r.stderr, r.stderr
    assert not bench.calls()


def test_relecture_compare_organisation_collections_historique_match():
    from sshvault.bw import _login_written
    it = x_item()
    it["collectionIds"] = []
    it["passwordHistory"] = [{"password": "ancien", "lastUsedDate": "2026-01-01T00:00:00.000Z"}]
    it["login"]["uris"][0]["match"] = 2  # ssh://db, gardée
    want = ["ssh://db", "ssh://root@db:22", "ssh://n"]
    good = json.loads(json.dumps(with_login_uris(it, want)))
    assert _login_written(good, it, want)
    for change in (lambda d: d.__setitem__("organizationId", "o"),
                   lambda d: d.__setitem__("collectionIds", ["c"]),
                   lambda d: d.__setitem__("passwordHistory", []),
                   lambda d: d["login"]["uris"][0].__setitem__("match", None),
                   lambda d: d["login"]["uris"][-2].__setitem__("match", 1)):  # ssh://n, nouvelle : null attendu
        after = json.loads(json.dumps(good))
        change(after)
        assert not _login_written(after, it, want)


def test_password_add_relu_different_commande_de_suppression(bench):
    unlocked(bench)
    r = bench.run("password", "add", "db", "--host", "db", input="s3cret\n", env={"FAKE_BW_FAIL": "create=corrupt"})
    assert r.returncode == 4
    [it] = logins_named(bench, "db")
    assert "BITWARDENCLI_APPDATA_DIR=%s %s delete item %s" % (bench.appdata, bench.bw, it["id"]) in r.stderr, r.stderr

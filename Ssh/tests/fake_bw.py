#!/usr/bin/env python3
"""Faux `bw` pour les tests de sshvault : mêmes sous-commandes, options, codes et JSON
que le CLI Bitwarden 2026.9.1, pour ce que sshvault utilise.

Faits reproduits (vrai bw 2026.9.1, lus dans le source embarqué du binaire et mesurés) :
  - données dans $BITWARDENCLI_APPDATA_DIR (créé au besoin, avec les lignes
    « Could not find dir/data file … creating it instead. » sur stderr) ;
  - sortie sur stdout sans retour à la ligne final quand stdout n'est pas un tty ;
  - erreur = une ligne sur stderr, code 1 ;
  - `status` : {"serverUrl","lastSync","userEmail","userId","status"} (email et id
    absents si non connecté) ; « unauthenticated » | « locked » | « unlocked » ;
  - session : `BW_SESSION` ou `--session` ; tout `unlock` invalide les précédentes ;
  - `--nointeraction` : jamais d'invite (« Master password is required… ») ;
  - non connecté : « You are not logged in. » ; verrouillé : « Vault is locked. » ;
  - `get item` absent : « Not found. » ; `lock` : « Your vault is locked. » ;
  - `sync` : « Syncing complete. » ; `config server` : « Saved setting `config`. » ;
  - `edit item <id> [encodedJson]` : JSON en base64 en argument ou sur stdin (aide de bw
    2026.9.1) ; champs repris comme `CipherExport.toView` (name, notes, favorite, reprompt,
    folderId ; `fields` et `passwordHistory` seulement s'ils ne sont pas null ; sshKey) ;
    `revisionDate` de la requête différente de celle du serveur : « The client copy of this
    cipher is out of date. Resync the client and try again. » ; l'élément modifié est rendu.
Mesuré sur le vrai bw contre le compte de test (2026-10-07) : mauvais mot de passe à
`unlock` (journaux « ERROR … » du SDK puis « Cryptography error, The decryption operation
failed », code 1), « Vault is locked. » sans session et avec une session invalide,
`status` « locked » avec une session invalide, « Not found. », « You have logged out. ».

Le « serveur » est un fichier JSON désigné par FAKE_BW_VAULT :
  {"email", "password", "userId", "clientId", "clientSecret", "items": [...]}.

Pannes simulées : FAKE_BW_FAIL="<commande>=<mode>[,…]" ; mode : badjson (JSON
invalide, code 0), error (code 1, « Unexpected error. »), hang (bloqué, avec un
enfant `sleep` ; pids écrits dans FAKE_BW_PIDS), hangonce (seul le premier appel bloque), hangnoecho
(écho du terminal coupé, puis bloqué), hangafter (edit : écrit, puis bloqué : la réponse se
perd), errorafter (edit : écrit, puis code 1), errorsecond (premier appel normal, les
suivants en erreur), silent (edit : code 0 sans rien écrire), erroronce (seul le premier appel en erreur).
FAKE_BW_EDIT_RACE=<champ>=<valeur> : à l'edit, le « serveur » change d'abord ce champ de
l'élément (autre client) puis traite la requête.
Journal : FAKE_BW_LOG (JSON par ligne : argv, BW_SESSION présent, appdata,
variables de l'environnement qui contiennent le mot de passe).
"""
import base64
import json
import os
import secrets
import subprocess
import sys
import time

USAGE_ERR = 1


def out(s):
    if not s:
        return
    sys.stdout.write(s if not sys.stdout.isatty() else s + "\n")
    sys.stdout.flush()


def fail(msg):
    sys.stderr.write(msg if not sys.stderr.isatty() else msg + "\n")
    sys.stderr.flush()
    sys.exit(1)


def appdata():
    d = os.environ.get("BITWARDENCLI_APPDATA_DIR") or os.path.expanduser("~/.config/Bitwarden CLI")
    if not os.path.isdir(d):
        sys.stderr.write('Could not find dir, "%s"; creating it instead.\n' % d)
        os.makedirs(d, exist_ok=True)
    data = os.path.join(d, "data.json")
    if not os.path.exists(data):
        sys.stderr.write('Could not find data file, "%s"; creating it instead.\n' % data)
        save_state(data, {"stateVersion": 85})
    return data


def load_state(path):
    with open(path) as f:
        return json.load(f)


def save_state(path, st):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, path)


def vault():
    with open(os.environ["FAKE_BW_VAULT"]) as f:
        return json.load(f)


def log(argv):
    path = os.environ.get("FAKE_BW_LOG")
    if not path:
        return
    try:
        pw = vault().get("password")
    except (KeyError, OSError, ValueError):
        pw = None
    rec = {"argv": argv, "session_env": bool(os.environ.get("BW_SESSION")),
           "appdata": os.environ.get("BITWARDENCLI_APPDATA_DIR"),
           "password_in_env": sorted(k for k, v in os.environ.items() if pw and v == pw),
           "nointeraction": "--nointeraction" in argv,
           "bw_env": sorted(k for k in os.environ if k.startswith(("BW_", "BITWARDENCLI_")))}
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def injected(cmd):
    spec = os.environ.get("FAKE_BW_FAIL", "")
    for part in filter(None, spec.split(",")):
        c, _, mode = part.partition("=")
        if c == cmd:
            return mode
    return None


def simulate(mode):
    if mode == "badjson":
        out("<html>502 Bad Gateway</html>")
        sys.exit(0)
    if mode == "error":
        fail("Unexpected error.")
    if mode in ("hangafter", "errorafter", "silent"):
        return  # traité par la commande
    if mode == "errorsecond":  # premier appel normal, les suivants en erreur
        flag = (os.environ.get("FAKE_BW_PIDS") or "/nonexistent") + ".errsecond." + (sys.argv[1:] or ["?"])[-1]
        if not os.path.exists(flag):
            open(flag, "w").close()
            return
        fail("Unexpected error.")
    if mode == "erroronce":
        flag = (os.environ.get("FAKE_BW_PIDS") or "/nonexistent") + ".erronce"
        if os.path.exists(flag):
            return
        open(flag, "w").close()
        fail("Unexpected error.")
    if mode == "hangonce":
        # premier appel bloqué, les suivants normaux (connexion neuve qui passe : mesuré)
        flag = (os.environ.get("FAKE_BW_PIDS") or "/nonexistent") + ".once"
        if os.path.exists(flag):
            return
        open(flag, "w").close()
        mode = "hang"
    if mode == "hangnoecho":
        # saisie masquée en cours (écho coupé sur le terminal), puis bloqué
        import termios
        try:
            attrs = termios.tcgetattr(0)
            attrs[3] &= ~termios.ECHO
            termios.tcsetattr(0, termios.TCSANOW, attrs)
        except termios.error:
            pass
        sys.stderr.write("? Master password: [input is hidden] ")
        sys.stderr.flush()
        mode = "hang"
    if mode == "hang":
        child = subprocess.Popen(["sleep", "600"])
        pids = os.environ.get("FAKE_BW_PIDS")
        if pids:
            with open(pids, "w") as f:
                f.write("%d %d\n" % (os.getpid(), child.pid))
        time.sleep(600)
        sys.exit(0)


# --- analyse des arguments (sous-ensemble de commander) ------------------------

GLOBAL_FLAGS = {"--pretty", "--raw", "--response", "--cleanexit", "--quiet", "--nointeraction"}
GLOBAL_VALUE = {"--session"}
CMD_FLAGS = {
    "login": ({"--apikey", "--check", "--sso"}, {"--method", "--code", "--passwordenv", "--passwordfile"}),
    "unlock": ({"--check"}, {"--passwordenv", "--passwordfile"}),
    "list": ({"--trash", "--archived"}, {"--search", "--url", "--folderid", "--collectionid", "--organizationid"}),
    "get": (set(), {"--itemid", "--output", "--organizationid"}),
    "sync": ({"-f", "--force", "--last"}, set()),
    "config": (set(), {"--web-vault", "--api", "--identity", "--icons", "--notifications", "--events",
                       "--key-connector"}),
    "status": (set(), set()), "lock": (set(), set()), "logout": (set(), set()),
    "edit": (set(), {"--organizationid"}),
}


def parse(argv):
    flags, opts, pos = set(), {}, []
    cmd = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("-") and a != "-":
            name, eq, val = a.partition("=")
            local = CMD_FLAGS.get(cmd, (set(), set())) if cmd else (set(), set())
            if name in GLOBAL_FLAGS or name in local[0]:
                flags.add(name)
            elif name in GLOBAL_VALUE or name in local[1]:
                if not eq:
                    i += 1
                    if i >= len(argv):
                        fail("error: option '%s <value>' argument missing" % name)
                    val = argv[i]
                opts[name] = val
            else:
                fail("error: unknown option '%s'" % a)
        elif cmd is None:
            cmd = a
        else:
            pos.append(a)
        i += 1
    return cmd, flags, opts, pos


# --- commandes ------------------------------------------------------------------

class Ctx:
    def __init__(self, flags, opts):
        self.flags, self.opts = flags, opts
        self.data = appdata()
        self.st = load_state(self.data)
        self.session = opts.get("--session") or os.environ.get("BW_SESSION")
        self.noint = "--nointeraction" in flags or os.environ.get("BW_NOINTERACTION") == "true"

    def save(self):
        save_state(self.data, self.st)

    def authed(self):
        return bool(self.st.get("userId"))

    def unlocked(self):
        return self.authed() and bool(self.session) and self.session == self.st.get("session")

    def need_unlocked(self):
        if not self.authed():
            fail("You are not logged in.")
        if not self.unlocked():
            fail("Vault is locked.")

    def json(self, obj):
        out(json.dumps(obj, indent=2 if "--pretty" in self.flags else None, separators=None
                       if "--pretty" in self.flags else (",", ":")))

    def message(self, title, raw=None):
        if "--raw" in self.flags:
            if raw is not None:
                out(raw)
            return
        out(title)


def read_line(prompt_text):
    sys.stderr.write(prompt_text)
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        # vrai bw 2026.9.1 (mesuré) : invite interrompue par EOF -> fin en code 0, rien fait
        sys.exit(0)
    return line.rstrip("\r\n")


def get_password(ctx, pos_password):
    if pos_password:
        return pos_password
    if "--passwordfile" in ctx.opts:
        with open(ctx.opts["--passwordfile"]) as f:
            return f.readline().rstrip("\r\n")
    if "--passwordenv" in ctx.opts:
        v = os.environ.get(ctx.opts["--passwordenv"])
        if v:
            return v
    if ctx.noint:
        fail("Master password is required. Try again in interactive mode or provide a password file "
             "or environment variable.")
    return read_line("? Master password: [input is hidden] ")


def new_session(ctx):
    tok = secrets.token_bytes(64)
    ctx.st["session"] = base64.b64encode(tok).decode()
    ctx.save()
    return ctx.st["session"]


def cmd_status(ctx, pos):
    st = {"serverUrl": ctx.st.get("serverUrl"), "lastSync": ctx.st.get("lastSync")}
    if ctx.authed():
        st["userEmail"] = ctx.st.get("userEmail")
        st["userId"] = ctx.st.get("userId")
    st["status"] = "unlocked" if ctx.unlocked() else ("locked" if ctx.authed() else "unauthenticated")
    ctx.json(st)


def cmd_config(ctx, pos):
    if pos[:1] != ["server"]:
        fail("Unknown setting.")
    if len(pos) < 2:
        out(ctx.st.get("serverUrl") or "https://bitwarden.com")
        return
    if ctx.authed():
        fail("Logout required before server config update.")
    ctx.st["serverUrl"] = pos[1]
    ctx.save()
    out("Saved setting `config`.")


def cmd_login(ctx, pos):
    if ctx.authed():
        fail("You are already logged in as %s." % ctx.st.get("userEmail"))
    v = vault()
    if "--apikey" in ctx.flags:
        cid = os.environ.get("BW_CLIENTID") or (None if ctx.noint else read_line("? client_id: "))
        sec = os.environ.get("BW_CLIENTSECRET") or (None if ctx.noint else read_line("? client_secret: "))
        if not cid or not sec:
            fail("client_id and client_secret are required.")
        if cid != v.get("clientId") or sec != v.get("clientSecret"):
            fail("client_id or client_secret is incorrect. Try again.")
        ctx.st.update(userId=v["userId"], userEmail=v["email"], session=None,
                      lastSync="2026-10-06T00:00:00.000Z")
        ctx.save()
        ctx.message("You are logged in!\n\nTo unlock your vault, use the `unlock` command. ex:\n$ bw unlock")
        return
    email = pos[0] if pos else (None if ctx.noint else read_line("? Email address: "))
    if not email:
        fail("Email address is required.")
    password = get_password(ctx, pos[1] if len(pos) > 1 else None)
    if email.lower() != v["email"].lower() or password != v["password"]:
        fail("Username or password is incorrect. Try again.")
    ctx.st.update(userId=v["userId"], userEmail=v["email"], lastSync="2026-10-06T00:00:00.000Z")
    tok = new_session(ctx)
    ctx.message("You are logged in!\n\nTo unlock your vault, set your session key to the `BW_SESSION` "
                "environment variable. ex:\n$ export BW_SESSION=\"%s\"" % tok, raw=tok)


def cmd_logout(ctx, pos):
    if not ctx.authed():
        fail("You are not logged in.")
    ctx.st = {"stateVersion": 85, "serverUrl": ctx.st.get("serverUrl")}
    ctx.save()
    ctx.message("You have logged out.")  # mesuré


def cmd_unlock(ctx, pos):
    if not ctx.authed():
        fail("You are not logged in.")
    if "--check" in ctx.flags:
        if ctx.unlocked():
            ctx.message("Vault is unlocked!")
            return
        fail("Vault is locked.")
    password = get_password(ctx, pos[0] if pos else None)
    if password != vault()["password"]:
        # stderr réel mesuré (bw 2026.9.1, compte de test, 2026-10-07)
        fail("ERROR bitwarden_crypto::keys::master_key: error=The decryption operation failed\n\n"
             "ERROR bitwarden_core::client::internal: error=Cryptography error, The decryption operation failed\n\n"
             "ERROR bitwarden_core::key_management::crypto: error=Cryptography error, The decryption operation "
             "failed\n\nCryptography error, The decryption operation failed")
    tok = new_session(ctx)  # invalide toute session précédente
    ctx.message("Your vault is now unlocked!\n\nTo unlock your vault, set your session key to the "
                "`BW_SESSION` environment variable. ex:\n$ export BW_SESSION=\"%s\"" % tok, raw=tok)


def cmd_lock(ctx, pos):
    if not ctx.authed():
        fail("You are not logged in.")
    ctx.st["session"] = None
    ctx.save()
    ctx.message("Your vault is locked.")


def cmd_sync(ctx, pos):
    ctx.need_unlocked()
    ctx.st["lastSync"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    ctx.save()
    ctx.message("Syncing complete.")


def cmd_list(ctx, pos):
    if pos[:1] != ["items"]:
        fail("Unknown object.")
    ctx.need_unlocked()
    items = vault()["items"]
    q = ctx.opts.get("--search")
    if q:
        items = [i for i in items if q.lower() in (i.get("name") or "").lower()]
    ctx.json(items)


def cmd_get(ctx, pos):
    if len(pos) < 2 or pos[0] != "item":
        fail("Unknown object.")
    ctx.need_unlocked()
    for i in vault()["items"]:
        if i.get("id") == pos[1]:
            ctx.json(i)
            return
    fail("Not found.")


def save_vault(v):
    path = os.environ["FAKE_BW_VAULT"]
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(v, f)
    os.replace(tmp, path)


_rev = [0]


def now_iso():
    _rev[0] += 1
    t = time.time() + _rev[0] / 1000.0
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % (int(t * 1000) % 1000)


def cmd_edit(ctx, pos):
    if len(pos) < 2 or pos[0] != "item":
        fail("Unknown object.")
    ctx.need_unlocked()
    enc = pos[2] if len(pos) > 2 else sys.stdin.read()
    try:
        req = json.loads(base64.b64decode(enc.strip(), validate=True).decode())
    except ValueError:
        fail("Error parsing the encoded request data.")
    v = vault()
    item = next((i for i in v["items"] if i.get("id") == pos[1]), None)
    if item is None:
        fail("Not found.")
    race = os.environ.get("FAKE_BW_EDIT_RACE")
    if race:  # un autre client écrit d'abord
        k, _, val = race.partition("=")
        item[k] = val
        item["revisionDate"] = now_iso()
        save_vault(v)
    if req.get("revisionDate") and req["revisionDate"] != item.get("revisionDate"):
        fail("The client copy of this cipher is out of date. Resync the client and try again.")
    if injected("edit") == "silent":
        ctx.json(item)
        return
    for k in ("name", "notes", "favorite", "reprompt", "folderId"):
        item[k] = req.get(k)
    for k in ("fields", "passwordHistory"):
        if req.get(k) is not None:
            item[k] = req[k]
    if item.get("type") == 5:
        item["sshKey"] = req.get("sshKey")
    item["revisionDate"] = now_iso()
    save_vault(v)
    mode = injected("edit")
    if mode in ("hangafter", "errorafter"):
        simulate("hang" if mode == "hangafter" else "error")
    ctx.json(item)


CMDS = {"edit": cmd_edit, "status": cmd_status, "config": cmd_config, "login": cmd_login, "logout": cmd_logout,
        "unlock": cmd_unlock, "lock": cmd_lock, "sync": cmd_sync, "list": cmd_list, "get": cmd_get}


def main():
    argv = sys.argv[1:]
    log(argv)
    cmd, flags, opts, pos = parse(argv)
    if cmd is None:
        out("Usage: bw [options] [command]")
        return
    if cmd == "serve":
        fail("bw serve interdit dans les tests de sshvault")
    if cmd not in CMDS:
        fail("error: unknown command '%s'" % cmd)
    mode = injected(cmd)
    if mode:
        simulate(mode)
    CMDS[cmd](Ctx(flags, opts), pos)


if __name__ == "__main__":
    main()

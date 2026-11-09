#!/usr/bin/env python3
"""Équivalence original / autonome : lance borgHelperWWW (original, avec fastapi installé) puis la version autonome
(`python3 -I -S`, stdlib seule) sur le MÊME état (copie neuve du dossier d'état avant chaque lancement), rejoue les
mêmes requêtes HTTP et compare statut, en-têtes significatifs et corps (JSON normalisé).

    python3 compare_standalone.py --orig-dir D1 --dep-dir D2 --rc RC --state-src ETAT_PRISTINE --state-dst ETAT_COURANT \
        [--out RAPPORT.json] [--scenario defaut|groupes|nodl]

D1 : dossier de l'original (borgHelperWWW + borgHelper(.py) + UI), D2 : dossier de déploiement de l'autonome.
Les routes GET sont extraites automatiquement de /openapi.json de l'ORIGINAL (plus les routes de l'UI)."""
import argparse
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time

KEY = "testkey"
SKIP_HEADERS = {"date", "server"}
NICK = "demo-modules"


def start(kind, d, rc, port, extra, env_extra, logf):
    cmd = ([sys.executable, "-I", "-S"] if kind == "dep" else [sys.executable]) + [os.path.join(d, "borgHelperWWW"), "-C", rc,
                                                                                    "-K", KEY, "--port", str(port)] + extra
    env = {k: v for k, v in os.environ.items() if not k.startswith("BORGHELPERWWW_")}
    env.update(env_extra)
    p = subprocess.Popen(cmd, cwd=d, stdout=logf, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    for _ in range(100):
        time.sleep(0.2)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            c.request("GET", "/healthz")
            if c.getresponse().status == 200:
                return p
        except OSError:
            pass
        if p.poll() is not None:
            break
    raise SystemExit(f"[ERREUR] {kind} n'a pas démarré (voir le journal)")


def stop(p):
    import signal
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)


def req(port, method, path, headers=None, body=None, timeout=30):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        return r.status, [(k.lower(), v) for k, v in r.getheaders()], data
    except Exception as e:
        return -1, [], f"{type(e).__name__}: {e}".encode()
    finally:
        c.close()


_TS = re.compile(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?")
_HEX32 = re.compile(r"\b[0-9a-f]{32}\b")
_RUNID = re.compile(r"run_id=\S+")


def norm_text(s):
    s = _TS.sub("<TS>", s)
    s = _HEX32.sub("<HEX32>", s)
    s = re.sub(r"\b\d+ms\b", "<ms>", s)
    s = re.sub(r"127\.0\.0\.1:189\d\d", "127.0.0.1:<PORT>", s)
    s = re.sub(r"\d+\.\d+ h\b", "<H> h", s)
    s = re.sub(r"\\\"depuis\\\": \\\"[^\\]*\\\"", "depuis", s)
    s = re.sub(r"pid[\"': =]+\d+", "pid=<N>", s)
    return s


def norm_json(o, key=None):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k in ("vapid_public_key",):
                out[k] = "<VAPID>"
            elif k in ("timestamp", "elapsed", "duration", "started", "mtime", "age", "uptime", "ctime"):
                out[k] = "<VAR>"
            else:
                out[k] = norm_json(v, k)
        return out
    if isinstance(o, list):
        return [norm_json(x) for x in o]
    if isinstance(o, str):
        return norm_text(o)
    return o


def rc_root(rc, nick=NICK):
    """Chemin (sans « / » initial) de BORG_ROOTBKP du nick dans le rc : préfixe des chemins de l'archive."""
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(rc, encoding="utf-8")
    return cp[nick].get("BORG_ROOTBKP", "").strip().lstrip("/")


def build_requests(port, scenario, rc=None):
    """Liste de (étiquette, méthode, chemin, en-têtes, corps) construite depuis l'openapi de l'original."""
    ident = {"X-Email": "alice@example.org", "X-Groups": "admins"} if scenario == "groupes" else {}
    st, _h, data = req(port, "GET", "/openapi.json", ident)
    spec = json.loads(data)
    H = {"X-API-Key": KEY, **ident}
    reqs = []
    ROOT = rc_root(rc) if rc else "x"
    sample = {"nick": NICK, "nickname": "demo-new", "servername": "srv-x", "repo": "/tmp/x", "repo_passphrase": "p",
              "ftor": "etc/f1.txt", "pattern": "f1", "path": "etc/f1.txt", "where": "r", "prefix": "", "endpoint": "https://push.example.invalid/e1",
              "topn": "5", "depth": "2"}
    for path, ops in sorted(spec["paths"].items()):
        for m, op in sorted(ops.items()):
            if m not in ("get", "post", "delete", "patch", "put"):
                continue
            params = op.get("parameters", [])
            q = {}
            for p in params:
                if p["in"] == "query" and (p["required"] or p["name"] in ("nick", "json", "offline")):
                    q[p["name"]] = sample.get(p["name"], "x")
            if "/report" in path:
                q.update({"json": "true", "offline": "true"})
            if "/push/" in path or "restore" in path and m == "post" or "/bkp" == path[-4:] or "/init" in path or "/delbkp" in path or "/prune" in path or "/key" in path:
                pass
            qs = "&".join(f"{k}={v}" for k, v in q.items())
            full = path + ("?" + qs if qs else "")
            body = None
            hh = dict(H)
            if m in ("post", "patch", "put") and "requestBody" in op:
                body = json.dumps({"endpoint": "https://push.example.invalid/e1", "keys": {"p256dh": "BPRv5LWWS0s0S9g1FUP9BtP4Hoh1sEJjsmKDTu9HJvfGJdOFtIrsejzu3w6NcaVxPYU-VmipkeX4kaq-xvBgOm8", "auth": "a1b2c3d4e5f6g7h8i9j0kl"}}).encode()
                hh["Content-Type"] = "application/json"
            tag = f"{m.upper()} {path}"
            skip_exec = any(s in path for s in ("/bkp", "/restore", "/init", "/login", "/prune", "/delbkp", "/index", "/push/test"))
            if m != "get" and skip_exec:
                # exécutions lourdes : seulement sans clé (401) et avec nick inconnu
                reqs.append((tag + " [sans clé]", m.upper(), full, {}, body))
                reqs.append((tag + " [nick inconnu]", m.upper(), full.replace(NICK, "inconnu"), hh, body))
                continue
            reqs.append((tag, m.upper(), full, hh, body))
            if m == "get":
                reqs.append((tag + " [sans clé]", "GET", full, {}, None))
                reqs.append((tag + " [clé fausse]", "GET", full, {"X-API-Key": "x"}, None))
                reqs.append((tag + " [sans paramètres]", "GET", path, hh, None))
            else:
                reqs.append((tag + " [sans clé]", m.upper(), full, {}, body))
                reqs.append((tag + " [sans corps]", m.upper(), full, {"X-API-Key": KEY}, None))
    # UI et statiques
    for p in ("/", "/serveur/demo", "/historique/demo", "/explorer", "/explorer/demo/etc/x", "/notifications", "/sw.js",
              "/static/chart.umd.min.js", "/favicon.ico", "/version", "/healthz", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        reqs.append((f"GET {p}", "GET", p, ident, None))
    html = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
    for p in ("/xyz", "/serveur/a/b", "/api/inconnue", "/api/access/"):
        reqs.append((f"GET {p} [navigateur]", "GET", p, html, None))
        reqs.append((f"GET {p} [client API]", "GET", p, H, None))
    reqs += [
        ("HEAD /healthz", "HEAD", "/healthz", {}, None), ("HEAD /", "HEAD", "/", {}, None),
        ("OPTIONS /api/access", "OPTIONS", "/api/access", H, None), ("POST /healthz", "POST", "/healthz", {}, b"x"),
        ("DELETE /version", "DELETE", "/version", {}, None), ("GET /api/access/ (barre finale)", "GET", "/api/access/", H, None),
        ("GET /api//access", "GET", "/api//access", H, None), ("GET %2e%2e", "GET", "/api/%2e%2e/version", H, None),
        ("GET chemin accentué", "GET", "/explorer/d%C3%A9mo/un%20r%C3%A9p?archive=a-1", {}, None),
        ("GET requête ordure", "GET", "/api/access?%zz=1&&=", H, None),
        ("POST sync corps invalide JSON", "POST", "/api/push/subscribe/sync?endpoint=e", H, b"{"),
        ("POST subscribe JSON invalide", "POST", "/api/push/subscribe", {**H, "Content-Type": "application/json"}, b"{bad"),
        ("POST subscribe corps vide", "POST", "/api/push/subscribe", {**H, "Content-Type": "application/json"}, b""),
        ("POST subscribe corps liste", "POST", "/api/push/subscribe", {**H, "Content-Type": "application/json"}, b"[1,2]"),
        ("POST subscribe corps null", "POST", "/api/push/subscribe", {**H, "Content-Type": "application/json"}, b"null"),
        ("POST subscribe types faux", "POST", "/api/push/subscribe", {**H, "Content-Type": "application/json"},
         json.dumps({"endpoint": "", "keys": {"p256dh": 5}, "expires_in_days": "abc", "hosts": {"a": 3}}).encode()),
        ("POST subscribe sans Content-Type", "POST", "/api/push/subscribe", H,
         json.dumps({"endpoint": "https://push.example.invalid/e2", "keys": {"p256dh": "p", "auth": "a"}}).encode()),
        ("GET subscriptions e2", "GET", "/api/push/subscriptions?endpoint=https://push.example.invalid/e2", H, None),
        ("PATCH subscribe e2", "PATCH", "/api/push/subscribe", {**H, "Content-Type": "application/json"},
         json.dumps({"endpoint": "https://push.example.invalid/e2", "notify_end": True}).encode()),
        ("GET subscriptions e2 (après)", "GET", "/api/push/subscriptions?endpoint=https://push.example.invalid/e2", H, None),
        ("DELETE subscribe e2", "DELETE", "/api/push/subscribe?endpoint=https://push.example.invalid/e2", H, None),
        ("GET int faux", "GET", "/api/idxtop?nick=demo-modules&topn=abc", H, None),
        ("GET bool faux", "GET", "/api/report?json=maybe&nick=demo-modules", H, None),
        ("GET bool oui", "GET", "/api/report?json=yes&offline=1&nick=demo-modules", H, None),
        ("GET télécharger fichier", "GET", f"/api/download/file?nick=demo-modules&path={ROOT}/blob.bin", H, None),
        ("GET télécharger fichier texte", "GET", f"/api/download/file?nick=demo-modules&path={ROOT}/sub/a.conf", H, None),
        ("GET télécharger tar", "GET", f"/api/download/tar?nick=demo-modules&prefix={ROOT}/sub", H, None),
        ("GET télécharger fichier absent", "GET", f"/api/download/file?nick=demo-modules&path={ROOT}/absent", H, None),
        ("GET télécharger sans clé", "GET", f"/api/download/file?nick=demo-modules&path={ROOT}/blob.bin", {}, None),
        ("GET gros en-tête", "GET", "/healthz", {"X-Big": "a" * 20000}, None),
    ]
    if scenario == "groupes":
        for g in ("", "ops-admins", "rien"):
            reqs.append((f"GET /api/access groupes={g!r}", "GET", "/api/access", {**H, "X-Groups": g, "X-Email": "bob@example.org"}, None))
            reqs.append((f"GET /api/lstbkp groupes={g!r}", "GET", f"/api/lstbkp?nick={NICK}", {**H, "X-Groups": g, "X-Email": "bob@example.org"}, None))
        reqs.append(("GET /healthz sans identité", "GET", "/healthz", {}, None))
        reqs.append(("GET /api/access sans identité", "GET", "/api/access", H, None))
    return reqs


def run_all(kind, d, rc, port, extra, env_extra, state_src, state_dst, scenario, reqs, logpath, raw_dir):
    shutil.rmtree(state_dst, ignore_errors=True)
    shutil.copytree(state_src, state_dst, symlinks=True)
    with open(logpath, "wb") as logf:
        p = start(kind, d, rc, port, extra, env_extra, logf)
        res = []
        try:
            for tag, m, path, hh, body in reqs:
                st, headers, data = req(port, m, path, hh, body)
                res.append({"tag": tag, "method": m, "path": path, "status": st, "headers": headers, "body": data})
            # keep-alive et pipeline : deux requêtes sur une même connexion
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            ka = []
            for _ in range(3):
                c.request("GET", "/healthz")
                r = c.getresponse()
                ka.append((r.status, r.read().decode()))
            c.close()
            res.append({"tag": "keep-alive x3", "method": "GET", "path": "/healthz", "status": 200,
                        "headers": [], "body": json.dumps(ka).encode()})
        finally:
            stop(p)
    return res


def compare(a, b):
    diffs = []
    ident = 0
    for ra, rb in zip(a, b):
        d = []
        if ra["status"] != rb["status"]:
            d.append(f"statut {ra['status']} != {rb['status']}")
        ha = {k: v for k, v in ra["headers"] if k not in SKIP_HEADERS}
        hb = {k: v for k, v in rb["headers"] if k not in SKIP_HEADERS}
        for k in sorted(set(ha) | set(hb)):
            if k == "content-length":
                continue
            if norm_text(ha.get(k) or "") != norm_text(hb.get(k) or ""):
                d.append(f"en-tête {k}: {ha.get(k)!r} != {hb.get(k)!r}")
        ba, bb = ra["body"], rb["body"]
        try:
            ja, jb = norm_json(json.loads(ba)), norm_json(json.loads(bb))
            same = ja == jb
            if not same:
                d.append(f"corps JSON: {json.dumps(ja, ensure_ascii=False)[:300]} != {json.dumps(jb, ensure_ascii=False)[:300]}")
        except (ValueError, UnicodeDecodeError):
            try:
                same = norm_text(ba.decode("utf-8", "replace")) == norm_text(bb.decode("utf-8", "replace"))
            except Exception:
                same = ba == bb
            if not same:
                d.append(f"corps: {ba[:200]!r} != {bb[:200]!r}")
        if d:
            diffs.append((ra["tag"], ra["method"], ra["path"][:100], d))
        else:
            ident += 1
    return ident, diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig-dir", required=True)
    ap.add_argument("--dep-dir", required=True)
    ap.add_argument("--rc", required=True)
    ap.add_argument("--state-src", required=True)
    ap.add_argument("--state-dst", required=True)
    ap.add_argument("--scenario", default="defaut", choices=("defaut", "groupes", "nodl"))
    ap.add_argument("--workdir", default=".")
    a = ap.parse_args()
    extra = {"defaut": [], "nodl": ["--no-downloads"],
             "groupes": ["--groups-header", "X-Groups", "--user-header", "X-Email", "--require-user", "--allow-destructive",
                         "--restore-root", os.path.join(a.workdir, "restoreroot")]}[a.scenario]
    os.makedirs(os.path.join(a.workdir, "restoreroot"), exist_ok=True)
    outs = {}
    reqs = None
    for kind, d, port in (("orig", a.orig_dir, 18911), ("dep", a.dep_dir, 18912)):
        if reqs is None:
            shutil.rmtree(a.state_dst, ignore_errors=True)
            shutil.copytree(a.state_src, a.state_dst, symlinks=True)
            with open(os.path.join(a.workdir, "spec.log"), "wb") as lf:
                p = start("orig", a.orig_dir, a.rc, 18910, extra, {}, lf)
                try:
                    reqs = build_requests(18910, a.scenario, a.rc)
                finally:
                    stop(p)
        outs[kind] = run_all(kind, d, a.rc, port, extra, {}, a.state_src, a.state_dst, a.scenario, reqs,
                             os.path.join(a.workdir, f"{kind}-{a.scenario}.log"), a.workdir)
    ident, diffs = compare(outs["orig"], outs["dep"])
    total = len(reqs) + 1
    print(f"scénario {a.scenario} : {total} requêtes, {ident} identiques, {len(diffs)} avec écart")
    for tag, m, path, d in diffs:
        print(f"  - {tag} [{m} {path}]")
        for x in d:
            print(f"      {x}")
    with open(os.path.join(a.workdir, f"result-{a.scenario}.json"), "w") as f:
        json.dump({"total": total, "identical": ident, "diffs": diffs}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

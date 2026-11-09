#!/usr/bin/env python3
"""Générateur de la version AUTONOME de borgHelperWWW (stdlib Python seule à l'exécution).

    python3 Borg/dist/build_standalone.py --rev HEAD            # dernière version commitée de Borg/borgHelperWWW
    python3 Borg/dist/build_standalone.py --src Borg/borgHelperWWW   # ou un fichier du disque

Produit `<out-dir>/borgHelperWWW-<WWW_VERSION>` (exécutable, déterministe : même entrée -> même octets) et met à jour
le lien symbolique `<out-dir>/borgHelperWWW`. `<out-dir>` vaut par défaut le dossier de ce script (Borg/dist/).

Principe : le source d'origine est repris TEL QUEL, précédé d'une couche de compatibilité embarquée (dossier `compat/` :
sous-ensembles de fastapi, starlette, pydantic, uvicorn, anyio et un remplaçant de pywebpush/py_vapid/http_ece, tous en
stdlib) servie par un importeur placé en tête de `sys.meta_path`. Seule transformation du source (vérifiée : le
générateur échoue bruyamment si le motif attendu n'est plus trouvé exactement une fois) : la génération des clés VAPID,
qui n'appelle plus les objets de la bibliothèque `cryptography` mais `generate_raw_keys()` (même format stocké).
Le générateur vérifie aussi que le résultat se compile et que tout import (hors stdlib, `borgHelper` et modules
embarqués) est optionnel (dans un try/except ImportError).
"""
import argparse
import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPAT = HERE / "compat"
REPO_REL_SRC = "borgHelperWWW"          # relatif au dossier parent de dist/ (Borg/)
ALIASES = {"pywebpush": "webpush_lite", "py_vapid": "webpush_lite"}
ALLOWED_THIRD_PARTY = {"borgHelper"}    # importés tels quels, présents à côté du fichier généré
# Bibliothèque optionnelle : utilisée par webpush_lite seulement si importable (repli pur Python sinon, testé).
OPTIONAL_THIRD_PARTY = {"cryptography"}

# Transformations du source : (nom, motif exact attendu UNE fois, remplacement)
REPLACEMENTS = [
    ("génération des clés VAPID (sans cryptography obligatoire)",
     "    from py_vapid import Vapid\n"
     "    from py_vapid.utils import b64urlencode, num_to_bytes\n"
     "    from cryptography.hazmat.primitives import serialization\n"
     "    v=Vapid(); v.generate_keys()\n"
     "    priv=b64urlencode(num_to_bytes(v.private_key.private_numbers().private_value,32))\n"
     "    pub=b64urlencode(v.public_key.public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))\n",
     "    from py_vapid import generate_raw_keys   # version autonome : même format stocké (privée 32 octets, publique X9.62 non compressée)\n"
     "    priv,pub=generate_raw_keys()\n"),
]

RUNTIME_TEMPLATE = r'''# ── Couche de compatibilité embarquée (générée) ─────────────────────────────────────────────────────────
# Modules servis par un importeur en tête de sys.meta_path : fastapi, starlette, pydantic, uvicorn, anyio, pywebpush,
# py_vapid. Sources : Borg/dist/compat/ (hash __COMPAT_HASH__). Ce code remplace les paquets homonymes, même installés.
def _bh_install_embedded():
    import importlib.abc, importlib.util, sys
    mods = __EMBEDDED__
    aliases = __ALIASES__

    class _Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in mods:
                is_pkg, fname, _src = mods[fullname]
                return importlib.util.spec_from_loader(fullname, self, origin=fname, is_package=is_pkg)
            if fullname in aliases:
                return importlib.util.spec_from_loader(fullname, self, origin="alias:" + aliases[fullname])
            return None

        def create_module(self, spec):
            if spec.name in aliases:
                return importlib.import_module(aliases[spec.name])
            return None

        def exec_module(self, module):
            name = module.__spec__.name
            if name in aliases:
                return
            is_pkg, fname, src = mods[name]
            module.__file__ = fname
            if is_pkg:
                module.__path__ = []
            exec(compile(src, fname, "exec"), module.__dict__)

        def get_source(self, fullname):
            return mods[fullname][2] if fullname in mods else None

        def is_package(self, fullname):
            return mods[fullname][0] if fullname in mods else False

    sys.meta_path.insert(0, _Finder())
    # Hors déploiement (ex. lancé depuis Borg/dist/ du dépôt) : borgHelper cherché aussi dans le dossier parent.
    import os
    here = os.path.dirname(os.path.realpath(__file__))
    if not os.path.exists(os.path.join(here, "borgHelper.py")):
        up = os.path.dirname(here)
        if os.path.exists(os.path.join(up, "borgHelper.py")):
            sys.path.append(up)


_bh_install_embedded()
del _bh_install_embedded
# ── Fin de la couche de compatibilité : source d'origine de borgHelperWWW, inchangé hors VAPID ────────────
'''


def run(*cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True)
    if r.returncode:
        sys.exit(f"[ERREUR] {' '.join(cmd)} : {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def read_source(args):
    """-> (texte du source, description de l'origine)."""
    if args.src:
        p = Path(args.src)
        data = p.read_bytes()
        return data.decode("utf-8"), f"fichier {p.name} (sha256 {hashlib.sha256(data).hexdigest()[:16]})"
    top = Path(run("git", "-C", str(HERE), "rev-parse", "--show-toplevel").decode().strip())
    rel = (HERE.parent / REPO_REL_SRC).relative_to(top).as_posix()
    data = run("git", "-C", str(top), "show", f"{args.rev}:{rel}")
    commit = run("git", "-C", str(top), "log", "-1", "--format=%H", args.rev, "--", rel).decode().strip()
    blob = run("git", "-C", str(top), "rev-parse", f"{args.rev}:{rel}").decode().strip()
    return data.decode("utf-8"), f"commit {commit} (blob {blob[:12]}, {rel} @ {args.rev})"


def collect_compat():
    """-> {nom de module: (est_paquet, nom de fichier affiché, source)} pour tous les .py de compat/."""
    mods = {}
    for p in sorted(COMPAT.rglob("*.py")):
        rel = p.relative_to(COMPAT).as_posix()
        parts = rel[:-3].split("/")
        is_pkg = parts[-1] == "__init__"
        if is_pkg:
            parts = parts[:-1]
        name = ".".join(parts)
        src = p.read_text(encoding="utf-8")
        mods[name] = (is_pkg, f"borgHelperWWW-autonome/{rel}", src)   # ex. .../starlette/middleware/base.py
    for a, target in ALIASES.items():
        if target not in mods:
            sys.exit(f"[ERREUR] module {target} (alias {a}) absent de {COMPAT}")
    return mods


def literal(s):
    """Littéral Python lisible (chaîne brute entre ''') pour un source ; relu et comparé."""
    if "'''" in s or s.endswith("\\") or "\x00" in s or "\r" in s:
        sys.exit("[ERREUR] source embarqué non représentable en chaîne brute '''…'''")
    lit = "r'''" + s + "'''"
    if ast.literal_eval(lit) != s:
        sys.exit("[ERREUR] littéral embarqué infidèle")
    return lit


def embedded_literal(mods):
    out = ["{"]
    for name in sorted(mods):
        is_pkg, fname, src = mods[name]
        out.append(f"    {name!r}: ({is_pkg!r}, {fname!r}, {literal(src)}),")
    out.append("}")
    return "\n".join(out)


def stdlib_ok(top):
    return top in sys.stdlib_module_names or top in ("__future__",)


def check_imports(text, label, embedded):
    """Tout import hors stdlib / borgHelper / modules embarqués / OPTIONAL_THIRD_PARTY doit être optionnel (try/except)."""
    tree = ast.parse(text)
    parents = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[ch] = node
    allowed = set(embedded) | set(ALIASES) | ALLOWED_THIRD_PARTY | OPTIONAL_THIRD_PARTY | {m.split(".")[0] for m in embedded}
    bad = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for n in names:
            top = n.split(".")[0]
            if stdlib_ok(top) or top in allowed or n in allowed:
                continue
            p, optional = node, False
            while p in parents:
                p = parents[p]
                if isinstance(p, ast.Try) and any(
                        h.type is None or (isinstance(h.type, ast.Name) and h.type.id in ("ImportError", "Exception", "ModuleNotFoundError"))
                        or (isinstance(h.type, ast.Tuple) and any(isinstance(e, ast.Name) and e.id in ("ImportError", "Exception") for e in h.type.elts))
                        for h in p.handlers):
                    optional = True
                    break
            if not optional:
                bad.append(f"{label}:{node.lineno}: import {n}")
    return bad


def build(src_text, origin, mods):
    # 1. version
    m = re.findall(r'^WWW_VERSION="([^"]+)"\s*$', src_text, re.M)
    if len(m) != 1:
        sys.exit(f"[ERREUR] WWW_VERSION=\"…\" attendu exactement une fois en début de ligne, trouvé {len(m)}")
    version = m[0]
    # 2. transformations
    text = src_text
    for name, old, new in REPLACEMENTS:
        n = text.count(old)
        if n != 1:
            sys.exit(f"[ERREUR] transformation « {name} » : motif trouvé {n} fois (attendu 1) — le source a changé, "
                     f"adapter REPLACEMENTS dans {Path(__file__).name} et la couche compat/")
        text = text.replace(old, new)
    # 3. forme du source : shebang puis le reste
    if not text.startswith("#!/usr/bin/env python3\n"):
        sys.exit("[ERREUR] shebang attendu en première ligne du source")
    if "from __future__" in text:
        sys.exit("[ERREUR] `from __future__` dans le source : doit rester en tête du fichier, non géré")
    body = text[len("#!/usr/bin/env python3\n"):]
    chash = hashlib.sha256()
    for name in sorted(mods):
        chash.update(name.encode() + b"\0" + mods[name][2].encode() + b"\0")
    compat_hash = chash.hexdigest()[:16]
    header = (
        "#!/usr/bin/env python3\n"
        "# ═══════════════════════════════════════════════════════════════════════════════════════════════════\n"
        "# borgHelperWWW — VERSION AUTONOME. FICHIER GÉNÉRÉ : NE PAS ÉDITER À LA MAIN.\n"
        f"# Version source : borgHelperWWW {version}\n"
        f"# Origine        : {origin}\n"
        f"# Couche compat  : Borg/dist/compat/ (sha256 {compat_hash})\n"
        "# Générateur     : Borg/dist/build_standalone.py — régénérer à chaque nouvelle WWW_VERSION :\n"
        "#                  python3 Borg/dist/build_standalone.py --rev HEAD\n"
        "# Dépendances à l'exécution : bibliothèque standard Python >= 3.10 + borgHelper (à côté) + fichiers UI/JS.\n"
        "# Ni fastapi, ni starlette, ni pydantic, ni uvicorn, ni anyio, ni pywebpush/py_vapid/http_ece : ils sont remplacés\n"
        "# par des sous-ensembles stdlib embarqués ci-dessous (cryptography, si présente, sert seulement aux primitives\n"
        "# du Web Push). Voir Borg/dist/README.md.\n"
        "# ═══════════════════════════════════════════════════════════════════════════════════════════════════\n")
    runtime = (RUNTIME_TEMPLATE.replace("__EMBEDDED__", embedded_literal(mods))
               .replace("__ALIASES__", repr(ALIASES)).replace("__COMPAT_HASH__", compat_hash))
    out = header + runtime + body
    compile(out, "borgHelperWWW-autonome", "exec")   # SyntaxError -> échec bruyant
    bad = check_imports(body, "borgHelperWWW", mods)
    for name, (_p, fname, src) in sorted(mods.items()):
        bad += check_imports(src, fname, mods)
    if bad:
        sys.exit("[ERREUR] imports non stdlib non optionnels :\n  " + "\n  ".join(bad))
    return version, out


def main():
    ap = argparse.ArgumentParser(description="Génère la version autonome (stdlib seule) de borgHelperWWW.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--rev", help="révision git (ex. HEAD) dont lire Borg/borgHelperWWW (défaut : HEAD)")
    g.add_argument("--src", help="fichier borgHelperWWW du disque à la place d'une révision git")
    ap.add_argument("--out-dir", default=str(HERE), help="dossier de sortie (défaut : le dossier de ce script)")
    ap.add_argument("--no-link", action="store_true", help="ne pas mettre à jour le lien borgHelperWWW")
    args = ap.parse_args()
    if not args.src and not args.rev:
        args.rev = "HEAD"
    src_text, origin = read_source(args)
    version, out = build(src_text, origin, collect_compat())
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"borgHelperWWW-{version}"
    data = out.encode("utf-8")
    if not target.exists() or target.read_bytes() != data:
        tmp = out_dir / f".{target.name}.tmp"
        tmp.write_bytes(data)
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)
        state = "écrit"
    else:
        os.chmod(target, 0o755)
        state = "inchangé"
    if not args.no_link:
        link = out_dir / "borgHelperWWW"
        if not (link.is_symlink() and os.readlink(link) == target.name):
            tmp = out_dir / ".borgHelperWWW.lnk"
            if tmp.is_symlink() or tmp.exists():
                tmp.unlink()
            os.symlink(target.name, tmp)
            os.replace(tmp, link)
    print(f"{target} ({state}, {len(data)} octets, borgHelperWWW {version}, {origin})")


if __name__ == "__main__":
    main()

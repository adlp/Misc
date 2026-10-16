"""Écritures locales : dossiers 0700, fichiers 0600, temporaire jamais laissé."""
import os
import pathlib
import stat

import pytest

from sshvault import fsutil


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_ensure_dir_cree_en_0700(tmp_path):
    d = tmp_path / "a" / "b"
    fsutil.ensure_dir(str(d))
    assert mode(tmp_path / "a") == 0o700 and mode(d) == 0o700


def test_ensure_dir_resserre_un_dossier_existant(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    os.chmod(d, 0o755)
    fsutil.ensure_dir(str(d))
    assert mode(d) == 0o700


def test_ensure_dir_composant_fichier(tmp_path):
    f = tmp_path / "fichier"
    f.write_text("")
    os.chmod(f, 0o644)
    with pytest.raises(NotADirectoryError, match="n'est pas un dossier"):
        fsutil.ensure_dir(str(f / "sous"))
    with pytest.raises(NotADirectoryError):
        fsutil.ensure_dir(str(f))
    assert mode(f) == 0o644, "rien modifié"


def test_write_private_temporaire_retire_si_replace_echoue(tmp_path, monkeypatch):
    def boom(a, b):
        raise OSError(30, "Read-only file system")
    monkeypatch.setattr(fsutil.os, "replace", boom)
    with pytest.raises(OSError):
        fsutil.write_private(str(tmp_path / "d" / "session"), b"jeton")
    assert os.listdir(tmp_path / "d") == []


def test_write_private_temporaire_retire_sur_interruption(tmp_path, monkeypatch):
    def interrupt(a, b):
        raise KeyboardInterrupt
    monkeypatch.setattr(fsutil.os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        fsutil.write_private(str(tmp_path / "d" / "session"), b"jeton")
    assert os.listdir(tmp_path / "d") == []


def test_write_private_0600(tmp_path):
    p = tmp_path / "d" / "f"
    fsutil.write_private(str(p), b"x")
    assert mode(p) == 0o600 and p.read_bytes() == b"x"


def test_fs_type_point_de_montage_le_plus_long(tmp_path):
    from sshvault.fsutil import fs_type
    m = tmp_path / "mounts"
    m.write_text("/dev/sda1 / ext4 rw 0 0\ntmpfs /run tmpfs rw 0 0\ntmpfs /run/user/1001 tmpfs rw 0 0\n"
                 "/dev/sdb1 /run/user/1001/disque xfs rw 0 0\nx /mon\\040dossier ramfs rw 0 0\n")
    assert fs_type("/run/user/1001/a", str(m)) == "tmpfs"
    assert fs_type("/run/user/1001/disque/a", str(m)) == "xfs"
    assert fs_type("/run/user/10011", str(m)) == "tmpfs"  # préfixe /run, pas /run/user/1001
    assert fs_type("/mon dossier/x", str(m)) == "ramfs"
    assert fs_type("/home", str(m)) == "ext4"


def test_link_chain_40_maillons_dossier_de_la_cible(tmp_path):
    """Exactement 40 liens : la boucle s'arrête sur la cible ; son dossier est contrôlé aussi."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    target = b / "cible"
    target.write_text("x")
    prev = target
    for i in range(39, -1, -1):
        link = a / ("l%d" % i)
        link.symlink_to(prev)
        prev = link
    end, dirs = fsutil._link_chain(str(a / "l0"))
    assert end == str(target)
    assert str(b) in dirs


def test_link_chain_relatif_depuis_le_dossier_reel(tmp_path):
    """Lien relatif `..` dans un dossier atteint par un lien : résolu depuis le dossier réel."""
    (tmp_path / "vrai" / "sous").mkdir(parents=True)
    (tmp_path / "vrai" / "f").write_text("x")
    (tmp_path / "raccourci").symlink_to("vrai/sous")
    (tmp_path / "vrai" / "sous" / "l").symlink_to("../f")
    end, _ = fsutil._link_chain(str(tmp_path / "raccourci" / "l"))
    assert end == str(tmp_path / "vrai" / "f")


def test_link_chain_dotdot_dans_la_valeur_apres_un_dossier_lien(tmp_path):
    """`l -> dl/../f` avec `dl` lien vers vrai/sous : le noyau ouvre vrai/f (pas tmp/f)."""
    (tmp_path / "vrai" / "sous").mkdir(parents=True)
    (tmp_path / "vrai" / "f").write_text("vrai")
    (tmp_path / "f").write_text("leurre")
    (tmp_path / "dl").symlink_to("vrai/sous")
    (tmp_path / "l").symlink_to("dl/../f")
    end, _ = fsutil._link_chain(str(tmp_path / "l"))
    assert end == str(tmp_path / "vrai" / "f")
    assert pathlib.Path(end).read_text() == (tmp_path / "l").read_text() == "vrai"


def test_chain_exposure_dossier_dit_une_fois(tmp_path):
    """Dossier atteint par son chemin écrit (lien) et réel : une raison, un chmod."""
    (tmp_path / "vrai").mkdir()
    (tmp_path / "vrai").chmod(0o770)
    (tmp_path / "vrai" / "f").write_text("x")
    (tmp_path / "vrai" / "f").chmod(0o600)
    (tmp_path / "raccourci").symlink_to("vrai")
    _, reasons, to_chmod, _ = fsutil.chain_exposure(str(tmp_path / "raccourci" / "f"))
    mine = [r for r in reasons if r.startswith("dossier") and ("raccourci" in r or "vrai" in r)]
    assert len(mine) == 1, reasons
    assert len([c for c in to_chmod if "raccourci" in c or "vrai" in c]) == 1, to_chmod

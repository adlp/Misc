"""Écritures locales : dossiers 0700, fichiers 0600, temporaire jamais laissé."""
import os
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

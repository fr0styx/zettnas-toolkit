"""Code scanning follow-up: a snapshot's share and a VM's folder are single names inside their
folder, and the share path check still takes what it took before."""

import os

import pytest

from backend.services import snapshot_service


class Pal:
    def __init__(self, pool):
        self.pool = pool

    def list_shares(self):
        return []

    def get_pool_path(self, pool_id):
        return self.pool


def test_a_snapshot_share_is_one_name_inside_the_pool(tmp_path):
    (tmp_path / "@shares" / "photos").mkdir(parents=True)
    pal = Pal(str(tmp_path))
    assert snapshot_service._live_root("photos@auto-1", pal, "p") == str(tmp_path / "@shares" / "photos")
    for bad in ("..@x", ".@x", "a/b@x"):
        with pytest.raises(ValueError):
            snapshot_service._live_root(bad, pal, "p")
    with pytest.raises(FileNotFoundError):
        snapshot_service._live_root("gone@x", pal, "p")
    assert snapshot_service._live_root("pool-wide", pal, "p") == str(tmp_path)


def test_the_share_path_check_takes_what_it_took(tmp_path, monkeypatch):
    from backend.services import samba_engine

    root = tmp_path / "pool"
    (root / "media").mkdir(parents=True)
    monkeypatch.setattr(samba_engine, "_allowed_share_roots", lambda: [str(root)])
    assert samba_engine.validate_share_path(str(root / "media")) == os.path.realpath(root / "media")
    assert samba_engine.validate_share_path(str(root)) == os.path.realpath(root)
    for bad in (str(tmp_path / "elsewhere"), str(root) + "-twin", "relative/path", "/"):
        with pytest.raises(ValueError):
            samba_engine.validate_share_path(bad)

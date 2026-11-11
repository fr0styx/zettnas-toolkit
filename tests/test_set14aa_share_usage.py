"""SET-14 Shares 12: a share's usage counts as its own only where Unraid reports it per share."""

from backend.hardware.pal.base import NetworkShare
from backend.hardware.pal.unraid import UnraidStorageAdapter


def test_the_default_is_the_pool_figure():
    assert NetworkShare(name="x").usage_is_own is False


def test_unraid_figures_are_the_share_own(tmp_path, monkeypatch):
    (tmp_path / "shares.ini").write_text(
        '["media"]\nname="media"\nfree="1000"\nused="500"\n["empty"]\nname="empty"\n', encoding="utf-8"
    )
    monkeypatch.setattr("backend.hardware.pal.base.POOL_PATH", str(tmp_path))
    adapter = UnraidStorageAdapter()
    adapter._emhttp_dir = str(tmp_path)
    shares = {s.name: s for s in adapter.list_shares()}
    assert shares["media"].usage_is_own is True
    assert shares["media"].used_bytes == 500 * 1024
    assert shares["empty"].usage_is_own is False

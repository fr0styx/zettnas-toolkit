"""SEC-06: Samba share settings are validated before reaching smb.conf."""

import pytest

from backend import config
from backend.services import samba_engine
from backend.services.samba_engine import SambaShareConfig, validate_share


@pytest.fixture
def pool(tmp_path, monkeypatch):
    root = tmp_path / "pool"
    (root / "media").mkdir(parents=True)
    monkeypatch.setattr(config, "POOL_PATH", str(root))
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(root)])
    return root


def test_safe_defaults():
    s = SambaShareConfig(name="x", path="/mnt/x")
    assert s.guest_ok is False and s.force_user == "nobody" and s.force_group == "users"


@pytest.mark.parametrize(
    "field,value",
    [
        ("comment", "hi\n[global]\n   include = /etc/evil"),
        ("comment", "x]\n"),
        ("valid_users", "alice\npath = /"),
        ("force_user", "root\nadmin users = everyone"),
        ("write_list", "alice; rm"),
        ("force_user", "root nobody"),
    ],
)
def test_injection_is_rejected(pool, field, value):
    share = SambaShareConfig(name="media", path=str(pool / "media"))
    setattr(share, field, value)
    with pytest.raises(ValueError):
        validate_share(share)


@pytest.mark.parametrize("path", ["/", "/etc", "/app/data", "relative/path", "/tmp"])
def test_paths_outside_the_pool_are_rejected(pool, path):
    with pytest.raises(ValueError):
        validate_share(SambaShareConfig(name="bad", path=path))


def test_symlink_escape_is_rejected(pool, tmp_path):
    (pool / "escape").symlink_to("/etc")
    with pytest.raises(ValueError):
        validate_share(SambaShareConfig(name="bad", path=str(pool / "escape")))


def test_valid_share_passes_and_conf_skips_unsafe_stored_shares(pool, tmp_path, monkeypatch):
    validate_share(
        SambaShareConfig(name="media", path=str(pool / "media"), valid_users="alice @staff", write_list="alice")
    )
    monkeypatch.setattr(samba_engine, "SAMBA_CONF_FILE", str(tmp_path / "smb.conf"))
    engine = samba_engine.SambaEngine.__new__(samba_engine.SambaEngine)
    engine._shares = {
        "ok": SambaShareConfig(name="ok", path=str(pool / "media")),
        "evil": SambaShareConfig(name="evil", path="/etc", comment="x"),
    }
    conf = engine.generate_and_save_conf()
    assert "[ok]" in conf and "[evil]" not in conf
    assert "guest ok = no" in conf

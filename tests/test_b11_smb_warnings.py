"""B11 (SEC-28, D11): SMB does not yet follow share access, and skips two-factor; the Security
Advisor says so for one release before SMB is changed."""

from backend.services import safe_defaults_advisor, samba_engine, share_access
from backend.services.samba_engine import SambaShareConfig
from backend.users_db import users_db_session


class _Engine:
    def __init__(self, shares):
        self.shares = shares

    def list_shares(self):
        return self.shares


def _smb(monkeypatch, *shares):
    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: _Engine(list(shares)))
    return {f["id"]: f for f in safe_defaults_advisor._smb_findings()}


def test_a_share_kept_from_someone_but_open_over_smb_is_named(monkeypatch):
    share_access.save_config({"default_level": "write", "shares": {"media": {"users": {"kid": "none"}}}})
    found = _smb(monkeypatch, SambaShareConfig(name="media", path="/mnt/user/media"))
    assert "media" in found["smb_ignores_share_access"]["details"]
    assert "next release" in found["smb_ignores_share_access"]["details"]


def test_valid_users_on_the_share_or_open_access_is_fine(monkeypatch):
    share_access.save_config({"default_level": "write", "shares": {"media": {"users": {"kid": "none"}}}})
    found = _smb(monkeypatch, SambaShareConfig(name="media", path="/mnt/user/media", valid_users="ann"))
    assert "smb_ignores_share_access" not in found
    share_access.save_config({"default_level": "write", "shares": {}})
    found = _smb(monkeypatch, SambaShareConfig(name="media", path="/mnt/user/media"))
    assert "smb_ignores_share_access" not in found


def test_a_new_install_default_counts_as_restricted(monkeypatch):
    share_access.save_config({"default_level": "none", "shares": {}})
    assert "smb_ignores_share_access" in _smb(monkeypatch, SambaShareConfig(name="photos", path="/mnt/user/photos"))


def test_two_factor_accounts_are_named(monkeypatch):
    with users_db_session() as conn:
        conn.execute("UPDATE users SET mfa_enabled = 0")
    assert "smb_skips_two_factor" not in _smb(monkeypatch, SambaShareConfig(name="a", path="/mnt/user/a"))
    with users_db_session() as conn:
        conn.execute("UPDATE users SET mfa_enabled = 1 WHERE username = 'admin'")
    try:
        assert "smb_skips_two_factor" in _smb(monkeypatch, SambaShareConfig(name="a", path="/mnt/user/a"))
    finally:
        with users_db_session() as conn:
            conn.execute("UPDATE users SET mfa_enabled = 0 WHERE username = 'admin'")


def test_no_smb_shares_no_warnings(monkeypatch):
    assert _smb(monkeypatch) == {}

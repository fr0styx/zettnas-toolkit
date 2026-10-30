"""NSEC-8: a restore goes back only inside the share its Recycle Bin belongs to."""

import os
from types import SimpleNamespace

import pytest

from backend.api.files import trash


@pytest.fixture
def bin_with(tmp_path, monkeypatch):
    share = tmp_path / "Family"
    b = share / ".RecycleBin"
    (b / "files").mkdir(parents=True)
    (b / "info").mkdir()
    (b / "files" / "1700000000_note.txt").write_text("hi")
    other = tmp_path / "Other"
    other.mkdir()

    def write_info(path):
        (b / "info" / "1700000000_note.txt.trashinfo").write_text(f"[Trash Info]\nPath={path}\n")

    monkeypatch.setattr(trash.recycle_bin, "locate", lambda item: (str(b), "1700000000_note.txt"))
    monkeypatch.setattr(trash, "_is_files_admin", lambda p: True)
    monkeypatch.setattr(trash, "_contained", lambda p, must_exist=False: p)
    monkeypatch.setattr(trash, "check_user_path_access", lambda *a, **k: None)
    return SimpleNamespace(share=share, other=other, write_info=write_info)


def test_a_forged_trashinfo_cant_send_a_file_elsewhere(bin_with):
    bin_with.write_info(str(bin_with.other / "planted.txt"))
    out = trash._restore(SimpleNamespace(item_id="x", target_path=""), SimpleNamespace())
    assert os.path.dirname(out["path"]) == str(bin_with.share)
    assert not (bin_with.other / "planted.txt").exists()


def test_a_real_trashinfo_restores_in_place(bin_with):
    (bin_with.share / "docs").mkdir()
    bin_with.write_info(str(bin_with.share / "docs" / "note.txt"))
    out = trash._restore(SimpleNamespace(item_id="x", target_path=""), SimpleNamespace())
    assert out["path"] == str(bin_with.share / "docs" / "note.txt")


def test_the_code_step_checks_the_account_lockout(client, monkeypatch):
    """NSEC-14: the 2FA code step refuses while the account is locked, like the password step."""
    from backend.api import auth

    monkeypatch.setattr(auth, "verify_mfa_token", lambda t: {"u": "mia", "uid": "u1"})
    monkeypatch.setattr(auth, "_lockout_remaining", lambda key: 300 if key == "account:mia" else 0)
    r = client.post("/api/auth/mfa/challenge", json={"mfa_token": "mfa_x", "mfa_code": "123456"})
    assert r.status_code == 429

"""Batch 6 family scenario: three accounts, private folders, a quota, invites, a kid role."""

import os
import time

import pytest
from fastapi import HTTPException

from backend import config, users_db
from backend.auth import AuthenticatedPrincipal
from backend.services import user_spaces


@pytest.fixture
def family(tmp_path, monkeypatch):
    db = str(tmp_path / "users.db")
    pool = tmp_path / "pool"
    pool.mkdir()
    monkeypatch.setattr(config, "USERS_DB_PATH", db)
    monkeypatch.setattr(users_db, "USERS_DB_PATH", db, raising=False)
    monkeypatch.setattr(config, "POOL_PATH", str(pool))
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(pool)])
    import backend.services.path_access as pa

    monkeypatch.setattr(pa, "ALLOWED_BROWSE_ROOTS", [str(pool)], raising=False)
    users_db.init_users_db(db)
    users = {
        "mum": users_db.create_user("mum", "Mum", "Mum-Pass-123", role_id="superadmin", db_path=db),
        "dad": users_db.create_user("dad", "Dad", "Dad-Pass-123", role_id="share_user", db_path=db),
        "lea": users_db.create_user(
            "lea", "Lea", "Lea-Pass-123", role_id="kid", storage_quota_bytes=1024 * 1024, db_path=db
        ),
    }
    for name, u in users.items():
        user_spaces.ensure_home(name, int(u.get("storage_quota_bytes") or 0))
    return {"db": db, "pool": pool, "users": users}


def _principal(user, scopes):
    return AuthenticatedPrincipal(user_id=user["id"], username=user["username"], role_id=user["role_id"], scopes=scopes)


def test_each_person_has_a_private_folder(family):
    from backend.services.path_access import check_user_path_access

    homes = family["pool"] / "homes"
    assert {p.name for p in homes.iterdir()} == {"mum", "dad", "lea"}
    dad = _principal(family["users"]["dad"], ["shares:read", "shares:user_write", "system:view"])
    lea = _principal(family["users"]["lea"], ["shares:read", "shares:user_write"])
    check_user_path_access(str(homes / "lea" / "school.txt"), lea, write=True)
    for who, path in ((dad, homes / "lea"), (lea, homes / "dad" / "taxes.txt")):
        with pytest.raises(HTTPException) as e:
            check_user_path_access(str(path), who)
        assert e.value.status_code == 403


def test_the_kids_quota_holds(family):
    home = family["pool"] / "homes" / "lea"
    with open(home / "drawing.png", "wb") as f:
        f.write(b"x" * 600 * 1024)
    assert user_spaces.check_upload("lea", str(home / "small.txt"), 100 * 1024) is not None
    with pytest.raises(user_spaces.QuotaExceeded):
        user_spaces.check_upload("lea", str(home / "video.mp4"), 500 * 1024)
    # no quota for dad, and the kid's quota doesn't apply outside her folder
    assert user_spaces.check_upload("dad", str(family["pool"] / "homes" / "dad" / "big.iso"), 10**10) is None
    assert user_spaces.check_upload("lea", str(family["pool"] / "family" / "x"), 10**9) is None


def test_invite_link_creates_a_kid_account_once(family):
    db = family["db"]
    token, inv = users_db.create_invite("kid", 7, 1, "for Max", "mum", quota_bytes=2 * 1024**3, db_path=db)
    assert users_db.lookup_invite(token, db_path=db)["role_id"] == "kid"
    assert token not in str(users_db.list_invites(db_path=db))  # only the hash is stored
    user = users_db.accept_invite(token, "max", "Max", "Max-Pass-123", db_path=db)
    assert user["role_id"] == "kid" and int(user["storage_quota_bytes"]) == 2 * 1024**3
    with pytest.raises(LookupError):
        users_db.accept_invite(token, "max2", "Max", "Max-Pass-123", db_path=db)
    old, _ = users_db.create_invite("guest", 1, 1, "", "mum", db_path=db)
    with users_db.users_db_session(db) as conn:
        conn.execute("UPDATE invites SET expires_at = ?", (time.time() - 1,))
    assert users_db.lookup_invite(old, db_path=db) is None


def test_taken_usernames_are_refused(family):
    token, _ = users_db.create_invite("guest", 7, 2, "", "mum", db_path=family["db"])
    with pytest.raises(ValueError):
        users_db.accept_invite(token, "dad", "Dad", "Another-Pass-1", db_path=family["db"])


def test_kids_chat_stays_on_the_nas(family):
    from backend.services.ai_chat_agent import run_agentic_chat

    lea = _principal(family["users"]["lea"], ["shares:read", "shares:user_write"])
    res = run_agentic_chat("what is the weather in Paris", [], True, True, None, lea)
    assert res["web_allowed"] is False


def test_samba_offers_private_folders(family, tmp_path, monkeypatch):
    from backend.services import samba_engine

    monkeypatch.setattr(samba_engine, "SAMBA_CONF_FILE", str(tmp_path / "smb.conf"))
    eng = samba_engine.SambaEngine()
    eng.generate_and_save_conf()
    conf = (tmp_path / "smb.conf").read_text()
    assert "[homes]" in conf and "valid users = %S" in conf

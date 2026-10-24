"""File access: regression tests for the 2026-10 security audit.

F04 a folder above a share can be browsed but not read, zipped or shared;
F10 Recycle Bin restore needs write access where the item was deleted;
F15/F18 AI folder audit and manifest only show readable files.
"""

import os
import secrets

import pytest
from fastapi import HTTPException

from backend import config
from backend.api.fs import check_user_path_access
from backend.auth import AuthenticatedPrincipal
from backend.services import share_access
from backend.users_db import create_user


def _user(name):
    return AuthenticatedPrincipal(
        {
            "user_id": f"u_{name}",
            "username": name,
            "role_id": "share_user",
            "scopes": ["shares:read", "shares:user_write"],
        }
    )


@pytest.fixture
def tree(tmp_path, monkeypatch):
    name = f"fa{secrets.token_hex(3)}"
    root = tmp_path / "user"
    for d in ("media", "private", f"homes/{name}", "homes/bob"):
        (root / d).mkdir(parents=True)
    (root / "media" / "song.mp3").write_text("x")
    (root / "private" / "plan.txt").write_text("private")
    (root / "homes" / "bob" / "notes.txt").write_text("bob")
    (root / "loose.txt").write_text("root file")
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config, "POOL_PATH", str(root))
    monkeypatch.setattr("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)])
    monkeypatch.setattr(
        share_access,
        "known_shares",
        lambda: [
            {"name": "media", "path": str(root / "media"), "samba": None},
            {
                "name": "private",
                "path": str(root / "private"),
                "samba": {"valid": {"bob"}, "read": set(), "write": set(), "read_only": False},
            },
        ],
    )
    share_access.invalidate()
    return root, name


def _session(client, name):
    create_user(name, name, "GoodPass123!", role_id="share_user")
    r = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_folders_above_a_share_are_browse_only(tree):
    root, name = tree
    user = _user(name)
    for folder in (root, root / "homes"):
        check_user_path_access(str(folder), user, allow_list=True)
        with pytest.raises(HTTPException) as e:
            check_user_path_access(str(folder), user)
        assert e.value.status_code == 403


def test_zip_of_the_homes_folder_is_refused(client, tree):
    root, name = tree
    headers = _session(client, name)
    r = client.get("/api/fs/download-zip", params={"paths": str(root / "homes")}, headers=headers)
    assert r.status_code == 403
    assert client.get("/api/browse", params={"path": str(root)}, headers=headers).status_code == 200


def test_recycle_bin_restore_needs_write_access_where_it_was_deleted(client, tree):
    root, name = tree
    bin_dir = root / ".RecycleBin"
    (bin_dir / "files").mkdir(parents=True)
    (bin_dir / "info").mkdir()
    item = "1700000000_plan-old.txt"
    (bin_dir / "files" / item).write_text("private draft")
    (bin_dir / "info" / f"{item}.trashinfo").write_text(f"[Trash Info]\nPath={root / 'private' / 'plan-old.txt'}\n")

    headers = _session(client, name)
    r = client.post(
        "/api/fs/trash/restore",
        json={"item_id": item, "target_path": str(root / "homes" / name)},
        headers=headers,
    )
    assert r.status_code == 403
    assert (bin_dir / "files" / item).exists()
    assert not (root / "homes" / name / "plan-old.txt").exists()


def test_ai_folder_views_keep_only_readable_files(tree):
    from backend.services.rag_engine import RagSearchEngine

    root, name = tree
    engine = RagSearchEngine.__new__(RagSearchEngine)
    paths = [
        str(root / "media" / "song.mp3"),
        str(root / "private" / "plan.txt"),
        str(root / "homes" / "bob" / "notes.txt"),
        str(root / "homes" / name / "mine.txt"),
        str(root / "loose.txt"),
        str(root / "media" / ".RecycleBin" / "old.mp3"),
    ]
    readable = engine._readable_paths(paths, _user(name))
    assert readable == {str(root / "media" / "song.mp3"), str(root / "homes" / name / "mine.txt")}
    assert engine._readable_paths(paths, None) == set(paths)
    assert os.path.exists(paths[0])

"""B12a (REL-23, REL-27, REL-28): snapshot and off-site browsing show only what the person may
open; "Set up a backup" is ticked only after a backup reached somewhere else; a rotating log
file goes into the support bundle."""

import io
import json
import logging
import os
import zipfile

import pytest

from backend import config
from backend.auth import AuthenticatedPrincipal
from backend.services import getting_started, offsite_backup, share_access, snapshot_service


def _who(name, role="share_user", scopes=("shares:read", "shares:user_write", "backup:read")):
    return AuthenticatedPrincipal({"user_id": f"u_{name}", "username": name, "role_id": role, "scopes": list(scopes)})


ADMIN = _who("boss", "superadmin", ("*",))


@pytest.fixture
def tree(tmp_path, monkeypatch):
    pool = tmp_path / "pool"
    for d in ("media", "private"):
        (pool / d).mkdir(parents=True)
    snap = tmp_path / "snaps" / "daily-1"
    for d, f in (("media", "song.mp3"), ("private", "diary.txt")):
        (snap / d).mkdir(parents=True)
        (snap / d / f).write_text("x")
    monkeypatch.setattr(config, "POOL_PATH", str(pool))
    monkeypatch.setattr("backend.config.ALLOWED_BROWSE_ROOTS", [str(pool)])
    monkeypatch.setattr(
        share_access,
        "known_shares",
        lambda: [
            {"name": "media", "path": str(pool / "media"), "samba": None},
            {"name": "private", "path": str(pool / "private"), "samba": None},
        ],
    )
    share_access.save_config({"default_level": "none", "shares": {"media": {"users": {"alice": "read"}}}})

    class Pal:
        def list_snapshots(self, pool_id):
            return [{"name": "daily-1", "path": str(snap)}]

        def get_pool_path(self, pool_id):
            return str(pool)

        def list_pools(self):
            return []

    return Pal(), pool


def _names(listing):
    return sorted(e["name"] for e in listing["entries"])


def test_a_snapshot_shows_only_the_folders_the_person_may_open(tree):
    pal, _ = tree
    assert _names(snapshot_service.browse("daily-1", "", pal=pal, pool_id="p", principal=ADMIN)) == ["media", "private"]
    assert _names(snapshot_service.browse("daily-1", "", pal=pal, pool_id="p", principal=_who("alice"))) == ["media"]
    assert _names(snapshot_service.browse("daily-1", "media", pal=pal, pool_id="p", principal=_who("alice"))) == [
        "song.mp3"
    ]
    with pytest.raises(PermissionError):
        snapshot_service.browse("daily-1", "private", pal=pal, pool_id="p", principal=_who("alice"))


def test_an_off_site_version_shows_only_what_the_person_may_open(tree, monkeypatch):
    _, pool = tree
    lines = [
        {"struct_type": "snapshot"},
        {"struct_type": "node", "name": "media", "path": f"{pool}/media", "type": "dir"},
        {"struct_type": "node", "name": "private", "path": f"{pool}/private", "type": "dir"},
    ]
    monkeypatch.setattr(offsite_backup, "get_repo", lambda rid: {"id": rid, "location": "/x"})
    monkeypatch.setattr(
        offsite_backup, "run_restic", lambda repo, args, timeout=0: "\n".join(json.dumps(x) for x in lines)
    )
    every = offsite_backup.browse("r", "latest", str(pool))
    assert sorted(e["name"] for e in every) == ["media", "private"]
    mine = offsite_backup.browse("r", "latest", str(pool), principal=_who("alice"))
    assert [e["name"] for e in mine] == ["media"]
    with pytest.raises(PermissionError):
        offsite_backup.browse("r", "latest", f"{pool}/private", principal=_who("alice"))


# --- REL-27 ------------------------------------------------------------------------------------


def test_a_backup_counts_once_it_reached_somewhere_else(monkeypatch):
    jobs, repos = [], []
    monkeypatch.setattr("backend.services.backup_engine.get_backup_jobs", lambda: jobs)
    monkeypatch.setattr("backend.services.offsite_backup.list_repos", lambda: repos)
    assert getting_started._has_backup() is False
    jobs.append({"destination_type": "remote", "last_status": "error"})  # set up, never succeeded
    assert getting_started._has_backup() is False
    jobs.append({"destination_type": "local_snapshot", "last_success_at": 1})  # on the same box
    assert getting_started._has_backup() is False
    repos.append({"location": "/mnt/user/backups", "last_backup": 1, "last_result": "ok"})  # same pool
    assert getting_started._has_backup() is False
    repos.append({"location": "/mnt/disks/usb/zettnas", "last_backup": 1, "last_result": "ok"})
    assert getting_started._has_backup() is True
    repos.clear()
    jobs.append({"destination_type": "remote", "last_success_at": 2})
    assert getting_started._has_backup() is True


# --- REL-28 ------------------------------------------------------------------------------------


def test_the_log_file_rotates_and_goes_into_the_bundle(tmp_path, monkeypatch):
    from backend import logging_config
    from backend.api import diagnostics

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TESTING", raising=False)
    from backend import logging_config

    monkeypatch.setattr(logging_config, "test_mode", lambda: False)  # NARC-6: the one switch
    root = logging.getLogger("zn-test-file")
    root.propagate = False
    path = logging_config._add_file_handler(root, logging.Formatter("%(message)s"))
    assert path == str(tmp_path / "logs" / "zettnas.log")
    root.warning("disk sdb said hello token=zat_abcdefghijklmnopqrstuv")
    for h in root.handlers:
        h.flush()
    assert logging_config.log_files() == [path]
    monkeypatch.setenv("TESTING", "1")
    data = diagnostics._build_bundle_sync({})
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "logs/zettnas.log" in names
    text = zipfile.ZipFile(io.BytesIO(data)).read("logs/zettnas.log").decode()
    assert "disk sdb said hello" in text and "zat_abcdefghijklmnopqrstuv" not in text
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()


def test_no_log_file_in_tests_or_when_switched_off(tmp_path, monkeypatch):
    from backend import logging_config

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TESTING", "1")
    assert logging_config._add_file_handler(logging.getLogger("zn-x"), logging.Formatter()) is None
    monkeypatch.delenv("TESTING")
    monkeypatch.setenv("ZETTNAS_LOG_FILE", "0")
    assert logging_config._add_file_handler(logging.getLogger("zn-x"), logging.Formatter()) is None
    assert not os.path.exists(tmp_path / "logs")

"""B12b (FEAT-01): how well this NAS is protected (copies outside the box, the newest good one,
where they are) for the Overview, and where a new backup could go for "Protect this NAS"."""

import time
from types import SimpleNamespace

from backend.services import protection_status as ps

NOW = time.time()


def _sources(monkeypatch, repos=(), jobs=(), replication=()):
    monkeypatch.setattr("backend.services.offsite_backup.list_repos", lambda: list(repos))
    monkeypatch.setattr("backend.services.backup_engine.get_backup_jobs", lambda: list(jobs))
    monkeypatch.setattr(
        "backend.services.replication_engine.get_replication_engine",
        lambda: SimpleNamespace(list_jobs=lambda: list(replication)),
    )


def test_where_a_copy_is():
    assert ps.kind_of("rclone:b2:nas") == "cloud"
    assert ps.kind_of("/mnt/disks/usb1/zettnas-backup") == "usb"
    assert ps.kind_of("/mnt/remotes/office_nas/backup") == "nas"
    assert ps.kind_of("/mnt/user/backups") == "here"


def test_no_copy_outside_the_box(monkeypatch):
    _sources(monkeypatch, repos=[{"id": "same", "location": "/mnt/user/backups", "last_backup": NOW}])
    assert ps.status(NOW) == {"level": "none", "copies": 0, "total": 0, "last_good": None, "where": [], "items": []}


def test_current_copies_and_where(monkeypatch):
    _sources(
        monkeypatch,
        repos=[
            {"id": "usb", "name": "USB", "location": "/mnt/disks/usb1/b", "last_backup": NOW - 3600},
            {"id": "b2", "name": "Cloud", "location": "rclone:b2:nas", "last_backup": NOW - 10 * 86400},
        ],
        jobs=[
            {"name": "Old copy", "destination_type": "remote", "last_success_at": NOW - 7200},
            {"name": "Moved", "destination_type": "remote", "migrated_to": "from-x", "last_success_at": NOW},
            {"name": "Settings", "kind": "config", "destination_type": "remote", "last_success_at": NOW},
        ],
        replication=[
            {"name": "To office", "target_type": "remote_ssh", "last_success": NOW - 60},
            {"name": "Same box", "target_type": "local", "last_success": NOW},
        ],
    )
    st = ps.status(NOW)
    assert st["level"] == "good" and st["copies"] == 3 and st["total"] == 4
    assert st["where"] == ["cloud", "nas", "usb"] and st["last_good"] == NOW - 60


def test_only_old_copies(monkeypatch):
    _sources(monkeypatch, repos=[{"id": "b2", "location": "rclone:b2:nas", "last_backup": NOW - 9 * 86400}])
    st = ps.status(NOW)
    assert st["level"] == "stale" and st["last_good"] == NOW - 9 * 86400
    _sources(monkeypatch, repos=[{"id": "b2", "location": "rclone:b2:nas", "last_backup": None}])
    assert ps.status(NOW)["level"] == "stale"  # set up but never succeeded


def test_unreadable_sources_count_as_none(monkeypatch):
    def broken():
        raise RuntimeError("unreadable")

    monkeypatch.setattr("backend.services.offsite_backup.list_repos", broken)
    monkeypatch.setattr("backend.services.backup_engine.get_backup_jobs", broken)
    monkeypatch.setattr("backend.services.replication_engine.get_replication_engine", broken)
    assert ps.status(NOW)["level"] == "none"


def test_where_a_new_backup_could_go(tmp_path, monkeypatch):
    usb, remotes = tmp_path / "disks", tmp_path / "remotes"
    (usb / "usb1").mkdir(parents=True)
    (usb / "not-mounted").mkdir()
    (remotes / "office").mkdir(parents=True)
    monkeypatch.setattr(ps, "USB_ROOT", str(usb))
    monkeypatch.setattr(ps, "NAS_ROOTS", (str(remotes), str(tmp_path / "missing")))
    mounted = {str(usb / "usb1"), str(remotes / "office")}
    monkeypatch.setattr(ps.os.path, "ismount", lambda p: p in mounted)
    monkeypatch.setattr(
        "backend.services.rclone_engine.get_rclone_engine",
        lambda: SimpleNamespace(list_remotes=lambda: [{"name": "b2"}, {"name": "crypt_ab12"}, {}]),
    )
    assert ps.destinations() == {"usb": [str(usb / "usb1")], "nas": [str(remotes / "office")], "cloud": ["b2"]}

    def broken():
        raise RuntimeError("no rclone")

    monkeypatch.setattr("backend.services.rclone_engine.get_rclone_engine", broken)
    assert ps.destinations()["cloud"] == []


def test_the_routes(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ps, "status", lambda now=None: {"level": "none", "copies": 0})
    assert client.get("/api/system/protection", headers=auth_headers).json()["level"] == "none"
    monkeypatch.setattr(ps, "destinations", lambda: {"usb": ["/mnt/disks/usb1"], "nas": [], "cloud": []})
    assert client.get("/api/offsite/destinations", headers=auth_headers).json()["usb"] == ["/mnt/disks/usb1"]

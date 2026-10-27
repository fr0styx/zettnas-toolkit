"""A sleeping drive is never woken until the person confirms it (the "disk.wake" confirmation).

Reading it now, starting a self-test, Locate's disk-read blink, folder sizes and AI indexing
with force_wake all wake a sleeping drive; each answers 428 until a confirm token is sent.
A drive that is awake needs no confirmation.
"""

import subprocess
from unittest.mock import patch

import pytest

from backend.api import system
from backend.hardware import disks, locate

pytestmark = pytest.mark.real_confirmations


def _token(client, headers, target, action="disk.wake"):
    res = client.post("/api/confirmations", json={"action": action, "target": target}, headers=headers)
    assert res.status_code == 200, res.text
    return {**headers, "X-Confirm-Token": res.json()["token"]}


@pytest.fixture
def asleep(monkeypatch):
    state = {"asleep": True}
    monkeypatch.setattr(system, "is_drive_asleep", lambda dev: state["asleep"])
    return state


def test_a_self_test_on_a_sleeping_drive_waits_for_confirmation(client, auth_headers, asleep, monkeypatch):
    started = []
    monkeypatch.setattr(system, "run_disk_smart_test", lambda dev, kind: started.append(dev) or {"started": True})
    res = client.post("/api/disk/smart_test", json={"dev": "sdb", "test_type": "short"}, headers=auth_headers)
    assert res.status_code == 428
    body = res.json()
    assert body["action"] == "disk.wake" and body["target"] == "sdb" and "sdb" in body["summary"]
    assert started == []  # nothing ran, the drive stays asleep
    ok = client.post(
        "/api/disk/smart_test", json={"dev": "sdb", "test_type": "short"}, headers=_token(client, auth_headers, "sdb")
    )
    assert ok.status_code == 200 and started == ["sdb"]


def test_an_awake_drive_needs_no_confirmation(client, auth_headers, asleep, monkeypatch):
    asleep["asleep"] = False
    monkeypatch.setattr(system, "run_disk_smart_test", lambda dev, kind: {"started": True})
    res = client.post("/api/disk/smart_test", json={"dev": "sda", "test_type": "short"}, headers=auth_headers)
    assert res.status_code == 200


def test_reading_or_waking_a_sleeping_drive_waits_for_confirmation(client, auth_headers, asleep, monkeypatch):
    reads = []
    monkeypatch.setattr(system, "read_smart_detail", lambda dev, wake=False, max_age=0.0: reads.append(wake) or {})
    assert client.get("/api/disk_detail?dev=sdb", headers=auth_headers).status_code == 200  # last reading, no wake
    assert client.get("/api/disk_detail?dev=sdb&wake=true", headers=auth_headers).status_code == 428
    assert client.post("/api/disk_wake", json={"dev": "sdb"}, headers=auth_headers).status_code == 428
    assert reads == [False]
    ok = client.get("/api/disk_detail?dev=sdb&wake=true", headers=_token(client, auth_headers, "sdb"))
    assert ok.status_code == 200 and reads == [False, True]


def test_locate_uses_the_bay_lights_and_asks_only_before_reading_the_disk(client, auth_headers, asleep, monkeypatch):
    calls = []

    def lights_only(dev, duration, allow_read_strobe=True):
        calls.append(allow_read_strobe)
        return {"success": True, "tier": "argb"}

    monkeypatch.setattr(system, "locate_disk", lights_only)
    assert client.post("/api/disk/locate", json={"dev": "sdb"}, headers=auth_headers).status_code == 200
    assert calls == [False]  # blinked with the lights; the disk was not read

    calls.clear()

    def needs_read(dev, duration, allow_read_strobe=True):
        calls.append(allow_read_strobe)
        return {"success": True, "tier": "strobe"} if allow_read_strobe else {"success": False, "needs_wake": True}

    monkeypatch.setattr(system, "locate_disk", needs_read)
    assert client.post("/api/disk/locate", json={"dev": "sdb"}, headers=auth_headers).status_code == 428
    assert calls == [False]
    ok = client.post("/api/disk/locate", json={"dev": "sdb"}, headers=_token(client, auth_headers, "sdb"))
    assert ok.status_code == 200 and calls[-1] is True


def test_locate_never_reads_the_disk_unless_allowed(monkeypatch):
    monkeypatch.setattr(locate.os.path, "exists", lambda p: False)  # no SES backplane
    monkeypatch.setattr(locate, "find_led_port", lambda: None)  # no light bar
    assert locate.locate_drive_multitier("sdb", "/dev/sdb", 5, allow_read_strobe=False) == {
        "success": False,
        "needs_wake": True,
        "dev": "sdb",
    }


def test_folder_size_wakes_a_sleeping_drive_only_when_confirmed(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    folder = root / "photos"
    folder.mkdir(parents=True)
    (folder / "a.jpg").write_bytes(b"x" * 10)
    with (
        patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)]),
        patch("backend.services.rag_standby.is_backing_disk_in_standby", return_value=True),
    ):
        body = {"path": str(folder), "force_wake": True}
        assert client.post("/api/fs/folder-size", json=body, headers=auth_headers).status_code == 428
        ok = client.post("/api/fs/folder-size", json=body, headers=_token(client, auth_headers, str(folder)))
        assert ok.status_code == 200 and ok.json()["size"] == 10


def test_ai_indexing_that_forces_drives_awake_is_confirmed(client, auth_headers):
    res = client.post("/api/ai/index/sync", json={"force_wake": True}, headers=auth_headers)
    assert res.status_code == 428 and res.json()["target"] == "indexing"


class _Done:
    def __init__(self, rc, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def test_asleep_is_asked_without_waking(monkeypatch):
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        return _Done(2)

    monkeypatch.setattr(disks.subprocess, "run", run)
    assert disks.is_drive_asleep("sdb") is True
    assert "-n" in seen[0] and "standby" in seen[0]  # smartctl never spins it up to answer
    monkeypatch.setattr(disks.subprocess, "run", lambda cmd, **kw: _Done(0, "Power mode is: ACTIVE or IDLE"))
    assert disks.is_drive_asleep("sdb") is False
    assert disks.is_drive_asleep("nvme0n1") is False  # NVMe drives never count as asleep
    assert disks.is_drive_asleep("bad name!") is False

    def broken(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 6)

    monkeypatch.setattr(disks.subprocess, "run", broken)
    monkeypatch.setitem(disks.Z_STATE.cached_smart_data, "sdq", (None, "standby"))
    assert disks.is_drive_asleep("sdq") is True  # falls back to the last known state

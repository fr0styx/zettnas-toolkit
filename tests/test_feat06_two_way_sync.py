"""FEAT-06: two-way sync with conflict copies and a dry run first. The rclone tests run the real
rclone bisync between two local folders, so the parsing is checked against its real output."""

import os
import shutil
import time

import pytest

from backend.services import two_way_sync as tws

HAVE_RCLONE = shutil.which("rclone") is not None
REAL_BLOCKED = tws._blocked


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(tws, "PAIRS_FILE", str(tmp_path / "pairs.json"))
    monkeypatch.setattr(tws, "WORKDIR", str(tmp_path / "work"))
    monkeypatch.setattr(tws, "RCLONE_CONFIG_FILE", str(tmp_path / "rclone.conf"))
    monkeypatch.setattr(tws, "_blocked", lambda pair: None)
    tws._RUNNING.clear()
    return tmp_path


def _sides(tmp_path):
    a, b = tmp_path / "nas", tmp_path / "cloud"
    a.mkdir()
    b.mkdir()
    return a, b


def _pair(store, a, b, **kw):
    # the cloud side is a plain folder here; the API only accepts remote:path
    return tws.save_pair("photos", "Photos", str(a), "cloud:photos", check=lambda s: s, **kw) and tws._update(
        "photos", remote=str(b)
    )


def test_saving_checks_both_sides(store):
    with pytest.raises(ValueError, match="lowercase"):
        tws.save_pair("Bad Id", "x", "/a", "r:b", check=lambda s: s)
    with pytest.raises(ValueError, match="folder on this NAS"):
        tws.save_pair("p", "x", "r:a", "r:b", check=lambda s: s)
    with pytest.raises(ValueError, match="cloud folder"):
        tws.save_pair("p", "x", "/a", "/b", check=lambda s: s)
    p = tws.save_pair("p", "", "/a", "r:b", every_hours=500, max_delete=0, check=lambda s: s)
    assert p["name"] == "p" and p["every_hours"] == 168 and p["max_delete"] == 25 and p["state"] == "new"


def test_a_new_place_means_a_new_preview_and_first_run(store):
    tws.save_pair("p", "x", "/a", "r:b", check=lambda s: s)
    tws._update("p", state="active", baseline=True, preview={"ok": True})
    kept = tws.save_pair("p", "renamed", "/a", "r:b", check=lambda s: s)
    assert kept["state"] == "active" and kept["baseline"] is True
    moved = tws.save_pair("p", "renamed", "/a", "r:other", check=lambda s: s)
    assert moved["state"] == "new" and moved["baseline"] is False and moved["preview"] is None


def test_the_command():
    pair = {"local": "/mnt/user/a", "remote": "r:b", "max_delete": 10}
    cmd = tws.command(pair, dry_run=True)
    assert cmd[:4] == ["rclone", "bisync", "/mnt/user/a", "r:b"] and "--resync" in cmd and "--dry-run" in cmd
    assert cmd[cmd.index("--max-delete") + 1] == "10"
    assert "--resync" not in tws.command({**pair, "baseline": True}, dry_run=False)


def test_parse_normal_run_output():
    text = """
INFO  : Path1 checking for diffs
INFO  : - Path1    File is new                         - a.txt
INFO  : Applying changes
INFO  : - Path1    Queue copy to Path2                 - {path2/}a.txt
INFO  : - Path2    Queue copy to Path1                 - {path1/}b.txt
INFO  : - Path2    Queue delete                        - {path2/}old.txt
NOTICE: - WARNING  New or changed in both paths        - both.txt
"""
    s = tws.parse(text)
    assert (s["to_remote"], s["to_local"], s["delete_remote"], s["delete_local"], s["conflicts"]) == (1, 1, 1, 0, 1)
    assert s["files"]["to_remote"] == ["a.txt"] and s["too_many_deletes"] is False
    assert tws.parse("ERROR : Safety abort: too many deletes (>25%, 3 of 4)")["too_many_deletes"] is True


def test_approve_needs_a_good_recent_preview(store):
    tws.save_pair("p", "x", "/a", "r:b", check=lambda s: s)
    with pytest.raises(ValueError, match="preview first"):
        tws.approve("p")
    tws._update("p", state="previewed", preview={"ok": True, "at": time.time() - 2 * 86400})
    with pytest.raises(ValueError, match="more than a day old"):
        tws.approve("p")
    tws._update("p", preview={"ok": True, "at": time.time()})
    assert tws.approve("p")["state"] == "active"
    with pytest.raises(KeyError):
        tws.approve("nope")


def test_nothing_runs_unapproved_or_blocked(store, monkeypatch):
    tws.save_pair("p", "x", "/a", "r:b", check=lambda s: s)
    with pytest.raises(ValueError, match="approve"):
        tws.run_now("p", run=lambda *a, **k: pytest.fail("ran"))
    tws._update("p", state="active")
    monkeypatch.setattr(tws, "_blocked", lambda pair: "Writes are frozen by the ransomware guard")
    assert tws.run_now("p", run=lambda *a, **k: pytest.fail("ran"))["last_result"].startswith("Writes are frozen")


def test_run_due_and_delete(store):
    tws.save_pair("p", "x", "/a", "r:b", every_hours=1, check=lambda s: s)
    tws.save_pair("q", "y", "/a", "r:c", check=lambda s: s)
    tws._update("p", state="active", last_run=time.time() - 7200)
    tws._update("q", state="active", last_run=time.time())
    started = []
    assert tws.run_due(start=started.append) == ["p"] and started == ["p"]
    tws._RUNNING.add("p")
    assert tws.run_due(start=started.append) == []
    assert tws.delete_pair("q") and not tws.delete_pair("q")
    assert [p["id"] for p in tws.list_pairs()] == ["p"] and tws.list_pairs()[0]["running"] is True


@pytest.mark.skipif(not HAVE_RCLONE, reason="needs rclone")
def test_real_bisync_preview_first_run_and_conflict_copies(store):
    a, b = _sides(store)
    (a / "only-here.txt").write_text("nas")
    (b / "only-cloud.txt").write_text("cloud")
    _pair(store, a, b)

    p = tws.preview("photos")
    assert p["ok"] and p["first_run"] is True
    assert "only-here.txt" in p["files"]["to_remote"] and "only-cloud.txt" in p["files"]["to_local"]
    assert not (b / "only-here.txt").exists()  # a dry run changes nothing
    tws.approve("photos")

    first = tws.run_now("photos")
    assert first["last_result"] == "ok" and first["baseline"] is True
    assert (b / "only-here.txt").read_text() == "nas" and (a / "only-cloud.txt").read_text() == "cloud"

    # changed on both sides since the last run: both versions are kept
    time.sleep(1.1)
    (a / "only-here.txt").write_text("nas v2")
    (b / "only-here.txt").write_text("cloud v2")
    (b / "new-in-cloud.txt").write_text("hello")
    second = tws.run_now("photos")
    assert second["last_result"] == "ok", second.get("last_summary")
    assert second["last_summary"]["conflicts"] == 1
    names = set(os.listdir(a))
    assert {"only-here.txt..path1", "only-here.txt..path2", "new-in-cloud.txt"} <= names


@pytest.mark.skipif(not HAVE_RCLONE, reason="needs rclone")
def test_real_bisync_stops_on_a_mass_delete(store, monkeypatch):
    a, b = _sides(store)
    for i in range(8):
        (a / f"f{i}.txt").write_text(str(i))
    _pair(store, a, b, max_delete=25)
    tws.preview("photos")
    tws.approve("photos")
    assert tws.run_now("photos")["last_result"] == "ok"
    for i in range(6):  # 75% gone on this side, say by mistake or ransomware
        os.remove(a / f"f{i}.txt")
    sent = []
    monkeypatch.setattr(tws, "_notify", lambda pair, msg: sent.append(msg))
    out = tws.run_now("photos")
    assert out["state"] == "previewed" and "more than 25%" in out["last_result"] and sent
    assert len(os.listdir(b)) == 8  # nothing was deleted in the cloud


def test_blocked_checks(monkeypatch):
    from backend.services import rag_standby, ransomware_guard

    pair = {"local": "/mnt/user/photos"}
    monkeypatch.setattr(ransomware_guard, "writes_frozen", lambda: True)
    assert "frozen" in REAL_BLOCKED(pair)
    monkeypatch.setattr(ransomware_guard, "writes_frozen", lambda: False)
    monkeypatch.setattr(rag_standby, "is_backing_disk_in_standby", lambda p: True)
    assert "asleep" in REAL_BLOCKED(pair)
    monkeypatch.setattr(rag_standby, "is_backing_disk_in_standby", lambda p: False)
    assert REAL_BLOCKED(pair) is None


def test_api(client, auth_headers, store, monkeypatch):
    from backend.services import rclone_engine

    class Eng:
        def checked_location(self, spec, confine_local=True):
            return spec

    monkeypatch.setattr(rclone_engine, "get_rclone_engine", lambda: Eng())
    body = {"id": "docs", "name": "Docs", "local": "/mnt/user/docs", "remote": "gdrive:docs"}
    assert client.put("/api/sync/pairs", json=body, headers=auth_headers).json()["state"] == "new"
    assert client.put("/api/sync/pairs", json={**body, "local": "gdrive:x"}, headers=auth_headers).status_code == 400
    assert client.get("/api/sync/pairs", headers=auth_headers).json()["pairs"][0]["id"] == "docs"
    monkeypatch.setattr(tws, "preview", lambda pid: {"ok": True, "at": time.time()})
    assert client.post("/api/sync/pairs/docs/preview", headers=auth_headers).json()["ok"] is True
    assert client.post("/api/sync/pairs/docs/approve", headers=auth_headers).status_code == 400
    assert client.post("/api/sync/pairs/docs/run", headers=auth_headers).status_code == 400
    assert client.post("/api/sync/pairs/nope/approve", headers=auth_headers).status_code == 404
    assert client.delete("/api/sync/pairs/docs", headers=auth_headers).status_code == 200
    assert client.delete("/api/sync/pairs/docs", headers=auth_headers).status_code == 404

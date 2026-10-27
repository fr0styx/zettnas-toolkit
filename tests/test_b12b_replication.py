"""B12b (REL-5): replication sends what changed since the last snapshot both sides have, never
overwrites a target that isn't its replica, drains both programs' error output, keeps to the
bandwidth limit, prunes on both sides, runs on its schedule, and is watched like a backup. It is
offered only where ZettNAS manages the pools with their tools.

zfs, btrfs and ssh are stand-ins (tests/ runs anywhere): datasets and snapshots are folders and
files, a stream is a JSON line plus padding, and ssh runs the command here."""

import json
import os
import sys
from types import SimpleNamespace

import pytest

from backend.services import backup_watch
from backend.services import replication_engine as re_

FAKE_ZFS = r"""
import json, os, sys
state = os.environ["FAKE_STATE"]
args = [a for a in sys.argv[1:] if a != "--"]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(["zfs", *args]) + "\n")
ds_dir = lambda ds: os.path.join(state, "ds", ds)
snap_dir = lambda ds: os.path.join(state, "snaps", ds)
cmd = args[0]
if cmd == "list":
    ds = args[-1]
    if not os.path.isdir(ds_dir(ds)):
        sys.exit("cannot open '%s': dataset does not exist" % ds)
    if "snapshot" in args:
        d = snap_dir(ds)
        for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            print("%s@%s" % (ds, n))
    else:
        print(ds)
elif cmd == "snapshot":
    ds, name = args[-1].split("@")
    if not os.path.isdir(ds_dir(ds)):
        sys.exit("dataset does not exist")
    os.makedirs(snap_dir(ds), exist_ok=True)
    open(os.path.join(snap_dir(ds), name), "w").close()
elif cmd == "send":
    if os.environ.get("FAKE_SEND_FAIL"):
        sys.exit("send boom")
    base = args[args.index("-i") + 1].lstrip("@") if "-i" in args else ""
    ds, name = args[-1].split("@")
    sys.stderr.write("progress\n" * 50000)  # more than a pipe holds: must be read while it runs
    sys.stderr.flush()
    sys.stdout.write(json.dumps({"name": name, "base": base}) + "\n" + "x" * 5000)
elif cmd == "receive":
    data = sys.stdin.read()
    if os.environ.get("FAKE_RECV_FAIL"):
        sys.exit("cannot receive: out of space")
    head = json.loads(data.splitlines()[0])
    tgt = args[-1]
    exists = os.path.isdir(ds_dir(tgt))
    if head["base"] and not os.path.exists(os.path.join(snap_dir(tgt), head["base"])):
        sys.exit("incremental base missing")
    if not head["base"] and exists:
        sys.exit("destination exists")
    os.makedirs(ds_dir(tgt), exist_ok=True)
    os.makedirs(snap_dir(tgt), exist_ok=True)
    open(os.path.join(snap_dir(tgt), head["name"]), "w").close()
elif cmd == "destroy":
    ds, name = args[-1].split("@")
    os.remove(os.path.join(snap_dir(ds), name))
"""

FAKE_BTRFS = r"""
import json, os, shutil, sys
args = [a for a in sys.argv[1:] if a != "--"]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(["btrfs", *args]) + "\n")
if args[:2] == ["subvolume", "snapshot"]:
    os.makedirs(args[-1])
elif args[:2] == ["subvolume", "delete"]:
    shutil.rmtree(args[-1])
elif args[0] == "send":
    parent = os.path.basename(args[args.index("-p") + 1]) if "-p" in args else ""
    sys.stdout.write(json.dumps({"name": os.path.basename(args[-1]), "parent": parent}) + "\n")
elif args[0] == "receive":
    head = json.loads(sys.stdin.readline())
    if head["parent"] and not os.path.isdir(os.path.join(args[-1], head["parent"])):
        sys.exit("parent missing")
    os.makedirs(os.path.join(args[-1], head["name"]))
"""

FAKE_SSH = r"""
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(["ssh", *sys.argv[1:]]) + "\n")
os.execvp("sh", ["sh", "-c", sys.argv[-1]])
"""


class Adapter:
    def __init__(self, pools_dir, platform="generic_linux"):
        self.dir, self.platform = pools_dir, platform

    def get_platform_type(self):
        return SimpleNamespace(value=self.platform)

    def list_pools(self):
        return [
            SimpleNamespace(id="tank", name="tank", fs_type="zfs"),
            SimpleNamespace(id="data", name="data", fs_type="btrfs"),
            SimpleNamespace(id="usb", name="usb", fs_type="btrfs"),
            SimpleNamespace(id="ext", name="ext", fs_type="ext4"),
        ]

    def get_pool_path(self, pool_id):
        return os.path.join(self.dir, pool_id)


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("zfs", FAKE_ZFS), ("btrfs", FAKE_BTRFS), ("ssh", FAKE_SSH)):
        (bindir / name).write_text(f"#!{sys.executable}\n{body}")
        (bindir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log"))
    (tmp_path / "state" / "ds" / "tank" / "family").mkdir(parents=True)
    stamps = iter(f"20261027-{h:02d}00" for h in range(1, 24))
    monkeypatch.setattr(re_, "_stamp", lambda: next(stamps))
    monkeypatch.setattr(re_, "REPLICATION_JOBS_FILE", str(tmp_path / "jobs.json"))
    monkeypatch.setattr(re_, "REPLICATION_HISTORY_FILE", str(tmp_path / "history.json"))

    def calls(prog=None):
        lines = (tmp_path / "log").read_text().splitlines() if (tmp_path / "log").exists() else []
        return [c for c in map(json.loads, lines) if prog is None or c[0] == prog]

    return SimpleNamespace(calls=calls, state=tmp_path / "state", adapter=Adapter(str(tmp_path / "pools")))


def _job(**kw):
    job = {
        "id": "abcdef12-3456",
        "name": "DR",
        "source_pool": "tank",
        "source_dataset": "family",
        "target_type": "local",
        "target_pool": "backup",
        "target_dataset": "family",
        "retention_count": 2,
        "schedule": "daily",
    }
    return {**job, **kw}


def _snaps(state, ds):
    d = state / "snaps" / ds
    return sorted(os.listdir(d)) if d.is_dir() else []


def test_zfs_sends_all_then_what_changed_then_prunes_both_sides(fakes):
    job = _job()
    first = re_.replicate(job, fakes.adapter)
    assert first["snapshot"] == "zettnas-repl-abcdef12-20261027-0100" and first["bytes"] > 5000
    recv = [c for c in fakes.calls("zfs") if c[1] == "receive"][-1]
    assert recv == ["zfs", "receive", "-u", "-o", "readonly=on", "backup/family"]  # no -F, read-only
    job["last_snapshot"] = first["snapshot"]
    second = re_.replicate(job, fakes.adapter)
    send = [c for c in fakes.calls("zfs") if c[1] == "send"][-1]
    assert send == ["zfs", "send", "-i", f"@{first['snapshot']}", f"tank/family@{second['snapshot']}"]
    job["last_snapshot"] = second["snapshot"]
    third = re_.replicate(job, fakes.adapter)
    assert third["pruned"] == 2  # the first, on both sides
    for ds in ("tank/family", "backup/family"):
        assert _snaps(fakes.state, ds) == [second["snapshot"], third["snapshot"]]


def test_a_target_that_is_not_this_jobs_replica_is_never_overwritten(fakes):
    (fakes.state / "ds" / "backup" / "family").mkdir(parents=True)
    with pytest.raises(re_.ReplicationError, match="not overwritten"):
        re_.replicate(_job(), fakes.adapter)
    assert _snaps(fakes.state, "tank/family") == []  # refused before anything was made
    with pytest.raises(re_.ReplicationError, match="not overwritten"):
        re_.replicate(_job(last_snapshot="zettnas-repl-abcdef12-gone"), fakes.adapter)


def test_over_ssh_the_target_side_runs_there(fakes):
    job = _job(target_type="remote_ssh", target_host="backup.lan", target_user="zn", target_port=2222)
    re_.replicate(job, fakes.adapter)
    ssh = fakes.calls("ssh")
    assert ssh and all(
        c[1:8] == ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-p", "2222", "zn@backup.lan"] for c in ssh
    )
    assert any(c[-1] == "zfs receive -u -o readonly=on -- backup/family" for c in ssh)


def test_a_failed_receive_or_send_says_which(fakes, monkeypatch):
    monkeypatch.setenv("FAKE_RECV_FAIL", "1")
    with pytest.raises(re_.ReplicationError, match="receive failed: cannot receive: out of space"):
        re_.replicate(_job(), fakes.adapter)
    monkeypatch.delenv("FAKE_RECV_FAIL")
    monkeypatch.setenv("FAKE_SEND_FAIL", "1")
    with pytest.raises(re_.ReplicationError, match="send failed: send boom"):
        re_.replicate(_job(), fakes.adapter)


def test_the_bandwidth_limit_holds(fakes, monkeypatch):
    waits = []
    monkeypatch.setattr(re_.time, "sleep", waits.append)
    re_.replicate(_job(bandwidth_limit_kbps=1), fakes.adapter)  # ~5 KB at 1 KB/s
    assert waits and sum(waits) > 3


def test_btrfs_sends_all_then_with_the_parent(fakes):
    (fakes.state.parent / "pools" / "data" / "photos").mkdir(parents=True)
    job = _job(source_pool="data", source_dataset="photos", target_pool="usb", target_dataset="replica")
    first = re_.replicate(job, fakes.adapter)
    replica = fakes.state.parent / "pools" / "usb" / "replica"
    assert sorted(os.listdir(replica)) == [first["snapshot"]] and first["fs"] == "btrfs"
    job["last_snapshot"] = first["snapshot"]
    second = re_.replicate(job, fakes.adapter)
    send = [c for c in fakes.calls("btrfs") if c[1] == "send"][-1]
    assert send[2] == "-p" and send[3].endswith(first["snapshot"])
    job["last_snapshot"] = second["snapshot"]
    re_.replicate(job, fakes.adapter)
    assert len(os.listdir(replica)) == 2  # pruned to the newest two
    (replica / "zettnas-repl-abcdef12-20261027-0400").mkdir()
    with pytest.raises(re_.ReplicationError, match="not overwritten"):
        re_.replicate(job, fakes.adapter)


def test_only_zfs_and_btrfs_pools_replicate(fakes):
    with pytest.raises(re_.ReplicationError, match="ext4"):
        re_.replicate(_job(source_pool="ext"), fakes.adapter)
    with pytest.raises(re_.ReplicationError, match="no pool"):
        re_.replicate(_job(source_pool="nope"), fakes.adapter)


@pytest.mark.parametrize(
    "bad",
    [
        {"source_dataset": "../etc"},
        {"target_pool": "a;rm"},
        {"target_pool": ""},
        {"target_type": "remote_ssh", "target_host": "evil host"},
        {"target_type": "remote_ssh", "target_host": "nas", "target_user": "-oProxyCommand=x"},
        {"schedule": "yearly"},
    ],
)
def test_bad_settings_are_refused(bad):
    with pytest.raises(ValueError):
        re_.validate(_job(**bad))


def test_where_replication_runs(monkeypatch):
    from backend.hardware.pal import base

    monkeypatch.setattr(base, "storage_tools", lambda: {"zfs": False, "btrfs": True})
    assert re_.availability(Adapter("/x", "generic_linux")) == (True, "")
    assert "TrueNAS" in re_.availability(Adapter("/x", "truenas"))[1]
    assert "Unraid" in re_.availability(Adapter("/x", "unraid"))[1]
    assert re_.availability(Adapter("/x", "proxmox"))[0] is False
    monkeypatch.setattr(base, "storage_tools", lambda: {"zfs": False, "btrfs": False})
    monkeypatch.setattr(base, "storage_tools_problem", lambda: "")
    assert "neither" in re_.availability(Adapter("/x", "zettos"))[1]

    class Broken:
        def get_platform_type(self):
            raise RuntimeError("no adapter")

    assert re_.availability(Broken())[0] is False


def test_a_run_records_its_snapshot_and_a_failure_alerts(fakes, monkeypatch):
    engine = re_.ReplicationEngine()
    job = engine.create_job(_job(id=None, hour=3))
    alerts = []
    monkeypatch.setattr(re_, "_notify", lambda *a: alerts.append(a))
    monkeypatch.setattr(re_, "replicate", lambda j: {"snapshot": "zettnas-repl-x-1", "bytes": 10, "pruned": 0})
    engine._execute(job)
    done = engine.get_job(job["id"])
    assert done["last_status"] == "success" and done["last_snapshot"] == "zettnas-repl-x-1" and done["last_success"]

    def boom(j):
        raise re_.ReplicationError("receive failed: out of space")

    monkeypatch.setattr(re_, "replicate", boom)
    engine._execute(job)
    failed = engine.get_job(job["id"])
    assert failed["last_status"] == "error" and failed["last_snapshot"] == "zettnas-repl-x-1"  # the base stays
    assert alerts and "out of space" in alerts[0][1]
    assert [h["status"] for h in engine.get_history()] == ["success", "error"]


def test_the_schedule(fakes, monkeypatch):
    import time

    engine = re_.ReplicationEngine()
    sunday_3am = time.mktime((2026, 11, 1, 3, 0, 0, 0, 0, -1))
    monday_3am = sunday_3am + 86400
    assert engine.due({"id": "a", "schedule": "hourly", "last_run": sunday_3am - 4000}, sunday_3am)
    assert not engine.due({"id": "a", "schedule": "hourly", "last_run": sunday_3am - 60}, sunday_3am)
    assert engine.due({"id": "a", "schedule": "daily", "hour": 3}, monday_3am)
    assert not engine.due({"id": "a", "schedule": "daily", "hour": 4}, monday_3am)
    assert engine.due({"id": "a", "schedule": "weekly", "hour": 3}, sunday_3am)
    assert not engine.due({"id": "a", "schedule": "weekly", "hour": 3}, monday_3am)
    assert not engine.due({"id": "a", "schedule": "manual"}, monday_3am)
    job = engine.create_job(_job(id=None, schedule="hourly"))
    started = []
    monkeypatch.setattr(engine, "run_job_async", started.append)
    monkeypatch.setattr(re_, "availability", lambda: (False, "no tools"))
    assert engine.run_due(monday_3am) == []
    monkeypatch.setattr(re_, "availability", lambda: (True, ""))
    assert engine.run_due(monday_3am) == [job["id"]] and started == [job["id"]]


def test_failed_and_late_replication_is_watched_like_a_backup(fakes, monkeypatch):
    import time

    engine = re_.ReplicationEngine()
    monkeypatch.setattr(re_, "_REPLICATION_ENGINE", engine)
    old = time.time() - 10 * 86400
    a = engine.create_job(_job(id=None, name="Failing"))
    engine.update_job_status(a["id"], "error", error="boom")
    b = engine.create_job(_job(id=None, name="Late", schedule="daily"))
    jobs = engine.list_jobs()
    next(j for j in jobs if j["id"] == b["id"])["created_at"] = old
    re_.atomic_write_json(re_.REPLICATION_JOBS_FILE, jobs)
    engine.create_job(_job(id=None, name="By hand", schedule="manual"))
    found = {x["name"]: x["why"] for x in backup_watch.overdue_backups() if x["kind"] == "replication"}
    assert found == {"Failing": "its last run failed", "Late": "it hasn't run lately"}


def test_the_scheduler_runs_replication_and_survives_a_failure(monkeypatch):
    from backend.services import scheduler

    class Engine:
        def run_due(self, now):
            raise RuntimeError("broken")

    monkeypatch.setattr(re_, "get_replication_engine", lambda: Engine())
    scheduler._run_replication(0.0)  # logs, does not raise


def test_the_routes(client, auth_headers, fakes, monkeypatch):
    from backend.api import replication as api

    monkeypatch.setattr(re_, "_REPLICATION_ENGINE", re_.ReplicationEngine())
    monkeypatch.setattr(api, "availability", lambda: (False, "Replication runs only where ZettNAS manages the pools."))
    listed = client.get("/api/storage/replication/jobs", headers=auth_headers).json()
    assert listed["available"] is False and "manages the pools" in listed["reason"]
    body = {k: v for k, v in _job().items() if k not in ("id",)}
    assert client.post("/api/storage/replication/jobs", json=body, headers=auth_headers).status_code == 409
    monkeypatch.setattr(api, "availability", lambda: (True, ""))
    created = client.post("/api/storage/replication/jobs", json=body, headers=auth_headers).json()["job"]
    assert created["hour"] == 1 and created["last_snapshot"] is None
    bad = {**body, "target_type": "remote_ssh"}
    assert client.post("/api/storage/replication/jobs", json=bad, headers=auth_headers).status_code == 400
    monkeypatch.setattr(re_.ReplicationEngine, "run_job_async", lambda self, jid: {"status": "started", "job_id": jid})
    assert (
        client.post(f"/api/storage/replication/jobs/{created['id']}/run", headers=auth_headers).json()["status"]
        == "started"
    )

    def missing(self, jid):
        raise ValueError("Job nope not found")

    monkeypatch.setattr(re_.ReplicationEngine, "run_job_async", missing)
    assert client.post("/api/storage/replication/jobs/nope/run", headers=auth_headers).status_code == 404

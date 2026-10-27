"""B12b (REL-20): backups hold consistent databases and VMs. Databases whose data a backup reads
write a dump first; a running VM is paused while its disks are copied and resumed after."""

import json
import os
import tarfile
from types import SimpleNamespace

import pytest

from backend.services import app_backup, backup_engine, backup_hooks, docker_client
from backend.services import offsite_backup as ob


def _frame(text, stream=2):
    data = text.encode()
    return bytes([stream, 0, 0, 0]) + len(data).to_bytes(4, "big") + data


@pytest.fixture
def docker(tmp_path, monkeypatch):
    """A Docker stand-in: a postgres and a redis with data inside the backup, a redis and an
    nginx elsewhere, a mariadb on a named volume."""
    appdata = tmp_path / "appdata"
    (appdata / "immich" / "postgres").mkdir(parents=True)
    calls = []
    state = {"exit": 0, "output": b""}
    containers = [
        {
            "Id": "pg1",
            "Names": ["/immich_postgres"],
            "Image": "ghcr.io/immich-app/postgres:14",
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(appdata / "immich" / "postgres"),
                    "Destination": "/var/lib/postgresql/data",
                }
            ],
        },
        {
            "Id": "rd1",
            "Names": ["/immich_redis"],
            "Image": "docker.io/valkey/valkey:8",
            "Mounts": [{"Type": "bind", "Source": str(appdata / "immich" / "redis"), "Destination": "/data"}],
        },
        {
            "Id": "rd2",
            "Names": ["/other_redis"],
            "Image": "redis:7",
            "Mounts": [{"Type": "bind", "Source": "/elsewhere", "Destination": "/data"}],
        },
        {
            "Id": "web",
            "Names": ["/nginx"],
            "Image": "nginx",
            "Mounts": [{"Type": "bind", "Source": str(appdata / "www"), "Destination": "/usr/share/nginx"}],
        },
        {
            "Id": "db2",
            "Names": ["/mariadb"],
            "Image": "mariadb:11",
            "Mounts": [{"Type": "volume", "Source": "/var/lib/docker/volumes/x", "Destination": "/var/lib/mysql"}],
        },
    ]

    def request(method, path, body=None, timeout=15.0, headers=None):
        calls.append((method, path, body))
        if path == "/containers/json":
            return 200, containers
        if path.endswith("/exec"):
            return 201, {"Id": f"exec-{path.split('/')[2]}"}
        if path.startswith("/exec/") and path.endswith("/json"):
            return 200, {"ExitCode": state["exit"]}
        return 404, {}

    def raw_request(method, path, body=None, timeout=15.0, headers=None):
        calls.append((method, path, json.loads(body) if body else None))
        return 200, state["output"]

    monkeypatch.setattr(docker_client, "request", request)
    monkeypatch.setattr(docker_client, "raw_request", raw_request)
    return SimpleNamespace(appdata=appdata, calls=calls, state=state)


def test_databases_in_the_backup_write_a_dump_first(docker):
    found = {t["name"]: t for t in backup_hooks.targets([str(docker.appdata)])}
    assert set(found) == {"immich_postgres", "immich_redis"}  # not the others
    assert found["immich_postgres"]["kind"] == "postgres" and found["immich_redis"]["kind"] == "redis"
    results = backup_hooks.run_dumps([str(docker.appdata)])
    assert [r["ok"] for r in results] == [True, True]
    exec_pg = next(b for m, p, b in docker.calls if p == "/containers/pg1/exec")
    assert exec_pg["Env"] == ["D=/var/lib/postgresql/data"] and exec_pg["Cmd"][:2] == ["sh", "-c"]
    assert "pg_dumpall" in exec_pg["Cmd"][2] and '.zettnas-dump.sql.part" && mv' in exec_pg["Cmd"][2]
    assert ("POST", "/exec/exec-pg1/start", {"Detach": False, "Tty": False}) in docker.calls


def test_a_failed_dump_is_reported_and_the_backup_goes_on(docker):
    docker.state.update(exit=1, output=_frame("pg_dumpall: error: connection refused\n"))
    results = backup_hooks.run_dumps([str(docker.appdata / "immich" / "postgres")])
    assert results == [
        {"name": "immich_postgres", "kind": "postgres", "ok": False, "error": "pg_dumpall: error: connection refused"}
    ]


def test_without_docker_there_is_nothing_to_dump(monkeypatch):
    def gone(*a, **k):
        raise docker_client.DockerUnavailable(503, "no socket")

    monkeypatch.setattr(docker_client, "request", gone)
    assert backup_hooks.run_dumps(["/mnt/user"]) == []
    monkeypatch.setattr(docker_client, "request", lambda *a, **k: (500, {"message": "boom"}))
    assert backup_hooks.targets(["/mnt/user"]) == []


def test_a_dump_that_cannot_start_says_so(docker, monkeypatch):
    monkeypatch.setattr(
        docker_client,
        "request",
        lambda m, p, b=None, **k: (
            (
                200,
                [
                    {
                        "Id": "x",
                        "Image": "postgres",
                        "Names": ["/pg"],
                        "Mounts": [{"Type": "bind", "Source": "/mnt/a", "Destination": "/d"}],
                    }
                ],
            )
            if p == "/containers/json"
            else (409, {"message": "not running"})
        ),
    )
    assert backup_hooks.run_dumps(["/mnt/a"])[0]["error"] == "could not start the dump (409)"


def test_exec_output_is_read_with_or_without_frames():
    assert backup_hooks._demux(_frame("one\n", 1) + _frame("two")) == "one\ntwo"
    assert backup_hooks._demux(b"plain text\n") == "plain text"


def test_an_offsite_backup_dumps_its_databases_first(tmp_path, monkeypatch):
    from backend import config

    storage = tmp_path / "storage"
    (storage / "appdata").mkdir(parents=True)
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(storage)])
    monkeypatch.setattr(ob, "REPOS_FILE", str(tmp_path / "repos.json"))
    monkeypatch.setattr(ob, "KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    ob.save_repo("usb", "USB", str(storage / "usb"), [str(storage / "appdata")], hour=None)
    ob._update("usb", initialized=True)
    order = []
    monkeypatch.setattr(
        backup_hooks, "run_dumps", lambda paths: order.append(("dumps", paths)) or [{"name": "pg", "ok": True}]
    )
    monkeypatch.setattr(ob, "_unlock", lambda repo: order.append(("unlock",)))
    monkeypatch.setattr(ob, "_run", lambda repo, args, **kw: order.append(("backup",)) or (0, ""))
    monkeypatch.setattr(ob, "run_restic", lambda *a, **k: "")
    assert ob.backup("usb")["dumps"] == [{"name": "pg", "ok": True}]
    assert order[0] == ("dumps", [str(storage / "appdata")]) and order[1:] == [("unlock",), ("backup",)]


def test_a_copy_job_dumps_the_folder_it_reads(tmp_path, monkeypatch):
    (tmp_path / "pool" / "@shares" / "appdata").mkdir(parents=True)
    pal = SimpleNamespace(get_pool_path=lambda pool_id: str(tmp_path / "pool"))
    seen = []
    monkeypatch.setattr(backup_hooks, "run_dumps", lambda paths: seen.append(paths) or [])
    assert backup_engine._dump_databases(pal, "tank", "appdata") == []
    assert seen == [[str(tmp_path / "pool" / "@shares" / "appdata")]]

    def broken(pool_id):
        raise RuntimeError("no pool")

    assert backup_engine._dump_databases(SimpleNamespace(get_pool_path=broken), "tank", "") == []


@pytest.fixture
def vm(tmp_path, monkeypatch):
    from backend.services import vm_qemu

    vm_dir = tmp_path / "vms" / "vm1"
    vm_dir.mkdir(parents=True)
    (vm_dir / "disk.qcow2").write_bytes(b"disk")
    (tmp_path / "vms.json").write_text(json.dumps([{"id": "vm1", "name": "win", "vm_dir": str(vm_dir)}]))
    monkeypatch.setattr(app_backup, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_backup, "get_vm_backup_dir", lambda name: str(tmp_path / "out"))
    monkeypatch.setattr(app_backup, "save_app_backup_record", lambda record: None)
    (tmp_path / "out").mkdir()
    qmp = SimpleNamespace(alive=True, running=True, stop={"return": {}}, sent=[])

    def command(vm_id, cmd, arguments=None, timeout=2.5):
        qmp.sent.append(cmd)
        if cmd == "query-status":
            return {"return": {"running": qmp.running, "status": "running" if qmp.running else "paused"}}
        return qmp.stop if cmd == "stop" else {"return": {}}

    monkeypatch.setattr(vm_qemu, "_is_qemu_process_alive", lambda vm_id: qmp.alive)
    monkeypatch.setattr(vm_qemu, "_qmp_command", command)
    return SimpleNamespace(qmp=qmp, out=tmp_path / "out")


def _manifest(record):
    with tarfile.open(record["filepath"]) as tar:
        return json.load(tar.extractfile("manifest.json"))


def test_a_running_vm_is_paused_while_its_disks_are_copied(vm):
    record = app_backup.create_vm_backup("vm1")
    assert vm.qmp.sent == ["query-status", "stop", "cont"] and _manifest(record)["consistency"] == "paused"


def test_a_vm_that_cannot_be_paused_is_not_copied(vm):
    vm.qmp.stop = {"error": {"class": "GenericError", "desc": "migration in progress"}}
    with pytest.raises(RuntimeError, match="could not be paused"):
        app_backup.create_vm_backup("vm1")
    assert os.listdir(vm.out) == [] and "cont" not in vm.qmp.sent


def test_a_vm_paused_by_its_owner_stays_paused(vm):
    vm.qmp.running = False
    record = app_backup.create_vm_backup("vm1")
    assert vm.qmp.sent == ["query-status"] and _manifest(record)["consistency"] == "paused"


def test_a_stopped_vm_is_copied_as_it_is(vm):
    vm.qmp.alive = False
    assert _manifest(app_backup.create_vm_backup("vm1"))["consistency"] == "stopped" and vm.qmp.sent == []


def test_the_vm_is_resumed_even_when_the_copy_fails(vm, monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(app_backup.tarfile, "open", broken)
    with pytest.raises(OSError):
        app_backup.create_vm_backup("vm1")
    assert vm.qmp.sent[-1] == "cont"


def test_a_vm_that_does_not_resume_is_logged(vm, monkeypatch):
    from backend.services import vm_qemu

    errors = []
    monkeypatch.setattr(vm_qemu, "_qmp_command", lambda *a, **k: {"error": {"desc": "gone"}})
    monkeypatch.setattr(app_backup.logger, "error", errors.append)
    app_backup._resume_vm("vm1")
    assert "could not be resumed" in errors[0]


def test_a_monitor_that_does_not_answer_counts_as_cannot_pause(vm, monkeypatch):
    from backend.services import vm_qemu

    def timeout(*a, **k):
        raise TimeoutError("no answer")

    monkeypatch.setattr(vm_qemu, "_qmp_command", timeout)
    with pytest.raises(RuntimeError, match="could not be paused"):
        app_backup._pause_vm("vm1")

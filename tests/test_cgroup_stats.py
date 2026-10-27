"""Container stats from the kernel's cgroup and /proc files (PERF-4), with dockerd as the fallback.

The trees below are built the way the kernel lays them out: cgroup v2 with Docker's cgroupfs
driver, v2 with the systemd driver, and v1; ids and numbers are made up.
"""

import pytest

from backend.hardware import cgroup_stats as cg
from backend.hardware import docker_stats as ds

CID = "a" * 64
OTHER = "b" * 64


@pytest.fixture(autouse=True)
def _clean():
    cg._LAYOUT.clear()
    cg._PREV.clear()
    cg._HOST_MEM.clear()
    yield
    cg._LAYOUT.clear()
    cg._PREV.clear()
    cg._HOST_MEM.clear()


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def proc_tree(tmp_path, pid=4242, cid=CID, rx=1000, tx=500):
    proc = tmp_path / "proc"
    put(proc / "meminfo", "MemTotal:       16384000 kB\nMemFree:  100 kB\n")
    put(proc / str(pid) / "cgroup", f"0::/../{cid}\n")
    put(
        proc / str(pid) / "net" / "dev",
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
        "    lo:  9999 10 0 0 0 0 0 0  9999 10 0 0 0 0 0 0\n"
        f"  eth0:  {rx} 12 0 0 0 0 0 0  {tx} 8 0 0 0 0 0 0\n",
    )
    return str(proc)


def v2(tmp_path, where="docker", usec=1_000_000, current=50_000_000, inactive=10_000_000, limit="max"):
    root = tmp_path / "cgroup"
    d = root / "docker" / CID if where == "docker" else root / "system.slice" / f"docker-{CID}.scope"
    put(d / "cpu.stat", f"usage_usec {usec}\nuser_usec 1\nsystem_usec 1\n")
    put(d / "memory.current", f"{current}\n")
    put(d / "memory.max", f"{limit}\n")
    put(d / "memory.stat", f"anon 1\nfile 2\ninactive_file {inactive}\n")
    return str(root), d


def test_v2_cgroupfs_and_systemd_layouts(tmp_path):
    proc = proc_tree(tmp_path)
    for where in ("docker", "systemd"):
        cg._LAYOUT.clear()
        root, _ = v2(tmp_path / where, where=where)
        m = cg.cpu_and_memory(CID, root, proc)
        # memory leaves out the page cache the kernel can drop; no limit means the host's memory
        assert m == {"cpu_usec": 1_000_000, "mem_used": 40_000_000, "mem_limit": 16384000 * 1024}


def test_v1_layout_and_its_huge_no_limit(tmp_path):
    root = tmp_path / "cgroup"
    put(root / "cpu,cpuacct" / "docker" / CID / "cpuacct.usage", "3000000000\n")
    mem = root / "memory" / "docker" / CID
    put(mem / "memory.usage_in_bytes", "80000000\n")
    put(mem / "memory.limit_in_bytes", "9223372036854771712\n")
    put(mem / "memory.stat", "cache 5\ntotal_inactive_file 30000000\n")
    m = cg.cpu_and_memory(CID, str(root), proc_tree(tmp_path))
    assert m == {"cpu_usec": 3_000_000, "mem_used": 50_000_000, "mem_limit": 16384000 * 1024}


def test_a_set_limit_is_kept(tmp_path):
    root, _ = v2(tmp_path, limit="104857600")
    assert cg.cpu_and_memory(CID, root, proc_tree(tmp_path))["mem_limit"] == 104857600


def test_an_unknown_layout_or_a_vanished_container_says_none(tmp_path):
    assert cg.cpu_and_memory(CID, str(tmp_path / "nothing"), proc_tree(tmp_path)) is None
    root, d = v2(tmp_path)
    proc = proc_tree(tmp_path)
    assert cg.cpu_and_memory(CID, root, proc) is not None
    (d / "memory.current").unlink()
    assert cg.cpu_and_memory(CID, root, proc) is None
    assert CID not in cg._LAYOUT  # looked up again next time


def test_network_counts_every_interface_but_loopback_and_checks_the_process(tmp_path):
    proc = proc_tree(tmp_path)
    assert cg.network(4242, CID, proc) == (1000, 500)
    assert cg.network(4242, OTHER, proc) is None  # the number belongs to another container now
    assert cg.network(0, CID, proc) is None
    put(tmp_path / "proc" / "77" / "cgroup", "0::/\n")  # our own container, seen from inside it
    assert cg.owns(77, CID, proc)


def test_cpu_percent_needs_two_samples():
    assert cg.cpu_percent(CID, 1_000_000, now=100.0) is None
    assert cg.cpu_percent(CID, 1_500_000, now=102.0) == 25.0  # 0.5 s of CPU in 2 s
    assert cg.cpu_percent(CID, 100, now=104.0) is None  # the counter restarted


def test_telemetry_matches_what_docker_stats_gives(tmp_path):
    root, d = v2(tmp_path)
    proc = proc_tree(tmp_path)
    assert cg.telemetry(CID, 4242, False, root, proc) is None  # first round: dockerd answers
    put(d / "cpu.stat", "usage_usec 3000000\n")
    cg._PREV[CID] = (cg._PREV[CID][0] - 4.0, 1_000_000)
    t = cg.telemetry(CID, 4242, False, root, proc)
    assert t["source"] == "cgroup" and t["net_rx"] == 1000 and t["net_tx"] == 500
    assert 49.0 <= t["cpu_pct"] <= 51.0 and t["mem_used"] == 40_000_000
    assert set(t) >= {"cpu_pct", "mem_used", "mem_limit", "mem_pct", "net_rx", "net_tx", "updated_at"}
    host = cg.telemetry(CID, 0, True, root, proc)  # host network: no counters of its own
    assert host["net_rx"] == 0 and host["net_tx"] == 0
    cg.forget(set())
    assert not cg._PREV and not cg._LAYOUT


def test_docker_stats_uses_the_kernel_first_and_dockerd_otherwise(monkeypatch):
    calls = []
    inspect = {"State": {"Pid": 4242}, "HostConfig": {"NetworkMode": "bridge"}}
    monkeypatch.setattr(ds, "_fetch_container_inspect", lambda cid, conn=None: inspect)
    monkeypatch.setattr(cg, "owns", lambda pid, cid, proc=None: True)
    monkeypatch.setattr(
        cg, "telemetry", lambda cid, pid, host: calls.append((cid, pid, host)) or {"cpu_pct": 1.0, "source": "cgroup"}
    )
    assert ds._fetch_container_telemetry(CID)["source"] == "cgroup"
    assert calls == [(CID, 4242, False)]
    # unreadable: dockerd answers (here: no socket, so nothing)
    monkeypatch.setattr(cg, "telemetry", lambda cid, pid, host: None)
    monkeypatch.setattr(ds, "docker_sock", lambda: "/nonexistent.sock")
    assert ds._fetch_container_telemetry(CID) == {}


def test_a_restarted_container_gets_its_new_process(monkeypatch):
    pids = iter([111, 222])
    monkeypatch.setattr(ds, "_fetch_container_inspect", lambda cid, conn=None: {"State": {"Pid": next(pids)}})
    monkeypatch.setattr(cg, "owns", lambda pid, cid, proc=None: pid == 222)
    seen = []
    monkeypatch.setattr(cg, "telemetry", lambda cid, pid, host: seen.append(pid) or None)
    ds._kernel_telemetry(CID)
    assert seen == [222]

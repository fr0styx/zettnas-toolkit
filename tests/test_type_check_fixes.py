"""Crash paths the type check found (pyright ratchet): each used to raise instead of reporting."""

import io
import json
import zipfile

from backend.api import diagnostics
from backend.hardware import storage_diagnostics


def _fake_collectors(monkeypatch, disks):
    import backend.hardware.kernel_telemetry as kt
    import backend.services.docker_diagnostics as dd

    monkeypatch.setattr(
        storage_diagnostics, "collect_storage_diagnostics", lambda: {"live_disk_telemetry": disks, "pal_storage": {}}
    )
    monkeypatch.setattr(kt, "collect_kernel_telemetry", lambda: {})
    monkeypatch.setattr(dd, "collect_docker_diagnostics", lambda: {"containers_summary": {"troubled_names": []}})


def test_a_failing_drive_without_a_name_is_reported_not_a_crash(monkeypatch):
    disks = [{"smart_status": "failing"}, {"name": "sdb", "smart": {"status": "degraded"}}]
    _fake_collectors(monkeypatch, disks)
    data = diagnostics._build_bundle_sync(None)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = "\n".join(
            z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith((".json", ".md", ".txt"))
        )
    assert "unnamed drive" in text and "sdb" in text


def test_pools_and_shares_as_plain_dicts(monkeypatch):
    class Caps:
        def model_dump(self):
            return {"snapshots": True}

    class Adapter:
        def get_capabilities(self):
            return Caps()

        def list_pools(self):
            return [{"id": "pool1", "name": "pool1"}]

        def list_shares(self):
            return [{"name": "media", "path": "/mnt/pool1/media"}]

        def list_snapshots(self, pid):
            return [{"name": "daily", "pool": pid}]

        def is_storage_busy(self):
            # without it the storage section was an error, and the names were found only in
            # whatever other sections an earlier test left behind (random-order nightly)
            return False

    monkeypatch.setattr(storage_diagnostics, "get_storage_platform", lambda: Adapter())
    out = storage_diagnostics.collect_storage_diagnostics()
    pal = out["pal_storage"]
    assert "error" not in pal, pal
    assert pal["pools"][0]["id"] == "pool1" and pal["shares"][0]["name"] == "media"
    assert "daily" in json.dumps(out, default=str)


def test_fan_registers_not_mapped_read_and_write_nothing(monkeypatch, tmp_path):
    """The register map is checked where it is used: unmapped means no readings and no writes."""
    from backend.hardware.fans import ZettlabMmioFanController

    ctl = ZettlabMmioFanController(dev_mem_path=str(tmp_path / "mem"))
    monkeypatch.setattr(ctl, "_ensure_mapped", lambda: True)
    ctl._mm = None
    assert ctl.read_fans() == []
    assert ctl.write_pwm(1, 128) is False
    assert ctl.read_raw_registers() is None


def test_qmp_without_a_connection_reports_instead_of_crashing(monkeypatch):
    import asyncio

    import pytest

    from backend.services.vm_engine import PersistentQmpClient

    client = PersistentQmpClient("vm-1", "/nonexistent.sock")

    async def no_connect(timeout=2.5):
        return None

    async def scenario():
        with pytest.raises(ConnectionError):
            await client._read_json()
        monkeypatch.setattr(client, "connect", no_connect)
        return await client.execute("query-status")

    assert asyncio.run(scenario()) == {"error": "QMP not connected"}

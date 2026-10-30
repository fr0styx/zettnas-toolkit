"""NPERF-6: in the scrub hour each pool is looked at once, not every minute."""

import time
from types import SimpleNamespace

from backend.services import protection_jobs as pj


def test_each_pool_is_looked_at_once_an_hour(tmp_path, monkeypatch):
    looked = []
    pool = SimpleNamespace(id="tank", name="tank", fs_type="zfs")
    adapter = SimpleNamespace(
        get_capabilities=lambda: SimpleNamespace(can_trigger_scrub=True),
        is_storage_busy=lambda: False,
        list_pools=lambda: [pool],
        scrub_result=lambda p: looked.append(p.id) or {"finished_at": time.time(), "state": "finished"},
        trigger_scrub=lambda *a: {"status": "started"},
    )
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: adapter)
    monkeypatch.setattr(pj, "_platform", lambda a: next(iter(pj.OWNED)))
    monkeypatch.setattr(pj, "_scrub_file", lambda: str(tmp_path / "scrubs.json"))
    monkeypatch.setattr(pj, "scrub_enabled", lambda p, s: True)
    monkeypatch.setattr(pj, "_scrub_looked", {})
    t = time.mktime((2026, 10, 30, pj.SCRUB_HOUR, 5, 0, 0, 0, -1))
    assert pj.run_scrubs_due(t) == []  # scrubbed recently: not due
    assert pj.run_scrubs_due(t + 60) == []
    assert looked == ["tank"]  # once in the hour
    pj.run_scrubs_due(t + 86400)
    assert looked == ["tank", "tank"]  # the next day's scrub hour looks again

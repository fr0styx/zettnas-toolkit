"""AI-3: watched folders on awake disks are re-read on a schedule; sleeping disks never are."""

from types import SimpleNamespace


def _fake_engine(watched, synced):
    return SimpleNamespace(
        _ensure_schema=lambda: None,
        get_config=lambda: {
            "enabled": True,
            "auto_learn_on_spinup": True,
            "watched_paths": watched,
            "excluded_paths": [],
        },
        _known_sleeping_devs=set(),
        is_within_learning_schedule=lambda: (True, ""),
        _is_indexing=False,
        _sync_state="idle",
        get_deferred_queue=lambda: [],
        _last_spinup_rescan={},
        remove_deferred_path=lambda p: 0,
        start_background_sync=lambda **kw: synced.append(kw["paths"]) or {"ok": True},
        _sync_progress={},
    )


def test_awake_folders_are_rescanned_on_schedule_and_sleeping_ones_never(monkeypatch):
    from backend.services import rag_engine_learning as learning

    monkeypatch.setattr(learning.rag_standby, "get_sleeping_disks_list", lambda: ["sdb"])
    devs = {"/mnt/cache/photos": "nvme0n1", "/mnt/disk1/films": "sdb"}
    monkeypatch.setattr(learning.rag_standby, "resolve_path_backing_dev", lambda p: devs.get(p))
    monkeypatch.setattr(learning.rag_standby, "is_backing_disk_in_standby", lambda d: d == "sdb")
    monkeypatch.setattr(learning, "_is_solid_state", lambda d: d == "nvme0n1")
    synced = []
    eng = _fake_engine(list(devs), synced)
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(learning.time, "time", lambda: clock["t"])

    mixin = next(
        c for c in vars(learning).values() if isinstance(c, type) and hasattr(c, "check_and_trigger_spinup_auto_learn")
    )
    run = mixin.check_and_trigger_spinup_auto_learn

    assert run(eng)["triggered"] is False  # nothing right after start
    clock["t"] += learning.FRESH_RESCAN_SSD_SECS + 1
    assert run(eng)["triggered"] is True and synced[-1] == ["/mnt/cache/photos"]
    clock["t"] += 60
    assert run(eng)["triggered"] is False  # not again within the hour
    assert all("/mnt/disk1/films" not in p for p in synced)  # the sleeping disk is never touched

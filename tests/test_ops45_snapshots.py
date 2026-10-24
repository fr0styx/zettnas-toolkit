"""Snapshots for every new build, the last Stable kept, rollback images protected (OPS-4, OPS-5)."""

import json
import os
import time

from backend.services import data_snapshot as ds


def _data(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "settings.json").write_text("{}")
    return str(d)


def test_a_new_build_is_snapshotted_once_before_it_runs(tmp_path):
    data = _data(tmp_path)
    assert ds.snapshot_if_build_changed(data, "1.9.4+aaaaaaa") is None  # first run: nothing to protect
    assert ds.snapshot_if_build_changed(data, "1.9.4+aaaaaaa") is None  # same build
    snap = ds.snapshot_if_build_changed(data, "1.9.4+bbbbbbb")  # e.g. updated from the Unraid tab
    assert snap and os.path.isfile(os.path.join(snap, "settings.json"))
    with open(os.path.join(snap, ds.MANIFEST)) as f:
        meta = json.load(f)
    assert meta["kind"] == "startup" and meta["from_build"] == "1.9.4+aaaaaaa" and meta["to_build"] == "1.9.4+bbbbbbb"
    assert os.path.basename(snap).endswith("from-1.9.4_aaaaaaa")


def test_no_second_snapshot_after_an_in_app_update(tmp_path):
    data = _data(tmp_path)
    ds.snapshot_if_build_changed(data, "1.9.4+aaaaaaa")
    ds.take_snapshot(data, label="from-1.9.4+aaaaaaa", extra={"kind": "update", "to_build": "1.9.5+ccccccc"})
    before = len(ds.list_snapshots(data))
    assert ds.snapshot_if_build_changed(data, "1.9.5+ccccccc") is None
    assert len(ds.list_snapshots(data)) == before


def test_the_last_stable_snapshot_outlives_newer_ones(tmp_path, monkeypatch):
    data = _data(tmp_path)
    clock = {"t": time.time()}
    monkeypatch.setattr(ds.time, "strftime", lambda fmt, *a: f"2026{int(clock['t']):012d}")
    ds.take_snapshot(data, label="stable", extra={"stable": True})
    for i in range(5):
        clock["t"] += 1
        ds.take_snapshot(data, label=f"edge{i}", extra={"stable": False})
    labels = [s["label"] for s in ds.list_snapshots(data)]
    assert "stable" in labels and len(labels) == ds.KEEP + 1


def test_stable_tags():
    assert ds.is_stable_tag("ghcr.io/fr0styx/zettnas-toolkit:latest")
    assert ds.is_stable_tag("ghcr.io/fr0styx/zettnas-toolkit:1.9.4-core")
    assert ds.is_stable_tag("ghcr.io/fr0styx/zettnas-toolkit")
    assert not ds.is_stable_tag("ghcr.io/fr0styx/zettnas-toolkit:edge")
    assert not ds.is_stable_tag("ghcr.io/fr0styx/zettnas-toolkit:sha-abc1234")


def test_rollback_image_is_tagged_and_stale_tags_dropped(tmp_path, monkeypatch):
    from backend.services import self_updater as su

    data = _data(tmp_path)
    ds.take_snapshot(data, label="x", extra={"from_build": "1.9.4+aaaaaaa"})
    calls = []

    def fake(method, path, body=None, timeout=30.0):
        calls.append((method, path))
        if path.startswith("/images/json"):
            return 200, [{"RepoTags": [f"{su.ROLLBACK_REPO}:1.9.4_aaaaaaa", f"{su.ROLLBACK_REPO}:1.9.1_old0000"]}]
        return 201, {}

    monkeypatch.setattr(su, "_docker_request", fake)
    su._protect_rollback_image("sha256:abc", "1.9.4+aaaaaaa", data)
    assert ("POST", f"/images/sha256:abc/tag?repo={su.ROLLBACK_REPO}&tag=1.9.4_aaaaaaa") in calls
    assert ("DELETE", f"/images/{su.ROLLBACK_REPO}:1.9.1_old0000?noprune=1") in calls
    assert ("DELETE", f"/images/{su.ROLLBACK_REPO}:1.9.4_aaaaaaa?noprune=1") not in calls

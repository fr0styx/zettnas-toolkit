"""M4/M5: a simulated mass rename freezes writes, snapshots, blocks the source and alerts."""

import json

import pytest

from backend.services import ip_block
from backend.services import ransomware_guard as rg


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(ip_block, "STORE", str(tmp_path / "ip_blocks.json"))
    ip_block._reset_for_tests()
    monkeypatch.setattr(ip_block, "_sync_samba", lambda: None)
    guard = rg.RansomwareGuard(state_file=str(tmp_path / "guard.json"))
    monkeypatch.setattr(rg, "_GUARD", guard)
    yield guard
    ip_block._reset_for_tests()


def test_mass_rename_triggers_freeze_snapshot_block_and_alert(_clean, monkeypatch):
    guard = _clean
    alerts, freezes = [], []
    monkeypatch.setattr(rg, "_apply_share_freeze", lambda f: freezes.append(f))
    monkeypatch.setattr(rg, "_snapshot_pools", lambda: [{"pool": "tank", "name": "ransomware-guard-x", "ok": True}])
    monkeypatch.setattr(
        "backend.services.notifications.send_notification",
        lambda title, msg="", **k: alerts.append((title, msg, k.get("level"))),
    )
    for i in range(149):
        assert not guard.observe(
            "rename",
            f"/mnt/user/docs/f{i}.docx",
            user="bob",
            ip="192.168.1.50",
            new_path=f"/mnt/user/docs/f{i}.docx.bak",
        )
    assert guard.observe("rename", "/mnt/user/docs/last.docx", user="bob", ip="192.168.1.50")
    assert guard.frozen and freezes == [True]
    assert guard.status()["snapshots"][0]["name"] == "ransomware-guard-x"
    assert ip_block.is_blocked("192.168.1.50")
    assert alerts and alerts[0][2] == "critical" and "192.168.1.50" in alerts[0][1]
    guard.unfreeze(by="admin")
    assert not guard.frozen and freezes == [True, False]


def test_ransom_extensions_trigger_sooner(_clean, monkeypatch):
    guard = _clean
    hits = []
    guard._react = lambda reason, src: hits.append(reason)
    for i in range(10):
        guard.observe("rename", f"/s/a{i}.jpg", user="eve", new_path=f"/s/a{i}.jpg.lockbit")
    assert hits and "ransomware extensions" in hits[0]
    assert guard.is_suspicious_name("HOW_TO_DECRYPT_FILES.txt")
    assert not guard.is_suspicious_name("holiday.jpg") and not guard.is_suspicious_name("readme.md")


def test_guard_file_change_is_detected(_clean, tmp_path):
    guard = _clean
    hits = []
    guard._react = lambda reason, src: hits.append(src["example"])
    share = tmp_path / "share"
    share.mkdir()
    guard.state["canaries"] = True
    assert guard.place_canaries([str(share)]) == 1
    assert not guard.check_canaries()
    (share / rg.CANARY_NAME).write_bytes(b"encrypted!!")
    assert guard.check_canaries() and hits[0].endswith(rg.CANARY_NAME)


def test_frozen_writes_are_refused_but_reads_work(client, auth_headers, _clean):
    h = auth_headers
    _clean.state["frozen"] = True
    r = client.post("/api/fs/rename", json={"path": "/x", "new_name": "y"}, headers=h)
    assert r.status_code == 423
    assert client.request("MOVE", "/webdav/a.txt", headers={"Destination": "/webdav/b.txt"}).status_code == 423
    assert client.post("/api/fs/checksum", json={"path": "/x"}, headers=h).status_code != 423
    assert client.get("/api/security/ransomware", headers=h).json()["frozen"] is True
    assert client.post("/api/security/ransomware/unfreeze", headers=h).status_code == 200
    assert client.post("/api/fs/rename", json={"path": "/x", "new_name": "y"}, headers=h).status_code != 423


def test_repeated_failed_logins_block_the_address(monkeypatch):
    for _ in range(ip_block.FAIL_LIMIT - 1):
        assert not ip_block.record_auth_failure("203.0.113.9")
    assert ip_block.record_auth_failure("203.0.113.9")
    assert ip_block.is_blocked("203.0.113.9")
    assert not ip_block.block("127.0.0.1", "x")
    monkeypatch.setenv("ZETTNAS_TRUSTED_IPS", "10.0.0.0/8")
    assert not ip_block.block("10.1.2.3", "x")
    assert ip_block.unblock("203.0.113.9") and not ip_block.is_blocked("203.0.113.9")


def test_samba_config_goes_read_only_and_denies_blocked_hosts(_clean, tmp_path, monkeypatch, paths):
    from backend.services import samba_engine

    monkeypatch.setattr(samba_engine, "SAMBA_CONF_FILE", str(tmp_path / "smb.conf"))
    eng = samba_engine.SambaEngine.__new__(samba_engine.SambaEngine)
    eng._shares = {"docs": samba_engine.SambaShareConfig(name="docs", path=paths["pool"])}
    ip_block.block("198.51.100.7", "test")
    _clean.state["frozen"] = True
    conf = eng.generate_and_save_conf()
    assert "hosts deny = 198.51.100.7" in conf and "read only = yes" in conf
    _clean.state["frozen"] = False
    assert "read only = no" in eng.generate_and_save_conf()
    json.dumps(ip_block.list_blocks())

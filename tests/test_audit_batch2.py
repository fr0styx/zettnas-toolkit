"""
Tests for Batch 2 Architecture & Performance Hardening:
- Backup Engine generation, extraction, and zip-slip safety
- Fan state tracker eviction
- Static file serving and mode=lcd HTML transformation
- FastAPI backend.main entrypoint integration
"""

import io
import os
import zipfile
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.backup_engine import generate_backup_zip_stream, restore_backup_archive
from backend.hardware.fans import cleanup_stale_fan_trackers
from backend.state import Z_STATE


def test_backup_engine_generation_and_exclusion(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.backup_engine.DATA_DIR", str(tmp_path))

    # Create dummy files
    (tmp_path / "config.json").write_text('{"setting": 1}')
    (tmp_path / "history.db").write_text("dummy database")
    (tmp_path / "history.db-wal").write_text("dummy wal")
    (tmp_path / "sessions.json").write_text('{"token": "secret"}')

    buf = generate_backup_zip_stream()
    with zipfile.ZipFile(buf, "r") as z:
        names = z.namelist()
        assert "config.json" in names
        assert "history.db" not in names
        assert "history.db-wal" not in names
        assert "sessions.json" not in names


def test_backup_engine_safe_restoration(tmp_path, monkeypatch):
    restore_target = tmp_path / "restore_target"
    restore_target.mkdir()
    monkeypatch.setattr("backend.services.backup_engine.DATA_DIR", str(restore_target))

    # Create in-memory zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("led_state.json", '{"mode": "breathe"}')
        z.writestr("sub/nested.json", '{"nested": true}')
    buf.seek(0)

    restore_backup_archive(buf)

    assert (restore_target / "led_state.json").exists()
    assert (restore_target / "sub" / "nested.json").exists()


def test_backup_engine_zip_slip_rejection(tmp_path, monkeypatch):
    restore_target = tmp_path / "safe_dir"
    restore_target.mkdir()
    monkeypatch.setattr("backend.services.backup_engine.DATA_DIR", str(restore_target))

    # Malicious archive attempting path traversal
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.txt", "pwned")
    buf.seek(0)

    with pytest.raises(ValueError, match="Illegal path"):
        restore_backup_archive(buf)


def test_cleanup_stale_fan_trackers():
    Z_STATE.fan_state_tracker = {
        "pwm1": {"current": 100, "last_up_time": 0},
        "pwm2": {"current": 120, "last_up_time": 0},
        "pwm99": {"current": 67, "last_up_time": 0},  # Stale key
    }

    cleanup_stale_fan_trackers(active_keys={"pwm1", "pwm2"})

    assert "pwm1" in Z_STATE.fan_state_tracker
    assert "pwm2" in Z_STATE.fan_state_tracker
    assert "pwm99" not in Z_STATE.fan_state_tracker


def test_main_serve_index_and_lcd_mode(tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    index_html = static_dir / "index.html"
    index_html.write_text('<html lang="en"><body class="studio-workbench"><h1>ZettNAS</h1></body></html>')

    monkeypatch.setattr("backend.main.STATIC_DIR", str(static_dir))

    client = TestClient(app)

    # Standard browser request
    res = client.get("/")
    assert res.status_code == 200
    assert 'class="studio-workbench"' in res.text
    assert "no-cache" in res.headers.get("cache-control", "")

    # Hardware LCD mode request
    res_lcd = client.get("/?mode=lcd")
    assert res_lcd.status_code == 200
    assert 'class="studio-workbench lcd-direct"' in res_lcd.text


def test_client_preferences_endpoints(tmp_path, monkeypatch):
    prefs_file = tmp_path / "client_preferences.json"
    monkeypatch.setattr("backend.api.backup.CLIENT_PREFS_FILE", str(prefs_file))
    from backend.auth import create_session

    token = create_session("admin")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    # Initial empty state
    res = client.get("/api/system/client-preferences", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "preferences": {}}

    # Save preferences
    payload = {
        "lcd_theme": "cyber",
        "zettnas_language": "de",
        "zettnas_desktop_widgets_config": '{"widgets":{"clock":{"enabled":true}}}',
        "zettnas_win_bounds": '{"console":{"x":100,"y":50}}',
    }
    res_post = client.post("/api/system/client-preferences", json=payload, headers=headers)
    assert res_post.status_code == 200

    # Retrieve saved preferences
    res_get = client.get("/api/system/client-preferences", headers=headers)
    assert res_get.status_code == 200
    assert res_get.json()["preferences"] == payload

    # Invalid body
    res_bad = client.post(
        "/api/system/client-preferences", content="not a json", headers={"Content-Type": "application/json", **headers}
    )
    assert res_bad.status_code == 400


def test_backup_and_restore_with_client_preferences(tmp_path, monkeypatch):
    source_dir = tmp_path / "source_data"
    source_dir.mkdir()
    monkeypatch.setattr("backend.services.backup_engine.DATA_DIR", str(source_dir))

    # Write configs and client preferences
    (source_dir / "fan_state.json").write_text('{"curves": [30, 40]}')
    (source_dir / "client_preferences.json").write_text('{"lcd_theme": "amber"}')

    # Generate backup
    buf = generate_backup_zip_stream()

    # Restore in target
    restore_dir = tmp_path / "target_data"
    restore_dir.mkdir()
    monkeypatch.setattr("backend.services.backup_engine.DATA_DIR", str(restore_dir))

    restore_backup_archive(buf)

    assert (restore_dir / "fan_state.json").exists()
    assert (restore_dir / "client_preferences.json").exists()
    assert (restore_dir / "client_preferences.json").read_text() == '{"lcd_theme": "amber"}'

import time
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.scheduler import (
    DEFAULT_SMART_SCHEDULE,
    get_smart_schedule,
    save_smart_schedule,
)
from backend.services.stats_collector import (
    _SMART_VELOCITY_LAST_ALERT,
    evaluate_smart_velocity_alerts,
)


def test_scheduler_schedule_crud_and_validation(tmp_path):
    sched_file = str(tmp_path / "smart_schedule.json")
    with patch("backend.services.scheduler.SMART_SCHEDULE_FILE", sched_file):
        cfg = get_smart_schedule()
        assert cfg["enabled"] is True
        assert cfg["scrub_interval"] == "disabled"
        assert cfg["short_test_interval"] == "monthly"

        # Update schedule with valid values
        updated = save_smart_schedule(
            {
                "enabled": True,
                "short_test_interval": "weekly",
                "short_test_day": 3,
                "short_test_hour": 1,
                "extended_test_interval": "monthly",
                "extended_test_day": 10,
                "extended_test_hour": 3,
                "scrub_interval": "monthly",
                "scrub_day": 5,
                "scrub_hour": 4,
            }
        )
        assert updated["short_test_interval"] == "weekly"
        assert updated["short_test_day"] == 3
        assert updated["scrub_interval"] == "monthly"
        assert updated["scrub_day"] == 5
        assert updated["scrub_hour"] == 4

        # Read back
        loaded = get_smart_schedule()
        assert loaded["scrub_interval"] == "monthly"
        assert loaded["scrub_day"] == 5


def test_storage_schedule_rest_api(client, auth_headers):
    # 1. GET /api/storage/schedule
    resp = client.get("/api/storage/schedule", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "short_test_interval" in data
    assert "scrub_interval" in data

    # 2. PUT /api/storage/schedule
    put_resp = client.put(
        "/api/storage/schedule",
        headers=auth_headers,
        json={
            "enabled": True,
            "short_test_interval": "daily",
            "short_test_hour": 2,
            "scrub_interval": "monthly",
            "scrub_day": 1,
            "scrub_hour": 4,
        },
    )
    assert put_resp.status_code == 200
    res_data = put_resp.json()
    assert res_data["short_test_interval"] == "daily"
    assert res_data["scrub_interval"] == "monthly"


def test_scheduler_scrub_gating_on_unraid():
    """Verifies that on platforms with can_trigger_scrub == False (e.g. Unraid), scheduled scrubs are skipped."""
    mock_adapter = MagicMock()
    mock_caps = MagicMock()
    mock_caps.can_trigger_scrub = False
    mock_adapter.get_capabilities.return_value = mock_caps
    mock_adapter.get_platform_type.return_value.value = "unraid"

    with patch("backend.hardware.pal_storage.get_storage_platform", return_value=mock_adapter):
        # Even if scheduled, trigger_scrub should NEVER be called on Unraid
        assert not mock_caps.can_trigger_scrub
        mock_adapter.trigger_scrub.assert_not_called()


def test_smart_velocity_alerting_and_24h_deduplication():
    _SMART_VELOCITY_LAST_ALERT.clear()

    mock_disks = [{"dev": "sdb", "name": "sdb"}]
    mock_velocity = {
        "dev": "sdb",
        "shedding_sectors": True,
        "realloc_7d_delta": 12,
        "failure_risk": "critical",
        "recommendation": "Accelerating sector decay. Replace disk immediately.",
        "predictive_velocity": {"is_accelerating": True},
    }

    mock_notifications = []

    def mock_send(n):
        mock_notifications.append(n)

    with (
        patch("backend.hardware.disks._discover_disks", return_value=mock_disks),
        patch("backend.db.query_smart_velocity", return_value=mock_velocity),
        patch("backend.services.notifications.send_notification", side_effect=mock_send),
    ):
        # 1. First run -> should trigger alert
        alerts = evaluate_smart_velocity_alerts()
        assert len(alerts) == 1
        assert alerts[0]["dev"] == "sdb"
        assert alerts[0]["realloc_7d_delta"] == 12
        assert len(mock_notifications) == 1
        assert "sdb" in mock_notifications[0]["title"]
        assert mock_notifications[0]["level"] == "critical"

        # 2. Second run immediately -> should be deduplicated by 24h backoff
        alerts2 = evaluate_smart_velocity_alerts()
        assert len(alerts2) == 0
        assert len(mock_notifications) == 1  # No duplicate alert sent

        # 3. Simulate 25 hours later -> should alert again
        _SMART_VELOCITY_LAST_ALERT["sdb"] = time.time() - 90000
        alerts3 = evaluate_smart_velocity_alerts()
        assert len(alerts3) == 1
        assert len(mock_notifications) == 2

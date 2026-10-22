from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setattr(
        "backend.auth.get_current_session",
        lambda tok: {"user_id": "usr_admin", "username": "admin", "role_id": "superadmin", "scopes": ["*"]},
    )
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer test_admin_token"})
    return client


@patch("backend.api.system.container_action")
def test_docker_bulk_action_start_and_stop(mock_action, auth_client):
    mock_action.return_value = {"success": True, "action": "stop", "container_id": "c1"}

    payload = {
        "action": "stop",
        "container_ids": ["c1", "c2"],
        "force": False,
    }
    response = auth_client.post("/api/docker/containers/bulk-action", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "stop"
    assert data["total"] == 2
    assert data["successful"] == 2
    assert "c1" in data["results"]
    assert "c2" in data["results"]
    assert mock_action.call_count == 2


@patch("backend.services.docker_cleanup.destroy_container")
def test_docker_bulk_action_delete(mock_destroy, auth_client):
    mock_destroy.return_value = {"success": True, "deleted": "c1"}

    payload = {
        "action": "delete",
        "container_ids": ["c1"],
        "force": True,
    }
    response = auth_client.post("/api/docker/containers/bulk-action", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "delete"
    assert data["successful"] == 1
    mock_destroy.assert_called_once_with("c1", force=True)


def test_docker_bulk_action_invalid_action(auth_client):
    payload = {
        "action": "invalid_action_name",
        "container_ids": ["c1"],
    }
    response = auth_client.post("/api/docker/containers/bulk-action", json=payload)
    assert response.status_code == 422

"""D5: Unraid API companion mode against a mocked Unraid 7 GraphQL API."""

import json

import httpx
import pytest

from backend.services import unraid_api


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("UNRAID_API_URL", "http://tower")
    monkeypatch.setenv("UNRAID_API_KEY", "key-123")
    seen = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.append((req.url.path, req.headers.get("x-api-key"), body))
        if "createNotification" in body["query"]:
            return httpx.Response(200, json={"data": {"createNotification": {"title": "ZettNAS"}}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "array": {
                        "state": "STARTED",
                        "capacity": {"kilobytes": {"free": "1000", "used": "3000", "total": "4000"}},
                        "parities": [
                            {
                                "name": "parity",
                                "device": "sdb",
                                "status": "DISK_OK",
                                "temp": None,
                                "isSpinning": False,
                                "numErrors": 0,
                            }
                        ],
                        "disks": [
                            {
                                "name": "disk1",
                                "device": "sdc",
                                "status": "DISK_OK",
                                "temp": 34,
                                "isSpinning": True,
                                "numErrors": 3,
                                "fsSize": 10,
                                "fsFree": 4,
                                "fsUsed": 6,
                                "fsType": "xfs",
                            }
                        ],
                        "caches": [],
                        "parityCheckStatus": {
                            "status": "RUNNING",
                            "running": True,
                            "paused": False,
                            "progress": 42,
                            "errors": 0,
                            "speed": "150",
                            "date": None,
                        },
                    },
                    "shares": [{"name": "media", "comment": "", "free": 1, "used": 2, "size": 3}],
                    "notifications": {"overview": {"unread": {"alert": 1, "warning": 0, "info": 2, "total": 3}}},
                }
            },
        )

    return httpx.MockTransport(handler), seen


def test_status(api):
    t, seen = api
    st = unraid_api.status(transport=t)
    assert seen[0][0] == "/graphql" and seen[0][1] == "key-123"
    assert st["state"] == "STARTED" and st["capacity"]["total"] == 4000 * 1024
    assert st["sleeping"] == ["sdb"] and st["errors"] == {"disk1": 3}
    assert st["parity_check"]["progress"] == 42 and st["shares"][0]["name"] == "media"
    assert st["unread_notifications"]["alert"] == 1


def test_notify_maps_importance(api):
    t, seen = api
    assert unraid_api.notify("Disk failing", "Back up disk1.", level="critical", transport=t)
    v = seen[-1][2]["variables"]["input"]
    assert v["importance"] == "ALERT" and v["subject"] == "Disk failing"


def test_errors_and_config(monkeypatch):
    monkeypatch.delenv("UNRAID_API_URL", raising=False)
    assert not unraid_api.configured()
    monkeypatch.setenv("UNRAID_API_URL", "http://tower")
    monkeypatch.setenv("UNRAID_API_KEY", "bad")
    t = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"errors": [{"message": "Invalid CSRF token"}], "data": None})
    )
    with pytest.raises(unraid_api.UnraidApiError):
        unraid_api.status(transport=t)
    assert unraid_api.notify("x", "y", transport=t) is False

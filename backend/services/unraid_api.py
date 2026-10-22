"""
Unraid companion mode (D5): read the array through the Unraid API (Unraid 7, GraphQL)
and post ZettNAS alerts into Unraid's notification centre.

Set UNRAID_API_URL (for example http://tower or http://10.0.0.5) and UNRAID_API_KEY.
Create the key on the Unraid box with read access to the array, disks and shares and
create access to notifications, for example:
    unraid-api apikey --create --name zettnas --roles VIEWER --permissions NOTIFICATIONS:CREATE_ANY
Without them ZettNAS keeps reading Unraid's status files directly, as before. It never
starts, stops or changes the array through the API.
"""

import os
from typing import Any

import httpx

from backend.config import logger

STATUS_QUERY = """
query ZettNASStatus {
  array {
    state
    capacity { kilobytes { free used total } }
    parities { name device status temp isSpinning numErrors }
    disks { name device status temp isSpinning numErrors fsSize fsFree fsUsed fsType }
    caches { name device status temp isSpinning numErrors fsSize fsFree fsUsed fsType }
    parityCheckStatus { status running paused progress errors speed date }
  }
  shares { name comment free used size }
  notifications { overview { unread { alert warning info total } } }
}
"""
NOTIFY_MUTATION = """
mutation ZettNASNotify($input: NotificationData!) {
  createNotification(input: $input) { title }
}
"""
IMPORTANCE = {"critical": "ALERT", "alert": "ALERT", "error": "ALERT", "warning": "WARNING", "warn": "WARNING"}


class UnraidApiError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("UNRAID_API_URL") and os.environ.get("UNRAID_API_KEY"))


def _post(query: str, variables: dict[str, Any] | None = None, transport=None) -> dict[str, Any]:
    base = os.environ.get("UNRAID_API_URL", "").rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise UnraidApiError("UNRAID_API_URL must start with http:// or https://")
    with httpx.Client(timeout=10, transport=transport, verify=os.environ.get("UNRAID_API_VERIFY_TLS", "1") != "0") as c:
        r = c.post(
            f"{base}/graphql",
            json={"query": query, "variables": variables or {}},
            headers={"x-api-key": os.environ.get("UNRAID_API_KEY", ""), "Content-Type": "application/json"},
        )
    if r.status_code == 401:
        raise UnraidApiError("Unraid refused the API key")
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise UnraidApiError("; ".join(str(e.get("message")) for e in body["errors"])[:300])
    return body.get("data") or {}


def status(transport=None) -> dict[str, Any]:
    """Array state, capacity, disks (with spin state and errors), shares and parity check."""
    d = _post(STATUS_QUERY, transport=transport)
    arr = d.get("array") or {}
    kb = ((arr.get("capacity") or {}).get("kilobytes")) or {}
    to_bytes = lambda v: int(v) * 1024 if str(v or "").isdigit() else None  # noqa: E731
    disks = []
    for role, key in (("parity", "parities"), ("data", "disks"), ("cache", "caches")):
        for disk in arr.get(key) or []:
            disks.append({**disk, "role": role})
    unread = (((d.get("notifications") or {}).get("overview") or {}).get("unread")) or {}
    return {
        "state": arr.get("state"),
        "capacity": {
            "free": to_bytes(kb.get("free")),
            "used": to_bytes(kb.get("used")),
            "total": to_bytes(kb.get("total")),
        },
        "disks": disks,
        "sleeping": [x["device"] for x in disks if x.get("isSpinning") is False and x.get("device")],
        "errors": {x["name"]: x["numErrors"] for x in disks if (x.get("numErrors") or 0) > 0},
        "parity_check": arr.get("parityCheckStatus") or {},
        "shares": d.get("shares") or [],
        "unread_notifications": unread,
    }


def notify(title: str, message: str, level: str = "normal", link: str = "", transport=None) -> bool:
    """Posts an alert to Unraid's notification centre (bell icon and its email/agents)."""
    data = {
        "title": "ZettNAS",
        "subject": str(title)[:120],
        "description": str(message)[:1000],
        "importance": IMPORTANCE.get(str(level).lower(), "INFO"),
    }
    if link:
        data["link"] = link[:300]
    try:
        _post(NOTIFY_MUTATION, {"input": data}, transport=transport)
        return True
    except Exception as e:
        logger.warning(f"[UnraidAPI] Notification failed: {e}")
        return False

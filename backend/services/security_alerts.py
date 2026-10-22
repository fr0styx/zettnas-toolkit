"""
Security alerts: important audit events are also sent through the configured
notification channels (ntfy, webhooks, Apprise, Unraid), so an admin hears
about them without reading the audit log.

Called from log_security_event(); sending happens on a background thread and
never blocks or breaks the request. Repeats of the same event by the same
actor are collapsed for 10 minutes.
"""

import threading
from typing import Any, Optional

# event_type -> (title, level)
ALERT_EVENTS: dict[str, tuple] = {
    "auth.lockout": ("Sign-in locked after repeated failures", "warning"),
    "auth.login.blocked": ("Sign-in attempt on a disabled account", "warning"),
    "auth.mfa.disabled": ("Two-factor sign-in turned off", "warning"),
    "user.created": ("User account created", "normal"),
    "user.deleted": ("User account deleted", "warning"),
    "user.role.changed": ("User role changed", "warning"),
    "user.password.changed": ("Password changed", "normal"),
    "api_token.created": ("API token created", "warning"),
    "admin.account.disabled": ("Admin account disabled", "warning"),
    "worm_break_glass_delete": ("Protected (WORM) data deleted", "critical"),
    "confirm.storage.pool.create": ("Storage pool created (disks erased)", "warning"),
    "confirm.storage.pool.delete": ("Storage pool deleted", "critical"),
    "confirm.system.restore": ("Settings restored from a backup", "warning"),
    "confirm.updates.revert": ("ZettNAS reverted to a previous version", "warning"),
    "confirm.users.delete": ("User account deleted", "warning"),
}


def _describe(event_type: str, actor: str | None, ip: str | None, details: dict[str, Any]) -> str:
    parts = []
    if actor:
        parts.append(f"by {actor}")
    if ip:
        parts.append(f"from {ip}")
    for key in ("target", "target_user_id", "username", "role", "new_role", "name", "key"):
        if details.get(key):
            parts.append(f"{key.replace('_', ' ')}: {details[key]}")
    return ", ".join(parts) or event_type


def maybe_alert(
    event_type: str,
    status: str,
    actor_username: str | None = None,
    actor_ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> bool:
    """Sends an alert for events in ALERT_EVENTS. Returns True if one was queued."""
    spec = ALERT_EVENTS.get(event_type)
    if not spec or status not in ("success", "blocked", "warning", "failure"):
        return False
    title, level = spec
    message = _describe(event_type, actor_username, actor_ip, details or {})

    def _send():
        try:
            from backend.services.notifications import send_notification

            send_notification(
                f"ZettNAS security: {title}",
                message,
                level=level,
                event_type="security",
                dedup_key=f"sec:{event_type}:{actor_username or ''}:{actor_ip or ''}",
            )
        except Exception:
            pass

    threading.Thread(target=_send, name="security-alert", daemon=True).start()
    return True

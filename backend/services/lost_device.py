"""A lost phone or tablet (Users decision 8, SET-19 stage 2): what an administrator may do for
someone else, and how it is recorded. The routes are in backend/api/auth.py (they need its
password check and lockout); they ask for the administrator's own password first.
"""

import time
from typing import Any

# what a session row may show an administrator: never its hash, only a short id to name it
SESSION_FIELDS = ("created_at", "last_active_at", "expires_at", "ip_address", "user_agent", "is_remembered")


def sessions_of(user_id: str) -> list[dict[str, Any]]:
    """Where the person is signed in, newest first."""
    from backend.users_db import list_user_sessions

    return [
        {"id": s["session_id_hash"][:12], **{k: s.get(k) for k in SESSION_FIELDS}} for s in list_user_sessions(user_id)
    ]


def carry_out(target: dict[str, Any], sign_out: bool, turn_off_two_step: bool) -> dict[str, Any]:
    """Signs the person out on every device and/or turns off their two-step code."""
    from backend.services import mfa_policy
    from backend.users_db import disable_user_mfa, get_user_mfa, list_user_sessions, revoke_all_sessions_for_user

    ended = 0
    if sign_out:
        ended = len(list_user_sessions(target["id"]))
        revoke_all_sessions_for_user(target["id"])
    two_step_off = False
    if turn_off_two_step and (get_user_mfa(target["id"]) or {}).get("mfa_enabled"):
        two_step_off = bool(disable_user_mfa(target["id"]))
        mfa_policy.forget(target["id"])
    return {"sessions_ended": ended, "two_step_off": two_step_off}


def _notice(admin: str, done: dict[str, Any]) -> str:
    what = []
    if done["sessions_ended"]:
        what.append("signed you out on every device")
    if done["two_step_off"]:
        what.append("turned off your two-step sign-in, so you can set it up on a new phone")
    if not what:
        return ""
    when = time.strftime("%Y-%m-%d %H:%M")
    return f"{admin} {' and '.join(what)} on {when}. If you did not ask for this, tell them."


def record(target: dict[str, Any], admin_id: str, admin: str, ip: str, done: dict[str, Any]) -> bool:
    """The security log, the event log, and a word to the person. True when the person was told."""
    from backend.services.notifications import notify_person
    from backend.state import add_event, event_text
    from backend.users_db import log_security_event

    who = target.get("username", "")
    log_security_event(
        "user.lost_device",
        "success",
        actor_id=admin_id,
        actor_username=admin,
        actor_ip=ip,
        details={"target_user_id": target["id"], **done},
    )
    if done["sessions_ended"]:
        add_event(
            "warning",
            "Signed out everywhere",
            f"{admin} signed {who} out on every device.",
            event_text("lost_device_signed_out", admin=admin, user=who),
        )
    if done["two_step_off"]:
        add_event(
            "warning",
            "Two-step sign-in turned off",
            f"{admin} turned off two-step sign-in for {who}.",
            event_text("lost_device_two_step", admin=admin, user=who),
        )
    message = _notice(admin, done)
    if not message:
        return False
    return bool(notify_person(who, "Your sign-in was changed", message))  # it catches its own sending errors

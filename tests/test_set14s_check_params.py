"""SET-14: each built-in row of the security check says what goes into its sentence, so the page can translate it."""

from backend.services import security_advisor

BUILT_IN = {
    "default_password",
    "admin_mfa",
    "https_transport",
    "smb_guest_access",
    "stale_api_tokens",
    "ai_runtime_exposure",
}


def test_built_in_rows_carry_params():
    rows = {c["id"]: c for c in security_advisor.evaluate_security_posture(None)["checks"]}
    for cid in BUILT_IN:
        assert isinstance(rows[cid].get("params"), dict), cid
    assert rows["stale_api_tokens"]["params"]["count"] >= 0

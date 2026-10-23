"""The sign-in screen is a real form with labelled fields and an announced error (UX-3)."""

import pathlib
import re

INDEX = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html").read_text(encoding="utf-8")
AUTH = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src" / "components" / "auth.js").read_text(
    encoding="utf-8"
)


def test_credentials_step_is_a_form_with_labelled_fields():
    assert '<form id="login-step-credentials"' in INDEX
    for field in ("login-username", "login-password"):
        assert re.search(rf'<label for="{field}"', INDEX), field
    assert '<button type="button" id="login-btn"' in INDEX  # never a page-reloading submit


def test_errors_stay_visible_and_are_announced():
    assert '<p id="login-error" class="login-sso-error" role="alert" hidden></p>' in INDEX
    assert "_showLoginError(msg)" in AUTH
    assert "TOO MANY ATTEMPTS" not in AUTH

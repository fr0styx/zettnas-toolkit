"""The setup wizard has no step whose answer is thrown away (UX-2), and its password labels name their fields."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "frontend"


def test_no_operating_mode_step():
    assert "setup-host-mode" not in (ROOT / "index.html").read_text(encoding="utf-8")
    assert "zettnas_host_mode" not in (ROOT / "src" / "components" / "setup-wizard.js").read_text(encoding="utf-8")


def test_password_labels_name_their_fields():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for field in ("setup-current-pwd", "setup-new-pwd", "setup-confirm-pwd"):
        assert f'<label for="{field}"' in html, field

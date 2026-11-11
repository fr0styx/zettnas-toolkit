"""SET-14: install progress lines say how they were made, so the page can translate them."""

import re
from pathlib import Path

from backend.services import app_catalog

SRC = Path(app_catalog.__file__).read_text(encoding="utf-8")
EN = Path(__file__).resolve().parents[1].joinpath("frontend/src/locales/en.js").read_text(encoding="utf-8")


def test_a_sentence_gets_its_key_and_values():
    ev = app_catalog.with_text(
        {"step": "pull", "message": "Pulling jellyfin/jellyfin:10.11 from registry (downloading layers)..."}
    )
    assert ev["text"] == {"msg_key": "install.pulling", "params": {"image": "jellyfin/jellyfin:10.11"}}
    ev = app_catalog.with_text(
        {
            "message": "Deployment aborted: Host port 8096 is already in use by emby. Please choose an available port in configuration."
        }
    )
    assert ev["text"]["params"] == {"port": "8096", "by": "emby"}


def test_another_text_is_left_alone():
    ev = app_catalog.with_text({"message": "layer 3/7 extracting"})
    assert "text" not in ev


def test_every_sentence_is_still_said_by_the_installer_and_known_to_the_page():
    for key, tpl in app_catalog.INSTALL_SAID.items():
        first_literal = re.split(r"\{\w+\}", tpl)[0] or re.split(r"\{\w+\}", tpl)[1]
        assert first_literal.strip() and first_literal in SRC.split("INSTALL_SAID")[0], key
        assert f'"install.{key}":' in EN, key

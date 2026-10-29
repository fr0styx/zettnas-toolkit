"""SEC-35: secrets are kept apart from what they protect. The secret key can come from a file
outside the data folder, the first-run password is not written to the log, and the LCD
renderer's token travels in a header, never in a URL."""

import logging
import pathlib

import pytest

from backend import config, users_db

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_secret_key_from_a_secret_file(monkeypatch, tmp_path):
    key = tmp_path / "secret_key"
    key.write_text("k" * 64 + "\n")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY_FILE", str(key))
    assert config._get_or_create_secret_key() == "k" * 64
    monkeypatch.delenv("SECRET_KEY_FILE")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert config._get_or_create_secret_key() == "k" * 64


def test_an_unreadable_secret_file_stops_startup(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY_FILE", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="secret key"):
        config._get_or_create_secret_key()


def test_the_first_run_password_is_not_logged(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(config, "initial_password_file", lambda: str(tmp_path / "initial-admin-password"))
    with caplog.at_level(logging.WARNING):
        password = users_db._first_time_password()
    assert password and password not in caplog.text
    assert "initial-admin-password" in caplog.text


def test_the_lcd_page_url_carries_no_token():
    src = (ROOT / "backend" / "services" / "lcd_renderer.py").read_text(encoding="utf-8")
    assert "lcd_token=" not in src

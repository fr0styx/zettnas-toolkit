"""The pre-SQLite api_tokens.json store must not grant access."""

import os

from backend import api_tokens, config
from backend.auth import get_current_session, purge_legacy_session_files


def test_legacy_json_token_is_not_a_session(monkeypatch, tmp_path):
    monkeypatch.setattr(api_tokens, "TOKENS_FILE", str(tmp_path / "api_tokens.json"))
    raw = api_tokens.generate_token("old-integration")
    assert api_tokens.validate_api_token(raw)
    assert get_current_session(raw) is None


def test_legacy_json_token_file_is_purged(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSIONS_FILE", str(tmp_path / "sessions.json"))
    (tmp_path / "api_tokens.json").write_text("{}")
    purge_legacy_session_files()
    assert not os.path.exists(tmp_path / "api_tokens.json")

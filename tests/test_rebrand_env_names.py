"""R1-2: Kiboto reads KIBOTO_* settings, and the ZETTNAS_* names installs set before the rebrand
still work until 2.2; a new name set beside an old one wins."""

import os

from backend import db_crypto, legacy_names, settings


def test_old_env_name():
    assert legacy_names.old_env_name("KIBOTO_DATA_KEY") == "ZETTNAS_DATA_KEY"
    assert legacy_names.old_env_name("PORT") is None


def test_getenv_falls_back_and_the_new_name_wins(monkeypatch):
    monkeypatch.delenv("KIBOTO_PLATFORM", raising=False)
    monkeypatch.delenv("ZETTNAS_PLATFORM", raising=False)
    assert legacy_names.getenv("KIBOTO_PLATFORM", "auto") == "auto"
    monkeypatch.setenv("ZETTNAS_PLATFORM", "unraid")
    assert legacy_names.getenv("KIBOTO_PLATFORM") == "unraid"
    monkeypatch.setenv("KIBOTO_PLATFORM", "truenas")
    assert legacy_names.getenv("KIBOTO_PLATFORM") == "truenas"


def test_a_setting_reads_its_old_name(monkeypatch):
    monkeypatch.delenv("KIBOTO_THUMB_CACHE_MB", raising=False)
    monkeypatch.setenv("ZETTNAS_THUMB_CACHE_MB", "2048")
    assert settings.current("thumb_cache_mb") == 2048
    s, problems = settings.load_settings({"ZETTNAS_THUMB_CACHE_MB": "3072"})
    assert s.thumb_cache_mb == 3072 and not problems
    s, _ = settings.load_settings({"ZETTNAS_THUMB_CACHE_MB": "3072", "KIBOTO_THUMB_CACHE_MB": "4096"})
    assert s.thumb_cache_mb == 4096


def test_every_setting_is_named_kiboto_now():
    import dataclasses

    names = [f.metadata["env"] for f in dataclasses.fields(settings.Settings)]
    assert not [n for n in names if n.startswith(legacy_names.OLD_ENV_PREFIX)]


def test_the_data_key_from_either_name_or_credential(monkeypatch, tmp_path):
    for n in ("KIBOTO_DATA_KEY", "ZETTNAS_DATA_KEY", "KIBOTO_DATA_KEY_FILE", "ZETTNAS_DATA_KEY_FILE"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    assert not db_crypto.enabled()
    monkeypatch.setenv("ZETTNAS_DATA_KEY", "an-old-key-of-enough-length")
    assert db_crypto.enabled() and db_crypto._key_text() == "an-old-key-of-enough-length"
    monkeypatch.delenv("ZETTNAS_DATA_KEY")
    (tmp_path / "zettnas-data-key").write_text("a-sealed-key-of-enough-length\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert db_crypto.enabled() and db_crypto._key_text() == "a-sealed-key-of-enough-length"
    assert db_crypto._KDF_SALT == b"zettnas-data-key-v1"  # old databases were keyed with it
    os.remove(tmp_path / "zettnas-data-key")
    assert not db_crypto.enabled()


def test_the_session_cookie_from_before_still_signs_in():
    from backend.auth import SESSION_COOKIE, session_cookie

    assert SESSION_COOKIE == "kiboto_session"
    assert session_cookie({"zettnas_session": "old"}) == "old"
    assert session_cookie({"zettnas_session": "old", "kiboto_session": "new"}) == "new"
    assert session_cookie({}) == ""


def test_the_guard_file_from_before_takes_the_new_name(tmp_path):
    from backend.services import ransomware_guard as rg

    one, both = tmp_path / "one", tmp_path / "both"
    one.mkdir()
    both.mkdir()
    (one / "!ZettNAS-guard-file.docx").write_bytes(b"old")
    (both / "!ZettNAS-guard-file.docx").write_bytes(b"old")
    (both / rg.CANARY_NAME).write_bytes(b"new")
    rg._rename_old_canary(str(one), str(one / rg.CANARY_NAME))
    rg._rename_old_canary(str(both), str(both / rg.CANARY_NAME))
    assert sorted(p.name for p in one.iterdir()) == [rg.CANARY_NAME] and (one / rg.CANARY_NAME).read_bytes() == b"old"
    assert sorted(p.name for p in both.iterdir()) == [rg.CANARY_NAME] and (both / rg.CANARY_NAME).read_bytes() == b"new"
    rg._rename_old_canary(str(tmp_path), str(tmp_path / rg.CANARY_NAME))  # nothing there: nothing happens


def test_the_log_file_from_before_the_rebrand_carries_on(tmp_path):
    from backend import logging_config

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "zettnas.log").write_text("before\n")
    (logs / "zettnas.log.1").write_text("older\n")
    path = str(logs / "kiboto.log")
    logging_config._adopt_old_log(path)
    assert (logs / "kiboto.log").read_text() == "before\n" and (logs / "kiboto.log.1").read_text() == "older\n"
    assert not (logs / "zettnas.log").exists()
    (logs / "zettnas.log").write_text("stray\n")  # a new file is never overwritten
    logging_config._adopt_old_log(path)
    assert (logs / "kiboto.log").read_text() == "before\n"

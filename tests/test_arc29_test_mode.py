"""ARC-29: the test switches can't weaken a real install. TESTING / ZETTNAS_TEST_MODE make password
hashing fast, allow the shared default password and turn the Docker proxy off; in the released
image (which carries /etc/zettnas-release) they do nothing, whatever the environment says."""

import pathlib
import re

from backend import settings

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_switches_work_outside_the_image(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "RELEASE_MARKER", str(tmp_path / "absent"))
    monkeypatch.setenv("TESTING", "1")
    assert settings.test_mode() and settings.fast_hash()
    monkeypatch.delenv("TESTING")
    monkeypatch.delenv("ZETTNAS_TEST_MODE", raising=False)
    assert not settings.test_mode()
    monkeypatch.setenv("ZETTNAS_FAST_HASH", "1")
    assert settings.fast_hash() and not settings.test_mode()


def test_switches_do_nothing_in_the_released_image(monkeypatch, tmp_path):
    marker = tmp_path / "zettnas-release"
    marker.write_text("release image")
    monkeypatch.setattr(settings, "RELEASE_MARKER", str(marker))
    for name in ("TESTING", "ZETTNAS_TEST_MODE", "ZETTNAS_FAST_HASH"):
        monkeypatch.setenv(name, "1")
    assert not settings.test_mode()
    assert not settings.fast_hash()


def test_the_sensitive_checks_go_through_test_mode():
    for rel in ("backend/passwords.py", "backend/users_db.py", "backend/config.py", "backend/main.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r'environ\.get\("(TESTING|ZETTNAS_TEST_MODE|ZETTNAS_FAST_HASH)"', src), rel


def test_the_release_build_writes_the_marker():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'if [ "$DEV_BUILD" != "1" ]; then echo' in dockerfile and settings.RELEASE_MARKER in dockerfile

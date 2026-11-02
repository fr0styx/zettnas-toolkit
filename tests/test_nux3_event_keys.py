"""NUX-3: activity-log entries name message keys that exist in every language, with the same
values in each, so the log can show them in the reader's language."""

import glob
import os
import re

from backend.state import event_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANGS = ("en", "de", "fr", "es", "zh")


def _locale(lang: str) -> dict[str, str]:
    with open(os.path.join(ROOT, "frontend", "src", "locales", f"{lang}.js"), encoding="utf-8") as f:
        text = f.read()
    return dict(re.findall(r'^\s*"(ev\.[^"]+)":\s*"((?:[^"\\]|\\.)*)",?$', text, re.M))


def _names_used() -> set[str]:
    names = set()
    for path in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        names.update(re.findall(r'event_text\(\s*"([a-z0-9_]+)"', src))
        for a, b in re.findall(r'event_text\(\s*"([a-z0-9_]+)" if [^"]+ else "([a-z0-9_]+)"', src):
            names.update((a, b))
    names.update({"smart_short", "smart_long"})  # f"smart_{action_name}"
    return names


def _placeholders(s: str) -> set[str]:
    return set(re.findall(r"\{(\w+)", s))


def test_every_event_key_is_translated_with_the_same_values():
    used = _names_used()
    assert len(used) >= 40
    en = _locale("en")
    for lang in LANGS:
        strings = _locale(lang)
        for name in used:
            for part in ("title", "msg"):
                key = f"ev.{name}.{part}"
                assert key in strings, (lang, key)
                assert _placeholders(strings[key]) == _placeholders(en[key]), (lang, key)


def test_event_text_shape():
    assert event_text("fm_trashed", name="a.txt") == {
        "title_key": "ev.fm_trashed.title",
        "msg_key": "ev.fm_trashed.msg",
        "params": {"name": "a.txt"},
    }


def test_swapped_arguments_are_fixed():
    for rel in ("backend/services/ransomware_guard.py", "backend/services/docker_cleanup.py"):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            src = f.read()
        assert not re.search(r'add_event\(\s*"(security|docker)"', src), rel

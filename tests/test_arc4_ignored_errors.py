"""ARC-4: errors the code carries on after are counted, warned about and shown in diagnostics."""

import glob
import logging
import os
import re

from backend import ignored_errors as ie

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# places that ignore an error on purpose; lower it when you handle one properly, never raise it
IGNORED_BASELINE = 306


def _raise_and_ignore(where, now):
    try:
        raise ValueError("disk went away")
    except ValueError:
        ie.ignored(where, now=now)


def test_first_error_warns_repeats_are_counted_then_summarised_daily(caplog):
    ie.reset()
    caplog.set_level(logging.DEBUG, logger="ZettNAS")
    _raise_and_ignore("backend.x.read", now=1000.0)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in warnings] == ["[ignored] backend.x.read: ValueError: disk went away"]
    assert any(r.levelno == logging.DEBUG and r.exc_info for r in caplog.records)  # the traceback, at debug
    caplog.clear()
    for i in range(5):
        _raise_and_ignore("backend.x.read", now=1000.0 + 60 * i)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    _raise_and_ignore("backend.x.read", now=1000.0 + ie.REPEAT_WARNING_SECS)
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert msgs == ["[ignored] backend.x.read: ValueError: disk went away (6 times since the last warning)"]


def test_snapshot_lists_the_busiest_places_first():
    ie.reset()
    for _ in range(3):
        _raise_and_ignore("b.often", now=5.0)
    _raise_and_ignore("a.once", now=6.0)
    snap = ie.snapshot()
    assert snap["total"] == 4 and snap["places"] == 2
    assert [s["where"] for s in snap["top"]] == ["b.often", "a.once"]
    assert snap["top"][0]["last"] == "ValueError: disk went away"
    ie.ignored("outside.except", now=7.0)  # called without an exception: still counted
    assert ie.snapshot()["top"][-1]["last"] == "no exception"
    long = "x" * 400
    assert len(ie._describe(RuntimeError(long))) == 300


def test_the_old_debug_calls_are_routed_on_any_logger(caplog):
    ie.reset()
    caplog.set_level(logging.WARNING, logger="ZettNAS")
    child = logging.getLogger("ZettNAS.WebDAVApi")
    try:
        raise OSError("share gone")
    except OSError:
        child.debug("backend.api.webdav.mount: ignored error", exc_info=True)
    assert ie.snapshot()["top"][0]["where"] == "backend.api.webdav.mount"
    assert "[ignored] backend.api.webdav.mount: OSError: share gone" in caplog.text
    # other debug calls are untouched
    logging.getLogger("ZettNAS").debug("plain %s", "message")
    logging.getLogger("ZettNAS").debug("x: ignored error")  # no exc_info: an ordinary message
    assert ie.snapshot()["places"] == 1


def test_the_number_of_places_that_ignore_errors_only_goes_down():
    places = 0
    for f in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True):
        if f.endswith("ignored_errors.py"):
            continue
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        places += len(re.findall(r'\.debug\(\s*"[^"<\n]+: ignored error"', text)) + len(
            re.findall(r'\bignored\("', text)
        )
    assert places <= IGNORED_BASELINE, f"{places} places ignore errors (baseline {IGNORED_BASELINE})"


def test_diagnostics_show_the_counts(client, auth_headers):
    ie.reset()
    _raise_and_ignore("backend.demo.place", now=10.0)
    body = client.get("/api/system/diagnostics-summary", headers=auth_headers).json()
    ign = body["ignored_errors"]
    assert ign["total"] >= 1  # building the summary may ignore a few of its own (no btrfs here)
    assert "backend.demo.place" in [s["where"] for s in ign["top"]]
    assert "Ignored errors:" in body["support_markdown"]

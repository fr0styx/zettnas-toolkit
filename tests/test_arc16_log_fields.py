"""ARC-16: structured fields reach the JSON log lines."""

import json
import logging

from backend.logging_config import JSONLogFormatter


def _line(**extra):
    record = logging.getLogger("ZettNAS").makeRecord(
        "ZettNAS", logging.INFO, __file__, 1, "backup %s finished", ("nightly",), None, extra=extra or None
    )
    return json.loads(JSONLogFormatter().format(record))


def test_extra_fields_appear_under_fields():
    line = _line(job="nightly", files=12, took=1.5, target=object())
    assert line["message"] == "backup nightly finished"
    assert line["fields"]["job"] == "nightly" and line["fields"]["files"] == 12 and line["fields"]["took"] == 1.5
    assert line["fields"]["target"].startswith("<object object")  # not JSON: written as repr


def test_no_fields_without_extra_and_secrets_are_redacted():
    assert "fields" not in _line()
    assert "s3cr3t-value" not in json.dumps(_line(api_key="s3cr3t-value"))

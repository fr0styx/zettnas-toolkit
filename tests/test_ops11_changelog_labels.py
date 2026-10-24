"""Changelog entries don't claim a channel; promotion sets it (OPS-11)."""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAST_LABELLED = (1, 9, 4)  # entries up to here predate the rule


def test_new_entries_have_no_channel_label():
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        headings = re.findall(r"^## v(\d+)\.(\d+)\.(\d+)[^\n]*$", f.read(), re.M)
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        lines = [line for line in f if line.startswith("## v")]
    for (major, minor, patch), line in zip(headings, lines, strict=True):
        if (int(major), int(minor), int(patch)) <= LAST_LABELLED:
            continue
        assert not re.search(r"\b(Stable|Beta|Edge)\b", line), f"no channel in changelog headings: {line.strip()}"

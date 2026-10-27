"""Reading the result of the last scrub from what ZFS and btrfs print (B12a, REL-11).
No disk is read: zpool status and btrfs's saved scrub status only."""

from __future__ import annotations

import re
import time
from typing import Any

_ZPOOL_ERRORS = re.compile(r"with (\d+) errors? on (.+)$")


def parse_zpool_scan(text: str) -> dict[str, Any] | None:
    """The scan line of `zpool status`: the last scrub's errors and when it ended."""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line.startswith("scan:"):
            continue
        if "none requested" in line:
            return {"state": "never", "errors": 0, "finished_at": None}
        if "in progress" in line:
            return {"state": "running", "errors": 0, "finished_at": None}
        if "scrub canceled" in line:
            return {"state": "canceled", "errors": 0, "finished_at": None}
        m = _ZPOOL_ERRORS.search(line)
        if m and "scrub" in line:
            try:
                at = time.mktime(time.strptime(m.group(2).strip(), "%a %b %d %H:%M:%S %Y"))
            except ValueError:
                at = None
            return {"state": "finished", "errors": int(m.group(1)), "finished_at": at}
    return None


_BTRFS_COUNTS = ("read_errors", "csum_errors", "verify_errors", "super_errors", "uncorrectable_errors")


def parse_btrfs_scrub(text: str) -> dict[str, Any] | None:
    """`btrfs scrub status -R`: the error counters of the last scrub."""
    text = text or ""
    if "no stats available" in text:
        return {"state": "never", "errors": 0, "finished_at": None}
    status = re.search(r"^\s*Status:\s*(\w+)", text, re.M)
    if not status:
        return None
    errors = sum(int(m.group(1)) for k in _BTRFS_COUNTS for m in re.finditer(rf"\b{k}:\s*(\d+)", text))
    started = re.search(r"^\s*Scrub started:\s*(.+)$", text, re.M)
    at = None
    if started:
        try:
            at = time.mktime(time.strptime(started.group(1).strip(), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            at = None
    state = status.group(1).lower()
    return {"state": "finished" if state == "finished" else state, "errors": errors, "finished_at": at}

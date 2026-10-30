"""Is this disk asleep? One probe for the whole app (NARC-2).

"Never wake a sleeping disk" is the product's core promise, so the question is asked one way:
`smartctl -n standby -i`, which answers without spinning a disk up, read by smart_power's rule
(only smartctl's standby message means asleep; a drive that can't be opened is "unreachable",
never "asleep", NARC-1). One cache for every caller, so two features asking about the same disk
within PROBE_TTL_S start one smartctl, not two.

Cheaper sources come first in the callers that have them (Unraid's own spin state in disks.ini,
the SMART poller's last reading: rag_standby.is_backing_disk_in_standby). What a disk nobody can
place means is the caller's choice, said out loud: DEFER (count it as asleep: leave it alone, the
AI index and file listings) or CHECK (count it as awake: the ransomware guard looks anyway).

NVMe, loop, RAM and zram devices never sleep.
"""

from __future__ import annotations

import os
import time

from backend.hardware.smart_power import smartctl_power
from backend.proc import TIMED_OUT, run_bounded
from backend.state import Z_STATE

STANDBY, ACTIVE, UNREACHABLE, UNKNOWN = "standby", "active", "unreachable", "unknown"
DEFER, CHECK = "defer", "check"  # what an unknown disk counts as: asleep, or awake
PROBE_TTL_S = 10.0
NEVER_SLEEP = ("nvme", "loop", "ram", "zram")
_PROBES: dict[str, tuple[float, str]] = {}  # dev -> (when, state)


def dev_name(dev: str) -> str:
    """sdb from sdb, /dev/sdb or /host/dev/sdb."""
    return str(dev or "").removeprefix("/host/dev/").removeprefix("/dev/")


def dev_path(name: str) -> str:
    """Where the device node is: under /host/dev in the container when that exists."""
    host = f"/host/dev/{name}"
    return host if os.path.exists(host) else f"/dev/{name}"


def probe(dev: str, device_type: str | None = None, max_age: float = PROBE_TTL_S, path: str | None = None) -> str:
    """STANDBY, ACTIVE, UNREACHABLE or UNKNOWN (smartctl couldn't be run or didn't finish), asked
    without waking the disk. A reading at most max_age seconds old is reused (0: ask now)."""
    name = dev_name(dev)
    if not name:
        return UNKNOWN
    if name.startswith(NEVER_SLEEP):
        return ACTIVE
    now = time.monotonic()
    hit = _PROBES.get(name)
    if hit and max_age > 0 and now - hit[0] < max_age:
        return hit[1]
    cmd = ["smartctl", "-n", "standby", "-i"] + (["-d", device_type] if device_type else []) + [path or dev_path(name)]
    try:
        r = run_bounded(cmd, timeout=6, capture_output=True, text=True)
    except OSError:
        return UNKNOWN
    if r.returncode == TIMED_OUT:
        return UNKNOWN
    state = smartctl_power(r.returncode, (r.stdout or "") + " " + (r.stderr or ""))
    _PROBES[name] = (now, state)
    if state == STANDBY:  # the rest of the app sees it at once (Overview, Drive Health)
        prev = Z_STATE.cached_smart_data.get(name)
        Z_STATE.smart.set_reading(name, prev[0] if prev else None, "standby")
    return state


def asleep(state: str, unknown: str = DEFER) -> bool:
    """Whether a probe's answer means "leave it alone". UNREACHABLE is never asleep (NARC-1)."""
    if state == UNKNOWN:
        return unknown == DEFER
    return state == STANDBY


def forget() -> None:
    _PROBES.clear()

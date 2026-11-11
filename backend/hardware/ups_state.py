"""One reading of a UPS, in words, and the one rule that starts the safe shutdown (SET-08).

The status string was read in four places, each its own way. "OB" was looked for anywhere in the
string, so a UPS with its battery unplugged ("NOBATT") counted as on battery; a low-battery flag
counted as on battery even on mains, which shut a NAS down again after every start until the
battery had recharged; and Overview knew only one spelling. This module is the one reader.
"""

import re
from typing import Any

ONLINE = "online"
ON_BATTERY = "on_battery"
UNKNOWN = "unknown"

_ON_BATTERY_WORDS = {"OB", "ONBATT", "ONBATTERY"}
_ONLINE_WORDS = {"OL", "ONLINE"}
_LOW_WORDS = {"LB", "LOWBATT", "LOWBATTERY"}


def _words(status: Any) -> set[str]:
    text = str(status or "").upper().replace("ON BATT", "ONBATT").replace("LOW BATT", "LOWBATT")
    return {w for w in re.split(r"[^A-Z0-9]+", text) if w}


def power_state(status: Any) -> str:
    """ "on_battery", "online" or "unknown". A status that names neither, or nothing at all, is
    unknown, never online. A low-battery flag with no word about mains counts as on battery: a
    UPS that says only that cannot be proven to be on mains."""
    words = _words(status)
    if words & _ON_BATTERY_WORDS:
        return ON_BATTERY
    if words & _ONLINE_WORDS:
        return ONLINE
    if words & _LOW_WORDS:
        return ON_BATTERY
    return UNKNOWN


def battery_low(status: Any) -> bool:
    """The UPS's own low-battery flag, on mains or not."""
    return bool(_words(status) & _LOW_WORDS)


def is_reading(raw: dict[str, Any] | None) -> bool:
    """True when what a UPS connection returned is a reading: it carries a status. An error reply
    (stale data, driver not connected, access denied, an unknown UPS name) left only the UPS's
    name behind, and that was shown as a UPS that is online at 100 %."""
    return bool(raw) and (bool(str(raw.get("STATUS") or "").strip()) or bool(raw.get("PERMISSION_ERROR")))


def shutdown_reason(
    status: Any, charge: float | None, runtime: float | None, elapsed: float, cfg: dict[str, Any]
) -> str | None:
    """Why the safe shutdown starts now, or None. One rule: the first limit reached wins.

    The limits are the UPS's own low-battery signal, the minutes of runtime left and the charge;
    "after a set time on battery" joins them where it was chosen. A UPS that reports neither
    runtime nor charge used to leave only its own signal, which a UPS read over USB never sends:
    for such a UPS the set time applies always, so the rule cannot fail to fire."""
    if power_state(status) != ON_BATTERY:
        return None
    time_thresh = float(cfg.get("runtime_threshold_min", 5.0))
    batt_thresh = float(cfg.get("battery_threshold_pct", 20.0))
    timer_thresh = float(cfg.get("shutdown_timer_sec", 300.0))
    if battery_low(status):
        return "Hardware Low-Battery Flag (LB)"
    if runtime is not None and runtime <= time_thresh:
        return f"Runtime remaining below threshold ({runtime}m <= {time_thresh}m)"
    if charge is not None and charge <= batt_thresh:
        return f"Battery charge below threshold ({charge}% <= {batt_thresh}%)"
    blind = runtime is None and charge is None
    if (cfg.get("shutdown_policy") == "timer" or blind) and elapsed >= timer_thresh:
        why = "the UPS reports neither runtime nor charge; " if blind else ""
        return f"Time on battery exceeded threshold ({why}{int(elapsed)}s >= {int(timer_thresh)}s)"
    return None

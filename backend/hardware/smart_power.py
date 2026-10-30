"""Whether a drive is asleep, from one `smartctl -n standby` run (NARC-1).

smartctl's exit bit 1 (value 2) means "device open failed, device did not return an IDENTIFY
DEVICE structure, or device is in a low-power mode". Only the last prints a standby or sleep
message, so the message decides: a drive that couldn't be opened or didn't identify itself is
"unreachable", never "standby". It may be failing, unplugged or behind the wrong bridge type,
and it must not pass for a sleeping one.
"""

STANDBY_WORDS = ("DEVICE IS IN STANDBY", "DEVICE IS IN SLEEP", "STANDBY MODE", "SLEEP MODE")


def smartctl_power(returncode: int, output: str) -> str:
    """ "standby", "unreachable" or "active"."""
    out = (output or "").upper()
    if any(w in out for w in STANDBY_WORDS):
        return "standby"
    if int(returncode or 0) & 2:
        return "unreachable"
    return "active"


def is_standby(returncode: int, output: str) -> bool:
    return smartctl_power(returncode, output) == "standby"

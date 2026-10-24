"""Fails when an installed package differs from requirements.lock (ARCH-13).

CI installs the hash-locked set the image ships and then the test tools; this makes sure the
tools didn't upgrade or downgrade anything the image depends on.
"""

import re
import sys
from importlib import metadata

LOCK_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_versions(lock_text: str) -> dict[str, str]:
    out = {}
    for line in lock_text.splitlines():
        m = LOCK_LINE.match(line.strip())
        if m:
            out[_norm(m.group(1))] = m.group(2)
    return out


def mismatches(locked: dict[str, str], installed: dict[str, str]) -> list[str]:
    return [
        f"{name}: locked {want}, installed {installed.get(name, 'missing')}"
        for name, want in sorted(locked.items())
        if installed.get(name) != want
    ]


def main(path: str = "requirements.lock") -> int:
    with open(path, encoding="utf-8") as f:
        locked = locked_versions(f.read())
    installed = {_norm(d.metadata["Name"]): d.version for d in metadata.distributions()}
    bad = mismatches(locked, installed)
    for line in bad:
        print(f"::error title=Dependency drift::{line}")
    print(f"{len(locked)} locked packages checked, {len(bad)} differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))

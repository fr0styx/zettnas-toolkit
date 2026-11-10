"""Which Unraid and TrueNAS release lines have no recording yet (B9, run nightly in CI).

    python scripts/compat_trains.py [--summary $GITHUB_STEP_SUMMARY]

A release line is major.minor (Unraid 7.3, TrueNAS 25.10). The newest stable lines come from
Unraid's release list (releases.unraid.net/json) and TrueNAS's release tags on GitHub; a line counts
as covered when tests/compat/<platform>/ has a recording whose version starts with it. Exits 1 when
Unraid's newest line has none (Kiboto runs on Unraid every day); TrueNAS lines without one are listed,
since recording one needs a TrueNAS box (scripts/compat_capture.py truenas).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "compat"
UNRAID_FEED = "https://releases.unraid.net/json"
TRUENAS_TAGS = "https://api.github.com/repos/truenas/middleware/tags?per_page=100"
NEWEST = 2  # release lines per platform that should have a recording


def _get(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "kiboto-compat-check", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (two fixed https addresses)
        return json.loads(r.read())


def line(version: str) -> str:
    m = re.match(r"(\d+)\.(\d+)", version)
    return f"{m.group(1)}.{m.group(2)}" if m else ""


def unraid_lines(feed: object) -> list[str]:
    """Newest first, stable releases only."""
    out: list[str] = []
    for r in feed if isinstance(feed, list) else []:
        v = str((r or {}).get("version") or "")
        if re.fullmatch(r"\d+\.\d+\.\d+", v) and line(v) not in out:
            out.append(line(v))
    return sorted(out, key=lambda s: [int(x) for x in s.split(".")], reverse=True)


def truenas_lines(tags: object) -> list[str]:
    out: list[str] = []
    for t in tags if isinstance(tags, list) else []:
        m = re.fullmatch(r"TS-(\d+\.\d+)(\.\d+)*", str((t or {}).get("name") or ""))
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return sorted(out, key=lambda s: [int(x) for x in s.split(".")], reverse=True)


def recorded(platform: str) -> set[str]:
    folder = ROOT / platform
    return {line(p.name) for p in folder.iterdir() if p.is_dir()} if folder.is_dir() else set()


def report(unraid: list[str], truenas: list[str], have_unraid: set[str], have_truenas: set[str]) -> tuple[str, bool]:
    rows = ["| Platform | Release line | Recording |", "|---|---|---|"]
    for name, lines, have in (("Unraid", unraid, have_unraid), ("TrueNAS", truenas, have_truenas)):
        for ln in lines[:NEWEST]:
            rows.append(f"| {name} | {ln} | {'yes' if ln in have else '**none yet**'} |")
    missing_unraid = bool(unraid) and unraid[0] not in have_unraid
    return "\n".join(rows) + "\n", missing_unraid


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", default="")
    args = ap.parse_args(argv)
    text, missing = report(
        unraid_lines(_get(UNRAID_FEED)), truenas_lines(_get(TRUENAS_TAGS)), recorded("unraid"), recorded("truenas")
    )
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write("## Compatibility recordings\n\n" + text)
    if missing:
        print("Unraid's newest release line has no recording: run scripts/compat_capture.py unraid on a box with it.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

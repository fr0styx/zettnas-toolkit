"""Records what Kiboto reads from an Unraid or TrueNAS box, scrubbed, as a compatibility fixture (B9).

    python scripts/compat_capture.py unraid [--emhttp /var/local/emhttp] [--out tests/compat/unraid]
    TRUENAS_API_KEY=... python scripts/compat_capture.py truenas --url https://truenas.local [--out tests/compat/truenas]

TrueNAS: the REST answers Kiboto reads (TRUENAS_PATHS) go to tests/compat/truenas/<version>/*.json with
only the fields it uses, pools and datasets renamed (pool_1, pool_1/ds_1, …), shares and paths likewise,
and sizes made neutral.

Writes tests/compat/unraid/<version>/emhttp/{var,disks,shares}.ini. Only the keys Kiboto's parsers
read are kept (KEEP), and their values are made safe to publish:

- names that say whose box it is go: the host name becomes "tower", comments are dropped, share
  sections become share_1, share_2, … and user-named pools pool_1, … (disk1, parity, cache stay);
- serial numbers become stable fakes ("DISK-" and 8 hex digits of a hash, so the same disk keeps the
  same fake id across files);
- sizes, usage, temperatures and counters are replaced with neutral numbers that keep their relations
  (used + free = size, free <= size), so no figure from the real box is published.

The replay test (tests/test_b9_compat_recordings.py) runs Kiboto's Unraid parsers over every recording.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import io
import os
import re
import sys

FILES = ("var.ini", "disks.ini", "shares.ini")
KEEP = {
    "var.ini": {
        "version",
        "NAME",
        "SYS_MODEL",
        "mdState",
        "mdColor",
        "mdNumDisks",
        "mdNumDisabled",
        "mdNumInvalid",
        "mdNumMissing",
        "mdNumErased",
        "mdResync",
        "mdResyncAction",
        "mdResyncPos",
        "mdResyncSize",
        "mdResyncCorr",
        "sbSyncErrs",
        "sbSyncExit",
        "shareCachePool",
        "shareMoverActive",
        "fsState",
        "RemainFilesFromSecondary",
        "RemainFilesToSecondary",
        "TotalFilesFromSecondary",
        "TotalFilesToSecondary",
    },
    "disks.ini": {
        "name",
        "device",
        "id",
        "status",
        "type",
        "color",
        "temp",
        "size",
        "fsSize",
        "fsFree",
        "fsUsed",
        "fsType",
        "fsProfile",
        "fsState",
        "fsMountpoint",
        "numErrors",
        "numReads",
        "numWrites",
        "spundown",
        "rotational",
        "exportable",
        "nameOrig",
        "autotrim",
        "idx",
        "slots",
        "transport",
    },
    "shares.ini": {
        "name",
        "nameOrig",
        "comment",
        "allocator",
        "cachePool",
        "cachePool2",
        "useCache",
        "cow",
        "export",
        "exportNFS",
        "security",
        "free",
        "size",
        "used",
        "include",
        "exclude",
        "floor",
        "splitLevel",
    },
}
GENERIC_POOLS = re.compile(r"^(disk\d+|parity\d*|cache|flash|array)$")
SIZE_KEYS = {"size", "fsSize", "fsFree", "fsUsed", "free", "used"}
ZERO_KEYS = {
    "numErrors",
    "numReads",
    "numWrites",
    "mdResyncPos",
    "mdResyncCorr",
    "sbSyncErrs",
    "RemainFilesFromSecondary",
    "RemainFilesToSecondary",
    "TotalFilesFromSecondary",
    "TotalFilesToSecondary",
}


def _fake_id(value: str) -> str:
    return "DISK-" + hashlib.sha256(value.encode()).hexdigest()[:8].upper() if value else ""


def _read(path: str) -> configparser.RawConfigParser:
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str  # Unraid's keys are case-sensitive
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if not text.lstrip().startswith("["):
        text = "[global]\n" + text  # var.ini has no section header
    cp.read_string(text)
    return cp


def _q(v: str) -> str:
    return v if v.startswith('"') else f'"{v}"'


def scrub(name: str, cp: configparser.RawConfigParser, names: dict[str, str]) -> str:
    """The file's text with only KEEP's keys, scrubbed (names maps real share/pool names to fakes)."""
    out = io.StringIO()
    flat = name == "var.ini"
    for section in cp.sections():
        sec = section
        if name == "shares.ini":
            sec = names.setdefault(
                "share:" + section.strip('"'), f"share_{sum(k.startswith('share:') for k in names) + 1}"
            )
        elif name == "disks.ini" and not GENERIC_POOLS.match(section.strip('"')):
            sec = names.setdefault(
                "pool:" + section.strip('"'), f"pool_{sum(k.startswith('pool:') for k in names) + 1}"
            )
        if not flat:
            out.write(f'["{sec.strip(chr(34))}"]\n')
        values = {k: v.strip().strip('"') for k, v in cp.items(section) if k in KEEP[name]}
        if "size" in values or "fsSize" in values:
            values.update(_sizes(values))
        for key, value in values.items():
            if key == "NAME":
                value = "tower"
            elif key in ("comment", "shareComment"):
                value = ""
            elif key == "id":
                value = _fake_id(value)
            elif key in ("name", "nameOrig") and name == "shares.ini":
                value = names.get("share:" + value, sec.strip('"'))
            elif (
                key in ("name", "nameOrig", "cachePool", "cachePool2", "shareCachePool")
                and value
                and not GENERIC_POOLS.match(value)
            ):
                value = names.setdefault("pool:" + value, f"pool_{sum(k.startswith('pool:') for k in names) + 1}")
            elif key == "mdResyncSize" and value.isdigit():
                value = "7814037064"  # the array's size: a neutral two-disk figure
            elif key == "temp" and value.isdigit():
                value = "35"
            elif key in ZERO_KEYS and value.lstrip("-").isdigit():
                value = "0"
            elif key in ("fsMountpoint",) and value:
                value = "/mnt/" + names.get("pool:" + os.path.basename(value), os.path.basename(value))
            out.write(f"{key}={_q(value)}\n")
    return out.getvalue()


def _sizes(values: dict[str, str]) -> dict[str, str]:
    """Neutral sizes that keep their relations: a 4 TB disk, half used."""
    out = {}
    for key in SIZE_KEYS & values.keys():
        if not values[key].isdigit():
            continue
        out[key] = {
            "size": "3907018532",
            "fsSize": "3906988012",
            "fsUsed": "1953494006",
            "fsFree": "1953494006",
            "used": "1953494006",
            "free": "1953494006",
        }[key]
    return out


def capture_unraid(emhttp: str, out_root: str) -> str:
    cps = {f: _read(os.path.join(emhttp, f)) for f in FILES if os.path.exists(os.path.join(emhttp, f))}
    if "var.ini" not in cps:
        raise SystemExit(f"no var.ini in {emhttp}")
    version = cps["var.ini"].get("global", "version", fallback="unknown").strip('"')
    if not re.fullmatch(r"[0-9][0-9A-Za-z.\-]{0,30}", version):
        raise SystemExit(f"odd version {version!r}")
    folder = os.path.join(out_root, version, "emhttp")
    os.makedirs(folder, exist_ok=True)
    names: dict[str, str] = {}
    for f in ("disks.ini", "shares.ini", "var.ini"):  # pools first, so var.ini's cache pool maps the same
        if f in cps:
            with open(os.path.join(folder, f), "w", encoding="utf-8") as fh:
                fh.write(scrub(f, cps[f], names))
    return folder


TRUENAS_PATHS = {
    "pool.json": ("/pool", ("name", "status", "healthy", "size", "allocated", "free")),
    "pool_dataset.json": ("/pool/dataset?limit=500", ("id", "pool", "mountpoint", "type")),
    "sharing_smb.json": ("/sharing/smb", ("name", "path", "enabled")),
    "sharing_nfs.json": ("/sharing/nfs", ("path", "paths", "enabled")),
    "zfs_snapshot.json": ("/zfs/snapshot?limit=5000", ("name", "id", "dataset", "snapshot_name")),
}
NEUTRAL = {"size": 3985729650688, "allocated": 1992864825344, "free": 1992864825344}


class _Names:
    """Real pool/dataset/share names to stable fakes: tank/media/films -> pool_1/ds_1/ds_2."""

    def __init__(self):
        self.map: dict[str, str] = {}

    def part(self, kind: str, real: str) -> str:
        key = f"{kind}:{real}"
        if key not in self.map:
            self.map[key] = f"{kind}_{sum(k.startswith(kind + ':') for k in self.map) + 1}"
        return self.map[key]

    def dataset(self, real: str) -> str:
        bits = [b for b in str(real).split("/") if b]
        if not bits:
            return ""
        return "/".join([self.part("pool", bits[0])] + [self.part("ds", b) for b in bits[1:]])

    def path(self, real: str) -> str:
        real = str(real or "")
        return "/mnt/" + self.dataset(real[len("/mnt/") :]) if real.startswith("/mnt/") else ""


def scrub_truenas(name: str, rows: list, names: _Names) -> list:
    keep = TRUENAS_PATHS[name][1]
    out = []
    for row in rows if isinstance(rows, list) else []:
        r = {k: row.get(k) for k in keep if isinstance(row, dict) and k in row}
        for k in ("size", "allocated", "free"):
            if k in r:
                r[k] = NEUTRAL[k]
        if "name" in r and name == "pool.json":
            r["name"] = names.part("pool", r["name"])
        if "pool" in r:
            r["pool"] = names.part("pool", r["pool"])
        if "id" in r and name == "pool_dataset.json":
            r["id"] = names.dataset(r["id"])
        if "mountpoint" in r:
            r["mountpoint"] = names.path(r["mountpoint"])
        if name == "sharing_smb.json" and "name" in r:
            r["name"] = names.part("share", r["name"])
        if "path" in r:
            r["path"] = names.path(r["path"])
        if "paths" in r:
            r["paths"] = [names.path(x) for x in r["paths"] or []]
        if name == "zfs_snapshot.json":
            full = str(row.get("name") or row.get("id") or "")
            ds, _, snap = full.partition("@")
            fake = f"{names.dataset(ds)}@{names.part('snap', snap) if not snap.startswith('auto-') else snap}"
            r = {"name": fake, "id": fake, "dataset": names.dataset(ds), "snapshot_name": fake.split("@", 1)[1]}
        out.append(r)
    return out


def capture_truenas(url: str, key: str, out_root: str, get=None) -> str:
    import json
    import urllib.request

    def fetch(path):
        req = urllib.request.Request(f"{url.rstrip('/')}/api/v2.0{path}", headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (the maintainer's own TrueNAS)
            return json.loads(r.read())

    get = get or fetch
    info = get("/system/info")
    version = str(info.get("version") or "unknown").removeprefix("TrueNAS-SCALE-").removeprefix("TrueNAS-")
    if not re.fullmatch(r"[0-9][0-9A-Za-z.\-]{0,30}", version):
        raise SystemExit(f"odd version {version!r}")
    folder = os.path.join(out_root, version)
    os.makedirs(folder, exist_ok=True)
    names = _Names()
    for name, (path, _keep) in TRUENAS_PATHS.items():
        rows = scrub_truenas(name, get(path), names)
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1)
            fh.write("\n")
    return folder


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record what Kiboto reads from Unraid, scrubbed (B9)")
    sub = ap.add_subparsers(dest="platform", required=True)
    u = sub.add_parser("unraid")
    u.add_argument("--emhttp", default="/var/local/emhttp")
    u.add_argument("--out", default="tests/compat/unraid")
    t = sub.add_parser("truenas")
    t.add_argument("--url", required=True)
    t.add_argument("--out", default="tests/compat/truenas")
    args = ap.parse_args(argv)
    if args.platform == "truenas":
        key = os.environ.get("TRUENAS_API_KEY", "")
        if not key:
            raise SystemExit("set TRUENAS_API_KEY")
        folder = capture_truenas(args.url, key, args.out)
    else:
        folder = capture_unraid(args.emhttp, args.out)
    print(f"recorded {folder}; read it before committing")
    return 0


if __name__ == "__main__":
    sys.exit(main())

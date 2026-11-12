"""Delete a pool and erase its drives (S29: the owner chose to build it, 12 Nov 2026: A + B).

The danger is erasing a drive that is not in the pool, so nothing here guesses:

- the pool's drives come from the pool's own tool (ZFS, Btrfs, mdadm), never from names or rules
  of thumb, and every one is checked on disk: its label must carry this pool's id;
- one drive that cannot be confirmed refuses the whole erase, before anything changes;
- other kinds of pool (Unraid's array and pools, a plain disk) are not offered: the host's own
  settings delete them (decision B).

`run(cmd) -> (code, out, err)` is the caller's command runner, so tests use image files instead of
drives (decision A): mkfs.btrfs, blkid and wipefs work on files.
"""

import re
from collections.abc import Callable
from typing import Any

Run = Callable[[list[str]], tuple[int, str, str]]

ERASABLE_KINDS = ("zfs", "btrfs", "md")


class EraseRefused(Exception):
    """The erase would not be certain; nothing was changed."""


def kind_of(pool: Any) -> str:
    """'zfs', 'btrfs' or 'md' for a pool Kiboto can erase with certainty, else ''."""
    fs = str(getattr(pool, "fs_type", "") or "").lower()
    ptype = str(getattr(pool, "pool_type", "") or "").lower()
    if fs == "zfs" or ptype == "zfs_pool":
        return "zfs"
    if fs == "btrfs":
        return "btrfs"
    if ptype in ("mdadm", "md_raid", "raid") or str(getattr(pool, "id", "")).startswith("md"):
        return "md"
    return ""


def _kv(out: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def pool_id_and_devices(pool: Any, kind: str, run: Run) -> tuple[str, list[str]]:
    """The pool's own id and the devices its tool lists for it."""
    name = str(pool.id)
    if kind == "zfs":
        code, out, err = run(["zpool", "get", "-H", "-o", "value", "guid", name])
        if code != 0 or not out.strip():
            raise EraseRefused(f"ZFS did not give the id of {name}: {(err or out).strip()[:200]}")
        guid = out.strip()
        code, out, err = run(["zpool", "status", "-P", "-L", name])
        devs = re.findall(r"^\s+(/dev/\S+)\s", out, re.M) if code == 0 else []
        return guid, devs
    if kind == "btrfs":
        where = str(getattr(pool, "mountpoint", "") or name)
        code, out, err = run(["btrfs", "filesystem", "show", where])
        m = re.search(r"uuid:\s*([0-9a-f-]{36})", out or "")
        if code != 0 or not m:
            raise EraseRefused(f"Btrfs did not give the id of {name}: {(err or out).strip()[:200]}")
        return m.group(1), re.findall(r"\spath\s+(\S+)", out)
    if kind == "md":
        dev = name if name.startswith("/dev/") else f"/dev/{name}"
        code, out, err = run(["mdadm", "--detail", "--export", dev])
        info = _kv(out) if code == 0 else {}
        if not info.get("MD_UUID"):
            raise EraseRefused(f"mdadm did not give the id of {name}: {(err or out).strip()[:200]}")
        devs = [v for k, v in info.items() if re.fullmatch(r"MD_DEVICE_\w+_DEV", k)]
        return info["MD_UUID"], devs
    raise EraseRefused("Kiboto deletes only ZFS, Btrfs and mdadm pools; delete this one in the host's own settings.")


def label_of(dev: str, kind: str, run: Run) -> str:
    """The pool id written on the device itself ('' when there is none)."""
    if kind == "zfs":
        code, out, _ = run(["zdb", "-l", dev])
        m = re.search(r"^\s*pool_guid:\s*(\d+)", out or "", re.M) if code == 0 else None
        return m.group(1) if m else ""
    if kind == "btrfs":
        code, out, _ = run(["blkid", "-p", "-o", "export", dev])
        info = _kv(out) if code == 0 else {}
        return info.get("UUID", "") if info.get("TYPE") == "btrfs" else ""
    if kind == "md":
        code, out, _ = run(["mdadm", "--examine", "--export", dev])
        return _kv(out).get("MD_UUID", "") if code == 0 else ""
    return ""


def plan(pool: Any, run: Run) -> dict[str, Any]:
    """What would be erased, every drive confirmed on disk; raises EraseRefused otherwise."""
    kind = kind_of(pool)
    if not kind:
        raise EraseRefused(
            "Kiboto deletes only ZFS, Btrfs and mdadm pools; delete this one in the host's own settings."
        )
    pid, devices = pool_id_and_devices(pool, kind, run)
    if not devices:
        raise EraseRefused(f"{pool.name}: its drives could not be listed, so nothing is erased.")
    drives = [{"device": d, "label": label_of(d, kind, run)} for d in devices]
    stray = [d["device"] for d in drives if d["label"] != pid]
    if stray:
        raise EraseRefused(f"{', '.join(stray)} could not be confirmed as part of {pool.name}, so nothing is erased.")
    return {
        "pool": str(pool.id),
        "name": str(pool.name),
        "kind": kind,
        "id": pid,
        "drives": [d["device"] for d in drives],
        "mountpoint": getattr(pool, "mountpoint", "") or "",
    }


def execute(p: dict[str, Any], run: Run) -> list[str]:
    """Stops the pool, then erases each confirmed drive's signatures. Returns the drives erased."""
    kind, name = p["kind"], p["pool"]
    if kind == "zfs":
        code, out, err = run(["zpool", "destroy", "-f", name])
        if code != 0:
            raise EraseRefused(f"ZFS did not delete {name}: {(err or out).strip()[:200]}")
    else:
        if p.get("mountpoint"):
            code, out, err = run(["umount", p["mountpoint"]])
            if code != 0:
                raise EraseRefused(f"{p['name']} is in use and was not unmounted: {(err or out).strip()[:200]}")
        if kind == "md":
            run(["mdadm", "--stop", name if name.startswith("/dev/") else f"/dev/{name}"])
    erased = []
    for dev in p["drives"]:
        if kind == "zfs":
            run(["zpool", "labelclear", "-f", dev])
        elif kind == "md":
            run(["mdadm", "--zero-superblock", dev])
        code, out, err = run(["wipefs", "-a", dev])
        if code != 0:
            raise EraseRefused(f"{dev} was not erased: {(err or out).strip()[:200]}; the drives before it were.")
        erased.append(dev)
    return erased

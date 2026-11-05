"""Snapshot round trips on real pools (REL-4, FEAT-02, NREL-5, NREL-7), from the released image.

ZettNAS's own storage code (the generic Linux adapter and snapshot_service) runs against a scratch
folder on a btrfs pool and a scratch ZFS dataset, never against shares that are in use:

- btrfs: a new share is a subvolume; a snapshot is taken, listed and deleted; the share is changed
  and rolled back by a swap (NREL-7), with the safety snapshot kept; a plain folder share becomes a
  subvolume ("Make it snapshot-ready") with its files intact and can then be snapshotted.
- ZFS: a new share is a dataset; a snapshot is taken (its ZettNAS name kept in a user property),
  listed and deleted; the share is rolled back by copying back; a plain folder share becomes a
  dataset.

Everything made is removed at the end, and a scratch place that already holds something is
refused. Run it in the released image with the rights the app has (CAP_SYS_ADMIN; /dev/zfs for
ZFS) and a throwaway data folder:

    docker run --rm --cap-add SYS_ADMIN --device /dev/zfs -e DATA_DIR=/tmp/rt-data \\
      -v <empty folder on a btrfs pool>:/rt-btrfs -v $PWD/scripts:/rt-scripts:ro \\
      --entrypoint python3 -w /app <image> /rt-scripts/hardware_snapshots.py \\
      --btrfs /rt-btrfs --zfs-scratch <pool>/<new dataset name>

The log says PASS or FAIL for each step; the exit code is the number of failures.
"""

import argparse
import os
import shutil
import subprocess
import sys
import traceback

ZFS_MOUNT = "/rt-zfs"


def _run(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


class Steps:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""), flush=True)
        self.failed += 0 if ok else 1
        return ok


def _use_pool(path: str) -> None:
    """The scratch place is the pool for this run: shares may be made inside it (SEC-06)."""
    from backend import config

    config.POOL_PATH = path


def _round_trip(steps: Steps, pal, share_name: str, path: str, fs: str) -> None:
    """Snapshot, change, roll back, check; then delete the snapshots."""
    from backend.services import snapshot_service

    _write(os.path.join(path, "a.txt"), "first")
    taken = snapshot_service.take(share_name, schedule={"keep": 5, "immutable_days": 0}, pal=pal)
    steps.check(f"{fs}: snapshot taken", bool(taken.get("ok")), str(taken.get("detail")))
    names = [s.get("name") for s in pal.list_snapshots("")]
    steps.check(f"{fs}: snapshot listed", taken["name"] in names, ", ".join(map(str, names)))
    _write(os.path.join(path, "a.txt"), "changed")
    _write(os.path.join(path, "b.txt"), "new")
    out = snapshot_service.rollback(taken["name"], pal=pal)
    want = "swap" if fs == "btrfs" else None
    steps.check(
        f"{fs}: rolled back ({out.get('method') or 'copy'})", want is None or out.get("method") == want, str(out)
    )
    steps.check(
        f"{fs}: files as in the snapshot",
        _read(os.path.join(path, "a.txt")) == "first" and not os.path.exists(os.path.join(path, "b.txt")),
    )
    names = [s.get("name") for s in pal.list_snapshots("")]
    steps.check(
        f"{fs}: the state before the rollback kept", out.get("safety_snapshot") in names, ", ".join(map(str, names))
    )
    for n in names:
        if str(n).startswith(f"{share_name}@"):
            res = pal.delete_snapshot("", n)
            steps.check(
                f"{fs}: snapshot deleted ({n.split('@', 1)[1]})",
                res.get("status") in ("deleted", "ok") or res.get("success") is True,
                str(res),
            )
    left = [s.get("name") for s in pal.list_snapshots("") if str(s.get("name")).startswith(f"{share_name}@")]
    steps.check(f"{fs}: no snapshot left", not left, ", ".join(map(str, left)))


def btrfs(steps: Steps, root: str) -> None:
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter, is_subvolume

    if os.listdir(root):
        steps.check("btrfs: the scratch folder is empty", False, root)
        return
    _use_pool(root)
    pal = GenericLinuxStorageAdapter(pool_path=root)
    made: list[str] = []
    try:
        share = os.path.join(root, "rt-sub")
        pal.create_share("rt-sub", share, export_smb=False)
        made.append(share)
        steps.check("btrfs: a new share is a subvolume", is_subvolume(share))
        _round_trip(steps, pal, "rt-sub", share, "btrfs")

        folder = os.path.join(root, "rt-folder")
        os.makedirs(os.path.join(folder, "photos"))
        made.append(folder)
        _write(os.path.join(folder, "photos", "p.txt"), "kept")
        steps.check("btrfs: a folder share can be made snapshot-ready", pal.can_convert(folder))
        old = pal.convert_to_subvolume(folder)
        shutil.rmtree(old)
        steps.check("btrfs: it is a subvolume now", is_subvolume(folder))
        steps.check("btrfs: its files are intact", _read(os.path.join(folder, "photos", "p.txt")) == "kept")
        _round_trip(steps, pal, "rt-folder", folder, "btrfs")
    except Exception as e:  # report the step that broke, then clean up
        steps.check("btrfs: round trip ran to the end", False, f"{e}\n{traceback.format_exc()}")
    finally:
        for sub in [os.path.join(root, "@snapshots", n) for n in _ls(os.path.join(root, "@snapshots"))] + made:
            if os.path.exists(sub) and is_subvolume(sub):
                subprocess.run(["btrfs", "subvolume", "delete", sub], capture_output=True)
        for n in _ls(root):
            p = os.path.join(root, n)
            if is_subvolume(p):
                subprocess.run(["btrfs", "subvolume", "delete", p], capture_output=True)
            elif os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
        steps.check("btrfs: cleaned up", not _ls(root), ", ".join(_ls(root)))


def zfs(steps: Steps, dataset: str) -> None:
    from backend.hardware.pal.base import storage_tools
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter, zfs_dataset_at

    if not steps.check("zfs: the image's tools match the host's module", storage_tools()["zfs"]):
        return
    if "/" not in dataset or subprocess.run(["zfs", "list", dataset], capture_output=True).returncode == 0:
        steps.check("zfs: the scratch dataset is new", False, dataset)
        return
    _run("zfs", "create", "-o", f"mountpoint={ZFS_MOUNT}", dataset)
    try:
        _use_pool(ZFS_MOUNT)
        pal = GenericLinuxStorageAdapter(pool_path=ZFS_MOUNT)
        share = os.path.join(ZFS_MOUNT, "rt-ds")
        pal.create_share("rt-ds", share, export_smb=False)
        steps.check("zfs: a new share is a dataset", zfs_dataset_at(share) == f"{dataset}/rt-ds", zfs_dataset_at(share))
        _round_trip(steps, pal, "rt-ds", share, "zfs")

        folder = os.path.join(ZFS_MOUNT, "rt-folder")
        os.makedirs(folder)
        _write(os.path.join(folder, "p.txt"), "kept")
        steps.check("zfs: a folder share can be made snapshot-ready", pal.can_convert(folder))
        old = pal.convert_to_subvolume(folder)
        shutil.rmtree(old)
        steps.check(
            "zfs: it is a dataset now", zfs_dataset_at(folder) == f"{dataset}/rt-folder", zfs_dataset_at(folder)
        )
        steps.check("zfs: its files are intact", _read(os.path.join(folder, "p.txt")) == "kept")
    except Exception as e:
        steps.check("zfs: round trip ran to the end", False, f"{e}\n{traceback.format_exc()}")
    finally:
        holds = _run("zfs", "list", "-H", "-t", "snapshot", "-o", "name", "-r", dataset).split()
        for snap in holds:
            for line in _run("zfs", "holds", "-H", snap).splitlines():
                tag = line.split("\t")[1]
                subprocess.run(["zfs", "release", tag, snap], capture_output=True)
        done = subprocess.run(["zfs", "destroy", "-r", dataset], capture_output=True, text=True)
        steps.check("zfs: cleaned up", done.returncode == 0, done.stderr.strip())


def _ls(path: str) -> list[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Snapshot round trips on real pools.")
    ap.add_argument("--btrfs", default="", help="an empty folder on a btrfs pool")
    ap.add_argument("--zfs-scratch", default="", help="a ZFS dataset to create for the run, e.g. tank/zn-roundtrip")
    args = ap.parse_args(argv)
    if not args.btrfs and not args.zfs_scratch:
        ap.error("give --btrfs, --zfs-scratch or both")
    sys.path.insert(0, os.getcwd())
    steps = Steps()
    if args.btrfs:
        btrfs(steps, os.path.realpath(args.btrfs))
    if args.zfs_scratch:
        zfs(steps, args.zfs_scratch)
    print(f"{'PASS' if not steps.failed else 'FAIL'}  {steps.failed} step(s) failed", flush=True)
    return steps.failed


if __name__ == "__main__":
    sys.exit(main())

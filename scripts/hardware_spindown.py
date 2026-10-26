"""Does ZettNAS keep spinning disks awake? A read-only measurement for the self-hosted runner (PERF-2).

Nothing here talks to a drive: no hdparm, no smartctl, no reads of the disks themselves. It
samples what the kernel already counts, every --interval seconds for --minutes:

- /proc/diskstats: sectors read and written per disk; a disk with no I/O is idle.
- /sys/block/<disk>/queue/rotational: which disks spin (SSDs and NVMe are left out).
- /proc/<backend pid>/io: bytes the ZettNAS backend read from and wrote to storage.

A disk that has been idle for --sleep-after minutes would be asleep with a typical spin-down
timer. Its spin state can't be read without asking the drive, so "no I/O" stands in for it.
The budget, wakes: how often such a disk saw I/O in an interval in which the backend did
storage I/O too (the backend may have woken it). 0 passes. Other programs' I/O is not counted.

The public log says only PASS, FAIL or SKIP; the per-disk numbers go to --results/spindown/.
"""

import argparse
import json
import os
import sys
import time

HOST_PROC = os.environ.get("HOST_PROC", "/host/proc")
HOST_SYS = os.environ.get("HW_HOST_SYS", "/sys")


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def rotational_disks(sys_root=HOST_SYS):
    """Whole disks that spin (sda, sdb, ...), not partitions, SSDs, NVMe, loop or md devices."""
    out = []
    try:
        names = sorted(os.listdir(os.path.join(sys_root, "block")))
    except OSError:
        return out
    for name in names:
        if name.startswith(("loop", "ram", "zram", "md", "dm-", "nvme", "sr")):
            continue
        if _read(os.path.join(sys_root, "block", name, "queue", "rotational")).strip() == "1":
            out.append(name)
    return out


def disk_sectors(proc=HOST_PROC):
    """{disk: sectors read + written} from /proc/diskstats."""
    out = {}
    for line in _read(os.path.join(proc, "diskstats")).splitlines():
        parts = line.split()
        if len(parts) >= 10:
            out[parts[2]] = int(parts[5]) + int(parts[9])
    return out


def backend_pid(proc=HOST_PROC):
    try:
        names = os.listdir(proc)
    except OSError:
        return None
    for name in names:
        if name.isdigit():
            cmd = _read(os.path.join(proc, name, "cmdline")).replace("\0", " ")
            if "backend.main" in cmd and "fan_watchdog" not in cmd:
                return name
    return None


def backend_io(pid, proc=HOST_PROC):
    """Bytes the backend read from and wrote to storage (not the page cache), or None."""
    if not pid:
        return None
    vals = {}
    for line in _read(os.path.join(proc, pid, "io")).splitlines():
        key, _, val = line.partition(":")
        if key in ("read_bytes", "write_bytes"):
            vals[key] = int(val)
    return vals.get("read_bytes", 0) + vals.get("write_bytes", 0) if vals else None


def analyse(samples, disks, interval, sleep_after_s):
    """Per disk: longest idle stretch, intervals with I/O, and wakes after a long idle stretch that
    coincided with backend storage I/O. samples: [(t, {disk: sectors}, backend_bytes or None)]."""
    report = {}
    for d in disks:
        idle = 0.0
        longest = 0.0
        busy = 0
        wakes = 0
        for (t0, s0, b0), (t1, s1, b1) in zip(samples, samples[1:], strict=False):  # consecutive pairs
            dt = t1 - t0
            active = s1.get(d, 0) != s0.get(d, 0)
            if not active:
                idle += dt
                longest = max(longest, idle)
                continue
            busy += 1
            backend_busy = b0 is not None and b1 is not None and b1 != b0
            if idle >= sleep_after_s and backend_busy:
                wakes += 1
            idle = 0.0
        report[d] = {"longest_idle_min": round(longest / 60, 1), "busy_intervals": busy, "wakes": wakes}
    return report


def measure(minutes, interval, proc=HOST_PROC, sys_root=HOST_SYS, sleep=time.sleep, clock=time.monotonic):
    disks = rotational_disks(sys_root)
    pid = backend_pid(proc)
    samples = []
    end = clock() + minutes * 60
    while True:
        samples.append((clock(), disk_sectors(proc), backend_io(pid, proc)))
        if clock() >= end:
            break
        sleep(interval)
    return disks, pid, samples


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument(
        "--sleep-after", type=float, default=10, help="minutes of no I/O after which a disk counts as asleep"
    )
    ap.add_argument("--results", default=os.environ.get("HW_RESULTS_DIR", "/results"))
    args = ap.parse_args(argv)

    disks, pid, samples = measure(args.minutes, args.interval)
    if not disks:
        print("SKIP spindown (no spinning disks visible)")
        return 0
    if not pid:
        print("SKIP spindown (the ZettNAS backend is not running)")
        return 0
    report = analyse(samples, disks, args.interval, args.sleep_after * 60)
    wakes = sum(r["wakes"] for r in report.values())
    print(f"{'PASS' if wakes == 0 else 'FAIL'} spindown")
    if wakes:
        print(
            "::warning title=Spin-down::a spinning disk saw I/O after a long idle stretch while ZettNAS did storage I/O"
        )
    try:
        out = os.path.join(args.results, "spindown")
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, time.strftime("%Y-%m-%d-%H%M") + ".json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "minutes": args.minutes,
                    "interval_s": args.interval,
                    "sleep_after_min": args.sleep_after,
                    "disks": report,
                },
                f,
                indent=1,
            )
    except OSError as e:
        print(f"results not saved: {e.strerror}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

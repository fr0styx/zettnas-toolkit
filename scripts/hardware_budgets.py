"""Performance budgets measured on real hardware (PERF-10), for the self-hosted runner.

Reads the host's /proc (mounted read-only at HOST_PROC, default /host/proc) and soaks for
--seconds (default 300) while nobody uses the app:

  idle-cpu        backend CPU, % of one core            <= 1.0
  wakeups         backend context switches per minute    <= 1500
  backend-memory  backend resident memory, MB            <= 200
  ai-memory       chat-model server memory, MB           <= 1024 (after 15 idle minutes)

The public log says only PASS or FAIL per budget (the repository's Actions logs are public and
must not carry numbers from a private server). The numbers go to --results/<date>.json on the
machine itself. Budgets can be tuned with HW_BUDGET_<NAME> (e.g. HW_BUDGET_IDLE_CPU=1.5).
Failed budgets are reported as warnings; with --strict the exit code is 1 (a hard gate).
"""

import argparse
import json
import os
import sys
import time

HOST_PROC = os.environ.get("HOST_PROC", "/host/proc")
BUDGETS = {
    "idle-cpu": float(os.environ.get("HW_BUDGET_IDLE_CPU", "1.0")),
    "wakeups": float(os.environ.get("HW_BUDGET_WAKEUPS", "1500")),
    "backend-memory": float(os.environ.get("HW_BUDGET_BACKEND_MEMORY", "200")),
    "ai-memory": float(os.environ.get("HW_BUDGET_AI_MEMORY", "1024")),
}
CHAT_SERVERS = ("ovms", "ollama", "llama-server", "vllm")
APP_PORT = int(os.environ.get("HW_APP_PORT", "8082"))
IDLE_BUDGETS = ("idle-cpu", "wakeups")  # only meaningful with nobody using the app
BACKEND_BUDGETS = ("idle-cpu", "wakeups", "backend-memory")  # meaningless if the backend restarted mid-soak


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def processes(proc=HOST_PROC):
    """[(pid, cmdline)] of every process the host shows."""
    out = []
    for name in os.listdir(proc):
        if name.isdigit():
            cmd = _read(os.path.join(proc, name, "cmdline")).replace("\0", " ").strip()
            if cmd:
                out.append((name, cmd))
    return out


def backend_pid(procs, proc=HOST_PROC):
    """The backend: of the processes running backend.main, the largest (helpers match too)."""
    found = [pid for pid, cmd in procs if "backend.main" in cmd and "fan_watchdog" not in cmd]
    return max(found, key=lambda pid: rss_mb(pid, proc), default=None)


def cpu_ticks(pid, proc=HOST_PROC):
    stat = _read(os.path.join(proc, pid, "stat"))
    fields = stat[stat.rfind(")") + 2 :].split()
    return int(fields[11]) + int(fields[12]) if len(fields) > 12 else 0


def context_switches(pid, proc=HOST_PROC):
    total = 0
    task_dir = os.path.join(proc, pid, "task")
    try:
        tids = os.listdir(task_dir)
    except OSError:
        return 0
    for tid in tids:
        for line in _read(os.path.join(task_dir, tid, "status")).splitlines():
            if line.startswith(("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")):
                total += int(line.split()[1])
    return total


def rss_mb(pid, proc=HOST_PROC):
    for line in _read(os.path.join(proc, pid, "status")).splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


def chat_server_mb(procs, proc=HOST_PROC):
    total = 0.0
    for pid, cmd in procs:
        exe = cmd.split()[0].rsplit("/", 1)[-1]
        if any(name in exe for name in CHAT_SERVERS):
            total += rss_mb(pid, proc)
    return round(total, 1)


def viewers(pid, proc=HOST_PROC, port=APP_PORT):
    """Open connections to the app's web port, seen from its own network namespace."""
    n = 0
    for name in ("tcp", "tcp6"):
        for line in _read(os.path.join(proc, pid, "net", name)).splitlines()[1:]:
            parts = line.split()
            if len(parts) > 3 and parts[3] == "01" and int(parts[1].rsplit(":", 1)[1], 16) == port:
                n += 1
    return n


def measure(seconds, proc=HOST_PROC, sleep=time.sleep, clock=time.time):
    procs = processes(proc)
    pid = backend_pid(procs, proc)
    if not pid:
        raise SystemExit("the ZettNAS backend is not running on this machine")
    hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    seen = viewers(pid, proc)
    t0, c0, s0 = clock(), cpu_ticks(pid, proc), context_switches(pid, proc)
    sleep(seconds)
    t1, c1, s1 = clock(), cpu_ticks(pid, proc), context_switches(pid, proc)
    seen = max(seen, viewers(pid, proc))
    elapsed = max(1e-6, t1 - t0)
    # a deploy or a crash during the soak: the counters belong to two processes
    restarted = backend_pid(processes(proc), proc) != pid or c1 < c0 or s1 < s0
    return {
        "restarted": restarted,
        "viewers": seen,
        "idle-cpu": round(100 * (c1 - c0) / hz / elapsed, 2),
        "wakeups": round((s1 - s0) / elapsed * 60),
        "backend-memory": round(rss_mb(pid, proc), 1),
        "ai-memory": chat_server_mb(processes(proc), proc),
    }


def skip_reason(values, name):
    """Why a budget can't be judged this time, or None."""
    if values.get("restarted") and name in BACKEND_BUDGETS:
        return "the backend restarted during the soak"
    if values.get("viewers") and name in IDLE_BUDGETS:
        return "someone was using the app"
    return None


def verdicts(values, budgets=BUDGETS):
    """True/False per budget; None (skipped) when it can't be judged (skip_reason)."""
    return {
        name: (None if skip_reason(values, name) else values[name] <= limit)
        for name, limit in budgets.items()
        if name in values
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--results", default=os.environ.get("HW_RESULTS_DIR", "/results"))
    ap.add_argument("--strict", action="store_true", help="exit 1 when a budget fails (a hard gate)")
    args = ap.parse_args(argv)
    values = measure(args.seconds)
    ok = verdicts(values)
    for name in BUDGETS:
        if ok.get(name) is None:
            print(f"SKIP {name} ({skip_reason(values, name)})")
            continue
        print(f"{'PASS' if ok.get(name) else 'FAIL'} {name}")
        if not ok.get(name):
            print(f"::warning title=Hardware budget::{name} is over its budget")
    try:
        os.makedirs(args.results, exist_ok=True)
        path = os.path.join(args.results, time.strftime("%Y-%m-%d-%H%M") + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"values": values, "budgets": BUDGETS, "pass": ok}, f, indent=1)
    except OSError as e:
        print(f"results not saved: {e.strerror}")
    return 1 if args.strict and any(v is False for v in ok.values()) else 0


if __name__ == "__main__":
    sys.exit(main())

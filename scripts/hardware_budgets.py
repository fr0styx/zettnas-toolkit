"""Performance budgets measured on real hardware (PERF-10), for the self-hosted runner.

Reads the host's /proc (mounted read-only at HOST_PROC, default /host/proc) and soaks for
--seconds (default 300) while nobody uses the app. Everything in the backend's container counts
(its cgroup: helper processes, the healthcheck, tools it starts), sampled every --interval:

  idle-cpu        container CPU, % of one core                    <= 1.0
  wakeups         container voluntary context switches per minute  <= 1500
  spawns          processes started in the container per minute    <= 10
  backend-memory  backend resident memory, MB                      <= 200
  ai-memory       chat-model server memory, MB                     <= 1024 (after 15 idle minutes)

With --pid and --scope tree it measures one process and its children instead (the PR-time idle
minute in CI, where the job's cgroup holds the runner too). Connections from the machine itself
(127.0.0.1, ::1: the healthcheck, a local probe) don't count as someone using the app.

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
    "spawns": float(os.environ.get("HW_BUDGET_SPAWNS", "10")),
    "backend-memory": float(os.environ.get("HW_BUDGET_BACKEND_MEMORY", "200")),
    "ai-memory": float(os.environ.get("HW_BUDGET_AI_MEMORY", "1024")),
}
CHAT_SERVERS = ("ovms", "ollama", "llama-server", "vllm")
APP_PORT = int(os.environ.get("HW_APP_PORT", "8082"))
IDLE_BUDGETS = ("idle-cpu", "wakeups", "spawns")  # only meaningful with nobody using the app
BACKEND_BUDGETS = ("idle-cpu", "wakeups", "spawns", "backend-memory")  # meaningless if the backend restarted
LOOPBACK = ("0100007F", "0000000000000000FFFF00000100007F", "00000000000000000000000001000000")


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def pids(proc=HOST_PROC):
    try:
        return [name for name in os.listdir(proc) if name.isdigit()]
    except OSError:
        return []


def processes(proc=HOST_PROC):
    """[(pid, cmdline)] of every process the host shows."""
    out = []
    for name in pids(proc):
        cmd = _read(os.path.join(proc, name, "cmdline")).replace("\0", " ").strip()
        if cmd:
            out.append((name, cmd))
    return out


def backend_pid(procs, proc=HOST_PROC):
    """The backend: of the processes running backend.main, the largest (helpers match too)."""
    found = [pid for pid, cmd in procs if "backend.main" in cmd and "fan_watchdog" not in cmd]
    return max(found, key=lambda pid: rss_mb(pid, proc), default=None)


def _stat(pid, proc=HOST_PROC):
    """The fields of /proc/<pid>/stat after the command name ([] when it's gone)."""
    stat = _read(os.path.join(proc, pid, "stat"))
    return stat[stat.rfind(")") + 2 :].split() if stat else []


def cpu_ticks(pid, proc=HOST_PROC):
    fields = _stat(pid, proc)
    return int(fields[11]) + int(fields[12]) if len(fields) > 12 else 0


def started(pid, proc=HOST_PROC):
    """When the process started (clock ticks since boot): a pid with another start is another process."""
    fields = _stat(pid, proc)
    return fields[19] if len(fields) > 19 else ""


def parent(pid, proc=HOST_PROC):
    fields = _stat(pid, proc)
    return fields[1] if len(fields) > 1 else ""


def cgroup(pid, proc=HOST_PROC):
    return _read(os.path.join(proc, pid, "cgroup")).strip()


def context_switches(pid, proc=HOST_PROC, kinds=("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")):
    total = 0
    task_dir = os.path.join(proc, pid, "task")
    try:
        tids = os.listdir(task_dir)
    except OSError:
        return 0
    for tid in tids:
        for line in _read(os.path.join(task_dir, tid, "status")).splitlines():
            if line.startswith(kinds):
                total += int(line.split()[1])
    return total


def wakeups(pid, proc=HOST_PROC):
    """Voluntary switches: a thread went to sleep and something woke it (a timer, I/O, a lock)."""
    return context_switches(pid, proc, ("voluntary_ctxt_switches",))


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
    """Open connections to the app's web port from another machine, seen from its own network
    namespace. Loopback ones (the healthcheck, a local probe) are not someone using the app."""
    n = 0
    for name in ("tcp", "tcp6"):
        for line in _read(os.path.join(proc, pid, "net", name)).splitlines()[1:]:
            parts = line.split()
            if len(parts) > 3 and parts[3] == "01" and int(parts[1].rsplit(":", 1)[1], 16) == port:
                if parts[2].rsplit(":", 1)[0].upper() not in LOOPBACK:
                    n += 1
    return n


class Members:
    """The processes being measured: the backend's cgroup (scope "cgroup"), or the backend and
    everything it started (scope "tree"). Each is keyed by (pid, start time)."""

    def __init__(self, root, scope, proc=HOST_PROC):
        self.proc = proc
        self.scope = scope
        self.root = root
        self.cgroup = cgroup(root, proc)
        if scope == "cgroup" and not self.cgroup:
            self.scope = "self"  # no cgroup to go by: the backend alone
        self.known = {}  # pid -> (start, member?)
        self.tree = {root}

    def current(self):
        out = []
        listed = pids(self.proc)
        if self.scope == "tree":  # parents before children
            listed.sort(key=lambda p: int(started(p, self.proc) or 0))
        for pid in listed:
            start = started(pid, self.proc)
            if not start:
                continue
            seen = self.known.get(pid)
            if seen is None or seen[0] != start:
                if self.scope == "cgroup":
                    member = cgroup(pid, self.proc) == self.cgroup
                elif self.scope == "tree":
                    member = pid == self.root or parent(pid, self.proc) in self.tree
                else:
                    member = pid == self.root
                seen = (start, member)
                self.known[pid] = seen
            if seen[1]:
                self.tree.add(pid)
                out.append((pid, start))
        return out


def measure(seconds, proc=HOST_PROC, sleep=time.sleep, clock=time.time, pid=None, scope="cgroup", interval=1.0):
    procs = processes(proc)
    pid = pid or backend_pid(procs, proc)
    if not pid:
        raise SystemExit("the ZettNAS backend is not running on this machine")
    hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    members = Members(pid, scope, proc)
    root_start = started(pid, proc)
    first = {}  # (pid, start) -> (ticks, wakeups) at its first sample; zero for one born mid-soak
    last = {}
    born = set()
    seen = viewers(pid, proc)
    t0 = clock()
    end = t0 + seconds
    sample = 0
    while True:
        for key in members.current():
            now = (cpu_ticks(key[0], proc), wakeups(key[0], proc))
            if key not in first:
                first[key] = now if sample == 0 else (0, 0)
                if sample:
                    born.add(key)
            last[key] = now
        sample += 1
        seen = max(seen, viewers(pid, proc))
        left = end - clock()
        if left <= 0:
            break
        sleep(min(interval, left))
    elapsed = max(1e-6, clock() - t0)
    ticks = sum(max(0, last[k][0] - first[k][0]) for k in last)
    woke = sum(max(0, last[k][1] - first[k][1]) for k in last)
    # a deploy or a crash during the soak: the backend measured at the end isn't the one at the start
    restarted = started(pid, proc) != root_start
    return {
        "restarted": restarted,
        "viewers": seen,
        "processes": len(last),
        "idle-cpu": round(100 * ticks / hz / elapsed, 2),
        "wakeups": round(woke / elapsed * 60),
        "spawns": round(len(born) / elapsed * 60, 1),
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
    ap.add_argument("--warmup", type=float, default=0, help="wait this long before measuring")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between samples")
    ap.add_argument("--pid", help="measure this process instead of finding the backend")
    ap.add_argument("--scope", choices=("cgroup", "tree"), default="cgroup")
    ap.add_argument("--only", help="comma-separated budgets to judge (default: all)")
    ap.add_argument("--results", default=os.environ.get("HW_RESULTS_DIR", "/results"))
    ap.add_argument(
        "--strict",
        nargs="?",
        const="all",
        help="exit 1 when a budget fails (a hard gate); optionally only for these comma-separated ones",
    )
    ap.add_argument("--show", action="store_true", help="print the numbers too (never on the private server)")
    args = ap.parse_args(argv)
    budgets = BUDGETS
    if args.only:
        budgets = {n: BUDGETS[n] for n in _names(ap, args.only)}
    strict = set(budgets) if args.strict == "all" else set(_names(ap, args.strict or ""))
    if args.warmup > 0:
        time.sleep(args.warmup)
    values = measure(args.seconds, pid=args.pid, scope=args.scope, interval=args.interval)
    ok = verdicts(values, budgets)
    for name in budgets:
        if ok.get(name) is None:
            print(f"SKIP {name} ({skip_reason(values, name)})")
            continue
        print(
            f"{'PASS' if ok.get(name) else 'FAIL'} {name}"
            + (f" ({values[name]} / {budgets[name]})" if args.show else "")
        )
        if not ok.get(name):
            print(f"::warning title=Hardware budget::{name} is over its budget")
    try:
        os.makedirs(args.results, exist_ok=True)
        path = os.path.join(args.results, time.strftime("%Y-%m-%d-%H%M") + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"values": values, "budgets": budgets, "pass": ok}, f, indent=1)
    except OSError as e:
        print(f"results not saved: {e.strerror}")
    return 1 if any(ok.get(name) is False for name in strict) else 0


def _names(ap, text):
    wanted = [n.strip() for n in text.split(",") if n.strip()]
    unknown = [n for n in wanted if n not in BUDGETS]
    if unknown:
        ap.error(f"unknown budget: {', '.join(unknown)}")
    return wanted


if __name__ == "__main__":
    sys.exit(main())

"""Runs pyright and fails if any file has more type errors than recorded (OPS-24).

python scripts/pyright_ratchet.py            # check
python scripts/pyright_ratchet.py --update   # record the current counts (after fixing some)
"""

import collections
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "pyright-baseline.json")
# a baseline well above today's counts would let new errors in unseen (NARC-3)
SLACK_PER_FILE = 2
SLACK_TOTAL = 25


def current():
    out = subprocess.run(["pyright", "--outputjson"], cwd=ROOT, capture_output=True, text=True)
    data = json.loads(out.stdout)
    counts = collections.Counter()
    by_file = collections.defaultdict(list)
    for d in data["generalDiagnostics"]:
        if d["severity"] != "error":
            continue
        rel = os.path.relpath(d["file"], ROOT)
        counts[rel] += 1
        by_file[rel].append(f"{rel}:{d['range']['start']['line'] + 1}: {d['message'].splitlines()[0]}")
    return dict(counts), by_file


def main():
    counts, by_file = current()
    if "--update" in sys.argv:
        with open(BASELINE, "w") as f:
            json.dump(dict(sorted(counts.items())), f, indent=1)
            f.write("\n")
        print(f"recorded {sum(counts.values())} pyright errors in {len(counts)} files")
        return 0
    baseline = {}
    if os.path.exists(BASELINE):
        with open(BASELINE) as f:
            baseline = json.load(f)
    worse = {f: n for f, n in counts.items() if n > baseline.get(f, 0)}
    total, base_total = sum(counts.values()), sum(baseline.values())
    if worse:
        for f, n in sorted(worse.items()):
            print(f"✗ {f}: {n} type errors (baseline {baseline.get(f, 0)})")
            for line in by_file[f][:10]:
                print("    " + line)
        return 1
    loose = {f: n for f, n in baseline.items() if n - counts.get(f, 0) > SLACK_PER_FILE}
    if loose or base_total - total > SLACK_TOTAL:
        for f, n in sorted(loose.items())[:10]:
            print(f"✗ {f}: {counts.get(f, 0)} type errors, baseline still {n}")
        print(
            f"✗ the baseline ({base_total}) is looser than today ({total}): run python scripts/pyright_ratchet.py --update"
        )
        return 1
    print(f"pyright: {total} errors (baseline {base_total}); no file got worse")
    return 0


if __name__ == "__main__":
    sys.exit(main())

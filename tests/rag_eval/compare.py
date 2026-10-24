"""Compare an eval result with a recorded baseline (AI-3).

    python -m tests.rag_eval.compare result.json tests/rag_eval/baseline_nightly.json [--tolerance 0.02]

Exits 1 when any recall@1, recall@5 or mrr@10 (overall, per language, per kind) or the answer
accuracy dropped by more than the tolerance; a missing baseline only prints the result.
"""

import argparse
import json
import os
import sys


def drops(now: dict, base: dict, tol: float) -> list[str]:
    out = []
    scopes = [("overall", now.get("overall"), base.get("overall"))]
    for group in ("by_language", "by_kind"):
        for k, v in (base.get(group) or {}).items():
            scopes.append((f"{group}.{k}", (now.get(group) or {}).get(k), v))
    for name, n, b in scopes:
        if not n or not b:
            continue
        for metric in ("recall@1", "recall@5", "mrr@10"):
            if metric in b and n.get(metric, 0) < b[metric] - tol:
                out.append(f"{name} {metric}: {b[metric]} -> {n.get(metric)}")
    if "answers" in base and "answers" in now and now["answers"]["accuracy"] < base["answers"]["accuracy"] - tol:
        out.append(f"answers accuracy: {base['answers']['accuracy']} -> {now['answers']['accuracy']}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("baseline")
    ap.add_argument("--tolerance", type=float, default=0.02)
    a = ap.parse_args()
    with open(a.result, encoding="utf-8") as f:
        now = json.load(f)
    if not os.path.exists(a.baseline):
        print(f"no baseline at {a.baseline}; result recorded only")
        return 0
    with open(a.baseline, encoding="utf-8") as f:
        base = json.load(f)
    found = drops(now, base, a.tolerance)
    for d in found:
        print("worse:", d)
    print("ok" if not found else f"{len(found)} metric(s) got worse")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

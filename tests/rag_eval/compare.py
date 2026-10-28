"""Compare an eval result with a recorded baseline (AI-3).

    python -m tests.rag_eval.compare result.json tests/rag_eval/baseline_nightly.json [--tolerance 0.02]

Exits 1 when any recall@1, recall@5 or mrr@10 (overall, per language, per kind), the answer
accuracy or the answers' faithfulness to their sources dropped by more than the tolerance, or the
answers' p95 first-token time grew by half (AI-16) or passed --first-token-p95-ms. Answers by
another model than the baseline's are not compared (their baseline is recorded from a run); a
missing baseline only prints the result.
"""

import argparse
import json
import os
import sys


def drops(now: dict, base: dict, tol: float, first_token_p95_ms: float | None = None) -> list[str]:
    out = []
    ft_now = ((now.get("answers") or {}).get("first_token") or {}).get("p95_ms")
    if first_token_p95_ms and ft_now and ft_now > first_token_p95_ms:
        out.append(f"answers first-token p95: {ft_now} ms (budget {first_token_p95_ms})")
    if "answers" in base and "answers" in now and base["answers"].get("model") != now["answers"].get("model"):
        base = {k: v for k, v in base.items() if k != "answers"}  # another model: not comparable
    scopes = [("overall", now.get("overall"), base.get("overall"))]
    for group in ("by_language", "by_kind", "by_split"):
        for k, v in (base.get(group) or {}).items():
            scopes.append((f"{group}.{k}", (now.get(group) or {}).get(k), v))
    for name, n, b in scopes:
        if not n or not b:
            continue
        for metric in ("recall@1", "recall@5", "all@5", "mrr@10"):
            if metric in b and n.get(metric, 0) < b[metric] - tol:
                out.append(f"{name} {metric}: {b[metric]} -> {n.get(metric)}")
    lb, ln = (base.get("latency") or {}).get("p95_units"), (now.get("latency") or {}).get("p95_units")
    if lb and ln and ln > lb * 1.5:
        out.append(f"search p95: {lb} -> {ln} units (more than half again as slow)")
    if "answers" in base and "answers" in now and now["answers"]["accuracy"] < base["answers"]["accuracy"] - tol:
        out.append(f"answers accuracy: {base['answers']['accuracy']} -> {now['answers']['accuracy']}")
    # faithfulness: the answers say only what their sources say (AI-16)
    for metric in ("faithfulness", "fully_supported"):
        b, n = (base.get("answers") or {}).get(metric), (now.get("answers") or {}).get(metric)
        if b is not None and n is not None and n < b - tol:
            out.append(f"answers {metric}: {b} -> {n}")
    ft_base = ((base.get("answers") or {}).get("first_token") or {}).get("p95_ms")
    if ft_base and ft_now and ft_now > ft_base * 1.5:
        out.append(f"answers first-token p95: {ft_base} -> {ft_now} ms (more than half again as slow)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("baseline")
    ap.add_argument("--tolerance", type=float, default=0.02)
    ap.add_argument("--first-token-p95-ms", type=float, default=None, help="fail above this p95 first-token time")
    a = ap.parse_args()
    with open(a.result, encoding="utf-8") as f:
        now = json.load(f)
    if not os.path.exists(a.baseline):
        print(f"no baseline at {a.baseline}; result recorded only")
        over = drops(now, {}, a.tolerance, a.first_token_p95_ms)
        for d in over:
            print("worse:", d)
        return 1 if over else 0
    with open(a.baseline, encoding="utf-8") as f:
        base = json.load(f)
    found = drops(now, base, a.tolerance, a.first_token_p95_ms)
    for d in found:
        print("worse:", d)
    print("ok" if not found else f"{len(found)} metric(s) got worse")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

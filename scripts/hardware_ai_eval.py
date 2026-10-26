"""The AI check on real hardware (AI-16, PERF-10), for the self-hosted runner.

Runs the search and answer eval (tests/rag_eval) against the model servers a ZettNAS install
actually uses (the embedder and the chat server, read-only: nothing is installed, pulled or
changed on them) and compares with the last recorded result of this machine.

    /opt/zn-eval/bin/python scripts/hardware_ai_eval.py \\
        --embedder http://zettnas-eg2:11434 --embedding-model embeddinggemma-2-ov --dim 768 \\
        --chat http://zettnas-ovms:8000/v1 --chat-model Qwen3-4B

The public log says only PASS, FAIL or SKIP per set (the repository's Actions logs are public
and must not carry numbers from a private server). Results and baselines are written to
--results/ai on the machine: the first run of a set, or a run with another model, records the
baseline. A set fails when a score drops by more than --tolerance.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETS = ("all", "documents")  # base + extended, and long / Office / scanned / multi-hop


def _isolated_env() -> None:
    """The app's code runs here without its data folder or the host's devices."""
    tmp = tempfile.mkdtemp(prefix="zettnas-ai-eval-")
    for name in ("data", "pool", "sys", "dev", "proc"):
        os.makedirs(os.path.join(tmp, name), exist_ok=True)
    os.environ.update(
        {
            "DATA_DIR": os.path.join(tmp, "data"),
            "POOL_PATH": os.path.join(tmp, "pool"),
            "BROWSE_ROOTS": os.path.join(tmp, "pool"),
            "HOST_SYS": os.path.join(tmp, "sys"),
            "HOST_DEV": os.path.join(tmp, "dev"),
            "HOST_PROC": os.path.join(tmp, "proc"),
            "ENABLE_FB": "0",
            "LED_PORT": os.path.join(tmp, "dev", "none"),
        }
    )


def lock_matches(lock_path: str, recorded_path: str = "/opt/zn-eval/lock.sha256") -> bool:
    """The runner's packages were installed from this checkout's requirements.lock."""
    try:
        with open(lock_path, "rb") as f:
            now = hashlib.sha256(f.read()).hexdigest()
        with open(recorded_path, encoding="utf-8") as f:
            return f.read().strip() == now
    except OSError:
        return False


def reachable(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def scores(result: dict) -> dict:
    """What a run is judged on (the per-query detail stays out of the baseline)."""
    keep = {k: result[k] for k in ("model", "set", "overall", "by_kind", "by_language", "by_split") if k in result}
    if "answers" in result:
        keep["answers"] = {k: v for k, v in result["answers"].items() if k != "wrong"}
    return keep


def verdict(now: dict, base: dict | None, chat_model: str, tolerance: float) -> tuple[str, list[str]]:
    """('PASS' | 'FAIL' | 'RECORDED', reasons). A first run or another model records a baseline."""
    from tests.rag_eval.compare import drops

    if not base or base.get("model") != now.get("model") or (base.get("answers") or {}).get("model") != chat_model:
        return "RECORDED", []
    found = drops(now, base, tolerance)
    return ("FAIL" if found else "PASS"), found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--embedder", default="http://zettnas-eg2:11434")
    ap.add_argument("--embedding-model", default="embeddinggemma-2-ov")
    ap.add_argument("--dim", type=int, default=768)
    ap.add_argument("--chat", default="http://zettnas-ovms:8000/v1")
    ap.add_argument("--chat-model", default="Qwen3-4B")
    ap.add_argument("--results", default=os.environ.get("HW_RESULTS_DIR", "/results"))
    ap.add_argument("--tolerance", type=float, default=0.03)
    ap.add_argument("--sets", default=",".join(SETS))
    args = ap.parse_args(argv)

    if not lock_matches(os.path.join(ROOT, "requirements.lock")):
        print("SKIP ai-eval (the runner image is behind requirements.lock: rebuild it, docs/HARDWARE_RUNNER.md)")
        return 0
    if not reachable(f"{args.embedder}/api/tags") or not reachable(f"{args.chat}/models"):
        print("SKIP ai-eval (the model servers are not reachable from the runner)")
        return 0

    _isolated_env()
    sys.path.insert(0, ROOT)
    from tests.rag_eval.run_eval import evaluate

    out_dir = os.path.join(args.results, "ai")
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M")
    failed = False
    for name in [s for s in args.sets.split(",") if s]:
        try:
            result = evaluate(
                model=args.embedding_model,
                dim=args.dim,
                which=name,
                host=args.embedder,
                answers_model=args.chat_model,
                llm_host=args.chat,
            )
        except Exception as e:  # the log stays free of details; the file gets them
            with open(os.path.join(out_dir, f"{stamp}-{name}-error.txt"), "w", encoding="utf-8") as f:
                f.write(f"{type(e).__name__}: {e}\n")
            print(f"FAIL ai-eval {name} (the eval did not finish)")
            failed = True
            continue
        now = scores(result)
        with open(os.path.join(out_dir, f"{stamp}-{name}.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        base_path = os.path.join(out_dir, f"baseline_{name}.json")
        try:
            with open(base_path, encoding="utf-8") as f:
                base = json.load(f)
        except (OSError, ValueError):
            base = None
        state, reasons = verdict(now, base, args.chat_model, args.tolerance)
        if state == "RECORDED":
            with open(base_path, "w", encoding="utf-8") as f:
                json.dump(now, f, ensure_ascii=False, indent=1)
            print(f"PASS ai-eval {name} (baseline recorded)")
        else:
            print(f"{state} ai-eval {name}")
            if reasons:
                failed = True
                with open(os.path.join(out_dir, f"{stamp}-{name}-worse.txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(reasons) + "\n")
                print(f"::warning title=AI eval::{name} scored lower than this machine's baseline")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

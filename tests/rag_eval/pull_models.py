"""Pull the eval's Ollama models and check each is the pinned build (NAI-10).

    python -m tests.rag_eval.pull_models [--host http://127.0.0.1:11434] embeddinggemma qwen3:4b

A tag like qwen3:4b can point at a new build upstream (a new model, template or quantisation),
which moves the eval's numbers with no change on our side. Each model's manifest digest is
checked against tests/rag_eval/models.json; a different one fails here, saying what changed,
instead of failing later as a quality drop. The pinned models and digests are printed, and added
to the job summary on GitHub Actions.
"""

import argparse
import json
import os
import sys
import urllib.request

PINS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models.json")


def full_name(model: str) -> str:
    return model if ":" in model else model + ":latest"


def _post(host: str, path: str, body: dict, timeout: float = 3600) -> dict:
    req = urllib.request.Request(
        host.rstrip("/") + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


def _get(host: str, path: str) -> dict:
    with urllib.request.urlopen(host.rstrip("/") + path, timeout=60) as resp:
        return json.loads(resp.read() or b"{}")


def installed_digests(host: str) -> dict[str, str]:
    out = {}
    for m in _get(host, "/api/tags").get("models") or []:
        digest = str(m.get("digest") or "")
        out[full_name(str(m.get("name") or m.get("model") or ""))] = (
            digest if digest.startswith("sha256:") else "sha256:" + digest
        )
    return out


def check(models: list[str], have: dict[str, str], pins: dict[str, str]) -> list[str]:
    """What differs from the pins: an unpinned model, a missing one or a different build."""
    problems = []
    for m in map(full_name, models):
        want, got = pins.get(m), have.get(m)
        if not want:
            problems.append(f"{m}: not pinned in tests/rag_eval/models.json (pulled {got or 'nothing'})")
        elif not got:
            problems.append(f"{m}: not installed after the pull")
        elif got != want:
            problems.append(
                f"{m}: upstream build changed ({got[:19]}, pinned {want[:19]}); run the nightly, "
                "re-record the baselines from its results and update models.json"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("models", nargs="+")
    args = ap.parse_args(argv)
    with open(PINS, encoding="utf-8") as f:
        pins = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    for m in args.models:
        _post(args.host, "/api/pull", {"model": m, "stream": False})
    have = installed_digests(args.host)
    lines = [f"- {full_name(m)} `{have.get(full_name(m), 'missing')[:19]}`" for m in args.models]
    print("Models:\n" + "\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("**Models**\n\n" + "\n".join(lines) + "\n\n")
    problems = check(args.models, have, pins)
    for p in problems:
        print("::error::" + p if os.environ.get("GITHUB_ACTIONS") else p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

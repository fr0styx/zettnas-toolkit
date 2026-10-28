"""Markdown summary of eval results for a workflow's step summary (AI-16).

python -m tests.rag_eval.summary eval-retrieval.json eval-documents.json >> "$GITHUB_STEP_SUMMARY"
"""

import json
import os
import sys


def render(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    out = [f"### {os.path.basename(path)} ({d.get('model')}, set {d.get('set')})\n"]
    out.append("| scope | recall@1 | recall@5 | mrr@10 |\n|---|---|---|---|")
    rows = (
        [("overall", d["overall"])]
        + list((d.get("by_kind") or {}).items())
        + list((d.get("by_language") or {}).items())
    )
    out += [f"| {k} | {v['recall@1']} | {v['recall@5']} | {v['mrr@10']} |" for k, v in rows]
    a = d.get("answers")
    if a:
        ft = a.get("first_token") or {}
        out.append(
            f"\nAnswers ({a['model']}): accuracy {a['accuracy']}, right source cited {a['source_hit']}, "
            f"first token p50 {ft.get('p50_ms')} ms / p95 {ft.get('p95_ms')} ms; by language {a['by_language']}\n"
        )
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    print("".join(render(p) for p in sys.argv[1:]))

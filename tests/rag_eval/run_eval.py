"""Retrieval and answer evaluation over tests/rag_eval (AI-11, AI-3).

40 home-NAS files in English, German, Chinese, French and Spanish (Markdown, text, CSV,
YAML, JSON, HTML, Python and shell) and three hand-written sets, asked the way a person would
ask. Files go through the real indexer and queries through the real search; nothing here is
tuned to the engine.

- queries.json: 200 queries, 5 per file, in the file's language (what CI gates on).
- queries_extended.json: 50 cross-language queries (asked in one language about a file in
  another) and 40 paraphrases that share few or no words with the file.
- qa.json: 97 questions with the facts a correct answer must contain, for answer quality.

    python -m tests.rag_eval.run_eval                                  # base set, lexical vectors (CI)
    python -m tests.rag_eval.run_eval --set extended                   # cross-language and paraphrase
    python -m tests.rag_eval.run_eval --model embeddinggemma --host http://127.0.0.1:11434 \\
        --set all --distractors 2000                                   # nightly: neural model, 2,000 extra files
    python -m tests.rag_eval.run_eval --model embeddinggemma --answers qwen3:4b   # answers, scored
"""

import argparse
import json
import os
import random
import re
import tempfile
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
FIXED_MTIME_NS = 1_700_000_000_000_000_000
SETS = {"base": "queries.json", "extended": "queries_extended.json"}


def load_queries(which: str = "base") -> list[dict]:
    names = list(SETS.values()) if which == "all" else [SETS[which]]
    out = []
    for name in names:
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            for q in json.load(f):
                out.append({"kind": "same-language", **q})
    return out


def load_qa() -> list[dict]:
    with open(os.path.join(HERE, "qa.json"), encoding="utf-8") as f:
        return json.load(f)


# Distractors: plausible household files on other subjects, generated the same way every time,
# so the right file has to beat thousands of others instead of 39.
_DISTRACT = {
    "en": (
        ["notes", "receipt", "log", "list", "plan", "letter"],
        [
            "The {a} for the {b} was moved to {d}.",
            "Remember to check the {a} before {d}.",
            "{n} {a} ordered for the {b}.",
            "Call about the {b} {a} on {d}.",
            "The {b} needs a new {a}; quote was {n} pounds.",
        ],
        [
            "garden",
            "shed",
            "bicycle",
            "printer",
            "piano",
            "garage",
            "school bag",
            "fridge",
            "lawn mower",
            "attic",
            "roof",
            "fence",
        ],
        ["filter", "battery", "lock", "cable", "hinge", "paint", "lamp", "warranty card", "spare key", "invoice"],
    ),
    "de": (
        ["notiz", "beleg", "liste", "plan", "brief"],
        [
            "Der {a} für den {b} kommt am {d}.",
            "Am {d} den {a} am {b} prüfen.",
            "{n} Stück {a} für den {b} bestellt.",
            "Wegen {b} und {a} am {d} anrufen.",
            "Der {b} braucht einen neuen {a}, Angebot {n} Euro.",
        ],
        [
            "Garten",
            "Keller",
            "Dachboden",
            "Fahrradschuppen",
            "Balkon",
            "Drucker",
            "Kühlschrank",
            "Rasenmäher",
            "Zaun",
            "Briefkasten",
        ],
        ["Schlüssel", "Akku", "Filter", "Lack", "Griff", "Kabel", "Ersatzteil", "Garantieschein", "Dübel", "Schlauch"],
    ),
    "fr": (
        ["note", "recu", "liste", "plan", "courrier"],
        [
            "Le {a} du {b} arrive le {d}.",
            "Vérifier le {a} du {b} avant le {d}.",
            "{n} {a} commandés pour le {b}.",
            "Appeler pour le {b} et le {a} le {d}.",
            "Le {b} a besoin d'un nouveau {a}, devis {n} euros.",
        ],
        ["jardin", "garage", "grenier", "balcon", "vélo", "réfrigérateur", "portail", "piano", "toit", "cellier"],
        [
            "filtre",
            "verrou",
            "câble",
            "joint",
            "pot de peinture",
            "tuyau",
            "bon de garantie",
            "double de clé",
            "chargeur",
            "store",
        ],
    ),
    "es": (
        ["nota", "recibo", "lista", "plan", "carta"],
        [
            "El {a} del {b} llega el {d}.",
            "Revisar el {a} del {b} antes del {d}.",
            "{n} {a} pedidos para el {b}.",
            "Llamar por el {b} y el {a} el {d}.",
            "El {b} necesita un {a} nuevo, presupuesto {n} euros.",
        ],
        ["jardín", "trastero", "balcón", "garaje", "frigorífico", "tejado", "buzón", "piano", "toldo", "patio"],
        [
            "filtro",
            "candado",
            "cable",
            "bisagra",
            "bote de pintura",
            "manguera",
            "cargador",
            "recambio",
            "mando",
            "enchufe",
        ],
    ),
    "zh": (
        ["笔记", "收据", "清单", "计划", "信件"],
        [
            "{b}的{a}在{d}送到。",
            "{d}之前检查{b}的{a}。",
            "给{b}订了{n}个{a}。",
            "{d}打电话问{b}的{a}。",
            "{b}需要换新的{a}，报价{n}元。",
        ],
        ["阳台", "车库", "花园", "储物间", "冰箱", "打印机", "屋顶", "信箱", "自行车", "钢琴"],
        ["滤芯", "电池", "门锁", "电线", "合页", "油漆", "水管", "充电器", "保修卡", "备用钥匙"],
    ),
}
_DATES = ["2 May", "14 June", "1 July", "30 August", "9 September", "21 November", "5 December"]


def write_distractors(folder: str, count: int, seed: int = 7) -> int:
    rng = random.Random(seed)
    langs = sorted(_DISTRACT)
    for i in range(count):
        lang = langs[i % len(langs)]
        kinds, templates, places, things = _DISTRACT[lang]
        lines = []
        for _ in range(rng.randint(4, 9)):
            lines.append(
                rng.choice(templates).format(
                    a=rng.choice(things), b=rng.choice(places), d=rng.choice(_DATES), n=rng.randint(2, 900)
                )
            )
        path = os.path.join(folder, lang, f"{rng.choice(kinds)}_{i:05d}.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return count


def _metrics(ranked: list[str], relevant: list[str]) -> dict[str, float]:
    rr = 0.0
    for i, p in enumerate(ranked[:10], start=1):
        if p in relevant:
            rr = 1.0 / i
            break
    return {
        "recall@1": float(any(p in relevant for p in ranked[:1])),
        "recall@5": float(any(p in relevant for p in ranked[:5])),
        "mrr@10": rr,
    }


def _norm(s: str) -> str:
    s = str(s or "").lower().replace(" ", " ")
    return re.sub(r"\s+", "", s)


REFUSAL_MARKERS = (
    "not in",
    "couldn't find",
    "could not find",
    "can't find",
    "cannot find",
    "no information",
    "isn't in",
    "nicht in",
    "nicht gefunden",
    "keine information",
    "finde ich nicht",
    "pas dans",
    "pas trouvé",
    "aucune information",
    "ne trouve pas",
    "no está",
    "no encontr",
    "no hay información",
    "no aparece",
    "没有找到",
    "未找到",
    "没有相关",
    "找不到",
    "不在",
)


def says_not_found(answer: str) -> bool:
    """An unanswerable question is answered correctly by saying the files don't say (AI-16)."""
    low = (answer or "").lower()
    return any(m in low for m in REFUSAL_MARKERS)


def answer_matches(answer: str, accepted: list[str]) -> bool:
    a = _norm(answer)
    return any(_norm(x) and _norm(x) in a for x in accepted)


def _index_tree(engine, root: str) -> None:
    for dirpath, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            st = os.stat(path)
            engine._index_single_file(
                path,
                name,
                os.path.splitext(name)[1],
                st.st_size,
                FIXED_MTIME_NS,
                None,
                respect_standby=False,
                force_wake=True,
            )


def evaluate(
    model: str = "zett_lexical_384d",
    dim: int | None = None,
    which: str = "base",
    distractors: int = 0,
    host: str | None = None,
    answers_model: str | None = None,
    qa_limit: int | None = None,
    llm_host: str | None = None,
) -> dict:
    from backend.services.rag_engine import RagSearchEngine

    tmp = tempfile.mkdtemp(prefix="zettnas-rag-eval-")
    engine = RagSearchEngine(db_path=os.path.join(tmp, "eval.db"))
    cfg = dict(engine.get_config())
    cfg.update({"embedding_model": model, "respect_standby": False})
    if dim:
        cfg["embedding_dim"] = dim
    if host:
        cfg["embedding_host"] = host
        cfg["llm_endpoint"] = llm_host or host
    if answers_model:
        cfg["active_model"] = answers_model
    if llm_host:
        cfg["llm_endpoint"] = llm_host
    rel = lambda p: os.path.relpath(p, CORPUS).replace(os.sep, "/")  # noqa: E731
    per_query = []
    qa_rows = []
    try:
        with (
            patch.object(engine, "get_config", return_value=cfg),
            patch("backend.services.rag_standby.is_backing_disk_in_standby", return_value=False),
        ):
            _index_tree(engine, CORPUS)
            if distractors:
                noise = os.path.join(tmp, "distractors")
                write_distractors(noise, distractors)
                _index_tree(engine, noise)
            for q in load_queries(which):
                res = engine.search(q["query"], limit=10)
                ranked = []
                for item in res.get("results") or []:
                    p = rel(item.get("canonical_path") or item.get("path") or "")
                    if p not in ranked:
                        ranked.append(p)
                per_query.append({**q, "ranked": ranked[:10], **_metrics(ranked, q["relevant"])})
            if answers_model:
                from backend.services import ai_chat_agent

                # test mode switches the language model off
                os.environ.pop("TESTING", None)
                os.environ.pop("ZETTNAS_TEST_MODE", None)

                with patch.object(ai_chat_agent, "get_rag_engine", return_value=engine):
                    for item in load_qa()[: qa_limit or None]:
                        out = ai_chat_agent.run_agentic_chat(
                            item["question"], allow_web_search=False, model_override=answers_model
                        )
                        text = out.get("reply") or out.get("reply_markdown") or ""
                        sources = [
                            rel(s.get("path") or s.get("file_path") or s.get("canonical_path") or "")
                            for s in (out.get("citations") or [])
                        ]
                        tel = out.get("llm_telemetry") or {}
                        qa_rows.append(
                            {
                                **item,
                                "model_answered": float(bool(tel.get("llm_invoked"))),
                                "correct": float(
                                    says_not_found(text)
                                    if item.get("unanswerable")
                                    else answer_matches(text, item["answer_any"])
                                ),
                                "source_hit": float(
                                    item.get("unanswerable") or any(p in item["relevant"] for p in sources)
                                ),
                                "answer": text[:400],
                            }
                        )
    finally:
        engine.close()

    def summary(rows):
        n = len(rows) or 1
        return {k: round(sum(r[k] for r in rows) / n, 3) for k in ("recall@1", "recall@5", "mrr@10")} | {
            "queries": len(rows)
        }

    langs = sorted({r["lang"] for r in per_query})
    kinds = sorted({r["kind"] for r in per_query})
    out = {
        "model": model,
        "set": which,
        "distractors": distractors,
        "overall": summary(per_query),
        "by_language": {lang: summary([r for r in per_query if r["lang"] == lang]) for lang in langs},
        "by_kind": {k: summary([r for r in per_query if r["kind"] == k]) for k in kinds},
        "misses": [
            {"id": r["id"], "query": r["query"], "top": r["ranked"][:3]} for r in per_query if not r["recall@5"]
        ],
    }
    if qa_rows:
        refusals = [r for r in qa_rows if r.get("unanswerable")]
        qa_rows = [r for r in qa_rows if not r.get("unanswerable")]
        n = len(qa_rows) or 1
        out["answers"] = {
            "model": answers_model,
            # unanswerable questions are scored apart, so the accuracy stays comparable
            "says_not_found": round(sum(r["correct"] for r in refusals) / max(1, len(refusals)), 3),
            "accuracy": round(sum(r["correct"] for r in qa_rows) / n, 3),
            "source_hit": round(sum(r["source_hit"] for r in qa_rows) / n, 3),
            "model_answered": round(sum(r["model_answered"] for r in qa_rows) / n, 3),
            "by_language": {
                lang: round(
                    sum(r["correct"] for r in qa_rows if r["lang"] == lang)
                    / max(1, sum(1 for r in qa_rows if r["lang"] == lang)),
                    3,
                )
                for lang in sorted({r["lang"] for r in qa_rows})
            },
            "wrong": [
                {"id": r["id"], "question": r["question"], "answer": r["answer"]} for r in qa_rows if not r["correct"]
            ],
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="zett_lexical_384d")
    ap.add_argument("--dim", type=int, default=None)
    ap.add_argument("--set", default="base", choices=["base", "extended", "all"])
    ap.add_argument("--distractors", type=int, default=0, help="extra generated files to search through")
    ap.add_argument("--host", default=None, help="Ollama-compatible host for the embedder and the answer model")
    ap.add_argument(
        "--answers", default=None, metavar="MODEL", help="also answer qa.json with this chat model and score it"
    )
    ap.add_argument("--llm-host", default=None, help="host of the answer model, when not the embedder host")
    ap.add_argument("--qa-limit", type=int, default=None, help="answer only the first N questions (quick check)")
    ap.add_argument("--misses", action="store_true", help="list queries whose file wasn't in the top 5")
    ap.add_argument("--out", default=None, help="write the JSON result here too")
    args = ap.parse_args()
    out = evaluate(
        args.model, args.dim, args.set, args.distractors, args.host, args.answers, args.qa_limit, args.llm_host
    )
    if not args.misses:
        out.pop("misses")
        if "answers" in out:
            out["answers"].pop("wrong")
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

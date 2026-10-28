"""Retrieval and answer evaluation over tests/rag_eval (AI-11, AI-3).

40 home-NAS files in English, German, Chinese, French and Spanish (Markdown, text, CSV,
YAML, JSON, HTML, Python and shell) and three hand-written sets, asked the way a person would
ask. Files go through the real indexer and queries through the real search; nothing here is
tuned to the engine.

- queries.json: 200 queries, 5 per file, in the file's language (what CI gates on).
- queries_extended.json: 50 cross-language queries (asked in one language about a file in
  another) and 40 paraphrases that share few or no words with the file.
- qa.json: 97 questions with the facts a correct answer must contain, for answer quality.
- queries_documents.json, qa_documents.json (AI-16): long, Office and scanned documents and
  multi-hop questions that need two files. The files are generated (documents.py) and indexed
  with the corpus; scanned ones are read by the vision model (--ocr vision) or, per commit, by a
  stand-in that returns each page's known text, which checks everything but the model itself.

Speed (AI-16): every result has the search times (latency: p50, p95, slowest) and the p95 in
units of a fixed piece of work timed on the same machine, so runs on different machines
compare; CI fails when that grows by half (tests/rag_eval/baseline_speed.json).

Held-out split (AI-16): one query or question in five, chosen by a hash of its id, is held out.
Tune and look at misses on the rest ("dev"); the held-out scores only say whether a change
generalises. --misses lists dev misses only (--show-heldout to see all, e.g. for a release).

    python -m tests.rag_eval.run_eval                                  # base set, lexical vectors (CI)
    python -m tests.rag_eval.run_eval --set extended                   # cross-language and paraphrase
    python -m tests.rag_eval.run_eval --model embeddinggemma --host http://127.0.0.1:11434 \\
        --set all --distractors 2000                                   # nightly: neural model, 2,000 extra files
    python -m tests.rag_eval.run_eval --model embeddinggemma --answers qwen3:4b   # answers, scored
    python -m tests.rag_eval.run_eval --set documents                              # long, Office, scanned, multi-hop
    python -m tests.rag_eval.run_eval --set documents --model embeddinggemma --host http://127.0.0.1:11434 \\
        --ocr vision --answers qwen3:4b                                            # with the real vision model
"""

import argparse
import hashlib
import json
import math
import os
import random
import re
import tempfile
import time
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
FIXED_MTIME_NS = 1_700_000_000_000_000_000
SETS = {"base": "queries.json", "extended": "queries_extended.json", "documents": "queries_documents.json"}
ALL = ("base", "extended")  # "all": what the nightly compares; documents run as their own set
HELDOUT_EVERY = 5


def split_of(item_id: str) -> str:
    """'heldout' for one id in five (fixed by its hash), else 'dev'."""
    return "heldout" if int(hashlib.sha1(item_id.encode()).hexdigest(), 16) % HELDOUT_EVERY == 0 else "dev"


def load_queries(which: str = "base") -> list[dict]:
    names = [SETS[w] for w in ALL] if which == "all" else [SETS[which]]
    out = []
    for name in names:
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            for q in json.load(f):
                out.append({"kind": "same-language", **q, "split": split_of(q["id"])})
    return out


def load_qa(which: str = "base") -> list[dict]:
    name = "qa_documents.json" if which == "documents" else "qa.json"
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return [{**q, "split": split_of(q["id"])} for q in json.load(f)]


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
        # every file the answer needs is in the top 5 (multi-hop; the same as recall@5 for one file)
        "all@5": float(all(p in ranked[:5] for p in relevant)),
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


def answer_matches(answer: str, accepted: list[str], required: list[str] | None = None) -> bool:
    """One of the accepted facts is in the answer, and every required one (multi-hop)."""
    a = _norm(answer)
    if required and not all(_norm(x) in a for x in required):
        return False
    return not accepted or any(_norm(x) and _norm(x) in a for x in accepted)


def faithfulness(rows: list[dict]) -> dict:
    """How much of the answers their cited sources back up (AI-16): the app's own sentence check
    (rag_grounding.score_answer_grounding, every number in a sentence must be in the source it
    leans on). `faithfulness` is the mean share of supported sentences, `fully_supported` the
    share of answers with every sentence supported; answers with nothing to check are left out."""
    scored = [r["faithful"] for r in rows if r.get("faithful") is not None]
    if not scored:
        return {"faithfulness": None, "fully_supported": None, "faithfulness_scored": 0}
    return {
        "faithfulness": round(sum(scored) / len(scored) / 100, 3),
        "fully_supported": round(sum(1 for s in scored if s >= 100) / len(scored), 3),
        "faithfulness_scored": len(scored),
    }


def read_scanned(engine, ocr: str = "standin", host: str | None = None) -> dict:
    """Runs the vision queue over the index until it has read every photo and scanned PDF.

    ocr "standin" answers with the known text of each page (tests/rag_eval/documents.py), so
    the pipeline from scan to search is checked without a model; "vision" uses the real one.
    """
    from backend.services.vision_queue import VisionQueue
    from tests.rag_eval import documents

    if ocr == "vision":
        q = VisionQueue(engine, idle=lambda: True, host=(lambda: host) if host else None)
    else:
        q = VisionQueue(
            engine,
            describe=lambda path, model, h: documents.photo_text_for(path),
            idle=lambda: True,
            host=lambda: "http://standin",
            model_picker=lambda cfg, h: "standin",
        )
        q.ocr = lambda data, model, h: documents.page_text_for(data)
    seen = {}
    for _ in range(200):
        state = q.process_one()
        seen[state] = seen.get(state, 0) + 1
        if state not in ("done", "error"):
            break
    return seen


def first_token_summary(times_ms: list) -> dict:
    """p50 and p95 of the answers' first-token times (AI-16); the ones the server didn't report
    are left out and counted."""
    got = sorted(float(t) for t in times_ms if t is not None)
    if not got:
        return {"measured": 0}

    def pct(q: float) -> float:  # nearest rank
        return round(got[min(len(got) - 1, max(0, math.ceil(q * len(got)) - 1))], 1)

    return {"p50_ms": pct(0.5), "p95_ms": pct(0.95), "measured": len(got), "missing": len(times_ms) - len(got)}


def calibrate(rounds: int = 7) -> float:
    """Milliseconds this machine takes for a fixed piece of work (sorting and hashing), the
    fastest of a few rounds (the least disturbed): search times divided by it compare across
    machines."""

    def work() -> str:
        h = hashlib.sha256()
        for item in sorted(str(i * 7919 % 100003) for i in range(60000)):
            h.update(item.encode())
        return h.hexdigest()

    times = []
    for _ in range(rounds):
        t = time.perf_counter()
        work()
        times.append((time.perf_counter() - t) * 1000)
    return min(times)


def latency_summary(times_ms: list[float], unit_ms: float) -> dict:
    s = sorted(times_ms) or [0.0]

    def pct(q: float) -> float:
        return s[min(len(s) - 1, int(q * len(s)))]

    return {
        "p50_ms": round(pct(0.5), 1),
        "p95_ms": round(pct(0.95), 1),
        "max_ms": round(s[-1], 1),
        "unit_ms": round(unit_ms, 1),
        "p95_units": round(pct(0.95) / unit_ms, 3) if unit_ms else None,
    }


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
    ocr: str = "standin",
    measure_cut_off: bool = True,
) -> dict:
    from backend.services import rag_calibration
    from backend.services.rag_engine import RagSearchEngine, similarity_profile

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
    docs_root = os.path.join(tmp, "documents")
    neural = model != "zett_lexical_384d"
    measured_patch = patch.object(rag_calibration, "measured", return_value=None)
    if neural and measure_cut_off:
        rag_calibration.reset()
        rag_calibration.ensure_measured(model, dim, host, background=False)
    elif neural:
        measured_patch.start()

    def rel(p: str) -> str:
        root = docs_root if p.startswith(docs_root + os.sep) else CORPUS
        return os.path.relpath(p, root).replace(os.sep, "/")

    per_query = []
    qa_rows = []
    search_ms = []
    unit_ms = calibrate()
    try:
        with (
            patch.object(engine, "get_config", return_value=cfg),
            patch("backend.services.rag_standby.is_backing_disk_in_standby", return_value=False),
        ):
            _index_tree(engine, CORPUS)
            scanned = None
            if which == "documents":
                from tests.rag_eval import documents

                documents.build(docs_root)
                _index_tree(engine, docs_root)
                scanned = read_scanned(engine, ocr, host)
            if distractors:
                noise = os.path.join(tmp, "distractors")
                write_distractors(noise, distractors)
                _index_tree(engine, noise)
            for q in load_queries(which):
                t0 = time.perf_counter()
                res = engine.search(q["query"], limit=10)
                search_ms.append((time.perf_counter() - t0) * 1000)
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

                # streamed, as the app's chat is: the first token's time is measured (AI-16)
                sink_token = ai_chat_agent._TOKEN_SINK.set(lambda kind, text: None)
                with patch.object(ai_chat_agent, "get_rag_engine", return_value=engine):
                    for item in load_qa(which)[: qa_limit or None]:
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
                                    else answer_matches(text, item["answer_any"], item.get("answer_all"))
                                ),
                                "source_hit": float(
                                    item.get("unanswerable") or all(p in sources for p in item["relevant"])
                                ),
                                "answer": text[:400],
                                "faithful": (out.get("grounding_detail") or {}).get("score"),
                                "first_token_ms": tel.get("first_token_ms"),
                            }
                        )
                ai_chat_agent._TOKEN_SINK.reset(sink_token)
    finally:
        engine.close()
        vec_min = similarity_profile(model, dim).get("vec_min")
        if neural and not measure_cut_off:
            measured_patch.stop()

    def summary(rows):
        n = len(rows) or 1
        return {k: round(sum(r[k] for r in rows) / n, 3) for k in ("recall@1", "recall@5", "all@5", "mrr@10")} | {
            "queries": len(rows)
        }

    langs = sorted({r["lang"] for r in per_query})
    kinds = sorted({r["kind"] for r in per_query})
    out = {
        "model": model,
        "set": which,
        "distractors": distractors,
        "vec_min": vec_min,
        "overall": summary(per_query),
        "by_language": {lang: summary([r for r in per_query if r["lang"] == lang]) for lang in langs},
        "by_kind": {k: summary([r for r in per_query if r["kind"] == k]) for k in kinds},
        "by_split": {s: summary([r for r in per_query if r["split"] == s]) for s in ("dev", "heldout")},
        "latency": latency_summary(search_ms, min(unit_ms, calibrate())),
        "misses": [
            {"id": r["id"], "split": r["split"], "query": r["query"], "top": r["ranked"][:3]}
            for r in per_query
            if not r["all@5"]
        ],
    }
    if scanned is not None:
        out["scanned_read"] = scanned
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
            "first_token": first_token_summary([r.get("first_token_ms") for r in qa_rows + refusals]),
            **faithfulness(qa_rows),
            "by_language": {
                lang: round(
                    sum(r["correct"] for r in qa_rows if r["lang"] == lang)
                    / max(1, sum(1 for r in qa_rows if r["lang"] == lang)),
                    3,
                )
                for lang in sorted({r["lang"] for r in qa_rows})
            },
            "by_split": {
                s: round(
                    sum(r["correct"] for r in qa_rows if r["split"] == s)
                    / max(1, sum(1 for r in qa_rows if r["split"] == s)),
                    3,
                )
                for s in ("dev", "heldout")
            },
            "wrong": [
                {"id": r["id"], "split": r["split"], "question": r["question"], "answer": r["answer"]}
                for r in qa_rows
                if not r["correct"]
            ],
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="zett_lexical_384d")
    ap.add_argument("--dim", type=int, default=None)
    ap.add_argument("--set", default="base", choices=["base", "extended", "all", "documents"])
    ap.add_argument("--distractors", type=int, default=0, help="extra generated files to search through")
    ap.add_argument("--host", default=None, help="Ollama-compatible host for the embedder and the answer model")
    ap.add_argument(
        "--answers", default=None, metavar="MODEL", help="also answer qa.json with this chat model and score it"
    )
    ap.add_argument("--llm-host", default=None, help="host of the answer model, when not the embedder host")
    ap.add_argument("--qa-limit", type=int, default=None, help="answer only the first N questions (quick check)")
    ap.add_argument("--misses", action="store_true", help="list dev queries whose files weren't in the top 5")
    ap.add_argument("--show-heldout", action="store_true", help="with --misses: held-out misses too (not for tuning)")
    ap.add_argument("--ocr", default="standin", choices=["standin", "vision"], help="how scanned files are read")
    ap.add_argument("--out", default=None, help="write the JSON result here too")
    ap.add_argument(
        "--no-calibration", action="store_true", help="use the built-in similarity cut-off, not one measured"
    )
    args = ap.parse_args()
    out = evaluate(
        args.model,
        args.dim,
        args.set,
        args.distractors,
        args.host,
        args.answers,
        args.qa_limit,
        args.llm_host,
        args.ocr,
        not args.no_calibration,
    )
    if not args.misses:
        out.pop("misses")
        if "answers" in out:
            out["answers"].pop("wrong")
    elif not args.show_heldout:
        out["misses"] = [m for m in out["misses"] if m["split"] == "dev"]
        if "answers" in out:
            out["answers"]["wrong"] = [w for w in out["answers"]["wrong"] if w["split"] == "dev"]
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

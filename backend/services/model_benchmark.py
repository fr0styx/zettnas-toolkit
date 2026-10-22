"""
Model benchmarks and model tiers (D2).

An admin starts a benchmark; it runs one fixed prompt on every installed chat model in
Ollama, one at a time, and records generation speed (tokens/s), time to the first
token, load time and where the model ran (GPU, split, CPU) from Ollama's /api/ps.
From that it recommends two tiers:

- fast: the quickest model, for short jobs;
- balanced: the largest model that still writes at least 12 tokens/s, so answers
  appear at reading speed. Ask Zetty uses it when you choose "Pick for me".

Results are kept in data/model_benchmarks.json. Embedding-only models and duplicate
names of the same model are skipped. Benchmarks load each model, so they run only
when started.
"""

import json
import os
import threading
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR, logger

RESULTS_FILE = os.path.join(DATA_DIR, "model_benchmarks.json")
PROMPT = "In two sentences, explain why a backup should also be kept somewhere other than the NAS itself."
READING_SPEED_TPS = 12.0
_lock = threading.Lock()
_job: dict[str, Any] = {"state": "idle"}


def _http_json(url: str, body: dict | None = None, timeout: float = 30.0) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")


def _host() -> str:
    from backend.services.rag_embeddings import _resolve_ollama_host

    return _resolve_ollama_host()


def chat_models(host: str, http: Callable = _http_json) -> list[dict[str, Any]]:
    """Installed chat models in Ollama's order; one name per model (the short, local one)."""
    tags = (http(f"{host}/api/tags", timeout=10) or {}).get("models") or []
    best: dict[str, str] = {}
    for m in tags:
        name, digest = m.get("name") or "", m.get("digest") or m.get("name") or ""
        cur = best.get(digest)
        if cur is None or (("/" in cur, len(cur)) > ("/" in name, len(name))):
            best[digest] = name
    out = []
    for m in tags:
        name = m.get("name")
        if not name or best.get(m.get("digest") or name) != name:
            continue
        try:
            caps = (http(f"{host}/api/show", {"model": name}, timeout=10) or {}).get("capabilities") or []
        except Exception:
            logger.debug("model_benchmark: /api/show failed for %s", name, exc_info=True)
            caps = []
        if caps and "completion" not in caps:
            continue
        out.append(
            {
                "name": name,
                "size_bytes": int(m.get("size") or 0),
                "params": (m.get("details") or {}).get("parameter_size", ""),
            }
        )
    return out


def _placement(host: str, name: str, http: Callable) -> str:
    try:
        for m in (http(f"{host}/api/ps", timeout=10) or {}).get("models") or []:
            if m.get("name") == name or m.get("model") == name:
                size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
                if size and vram >= size * 0.95:
                    return "GPU"
                return "split" if vram else "CPU"
    except Exception:
        logger.debug("model_benchmark: /api/ps unavailable", exc_info=True)
    return "unknown"


def benchmark_model(host: str, model: dict[str, Any], http: Callable = _http_json) -> dict[str, Any]:
    started = time.time()
    try:
        r = http(
            f"{host}/api/generate",
            {
                "model": model["name"],
                "prompt": PROMPT,
                "stream": False,
                "keep_alive": "30s",
                "options": {"num_predict": 96, "temperature": 0},
            },
            timeout=600,
        )
    except Exception as e:
        return {**model, "ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    ev_n, ev_ns = int(r.get("eval_count") or 0), int(r.get("eval_duration") or 0)
    pe_ns, load_ns = int(r.get("prompt_eval_duration") or 0), int(r.get("load_duration") or 0)
    return {
        **model,
        "ok": ev_n > 0 and ev_ns > 0,
        "tokens_per_s": round(ev_n / (ev_ns / 1e9), 1) if ev_ns else 0.0,
        "first_token_s": round((load_ns + pe_ns) / 1e9, 2),
        "load_s": round(load_ns / 1e9, 2),
        "wall_s": round(time.time() - started, 1),
        "placement": _placement(host, model["name"], http),
    }


def recommend(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in results if r.get("ok")]
    if not ok:
        return {"fast": None, "balanced": None}
    fast = max(ok, key=lambda r: r["tokens_per_s"])
    readable = [r for r in ok if r["tokens_per_s"] >= READING_SPEED_TPS]
    balanced = max(readable, key=lambda r: (r["size_bytes"], r["tokens_per_s"])) if readable else fast
    return {"fast": fast["name"], "balanced": balanced["name"]}


def load_results() -> dict[str, Any]:
    try:
        with open(RESULTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"results": [], "finished_at": None, "recommended": {"fast": None, "balanced": None}}


def status() -> dict[str, Any]:
    with _lock:
        job = dict(_job)
    return {**load_results(), "job": job}


def run(host: str | None = None, http: Callable = _http_json, only: list[str] | None = None) -> dict[str, Any]:
    host = host or _host()
    models = [m for m in chat_models(host, http) if not only or m["name"] in only]
    results = []
    for i, m in enumerate(models):
        with _lock:
            _job.update(state="running", current=m["name"], done=i, total=len(models))
        results.append(benchmark_model(host, m, http))
    out = {"results": results, "finished_at": time.time(), "host": host, "recommended": recommend(results)}
    tmp = RESULTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, RESULTS_FILE)
    with _lock:
        _job.clear()
        _job.update(state="done", done=len(models), total=len(models))
    return out


def start() -> dict[str, Any]:
    with _lock:
        if _job.get("state") == "running":
            return {"started": False, "job": dict(_job)}
        _job.clear()
        _job.update(state="running", done=0, total=0, started_at=time.time())

    def worker() -> None:
        try:
            run()
        except Exception as e:
            logger.warning(f"[Benchmark] Failed: {e}", exc_info=True)
            with _lock:
                _job.clear()
                _job.update(state="error", error=str(e)[:200])

    threading.Thread(target=worker, name="ModelBenchmark", daemon=True).start()
    return {"started": True}

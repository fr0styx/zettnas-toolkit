"""Cross-encoder server for OpenVINO: a reranker and an NLI (entailment) model, both multilingual.

Kiboto uses the reranker through the AI config's rerank_endpoint (search and Ask Kib, AI-12,
AI-28); the NLI model is optional and for experiments. Run it on the app's Docker network with no
published port.

  POST /v3/rerank, /rerank  {"query", "documents" | "texts", "top_n"?}
                            -> {"results": [{"index", "relevance_score"}]}  (0..1, best first)
  POST /nli                 {"pairs": [[premise, hypothesis], ...]}
                            -> {"results": [{"entailment", "neutral", "contradiction"}]}  (probabilities)
  GET  /health

Settings (environment): RERANK_DIR, RERANK_FILE (onnx/model.onnx), NLI_DIR, NLI_FILE, DEVICE (CPU, GPU),
PRECISION (f32, f16), MAX_TOKENS (512), BATCH (8), RERANK_STATIC / NLI_STATIC (a fixed token length for
exports that need fixed shapes), PORT (8000). A model whose folder is missing is left out.
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import openvino as ov
from transformers import AutoTokenizer

DEVICE = os.environ.get("DEVICE", "CPU")
PRECISION = os.environ.get("PRECISION", "f32")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "512"))
BATCH = int(os.environ.get("BATCH", "8"))
MAX_INPUTS = 64
core = ov.Core()


class CrossEncoder:
    def __init__(self, folder: str, file: str, static: int = 0):
        t0 = time.time()
        self.tok = AutoTokenizer.from_pretrained(folder)
        model = core.read_model(os.path.join(folder, file))
        self.static = static  # some exports (DeBERTa's) only compile with fixed shapes: [BATCH, static]
        if static:
            model.reshape({i.get_any_name(): [BATCH, static] for i in model.inputs})
        self.inputs = {i.get_any_name() for i in model.inputs}
        cfg = {"INFERENCE_PRECISION_HINT": PRECISION} if DEVICE != "CPU" or PRECISION != "f32" else {}
        self.compiled = core.compile_model(model, DEVICE, cfg)
        self.lock = threading.Lock()
        with open(os.path.join(folder, "config.json"), encoding="utf-8") as f:
            self.labels = {int(k): v.lower() for k, v in (json.load(f).get("id2label") or {}).items()}
        print(f"{folder} ({file}) on {DEVICE} ready in {time.time() - t0:.1f}s", flush=True)

    def logits(self, pairs: list[tuple[str, str]]) -> np.ndarray:
        out = []
        for i in range(0, len(pairs), BATCH):
            chunk = pairs[i : i + BATCH]
            n = len(chunk)
            if self.static:
                chunk = chunk + [("", "")] * (BATCH - n)
            enc = self.tok(
                [a for a, _ in chunk],
                [b for _, b in chunk],
                truncation=True,  # the longer text of a pair gives way: a document, or a passage
                max_length=self.static or MAX_TOKENS,
                padding="max_length" if self.static else True,
                return_tensors="np",
            )
            feed = {k: v.astype(np.int64) for k, v in enc.items() if k in self.inputs}
            with self.lock:
                res = self.compiled.create_infer_request().infer(feed)
            out.append(np.asarray(list(res.values())[0], dtype=np.float32)[:n])
        return np.concatenate(out, axis=0)


def _load(prefix: str) -> CrossEncoder | None:
    folder = os.environ.get(f"{prefix}_DIR", "")
    if not folder or not os.path.isdir(folder):
        return None
    static = int(os.environ.get(f"{prefix}_STATIC", "0"))
    return CrossEncoder(folder, os.environ.get(f"{prefix}_FILE", "onnx/model.onnx"), static)


RERANK = _load("RERANK")
NLI = _load("NLI")


def rerank(query: str, docs: list[str]) -> list[float]:
    logits = RERANK.logits([(query, d) for d in docs])[:, 0]
    return (1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))).tolist()


def nli(pairs: list[tuple[str, str]]) -> list[dict[str, float]]:
    logits = NLI.logits(pairs)
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = e / e.sum(axis=1, keepdims=True)
    return [{NLI.labels.get(j, str(j)): round(float(p[j]), 4) for j in range(p.shape[0])} for p in probs]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            ready = {"rerank": RERANK is not None, "nli": NLI is not None}
            return self._send(200, {"status": "ok", **ready, "device": DEVICE})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        try:
            if self.path in ("/v3/rerank", "/rerank"):
                if RERANK is None:
                    return self._send(404, {"error": "no reranker here"})
                docs = body.get("documents") or body.get("texts") or []
                query = body.get("query")
                if not isinstance(query, str) or not isinstance(docs, list) or not 0 < len(docs) <= MAX_INPUTS:
                    return self._send(400, {"error": f"query and 1-{MAX_INPUTS} documents"})
                docs = [d if isinstance(d, str) else str((d or {}).get("text", "")) for d in docs]
                scores = rerank(query, docs)
                order = sorted(range(len(scores)), key=lambda i: -scores[i])[: int(body.get("top_n") or len(docs))]
                results = [{"index": i, "relevance_score": round(scores[i], 6)} for i in order]
                return self._send(200, {"results": results})
            if self.path == "/nli":
                if NLI is None:
                    return self._send(404, {"error": "no NLI model here"})
                pairs = body.get("pairs")
                ok = isinstance(pairs, list) and 0 < len(pairs) <= MAX_INPUTS
                if not ok or not all(
                    isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) for x in p) for p in pairs
                ):
                    return self._send(400, {"error": f"pairs: 1-{MAX_INPUTS} [premise, hypothesis] lists"})
                return self._send(200, {"results": nli([(a, b) for a, b in pairs])})
        except Exception as e:  # the caller goes on without us
            return self._send(500, {"error": str(e)[:300]})
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()

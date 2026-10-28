"""A small Ollama-compatible embedding server for OpenVINO models (EmbeddingGemma 2 on an Intel GPU).

ZettNAS (or anything that speaks Ollama's embed API) points its embedding host here. It serves:
  POST /api/embed       {"model", "input": str | [str], "truncate"} -> {"model", "embeddings"}
  POST /api/embeddings  {"model", "prompt"} -> {"embedding"}   (older Ollama API)
  GET  /api/tags        the one model this server runs
  GET  /health

Settings (environment): MODEL_DIR (model.xml, model.bin), TOKENIZER_DIR, MODEL_NAME,
DEVICE (GPU, CPU), PRECISION (f32; f16 gives broken EmbeddingGemma vectors on Arc),
BATCH (2), MAX_TOKENS (2048), PORT (11434), TOKEN (optional: when set, the embed endpoints
need "Authorization: Bearer <TOKEN>"; ZettNAS sends its EMBEDDING_TOKEN).

Run it on the app's Docker network with no published port: only containers on that network can
reach it, and the token keeps the others out too.
"""

import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import openvino as ov
from transformers import AutoTokenizer

MODEL_DIR = os.environ.get("MODEL_DIR", "/models/model")
TOKENIZER_DIR = os.environ.get("TOKENIZER_DIR", "/models/tokenizer")
MODEL_NAME = os.environ.get("MODEL_NAME", "embeddinggemma-2-ov")
DEVICE = os.environ.get("DEVICE", "GPU")
PRECISION = os.environ.get("PRECISION", "f32")
BATCH = int(os.environ.get("BATCH", "2"))  # small batches were fastest on an Arc iGPU in testing
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "2048"))
MAX_INPUTS = 256
TOKEN = os.environ.get("TOKEN", "").strip()

tok = AutoTokenizer.from_pretrained(TOKENIZER_DIR)
core = ov.Core()
t0 = time.time()
compiled = core.compile_model(f"{MODEL_DIR}/model.xml", DEVICE, {"INFERENCE_PRECISION_HINT": PRECISION})
request = compiled.create_infer_request()
# One inference at a time. Searches (one or two short texts) go before the next batch of an
# indexing request, so a query waits for at most one batch, not a whole file's worth.
gpu = threading.Condition()
state = {"busy": False, "queries_waiting": 0}
print(f"{MODEL_NAME} on {DEVICE} ({PRECISION}) ready in {time.time() - t0:.1f}s", flush=True)


# EmbeddingGemma attends within 512-token windows. Padding a short text to a long one leaves
# windows of nothing but padding, and those come out NaN (on CPU too). Texts in one batch are
# therefore kept within this many tokens of each other.
MAX_SPREAD = 480


def batches(lengths: list[int]) -> list[list[int]]:
    """Text indexes grouped by length: at most BATCH each, longest minus shortest < MAX_SPREAD."""
    order = sorted(range(len(lengths)), key=lambda i: lengths[i])
    groups: list[list[int]] = []
    for i in order:
        g = groups[-1] if groups else None
        if g and len(g) < BATCH and lengths[i] - lengths[g[0]] < MAX_SPREAD:
            g.append(i)
        else:
            groups.append([i])
    return groups


def embed(texts: list[str]) -> list[list[float]]:
    ids = tok(texts, truncation=True, max_length=MAX_TOKENS)["input_ids"]
    out: list = [None] * len(texts)
    small = len(texts) <= 2
    for idx in batches([len(x) for x in ids]):
        with gpu:
            if small:
                state["queries_waiting"] += 1
            try:
                gpu.wait_for(lambda: not state["busy"] and (small or state["queries_waiting"] == 0))
            finally:
                if small:
                    state["queries_waiting"] -= 1
            state["busy"] = True
        try:
            enc = tok.pad({"input_ids": [ids[i] for i in idx]}, return_tensors="np")
            res = request.infer(
                {
                    "input_ids": enc["input_ids"].astype(np.int64),
                    "attention_mask": enc["attention_mask"].astype(np.int64),
                }
            )
            vecs = np.asarray(list(res.values())[0], dtype=np.float32)
            vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)
            if not np.isfinite(vecs).all():
                raise RuntimeError("the model returned NaN or infinite values")
            for i, v in zip(idx, vecs, strict=True):
                out[i] = v.tolist()
        finally:
            with gpu:
                state["busy"] = False
                gpu.notify_all()
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet: ZettNAS calls this many times a second while indexing
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
            return self._send(200, {"status": "ok", "model": MODEL_NAME, "device": DEVICE})
        if self.path == "/api/tags":
            return self._send(
                200, {"models": [{"name": MODEL_NAME, "model": MODEL_NAME, "details": {"family": "openvino"}}]}
            )
        if self.path == "/api/version":
            return self._send(200, {"version": "openvino-embed"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path not in ("/api/embed", "/api/embeddings"):
            return self._send(404, {"error": "not found"})
        if TOKEN and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {TOKEN}"):
            return self._send(401, {"error": "a valid token is needed"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        name = str(body.get("model") or "")
        if name not in (MODEL_NAME, f"{MODEL_NAME}:latest"):
            return self._send(404, {"error": f"model '{name}' not found; this server runs '{MODEL_NAME}'"})
        if self.path == "/api/embeddings":
            texts = [str(body.get("prompt") or "")]
        else:
            raw = body.get("input")
            texts = [raw] if isinstance(raw, str) else raw
        if (
            not isinstance(texts, list)
            or not texts
            or len(texts) > MAX_INPUTS
            or not all(isinstance(t, str) for t in texts)
        ):
            return self._send(400, {"error": f"input must be a string or a list of 1-{MAX_INPUTS} strings"})
        try:
            vecs = embed([t or " " for t in texts])
        except Exception as e:
            return self._send(500, {"error": str(e)[:300]})
        if self.path == "/api/embeddings":
            return self._send(200, {"embedding": vecs[0]})
        self._send(200, {"model": MODEL_NAME, "embeddings": vecs})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "11434"))), Handler).serve_forever()

"""Image and text vectors from SigLIP 2 on OpenVINO, for photo search by meaning (ZettNAS B14).

Both kinds of vectors live in one space: a photo's vector and the vector of "dog on the beach"
(in any language SigLIP 2 learned) are close when the photo shows it.

  POST /v1/embeddings  {"model", "input": [str | {"image": "<base64 JPEG/PNG/WebP>"}]}
                        -> {"data": [{"index", "embedding"}], "model"}   (unit vectors)
  GET  /health

Settings (environment): MODEL_DIR (export.py's output), MODEL_NAME (siglip2), DEVICE (GPU, CPU),
BATCH (8), PORT (11436), TOKEN (optional: the embeddings endpoint then needs
"Authorization: Bearer <TOKEN>"). Run it on the app's Docker network with no published port.
"""

import base64
import hmac
import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import openvino as ov
from PIL import Image
from transformers import AutoTokenizer

MODEL_DIR = os.environ.get("MODEL_DIR", "/models")
MODEL_NAME = os.environ.get("MODEL_NAME", "siglip2")
DEVICE = os.environ.get("DEVICE", "GPU")
BATCH = int(os.environ.get("BATCH", "8"))
TOKEN = os.environ.get("TOKEN", "").strip()
MAX_INPUTS = 64
MAX_IMAGE_BYTES = 20 * 1024 * 1024

with open(os.path.join(MODEL_DIR, "info.json")) as f:
    INFO = json.load(f)
SIZE = int(INFO["image_size"])
MEAN = np.array(INFO["image_mean"], dtype=np.float32).reshape(3, 1, 1)
STD = np.array(INFO["image_std"], dtype=np.float32).reshape(3, 1, 1)
tok = AutoTokenizer.from_pretrained(os.path.join(MODEL_DIR, "tokenizer"))
core = ov.Core()
vision = core.compile_model(os.path.join(MODEL_DIR, "vision.xml"), DEVICE)
text = core.compile_model(os.path.join(MODEL_DIR, "text.xml"), DEVICE)
lock = threading.Lock()  # one inference at a time on the GPU
print(f"{MODEL_NAME} on {DEVICE} ready ({INFO['model']}, {INFO['weights']})", flush=True)


def _unit(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)


def pixels(data: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(data)).convert("RGB").resize((SIZE, SIZE), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0
    return (arr - MEAN) / STD


def embed_images(blobs: list[bytes]) -> list[list[float]]:
    out = []
    for i in range(0, len(blobs), BATCH):
        batch = np.stack([pixels(b) for b in blobs[i : i + BATCH]])
        with lock:
            vecs = next(iter(vision({"pixel_values": batch}).values()))
        out.extend(_unit(np.asarray(vecs, dtype=np.float32)).tolist())
    return out


def embed_texts(texts: list[str]) -> list[list[float]]:
    if INFO.get("lowercase"):
        texts = [t.lower() for t in texts]
    out = []
    for i in range(0, len(texts), BATCH):
        ids = tok(
            texts[i : i + BATCH],
            padding="max_length",
            max_length=int(INFO["max_length"]),
            truncation=True,
            return_tensors="np",
        )
        with lock:
            vecs = next(iter(text({"input_ids": ids["input_ids"].astype(np.int64)}).values()))
        out.extend(_unit(np.asarray(vecs, dtype=np.float32)).tolist())
    return out


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
            return self._send(200, {"status": "ok", "model": MODEL_NAME, "device": DEVICE})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/embeddings":
            return self._send(404, {"error": "not found"})
        if TOKEN and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {TOKEN}"):
            return self._send(401, {"error": "a valid token is needed"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        items = body.get("input")
        items = [items] if isinstance(items, (str, dict)) else items
        if not isinstance(items, list) or not items or len(items) > MAX_INPUTS:
            return self._send(400, {"error": f"input must be 1-{MAX_INPUTS} texts or images"})
        texts, images = [], []
        try:
            for i, it in enumerate(items):
                if isinstance(it, str):
                    texts.append((i, it))
                elif isinstance(it, dict) and isinstance(it.get("image"), str):
                    raw = base64.b64decode(it["image"], validate=True)
                    if len(raw) > MAX_IMAGE_BYTES:
                        raise ValueError("image too large")
                    images.append((i, raw))
                else:
                    raise ValueError('each input is a text or {"image": base64}')
            vecs: dict[int, list[float]] = {}
            if texts:
                vecs.update(zip([i for i, _ in texts], embed_texts([t for _, t in texts]), strict=True))
            if images:
                vecs.update(zip([i for i, _ in images], embed_images([b for _, b in images]), strict=True))
        except (ValueError, OSError) as e:
            return self._send(400, {"error": str(e)[:200]})
        except Exception as e:
            return self._send(500, {"error": str(e)[:300]})
        data = [{"object": "embedding", "index": i, "embedding": vecs[i]} for i in range(len(items))]
        self._send(200, {"object": "list", "model": MODEL_NAME, "data": data})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "11436"))), Handler).serve_forever()

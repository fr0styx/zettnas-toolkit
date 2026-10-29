"""Photo search by meaning without Immich (B14): image-text vectors from SigLIP 2.

contrib/openvino-clip serves SigLIP 2 on the iGPU. Each indexed photo gets a vector from its
stored thumbnail (photo_assets.thumb_webp, so no disk wakes), and a search question gets a
vector in the same space, in any language SigLIP 2 learned. Photos whose vectors are close to
the question's come back even when no caption or file name says what they show.

Off until a server is set (rag config "photo_vector_host", e.g. http://zettnas-clip:11436).
Vectors are made in the background, a batch at a time, only while the machine is idle (the
caption queue's rules), and are kept per model, so a different model starts over.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from backend.config import logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS photo_semantic (
    file_id INTEGER PRIMARY KEY REFERENCES indexed_files(file_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    vec BLOB NOT NULL
);
"""
BATCH = 16
TIMEOUT = 60.0
TOP_K = 200
# How a photo's closeness to the question becomes 0..1. SigLIP 2's cosines between a question and
# real photos are small (the best around 0.07-0.12, a typical photo 0.01-0.06), and their level
# changes with the question, so each photo is measured against the question's own spread over the
# whole library: photos that show it stand 4 to 6 deviations above the rest (measured on 400 real
# photos). 3 deviations counts a little, 5.5 fully; a vague question ("people") gives no match.
Z_FLOOR, Z_FULL = 3.0, 5.5
MIN_STATS = 30  # fewer photos than this: an absolute scale instead
ABS_FLOOR, ABS_FULL = 0.08, 0.16
_QUERY_CACHE: dict[tuple[str, str, str], list[float]] = {}


def settings(cfg: dict[str, Any]) -> tuple[str, str]:
    host = str(cfg.get("photo_vector_host") or "").strip().rstrip("/")
    return host, str(cfg.get("photo_vector_model") or "").strip() or "siglip2"


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "User-Agent": "ZettNAS-RAG-Engine/2.0"}
    token = os.environ.get("PHOTO_VECTOR_TOKEN", "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def post_embeddings(host: str, model: str, items: list[Any], timeout: float = TIMEOUT) -> list[list[float]]:
    """POST <host>/v1/embeddings; the vectors in input order (texts, or {"image": base64})."""
    url = host if host.endswith("/v1/embeddings") else f"{host}/v1/embeddings"
    req = urllib.request.Request(url, data=json.dumps({"model": model, "input": items}).encode(), headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (the configured server only)
        data = json.loads(r.read())
    rows = sorted(data.get("data") or [], key=lambda d: int(d.get("index", 0)))
    vecs = [row.get("embedding") for row in rows]
    if len(vecs) != len(items) or not all(isinstance(v, list) and v for v in vecs):
        raise ValueError("the photo vector server answered with the wrong number of vectors")
    return vecs


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


class PhotoVectorQueue:
    """Makes the missing photo vectors, a batch at a time, while the machine is idle."""

    def __init__(self, engine, idle: Callable[[], bool], post: Callable = post_embeddings):
        """engine: the AI engine; idle: when the GPU may be used (vision_queue.system_idle).
        Both are handed in: this module is used by search, which the engine imports."""
        self.engine = engine
        self.idle = idle
        self.post = post
        self.last_state = "starting"
        self.last_error = ""

    def process_batch(self) -> str:
        host, model = settings(self.engine.get_config())
        if not host:
            return "disabled"
        if not self.idle():
            return "busy"
        conn = self.engine._get_conn()
        try:
            ensure_schema(conn)
            rows = conn.execute(
                """SELECT p.file_id, p.thumb_webp FROM photo_assets p
                   JOIN indexed_files f ON f.file_id = p.file_id
                   LEFT JOIN photo_semantic s ON s.file_id = p.file_id AND s.model = ?
                   WHERE s.file_id IS NULL AND f.parse_status = 'ok' AND p.thumb_webp IS NOT NULL
                   ORDER BY f.mtime_ns DESC LIMIT ?""",
                (model, BATCH),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return "empty"
        items = [{"image": base64.b64encode(bytes(r[1])).decode()} for r in rows]
        from backend.services import gpu_queue

        gpu_queue.wait_turn(gpu_queue.VISION)
        with gpu_queue.use(gpu_queue.VISION):
            vecs = self.post(host, model, items)
        with self.engine._write_lock:
            conn = self.engine._get_conn()
            try:
                conn.executemany(
                    "INSERT OR REPLACE INTO photo_semantic (file_id, model, vec) VALUES (?, ?, ?)",
                    [(int(r[0]), model, pack(v)) for r, v in zip(rows, vecs, strict=True)],
                )
                conn.commit()
            finally:
                conn.close()
        return "done"

    def status(self) -> dict[str, Any]:
        host, model = settings(self.engine.get_config())
        conn = self.engine._get_conn()
        try:
            ensure_schema(conn)
            total = conn.execute("SELECT COUNT(*) FROM photo_assets WHERE thumb_webp IS NOT NULL").fetchone()[0]
            done = conn.execute("SELECT COUNT(*) FROM photo_semantic WHERE model = ?", (model,)).fetchone()[0]
        finally:
            conn.close()
        return {"enabled": bool(host), "model": model, "photos": total, "done": done, "state": self.last_state}

    def run_forever(self, sleep: Callable = time.sleep) -> None:
        waits = {"done": 1, "empty": 300, "busy": 60, "disabled": 300, "error": 120}
        while True:
            try:
                self.last_state = self.process_batch()
            except Exception as e:
                self.last_state, self.last_error = "error", f"{type(e).__name__}: {e}"[:300]
                logger.debug("photo_vectors: batch failed", exc_info=True)
            sleep(waits.get(self.last_state, 60))


def query_vector(cfg: dict[str, Any], query: str) -> list[float] | None:
    host, model = settings(cfg)
    if not host or not query.strip():
        return None
    key = (host, model, query.strip())
    if key in _QUERY_CACHE:
        return _QUERY_CACHE[key]
    try:
        vec = post_embeddings(host, model, [query.strip()], timeout=5.0)[0]
    except Exception:
        logger.debug("photo_vectors: no vector for the question", exc_info=True)
        return None
    if len(_QUERY_CACHE) > 256:
        _QUERY_CACHE.clear()
    _QUERY_CACHE[key] = vec
    return vec


def scaled(cos: float, mean: float | None = None, std: float | None = None) -> float:
    if mean is not None and std:
        z = (cos - mean) / std
        return max(0.0, min(1.0, (z - Z_FLOOR) / (Z_FULL - Z_FLOOR)))
    return max(0.0, min(1.0, (cos - ABS_FLOOR) / (ABS_FULL - ABS_FLOOR)))


def _all_cosines(conn, vec: list[float], model: str) -> list[tuple[int, float]]:
    try:
        q = pack(vec)
        return [
            (int(f), float(c))
            for f, c in conn.execute(
                "SELECT file_id, 1.0 - vec_distance_cosine(vec, ?) FROM photo_semantic WHERE model = ?", (q, model)
            )
        ]
    except Exception:  # no sqlite-vec: the same in Python (slower; small libraries only)
        out = []
        for fid, blob in conn.execute("SELECT file_id, vec FROM photo_semantic WHERE model = ?", (model,)):
            v = struct.unpack(f"<{len(blob) // 4}f", blob)
            out.append((int(fid), sum(a * b for a, b in zip(vec, v, strict=False))))
        return out


def matches(conn, cfg: dict[str, Any], query: str, k: int = TOP_K) -> dict[int, float]:
    """file_id -> 0..1 for the photos that stand out for the question (all of them, before
    permissions: the caller's SQL decides who may see which)."""
    vec = query_vector(cfg, query)
    if not vec:
        return {}
    _, model = settings(cfg)
    try:
        rows = _all_cosines(conn, vec, model)
    except Exception:
        return {}  # no photo vectors yet
    if not rows:
        return {}
    mean = std = None
    if len(rows) >= MIN_STATS:
        cs = [c for _, c in rows]
        mean = sum(cs) / len(cs)
        std = (sum((c - mean) ** 2 for c in cs) / len(cs)) ** 0.5 or None
    scored = sorted(((fid, scaled(c, mean, std)) for fid, c in rows), key=lambda r: r[1], reverse=True)
    return {fid: s for fid, s in scored[:k] if s > 0.0}


_QUEUE: PhotoVectorQueue | None = None


def get_queue(engine=None, idle: Callable[[], bool] | None = None) -> PhotoVectorQueue:
    """The one queue; the first caller hands in the engine and the idle check."""
    global _QUEUE
    if _QUEUE is None:
        if engine is None or idle is None:
            raise RuntimeError("the photo vector queue starts with the engine and an idle check")
        _QUEUE = PhotoVectorQueue(engine, idle)
    return _QUEUE

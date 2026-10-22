"""
Photo captions and text-in-image search with a local vision model (AI-14).

Photo search used to know only colours, EXIF and folder names. This queue sends one
photo at a time to a vision model on this NAS (Ollama, which runs on the NPU or GPU
when it has one) and stores a one-line caption plus any readable text (OCR). Both
go into the photo search index, so "receipt from the hardware store" or "kids on
the beach" find the right pictures.

It only works when the box is idle: CPU load under half the cores, CPU under 75 °C,
inside the learning schedule if one is set, and never on a sleeping disk when
"Standby-Safe" is on. Results are keyed by file content, so a re-index or a move
keeps them.

Config (rag_config): vision_captions "auto" (default: on when a vision model is
installed) or "off"; vision_model to pin a model.
"""

import base64
import io
import json
import logging
import os
import re
import time
import urllib.request
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("ZettNAS")

VISION_FAMILIES = (
    "llava",
    "bakllava",
    "gemma3",
    "qwen2.5vl",
    "qwen2.5-vl",
    "qwen2-vl",
    "qwen3-vl",
    "minicpm-v",
    "llama3.2-vision",
    "llama4",
    "moondream",
    "granite3.2-vision",
    "mistral-small3",
    "internvl",
)
PROMPT = (
    "You are indexing a personal photo library for search. Reply with JSON only: "
    '{"caption": "<one plain sentence: the main subjects, how many people, the place and what is happening>", '
    '"text": "<all readable text in the image, copied exactly, or empty>"}'
)
MAX_SIDE = 896
CAPTION_MAX = 300
TEXT_MAX = 2000
_MODEL_CACHE: dict[str, tuple[float, str | None]] = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS photo_vision (
    content_key TEXT PRIMARY KEY,
    model TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'done',
    error TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);
"""


def _http_json(url: str, body: dict | None = None, timeout: float = 10.0) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", "User-Agent": "ZettNAS/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")


def pick_model(cfg: dict, host: str, fetch: Callable = _http_json) -> str | None:
    """The configured vision model, else the first installed model that can see images."""
    if cfg.get("vision_model"):
        return str(cfg["vision_model"])
    hit = _MODEL_CACHE.get(host)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    found = None
    try:
        names = [m.get("name") or m.get("model") for m in (fetch(f"{host}/api/tags") or {}).get("models") or []]
    except Exception:
        logger.debug("vision_queue.pick_model: model list unavailable", exc_info=True)
        names = []
    for name in [n for n in names if n]:
        try:
            caps = (fetch(f"{host}/api/show", {"model": name}) or {}).get("capabilities") or []
        except Exception:
            logger.debug("vision_queue.pick_model: /api/show failed for %s", name, exc_info=True)
            caps = []
        if "vision" in caps or (not caps and any(f in name.lower() for f in VISION_FAMILIES)):
            found = name
            break
    _MODEL_CACHE[host] = (time.time(), found)
    return found


def encode_image(path: str) -> str:
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _clean(s: Any, limit: int) -> str:
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(s or ""))
    return re.sub(r"[ \t]+", " ", s).strip()[:limit]


def parse_reply(content: str) -> tuple[str, str]:
    m = re.search(r"\{.*\}", content or "", re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            return _clean(d.get("caption"), CAPTION_MAX), _clean(d.get("text"), TEXT_MAX)
        except ValueError:
            logger.debug("vision_queue.parse_reply: reply was not JSON", exc_info=True)
    return _clean(content, CAPTION_MAX), ""


def describe_image(path: str, model: str, host: str, post: Callable = _http_json) -> tuple[str, str]:
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "keep_alive": "2m",
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": PROMPT, "images": [encode_image(path)]}],
    }
    reply = post(f"{host}/api/chat", body, timeout=180)
    return parse_reply(((reply or {}).get("message") or {}).get("content") or "")


def system_idle() -> bool:
    try:
        if os.getloadavg()[0] > max(1, os.cpu_count() or 1) * 0.5:
            return False
        from backend.hardware.cpu import read_cpu_temp

        return (read_cpu_temp() or 0.0) < 75.0
    except Exception:
        logger.debug("vision_queue.system_idle: probe failed", exc_info=True)
        return False


def merged_caption(base: str, caption: str, text: str) -> str:
    out = caption.rstrip(".")
    if text:
        out += f". Text: {text[:300]}"
    return f"{out}. {base}".strip(" .") if base else out


class VisionQueue:
    def __init__(
        self,
        engine,
        describe: Callable = describe_image,
        idle: Callable = system_idle,
        host: Callable | None = None,
        model_picker: Callable = pick_model,
    ):
        self.engine = engine
        self.describe = describe
        self.idle = idle
        self.host = host
        self.model_picker = model_picker
        self.last_state = "starting"
        self.last_error = ""

    def _host(self) -> str:
        if self.host:
            return self.host()
        from backend.services.rag_engine import _resolve_ollama_host

        return _resolve_ollama_host()

    def _conn(self):
        conn = self.engine._get_conn()
        conn.executescript(SCHEMA)
        return conn

    def _reapply(self, conn) -> int:
        """Puts stored captions back on photos whose index row was rebuilt."""
        rows = conn.execute(
            """SELECT pa.file_id, pa.caption_text, pa.ocr_text, v.caption, v.ocr_text AS vtext
               FROM photo_assets pa JOIN indexed_files f ON f.file_id = pa.file_id
               JOIN photo_vision v ON v.content_key = f.sha256_hash
               WHERE v.status = 'done' AND v.caption != '' AND instr(pa.caption_text, v.caption) = 0
               LIMIT 200"""
        ).fetchall()
        for r in rows:
            self._apply(conn, r["file_id"], r["caption_text"], r["ocr_text"], r["caption"], r["vtext"])
        return len(rows)

    @staticmethod
    def _apply(conn, file_id: int, base_caption: str, base_ocr: str, caption: str, text: str) -> None:
        ocr = base_ocr if not text or text in (base_ocr or "") else "\n".join(x for x in (base_ocr, text) if x)
        conn.execute(
            "UPDATE photo_assets SET caption_text = ?, ocr_text = ? WHERE file_id = ?",
            (merged_caption(base_caption, caption, text), ocr[: TEXT_MAX * 2], file_id),
        )

    def process_one(self) -> str:
        """Captions one photo. Returns what happened; run_forever waits based on it."""
        cfg = self.engine.get_config()
        if not cfg.get("enabled", True) or str(cfg.get("vision_captions", "auto")).lower() == "off":
            return "disabled"
        in_window, _ = self.engine.is_within_learning_schedule()
        if not in_window:
            return "outside-schedule"
        if not self.idle():
            return "busy"
        conn = self._conn()
        try:
            self._reapply(conn)
            conn.commit()
            row = conn.execute(
                """SELECT pa.file_id, f.canonical_path, f.sha256_hash, pa.caption_text, pa.ocr_text
                   FROM photo_assets pa JOIN indexed_files f ON f.file_id = pa.file_id
                   LEFT JOIN photo_vision v ON v.content_key = f.sha256_hash
                   WHERE v.content_key IS NULL OR (v.status = 'error' AND v.attempts < 3 AND v.updated_at < ?)
                   ORDER BY pa.file_id DESC LIMIT 1""",
                (time.time() - 3600,),
            ).fetchone()
            if not row:
                return "empty"
            host = self._host()
            model = self.model_picker(cfg, host)
            if not model:
                return "no-model"
            path = row["canonical_path"]
            if cfg.get("respect_standby", True):
                from backend.services.rag_engine import is_backing_disk_in_standby, resolve_path_backing_dev

                if is_backing_disk_in_standby(resolve_path_backing_dev(path)):
                    return "standby"
            key = row["sha256_hash"]
            try:
                caption, text = self.describe(path, model, host)
                status, err = ("done", "") if caption or text else ("error", "empty reply")
            except Exception as e:
                caption, text, status, err = "", "", "error", f"{type(e).__name__}: {e}"[:300]
                logger.debug("vision_queue: captioning %s failed", path, exc_info=True)
            conn.execute(
                """INSERT INTO photo_vision (content_key, model, caption, ocr_text, status, error, attempts, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(content_key) DO UPDATE SET model = excluded.model, caption = excluded.caption,
                     ocr_text = excluded.ocr_text, status = excluded.status, error = excluded.error,
                     attempts = photo_vision.attempts + 1, updated_at = excluded.updated_at""",
                (key, model, caption, text, status, err, time.time()),
            )
            if status == "done":
                self._apply(conn, row["file_id"], row["caption_text"], row["ocr_text"], caption, text)
            conn.commit()
            self.last_error = err
            return status
        finally:
            conn.close()

    def status(self) -> dict[str, Any]:
        conn = self._conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM photo_assets").fetchone()[0]
            counts = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM photo_vision GROUP BY status")}
        finally:
            conn.close()
        cfg = self.engine.get_config()
        return {
            "mode": str(cfg.get("vision_captions", "auto")).lower(),
            "model": cfg.get("vision_model") or None,
            "photos": total,
            "captioned": counts.get("done", 0),
            "failed": counts.get("error", 0),
            "state": self.last_state,
            "last_error": self.last_error,
        }

    def run_forever(self, sleep: Callable = time.sleep) -> None:
        waits = {
            "done": 2,
            "error": 10,
            "empty": 300,
            "busy": 60,
            "standby": 300,
            "no-model": 600,
            "disabled": 300,
            "outside-schedule": 300,
        }
        while True:
            try:
                self.last_state = self.process_one()
            except Exception as e:
                self.last_state, self.last_error = "error", f"{type(e).__name__}: {e}"[:300]
                logger.debug("vision_queue.run_forever: pass failed", exc_info=True)
            sleep(waits.get(self.last_state, 60))


_QUEUE: VisionQueue | None = None


def get_vision_queue() -> VisionQueue:
    global _QUEUE
    if _QUEUE is None:
        from backend.services.rag_engine import get_rag_engine

        _QUEUE = VisionQueue(get_rag_engine())
    return _QUEUE


def vision_daemon() -> None:
    time.sleep(60)  # let startup and the first index pass settle
    get_vision_queue().run_forever()

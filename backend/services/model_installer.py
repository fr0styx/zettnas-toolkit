"""
Installs language and embedding models into the Ollama runtime ZettNAS uses (AI-03, AI-16).

Before, "Pull" only added a model to a list, so picking it failed later. Now an install
downloads it with Ollama's /api/pull, reports progress, can be cancelled, and checks
afterwards that Ollama really lists the model. Copies of a model under another name
(left by older versions) are reported, never deleted.
"""

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ZettNAS")

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/:@]{0,199}$")
_JOBS: Dict[str, Dict[str, Any]] = {}
_CANCEL: Dict[str, threading.Event] = {}
_LOCK = threading.Lock()


def _host() -> str:
    from backend.services.rag_engine import _resolve_ollama_host

    return _resolve_ollama_host()


def valid_model_name(name: str) -> bool:
    return bool(_NAME_RE.match(str(name or ""))) and ".." not in str(name)


def _tags(host: str, timeout: float = 3.0) -> List[Dict[str, Any]]:
    req = urllib.request.Request(f"{host}/api/tags", headers={"User-Agent": "ZettNAS-Toolkit"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return list(json.loads(resp.read().decode("utf-8")).get("models") or [])


def _same(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    return a == b or a == f"{b}:latest" or b == f"{a}:latest"


def installed_models() -> Dict[str, Any]:
    """What Ollama has installed, plus names that are copies of another installed model."""
    host = _host()
    try:
        models = _tags(host)
    except Exception as e:
        return {"reachable": False, "host": host, "models": [], "aliases": [], "error": str(e)}
    by_digest: Dict[str, List[str]] = {}
    for m in models:
        if m.get("digest"):
            by_digest.setdefault(m["digest"], []).append(m.get("name", ""))
    aliases = []
    for names in by_digest.values():
        if len(names) > 1:
            names = sorted(names, key=lambda n: (("/" in n) is False, len(n)))
            for extra in names[1:]:
                aliases.append({"name": extra, "same_as": names[0]})
    return {
        "reachable": True,
        "host": host,
        "models": [
            {
                "name": m.get("name"),
                "size_bytes": m.get("size"),
                "digest": m.get("digest"),
                "modified_at": m.get("modified_at"),
            }
            for m in models
        ],
        "aliases": aliases,
    }


def is_installed(name: str, models: Optional[List[Dict[str, Any]]] = None) -> bool:
    if models is None:
        models = installed_models().get("models") or []
    return any(_same(str(m.get("name") or ""), name) for m in models)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def cancel_job(job_id: str) -> bool:
    ev = _CANCEL.get(job_id)
    if not ev:
        return False
    ev.set()
    return True


def start_install(name: str, requested_by: str = "") -> Dict[str, Any]:
    name = str(name or "").strip()
    if not valid_model_name(name):
        raise ValueError("That isn't a valid model name.")
    with _LOCK:
        for job in _JOBS.values():
            if job["model"].lower() == name.lower() and job["state"] in ("starting", "downloading", "verifying"):
                return dict(job)
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "model": name,
            "state": "starting",
            "status": "Starting",
            "percent": 0.0,
            "completed_bytes": 0,
            "total_bytes": 0,
            "error": "",
            "requested_by": requested_by,
            "started_at": time.time(),
            "finished_at": None,
        }
        _JOBS[job_id] = job
        _CANCEL[job_id] = threading.Event()
    threading.Thread(target=_run, args=(job_id,), name=f"model-install-{job_id}", daemon=True).start()
    return dict(job)


def _update(job_id: str, **fields: Any) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(fields)


def _run(job_id: str) -> None:
    job = get_job(job_id) or {}
    name = job.get("model", "")
    cancel = _CANCEL[job_id]
    host = _host()
    layers: Dict[str, Dict[str, int]] = {}
    try:
        req = urllib.request.Request(
            f"{host}/api/pull",
            data=json.dumps({"model": name, "stream": True}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "ZettNAS-Toolkit"},
            method="POST",
        )
        _update(job_id, state="downloading", status="Connecting to the model registry")
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            for raw in resp:
                if cancel.is_set():
                    _update(job_id, state="cancelled", status="Cancelled", finished_at=time.time())
                    return
                try:
                    msg = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if msg.get("error"):
                    raise RuntimeError(str(msg["error"]))
                if msg.get("digest") and msg.get("total"):
                    layers[msg["digest"]] = {"total": int(msg["total"]), "completed": int(msg.get("completed") or 0)}
                total = sum(v["total"] for v in layers.values())
                done = sum(min(v["completed"], v["total"]) for v in layers.values())
                _update(
                    job_id,
                    status=str(msg.get("status") or "Downloading"),
                    total_bytes=total,
                    completed_bytes=done,
                    percent=round(100.0 * done / total, 1) if total else 0.0,
                )
                if msg.get("status") == "success":
                    break
        _update(job_id, state="verifying", status="Checking the model is installed")
        if not is_installed(name, installed_models().get("models")):
            raise RuntimeError("Ollama finished but doesn't list the model; the download may be incomplete.")
        _update(job_id, state="done", status="Installed", percent=100.0, finished_at=time.time())
        logger.info(f"[ModelInstaller] Installed {name} at {host}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", "")
        except Exception:
            pass
        _update(job_id, state="failed", status="Failed", error=detail or f"HTTP {e.code}", finished_at=time.time())
    except Exception as e:
        _update(job_id, state="failed", status="Failed", error=str(e), finished_at=time.time())
        logger.warning(f"[ModelInstaller] Installing {name} failed: {e}")
    finally:
        _CANCEL.pop(job_id, None)

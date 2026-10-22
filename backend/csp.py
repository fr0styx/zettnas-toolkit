"""
Content-Security-Policy for the web UI, report-only for now (FE-06).

The UI still has an inline bootstrap script and a few inline event handlers,
so an enforced policy would break it. Browsers report what an enforced policy
would block to /api/csp-report; those reports show what is left to fix before
Batch 4 switches to enforcement. The inline bootstrap script is allowed by its
SHA-256 hash, read from the built index.html at startup.
"""

import base64
import hashlib
import os
import re
import threading
import time
from typing import Dict, List

from backend import config

_policy_cache: Dict[str, str] = {}
_reports: Dict[str, float] = {}
_lock = threading.Lock()
REPORT_PATH = "/api/csp-report"


def _inline_script_hashes() -> List[str]:
    index = os.path.join(getattr(config, "STATIC_DIR", ""), "index.html")
    try:
        with open(index, encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return []
    hashes = []
    for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I):
        digest = hashlib.sha256(m.group(1).encode("utf-8")).digest()
        hashes.append("'sha256-" + base64.b64encode(digest).decode() + "'")
    return hashes


def policy() -> str:
    with _lock:
        if "policy" in _policy_cache:
            return _policy_cache["policy"]
    scripts = " ".join(["'self'", *_inline_script_hashes()])
    value = "; ".join(
        [
            "default-src 'self'",
            f"script-src {scripts}",
            "style-src 'self' 'unsafe-inline'",  # ~5,000 inline styles; phase 2 removes them
            "img-src 'self' data: blob: https:",
            "media-src 'self' blob:",
            "font-src 'self' data:",
            "connect-src 'self' ws: wss:",
            "worker-src 'self' blob:",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'self'",
            f"report-uri {REPORT_PATH}",
        ]
    )
    with _lock:
        _policy_cache["policy"] = value
    return value


def record_report(report: dict) -> bool:
    """Logs one line per distinct violation per hour. Returns True if it was logged."""
    body = report.get("csp-report", report) if isinstance(report, dict) else {}
    directive = str(body.get("violated-directive") or body.get("effectiveDirective") or "")[:80]
    blocked = str(body.get("blocked-uri") or body.get("blockedURL") or "")[:200]
    source = str(body.get("source-file") or body.get("sourceFile") or "")[:200]
    line = body.get("line-number") or body.get("lineNumber") or ""
    key = f"{directive}|{blocked}|{source}|{line}"
    now = time.time()
    with _lock:
        if now - _reports.get(key, 0) < 3600:
            return False
        if len(_reports) > 500:
            _reports.clear()
        _reports[key] = now
    from backend.config import logger

    logger.info(f"[CSP report-only] {directive} blocked={blocked or '-'} at {source or '-'}:{line}")
    return True

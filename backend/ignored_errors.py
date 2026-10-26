"""Errors the code deliberately carries on after, made visible (ARC-4).

About 310 places catch an error and carry on, logging it as
logger.debug("<where>: ignored error", exc_info=True), where nobody in the field would ever
see it. install() (called when the backend package loads) routes exactly those calls, on any
logger, to ignored(where); new code can call ignored("where") directly. Each place is
counted; its first error is logged as a warning, later ones at most once a day with a count,
and the full traceback still goes to the debug log. Diagnostics show the counts (snapshot()).

Only the standard library is imported here, so any module can use it.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

logger = logging.getLogger("ZettNAS")

REPEAT_WARNING_SECS = 24 * 3600.0
_LOCK = threading.Lock()
# where -> {"count", "since_warning", "warned_at", "last", "last_at"}
_SITES: dict[str, dict] = {}


def _describe(exc: BaseException | None) -> str:
    if exc is None:
        return "no exception"
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) <= 300 else text[:297] + "..."


def ignored(where: str, now: float | None = None) -> None:
    """Record the exception being handled at `where` and carry on."""
    exc = sys.exc_info()[1]
    now = time.time() if now is None else now
    desc = _describe(exc)
    with _LOCK:
        site = _SITES.setdefault(where, {"count": 0, "since_warning": 0, "warned_at": None, "last": "", "last_at": 0.0})
        site["count"] += 1
        site["since_warning"] += 1
        site["last"], site["last_at"] = desc, now
        warn = site["warned_at"] is None or now - site["warned_at"] >= REPEAT_WARNING_SECS
        if warn:
            repeats = site["since_warning"]
            site["warned_at"], site["since_warning"] = now, 0
    if warn:
        more = f" ({repeats} times since the last warning)" if site["count"] > 1 else ""
        logger.warning(f"[ignored] {where}: {desc}{more}", extra={"ignored_at": where, "repeats": repeats})
    logger.log(logging.DEBUG, "%s: traceback of the ignored error", where, exc_info=exc is not None)


SUFFIX = ": ignored error"
_PLAIN_DEBUG = logging.Logger.debug


def _debug(self, msg, *args, **kwargs):
    """Logger.debug, with "<where>: ignored error" (plus exc_info) counted as an ignored error."""
    if type(msg) is str and not args and kwargs.get("exc_info") and msg.endswith(SUFFIX):
        ignored(msg[: -len(SUFFIX)])
        return None
    return _PLAIN_DEBUG(self, msg, *args, **kwargs)


def install() -> None:
    logging.Logger.debug = _debug  # type: ignore[method-assign]


def snapshot(top: int = 20) -> dict:
    """The places that ignored errors, most frequent first (for diagnostics)."""
    with _LOCK:
        sites = [
            {"where": w, "count": s["count"], "last": s["last"], "last_at": round(s["last_at"])}
            for w, s in _SITES.items()
        ]
    sites.sort(key=lambda s: (-s["count"], s["where"]))
    return {"total": sum(s["count"] for s in sites), "places": len(sites), "top": sites[:top]}


def reset() -> None:
    with _LOCK:
        _SITES.clear()

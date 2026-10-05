"""
ZettNAS Toolkit - Application Entrypoint
Modular Backend Architecture
"""

import atexit
import gzip
import hashlib
import io
import mimetypes
import os
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response

from backend import __version__
from backend.api import api_router
from backend.auth import _load_sessions, auth_middleware
from backend.config import (
    COLLECTOR_WATCHDOG_SECS,
    DATA_DIR,
    LED_STATE_FILE,
    STATIC_DIR,
    _load_security,
    is_using_default_password,
    logger,
)
from backend.db import init_db
from backend.errors import register_error_handlers
from backend.fsutil import read_json
from backend.hardware.cpu import read_cpu_util
from backend.hardware.fans import failsafe_release_fans
from backend.hardware.led import apply_led_state
from backend.hardware.network import read_ip
from backend.hardware.storage import detect_chassis_model
from backend.services.button_listener import button_listener_daemon
from backend.services.lcd_renderer import render_lcd_loop
from backend.services.stats_collector import stats_collector_daemon
from backend.state import Z_STATE, _load_events, add_event


def _load_static_file(fp: str):
    """Load a static file into cache with ETag, gzip, and mtime validation."""
    with Z_STATE.lock:
        try:
            mtime = os.path.getmtime(fp)
        except OSError:
            return None
        if fp in Z_STATE.static_cache:
            entry = Z_STATE.static_cache[fp]
            if len(entry) == 4 and entry[3] == mtime:
                return entry
        try:
            with open(fp, "rb") as f:
                content = f.read()
        except OSError:
            return None

        etag = '"' + hashlib.md5(content).hexdigest()[:16] + '"'
        gz_content = None
        if len(content) > 1024:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
                gz.write(content)
            gz_content = buf.getvalue()
        entry = (content, etag, gz_content, mtime)
        Z_STATE.static_cache[fp] = entry
        return entry


def startup_system():
    """System initialization and background services launch."""
    read_cpu_util()
    if DATA_DIR:
        os.makedirs(DATA_DIR, exist_ok=True)

    init_db()
    _load_security()
    _load_sessions()
    _load_events()
    read_ip()  # Pre-populate IP cache at startup
    detect_chassis_model()  # Pre-populate chassis model cache

    if is_using_default_password():
        logger.warning("=" * 60)
        logger.warning("[SECURITY WARNING] Default password ('admin') is active!")
        logger.warning("[SECURITY WARNING] Change password in Toolkit Settings.")
        logger.warning("=" * 60)
        add_event(
            "warning",
            "Default Password In Use",
            "The system is using the default password 'admin'. Please change it in Settings.",
        )

    led_cfg = read_json(LED_STATE_FILE, None)
    if isinstance(led_cfg, dict):
        try:
            apply_led_state(led_cfg)
        except OSError as e:
            logger.warning(f"Failed to apply initial LED state: {e}")

    threading.Thread(target=stats_collector_daemon, daemon=True, name="StatsCollector").start()
    threading.Thread(target=button_listener_daemon, daemon=True, name="ButtonListener").start()
    threading.Thread(target=render_lcd_loop, daemon=True, name="LcdRenderer").start()
    threading.Thread(target=fan_watchdog_daemon, daemon=True, name="FanWatchdog").start()
    # Backup in case the server exits without running the lifespan shutdown.
    # Registered here (not at import) so tooling that imports app.py is inert.
    atexit.register(lambda: Z_STATE.fans_locked or _shutdown_fans("exit"))


def fan_watchdog_daemon():
    """Hand fans back to firmware if the stats collector stops updating.

    The collector is the only thing driving PWM. If it hangs (e.g. a blocked
    smartctl call) the fans would stay frozen at their last value, so after
    COLLECTOR_WATCHDOG_SECS without a heartbeat we engage the failsafe. The
    collector automatically reclaims control once it recovers.
    """
    while True:
        time.sleep(5)
        hb = Z_STATE.collector_heartbeat
        if not hb or Z_STATE.fans_locked:
            continue
        stale = time.time() - hb
        if stale > COLLECTOR_WATCHDOG_SECS and not Z_STATE.fans_released:
            logger.error(f"[WATCHDOG] Stats collector unresponsive for {int(stale)}s.")
            failsafe_release_fans("watchdog")
            add_event(
                "error",
                "Fan Watchdog Triggered",
                f"Stats collector stalled for {int(stale)}s; fans returned to firmware control.",
            )


def _shutdown_fans(reason: str):
    try:
        failsafe_release_fans(reason, lock=True)
    except Exception as e:  # never block shutdown
        logger.error(f"[FANS] Failsafe on {reason} failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_system()
    try:
        yield
    finally:
        Z_STATE.shutting_down = True
        if not Z_STATE.fans_locked:
            _shutdown_fans("shutdown")


app = FastAPI(title="ZettNAS Toolkit", version=__version__, docs_url="/docs", redoc_url="/redoc", lifespan=lifespan)

# Consistent {error, detail, code} error responses
register_error_handlers(app)

# Authentication middleware
app.middleware("http")(auth_middleware)

# Register API routers with backwards-compatible /api alias and modern /api/v1 prefix
app.include_router(api_router, prefix="/api")
app.include_router(api_router, prefix="/api/v1")


@app.get("/{path:path}")
async def serve_static(request: Request, path: str):
    if not path or path == "":
        path = "index.html"

    base_dir = os.path.abspath(STATIC_DIR)
    fp = os.path.abspath(os.path.join(base_dir, path))
    if not (fp == base_dir or fp.startswith(base_dir + os.sep)) or not os.path.isfile(fp):
        raise HTTPException(status_code=404, detail="not found")

    entry = _load_static_file(fp)
    if not entry:
        raise HTTPException(status_code=404, detail="not found")

    content, etag, gz_content, _mtime = entry
    ctype, _ = mimetypes.guess_type(fp)
    if not ctype:
        ctype = "application/octet-stream"

    if fp.endswith("index.html"):
        html_str = content.decode("utf-8")
        if request.query_params.get("mode") == "lcd" or "mode=lcd" in str(request.query_params):
            html_str = html_str.replace('<body class="studio-workbench">', '<body class="studio-workbench lcd-direct">')
        content = html_str.encode("utf-8")
        etag = None
        gz_content = None

    headers = {}
    if etag:
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "max-age=3600"})
        headers["ETag"] = etag
        headers["Cache-Control"] = "max-age=3600"
    else:
        headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

    if gz_content and "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
        return Response(content=gz_content, media_type=ctype, headers=headers)

    return Response(content=content, media_type=ctype, headers=headers)


class ZettServer(uvicorn.Server):
    """Engage the fan failsafe as soon as a stop signal arrives.

    uvicorn runs the lifespan shutdown only after open connections drain; the
    long-lived SSE streams (incl. the LCD renderer) can keep that from ever
    happening before Docker's SIGKILL, so we don't rely on it alone.
    """

    def handle_exit(self, sig, frame):
        Z_STATE.shutting_down = True
        if not Z_STATE.fans_locked:
            _shutdown_fans(f"signal {sig}")
        super().handle_exit(sig, frame)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8082"))
    logger.info(f"ZettNAS dashboard starting on :{port} (version {__version__})")
    server_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        timeout_graceful_shutdown=3,
    )
    ZettServer(server_config).run()

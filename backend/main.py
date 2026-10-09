"""
ZettNAS Toolkit - Application Entrypoint
Modular Backend Architecture
"""

import asyncio
import atexit
import os
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

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
from backend.services.broadcaster import broadcaster
from backend.api.webdav import proxy_router as webdav_proxy_router
from backend.services.webdav_engine import get_webdav_engine
from backend.services.notifications import close_notification_client
from backend.services.button_listener import button_listener_daemon
from backend.services.lcd_renderer import render_lcd_loop
from backend.services.stats_collector import smart_poller_daemon, stats_collector_daemon
from backend.state import Z_STATE, _load_events, add_event


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
    threading.Thread(target=smart_poller_daemon, daemon=True, name="SmartPoller").start()
    threading.Thread(target=button_listener_daemon, daemon=True, name="ButtonListener").start()
    threading.Thread(target=render_lcd_loop, daemon=True, name="LcdRenderer").start()
    threading.Thread(target=fan_watchdog_daemon, daemon=True, name="FanWatchdog").start()

    try:
        get_webdav_engine().start_if_enabled()
    except Exception as e:
        logger.warning(f"Could not auto-start WebDAV engine: {e}")

    # Backup in case the server exits without running the lifespan shutdown.
    # Registered here (not at import) so tooling that imports main.py is inert.
    atexit.register(lambda: Z_STATE.fans_locked or _shutdown_fans("exit"))


def fan_watchdog_daemon():
    """Hand fans back to firmware if the stats collector stops updating.

    The collector is the only thing driving PWM. If it hangs (e.g. a blocked
    smartctl call) the fans would stay frozen at their last value, so after
    COLLECTOR_WATCHDOG_SECS without a heartbeat we engage the failsafe. The
    collector automatically reclaims control once it recovers.
    """
    while not Z_STATE.shutting_down:
        time.sleep(5)
        if Z_STATE.shutting_down:
            break
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
    broadcaster.set_loop(asyncio.get_running_loop())
    startup_system()
    try:
        yield
    finally:
        Z_STATE.shutting_down = True
        Z_STATE.ui_wake.set()
        broadcaster.shutdown()
        close_notification_client()
        try:
            get_webdav_engine().stop()
        except Exception:
            pass
        if not Z_STATE.fans_locked:
            _shutdown_fans("shutdown")


app = FastAPI(title="ZettNAS Toolkit", version=__version__, docs_url="/docs", redoc_url="/redoc", lifespan=lifespan)

# Consistent {error, detail, code} error responses
register_error_handlers(app)


# Enterprise defense-in-depth HTTP security headers middleware
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


# Authentication middleware
app.middleware("http")(auth_middleware)

# WebDAV streaming reverse proxy
app.include_router(webdav_proxy_router)

# Register API routers with backwards-compatible /api alias and modern /api/v1 prefix
app.include_router(api_router, prefix="/api")
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
@app.get("/index.html")
def serve_index(request: Request):
    index_file = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_file):
        raise HTTPException(status_code=404, detail="index.html not found")
    with open(index_file, "r", encoding="utf-8") as f:
        html_str = f.read()
    if request.query_params.get("mode") == "lcd" or "mode=lcd" in str(request.query_params):
        html_str = html_str.replace('<body class="studio-workbench">', '<body class="studio-workbench lcd-direct">')
    return Response(
        content=html_str,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# Mount static assets using native FastAPI StaticFiles for streaming, proper Range headers, and zero RAM caching
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")


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


def main():
    port = int(os.environ.get("PORT", "8082"))
    trusted_proxies = os.environ.get("TRUSTED_PROXIES", "127.0.0.1")
    logger.info(f"ZettNAS dashboard starting on :{port} (version {__version__})")
    server_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        ws="none",
        timeout_keep_alive=15,
        timeout_graceful_shutdown=3,
        proxy_headers=True,
        forwarded_allow_ips=trusted_proxies,
        server_header=False,
        limit_concurrency=256,
    )
    ZettServer(server_config).run()


if __name__ == "__main__":
    main()

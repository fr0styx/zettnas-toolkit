"""
ZettNAS Toolkit - Application Entrypoint
Modular Backend Architecture
"""

import asyncio
import atexit
import glob
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

from backend import __version__
from backend.api import api_router
from backend.auth import _load_sessions, auth_middleware
from backend.logging_config import correlation_id_ctx, setup_structured_logging
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
from backend.services.backup_engine import start_backup_scheduler, stop_backup_scheduler
from backend.state import Z_STATE, _load_events, add_event


def startup_system():
    """System initialization and background services launch."""
    import gc

    gc.set_threshold(50000, 10, 10)
    setup_structured_logging()
    read_cpu_util()
    if DATA_DIR:
        os.makedirs(DATA_DIR, exist_ok=True)

    init_db()
    _load_security()
    _load_sessions()
    _load_events()
    read_ip()  # Pre-populate IP cache at startup
    detect_chassis_model()  # Pre-populate chassis model cache

    # Auto-link host KVM, vhost-net, mem, and USB/HID nodes into container /dev if present
    for node, host_node in [
        ("/dev/kvm", "/host/dev/kvm"),
        ("/dev/vhost-net", "/host/dev/vhost-net"),
        ("/dev/mem", "/host/dev/mem"),
        ("/dev/bus/usb", "/host/dev/bus/usb"),
        ("/dev/usb", "/host/dev/usb"),
    ]:
        if not os.path.exists(node) and os.path.exists(host_node):
            try:
                os.symlink(host_node, node)
                logger.info(f"[DEV] Auto-linked {node} -> {host_node}")
            except OSError as e:
                logger.debug(f"[DEV] Could not link {node}: {e}")

    # Auto-link any character hidraw devices (/host/dev/hidraw*) into container /dev
    for h_node in glob.glob("/host/dev/hidraw*"):
        target_node = os.path.join("/dev", os.path.basename(h_node))
        if not os.path.exists(target_node):
            try:
                os.symlink(h_node, target_node)
                logger.info(f"[DEV] Auto-linked {target_node} -> {h_node}")
            except OSError as e:
                logger.debug(f"[DEV] Could not link {target_node}: {e}")

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
    from backend.hardware.fans import is_zettlab_appliance

    if is_zettlab_appliance():
        threading.Thread(target=button_listener_daemon, daemon=True, name="ButtonListener").start()
    else:
        logger.debug("[Main] Non-appliance hardware detected; skipping ButtonListener daemon.")
    threading.Thread(target=render_lcd_loop, daemon=True, name="LcdRenderer").start()
    threading.Thread(target=fan_watchdog_daemon, daemon=True, name="FanWatchdog").start()

    try:
        get_webdav_engine().start_if_enabled()
    except Exception as e:
        logger.warning(f"Could not auto-start WebDAV engine: {e}")

    try:
        start_backup_scheduler()
    except Exception as e:
        logger.warning(f"Could not auto-start hyper-backup scheduler: {e}")

    try:
        from backend.services.scheduler import start_scheduler

        start_scheduler()
    except Exception as e:
        logger.warning(f"Could not auto-start SMART test scheduler: {e}")

    try:
        from backend.services.rag_engine import get_rag_engine

        get_rag_engine()
        logger.info("[ZettAI] Spin-up auto-learner & standby guard daemon initialized.")
    except Exception as e:
        logger.warning(f"Could not auto-start ZettAI spin-up watcher: {e}")

    # VM Autostart Background Daemon
    def _autostart_vms():
        try:
            import time

            time.sleep(3.0)  # Brief pause to allow storage and bridge initialization
            from backend.api.vms import _load_vms, _start_qemu, _is_qemu_process_alive, _get_qemu_vnc_port, _save_vms

            vms = _load_vms()
            started_any = False
            for vm in vms:
                if vm.get("autostart") and vm.get("state") != "running":
                    vm_id = vm.get("id")
                    if not _is_qemu_process_alive(vm_id):
                        vnc_port = _get_qemu_vnc_port(vms, vm_id)
                        logger.info(f"[VM Autostart] Starting VM '{vm.get('name')}' (ID: {vm_id})...")
                        ok, _ = _start_qemu(vm, vnc_port)
                        if ok:
                            vm["state"] = "running"
                            started_any = True
            if started_any:
                _save_vms(vms)
        except Exception as e:
            logger.warning(f"[VM Autostart] Error starting autostart VMs: {e}")

    threading.Thread(target=_autostart_vms, daemon=True, name="VmAutostart").start()

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
    import concurrent.futures
    import multiprocessing

    loop = asyncio.get_running_loop()
    try:
        cpu_cores = multiprocessing.cpu_count()
    except Exception:
        cpu_cores = 4
    worker_count = min(64, max(16, cpu_cores * 4))
    loop.set_default_executor(
        concurrent.futures.ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ZettAsyncWorker")
    )
    broadcaster.set_loop(loop)
    startup_system()
    try:
        yield
    finally:
        Z_STATE.shutting_down = True
        Z_STATE.ui_wake.set()
        broadcaster.shutdown()
        close_notification_client()
        try:
            from backend.services.scheduler import stop_scheduler

            stop_scheduler()
        except Exception:
            pass
        stop_backup_scheduler()
        try:
            get_webdav_engine().stop()
        except Exception:
            pass
        try:
            from backend.services.sftp_engine import get_sftp_engine

            get_sftp_engine().stop()
        except Exception:
            pass
        if not Z_STATE.fans_locked:
            _shutdown_fans("shutdown")


app = FastAPI(
    title="ZettNAS Toolkit",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)

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
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# Authentication middleware
app.middleware("http")(auth_middleware)


# Request correlation ID tracking middleware (outermost in processing chain)
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    corr_id = request.headers.get("X-Correlation-ID") or secrets.token_hex(8)
    token = correlation_id_ctx.set(corr_id)
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = corr_id
        return response
    finally:
        correlation_id_ctx.reset(token)


# WebDAV streaming reverse proxy
app.include_router(webdav_proxy_router)

# DMTF Redfish Scalable Platforms Management API
from backend.api.redfish import router as redfish_router

app.include_router(redfish_router, prefix="/redfish/v1")
app.include_router(redfish_router, prefix="/redfish")

# Register API routers with backwards-compatible /api alias and modern /api/v1 prefix
app.include_router(api_router, prefix="/api")
app.include_router(api_router, prefix="/api/v1")


@app.api_route("/api/{unmatched_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
@app.api_route("/api/v1/{unmatched_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def api_route_not_found(unmatched_path: str):
    raise HTTPException(status_code=404, detail=f"API route '/api/{unmatched_path}' not found.")


@app.get("/")
@app.get("/index.html")
def serve_index(request: Request):
    index_file = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_file):
        raise HTTPException(status_code=404, detail="index.html not found")
    with open(index_file, "r", encoding="utf-8") as f:
        html_str = f.read()
    if request.query_params.get("mode") == "lcd" or "mode=lcd" in str(request.query_params):
        html_str = html_str.replace('class="studio-workbench', 'class="studio-workbench lcd-direct')
    return Response(
        content=html_str,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# Mount static assets using native FastAPI StaticFiles for streaming, proper Range headers, and zero RAM caching
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


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
        ws="auto",
        ws_max_size=16777216,
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

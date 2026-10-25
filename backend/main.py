"""
ZettNAS Toolkit - Application Entrypoint
Modular Backend Architecture
"""

import asyncio
import atexit
import glob
import json
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

from backend import __version__
from backend.api import api_router
from backend.api.webdav import proxy_router as webdav_proxy_router
from backend.auth import auth_middleware, purge_legacy_session_files
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
from backend.fast_json import FastJSONResponse
from backend.fsutil import read_json
from backend.hardware.cpu import read_cpu_util
from backend.hardware.fans import failsafe_release_fans
from backend.hardware.led import apply_led_state
from backend.hardware.network import read_ip
from backend.hardware.storage import detect_chassis_model
from backend.logging_config import correlation_id_ctx, setup_structured_logging
from backend.services.backup_engine import stop_backup_scheduler
from backend.services.broadcaster import broadcaster
from backend.services.button_listener import button_listener_daemon
from backend.services.lcd_renderer import render_lcd_loop
from backend.services.notifications import close_notification_client
from backend.services.stats_collector import smart_poller_daemon, stats_collector_daemon
from backend.services.webdav_engine import get_webdav_engine
from backend.state import Z_STATE, _load_events, add_event


def _start_docker_proxy(supervise) -> None:
    """Runs the Docker API allow-list proxy as its own process and points the app at it (SEC-09)."""
    import subprocess
    import sys

    from backend.config import RAW_DOCKER_SOCK

    if os.environ.get("ZETTNAS_DOCKER_PROXY", "on") == "off" or os.environ.get("TESTING") == "1":
        return
    if not os.path.exists(RAW_DOCKER_SOCK):
        return
    sock = os.environ.get("ZETTNAS_DOCKER_PROXY_SOCK", "/run/zettnas/docker.sock")

    def run() -> None:
        env = {**os.environ, "ZETTNAS_DOCKER_PROXY_SOCK": sock}
        env.pop("ZETTNAS_DOCKER_SOCK", None)
        rc = subprocess.run([sys.executable, "-m", "backend.docker_proxy"], env=env).returncode
        raise RuntimeError(f"docker proxy exited with code {rc}")

    supervise("DockerProxy", run)
    for _ in range(50):
        if os.path.exists(sock):
            os.environ["ZETTNAS_DOCKER_SOCK"] = sock
            logger.info(f"[Main] Docker API calls go through the allow-list proxy at {sock}")
            return
        time.sleep(0.1)
    logger.warning("[Main] Docker proxy did not start; using the Docker socket directly")


def startup_system():
    """System initialization and background services launch."""
    import gc

    gc.set_threshold(50000, 10, 10)
    setup_structured_logging()
    read_cpu_util()
    if DATA_DIR:
        os.makedirs(DATA_DIR, exist_ok=True)

    # Refuse databases written by a newer ZettNAS before touching them (OPS-03).
    from backend.db_schema import NewerDatabaseError, check_versions, stamp_versions

    try:
        check_versions()
    except NewerDatabaseError as e:
        logger.critical(f"[Main] {e}")
        raise SystemExit(3) from e

    # A new build on this data folder without an in-app update (Unraid Docker tab, compose pull):
    # snapshot the data before anything is migrated (OPS-4)
    try:
        from backend.services.data_snapshot import snapshot_if_build_changed

        snapshot_if_build_changed(DATA_DIR)
    except Exception as e:
        logger.error(f"[Main] Could not snapshot the data folder for the new build: {e}")

    # Damaged databases are found before anything opens them (REL-2)
    try:
        from backend.services.data_health import check_and_repair

        check_and_repair(DATA_DIR)
    except Exception as e:
        logger.error(f"[Main] Could not check the data folder's databases: {e}")

    # Encryption at rest for the AI chat history (AI-20); the index follows in the background
    from backend import db_crypto
    from backend.services.ai_conversations_db import get_db_path as _conv_db_path

    _data_key_problem = ""
    try:
        db_crypto.prepare(_conv_db_path())
    except Exception as e:
        _data_key_problem = str(e)
        logger.critical(f"[Encryption] {e}")

    init_db()
    _load_security()
    purge_legacy_session_files()
    _load_events()
    try:
        from backend.services import security_upgrade

        security_upgrade.run_once()  # v1.9.2: revoke old credentials, disable unsafe WebDAV
        security_upgrade.run_1_10_2_once()  # v1.10.2: token, role, backup and WebDAV cleanup
    except Exception as e:
        logger.error(f"[Main] Security upgrade step failed: {e}")
    try:
        from backend.api.auth import align_admin_password_mirror

        align_admin_password_mirror()
    except Exception as e:
        logger.error(f"[Main] Could not align the admin password copy: {e}")
    stamp_versions()
    try:
        from backend.services.self_updater import report_last_update_result

        report_last_update_result(DATA_DIR)  # event + notification if the last update rolled back (OPS-7)
    except Exception as e:
        logger.error(f"[Main] Could not report the last update result: {e}")
    from backend.services.rag_engine import RAG_DB_PATH as _rag_db_path

    db_crypto.prepare_in_background(_rag_db_path)
    if _data_key_problem:
        add_event("error", "AI data locked", _data_key_problem)
    try:
        from backend.secret_box import migrate_plaintext_mfa_secrets

        migrate_plaintext_mfa_secrets()
    except Exception as e:
        logger.error(f"[Main] Could not encrypt stored two-factor secrets: {e}")
    try:
        from backend.services.data_permissions import harden_data_permissions

        harden_data_permissions()
    except Exception as e:
        logger.warning(f"[Main] Could not tighten data permissions: {e}")
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

    # Supervised: a daemon that crashes is logged and restarted with back-off (ARC-02)
    from backend.services.supervisor import supervise

    _start_docker_proxy(supervise)

    supervise("StatsCollector", stats_collector_daemon)
    supervise("SmartPoller", smart_poller_daemon)
    from backend.hardware.fans import is_zettlab_appliance

    if is_zettlab_appliance():
        supervise("ButtonListener", button_listener_daemon)
    else:
        logger.debug("[Main] Non-appliance hardware detected; skipping ButtonListener daemon.")
    supervise("LcdRenderer", render_lcd_loop)
    supervise("FanWatchdog", fan_watchdog_daemon)
    if os.environ.get("TESTING") != "1":
        from backend.services.vision_queue import vision_daemon

        supervise("VisionCaptioner", vision_daemon)  # AI-14, idle-only
        from backend.services.ransomware_guard import guard_daemon

        supervise("RansomwareGuard", guard_daemon)  # M4: guard-file checks
        from backend.services.data_health import data_guard_daemon

        supervise("DataGuard", data_guard_daemon)  # REL-2: daily data snapshot

    try:
        get_webdav_engine().start_if_enabled()
    except Exception as e:
        logger.warning(f"Could not auto-start WebDAV engine: {e}")

    # Schedulers run supervised, so a crash is restarted and shows in health (ARC-10)
    from backend.services.backup_engine import backup_scheduler_daemon

    supervise("BackupScheduler", backup_scheduler_daemon)

    from backend.services.scheduler import scheduler_daemon

    supervise("TaskScheduler", scheduler_daemon)  # SMART tests and scrubs on schedule

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
            from backend.api.vms import _get_qemu_vnc_port, _is_qemu_process_alive, _load_vms, _save_vms, _start_qemu

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
            logger.debug("backend.main.lifespan: ignored error", exc_info=True)
        stop_backup_scheduler()
        try:
            get_webdav_engine().stop()
        except Exception:
            logger.debug("backend.main.lifespan: ignored error", exc_info=True)
        try:
            from backend.services.sftp_engine import get_sftp_engine

            get_sftp_engine().stop()
        except Exception:
            logger.debug("backend.main.lifespan: ignored error", exc_info=True)
        if not Z_STATE.fans_locked:
            _shutdown_fans("shutdown")


app = FastAPI(
    title="ZettNAS Toolkit",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    default_response_class=FastJSONResponse,
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
    # Enforced CSP for the UI pages (FE-06); user files keep their own sandbox policy (SEC-05)
    if "content-security-policy" not in response.headers and response.headers.get("content-type", "").startswith(
        "text/html"
    ):
        from backend.csp import policy

        response.headers["Content-Security-Policy"] = policy()
    from backend.auth import request_is_https

    if request_is_https(request):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# Authentication middleware
app.middleware("http")(auth_middleware)


@app.post("/api/csp-report", include_in_schema=False)
async def csp_report(request: Request):
    """Browsers post CSP violation reports here (report-only mode, FE-06)."""
    from backend.csp import record_report

    body = await request.body()
    if len(body) > 16384:
        return Response(status_code=413)
    try:
        record_report(json.loads(body or b"{}"))
    except ValueError:
        pass
    return Response(status_code=204)


# Request correlation ID tracking middleware (outermost in processing chain)

from backend.request_metrics import REQUEST_METRICS, route_template  # noqa: E402


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    corr_id = request.headers.get("X-Correlation-ID") or secrets.token_hex(8)
    token = correlation_id_ctx.set(corr_id)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Correlation-ID"] = corr_id
        return response
    finally:
        correlation_id_ctx.reset(token)
        # Request metrics by route template (ARCH-10); static files and the SPA are not API calls
        path = request.url.path
        if path.startswith(("/api", "/redfish")):
            REQUEST_METRICS.observe(
                request.method, route_template(request.scope), status, time.perf_counter() - started
            )


# Applies the body size limit to requests sent without a Content-Length (outermost)
from backend.auth import BodySizeLimit  # noqa: E402

app.add_middleware(BodySizeLimit)

# WebDAV streaming reverse proxy
app.include_router(webdav_proxy_router)

# DMTF Redfish Scalable Platforms Management API
import logging

from backend.api.redfish import router as redfish_router

logger = logging.getLogger("ZettNAS")

app.include_router(redfish_router, prefix="/redfish/v1")
app.include_router(redfish_router, prefix="/redfish")

# Register API routers with backwards-compatible /api alias and modern /api/v1 prefix
# /api/v1 is the documented API (tokens, Home Assistant, MCP); /api serves the web UI and is
# not in the OpenAPI document. Token clients on /api get Deprecation/Sunset headers (ARCH-8).
app.include_router(api_router, prefix="/api", include_in_schema=False)
app.include_router(api_router, prefix="/api/v1")

# Response schemas in the OpenAPI document for the routes without a response_model (ARCH-11)
from backend.api_docs import document_responses  # noqa: E402

document_responses(app)


@app.api_route(
    "/api/{unmatched_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
@app.api_route(
    "/api/v1/{unmatched_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
def api_route_not_found(unmatched_path: str):
    raise HTTPException(status_code=404, detail=f"API route '/api/{unmatched_path}' not found.")


@app.get("/")
@app.get("/index.html")
def serve_index(request: Request):
    index_file = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_file):
        raise HTTPException(status_code=404, detail="index.html not found")
    is_lcd = request.query_params.get("mode") == "lcd" or "mode=lcd" in str(request.query_params)
    # Revalidated on every load (no-cache), but an unchanged page is answered with 304 (PERF-5)
    headers = {"Cache-Control": "no-cache", "Vary": "Accept-Encoding"}
    picked = None
    if not is_lcd:
        # The page is the same for everyone: send the copy the build compressed (FE-01).
        from backend.static_files import pick_precompressed

        picked = pick_precompressed(index_file, request.headers.get("accept-encoding", ""))
    st = os.stat(picked[0] if picked else index_file)
    variant = "lcd" if is_lcd else (picked[1] if picked else "identity")
    etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}-{variant}"'
    headers["ETag"] = etag
    if etag in [t.strip() for t in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers=headers)
    if picked:
        with open(picked[0], "rb") as f:
            body = f.read()
        return Response(content=body, media_type="text/html", headers={**headers, "Content-Encoding": picked[1]})
    with open(index_file, encoding="utf-8") as f:
        html_str = f.read()
    if is_lcd:
        html_str = html_str.replace('class="studio-workbench', 'class="studio-workbench lcd-direct')
    return Response(content=html_str, media_type="text/html", headers=headers)


# Mount static assets using native FastAPI StaticFiles for streaming, proper Range headers, and zero RAM caching
if os.path.isdir(STATIC_DIR):
    from backend.static_files import CompressedStaticFiles

    app.mount("/", CompressedStaticFiles(directory=STATIC_DIR, html=True), name="static")


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

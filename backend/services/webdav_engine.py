"""
ZettNAS Toolkit - Universal WebDAV Engine
Manages embedded line-rate rclone WebDAV daemon on Port 8084 with zero-conflict routing.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, Optional

import backend.config as config
from backend.fsutil import atomic_write_json, read_json

logger = logging.getLogger("ZettNAS.WebDAV")


def ensure_fuse_device() -> bool:
    """Ensure /dev/fuse is available in the container for FUSE operations."""
    if os.path.exists("/dev/fuse") and os.access("/dev/fuse", os.R_OK | os.W_OK):
        return True
    if os.path.exists("/host/dev/fuse"):
        try:
            if os.path.exists("/dev/fuse"):
                os.remove("/dev/fuse")
            os.symlink("/host/dev/fuse", "/dev/fuse")
            logger.info("Symlinked /host/dev/fuse to /dev/fuse successfully.")
            return True
        except OSError as e:
            logger.warning(f"Could not symlink /host/dev/fuse to /dev/fuse: {e}")
    return False


class WebdavEngine:
    """Orchestrates the rclone WebDAV server process and lifecycle."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._started_at: Optional[float] = None
        self._last_error: Optional[str] = None
        self.ensure_config_defaults()

    def get_default_config(self) -> Dict[str, Any]:
        root = config.POOL_PATH if os.path.exists(config.POOL_PATH) else "/mnt/user"
        return {
            "enabled": True,
            "port": config.WEBDAV_PORT,
            "root_path": root,
            "read_only": False,
            "username": "admin",
            "password": "",  # If empty, uses toolkit password or defaults to admin
            "auth_enabled": True,
        }

    def ensure_config_defaults(self):
        cfg_file = config.WEBDAV_CONFIG_FILE
        if not os.path.exists(cfg_file):
            cfg = self.get_default_config()
            try:
                os.makedirs(os.path.dirname(cfg_file), exist_ok=True)
                atomic_write_json(cfg_file, cfg)
            except OSError as e:
                logger.warning(f"Failed to initialize webdav config: {e}")

    def load_config(self) -> Dict[str, Any]:
        defaults = self.get_default_config()
        stored = read_json(config.WEBDAV_CONFIG_FILE, {})
        if not isinstance(stored, dict):
            stored = {}
        merged = {**defaults, **stored}
        # Keep port normalized
        try:
            merged["port"] = int(merged.get("port", config.WEBDAV_PORT))
        except (ValueError, TypeError):
            merged["port"] = config.WEBDAV_PORT
        return merged

    def save_config(self, new_cfg: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            current = self.load_config()
            for k in ["enabled", "port", "root_path", "read_only", "username", "password", "auth_enabled"]:
                if k in new_cfg:
                    current[k] = new_cfg[k]
            try:
                os.makedirs(os.path.dirname(config.WEBDAV_CONFIG_FILE), exist_ok=True)
                atomic_write_json(config.WEBDAV_CONFIG_FILE, current)
            except OSError as e:
                logger.error(f"Failed to save webdav config: {e}")
                raise
            return current

    def is_running(self) -> bool:
        if self._proc is not None:
            if self._proc.poll() is None:
                return True
            else:
                self._proc = None
                self._started_at = None
        return False

    def start(self) -> Dict[str, Any]:
        """Starts the rclone serve webdav background process."""
        with self._lock:
            if self.is_running():
                return self.get_status()

            ensure_fuse_device()

            rclone_bin = shutil.which("rclone")
            if not rclone_bin:
                msg = "rclone binary not found in container PATH."
                logger.error(f"[WEBDAV] {msg}")
                self._last_error = msg
                return self.get_status()

            cfg = self.load_config()
            port = int(cfg.get("port", config.WEBDAV_PORT))
            root = str(cfg.get("root_path", config.POOL_PATH))

            if not os.path.exists(root):
                try:
                    os.makedirs(root, exist_ok=True)
                except OSError as e:
                    logger.warning(f"[WEBDAV] Could not create root path {root}: {e}")

            proxy_script = os.path.join(os.path.dirname(__file__), "rclone_auth_proxy.py")
            if cfg.get("auth_enabled", True) and os.path.exists(proxy_script):
                cmd = [
                    rclone_bin,
                    "serve",
                    "webdav",
                    "--addr",
                    f":{port}",
                    "--vfs-cache-mode",
                    "writes",
                    "--dir-cache-time",
                    "10s",
                    "--auth-proxy",
                    proxy_script,
                ]
            else:
                cmd = [
                    rclone_bin,
                    "serve",
                    "webdav",
                    root,
                    "--addr",
                    f":{port}",
                    "--vfs-cache-mode",
                    "writes",
                    "--dir-cache-time",
                    "10s",
                ]
                if cfg.get("auth_enabled", True):
                    username = cfg.get("username", "admin") or "admin"
                    password = cfg.get("password")
                    if not password:
                        password = config.WEB_PASSWORD or "admin"
                    cmd.extend(["--user", username, "--pass", password])

            if cfg.get("read_only"):
                cmd.append("--read-only")

            logger.info(
                f"[WEBDAV] Launching: {' '.join(cmd[:5])} ... (auth={cfg.get('auth_enabled')}, proxy={os.path.exists(proxy_script)})"
            )
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self._started_at = time.time()
                self._last_error = None

                # Wait briefly to detect rapid crash / port conflict
                time.sleep(0.4)
                if self._proc.poll() is not None:
                    _, err = self._proc.communicate(timeout=1.0)
                    self._last_error = err.strip() if err else f"Exited with code {self._proc.returncode}"
                    logger.error(f"[WEBDAV] Failed to start daemon: {self._last_error}")
                    self._proc = None
                    self._started_at = None
                else:
                    logger.info(f"[WEBDAV] Daemon successfully running on port {port} (PID: {self._proc.pid})")
            except Exception as e:
                logger.error(f"[WEBDAV] Exception launching daemon: {e}")
                self._last_error = str(e)
                self._proc = None
                self._started_at = None

            return self.get_status()

    def stop(self) -> Dict[str, Any]:
        """Stops the rclone serve webdav background process."""
        with self._lock:
            if self._proc is not None:
                pid = self._proc.pid
                logger.info(f"[WEBDAV] Stopping daemon (PID: {pid})...")
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    logger.warning(f"[WEBDAV] Daemon PID {pid} didn't exit in 3s; killing with SIGKILL")
                    self._proc.kill()
                    self._proc.wait()
                self._proc = None
                self._started_at = None
            return self.get_status()

    def restart(self) -> Dict[str, Any]:
        self.stop()
        return self.start()

    def start_if_enabled(self):
        cfg = self.load_config()
        if cfg.get("enabled", True):
            self.start()

    def get_status(self) -> Dict[str, Any]:
        cfg = self.load_config()
        running = self.is_running()
        port = int(cfg.get("port", config.WEBDAV_PORT))
        from backend.hardware.network import read_ip

        host_ip = read_ip() or "127.0.0.1"
        username = cfg.get("username", "admin")

        direct_url = f"http://{host_ip}:{port}/"
        proxy_url = "/webdav/"

        return {
            "enabled": bool(cfg.get("enabled", True)),
            "running": running,
            "pid": self._proc.pid if running and self._proc else None,
            "uptime_seconds": round(time.time() - self._started_at, 1) if running and self._started_at else None,
            "port": port,
            "root_path": cfg.get("root_path", config.POOL_PATH),
            "read_only": bool(cfg.get("read_only", False)),
            "username": username,
            "auth_enabled": bool(cfg.get("auth_enabled", True)),
            "direct_url": direct_url,
            "proxy_url": proxy_url,
            "last_error": self._last_error,
            "quick_connect": {
                "macos": f"open 'http://{username}@{host_ip}:{port}/'",
                "windows": f"net use Z: http://{host_ip}:{port}/ /user:{username}",
                "ios": direct_url,
                "linux": f"gio mount dav://{username}@{host_ip}:{port}/",
            },
        }


# Global singleton instance
_webdav_engine: Optional[WebdavEngine] = None


def get_webdav_engine() -> WebdavEngine:
    global _webdav_engine
    if _webdav_engine is None:
        _webdav_engine = WebdavEngine()
    return _webdav_engine

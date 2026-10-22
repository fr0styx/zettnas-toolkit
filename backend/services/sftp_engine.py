"""
ZettNAS Toolkit - SFTP Engine Service
Provides production-grade inbound SFTP (SSH File Transfer Protocol) file sharing.
Operates with strict ChrootDirectory isolation, key/password authentication,
and zero interactive host shell access to protect NAS security.
"""

import json
import logging
import os
import re
import socket
import subprocess
import time
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.config import DATA_DIR, POOL_PATH, docker_sock, logger
from backend.fsutil import atomic_write_json, read_json

SFTP_DIR = os.path.join(DATA_DIR, "sftp")
SFTP_CONFIG_FILE = os.path.join(SFTP_DIR, "config.json")
SFTP_USERS_FILE = os.path.join(SFTP_DIR, "users.json")
SFTP_CONF_FILE = os.path.join(SFTP_DIR, "sshd_config")


class SFTPUser(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    display_name: str = ""
    password: str | None = None
    pubkey: str | None = None
    shares: list[str] = Field(default_factory=list)
    read_only: bool = False
    enabled: bool = True


class SFTPConfig(BaseModel):
    enabled: bool = False
    port: int = Field(2222, ge=1024, le=65535)
    allow_password_auth: bool = True
    allow_pubkey_auth: bool = True
    banner: str = "Welcome to ZettNAS Secure SFTP Storage"
    chroot_enabled: bool = True


class SFTPStatus(BaseModel):
    running: bool
    mode: str  # "native_sidecar", "host_sshd", "subprocess", "disabled", "configured"
    port: int
    port_open: bool
    shares_count: int
    users_count: int
    sidecar_detected: bool = False
    sidecar_status: str = "not_found"
    config_path: str = SFTP_CONFIG_FILE
    quick_connect: str = ""


class SFTPEngine:
    """
    Manages SFTP service configuration, user permissions, chroot environments,
    and sidecar container orchestration.
    """

    DEFAULT_CONFIG = {
        "enabled": False,
        "port": 2222,
        "allow_password_auth": True,
        "allow_pubkey_auth": True,
        "banner": "Welcome to ZettNAS Secure SFTP Storage",
        "chroot_enabled": True,
    }

    def __init__(self):
        os.makedirs(SFTP_DIR, exist_ok=True)
        if not os.path.exists(SFTP_CONFIG_FILE):
            atomic_write_json(SFTP_CONFIG_FILE, self.DEFAULT_CONFIG)
        if not os.path.exists(SFTP_USERS_FILE):
            atomic_write_json(SFTP_USERS_FILE, [])
        self._proc: subprocess.Popen | None = None

    def get_config(self) -> dict[str, Any]:
        cfg = dict(self.DEFAULT_CONFIG)
        saved = read_json(SFTP_CONFIG_FILE, {})
        if isinstance(saved, dict):
            cfg.update(saved)
        return cfg

    def save_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        cfg = self.get_config()
        cfg.update(updates)
        atomic_write_json(SFTP_CONFIG_FILE, cfg)
        self._generate_sshd_config(cfg)
        return cfg

    def _generate_sshd_config(self, cfg: dict[str, Any]) -> str:
        """Generates hardened OpenSSH sshd_config with strict chroot and no shell access."""
        port = cfg.get("port", 2222)
        pw_auth = "yes" if cfg.get("allow_password_auth", True) else "no"
        pk_auth = "yes" if cfg.get("allow_pubkey_auth", True) else "no"

        content = f"""# ZettNAS Secure Inbound SFTP Configuration
Port {port}
Protocol 2
HostKey {os.path.join(SFTP_DIR, "ssh_host_ed25519_key")}
HostKey {os.path.join(SFTP_DIR, "ssh_host_rsa_key")}

# Strict Subsystem isolation
Subsystem sftp internal-sftp

# Authentication
PasswordAuthentication {pw_auth}
PubkeyAuthentication {pk_auth}
ChallengeResponseAuthentication no
UsePAM yes

# Security Hardening
X11Forwarding no
AllowTcpForwarding no
AllowAgentForwarding no
PermitTunnel no
PermitUserEnvironment no

# Chroot Jail: user cannot escape /home/%u and has NO shell access
Match Group sftpusers
    ChrootDirectory /home/%u
    ForceCommand internal-sftp
    AllowTcpForwarding no
    X11Forwarding no
"""
        with open(SFTP_CONF_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        return content

    def _check_port(self, port: int) -> bool:
        """Checks if SFTP port is actively listening locally, on host, or container gateway."""
        candidates = ["127.0.0.1"]
        # Check container default gateway
        try:
            with open("/proc/net/route") as f:
                for line in f:
                    fields = line.strip().split()
                    if len(fields) >= 3 and fields[1] == "00000000":
                        gw_hex = fields[2]
                        gw_ip = socket.inet_ntoa(bytes.fromhex(gw_hex)[::-1])
                        if gw_ip and gw_ip not in candidates:
                            candidates.append(gw_ip)
                        break
        except Exception:
            logger.debug("backend.services.sftp_engine.SFTPEngine._check_port: ignored error", exc_info=True)

        # Check primary host IP
        try:
            from backend.hardware.network import get_network_topology

            primary_ip = get_network_topology().get("summary", {}).get("primary_ip")
            if primary_ip and primary_ip not in candidates:
                candidates.append(primary_ip)
        except Exception:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect(("1.1.1.1", 80))
                    hip = s.getsockname()[0]
                    if hip and hip not in candidates:
                        candidates.append(hip)
            except Exception:
                logger.debug("backend.services.sftp_engine.SFTPEngine._check_port: ignored error", exc_info=True)

        for ip in candidates:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.35)
                    if s.connect_ex((ip, port)) == 0:
                        return True
            except Exception:
                continue
        return False

    def list_users(self, mask_passwords: bool = True) -> list[dict[str, Any]]:
        raw = read_json(SFTP_USERS_FILE, [])
        if not isinstance(raw, list):
            return []
        if not mask_passwords:
            return raw
        masked = []
        for u in raw:
            item = dict(u)
            if item.get("password"):
                item["password"] = "********"
            masked.append(item)
        return masked

    def add_user(self, user_data: dict[str, Any]) -> dict[str, Any]:
        username = re.sub(r"[^a-zA-Z0-9_-]+", "", user_data.get("username", "").strip().lower())
        if len(username) < 2:
            raise ValueError("Username must be at least 2 alphanumeric characters.")

        users = self.list_users(mask_passwords=False)
        if any(u.get("username") == username for u in users):
            raise ValueError(f"SFTP user '{username}' already exists.")

        raw_pw = user_data.get("password")
        stored_pw = None
        if raw_pw:
            if raw_pw.startswith("$argon2"):
                stored_pw = raw_pw
            else:
                from backend.passwords import hash_password

                stored_pw = hash_password(raw_pw)

        user_entry = {
            "username": username,
            "display_name": user_data.get("display_name", username),
            "password": stored_pw,
            "pubkey": user_data.get("pubkey"),
            "shares": user_data.get("shares", []),
            "read_only": bool(user_data.get("read_only", False)),
            "enabled": True,
            "created_at": user_data.get("created_at"),
        }
        users.append(user_entry)
        atomic_write_json(SFTP_USERS_FILE, users)
        return_entry = dict(user_entry)
        if return_entry.get("password"):
            return_entry["password"] = "********"
        return return_entry

    def delete_user(self, username: str) -> bool:
        users = self.list_users()
        filtered = [u for u in users if u.get("username") != username]
        if len(filtered) == len(users):
            return False
        atomic_write_json(SFTP_USERS_FILE, filtered)
        return True

    def _start_sidecar(self, port: int) -> bool:
        """Starts or creates the zettnas-sftp sidecar container with host network mode."""
        sock_path = docker_sock()
        if not os.path.exists(sock_path):
            return False

        try:
            from backend.services.container_mutator import _docker_request

            # 1. Check if container already exists
            code, c_data = _docker_request("GET", "/containers/zettnas-sftp/json")
            if code == 200:
                is_running = bool(c_data.get("State", {}).get("Running", False))
                cmd = c_data.get("Config", {}).get("Cmd", [])
                if is_running and f":{port}" in cmd:
                    logger.info(f"[SFTP] Sidecar zettnas-sftp already running on port {port}")
                    return True

                if not is_running and f":{port}" in cmd:
                    code_st, _ = _docker_request("POST", "/containers/zettnas-sftp/start")
                    if code_st in (204, 200, 304):
                        logger.info(f"[SFTP] Existing sidecar zettnas-sftp started on port {port}")
                        return True

                # Port mismatch or failure: recreate cleanly
                _docker_request("POST", "/containers/zettnas-sftp/stop?t=2")
                _docker_request("DELETE", "/containers/zettnas-sftp?force=true")

            # 2. Inspect parent container for image and host volume bindings
            code_tk, tk_info = _docker_request("GET", "/containers/zettnas-toolkit/json")
            image = "ghcr.io/fr0styx/zettnas-toolkit:latest"
            tk_binds = []
            if code_tk == 200:
                image = tk_info.get("Config", {}).get("Image") or image
                tk_binds = tk_info.get("HostConfig", {}).get("Binds", []) or []

            # 3. Determine host path for data directory
            host_data_dir = None
            for b in tk_binds:
                parts = b.split(":")
                if len(parts) >= 2 and parts[1] == "/app/data":
                    host_data_dir = parts[0]
                    break

            if not host_data_dir:
                if os.path.exists("/mnt/user/appdata/zettnas-toolkit/data"):
                    host_data_dir = "/mnt/user/appdata/zettnas-toolkit/data"
                else:
                    host_data_dir = DATA_DIR

            host_repo = os.path.dirname(host_data_dir) if host_data_dir else None

            # 4. Construct binds for the sidecar
            binds = [f"{host_data_dir}:/app/data:rw"]
            for b in tk_binds:
                if ":/mnt/user" in b or ":/mnt/storage" in b:
                    if b not in binds:
                        binds.append(b)

            if not any(":/mnt/user" in b for b in binds) and os.path.exists("/mnt/user"):
                binds.append("/mnt/user:/mnt/user:rw")
            if not any(":/mnt/storage" in b for b in binds) and os.path.exists("/mnt/storage"):
                binds.append("/mnt/storage:/mnt/storage:rw")

            if host_repo and os.path.exists("/mnt/user/appdata/zettnas-toolkit/backend"):
                binds.append(f"{host_repo}/backend:/app/backend:ro")

            payload = {
                "Image": image,
                "Cmd": [
                    "rclone",
                    "serve",
                    "sftp",
                    "--addr",
                    f":{port}",
                    "--vfs-cache-mode",
                    "writes",
                    "--dir-cache-time",
                    "10s",
                    "--cache-dir",
                    "/app/data/sftp/cache",
                    "--auth-proxy",
                    "/app/backend/services/rclone_auth_proxy.py",
                ],
                "HostConfig": {
                    "NetworkMode": "host",
                    "Binds": binds,
                    "RestartPolicy": {"Name": "unless-stopped"},
                },
                "Labels": {
                    "app": "zettnas-sftp",
                    "managed-by": "zettnas-toolkit",
                },
            }

            code_cr, resp_cr = _docker_request("POST", "/containers/create?name=zettnas-sftp", body=payload)
            if code_cr in (201, 200):
                code_st, resp_st = _docker_request("POST", "/containers/zettnas-sftp/start")
                if code_st in (204, 200, 304):
                    logger.info(f"[SFTP] Sidecar container zettnas-sftp started on host port {port}")
                    return True
                else:
                    logger.error(f"[SFTP] Failed to start sidecar container: {code_st} {resp_st}")
                    return False
            else:
                logger.error(f"[SFTP] Failed to create sidecar container: {code_cr} {resp_cr}")
                return False

        except Exception as e:
            logger.warning(f"[SFTP] Exception in _start_sidecar: {e}")
            return False

    def _start_subprocess(self, port: int) -> bool:
        """Starts local rclone SFTP server process as a fallback."""
        auth_proxy = os.path.abspath(os.path.join(os.path.dirname(__file__), "rclone_auth_proxy.py"))
        cache_dir = os.path.join(SFTP_DIR, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        cmd = [
            "rclone",
            "serve",
            "sftp",
            "--addr",
            f":{port}",
            "--vfs-cache-mode",
            "writes",
            "--dir-cache-time",
            "10s",
            "--cache-dir",
            cache_dir,
            "--auth-proxy",
            auth_proxy,
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info(f"[SFTP] Subprocess started (PID: {self._proc.pid}) on port {port}")
            return True
        except Exception as e:
            logger.warning(f"[SFTP] Subprocess start failed: {e}")
            return False

    def get_status(self) -> SFTPStatus:
        cfg = self.get_config()
        port = cfg.get("port", 2222)
        enabled = cfg.get("enabled", False)
        port_open = self._check_port(port)

        # Check sidecar container status if Docker socket exists
        sidecar_detected = False
        sidecar_status = "not_found"

        sock_path = docker_sock()
        if os.path.exists(sock_path):
            try:
                from backend.services.container_mutator import _docker_request

                code, c_data = _docker_request("GET", "/containers/zettnas-sftp/json")
                if code == 200:
                    sidecar_detected = True
                    sidecar_status = "running" if c_data.get("State", {}).get("Running") else "stopped"
            except Exception:
                logger.debug("backend.services.sftp_engine.SFTPEngine.get_status: ignored error", exc_info=True)

        subprocess_running = bool(hasattr(self, "_proc") and self._proc and self._proc.poll() is None)
        running = enabled and (port_open or sidecar_status == "running" or subprocess_running)

        if not enabled:
            mode = "disabled"
        elif sidecar_status == "running":
            mode = "native_sidecar"
        elif port_open:
            mode = "host_sshd"
        elif subprocess_running:
            mode = "subprocess"
        else:
            mode = "configured"

        # Primary host IP heuristic
        host_ip = "127.0.0.1"
        try:
            from backend.hardware.network import get_network_topology

            host_ip = get_network_topology().get("summary", {}).get("primary_ip") or "127.0.0.1"
        except Exception:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect(("1.1.1.1", 80))
                    host_ip = s.getsockname()[0]
            except Exception:
                logger.debug("backend.services.sftp_engine.SFTPEngine.get_status: ignored error", exc_info=True)

        users = self.list_users()
        sample_user = users[0]["username"] if users else "username"
        quick_connect = f"sftp -P {port} {sample_user}@{host_ip}"

        # Total shares accessible across all SFTP users
        shares_set = set()
        for u in users:
            for s in u.get("shares", []):
                shares_set.add(s)

        return SFTPStatus(
            running=running,
            mode=mode,
            port=port,
            port_open=port_open,
            shares_count=len(shares_set),
            users_count=len(users),
            sidecar_detected=sidecar_detected,
            sidecar_status=sidecar_status,
            config_path=SFTP_CONFIG_FILE,
            quick_connect=quick_connect,
        )

    def start(self) -> SFTPStatus:
        cfg = self.save_config({"enabled": True})
        port = cfg.get("port", 2222)
        logger.info(f"[SFTP] Starting SFTP service on port {port}...")

        # 1. Try Docker sidecar first if Docker socket exists
        started_sidecar = False
        sock_path = docker_sock()
        if os.path.exists(sock_path):
            try:
                started_sidecar = self._start_sidecar(port)
            except Exception as e:
                logger.warning(f"[SFTP] Could not start sidecar container: {e}")

        # 2. Fallback to subprocess if sidecar did not start and port is not listening
        if not started_sidecar and not self._check_port(port):
            try:
                self._start_subprocess(port)
            except Exception as e:
                logger.warning(f"[SFTP] Could not start fallback subprocess: {e}")

        # 3. Wait up to 2.5s for service to listen on port
        for _ in range(12):
            if self._check_port(port):
                break
            time.sleep(0.2)

        return self.get_status()

    def stop(self) -> SFTPStatus:
        self.save_config({"enabled": False})
        logger.info("[SFTP] Stopping SFTP service...")

        # 1. Stop Docker sidecar if Docker socket exists
        sock_path = docker_sock()
        if os.path.exists(sock_path):
            try:
                from backend.services.container_mutator import _docker_request

                code, _ = _docker_request("GET", "/containers/zettnas-sftp/json")
                if code == 200:
                    _docker_request("POST", "/containers/zettnas-sftp/stop?t=2")
            except Exception as e:
                logger.warning(f"[SFTP] Failed to stop sidecar: {e}")

        # 2. Terminate subprocess if active
        if hasattr(self, "_proc") and self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    logger.debug("backend.services.sftp_engine.SFTPEngine.stop: ignored error", exc_info=True)
            self._proc = None

        time.sleep(0.3)
        return self.get_status()

    def restart(self) -> SFTPStatus:
        self.stop()
        return self.start()


_SFTP_ENGINE: SFTPEngine | None = None


def get_sftp_engine() -> SFTPEngine:
    global _SFTP_ENGINE
    if _SFTP_ENGINE is None:
        _SFTP_ENGINE = SFTPEngine()
    return _SFTP_ENGINE

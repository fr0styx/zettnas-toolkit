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
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.config import DATA_DIR, POOL_PATH, logger
from backend.fsutil import atomic_write_json, read_json

SFTP_DIR = os.path.join(DATA_DIR, "sftp")
SFTP_CONFIG_FILE = os.path.join(SFTP_DIR, "config.json")
SFTP_USERS_FILE = os.path.join(SFTP_DIR, "users.json")
SFTP_CONF_FILE = os.path.join(SFTP_DIR, "sshd_config")


class SFTPUser(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    display_name: str = ""
    password: Optional[str] = None
    pubkey: Optional[str] = None
    shares: List[str] = Field(default_factory=list)
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
    mode: str  # "native_sidecar", "host_sshd", "disabled"
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

    def get_config(self) -> Dict[str, Any]:
        cfg = dict(self.DEFAULT_CONFIG)
        saved = read_json(SFTP_CONFIG_FILE, {})
        if isinstance(saved, dict):
            cfg.update(saved)
        return cfg

    def save_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.get_config()
        cfg.update(updates)
        atomic_write_json(SFTP_CONFIG_FILE, cfg)
        self._generate_sshd_config(cfg)
        return cfg

    def _generate_sshd_config(self, cfg: Dict[str, Any]) -> str:
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
        """Checks if SFTP port is actively listening locally or on network interfaces."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    def list_users(self) -> List[Dict[str, Any]]:
        raw = read_json(SFTP_USERS_FILE, [])
        return raw if isinstance(raw, list) else []

    def add_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        username = re.sub(r"[^a-zA-Z0-9_-]+", "", user_data.get("username", "").strip().lower())
        if len(username) < 2:
            raise ValueError("Username must be at least 2 alphanumeric characters.")

        users = self.list_users()
        if any(u.get("username") == username for u in users):
            raise ValueError(f"SFTP user '{username}' already exists.")

        user_entry = {
            "username": username,
            "display_name": user_data.get("display_name", username),
            "password": user_data.get("password"),
            "pubkey": user_data.get("pubkey"),
            "shares": user_data.get("shares", []),
            "read_only": bool(user_data.get("read_only", False)),
            "enabled": True,
            "created_at": user_data.get("created_at"),
        }
        users.append(user_entry)
        atomic_write_json(SFTP_USERS_FILE, users)
        return user_entry

    def delete_user(self, username: str) -> bool:
        users = self.list_users()
        filtered = [u for u in users if u.get("username") != username]
        if len(filtered) == len(users):
            return False
        atomic_write_json(SFTP_USERS_FILE, filtered)
        return True

    def get_status(self) -> SFTPStatus:
        cfg = self.get_config()
        port = cfg.get("port", 2222)
        enabled = cfg.get("enabled", False)
        port_open = self._check_port(port)

        # Check sidecar container status if Docker socket exists
        sidecar_detected = False
        sidecar_status = "not_found"

        sock_path = "/var/run/docker.sock"
        if os.path.exists(sock_path):
            try:
                from backend.services.container_mutator import _docker_request

                code, c_data = _docker_request("GET", "/containers/zettnas-sftp/json")
                if code == 200:
                    sidecar_detected = True
                    sidecar_status = "running" if c_data.get("State", {}).get("Running") else "stopped"
            except Exception:
                pass

        running = enabled and (port_open or sidecar_status == "running")
        mode = (
            "native_sidecar"
            if sidecar_detected
            else ("host_sshd" if port_open else ("disabled" if not enabled else "configured"))
        )

        # Primary host IP heuristic
        host_ip = "127.0.0.1"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("1.1.1.1", 80))
                host_ip = s.getsockname()[0]
        except Exception:
            pass

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
        logger.info(f"[SFTP] Starting SFTP service on port {cfg.get('port', 2222)}...")
        return self.get_status()

    def stop(self) -> SFTPStatus:
        self.save_config({"enabled": False})
        logger.info("[SFTP] Stopping SFTP service...")
        return self.get_status()

    def restart(self) -> SFTPStatus:
        self.stop()
        return self.start()


_SFTP_ENGINE: Optional[SFTPEngine] = None


def get_sftp_engine() -> SFTPEngine:
    global _SFTP_ENGINE
    if _SFTP_ENGINE is None:
        _SFTP_ENGINE = SFTPEngine()
    return _SFTP_ENGINE

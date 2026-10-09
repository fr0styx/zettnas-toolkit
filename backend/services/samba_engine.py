"""
ZettNAS Toolkit - Samba Engine
Manages production-grade Samba (SMB/CIFS) file sharing for Generic Linux & Turnkey Sidecars.
Features Apple vfs_fruit extensions for native macOS Finder & Time Machine support,
10GbE Multi-Channel performance tuning, and cross-platform permissions mapping.
"""

import configparser
import json
import os
import re
import socket
import subprocess
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.config import DATA_DIR, POOL_PATH, logger

SAMBA_DIR = os.path.join(DATA_DIR, "samba")
SAMBA_CONF_FILE = os.path.join(SAMBA_DIR, "smb.conf")
SAMBA_SHARES_FILE = os.path.join(SAMBA_DIR, "shares.json")


class SambaShareConfig(BaseModel):
    name: str
    path: str
    comment: str = ""
    read_only: bool = False
    guest_ok: bool = True
    browseable: bool = True
    timemachine: bool = False
    timemachine_quota_gb: Optional[int] = None
    force_user: str = "root"
    force_group: str = "root"
    valid_users: Optional[str] = None


class SambaStatus(BaseModel):
    running: bool
    mode: str  # "native_sidecar", "host_auditor", "disabled"
    port_445_open: bool
    shares_count: int
    sidecar_detected: bool = False
    sidecar_status: str = "not_found"
    config_path: str = SAMBA_CONF_FILE


class SambaEngine:
    """
    Manages Samba daemon configuration, shares lifecycle, and sidecar integration.
    """

    _DEFAULT_GLOBAL_CONFIG = """[global]
   workgroup = WORKGROUP
   server string = ZettNAS Storage Server
   server role = standalone server
   security = user
   map to guest = Bad User
   dns proxy = no
   usershare allow guests = yes

   # Line-rate 10GbE & Multi-Channel performance tuning
   min protocol = SMB2_10
   server multi channel support = yes
   aio read size = 1
   aio write size = 1
   deadtime = 15

   # Apple macOS Finder & Time Machine enhancements (vfs_fruit)
   vfs objects = catia fruit streams_xattr
   fruit:metadata = netatalk
   fruit:model = MacPro
   fruit:posix_rename = yes
   fruit:veto_appledouble = no
   fruit:wipe_intentionally_left_blank_rfork = yes
   fruit:delete_empty_adfiles = yes
"""

    def __init__(self):
        os.makedirs(SAMBA_DIR, exist_ok=True)
        self._shares: Dict[str, SambaShareConfig] = {}
        self._load_shares()
        self._ensure_default_conf()

    def _ensure_default_conf(self) -> None:
        """Ensures smb.conf exists with initial configuration if missing."""
        if not os.path.isfile(SAMBA_CONF_FILE):
            self.generate_and_save_conf()

    def _load_shares(self) -> None:
        """Loads configured shares from JSON storage."""
        if os.path.isfile(SAMBA_SHARES_FILE):
            try:
                with open(SAMBA_SHARES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            try:
                                share = SambaShareConfig(**item)
                                self._shares[share.name] = share
                            except Exception:
                                pass
            except Exception as e:
                logger.debug(f"[SambaEngine] Failed loading shares JSON: {e}")

        # If no shares exist yet and default pool path exists, configure a default share
        if not self._shares:
            default_path = os.path.join(POOL_PATH, "shares") if POOL_PATH else "/mnt/storage"
            default_share = SambaShareConfig(
                name="storage",
                path=default_path,
                comment="ZettNAS Primary Storage Pool",
                read_only=False,
                guest_ok=True,
                browseable=True,
                timemachine=False,
            )
            self._shares[default_share.name] = default_share
            self._save_shares_json()

    def _save_shares_json(self) -> None:
        """Persists configured shares to JSON."""
        try:
            with open(SAMBA_SHARES_FILE, "w", encoding="utf-8") as f:
                data = [s.model_dump() for s in self._shares.values()]
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"[SambaEngine] Failed writing shares JSON: {e}")

    def list_shares(self) -> List[SambaShareConfig]:
        """Returns all configured Samba shares."""
        return list(self._shares.values())

    def get_share(self, name: str) -> Optional[SambaShareConfig]:
        """Returns share by name."""
        return self._shares.get(name)

    def add_or_update_share(self, share: SambaShareConfig) -> SambaShareConfig:
        """Adds or updates a Samba share and regenerates smb.conf."""
        # Validate name (safe SMB share name)
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", share.name.strip())
        if not clean_name:
            raise ValueError("Share name cannot be empty or invalid")
        share.name = clean_name

        # Ensure directory exists if possible
        try:
            if not os.path.exists(share.path):
                os.makedirs(share.path, exist_ok=True)
        except Exception as e:
            logger.warning(f"[SambaEngine] Could not create share directory {share.path}: {e}")

        self._shares[share.name] = share
        self._save_shares_json()
        self.generate_and_save_conf()
        self.reload_service()
        return share

    def remove_share(self, name: str) -> bool:
        """Removes a share and regenerates smb.conf."""
        if name in self._shares:
            del self._shares[name]
            self._save_shares_json()
            self.generate_and_save_conf()
            self.reload_service()
            return True
        return False

    def generate_and_save_conf(self) -> str:
        """Generates the full smb.conf text and saves it to disk."""
        conf_lines = [self._DEFAULT_GLOBAL_CONFIG.strip(), ""]

        for share in self._shares.values():
            conf_lines.append(f"[{share.name}]")
            conf_lines.append(f"   path = {share.path}")
            if share.comment:
                conf_lines.append(f"   comment = {share.comment}")
            conf_lines.append(f"   browseable = {'yes' if share.browseable else 'no'}")
            conf_lines.append(f"   read only = {'yes' if share.read_only else 'no'}")
            conf_lines.append(f"   guest ok = {'yes' if share.guest_ok else 'no'}")
            conf_lines.append("   create mask = 0775")
            conf_lines.append("   directory mask = 0775")
            conf_lines.append(f"   force user = {share.force_user}")
            conf_lines.append(f"   force group = {share.force_group}")

            if share.valid_users:
                conf_lines.append(f"   valid users = {share.valid_users}")

            if share.timemachine:
                conf_lines.append("   fruit:time machine = yes")
                if share.timemachine_quota_gb and share.timemachine_quota_gb > 0:
                    conf_lines.append(f"   fruit:time machine max size = {share.timemachine_quota_gb}G")

            conf_lines.append("")

        full_conf = "\n".join(conf_lines)
        try:
            with open(SAMBA_CONF_FILE, "w", encoding="utf-8") as f:
                f.write(full_conf)
            logger.info(f"[SambaEngine] Generated and saved smb.conf with {len(self._shares)} shares")
        except Exception as e:
            logger.error(f"[SambaEngine] Failed writing smb.conf: {e}")

        return full_conf

    def get_config_text(self) -> str:
        """Returns the current content of smb.conf."""
        if os.path.isfile(SAMBA_CONF_FILE):
            try:
                with open(SAMBA_CONF_FILE, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
        return self.generate_and_save_conf()

    def check_port_445(self) -> bool:
        """Tests if SMB port 445 is accepting TCP connections."""
        targets = ["127.0.0.1", "localhost", "10.40.30.249"]
        for target in targets:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.4)
                res = s.connect_ex((target, 445))
                s.close()
                if res == 0:
                    return True
            except Exception:
                pass
        return False

    def check_sidecar(self) -> Dict[str, Any]:
        """Inspects Docker for running zettnas-samba sidecar container if docker socket is accessible."""
        docker_sock = "/var/run/docker.sock"
        if not os.path.exists(docker_sock):
            return {"detected": False, "status": "no_docker_socket"}

        try:
            import httpx

            transport = httpx.HTTPTransport(uds=docker_sock)
            with httpx.Client(transport=transport, timeout=1.5) as client:
                r = client.get("http://localhost/containers/json?all=1")
                if r.status_code == 200:
                    containers = r.json()
                    for c in containers:
                        names = [n.lstrip("/") for n in c.get("Names", [])]
                        if "zettnas-samba" in names:
                            return {
                                "detected": True,
                                "id": c.get("Id", "")[:12],
                                "state": c.get("State", "unknown"),
                                "status": c.get("Status", ""),
                            }
        except Exception as e:
            logger.debug(f"[SambaEngine] Docker socket inspection error: {e}")

        return {"detected": False, "status": "not_found"}

    def reload_service(self) -> bool:
        """Attempts to signal smbd or restart the zettnas-samba container if running."""
        # 1. Try smbcontrol if available in container/host
        try:
            res = subprocess.run(["smbcontrol", "all", "reload-config"], capture_output=True, timeout=2)
            if res.returncode == 0:
                logger.info("[SambaEngine] smbcontrol reload-config succeeded")
                return True
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

        # 2. Try docker restart on sidecar container if available
        docker_sock = "/var/run/docker.sock"
        if os.path.exists(docker_sock):
            try:
                import httpx

                transport = httpx.HTTPTransport(uds=docker_sock)
                with httpx.Client(transport=transport, timeout=3.0) as client:
                    r = client.post("http://localhost/containers/zettnas-samba/restart?t=2")
                    if r.status_code in (204, 200):
                        logger.info("[SambaEngine] zettnas-samba sidecar restarted successfully")
                        return True
            except Exception:
                pass

        return False

    def get_status(self) -> SambaStatus:
        """Returns comprehensive status of Samba file sharing service."""
        port_open = self.check_port_445()
        sidecar_info = self.check_sidecar()
        sidecar_detected = sidecar_info.get("detected", False)

        from backend.hardware.pal_storage import StoragePlatformDetector, PlatformType

        platform = StoragePlatformDetector.detect()

        if platform == PlatformType.UNRAID:
            mode = "host_auditor"
            running = port_open
        elif sidecar_detected and sidecar_info.get("state") == "running":
            mode = "native_sidecar"
            running = True
        else:
            mode = "native_sidecar" if platform == PlatformType.GENERIC_LINUX else "host_auditor"
            running = port_open

        return SambaStatus(
            running=running,
            mode=mode,
            port_445_open=port_open,
            shares_count=len(self._shares),
            sidecar_detected=sidecar_detected,
            sidecar_status=sidecar_info.get("status", "not_found"),
            config_path=SAMBA_CONF_FILE,
        )


_SAMBA_ENGINE_INSTANCE: Optional[SambaEngine] = None


def get_samba_engine() -> SambaEngine:
    global _SAMBA_ENGINE_INSTANCE
    if _SAMBA_ENGINE_INSTANCE is None:
        _SAMBA_ENGINE_INSTANCE = SambaEngine()
    return _SAMBA_ENGINE_INSTANCE

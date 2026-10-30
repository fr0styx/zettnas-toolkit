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
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.config import DATA_DIR, POOL_PATH, docker_sock, logger
from backend.config import docker_sock as _docker_sock_path
from backend.fsutil import atomic_write_json, atomic_write_text
from backend.ignored_errors import ignored

SAMBA_DIR = os.path.join(DATA_DIR, "samba")
SAMBA_CONF_FILE = os.path.join(SAMBA_DIR, "smb.conf")
SAMBA_SHARES_FILE = os.path.join(SAMBA_DIR, "shares.json")


def _snapshot_dir_for(share_path: str) -> str | None:
    """The pool's snapshot folder for a share at <pool>/@shares/<name> or <pool>/<name>."""
    import os

    parent = os.path.dirname(share_path.rstrip("/"))
    pool = os.path.dirname(parent) if os.path.basename(parent) == "@shares" else parent
    snapdir = os.path.join(pool, "@snapshots")
    return snapdir if pool else None


class SambaShareConfig(BaseModel):
    name: str
    path: str
    comment: str = ""
    read_only: bool = False
    guest_ok: bool = False  # guests only when asked for (SEC-06)
    browseable: bool = True
    timemachine: bool = False
    timemachine_quota_gb: int | None = None
    quota_gb: int | None = None
    force_user: str = "nobody"
    force_group: str = "users"
    valid_users: str | None = None
    read_list: str | None = None
    write_list: str | None = None
    previous_versions: bool = False  # Windows Previous Versions from scheduled snapshots
    recycle_bin: bool = True  # what is deleted over SMB goes to the share's Recycle Bin (REL-15)


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_PRINCIPAL = re.compile(r"^[@+&]{0,2}[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")
_UNIX_NAME = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$", re.IGNORECASE)
_FORBIDDEN_PREFIXES = (
    "/etc",
    "/root",
    "/app",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/host",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
)


def _allowed_share_roots() -> list[str]:
    from backend import config

    roots = [getattr(config, "POOL_PATH", "") or ""]
    roots += list(getattr(config, "ALLOWED_BROWSE_ROOTS", []) or [])
    return [os.path.realpath(r) for r in roots if r]


def validate_share_path(path: str) -> str:
    """The real path of a share folder, which must be inside the storage roots (SEC-06)."""
    path = (path or "").strip()
    if not os.path.isabs(path) or _CONTROL_CHARS.search(path):
        raise ValueError("Share path must be an absolute path")
    real = os.path.realpath(path)
    roots = _allowed_share_roots()
    inside = any(real == r or real.startswith(r.rstrip("/") + "/") for r in roots)
    system_path = real == "/" or any(real == f or real.startswith(f + "/") for f in _FORBIDDEN_PREFIXES)
    if not inside or system_path:
        raise ValueError(f"Share path must be inside {', '.join(roots) or 'the storage pool'}")
    from backend.fsutil import is_protected

    if is_protected(real):
        raise ValueError("Share path is ZettNAS's own data folder; choose another folder")
    return real


def protected_veto_names(share_path: str) -> list[str]:
    """Names of app folders inside a share, for Samba's veto files (SEC-28): they never show over SMB."""
    from backend.fsutil import protected_dirs

    base = os.path.realpath(share_path or "")
    inside = [d for d in protected_dirs() if base and d != base and d.startswith(base.rstrip("/") + "/")]
    names = []
    for d in inside:
        if any(p != d and d.startswith(p.rstrip("/") + "/") for p in inside):
            continue  # its parent is hidden already (the install folder hides its data folder)
        name = os.path.basename(d)
        if name and name not in names and "/" not in name:
            names.append(name)
    return names


def validate_share(share: "SambaShareConfig") -> None:
    """Rejects settings that would let a share expose system paths or inject smb.conf lines (SEC-06)."""
    for field in ("name", "path", "comment", "force_user", "force_group", "valid_users", "read_list", "write_list"):
        value = getattr(share, field) or ""
        if _CONTROL_CHARS.search(value):
            raise ValueError(f"'{field}' must not contain line breaks or control characters")
    if "[" in share.comment or "]" in share.comment:
        raise ValueError("'comment' must not contain square brackets")

    share.path = validate_share_path(share.path)

    for field in ("valid_users", "read_list", "write_list"):
        value = getattr(share, field)
        if not value:
            continue
        for principal in re.split(r"[,\s]+", value.strip()):
            if principal and not _PRINCIPAL.match(principal):
                raise ValueError(f"'{field}' contains an invalid user or group: {principal!r}")
    for field in ("force_user", "force_group"):
        value = (getattr(share, field) or "").strip()
        if value and not _UNIX_NAME.match(value):
            raise ValueError(f"'{field}' must be a plain user or group name")
    for field in ("quota_gb", "timemachine_quota_gb"):
        value = getattr(share, field)
        if value is not None and not (0 <= int(value) <= 1_000_000):
            raise ValueError(f"'{field}' is out of range")


class SambaStatus(BaseModel):
    running: bool
    mode: str  # "native_sidecar", "host_auditor", "disabled", "host_native"
    port_445_open: bool
    shares_count: int
    sidecar_detected: bool = False
    sidecar_status: str = "not_found"
    config_path: str = Field(default_factory=lambda: SAMBA_CONF_FILE)  # not in the API schema: it depends on the host
    native_samba_active: bool = False


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
        private_dir = os.path.join(SAMBA_DIR, "private")
        try:
            os.makedirs(private_dir, mode=0o700, exist_ok=True)
            os.chmod(private_dir, 0o700)
        except OSError:
            pass
        self._shares: dict[str, SambaShareConfig] = {}
        self._load_shares()
        self.sync_sidecar_policy()
        self._ensure_default_conf()

    def sync_sidecar_policy(self) -> tuple[bool, str]:
        """Ensures disable_sidecar marker exists when host has native Samba active or is a turnkey OS."""
        can_run, reason = self.can_run_sidecar()
        marker_file = os.path.join(SAMBA_DIR, "disable_sidecar")
        if not can_run:
            try:
                with open(marker_file, "w", encoding="utf-8") as f:
                    f.write(f"disabled: {reason}\n")
            except Exception as e:
                logger.debug(f"[SambaEngine] Could not write disable_sidecar marker: {e}")
        else:
            if os.path.isfile(marker_file):
                try:
                    os.remove(marker_file)
                except Exception:
                    ignored("backend.services.samba_engine.SambaEngine.sync_sidecar_policy")
        return can_run, reason

    def can_run_sidecar(self) -> tuple[bool, str]:
        """Pre-flight check to verify if zettnas-samba sidecar can bind port 445."""
        from backend.hardware.pal.base import PlatformType
        from backend.hardware.pal.detect import StoragePlatformDetector

        platform = StoragePlatformDetector.detect()
        if platform in (
            PlatformType.UNRAID,
            PlatformType.TRUENAS,
            PlatformType.PROXMOX,
            PlatformType.FYGOOS,
            PlatformType.ZETTOS,
            PlatformType.UGOS,
            PlatformType.GENERIC_OBSERVER,
        ):
            return False, f"Host is running {platform.value} with native host storage/SMB services."

        sidecar_info = self.check_sidecar()
        is_sidecar_running = sidecar_info.get("detected") and sidecar_info.get("state") == "running"
        if not is_sidecar_running and self.check_port_445():
            return False, "Port 445 is already bound on host by an existing SMB daemon."

        return True, "Ready"

    def _ensure_default_conf(self) -> None:
        """Ensures smb.conf exists with initial configuration if missing."""
        if not os.path.isfile(SAMBA_CONF_FILE):
            self.generate_and_save_conf()

    def _load_shares(self) -> None:
        """Loads configured shares from JSON storage."""
        if os.path.isfile(SAMBA_SHARES_FILE):
            try:
                with open(SAMBA_SHARES_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            try:
                                share = SambaShareConfig(**item)
                                self._shares[share.name] = share
                            except Exception:
                                ignored("backend.services.samba_engine.SambaEngine._load_shares")
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
                guest_ok=False,
                browseable=True,
                timemachine=False,
            )
            self._shares[default_share.name] = default_share
            self._save_shares_json()

    def _save_shares_json(self) -> None:
        """Persists configured shares to JSON."""
        try:
            atomic_write_json(SAMBA_SHARES_FILE, [s.model_dump() for s in self._shares.values()], indent=2)
        except Exception as e:
            logger.error(f"[SambaEngine] Failed writing shares JSON: {e}")

    def list_shares(self) -> list[SambaShareConfig]:
        """Returns all configured Samba shares."""
        return list(self._shares.values())

    def get_share(self, name: str) -> SambaShareConfig | None:
        """Returns share by name."""
        return self._shares.get(name)

    def add_or_update_share(self, share: SambaShareConfig) -> SambaShareConfig:
        """Adds or updates a Samba share and regenerates smb.conf."""
        validate_share(share)
        # Validate name (safe SMB share name)
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", share.name.strip())
        if not clean_name or clean_name.lower() in ("global", "homes", "printers", "ipc$"):
            raise ValueError("Share name cannot be empty, invalid or reserved")
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
        glob = self._DEFAULT_GLOBAL_CONFIG.strip()
        if not any(getattr(s, "guest_ok", False) for s in self._shares.values()):
            # B11 (SEC-22): no guest share, so a wrong password is refused, never mapped to guest
            glob = glob.replace("map to guest = Bad User", "map to guest = Never")
        conf_lines = [glob]
        from backend.services import ip_block
        from backend.services.ransomware_guard import get_guard

        blocked = [b["ip"] for b in ip_block.list_blocks()]
        if blocked:
            conf_lines.append(f"   hosts deny = {' '.join(blocked)}")  # M5
        frozen = get_guard().frozen  # M4: every share read-only while frozen
        conf_lines.append("")

        # Private folders (Batch 6): each signed-in person sees only their own as a share named after them
        try:
            from backend.services.user_spaces import homes_root

            if os.path.isdir(homes_root()):
                conf_lines.extend(
                    [
                        "[homes]",
                        f"   path = {homes_root()}/%S",
                        "   valid users = %S",
                        "   browseable = no",
                        f"   read only = {'yes' if frozen else 'no'}",
                        "   create mask = 0660",
                        "   directory mask = 0770",
                        "",
                    ]
                )
        except Exception:
            logger.debug("[SambaEngine] homes section skipped", exc_info=True)

        for share in self._shares.values():
            try:
                validate_share(share)
            except ValueError as e:
                logger.error(f"[SambaEngine] Skipping share '{share.name}' with unsafe settings: {e}")
                continue
            conf_lines.append(f"[{share.name}]")
            conf_lines.append(f"   path = {share.path}")
            if share.comment:
                conf_lines.append(f"   comment = {share.comment}")
            conf_lines.append(f"   browseable = {'yes' if share.browseable else 'no'}")
            conf_lines.append(f"   read only = {'yes' if share.read_only or frozen else 'no'}")
            conf_lines.append(f"   guest ok = {'yes' if share.guest_ok else 'no'}")
            conf_lines.append("   create mask = 0775")
            conf_lines.append("   directory mask = 0775")
            if share.force_user:
                conf_lines.append(f"   force user = {share.force_user}")
            if share.force_group:
                conf_lines.append(f"   force group = {share.force_group}")

            veto = protected_veto_names(share.path)
            if veto:
                conf_lines.append("   veto files = " + "".join(f"/{n}/" for n in veto))
                conf_lines.append("   delete veto files = no")
            if share.valid_users:
                conf_lines.append(f"   valid users = {share.valid_users}")
            if share.read_list:
                conf_lines.append(f"   read list = {share.read_list}")
            if share.write_list:
                conf_lines.append(f"   write list = {share.write_list}")

            vfs = ["catia", "fruit", "streams_xattr"]
            if share.previous_versions:
                # Windows "Previous Versions" from the scheduled snapshots
                # (<pool>/@snapshots/<share>@auto-YYYYMMDD-HHMM, see snapshot_service)
                snapdir = _snapshot_dir_for(share.path)
                if snapdir:
                    vfs.append("shadow_copy2")
                    conf_lines.append(f"   shadow:snapdir = {snapdir}")
                    conf_lines.append(f"   shadow:basedir = {share.path}")
                    conf_lines.append(f"   shadow:format = {share.name}@auto-%Y%m%d-%H%M")
                    conf_lines.append("   shadow:sort = desc")
                    conf_lines.append("   shadow:localtime = no")  # snapshot names are UTC (NREL-15)

            if share.recycle_bin:
                vfs.append("recycle")
                conf_lines += [
                    "   recycle:repository = .RecycleBin/files",
                    "   recycle:keeptree = no",
                    "   recycle:versions = yes",
                    "   recycle:touch_mtime = yes",
                    "   recycle:directory_mode = 0770",
                    "   recycle:exclude = *.tmp,~$*,.~lock.*",
                    "   recycle:exclude_dir = .RecycleBin",
                ]
            if len(vfs) > 3:
                conf_lines.append("   vfs objects = " + " ".join(vfs))

            if share.timemachine:
                conf_lines.append("   fruit:time machine = yes")
                if share.timemachine_quota_gb and share.timemachine_quota_gb > 0:
                    conf_lines.append(f"   fruit:time machine max size = {share.timemachine_quota_gb}G")
            elif share.quota_gb and share.quota_gb > 0:
                conf_lines.append(f"   # storage quota = {share.quota_gb}G")

            conf_lines.append("")

        full_conf = "\n".join(conf_lines)
        try:
            atomic_write_text(SAMBA_CONF_FILE, full_conf)  # Samba never reads half a file (REL-22)
            logger.info(f"[SambaEngine] Generated and saved smb.conf with {len(self._shares)} shares")
        except Exception as e:
            logger.error(f"[SambaEngine] Failed writing smb.conf: {e}")

        return full_conf

    def get_config_text(self) -> str:
        """Returns the current content of smb.conf."""
        if os.path.isfile(SAMBA_CONF_FILE):
            try:
                with open(SAMBA_CONF_FILE, encoding="utf-8") as f:
                    return f.read()
            except Exception:
                ignored("backend.services.samba_engine.SambaEngine.get_config_text")
        return self.generate_and_save_conf()

    def check_port_445(self) -> bool:
        """Tests if SMB port 445 is accepting TCP connections."""
        targets = ["127.0.0.1", "localhost"]
        try:
            from backend.state import Z_STATE

            host_ip = getattr(Z_STATE, "discovered_host_ip", None) or os.environ.get("HOST_IP")
            if host_ip and host_ip not in targets:
                targets.append(host_ip)
        except Exception:
            ignored("backend.services.samba_engine.SambaEngine.check_port_445")
        for target in targets:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.4)
                res = s.connect_ex((target, 445))
                s.close()
                if res == 0:
                    return True
            except Exception:
                ignored("backend.services.samba_engine.SambaEngine.check_port_445")
        return False

    def check_sidecar(self) -> dict[str, Any]:
        """Inspects Docker for running zettnas-samba sidecar container if docker socket is accessible."""
        docker_sock = _docker_sock_path()
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
        docker_sock = _docker_sock_path()
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
                ignored("backend.services.samba_engine.SambaEngine.reload_service")

        return False

    def sync_samba_user(self, username: str, password: str | None = None, delete: bool = False) -> bool:
        """
        Synchronizes a user into the Samba passdb database.
        When delete=True, removes the user from passdb.
        When password is provided, creates or updates the SMB credentials.
        """
        if not re.fullmatch(r"^[a-zA-Z0-9_\-\.]{1,32}$", username):
            logger.warning(f"[SambaEngine] Rejected invalid username for passdb sync: '{username}'")
            return False

        sidecar_info = self.check_sidecar()
        docker_sock = _docker_sock_path()

        # 1. Try local execution if smbpasswd exists on the system
        try:
            if delete:
                res = subprocess.run(["smbpasswd", "-x", username], capture_output=True, timeout=3)
                if res.returncode == 0:
                    logger.info(f"[SambaEngine] Removed user '{username}' from passdb.")
                    return True
            elif password:
                subprocess.run(["adduser", "-D", "-H", username], capture_output=True, timeout=2)
                p = subprocess.Popen(
                    ["smbpasswd", "-a", "-s", username],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                p.communicate(f"{password}\n{password}\n", timeout=3)
                if p.returncode == 0:
                    logger.info(f"[SambaEngine] Synchronized user '{username}' into passdb.")
                    return True
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

        # 2. Try docker exec into zettnas-samba container
        if sidecar_info.get("detected") and os.path.exists(docker_sock):
            try:
                import httpx

                transport = httpx.HTTPTransport(uds=docker_sock)
                with httpx.Client(transport=transport, timeout=5.0) as client:
                    cid = sidecar_info.get("id", "zettnas-samba")
                    if delete:
                        create_exec = client.post(
                            f"http://localhost/containers/{cid}/exec",
                            json={"Cmd": ["smbpasswd", "-x", username], "AttachStdout": True, "AttachStderr": True},
                        )
                        if create_exec.status_code == 201:
                            exec_id = create_exec.json().get("Id")
                            client.post(f"http://localhost/exec/{exec_id}/start", json={"Detach": False, "Tty": False})
                            logger.info(f"[SambaEngine] Removed user '{username}' from sidecar passdb.")
                            return True
                    elif password:
                        u_exec = client.post(
                            f"http://localhost/containers/{cid}/exec",
                            json={
                                "Cmd": [
                                    "sh",
                                    "-c",
                                    'id -u "$1" >/dev/null 2>&1 || adduser -D -H -u 1000 "$1" 2>/dev/null || adduser -D -H "$1"',  # 1000 once, then the next free id
                                    "--",
                                    username,
                                ],
                                "AttachStdout": True,
                                "AttachStderr": True,
                            },
                        )
                        if u_exec.status_code == 201:
                            client.post(
                                f"http://localhost/exec/{u_exec.json().get('Id')}/start",
                                json={"Detach": False, "Tty": False},
                            )

                        p_exec = client.post(
                            f"http://localhost/containers/{cid}/exec",
                            json={
                                "Cmd": [
                                    "sh",
                                    "-c",
                                    'printf "%s\\n%s\\n" "$SMB_PASS" "$SMB_PASS" | smbpasswd -a -s "$1"',
                                    "--",
                                    username,
                                ],
                                "Env": [f"SMB_PASS={password}"],
                                "AttachStdout": True,
                                "AttachStderr": True,
                            },
                        )
                        if p_exec.status_code == 201:
                            client.post(
                                f"http://localhost/exec/{p_exec.json().get('Id')}/start",
                                json={"Detach": False, "Tty": False},
                            )
                            logger.info(f"[SambaEngine] Synchronized user '{username}' into sidecar passdb.")
                            return True
            except Exception as e:
                logger.debug(f"[SambaEngine] Docker exec passdb sync error: {e}")

        return False

    def get_status(self) -> SambaStatus:
        """Returns comprehensive status of Samba file sharing service."""
        port_open = self.check_port_445()
        sidecar_info = self.check_sidecar()
        sidecar_detected = sidecar_info.get("detected", False)
        is_sidecar_running = sidecar_detected and sidecar_info.get("state") == "running"

        from backend.hardware.pal.base import PlatformType
        from backend.hardware.pal.detect import StoragePlatformDetector

        platform = StoragePlatformDetector.detect()
        is_turnkey = platform in (
            PlatformType.UNRAID,
            PlatformType.TRUENAS,
            PlatformType.PROXMOX,
            PlatformType.FYGOOS,
            PlatformType.ZETTOS,
            PlatformType.UGOS,
            PlatformType.GENERIC_OBSERVER,
        )

        self.sync_sidecar_policy()
        native_samba = is_turnkey or (port_open and not is_sidecar_running)

        if is_turnkey:
            mode = "host_native" if platform == PlatformType.ZETTOS else "host_auditor"
            running = port_open
            sidecar_status = "standby_host_native" if sidecar_detected else sidecar_info.get("status", "not_found")
        elif is_sidecar_running:
            mode = "native_sidecar"
            running = True
            sidecar_status = sidecar_info.get("status", "running")
        else:
            mode = "native_sidecar" if platform == PlatformType.GENERIC_LINUX else "host_auditor"
            running = port_open
            sidecar_status = sidecar_info.get("status", "not_found")

        return SambaStatus(
            running=running,
            mode=mode,
            port_445_open=port_open,
            shares_count=len(self._shares),
            sidecar_detected=sidecar_detected,
            sidecar_status=sidecar_status,
            config_path=SAMBA_CONF_FILE,
            native_samba_active=native_samba,
        )


_SAMBA_ENGINE_INSTANCE: SambaEngine | None = None


def get_samba_engine() -> SambaEngine:
    global _SAMBA_ENGINE_INSTANCE
    if _SAMBA_ENGINE_INSTANCE is None:
        _SAMBA_ENGINE_INSTANCE = SambaEngine()
    return _SAMBA_ENGINE_INSTANCE

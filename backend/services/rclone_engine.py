"""
ZettNAS Toolkit - Rclone Cloud & Remote Storage Engine
Universal userspace cloud integration (S3, B2, Google Drive, OneDrive, SFTP, WebDAV) via FUSE.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import backend.config as config
from backend.services.webdav_engine import ensure_fuse_device

logger = logging.getLogger("ZettNAS.Rclone")

VALID_REMOTE_NAME = re.compile(r"^[a-zA-Z0-9_\-\.]{1,64}$")

SENSITIVE_KEYS = {
    "pass",
    "password",
    "token",
    "secret",
    "secret_access_key",
    "account_key",
    "api_key",
    "private_key",
    "client_secret",
}


def is_sensitive_key(k: str) -> bool:
    kl = k.lower()
    if kl in SENSITIVE_KEYS:
        return True
    if any(kl.endswith(f"_{s}") or kl.startswith(f"{s}_") for s in ["pass", "password", "token", "secret"]):
        return True
    return False


CURATED_PROVIDERS = [
    {
        "type": "s3",
        "name": "Amazon S3 & S3 Compatible",
        "category": "Object Storage",
        "icon": "cloud-lightning",
        "description": "AWS S3, MinIO, Wasabi, Cloudflare R2, Ceph, DigitalOcean Spaces, Backblaze B2 S3 API.",
        "fields": [
            {
                "name": "provider",
                "label": "Provider Type",
                "type": "select",
                "options": ["AWS", "Minio", "Wasabi", "Cloudflare", "Ceph", "Other"],
                "default": "AWS",
                "required": True,
            },
            {"name": "access_key_id", "label": "Access Key ID", "type": "text", "required": True},
            {"name": "secret_access_key", "label": "Secret Access Key", "type": "password", "required": True},
            {"name": "region", "label": "Region", "type": "text", "default": "us-east-1", "required": False},
            {
                "name": "endpoint",
                "label": "Custom Endpoint URL",
                "type": "text",
                "placeholder": "https://s3.us-west-000.backblazeb2.com",
                "required": False,
            },
        ],
    },
    {
        "type": "b2",
        "name": "Backblaze B2 (Native)",
        "category": "Object Storage",
        "icon": "hard-drive",
        "description": "Direct native Backblaze B2 Cloud Storage API with low overhead.",
        "fields": [
            {"name": "account", "label": "Application Key ID / Account", "type": "text", "required": True},
            {"name": "key", "label": "Application Key", "type": "password", "required": True},
        ],
    },
    {
        "type": "drive",
        "name": "Google Drive",
        "category": "Cloud Drives",
        "icon": "triangle",
        "description": "Mount or sync personal and Google Workspace / Shared Team Drives.",
        "fields": [
            {"name": "client_id", "label": "OAuth Client ID (Optional)", "type": "text", "required": False},
            {"name": "client_secret", "label": "OAuth Client Secret (Optional)", "type": "password", "required": False},
            {
                "name": "scope",
                "label": "Access Scope",
                "type": "select",
                "options": ["drive", "drive.readonly", "drive.file"],
                "default": "drive",
                "required": False,
            },
        ],
    },
    {
        "type": "onedrive",
        "name": "Microsoft OneDrive & SharePoint",
        "category": "Cloud Drives",
        "icon": "cloud",
        "description": "Personal OneDrive, OneDrive for Business, and SharePoint Document Libraries.",
        "fields": [
            {"name": "client_id", "label": "OAuth Client ID (Optional)", "type": "text", "required": False},
            {"name": "client_secret", "label": "OAuth Client Secret (Optional)", "type": "password", "required": False},
            {
                "name": "drive_type",
                "label": "Drive Type",
                "type": "select",
                "options": ["personal", "business", "documentLibrary"],
                "default": "personal",
                "required": False,
            },
        ],
    },
    {
        "type": "sftp",
        "name": "SFTP / SSH Server",
        "category": "Remote Server",
        "icon": "server",
        "description": "Secure file transfer over SSH from offsite servers or backup targets.",
        "fields": [
            {"name": "host", "label": "Host / IP Address", "type": "text", "required": True},
            {"name": "user", "label": "Username", "type": "text", "required": True},
            {"name": "port", "label": "Port", "type": "number", "default": 22, "required": False},
            {"name": "pass", "label": "Password", "type": "password", "required": False},
            {"name": "key_file", "label": "Private Key Path", "type": "text", "required": False},
        ],
    },
    {
        "type": "webdav",
        "name": "Remote WebDAV Server",
        "category": "Network Share",
        "icon": "folder-network",
        "description": "Connect to external Nextcloud, ownCloud, Synology, or remote WebDAV shares.",
        "fields": [
            {
                "name": "url",
                "label": "WebDAV URL",
                "type": "text",
                "placeholder": "https://nextcloud.example.com/remote.php/webdav/",
                "required": True,
            },
            {"name": "user", "label": "Username", "type": "text", "required": False},
            {"name": "pass", "label": "Password / App Token", "type": "password", "required": False},
            {
                "name": "vendor",
                "label": "Vendor",
                "type": "select",
                "options": ["nextcloud", "owncloud", "synology", "other"],
                "default": "other",
                "required": False,
            },
        ],
    },
    {
        "type": "smb",
        "name": "Remote SMB / CIFS Share",
        "category": "Network Share",
        "icon": "share-2",
        "description": "Mount network shares from Windows machines or other NAS appliances.",
        "fields": [
            {"name": "host", "label": "Server Host / IP", "type": "text", "required": True},
            {"name": "user", "label": "Username", "type": "text", "required": False},
            {"name": "pass", "label": "Password", "type": "password", "required": False},
            {"name": "domain", "label": "Domain (Optional)", "type": "text", "required": False},
        ],
    },
    {
        "type": "dropbox",
        "name": "Dropbox",
        "category": "Cloud Drives",
        "icon": "box",
        "description": "Mount or sync personal and business Dropbox accounts.",
        "fields": [
            {"name": "client_id", "label": "App Key (Optional)", "type": "text", "required": False},
            {"name": "client_secret", "label": "App Secret (Optional)", "type": "password", "required": False},
        ],
    },
]


class RcloneEngine:
    """Manages cloud remotes, FUSE mounting, and synchronization jobs."""

    def __init__(self):
        self._lock = threading.Lock()
        self.config_file = config.RCLONE_CONFIG_FILE
        self.cache_dir = config.RCLONE_CACHE_DIR
        self.remotes_dir = config.REMOTES_PATH
        self._active_mounts: Dict[str, Dict[str, Any]] = {}
        self._sync_jobs: Dict[str, Dict[str, Any]] = {}

        self._ensure_directories()

    def _ensure_directories(self):
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            os.makedirs(self.cache_dir, exist_ok=True)
            os.makedirs(self.remotes_dir, exist_ok=True)
        except OSError as e:
            logger.warning(f"[RCLONE] Failed creating directories: {e}")

    def _get_rclone_bin(self) -> str:
        rclone_bin = shutil.which("rclone")
        if not rclone_bin:
            raise RuntimeError("rclone binary not found in system PATH.")
        return rclone_bin

    def get_providers(self) -> List[Dict[str, Any]]:
        """Returns list of curated and supported cloud providers."""
        return CURATED_PROVIDERS

    def list_remotes(self) -> List[Dict[str, Any]]:
        """Dumps configured remotes from rclone.conf and scrubs secrets."""
        with self._lock:
            self._ensure_directories()
            if not os.path.exists(self.config_file):
                return []

            rclone_bin = self._get_rclone_bin()
            try:
                proc = subprocess.run(
                    [rclone_bin, "config", "dump", "--config", self.config_file],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                if proc.returncode != 0:
                    logger.warning(f"[RCLONE] config dump error: {proc.stderr.strip()}")
                    return []
                data = json.loads(proc.stdout) if proc.stdout.strip() else {}
            except Exception as e:
                logger.error(f"[RCLONE] Failed to parse config dump: {e}")
                return []

            remotes = []
            for name, cfg in sorted(data.items()):
                clean_params = {}
                for k, v in cfg.items():
                    if is_sensitive_key(k):
                        clean_params[k] = "********"
                    else:
                        clean_params[k] = v

                mount_path = os.path.join(self.remotes_dir, name)
                is_mounted = self._check_is_mounted(name, mount_path)

                mount_info = self._active_mounts.get(name, {})
                remotes.append(
                    {
                        "name": name,
                        "type": cfg.get("type", "unknown"),
                        "is_mounted": is_mounted,
                        "mount_path": mount_path,
                        "pid": mount_info.get("pid"),
                        "uptime_seconds": (
                            round(time.time() - mount_info["started_at"], 1)
                            if mount_info.get("started_at") and is_mounted
                            else None
                        ),
                        "parameters": clean_params,
                    }
                )
            return remotes

    def _check_is_mounted(self, name: str, mount_path: str) -> bool:
        """Determines if a remote path is currently mounted via FUSE."""
        if not os.path.exists(mount_path):
            return False
        # 1. Check in /proc/mounts
        try:
            if os.path.exists("/proc/mounts"):
                with open("/proc/mounts", "r") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == mount_path:
                            return True
        except OSError:
            pass

        # 2. Check tracked subprocess
        tracked = self._active_mounts.get(name)
        if tracked and tracked.get("proc"):
            if tracked["proc"].poll() is None:
                return True
            else:
                del self._active_mounts[name]

        return os.path.ismount(mount_path)

    def create_remote(self, name: str, remote_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Creates or updates a remote in rclone.conf."""
        if not VALID_REMOTE_NAME.fullmatch(name):
            raise ValueError(f"Invalid remote name: '{name}'. Must be 1-64 alphanumeric chars, dash, or underscore.")

        rclone_bin = self._get_rclone_bin()
        self._ensure_directories()

        cmd = [
            rclone_bin,
            "config",
            "create",
            name,
            remote_type,
            "--config",
            self.config_file,
            "--non-interactive",
        ]

        for k, v in parameters.items():
            if v is not None and v != "":
                cmd.append(f"{k}={v}")

        logger.info(f"[RCLONE] Creating remote '{name}' (type={remote_type})...")
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        if proc.returncode != 0:
            err = proc.stderr.strip() or "Unknown error creating remote"
            logger.error(f"[RCLONE] config create failed: {err}")
            raise RuntimeError(f"Failed to create remote: {err}")

        return {"status": "ok", "name": name, "type": remote_type}

    def delete_remote(self, name: str) -> Dict[str, Any]:
        """Unmounts and removes a remote from rclone.conf."""
        if self._check_is_mounted(name, os.path.join(self.remotes_dir, name)):
            try:
                self.unmount_remote(name)
            except Exception as e:
                logger.warning(f"[RCLONE] Error unmounting {name} prior to deletion: {e}")

        rclone_bin = self._get_rclone_bin()
        cmd = [rclone_bin, "config", "delete", name, "--config", self.config_file]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        if proc.returncode != 0:
            err = proc.stderr.strip()
            raise RuntimeError(f"Failed to delete remote: {err}")

        return {"status": "ok", "deleted": name}

    def mount_remote(
        self,
        name: str,
        remote_path: str = "",
        vfs_cache: str = "writes",
        read_only: bool = False,
    ) -> Dict[str, Any]:
        """Mounts remote storage into /mnt/remotes/{name} via FUSE."""
        with self._lock:
            ensure_fuse_device()
            mount_path = os.path.join(self.remotes_dir, name)
            if self._check_is_mounted(name, mount_path):
                return {"status": "already_mounted", "path": mount_path}

            os.makedirs(mount_path, exist_ok=True)
            rclone_bin = self._get_rclone_bin()

            target_spec = f"{name}:{remote_path}" if remote_path else f"{name}:"
            cmd = [
                rclone_bin,
                "mount",
                target_spec,
                mount_path,
                "--config",
                self.config_file,
                "--vfs-cache-mode",
                vfs_cache,
                "--cache-dir",
                self.cache_dir,
                "--allow-other",
                "--dir-cache-time",
                "30s",
                "--poll-interval",
                "1m",
            ]
            if read_only:
                cmd.append("--read-only")

            logger.info(f"[RCLONE] Mounting {target_spec} -> {mount_path} (cache={vfs_cache})...")
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                time.sleep(1.0)
                if proc.poll() is not None:
                    _, err = proc.communicate(timeout=1.0)
                    raise RuntimeError(
                        f"Mount exited immediately: {err.strip() if err else 'code ' + str(proc.returncode)}"
                    )

                self._active_mounts[name] = {
                    "proc": proc,
                    "pid": proc.pid,
                    "started_at": time.time(),
                    "mount_path": mount_path,
                }
                logger.info(f"[RCLONE] Remote '{name}' successfully mounted (PID: {proc.pid})")
                return {"status": "mounted", "name": name, "path": mount_path, "pid": proc.pid}
            except Exception as e:
                logger.error(f"[RCLONE] Mount failure for {name}: {e}")
                # Try to cleanup empty dir
                try:
                    os.rmdir(mount_path)
                except OSError:
                    pass
                raise

    def unmount_remote(self, name: str) -> Dict[str, Any]:
        """Unmounts /mnt/remotes/{name} and cleans up mount directory."""
        with self._lock:
            mount_path = os.path.join(self.remotes_dir, name)
            logger.info(f"[RCLONE] Unmounting remote '{name}' at {mount_path}...")

            # 1. Try fusermount3 / fusermount
            fuser = shutil.which("fusermount3") or shutil.which("fusermount")
            unmounted = False
            if fuser and os.path.exists(mount_path):
                res = subprocess.run([fuser, "-u", mount_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode == 0:
                    unmounted = True

            # 2. Try generic umount
            if not unmounted and os.path.exists(mount_path):
                res = subprocess.run(["umount", "-l", mount_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode == 0:
                    unmounted = True

            # 3. Terminate background process if tracked
            tracked = self._active_mounts.pop(name, None)
            if tracked and tracked.get("proc"):
                proc = tracked["proc"]
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()

            # Clean up empty dir if not mounted anymore
            if not self._check_is_mounted(name, mount_path):
                try:
                    os.rmdir(mount_path)
                except OSError:
                    pass
                return {"status": "unmounted", "name": name}
            else:
                raise RuntimeError(f"Could not unmount {mount_path}; resource may be busy.")

    def list_remote_files(self, name: str, path: str = "") -> List[Dict[str, Any]]:
        """Lists files and folders inside a remote using rclone lsf --json."""
        rclone_bin = self._get_rclone_bin()
        target = f"{name}:{path}" if path else f"{name}:"
        cmd = [
            rclone_bin,
            "lsf",
            target,
            "--config",
            self.config_file,
            "--json",
            "--max-depth",
            "1",
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        if proc.returncode != 0:
            err = proc.stderr.strip()
            raise RuntimeError(f"Failed to list remote files: {err}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []

    def start_sync_job(
        self,
        src: str,
        dst: str,
        action: str = "sync",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Launches a background sync/copy/move operation between local and remote."""
        if action not in ["sync", "copy", "move"]:
            raise ValueError(f"Invalid sync action: '{action}'. Choose from sync, copy, or move.")

        job_id = str(uuid.uuid4())[:8]
        job = {
            "id": job_id,
            "src": src,
            "dst": dst,
            "action": action,
            "dry_run": dry_run,
            "status": "running",
            "started_at": time.time(),
            "completed_at": None,
            "bytes_transferred": 0,
            "error": None,
        }
        self._sync_jobs[job_id] = job

        def _run_sync():
            try:
                rclone_bin = self._get_rclone_bin()
                cmd = [
                    rclone_bin,
                    action,
                    src,
                    dst,
                    "--config",
                    self.config_file,
                    "--stats",
                    "2s",
                    "--stats-one-line",
                ]
                if dry_run:
                    cmd.append("--dry-run")

                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                job["completed_at"] = time.time()
                if proc.returncode == 0:
                    job["status"] = "success"
                else:
                    job["status"] = "error"
                    job["error"] = proc.stderr.strip() or f"Exited with code {proc.returncode}"
            except Exception as e:
                job["completed_at"] = time.time()
                job["status"] = "error"
                job["error"] = str(e)

        t = threading.Thread(target=_run_sync, daemon=True, name=f"RcloneSync-{job_id}")
        t.start()
        return job

    def get_sync_jobs(self) -> List[Dict[str, Any]]:
        """Returns list of tracked synchronization jobs."""
        return list(self._sync_jobs.values())


# Singleton instance
_rclone_engine: Optional[RcloneEngine] = None


def get_rclone_engine() -> RcloneEngine:
    global _rclone_engine
    if _rclone_engine is None:
        _rclone_engine = RcloneEngine()
    return _rclone_engine

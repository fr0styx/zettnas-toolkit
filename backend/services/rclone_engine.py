"""
ZettNAS Toolkit - Rclone Cloud & Remote Storage Engine
Universal userspace cloud integration (S3, B2, Google Drive, OneDrive, SFTP, WebDAV) via FUSE.
"""

import configparser
import errno
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Optional

import backend.config as config
from backend.services.webdav_engine import ensure_fuse_device

logger = logging.getLogger("ZettNAS.Rclone")

# The first character is never a dot: a remote is mounted at <remotes>/<name>, and "." or ".." would be
# the remotes folder itself (unmounting every cloud mount) or the folder above it.
VALID_REMOTE_NAME = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_\-\.]{0,63}$")
MASKED = "********"  # what list_remotes shows instead of a secret


def check_remote_name(name: str) -> str:
    if not VALID_REMOTE_NAME.fullmatch(str(name or "")):
        raise ValueError(f"Invalid remote name: '{name}'.")
    return name


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
    "key",
    "application_key",
    "app_key",
}


def is_sensitive_key(k: str) -> bool:
    kl = k.lower()
    if kl in SENSITIVE_KEYS:
        return True
    return bool(any(kl.endswith(f"_{s}") or kl.startswith(f"{s}_") for s in ["pass", "password", "token", "secret"]))


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
        "authorize_cmd": 'rclone authorize "drive"',
        "fields": [
            {
                "name": "token",
                "label": "OAuth2 Token (JSON)",
                "type": "textarea",
                "placeholder": 'Paste the JSON token block from: rclone authorize "drive"\ne.g. {"access_token":"...","token_type":"Bearer","refresh_token":"...","expiry":"..."}',
                "required": True,
                "help": 'Run `rclone authorize "drive"` on a machine with a browser, authorize Google Drive, and paste the generated JSON token block here.',
            },
            {
                "name": "scope",
                "label": "Access Scope",
                "type": "select",
                "options": ["drive", "drive.readonly", "drive.file"],
                "default": "drive",
                "required": False,
            },
            {
                "name": "root_folder_id",
                "label": "Root Folder ID or Shared Drive ID (Optional)",
                "type": "text",
                "placeholder": "Leave empty for root of My Drive",
                "required": False,
            },
            {"name": "client_id", "label": "Custom OAuth Client ID (Optional)", "type": "text", "required": False},
            {
                "name": "client_secret",
                "label": "Custom OAuth Client Secret (Optional)",
                "type": "password",
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
        "authorize_cmd": 'rclone authorize "onedrive"',
        "fields": [
            {
                "name": "token",
                "label": "OAuth2 Token (JSON)",
                "type": "textarea",
                "placeholder": 'Paste the JSON token block from: rclone authorize "onedrive"\ne.g. {"access_token":"...","token_type":"Bearer","refresh_token":"...","expiry":"..."}',
                "required": True,
                "help": 'Run `rclone authorize "onedrive"` on a machine with a browser, sign in to Microsoft, and paste the generated JSON token block here.',
            },
            {
                "name": "drive_type",
                "label": "Drive Type",
                "type": "select",
                "options": ["personal", "business", "documentLibrary"],
                "default": "personal",
                "required": False,
            },
            {
                "name": "drive_id",
                "label": "Drive ID / SharePoint Library ID (Optional)",
                "type": "text",
                "placeholder": "Leave empty for default personal drive, or specify for SharePoint / Business",
                "required": False,
            },
            {"name": "client_id", "label": "Custom Azure Client ID (Optional)", "type": "text", "required": False},
            {
                "name": "client_secret",
                "label": "Custom Azure Client Secret (Optional)",
                "type": "password",
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
        "authorize_cmd": 'rclone authorize "dropbox"',
        "fields": [
            {
                "name": "token",
                "label": "OAuth2 Token (JSON)",
                "type": "textarea",
                "placeholder": 'Paste the JSON token block from: rclone authorize "dropbox"\ne.g. {"access_token":"...","token_type":"bearer","refresh_token":"...","expiry":"..."}',
                "required": True,
                "help": 'Run `rclone authorize "dropbox"` on a machine with a browser, authorize Dropbox, and paste the generated JSON token block here.',
            },
            {"name": "client_id", "label": "Custom App Key (Optional)", "type": "text", "required": False},
            {"name": "client_secret", "label": "Custom App Secret (Optional)", "type": "password", "required": False},
        ],
    },
    {
        "type": "box",
        "name": "Box.com",
        "category": "Cloud Drives",
        "icon": "package",
        "description": "Enterprise cloud storage, personal Box vaults, and team collaboration folders.",
        "authorize_cmd": 'rclone authorize "box"',
        "fields": [
            {
                "name": "token",
                "label": "OAuth2 Token (JSON)",
                "type": "textarea",
                "placeholder": 'Paste the JSON token block from: rclone authorize "box"\\ne.g. {"access_token":"...","token_type":"bearer","refresh_token":"...","expiry":"..."}',
                "required": True,
                "help": 'Run `rclone authorize "box"` on a machine with a browser, authorize Box, and paste the generated JSON token block here.',
            },
            {
                "name": "box_sub_type",
                "label": "Box Account Type",
                "type": "select",
                "options": ["user", "enterprise"],
                "default": "user",
            },
            {"name": "client_id", "label": "Custom Client ID (Optional)", "type": "text", "required": False},
            {
                "name": "client_secret",
                "label": "Custom Client Secret (Optional)",
                "type": "password",
                "required": False,
            },
        ],
    },
    {
        "type": "crypt",
        "name": "Encrypted Remote (rclone crypt)",
        "category": "Encryption & Security",
        "icon": "shield-check",
        "description": "Client-side encrypted overlay remote. Encrypts file contents and directory names before sending to any remote or storage path.",
        "fields": [
            {
                "name": "remote",
                "label": "Base Remote Path",
                "type": "text",
                "placeholder": "my-remote:path or /mnt/user/backups/crypt",
                "required": True,
            },
            {"name": "password", "label": "Encryption Password", "type": "password", "required": True},
            {
                "name": "password2",
                "label": "Salt / Secondary Password (Optional)",
                "type": "password",
                "required": False,
            },
            {
                "name": "filename_encryption",
                "label": "Filename Encryption",
                "type": "select",
                "options": ["standard", "obfuscate", "off"],
                "default": "standard",
                "required": False,
            },
            {
                "name": "directory_name_encryption",
                "label": "Directory Name Encryption",
                "type": "select",
                "options": ["true", "false"],
                "default": "true",
                "required": False,
            },
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
        self._active_mounts: dict[str, dict[str, Any]] = {}
        self._sync_jobs: dict[str, dict[str, Any]] = {}

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

    def get_providers(self) -> list[dict[str, Any]]:
        """Returns list of curated and supported cloud providers."""
        return CURATED_PROVIDERS

    def list_remotes(self) -> list[dict[str, Any]]:
        """Dumps configured remotes from rclone.conf and scrubs secrets."""
        with self._lock:
            self._ensure_directories()
            if not os.path.exists(self.config_file):
                return []

            rclone_bin = self._get_rclone_bin()
            try:
                proc = subprocess.run(
                    [rclone_bin, "config", "dump", "--config", self.config_file],
                    capture_output=True,
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
        try:
            os.stat(mount_path)
        except OSError as err:
            if err.errno in (errno.ENOTCONN, errno.ECONNABORTED, errno.EIO, errno.EPIPE):
                return False
            return False

        # 1. Check in /proc/mounts
        try:
            if os.path.exists("/proc/mounts"):
                with open("/proc/mounts") as f:
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

    def _obscure_password(self, password: str) -> str:
        """rclone's obscured form of a password, passed on stdin: on a command line it would be
        visible to anyone who can list the host's processes."""
        if not password:
            return ""
        try:
            proc = subprocess.run(
                [self._get_rclone_bin(), "obscure", "-"],
                input=password,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
            logger.warning("[RCLONE] rclone obscure failed: %s", proc.stderr.strip()[:200])
        except Exception as e:
            logger.warning(f"[RCLONE] Failed obscuring password: {e}")
        raise ValueError("The password could not be stored.")

    def _resolve_onedrive_metadata(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Auto-queries Microsoft Graph API to resolve drive_id and drive_type if missing."""
        token_val = parameters.get("token")
        if not token_val:
            return parameters

        access_token = None
        try:
            if isinstance(token_val, str):
                tok_obj = json.loads(token_val.strip())
            elif isinstance(token_val, dict):
                tok_obj = token_val
            else:
                tok_obj = {}
            access_token = tok_obj.get("access_token")
        except Exception as e:
            logger.debug(f"[OneDrive] Parsing token JSON failed: {e}")

        if not access_token:
            return parameters

        # 1. Try /v1.0/me/drive
        try:
            req = urllib.request.Request(
                "https://graph.microsoft.com/v1.0/me/drive",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    drive_id = data.get("id")
                    drive_type = data.get("driveType", "personal")
                    if drive_id:
                        parameters["drive_id"] = drive_id
                        parameters["drive_type"] = drive_type
                        logger.info(f"[OneDrive] Auto-resolved drive_id={drive_id} (drive_type={drive_type})")
                        return parameters
        except Exception as e:
            logger.warning(f"[OneDrive] Query /v1.0/me/drive failed: {e}")

        # 2. Try /v1.0/me/drives (for multiple or business drives)
        try:
            req = urllib.request.Request(
                "https://graph.microsoft.com/v1.0/me/drives",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    drives = data.get("value", [])
                    if drives and isinstance(drives, list):
                        first_drive = drives[0]
                        drive_id = first_drive.get("id")
                        drive_type = first_drive.get("driveType", "personal")
                        if drive_id:
                            parameters["drive_id"] = drive_id
                            parameters["drive_type"] = drive_type
                            logger.info(f"[OneDrive] Auto-resolved drive_id={drive_id} from /me/drives")
                            return parameters
        except Exception as e:
            logger.warning(f"[OneDrive] Query /v1.0/me/drives failed: {e}")

        if not parameters.get("drive_type"):
            parameters["drive_type"] = "personal"

        return parameters

    def create_remote(self, name: str, remote_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Creates or updates a remote in rclone.conf via RawConfigParser."""
        if not VALID_REMOTE_NAME.fullmatch(name):
            raise ValueError(
                f"Invalid remote name: '{name}'. 1-64 letters, digits, dots, dashes or underscores, not starting with a dot."
            )

        parameters = dict(parameters)
        if remote_type == "onedrive" and not parameters.get("drive_id") and parameters.get("token"):
            parameters = self._resolve_onedrive_metadata(parameters)

        with self._lock:
            self._ensure_directories()
            cfg = configparser.RawConfigParser()
            if os.path.exists(self.config_file):
                try:
                    cfg.read(self.config_file)
                except Exception as e:
                    logger.warning(f"[RCLONE] Reading existing rclone.conf failed: {e}")

            if not cfg.has_section(name):
                cfg.add_section(name)

            cfg.set(name, "type", remote_type)

            for k, v in parameters.items():
                if v is None or v == "":
                    continue
                if str(v) == MASKED:
                    continue  # the masked value from list_remotes: keep what is stored
                # If password field, obscure it (unless it is the stored, already obscured value)
                if k.lower() in ("pass", "password", "password2"):
                    if cfg.has_option(name, k) and cfg.get(name, k) == str(v):
                        continue
                    v = self._obscure_password(str(v))
                elif k == "token" and isinstance(v, str):
                    v_str = v.strip()
                    try:
                        token_obj = json.loads(v_str)
                        v = json.dumps(token_obj)
                    except Exception:
                        v = v_str
                cfg.set(name, k, str(v))

            # Atomic write
            tmp_conf = f"{self.config_file}.tmp.{uuid.uuid4().hex[:8]}"
            with open(tmp_conf, "w") as f:
                cfg.write(f)
            os.replace(tmp_conf, self.config_file)

            logger.info(f"[RCLONE] Successfully saved remote '{name}' (type={remote_type}) to config.")
            return {"status": "ok", "name": name, "type": remote_type}

    def create_crypt_remote(
        self,
        name: str,
        base_remote_path: str,
        password: str,
        password2: str | None = None,
        filename_encryption: str = "standard",
        directory_name_encryption: bool = True,
    ) -> dict[str, Any]:
        """
        Creates or updates an rclone crypt overlay remote wrapping a base remote or directory path.
        All data written to this remote is encrypted on the client side with AES-XTS before transmission.
        """
        params = {
            "remote": base_remote_path,
            "password": password,
            "filename_encryption": filename_encryption,
            "directory_name_encryption": "true" if directory_name_encryption else "false",
        }
        if password2:
            params["password2"] = password2
        return self.create_remote(name, "crypt", params)

    def delete_remote(self, name: str) -> dict[str, Any]:
        """Unmounts and removes a remote from rclone.conf."""
        check_remote_name(name)
        if self._check_is_mounted(name, os.path.join(self.remotes_dir, name)):
            try:
                self.unmount_remote(name)
            except Exception as e:
                logger.warning(f"[RCLONE] Error unmounting {name} prior to deletion: {e}")

        with self._lock:
            self._ensure_directories()
            if os.path.exists(self.config_file):
                cfg = configparser.RawConfigParser()
                try:
                    cfg.read(self.config_file)
                    if cfg.has_section(name):
                        cfg.remove_section(name)
                        tmp_conf = f"{self.config_file}.tmp.{uuid.uuid4().hex[:8]}"
                        with open(tmp_conf, "w") as f:
                            cfg.write(f)
                        os.replace(tmp_conf, self.config_file)
                except Exception as e:
                    logger.error(f"[RCLONE] Error removing remote from config: {e}")

            return {"status": "ok", "deleted": name}

    def test_remote(self, name: str) -> dict[str, Any]:
        """Tests connectivity and credentials of an existing remote in rclone.conf."""
        check_remote_name(name)
        with self._lock:
            self._ensure_directories()
            rclone_bin = self._get_rclone_bin()
            target_spec = f"{name}:"
            cmd = [
                rclone_bin,
                "lsf",
                target_spec,
                "--config",
                self.config_file,
                "--max-depth",
                "1",
                "--contimeout",
                "6s",
                "--timeout",
                "10s",
                "--retries",
                "1",
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
                if proc.returncode == 0:
                    items = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
                    return {
                        "status": "connected",
                        "name": name,
                        "success": True,
                        "item_count": len(items),
                        "items_sample": items[:5],
                    }
                else:
                    err = proc.stderr.strip() or f"Failed with exit code {proc.returncode}"
                    return {
                        "status": "error",
                        "name": name,
                        "success": False,
                        "error": err,
                    }
            except subprocess.TimeoutExpired:
                return {
                    "status": "timeout",
                    "name": name,
                    "success": False,
                    "error": "Connection timed out after 12s. Please verify network or credentials.",
                }
            except Exception as e:
                return {
                    "status": "error",
                    "name": name,
                    "success": False,
                    "error": str(e),
                }

    def test_remote_config(self, remote_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Tests connectivity and credentials of candidate remote configuration before saving."""
        parameters = dict(parameters)
        if remote_type == "onedrive" and not parameters.get("drive_id") and parameters.get("token"):
            parameters = self._resolve_onedrive_metadata(parameters)

        rclone_bin = self._get_rclone_bin()
        test_sec = "_zett_test_temp"
        cfg = configparser.RawConfigParser()
        cfg.add_section(test_sec)
        cfg.set(test_sec, "type", remote_type)

        for k, v in parameters.items():
            if v is None or v == "":
                continue
            if k.lower() in ("pass", "password"):
                v = self._obscure_password(str(v))
            elif k == "token" and isinstance(v, str):
                v_str = v.strip()
                try:
                    token_obj = json.loads(v_str)
                    v = json.dumps(token_obj)
                except Exception:
                    v = v_str
            cfg.set(test_sec, k, str(v))

        tmp_conf = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
                cfg.write(f)
                tmp_conf = f.name

            cmd = [
                rclone_bin,
                "lsf",
                f"{test_sec}:",
                "--config",
                tmp_conf,
                "--max-depth",
                "1",
                "--contimeout",
                "6s",
                "--timeout",
                "10s",
                "--retries",
                "1",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
            if proc.returncode == 0:
                items = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
                return {
                    "status": "connected",
                    "success": True,
                    "type": remote_type,
                    "item_count": len(items),
                    "items_sample": items[:5],
                    "drive_id": parameters.get("drive_id"),
                    "drive_type": parameters.get("drive_type"),
                }
            else:
                err = proc.stderr.strip() or f"Failed with exit code {proc.returncode}"
                return {
                    "status": "error",
                    "success": False,
                    "type": remote_type,
                    "error": err,
                }
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "success": False,
                "type": remote_type,
                "error": "Connection timed out after 12s. Check endpoint, host, or credentials.",
            }
        except Exception as e:
            return {
                "status": "error",
                "success": False,
                "type": remote_type,
                "error": str(e),
            }
        finally:
            if tmp_conf and os.path.exists(tmp_conf):
                try:
                    os.unlink(tmp_conf)
                except OSError:
                    pass

    def mount_remote(
        self,
        name: str,
        remote_path: str = "",
        vfs_cache: str = "writes",
        read_only: bool = False,
    ) -> dict[str, Any]:
        """Mounts remote storage into /mnt/remotes/{name} via FUSE."""
        check_remote_name(name)
        with self._lock:
            ensure_fuse_device()
            mount_path = os.path.join(self.remotes_dir, name)

            # 1. Recover from stale hung FUSE mount if endpoint is disconnected
            try:
                os.stat(mount_path)
            except OSError as err:
                if err.errno in (errno.ENOTCONN, errno.ECONNABORTED, errno.EIO, errno.EPIPE):
                    logger.warning(f"[RCLONE] Detected hung mount at {mount_path} ({err}); lazy unmounting...")
                    subprocess.run(["umount", "-l", mount_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(0.3)

            if self._check_is_mounted(name, mount_path):
                return {"status": "already_mounted", "path": mount_path}

            os.makedirs(mount_path, exist_ok=True)
            rclone_bin = self._get_rclone_bin()

            target_spec = f"{name}:{remote_path}" if remote_path else f"{name}:"
            log_file = os.path.join(self.cache_dir, f"rclone_mount_{name}.log")
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
                "--log-file",
                log_file,
                "--log-level",
                "NOTICE",
            ]
            if read_only:
                cmd.append("--read-only")

            logger.info(f"[RCLONE] Mounting {target_spec} -> {mount_path} (cache={vfs_cache})...")
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(1.0)
                if proc.poll() is not None:
                    err_msg = ""
                    if os.path.exists(log_file):
                        try:
                            with open(log_file) as lf:
                                lines = lf.readlines()
                                err_msg = "".join(lines[-15:]).strip()
                        except Exception:
                            logger.debug(
                                "backend.services.rclone_engine.RcloneEngine.mount_remote: ignored error", exc_info=True
                            )
                    raise RuntimeError(
                        f"Mount exited immediately: {err_msg if err_msg else 'code ' + str(proc.returncode)}"
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

    def unmount_remote(self, name: str) -> dict[str, Any]:
        """Unmounts /mnt/remotes/{name} and cleans up mount directory."""
        check_remote_name(name)
        with self._lock:
            mount_path = os.path.join(self.remotes_dir, name)
            logger.info(f"[RCLONE] Unmounting remote '{name}' at {mount_path}...")

            # 1. Try fusermount3 / fusermount
            fuser = shutil.which("fusermount3") or shutil.which("fusermount")
            unmounted = False
            if fuser and os.path.exists(mount_path):
                res = subprocess.run([fuser, "-u", mount_path], capture_output=True)
                if res.returncode == 0:
                    unmounted = True

            # 2. Try generic umount
            if not unmounted and os.path.exists(mount_path):
                res = subprocess.run(["umount", "-l", mount_path], capture_output=True)
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

    def list_remote_files(self, name: str, path: str = "") -> list[dict[str, Any]]:
        """Lists files and folders inside a remote using rclone lsf --json."""
        check_remote_name(name)
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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            err = proc.stderr.strip()
            raise RuntimeError(f"Failed to list remote files: {err}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []

    def _run_rclone(self, args: list[str], timeout: int = 300) -> str:
        cmd = [self._get_rclone_bin(), *args[:1], "--config", self.config_file, *args[1:]]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr.strip().splitlines() or [f"rclone exited {proc.returncode}"])[-1][:300])
        return proc.stdout

    def list_dirs(self, location: str) -> list[str]:
        """The folder names directly inside `location` ("remote:path"); [] when it doesn't exist."""
        try:
            out = self._run_rclone(["lsf", "--dirs-only", "--", location], timeout=120)
        except RuntimeError as err:
            if "not found" in str(err).lower() or "doesn't exist" in str(err).lower():
                return []
            raise
        return [line.rstrip("/") for line in out.splitlines() if line.strip()]

    def purge(self, location: str) -> None:
        """Deletes `location` ("remote:path") and everything in it."""
        self._run_rclone(["purge", "--", location], timeout=3600)

    _REMOTE_SPEC_RE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_. -]{0,63}):(.*)", re.S)

    def checked_location(self, spec: str, confine_local: bool = True) -> str:
        """A sync source or destination: a configured remote ("name:path") or a local path.

        Options and rclone's on-the-fly or connection-string remotes are refused, and
        local paths must be inside the storage pool unless confine_local is False.
        """
        spec = (spec or "").strip()
        if not spec or spec.startswith(("-", ":")) or re.search(r"[\x00-\x1f]", spec):
            raise ValueError("Invalid sync location.")
        m = self._REMOTE_SPEC_RE.fullmatch(spec)
        if m and not spec.startswith("/"):
            cfg = configparser.RawConfigParser(strict=False)
            try:
                cfg.read(self.config_file)
            except configparser.Error as e:
                raise ValueError("The rclone config could not be read.") from e
            if not cfg.has_section(m.group(1)):
                raise ValueError(f"Unknown remote '{m.group(1)}'.")
            return spec
        if not spec.startswith("/"):
            raise ValueError("Local sync paths must be absolute.")
        if not confine_local:
            return spec
        from backend.fsutil import resolve_within

        real = resolve_within(spec, config.ALLOWED_BROWSE_ROOTS)
        if not real:
            raise ValueError("Local sync paths must be inside the storage pool.")
        return real

    def start_sync_job(
        self,
        src: str,
        dst: str,
        action: str = "sync",
        dry_run: bool = False,
        ignore_errors: bool = False,
        retries: int = 3,
        verbose: bool = False,
        notify: bool = True,
        extra_flags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Launches a background sync/copy/move operation between local and remote with real-time stats streaming.

        `extra_flags` are fixed rclone options from our own code (e.g. --max-delete), never user text."""
        if action not in ["sync", "copy", "move"]:
            raise ValueError(f"Invalid sync action: '{action}'. Choose from sync, copy, or move.")

        job_id = str(uuid.uuid4())[:8]
        job: dict[str, Any] = {
            "id": job_id,
            "src": src,
            "dst": dst,
            "action": action,
            "dry_run": dry_run,
            "ignore_errors": ignore_errors,
            "retries": retries,
            "verbose": verbose,
            "notify": notify,
            "status": "running",
            "started_at": time.time(),
            "completed_at": None,
            "bytes_transferred": 0,
            "total_bytes": 0,
            "percent": 0.0,
            "speed_mbps": 0.0,
            "eta_seconds": None,
            "error": None,
            "successful_files": [],
            "failed_files": [],
            "transfer_log": [],
        }
        self._sync_jobs[job_id] = job

        def _run_sync():
            try:
                rclone_bin = self._get_rclone_bin()
                cmd = [
                    rclone_bin,
                    action,
                    "--config",
                    self.config_file,
                    "--use-json-log",
                    "--stats",
                    "1s",
                    "--stats-log-level",
                    "NOTICE",
                    "--retries",
                    str(max(1, int(retries))),
                ]
                if ignore_errors:
                    cmd.append("--ignore-errors")
                if verbose:
                    cmd.append("-v")
                if dry_run:
                    cmd.append("--dry-run")
                cmd += [str(f) for f in (extra_flags or [])]
                cmd += ["--", src, dst]  # locations are never read as options

                logger.info(f"[RCLONE] Starting async sync job {job_id}: {' '.join(cmd)}")
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                if proc.stdout:
                    for raw_line in iter(proc.stdout.readline, ""):
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            # 1. Parse stats payload
                            stats = data.get("stats")
                            if isinstance(stats, dict):
                                b = stats.get("bytes", 0)
                                tb = stats.get("totalBytes", 0)
                                job["bytes_transferred"] = b
                                job["total_bytes"] = tb
                                if tb > 0:
                                    job["percent"] = round((b / tb) * 100.0, 1)
                                elif b > 0 and tb == 0:
                                    job["percent"] = 100.0

                                spd = stats.get("speed", 0.0)
                                job["speed_mbps"] = round(spd / (1024 * 1024), 2)
                                job["eta_seconds"] = stats.get("eta")

                            # 2. Parse file log items
                            msg = data.get("msg", "")
                            obj = data.get("object") or data.get("source")
                            level = data.get("level", "info")

                            log_entry = {
                                "time": round(time.time(), 2),
                                "level": level,
                                "message": msg,
                                "object": obj,
                            }
                            if len(job["transfer_log"]) < 200:
                                job["transfer_log"].append(log_entry)
                            else:
                                job["transfer_log"] = job["transfer_log"][-199:] + [log_entry]

                            if level == "error" or "failed" in msg.lower():
                                if obj and obj not in [f.get("file") for f in job["failed_files"]]:
                                    job["failed_files"].append(
                                        {"file": obj, "error": msg, "time": round(time.time(), 2)}
                                    )
                            elif "copied" in msg.lower() or (obj and "done" in msg.lower()):
                                if obj and obj not in [f.get("file") for f in job["successful_files"]]:
                                    job["successful_files"].append({"file": obj, "time": round(time.time(), 2)})

                        except json.JSONDecodeError:
                            if len(job["transfer_log"]) < 200:
                                job["transfer_log"].append(
                                    {"time": round(time.time(), 2), "level": "info", "message": line}
                                )

                    proc.stdout.close()
                proc.wait()

                job["completed_at"] = time.time()
                if proc.returncode == 0:
                    job["status"] = "success"
                    job["percent"] = 100.0
                    job["eta_seconds"] = 0
                else:
                    job["status"] = "error"
                    if job["failed_files"]:
                        job["error"] = f"{len(job['failed_files'])} file(s) failed during transfer."
                    else:
                        job["error"] = f"Rclone exited with code {proc.returncode}"
            except Exception as e:
                job["completed_at"] = time.time()
                job["status"] = "error"
                job["error"] = str(e)

            # Notification dispatch
            if job.get("notify", True):
                try:
                    from backend.services.notifications import send_notification

                    if job["status"] == "success":
                        mb = round(job.get("bytes_transferred", 0) / (1024 * 1024), 2)
                        send_notification(
                            {
                                "type": "sync",
                                "title": f"Cloud Sync Completed: {action.capitalize()}",
                                "message": f"Operation '{action}' from {src} to {dst} finished successfully ({mb} MB transferred).",
                                "level": "info",
                                "meta": {"job_id": job_id, "src": src, "dst": dst},
                            }
                        )
                    else:
                        send_notification(
                            {
                                "type": "sync",
                                "title": f"Cloud Sync Failed: {action.capitalize()}",
                                "message": f"Sync from {src} to {dst} failed: {job.get('error')}",
                                "level": "error",
                                "meta": {"job_id": job_id, "src": src, "dst": dst, "error": job.get("error")},
                            }
                        )
                except Exception as notify_err:
                    logger.debug(f"[RCLONE] Notification error: {notify_err}")

        t = threading.Thread(target=_run_sync, daemon=True, name=f"RcloneSync-{job_id}")
        t.start()
        return job

    def get_sync_job(self, job_id: str) -> dict[str, Any] | None:
        """Returns specific tracked synchronization job by ID."""
        return self._sync_jobs.get(job_id)

    def get_sync_jobs(self) -> list[dict[str, Any]]:
        """Returns list of tracked synchronization jobs."""
        return list(self._sync_jobs.values())


# Singleton instance
_rclone_engine: RcloneEngine | None = None


def get_rclone_engine() -> RcloneEngine:
    global _rclone_engine
    if _rclone_engine is None:
        _rclone_engine = RcloneEngine()
    return _rclone_engine


def create_crypt_remote(
    name: str,
    base_remote_path: str,
    password: str,
    password2: str | None = None,
    filename_encryption: str = "standard",
    directory_name_encryption: bool = True,
) -> dict[str, Any]:
    return get_rclone_engine().create_crypt_remote(
        name,
        base_remote_path,
        password,
        password2=password2,
        filename_encryption=filename_encryption,
        directory_name_encryption=directory_name_encryption,
    )

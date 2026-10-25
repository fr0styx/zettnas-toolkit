"""
ZettNAS Toolkit - NFS Engine
Manages production-grade Network File System (NFSv3 / NFSv4) exports for Generic Linux.
Supports granular root squash control (no_root_squash, root_squash, all_squash),
custom anonuid / anongid mapping for Kubernetes PersistentVolumeClaims (PostgreSQL / MySQL pods),
and atomic exports configuration reloading.
"""

import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json

NFS_DIR = os.path.join(DATA_DIR, "nfs")
NFS_EXPORTS_FILE = os.path.join(NFS_DIR, "exports.json")
SYSTEM_EXPORTS_D_DIR = "/etc/exports.d"
SYSTEM_EXPORTS_FILE = "/etc/exports"
ZETTNAS_EXPORTS_D_FILE = os.path.join(SYSTEM_EXPORTS_D_DIR, "zettnas.exports")


_NFS_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_NFS_UNSAFE = re.compile(r'[\x00-\x1f\x7f"]')
_NFS_CLIENT_RE = re.compile(r"[A-Za-z0-9.*?:/\[\]_-]{1,255}")


class NfsExportRule(BaseModel):
    name: str = Field(..., description="Unique identifier or share name")
    path: str = Field(..., description="Filesystem directory path to export")
    clients: str = Field(default="*", description="Allowed client hosts, subnets (CIDR), or wildcard (*)")
    permission: str = Field(default="rw", description="'rw' (read-write) or 'ro' (read-only)")
    squash: str = Field(
        default="no_root_squash",
        description="Root squash policy: 'no_root_squash', 'root_squash', or 'all_squash'",
    )
    anonuid: int = Field(default=1000, description="Anonymous UID for squashed credentials (K8s/DB pod mapping)")
    anongid: int = Field(default=1000, description="Anonymous GID for squashed credentials (K8s/DB pod mapping)")
    sync_mode: str = Field(default="sync", description="'sync' (safe ACID persistence) or 'async' (maximum throughput)")
    no_subtree_check: bool = Field(
        default=True, description="Disable subtree checking for improved reliability and speed"
    )
    insecure: bool = Field(
        default=True, description="Permit NFS clients connecting on unprivileged ports > 1024 (macOS / K8s)"
    )
    fsid: int | None = Field(default=None, description="Optional unique numeric filesystem identifier for NFSv4")
    comment: str = Field(default="", description="Human-readable description")
    created_at: float = Field(default_factory=time.time)

    # Every field ends up in exports(5) syntax, where a line break starts a new export.
    @field_validator("path")
    @classmethod
    def _plain_path(cls, v: str) -> str:
        if not v.startswith("/") or _NFS_UNSAFE.search(v):
            raise ValueError("NFS export path must be an absolute path without quotes or control characters")
        return v

    @field_validator("clients")
    @classmethod
    def _one_client(cls, v: str) -> str:
        v = (v or "").strip() or "*"
        if not _NFS_CLIENT_RE.fullmatch(v):
            raise ValueError("NFS clients must be one host, subnet (CIDR) or '*'")
        return v

    @field_validator("permission")
    @classmethod
    def _permission(cls, v: str) -> str:
        if v not in ("rw", "ro"):
            raise ValueError("NFS permission must be rw or ro")
        return v

    @field_validator("squash")
    @classmethod
    def _squash(cls, v: str) -> str:
        if v not in ("no_root_squash", "root_squash", "all_squash"):
            raise ValueError("NFS squash must be no_root_squash, root_squash or all_squash")
        return v

    @field_validator("sync_mode")
    @classmethod
    def _sync_mode(cls, v: str) -> str:
        if v not in ("sync", "async"):
            raise ValueError("NFS sync mode must be sync or async")
        return v

    @field_validator("comment")
    @classmethod
    def _one_line_comment(cls, v: str) -> str:
        return " ".join(_NFS_CTRL.sub(" ", v or "").split())


class NfsStatus(BaseModel):
    running: bool
    port_2049_open: bool
    exports_count: int
    exports_file: str
    kernel_nfs_supported: bool


class NfsEngine:
    """
    Manages NFS kernel server export lifecycle, /etc/exports.d persistence,
    and granular UID/GID security configurations for containerized and clustered workloads.
    """

    def __init__(self, exports_d_path: str | None = None):
        os.makedirs(NFS_DIR, exist_ok=True)
        self._exports_d_file = exports_d_path or ZETTNAS_EXPORTS_D_FILE
        self._exports: dict[str, NfsExportRule] = {}
        self._load_exports()

    def _load_exports(self) -> None:
        """Loads configured exports from JSON persistent storage."""
        if os.path.isfile(NFS_EXPORTS_FILE):
            try:
                with open(NFS_EXPORTS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            try:
                                rule = NfsExportRule(**item)
                                self._exports[rule.name] = rule
                            except Exception as ex:
                                logger.warning(f"[NFS] Skipping invalid export item: {ex}")
            except Exception as e:
                logger.error(f"[NFS] Failed reading {NFS_EXPORTS_FILE}: {e}")

    def _save_exports(self) -> None:
        """Persists configured exports to JSON storage."""
        try:
            atomic_write_json(NFS_EXPORTS_FILE, [rule.model_dump() for rule in self._exports.values()], indent=2)
        except Exception as e:
            logger.error(f"[NFS] Failed writing {NFS_EXPORTS_FILE}: {e}")

    def list_exports(self) -> list[NfsExportRule]:
        """Returns all configured NFS export rules."""
        return list(self._exports.values())

    def get_export(self, name: str) -> NfsExportRule | None:
        """Retrieves a single export rule by name."""
        return self._exports.get(name)

    def add_or_update_export(self, rule: NfsExportRule) -> None:
        """Adds or updates an export rule and applies changes to host exportfs."""
        self._exports[rule.name] = rule
        self._save_exports()
        self.apply_exports()

    def remove_export(self, name: str) -> bool:
        """Removes an export rule by name and reloads exportfs."""
        if name in self._exports:
            del self._exports[name]
            self._save_exports()
            self.apply_exports()
            return True
        return False

    def generate_export_options(self, rule: NfsExportRule) -> str:
        """
        Builds the options string for /etc/exports entry according to RFC & Linux NFS kernel semantics.
        e.g. rw,sync,no_root_squash,anonuid=1000,anongid=1000,no_subtree_check,insecure
        """
        from backend.services.ransomware_guard import writes_frozen

        opts = ["ro" if writes_frozen() else rule.permission]  # read-only while frozen (SEC-6)

        if rule.sync_mode == "async":
            opts.append("async")
        else:
            opts.append("sync")

        # Squash policy
        if rule.squash == "no_root_squash":
            opts.append("no_root_squash")
        elif rule.squash == "all_squash":
            opts.append("all_squash")
        else:
            opts.append("root_squash")

        # Anonymous UID/GID mapping (critical for K8s PVCs & root squashing)
        opts.append(f"anonuid={rule.anonuid}")
        opts.append(f"anongid={rule.anongid}")

        if rule.no_subtree_check:
            opts.append("no_subtree_check")
        else:
            opts.append("subtree_check")

        if rule.insecure:
            opts.append("insecure")

        if rule.fsid is not None:
            opts.append(f"fsid={rule.fsid}")

        return ",".join(opts)

    def generate_export_line(self, rule: NfsExportRule) -> str:
        """
        Generates a standard exports(5) line:
        "/path/on/disk" client(opts)
        """
        opts = self.generate_export_options(rule)
        clients = rule.clients.strip() or "*"
        return f'"{rule.path}" {clients}({opts})'

    def generate_exports_file_content(self) -> str:
        """Generates full /etc/exports.d/zettnas.exports content."""
        lines = [
            "# ==============================================================================",
            "# ZettNAS Toolkit - Auto-Generated NFS Export Rules",
            "# DO NOT EDIT DIRECTLY - Managed via ZettNAS PAL Storage Subsystem",
            f"# Last Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
            "# ==============================================================================",
            "",
        ]

        for rule in self._exports.values():
            if rule.comment:
                lines.append(f"# {rule.comment}")
            lines.append(self.generate_export_line(rule))
            lines.append("")

        return "\n".join(lines)

    def apply_exports(self) -> bool:
        """
        Writes export rules to /etc/exports.d/zettnas.exports (or /etc/exports) and runs exportfs -ra.
        Gracefully handles environments without root write access or missing exportfs.
        """
        content = self.generate_exports_file_content()
        written = False

        # 1. Try writing to /etc/exports.d/zettnas.exports
        try:
            d = os.path.dirname(self._exports_d_file)
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(self._exports_d_file, "w", encoding="utf-8") as f:
                f.write(content)
            written = True
        except Exception as e:
            logger.debug(f"[NFS] Could not write to {self._exports_d_file}: {e}")

        # 2. Fallback to /etc/exports if /etc/exports.d is unsupported
        if not written:
            try:
                with open(SYSTEM_EXPORTS_FILE, "a+", encoding="utf-8") as f:
                    # Append or write if writable
                    f.write(f"\n# ZettNAS NFS\n{content}\n")
                written = True
            except Exception as e:
                logger.debug(f"[NFS] Could not write to {SYSTEM_EXPORTS_FILE}: {e}")

        # 3. Always write a copy to DATA_DIR/nfs/exports.generated for auditing
        try:
            audit_file = os.path.join(NFS_DIR, "exports.generated")
            with open(audit_file, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            logger.debug("backend.services.nfs_engine.NfsEngine.apply_exports: ignored error", exc_info=True)

        # 4. Invoke exportfs -ra or service reload
        try:
            res = subprocess.run(["exportfs", "-ra"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                logger.info("[NFS] exportfs -ra succeeded.")
                return True
            logger.debug(f"[NFS] exportfs returned {res.returncode}: {res.stderr.strip()}")
        except (FileNotFoundError, subprocess.SubprocessError) as ex:
            logger.debug(f"[NFS] exportfs execution skipped or unavailable: {ex}")

        return written

    def get_status(self) -> NfsStatus:
        """Audits current host NFS server status and port 2049 availability."""
        import socket

        port_open = False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex(("127.0.0.1", 2049))
            port_open = result == 0
            sock.close()
        except Exception:
            logger.debug("backend.services.nfs_engine.NfsEngine.get_status: ignored error", exc_info=True)

        kernel_supported = os.path.exists("/proc/fs/nfsd") or os.path.exists("/proc/net/rpc/nfsd")

        return NfsStatus(
            running=port_open or len(self._exports) > 0,
            port_2049_open=port_open,
            exports_count=len(self._exports),
            exports_file=self._exports_d_file,
            kernel_nfs_supported=kernel_supported,
        )


_NFS_ENGINE_INSTANCE: NfsEngine | None = None


def get_nfs_engine() -> NfsEngine:
    """Singleton factory for NfsEngine."""
    global _NFS_ENGINE_INSTANCE
    if _NFS_ENGINE_INSTANCE is None:
        _NFS_ENGINE_INSTANCE = NfsEngine()
    return _NFS_ENGINE_INSTANCE

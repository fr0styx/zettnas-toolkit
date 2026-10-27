"""
Ransomware guard (M4).

Watches file changes made through ZettNAS (file manager, uploads, WebDAV) and,
optionally, guard files placed in each share. It reacts when it sees:

- many renames or deletes in a short time from one user or address
  (default 150 in 60 s);
- files renamed to known ransomware extensions, or ransom notes being written
  (default 10 in 60 s);
- a guard file changed or deleted (any protocol, including SMB and NFS).

Then it, in order:
1. freezes writes: the file manager, uploads and WebDAV refuse changes, ZettNAS's
   own Samba shares become read-only, and the SFTP service stops;
2. snapshots every pool where ZettNAS manages snapshots (Btrfs, ZFS on generic
   Linux; on Unraid, snapshots stay Unraid's job and the alert says so);
3. blocks the address the changes came from for 24 hours (M5);
4. raises a critical alert through every notification channel.

An admin lifts the freeze under Security once the source is cleaned up.
"""

import io
import json
import os
import re
import threading
import time
import zipfile
from collections import deque
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json

STATE_FILE = os.path.join(DATA_DIR, "ransomware_guard.json")
CANARY_NAME = "!ZettNAS-guard-file.docx"
RANSOM_EXTENSIONS = {
    ".encrypted",
    ".enc",
    ".locked",
    ".lock",
    ".crypt",
    ".crypted",
    ".cry",
    ".crypz",
    ".cryp1",
    ".wncry",
    ".wnry",
    ".wcry",
    ".locky",
    ".zepto",
    ".odin",
    ".cerber",
    ".cerber3",
    ".zzzzz",
    ".micro",
    ".vvv",
    ".ecc",
    ".ezz",
    ".exx",
    ".xyz",
    ".aaa",
    ".abc",
    ".ccc",
    ".ttt",
    ".kraken",
    ".darkness",
    ".nochance",
    ".lockbit",
    ".conti",
    ".ryk",
    ".ryuk",
    ".hive",
    ".blackcat",
    ".akira",
    ".royal",
    ".basta",
    ".clop",
    ".phobos",
    ".djvu",
    ".stop",
    ".dharma",
    ".makop",
    ".medusa",
    ".rhysida",
    ".play",
    ".8base",
}
RANSOM_NOTE_RE = re.compile(
    r"(readme|read_me|how[_ -]?to|restore|recover|decrypt|help)[^/]*(files?|data|decrypt|instructions|restore|recover)[^/]*\.(txt|html?|hta|url)$"
    r"|^(_?readme_?|!!!.*|.*ransom.*|.*decrypt.*instructions.*)\.(txt|html?|hta)$",
    re.I,
)
WRITE_KINDS = {"rename", "delete", "write"}
WINDOW_S = 60


def _default_state() -> dict[str, Any]:
    return {
        "enabled": True,
        "canaries": False,
        "rename_delete_limit": 150,
        "suspicious_limit": 10,
        "frozen": False,
        "frozen_at": None,
        "reason": "",
        "source": {},
        "canary_files": {},
        "snapshots": [],
    }


class RansomwareGuard:
    def __init__(self, state_file: str = STATE_FILE, react=None):
        self.state_file = state_file
        self._lock = threading.Lock()
        self._events: dict[str, deque] = {}
        self._suspicious: dict[str, deque] = {}
        self._react = react or self._lockdown
        self.state = self._load()

    # --- state ---------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        st = _default_state()
        try:
            with open(self.state_file, encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                st.update(saved)
        except (OSError, ValueError):
            logger.debug("ransomware_guard: no saved state yet", exc_info=True)
        return st

    def _save(self) -> None:
        try:
            atomic_write_json(self.state_file, self.state, indent=1)
        except OSError:
            logger.warning("[RansomwareGuard] Could not save state", exc_info=True)

    def update_settings(self, **changes: Any) -> dict[str, Any]:
        with self._lock:
            for k in ("enabled", "canaries"):
                if changes.get(k) is not None:
                    self.state[k] = bool(changes[k])
            for k in ("rename_delete_limit", "suspicious_limit"):
                if changes.get(k) is not None:
                    self.state[k] = max(3, min(100000, int(changes[k])))
            self._save()
        if self.state["canaries"]:
            self.place_canaries()
        return self.status()

    def status(self) -> dict[str, Any]:
        keys = (
            "enabled",
            "canaries",
            "rename_delete_limit",
            "suspicious_limit",
            "frozen",
            "frozen_at",
            "reason",
            "source",
            "snapshots",
        )
        return {k: self.state.get(k) for k in keys} | {"canary_count": len(self.state.get("canary_files") or {})}

    @property
    def frozen(self) -> bool:
        return bool(self.state.get("frozen"))

    # --- detection -----------------------------------------------------
    @staticmethod
    def is_suspicious_name(path: str) -> bool:
        name = os.path.basename(str(path or "").rstrip("/"))
        ext = os.path.splitext(name)[1].lower()
        return ext in RANSOM_EXTENSIONS or bool(RANSOM_NOTE_RE.search(name))

    def observe(self, kind: str, path: str, user: str = "", ip: str = "", new_path: str = "") -> bool:
        """Records one file change. Returns True when it triggered the lockdown."""
        if kind not in WRITE_KINDS or not self.state.get("enabled", True) or self.frozen:
            return False
        now = time.time()
        actor = user or ip or "unknown"
        trigger = None
        with self._lock:
            if kind in ("rename", "delete"):
                q = self._events.setdefault(actor, deque())
                q.append(now)
                while q and now - q[0] > WINDOW_S:
                    q.popleft()
                if len(q) >= int(self.state["rename_delete_limit"]):
                    trigger = f"{len(q)} renames or deletes in {WINDOW_S} seconds"
            if self.is_suspicious_name(new_path or path):
                s = self._suspicious.setdefault(actor, deque())
                s.append(now)
                while s and now - s[0] > WINDOW_S:
                    s.popleft()
                if len(s) >= int(self.state["suspicious_limit"]):
                    trigger = f"{len(s)} files renamed to ransomware extensions or ransom notes in {WINDOW_S} seconds"
            if trigger:
                self._events.pop(actor, None)
                self._suspicious.pop(actor, None)
        if trigger:
            self._react(trigger, {"user": user, "ip": ip, "example": new_path or path})
            return True
        return False

    # --- guard files ---------------------------------------------------
    @staticmethod
    def _canary_bytes() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            )
            z.writestr(
                "_rels/.rels",
                '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
            )
            z.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>ZettNAS ransomware guard file. Please leave it here: if it changes, ZettNAS stops all writes to protect your files.</w:t></w:r></w:p></w:body></w:document>',
            )
        return buf.getvalue()

    @staticmethod
    def protected_roots() -> list[str]:
        roots: list[str] = []
        try:
            from backend.services.samba_engine import get_samba_engine

            roots += [s.path for s in get_samba_engine().list_shares()]
        except Exception:
            logger.debug("ransomware_guard: no Samba shares", exc_info=True)
        pool = os.environ.get("POOL_PATH", "/mnt/user")
        skip = {"appdata", "system", "domains", "isos", "docker", "libvirt"}
        try:
            roots += [
                os.path.join(pool, d)
                for d in sorted(os.listdir(pool))
                if d not in skip and not d.startswith(".") and os.path.isdir(os.path.join(pool, d))
            ]
        except OSError:
            logger.debug("ransomware_guard: pool folder unreadable", exc_info=True)
        return sorted({os.path.normpath(r) for r in roots if os.path.isdir(r)})

    def place_canaries(self, roots: list[str] | None = None) -> int:
        data = self._canary_bytes()
        placed = {}
        for root in roots if roots is not None else self.protected_roots():
            p = os.path.join(root, CANARY_NAME)
            try:
                if not os.path.exists(p):
                    with open(p, "wb") as f:
                        f.write(data)
                st = os.stat(p)
                placed[p] = {"size": st.st_size, "mtime": st.st_mtime_ns}
            except OSError:
                logger.debug("ransomware_guard: could not place %s", p, exc_info=True)
        with self._lock:
            self.state["canary_files"] = placed
            self._save()
        return len(placed)

    @staticmethod
    def _on_sleeping_disk(path: str) -> bool:
        """True only when the guard file's disk is known and asleep. Checking it then could wake
        it, and a sleeping disk is not being written to. Unknown disks are still checked (PERF-7)."""
        try:
            from backend.services import rag_standby

            dev = rag_standby.resolve_path_backing_dev(path)
            if not dev or dev == rag_standby.UNKNOWN_BACKING_DEV:
                return False
            return rag_standby.is_backing_disk_in_standby(dev)
        except Exception:
            return False

    def check_canaries(self) -> bool:
        if not self.state.get("enabled", True) or not self.state.get("canaries") or self.frozen:
            return False
        for p, seen in list((self.state.get("canary_files") or {}).items()):
            if self._on_sleeping_disk(p):
                continue
            try:
                st = os.stat(p)
                changed = st.st_size != seen["size"] or st.st_mtime_ns != seen["mtime"]
            except FileNotFoundError:
                changed = True
            except OSError:
                continue  # unreadable for now (disk asleep, share offline): not evidence
            if changed:
                self._react("a guard file was changed or deleted", {"example": p})
                return True
        return False

    # --- response ------------------------------------------------------
    def _lockdown(self, reason: str, source: dict[str, Any]) -> None:
        logger.critical(f"[RansomwareGuard] {reason} ({source}). Freezing writes.")
        with self._lock:
            self.state.update(frozen=True, frozen_at=time.time(), reason=reason, source=source)
            self._save()
        _apply_share_freeze(True)
        snaps = _snapshot_pools()
        with self._lock:
            self.state["snapshots"] = snaps
            self._save()
        if source.get("ip"):
            from backend.services import ip_block

            ip_block.block(source["ip"], f"ransomware guard: {reason}", seconds=24 * 3600)
        snap_txt = ", ".join(s["name"] for s in snaps if s.get("ok")) or "no pool here supports ZettNAS snapshots"
        msg = (
            f"{reason}. Writes are frozen on ZettNAS shares, the file manager and WebDAV. "
            f"Source: {source.get('user') or '-'} from {source.get('ip') or '-'}. Example: {source.get('example', '-')}. "
            f"Snapshots: {snap_txt}. Check the source computer, then lift the freeze under Security."
        )
        try:
            from backend.state import add_event

            add_event("security", f"Ransomware guard: {reason}", "critical")
        except Exception:
            logger.debug("ransomware_guard: event log unavailable", exc_info=True)
        try:
            from backend.services.notifications import send_notification

            send_notification(
                "ZettNAS stopped a possible ransomware attack",
                msg,
                level="critical",
                event_type="security",
                dedup_key="ransomware-guard",
            )
        except Exception:
            logger.warning("[RansomwareGuard] Could not send the alert", exc_info=True)

    def unfreeze(self, by: str = "") -> dict[str, Any]:
        with self._lock:
            self.state.update(frozen=False, reason="", source={}, frozen_at=None)
            self._save()
        _apply_share_freeze(False)
        if self.state.get("canaries"):
            self.place_canaries()
        try:
            from backend.state import add_event

            add_event("security", f"Ransomware guard freeze lifted by {by or 'an admin'}", "info")
        except Exception:
            logger.debug("ransomware_guard: event log unavailable", exc_info=True)
        return self.status()

    def run_forever(self, sleep=time.sleep) -> None:
        from backend.services.supervisor import beat

        while True:
            beat("RansomwareGuard")
            try:
                self.check_canaries()
            except Exception:
                logger.debug("ransomware_guard: canary check failed", exc_info=True)
            sleep(30)


def _apply_share_freeze(frozen: bool) -> None:
    try:
        from backend.services.samba_engine import get_samba_engine

        eng = get_samba_engine()
        eng.generate_and_save_conf()
        eng.reload_service()
    except Exception:
        logger.debug("ransomware_guard: Samba not managed here", exc_info=True)
    try:
        from backend.services.nfs_engine import get_nfs_engine

        get_nfs_engine().apply_exports()  # exports become read-only while frozen
    except Exception:
        logger.debug("ransomware_guard: NFS not managed here", exc_info=True)
    try:
        from backend.services.webdav_engine import get_webdav_engine

        dav = get_webdav_engine()
        if dav.is_running():
            dav.restart()  # restarts read-only while frozen, writable again after
    except Exception:
        logger.debug("ransomware_guard: WebDAV not running", exc_info=True)
    if frozen:
        try:
            from backend.services.container_mutator import _docker_request

            _docker_request("POST", "/containers/zettnas-sftp/stop?t=2")
        except Exception:
            logger.debug("ransomware_guard: no SFTP service to stop", exc_info=True)


def writes_frozen() -> bool:
    """True while the guard has frozen writes on every share (M4, SEC-6)."""
    try:
        return get_guard().frozen
    except Exception:
        logger.debug("ransomware_guard: state unavailable", exc_info=True)
        return False


def _snapshot_pools() -> list[dict[str, Any]]:
    out = []
    try:
        from backend.hardware.pal_storage import get_storage_platform

        pal = get_storage_platform()
        from backend.services import truenas_api

        if pal.get_capabilities().is_observer_mode and not truenas_api.configured():
            return out
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for pool in pal.list_pools():
            if pool.fs_type not in ("btrfs", "zfs"):
                continue
            name = f"ransomware-guard-{stamp}"
            try:
                # locked for a week, so whoever triggered the guard can't delete them (Batch 6)
                try:
                    res = pal.create_snapshot(
                        pool.id, "", name, readonly=True, worm_mode="governance", retention_days=7
                    )
                except TypeError:  # an adapter without retention locks
                    res = pal.create_snapshot(pool.id, "", name, readonly=True)
                out.append({"pool": pool.id, "name": name, "ok": bool(res.get("success", True))})
            except Exception as e:
                out.append({"pool": pool.id, "name": name, "ok": False, "error": str(e)[:200]})
    except Exception:
        logger.warning("[RansomwareGuard] Snapshot step failed", exc_info=True)
    return out


_GUARD: RansomwareGuard | None = None


def get_guard() -> RansomwareGuard:
    global _GUARD
    if _GUARD is None:
        _GUARD = RansomwareGuard()
    return _GUARD


def guard_daemon() -> None:
    get_guard().run_forever()

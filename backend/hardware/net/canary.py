"""Host IP changes that undo themselves: Unraid network.cfg read and write, and the canary watchdog that reverts a change unless it is confirmed in time.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import secrets
import threading
import time
from typing import Any

from backend.config import logger
from backend.hardware.net import common


class CanaryWatchdog:
    """
    60-second self-lockout prevention watchdog for host network reconfiguration.
    Automatically rolls back host IP, gateway, and DNS settings if the client fails
    to confirm connectivity within the timeout window.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.is_active = False
        self.canary_id = ""
        self.started_at = 0.0
        self.deadline = 0.0
        self.target_ip = ""
        self.target_config: dict[str, Any] = {}
        self.original_config: dict[str, Any] = {}
        self._timer: threading.Timer | None = None

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            rem = max(0, int(self.deadline - now)) if self.is_active else 0
            return {
                "is_active": self.is_active,
                "expires_in": rem,
                "target_ip": self.target_ip if self.is_active else None,
                "canary_id": self.canary_id if self.is_active else None,
            }

    def arm(
        self,
        target_config: dict[str, Any],
        original_config: dict[str, Any],
        timeout_sec: int = 60,
    ) -> str:
        with self._lock:
            if self._timer:
                try:
                    self._timer.cancel()
                except Exception:
                    logger.debug("backend.hardware.network.CanaryWatchdog.arm: ignored error", exc_info=True)
                self._timer = None

            canary_id = secrets.token_hex(8)
            now = time.time()
            self.is_active = True
            self.canary_id = canary_id
            self.started_at = now
            self.deadline = now + timeout_sec
            self.target_config = dict(target_config)
            self.original_config = dict(original_config)
            self.target_ip = target_config.get("ip_address") or ""

            # Launch atomic background rollback watchdog
            self._timer = threading.Timer(float(timeout_sec), self._on_timeout, args=[canary_id])
            self._timer.daemon = True
            self._timer.start()
            return canary_id

    def confirm(self, canary_id: str | None = None) -> bool:
        with self._lock:
            if not self.is_active:
                return False
            if canary_id and canary_id != self.canary_id:
                return False
            if self._timer:
                try:
                    self._timer.cancel()
                except Exception:
                    logger.debug("backend.hardware.network.CanaryWatchdog.confirm: ignored error", exc_info=True)
                self._timer = None
            self.is_active = False
            return True

    def revert(self, canary_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            if not self.is_active:
                return None
            if canary_id and canary_id != self.canary_id:
                return None
            if self._timer:
                try:
                    self._timer.cancel()
                except Exception:
                    logger.debug("backend.hardware.network.CanaryWatchdog.revert: ignored error", exc_info=True)
                self._timer = None
            orig = dict(self.original_config)
            self.is_active = False
            return orig

    def _on_timeout(self, canary_id: str):
        orig = None
        with self._lock:
            if not self.is_active or self.canary_id != canary_id:
                return
            orig = dict(self.original_config)
            self.is_active = False
            self._timer = None

        logger.warning(
            f"[Network Canary] 60s Watchdog expired for canary {canary_id}! Auto-reverting host network to prevent self-lockout."
        )
        if orig:
            _execute_revert(orig)
            try:
                from backend.state import add_event

                add_event(
                    "error",
                    "Network Canary Expired",
                    "Canary rollback watchdog expired after 60s without confirmation! Host network automatically restored to prevent lockout.",
                )
            except Exception:
                logger.debug("backend.hardware.network.CanaryWatchdog._on_timeout: ignored error", exc_info=True)


_CANARY_WATCHDOG = CanaryWatchdog()


def get_canary_watchdog() -> CanaryWatchdog:
    return _CANARY_WATCHDOG


def _parse_unraid_network_cfg() -> dict[str, str]:
    """Parse key-values from Unraid /boot/config/network.cfg if present."""
    cfg: dict[str, str] = {}
    for c in common.UNRAID_NETWORK_CFG:
        if os.path.isfile(c):
            try:
                with open(c, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            cfg[k.strip()] = v.strip().strip('"').strip("'")
                return cfg
            except Exception as e:
                logger.debug(f"Error parsing unraid network cfg: {e}")
    return cfg


def _write_unraid_network_cfg(updates: dict[str, str]) -> bool:
    """Update Unraid /boot/config/network.cfg preserving order and unmanaged keys."""
    for c in common.UNRAID_NETWORK_CFG:
        if os.path.isfile(c):
            try:
                lines = []
                with open(c, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                updated_keys = set()
                new_lines = []
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        k = stripped.split("=", 1)[0].strip()
                        if k in updates:
                            new_lines.append(f'{k}="{updates[k]}"\n')
                            updated_keys.add(k)
                            continue
                    new_lines.append(line)
                for k, v in updates.items():
                    if k not in updated_keys:
                        new_lines.append(f'{k}="{v}"\n')
                tmp_c = f"{c}.tmp.{os.getpid()}"
                with open(tmp_c, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                os.replace(tmp_c, c)
                return True
            except Exception as e:
                logger.warning(f"Error writing unraid network cfg: {e}")
    return False


def _execute_revert(orig: dict[str, Any]) -> None:
    """Restores original network settings on the host."""
    cfg = common.load_network_config()
    cfg.pop("host_ip_staged", None)
    common.save_network_config(cfg)

    # Revert Unraid /boot/config/network.cfg if on Unraid
    unraid_updates = {}
    orig_mode = orig.get("mode", "static")
    if orig_mode == "dhcp":
        unraid_updates["USE_DHCP[0]"] = "yes"
    else:
        unraid_updates["USE_DHCP[0]"] = "no"
        if orig.get("ip_address"):
            unraid_updates["IPADDR[0]"] = orig["ip_address"]
        if orig.get("netmask"):
            unraid_updates["NETMASK[0]"] = orig["netmask"]
        if orig.get("gateway"):
            unraid_updates["GATEWAY[0]"] = orig["gateway"]
        if orig.get("dns1"):
            unraid_updates["DNS_SERVER1"] = orig["dns1"]
        if "dns2" in orig:
            unraid_updates["DNS_SERVER2"] = orig["dns2"]

    if unraid_updates:
        _write_unraid_network_cfg(unraid_updates)

import glob
import mmap
import os
import threading
import time
from typing import List, Optional

from backend.config import (
    FAN_FAILSAFE_PWM,
    FAN_KICKSTART_PWM,
    FAN_KICKSTART_SECS,
    FAN_MAX_PWM,
    FAN_MIN_PWM,
    HOST_DEV,
    HOST_SYS,
    logger,
)
from backend.hardware.cpu import _find_hwmon
from backend.state import Z_STATE


def is_zettlab_appliance() -> bool:
    """Detects whether running host is a Zettlab or Aoostar NAS appliance."""
    force = os.environ.get("FORCE_ZETTLAB_MMIO", "").strip()
    if force == "1":
        return True
    if force == "0":
        return False
    try:
        from backend.hardware.chassis import ChassisEngine

        vendor = ChassisEngine._read_dmi_sys_vendor().lower()
        product = ChassisEngine._read_dmi_product_name().lower()
        board = ChassisEngine._read_dmi_field("board_name").lower()
        dmi_str = f"{vendor} {product} {board}"
        return any(
            k in dmi_str for k in ("zettlab", "zettos", "wy110", "wy120", "wy140", "d4", "d6", "d6u", "d8u", "aoostar")
        )
    except Exception:
        return False


class ZettlabMmioFanController:
    """Direct Memory-Mapped I/O (MMIO) hardware fan controller for Zettlab & Aoostar NAS appliances.

    Accesses physical Embedded Controller (EC) register aperture at 0xFE0B0456 via /dev/mem
    without requiring any out-of-tree Linux kernel modules (e.g. zettlab_d8_fans.ko).

    Immune to Linux kernel updates (Unraid 7.3.3, 7.4.x, TrueNAS, Ubuntu, Proxmox).
    """

    PHYS_BASE_ADDR = 0xFE0B0456
    PAGE_SIZE = 4096

    # Register offsets relative to PHYS_BASE_ADDR
    OFF_FAN1_RPM = 0  # 16-bit big-endian tachometer (Disks Zone 1: Bays 1-4)
    OFF_FAN1_PWM = 2  # 8-bit PWM (0..183)
    OFF_FAN2_RPM = 3  # 16-bit big-endian tachometer (Disks Zone 2: Bays 5-8)
    OFF_FAN2_PWM = 5  # 8-bit PWM (0..183)
    OFF_FAN3_RPM = 6  # 16-bit big-endian tachometer (CPU Fan)
    OFF_FAN3_PWM = 8  # 8-bit PWM (0 = firmware auto, 58..183 = manual)

    def __init__(self, dev_mem_path: Optional[str] = None):
        self._dev_path = dev_mem_path
        self._fd: Optional[int] = None
        self._mm: Optional[mmap.mmap] = None
        self._lock = threading.Lock()
        self._failed_previously = False

        self._base_page = self.PHYS_BASE_ADDR & ~(self.PAGE_SIZE - 1)
        self._page_offset = self.PHYS_BASE_ADDR - self._base_page

    def _get_candidate_paths(self) -> List[str]:
        if self._dev_path:
            return [self._dev_path]
        return [
            "/dev/mem",
            os.path.join(HOST_DEV, "mem"),
            "/host/dev/mem",
        ]

    def _ensure_mapped(self) -> bool:
        with self._lock:
            if self._mm is not None:
                return True
            if self._failed_previously:
                return False

            for cand in self._get_candidate_paths():
                if not cand or not os.path.exists(cand):
                    continue
                fd = None
                try:
                    fd = os.open(cand, os.O_RDWR | os.O_SYNC)
                    mm = mmap.mmap(
                        fd,
                        self.PAGE_SIZE,
                        mmap.MAP_SHARED,
                        mmap.PROT_READ | mmap.PROT_WRITE,
                        offset=self._base_page,
                    )
                    # Verify probe read
                    _ = mm[self._page_offset]
                    self._fd = fd
                    self._mm = mm
                    logger.info(
                        f"[FANS-MMIO] Successfully memory-mapped hardware fan controller at 0x{self.PHYS_BASE_ADDR:X} via {cand}"
                    )
                    return True
                except Exception as e:
                    logger.debug(f"[FANS-MMIO] Failed mapping {cand}: {e}")
                    if fd is not None:
                        try:
                            os.close(fd)
                        except Exception:
                            pass

            self._failed_previously = True
            return False

    def is_available(self) -> bool:
        if not is_zettlab_appliance():
            return False
        return self._ensure_mapped()

    def read_fans(self) -> List[int]:
        if not self._ensure_mapped():
            return []
        with self._lock:
            try:
                base = self._page_offset
                rpm1 = (self._mm[base + self.OFF_FAN1_RPM] << 8) | self._mm[base + self.OFF_FAN1_RPM + 1]
                rpm2 = (self._mm[base + self.OFF_FAN2_RPM] << 8) | self._mm[base + self.OFF_FAN2_RPM + 1]
                rpm3 = (self._mm[base + self.OFF_FAN3_RPM] << 8) | self._mm[base + self.OFF_FAN3_RPM + 1]
                return [rpm1, rpm2, rpm3]
            except Exception as e:
                logger.warning(f"[FANS-MMIO] Error reading RPM registers: {e}")
                return []

    def write_pwm(self, channel: int, pwm_val: int) -> bool:
        if not self._ensure_mapped():
            return False
        with self._lock:
            try:
                base = self._page_offset
                clamped = max(0, min(FAN_MAX_PWM, int(pwm_val)))
                if channel == 1:
                    self._mm[base + self.OFF_FAN1_PWM] = clamped
                elif channel == 2:
                    self._mm[base + self.OFF_FAN2_PWM] = clamped
                elif channel == 3:
                    self._mm[base + self.OFF_FAN3_PWM] = clamped
                else:
                    return False
                return True
            except Exception as e:
                logger.warning(f"[FANS-MMIO] Error writing PWM channel {channel} val {pwm_val}: {e}")
                return False

    def close(self):
        with self._lock:
            if self._mm is not None:
                try:
                    self._mm.close()
                except Exception:
                    pass
                self._mm = None
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
                self._fd = None
            self._failed_previously = False


_mmio_controller: Optional[ZettlabMmioFanController] = None


def get_mmio_fan_controller() -> Optional[ZettlabMmioFanController]:
    global _mmio_controller
    if _mmio_controller is None:
        _mmio_controller = ZettlabMmioFanController()
    return _mmio_controller


def clamp_fan_pwm(val: int, allow_zero: bool = False) -> int:
    """Enforce physical PWM bounds and strict binary cutoff for Zero RPM.

    If allow_zero is True and val <= 0:
        Returns 0 (fan stopped).
    Otherwise:
        Clamps val to [FAN_MIN_PWM, FAN_MAX_PWM] (58..183).
    Values between 1 and 57 are strictly forbidden to prevent motor stall currents,
    locked-rotor heating, and coil whine.
    """
    try:
        ival = int(val)
    except (TypeError, ValueError):
        ival = FAN_MIN_PWM

    if allow_zero and ival <= 0:
        return 0
    return max(FAN_MIN_PWM, min(FAN_MAX_PWM, ival))


def read_fans():
    hw = _find_hwmon()
    fans = []
    if hw:
        Z_STATE.fan_driver_mode = "hwmon"
        for f in sorted(glob.glob(os.path.join(hw, "fan*_input"))):
            try:
                with open(f, "r") as fp:
                    rpm = int(fp.read().strip() or 0)
                fans.append(rpm)
            except Exception:
                fans.append(0)
    else:
        mmio = get_mmio_fan_controller()
        if mmio and mmio.is_available():
            Z_STATE.fan_driver_mode = "mmio"
            fans = mmio.read_fans()
        else:
            Z_STATE.fan_driver_mode = "none"
            for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
                for f in sorted(glob.glob(os.path.join(h, "fan*_input"))):
                    try:
                        with open(f, "r") as fp:
                            rpm = int(fp.read().strip() or 0)
                        if rpm > 0:
                            fans.append(rpm)
                    except Exception:
                        pass
    # Sanitize fan readings (e.g. spurious 8000 RPM or 65535 spikes from I2C bugs)
    for i in range(len(fans)):
        if fans[i] >= 6000:
            fans[i] = 0

    global _fan_presence_counter
    if "_fan_presence_counter" not in globals():
        _fan_presence_counter = {}

    for idx, rpm in enumerate(fans):
        if rpm > 300:
            _fan_presence_counter[idx] = _fan_presence_counter.get(idx, 0) + 1
            if _fan_presence_counter[idx] >= 3:
                Z_STATE.known_active_fans.add(idx)
        else:
            if idx not in Z_STATE.known_active_fans:
                _fan_presence_counter[idx] = 0
    return fans


def cleanup_stale_fan_trackers(active_keys=None):
    """Evict stale pwm_key entries from Z_STATE.fan_state_tracker."""
    if active_keys is None:
        hw = _find_hwmon()
        if hw:
            active_keys = {os.path.basename(p) for p in glob.glob(os.path.join(hw, "pwm[1-9]"))}
        elif is_zettlab_appliance():
            active_keys = {"pwm1", "pwm2", "pwm3"}
        else:
            active_keys = set()
    if active_keys:
        stale = [k for k in list(Z_STATE.fan_state_tracker.keys()) if k not in active_keys]
        for k in stale:
            Z_STATE.fan_state_tracker.pop(k, None)


def sanitize_curve_points(points):
    """Normalize user curve points to a safe, monotonic, bounded curve.

    - temps clamped to 0..100 °C, percentages to 0..100
    - sorted by temperature, duplicate temperatures collapsed
    - fan % made non-decreasing (a hotter point can never be slower)
    Returns None when fewer than 2 valid points remain.
    """
    if not points:
        return None
    cleaned = {}
    for pt in points:
        try:
            t, p = int(pt[0]), int(pt[1])
        except (TypeError, ValueError, IndexError):
            continue
        t = max(0, min(100, t))
        p = max(0, min(100, p))
        cleaned[t] = max(p, cleaned.get(t, 0))
    if len(cleaned) < 2:
        return None
    out, running = [], 0
    for t in sorted(cleaned):
        running = max(running, cleaned[t])
        out.append([t, running])
    return out


def calc_curve_pwm(
    temp,
    min_pwm=FAN_MIN_PWM,
    max_pwm=FAN_MAX_PWM,
    temp_min=37,
    temp_max=50,
    curve_points=None,
    allow_zero=False,
):
    if temp is None or temp <= 0:
        # Thermal failsafe: missing, disconnected, or unreadable sensor data
        # must never stall or stop cooling fans. Default to failsafe PWM.
        return FAN_FAILSAFE_PWM

    effective_min = 0 if allow_zero else min_pwm

    # Inviolable hardware thermal watchdog with hysteresis
    WATCHDOG_CEILING_TEMP = 80
    WATCHDOG_RELEASE_TEMP = 74

    if temp >= WATCHDOG_CEILING_TEMP or (
        getattr(Z_STATE, "thermal_watchdog_engaged", False) and temp > WATCHDOG_RELEASE_TEMP
    ):
        Z_STATE.thermal_watchdog_engaged = True
        return max_pwm
    else:
        Z_STATE.thermal_watchdog_engaged = False

    pts = sanitize_curve_points(curve_points)
    if pts:
        if temp <= pts[0][0]:
            pct = pts[0][1]
        elif temp >= pts[-1][0]:
            pct = pts[-1][1]
        else:
            pct = pts[0][1]
            for i in range(len(pts) - 1):
                t1, p1 = pts[i]
                t2, p2 = pts[i + 1]
                if t1 <= temp <= t2:
                    span = max(1, t2 - t1)
                    ratio = (temp - t1) / float(span)
                    pct = p1 + ratio * (p2 - p1)
                    break
        val = int((pct / 100.0) * max_pwm)
        return clamp_fan_pwm(val, allow_zero=allow_zero)

    if temp >= temp_max:
        return max_pwm
    if temp <= temp_min:
        return effective_min
    span = max(1, temp_max - temp_min)
    ratio = (temp - temp_min) / float(span)
    val = int(min_pwm + ratio * (max_pwm - min_pwm))
    return clamp_fan_pwm(val, allow_zero=allow_zero)


def apply_zone_pwm(pwm_index, target_pwm, hold_secs=120, allow_zero=False):
    now = time.time()
    pwm_key = f"pwm{pwm_index}"
    # CPU fan (pwm3) is strictly forbidden from entering Zero RPM
    if pwm_key == "pwm3":
        allow_zero = False

    if pwm_key not in Z_STATE.fan_state_tracker:
        Z_STATE.fan_state_tracker[pwm_key] = {
            "current": 67,
            "last_up_time": 0.0,
            "kickstart_until": 0.0,
            "last_spinup_time": now,
            "standby_since": 0.0,
        }
    state = Z_STATE.fan_state_tracker[pwm_key]
    current = state.get("current", 67)
    clamped_target = clamp_fan_pwm(target_pwm, allow_zero=allow_zero)

    # 1. Non-blocking Kickstart from 0 RPM to Active Speed
    if current == 0 and clamped_target > 0:
        state["kickstart_until"] = now + FAN_KICKSTART_SECS
        state["last_spinup_time"] = now
        state["current"] = clamped_target
        state["last_up_time"] = now
        return FAN_KICKSTART_PWM

    # If kickstart window is currently active, deliver kickstart pulse unless target is higher
    if now < state.get("kickstart_until", 0.0):
        if clamped_target > FAN_KICKSTART_PWM:
            state["kickstart_until"] = 0.0
            state["current"] = clamped_target
            state["last_up_time"] = now
            return clamped_target
        if clamped_target > 0:
            state["current"] = clamped_target
        return FAN_KICKSTART_PWM

    # 2. Upward ramp: instantaneous
    if clamped_target > current:
        state["current"] = clamped_target
        state["last_up_time"] = now
        return clamped_target

    # 3. Downward ramp: apply hysteresis hold
    elif clamped_target < current:
        if (now - state.get("last_up_time", 0.0)) >= hold_secs:
            state["current"] = clamped_target
            return clamped_target
        else:
            return current

    return current


def get_hold_remaining(pwm_key, hold_secs=120):
    state = Z_STATE.fan_state_tracker.get(pwm_key, {})
    last_up = state.get("last_up_time", 0.0)
    rem = hold_secs - (time.time() - last_up)
    return max(0, int(rem))


def _write_sysfs(path, value):
    try:
        with open(path, "w") as f:
            f.write(f"{value}\n")
        return True
    except OSError as e:
        logger.warning(f"[FANS] Failed writing {value} to {path}: {e}")
        return False


def set_fan_pwm(profile, manual_pct=60, custom_pwms=None, ctrl_cpu_fan=False, zero_rpm_allowed=False):
    if Z_STATE.fans_locked:
        return False
    hw = _find_hwmon()
    if hw:
        Z_STATE.fan_driver_mode = "hwmon"
        applied = 0
        available_pwms = sorted(glob.glob(os.path.join(hw, "pwm[1-9]")))
        cleanup_stale_fan_trackers({os.path.basename(p) for p in available_pwms})

        if custom_pwms:
            targets = {}
            for p in available_pwms:
                key = os.path.basename(p)
                if key == "pwm3" and not ctrl_cpu_fan:
                    continue
                targets[p] = custom_pwms.get(key, 67)
        else:
            pct_map = {"quiet": 67, "balanced": 120, "performance": 155, "full": FAN_MAX_PWM}
            raw = pct_map.get(profile, int((manual_pct / 100.0) * FAN_MAX_PWM))
            targets = {p: raw for p in available_pwms if not (os.path.basename(p) == "pwm3" and not ctrl_cpu_fan)}

        # CPU fan: hand back to firmware when we are not controlling it.
        pwm3_enable_file = os.path.join(hw, "pwm3_enable")
        if not ctrl_cpu_fan and _read_sysfs(pwm3_enable_file) not in (None, "2"):
            _write_sysfs(pwm3_enable_file, 2)

        for path, val in targets.items():
            key = os.path.basename(path)
            allow_zero_channel = zero_rpm_allowed and (key in ("pwm1", "pwm2"))
            val = clamp_fan_pwm(val, allow_zero=allow_zero_channel)
            # Claim manual mode for channels we drive (pwm3 may have been handed to
            # firmware). On this driver pwm1/2_enable are read-only and always 1.
            enable_file = f"{path}_enable"
            if _read_sysfs(enable_file) not in (None, "1") and _is_writable(enable_file):
                _write_sysfs(enable_file, 1)
            if os.path.exists(path) and _write_sysfs(path, val):
                applied += 1

        if applied:
            if Z_STATE.fans_released:
                logger.info("[FANS] Software fan control resumed.")
            Z_STATE.fans_released = False
        return applied > 0

    # Fallback to direct Userspace MMIO on supported appliances
    mmio = get_mmio_fan_controller()
    if not mmio or not mmio.is_available():
        Z_STATE.fan_driver_mode = "none"
        return False

    Z_STATE.fan_driver_mode = "mmio"
    cleanup_stale_fan_trackers({"pwm1", "pwm2", "pwm3"})

    if custom_pwms:
        target1 = custom_pwms.get("pwm1", 67)
        target2 = custom_pwms.get("pwm2", 67)
        target3 = custom_pwms.get("pwm3", 85)
    else:
        pct_map = {"quiet": 67, "balanced": 120, "performance": 155, "full": FAN_MAX_PWM}
        raw = pct_map.get(profile, int((manual_pct / 100.0) * FAN_MAX_PWM))
        target1 = target2 = target3 = raw

    # CPU fan: hand back to firmware (offset 8 = 0) when not controlling it.
    if not ctrl_cpu_fan:
        pwm3_val = 0
    else:
        pwm3_val = clamp_fan_pwm(target3, allow_zero=False)

    pwm1_val = clamp_fan_pwm(target1, allow_zero=zero_rpm_allowed)
    pwm2_val = clamp_fan_pwm(target2, allow_zero=zero_rpm_allowed)

    ok1 = mmio.write_pwm(1, pwm1_val)
    ok2 = mmio.write_pwm(2, pwm2_val)
    ok3 = mmio.write_pwm(3, pwm3_val)

    if ok1 or ok2 or ok3:
        if Z_STATE.fans_released:
            logger.info("[FANS] Software fan control resumed via MMIO.")
        Z_STATE.fans_released = False
        return True
    return False


def _read_sysfs(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _is_writable(path):
    """sysfs enforces mode bits even for root, so check them directly."""
    try:
        return bool(os.stat(path).st_mode & 0o222)
    except OSError:
        return False


def failsafe_release_fans(reason="shutdown", lock=False):
    """Put every fan channel in a safe state.

    - Channels that support firmware/EC automatic control (writable
      pwmN_enable, e.g. the CPU fan) are handed back to it (enable = 2).
    - Channels without a firmware mode (the ZettLab disk fans: pwm1/2_enable
      are read-only) are pinned at FAN_FAILSAFE_PWM, which the driver keeps
      after the container exits.
    Safe to call repeatedly. With lock=True (shutdown) software control is
    not reclaimed afterwards.
    """
    if lock:
        Z_STATE.fans_locked = True
    hw = _find_hwmon()
    if hw:
        failsafe = max(FAN_MIN_PWM, min(FAN_MAX_PWM, FAN_FAILSAFE_PWM))
        logger.warning(f"[FANS] Failsafe engaged ({reason}): disk fans -> PWM {failsafe}, CPU fan -> firmware auto.")
        for path in sorted(glob.glob(os.path.join(hw, "pwm[1-9]"))):
            enable_file = f"{path}_enable"
            if _is_writable(enable_file):
                if _read_sysfs(enable_file) != "2":
                    _write_sysfs(enable_file, 2)
            else:
                _write_sysfs(path, failsafe)
        Z_STATE.fans_released = True
        return True

    mmio = get_mmio_fan_controller()
    if mmio and mmio.is_available():
        failsafe = max(FAN_MIN_PWM, min(FAN_MAX_PWM, FAN_FAILSAFE_PWM))
        logger.warning(
            f"[FANS] Failsafe engaged ({reason}) via MMIO: disk fans -> PWM {failsafe}, CPU fan -> firmware auto."
        )
        mmio.write_pwm(1, failsafe)
        mmio.write_pwm(2, failsafe)
        mmio.write_pwm(3, 0)
        Z_STATE.fans_released = True
        return True

    return False

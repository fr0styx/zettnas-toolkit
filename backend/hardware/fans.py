import glob
import os
import time

from backend.config import FAN_FAILSAFE_PWM, FAN_MAX_PWM, FAN_MIN_PWM, HOST_SYS, logger
from backend.hardware.cpu import _find_hwmon
from backend.state import Z_STATE


def read_fans():
    hw = _find_hwmon()
    fans = []
    if hw:
        for f in sorted(glob.glob(os.path.join(hw, "fan*_input"))):
            try:
                with open(f, "r") as fp:
                    rpm = int(fp.read().strip() or 0)
                fans.append(rpm)
            except Exception:
                fans.append(0)
    else:
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

    for idx, rpm in enumerate(fans):
        if rpm > 300:
            Z_STATE.known_active_fans.add(idx)
    return fans


def cleanup_stale_fan_trackers(active_keys=None):
    """Evict stale pwm_key entries from Z_STATE.fan_state_tracker."""
    if active_keys is None:
        hw = _find_hwmon()
        if hw:
            active_keys = {os.path.basename(p) for p in glob.glob(os.path.join(hw, "pwm[1-9]"))}
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


def calc_curve_pwm(temp, min_pwm=FAN_MIN_PWM, max_pwm=FAN_MAX_PWM, temp_min=37, temp_max=50, curve_points=None):
    if temp is None or temp <= 0:
        return min_pwm

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
        # Never below the minimum reliable spin speed.
        return max(min_pwm, min(max_pwm, val))

    if temp >= temp_max:
        return max_pwm
    if temp <= temp_min:
        return min_pwm
    span = max(1, temp_max - temp_min)
    ratio = (temp - temp_min) / float(span)
    val = int(min_pwm + ratio * (max_pwm - min_pwm))
    return max(min_pwm, min(max_pwm, val))


def apply_zone_pwm(pwm_index, target_pwm, hold_secs=120):
    now = time.time()
    pwm_key = f"pwm{pwm_index}"
    if pwm_key not in Z_STATE.fan_state_tracker:
        Z_STATE.fan_state_tracker[pwm_key] = {"current": 67, "last_up_time": 0.0}
    state = Z_STATE.fan_state_tracker[pwm_key]
    current = state["current"]

    if target_pwm > current:
        state["current"] = target_pwm
        state["last_up_time"] = now
        return target_pwm
    elif target_pwm < current:
        if (now - state["last_up_time"]) >= hold_secs:
            state["current"] = target_pwm
            return target_pwm
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


def set_fan_pwm(profile, manual_pct=60, custom_pwms=None, ctrl_cpu_fan=False):
    if Z_STATE.fans_locked:
        return False
    hw = _find_hwmon()
    if not hw:
        return False

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
        val = max(FAN_MIN_PWM, min(FAN_MAX_PWM, int(val)))
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
    if not hw:
        return False
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

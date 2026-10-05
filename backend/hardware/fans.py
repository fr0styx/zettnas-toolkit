import os
import glob
import time
from backend.config import logger, HOST_SYS
from backend.state import Z_STATE
from backend.hardware.cpu import _find_hwmon

def read_fans():
    hw = _find_hwmon()
    fans = []
    if hw:
        for f in sorted(glob.glob(os.path.join(hw, "fan*_input"))):
            try:
                rpm = int(open(f).read().strip() or 0)
                fans.append(rpm)
            except Exception:
                fans.append(0)
    else:
        for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
            for f in sorted(glob.glob(os.path.join(h, "fan*_input"))):
                try:
                    rpm = int(open(f).read().strip() or 0)
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

def calc_curve_pwm(temp, min_pwm=58, max_pwm=183, temp_min=37, temp_max=50, curve_points=None):
    if temp is None or temp <= 0:
        return min_pwm

    if curve_points and len(curve_points) >= 2:
        pts = sorted(curve_points, key=lambda x: x[0])
        if temp <= pts[0][0]:
            pct = pts[0][1]
        elif temp >= pts[-1][0]:
            pct = pts[-1][1]
        else:
            pct = pts[0][1]
            for i in range(len(pts)-1):
                t1, p1 = pts[i]
                t2, p2 = pts[i+1]
                if t1 <= temp <= t2:
                    span = max(1, t2 - t1)
                    ratio = (temp - t1) / float(span)
                    pct = p1 + ratio * (p2 - p1)
                    break
        val = int((pct / 100.0) * max_pwm)
        return max(0, min(max_pwm, val))

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

def set_fan_pwm(profile, manual_pct=60, custom_pwms=None, ctrl_cpu_fan=False):
    hw = _find_hwmon()
    if not hw:
        return False

    applied = 0
    available_pwms = sorted(glob.glob(os.path.join(hw, "pwm[1-9]")))

    if custom_pwms:
        targets = {}
        for p in available_pwms:
            key = os.path.basename(p)
            if key == "pwm3" and not ctrl_cpu_fan:
                continue
            targets[p] = custom_pwms.get(key, 67)
    else:
        pct_map = {"quiet": 67, "balanced": 120, "performance": 155, "full": 183}
        raw = pct_map.get(profile, int((manual_pct / 100.0) * 183))
        raw = max(58, min(183, raw))
        targets = {p: raw for p in available_pwms if not (os.path.basename(p) == "pwm3" and not ctrl_cpu_fan)}

    pwm3_enable_file = os.path.join(hw, "pwm3_enable")
    if os.path.exists(pwm3_enable_file):
        try:
            with open(pwm3_enable_file, "w") as f:
                f.write("1\n" if ctrl_cpu_fan else "2\n")
        except Exception as e:
            logger.debug(f"Silenced exception: {e}")

    for path, val in targets.items():
        if os.path.exists(path):
            try:
                with open(path, "w") as f:
                    f.write(f"{val}\n")
                applied += 1
            except Exception as e:
                logger.debug(f"Silenced exception: {e}")

    return applied > 0

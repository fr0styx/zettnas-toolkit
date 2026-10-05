import glob
import os

from backend.config import HOST_PROC, HOST_SYS
from backend.state import Z_STATE


def read_cpu_util():
    try:
        with open(os.path.join(HOST_PROC, "stat")) as f:
            parts = f.readline().split()[1:]
        vals = list(map(int, parts))
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        d_idle = idle - Z_STATE.prev["idle"]
        d_total = total - Z_STATE.prev["total"]
        Z_STATE.prev["idle"], Z_STATE.prev["total"] = idle, total
        if d_total <= 0:
            return 0
        return round(100 * (1 - d_idle / d_total))
    except Exception:
        return 0


def _find_hwmon():
    if Z_STATE.cached_hwmon and os.path.exists(Z_STATE.cached_hwmon):
        return Z_STATE.cached_hwmon
    for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
        try:
            with open(os.path.join(h, "name")) as f:
                n = f.read().strip()
                if n in ("zettlab_d8_fans", "zettos_pwm_fan", "nct6775", "it87"):
                    Z_STATE.cached_hwmon = h
                    return h
        except Exception:
            continue
    for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
        if glob.glob(os.path.join(h, "pwm*")):
            Z_STATE.cached_hwmon = h
            return h
    return None


def read_cpu_temp():
    if Z_STATE.cached_cpu_temp_path and os.path.exists(Z_STATE.cached_cpu_temp_path):
        try:
            val = int(open(Z_STATE.cached_cpu_temp_path).read().strip() or 0) / 1000
            if val > 0:
                return round(val)
        except Exception:
            Z_STATE.cached_cpu_temp_path = None

    for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
        try:
            name = open(os.path.join(h, "name")).read().strip()
            if name in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
                for t in sorted(glob.glob(os.path.join(h, "temp*_input"))):
                    val = int(open(t).read().strip() or 0) / 1000
                    if val > 0:
                        Z_STATE.cached_cpu_temp_path = t
                        return round(val)
        except Exception:
            continue
    return 0

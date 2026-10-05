import os
from backend.config import HOST_PROC

def read_mem():
    info = {}
    try:
        with open(os.path.join(HOST_PROC, "meminfo")) as f:
            for line in f:
                k, v = line.split(":")
                info[k.strip()] = int(v.split()[0])
        total = info.get("MemTotal", 0) / 1024 / 1024
        avail = info.get("MemAvailable", 0) / 1024 / 1024
        used = total - avail
        pct = round(100 * used / total) if total else 0
        return {"used_gb": round(used, 1), "total_gb": round(total, 1), "pct": pct}
    except Exception:
        return {"used_gb": 0, "total_gb": 0, "pct": 0}

import logging
import os

from backend.config import HOST_PROC

logger = logging.getLogger("ZettNAS")


def read_mem():
    info = {}
    try:
        with open(os.path.join(HOST_PROC, "meminfo")) as f:
            for line in f:
                k, v = line.split(":")
                info[k.strip()] = int(v.split()[0])
        total = info.get("MemTotal", 0) / 1024 / 1024
        avail = info.get("MemAvailable", 0) / 1024 / 1024

        # Reclaimable ZFS ARC cache accounting
        arc_bytes = 0
        arc_path = os.path.join(HOST_PROC, "spl/kstat/zfs/arcstats")
        if os.path.exists(arc_path):
            try:
                with open(arc_path) as af:
                    for aline in af:
                        parts = aline.split()
                        if len(parts) >= 3 and parts[0] == "size":
                            arc_bytes = int(parts[2])
                            break
            except Exception:
                logger.debug("backend.hardware.memory.read_mem: ignored error", exc_info=True)
        arc_gb = arc_bytes / (1024 * 1024 * 1024)
        effective_avail = min(total, avail + arc_gb)
        used = max(0.0, total - effective_avail)
        pct = round(100 * used / total) if total else 0
        return {"used_gb": round(used, 1), "total_gb": round(total, 1), "pct": pct}
    except Exception:
        return {"used_gb": 0, "total_gb": 0, "pct": 0}

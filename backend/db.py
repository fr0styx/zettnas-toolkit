import json
import os
import sqlite3
import time

from backend.config import DB_PATH, logger


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    try:
        with get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    ts INTEGER PRIMARY KEY,
                    cpu_temp REAL,
                    cpu_util REAL,
                    mem_pct REAL,
                    disks_json TEXT,
                    fans_json TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS copy_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER,
                    source TEXT,
                    dest TEXT,
                    files_count INTEGER,
                    total_bytes INTEGER,
                    status TEXT,
                    checksum_verified INTEGER DEFAULT 0,
                    duration_sec REAL DEFAULT 0.0,
                    error TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_copy_history_ts ON copy_history(ts DESC)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS smart_history (
                    ts INTEGER NOT NULL,
                    dev TEXT NOT NULL,
                    temp REAL,
                    reallocated_sectors INTEGER DEFAULT 0,
                    pending_sectors INTEGER DEFAULT 0,
                    offline_uncorrectable INTEGER DEFAULT 0,
                    crc_errors INTEGER DEFAULT 0,
                    nvme_pct_used INTEGER DEFAULT 0,
                    nvme_media_errors INTEGER DEFAULT 0,
                    PRIMARY KEY (ts, dev)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_smart_history_dev_ts ON smart_history(dev, ts DESC)")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")


def log_metrics(ts: int, cpu_temp: float, cpu_util: float, mem_pct: float, disks: list, fans: list):
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO metrics (ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, cpu_temp, cpu_util, mem_pct, json.dumps(disks), json.dumps(fans)),
            )
            # Prune records older than 30 days (2,592,000 seconds)
            conn.execute("DELETE FROM metrics WHERE ts < ?", (ts - 2592000,))
    except Exception as db_e:
        logger.info(f"[ZettNAS] DB Log Error: {db_e}")


def query_history(range_str: str = "24h"):
    now_ts = int(time.time())

    if range_str == "1h":
        cutoff = now_ts - 3600
        group_sql = (
            "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? ORDER BY ts ASC"
        )
    elif range_str == "6h":
        cutoff = now_ts - 21600
        group_sql = (
            "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? ORDER BY ts ASC"
        )
    elif range_str == "7d":
        cutoff = now_ts - (86400 * 7)
        # Downsample to 30-minute buckets for 7-day range to keep payload fast and preserve accuracy
        group_sql = "SELECT (ts / 1800) * 1800 AS ts, ROUND(AVG(cpu_temp), 1) AS cpu_temp, ROUND(AVG(cpu_util), 1) AS cpu_util, ROUND(AVG(mem_pct), 1) AS mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? GROUP BY (ts / 1800) ORDER BY ts ASC"
    elif range_str == "30d":
        cutoff = now_ts - (86400 * 30)
        # Downsample to 2-hour buckets for 30-day range
        group_sql = "SELECT (ts / 7200) * 7200 AS ts, ROUND(AVG(cpu_temp), 1) AS cpu_temp, ROUND(AVG(cpu_util), 1) AS cpu_util, ROUND(AVG(mem_pct), 1) AS mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? GROUP BY (ts / 7200) ORDER BY ts ASC"
    else:  # default 24h
        cutoff = now_ts - 86400
        group_sql = (
            "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? ORDER BY ts ASC"
        )

    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(group_sql, (cutoff,)).fetchall()
        data = []
        for r in rows:
            disks = []
            if "disks_json" in r.keys() and r["disks_json"]:
                try:
                    disks = json.loads(r["disks_json"])
                except Exception:
                    disks = []

            fans = []
            if "fans_json" in r.keys() and r["fans_json"]:
                try:
                    fans = json.loads(r["fans_json"])
                except Exception:
                    fans = []

            data.append(
                {
                    "ts": r["ts"],
                    "cpu_temp": round(r["cpu_temp"], 1) if r["cpu_temp"] else 0,
                    "cpu_util": round(r["cpu_util"], 1) if r["cpu_util"] else 0,
                    "mem_pct": round(r["mem_pct"], 1) if r["mem_pct"] else 0,
                    "disks": disks,
                    "fans": fans,
                }
            )
        return data


def log_copy_event(
    ts: int,
    source: str,
    dest: str,
    files_count: int,
    total_bytes: int,
    status: str,
    checksum_verified: bool = False,
    duration_sec: float = 0.0,
    error: str = "",
):
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO copy_history (ts, source, dest, files_count, total_bytes, status, checksum_verified, duration_sec, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    source,
                    dest,
                    files_count,
                    total_bytes,
                    status,
                    1 if checksum_verified else 0,
                    round(duration_sec, 2),
                    str(error or ""),
                ),
            )
            # Prune old records past 500 entries
            conn.execute(
                """
                DELETE FROM copy_history WHERE id NOT IN (
                    SELECT id FROM copy_history ORDER BY ts DESC LIMIT 500
                )
                """
            )
    except Exception as db_e:
        logger.info(f"[ZettNAS] DB Copy Log Error: {db_e}")


def query_copy_history(limit: int = 50):
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, ts, source, dest, files_count, total_bytes, status, checksum_verified, duration_sec, error
                FROM copy_history
                ORDER BY ts DESC
                LIMIT ?
                """,
                (max(1, min(200, limit)),),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "source": r["source"],
                    "dest": r["dest"],
                    "files_count": r["files_count"],
                    "total_bytes": r["total_bytes"],
                    "status": r["status"],
                    "checksum_verified": bool(r["checksum_verified"]),
                    "duration_sec": r["duration_sec"],
                    "error": r["error"],
                }
                for r in rows
            ]
    except Exception as db_e:
        logger.info(f"[ZettNAS] DB Query Copy History Error: {db_e}")
        return []


def log_smart_metrics(ts: int, dev: str, temp: float | None, metrics: dict):
    """Logs disk SMART health metrics into SQLite and prunes entries older than 90 days."""
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO smart_history (
                    ts, dev, temp, reallocated_sectors, pending_sectors,
                    offline_uncorrectable, crc_errors, nvme_pct_used, nvme_media_errors
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    dev,
                    round(temp, 1) if temp is not None else None,
                    metrics.get("realloc", 0) or 0,
                    metrics.get("pending", 0) or 0,
                    metrics.get("offline", 0) or 0,
                    metrics.get("crc", 0) or 0,
                    metrics.get("nvme_used", 0) or 0,
                    metrics.get("nvme_media_err", 0) or 0,
                ),
            )
            # Prune records older than 90 days (7,776,000 seconds)
            conn.execute("DELETE FROM smart_history WHERE ts < ?", (ts - 7776000,))
    except Exception as db_e:
        logger.info(f"[ZettNAS] DB Log SMART History Error: {db_e}")


def query_smart_velocity(dev: str) -> dict:
    """
    Predictive SMART degradation engine:
    Computes rate-of-change velocity over 7-day and 30-day sliding windows.
    Detects shedding sectors, stuck pending sectors, and wear acceleration.
    """
    now_ts = int(time.time())
    ts_7d = now_ts - (7 * 86400)
    ts_30d = now_ts - (30 * 86400)
    ts_48h = now_ts - (2 * 86400)

    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            # Latest reading
            latest = conn.execute(
                "SELECT * FROM smart_history WHERE dev = ? ORDER BY ts DESC LIMIT 1",
                (dev,),
            ).fetchone()

            if not latest:
                return {
                    "dev": dev,
                    "status": "insufficient_data",
                    "shedding_sectors": False,
                    "stuck_pending": False,
                    "realloc_current": 0,
                    "realloc_7d_delta": 0,
                    "realloc_30d_delta": 0,
                    "recommendation": "Collecting baseline telemetry",
                }

            # Baseline 7 days ago
            rec_7d = conn.execute(
                "SELECT * FROM smart_history WHERE dev = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                (dev, ts_7d),
            ).fetchone()

            # Baseline 30 days ago
            rec_30d = conn.execute(
                "SELECT * FROM smart_history WHERE dev = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                (dev, ts_30d),
            ).fetchone()

            # Check for stuck pending sectors over past 48h
            pending_48h_rows = conn.execute(
                "SELECT pending_sectors FROM smart_history WHERE dev = ? AND ts >= ? ORDER BY ts ASC",
                (dev, ts_48h),
            ).fetchall()
            stuck_pending = len(pending_48h_rows) >= 2 and all(r["pending_sectors"] > 0 for r in pending_48h_rows)

            curr_realloc = latest["reallocated_sectors"] or 0
            base_realloc_7d = rec_7d["reallocated_sectors"] if rec_7d else curr_realloc
            base_realloc_30d = rec_30d["reallocated_sectors"] if rec_30d else curr_realloc

            delta_7d = max(0, curr_realloc - base_realloc_7d)
            delta_30d = max(0, curr_realloc - base_realloc_30d)

            shedding = delta_7d >= 2
            status = "healthy"
            rec_text = "Drive health metrics are stable within expected thresholds."

            if shedding:
                status = "critical"
                rec_text = f"Active sector shedding detected: {delta_7d} reallocated sectors in the last 7 days. Plan disk replacement soon."
            elif stuck_pending:
                status = "warning"
                rec_text = "Pending sectors detected for over 48 hours without sector reallocation. Run an extended SMART test to force relocation."
            elif delta_30d > 0:
                status = "monitor"
                rec_text = f"Minor degradation velocity: {delta_30d} reallocated sectors over 30 days. Monitor SMART trends closely."
            elif (latest["reallocated_sectors"] or 0) > 0:
                status = "monitor"
                rec_text = f"Drive has {latest['reallocated_sectors']} historical reallocated sectors, but velocity is zero over the last 30 days."

            return {
                "dev": dev,
                "status": status,
                "shedding_sectors": shedding,
                "stuck_pending": stuck_pending,
                "realloc_current": curr_realloc,
                "realloc_7d_delta": delta_7d,
                "realloc_30d_delta": delta_30d,
                "recommendation": rec_text,
            }
    except Exception as db_e:
        logger.info(f"[ZettNAS] DB Query SMART Velocity Error: {db_e}")
        return {
            "dev": dev,
            "status": "unknown",
            "shedding_sectors": False,
            "stuck_pending": False,
            "realloc_current": 0,
            "realloc_7d_delta": 0,
            "realloc_30d_delta": 0,
            "recommendation": "Unable to calculate velocity",
        }


def query_all_smart_velocities() -> dict:
    """Returns degradation velocity assessment for all disks with recorded history."""
    out = {}
    try:
        with get_db_connection() as conn:
            devs = [r[0] for r in conn.execute("SELECT DISTINCT dev FROM smart_history").fetchall()]
        for d in devs:
            out[d] = query_smart_velocity(d)
    except Exception as e:
        logger.debug(f"[ZettNAS] Failed to query all velocities: {e}")
    return out

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
        group_sql = "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? ORDER BY ts ASC"
    elif range_str == "6h":
        cutoff = now_ts - 21600
        group_sql = "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? ORDER BY ts ASC"
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
        group_sql = "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? ORDER BY ts ASC"

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

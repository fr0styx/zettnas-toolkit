import os
import time
import json
import sqlite3
from backend.config import logger, DB_PATH

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    try:
        with sqlite3.connect(DB_PATH) as conn:
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
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

def log_metrics(ts: int, cpu_temp: float, cpu_util: float, mem_pct: float, disks: list, fans: list):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO metrics (ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, cpu_temp, cpu_util, mem_pct, json.dumps(disks), json.dumps(fans))
            )
            # Prune records older than 30 days (2,592,000 seconds)
            conn.execute("DELETE FROM metrics WHERE ts < ?", (ts - 2592000,))
    except Exception as db_e:
        logger.info(f"[ZettNAS] DB Log Error: {db_e}")

def query_history(range_str: str = "24h"):
    now_ts = int(time.time())

    if range_str == "7d":
        cutoff = now_ts - (86400 * 7)
        group_sql = "SELECT CAST(strftime('%s', strftime('%Y-%m-%d %H:00:00', datetime(ts, 'unixepoch', 'localtime'))) AS INTEGER) as ts, avg(cpu_temp) as cpu_temp, avg(cpu_util) as cpu_util, avg(mem_pct) as mem_pct FROM metrics WHERE ts > ? GROUP BY strftime('%Y-%m-%d %H:00:00', datetime(ts, 'unixepoch', 'localtime')) ORDER BY ts ASC"
    elif range_str == "30d":
        cutoff = now_ts - (86400 * 30)
        group_sql = "SELECT CAST(strftime('%s', strftime('%Y-%m-%d 00:00:00', datetime(ts, 'unixepoch', 'localtime'))) AS INTEGER) as ts, avg(cpu_temp) as cpu_temp, avg(cpu_util) as cpu_util, avg(mem_pct) as mem_pct FROM metrics WHERE ts > ? GROUP BY strftime('%Y-%m-%d 00:00:00', datetime(ts, 'unixepoch', 'localtime')) ORDER BY ts ASC"
    else:  # default 24h
        cutoff = now_ts - 86400
        group_sql = "SELECT ts, cpu_temp, cpu_util, mem_pct FROM metrics WHERE ts > ? ORDER BY ts ASC"

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(group_sql, (cutoff,)).fetchall()
        data = []
        for r in rows:
            data.append({
                "ts": r["ts"],
                "cpu_temp": round(r["cpu_temp"], 1) if r["cpu_temp"] else 0,
                "cpu_util": round(r["cpu_util"], 1) if r["cpu_util"] else 0,
                "mem_pct": round(r["mem_pct"], 1) if r["mem_pct"] else 0,
                "disks": [],
                "fans": []
            })
        return data

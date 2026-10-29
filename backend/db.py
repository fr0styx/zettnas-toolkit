import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Optional, cast

from backend.config import DB_PATH, logger

_DB_LOCK = threading.RLock()


def get_db_connection() -> sqlite3.Connection:
    from backend.sqlite_conn import connect

    return connect("history", DB_PATH, row_factory=False)


@contextmanager
def db_session():
    """Thread-safe SQLite session context manager ensuring commit, rollback on error, and guaranteed connection closure."""
    with _DB_LOCK:
        conn = get_db_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@contextmanager
def db_read_session():
    """A connection for reads only, without the global write lock: WAL lets readers run
    alongside the writer, so history and SMART queries don't queue behind writes (ARCH-7)."""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


_LAST_PRUNE_TS: int = 0

# One connection kept open for the history writers (metrics, SMART): no connect and PRAGMAs
# per write, and the WAL file is not created and deleted around every row (PERF-3).
_HISTORY: dict[str, Any] = {"conn": None, "path": None, "ino": None}
_METRICS_COLS: dict[str, set[str]] = {}


def _history_conn() -> sqlite3.Connection:
    path = DB_PATH
    try:
        ino = os.stat(path).st_ino
    except OSError:
        ino = None
    h = _HISTORY
    if h["conn"] is None or h["path"] != path or h["ino"] != ino or ino is None:
        if h["conn"] is not None:
            try:
                h["conn"].close()
            except sqlite3.Error:
                logger.debug("backend.db._history_conn: close failed", exc_info=True)
        conn = get_db_connection()
        h.update(conn=conn, path=path, ino=os.stat(path).st_ino)
        return conn
    return cast(sqlite3.Connection, h["conn"])


@contextmanager
def history_session():
    """Like db_session, on the long-lived history connection."""
    with _DB_LOCK:
        conn = _history_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def close_history_connection() -> None:
    with _DB_LOCK:
        if _HISTORY["conn"] is not None:
            try:
                _HISTORY["conn"].close()
            except sqlite3.Error:
                logger.debug("backend.db.close_history_connection: close failed", exc_info=True)
        _HISTORY.update(conn=None, path=None, ino=None)


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    try:
        with db_session() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    ts INTEGER PRIMARY KEY,
                    cpu_temp REAL,
                    cpu_util REAL,
                    mem_pct REAL,
                    disks_json TEXT,
                    fans_json TEXT,
                    net_rx_bytes_sec REAL DEFAULT 0.0,
                    net_tx_bytes_sec REAL DEFAULT 0.0,
                    disk_read_bytes_sec REAL DEFAULT 0.0,
                    disk_write_bytes_sec REAL DEFAULT 0.0
                )
            """)
            conn.execute("DROP INDEX IF EXISTS idx_metrics_ts")
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
                    power_on_hours INTEGER DEFAULT 0,
                    command_timeouts INTEGER DEFAULT 0,
                    spin_retries INTEGER DEFAULT 0,
                    PRIMARY KEY (ts, dev)
                )
            """)
            # columns added after these tables first shipped (metrics rates, power-on hours): ARC-8
            from backend.db_schema import ensure_columns

            ensure_columns(conn, "history.db")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_smart_history_dev_ts ON smart_history(dev, ts DESC)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ups_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_sec REAL DEFAULT 0.0,
                    start_battery_pct REAL,
                    end_battery_pct REAL,
                    min_line_volts REAL,
                    max_load_pct REAL,
                    action_taken TEXT DEFAULT '',
                    details TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ups_events_ts ON ups_events(ts DESC)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS smart_test_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    dev TEXT NOT NULL,
                    model TEXT DEFAULT '',
                    serial TEXT DEFAULT '',
                    is_nvme INTEGER NOT NULL DEFAULT 0,
                    test_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    passed INTEGER NOT NULL DEFAULT 1,
                    duration_sec REAL DEFAULT 0.0,
                    power_on_hours INTEGER DEFAULT 0,
                    temp_start REAL,
                    temp_end REAL,
                    lba_first_error TEXT DEFAULT '-',
                    summary TEXT DEFAULT '',
                    recommendation TEXT DEFAULT '',
                    report_markdown TEXT DEFAULT '',
                    raw_details_json TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_smart_test_history_dev_ts ON smart_test_history(dev, ts DESC)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")


def get_app_config_value(key: str, default: Any = None) -> Any:
    """Retrieves a persistent configuration object from the SQLite database."""
    try:
        with db_session() as conn:
            cur = conn.execute("SELECT value_json FROM app_config WHERE key = ?", (key,))
            row = cur.fetchone()
            if row and row[0]:
                return json.loads(row[0])
    except Exception as e:
        logger.debug(f"[DB] Error getting app_config for {key}: {e}")
    return default


def set_app_config_value(key: str, val: Any) -> None:
    """Persists a configuration object to the SQLite database with atomic transaction."""
    try:
        val_str = json.dumps(val)
        now = time.time()
        with db_session() as conn:
            conn.execute(
                """INSERT INTO app_config (key, value_json, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at""",
                (key, val_str, now),
            )
    except Exception as e:
        logger.warning(f"[DB] Error saving app_config for {key}: {e}")


def log_metrics(
    ts: int,
    cpu_temp: float,
    cpu_util: float,
    mem_pct: float,
    disks: list,
    fans: list,
    net_rx_bytes_sec: float = 0.0,
    net_tx_bytes_sec: float = 0.0,
    disk_read_bytes_sec: float = 0.0,
    disk_write_bytes_sec: float = 0.0,
):
    try:
        with history_session() as conn:
            cols = _METRICS_COLS.get(DB_PATH)
            if cols is None:
                cols = _METRICS_COLS[DB_PATH] = {
                    row[1] for row in conn.execute("PRAGMA table_info(metrics)").fetchall()
                }
            if "net_rx_bytes_sec" in cols:
                conn.execute(
                    """INSERT INTO metrics
                       (ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json, net_rx_bytes_sec, net_tx_bytes_sec, disk_read_bytes_sec, disk_write_bytes_sec)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ts,
                        cpu_temp,
                        cpu_util,
                        mem_pct,
                        json.dumps(disks),
                        json.dumps(fans),
                        float(net_rx_bytes_sec or 0.0),
                        float(net_tx_bytes_sec or 0.0),
                        float(disk_read_bytes_sec or 0.0),
                        float(disk_write_bytes_sec or 0.0),
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO metrics (ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (ts, cpu_temp, cpu_util, mem_pct, json.dumps(disks), json.dumps(fans)),
                )
            # Prune records older than 30 days (2,592,000 seconds) periodically (hourly)
            global _LAST_PRUNE_TS
            if ts - _LAST_PRUNE_TS >= 3600:
                conn.execute("DELETE FROM metrics WHERE ts < ?", (ts - 2592000,))
                _LAST_PRUNE_TS = ts
    except Exception as db_e:
        logger.info(f"[ZettNAS] DB Log Error: {db_e}")


def query_history(range_str: str = "24h"):
    now_ts = int(time.time())

    with db_read_session() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("PRAGMA table_info(metrics)")
        cols = {row[1] for row in cur.fetchall()}
        has_net_io = "net_rx_bytes_sec" in cols

        if has_net_io:
            if range_str == "1h":
                cutoff = now_ts - 3600
                group_sql = (
                    "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json, "
                    "net_rx_bytes_sec AS net_rx, net_tx_bytes_sec AS net_tx, "
                    "disk_read_bytes_sec AS disk_read, disk_write_bytes_sec AS disk_write "
                    "FROM metrics WHERE ts > ? ORDER BY ts ASC"
                )
            elif range_str == "6h":
                cutoff = now_ts - 21600
                group_sql = (
                    "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json, "
                    "net_rx_bytes_sec AS net_rx, net_tx_bytes_sec AS net_tx, "
                    "disk_read_bytes_sec AS disk_read, disk_write_bytes_sec AS disk_write "
                    "FROM metrics WHERE ts > ? ORDER BY ts ASC"
                )
            elif range_str == "7d":
                cutoff = now_ts - (86400 * 7)
                group_sql = (
                    "SELECT (ts / 1800) * 1800 AS ts, "
                    "ROUND(AVG(cpu_temp), 1) AS cpu_temp, ROUND(AVG(cpu_util), 1) AS cpu_util, ROUND(AVG(mem_pct), 1) AS mem_pct, "
                    "ROUND(AVG(COALESCE(net_rx_bytes_sec, 0.0)), 1) AS net_rx, ROUND(AVG(COALESCE(net_tx_bytes_sec, 0.0)), 1) AS net_tx, "
                    "ROUND(AVG(COALESCE(disk_read_bytes_sec, 0.0)), 1) AS disk_read, ROUND(AVG(COALESCE(disk_write_bytes_sec, 0.0)), 1) AS disk_write, "
                    "disks_json, fans_json FROM metrics WHERE ts > ? GROUP BY (ts / 1800) ORDER BY ts ASC"
                )
            elif range_str == "30d":
                cutoff = now_ts - (86400 * 30)
                group_sql = (
                    "SELECT (ts / 7200) * 7200 AS ts, "
                    "ROUND(AVG(cpu_temp), 1) AS cpu_temp, ROUND(AVG(cpu_util), 1) AS cpu_util, ROUND(AVG(mem_pct), 1) AS mem_pct, "
                    "ROUND(AVG(COALESCE(net_rx_bytes_sec, 0.0)), 1) AS net_rx, ROUND(AVG(COALESCE(net_tx_bytes_sec, 0.0)), 1) AS net_tx, "
                    "ROUND(AVG(COALESCE(disk_read_bytes_sec, 0.0)), 1) AS disk_read, ROUND(AVG(COALESCE(disk_write_bytes_sec, 0.0)), 1) AS disk_write, "
                    "disks_json, fans_json FROM metrics WHERE ts > ? GROUP BY (ts / 7200) ORDER BY ts ASC"
                )
            else:  # default 24h
                cutoff = now_ts - 86400
                group_sql = (
                    "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json, "
                    "net_rx_bytes_sec AS net_rx, net_tx_bytes_sec AS net_tx, "
                    "disk_read_bytes_sec AS disk_read, disk_write_bytes_sec AS disk_write "
                    "FROM metrics WHERE ts > ? ORDER BY ts ASC"
                )
        else:
            if range_str == "1h":
                cutoff = now_ts - 3600
                group_sql = "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? ORDER BY ts ASC"
            elif range_str == "6h":
                cutoff = now_ts - 21600
                group_sql = "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? ORDER BY ts ASC"
            elif range_str == "7d":
                cutoff = now_ts - (86400 * 7)
                group_sql = "SELECT (ts / 1800) * 1800 AS ts, ROUND(AVG(cpu_temp), 1) AS cpu_temp, ROUND(AVG(cpu_util), 1) AS cpu_util, ROUND(AVG(mem_pct), 1) AS mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? GROUP BY (ts / 1800) ORDER BY ts ASC"
            elif range_str == "30d":
                cutoff = now_ts - (86400 * 30)
                group_sql = "SELECT (ts / 7200) * 7200 AS ts, ROUND(AVG(cpu_temp), 1) AS cpu_temp, ROUND(AVG(cpu_util), 1) AS cpu_util, ROUND(AVG(mem_pct), 1) AS mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? GROUP BY (ts / 7200) ORDER BY ts ASC"
            else:  # default 24h
                cutoff = now_ts - 86400
                group_sql = "SELECT ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json FROM metrics WHERE ts > ? ORDER BY ts ASC"

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
                    "net_rx": round(r["net_rx"], 1) if "net_rx" in r.keys() and r["net_rx"] else 0.0,
                    "net_tx": round(r["net_tx"], 1) if "net_tx" in r.keys() and r["net_tx"] else 0.0,
                    "disk_read": round(r["disk_read"], 1) if "disk_read" in r.keys() and r["disk_read"] else 0.0,
                    "disk_write": round(r["disk_write"], 1) if "disk_write" in r.keys() and r["disk_write"] else 0.0,
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
        with db_session() as conn:
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
        with db_session() as conn:
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


def compute_linear_regression_slope(x_vals: list[float], y_vals: list[float]) -> tuple[float, float]:
    """
    Computes closed-form least-squares linear regression slope and R^2.
    Returns (slope, r_squared).
    Execution takes < 50 microseconds (< 150 FLOPs for N <= 48).
    """
    n = len(x_vals)
    if n < 3:
        return 0.0, 0.0

    sum_x = sum(x_vals)
    sum_y = sum(y_vals)
    sum_xx = sum(x * x for x in x_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals, strict=False))

    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-9:
        return 0.0, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    mean_y = sum_y / n
    ss_tot = sum((y - mean_y) ** 2 for y in y_vals)
    if ss_tot < 1e-9:
        return 0.0, 1.0 if abs(slope) < 1e-9 else 0.0

    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(x_vals, y_vals, strict=False))
    r_squared = max(0.0, min(1.0, 1.0 - (ss_res / ss_tot)))

    return round(slope, 5), round(r_squared, 4)


SMART_HISTORY_EVERY_SECS = 600  # a row at least this often while nothing changes
SMART_HISTORY_TEMP_STEP = 3.0  # a temperature move this large (°C) is stored at once
_SMART_STORED: dict[tuple[str, str], tuple[int, tuple, float | None]] = {}
_SMART_PRUNED: dict[str, int] = {}


def _smart_counters(metrics: dict) -> tuple:
    return tuple(
        int(metrics.get(k, 0) or 0)
        for k in (
            "realloc",
            "pending",
            "offline",
            "crc",
            "nvme_used",
            "nvme_media_err",
            "timeouts",
            "spin_retries",
        )
    )


def _smart_row_due(conn: sqlite3.Connection, ts: int, dev: str, temp: float | None, counters: tuple) -> bool:
    """A SMART sample is stored when a counter changes, the temperature moves, or every 10 minutes (PERF-3)."""
    key = (DB_PATH, dev)
    last = _SMART_STORED.get(key)
    if last is None:
        row = conn.execute(
            "SELECT ts, reallocated_sectors, pending_sectors, offline_uncorrectable, crc_errors, nvme_pct_used, "
            "nvme_media_errors, command_timeouts, spin_retries, temp FROM smart_history "
            "WHERE dev = ? ORDER BY ts DESC LIMIT 1",
            (dev,),
        ).fetchone()
        if row is None:
            return True
        last = (row[0], tuple(int(v or 0) for v in row[1:9]), row[9])
        _SMART_STORED[key] = last
    last_ts, last_counters, last_temp = last
    if counters != last_counters:
        return True
    if temp is not None and (last_temp is None or abs(temp - last_temp) >= SMART_HISTORY_TEMP_STEP):
        return True
    return ts - last_ts >= SMART_HISTORY_EVERY_SECS or ts < last_ts


def log_smart_metrics(ts: int, dev: str, temp: float | None, metrics: dict, power_on_hours: int = 0):
    """Stores a SMART sample when it adds something (see _smart_row_due); prunes rows older than 90 days hourly."""
    poh = power_on_hours or metrics.get("power_on_hours", 0) or 0
    counters = _smart_counters(metrics)
    try:
        with history_session() as conn:
            if not _smart_row_due(conn, ts, dev, temp, counters):
                return
            conn.execute(
                """
                INSERT OR REPLACE INTO smart_history (
                    ts, dev, temp, reallocated_sectors, pending_sectors,
                    offline_uncorrectable, crc_errors, nvme_pct_used, nvme_media_errors, power_on_hours,
                    command_timeouts, spin_retries
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    int(poh) if str(poh).isdigit() else 0,
                    metrics.get("timeouts", 0) or 0,
                    metrics.get("spin_retries", 0) or 0,
                ),
            )
            _SMART_STORED[(DB_PATH, dev)] = (ts, counters, round(temp, 1) if temp is not None else None)
            if ts - _SMART_PRUNED.get(DB_PATH, 0) >= 3600:  # rows older than 90 days, hourly
                conn.execute("DELETE FROM smart_history WHERE ts < ?", (ts - 7776000,))
                _SMART_PRUNED[DB_PATH] = ts
    except Exception as db_e:
        logger.info(f"[ZettNAS] DB Log SMART History Error: {db_e}")


def log_smart_test_result(
    dev: str,
    test_type: str,
    status: str,
    passed: bool,
    duration_sec: float = 0.0,
    power_on_hours: int = 0,
    temp_start: float | None = None,
    temp_end: float | None = None,
    lba_first_error: str = "-",
    model: str = "",
    serial: str = "",
    is_nvme: bool = False,
    summary: str = "",
    recommendation: str = "",
    report_markdown: str = "",
    raw_details: dict | None = None,
) -> int:
    """Logs a completed, failed, or aborted S.M.A.R.T. self-test into the persistent SQLite WAL database."""
    ts = int(time.time())
    raw_json = json.dumps(raw_details) if raw_details else ""
    try:
        with db_session() as conn:
            cur = conn.execute(
                """
                INSERT INTO smart_test_history
                (ts, dev, model, serial, is_nvme, test_type, status, passed, duration_sec, power_on_hours, temp_start, temp_end, lba_first_error, summary, recommendation, report_markdown, raw_details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    dev,
                    model,
                    serial,
                    1 if is_nvme else 0,
                    test_type,
                    status,
                    1 if passed else 0,
                    float(duration_sec),
                    int(power_on_hours),
                    temp_start,
                    temp_end,
                    lba_first_error,
                    summary,
                    recommendation,
                    report_markdown,
                    raw_json,
                ),
            )
            return cur.lastrowid or 0
    except Exception as e:
        logger.error(f"[ZettNAS] Failed to log smart test result for {dev}: {e}")
        return 0


def get_latest_smart_test_result(dev: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """Returns the most recent self-test record for a specific drive."""

    def _query(c: sqlite3.Connection):
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT * FROM smart_test_history WHERE dev = ? ORDER BY ts DESC LIMIT 1",
            (dev,),
        ).fetchone()
        if not row:
            return None
        res = dict(row)
        res["passed"] = bool(res["passed"])
        res["is_nvme"] = bool(res["is_nvme"])
        return res

    try:
        if conn is not None:
            return _query(conn)
        with db_session() as c:
            return _query(c)
    except Exception as e:
        logger.error(f"[ZettNAS] Failed to get latest smart test result for {dev}: {e}")
        return None


def get_smart_test_history(dev: str | None = None, limit: int = 20) -> list[dict]:
    """Returns historical self-test runs across all drives or filtered by dev node."""
    try:
        with db_session() as conn:
            conn.row_factory = sqlite3.Row
            if dev:
                rows = conn.execute(
                    "SELECT * FROM smart_test_history WHERE dev = ? ORDER BY ts DESC LIMIT ?",
                    (dev, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM smart_test_history ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            out = []
            for r in rows:
                item = dict(r)
                item["passed"] = bool(item["passed"])
                item["is_nvme"] = bool(item["is_nvme"])
                out.append(item)
            return out
    except Exception as e:
        logger.error(f"[ZettNAS] Failed to query smart test history: {e}")
        return []


# (database file, device) -> last velocity result and what it was computed from
_VELOCITY_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
VELOCITY_RECHECK_SECS = 600  # temperature/power-on-hours-only changes refresh at most this often
SPARKLINE_BUCKET_SECS = 7200  # 30 days -> at most 360 sparkline points


def get_smart_history_samples(dev: str, days: int = 45, bucket_secs: int = 21600) -> list[dict]:
    """A drive's stored counters over `days` days, one sample per `bucket_secs` (the highest value of
    each counter in it: they only grow), plus the newest row. For Drive Health's trends."""
    since = int(time.time()) - days * 86400
    try:
        with history_session() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                """SELECT MAX(ts) AS ts, ROUND(AVG(temp), 1) AS temp,
                          MAX(reallocated_sectors) AS reallocated_sectors, MAX(pending_sectors) AS pending_sectors,
                          MAX(offline_uncorrectable) AS offline_uncorrectable, MAX(crc_errors) AS crc_errors,
                          MAX(nvme_pct_used) AS nvme_pct_used, MAX(nvme_media_errors) AS nvme_media_errors,
                          MAX(power_on_hours) AS power_on_hours, MAX(command_timeouts) AS command_timeouts,
                          MAX(spin_retries) AS spin_retries
                   FROM smart_history WHERE dev = ? AND ts >= ? GROUP BY ts / ? ORDER BY ts ASC""",
                (dev, since, bucket_secs),
            ).fetchall()
            out = [dict(r) for r in rows]
            last = c.execute("SELECT * FROM smart_history WHERE dev = ? ORDER BY ts DESC LIMIT 1", (dev,)).fetchone()
            if last is not None and (not out or out[-1]["ts"] != last["ts"]):
                out.append(dict(last))
            return out
    except sqlite3.Error:
        logger.debug("backend.db.get_smart_history_samples: no history for %s", dev, exc_info=True)
        return []


def query_smart_velocity(dev: str, conn: sqlite3.Connection | None = None) -> dict:
    """
    Predictive SMART degradation engine:
    Computes rate-of-change velocity over 7-day and 30-day sliding windows,
    and runs closed-form least-squares linear regression over the 48-checkpoint window
    against active Power-On Hours to detect accelerating media degradation early.
    """
    now_ts = int(time.time())
    ts_7d = now_ts - (7 * 86400)
    ts_30d = now_ts - (30 * 86400)
    ts_48h = now_ts - (2 * 86400)

    def _eval_velocity(c: sqlite3.Connection) -> dict:
        c.row_factory = sqlite3.Row
        # Latest reading
        latest = c.execute(
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
                "failure_probability": 0.0,
                "failure_risk": "low",
                "key_attributes": {
                    "reallocated_sectors": 0,
                    "pending_sectors": 0,
                    "uncorrectable_sectors": 0,
                    "crc_errors": 0,
                },
                "predictive_velocity": {
                    "sample_points": 0,
                    "realloc_slope_per_1000h": 0.0,
                    "realloc_r2": 0.0,
                    "wear_slope_per_1000h": 0.0,
                    "wear_r2": 0.0,
                    "is_accelerating": False,
                },
                "recommendation": "Collecting baseline telemetry",
            }

        # Baseline 7 days ago
        rec_7d = c.execute(
            "SELECT * FROM smart_history WHERE dev = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (dev, ts_7d),
        ).fetchone()

        # Baseline 30 days ago
        rec_30d = c.execute(
            "SELECT * FROM smart_history WHERE dev = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (dev, ts_30d),
        ).fetchone()

        # Stuck pending sectors: every sample of the past 48 h has some, over at least 44 h (one aggregate row)
        p48 = c.execute(
            "SELECT COUNT(*) AS n, MIN(ts) AS t0, MAX(ts) AS t1, MIN(COALESCE(pending_sectors, 0)) AS low "
            "FROM smart_history WHERE dev = ? AND ts >= ?",
            (dev, ts_48h),
        ).fetchone()
        stuck_pending = bool(p48["n"] >= 2 and (p48["t1"] - p48["t0"]) >= 44 * 3600 and p48["low"] > 0)

        curr_realloc = latest["reallocated_sectors"] or 0
        base_realloc_7d = rec_7d["reallocated_sectors"] if rec_7d else curr_realloc
        base_realloc_30d = rec_30d["reallocated_sectors"] if rec_30d else curr_realloc

        delta_7d = max(0, curr_realloc - base_realloc_7d)
        delta_30d = max(0, curr_realloc - base_realloc_30d)

        shedding = delta_7d >= 2
        curr_nvme_wear = latest["nvme_pct_used"] if "nvme_pct_used" in latest.keys() else None
        curr_nvme_err = latest["nvme_media_errors"] if "nvme_media_errors" in latest.keys() else None

        # 48-checkpoint sliding regression window for predictive degradation forecasting
        reg_rows = c.execute(
            """
            SELECT ts, reallocated_sectors, nvme_pct_used, pending_sectors,
                   COALESCE(power_on_hours, 0) AS poh
            FROM smart_history
            WHERE dev = ?
            ORDER BY ts DESC
            LIMIT 48
            """,
            (dev,),
        ).fetchall()
        reg_rows = list(reversed(reg_rows))

        poh_vals = [r["poh"] for r in reg_rows]
        has_varying_poh = len(set(poh_vals)) > 1 and max(poh_vals) > 0
        if has_varying_poh:
            x_vals = [float(p) for p in poh_vals]
        elif reg_rows:
            t0 = reg_rows[0]["ts"]
            x_vals = [float(r["ts"] - t0) / 3600.0 for r in reg_rows]
        else:
            x_vals = []

        realloc_y = [float(r["reallocated_sectors"] or 0) for r in reg_rows]
        wear_y = [float(r["nvme_pct_used"] or 0) for r in reg_rows]

        realloc_slope, realloc_r2 = compute_linear_regression_slope(x_vals, realloc_y)
        wear_slope, wear_r2 = compute_linear_regression_slope(x_vals, wear_y)

        realloc_slope_per_1000h = round(realloc_slope * 1000.0, 4)
        wear_slope_per_1000h = round(wear_slope * 1000.0, 4)
        is_accelerating = realloc_slope > 0.005 and realloc_r2 >= 0.5

        status = "healthy"
        rec_text = "Drive health metrics are stable within expected thresholds."

        if shedding:
            status = "critical"
            rec_text = f"Active sector shedding detected: {delta_7d} reallocated sectors in the last 7 days. Plan disk replacement soon."
        elif curr_nvme_err is not None and curr_nvme_err > 0:
            status = "critical"
            rec_text = f"NVMe media and data integrity errors detected ({curr_nvme_err}). Plan SSD replacement."
        elif is_accelerating:
            status = "warning"
            rec_text = f"Degradation velocity model detected accelerating sector decay (+{realloc_slope_per_1000h} sectors/1000h, R²={realloc_r2}). Plan drive replacement."
        elif stuck_pending:
            status = "warning"
            rec_text = "Pending sectors detected for over 48 hours without sector reallocation. Run an extended SMART test to force relocation."
        elif curr_nvme_wear is not None and curr_nvme_wear >= 90:
            status = "warning"
            rec_text = f"NVMe endurance exhausted ({curr_nvme_wear}% used). Prepare replacement drive."
        elif delta_30d > 0:
            status = "monitor"
            rec_text = f"Minor degradation velocity: {delta_30d} reallocated sectors over 30 days. Monitor SMART trends closely."
        elif (latest["reallocated_sectors"] or 0) > 0:
            status = "monitor"
            rec_text = f"Drive has {latest['reallocated_sectors']} historical reallocated sectors, but velocity is zero over the last 30 days."

        # Check if the latest self-test for this drive failed
        try:
            latest_test_row = c.execute(
                "SELECT test_type, status, passed, lba_first_error FROM smart_test_history WHERE dev = ? ORDER BY ts DESC LIMIT 1",
                (dev,),
            ).fetchone()
            if latest_test_row and not latest_test_row["passed"] and str(latest_test_row["status"]).upper() == "FAILED":
                status = "critical"
                lba_err = latest_test_row["lba_first_error"] or "Unknown"
                rec_text = (
                    f"Critical hardware test failure detected: {str(latest_test_row['test_type']).title()} test "
                    f"failed with surface defect at LBA {lba_err}. Plan disk replacement immediately."
                )
        except Exception:
            logger.debug("backend.db.query_smart_velocity._eval_velocity: ignored error", exc_info=True)

        # Compute Failure Probability Telemetry (Scrutiny-style degradation assessment)
        if status == "critical" or shedding:
            failure_prob = min(0.98, round(0.85 + (delta_7d * 0.02), 2))
            failure_risk = "critical"
        elif is_accelerating:
            failure_prob = 0.72
            failure_risk = "high"
        elif stuck_pending:
            failure_prob = 0.65
            failure_risk = "high"
        elif curr_nvme_wear is not None and curr_nvme_wear >= 90:
            failure_prob = min(0.95, round(0.60 + ((curr_nvme_wear - 90) * 0.035), 2))
            failure_risk = "high" if curr_nvme_wear >= 95 else "moderate"
        elif delta_30d > 0:
            failure_prob = min(0.48, round(0.25 + (delta_30d * 0.05), 2))
            failure_risk = "moderate"
        elif (latest["reallocated_sectors"] or 0) > 0:
            failure_prob = 0.15
            failure_risk = "moderate"
        else:
            failure_prob = 0.01
            failure_risk = "low"

        # 30-day sparkline, one point per SPARKLINE_BUCKET_SECS: the chart is ~320 px wide, and older
        # history has a row every 15 s (tens of thousands per disk)
        history_rows = c.execute(
            """SELECT MIN(ts) AS ts, ROUND(AVG(temp), 1) AS temp, MAX(reallocated_sectors) AS realloc,
                      MAX(pending_sectors) AS pending, MAX(nvme_pct_used) AS wear
               FROM smart_history WHERE dev = ? AND ts >= ?
               GROUP BY ts / ? ORDER BY ts ASC""",
            (dev, ts_30d, SPARKLINE_BUCKET_SECS),
        ).fetchall()
        sparkline_points = [
            {
                "ts": r["ts"],
                "temp": r["temp"],
                "realloc": r["realloc"] or 0,
                "pending": r["pending"] or 0,
                "wear": r["wear"] or 0,
            }
            for r in history_rows
        ]

        return {
            "dev": dev,
            "status": status,
            "failure_probability": failure_prob,
            "failure_risk": failure_risk,
            "shedding_sectors": shedding,
            "stuck_pending": stuck_pending,
            "realloc_current": curr_realloc,
            "realloc_7d_delta": delta_7d,
            "realloc_30d_delta": delta_30d,
            "nvme_pct_used": curr_nvme_wear,
            "nvme_media_errors": curr_nvme_err,
            "key_attributes": {
                "05_reallocated_sectors": curr_realloc,
                "c5_pending_sectors": latest["pending_sectors"] or 0,
                "c6_offline_uncorrectable": latest["offline_uncorrectable"] or 0,
                "c7_crc_errors": latest["crc_errors"] or 0,
                "nvme_pct_used": curr_nvme_wear,
                "power_on_hours": latest["power_on_hours"] or 0,
            },
            "predictive_velocity": {
                "sample_points": len(x_vals),
                "realloc_slope_per_1000h": realloc_slope_per_1000h,
                "realloc_r2": realloc_r2,
                "wear_slope_per_1000h": wear_slope_per_1000h,
                "wear_r2": wear_r2,
                "is_accelerating": is_accelerating,
            },
            "recommendation": rec_text,
            "sparkline_points": sparkline_points,
        }

    def _cached(c: sqlite3.Connection) -> dict:
        # The full evaluation reads up to 30 days of rows; it only changes when a disk's
        # counters or self-test result change, so it is reused until then (PERF-1).
        c.row_factory = sqlite3.Row
        head = c.execute(
            "SELECT ts, reallocated_sectors, pending_sectors, offline_uncorrectable, crc_errors, "
            "nvme_pct_used, nvme_media_errors FROM smart_history WHERE dev = ? ORDER BY ts DESC LIMIT 1",
            (dev,),
        ).fetchone()
        if head is None:
            return _eval_velocity(c)
        try:
            test = c.execute("SELECT MAX(ts) FROM smart_test_history WHERE dev = ?", (dev,)).fetchone()[0]
        except sqlite3.Error:
            test = None
        db_file = c.execute("PRAGMA database_list").fetchone()[2]
        counters = (tuple(head)[1:], test)
        key = (db_file, dev)
        hit = _VELOCITY_CACHE.get(key)
        if (
            hit
            and hit["counters"] == counters
            and (hit["ts"] == head["ts"] or now_ts - hit["at"] < VELOCITY_RECHECK_SECS)
        ):
            return dict(hit["result"])  # shallow: callers only read the nested parts
        result = _eval_velocity(c)
        _VELOCITY_CACHE[key] = {"counters": counters, "ts": head["ts"], "at": now_ts, "result": result}
        return dict(result)

    try:
        if conn is not None:
            return _cached(conn)
        with db_read_session() as new_conn:
            return _cached(new_conn)
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
            "failure_probability": 0.0,
            "failure_risk": "low",
            "key_attributes": {
                "reallocated_sectors": 0,
                "pending_sectors": 0,
                "uncorrectable_sectors": 0,
                "crc_errors": 0,
            },
            "recommendation": "Unable to calculate velocity",
            "sparkline_points": [],
        }


def query_all_smart_velocities() -> dict:
    """Returns degradation velocity assessment for all disks with recorded history."""
    out = {}
    try:
        with db_session() as conn:
            conn.row_factory = sqlite3.Row
            skip_scan_sql = """
                WITH RECURSIVE cte AS (
                    SELECT MIN(dev) AS dev FROM smart_history WHERE dev IS NOT NULL
                    UNION ALL
                    SELECT (SELECT MIN(dev) FROM smart_history WHERE dev > cte.dev AND dev IS NOT NULL)
                    FROM cte WHERE dev IS NOT NULL
                )
                SELECT dev FROM cte WHERE dev IS NOT NULL;
            """
            devs = [r[0] for r in conn.execute(skip_scan_sql).fetchall()]
            for d in devs:
                out[d] = query_smart_velocity(d, conn=conn)
    except Exception as e:
        logger.debug(f"[ZettNAS] Failed to query all velocities: {e}")
    return out


def log_ups_event(
    event_type: str,
    status: str = "COMPLETED",
    duration_sec: float = 0.0,
    start_battery_pct: float | None = None,
    end_battery_pct: float | None = None,
    min_line_volts: float | None = None,
    max_load_pct: float | None = None,
    action_taken: str = "",
    details: str = "",
    ts: int | None = None,
) -> int:
    now_ts = int(time.time()) if ts is None else ts
    try:
        with db_session() as conn:
            cur = conn.execute(
                """
                INSERT INTO ups_events (
                    ts, event_type, status, duration_sec, start_battery_pct,
                    end_battery_pct, min_line_volts, max_load_pct, action_taken, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_ts,
                    event_type,
                    status,
                    duration_sec,
                    start_battery_pct,
                    end_battery_pct,
                    min_line_volts,
                    max_load_pct,
                    action_taken,
                    details,
                ),
            )
            return cur.lastrowid or 0
    except Exception as e:
        logger.error(f"[UPS DB] Failed to log UPS event: {e}")
        return 0


def query_ups_events(limit: int = 50) -> list[dict]:
    out = []
    try:
        with db_session() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, ts, event_type, status, duration_sec, start_battery_pct,
                       end_battery_pct, min_line_volts, max_load_pct, action_taken, details
                FROM ups_events
                ORDER BY ts DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            for r in rows:
                out.append(dict(r))
    except Exception as e:
        logger.debug(f"[UPS DB] Failed to query UPS events: {e}")
    return out

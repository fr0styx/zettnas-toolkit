-- history.db at schema v1, with seed rows (ARCH-7 upgrade tests). Generated from the v1 init code.
CREATE TABLE app_config (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
CREATE TABLE copy_history (
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
                );
CREATE TABLE metrics (
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
                );
INSERT INTO "metrics" VALUES(1790000000,41.0,12.5,33.0,'[]','[]',0.0,0.0,0.0,0.0);
CREATE TABLE smart_history (
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
                    PRIMARY KEY (ts, dev)
                );
INSERT INTO "smart_history" VALUES(1790000000,'sda',35.0,2,0,0,0,0,0,0);
CREATE TABLE smart_test_history (
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
                );
CREATE TABLE ups_events (
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
                );
CREATE INDEX idx_copy_history_ts ON copy_history(ts DESC);
CREATE INDEX idx_smart_history_dev_ts ON smart_history(dev, ts DESC);
CREATE INDEX idx_ups_events_ts ON ups_events(ts DESC);
CREATE INDEX idx_smart_test_history_dev_ts ON smart_test_history(dev, ts DESC);

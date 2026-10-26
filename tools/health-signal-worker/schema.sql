-- ZettNAS health signal: one row per install per ISO week (docs/HEALTH_SIGNAL.md)
CREATE TABLE IF NOT EXISTS reports (
  id TEXT NOT NULL,          -- random install id (not derived from the machine)
  week TEXT NOT NULL,        -- e.g. 2026-W43
  version TEXT NOT NULL,
  platform TEXT NOT NULL,
  arch TEXT NOT NULL,
  variant TEXT NOT NULL,
  drives TEXT NOT NULL,      -- a range: 0, 1-2, 3-4, 5-8, 9-16, 17+
  features TEXT NOT NULL,    -- comma-separated, from a fixed list
  PRIMARY KEY (id, week)
);
CREATE INDEX IF NOT EXISTS idx_reports_week ON reports (week);

# ZettNAS Toolkit — System Architecture

This document describes the high-level architecture, threading model, data flow, and hardware integration of the ZettNAS Toolkit.

---

## 1. High-Level Architecture Overview

```
                      +-----------------------------------+
                      |   Client WebUI / Mobile Browser   |
                      +-----------------+-----------------+
                                        | (HTTP / SSE / REST)
                                        v
+-----------------------------------------------------------------------------------+
|                              FastAPI Web Application                              |
|                                                                                   |
|  - Auth Middleware & Scrypt Passwords    - Native StaticFiles & Streaming Uploads |
|  - Threadpool Worker Offloading          - S.M.A.R.T. Diagnostics API (Parallel)  |
|  - Fan Curve & Thermal Control API       - WS2812B ARGB Lighting API              |
|  - LCD Framebuffer & Layout API          - Path-Guarded File Browser & Backup     |
+-----------------------------------------------------------------------------------+
       |                 |                   |                   |
       v                 v                   v                   v
+--------------+  +--------------+   +---------------+   +----------------+
|    Stats     |  |     LCD      |   |    Button     |   |  Fan Watchdog  |
|  Collector   |  |   Renderer   |   |   Listener    |   |     Daemon     |
|   (Daemon)   |  |   (Daemon)   |   |   (Daemon)    |   |    (Daemon)    |
+-------+------+  +-------+------+   +-------+-------+   +--------+-------+
        |                 |                  |                    |
        v                 v                  v                    v
  Host Hardware:    Direct Linux       Host GPIO /        Sysfs Watchdog
 - /host/proc/stat  Framebuffer:       evdev Input:       Failsafe:
 - /host/sys/class  /dev/fb0           /dev/input/event*  Restores Auto PWM
 - smartctl drives  172x640 (rot 270)  Debounce daemon    on Hang / Crash
 - WS2812B Serial   RGB565 / BGRA
```

---

## 2. Background Daemon Threading Model

The application starts four persistent background daemon threads upon startup via FastAPI's `lifespan`:

### 2.1 Stats Collector Daemon (`StatsCollector`)
- **Interval**: 2.0 seconds.
- **Responsibilities**:
  1. Reads `/host/proc/stat` and `/host/proc/net/dev` for CPU utilization and network bandwidth.
  2. Queries drive temperatures and standby status via `smartctl` concurrently using `ThreadPoolExecutor(max_workers=min(8, len(targets)))`, preventing blocking of UPS telemetry during disk sleep.
  3. Reads Unraid telemetry (`var.ini`, `mover.ini`) with atomic retry backoff loops (`max_retries=3`, `retry_delay=0.05s`) to prevent false alerts during uncommitted array status writes.
  4. Evaluates active thermal fan curves and calculates duty cycles (`calc_curve_pwm`) with floor clamps and critical temperature overrides (100% PWM at >= 55 °C).
  5. Writes PWM values to `/host/sys/class/hwmon/hwmon*/pwm*` and prunes stale fan trackers via `cleanup_stale_fan_trackers()`.
  6. Persists telemetry snapshots to SQLite via `backend.db.log_metrics()` utilizing WAL journal mode and a 5000ms `busy_timeout`.
  7. Updates `Z_STATE.collector_heartbeat` to signal liveness to the watchdog.
  8. Dispatches telemetry to connected Server-Sent Events (SSE) subscribers.

### 2.2 Direct LCD Framebuffer Renderer (`LcdRenderer`)
- **Display Target**: Physical portrait LCD panel mapped to `/dev/fb0` (resolution `172x640`, portrait scan orientation).
- **Responsibilities**:
  1. Launches an internal headless Chromium session via Playwright targeting `http://127.0.0.1:8082/?mode=lcd`.
  2. Renders with upright hardware geometry (`transform: rotate(90deg) translate(0, -172px)`).
  3. Authenticates using an ephemeral single-session `lcd_token`.
  4. Periodically captures the dashboard canvas at target FPS (`LCD_FPS`, default 10).
  5. Manages memory-mapped buffer via `mmap.mmap()` with explicit `fb_mem.close()` in `finally` blocks to prevent descriptor leaks.
  6. Implements exponential backoff (2s → 60s) for Chromium crash recovery to mitigate CPU spikes.
  7. Automatically sleeps or blanks the screen when screen timeout or night mode is enabled.

### 2.3 Hardware Button Listener (`ButtonListener`)
- **Input Targets**: Hardware chassis push-button mapped through sysfs GPIO or `/dev/input/event*`.
- **Responsibilities**:
  1. Implements hardware debounce filtering.
  2. Differentiates between short press (< 1s) and long press (>= 2s).
  3. Short press: Cycles display modes or wakes the screen.
  4. Long press: Triggers automated storage transfer / copy engine workflows or powers off display.

### 2.4 Fan Watchdog Daemon (`FanWatchdog`)
- **Interval**: 5.0 seconds.
- **Responsibilities**:
  1. Monitors `Z_STATE.collector_heartbeat`.
  2. If the stats collector thread stalls or hangs for longer than `COLLECTOR_WATCHDOG_SECS` (15s):
     - Logs critical error.
     - Releases manual fan overrides and restores motherboard firmware / BIOS fan control (`pwmN_enable = 2`).
     - Logs an alert event to the event subsystem.

---

## 3. Data Persistence & State Model

1. **SQLite Database (`data/history.db`)**:
   - Stores time-series system telemetry (CPU temperature, CPU load, memory utilization, disk temperatures, and fan tachometers) for interactive historical charts.
   - Configured with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`) and `PRAGMA busy_timeout=5000;` to ensure concurrent, non-locking reads and writes across API routes and the stats collector daemon.
   - Automatically pruned via retention policies.

2. **Backup & Restore Engine (`backend/services/backup_engine.py`)**:
   - Exports configuration snapshots and SQLite database states into validated zip archives.
   - Restores configurations with strict zip-slip path validation and atomic staging.

3. **Atomic JSON State Files (`data/*.json`)**:
   - `fan_state.json`: Custom fan curves, manual overrides, minimum floors, and hysteresis.
   - `led_state.json`: Active ARGB lightbar effects, colors, speed, and schedule.
   - `dash_layout.json`: Custom dashboard module order, sizes, and visibility toggles.
   - `security.json`: Administrator credentials (salted `scrypt` hash), username, and contact.
   - `sessions.json`: Active WebUI authorization tokens.
   - `events.json`: System audit and security event log.
   - *All JSON writes utilize atomic staging (`tmp` file + `os.replace` via `backend.fsutil.atomic_write_json`)*.

---

## 4. Frontend Architecture

- **Offline-First & Zero External CDNs**: All scripts, styles, fonts, and chart renderers (`Chart.js`) are bundled locally using Vite.
- **Centralized API Client (`frontend/src/api.js`)**:
  - Handles authentication tokens (`Bearer <token>`).
  - Transparent 401 interception dispatching `auth:required` events to the login modal.
  - Safe typed methods (`api.get`, `api.post`, `api.put`, `api.delete`).
- **Decoupled Event Bus with rAF Debouncing (`frontend/src/event-bus.js`)**:
  - Dispatches events scheduled on `requestAnimationFrame` to prevent UI thread lockups during high-frequency telemetry.
  - Performs state diffing in `frontend/src/state.js` before broadcasting updates.
- **DOM Diffing Protection (`frontend/src/components/dashboard.js`)**:
  - Utilizes `setText()` and `setHtml()` guard functions that check whether values have changed before touching DOM nodes, eliminating layout thrashing and reflows.
- **Automated Accessibility Layer (`frontend/src/a11y.js`)**:
  - Delegates keyboard listeners for `Enter` and `Space` on custom interactive elements.
  - Uses a `MutationObserver` to automatically attach `role="button"`, `tabindex="0"`, and `aria-label` attributes across windows, modal triggers, and dock controls.
- **Window Management & Docking (`frontend/src/components/dock.js`)**:
  - Full desktop windowing subsystem supporting drag, minimize to dock, restore, bring-to-front z-index stacking, and live window hover previews.
- **Frontend Testing Infrastructure**:
  - Unit tested with Vitest + JSDOM (`npm test`), verifying event handling, DOM diffing, and accessibility compliance.

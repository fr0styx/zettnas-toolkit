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
|  - Auth Middleware & Scrypt Passwords    - Static Asset Server (Immutable Cache)  |
|  - Rate-Limited Login & Auth Sessions     - S.M.A.R.T. Diagnostics API             |
|  - Fan Curve & Thermal Control API       - WS2812B ARGB Lighting API              |
|  - LCD Framebuffer & Layout API          - Path-Guarded File Browser & Copy API   |
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
  2. Queries drive temperatures and standby status via `smartctl` with caching and sleep-state awareness.
  3. Evaluates active thermal fan curves and calculates duty cycles (`calc_curve_pwm`) with floor clamps and critical temperature overrides (100% PWM at >= 55 °C).
  4. Writes PWM values to `/host/sys/class/hwmon/hwmon*/pwm*`.
  5. Updates `Z_STATE.collector_heartbeat` to signal liveness to the watchdog.
  6. Dispatches telemetry to connected Server-Sent Events (SSE) subscribers.

### 2.2 Direct LCD Framebuffer Renderer (`LcdRenderer`)
- **Display Target**: Physical portrait LCD panel mapped to `/dev/fb0` (resolution `172x640`, rotated 270° in hardware).
- **Responsibilities**:
  1. Launches an internal headless Chromium session via Playwright targeting `http://127.0.0.1:8082/?mode=lcd`.
  2. Authenticates using an ephemeral single-session `lcd_token`.
  3. Periodically captures the dashboard canvas at target FPS (`LCD_FPS`, default 10).
  4. Rotates and packs pixel buffers into `/dev/fb0` memory, handling custom display stride (e.g. 704 bytes).
  5. Automatically sleeps or blanks the screen when screen timeout or night mode is enabled.

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
   - Automatically pruned via retention policies.

2. **Atomic JSON State Files (`data/*.json`)**:
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
- **Decoupled Event Bus (`frontend/src/event-bus.js`)**:
  - Coordinates telemetry streaming, modal states, toast notifications, and drawer controls without tight coupling or global namespace pollution.
- **Window Management & Docking (`frontend/src/components/dock.js`)**:
  - Full desktop windowing subsystem supporting drag, minimize to dock, restore, bring-to-front z-index stacking, and live window hover previews.

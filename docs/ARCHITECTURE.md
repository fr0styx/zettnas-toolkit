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
  4. Evaluates active thermal fan curves and calculates duty cycles (`calc_curve_pwm`) with floor clamps and a full-speed override when a hard disk reaches `HDD_CRITICAL_TEMP` (55 °C), an NVMe drive `NVME_CRITICAL_TEMP` (75 °C) or the CPU 80 °C.
  5. Writes PWM values to `/host/sys/class/hwmon/hwmon*/pwm*` and prunes stale fan trackers via `cleanup_stale_fan_trackers()`.
  6. Persists telemetry snapshots to SQLite via `backend.db.log_metrics()` utilizing WAL journal mode and a 15000 ms `busy_timeout`.
  7. Updates `Z_STATE.collector_heartbeat` to signal liveness to the watchdog.
  8. Dispatches telemetry to connected Server-Sent Events (SSE) subscribers.

### 2.2 Front LCD Renderer (`LcdRenderer`)
- **Display Target**: Physical portrait LCD panel mapped to `/dev/fb0` (640×172 landscape content, written rotated to the panel's 172×640 portrait scan).
- **Two renderers**, chosen by `LCD_RENDERER` (`auto`, `pil`, `chromium`; `auto` picks Chromium when it is installed):
  - **Built-in (`pil`, `backend/services/lcd_pil.py`)**: draws the four LCD pages directly with Pillow in a few milliseconds. It redraws when the stats collector publishes new numbers (its own wake-up signal, `Z_STATE.lcd_wake`) and at the turn of each minute, otherwise it sleeps. Used by the `-core` images, which have no Chromium. `/api/lcd/preview.png` returns the current frame.
  - **Chromium (`chromium`)**: a headless Chromium session (Playwright) renders `http://127.0.0.1:8082/?mode=lcd` with an ephemeral `lcd_token`; frames arrive by screencast when the page changes. Restarts back off from 2 s to 60 s after a crash.
- **Both**: convert to the framebuffer's pixel format (32-bit BGRA or 16-bit RGB565), write through a memory map closed in `finally`, and blank the screen for the screen timeout and night mode.

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

### 2.5 Virtual Machine Hypervisor & Resource Governor
- **Target**: Linux KVM (`/dev/kvm`) and QEMU/libvirt virtualization layer.
- **Responsibilities**:
  1. Computes dynamic elastic host memory reserve (`max(2GB, 0.10 * Total RAM)`) to prevent host OOM freezes.
  2. Enforces non-destructive resource limits across guest domains with thread overcommit detection.
  3. Supervises guest VNC ports and provides authenticated WebSocket tunnels for `@novnc/novnc` browser console rendering.
  4. Manages official ISO catalog downloads with SHA-256 integrity checks and background download queuing.

### 2.6 Enterprise Standards: DMTF Redfish & SNMP
- **Standards**: DMTF Redfish 1.16+ and SNMP v2c/v3.
- **Responsibilities**:
  1. Exposes standard in-memory Redfish endpoints (`/redfish/v1/Chassis/1/Thermal`, `/redfish/v1/Systems/1`, `/redfish/v1/Storage/1`) backed directly by the live telemetry state cache with zero subprocess forks.
  2. Implements standard MIB counters for automated ingestion into homelab and enterprise infrastructure monitoring tools.

### 2.7 Storage Platform Abstraction Layer (PAL) & Observer Mode
- **Adapters**: Unraid Array, Btrfs Active Provisioner, OpenZFS Engine, and Non-Intrusive Observer Mode adapters for FygoOS, ZettOS, UGOS (Ugreen NAS), TrueNAS SCALE, Proxmox VE, and Generic Linux.
- **Responsibilities & Invariants**:
  1. `is_observer_mode = True`: Discovers storage pools and volume topology without modifying host partitions or background services.
  2. Spindown Safety: Strictly enforces `smartctl -n standby` (exit code 2) to prevent waking sleeping drive platters.
  3. eMMC OS Drive Isolation: Auto-detects internal `/dev/mmcblk*` boot flash on Zettlab D4 hardware to avoid invalid S.M.A.R.T. commands.
  4. Scrub Thermal Watchdog: Automatically suppresses Zero RPM fan modes during active filesystem scrubs and balances.
  5. Native Samba Interoperability: Auto-detects active host Samba (`smbd`/`nmbd` on port 445) on turnkey operating systems and switches embedded Samba containers to standby to prevent port binding collisions.
  6. Filesystem-Accurate Capacity: Calculates pool used space from active filesystem mount statistics (`statvfs`) rather than raw block device allocation tables to prevent capacity inflation on mdraid and LVM.

### 2.8 In-App Self-Updater & Release Orchestration
- **Three channels**: `stable` (each release after 7 days on beta, `:latest`), `beta` (new releases at once) and `edge` (every commit on `main` that passes CI). The updater stays on the image variant you run (full or `-core`).
- **Responsibilities**:
  1. Finds the newest image for the channel and pins it by digest.
  2. Verifies that this project's CI signed exactly that digest (Sigstore bundle, `backend/services/image_signature.py`) before installing; `UPDATE_SIGNATURES=warn|off` relaxes this.
  3. Snapshots the data folder when the version changes, and keeps the last Stable snapshot and the rollback image.
  4. Recreates the container with the same mounts and ports through a helper, keeps the old one until the new one has reported healthy for 60 seconds, and rolls back otherwise; the result is shown as a notice and a notification.

### 2.9 Direct Userspace MMIO Fan Controller
- **Target**: Physical register block at `0xFE0B0456` via `/dev/mem` (or `/host/dev/mem`).
- **Responsibilities & Invariants**:
  1. Operates on verified appliance hardware (Zettlab D6/D6U/D8U, Aoostar WTR Pro) without kernel modules.
  2. **D4 & Generic Hardware MMIO Gatekeeper**: `is_zettlab_mmio_supported()` strictly gates MMIO mapping by verifying motherboard DMI strings. Zettlab D4, ARM64, and non-supported chipsets are never permitted to touch `/dev/mem` aperture, preventing hardware bus aborts and unexpected reboots.
  3. Dynamic fallback: auto-detects `hwmon` driver and routes commands to sysfs if present, falling back to MMIO when absent.
  4. CPU Fan Inviolability: maintains $\ge 58\text{ PWM}$ when driven, or releases to motherboard EC auto control (`0`) when unmanaged.
  5. Emergency Thermal Clamp: unconditionally clamps all fans to maximum PWM (`183`) at $\ge 80^\circ\text{C}$.
  6. Optimized Cooldown & Anti-Flutter: downward hysteresis hold (20s/45s) and Zero RPM standby cooldown (30s) eliminate acoustic hunting.

### 2.10 Zero-Dependency Direct USB HID & Multi-Tier Persistent UPS Engine
- **Target**: Connected USB HID power devices via `/dev/hidraw*` (WalleCube W180, OpenUPS, APC, CyberPower, Eaton) or network NUT/APCUPSD daemons.
- **Responsibilities & Persistence**:
  1. Direct ioctl descriptor querying (`HIDIOCGRDESC`) and feature/interrupt report extraction without host daemons (`nut`/`apcupsd`).
  2. Translates USB HID Power Device (`0x84`) and Battery System (`0x85`) usage pages into live battery charge %, AC power status, and voltage.
  3. **Multi-Tier Persistence Hierarchy**: Stores UPS configuration in SQLite `history.db` (`app_config` table) and falls back through 6 tiers (env vars, host `/etc/nut`, auto-discovery) to guarantee persistence across container reboots.
  4. **DC UPS Wattage Synthesis**: Dynamically calculates wattage and load percentage from `output.voltage` and `output.current` for DC homelab UPS units lacking explicit AC wattage registers.

### 2.11 Multi-Protocol S.M.A.R.T. Engine & Device Self-Test (DST)
- **Protocols**: ATA/SATA (`-d sat`), NVMe (`-d nvme`), SCSI/SAS (`-d scsi`), and USB bridge protocols.
- **Responsibilities**:
  1. Non-invasive standby polling: strictly enforces `smartctl -n standby` to avoid waking sleeping drive platters.
  2. NVMe Device Self-Test: initiates Short and Extended DST tests via controller admin commands with live percentage tracking.
  3. Executive Diagnostic Reports: synthesizes structured report cards with health verdicts, tested sectors, and homelab remediation advice.
  4. Activity Monitor Integration: publishes test lifecycle events and findings to the system audit ledger.

### 2.12 System Observability & Sanitized Diagnostics Subsystem
- **Bundle Format**: Standardized multi-layer ZIP archive (`zettnas_diagnostics_<timestamp>.zip`).
- **Responsibilities & Invariants**:
  1. Zero Spindown Disruption: preserves platter sleep states throughout diagnostic capture.
  2. Deep Subsystem Coverage: collects kernel dmesg, MMIO fan registers, USB descriptors, Btrfs chunk allocation, ZFS pools, Docker stacks, and App Backups.
  3. Comprehensive Secrets Redaction: recursively masks API tokens (`zat_****`), password hashes, private keys, bot credentials, and environment variables.
  4. Executive Health Summary: computes instant in-browser health status banner and component count rollups without generating full archives.

---

### 2.13 Supervisor and Docker API proxy

`backend/services/supervisor.py` starts the long-running daemons (StatsCollector,
SmartPoller, ButtonListener, LcdRenderer, FanWatchdog, DockerProxy). A daemon that
raises is logged with its traceback and restarted after 1 s, 2 s, 4 s … up to 60 s.
`/api/health` lists each daemon's state and restart count.

`backend/docker_proxy.py` runs as a child process listening on
`/run/zettnas/docker.sock`. The app reaches Docker only through it
(`backend.config.docker_sock()`). It handles one request per connection, checks
the method and path against an allow-list, and inspects container-create and exec
bodies for host-level settings. See SECURITY.md for the policy.

### 2.14 AI and VM modules

| Module | Holds |
| ------ | ----- |
| `rag_engine.py` | `RagSearchEngine`: index schema, indexing, search, learning sessions |
| `rag_text.py` | Vocabulary, file-type lists, tokenisation (with CJK bigrams), query parsing |
| `rag_embeddings.py` | Built-in lexical vectors, Ollama embeddings, sqlite-vec |
| `rag_documents.py` | Text extraction and chunking |
| `rag_grounding.py` | Context ordering, retrieval grading, grounding score |
| `rag_standby.py` | Standby guard (which disks hold a path, are they asleep) |
| `vision_queue.py` | Idle-time photo captions and OCR |
| `ai_chat_agent.py` | Ask Zetty orchestration, LLM runtime, answer synthesis |
| `chat_tools.py` | Tool registry: definition, handler and permission policy per tool |
| `chat_web_tools.py` | Web search and weather tools |
| `api/vms.py` | VM HTTP routes and console WebSockets |
| `vm_store.py` | VM settings storage, input confinement, shared QEMU process state |
| `vm_host.py` | Host capabilities: budget, KVM, ISOs, bridges, USB/PCI passthrough, firmware, vTPM |
| `vm_guest.py` | VM IP discovery (ARP, guest agent) |
| `vm_qemu.py` | QEMU command line, start/stop, QMP, vms.json |

### 2.15 Thread pools and time limits (ARC-21)

| Pool | Size | Used for |
|---|---|---|
| AnyIO's thread pool | `SYNC_ROUTE_THREADS` (40) | API routes that are plain functions and block on files, disks or Docker |
| `ZettAsyncWorker` (asyncio's default executor) | 4 per core, 16 to 64 | `asyncio.to_thread` work from async code, including each request's session lookup |
| `SmartPoll` | 8 | SMART reads |
| `DockerInspect` | 4 | container inspection for the stats |
| `zett_notify` | 2 | sending alerts |

The two big pools are separate, so a burst of slow API calls can't starve the services' own
background work, and the session lookup that every request makes never runs on the event loop.
Short external commands always have a time limit: `subprocess.run` and friends get `timeout=`, or
go through `backend.proc.run_bounded`, where a hang counts as a failure (exit code 124);
`tests/test_arc21_bounded.py` refuses a new call without one. Long-running children (the Docker
proxy, WebDAV, SFTP, rclone mounts) are `Popen` and watched by their supervisors.

## 3. Data Persistence & State Model

Every SQLite database opens through `backend.sqlite_conn.connect`, which applies that
database's profile (`users`, `history`, `ai_conversations`, `rag_index`: the pragmas, and
whether it goes through the SQLCipher driver). A migration that fails at startup stops ZettNAS
with a message instead of letting it run on a half-updated layout; an AI database whose key is
missing only waits for the key (ARC-30).

1. **SQLite Database (`data/history.db`)**:
   - Stores time-series system telemetry (CPU temperature, CPU load, memory utilization, disk temperatures, and fan tachometers) for interactive historical charts.
   - Configured with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`) and `PRAGMA busy_timeout=15000;` to ensure concurrent, non-locking reads and writes across API routes and the stats collector daemon.
   - Automatically pruned via retention policies.

2. **Backup & Restore Engine (`backend/services/backup_engine.py`)**:
   - Exports configuration snapshots and SQLite database states into validated zip archives.
   - Restores configurations with strict zip-slip path validation and atomic staging.

3. **Atomic JSON State Files (`data/*.json`)**:
   - `fan_state.json`: Custom fan curves, manual overrides, minimum floors, and hysteresis.
   - `led_state.json`: Active ARGB lightbar effects, colors, speed, and schedule.
   - `dash_layout.json`: Custom dashboard module order, sizes, and visibility toggles.
   - People, roles, sessions and API tokens live in `data/users.db` (SQLite, WAL); the older
     `security.json`, `sessions.json` and `api_tokens.json` are read once and migrated
     (`backend/users_db.py`).
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
- **Desktop Spatial Collision Avoidance & Grid Engine (`frontend/src/components/dock.js`)**:
  - Computes spatial clearance ($\Delta X < 80\text{px}$, $\Delta Y < 70\text{px}$) to identify overlapping desktop icons.
  - Dynamic slot reallocation (`findNextFreeSlot`) automatically cascades colliding icons down vertical grid columns without stacking.
  - Snapping guard prevents multiple icons from dropping or snapping into identical grid slots.
- **Keyed DOM Reconciliation Engine (`reconcileKeyedTable`)**:
  - Preserves table row elements and selection state across telemetry polling cycles with pre-pruning of stale nodes.
- **Frontend Testing Infrastructure**:
  - Unit tested with Vitest + JSDOM (`npm test`), verifying event handling, DOM diffing, and accessibility compliance.

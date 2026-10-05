# ZettNAS Toolkit - Release Changelog

## v1.1.0 (2026-10-05)
### ⚡ Performance, Telemetry Broadcaster & Multi-Channel Alerting
- **Multi-Channel Notifications Engine**:
  - Unraid native notification subsystem integration (`/usr/local/emhttp/webGui/scripts/notify` with host fallback).
  - ntfy.sh push notification dispatcher with priority levels, custom topics, tags, and Bearer token authentication.
  - Generic Webhook and Discord webhook dispatcher with rich embeds and severity coloring.
  - Automated alerting for fan stall events, CPU thermal warnings/critical throttling, drive S.M.A.R.T. health failures/overheats, and media ingest completion/error.
  - Per-event deduplication and rate-limiting cooldown with critical-level bypass.
  - REST API configuration management (`GET/POST /api/notifications/config`) and test dispatch endpoint (`POST /api/notifications/test`).
- **Centralized SSE Stats Broadcaster**:
  - High-performance fan-out broadcaster (`StatsBroadcaster`) with bounded subscriber queues and instant initial state delivery.
  - Thread-safe serialization and dispatch from the background collector daemon to asyncio clients via `loop.call_soon_threadsafe`.
  - Replaced per-client polling loops in `/api/stats/stream` for 0ms telemetry reaction times and zero redundant sysfs polling.
  - Added periodic keepalive SSE comments (`: keepalive\n\n`) on 15s intervals to keep idle reverse proxy connections alive.
- **LCD Renderer Performance & Dynamic Hardware Discovery**:
  - Dynamic discovery of backlight sysfs paths (`/sys/class/backlight/*/brightness`, `/host/sys/class/backlight/...`), gracefully adapting to GPU variations.
  - Dynamic discovery of framebuffer resolution and stride via sysfs (`stride`, `virtual_size`), falling back to 704 stride.
  - Screen-off pause: drops render loop to 0 FPS (0% CPU) when screen brightness is 0 or night mode is blanked.
  - Adaptive FPS backoff: incrementally scales idle rendering down to 1 FPS when display is static, bursting back to target FPS instantly on frame change or `ui_wake` event.
- **Per-Zone Fan Curves**:
  - Extended fan curve configuration to support independent multi-point curves for HDD backplanes (`zone1_curve_points`, `zone2_curve_points`), NVMe cache drives (`nvme_curve_points`), and CPU cooling (`cpu_curve_points`).
  - Thermal monitoring and telemetry tracking for NVMe cache drives with airflow boost logic.
- **CSS Modularization & Frontend Sanitization**:
  - CSS `@layer reset, base, layout, components, themes;` established in `style.css`.
  - Centralized `escapeHtml` utility in `frontend/src/utils.js` for safe user string rendering.
- **Quality Assurance & Verification**:
  - 171 automated unit tests passing (100% pass rate).
  - Verified live physical `/dev/fb0` LCD display (640x172, 704 stride) with zero visual regressions.

## v1.0.0 (2026-10-05)
### 🚀 Release Engineering & Production Readiness
- **Offline-First Frontend & Local Chart.js Bundling**:
  - Eliminated all external CDN dependencies (including `cdn.jsdelivr.net` for Chart.js).
  - Bundled Chart.js (`^4.5.1`) directly into the production asset bundle via Vite (`import Chart from 'chart.js/auto'`).
  - ZettNAS Toolkit is now 100% offline-first and runs cleanly on air-gapped or isolated homelab networks.
- **Frontend Architecture & API Client Refactor**:
  - Eliminated the global `window.fetch` monkey-patch in `frontend/src/api.js`.
  - Refactored all network calls across `folder-browser.js`, `modals.js`, and components to use the centralized `api` client (`api.get`, `api.post`, `api.request`).
  - Purged legacy `window.` global variable pollution (`window.DockManager`, `window.showToast`, `window.confirmCopy`, `window.abortCopyConfirm`, `window.openDrawer`, etc.), migrating to direct ES module imports and `ZettEventBus`.
- **First-Run Setup Wizard**:
  - Built an interactive, dark glass initial onboarding wizard (`setup-wizard.js`).
  - Prompts the user on initial startup to change the factory default password (`admin` -> secure password, min 8 characters) with confirmation and validation.
  - Displays hardware detection summary (Chassis model, `/dev/fb0` LCD status, hwmon cooling fans, ARGB lightbar).
  - Includes a manual launcher button in Settings so users can revisit the wizard anytime.
- **Static File Serving & Immutable Caching**:
  - Configured `Cache-Control: public, max-age=31536000, immutable` for all Vite hashed assets in `/assets/*`.
  - Configured `Cache-Control: no-cache, no-store, must-revalidate` for `index.html` to guarantee instant pickup of frontend upgrades.
  - Preserved dynamic `mode=lcd` body class injection for the physical LCD screen.
- **Multi-Stage Dockerfile & Container Permissions**:
  - Re-architected `Dockerfile` with a multi-stage build:
    - Stage 1: `node:20-alpine AS frontend-builder` compiles the Vite frontend from source.
    - Stage 2: `python:3.12-slim` runs the backend with minimal runtime footprint.
  - Created `docker-compose.dev.yml` for local bind-mount development (`./app.py`, `./backend`, `./static`, `./data`).
  - Standardized `docker-compose.yml` for production image deployments, targeting persistent data in `./data:/app/data`.
  - Tightened container device permissions (`SYS_RAWIO`, `SYS_ADMIN`, and specific major numbers for fb0, DRI, serial, and block devices).
  - Updated `unraid/zettnas-toolkit.xml` to pull from `ghcr.io/fr0styx/zettnas-toolkit:latest`.
- **GitHub Container Registry (GHCR) Publishing Workflow**:
  - Updated CI configuration in `ci/github-actions-ci.yml` with automated Docker Buildx and GHCR publishing on version tags (`v*`).
- **Comprehensive Documentation Suite**:
  - Created `docs/ARCHITECTURE.md`: High-level system architecture, threading model (`StatsCollector`, `LcdRenderer`, `ButtonListener`, `FanWatchdog`), data persistence, and frontend design.
  - Created `docs/HARDWARE_PROTOCOL.md`: Physical hardware interfaces, WS2812B serial packet protocol, sysfs thermal and PWM fan paths, direct `/dev/fb0` framebuffer memory mapping, and chassis button events.
  - Created `docs/REVERSE_PROXY.md`: Production reverse proxy configuration guides for Nginx, Caddy, Traefik, and Nginx Proxy Manager with SSE buffering disabled.
  - Created `CONTRIBUTING.md`: Development guidelines, local setup, running tests (`pytest`), and PR standards.

## v0.9.5 (2026-10-05)
### 🧪 Tests, CI & Observability
- **Pytest Suite (144 tests, 100% passing)**:
  - Added comprehensive automated test suite in `tests/`:
    - `test_fan_curves.py`: Monotonic sorting, bounds clamping, curve interpolation, PWM floor/ceiling, and zone ramp/hold timing.
    - `test_fan_sysfs.py`: Hardware sysfs writes against simulated `zettlab_d8_fans`, firmware handover of CPU fan, failsafe pin on shutdown, and watchdog resumption.
    - `test_smart_parsing.py`: SMART attribute parsing for both ATA HDDs and NVMe SSDs, wear warnings, pending sectors, offline uncorrectable, and health alerts.
    - `test_core_utils.py`: Salted scrypt hashing, legacy SHA-256 transparent upgrade, atomic JSON file writes, path containment checks, and night-window calculation.
    - `test_copy_policy.py`: Media ingest file discovery, EXIF date folder grouping, symlink filtering, and collision policies (skip vs overwrite).
    - `test_api_auth.py`: Authentication, bearer/query token validation, rate-limiting lockout backoff, password validation rules, and docs gating.
    - `test_api_guards.py`: Allowed root containment on `/api/browse` and `/api/mkdir`, wallpaper type verification, upload size caps, traversal rejection, and Pydantic schema validation.
- **Continuous Integration Workflow (`ci/github-actions-ci.yml`)**:
  - Full CI pipeline configuration ready for GitHub Actions:
    - Ruff linting and format verification.
    - Pytest test suite execution (144 tests).
    - Frontend Vite production compilation.
    - Docker container build verification.
  - Ready to be activated into `.github/workflows/` (requires PAT with `workflow` scope).
- **Docker Container HEALTHCHECK**:
  - Added dynamic `HEALTHCHECK` directive in `Dockerfile` testing `GET /api/health` against `$PORT`. Unraid Dockerman now natively reports container health status (`healthy`).
- **Unified API Error Schema (`backend/errors.py`)**:
  - Standardized all error responses to `{ "error": "<slug>", "detail": "<message>", "code": <status> }`.
  - Integrated FastAPI exception handlers for `HTTPException`, `RequestValidationError`, and unhandled exceptions.
  - Upgraded frontend API client (`frontend/src/api.js`) with an `ApiError` class that preserves response details.
- **Legacy Route Deprecation**:
  - Deprecated and removed legacy state-mutating GET routes (`GET /api/mkdir`, `GET /api/events/clear`).
  - Updated frontend to use standard `DELETE /api/events/clear` and `POST /api/mkdir`.
- **Dependency Security & Dependabot**:
  - Bumped Pillow to `10.4.0` (resolving security advisories) and Playwright to `1.47.0`.
  - Added `.github/dependabot.yml` tracking `pip`, `npm`, and `github-actions` updates weekly.

## v0.9.0 (2026-10-05)
### 🛡️ Safety & Security
- **Fan failsafe**:
  - On shutdown or `docker stop`, the disk fans are pinned at PWM 150 (~82%) and the CPU fan goes back to firmware auto. The disk-fan channels have no firmware mode on this driver (`pwm1/2_enable` are read-only), so they hold that value after the container exits.
  - A new watchdog thread engages the same failsafe if the stats collector stops updating for 20 s. Software control resumes automatically once the collector recovers.
- **Fan curve safety**:
  - Curve points are clamped, de-duplicated and made non-decreasing.
  - Fan output never drops below the 58 PWM floor. It used to be able to reach 0, which once left a fan at PWM 35.
  - Any spinning disk at or above **55°C** forces the disk fans to 100% regardless of profile, and logs an event.
- **Passwords & login**:
  - Passwords are hashed with salted **scrypt**. Old SHA-256 hashes are upgraded automatically on the next login.
  - Repeated failed logins are rate-limited per IP with exponential backoff (HTTP 429 + `Retry-After`).
  - New passwords need at least 8 characters, and `admin` is rejected.
  - New `POST /api/auth/logout` revokes the session.
- **No more localhost bypass**: the physical LCD renderer now uses a random internal token generated each time the server starts. Requests from inside the container without credentials now get 401.
- **Wallpaper uploads**:
  - The file content is checked with Pillow; only PNG, JPEG, GIF and WEBP are accepted, up to 10 MB.
  - The stored file's extension comes from its detected type, not the uploaded name.
  - Filenames are reduced to a bare name, so paths can't be smuggled in.
  - Downloads send an explicit content type with `nosniff`.
- **Filesystem containment**:
  - `/api/browse`, `/api/mkdir` and the copy-button destination only accept paths inside `BROWSE_ROOTS` (default `/mnt/user`).
  - Paths are fully resolved first, so `..` tricks and symlinks can't escape.
  - The folder browser only lets you navigate within those folders.
- **API hardening**:
  - `/docs`, `/redoc` and `/openapi.json` are off unless `ENABLE_API_DOCS=1`, and need a login when on.
  - `/layout`, `/state` and `/fans` requests are validated against typed schemas.
  - Request bodies over 16 MB are rejected (HTTP 413).
  - Error responses no longer include raw exception text.
- **Crash-safe config**: all JSON state (sessions, events, fans, LED, layout, buttons, wallpapers, security) is written atomically (temp file → fsync → rename).
- **New `GET /api/health`** (no login needed): reports version, collector heartbeat age, LCD renderer status, failsafe state and critical-temperature state.
- Cleanup: removed the dead `_old_collect_wrapper`, and moved the mobile CSS fix from an HTML injection in `app.py` into `style.css`.

## v0.8.6 (2026-10-05)
### 🪟 Dock Hover Previews & Alert Cleanup
- **Dock Hover Preview Cards & Live Thumbnails**:
  - Implemented an interactive mouse-over hover preview card for all OS dock items (`#dock-hover-tooltip`).
  - Displays the target window title, icon, and dynamic status pill (`ACTIVE`, `MINIMIZED`, or `WORKSPACE`).
  - Renders a live miniature visual thumbnail preview:
    - **System Console**: A scaled replica of the live 640×172 hardware LCD display with real-time gauges, dials, temperatures, and disks.
    - **S.M.A.R.T. Diagnostics**: Disk model, health status indicator, and power-on hours summary.
    - **Media Card Ingest**: Live copy status, progress bar percentage, and active filename.
    - **Destination Folder**: Target storage filesystem path.
    - **Dashboard Home**: NAS chassis thumbnail with workspace shortcut hint.
- **Removed Debug Minimize Toast Alert**:
  - Removed accidental `showToast("Minimize clicked")` call from `modals.js`, preventing spurious red alert notifications from appearing when minimizing diagnostic windows.

## v0.8.5 (2026-10-05)
### 🖥️ Desktop Workspace Icon & Console Window Enhancements
- **Top-Left Scaled Chassis Desktop Icon**:
  - Relocated the NAS chassis hero image from the center stage to the top-left corner of the desktop workspace (`top: 24px, left: 24px`).
  - Scaled down to 20% width (`136px`) and encapsulated it in a sleek interactive desktop card (`.chassis-desktop-icon`) featuring glassmorphism backdrop blur, live telemetry pulse indicator dot, and tactile hover elevation.
- **Click-to-Open Dashboard Window Management**:
  - Clicking the top-left chassis desktop icon immediately restores and brings the System Console window (`#console-window`) to the front, complete with a focus-pulse animation.
- **Window Controls (Close & Standalone Pop-out)**:
  - Added a dedicated Close button (`✕`) to `#console-window` header alongside the Minimize button (`–`), allowing users to close the dashboard window and enjoy an unobstructed desktop wallpaper.
  - Added a Pop-out button (`↗`) allowing users to launch the LCD dashboard into a dedicated standalone popup window (`/?mode=lcd`) for secondary displays.
- **Physical LCD Isolation Guarantee**:
  - Explicitly added `.chassis-desktop-icon` to [lcd-direct.css](file:///Volumes/appdata/zettnas-toolkit/frontend/src/lcd-direct.css) to ensure the physical 172×640 LCD display (`/dev/fb0`) remains 100% untouched and renders pure hardware telemetry without desktop shortcut elements.

## v0.8.4 (2026-10-05)
### 🛠️ Hardware Integration & WebUI Controls Restoration
- **ARGB LED Strip Control & Stability**:
  - Realigned all component IDs and classes in `led-control.js` (`#led-slider`, `#led-val-display`, `#speed-slider`, `#btn-toggle-led`, `#reactive-toggle`, `.color-chip`, `.color-chip2`, `.effect-btn`, `.profile-pill`) to match the HTML structure, restoring click actions across all colors, effects, brightness sliders, and preset pills.
  - Added `-hupcl` (disable hangup on close) serial configuration in `backend/hardware/led.py` to prevent CDC-ACM microcontrollers from dropping DTR and rebooting upon packet transmission.
  - Prevented routine background disk I/O in `stats_collector.py` from repeatedly overriding manual user lighting preferences.
- **Dynamic Fan Curve Custom Points & Drag Controls**:
  - Corrected SVG curve path element selector IDs (`curve-svg-path` and `curve-area-path`) in `fan-control.js`, resolving an issue where control point handles (`ch-0`, `ch-1`, `ch-2`, `ch-3`) defaulted to `(0, 0)` in the top-left corner.
  - Enabled smooth interactive mouse and touch drag handles across the thermal gradient map.
- **CPU Fan Software Control**:
  - Reconnected the `cpu-fan-toggle` switch in `fan-control.js` to control `pwm3` and `pwm3_enable` (1 for manual curve with 90s hold timer, 2 for firmware/BIOS auto).
- **Manual PWM Override Status Indicator**:
  - Updated `#fan-pwm-val-display` so that when automatic curve control is engaged, "Auto Curve" is displayed in a grayed-out, dimmed state (`color: var(--muted); opacity: 0.5`). When the manual override slider is actively used, the badge updates dynamically to `${pct}% (Manual Active)` in bright accent styling.
- **Chassis Media Slots & Capacity Badges**:
  - Added live capacity formatting to the Source Media Slot dropdown (`SD 4.0 Slot [125.3 GB]` or `[Empty]`).
  - Added a dedicated `#media-slot-info-badge` indicator badge in the Copy Button drawer tab showing current inserted media status (`SD: 125.3 GB` or `SLOTS EMPTY`).
- **Hardware Copy Button & Collision Rule Handling**:
  - Restored full copy toast lifecycle (`#copy-toast`) in `dashboard.js`, providing live transfer progress, file counts, transfer rate (MB/s), ETA estimations, pause/resume, and abort confirmation.
  - Added an "Existing File Collision Rule" setting in the Copy Button tab (`skip`, `overwrite`, or `ask`), defaulting to automatic skipping so that front-panel copy button presses never hang indefinitely on file collisions.
  - Added interactive collision action buttons (`Skip Existing`, `Overwrite All`, `Cancel`) to the copy toast modal for manual confirmation when configured.
- **Physical LCD Real-Time Layout & Timezone Synchronization**:
  - Added layout version detection and `applyDashboardLayout()` trigger directly inside `applyStats()` in `dashboard.js`.
  - Reordering cards, toggling card visibility, resizing modules, or updating timezones and clock formats (12h/24h) on the Live Canvas or Settings drawer now immediately synchronizes to the physical `/dev/fb0` LCD screen in real time.
- **Console Overlay Pointer-Events Fix**:
  - Set `pointer-events: none` on `#console-modal-overlay` while keeping `#console-window` interactive, eliminating invisible fullscreen click interception over the top bar and Toolkit Settings button.

## v0.8.3 (2026-10-05)
### 🔔 Toast System Refactor & Standby Confirmation
- **Top-Centered Notification Toasts**: Re-engineered system notification toasts to always render centered at the top of the browser window below the top navigation bar (`top: 64px`, `z-index: 100000`). Solved the issue where default password security warnings and system alerts were hidden behind the ZETTNAS System Console window.
- **Standby Drive Confirmation Toast**: Fixed confirmation prompt for sleeping/standby drives, rendering a focused dialog below the top bar (`z-index: 100002`) with a subtle backdrop. Users can choose to cancel (leaving the disk asleep) or confirm (`⚡ Wake & Inspect`) to spin up the drive and retrieve SMART health details.
- **Robust Standby Drive Detection**: Enhanced click delegation in `dashboard.js` to cross-reference both DOM classes and reactive telemetry data (`stats.disks`), guaranteeing standby drives are accurately identified.
- **Separation from Media Card Ingest**: Decoupled general system alerts from the media card copy-engine UI (`#copy-toast`), eliminating unnecessary full-screen backdrops and copy progress artifacts during system notifications.

## v0.8.2 (2026-10-05)
### 🐛 Bug Fixes & Drive Interaction Reliability
- **Invisible Modal Click Interception**: Resolved an issue where closed diagnostic modals (SMART diagnostics, metrics, confirm dialogs) remained present in the DOM over `#diskRow` with `pointer-events: auto` at zero opacity. Added explicit `display: none !important`, `pointer-events: none !important`, and `visibility: hidden !important` to all inactive modal backdrops and child windows.
- **Disk Row DOM Preservation & In-Place Updates**: Fixed `renderDisks()` continually destroying and recreating the entire `#diskRow` DOM every 2 seconds caused by comparing role-ordered arrays against raw hardware-ordered arrays. Switched to sorted device comparison and smooth in-place updates of temperatures, standby states, activity dots, and bar gauges.
- **Event Delegation on Disk Tray**: Implemented robust event delegation on `#diskRow` for disk selection, guaranteeing click events are never dropped or detached during stats polling cycles.
- **Device Parameter Normalization & SMART Detail**: Updated `/api/disk_detail` to automatically strip `/dev/` prefixes and translate device aliases (e.g., `nv0` -> `nvme0n1`), eliminating 400 "Invalid device parameter" errors.
- **Standby Drive Wakeup Timeout**: Increased `smartctl` execution timeout in `backend/hardware/disks.py` from 12s to 20s, allowing high-capacity mechanical hard drives sufficient time to spin up from standby sleep mode without timing out.
- **Modal Dismissal Enhancements**: Added click-outside backdrop dismissal to confirmation dialogs and the folder browser modal.

## v0.8.1 (2026-10-05)
### 🐛 Bug Fixes & Hardware Display Restoration
- **Physical LCD Hardware Rendering**: Fixed display cutoff in headless framebuffer output (`lcd-direct.css`) by ensuring `.smart-modal-backdrop` does not hide `#console-modal-overlay` and restoring hardware orientation transforms (`rotate(90deg) translate(0, -172px)`).
- **Physical LCD Output Isolation**: Suppressed WebUI toast alerts, confirm dialogs, and desktop background wallpapers in direct LCD mode (`mode=lcd`), ensuring clean, distraction-free hardware telemetry.
- **Toolkit Settings Drawer Restoration**: Corrected drawer element selectors (`#led-drawer`, `#drawer-overlay`), reconnected tab navigation (Dashboard Layout, LED Strip bar, Fans, Copy Button, Misc), and restored settings keyboard shortcuts.
- **Dashboard Layout Persistence**: Added missing `GET /api/layout` endpoint in `backend/api/system.py` to prevent 404 errors when loading dashboard arrangements.

## v0.8.0 (2026-10-05)
### 🎨 Frontend Modularization & Component Architecture (Phase 3)
- **Monolithic main.js Deconstruction**: Decomposed the monolithic 3,604-line `main.js` into focused, reusable ES modules under `frontend/src/`:
  - `api.js`: Centralized API client managing Bearer token auth, 401 Unauthorized handling, and JSON serialization.
  - `event-bus.js`: Reactive pub-sub event bus supporting `.on()`, `.off()`, `.emit()`, and `.once()` while retaining backward compatibility with the `EventTarget` DOM API.
  - `state.js`: Centralized reactive state store maintaining active layout, telemetry cache, theme, fan curve points, and view preferences.
  - `components/dashboard.js`: Hardware telemetry renderers, radial gauges, fan tachometers, and dynamic drive trays.
  - `components/dock.js`: MacOS-style dock manager, active window depth stack (`bringToFront`), modal minimize/restore, and universal window dragging (`makeDraggable`).
  - `components/fan-control.js`: Interactive SVG fan curve editor with drag-and-drop thermal nodes, zone isolation filters, and PWM profile management.
  - `components/led-control.js`: Physical and virtual ARGB lightbar effects, color hex palettes, speed, and night schedule.
  - `components/mini-preview.js`: 640x172 mini LCD canvas preview, drag-and-drop card rearrangement, scaling, and layout persistence.
  - `components/wallpapers.js`: Custom wallpaper gallery, upload, selection, rename, and deletion.
  - `components/events.js`: Hardware alert and diagnostic event logger with log filtering and clearing.
  - `components/settings.js`: Toolkit settings drawer, auto-copy button options, screen backlight dimming, and security forms.
  - `components/metrics-chart.js`: Chart.js telemetry line graphs across historical ranges (1h, 6h, 24h, 7d, 30d).
  - `components/auth.js`: Login dialog controller, credential verification, and token storage.
- **Dedicated Framebuffer Isolation (`lcd-direct.css`)**: Extracted all headless LCD framebuffer (`172x640`) rendering rules out of `style.css` into a dedicated stylesheet.
- **CSS Specificity Overhaul**: Slashed `!important` declarations by **84%** (from 114 down to 18), eliminating specificity wars while preserving responsive layout integrity.
- **Robust Error Handling**: Added modal confirmation dialogs for drive wakeups and error-handled API requests across all user interactions.

## v0.7.0 (2026-10-05)
### 🏛️ Backend Modularization & API Architecture (Phase 2)
- **Monolithic Deconstruction**: Refactored the monolithic ~2,300-line `app.py` into a clean, maintainable `backend/` Python package with clear separation of concerns across configuration, state management, database telemetry, hardware interfaces, background daemons, and route handlers.
- **Dedicated Hardware Layer (`backend/hardware/`)**:
  - `cpu.py`: CPU core telemetry, thermal readings with fallback across sysfs hwmon sensors.
  - `memory.py`: `/proc/meminfo` RAM parser.
  - `fans.py`: PWM fan curves, fan speed reading, zone-based thermal holds.
  - `led.py`: ARGB LED protocol, CRC table calculation, rainbow effect worker.
  - `screen.py`: Screen brightness controls and scheduled night mode logic.
  - `network.py`: Network interface traffic calculation and IP resolution.
  - `storage.py` & `disks.py`: Storage pool capacity metrics, SMART health attributes, chassis model detection.
- **Background Daemon Services (`backend/services/`)**:
  - `stats_collector.py`: Continuous hardware telemetry collector and 5-minute SQLite metric logger.
  - `lcd_renderer.py`: Low-latency Playwright Chromium framebuffer (`/dev/fb0`) renderer.
  - `button_listener.py`: Hardware button interrupt and SD/TF media copy trigger listener.
  - `copy_engine.py`: High-speed multi-threaded media backup engine with EXIF metadata parsing.
- **Validated Data Models (`backend/models/schemas.py`)**: Implemented strict Pydantic v2 schemas for all API inputs (`LoginRequest`, `SecurityUpdateRequest`, `FanConfigRequest`, `LedConfigRequest`, `WallpaperSelectRequest`, `WallpaperRenameRequest`, `ButtonConfigRequest`, `CopyConfirmRequest`, `MkdirRequest`).
- **Modular API Routers & Versioning (`backend/api/`)**:
  - Segmented routes into dedicated domain routers: `auth`, `stats`, `fans`, `led`, `wallpapers`, and `system`.
  - Added modern `/api/v1/*` routes alongside 100% backwards-compatible `/api/*` aliases for frontend stability.
  - Standardized REST compliance for event clearing (`GET`, `POST`, and `DELETE` on `/api/events/clear`).
  - Auto-generated interactive OpenAPI / Swagger docs at `/docs` and `/redoc`.
- **Slim Entrypoint & Docker Compose Mount**:
  - Root `app.py` reduced from 2,300+ lines to ~140 lines using FastAPI `lifespan` lifecycle management.
  - Updated `docker-compose.yml` to bind-mount `./backend:/app/backend` for hot code changes without full container rebuilds.

## v0.6.0 (2026-10-05)
### 🛡️ Security & Stability Hardening (Phase 1)
- **Session-Based Authentication Engine**: Eliminated critical auth token leak where raw SHA-256 password hashes were returned to the client and accepted as bearer tokens. Implemented cryptographically secure, random session tokens via `secrets.token_urlsafe(32)` with 30-day TTL expiration, active session pruning, and server-side persistence in `sessions.json`.
- **Default Password Audit & Alerts**: Added proactive default credential detection (`is_using_default_password()`). The system now displays prominent startup console warnings, exposes password health via `/api/security`, and automatically logs a warning alert to the dashboard Event Log if the default `"admin"` password is still in use.
- **Thread Lock Integrity (RLock)**: Resolved a critical race condition where `Z_STATE.lock` was reassigned 4 separate times across module load, breaking mutual exclusion. Consolidated all state initialization inside `ZettState.__init__` with a single, persistent `threading.RLock()`.
- **Deduplication & Error Recovery**: Removed redundant duplicate definitions of `_load_events()` and `add_event()` (lines 1599/1609). Fixed an interrupted `except Exception as e:` handler in `render_lcd_loop()` to ensure the LCD framebuffer streamer can cleanly recover from frame capture errors.
- **Robust Exception Handling**: Replaced all 15 bare `except: pass` blocks across file operations, hardware sysfs reads, and JSON loading with explicit, targeted exception tuples (`json.JSONDecodeError`, `OSError`, `ValueError`, `IndexError`), preventing suppression of critical system signals (`KeyboardInterrupt`, `SystemExit`).
- **Container Build Hardening**: Added `.dockerignore` to keep development dependencies (`node_modules/`, ~25MB+), `.git/`, `.env`, and local `data/` out of production Docker container builds.
- **Pinned Dependencies**: Explicitly pinned all runtime packages in `requirements.txt` (`fastapi==0.115.0`, `uvicorn==0.32.0`, `sse-starlette==2.1.3`, `aiofiles==24.1.0`, `exifread==3.0.0`, `Pillow==10.2.0`, `playwright==1.42.0`).

## v0.5.1 (2026-10-02)
### 📱 Mobile UI Viewport Constraint Fix
- **System Console Clipping Fix**: Constrained the physical `.chassis-front-panel` modal to `max-height: 85vh` with `overflow-y: auto` in mobile responsive views (<= 720px). This prevents the vertically centered fixed modal from getting pushed off the top edge of mobile browser viewports.


## v0.5.0 (2026-10-02)
### 🖼️ Wallpaper Gallery & UI Polish
- **Custom Wallpaper Engine**: Upload custom images from your device to instantly overwrite the default studio background. Wallpapers are permanently saved in the Unraid `appdata` directory.
- **Wallpaper Gallery Management**: Added a dropdown gallery to browse, switch between, rename, and selectively delete past wallpaper uploads without needing to re-upload.
- **Zero-Latency Authentication Exception**: Added a precise middleware exception allowing the browser to natively GET and render wallpaper images seamlessly without triggering API authentication `401 Unauthorized` blocks.

### 🪟 Windows Depth & Dock Management
- **MacOS-Style Persistent Dock**: Pinned the ZettNAS dock `z-index` to absolute foreground. The dock now intelligently tracks active windows via depth tracking and brightly highlights the icon of whichever application currently holds foreground focus.
- **System Console Refinements**: 
  - The System Console now perfectly centers itself on the dashboard viewport upon initial page load.
  - The draggable hitbox has been expanded to encompass the entire top bezel.
  - The console bezel geometry has been re-architected with absolute positioning to perfectly match the top and bottom padding for symmetrical hardware aesthetics.
  - Fixed a collision bug between Javascript position dragging and CSS `transform` animations that caused the console to rapidly slingshot across the screen when first grabbed.
  - Eliminated `.card-collapsed` CSS padding stripping, restoring cohesive 14px padding to all minimizable toolkit sections.


## v0.4.1 (2026-10-02)
### 📱 Mobile UI/UX Optimization
- **Dashboard Z-Overlap Fix**: Overrode flex-basis collapse issues on mobile viewports. Upper dashboard cards and lower disk groups now correctly stack in a column on narrow screens instead of overlapping.
- **Top Navigation Compaction**: Dynamically hides the `/dev/ttyACM0` and `/dev/fb0` telemetry pills on screens under 720px to prevent layout squishing.
- **Iconographic Toolkit Settings**: Compresses the "TOOLKIT SETTINGS" drawer button into a sleek, center-aligned `⚙` icon-only button on mobile to preserve critical header space.
- **Chassis Touch Targets**: Slashed the excessive side padding on the physical `.chassis-front-panel` box specifically for mobile, expanding the interactive dashboard closer to screen edges for easier tapping.
- **LCD Preview Responsiveness**: Protected the 640x172 "Live Canvas Re-arrange" mini-preview from inheriting the mobile dashboard's vertical column wrapping, keeping the drag-and-drop tiles perfectly aligned.
- **Dynamic Mini-Canvas Downscaling**: Added a `--mini-scale: 0.46` hook to the mobile layout. The preview canvas now perfectly fits within the mobile settings drawer without horizontal compression or text clipping.


## v0.4.0 (2026-10-01)
### 🏗️ Major Architectural & Decoupling Upgrades
- **Frontend Modularization (Vite ES6)**: Eradicated the monolithic `app.js` file. The frontend has been entirely decoupled into strictly scoped ES6 modules (`api.js`, `state.js`, `ui-layout.js`, `hardware-events.js`, `modals.js`, `toast.js`, `folder-browser.js`, `event-bus.js`).
- **Vite Build Pipeline**: Transitioned from raw static files to a modern Vite build pipeline (`npm run build`), delivering minified, hashed, and optimized assets directly to the Python backend.
- **ZettEventBus Custom Event System**: Implemented a native Javascript `CustomEvent` bus to completely decouple the layout engine, modals, and hardware telemetry events.
- **Backend Thread-Safety & Optimization**: 
  - Restructured `app.py` to decouple global state into a thread-safe `ZettState` manager.
  - Implemented dynamic `ETag` and `gzip` compression caching for static assets.
  - Reduced Python `os.walk` passes during SD card ingestion from O(2n) to O(n).
  - Stopped spawning `stty` subprocesses on every single LED packet transmission, drastically reducing CPU overhead during smooth lighting animations.
  - Extracted repetitive GET/POST routing logic into DRY helper methods.

### 🐛 Bug Fixes & Refinements
- **LCD Preview Sync Issues**: Fixed a race condition where the mini-preview canvas structure would trap the disk row inside a restricted flexbox container, causing it to render as 0 pixels high until dragged. 
- **Telemetry Live-Sync Re-Write**: Replaced fragile `querySelector` ID polling for the preview canvas with robust 10 FPS `innerHTML` cloning, fixing an issue where preview numbers remained stuck at 0GB.
- **Cooling Duty Profile Calibration**: Fixed a UI bug where Fan PWM sliders and presets misleadingly presented the 8-bit limit as `255`. The interface now correctly scales and displays the true hardware limits (67, 120, 155, 183 PWM).
- **Modal Event Crashes**: Fixed silent `ReferenceError` crashes in the main update loop that occurred after decoupling modal functions.
- **AbortControllers**: Added `AbortController` signals to S.M.A.R.T. modal fetches to gracefully cancel obsolete disk queries.

### 🎨 UI / UX Enhancements
- **Responsive Tablet Overlay**: Added a `max-width: 1100px` breakpoint so the dashboard elegantly scales on tablets without clipping into the sliding settings drawer.
- **GPU-Accelerated Animations**: Replaced expensive CSS `box-shadow` animations with pseudo-element `opacity` transitions (`boxEmber`), eliminating continuous browser repaints.
- **Accessibility (A11y)**: Fortified all modals and toasts with proper `role="dialog"`, `aria-modal`, and `aria-label` tags for screen readers.

## v0.3.1 (2026-10-01)
- **Fix:** Fixed hardware mapping issue where the container lost access to `/dev/mem` due to stripped `privileged` mode, preventing the physical Copy button from functioning.
- **Fix:** Unified the UI alert system to use the native, centered Modal UI for all frontend and validation errors, ensuring critical config errors are visible.
- **Fix:** Corrected an aggressive frontend bug where `applyStats` instantly hid active UI toasts.
- **Fix:** Implemented `mtime` file modification tracking on the backend Python static cache to safely allow instantaneous frontend JS edits.
- **Fix:** Added deep directory verification on "Save Configuration" to prevent saving bogus destination paths before copy operations.
- **Enhancement:** Increased visual error toast duration to 8 seconds for improved readability.



## 🚀 New Features & Capabilities

**1. Hardware Copy Ingestion System**
- **Physical "Copy" Button Integration**: The front panel "Copy" button on the Zettlab chassis can now be bound to instantly mount, read, and ingest contents from an inserted SD or TF card directly to your Unraid/Debian array.
- **Interactive Copy Progress UI**: Real-time copy progress, speed (MB/s), file-count estimates, and ETAs are now seamlessly streamed to a centered, blurred-backdrop modal on the web dashboard.
- **Dynamic Slot Capacity Detection**: The UI intelligently queries the Linux `sysfs` tree in real-time to auto-detect and report the live capacity of inserted SD/TF media cards.

**2. Intelligent File Collision Engine**
- **Overwrite Handling**: The ingestion backend now actively pre-scans for file collisions before copying. If duplicates are found, it safely halts and invokes a UI dialog allowing the user to "Skip Existing", "Overwrite All", or "Cancel".
- **Secure Abort Mechanism**: Added a "Cancel Transfer" UI drawer (Red `×`). Triggering this safely kills the ingestion thread and immediately purges any partially-written files to strictly prevent media corruption.

**3. Performance & Backend Upgrades**
- **Zero-Latency Telemetry**: Ripped out the standard polling delays. The physical front-panel button now triggers a `threading.Event()` to instantly wake the SSE engine, resulting in 0ms latency UI reactions.
- **Server-Sent Events (SSE)**: Upgraded the entire `/api/stats` architecture to use SSE (`/api/stats/stream`), drastically lowering overhead and browser network flooding.
- **In-Memory Caching**: Implemented a rigorous caching mechanism for disks, chassis detection, and static assets, utilizing dynamic `gzip` compression and `ETag` generation for near-instant dashboard loads.
- **Kernel USB I/O Tuning**: Ingestion mounts now leverage `-o noatime,nodiratime` kernel flags, freeing up maximum USB 4.0 read bandwidth (stress-tested to over 1000+ MB/s internal routing throughput).

## 🛠️ Bug Fixes & Stability

- **I2C Tachometer Filtering**: Patched an elusive hardware bug where the `hwmon` sensor would occasionally report spurious tachometer spikes (e.g. `8000 RPM`). Erroneous data above expected bounds is now aggressively filtered and safely zeroed out.
- **Hardware Bus Mapping Bug**: Explicitly filtered ingestion targets to the `usb` bus block-symlinks, ensuring the ingestion tool never accidentally attempts to mount your internal `sata` array disks.
- **Browser Memory Leak / Endless Prompts**: Fixed a DOM event-listener leak by implementing `dataset.listening` locks. This guarantees that UI cancellation prompts only fire exactly once instead of triggering 50 consecutive `confirm()` boxes and blocking browser execution.
- **Python Thread Scoping**: Restructured how asynchronous thread-locks and global variables are scoped, fixing a `SyntaxError: name used prior to global declaration` crash across endpoints.

## 🎨 UI / UX Polish

- The Toast overlay layout has been entirely rebuilt, detaching it from the right-hand panel and securing it as a true fixed `absolute` overlay with backdrop blurring.
- Text & Menu clarity tweaks: Correctly labeled the "Media card ingest" UI, updated the Copy Button setup description, and explicitly renamed the right-hand drawer tab to "Copy Button".
- Visually improved the interactive thermal map by explicitly restricting the olive green (`#6b8e23`) highlights specifically to the "Zone 1" active telemetry dot, leaving the overarching interactive curve and nodes at their original teal styling for maximum contrast.

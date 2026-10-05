# ZettNAS Toolkit - Release Changelog

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

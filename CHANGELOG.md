# ZettNAS Toolkit - Release Changelog

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

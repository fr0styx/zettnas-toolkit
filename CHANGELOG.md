# ZettNAS Toolkit - Release Changelog

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

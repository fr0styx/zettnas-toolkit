<div align="center">
  <img src="static/img/icon.png" width="128" height="128" alt="ZettNAS Toolkit Icon" style="border-radius: 24px;">
  <h1>ZettNAS Toolkit</h1>
  <p><strong>All-in-one hardware management suite, real-time web desktop, and live front-panel LCD dashboard for Zettlab NAS enclosures (D4, D6, D8).</strong></p>

  <p>
    <a href="https://github.com/fr0styx/zettnas-toolkit/releases"><img src="https://img.shields.io/github/v/release/fr0styx/zettnas-toolkit?color=25c2a0&style=flat-square" alt="GitHub Release"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square" alt="License: MIT"></a>
    <img src="https://img.shields.io/badge/Platform-Unraid%20%7C%20Linux%20%7C%20Docker-orange?style=flat-square" alt="Platform">
    <img src="https://img.shields.io/badge/Display-640x172%20IPS%20%28%2Fdev%2Ffb0%29-informational?style=flat-square" alt="Display">
  </p>
</div>

---

## Overview

<div align="center">
  <img src="static/img/ui-screenshot.png" width="90%" alt="ZettNAS Web Studio & Desktop UI" style="border-radius: 8px; box-shadow: 0 12px 36px rgba(0,0,0,0.5);">
</div>

**ZettNAS Toolkit** (**NAS WORKBENCH**) is a specialized hardware orchestration platform engineered for Zettlab NAS enclosures (D4, D6, and D8 models) and custom homelab servers running Unraid, Debian, or generic Docker hosts. It bridges physical chassis peripherals with modern web management:

* **Direct Front-Panel LCD (`/dev/fb0`)** — 640×172 zero-overhead rendering with multi-page rotation, hardware button cycling, screen-off sleep (0 FPS), and adaptive idle rates.
* **Modern Web OS Desktop (Port `8082`)** — Windowed workspace featuring customizable desktop icons, persistent window coordinate bounds (`localStorage`), 8-zone Aero Snap window tiling, snap assist hover flyouts, and interactive taskbar dock with live hover previews.
* **Universal Spotlight Command Palette (`Cmd+K` / `Ctrl+K`)** — Lightning-fast fuzzy search across applications, active Docker containers, storage browse roots, and direct hardware actions (`>reboot`, `>spindown`, `>quiet fans`, `>turbo`, `>theme oled`).
* **Curated 25+ Homelab App Catalog & Conflict Resolver** — Built-in 1-click Docker application catalog (Jellyfin, Immich, Nextcloud, Home Assistant, Vaultwarden, qBittorrent, etc.) with automatic pre-flight host port conflict resolution and live Compose generation.
* **In-Browser Container Web Terminal** — Interactive container console in the Container Inspector allowing live shell command execution, history navigation, and clean output streaming.
* **Parametric 2.5D SVG Chassis Twin & Drive Locator** — Real-time interactive physical twin for Zettlab D4, D6, D8, and DIY enclosures with per-bay thermal heatmaps, spindown platter states, and physical quad-action "Locate Drive" strobe with Web Audio chirps.
* **Desktop Marquee Lasso & Context Menu** — Desktop wallpaper click-and-drag multi-select box and right-click desktop workspace context menu.
* **Mobile PWA & Touch Haptics** — Standalone progressive web app (`manifest.json`) with responsive bottom-sheet layouts and tactile touch vibration feedback (`navigator.vibrate`).
* **Mission Control & Hardware Settings** — Centralized administration hub with responsive left-sidebar navigation, live Docker container telemetry (CPU, RAM, Net I/O), custom named fan curves, and diagnostic inspectors.
* **Predictive S.M.A.R.T. & NVMe Health** — SQLite-backed rate-of-change degradation velocity tracking (shedding sectors, stuck pending sectors, thermal drift) with 30-day sparklines plus NVMe wear metrics (TBW, available spare %, critical warnings).
* **Native NUT UPS Protocol & Emergency Failsafes** — Zero-subprocess TCP socket client (port 3493) with automated failsafes: pauses photo transfers, flushes dirty OS buffers (`os.sync()`), dispatches priority alerts, and triggers host powerdown.
* **High-Integrity Media Ingestion** — Front SD/TF card auto-detection with interactive confirmation dialog, safe eject protection, async I/O (`aiofiles`), SHA-256 verification, and persistent SQLite logs.
* **Multi-Architecture Docker Distribution** — Native multi-arch support (`linux/amd64` and `linux/arm64` for Raspberry Pi, ARM NAS boards, and Apple Silicon) published directly to GitHub Container Registry.
* **Full Internationalization (i18n)** — Zero-dependency client-side localization across 5 languages (English, German, Simplified Chinese, French, and Spanish) spanning all interfaces, modals, and settings.
* **Hardware- & OS-Agnostic Container Engine** — Pure Docker Engine API compliance over `/var/run/docker.sock` across Debian, Ubuntu, TrueNAS SCALE, Proxmox, and Unraid. Features dynamic OCI Compose Spec v3.8+ YAML synthesizer with secret masking, multiplexed live logs console, zero-downtime resource tuning, and atomic port reconfiguration with rollback protection.
* **Strictly Isolated Theme Architecture** — Decoupled styling engines for the physical front-panel LCD (`/dev/fb0`) vs. desktop web workspace, ensuring desktop accent color changes never alter hardware display telemetry.
* **Chassis ARGB Lightbar (`/dev/ttyACM0`)** — USB microcontroller driver for 38 WS2812B LEDs with hardware animations, error-reactive alerts (red/amber), and blackout night scheduling.

---

## Hardware Compatibility

| Component | Target Hardware | Interface & Drivers |
| :--- | :--- | :--- |
| **Enclosures** | Zettlab D4, D6, D8 | Auto-detected via DMI product name or discovered drive topology |
| **Front Display** | Internal 640×172 IPS LCD | Direct memory-mapped `/dev/fb0` (stride 704) |
| **Cooling Fans** | Motherboard `hwmon` | Supports `nct6775`, `it87`, `zettlab_d8_fans`, or standard Linux PWM (`pwm1`–`pwm3`) |
| **ARGB Strip** | Built-in USB microcontroller | Recognized as `ZettOS_RGB` or `/dev/ttyACM0` (38 WS2812B nodes) |
| **Card Reader** | Front SD / MicroSD Slots | Removable block storage (`/dev/sd*`) with auto-detection |

---

## Installation & Deployment

> [!IMPORTANT]  
> **Default Admin Password**: `admin`  
> *(You can update credentials anytime from the "Account & Security" section in the Management window or Toolkit Settings).*

### Option A: Unraid OS (Docker Template)

1. On your Unraid host, copy [`unraid/zettnas-toolkit.xml`](unraid/zettnas-toolkit.xml) into your template directory:
   ```bash
   /boot/config/plugins/dockerMan/templates-user/my-zettnas-toolkit.xml
   ```
2. In the Unraid WebUI, navigate to **Docker** → **Add Container**.
3. Select **zettnas-toolkit** from the template dropdown, verify hardware device paths (`/dev/fb0`, `/dev/dri`, `/dev/ttyACM0`), and click **Apply**.
4. Open the Web Desktop at `http://<unraid-ip>:8082`.

---

### Option B: Ubuntu / Debian / Generic Linux (Docker Compose)

Ideal for custom DIY NAS servers, mini PCs, and Debian/Ubuntu homelab nodes.

1. **Install Docker Engine & Compose Plugin** (if not already installed):
   ```bash
   sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2
   sudo usermod -aG docker,dialout $USER
   ```
2. **Clone & Launch with Linux Compose**:
   ```bash
   git clone https://github.com/fr0styx/zettnas-toolkit.git
   cd zettnas-toolkit
   mkdir -p data
   ```
3. **Start the Container**:
   ```bash
   docker compose -f docker-compose.linux.yml up -d
   ```
   *(By default, this maps persistent app data to `./data` and mounts `/mnt/storage` as the storage pool. You can customize storage roots via `STORAGE_POOL_PATH=/path/to/storage` in `.env` or the compose file).*
4. Access the Web Desktop at `http://<server-ip>:8082`.

---

### Option C: FygoOS / Fygos NAS (App Center & Compose Stack)

FygoOS provides a turnkey, web-based private cloud OS with native Docker support. You can deploy ZettNAS Toolkit via the FygoOS Docker / App Manager:

1. **Create an App Directory on FygoOS**:
   On your primary storage pool (e.g. `/vol1`), create an appdata directory:
   ```bash
   mkdir -p /vol1/appdata/zettnas-toolkit/data
   ```
2. **Deploy via FygoOS Docker Compose / Project Stack**:
   In the FygoOS WebUI, navigate to **Docker** → **Compose / Projects** → **Add Project**, name it `zettnas-toolkit`, and paste the following configuration:
   ```yaml
   services:
     zettnas-toolkit:
       image: ghcr.io/fr0styx/zettnas-toolkit:latest
       container_name: zettnas-toolkit
       restart: unless-stopped
       ports:
         - "8082:8082"
       volumes:
         - /proc:/host/proc:ro
         - /sys:/host/sys:rw
         - /dev:/host/dev:rw
         - /etc/localtime:/etc/localtime:ro
         - /vol1:/mnt/storage:rw
         - /vol1/appdata/zettnas-toolkit/data:/app/data:rw
         - /var/run/docker.sock:/var/run/docker.sock:ro
       environment:
         - PORT=8082
         - WEB_PASSWORD=admin
         - NAS_NAME=FygoNAS
         - POOL_PATH=/mnt/storage
         - HOST_PROC=/host/proc
         - HOST_SYS=/host/sys
         - HOST_DEV=/host/dev
         - LCD_FPS=10
       tmpfs:
         - /host/sys/firmware:ro
         - /host/sys/kernel/debug:ro
       cap_add:
         - SYS_RAWIO
         - SYS_ADMIN
       device_cgroup_rules:
         - 'c 29:* rwm'    # Framebuffer (/dev/fb0)
         - 'c 226:* rwm'   # DRI GPU rendering (/dev/dri/*)
         - 'c 188:* rwm'   # USB Serial (/dev/ttyUSB*)
         - 'c 166:* rwm'   # ACM Serial (/dev/ttyACM*)
         - 'b 8:* rwm'     # SCSI/SATA disks (/dev/sd*)
         - 'b 259:* rwm'   # NVMe disks (/dev/nvme*)
   ```
3. Click **Deploy / Start**.
4. Open your browser to `http://<fygoos-ip>:8082`.

---

### Option D: Standalone Docker CLI (`docker run`)

For rapid testing on any Linux host without Docker Compose:

```bash
docker run -d \
  --name zettnas-toolkit \
  --restart unless-stopped \
  -p 8082:8082 \
  -v /proc:/host/proc:ro \
  -v /sys:/host/sys:rw \
  -v /dev:/host/dev:rw \
  -v /etc/localtime:/etc/localtime:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v $(pwd)/data:/app/data:rw \
  -e PORT=8082 \
  -e WEB_PASSWORD=admin \
  -e HOST_PROC=/host/proc \
  -e HOST_SYS=/host/sys \
  -e HOST_DEV=/host/dev \
  --cap-add SYS_RAWIO \
  --cap-add SYS_ADMIN \
  --device-cgroup-rule='c 29:* rwm' \
  --device-cgroup-rule='c 226:* rwm' \
  --device-cgroup-rule='c 166:* rwm' \
  --device-cgroup-rule='b 8:* rwm' \
  --device-cgroup-rule='b 259:* rwm' \
  ghcr.io/fr0styx/zettnas-toolkit:latest
```

> [!TIP]  
> **Headless & Display Peripherals**: ZettNAS Toolkit runs seamlessly on headless servers (without a physical `/dev/fb0` LCD or `/dev/ttyACM0` ARGB lightbar). If physical display hardware is not detected, the toolkit automatically starts in headless mode and serves the interactive Web OS Desktop over HTTP.

---

## Web Desktop & Shortcuts

When accessing the Web Desktop (`http://<server-ip>:8082`):
* **Desktop Icons** — Clean 4-icon desktop workspace: **Mission Control**, **File Explorer**, **Recycle Bin**, and **ZettNAS (IPS Display)**. Drag and drop anywhere on screen; positions and open window bounds persist automatically across reloads.
* **Hardware Settings Drawer** — Press `T` or click `HARDWARE SETTINGS` in the top navbar to configure acoustic fan profiles, LCD sleep schedules, ARGB lightbar effects, and media slots.
* **Command Palette** — Press `Cmd+K` (macOS) or `Ctrl+K` (Linux/Windows) for fuzzy-search navigation across all toolkit tools, settings, and hardware panels.
* **Window Snapping** — Drag any window to screen edges or top to snap (Half-Screen Left / Right / Maximize).
* **Accessibility (A11y)** — Full keyboard navigation with `Tab`, `Enter`, and `Space` activation on interactive elements and screen-reader ARIA roles.
* **Themes & Display Styles** — 5 curated interface themes: **Cyber** (default dark), **Amber** (CRT monochrome phosphor), **Emerald** (matrix green terminal), **Light** (clean modern high-contrast), and **Yak Express** (easter egg cult theme).
* **Language Selector** — Quick 1-click language switcher in the navbar (`EN`, `DE`, `ZH`, `FR`, `ES`) with instant dynamic UI translation.
* **Mobile Stacked Mode** — Toggle between floating windowed desktop and vertical touch-optimized card layout via the top navbar button.
* **Keyboard Hotkeys**:
  * `Cmd+K` / `Ctrl+K` — Open Command Palette.
  * `T` — Toggle Hardware Settings Drawer.
  * `Z` or `Mouse Wheel` — Cycle Chassis Zoom scale (1x, 1.25x, 1.5x, 2x).
  * `Y` — Toggle Yak theme aesthetic.
  * `Esc` — Close open modals, command palette, and drawers.

---

## REST API Reference

All routes are mounted at `/api` (or versioned alias `/api/v1`). Authenticated endpoints accept the `X-ZettNAS-Token` header or `?token=` query parameter.

For complete endpoint specifications, parameter schemas, Server-Sent Events (SSE) telemetry contracts, and curl examples, see the dedicated **[REST API Reference](docs/API.md)**.

| Category | Highlights | Docs |
| :--- | :--- | :---: |
| **Telemetry & Streaming** | Real-time metrics snapshot (`/api/stats`), 1 Hz live SSE stream (`/api/stats/stream`), historical time-series graphs (`/api/history`). | [Details](docs/API.md#1-telemetry--live-streaming) |
| **Subsystem Management** | Acoustic profiles (`/api/system/profile`), Unraid array (`/api/unraid`), Docker orchestration, Compose synthesizer, logs & port mutator (`/api/docker/*`), UPS/NUT (`/api/ups`). | [Details](docs/API.md#2-system--subsystem-management) |
| **Hardware Controls** | Fan curves/PWM (`/api/fans`), ARGB lightbar effects (`/api/led`), LCD brightness/pages (`/api/lcd/*`), S.M.A.R.T. self-tests (`/api/disk/*`). | [Details](docs/API.md#3-hardware-controls--diagnostics) |
| **Media & Filesystem** | Chunked uploads (`/api/fs/upload`), card slot detection & auto-ingest (`/api/media_slots`, `/api/copy/*`), safe ejection. | [Details](docs/API.md#4-media-ingest--filesystem-management) |
| **Security & System** | Password rotation (`/api/security`), scoped API tokens (`/api/tokens`), multi-channel alerts (`/api/notifications/*`), backup export/restore (`/api/backup/*`). | [Details](docs/API.md#5-configuration-notifications--security) |

---

## Frontend Build & Development

The frontend is built with vanilla ES modules and bundled via Vite:

```bash
npm install
npm run build     # Outputs minified production assets to static/
npm test          # Executes Vitest + JSDOM frontend test suite
```

To run in development mode with hot-reloading:
```bash
npm run dev
```

---

## Documentation & Guides

* **[REST API Reference](docs/API.md)** — Complete endpoint specifications, live SSE telemetry contracts, card reader auto-ingest, and hardware control APIs.
* **[System Architecture](docs/ARCHITECTURE.md)** — Threading model (`StatsCollector`, `LcdRenderer`, `ButtonListener`, `FanWatchdog`), SQLite WAL persistence, and data flow.
* **[Hardware Protocol Reference](docs/HARDWARE_PROTOCOL.md)** — WS2812B serial packet specifications, sysfs thermal & PWM mappings, and direct `/dev/fb0` memory buffers.
* **[Reverse Proxy & TLS Guide](docs/REVERSE_PROXY.md)** — Production configurations for Nginx, Caddy, Traefik, and Nginx Proxy Manager with SSE stream buffering disabled.
* **[Contributing Guidelines](CONTRIBUTING.md)** — Pull request standards, local test environment, and automated test execution.

---

## Acknowledgments & Credits

* **[torharrington/zettlab-display](https://github.com/torharrington/zettlab-display)** — Foundational framebuffer layout experiments for Zettlab front-panel screens.
* **[henryxwong/zettlab-ubuntu](https://github.com/henryxwong/zettlab-ubuntu)** — Comprehensive hardware reverse-engineering of Zettlab registers, fan controller paths, and LED microcontroller protocols.

---

## License

This project is licensed under the [MIT License](LICENSE).

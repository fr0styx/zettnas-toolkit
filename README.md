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

**ZettNAS Toolkit** is a specialized hardware orchestration platform engineered for Zettlab NAS enclosures (D4, D6, and D8 models) running Unraid or Debian/Docker. It bridges physical chassis peripherals with modern web management:

* **Direct Front-Panel LCD (`/dev/fb0`)** — 640×172 zero-overhead rendering with multi-page rotation, hardware button cycling, screen-off sleep (0 FPS), and adaptive idle rates.
* **Modern Web OS Desktop (Port `8082`)** — Windowed workspace featuring customizable desktop icons with persistent drag-and-drop placement, Aero Snap window tiling, and interactive taskbar dock with live hover previews.
* **Full Internationalization (i18n)** — Zero-dependency client-side localization across 5 languages (English, German, Simplified Chinese, French, and Spanish) spanning all interfaces, modals, and settings.
* **System Management Hub** — Dedicated management center featuring responsive left-sidebar navigation, live telemetry badges, Docker container lifecycle controls, and UPS battery monitoring.
* **Interactive Historical Charts** — Dynamic pan-and-zoom telemetry charts powered by `chartjs-plugin-zoom` with multi-device breakdowns (CPU, RAM, individual disk drives, cooling fans) across 1h to 30d retention.
* **Intelligent Per-Zone Fan Regulation** — Independent multi-point thermal curves for HDD backplanes, NVMe cache, and CPU cooling with hysteresis hold protection and shutdown failsafe.
* **Chassis ARGB Lightbar (`/dev/ttyACM0`)** — USB microcontroller driver for 38 WS2812B LEDs with hardware animations, error-reactive alerts (red/amber), and blackout night scheduling.
* **Homelab & Subsystem Health** — Native Unraid array and parity telemetry, zero-dependency Docker container controls (start/stop/restart), UPS battery monitoring, and active drive S.M.A.R.T. self-tests.
* **High-Integrity Media Ingestion** — Front SD/TF card copy engine with async I/O (`aiofiles`), SHA-256 post-copy verification, and persistent SQLite transfer logs.

<div align="center">
  <img src="static/img/ui-screenshot.png" width="90%" alt="ZettNAS Web Studio & Desktop UI" style="border-radius: 8px; box-shadow: 0 12px 36px rgba(0,0,0,0.5);">
</div>

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

### Option A: Unraid Docker Template (Recommended)

1. On your Unraid host, copy [`unraid/zettnas-toolkit.xml`](unraid/zettnas-toolkit.xml) into:
   ```bash
   /boot/config/plugins/dockerMan/templates-user/my-zettnas-toolkit.xml
   ```
2. In the Unraid WebUI, navigate to **Docker** → **Add Container**.
3. Select **zettnas-toolkit** from the template dropdown, verify hardware device paths (`/dev/fb0`, `/dev/dri`, `/dev/ttyACM0`), and click **Apply**.
4. Access the web interface at `http://<server-ip>:8082`.

### Option B: Docker Compose

1. **Verify Prerequisites**:
   ```bash
   ls -l /dev/fb0 /dev/ttyACM0
   ```
2. **Clone & Configure**:
   ```bash
   cd /mnt/user/appdata
   git clone https://github.com/fr0styx/zettnas-toolkit.git
   cd zettnas-toolkit
   cp .env.example .env
   ```
3. **Launch**:
   ```bash
   docker compose up -d --build
   ```

---

## Web Desktop & Shortcuts

When accessing the Web Desktop (`http://<server-ip>:8082`):
* **Desktop Icons** — Drag and drop the **Management** and **ZettNAS** icons anywhere on screen; coordinates persist automatically across sessions.
* **Window Snapping** — Drag any window to the screen edges or top to snap (Half-Screen Left / Right / Maximize).
* **Language Selector** — Quick 1-click language switcher in the navbar (`EN`, `DE`, `ZH`, `FR`, `ES`) with instant dynamic UI translation.
* **Mobile Stacked Mode** — Toggle between floating windowed desktop and vertical touch-optimized card layout via the top navbar button.
* **Keyboard Hotkeys**:
  * `T` — Toggle Hardware Toolkit Settings Drawer.
  * `Z` or `Mouse Wheel` — Cycle Chassis Zoom scale (1x, 1.25x, 1.5x, 2x).
  * `Y` — Toggle Yak theme aesthetic.
  * `Esc` — Close open modals and drawers.

---

## REST API Reference

All routes are mounted at `/api` (or versioned alias `/api/v1`). Authenticated endpoints accept `X-ZettNAS-Token` header or `?token=` query parameter.

### Telemetry & Live Streaming
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/stats` | `GET` | Snapshot of all real-time system metrics (CPU, RAM, storage, fans, disks, lightbar, Unraid, UPS) |
| `/api/stats/stream` | `GET` | Server-Sent Events (SSE) stream for zero-latency live telemetry updates |
| `/api/history` | `GET` | Query historical time-series data with `?range=1h\|6h\|24h\|7d\|30d` (includes per-disk & fan trends) |
| `/api/health` | `GET` | Public daemon liveness probe reporting thread heartbeats and collector status |

### System & Subsystem Management
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/system/profile` | `POST` | Apply unified acoustic profiles (`auto`, `quiet`, `balanced`, `performance`) |
| `/api/unraid` | `GET` | Query Unraid array state, parity sync progress, mover activity, and disk allocation |
| `/api/docker/containers` | `GET` | List Docker containers, images, runtime states, and uptime status |
| `/api/docker/containers/{id}/action` | `POST` | Execute container actions: `start`, `stop`, `restart`, `pause`, `unpause` |
| `/api/ups` | `GET` | Query UPS battery charge percentage, runtime estimate, load, and utility line voltage |

### Hardware Controls & Diagnostics
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/fans` | `GET` / `POST` | Query tachometer RPMs or set manual PWM duty cycles and per-zone curves |
| `/api/led` | `GET` / `POST` | Query lightbar state or apply animations, colors, brightness, and blackout schedules |
| `/api/screen` | `GET` | Query front-panel LCD backlight brightness and power state |
| `/api/state` | `POST` | Update front-panel LCD backlight brightness (0–100%) |
| `/api/lcd_status` | `GET` | Inspect headless Chromium `/dev/fb0` renderer health, active FPS, and framebuffer status |
| `/api/lcd/page` | `GET` / `POST` | Query active LCD carousel page index or switch directly to a target page |
| `/api/lcd/cycle` | `POST` | Advance front-panel LCD to the next telemetry page |
| `/api/disk_detail` | `GET` | Fetch drive identity, S.M.A.R.T. health attributes, and power standby state (`?dev=sda`) |
| `/api/disk/smart_test` | `POST` | Trigger background Short or Extended S.M.A.R.T. self-test on disk |
| `/api/disk_wake` | `POST` | Send spin-up command to standby drive for inspection |

### Media Ingest & Filesystem
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/browse` | `GET` | Explore filesystem directories within allowed storage pool roots (`?path=...`) |
| `/api/mkdir` | `POST` | Create a destination directory within the storage pool |
| `/api/copy/confirm` | `POST` | Start card reader import with optional SHA-256 verification and destination path |
| `/api/copy/pause` | `POST` | Pause an active media copy transfer |
| `/api/copy/resume` | `POST` | Resume a paused media copy transfer |
| `/api/copy/cancel` | `POST` | Cleanly abort an active transfer with partial file cleanup |
| `/api/copy/history` | `GET` | Retrieve persistent SQLite media ingest history and checksum audit logs |

### Configuration, Notifications & Security
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/layout` | `GET` / `POST` | Retrieve or persist front-panel card ordering, visibility, and clock settings |
| `/api/notifications/config` | `GET` / `POST` | Manage multi-channel alert settings (Unraid notify, ntfy.sh, Discord/Webhooks) |
| `/api/notifications/test` | `POST` | Dispatch test notification across all configured notification channels |
| `/api/auth/login` | `POST` | Authenticate session and receive access token |
| `/api/auth/logout` | `POST` | Invalidate active session token |
| `/api/security` | `GET` / `POST` | Check default password status or update master credentials |
| `/api/wallpapers` | `GET` | List available custom desktop wallpapers |
| `/api/wallpapers/upload` | `POST` | Upload and validate new desktop background image |
| `/api/events/clear` | `DELETE` | Flush system hardware event log |

---

## Frontend Build & Development

The frontend is built with vanilla ES modules and bundled via Vite:

```bash
cd frontend
npm install
npm run build     # Outputs minified production assets to static/
```

To run in development mode with hot-reloading:
```bash
npm run dev
```

---

## Documentation & Guides

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

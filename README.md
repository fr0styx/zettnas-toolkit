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
* **Modern Web OS Desktop (Port `8082`)** — Windowed workspace featuring customizable desktop icons, persistent window coordinate bounds (`localStorage`), Aero Snap window tiling, and interactive taskbar dock with live hover previews.
* **Mission Control & Hardware Settings** — Centralized administration hub with responsive left-sidebar navigation, live Docker container telemetry (CPU, RAM, Net I/O), custom named fan curves, and diagnostic inspectors.
* **Predictive S.M.A.R.T. & NVMe Health** — SQLite-backed rate-of-change degradation velocity tracking (shedding sectors, stuck pending sectors, thermal drift) plus NVMe wear metrics (TBW, available spare %, critical warnings).
* **Native NUT UPS Protocol & Emergency Failsafes** — Zero-subprocess TCP socket client (port 3493) with automated failsafes: pauses photo transfers, flushes dirty OS buffers (`os.sync()`), dispatches priority alerts, and triggers host powerdown.
* **High-Integrity Media Ingestion** — Front SD/TF card auto-detection with interactive confirmation dialog, safe eject protection, async I/O (`aiofiles`), SHA-256 verification, and persistent SQLite logs.
* **Multi-Architecture Docker Distribution** — Native multi-arch support (`linux/amd64` and `linux/arm64` for Raspberry Pi, ARM NAS boards, and Apple Silicon) published directly to GitHub Container Registry.
* **Full Internationalization (i18n)** — Zero-dependency client-side localization across 5 languages (English, German, Simplified Chinese, French, and Spanish) spanning all interfaces, modals, and settings.
* **Intelligent Per-Zone Fan Regulation** — Independent multi-point thermal curves for HDD backplanes, NVMe cache, and CPU cooling with user-defined named presets, hysteresis hold protection, and shutdown failsafe.
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
3. **Launch Production**:
   ```bash
   docker compose up -d
   ```
   *(For development with live source code bind-mounts, run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`)*

---

## Web Desktop & Shortcuts

When accessing the Web Desktop (`http://<server-ip>:8082`):
* **Desktop Icons** — Clean 4-icon desktop workspace: **Mission Control**, **File Explorer**, **Recycle Bin**, and **ZettNAS (IPS Display)**. Drag and drop anywhere on screen; positions and open window bounds persist automatically across reloads.
* **Hardware Settings Drawer** — Press `T` or click `HARDWARE SETTINGS` in the top navbar to configure acoustic fan profiles, LCD sleep schedules, ARGB lightbar effects, and media slots.
* **Command Palette** — Press `Cmd+K` (macOS) or `Ctrl+K` (Linux/Windows) for fuzzy-search navigation across all toolkit tools, settings, and hardware panels.
* **Window Snapping** — Drag any window to screen edges or top to snap (Half-Screen Left / Right / Maximize).
* **Accessibility (A11y)** — Full keyboard navigation with `Tab`, `Enter`, and `Space` activation on interactive elements and screen-reader ARIA roles.
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
| **Subsystem Management** | Acoustic profiles (`/api/system/profile`), Unraid array status (`/api/unraid`), Docker orchestration (`/api/docker/containers`), UPS/NUT metrics (`/api/ups`). | [Details](docs/API.md#2-system--subsystem-management) |
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

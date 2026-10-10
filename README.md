<div align="center">
  <img src="static/img/icon.png" width="128" height="128" alt="ZettNAS Toolkit Icon" style="border-radius: 24px;">
  <h1>ZettNAS Toolkit</h1>
  <p><strong>Universal hardware orchestration suite, glassmorphic Web Desktop OS, and container management platform for any NAS and homelab server.</strong></p>

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

**ZettNAS Toolkit** (**NAS WORKBENCH**) is an enterprise-grade, hardware-agnostic orchestration platform, modern web desktop OS, and container management suite engineered for any NAS appliance or custom DIY homelab server (Aoostar, Zettlab, Fractal, Jonsbo, Supermicro, SilverStone) running Unraid, Debian, Ubuntu, TrueNAS SCALE, Proxmox, or Docker. It bridges low-level hardware intelligence with a fluid, multi-window desktop operating experience:

* 🖥️ **Glassmorphic Web Desktop OS** — Fluid multi-window desktop with window snapping, macOS-style parabolic dock magnification, Spotlight command palette (`Cmd+K`), visual wallpaper gallery with drag-and-drop ingestion, and instant themes (Cyber Teal, Amber CRT, Emerald Matrix, Yak Bronze, and Pure OLED Black).
* 🛡️ **Enterprise Multi-User & Granular RBAC** — SQLite WAL user store (`users.db`), RFC 9106 Argon2id credential hashing, TOTP two-factor authentication (2FA), Reverse Proxy SSO (`X-Forwarded-User`), scoped API tokens with CIDR whitelisting, private `/homes/` isolation, and desktop auto-lock (`Cmd+L`).
* ❄️ **Hardware HAL & Acoustic Zero-RPM Fans** — Dynamic Chassis Digital Twin (Aoostar, Zettlab D4/D6/D8, DIY), Zero RPM standby mode for spun-down drive bays, 6-point SVG fan curve designer, and hardware thermal watchdogs.
* 💾 **Universal Storage, WebDAV & PAL** — Platform Abstraction Layer coexisting across Btrfs RAID, Unraid array, and ZFS; multi-protocol S.M.A.R.T. diagnostics (SATA, NVMe, SAS, USB); zero-wake ATA spindown checks (`smartctl -n standby`); collision-free WebDAV (Port `8084`); and 20+ cloud backends via Rclone.
* 🐳 **Docker Containers & Compose Stacks** — In-place Compose stack editor, live container log streaming, clickable update badges, 1-click batch updates with rollback protection, and curated 25+ app catalog.
* 🔔 **Multi-Channel Alerts & 3-2-1 Hyper-Backup** — Unified Apprise alerting (Discord, Telegram, SMTP Email, ntfy, Pushover, Gotify, Webhooks), automated local/cloud snapshot schedules, retention pruning, and native NUT UPS emergency failsafes.
* 📺 **Physical LCD & Media Automation** — Direct memory-mapped front-panel LCD rendering (`/dev/fb0`, 640×172), dynamic hardware button cycling, and front SD/TF card auto-detection with SHA-256 integrity verification.
* 🌐 **Zero-Dependency Internationalization** — Full instant client-side localization across English, German, Simplified Chinese, French, and Spanish.

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
> [!IMPORTANT]  
> **Default Credentials**: Username `admin` | Password `admin`  
> *(You can update credentials or provision multi-user accounts anytime in **Mission Control** → **System & Security**).*

### 🚀 Quick Start (Docker Compose)

For Linux homelab servers, mini PCs, and custom NAS builds:

```bash
# 1. Clone repository & create persistent data folder
git clone https://github.com/fr0styx/zettnas-toolkit.git && cd zettnas-toolkit
mkdir -p data

# 2. Launch production stack
docker compose -f docker-compose.linux.yml up -d
```
Open your browser to `http://<server-ip>:8082`.

---

### 📖 Platform Deployment Guides

For complete configuration templates, hardware pass-through rules, and platform-specific walkthroughs, see the **[Installation & Deployment Guide (docs/INSTALLATION.md)](docs/INSTALLATION.md)**:

| Platform | Deployment Method | Guide Link |
| :--- | :--- | :---: |
| **Unraid OS** | Official DockerMan XML Template | [Unraid Setup](docs/INSTALLATION.md#option-a-unraid-os-docker-template) |
| **Ubuntu / Debian / Generic Linux** | Production Docker Compose (`docker-compose.linux.yml`) | [Linux Compose Setup](docs/INSTALLATION.md#option-b-ubuntu--debian--generic-linux-docker-compose) |
| **FygoOS / Fygos NAS** | Native App Center & Compose Stack | [FygoOS Setup](docs/INSTALLATION.md#option-c-fygoos--fygos-nas-app-center--compose-stack) |
| **TrueNAS SCALE** | Custom App & Compose (Dragonfish / Electric Eel) | [TrueNAS Setup](docs/INSTALLATION.md#option-d-truenas-scale-custom-app--compose) |
| **Standalone Docker CLI** | Direct `docker run` command with device permissions | [Docker CLI Setup](docs/INSTALLATION.md#option-e-standalone-docker-cli-docker-run) |
| **Headless Servers** | Runs seamlessly without physical display (`/dev/fb0`) or ARGB | [Headless Guide](docs/INSTALLATION.md#headless-server-deployments-no-lcd--argb) |

👉 **Read the full [Installation & Deployment Guide](docs/INSTALLATION.md)** for hardware device mappings (`/dev/fb0`, `/dev/dri`, `/dev/ttyACM0`), environment variables, and storage configurations.

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

* **[Installation & Deployment Guide](docs/INSTALLATION.md)** — Step-by-step setup for Unraid, Ubuntu/Debian, FygoOS, TrueNAS SCALE, Docker CLI, device rules, and headless servers.
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

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
* **Desktop Workspace & Custom Shortcuts** — Interactive glassmorphic workspace featuring **Mission Control**, **File Explorer**, **Recycle Bin**, and **Physical LCD Canvas**. Right-click empty workspace to create custom application shortcuts (Containers, Storage Pools, Activity Monitor) or align to grid; positions and window bounds persist automatically across browser reloads.
* **macOS-Style Parabolic Dock** — Fluid magnification on hover, active running indicators, unread notification counter badges, and configurable dock positioning (Bottom, Left, Right).
* **Spotlight Command Palette** — Press `Cmd+K` (macOS) or `Ctrl+K` (Linux/Windows) for fuzzy-search navigation across applications, active Docker containers, storage browse roots, and quick hardware actions (`>reboot`, `>spindown`, `>quiet fans`, `>turbo`, `>theme oled`).
* **Dynamic Hardware Settings Drawer** — Press `T` or click `HARDWARE SETTINGS` in the top navbar. Dynamically displays only when custom appliance features (LCD `/dev/fb0`, front copy button, SD/TF card slot) are present; automatically hides on standard generic servers.
* **Window Snapping & Aero Tiling** — 8-zone edge and corner window snapping with translucent acrylic preview ghost and maximize hover flyouts.
* **Inactivity Auto-Lock & Lock Screen** — Lock the desktop workspace at any time via `Cmd+L` / `Win+L` or configurable inactivity timers without terminating background jobs.
* **Themes & Personalization** — 8 curated themes: **Cyber Teal**, **Amber CRT**, **Emerald Matrix**, **Sapphire Ice**, **Amethyst**, **Crimson**, **Yak Bronze** (with instant Yak wallpaper switch), and **Pure OLED Black** (`theme-oled`). Includes visual wallpaper gallery with drag-and-drop upload and acrylic blur sliders.
* **Multi-User Profile Switcher** — User avatar pill with role badge (`SuperAdmin`, `StorageAdmin`, `AppOperator`, `ShareUser`), fast account switching, and password rotation.
* **1-Click Language Switcher** — Instant UI translation across 5 languages: English (`EN`), German (`DE`), Simplified Chinese (`ZH`), French (`FR`), and Spanish (`ES`).
* **Mobile Responsive Mode** — Seamless touch-optimized viewport scaling, gesture window dragging, and haptic tactile feedback (`triggerHaptic`).
* **Keyboard Hotkeys**:
  * `Cmd+K` / `Ctrl+K` — Open Spotlight Command Palette
  * `Cmd+L` / `Win+L` — Lock Desktop Workspace
  * `T` — Toggle Hardware Settings Drawer (when appliance hardware present)
  * `Z` or `Mouse Wheel` — Cycle Chassis Zoom scale (1x, 1.25x, 1.5x, 2x)
  * `Y` — Toggle Yak theme aesthetic
  * `Esc` — Close open modals, command palette, and drawers

---

## REST API Reference

All routes are mounted at `/api` (or versioned alias `/api/v1`). Authenticated endpoints accept `Authorization: Bearer <zat_token>` headers, HttpOnly SameSite session cookies, or the `X-ZettNAS-Token` header.

For complete endpoint specifications, parameter schemas, Server-Sent Events (SSE) telemetry contracts, and curl examples, see the dedicated **[REST API Reference (docs/API.md)](docs/API.md)**.

| Category | Highlights | Docs |
| :--- | :--- | :---: |
| **Identity & Multi-User RBAC** | User inventory & roles (`/api/auth/users`), TOTP 2FA setup & verify (`/api/auth/totp/*`), session revocation (`/api/auth/sessions`), scoped API tokens (`/api/tokens`). | [Details](docs/API.md#1-identity-multi-user--rbac) |
| **Telemetry & Live Streaming** | Real-time system metrics snapshot (`/api/stats`), 1 Hz live SSE stream (`/api/stats/stream`), historical time-series graphs (`/api/history`), health probe (`/api/health`). | [Details](docs/API.md#2-telemetry--live-streaming) |
| **Storage & Platform Abstraction (PAL)** | Platform storage pools (`/api/storage/pools`), physical drive inventory (`/api/storage/disks`), bay slot mapping (`/api/storage/bay-slots`), quad-action disk locate strobe (`/api/storage/locate`). | [Details](docs/API.md#3-storage--platform-abstraction-layer-pal) |
| **Docker Orchestration & Compose** | Containers & updates (`/api/docker/containers`, `/api/docker/updates/*`), Compose stack synthesis & editing (`/api/docker/stacks/*`), Web Terminal (`/api/docker/containers/{id}/exec`), 25+ app catalog (`/api/docker/catalog`). | [Details](docs/API.md#4-docker-containers-stacks--app-catalog) |
| **Cloud Remotes & WebDAV** | Universal WebDAV server port 8084 (`/api/webdav/*`), Rclone multi-cloud mounting (`/api/remotes/*`) for 20+ cloud backends (S3, B2, Google Drive, OneDrive). | [Details](docs/API.md#5-remote-cloud-storage--webdav) |
| **Hardware Controls & Fans** | 6-point fan curves & Zero RPM mode (`/api/fans`), WS2812B ARGB lightbar effects (`/api/led`), physical LCD brightness/pages (`/api/lcd/*`), S.M.A.R.T. tests (`/api/disk/*`). | [Details](docs/API.md#6-hardware-controls--diagnostics) |
| **Alerts & Hyper-Backup** | Apprise multi-channel alerts & test dispatch (`/api/notifications/*`), local/cloud snapshot schedules & 1-click restore (`/api/backup/*`), sanitized diagnostics bundle (`/api/system/diagnostics`). | [Details](docs/API.md#7-notifications-hyper-backup--diagnostics) |
| **Media & Filesystem** | Chunked file streaming (`/api/fs/upload`), front SD/TF card auto-detection & SHA-256 verified ingest (`/api/media_slots`, `/api/copy/*`), safe ejection. | [Details](docs/API.md#8-media-ingest--filesystem-management) |

---

## Development & Test Suite

The frontend is built with vanilla modern ES modules and bundled via Vite. The backend is powered by FastAPI, SQLite WAL, and multi-protocol hardware daemons.

### Frontend Workflow
```bash
npm install
npm run build          # Compiles minified production assets to static/
npm test               # Runs full Vitest + JSDOM frontend test suite (40 test files, 256 tests)
npm run test:coverage  # Generates Vitest V8 code coverage report
npm run dev            # Starts local Vite development server with hot module reload
```

### Backend Workflow & Pytest Suite
```bash
# Run full Pytest test suite (422 unit and integration tests)
docker exec -i zettnas-toolkit python3 -m pytest -q /mnt/user/appdata/zettnas-toolkit/tests

# Run code style & formatting checks
ruff check app.py backend tests
ruff format --check app.py backend tests
```

For remote test appliance execution rules and architectural invariants, see **[AGENTS.md](AGENTS.md)**.

---

## Documentation & Guides

* **[Installation & Deployment Guide (docs/INSTALLATION.md)](docs/INSTALLATION.md)** — Step-by-step setup for Unraid, Ubuntu/Debian, FygoOS, TrueNAS SCALE, Docker CLI, device rules, and headless servers.
* **[Developer & AI Agent Guidelines (AGENTS.md)](AGENTS.md)** — Operational blueprint, testing gates, architectural invariants, and remote execution protocols.
* **[REST API Reference (docs/API.md)](docs/API.md)** — Complete endpoint specifications, live SSE telemetry contracts, card reader auto-ingest, and hardware control APIs.
* **[System Architecture (docs/ARCHITECTURE.md)](docs/ARCHITECTURE.md)** — Threading model (`StatsCollector`, `LcdRenderer`, `ButtonListener`, `FanWatchdog`), SQLite WAL persistence, and data flow.
* **[Hardware Protocol Reference (docs/HARDWARE_PROTOCOL.md)](docs/HARDWARE_PROTOCOL.md)** — WS2812B serial packet specifications, sysfs thermal & PWM mappings, and direct `/dev/fb0` memory buffers.
* **[Reverse Proxy & TLS Guide (docs/REVERSE_PROXY.md)](docs/REVERSE_PROXY.md)** — Production configurations for Nginx, Caddy, Traefik, and Nginx Proxy Manager with SSE stream buffering disabled.
* **[Contributing Guidelines](CONTRIBUTING.md)** — Pull request standards, local test environment, and automated test execution.

---

## Acknowledgments & Credits

* **[torharrington/zettlab-display](https://github.com/torharrington/zettlab-display)** — Foundational framebuffer layout experiments for Zettlab front-panel screens.
* **[henryxwong/zettlab-ubuntu](https://github.com/henryxwong/zettlab-ubuntu)** — Comprehensive hardware reverse-engineering of Zettlab registers, fan controller paths, and LED microcontroller protocols.

---

## License

This project is licensed under the [MIT License](LICENSE).

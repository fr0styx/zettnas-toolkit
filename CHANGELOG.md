# ZettNAS Toolkit - Release Changelog

## v1.6.0 (2026-10-10) - Stable
### 🛡️ Universal Multi-User RBAC, Enterprise Notifications, Hyper-Backup & Modern Desktop OS

This landmark release transforms ZettNAS Workbench into an enterprise-ready, cross-platform NAS operating environment. Peer-reviewed across multiple systems engineering disciplines, v1.6.0 introduces an enterprise SQLite-backed Multi-User & RBAC engine, multi-channel alerting with Apprise, 3-2-1 Hyper-Backup and disaster recovery, a universal Platform Abstraction Layer (PAL) with Btrfs/Unraid/ZFS coexistence, an in-place Docker Compose Stack Editor, an interactive visual Network Topology inspector, and deep Desktop OS personalization with macOS-style dock magnification, dynamic hardware detection, and an OLED pure black theme:

- **Enterprise Identity, Multi-User & Granular RBAC (Phases 1–5)**:
  - **SQLite WAL User Store (`users.db`)**: High-performance persistence layer operating in Write-Ahead Logging (WAL) mode for users, roles, sessions, scoped API tokens, and structured security audit logs. Features transparent zero-downtime migration from legacy `security.json` and `sessions.json`.
  - **Argon2id Cryptographic Security**: Upgraded credential hashing to RFC 9106 Argon2id (`m=64MB`, `t=3`, `p=4`) with automated transparent rehash on valid user login.
  - **Multi-Factor Authentication (MFA / 2FA)**: RFC 6238 TOTP implementation with QR provisioning (`otpauth://`), time-drift tolerance, replay attack prevention, and 8 single-use cryptographically hashed recovery codes.
  - **Enterprise SSO & Reverse Proxy Header Auth**: Native support for `X-Forwarded-User`, `Remote-User`, and `X-Forwarded-Email` headers from Authelia, Authentik, Traefik, and Cloudflare Access with trusted subnet validation.
  - **Granular RBAC Scope Taxonomy**: Role-based access control with standard roles (`SuperAdmin`, `StorageAdmin`, `AppOperator`, `BackupOperator`, `ShareUser`, `Auditor`) and granular permission scopes (`system:*`, `storage:*`, `shares:*`, `containers:*`, `users:*`, `hardware:*`, `logs:*`).
  - **Scoped API Tokens & Service Accounts**: Token provisioning with customizable scope matrices, CIDR whitelisting, expiration timestamps, and masked secret previews (`zat_****`).
  - **Desktop UX & Authentication Overhaul**: Dual-mode login screen (User Avatar Chooser vs Classic Mode), 6-digit numeric OTP challenge, acrylic glassmorphic Inactivity Auto-Lock screen (`Cmd+L`), and top-bar user account pill and flyout.
  - **Private Home Isolation & Multi-User WebDAV**: Automatic home directory provisioning (`/mnt/user/homes/<username>`) with 0700 permissions, per-user desktop state synchronization (wallpaper, theme, dock pins), and WebDAV authentication proxy.

- **Universal Storage, Multi-Protocol HAL & Platform Abstraction Layer (PAL)**:
  - **Multi-Protocol S.M.A.R.T. Engine**: Universal drive diagnostics supporting SATA (`-d sat`), NVMe (`-d nvme`), SAS (`-d scsi`), and USB bridge enclosures (`-d sntrealtek`, `-d sntjmicron`).
  - **ATA Zero-Wake Spindown Safeguard**: Uses `smartctl -n standby` to query telemetry and temperatures without waking sleeping hard drive platters.
  - **Virtual Block Device Filtering**: Automatically filters out zram, loop devices, and zero-byte virtual blocks from physical disk discovery.
  - **Dynamic 2.5D Parametric Chassis Visualizer**: Dynamically models custom drive counts and backplanes beyond fixed 4/6/8 bay enclosures. Includes an interactive Bay Slots Mapping modal for drag-to-reorder disk identification and quad-action locate strobe.
  - **Platform Abstraction Layer (PAL)**: Dynamic coexistence between Unraid array management and generic Linux storage engines (Btrfs RAID 0/1/5/6/10, mdadm, and ZFS).
  - **Samba Port 445 Paradox Resolution**: Automatically probes port 445; acts as Host Share Auditor on appliance hosts (Unraid/TrueNAS) or provisions active Samba sidecars on Generic Linux.
  - **Universal WebDAV & Rclone Multi-Cloud Gateway**: Zero-conflict WebDAV file server (Port `8084`) and Rclone cloud engine supporting 20+ remote providers (S3, Backblaze B2, Google Drive, Dropbox) directly browseable in File Explorer.

- **Enterprise Multi-Channel Notifications & Alert Routing**:
  - **Unified Apprise Integration**: Native dispatch across Discord (webhooks), Telegram (bot token & chat ID), Email/SMTP (TLS/SSL auth), ntfy (topics & self-hosted servers), Pushover, Gotify, generic webhooks, and raw Apprise URLs.
  - **Mission Control Setup Wizards**: Dedicated `#mgmt-pane-notifications` tab with visual channel cards, active/disabled status badges, 1-click in-place test dispatches, and secret masking.
  - **Dock Notification Center Deep-Link**: Quick header gear button in the Dock's notification flyout linking straight to notification channel settings.
  - **Granular Alert Triggers & Thresholds**: Configurable event rules for S.M.A.R.T. degradation velocity, hard drive and CPU thermal ceilings, fan stalls, UPS power interrupts, container events, and backup status.

- **Hyper-Backup & Disaster Recovery Subsystem**:
  - **3-2-1 Backup Engine**: Automated pipeline supporting local filesystem snapshots and off-site cloud replication via Rclone.
  - **Automated Scheduling & Pruning**: Configurable cron schedules with automated retention policies (hourly, daily, weekly, monthly prune).
  - **1-Click Snapshot Rollback**: Instant filesystem snapshot restoration with transactional safety.
  - **Sanitized Backup Archives**: System configuration exports with automatic exclusion of credentials, API tokens, and sensitive keys.

- **Docker Containers, Compose Stacks & App Catalog**:
  - **Top-Level Mission Control Menu**: Elevated "Apps & Containers" to a primary top-level sidebar menu item with live running container count badges.
  - **In-Place Compose Stack Inspector & Editor**: Interactive editor for `docker-compose.yml` stacks and container configurations with syntax highlighting, validation, and live restart triggers.
  - **Native UI Dialogs & Stack Picker**: Custom glassmorphic modals replacing native browser `prompt()` and `confirm()` dialogs.
  - **Container Mutator & Update Engine**: Clickable container update badges, individual container updates, and "Update All" with automatic image pull, recreate, and rollback protection.
  - **Docker Cleanup & External Templates**: URL-encoded Docker prune filters and support for external app templates (Portainer, Lissy93).

- **Visual Network Topology & Virtual Switch Inspector**:
  - **Interactive Network Interface Cards**: Visual SVG cards for physical interfaces, virtual bridges, and bonding interfaces (`bond0`) with live link speeds, MTU, duplex, and IPv4/IPv6 addresses.
  - **Real-Time Throughput Sparklines**: Keyed zero-flicker table reconciler and SVG throughput graphs for live RX/TX network traffic.

- **Structured Diagnostics & Correlation Tracing**:
  - **Structured JSON Logging**: Uniform JSON logging with UUID `x-correlation-id` request tracing across all API endpoints, SSE streams, and background daemons.
  - **1-Click Anonymized Diagnostics Bundle**: One-click download of sanitized system diagnostics with automatic redaction of passwords, tokens, public IPs, and user hashes.

- **Desktop OS Personalization & UX Polish**:
  - **Visual Wallpaper Gallery Grid**: Thumbnail grid with lazy loading, active wallpaper indicators, drag-and-drop file ingestion, and custom modal for rename/delete.
  - **Parabolic Dock Magnification**: Smooth macOS-style magnification on hover, configurable dock positioning (Bottom, Left, Right), and dynamic desktop workspace bounds.
  - **Acrylic Glassmorphism Controls**: Sliders for blur strength, opacity, and specular highlights (disabled by default for clean contrast).
  - **Themes & Instant Yak Switching**: Cyber Teal, Amber CRT, Emerald Matrix, Sapphire Ice, Amethyst, Crimson, Yak Bronze, and Pure OLED Black (`theme-oled`). Instant wallpaper switch to Yak wallpaper when Yak theme is selected.
  - **Desktop Shortcuts & Context Menu**: Right-click desktop workspace menu with deduplication and alignment tools; custom desktop shortcuts for Containers, Storage, and Activity Monitor.

- **Dynamic Hardware HAL & Custom Chassis Features**:
  - **Dynamic Hardware Settings Button**: Automatically detects whether host has custom appliance hardware (Physical LCD panel `/dev/fb0`, front copy button, SD/TF card slot as on ZETTLABS D6U / Aoostar WTR) vs generic servers, intelligently hiding unsupported menus.
  - **Dynamic MCU & FB Status Badges**: Top-bar MCU (`/dev/ttyACM0`) and FB (`/dev/fb0`) status badges automatically hide if the physical peripheral is not connected.
  - **Universal Card Re-ordering**: Card locking and drag-to-reorder now works universally across all 4 drawer tabs (Dashboard Layout, LED Strip Bar, Fans, Copy Button).

## v1.5.0 (2026-10-08) - Stable
### 🚀 Master UI/UX Evolution & System Hardening (Phases 1–5 Complete)

This major production release elevates ZettNAS Workbench into the premier homelab and NAS operating experience. It delivers next-generation desktop window management, physical chassis digital twins, a curated 25+ container app catalog, in-browser container execution terminals, a universal Spotlight command palette (`Cmd+K`), and a mobile PWA touch experience with zero bundle bloat and complete hardware/OS agnosticism:

- **Phase 1: Core Desktop OS & Window Gestures**:
  - **8-Zone Aero Snap & Acrylic Lens**: Unified pointer capture window tiling supporting edge halves and 4 corner quarters with acrylic translucent snap preview ghost (`#window-snap-ghost`).
  - **Snap Assist Hover Flyout**: Hovering over the maximize button reveals interactive quick-tile layouts (Left/Right half, Full, Top/Bottom split).
  - **A11y & Visual Contrast Overhaul**: WCAG 2.2 AA compliant focus rings adapting across all 7 desktop themes + new `theme-oled` Pure Black theme. Added live `#a11y-live-announcer` screen reader notifications for window snapping and docking operations.

- **Phase 2: Physical Chassis & Storage Visualizer**:
  - **Parametric 2.5D SVG Chassis Digital Twin**: Dynamically models Zettlab D4 (4-bay), D6 (6-bay), D8 (8-bay), and DIY enclosures with live bay drive presence, model tags, and spindown platter animations.
  - **Thermal Heatmap Engine**: Per-bay color-coded heatmaps based on live disk temperature sensors.
  - **Quad-Action "Locate Drive" Strobe**: Non-destructive physical disk locator triggering drive read activity pulses, chassis ARGB alerts, and zero-asset Web Audio high-visibility sonic chirps.
  - **30-Day S.M.A.R.T. Degradation Velocity Sparklines**: Historical degradation trends (reallocated sectors, pending sectors, NVMe wear) embedded into drive diagnostics with predictive health warnings.

- **Phase 3: Container App Catalog & Web Terminal**:
  - **Curated 25+ Homelab App Catalog**: Built-in 1-click application templates spanning Media (Jellyfin, Plex, Emby, Audiobookshelf, Calibre-web), Cloud & Photos (Immich, PhotoPrism, Nextcloud), Automation (Home Assistant, Node-RED, Scrypted, Zigbee2MQTT), Utilities (Vaultwarden, Pi-hole, AdGuard Home, NPM, Uptime Kuma), and Downloads (Radarr, Sonarr, Prowlarr, Bazarr, qBittorrent, Transmission, SABnzbd).
  - **Pre-flight Port Conflict Resolver**: Probes host sockets and container listeners, automatically recommending the next free host port on conflict with live Docker Compose synthesis.
  - **In-Browser Container Web Terminal**: Interactive terminal tab in the Container Inspector modal allowing live shell execution (`/bin/sh` / `/bin/bash`), command history (`Up`/`Down` arrows), and clean terminal output streaming.

- **Phase 4: Spotlight Universal Command Palette & Desktop Workspace**:
  - **Universal Command Palette (`Cmd+K` / `Ctrl+K`)**: Floating glassmorphic spotlight search across applications, active Docker containers, storage browse roots, and hardware quick-actions (`>reboot`, `>spindown`, `>quiet fans`, `>turbo`, `>theme oled`, `>theme cyber`, `>refresh`).
  - **Desktop Lasso Marquee Selection**: Click-and-drag desktop wallpaper marquee selection with boundary intersection detection for desktop icons.
  - **Desktop Context Menu**: Right-click desktop menu featuring Command Palette (`Cmd+K`), Mission Control, File Explorer, Refresh, Align to Grid, and Sort by Name.

- **Phase 5: Mobile PWA, Responsive Touch & Haptics**:
  - **Mobile PWA Capabilities**: Full standalone web app manifest (`manifest.json`) and mobile viewport optimization for mobile home screen installation.
  - **Tactile Touch Haptics Engine (`triggerHaptic`)**: Subtle tactile vibration feedback on window snapping, toast notifications, and interactive controls via `navigator.vibrate()`.
  - **Comprehensive Production Certification**: 100% test pass rate across 295 Pytest backend tests and 110 Vitest frontend tests.

- **Production Audit & System Hardening (Batches 1–5)**:
  - **API Token SHA-256 Hashing**: Stored tokens are cryptographically hashed using SHA-256 with opaque UUID identifiers. `GET /api/tokens` returns masked secrets (`zat_****`) and UUIDs, preventing token leakage. Added automated legacy plaintext token migration and constant-time digest verification.
  - **Symlink Path Containment**: Hardened `_safe_fs_target` and `fs_upload` with strict `resolve_within` canonicalization across `ALLOWED_BROWSE_ROOTS`, rejecting symlink escapes with HTTP 403.
  - **Zip Slip & Zip Bomb Protection**: Reinforced `restore_backup_archive` with symlink rejection (`0o120000`), a 50MB decompression limit, a 1000-member limit, and Python 3.12 `filter="data"`. Excluded `api_tokens.json` from backup exports.
  - **Trusted Proxy CIDR Enforcement**: Restricted Uvicorn `forwarded_allow_ips` from wildcard `*` to `TRUSTED_PROXIES` (defaulting to local loopback `127.0.0.1`), preventing brute-force lockout spoofing.
  - **Auth Rate-Limiter Pruning**: Added automatic TTL expiry pruning to `_failures` dictionary to prevent unbounded memory growth from IP brute-force attempts.
  - **Headless Server Deployment Safety**: Removed mandatory `--device=/dev/fb0` and `--device=/dev/dri` from default Unraid XML template `<ExtraParams>`, preventing container boot crashes on headless hosts.

- **Batch 2: Thermal Safety & Hardware Engine Stabilization**:
  - **Sensor Fault Failsafe Duty**: Hardened `calc_curve_pwm()` in `fans.py` to return `FAN_FAILSAFE_PWM` (150/183 duty cycle, ~82%) whenever sensor readings are missing, None, or invalid, preventing thermal runaway on sensor bus faults.
  - **Synchronous UPS Failsafe Sync**: Joined the filesystem flush worker thread with a strict 10.0s timeout before signaling `_signal_host_powerdown()`, guaranteeing page cache commit before shutdown.
  - **Zero RPM Gating for Under-Populated & All-Flash Arrays**: Fixed Zone 2 lockout when fewer than 5 disks are present (`zone2_disks == []`) and enabled NVMe temperature-based Zero RPM for all-flash arrays (`sata_disks == []`). Added default NVMe cooling ramp (50°C -> 95 PWM, 75°C -> 183 PWM).
  - **Framebuffer Deferred-I/O Synchronization**: Added explicit `fb_mem.flush()` after mmap framebuffer byte copies in `lcd_renderer.py` for tear-free output on Linux deferred-I/O displays.
  - **SMART Velocity Time Delta Validation**: Prevented false-positive stuck pending sector alarms by requiring at least 2 readings spanning $\ge 44$ hours. Integrated NVMe wear percentage and media integrity errors into velocity scoring.
  - **UPS Prober Gateway Network Scoping**: Constrained Docker gateway socket probe to private Docker bridge subnets (`172.16.0.0/12`), preventing port 3551/3493 probes to LAN routers in host networking mode.

- **Batch 3: Backend Concurrency & Database Resilience**:
  - **Event Loop Decoupling**: Offloaded cold-boot `collect()` in `stats.py` to `asyncio.to_thread(collect)` to eliminate event loop blocking during initial SSE connections. Offloaded file deletion, backup archive extraction, and wallpaper image writes to worker threadpools.
  - **SSE Telemetry Connection Throttling**: Introduced `MAX_SSE_SUBSCRIBERS = 32` capacity check with HTTP 429 response, preventing client tab proliferation from exhausting Uvicorn worker pools.
  - **Decoupled Global State Lock from Disk fsync**: Cloned the event log inside `Z_STATE.lock` and executed `atomic_write_json(EVENTS_FILE)` outside the mutex in `add_event()`, ensuring the 1-second fan PWM loop never stalls on storage I/O wait.
  - **SQLite Connection & WAL Pragma Optimization**: Configured `busy_timeout=15000` (15s) in `get_db_connection()`, eliminated redundant per-connection `PRAGMA journal_mode=WAL` executions, and established connection reuse in `query_smart_velocity` and `query_all_smart_velocities`.
  - **Graceful Daemon Shutdown Lifecycles**: Updated `stats_collector_daemon`, `smart_poller_daemon`, `fan_watchdog_daemon`, and `_docker_telemetry_worker` to exit cleanly on `Z_STATE.shutting_down` with responsive sleep intervals and guaranteed socket cleanup.

- **Batch 4: Container Orchestration & DevOps Reliability**:
  - **Container Mutator Self-Termination Protection**: Added pre-flight check in `container_mutator.py` that inspects container hostname and image identifiers, rejecting recreation of `zettnas-toolkit` with HTTP 400.
  - **Dual-Stack Host Port Conflict Detection**: Upgraded `check_port_available()` to inspect host procfs socket tables (`/host/proc/net/tcp`, `/host/proc/net/tcp6`, `/proc/net/tcp`) for active listeners in addition to container socket binding.
  - **Compose Synthesizer Runtime Mount Filtering**: Filtered internal Docker runtime mounts (`/etc/resolv.conf`, `/etc/hostname`, `/etc/hosts`, `/dev/shm`) from synthesized OCI Compose files, preventing deployment conflicts.
  - **TTY Container Log Stream Decoding**: Added raw line-stream fallback in `get_container_logs_chunk` for containers running with `Tty: true` without 8-byte multiplexed headers.
  - **CI/CD Action Pinning**: Pinned verified stable GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`, `docker/build-push-action@v6`) across `.github/workflows/ci.yml`.
  - **Multi-Arch Dockerfile Assets**: Added `libgl1-mesa-dri`, `mesa-va-drivers`, `fonts-noto-cjk`, and `fonts-noto-color-emoji` to prevent tofu glyphs (`□□□`) on physical LCD displays and enable hardware acceleration.

- **Batch 5: Frontend Desktop OS & UX Excellence**:
  - **Background Tab Telemetry Stalling Bypass**: Updated `frontend/src/event-bus.js` to bypass `requestAnimationFrame` coalescing when `document.hidden` is true, ensuring continuous background telemetry ingestion.
  - **Eliminated Synchronous Layout Thrashing**: Replaced `el.innerText` with layout-independent `el.textContent` in `a11y.js` `enhanceInteractiveElements()`, eliminating layout reflow thrashing inside `MutationObserver`.
  - **Container Inspector Window Layering**: Added `container-inspector-window` to `isDesktopApp` whitelist in `dock.js`, integrating it into dynamic desktop window z-index layering.
  - **Pointer Events Touch Window Dragging**: Upgraded window dragging in `dock.js` to unified Pointer Events (`pointerdown`, `pointermove`, `pointerup`, `pointercancel`, `setPointerCapture`), enabling smooth touchscreen window dragging.
  - **In-Memory Secret Handling**: Replaced plain DOM attributes (`data-raw`, `data-val`) in `container-modal.js` with an in-memory JavaScript `Map`, keeping credentials strictly out of DOM inspection.
  - **Monotonic Fan Curve Constraints**: Enforced monotonic PWM constraints (`p = Math.max(p, pts[dragIndex - 1][1])`) in `fan-control.js` to prevent inverted curve configurations.
  - **CSS Token Scoping**: Implemented hierarchical custom properties (`--desktop-accent`, `--desktop-ok2`, `--lcd-accent`, `--lcd-ok2`) and isolated `#screen`, `#console-window`, and `#mini-lcd-canvas`, ensuring desktop appearance accent changes never bleed into the physical LCD or console display.
  - **Test Suite Expansion**: Added unit and integration test suites across all 5 batches, achieving 100% pass rates across 286 Pytest backend tests and 85 Vitest frontend tests.

## v1.4.3 (2026-10-08) - Stable
### 🐳 Enterprise Container Orchestration (Dynamic Compose Synthesizer, Live Logs, Atomic Port Reconfig & Zero-Downtime Resource Tuning) & Strict Theme Isolation

This major release introduces a hardware- and OS-agnostic container management layer, peer-reviewed by an independent Principal Systems Architect. It empowers users to inspect, reverse-engineer Docker Compose configurations, modify published ports atomically with rollback protection, stream multiplexed logs, tune resources on running containers with zero downtime, and enjoy completely decoupled styling between the physical LCD screen and desktop web workspace:

- **Hardware-Agnostic & OS-Agnostic Architecture (HAL & PAL)**:
  - **Dynamic Hardware Abstraction Layer (HAL)**: Added dynamic device detection across hardware vendors without hardcoded chipset paths. Automatically surfaces badges for Intel GPU (`[GPU]`, i915 / Intel Xe), AMD GPU (`[ROCm]`, amdgpu), NVIDIA GPU (`[NVIDIA]`, NVIDIA Container Runtime), and Google Coral Edge TPU (`[TPU]`).
  - **Pure Docker Engine API Compliance (PAL)**: Runs 100% through the standard Docker daemon socket (`/var/run/docker.sock` or TCP socket) without host shellouts, `sudo`, or external CLI dependencies. Operates seamlessly on Debian, Ubuntu, TrueNAS SCALE, Proxmox VE, Arch Linux, Alpine, and Unraid OS.
  - **Stack Classification**: Automatically detects and groups containers by OCI Compose v2 labels (`com.docker.compose.project`), Unraid template metadata, and standalone definitions.
- **Dynamic Docker Compose Synthesizer (OCI Compose Spec v3.8+)**:
  - **Reconstruction Engine** (`backend/services/compose_synthesizer.py`): Synthesizes valid, standardized `docker-compose.yml` definitions directly from container inspect metadata for any container—regardless of whether it was created via Compose, Unraid webGUI, or `docker run`.
  - **Secret Masking & Privacy**: Automatically detects and redacts sensitive environment variables (`PASSWORD`, `SECRET`, `KEY`, `TOKEN`, `CREDENTIAL`, `AUTH`) as `********` by default, complete with an interactive UI reveal toggle, one-click `📋 Copy YAML`, and `⬇️ Download .yml` buttons.
  - **Preserves Critical Directives**: Faithfully reconstructs volume binds, named mounts, published port formats, network links, restart policies, capabilities, devices, and health checks.
- **Atomic Port Reconfiguration Engine & Pre-flight Conflict Checker**:
  - **Pre-flight Socket Validation** (`GET /api/docker/check_port`): Tests socket availability across IPv4 (`0.0.0.0`) and IPv6 (`::`) before modifying container state, actively preventing port binding collisions.
  - **Transactional Clone-and-Recreate** (`backend/services/container_mutator.py`): Safely snapshots existing container state, gracefully stops the container, renames it to a backup tag, spins up the replacement container with updated `HostConfig.PortBindings`, and verifies healthy execution.
  - **Automated Rollback Protection**: Automatically rolls back to the original container and restores its active state if container recreation or startup encounters an error, guaranteeing zero orphaned configurations or service interruption.
- **Zero-Downtime Live Resource Tuning**:
  - **Live Cgroup Hot-Reloading**: Dynamically adjusts memory limits (`Memory`) and CPU core quotas (`NanoCPUs`) on running containers via `POST /api/docker/containers/{id}/resources` with zero downtime or service restart.
- **Multiplexed Live Logs Console**:
  - **8-Byte Frame Multiplexer**: Decodes Docker socket streams natively, accurately separating stdout (Stream Type 1) and stderr (Stream Type 2).
  - **Interactive Terminal View**: Real-time log streaming with configurable tail depth (50, 100, 200, 500, 1000 lines), live keyword search filtering, auto-scroll tracking, color-coded stream output (cyan timestamps, red stderr, clean stdout), and one-click clipboard export.
- **Tabbed Container Inspector Modal**:
  - **Comprehensive Diagnostics**: Tabbed workstation (`Overview`, `Ports & Web`, `Mounts & Storage`, `Environment`, `Docker Compose`, `Live Logs`).
  - **Storage Deep-Links**: One-click "Reveal in File Explorer" button for host volume mounts, deep-linking directly into the desktop File Explorer.
  - **WebUI Auto-Discovery**: Identifies published HTTP/HTTPS service ports (`80`, `443`, `8080`, `8096`, `3000`, `2283`, etc.) and renders clickable `[ 🌐 :PORT ↗ ]` buttons that dynamically resolve using the browser's active host address.
  - **Container Table Enhancements**: Live CPU and RAM metric badges, instant search filter, and stack filter pills (`All`, `Running`, `Stopped`, `Compose`, `Standalone`).
- **Strictly Isolated Theme Architecture: Desktop Theme vs. LCD Screen Themer**:
  - **Decoupled Styling Cascades**: Eliminated theme bleed where desktop accent changes affected the physical front-panel screen (`/dev/fb0`), LCD Live Canvas, or System Console.
  - **Appearance Sub-Tab**: Relocated "Desktop Theme & Accent Color" into Mission Control -> Appearance with aligned preset names (Cyber Teal, Amber Gold, Emerald Matrix, Sapphire Ice, Amethyst Violet, Crimson Ruby, Daylight White, Yak Bronze).
  - **Daylight White Contrast Tuning**: Refined the Daylight White LCD theme with crisp high-contrast dark typography and dark grayish element card styling for optimal legibility.
- **Test Suite Expansion & CI Verification**:
  - Added unit test suites for `container_mutator.py` (7 tests), `compose_synthesizer.py` (10 tests), and `docker_stats.py` HAL enrichment (5 tests).
  - Added Vitest frontend test suites for `container-modal.js` (8 tests) and container table management (3 tests).
  - 100% CI pass rate: 265 Pytest tests, 82 Vitest tests, Ruff format and lint checks, and 958ms production static assets build.

## v1.4.2 (2026-10-08) - Stable
### ❄️ Zero RPM HDD Standby Fan Mode & Dynamic Thermal Safety Architecture (GitHub Issue #13)

This release delivers the complete implementation of **Zero RPM Fan Mode** for hard drive bay exhaust fans when drives are spun down in standby, coupled with fail-safe thermal watchdogs, chassis wind-tunnel overrides, and BLDC motor anti-stall protection:

- **BLDC Motor Stiction & Stall Protection**:
  - **Strict Binary Cutoff**: Enforced binary duty cycle clamping in `backend/hardware/fans.py` (`0` or `58..183` PWM) to eliminate motor buzzing, electrical stall currents, and bearing wear within the 1–57 PWM deadband.
  - **2.0s Kickstart Pulse**: Added non-blocking initial `150 PWM` (~82%) burst upon any transition from stopped (`0`) to spinning (`> 0`) to overcome rotor static friction.
  - **Absolute CPU Fan (`pwm3`) Invariance**: CPU cooling fan is unconditionally excluded from Zero RPM mode under all conditions, maintaining continuous active cooling.
- **Chassis Topology & Thermal Overrides**:
  - **Chassis Topology Awareness**: D4 chassis requires all 4 bay drives to be spun down before stopping its single rear exhaust fan. D6U and D8 chassis support independent spindown per zone (Zone 1: bays 1–4, Zone 2: bays 5+).
  - **NVMe Wind-Tunnel Override**: Automatically revokes Zero RPM across all bay fans if any M.2 NVMe SSD reaches $\ge 50^\circ\text{C}$ (`zero_rpm_nvme_ceiling`) to preserve critical convective airflow.
  - **Continuous 180s Anti-Flutter Delay**: Requires 180 continuous seconds of cold temperatures and disk standby before cutting fan power, preventing rapid acoustic cycling.
  - **Storage Subsystem Interlock**: Active Unraid `mover` or `parity_check` operations automatically prevent fan shutdown.
  - **Intelligent Stall Watchdog Suppression**: Tachometer stall monitor suppresses false-positive 0 RPM alarms during intentional Zero RPM standby and within the 6.0s spinup grace window.
- **Frontend Workstation & Multilingual UI**:
  - **SVG Fan Curve Workstation**: Realigned graphical floor coordinate system ($Y=104$ at $0\%$, dashed threshold line at $Y=77$ for $32\%$ minimum reliable spin). Interactive sliders snap cleanly out of the deadband.
  - **Accurate Thermal Mapping & Granular Axis**: Re-anchored SVG temperature axis across 5 granular positions ($30^\circ\text{C}$, $37.5^\circ\text{C}$, $45^\circ\text{C}$, $52.5^\circ\text{C}$, and $60^\circ\text{C}+$) with vertical guide gridlines. Fixed CPU dot coordinate projection to use `tempToX()` identically with disk dots, eliminating coordinate distortion.
  - **6-Point Dynamic Curve Controls**: Expanded interactive SVG fan curve from 4 to 6 control points (`ch-0` through `ch-5`) with automatic linear midpoint interpolation (`expandTo6Points`), boundary locking at $30^\circ\text{C}$ and $60^\circ\text{C}$, and full multi-touch/mouse drag support.
  - **Calm Ice-Cyan Status Badges**: Stopped fans in Zero RPM mode display `0 (PASSIVE)` with `#38bdf8` styling across dashboard cards, drawers, and LCD previews.
  - **Fan Drawer Streamlining & Header Integration**: Removed obsolete static "Thermal Threshold Inspector" and redundant "Custom Ramp Temperatures" cards (~260px vertical drawer reduction). Placed the dynamic ramp range badge (`#fan-curve-range-val`) directly into the interactive curve legend row alongside live telemetry readouts, preserving clean single-line headline alignment for the card title and `HOLD: READY` badge without text wrapping or wasted space.
  - **Contextual Event Detail Action Routing**: Re-engineered the action button and subsystem classifier in the Event Detail modal (`modals.js`). SD Card and media slot events (`SD Card Ejected`, `SD Card Inserted`, `TF Card Inserted`, `Media Ingest`, `Auto-Ingest Started`) now display the `MEDIA & INGEST` subsystem and feature a direct `Open Media Card Settings` action that opens the drawer's Copy Button & Media Slots tab (`tab-buttons`). Added dedicated associations across all subsystems: ARGB Lightbar (`tab-led`), File Explorer & Recycle Bin (`file-manager-window`), Security & Tokens (`mgmt-pane-security`), Power & UPS (`mgmt-sec-ups`), Unraid Array (`mgmt-pane-unraid`), System Console (`console-window`), and Wallpaper/Theme (`mgmt-pane-wallpaper`), complete with multilingual translations across 5 languages.
  - **Multilingual i18n**: Added complete translations for Zero RPM controls and descriptions across English, German, French, Spanish, and Simplified Chinese.
- **Desktop Window Management & Stacking Hierarchy**:
  - **Dynamic Stacking Order**: Refactored `bringToFront()` in `dock.js` so desktop application windows (ZettNAS System Console, Mission Control, File Explorer, Notification Center) utilize standard dynamic z-index stacking (`1000..4900`), seamlessly alternating foreground elevation on click or focus.
  - **Overlay Stacking Synchronization**: Synchronized parent overlay wrappers (`#console-modal-overlay`, `#management-modal-overlay`) with active desktop window elevation, preventing the Console from remaining persistently pinned over newly opened applications.
  - **Slide Drawer & Modal Layer Separation**: Enforced strict layer boundaries where the Hardware Settings slide drawer (`z-index: 7100`) smoothly renders above all open desktop windows, while true modal dialogs (S.M.A.R.T. diagnostics, Setup Wizard, Fan Preset modals) retain modal protection at `9000/9100`.
- **Configuration & Deployment Templates**:
  - **Generic Host IP in `.env.example`**: Replaced specific local host IP with generic RFC 1918 example address (`192.168.1.100`) for seamless new-user setup and documentation privacy.
  - **Generic UI Placeholders in Mission Control**: Sanitized static Unraid subsystem cards in `frontend/index.html` to display neutral placeholders (`NAS`, `Unraid OS`, `–`) prior to live telemetry arrival.
  - **Configurable CI Verifier**: Parameterized remote host and path variables (`ZETTNAS_SSH_HOST`, `ZETTNAS_REMOTE_DIR`) and added local Docker fallback in `scripts/verify_ci.sh`.
  - **Generic Test Fixtures**: Updated mock Unraid telemetry fixtures in `tests/test_unraid_telemetry.py` to use generic `ZettNAS` hostname.
- **Unified Configuration Backup & Client Customization Sync**:
  - **Eliminated Duplicate Stub Card**: Removed legacy un-wired "Suite Configuration Backup" stub card from the Dashboard Layout drawer (`tab-layout`) in `frontend/index.html`.
  - **Single Consolidated Backup System**: Centralized all suite configuration export and import controls into Mission Control -> System Settings & API (`mgmt-pane-system`).
  - **Server-Synced Client Customizations**: Added `GET /api/system/client-preferences` and `POST /api/system/client-preferences` backed by atomic persistence to `client_preferences.json` inside `DATA_DIR`.
  - **100% Comprehensive Backup Coverage**: Backup archives now bundle all server hardware configurations (`fan_state.json` 6-point curves and Zero RPM settings, `led_state.json` ARGB profiles, `screen_state.json`, `button_state.json`, `notifications.json`, `wallpaper_config.json`, `wallpapers/`, `security.json`, `api_tokens.json`) AND all client desktop customizations (`zettnas_desktop_widgets_config`, `zettnas_win_bounds`, `zettnas_dock_pinned_v1`, `lcd_theme`, `zettnas_language`, `zettnas_collapsed_cards`, `zettnas_layout_lock`, `zettnas_layout_sections_order`).
  - **Seamless Restore & Client Hydration**: Restoring a backup zip automatically hydrates restored preferences directly into browser `localStorage` before initiating an automated reload. Added cross-device hydration on uninitialized browser sessions.
- **Relocated Language & Localization to Mission Control Appearance**:
  - **Drawer Decluttering**: Removed "Display Language & Localization" (`data-layout-card-id="sec-language"`) from the Dashboard Layout drawer (`tab-layout`), keeping the drawer dedicated strictly to physical dashboard module sizing, presets, and live arrangement.
  - **First-Class Appearance Sub-Tab**: Added a dedicated "Language" sub-tab (`mgmt-pane-language`) within Mission Control -> Appearance alongside Wallpaper and Widgets.
  - **Bi-Directional State Synchronization**: Fully registered `mgmt-pane-language` in `management.js` (`SUBPANE_MAP`) and wired `#mgmt-lang-select` (`.language-picker-select`) to automatically synchronize across the suite navbar header, command palette, and Mission Control in English, German, French, Spanish, and Simplified Chinese.
- **Strictly Isolated Theme Architecture: Desktop Theme vs. LCD Screen Themer**:
  - **Desktop Theme Workstation (Mission Control -> Appearance)**: Moved the full desktop theme customization workstation to a dedicated "Desktop Theme" sub-tab (`mgmt-pane-theme`) in Mission Control. Offers 8 presets (Cyber Teal, Amber Gold, Emerald Matrix, Sapphire Ice, Amethyst Violet, Crimson Ruby, Daylight White, and Yak Bronze), quick color chips, hex picker, and reset button. Updates the web desktop, windows, dock, and notification center without altering the physical front-panel screen or console canvas.
  - **Compact LCD Screen Themer (Dashboard Layout Drawer)**: Replaced the layout drawer card with a sleek, dedicated "LCD Screen Theme" card (`sec-lcd-theme`) featuring 8 compact color chips, custom accent picker, and "High-Contrast Text on Physical Screen" toggle. Modifies `--brand`, `--ok2`, and `lcd-theme-*` specifically scoped to `#screen`, `#mini-lcd-canvas`, and direct LCD framebuffer renderers without touching the web desktop.
  - **Strict CSS Isolation**: Scoped palette variables (`--bg`, `--card`, `--fg`, `--brand`, `--ok2`) directly onto `#screen` and `#mini-lcd-canvas`, breaking stylesheet cascading from `body.theme-*`.
  - **Independent Server Persistence**: Persists web workstation preferences under `desktop_theme` and `desktop_custom_accent`, while physical display settings are stored under `lcd_theme`, `lcd_custom_accent`, and `lcd_text_clarity`.
  - **Headless Framebuffer Renderer Isolation**: Playwright renderer in `mode=lcd` listens exclusively to `lcd_theme` SSE events and synchronizes the physical screen without being affected by desktop theme toggles.
- **Automated Verification**:
  - 8 new integration tests in `tests/test_zero_rpm_integration.py`, 3 new tests in `tests/test_audit_batch2.py`, and 27 frontend tests across `zero_rpm_fan_control.test.js`, `backup_system.test.js`, `theme_customization.test.js`, and `batch9_frontend_hardening.test.js`.
  - Full suite verification: 243/243 backend pytest tests and 71/71 frontend Vitest tests passing with 100% success rate.

## v1.4.1 (2026-10-07) - Stable
### 🛡️ Enterprise Subsystems Hardening, Safety Watchdogs, Container Lockdown & Telemetry Modernization (Audit Batches 7–10)

This release delivers the full implementation of the peer-reviewed Enterprise Production Audit roadmap across hardware safety, container isolation, access control, front-end architecture, and performance:

- **Critical Hardware & Systems Safety (Batch 7)**:
  - **Inviolable Thermal Watchdog**: Clamped fan curve calculation to full hardware PWM (`183`) at $\ge 80^\circ\text{C}$ with a $74^\circ\text{C}$ release hysteresis in `backend/hardware/fans.py`, overriding any flat custom curves during emergency thermal events. Added `cpu_temp >= 85°C` to critical override rules.
  - **SQLite Connection & Transaction Safety**: Implemented `@contextmanager def db_session()` in `backend/db.py` with `check_same_thread=False`, auto-commit, explicit rollback on errors, and guaranteed connection teardown, refactoring all 8 database callers.
  - **LCD Renderer Termination Invariance**: Bound Chromium browser supervisor loop in `backend/services/lcd_renderer.py` to `Z_STATE.shutting_down` with clean process termination to eliminate zombie process respawns during host shutdown.
  - **Non-Blocking UPS Emergency Sync**: Offloaded blocking `os.sync()` calls during critical UPS failsafes to background daemon threads to prevent ASGI event loop stalls.
- **Enterprise Security Hardening & Container Lockdown (Batch 8)**:
  - **Explicit Device Cgroups**: Removed wildcard device cgroup rules (`c *:* rwm`, `b *:* rwm`) in `docker-compose.yml`, strictly isolating container access to designated framebuffers (`29:*`), DRI (`226:*`), serial (`188:*`, `166:*`), SCSI/SATA (`8:*`), and NVMe (`259:*`).
  - **Host Sysfs Masking**: Added read-only `tmpfs` masks over `/host/sys/firmware` and `/host/sys/kernel/debug` to prevent host kernel exposure while preserving necessary `/host/sys/class/hwmon` and backlight controls.
  - **In-Memory Auth & Token Cache**: Replaced blocking disk reads with an in-memory session/token cache validated via file modification timestamps (`st_mtime_ns`) protected by `threading.RLock()`, mitigating disk I/O exhaustion DoS attacks on invalid token sweeps.
  - **Timing Attack Mitigation**: Replaced standard equality string comparisons with constant-time `hmac.compare_digest` across all session tokens and API keys.
  - **ASGI Security Headers**: Injected standard HTTP security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`).
- **Frontend Architecture, UX & Accessibility Compliance (Batch 9)**:
  - **WCAG 2.1 AA Accessibility Remediation**: Stripped raw `el.className` fallbacks from automated aria-label generation in `frontend/src/a11y.js`, formatting semantic labels from `data-title`, inner text, or formatted `data-action`, and applying `aria-hidden="true"` to purely visual decorative icons.
  - **Full-Spectrum Theme Tokens**: Defined comprehensive CSS design tokens for `theme-amber` (CRT monochrome phosphor) and `theme-emerald` (cyberpunk matrix green) with high-contrast `theme-light` support in `frontend/src/style.css` and added Cmd+K quick-switch actions.
  - **Window Z-Index & Modal Stacking**: Guarded modals and backdrops from being assigned window-level z-indices (`--z-modal: 9100`), and implemented linear re-normalization when stacking reaches $\ge 4900$ to prevent z-index exhaustion.
  - **Scoped Event Bus Registry**: Added `createScope()` to `ZettEventBus` for bulk event listener teardown on component destruction, preventing memory leaks.
  - **Vite Vendor Chunk Splitting**: Reconfigured Vite/Rollup with `manualChunks` to split heavy charting and gesture dependencies (`vendor-chartjs` and `vendor-zoom`), slashing initial bundle size from 630 kB to 393 kB.
- **Performance Optimization & Subsystems Modernization (Batch 10)**:
  - **Structured `smartctl -j` JSON Telemetry**: Switched from regex text scraping to structured JSON parsing for ATA SMART attributes and NVMe health information logs in `backend/hardware/disks.py`, with graceful fallback to legacy text parsing.
  - **Persistent Serial Connection for Chassis ARGB**: Replaced per-frame port open/close cycles at 25 Hz in `backend/hardware/led.py` with a persistent, thread-safe serial handle and automatic 3-second reconnect backoff.
  - **Physical Media Bit Verification**: Enforced `os.fdatasync()` and `os.posix_fadvise(..., os.POSIX_FADV_DONTNEED)` before computing SHA-256 verification hashes in `backend/services/copy_engine.py`, guaranteeing direct physical drive sector reads.
  - **Vitest Coverage Automation**: Integrated `@vitest/coverage-v8` with text, lcov, html, and json reporters, and updated `.github/workflows/ci.yml` to run automated coverage on every pull request and release build.

## v1.4.0 (2026-10-07) - Stable
### 🚀 NAS WORKBENCH, Multi-Arch Distribution, Predictive Diagnostics, UPS Protection & Desktop OS Polish

This major stable release introduces a complete hardware orchestration suite: native dual-architecture builds (`linux/amd64` and `linux/arm64`), native NUT protocol communication with automated emergency power failsafes, SQLite-backed predictive drive degradation tripwires, NVMe endurance metrics, custom named fan profiles, robust media slot auto-ingestion with user confirmation, and refined desktop workspace persistence.

#### 🖥️ Desktop OS Metaphor, Persistence & UI/UX Polish
- **Branding & Layout Modernization**: Renamed Toolkit Settings to **Hardware Settings** and elevated suite identity to **NAS WORKBENCH**; unified window headers with consistent 3-dot Mac-style window controls and top-right close dots.
- **Persistent Window Bounds**: Floating windows (`management`, `file-manager`, `fan-control`, `led-control`, `console`, `notification-center`) now automatically save their `(x, y, width, height, z-index)` in `localStorage` and clamp dynamically to screen boundaries upon resolution changes.
- **Instant Desktop Initialization**: Completely eliminated widget layout shift and initial page load jumping by computing CSS geometry in early `<head>` scripts before first paint.
- **Wallpaper Delivery Streamlining**: Replaced heavy PNG background assets with pre-optimized WebP images (`<link rel="preload">`), eliminating visual redraw jitter during initial load.
- **Enhanced Notification Center**: Converted Notification Center into a dedicated floating window with severity filtering tabs (All, Errors, Warnings, Info), unread count badges, memoized event rendering, and single-click event inspection modals.
- **File Manager Multi-Selection**: Upgraded File Explorer with Shift-click contiguous selection and Ctrl/Cmd-click multi-selection for bulk operations.

#### 🛡️ Advanced Hardware Intelligence & Predictive Diagnostics
- **Live Docker Container Telemetry**: Streamlined persistent Docker telemetry polling calculating real-time container CPU %, memory usage (excluding page cache/buffers), and network I/O stats without daemon CPU spikes.
- **SMART Historical Trends & Velocity Degradation**: Introduced SQLite-backed `smart_history` table in `backend/db.py` tracking drive health over 7-day and 30-day sliding windows to flag shedding sectors, stuck pending sectors, and thermal friction drift before catastrophic drive failure.
- **NVMe Endurance & Wear Monitoring**: Parsed and exposed critical NVMe telemetry: Percentage Used, Total Bytes Written (TBW), Available Spare %, and Media Error tallies in both REST APIs and UI diagnostics.
- **Custom Named Fan Curves**: Full-stack CRUD engine allowing users to create, save, load, and delete custom named acoustic profiles (e.g., "Silent Noctua", "High Altitude", "Crypto Rig") alongside standard presets.

#### ⚡ UPS Protection & High-Integrity Media Automation
- **Native NUT Socket Client**: Replaced external subprocess invocations with a zero-subprocess asynchronous TCP socket client querying NUT daemon port `3493`.
- **Automated Emergency Power Failsafe**: Configurable threshold rules (battery charge $\le 20\%$ or runtime $\le 5$ min) that automatically pause active file transfers, flush OS disk buffers via `os.sync()`, broadcast high-priority Apprise notifications, and signal safe host shutdown.
- **Media Slot Auto-Ingestion**: Kernel block device monitoring detects SD/TF card insertion, displaying an interactive ingestion confirmation prompt. State machine tracks ejected cards to prevent re-prompting while physical cards remain in slot until physical re-insertion.

#### 🐳 Multi-Arch Containerization & CI/CD Release Automation
- **Native Dual-Arch Docker Support**: Re-engineered `Dockerfile` for native `linux/amd64` and `linux/arm64` cross-compilation utilizing Debian system `chromium` and `chromium-sandbox` without proprietary browser binary downloads.
- **Automated GitHub Container Registry Publishing**: GitHub Actions Buildx pipeline publishes unified multi-architecture manifests (`ghcr.io/fr0styx/zettnas-toolkit:latest` and tagged releases) with layer caching (`type=gha,mode=max`).
- **Headless Playwright E2E Suite in CI**: Spin up background test server in GitHub Actions to validate real browser rendering, LCD geometry, and session state before container release.
- **Node.js 24 & JSDOM 30 Compatibility**: Upgraded CI and build toolchain to Node.js 24 and `jsdom: 30.1.2`, eliminating Node 20 deprecation warnings and ensuring fast, robust Vitest execution.


## v1.3.2 (2026-10-07)
### 🛡️ Enterprise-Grade System Hardening, Concurrency, Stability & Quality Assurance

Comprehensive multi-domain architectural hardening based on the enterprise-grade audit plan across backend concurrency, systems integration, UI performance, and testing infrastructure:

- **Critical Stability & Concurrency (Batch 1)**:
  - **FastAPI Threadpool Routing**: Converted non-awaiting FastAPI handlers (`fans`, `led`, `notifications`, `stats`, `metrics`, `auth`, `backup`, `system`) to synchronous `def` functions, allowing FastAPI to route them automatically to worker threadpools and preventing event loop stalls on blocking SQLite and filesystem operations.
  - **OOM Prevention on File Ingestion**: Refactored `fs_upload` in `backend/api/system.py` to stream client bodies iteratively (`async for chunk in request.stream()`) with path traversal guards.
  - **Telemetry Database Concurrency**: Migrated background daemon in `backend/services/stats_collector.py` to use `backend.db.log_metrics()` with SQLite WAL mode and a 5000ms `busy_timeout`, eliminating `database is locked` errors during concurrent API traffic.
  - **Concurrent S.M.A.R.T. Drive Polling**: Refactored `poll_all_disks_smart` in `backend/services/disks.py` to poll drives in parallel via `ThreadPoolExecutor(max_workers=min(8, len(targets)))`, slashing latency from ~15s to <2s and preventing UPS telemetry starvation during power events.
  - **Atomic Unraid Telemetry Retries**: Added retry backoff mechanism (`max_retries=3`, `retry_delay=0.05s`) in `backend/services/unraid.py` for reading `var.ini`, preventing transient incomplete writes from triggering false array error alerts.
  - **Decoupled SSE Reconnection**: Isolated SSE reconnection timers and polling fallback in `frontend/src/main.js` to eliminate competing network requests upon connection drops.
  - **Production Docker Volume Isolation**: Removed code mounts (`./backend`, `./static`) from production `docker-compose.yml`, strictly isolating them to `docker-compose.dev.yml` to prevent shadowing built assets.

- **Performance & Architecture Hardening (Batch 2)**:
  - **Native Static File Streaming**: Replaced hand-rolled in-memory static file caching with FastAPI's native `fastapi.staticfiles.StaticFiles`.
  - **Clean Architectural Relocation**: Relocated root entrypoint to `backend/main.py`, providing a backward-compatible root shim in `app.py`.
  - **Clean Top-Level Imports**: Cleaned up inline imports across all API and service modules to standard top-level definitions.
  - **Dedicated Backup Engine**: Extracted zip archive creation and extraction into `backend/services/backup_engine.py` with zip-slip path traversal validation.
  - **Asynchronous HDD Wake**: Converted spinning drive `dd` wake calls to non-blocking `subprocess.Popen` in `backend/services/disks.py`.
  - **Resource Leak Prevention**: Wrapped `/dev/fb0` memory maps in explicit `fb_mem.close()` within a `finally` block in `backend/services/lcd_renderer.py` to prevent descriptor leaks.
  - **Crash Recovery Exponential Backoff**: Replaced static 2s restart sleep with exponential backoff (2s → 60s) for Chromium crash recovery on `/dev/fb0`.
  - **Fan State Pruning**: Added `cleanup_stale_fan_trackers()` in `backend/services/fans.py` to evict stale PWM keys and wrapped sysfs fan reads in safe non-blocking context managers.
  - **UI Render Optimization**: Introduced `requestAnimationFrame` debouncing on `EventBus.emit()` and state diffing in `frontend/src/state.js` before dispatching updates.
  - **Docker BuildKit Caching**: Added `--mount=type=cache,target=/root/.cache/pip` to `Dockerfile` for accelerated container builds.

- **UI/UX, Accessibility & Quality Hardening (Batch 3)**:
  - **DOM Diffing Guards**: Added `setText()` and `setHtml()` helpers in `frontend/src/components/dashboard.js` to eliminate layout recalculations and DOM thrashing on high-frequency SSE telemetry ticks.
  - **Generic Mobile Touch Scrolling**: Replaced brittle hardcoded class selector exclusion lists with generic `[data-scrollable="true"]` handling.
  - **Automated Accessibility (A11y) Layer**: Built `frontend/src/a11y.js` with delegated keyboard event handlers (`Enter`/`Space`) and an automated `MutationObserver` attaching `role="button"`, `tabindex="0"`, and `aria-label` to interactive elements.
  - **Frontend Unit Testing**: Added Vitest + JSDOM testing framework (`npm test`) with passing unit test suites.
  - **Playwright E2E Integration Testing**: Added end-to-end integration test suite (`tests/test_e2e_integration.py`).
  - **Test Coverage Reporting**: Integrated `pytest-cov` (195 passed tests, 53% coverage across 3,808 lines of Python code).
  - **Hardware LCD Orientation**: Calibrated front-panel 172x640 portrait scan orientation (`rotate(90deg) translate(0, -172px)`) ensuring upright display.

## v1.3.0 (2026-10-06)
### 🚀 Desktop Web OS, Mobile Optimizations, File Explorer & Architecture Audit

- **Desktop OS Metaphor & Window Management**:
  - Halved the vertical spacing between desktop icons (from 48px to 20px) for a tighter, cleaner aesthetic.
  - Reordered desktop icons to match a logical visual flow: *Management* → *ZettNAS* → *File Explorer* → *Recycle Bin*.
  - Standardized window controls across all UI panels to a clean 3-button layout (`Minimize`, `Maximize`, `Close`), replacing convoluted multiple close buttons.
  - Implemented the Command Palette (`Cmd+K` / `Ctrl+K`) for rapid keyboard-driven navigation across the toolkit.
  - Initial startup now boots with the ZettNAS console window minimized by default, presenting a clean desktop workspace.

- **File Explorer & Recycle Bin**:
  - Introduced a fully featured floating File Explorer window with robust drag-and-drop file support, interactive breadcrumbs, and row-level sorting.
  - Added a functional Recycle Bin directly onto the desktop.

- **Mobile & Touch UI Overhaul**:
  - Fixed mobile UI viewport issues where windows would overflow past the top navigation bar and dock. Windows are now strictly clamped to the screen constraints with internal scrolling.
  - Prevented background body scrolling on mobile while floating windows are active, preserving the top navigation bar visibility.
  - Replaced the convoluted default mobile view with a streamlined, minimized-first experience.

- **UI & Widget Enhancements**:
  - Changed the primary management label to simply "**HUB**".
  - Enhanced the Calendar widget to automatically highlight country official holidays, complete with a glanceable hover tooltip displaying the holiday name.
  - Upgraded the Weather/Location widget with a dynamic auto-complete dropdown for major cities, automatically saving the user's selection and instantly updating weather telemetry.

- **Production Readiness & DevOps Audit**:
  - Removed source code volume mounts (`./backend`, etc.) from the production `docker-compose.yml`, preventing host directories from overwriting built production assets.
  - Resolved Python backend test suite issues, successfully expanding and passing 189 `pytest` cases.
  - Performed a full Enterprise-Grade System Audit resulting in a batched strategic roadmap (`master_audit_plan.md`) for stability, security, and performance optimizations.

## v1.2.0 (2026-10-05)
### 🚀 Major Upgrade: Full Internationalization (i18n), System Management Hub, Unraid & Docker Controls, UPS Monitoring, Interactive Charts & Ingest v2

- **Frontend Internationalization (i18n) Engine**:
  - Complete zero-dependency client-side localization engine (`frontend/src/i18n.js`) with 347 localization keys across 5 languages:
    - **English** (`en`) — Standard Homelab & Hardware terminology.
    - **German** (`de`) — Full German translation ("Systemverwaltung", "Hardware-Toolkit-Einstellungen", etc.).
    - **Simplified Chinese** (`zh`) — Native Chinese localization ("系统控制台", "系统管理中心", etc.) with high-fidelity CJK font fallback stack (`PingFang SC`, `Hiragino Sans GB`, `Microsoft YaHei`, `WenQuanYi Micro Hei`).
    - **French** (`fr`) — Full French translation ("Console Système", "Centre de Gestion", etc.).
    - **Spanish** (`es`) — Full Spanish translation ("Consola del Sistema", "Centro de Gestión", etc.).
  - 100% localization coverage: All views, desktop icons, dock tooltips, S.M.A.R.T. modal, Setup Wizard, Management hub, and Hardware Toolkit Settings.
  - 1-click quick language picker select in top navigation bar (`#suite-lang-select`) and dedicated "Display Language & Localization" card in Toolkit Settings.
  - Reactive DOM translation scanner (`data-i18n`, `data-i18n-title`, `data-i18n-placeholder`) and `zettnas:lang-changed` event bus dynamically translating components on the fly without page reload.
  - User language preference saved in `localStorage` (`zettnas_language`) with automatic browser language detection.

- **System Management Hub & Left-Sidebar Architecture**:
  - Modernized category navigation from top horizontal tabs to a responsive full-height left sidebar (`.mgmt-sidebar`).
  - Dynamic active tab indicators, glowing accents, and real-time live telemetry badges (Docker container counts, active alerts).
  - Reordered desktop icons: **Management** is placed first (featuring official 3D chassis artwork `chassis-d6u.png`), followed by **ZettNAS** (renamed from ZettNAS Console with screen display glyph).
  - Persistent drag-and-drop desktop icons: users can drag and position desktop icons anywhere on screen with automatic viewport boundary clamping, saved in `localStorage` (`zettnas_desktop_icon_positions`).
  - Intelligent drag-vs-click arbitration (>5px movement threshold) preventing accidental window launches on drop.

- **Unraid Host Subsystem & Parity Integration**:
  - Live telemetry parser for `/var/local/emhttp/var.ini` and `mover.ini` with caching and graceful non-Unraid fallback.
  - Monitors array state (`STARTED`, `STOPPED`), array health, server hostname (e.g. `NAS`), chassis model (`D6U`), OS version (e.g. `Unraid 7.x`), and assigned disk topology.
  - Real-time parity check monitoring (`action`, `progress_pct`, `errors`) and Mover activity tracking (`remain_files`).
  - Real-time navbar pills (`Array: STARTED`, `Parity: 0%`, Mover status) and storage card badges in WebUI and LCD.
  - Dedicated REST API endpoint `GET /api/unraid` and Unraid card inside System Management window.

- **Docker Container Introspection & Lifecycle Controls**:
  - Zero-dependency Unix domain socket client communicating directly with `/var/run/docker.sock` via Python standard library `http.client` and `AF_UNIX`.
  - Introspection table returning container list, state (`running`, `exited`), health status (`healthy`, `unhealthy`), uptime, image, and ID.
  - Direct container lifecycle control (`Start`, `Stop`, `Restart`) within the Management window Docker table.
  - REST endpoints `GET /api/docker/containers` and `POST /api/docker/containers/{container_id}/action` with robust ID sanitization and asynchronous non-blocking execution.
  - In-place action button spinners, error notifications, and automated container list re-polling.

- **UPS & Power Integrity Monitoring**:
  - Native telemetry provider for Uninterruptible Power Supplies supporting Network UPS Tools (NUT) and apcupsd NIS protocol (port 3551) with fallback to `/sbin/apcaccess`.
  - Reports daemon status, battery percentage, estimated runtime, load percentage, and line input voltage.
  - REST endpoint `GET /api/ups` and dedicated "UPS & Power Integrity" card in System Management window.

- **Interactive Historical Charts (Pan & Zoom)**:
  - Integrated `chartjs-plugin-zoom` dynamically loaded on-demand alongside Chart.js (`chartjs-plugin-zoom.esm-*.js`).
  - Enabled mouse-wheel and touch pinch zooming along the horizontal time axis, accompanied by click-and-drag panning and boundary clamping.
  - Dynamic "↺ Reset Zoom" button appearing automatically upon viewport interaction to restore default time range.
  - Granular multi-device historical metrics view split into dedicated category tabs: "All Devices", "CPU & RAM", "Storage Disks", and "Cooling Fans".
  - Individual drive temperature curves (`sda`, `sdb`, `nv0`, `nv1`, etc.) and dual-axis cooling fan RPM tracking across granular time windows (`1h`, `6h`, `24h`, `7d`, `30d`).
  - Live summary telemetry pills displaying instantaneous CPU, memory, drive temperatures, and fan speeds above the charts.

- **Active S.M.A.R.T. Drive Self-Tests**:
  - REST endpoint `POST /api/disk/smart_test` triggering background `smartctl -t short` or `smartctl -t long` self-tests on SATA/NVMe drives.
  - Input validation strictly guarding device names against shell injection.
  - Interactive "Run Short Test (~2m)" and "Run Extended Test" buttons added directly into S.M.A.R.T. Diagnostics modal with real-time toast feedback.

- **Copy Engine v2 - SHA-256 Checksums & Persistent History**:
  - Post-ingest streaming SHA-256 integrity verification (`verify_checksum=True`) verifying source and destination files match bit-for-bit.
  - Persistent SQLite audit log in `history.db` (`copy_history` table) tracking timestamp, source, destination, file counts, bytes, duration, checksum status, and error logs.
  - Dedicated `Media Ingest & Checksum History` app card and table in System Management window with dynamic refresh.
  - REST endpoint `GET /api/copy/history?limit=50`.

- **LCD Multi-Page Carousel & Hardware Button Cycling**:
  - Modular 4-page LCD carousel strictly fitted to 640x172 (and rotated 172x640 `/dev/fb0` display):
    - **Page 0 (Overview Dashboard)**: Gauges, storage pool rings, fans, and disks row.
    - **Page 1 (Drive Bay & S.M.A.R.T. Matrix)**: 6-bay visual chassis layout, disk temperature pills, S.M.A.R.T. health badges, and alert summary.
    - **Page 2 (Network & Storage I/O Telemetry)**: Inbound RX rate & peak, Outbound TX rate & peak, real-time interface IP, storage I/O throughput, active device count.
    - **Page 3 (Unraid Array & Media Ingest Hub)**: Array state badge, disk assignment, parity check progress bar, media slot status, copy progress bar.
  - Screen header pagination dots `(1) (2) (3) (4)` with interactive click navigation and active state sync.
  - Physical front-panel chassis button cycling: pressing the hardware button advances through LCD pages when copy is not active.
  - Configurable auto-cycle interval in Toolkit Settings (`Off`, `5s`, `10s`, `15s`, `30s`) and REST endpoints `GET/POST /api/lcd/page`, `POST /api/lcd/cycle`.

- **Acoustic Profiles & Auto Dynamic Synchronization**:
  - System Acoustic profile presets ("Quiet", "Balanced", "Performance") mapping fan curve ceilings and ARGB brightness/effects.
  - Direct 1-click switcher in System Management window and REST endpoint `POST /api/system/profile`.
  - Dynamic synchronization with live `stats.fan_control.profile` and dedicated "Auto Dynamic" status pill.

- **Aero Snap Desktop Window Management**:
  - Interactive window snapping to screen edges: Dragging a window header to the left or right edge triggers a translucent animated ghost outline (`#window-snap-ghost`) for a half-screen snap; dragging to the top edge snaps to full screen.
  - Header double-click toggles maximize / restore with saved geometry.
  - Natural un-snapping allows windows to restore to original bounds when dragged away from snapped edges.
  - Dedicated maximize/restore button in window header and dock integration.

- **Dedicated Mobile Stacked Mode & Responsive Layout**:
  - Top navigation bar toggle (`#mobile-view-toggle-btn`) allowing 1-click toggling between floating desktop windows and vertical mobile stacked cards.
  - User preference persisted across reloads in `localStorage` (`zettnas_mobile_mode`).
  - Mobile layout automatically handles narrow viewports (`@media (max-width: 768px)` and `body.mobile-mode`) stacking CPU, storage, fans, drives, and ARGB lights into full-width cards.
  - Dock and modals scale proportionally with touch-friendly button targets.

- **Dynamic Code-Splitting for Chart.js**:
  - Migrated `chart.js/auto` from monolithic initial bundle to dynamic on-demand import (`import('chart.js/auto')`).
  - Reduced initial bundle size by over 203 kB (`index.js` drops from ~324 kB to 121 kB), dramatically accelerating first paint and mobile load times.

- **Database & Architecture Optimizations**:
  - Configured SQLite connection pool with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`), `PRAGMA synchronous=NORMAL;`, and `PRAGMA busy_timeout=5000;` for zero write contention during heavy telemetry ingest.
  - Wrapped synchronous filesystem directory scans (`os.scandir`) in `asyncio.to_thread` for fast, non-blocking folder exploration in `POST /api/browse`.
  - Re-themed native select dropdowns (e.g. LCD Auto-cycle) to match project dark/teal design language with custom SVG chevron arrow, dark menu styling, and focus glow.

- **Accessibility & Focus Trapping**:
  - Built-in `trapFocus(element, onEscape)` utility cycling focus strictly inside open dialogs (S.M.A.R.T., Metrics, Management, Settings).
  - ARIA dialog attributes (`role="dialog"`, `aria-modal="true"`, `aria-label`) added to modals and management window.
  - Dock toolbar (`role="toolbar"`) with left/right arrow key navigation and Enter/Space actuation.
  - Universal `Escape` key dismissal for all active overlays and modals.
  - Automatic `prefers-color-scheme` media query synchronization.


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

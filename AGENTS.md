# AGENTS.md — Developer & AI Agent Guidelines for ZettNAS Toolkit

Welcome, Agent! This repository contains **ZettNAS Toolkit** (**NAS WORKBENCH**), an enterprise-grade hardware orchestration suite, glassmorphic Web Desktop OS, and Docker management platform.

This document serves as your operational blueprint, covering the architecture, development invariants, testing protocols, and core philosophies necessary to build, debug, and maintain this codebase with zero regressions.

---

## 1. Core Philosophy & Architectural Invariants

### 1.1 Hardware & OS Agnosticism (HAL & PAL)
- **Universal Hardware**: The toolkit runs on custom appliance NAS hardware (Zettlab D4/D6/D8, Aoostar WTR Pro / R1) **and** generic DIY homelab servers (Fractal, Jonsbo, Supermicro, SilverStone, Mini-PCs, ARM64 SBCs).
- **Universal Host OS**: Seamlessly coexists on **Unraid**, **Ubuntu/Debian**, **TrueNAS SCALE**, **Proxmox VE**, **Alpine**, and **FygoOS**.
- **The Invariant**: **Never hardcode assumptions about host OS or physical peripherals.**
  - If a physical LCD (`/dev/fb0`), ARGB lightbar (`/dev/ttyACM0`), or front Copy button is missing, the application **must** run in headless mode without crashing, throwing unhandled exceptions, or spamming error logs.
  - The UI must dynamically detect peripheral presence and hide appliance-only menus and top-bar status badges (`MCU`, `FB`) when hardware is not detected.
  - Storage logic must adapt dynamically: show Unraid array widgets when on Unraid, and Btrfs RAID / ZFS / mdadm topology when on generic Linux.

### 1.2 Thermal & Disk Spindown Safety Invariant
- **Never Wake Sleeping Hard Drives**: Querying disk temperatures or S.M.A.R.T. health must **never** spin up sleeping drive platters.
  - Always execute `smartctl` with the `-n standby` flag.
  - Exit code `2` from `smartctl` indicates the drive is in `SLEEP` or `STANDBY`. Respect this state and return cached or standby indicators.
- **Zero RPM Standby Safety**:
  - Hard drive bay exhaust fans may enter Zero RPM mode **only** when all drives in the zone are spun down and temperatures are below threshold.
  - **CPU fan (`pwm3`) is strictly inviolable**: It must **never** be shut down under any condition.
  - **Emergency Thermal Clamp**: If any component reaches $\ge 80^\circ\text{C}$, the fan curve calculation in `fans.py` unconditionally clamps to maximum hardware PWM (`183`).

### 1.3 Keyed DOM Reconciliation (Frontend Table Performance)
- Container tables and disk inventories use `reconcileKeyedTable()` to avoid DOM destruction, flickering, and loss of input/selection state.
- **Row Dataset Invariant**: Any state rendered in table row HTML (e.g. `hasUpdate`, `state`, `name`, `id`) **must** be mirrored on `tr.dataset` (e.g. `tr.dataset.hasUpdate = '1'`).
- In `updateContainerRow()`, always check if dataset attributes have changed (`prevHasUpdate !== hasUpdate`). If changed, re-render the inner row (`tr.innerHTML = buildContainerRowInner(...)`) so the DOM immediately reflects changes without requiring a full browser page reload.

### 1.4 Cryptographic Security & Secrets Redaction
- **Password Hashing**: RFC 9106 Argon2id (`m=64MB, t=3, p=4`) with transparent legacy rehash on valid login.
- **Secrets Redaction Invariant**: Tokens (`zat_...`), SMTP passwords, bot tokens, and webhook URLs must **never** be exposed in plaintext in API responses. Mask them (e.g. `zat_****` or `********`).
- **Database**: SQLite operates in Write-Ahead Logging (WAL) mode with `busy_timeout=15000` and thread-safe connection pooling.

### 1.5 Strict Theme & Style Isolation
- The application provides two distinct styling layers:
  1. **Web Desktop Workspace**: Dynamic themes (`Cyber Teal`, `Amber CRT`, `Emerald Matrix`, `Yak Bronze`, `Pure OLED Black`).
  2. **Physical LCD Framebuffer (`/dev/fb0`) & Mini-LCD Canvas**: Dedicated palette scoped strictly to `#screen` and `#mini-lcd-canvas`.
- Changes to the desktop appearance must **never** cascade into or corrupt the physical LCD front-panel display.

---

## 2. Repository Layout & Key Directories

```
zettnas-toolkit/
├── backend/
│   ├── main.py                     # Entry point & ASGI application startup
│   ├── app.py                      # FastAPI app initialization, middleware, routes
│   ├── auth.py                     # Session validation, cookie handling, reverse proxy auth
│   ├── users_db.py                 # SQLite WAL multi-user store, Argon2id, RBAC roles
│   ├── db.py                       # Time-series SQLite database (metrics, SMART velocity)
│   ├── api/                        # REST API routers
│   │   ├── auth.py                 # Login, logout, TOTP 2FA, session management
│   │   ├── docker.py               # Containers, Compose stacks, updates, terminal, prune
│   │   ├── storage.py              # PAL storage pools, physical disks, bay slots
│   │   ├── notifications.py        # Apprise multi-channel alerts & test endpoints
│   │   ├── backup.py               # Hyper-backup archives, snapshots, restore
│   │   ├── fans.py                 # Fan curves, acoustic profiles, Zero RPM
│   │   ├── led.py                  # ARGB lightbar effects & serial packet dispatch
│   │   ├── system.py               # System reboot, powerdown, diagnostics bundle
│   │   └── wallpapers.py           # Wallpaper gallery upload, active set, deletion
│   ├── hardware/                   # Hardware Abstraction Layer (HAL)
│   │   ├── disks.py                # lsblk discovery, SMART parsing, temperature polling
│   │   ├── fans.py                 # sysfs hwmon PWM controls, thermal watchdog
│   │   ├── led.py                  # WS2812B serial protocol handler (/dev/ttyACM0)
│   │   ├── screen.py               # Memory-mapped /dev/fb0 rendering & sleep timers
│   │   ├── ups.py                  # Native NUT TCP client (port 3493) & failsafes
│   │   ├── pal_storage.py          # Platform Abstraction Layer (Btrfs, Unraid, ZFS)
│   │   └── smart_engine.py         # Multi-protocol SMART runner (SATA, NVMe, SAS, UAS)
│   └── services/                   # Background services & business engines
│       ├── compose_synthesizer.py  # Reverse-engineers docker-compose.yml from containers
│       ├── container_mutator.py    # Atomic container recreation, port config & rollback
│       ├── docker_cleanup.py       # Docker prune & storage reclamation
│       ├── notifications.py        # Apprise dispatcher & deduplication engine
│       ├── rclone_engine.py        # Multi-cloud remote FUSE mounting
│       └── stats_collector.py      # Real-time host metrics collector & SSE broadcaster
├── frontend/
│   ├── index.html                  # Main Web Desktop HTML template & modal definitions
│   ├── src/
│   │   ├── main.js                 # Frontend boot, SSE subscriber, window initialization
│   │   ├── api.js                  # Fetch wrapper with token injection & error toasts
│   │   ├── state.js                # Shared client-side reactive state & event subscriptions
│   │   ├── i18n.js                 # Multilingual translation dictionary (EN, DE, ZH, FR, ES)
│   │   ├── style.css               # Comprehensive CSS variables, glassmorphism, themes
│   │   └── components/             # Modular desktop components
│   │       ├── dock.js             # macOS-style dock, window drag/snap, taskbar
│   │       ├── management.js       # Mission Control (Containers, Storage, System, Alerts)
│   │       ├── container-modal.js  # Tabbed Container Inspector & Compose Stack editor
│   │       ├── chassis-visualizer.js # Parametric 2.5D chassis SVG digital twin
│   │       ├── auth.js             # Multi-user login chooser, 2FA challenge, auto-lock
│   │       └── settings.js         # Hardware Settings drawer (Fans, LED, LCD, Media)
│   └── src/__tests__/              # Vitest unit & integration test suites (40+ files)
├── static/                         # Production assets generated by `npm run build`
├── tests/                          # Backend Pytest test suite (420+ tests)
├── docs/                           # Architecture, API, and deployment documentation
│   ├── INSTALLATION.md             # Multi-platform deployment guide
│   ├── API.md                      # REST API & SSE contracts
│   └── ARCHITECTURE.md             # System threading & concurrency model
└── docker-compose.linux.yml        # Standard production Docker Compose stack
```

---

## 3. Remote Development & Execution Protocol

### 3.1 Primary Host Configuration
- **Host Address**: `root@10.40.30.249` (Unraid test appliance).
- **Host Repository Root**: `/mnt/user/appdata/zettnas-toolkit`.
- **Local Mac Mount**: `/Volumes/appdata/zettnas-toolkit`.
- **Live Container**: `zettnas-toolkit` running on `http://10.40.30.249:8082`.

### 3.2 Command Execution Rule
> [!CRITICAL]  
> **Always execute git commands, build scripts, and test suites via SSH on `root@10.40.30.249`:**
> ```bash
> ssh root@10.40.30.249 "cd /mnt/user/appdata/zettnas-toolkit && <command>"
> ```
> **Never run `git` locally inside `/Volumes/appdata/zettnas-toolkit`** across the SMB/network share, as network file locks can corrupt git index and loose objects.

### 3.3 The Frontend Build & Deploy Lifecycle
Whenever you modify files in `frontend/src/` or `frontend/index.html`:
1. **Run Vitest tests**:
   ```bash
   ssh root@10.40.30.249 "cd /mnt/user/appdata/zettnas-toolkit && npm test"
   ```
2. **Compile the production bundle**:
   ```bash
   ssh root@10.40.30.249 "cd /mnt/user/appdata/zettnas-toolkit && npm run build"
   ```
3. **Copy built assets to the running container**:
   ```bash
   ssh root@10.40.30.249 "docker cp /mnt/user/appdata/zettnas-toolkit/static/. zettnas-toolkit:/app/static/"
   ```
4. **Verify container response**:
   ```bash
   ssh root@10.40.30.249 "curl -sI http://127.0.0.1:8082 | head -n 5"
   ```

---

## 4. Testing & Verification Gates

### 4.1 The Zero-Broken-Tests Rule
Before committing any changes or concluding a task, you **must** verify that all test suites pass with 100% success rate:
- **Frontend (Vitest)**: 40 test files, 256+ unit tests.
- **Backend (Pytest)**: 420+ unit and integration tests.

### 4.2 Running Tests

#### Run Single Frontend Test File:
```bash
ssh root@10.40.30.249 "cd /mnt/user/appdata/zettnas-toolkit && node ./node_modules/vitest/dist/cli.js run frontend/src/__tests__/<test_name>.test.js"
```

#### Run Full Frontend Test Suite:
```bash
ssh root@10.40.30.249 "cd /mnt/user/appdata/zettnas-toolkit && npm test"
```

#### Run Backend Pytest Suite:
```bash
ssh root@10.40.30.249 "docker exec -i zettnas-toolkit python3 -m pytest -q /mnt/user/appdata/zettnas-toolkit/tests"
```

#### Run Specific Backend Test:
```bash
ssh root@10.40.30.249 "docker exec -i zettnas-toolkit python3 -m pytest -v /mnt/user/appdata/zettnas-toolkit/tests/test_docker_updates.py"
```

---

## 5. Coding & Contribution Rules

### 5.1 Multilingual Localization (i18n)
- Every user-facing string added to the application **must** be localized across all 5 languages in `frontend/src/i18n.js`:
  1. English (`en`)
  2. German (`de`)
  3. Simplified Chinese (`zh`)
  4. French (`fr`)
  5. Spanish (`es`)
- Use `data-i18n="key"` in HTML templates or `t('key')` in JavaScript components.

### 5.2 Responsive & Modal Stacking Hierarchy
- **Window Stacking (`bringToFront`)**: Desktop application windows alternate dynamically between `z-index: 1000..4900`.
- **Slide Drawers**: Hardware Settings slide drawer renders at `z-index: 7100`.
- **Modal Dialogs**: Modals, confirmation toasts, and wizards render at `z-index: 9000..9500`.

### 5.3 Commit Messages & Release Engineering
- Use standard Conventional Commits:
  - `feat(scope): ...` for new features
  - `fix(scope): ...` for bug fixes
  - `docs(scope): ...` for documentation updates
  - `chore(release): vX.Y.Z - ...` for releases
- **Updating Releases**: When cutting a release, update `CHANGELOG.md` under `## vX.Y.Z (YYYY-MM-DD) - Stable`. The CI workflow automatically extracts this section to populate the GitHub Release notes.

---

## 6. Common Pitfalls & Solutions

| Pitfall | Cause | Correct Solution |
| :--- | :--- | :--- |
| Table row doesn't show badge after data updates | Keyed DOM reconciler reuses the existing `<tr>` node without detecting a change | Store state on `tr.dataset` (e.g. `tr.dataset.hasUpdate = '1'`) and trigger `tr.innerHTML = buildContainerRowInner(...)` in `updateContainerRow()` if dataset changed. |
| Hard drives spin up unexpectedly | Running raw `smartctl -A /dev/sdX` without power mode checks | Always pass `-n standby` (`smartctl -n standby -A ...`). If exit code is 2, skip reading to preserve standby. |
| CPU fan curve drops below safe threshold | Custom curve configured with 0 PWM at high temp | Hardware watchdog in `fans.py` overrides curve and enforces maximum PWM at $\ge 80^\circ\text{C}$. Never bypass this check. |
| Container build fails with missing fonts on LCD | Missing CJK or Emoji font packages in Dockerfile | Debian packages `fonts-noto-cjk` and `fonts-noto-color-emoji` are required to prevent tofu box glyphs (`□□□`). |
| Git commands freeze on `/Volumes/appdata` | SMB file locking across macOS network share | Run all git operations via SSH on `root@10.40.30.249`. |

---

*Keep this guide updated as new subsystems and architecture patterns evolve. Happy coding!*

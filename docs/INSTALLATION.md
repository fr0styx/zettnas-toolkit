# ZettNAS Toolkit - Installation & Deployment Guide

This document provides complete, step-by-step instructions for installing and running **ZettNAS Toolkit** across all supported operating systems, container engines, and hardware configurations.

---

## Table of Contents
1. [Prerequisites & System Requirements](#prerequisites--system-requirements)
2. [Default Credentials & Initial Access](#default-credentials--initial-access)
3. [Deployment Options](#deployment-options)
   - [Option A: Unraid OS (Docker Template)](#option-a-unraid-os-docker-template)
   - [Option B: Ubuntu / Debian / Generic Linux (Docker Compose)](#option-b-ubuntu--debian--generic-linux-docker-compose)
   - [Option C: FygoOS / Fygos NAS (App Center & Compose Stack)](#option-c-fygoos--fygos-nas-app-center--compose-stack)
   - [Option D: TrueNAS SCALE (Custom App / Compose)](#option-d-truenas-scale-custom-app--compose)
   - [Option E: UGOS (Ugreen NAS) & Observer Platforms](#option-e-ugos-ugreen-nas--observer-platforms)
   - [Option F: Standalone Docker CLI (`docker run`)](#option-f-standalone-docker-cli-docker-run)
   - [Option G: Building the Production Image from Source](#option-g-building-the-production-image-from-source)
4. [Hardware Device & Capability Mappings](#hardware-device--capability-mappings)
5. [Headless Server Deployments (No LCD / ARGB)](#headless-server-deployments-no-lcd--argb)
6. [Environment Variables Reference](#environment-variables-reference)
7. [Volume Mounts & Data Persistence](#volume-mounts--data-persistence)
8. [Reverse Proxy & HTTPS Setup](#reverse-proxy--https-setup)
9. [Upgrades & Maintenance](#upgrades--maintenance)
10. [Troubleshooting & FAQ](#troubleshooting--faq)

---

## Prerequisites & System Requirements

- **Architecture**: `linux/amd64` (x86_64) or `linux/arm64` (aarch64).
- **Container Engine**: Docker 24.0+ and Docker Compose v2.20+ (or Podman with docker-compose compatibility).
- **Host Kernel**: Linux kernel 5.15+ recommended with `cgroup v2` support.
- **Virtualization (Optional for VMs)**: Intel VT-x or AMD-V hardware virtualization enabled in host BIOS/UEFI with `/dev/kvm` accessible.
- **Port Availability**: Port `8082` (Web Desktop & REST API) and optionally Port `8084` (WebDAV Server).

### Unraid companion mode

ZettNAS reads Unraid's status files when it runs on the Unraid box itself. When it runs
elsewhere (or to post alerts into Unraid's bell), point it at the Unraid API (Unraid 7):
create a key on the Unraid box under **Settings > Management Access > API Keys** with only
these permissions: Array, Disk, Share and Info (read), and Notifications (read and create).
On unraid-api 4.37 the command-line `--permissions` option fails with "Invalid data
structure"; the web page (or the GraphQL `apiKey.create` mutation) works.

Then set `UNRAID_API_KEY` and `UNRAID_API_URL`. With HTTPS on (Unraid's default), Unraid
only answers plain HTTP on the box itself, so use its HTTPS address from Settings >
Management Access, for example `https://10-0-0-5.<hash>.myunraid.net`. ZettNAS verifies
that certificate: it ships the Let's Encrypt link these certificates need
(`backend/certs/README.md`), and `UNRAID_API_CA` can add another CA file. ZettNAS then
reads the array, disks (including which are spun down), shares and parity-check progress,
and posts its alerts to Unraid's notification centre. It never starts, stops or changes
the array through the API.

### TrueNAS companion mode

On TrueNAS SCALE, set `TRUENAS_URL` (for example `https://truenas.local`) and
`TRUENAS_API_KEY` (TrueNAS: user menu → API Keys) in the container environment. ZettNAS
then reads pools, datasets and shares through the TrueNAS API and can take ZFS snapshots
(used by the ransomware guard). It never changes pools or shares. Add
`TRUENAS_VERIFY_TLS=0` if TrueNAS still uses its self-signed certificate.

### Image variants

| Tag | Size | Includes |
| --- | ---- | -------- |
| `latest`, `edge` | about 1.7 GB | Everything: virtual machines (QEMU, UEFI, vTPM) and the front-panel LCD renderer |
| `latest-core`, `edge-core` | about 500 MB | Everything except virtual machines and the LCD renderer |

Use the core tags on servers without the ZettLab front LCD that don't run VMs. The
in-app updater keeps you on the variant you installed. To switch, change the tag in
your compose file or Unraid template and recreate the container.

---

## Default Credentials & Initial Access

- **Web Desktop URL**: `http://<server-ip>:8082`
- **Username**: `admin`
- **First-time password**: if you leave `WEB_PASSWORD` empty, ZettNAS generates one on first start. It is written to the container log (`docker logs zettnas-toolkit`) and saved as `initial-admin-password` in the app data folder (readable by root only). It works once: you choose your own password at first sign-in, and the file is then deleted.

> [!WARNING]  
> Upon your first login, immediately navigate to **Mission Control** → **System & Security** → **Security** (or press `Cmd+K` and type `>password`) to set a strong master password or provision a new user account.

---

## Deployment Options

### Option A: Unraid OS (Docker Template)

ZettNAS Toolkit integrates directly with Unraid's DockerMan subsystem and device assignment.

1. **Install the Template**:
   Copy the pre-configured [`unraid/zettnas-toolkit.xml`](../unraid/zettnas-toolkit.xml) template into your Unraid flash drive:
   ```bash
   mkdir -p /boot/config/plugins/dockerMan/templates-user
   cp unraid/zettnas-toolkit.xml /boot/config/plugins/dockerMan/templates-user/my-zettnas-toolkit.xml
   ```

2. **Add Container via WebUI**:
   - In the Unraid WebUI, navigate to **Docker** → **Add Container**.
   - Select **zettnas-toolkit** from the template dropdown.
   - Verify hardware paths (e.g. `/dev/fb0` for physical LCD, `/dev/dri` for GPU telemetry, `/dev/ttyACM0` for ARGB lighting). If running on a server without front LCD hardware, leave these fields empty.
   - Click **Apply**.

3. **Access**:
   Open your browser to `http://<unraid-ip>:8082`.

---

### Option B: Ubuntu / Debian / Generic Linux (Docker Compose)

Recommended for custom DIY homelab builds (Jonsbo N1/N2/N3/N4, Fractal Node 804, SilverStone, rackmount chassis), Aoostar mini-PCs, and standard Linux servers.

1. **Install Docker Engine & Compose**:
   ```bash
   sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2
   sudo usermod -aG docker,dialout $USER
   # Log out and log back in for group changes to take effect
   ```

2. **Create Project Directory & Compose File**:
   ```bash
   mkdir -p ~/zettnas-toolkit/data
   cd ~/zettnas-toolkit
   ```

3. **Save `docker-compose.yml`**:
   ```yaml
   services:
     zettnas-toolkit:
       image: ghcr.io/fr0styx/zettnas-toolkit:latest
       container_name: zettnas-toolkit
       restart: unless-stopped
       network_mode: bridge
       ports:
         - "8082:8082"   # Web Desktop & API
         - "8084:8084"   # Universal WebDAV Server
       environment:
         - PORT=8082
         - WEB_PASSWORD=   # empty: a first-time password is generated (see the log)
         - DATA_DIR=/app/data
         - STORAGE_POOL_PATH=/mnt/storage
         - HOST_PROC=/host/proc
         - HOST_SYS=/host/sys
         - HOST_DEV=/host/dev
         - PUID=1000
         - PGID=1000
       volumes:
         - ./data:/app/data:rw
         - /mnt/storage:/mnt/storage:rw
         - /proc:/host/proc:ro
         - /sys:/host/sys:rw
         - /dev:/host/dev:rw
         - /etc/localtime:/etc/localtime:ro
         - /var/run/docker.sock:/var/run/docker.sock:ro
       tmpfs:
         - /host/sys/firmware:ro
         - /host/sys/kernel/debug:ro
       cap_add:
         - SYS_RAWIO
         - SYS_ADMIN
       device_cgroup_rules:
         - 'c 1:1 rwm'     # /dev/mem (Physical Memory-Mapped I/O for appliance fan and hardware control)
         - 'c 1:* rwm'     # Memory character devices (/dev/mem, /dev/port)
         - 'c 29:* rwm'    # Framebuffer (/dev/fb0)
         - 'c 226:* rwm'   # DRI GPU devices
         - 'c 188:* rwm'   # USB Serial (/dev/ttyUSB*)
         - 'c 166:* rwm'   # USB ACM Serial (/dev/ttyACM*)
         - 'c 189:* rwm'   # USB Character Devices & Bus (/dev/bus/usb/*)
         - 'c 180:* rwm'   # USB HID Devices (/dev/usb/hiddev*)
         - 'c 240:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 241:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 242:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 243:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 244:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 245:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 10:232 rwm'  # KVM hardware virtualization (/dev/kvm)
         - 'c 10:* rwm'    # Misc character devices (KVM, vhost-net)
         - 'b 8:* rwm'     # SCSI/SATA hard drives (/dev/sd*)
         - 'b 259:* rwm'   # NVMe solid state drives (/dev/nvme*)
         - 'b 9:* rwm'     # Linux Software RAID block devices (/dev/md*)
         - 'b 253:* rwm'   # Device-Mapper / LVM / Crypt block devices (/dev/dm-*)
   ```

4. **Launch**:
   ```bash
   docker compose up -d
   ```

5. **Verify**:
   ```bash
   docker compose logs -f
   ```

---

### Option C: FygoOS / Fygos NAS (App Center & Compose Stack)

FygoOS provides a modern, turnkey private cloud OS with native Docker support.

1. **Create Directory**:
   On your main storage pool (e.g. `/vol1`), create an application folder:
   ```bash
   mkdir -p /vol1/appdata/zettnas-toolkit/data
   ```

2. **Deploy via App Center / Compose**:
   - In FygoOS WebUI, go to **Docker** → **Compose / Projects** → **Add Project**.
   - Project Name: `zettnas-toolkit`.
   - Paste the following configuration:
   ```yaml
   services:
     zettnas-toolkit:
       image: ghcr.io/fr0styx/zettnas-toolkit:latest
       container_name: zettnas-toolkit
       restart: unless-stopped
       ports:
         - "8082:8082"
         - "8084:8084"
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
         - WEB_PASSWORD=   # empty: a first-time password is generated (see the log)
         - NAS_NAME=FygoNAS
         - POOL_PATH=/mnt/storage
         - HOST_PROC=/host/proc
         - HOST_SYS=/host/sys
         - HOST_DEV=/host/dev
       tmpfs:
         - /host/sys/firmware:ro
         - /host/sys/kernel/debug:ro
       cap_add:
         - SYS_RAWIO
         - SYS_ADMIN
       device_cgroup_rules:
         - 'c 29:* rwm'
         - 'c 226:* rwm'
         - 'c 188:* rwm'
         - 'c 166:* rwm'
         - 'c 189:* rwm'   # USB Character Devices & Bus (/dev/bus/usb/*)
         - 'c 180:* rwm'   # USB HID Devices (/dev/usb/hiddev*)
         - 'c 240:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 241:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 242:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 243:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 244:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 245:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 10:232 rwm'  # KVM hardware virtualization (/dev/kvm)
         - 'c 10:* rwm'    # Misc character devices (KVM, vhost-net)
         - 'b 8:* rwm'
         - 'b 259:* rwm'
   ```
3. Click **Deploy / Start** and open `http://<fygoos-ip>:8082`.

---

### Option D: TrueNAS SCALE (Custom App / Compose)

TrueNAS SCALE (Dragonfish & Electric Eel) supports custom Docker Compose applications directly.

1. In the TrueNAS WebUI, navigate to **Apps** → **Discover Apps** → **Custom App** (or Docker Compose).
2. Configure App Name: `zettnas-toolkit`.
3. Image Repository: `ghcr.io/fr0styx/zettnas-toolkit`, Tag: `latest`.
4. Add Host Paths:
   - `/mnt/tank` → `/mnt/storage`
   - `/mnt/tank/appdata/zettnas-toolkit/data` → `/app/data`
   - `/var/run/docker.sock` → `/var/run/docker.sock`
   - `/proc` → `/host/proc` (Read-only)
   - `/sys` → `/host/sys` (Read-write)
   - `/dev` → `/host/dev` (Read-write)
5. Set Capabilities: Enable `SYS_RAWIO` and `SYS_ADMIN`.
6. Expose Port `8082` on Host Port `8082`.
7. Save and deploy.

---

### Option E: UGOS (Ugreen NAS) & Observer Platforms

For **UGOS (Ugreen NAS OS)**, **FygoOS**, **ZettOS**, or **Proxmox VE**, ZettNAS Toolkit operates in **Non-Intrusive Observer Mode (`is_observer_mode = True`)**. It monitors storage pools, drive temperatures, S.M.A.R.T. health, and host metrics without modifying host configuration files or competing with native storage daemons.

1. **Deploy Compose Stack**:
   In UGOS Docker Manager or via SSH:
   ```yaml
   services:
     zettnas-toolkit:
       image: ghcr.io/fr0styx/zettnas-toolkit:latest
       container_name: zettnas-toolkit
       restart: unless-stopped
       ports:
         - "8082:8082"
         - "8084:8084"
       environment:
         - PORT=8082
         - ZETTNAS_OBSERVER_ADAPTER=ugos   # Explicitly set adapter or use 'auto'
         - UPDATE_CHANNEL=stable
       volumes:
         - /proc:/host/proc:ro
         - /sys:/host/sys:rw
         - /dev:/host/dev:rw
         - /volume1:/mnt/storage:rw
         - /volume1/docker/zettnas/data:/app/data:rw
         - /var/run/docker.sock:/var/run/docker.sock:ro
       cap_add:
         - SYS_RAWIO
         - SYS_ADMIN
       device_cgroup_rules:
         - 'c 189:* rwm'   # USB Character Devices & Bus (/dev/bus/usb/*)
         - 'c 180:* rwm'   # USB HID Devices (/dev/usb/hiddev*)
         - 'c 240:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 241:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 242:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 243:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 244:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'c 245:* rwm'   # HIDRAW Character Devices (/dev/hidraw*)
         - 'b 8:* rwm'
         - 'b 259:* rwm'
   ```

2. Open `http://<ugos-ip>:8082`.

---

### Option F: Standalone Docker CLI (`docker run`)

For rapid testing on any Linux host without Docker Compose:

```bash
docker run -d \
  --name zettnas-toolkit \
  --restart unless-stopped \
  -p 8082:8082 \
  -p 8084:8084 \
  -v /proc:/host/proc:ro \
  -v /sys:/host/sys:rw \
  -v /dev:/host/dev:rw \
  -v /etc/localtime:/etc/localtime:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v $(pwd)/data:/app/data:rw \
  -v /mnt/storage:/mnt/storage:rw \
  -e PORT=8082 \
  -e WEB_PASSWORD= \
  -e HOST_PROC=/host/proc \
  -e HOST_SYS=/host/sys \
  -e HOST_DEV=/host/dev \
  --cap-add SYS_RAWIO \
  --cap-add SYS_ADMIN \
  --device-cgroup-rule='c 29:* rwm' \
  --device-cgroup-rule='c 226:* rwm' \
  --device-cgroup-rule='c 166:* rwm' \
  --device-cgroup-rule='c 188:* rwm' \
  --device-cgroup-rule='c 189:* rwm' \
  --device-cgroup-rule='c 180:* rwm' \
  --device-cgroup-rule='c 240:* rwm' \
  --device-cgroup-rule='c 241:* rwm' \
  --device-cgroup-rule='c 242:* rwm' \
  --device-cgroup-rule='c 243:* rwm' \
  --device-cgroup-rule='c 244:* rwm' \
  --device-cgroup-rule='c 245:* rwm' \
  --device-cgroup-rule='c 10:232 rwm' \
  --device-cgroup-rule='c 10:* rwm' \
  --device-cgroup-rule='b 8:* rwm' \
  --device-cgroup-rule='b 259:* rwm' \
  --device-cgroup-rule='b 9:* rwm' \
  --device-cgroup-rule='b 253:* rwm' \
  ghcr.io/fr0styx/zettnas-toolkit:latest
```

---

### Option G: Building the Production Image from Source

For developers, homelab maintainers, and air-gapped homelabs building custom images locally rather than pulling from GitHub Container Registry (GHCR):

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/fr0styx/zettnas-toolkit.git
   cd zettnas-toolkit
   mkdir -p data
   ```

2. **Build the Container Image**:
   The multi-stage `Dockerfile` handles everything automatically:
   - **Stage 1 (`frontend-builder`)**: Uses `node:26.12.1-alpine` (the version in `.nvmrc`) to compile and bundle the glassmorphic web desktop via Vite into minified offline assets.
   - **Stage 2 (`runtime`)**: Prepares `python:3.12-slim` with Linux system utilities (`smartmontools`, `nvme-cli`, `ovmf`, `qemu-system-x86`, `rclone`, `fuse3`), installs pip requirements, and overlays the built desktop assets.

   ```bash
   docker build -t zettnas-toolkit:local .
   ```

3. **Run with Docker Compose (Local Build)**:
   You can build and start the entire stack in one command using `docker-compose.yml`:
   ```bash
   docker compose up -d --build
   ```

4. **Verify Container Health**:
   ```bash
   docker compose ps
   curl -s http://localhost:8082/api/health
   ```

---

## Hardware Device & Capability Mappings

ZettNAS Toolkit accesses physical hardware through Linux device nodes and `cgroup` rules:

| Device Node | Major/Minor Rule | Purpose | Required? |
| :--- | :--- | :--- | :---: |
| `/dev/fb0` | `c 29:* rwm` | Physical front-panel IPS LCD display (640×172) | Optional |
| `/dev/dri/*` | `c 226:* rwm` | GPU hardware acceleration (Intel QuickSync, AMD ROCm) | Optional |
| `/dev/kvm` | `c 10:232 rwm` | Hardware-assisted virtual machine acceleration (KVM) | Optional |
| `/dev/ttyACM0` | `c 166:* rwm` | WS2812B ARGB chassis lightbar USB microcontroller | Optional |
| `/dev/ttyUSB*` | `c 188:* rwm` | Alternative USB serial LED / MCU controllers | Optional |
| `/dev/bus/usb/*` | `c 189:* rwm` | USB character devices and USB bus discovery | Optional / USB |
| `/dev/usb/hiddev*` | `c 180:* rwm` | Legacy USB HID power devices | Optional / UPS |
| `/dev/hidraw*` | `c 240:*..245:* rwm` | Direct USB HID UPS telemetry (WalleCube, OpenUPS, APC, CyberPower) | Recommended for USB UPS |
| `/dev/sd*` | `b 8:* rwm` | Physical SATA/SAS hard drives and SD/TF card slots | Recommended |
| `/dev/nvme*` | `b 259:* rwm` | M.2 NVMe SSD storage and endurance telemetry | Recommended |
| `/dev/md*` | `b 9:* rwm` | Linux Software RAID (mdraid) arrays | Optional / Linux RAID |
| `/dev/dm-*` | `b 253:* rwm` | Device-Mapper / LVM / Crypt volumes | Optional / LVM |
| `/dev/mem` | `c 1:1 rwm` | Userspace physical MMIO fan controller (`0xFE0B0456`) and front copy button | Optional / Zettlab & Aoostar |
| `/dev/fuse` | `--device /dev/fuse` | Rclone Multi-Cloud remote FUSE mounts | Optional |

---

## Headless Server Deployments (No LCD / ARGB)

**ZettNAS Toolkit is completely hardware- and OS-agnostic.**
- If physical front-panel hardware (`/dev/fb0` or `/dev/ttyACM0`) is not present on your system, the toolkit automatically detects the absence during boot.
- The LCD renderer cleanly enters standby without throwing errors or consuming CPU cycles.
- The top-bar `MCU` and `FB` status indicators, as well as appliance-only menus, are dynamically hidden.
- The full glassmorphic Web Desktop, Docker orchestrator, storage visualizer, and file manager operate at 100% functionality over standard HTTP.

---

## Environment Variables Reference

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8082` | HTTP port for the Web Desktop and REST API |
| `WEB_PASSWORD` | (empty) | First-time admin password. Empty or `admin`: a random one is generated and shown in the log. Ignored once `users.db` exists |
| `ZETTNAS_DATA_KEY` | *(empty)* | Optional. Encrypts the AI search index and chat history at rest (SQLCipher, 16+ characters, e.g. `openssl rand -base64 32`). Keep it outside the data folder (Unraid template, or `.env` next to the compose file) and in a password manager. See SECURITY.md |
| `LOGIN_USER_CHOOSER` | `0` | Show user tiles on the login screen. Off by default because it lists account names to anyone who can open the login page |
| `CSRF_TRUSTED_ORIGINS` | *(empty)* | Extra origins (comma-separated, e.g. `https://nas.example.com`) allowed to make changes with the session cookie, for reverse proxies that rewrite the `Host` header |
| `DATA_DIR` | `/app/data` | Path to persistent database, sessions, tokens, and configuration |
| `STORAGE_POOL_PATH` | `/mnt/storage` | Root path mapped to host storage pool or Unraid user shares |
| `HOST_PROC` | `/host/proc` | Path to host procfs for real-time CPU, RAM, and network socket telemetry |
| `HOST_SYS` | `/host/sys` | Path to host sysfs for hwmon temperatures, fan PWM, and disk telemetry |
| `HOST_DEV` | `/host/dev` | Path to host devfs for block device discovery and disk serial lookups |
| `LCD_FPS` | `10` | Frame rate for physical LCD display (`1`–`30`) |
| `LCD_SLEEP_SEC` | `180` | Inactivity timer (seconds) before turning off physical LCD panel |
| `ZERO_RPM_ENABLED` | `true` | Enable Zero RPM fan mode for spun-down HDD bays |
| `ZERO_RPM_TEMP` | `40` | Temperature ceiling (°C) above which Zero RPM is prohibited |
| `ZERO_RPM_NVME` | `50` | NVMe temperature ceiling (°C) triggering convective airflow spinup |
| `TRUSTED_PROXIES` | `127.0.0.1` | Comma-separated list of reverse proxy IP addresses/CIDRs |
| `VM_ISO_DIR` | `/mnt/user/isos` | Directory for uploaded and downloaded guest ISO images |
| `TAILSCALE_STATE_DIR` | `/app/data/tailscale` | State and configuration directory for embedded Tailscale mesh node |
| `SFTP_PORT` | `2222` | Port for drop-in chrooted SFTP server |
| `UPDATE_CHANNEL` | `stable` | Update channel: `stable` (releases after a 7-day beta, `:latest`), `beta` (new releases right away, `:beta`) or `edge` (every commit on main); see docs/RELEASING.md |
| `ZETTNAS_OBSERVER_ADAPTER` | `auto` | Force storage adapter mode (`auto`, `generic`, `fygoos`, `zettos`, `ugos`, `truenas`, `proxmox`, `unraid`) |
| `ZETTNAS_LCD_CAPTURE` | `screencast` | How the front LCD gets frames: `screencast` (Chromium sends one only when the screen changes) or `poll` (a screenshot every frame) |
| `ZETTNAS_VIDEO_HWENC` | `auto` | Convert videos browsers can't play with Intel Quick Sync when `/dev/dri` is passed to the container (`--device /dev/dri`); `off` uses the CPU |
| `ZETTNAS_THUMB_CACHE_MB` | `1024` | Disk space for photo and video thumbnails (`data/cache/thumbs`); the least recently used are removed first |

---

## Volume Mounts & Data Persistence

Ensure your container preserves the following host volume:
- **`./data:/app/data`**: Houses the SQLite WAL user store (`users.db`), API tokens, fan curves (`fan_state.json`), wallpaper library, client preferences, and system event logs. Backing up this directory backs up your entire ZettNAS configuration.
- `data/cache/` holds thumbnails only. It can be deleted at any time and is not part of pre-update snapshots.

---

## Reverse Proxy & HTTPS Setup

To expose ZettNAS Toolkit behind Nginx, Caddy, Traefik, or Cloudflare Tunnel:
- Configure your reverse proxy to forward to `http://<server-ip>:8082`.
- **Disable buffering for Server-Sent Events (SSE)** on `/api/stats/stream` and `/api/events` (e.g. `proxy_buffering off;` in Nginx).
- For complete production reverse proxy configurations and SSL/TLS examples, see [`docs/REVERSE_PROXY.md`](REVERSE_PROXY.md).

---

## Local AI runtimes

ZettAI talks to an Ollama or OpenVINO Model Server (OVMS) runtime. It looks for one only on this NAS: `OLLAMA_HOST` / `LLM_HOST` if you set them, containers named `zettnas-ollama`, `ollama`, `zettnas-ovms` or `ovms` on a shared Docker network, then the Docker host itself. It never sends prompts to your router or other machines on the LAN unless you point `OLLAMA_HOST` there.

Neither runtime has a password. Don't publish their ports (11434, 8000) to the LAN; attach them to the ZettNAS network instead:

```yaml
services:
  zettnas-ollama:
    image: ollama/ollama
    networks: [zettnas]
    volumes:
      - ./ollama:/root/.ollama
    # no "ports:" section: only ZettNAS can reach it

networks:
  zettnas:
    external: true
    name: zettnas-toolkit_default   # the network your ZettNAS container is on
```

The Security Advisor warns when an AI container publishes a port on all interfaces. Web search and weather are off in chat unless you turn on **Web**, and answers that used outside services say so.

---

## Upgrades & Maintenance

### In-App Self-Updater (Web Desktop)
Administrators can check for updates and trigger 1-click container self-updates directly from the Web Desktop:
1. Open **Mission Control** → **System & Identity** → **System Updates**.
2. Select your preferred channel:
   - **Stable**: Official tagged production releases with changelog notes.
   - **Edge**: Latest tested commits from the GitHub `main` branch.
3. If an update is available, click **⚡ Update Now**. ZettNAS will pull the target container image via Docker socket, recreate the container, and verify daemon health.

### Upgrading via Docker Compose
```bash
cd ~/zettnas-toolkit
docker compose pull
docker compose up -d
```

### Upgrading via Unraid
In the Unraid WebUI, navigate to **Docker**, click **Check for Updates**, and click **Update** next to `zettnas-toolkit`.

---

## Troubleshooting & FAQ

#### Q: The WebUI shows "Permission Denied" on `/var/run/docker.sock`
**A**: Check that the socket is mounted (`-v /var/run/docker.sock:/var/run/docker.sock`) and that the container runs as root (the default) or as a user in the host's `docker` group:
```bash
ls -l /var/run/docker.sock      # usually root:docker, mode 660
getent group docker             # the group id to pass with --group-add
```
Do **not** run `chmod 666` on the socket: that gives every local user and every other container full root control of the host.

#### Q: Hard drive temperatures are not showing or reading `--`
**A**: Ensure `/dev` and `/sys` are mounted as specified in the compose file and that `cap_add: [SYS_RAWIO, SYS_ADMIN]` is present. ZettNAS uses `smartctl` with the `-n standby` flag to read drive temperatures safely without waking sleeping platters.

#### Q: How do I access WebDAV from Windows / macOS / iOS?
**A**: Port `8084` provides zero-conflict WebDAV access:
- **Windows**: File Explorer → Map Network Drive → `http://<server-ip>:8084`.
- **macOS**: Finder → Connect to Server (`Cmd+K`) → `http://<server-ip>:8084`.
- **iOS / Android**: Connect via the Files app or Owlfiles using your ZettNAS user credentials.

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
   - [Option E: Standalone Docker CLI (`docker run`)](#option-e-standalone-docker-cli-docker-run)
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
- **Port Availability**: Port `8082` (Web Desktop & REST API) and optionally Port `8084` (WebDAV Server).

---

## Default Credentials & Initial Access

- **Web Desktop URL**: `http://<server-ip>:8082`
- **Default Username**: `admin`
- **Default Password**: `admin`

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
         - WEB_PASSWORD=admin
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
         - 'c 29:* rwm'    # Framebuffer (/dev/fb0)
         - 'c 226:* rwm'   # DRI GPU devices
         - 'c 188:* rwm'   # USB Serial (/dev/ttyUSB*)
         - 'c 166:* rwm'   # USB ACM Serial (/dev/ttyACM*)
         - 'b 8:* rwm'     # SCSI/SATA hard drives (/dev/sd*)
         - 'b 259:* rwm'   # NVMe solid state drives (/dev/nvme*)
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
         - WEB_PASSWORD=admin
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

### Option E: Standalone Docker CLI (`docker run`)

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
  -e WEB_PASSWORD=admin \
  -e HOST_PROC=/host/proc \
  -e HOST_SYS=/host/sys \
  -e HOST_DEV=/host/dev \
  --cap-add SYS_RAWIO \
  --cap-add SYS_ADMIN \
  --device-cgroup-rule='c 29:* rwm' \
  --device-cgroup-rule='c 226:* rwm' \
  --device-cgroup-rule='c 166:* rwm' \
  --device-cgroup-rule='c 188:* rwm' \
  --device-cgroup-rule='b 8:* rwm' \
  --device-cgroup-rule='b 259:* rwm' \
  ghcr.io/fr0styx/zettnas-toolkit:latest
```

---

## Hardware Device & Capability Mappings

ZettNAS Toolkit accesses physical hardware through Linux device nodes and `cgroup` rules:

| Device Node | Major/Minor Rule | Purpose | Required? |
| :--- | :--- | :--- | :---: |
| `/dev/fb0` | `c 29:* rwm` | Physical front-panel IPS LCD display (640×172) | Optional |
| `/dev/dri/*` | `c 226:* rwm` | GPU hardware acceleration (Intel QuickSync, AMD ROCm) | Optional |
| `/dev/ttyACM0` | `c 166:* rwm` | WS2812B ARGB chassis lightbar USB microcontroller | Optional |
| `/dev/ttyUSB*` | `c 188:* rwm` | Alternative USB serial LED / MCU controllers | Optional |
| `/dev/sd*` | `b 8:* rwm` | Physical SATA/SAS hard drives and SD/TF card slots | Recommended |
| `/dev/nvme*` | `b 259:* rwm` | M.2 NVMe SSD storage and endurance telemetry | Recommended |
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
| `WEB_PASSWORD` | `admin` | Initial admin master password (overridden by `users.db` once set) |
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

---

## Volume Mounts & Data Persistence

Ensure your container preserves the following host volume:
- **`./data:/app/data`**: Houses the SQLite WAL user store (`users.db`), API tokens, fan curves (`fan_state.json`), wallpaper library, client preferences, and system event logs. Backing up this directory backs up your entire ZettNAS configuration.

---

## Reverse Proxy & HTTPS Setup

To expose ZettNAS Toolkit behind Nginx, Caddy, Traefik, or Cloudflare Tunnel:
- Configure your reverse proxy to forward to `http://<server-ip>:8082`.
- **Disable buffering for Server-Sent Events (SSE)** on `/api/stats/stream` and `/api/events` (e.g. `proxy_buffering off;` in Nginx).
- For complete production reverse proxy configurations and SSL/TLS examples, see [`docs/REVERSE_PROXY.md`](REVERSE_PROXY.md).

---

## Upgrades & Maintenance

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
**A**: Ensure your user or container runtime has access to the Docker socket. On Linux hosts, verify that the docker group has read/write permissions on the socket:
```bash
sudo chmod 666 /var/run/docker.sock
```

#### Q: Hard drive temperatures are not showing or reading `--`
**A**: Ensure `/dev` and `/sys` are mounted as specified in the compose file and that `cap_add: [SYS_RAWIO, SYS_ADMIN]` is present. ZettNAS uses `smartctl` with the `-n standby` flag to read drive temperatures safely without waking sleeping platters.

#### Q: How do I access WebDAV from Windows / macOS / iOS?
**A**: Port `8084` provides zero-conflict WebDAV access:
- **Windows**: File Explorer → Map Network Drive → `http://<server-ip>:8084`.
- **macOS**: Finder → Connect to Server (`Cmd+K`) → `http://<server-ip>:8084`.
- **iOS / Android**: Connect via the Files app or Owlfiles using your ZettNAS user credentials.

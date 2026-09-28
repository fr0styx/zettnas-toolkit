# ZettNAS Toolkit

An all-in-one chassis management suite and live front-panel LCD dashboard designed for Zettlab NAS enclosures (D4, D6, and D8 models) running Unraid or Debian/Docker environments.

This toolkit provides zero-overhead, direct-to-framebuffer rendering for the front display, intelligent thermal curve fan controls, dynamic RGB LED strip management with error-reactive lighting, and a web workbench for real-time monitoring and configuration.

---

## Features

- **Direct Framebuffer LCD Dashboard (/dev/fb0):**
  - Ultra-crisp 640x172 display output oriented specifically for the front panel via zero-overhead CSS orientation transforms and direct memory-mapped (mmap) writes.
  - Optimized active render loop delivering smooth animations (up to 30 FPS) with low sustained CPU overhead.
  - Live readout of storage pools, CPU utilization, thermals, memory, dual network throughput (RX/TX), active fan tachometers, and drive temperatures.
  - Per-drive health tracking (S.M.A.R.T. status) with visual I/O activity indicators.

- **Intelligent Thermal Fan Automation:**
  - Dual-zone SATA backplane fan regulation mapped to individual drive temperatures.
  - Optional CPU fan takeover with smooth step-up and temperature hysteresis hold timers to prevent annoying fan cycling.
  - Multiple presets: Auto (dynamic curve), Quiet, Balanced, Performance, and direct manual PWM control.

- **Chassis RGB Lightbar Control:**
  - Direct serial communication (/dev/ttyACM0 / CRC-validated protocol) with onboard chassis controllers.
  - Modes: Solid, Breathe, Flow, Chase, Gradient, Flashing, and smooth real-time Rainbow.
  - **Reactive Alerting:** Automatically overrides the lightbar with warning (amber breathe) or critical (red pulse) states if a drive reports S.M.A.R.T. degradation, CPU temp breaches 70C/85C, or a cooling fan stalls.

- **Interactive Web Studio & Workbench (Port 8082):**
  - Full-featured web interface mirroring the physical display.
  - Drag-and-drop module layout customization, component visibility toggles, and timezone configuration saved persistently.
  - Detailed S.M.A.R.T. inspection modal with raw attribute dumps.

---

## Hardware Compatibility

- **Zettlab Enclosures:** D4, D6, D8 (auto-detected via DMI product name or discovered drive topology).
- **Display:** Internal 640x172 LCD interfaced through /dev/fb0.
- **Fan Controller:** Motherboard hwmon supporting nct6775, it87, zettlab_d8_fans, or standard Linux PWM channels (pwm1-pwm3).
- **RGB Strip:** Built-in USB-to-serial microcontroller (ZettOS_RGB or /dev/ttyACM0).

---

## Installation & Deployment

### 1. Prerequisites (Unraid / Docker)

Ensure the front panel framebuffer device exists on your host:
```bash
ls -l /dev/fb0
```

Verify access to the chassis RGB controller:
```bash
ls -l /dev/ttyACM0
```

### 2. Clone the Repository

```bash
cd /mnt/user/appdata
git clone https://github.com/fr0styx/zettnas-toolkit.git
cd zettnas-toolkit
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` to match your local setup:
```ini
NAS_NAME=Ark
PORT=8082
STORAGE_POOL_PATH=/mnt/user
OS_NVME=nvme1n1
LCD_FPS=30
```

### 4. Deploy via Docker Compose

```bash
docker-compose up -d --build
```

---

## Acknowledgments & Credits

This project builds upon the foundational reverse-engineering, hardware discoveries, and utility scripts established by members of the community:

- **[torharrington/zettlab-display](https://github.com/torharrington/zettlab-display)** - Early framebuffer display proof-of-concepts, layout experiments, and initialization routines for Zettlab front-panel LCD screens.
- **[henryxwong/zettlab-ubuntu](https://github.com/henryxwong/zettlab-ubuntu)** - Detailed documentation on Zettlab hardware interfaces, fan controller registers (hwmon), LED serial packet structures, and Linux kernel integration.

Thank you for paving the way and making custom OS deployments on these chassis possible.

---

## License

This project is licensed under the [MIT License](LICENSE).

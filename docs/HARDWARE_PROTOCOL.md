# ZettNAS Toolkit — Hardware Protocol & Interface Reference

This document provides a low-level specification of the hardware interfaces, serial packet protocols, sysfs thermal paths, direct framebuffer bindings, and input mechanisms used by ZettNAS Toolkit.

---

## 1. Supported Hardware Platforms

| Chassis / Subsystem | Primary Controller | Fan Channels | LCD Display | ARGB Lightbar |
|---|---|---|---|---|
| **ZettLab D8** | Custom STM32 / CH340 + I2C hwmon | 2x Disk + 1x CPU | 172×640 (rotated 270°) | 24-LED WS2812B |
| **ZettLab D6U** | Embedded USB Serial | 2x Disk + 1x CPU | 172×640 (rotated 270°) | 18-LED WS2812B |
| **ZettLab D4** | USB Serial | 1x Disk + 1x CPU | Optional | 12-LED WS2812B |
| **Generic Homelab** | Standard Motherboard it87/nct6775 | Detected hwmon | Direct fb or WebUI only | Optional USB CDC |

---

## 2. ARGB Lightbar Protocol (WS2812B Serial)

The front panel lighting bar communicates over USB Serial CDC at **115200 baud, 8 data bits, no parity, 1 stop bit (8N1)**.

### 2.1 Packet Structure

Each serial packet sent to the microcontroller is structured as follows:

```
+------------+------------+------------+--------------------+------------+
| Header (2) |  Mode (1)  | Speed (1)  | RGB Payload (3..N) | Checksum/EOP|
| 0xAA  0x55 |    0x??    |  0x01..FF  |    R    G    B     |    0xEE    |
+------------+------------+------------+--------------------+------------+
```

### 2.2 Lighting Modes

| Mode Byte | Name | Description | Payload Data |
|---|---|---|---|
| `0x00` | **OFF** | All LEDs disabled (black) | None / 0x00 0x00 0x00 |
| `0x01` | **SOLID** | Static uniform color across all LEDs | `[R, G, B]` (0–255 each) |
| `0x02` | **BREATHE** | Smooth sinusoidal pulsing brightness | `[R, G, B]` + Speed byte |
| `0x03` | **RAINBOW** | Continuous chromatic spectrum wave | Speed byte |
| `0x04` | **CHASE** | Knight Rider / Cylon bouncing comet | `[R, G, B]` + Speed byte |
| `0x05` | **REACTIVE** | Real-time thermal gradient (Green → Yellow → Red) | Current highest drive temp (°C) |

---

## 3. Cooling Subsystem & Sysfs Fan Control

Thermal management interfaces directly with the Linux kernel hardware monitoring subsystem (`sysfs`).

### 3.1 Hwmon Discovery

The daemon traverses `/host/sys/class/hwmon/hwmon*` searching for compatible drivers:
- `zettlab_d8_fans` (dedicated chassis I2C driver)
- `nct6775` / `nct6798` (standard consumer boards)
- `it87` (Nuvoton / ITE SuperIO)
- `coretemp` / `k10temp` (CPU temperature inputs)

### 3.2 Sysfs Fan Controls & Safety Semantics

| Sysfs Node | Type | Perms | Valid Range | Function |
|---|---|---|---|---|
| `pwm1` | Integer | RW | `0..183` or `0..255` | Rear HDD Fan 1 Duty Cycle |
| `pwm2` | Integer | RW | `0..183` or `0..255` | Rear HDD Fan 2 Duty Cycle |
| `pwm3` | Integer | RW | `0..183` or `0..255` | CPU Fan Duty Cycle |
| `pwm1_enable` | Integer | RO/RW | `1` (Manual), `2` (Auto) | PWM1 mode control |
| `pwm2_enable` | Integer | RO/RW | `1` (Manual), `2` (Auto) | PWM2 mode control |
| `pwm3_enable` | Integer | RW | `1` (Manual), `2` (Auto) | PWM3 mode control |
| `fan1_input` | Integer | RO | RPM | Fan 1 Tachometer speed |
| `fan2_input` | Integer | RO | RPM | Fan 2 Tachometer speed |
| `fan3_input` | Integer | RO | RPM | Fan 3 Tachometer speed |

#### Hardware Safety Guarantees:
1. **Critical Temperature Floor**: Any HDD reading >= 55 °C or CPU >= 80 °C triggers a hard hardware override setting PWM to 100% duty cycle.
2. **Watchdog Failsafe**: If the control daemon crashes or stalls for > 15 seconds, firmware control (`pwmN_enable = 2`) is automatically restored.
3. **Shutdown Failsafe**: On `SIGTERM` or `SIGINT`, fans are locked to full speed / firmware auto before process termination.

---

## 4. Direct LCD Framebuffer (`/dev/fb0`)

The physical front-panel telemetry screen is driven directly via the Linux Framebuffer driver.

### 4.1 Panel Geometry & Memory Mapping

```
Native Panel Orientation (Portrait):
   +-----------------------+
   | (0, 0)         W: 172 |
   |                       |
   |                       |
   |                       |
   |                       |  Height: 640
   |                       |
   |                       |
   |              (171,639)|
   +-----------------------+
Hardware Stride: 704 bytes / row (padded)
Pixel Format: 32-bit BGRA (8 bits per channel)
```

### 4.2 Rendering Pipeline

1. **Chromium Canvas Capture**: Playwright headless browser renders `index.html?mode=lcd` into memory at native `640x172`.
2. **Buffer Transformation**:
   - Rotated 270° counter-clockwise to match physical portrait orientation.
   - Padded row-stride to align with 704-byte hardware stride.
   - Converted to BGRA byte order.
3. **Direct Memory Write**: Transformed byte buffer is written directly to `/dev/fb0` via `open('/dev/fb0', 'wb')`.
4. **Backlight Control**: Display brightness is regulated via `/sys/class/backlight/*/brightness`.

---

## 5. Front-Panel Button & Event Daemon

The chassis front-panel momentary switch is handled through Linux GPIO sysfs or the `evdev` event interface.

### 5.1 Click Thresholds & Actions

- **Debounce Window**: 50ms noise rejection filter.
- **Short Press (< 1000ms)**:
  - If LCD is sleeping: Wakes display and restores backlight.
  - If LCD is awake: Cycles dashboard carousel pages.
- **Long Press (>= 2000ms)**:
  - Initiates one-touch storage ingest / SD card copy workflow.
  - Confirmation status is displayed directly on the physical screen.

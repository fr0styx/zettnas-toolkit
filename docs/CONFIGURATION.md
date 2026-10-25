# Configuration

Environment variables ZettNAS reads at startup. Generated from `backend/settings.py`
(`python -m backend.settings --markdown > docs/CONFIGURATION.md`); a value that can't be
used keeps its default, and the log says which variable and why.

## Host

| Variable | Default | Meaning |
|---|---|---|
| `HOST_PROC` | `/host/proc` | Where the host's /proc is mounted. |
| `HOST_SYS` | `/host/sys` | Where the host's /sys is mounted. |
| `HOST_DEV` | `/host/dev` | Where the host's /dev is mounted. |
| `DISKS` | `(empty)` | Comma-separated disks to show when they can't be detected. |
| `OS_NVME` | `nvme1n1` | The NVMe device the operating system runs from, hidden from data disks. |
| `SHOW_OS_DISK` | `on` | Show the operating-system disk in the disk list. |
| `REMOTES_PATH` | `/mnt/remotes` | Where cloud and network remotes are mounted. |

## Web

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8082` | Port of the web interface. (1–65535) |
| `TRUSTED_PROXIES` | `127.0.0.1, ::1` | Reverse proxies whose X-Forwarded-For is believed (comma-separated). |
| `ENABLE_PROXY_SSO` | `off` | Accept a signed-in user from a trusted proxy's header. |
| `CSRF_TRUSTED_ORIGINS` | `(none)` | Extra origins allowed to send requests that change things (comma-separated). |
| `ENABLE_API_DOCS` | `off` | Serve the interactive API documentation at /api/docs. |
| `LOGIN_USER_CHOOSER` | `off` | Show a list of users on the sign-in page. |
| `MAX_BODY_MB` | `16` | Largest request body accepted, in MB (uploads excepted). (1–4096) |
| `MAX_WALLPAPER_MB` | `10` | Largest wallpaper upload, in MB. (1–1024) |
| `MAX_UPLOAD_GB` | `64` | Largest file upload, in GB. (1–100000) |

## File services

| Variable | Default | Meaning |
|---|---|---|
| `SFTP_PORT` | `2222` | Port of the built-in SFTP server. (1–65535) |
| `WEBDAV_PORT` | `8084` | Port of the built-in WebDAV server. (1–65535) |

## Updates

| Variable | Default | Meaning |
|---|---|---|
| `UPDATE_CHANNEL` | `stable` | Release channel to follow. (one of `stable`, `beta`, `edge`) |
| `UPDATE_SIGNATURES` | `enforce` | In-app updates check the image's signature from this project's CI first: enforce (refuse an unsigned or wrongly signed image), warn (log it and install anyway) or off. (one of `enforce`, `warn`, `off`) |
| `ZETTNAS_IMAGE_VARIANT` | `full` | full ships VMs and the LCD renderer; core leaves them out. (one of `full`, `core`) |

## Power

| Variable | Default | Meaning |
|---|---|---|
| `UPS_MODE` | `auto` | How to reach the UPS (auto, nut, usb, ...). |
| `NUT_HOST` | `127.0.0.1` | Network UPS Tools server. |
| `NUT_PORT` | `3493` | Network UPS Tools port. (1–65535) |
| `NUT_NAME` | `ups` | UPS name on the NUT server. |

## Front panel

| Variable | Default | Meaning |
|---|---|---|
| `ENABLE_FB` | `on` | Drive the front LCD. |
| `LCD_FPS` | `5` | Frames per second sent to the front LCD. (1–30) |
| `LCD_FORMAT` | `jpeg` | Image format of LCD frames. (one of `jpeg`, `png`) |
| `LCD_RENDERER` | `auto` | What draws the front LCD: chromium (the web dashboard), pil (drawn directly, no browser) or auto (chromium when installed, otherwise pil). (one of `auto`, `chromium`, `pil`) |
| `LCD_SLEEP_SEC` | `300` | Seconds without activity before the LCD dims. (0–86400) |

## Disks

| Variable | Default | Meaning |
|---|---|---|
| `SMART_POLL_HDD` | `45` | Seconds between SMART reads of spinning disks. (5–86400) |
| `SMART_POLL_NVME` | `15` | Seconds between SMART reads of NVMe disks. (5–86400) |
| `SMART_IDLE_ADAPTIVE` | `off` | Read SMART less often from spinning disks with no recent activity, so they can spin down. |
| `SMART_IDLE_POLL` | `1800` | Seconds between SMART reads of an idle spinning disk. (60–86400) |
| `HDD_WARN_TEMP` | `50` | Hard disk temperature that raises a warning, °C. (20–100) |
| `HDD_CRITICAL_TEMP` | `55` | Hard disk temperature that forces full fan speed, °C. (20–100) |
| `NVME_WARN_TEMP` | `70` | NVMe temperature that raises a warning, °C. (20–110) |
| `NVME_CRITICAL_TEMP` | `75` | NVMe temperature that forces full fan speed, °C. (20–110) |
| `COLLECTOR_WATCHDOG_SECS` | `20` | Seconds without fresh stats before health reports degraded. (5–3600) |

## Fans

| Variable | Default | Meaning |
|---|---|---|
| `FAN_FAILSAFE_PWM` | `150` | Fan PWM when the CPU temperature can't be read. (0–255) |
| `FAN_KICKSTART_PWM` | `150` | PWM used to start a stopped fan. (0–255) |
| `FAN_KICKSTART_SECS` | `2.0` | Seconds of kick-start PWM. (0–60) |
| `FAN_SPINUP_GRACE_SECS` | `6.0` | Seconds a starting fan may show 0 RPM before it counts as stalled. (0–120) |
| `FAN_DISK_HOLD_SECS` | `30` | Seconds disk fans hold a higher speed before slowing down. (0–3600) |
| `FAN_CPU_HOLD_SECS` | `30` | Seconds the CPU fan holds a higher speed before slowing down. (0–3600) |
| `ZERO_RPM_ENABLED` | `off` | Default for stopping the disk fans while all disks sleep. |
| `FAN_ZERO_RPM_STOP_DELAY` | `30` | Seconds disks must sleep before the fans stop. (0–3600) |
| `FAN_ZERO_RPM_NVME_CEILING` | `50` | Highest NVMe temperature at which fans may stop, °C. (20–100; also read as `ZERO_RPM_NVME`) |
| `FAN_ZERO_RPM_STOP_TEMP` | `34` | Disk bay temperature at or below which fans may stop, °C. (15–80; also read as `ZERO_RPM_TEMP`) |
| `FAN_ZERO_RPM_START_TEMP` | `38` | Disk bay temperature that restarts stopped fans, °C. (15–90) |

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
| `HOST_ETC` | `/host/etc` | Where the host's /etc is mounted. |
| `ZETTNAS_OBSERVER_MODE` | `off` | Only watch the host on an unknown system: read-only telemetry, no changes. |
| `SQLITE_VEC_PATH` | `(empty)` | Extra place to look for the sqlite-vec library (vec0.so) for AI search. |
| `HOST_NET_IFACE` | `(empty)` | Network interface whose traffic the dashboard shows; empty = all physical ones. |
| `CONTAINERIZED` | `off` | Say ZettNAS runs in a container when it can't tell by itself. |
| `ZETTNAS_THUMB_CACHE_MB` | `1024` | Size of the preview thumbnail cache, in MB (at least 16). (0–1.04858e+06) |
| `SYNC_ROUTE_THREADS` | `40` | Threads for API requests that wait on files, disks or Docker; more serve more people at once and use more memory. (8–256) |
| `APP_MEMORY_WARN_MB` | `1536` | Warn when ZettNAS itself uses more memory than this, in MB (virtual machines not counted); 0 = off. (0–1.04858e+06) |

## Web

| Variable | Default | Meaning |
|---|---|---|
| `ZETTNAS_PUSH_CONTACT` | `https://github.com/fr0styx/zettnas-toolkit` | Contact address sent to browser push services with each notification. |
| `PORT` | `8082` | Port of the web interface. (1–65535) |
| `TRUSTED_PROXIES` | `127.0.0.1, ::1` | Reverse proxies whose X-Forwarded-For is believed (comma-separated). |
| `ENABLE_PROXY_SSO` | `off` | Accept a signed-in user from a trusted proxy's header. |
| `CSRF_TRUSTED_ORIGINS` | `(none)` | Extra origins allowed to send requests that change things (comma-separated). |
| `ENABLE_API_DOCS` | `off` | Serve the interactive API documentation at /api/docs. |
| `LOGIN_USER_CHOOSER` | `off` | Show a list of users on the sign-in page. |
| `MAX_BODY_MB` | `16` | Largest request body accepted, in MB (uploads excepted). (1–4096) |
| `MAX_WALLPAPER_MB` | `10` | Largest wallpaper upload, in MB. (1–1024) |
| `MAX_UPLOAD_GB` | `64` | Largest file upload, in GB. (1–100000) |
| `ZETTNAS_TRUSTED_IPS` | `(none)` | Addresses or networks (CIDR) never blocked after failed sign-ins, comma-separated. |

## File services

| Variable | Default | Meaning |
|---|---|---|
| `AUTO_INGEST_ENABLED` | `off` | Copy a card as soon as it is inserted, even when Automatic Slot Ingest is off in the settings. |
| `SFTP_PORT` | `2222` | Port of the built-in SFTP server. (1–65535) |
| `WEBDAV_PORT` | `8084` | Port of the built-in WebDAV server. (1–65535) |

## Updates

| Variable | Default | Meaning |
|---|---|---|
| `UPDATE_CHANNEL` | `stable` | Release channel to follow. (one of `stable`, `beta`, `edge`) |
| `UPDATE_SIGNATURES` | `enforce` | In-app updates check the image's signature from this project's CI first: enforce (refuse an unsigned or wrongly signed image), warn (log it and install anyway) or off. (one of `enforce`, `warn`, `off`) |
| `ZETTNAS_IMAGE_VARIANT` | `full` | full ships VMs and the LCD renderer; core leaves them out. (one of `full`, `core`) |
| `HEALTH_SIGNAL_URL` | `(empty)` | Where the opt-in anonymous health report goes; empty uses the project's receiver. |
| `BUILD_COMMIT` | `(empty)` | The commit the image was built from; set by the image build. |
| `BUILD_DATE` | `(empty)` | When the image was built; set by the image build. |

## Logs

| Variable | Default | Meaning |
|---|---|---|
| `LOG_FORMAT` | `text` | Log lines as plain text, or as one JSON object per line (with a request id) for log collectors. (one of `text`, `json`) |
| `ZETTNAS_AUDIT_RETENTION_DAYS` | `365` | Days the security audit log keeps an event; 0 keeps everything. (0–36500) |

## Host

| Variable | Default | Meaning |
|---|---|---|
| `ZETTNAS_GIL_SWITCH_SECS` | `0.02` | How long a Python thread runs before handing over to another, in seconds; longer means fewer wakeups. (0.001–1) |
| `LAYOUT_PATH` | `(empty)` | The desktop layout file; empty keeps it in the data folder. |
| `BACKUP_DIR` | `(empty)` | Where settings backups go; empty keeps them in the data folder. |
| `VM_ISO_DIR` | `(empty)` | The ISO library for virtual machines; empty keeps it in the data folder. |
| `TAILSCALE_STATE_DIR` | `(empty)` | Tailscale's state folder; empty keeps it in the data folder. |
| `HOST_IP` | `(empty)` | The server's address, when it can't be found by itself. |

## Power

| Variable | Default | Meaning |
|---|---|---|
| `UPS_MODE` | `auto` | How to reach the UPS (auto, nut, usb, ...). |
| `NUT_HOST` | `127.0.0.1` | Network UPS Tools server. |
| `NUT_PORT` | `3493` | Network UPS Tools port. (1–65535) |
| `NUT_NAME` | `ups` | UPS name on the NUT server. |
| `UPS_FAILSAFE_BATTERY_MIN` | `20.0` | Battery percent that counts as low when the UPS settings can't be read. (0–100) |
| `UPS_FAILSAFE_RUNTIME_MIN` | `5.0` | Minutes of runtime that count as low when the UPS settings can't be read. (0–1440) |

## Front panel

| Variable | Default | Meaning |
|---|---|---|
| `ENABLE_FB` | `on` | Drive the front LCD. |
| `LCD_FPS` | `5` | Frames per second sent to the front LCD. (1–30) |
| `LCD_FORMAT` | `jpeg` | Image format of LCD frames. (one of `jpeg`, `png`) |
| `LCD_RENDERER` | `auto` | What draws the front LCD: chromium (the web dashboard), pil (drawn directly, no browser) or auto (chromium when installed, otherwise pil). (one of `auto`, `chromium`, `pil`) |
| `LCD_SLEEP_SEC` | `300` | Seconds without activity before the LCD dims. (0–86400) |
| `ZETTNAS_LCD_CAPTURE` | `screencast` | How the front LCD gets its frames: pushed when the page changes, or a screenshot every frame. (one of `screencast`, `poll`) |

## Disks

| Variable | Default | Meaning |
|---|---|---|
| `SMART_POLL_HDD` | `45` | Seconds between SMART reads of spinning disks. (5–86400) |
| `SMART_POLL_NVME` | `60` | Seconds between SMART reads of NVMe disks. (5–86400) |
| `SMART_IDLE_ADAPTIVE` | `on` | Read SMART less often from spinning disks with no recent activity, so they can spin down. |
| `SMART_IDLE_POLL` | `1800` | Seconds between SMART reads of an idle spinning disk. (60–86400) |
| `HDD_WARN_TEMP` | `50` | Hard disk temperature that raises a warning, °C. (20–100) |
| `HDD_CRITICAL_TEMP` | `55` | Hard disk temperature that forces full fan speed, °C. (20–100) |
| `NVME_WARN_TEMP` | `70` | NVMe temperature that raises a warning, °C. (20–110) |
| `NVME_CRITICAL_TEMP` | `75` | NVMe temperature that forces full fan speed, °C. (20–110) |
| `COLLECTOR_WATCHDOG_SECS` | `20` | Seconds without fresh stats before health reports degraded. (5–3600) |
| `ZETTNAS_STANDBY_UNKNOWN` | `defer` | When it can't tell which disk holds a folder: defer the work (it may be asleep) or check anyway. (one of `defer`, `allow`) |

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

## AI and media

| Variable | Default | Meaning |
|---|---|---|
| `ZETTNAS_AI_NUM_CTX` | `0` | Chat context window in tokens; 0 uses the built-in size, values under 2048 are ignored. (0–1.04858e+06) |
| `ZETTNAS_VIDEO_HWENC` | `auto` | Convert videos with the iGPU when it can (auto) or always in software (off). (one of `auto`, `off`) |
| `OLLAMA_HOST` | `(empty)` | The Ollama server (host, host:port or URL); empty finds it. |
| `LLM_HOST` | `(empty)` | Older name for OLLAMA_HOST, read when that is empty. |

## Platforms

| Variable | Default | Meaning |
|---|---|---|
| `TRUENAS_VERIFY_TLS` | `on` | Check the TrueNAS certificate; off accepts a self-signed one. |
| `UNRAID_API_VERIFY_TLS` | `on` | Check the Unraid API certificate; off accepts any. |
| `UNRAID_EMHTTP_DIR` | `(empty)` | Unraid's emhttp state folder, when it isn't in a usual place. |
| `ZETTNAS_PLATFORM` | `(empty)` | Which host this is (unraid, truenas, zettos, ...); empty detects it. |
| `ZETTNAS_OBSERVER_ADAPTER` | `(empty)` | The host to read in observer mode; empty or auto detects it. |
| `ZETTNAS_PAL_MODE` | `(empty)` | observer, readonly or telemetry: only read the host, never change it. |

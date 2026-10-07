# ZettNAS Toolkit REST API Reference

All routes are mounted at `/api` (with the versioned alias `/api/v1`). The daemon exposes a comprehensive RESTful interface and Server-Sent Events (SSE) stream for telemetry, hardware diagnostics, acoustic controls, Unraid management, Docker orchestration, and media auto-ingest.

---

## Authentication & Headers

Protected endpoints require authentication. The daemon accepts tokens via any of the following mechanisms:

1. **HTTP Header (Recommended)**:
   ```http
   X-ZettNAS-Token: <your_session_or_api_token>
   ```
2. **Query Parameter** (ideal for SSE event sources, image tags, or direct downloads):
   ```http
   GET /api/stats/stream?token=<your_token>
   ```
3. **Session Cookie**:
   Automated browser sessions transmit session credentials established via `/api/auth/login`.

Persistent scoped tokens can be provisioned and managed via `/api/tokens`.

---

## Endpoint Catalog

### 1. Telemetry & Live Streaming

| Endpoint | Method | Auth | Description |
| :--- | :---: | :---: | :--- |
| `/api/stats` | `GET` | Yes | Real-time snapshot of CPU, RAM, temperatures, disks, fan tachometers, ARGB lightbar, Unraid state, and UPS telemetry. |
| `/api/stats/stream` | `GET` | Yes | Server-Sent Events (SSE) stream delivering zero-latency telemetry ticks (~1 Hz) directly to connected frontends. |
| `/api/history` | `GET` | Yes | Historical time-series telemetry. Accepts `?range=1h\|6h\|24h\|7d\|30d` for CPU/RAM/disks/fans pan/zoom charting. |
| `/api/health` | `GET` | No | Public daemon liveness probe returning thread heartbeat statuses and collector uptime. |

#### SSE Event Streaming Example
```bash
curl -N -H "X-ZettNAS-Token: $TOKEN" https://nas.local:8082/api/stats/stream
```

---

### 2. System & Subsystem Management

| Endpoint | Method | Auth | Description |
| :--- | :---: | :---: | :--- |
| `/api/system/profile` | `POST` | Yes | Apply unified thermal/acoustic profiles (`auto`, `quiet`, `balanced`, `performance`). |
| `/api/unraid` | `GET` | Yes | Query Unraid array state, disk sync/parity check status, mover activity, and individual array drive allocations. |
| `/api/docker/containers` | `GET` | Yes | List local Docker containers, images, runtime states (`running`, `exited`), and health metrics. |
| `/api/docker/containers/{id}/action` | `POST` | Yes | Dispatch container lifecycle actions: `start`, `stop`, `restart`, `pause`, `unpause`. |
| `/api/ups` | `GET` | Yes | Direct NUT socket telemetry: battery charge %, estimated runtime, current load, and utility line voltage. |

---

### 3. Hardware Controls & Diagnostics

| Endpoint | Method | Auth | Description |
| :--- | :---: | :---: | :--- |
| `/api/fans` | `GET` | Yes | Read current fan RPMs, PWM values, and active curve profiles across all zones. |
| `/api/fans` | `POST` | Yes | Update fan speeds: manual PWM duty cycles (0–255), preset profiles, or multi-point temperature curves. |
| `/api/led` | `GET` | Yes | Query WS2812B lightbar state: power, effect mode, colors, brightness, and blackout window. |
| `/api/led` | `POST` | Yes | Update lightbar animation (`breathing`, `rainbow`, `chase`, `solid`, `alert`), colors, or night blackout hours. |
| `/api/screen` | `GET` | Yes | Query front-panel 640×172 LCD backlight brightness and power state. |
| `/api/state` | `POST` | Yes | Set front-panel LCD backlight brightness level (0–100%). |
| `/api/lcd_status` | `GET` | Yes | Inspect headless Chromium `/dev/fb0` renderer health, render loop FPS, and frame drop metrics. |
| `/api/lcd/page` | `GET` | Yes | Get the active carousel page index on the front-panel LCD. |
| `/api/lcd/page` | `POST` | Yes | Jump front-panel LCD directly to a specific page index. |
| `/api/lcd/cycle` | `POST` | Yes | Advance front-panel LCD immediately to the next telemetry page. |
| `/api/disk_detail` | `GET` | Yes | Fetch drive identity, serial number, S.M.A.R.T. attributes, wear level, and power standby state (`?dev=sda`). |
| `/api/disk/smart_test` | `POST` | Yes | Trigger background Short or Extended S.M.A.R.T. self-test on disk. |
| `/api/disk_wake` | `POST` | Yes | Send spin-up command to an idle or spun-down disk for inspection. |

---

### 4. Media Ingest & Filesystem Management

| Endpoint | Method | Auth | Description |
| :--- | :---: | :---: | :--- |
| `/api/browse` | `GET` | Yes | Explore directories within allowed storage pool roots (`?path=...`). |
| `/api/mkdir` | `POST` | Yes | Create a new destination directory within the storage pool boundaries. |
| `/api/fs/upload` | `POST` | Yes | High-efficiency chunked streaming file upload (`request.stream()`) with path containment checks. |
| `/api/fs/delete` | `POST` | Yes | Remove files or directories within allowed storage boundaries. |
| `/api/fs/rename` | `POST` | Yes | Rename files or folders within allowed storage pool boundaries. |
| `/api/media_slots` | `GET` | Yes | Query SD and TF card slot insertion status, device nodes, capacity, and auto-ingest readiness. |
| `/api/media_slots/rescan` | `POST` | Yes | Force SCSI bus rescanning and kernel partition table re-read for card reader slots. |
| `/api/media_slots/eject` | `POST` | Yes | Safely unmount filesystem, flush kernel buffers, and mark card reader slot as safely ejected. |
| `/api/copy/confirm` | `POST` | Yes | Initiate card reader media import job with optional SHA-256 verification and dated target folder creation. |
| `/api/copy/pause` | `POST` | Yes | Pause an active media copy job. |
| `/api/copy/resume` | `POST` | Yes | Resume a paused media copy transfer. |
| `/api/copy/cancel` | `POST` | Yes | Abort an active transfer with partial file cleanup. |
| `/api/copy/history` | `GET` | Yes | Query persistent SQLite media ingest history, speed stats, and SHA-256 verification logs. |

---

### 5. Configuration, Notifications & Security

| Endpoint | Method | Auth | Description |
| :--- | :---: | :---: | :--- |
| `/api/layout` | `GET` | Yes | Read front-panel card ordering, visibility, and clock 12h/24h format settings. |
| `/api/layout` | `POST` | Yes | Persist customized front-panel layout configuration. |
| `/api/notifications/config` | `GET` | Yes | Retrieve multi-channel notification dispatch settings. |
| `/api/notifications/config` | `POST` | Yes | Save notification settings (Unraid native notify, ntfy.sh, Discord webhooks, severity filters). |
| `/api/notifications/test` | `POST` | Yes | Send a test notification alert across all configured channels. |
| `/api/auth/login` | `POST` | No | Authenticate with administrator password and obtain session token. |
| `/api/auth/logout` | `POST` | Yes | Terminate current session token. |
| `/api/security` | `GET` | Yes | Check whether default password (`admin`) is active and inspect TLS status. |
| `/api/security` | `POST` | Yes | Change master administration password. |
| `/api/wallpapers` | `GET` | Yes | List custom desktop wallpaper images. |
| `/api/wallpapers/upload` | `POST` | Yes | Upload and validate a custom desktop background image. |
| `/api/backup/export` | `GET` | Yes | Export configuration, SQLite databases, and settings as a verified zip archive. |
| `/api/backup/restore` | `POST` | Yes | Restore configuration from an uploaded backup zip with zip-slip path protection. |
| `/api/tokens` | `GET` | Yes | List active API tokens with expiration dates and creation timestamps. |
| `/api/tokens` | `POST` | Yes | Create a new scoped API token with optional expiration and label. |
| `/api/tokens/{id}` | `DELETE` | Yes | Revoke an existing API token. |
| `/api/events/clear` | `DELETE` | Yes | Clear non-critical events from the persistent hardware event log. |

---

## Response Formats & Error Handling

Standard responses are returned as `application/json`. Errors adhere to standard HTTP status codes:

```json
{
  "detail": "Descriptive error message"
}
```

* `400 Bad Request` — Invalid input, out-of-range fan curve value, or malformed JSON payload.
* `401 Unauthorized` — Missing or invalid authentication token.
* `403 Forbidden` — Path traversal attempt or access outside allowed storage roots.
* `404 Not Found` — Disk, container, file, or token ID not found.
* `409 Conflict` — Copy job or S.M.A.R.T. self-test already in progress on target device.
* `500 Internal Server Error` — Hardware communication failure or unexpected exception.

# ZettNAS Toolkit REST API Reference

All routes are mounted at `/api` (with the versioned alias `/api/v1`). The daemon exposes a comprehensive RESTful interface, Server-Sent Events (SSE) live streaming, and interactive WebSocket endpoints for hardware orchestration, storage topology, multi-user identity, Docker stacks, and remote cloud storage.

---

## Authentication & Authorization

Protected endpoints enforce Role-Based Access Control (RBAC). The daemon accepts authentication through any of the following mechanisms:

1. **HTTP Authorization Header (Recommended for CLI / curl / Scripts)**:
   ```http
   Authorization: Bearer <your_session_or_zat_token>
   ```
2. **Legacy HTTP Token Header**:
   ```http
   X-ZettNAS-Token: <your_session_or_zat_token>
   ```
3. **Query Parameter** (Ideal for Server-Sent Events streams, raw browser downloads, and image tags):
   ```http
   GET /api/stats/stream?token=<your_token>
   ```
4. **HttpOnly SameSite Session Cookie**:
   Automated browser sessions transmit session credentials established via `/api/auth/login`.

Persistent scoped tokens can be provisioned and managed via `/api/tokens`.

---

## Endpoint Catalog

### 1. Identity, Multi-User & RBAC

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/auth/login` | `POST` | Public | Authenticate with username and password, returns session cookie and token. |
| `/api/auth/logout` | `POST` | Yes | Invalidate active session and clear session cookies. |
| `/api/auth/me` | `GET` | Yes | Get currently authenticated user principal, role, and granted scopes. |
| `/api/auth/users-list` | `GET` | Public | List user display cards for the desktop avatar chooser screen. |
| `/api/auth/users` | `GET` | `users:read` | Inventory all user accounts, roles, storage quotas, and MFA status. |
| `/api/auth/users` | `POST` | `users:write` | Provision a new user account with role, home directory, and storage quota. |
| `/api/auth/users/{id}` | `PUT` | `users:write` | Update user details, role assignment, quota, or disable account. |
| `/api/auth/users/{id}` | `DELETE` | `users:delete` | Delete user account and revoke all associated sessions. |
| `/api/auth/roles` | `GET` | `users:read` | List system RBAC roles (`SuperAdmin`, `StorageAdmin`, `AppOperator`, `ShareUser`, `Auditor`). |
| `/api/auth/sessions` | `GET` | Yes | List active login sessions and devices for the current or specified user. |
| `/api/auth/sessions/{id}` | `DELETE` | Yes | Revoke a specific active login session. |
| `/api/auth/totp/setup` | `POST` | Yes | Generate RFC 6238 TOTP secret, provisioning URI (`otpauth://`), and QR code. |
| `/api/auth/totp/verify` | `POST` | Yes | Verify 6-digit TOTP code and enable MFA; returns single-use recovery codes. |
| `/api/auth/totp/disable` | `POST` | Yes | Disable MFA after validating current password or backup code. |
| `/api/tokens` | `GET` | `tokens:read` | List active scoped API tokens (`zat_****`) with CIDR masks and expiration. |
| `/api/tokens` | `POST` | `tokens:write` | Create a new scoped API token with specific permission scopes. |
| `/api/tokens/{id}` | `DELETE` | `tokens:delete` | Permanently revoke an API token. |

---

### 2. Telemetry & Live Streaming

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/stats` | `GET` | Yes | Snapshot of CPU %, RAM, storage pools, disk temperatures, fan RPMs, ARGB state, and UPS. |
| `/api/stats/stream` | `GET` | Yes | Server-Sent Events (SSE) stream broadcasting ~1 Hz real-time hardware telemetry ticks. |
| `/api/events` | `GET` | Yes | Real-time SSE stream for hardware alerts, container updates, and copy jobs. |
| `/api/history` | `GET` | Yes | Historical time-series metrics. Accepts `?range=1h\|6h\|24h\|7d\|30d` for telemetry charting. |
| `/api/health` | `GET` | Public | Liveness probe returning component daemon heartbeats and system uptime. |

---

### 3. Storage & Platform Abstraction Layer (PAL)

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/storage/pools` | `GET` | `storage:read` | Unified storage pools across Btrfs RAID, Unraid array, and ZFS datasets. |
| `/api/storage/disks` | `GET` | `storage:read` | Physical disk inventory (SATA, NVMe, SAS, USB) with standby states and SMART health. |
| `/api/storage/bay-slots` | `GET` | `storage:read` | Dynamic chassis bay slot mapping for 2.5D visualizer digital twin. |
| `/api/storage/bay-slots` | `POST` | `storage:admin` | Save custom disk-to-bay assignment mappings. |
| `/api/storage/locate` | `POST` | `hardware:write` | Trigger quad-action locate strobe (disk activity pulse, ARGB beacon, audio chirp). |
| `/api/disk_detail` | `GET` | `storage:read` | Query comprehensive SMART attributes, NVMe wear %, and health log (`?dev=sda`). |
| `/api/disk/smart_test` | `POST` | `storage:admin` | Launch background Short or Extended SMART self-test. |
| `/api/disk_wake` | `POST` | `storage:admin` | Spin up an idle hard drive from standby for inspection. |

---

### 4. Docker Containers, Stacks & App Catalog

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/docker/containers` | `GET` | `containers:read` | List containers, images, status, live CPU %, and memory usage. |
| `/api/docker/containers/{id}/action` | `POST` | `containers:write` | Container lifecycle actions: `start`, `stop`, `restart`, `pause`, `unpause`. |
| `/api/docker/containers/{id}/details`| `GET` | `containers:read` | Full container inspect metadata (ports, mounts, env, resource limits). |
| `/api/docker/containers/{id}/logs` | `GET` | `containers:read` | Stream multiplexed stdout/stderr container logs with tail depth filter. |
| `/api/docker/containers/{id}/exec` | `POST` | `containers:exec` | Interactive container web terminal execution (`/bin/sh` or `/bin/bash`). |
| `/api/docker/containers/{id}/update-image` | `POST` | `containers:manage` | Pull latest image, recreate container, and verify health with rollback. |
| `/api/docker/stacks` | `GET` | `containers:read` | Discover and list active Docker Compose stacks and projects. |
| `/api/docker/stacks/{name}` | `GET` | `containers:read` | Fetch synthesized or original `docker-compose.yml` for stack. |
| `/api/docker/stacks/{name}` | `POST` | `containers:manage` | Save modified Compose stack and trigger rolling restart. |
| `/api/docker/updates/status` | `GET` | `containers:read` | Retrieve cached container image update availability. |
| `/api/docker/updates/check` | `POST` | `containers:read` | Trigger fresh remote registry check for container updates. |
| `/api/docker/updates/apply-all` | `POST` | `containers:manage` | Batch-update all containers with pending image updates. |
| `/api/docker/catalog` | `GET` | `containers:read` | Browse curated 25+ homelab application template catalog. |
| `/api/docker/system/df` | `GET` | `containers:read` | Inspect reclaimable Docker disk space (images, containers, volumes, cache). |
| `/api/docker/system/prune` | `POST` | `containers:manage` | Execute Docker system prune with custom resource filters. |

---

### 5. Remote Cloud Storage & WebDAV

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/webdav/status` | `GET` | `shares:read` | Inspect universal WebDAV file server status (Port `8084`). |
| `/api/remotes` | `GET` | `storage:read` | List configured Rclone multi-cloud remotes (S3, B2, Google Drive, OneDrive). |
| `/api/remotes/mount` | `POST` | `storage:admin` | Mount remote cloud bucket into local storage hierarchy via FUSE. |
| `/api/remotes/unmount` | `POST` | `storage:admin` | Safely unmount an active cloud remote mount. |
| `/api/remotes/sync` | `POST` | `storage:admin` | Execute scheduled or 1-click cloud synchronization job. |

---

### 6. Hardware Controls & Diagnostics

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/fans` | `GET` | `hardware:read` | Read fan tachometers, PWM duty cycles, and active thermal curve profile. |
| `/api/fans` | `POST` | `hardware:fans` | Set fan PWM, 6-point temperature curves, or Zero RPM standby parameters. |
| `/api/led` | `GET` | `hardware:read` | Query WS2812B ARGB lightbar power, animation mode, colors, and brightness. |
| `/api/led` | `POST` | `hardware:led` | Update lightbar animation (`breathing`, `rainbow`, `chase`, `solid`, `alert`). |
| `/api/screen` | `GET` | `hardware:read` | Query front-panel 640×172 LCD backlight brightness and power state. |
| `/api/state` | `POST` | `hardware:write`| Set front-panel LCD brightness (0–100%). |
| `/api/lcd/page` | `GET` | `hardware:read` | Get active carousel page index on front-panel LCD. |
| `/api/lcd/cycle` | `POST` | `hardware:write`| Advance front-panel LCD to next telemetry screen. |
| `/api/system/profile` | `POST` | `hardware:fans` | Apply unified acoustic profile (`auto`, `quiet`, `balanced`, `performance`). |
| `/api/ups` | `GET` | `system:read` | Query native NUT UPS status, battery charge %, and line voltage. |

---

### 7. Notifications, Hyper-Backup & Diagnostics

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/notifications/config` | `GET` | `notif:read` | Retrieve Apprise channel settings with masked credentials. |
| `/api/notifications/config` | `POST` | `notif:write` | Save notification channels (Discord, Telegram, SMTP, ntfy, Webhooks). |
| `/api/notifications/test` | `POST` | `notif:write` | Send a test notification alert across all configured channels. |
| `/api/notifications/test-channel` | `POST` | `notif:write` | Test an individual notification channel before saving. |
| `/api/backup/export` | `GET` | `backup:read` | Export verified, sanitized zip archive of suite configuration. |
| `/api/backup/restore` | `POST` | `backup:write`| Restore system configuration from uploaded backup zip. |
| `/api/backup/snapshots` | `GET` | `backup:read` | List local filesystem and cloud backup snapshots. |
| `/api/backup/snapshots/create` | `POST` | `backup:write`| Create an immediate filesystem snapshot. |
| `/api/system/diagnostics` | `GET` | `system:read` | Download 1-click sanitized system diagnostics bundle. |

---

### 8. Media Ingest & Filesystem Management

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/browse` | `GET` | `shares:read` | Explore folders within allowed storage pool roots (`?path=...`). |
| `/api/mkdir` | `POST` | `shares:write`| Create a destination directory within storage pool roots. |
| `/api/fs/upload` | `POST` | `shares:write`| Stream file upload with path containment validation. |
| `/api/fs/delete` | `POST` | `shares:write`| Delete a file or directory within storage pool roots. |
| `/api/fs/rename` | `POST` | `shares:write`| Rename a file or directory within storage pool roots. |
| `/api/media_slots` | `GET` | `hardware:read`| Query front SD and TF card slot insertion status and capacity. |
| `/api/media_slots/eject` | `POST` | `hardware:write`| Safely unmount filesystem and eject media card. |
| `/api/copy/confirm` | `POST` | `hardware:write`| Start card media ingestion job with optional SHA-256 verification. |
| `/api/copy/history` | `GET` | `hardware:read`| Query SQLite media ingest history and transfer speeds. |
| `/api/wallpapers` | `GET` | Yes | List uploaded custom desktop wallpapers. |
| `/api/wallpapers/upload` | `POST` | Yes | Upload and validate a new custom desktop wallpaper image. |
| `/api/wallpapers/active` | `POST` | Yes | Set active desktop wallpaper. |

---

## Response Formats & Error Handling

Standard responses are returned as `application/json`. Errors adhere to standard HTTP status codes:

```json
{
  "detail": "Descriptive error message"
}
```

* `400 Bad Request` — Invalid input, out-of-range fan curve value, or malformed JSON payload.
* `401 Unauthorized` — Missing or expired authentication token / cookie.
* `403 Forbidden` — Insufficient RBAC permission scope or path traversal attempt outside storage roots.
* `404 Not Found` — Disk, container, stack, file, or user not found.
* `409 Conflict` — Copy job, container update, or SMART self-test already in progress on target.
* `429 Too Many Requests` — Rate limit exceeded on authentication attempts or SSE subscriber saturation.
* `500 Internal Server Error` — Hardware communication failure or unhandled exception.

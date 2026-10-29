# ZettNAS Toolkit REST API Reference

All routes are mounted at `/api` (with the versioned alias `/api/v1`). The daemon exposes a comprehensive RESTful interface, Server-Sent Events (SSE) live streaming, and interactive WebSocket endpoints for hardware orchestration, storage topology, multi-user identity, Docker stacks, and remote cloud storage.

---

## Versions, errors and deprecation

- **Use `/api/v1/…`.** It is the documented API (`/openapi.json`, `/docs` when enabled) for API tokens, Home Assistant and MCP clients. The same routes are also served under the bare `/api/…` for the web UI; that prefix is not documented. Requests with an API token to the bare `/api/…` get `Deprecation: true`, `Sunset: Wed, 30 Jun 2027` and a `Link` to the `/api/v1` route; after that date token clients must use `/api/v1`.
- **Errors** always have the shape `{"error": "<slug>", "detail": "<message>", "code": <status>}`; validation errors add `errors: [{field, message}]`. Branch on `error`, show `detail`.
- **500 errors** never carry internal error text. They add a `reference`; the full error is in the server log under that reference (include it when reporting a problem). A few failures that are meant for you, such as why a VM didn't start, keep their message and have their own `error` slug (e.g. `vm_start_failed`).

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
| `/api/auth/roles` | `GET` | `users:read` | List system RBAC roles (`superadmin`, `storage_admin`, `app_operator`, `shareUser`, `Auditor`). |
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
| `/api/health` | `GET` | Public | Health probe: `checks` for the stats collector, user database and data folder; HTTP 503 when one has failed, 200 while starting or healthy. |

---

### 3. Storage & Platform Abstraction Layer (PAL)

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/storage/pools` | `GET` | `storage:read` | Unified storage pools across Btrfs RAID, Unraid array, and ZFS datasets. |
| `/api/storage/disks` | `GET` | `storage:read` | Physical disk inventory (SATA, NVMe, SAS, USB) with standby states and SMART health. |
| `/api/storage/bay-slots` | `GET` | `storage:read` | Which drive sits in which bay, for the drive bays picture. |
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
| `/api/docker/catalog` | `GET` | `containers:read` | Browse the catalog of 78 tested one-click apps, plus any template sources you add. |
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

### 7. Notifications, Backups & Diagnostics

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
| `/api/system/diagnostics` | `GET` | `system:read` | Download 1-click sanitized system diagnostics bundle archive. |
| `/api/system/diagnostics-bundle` | `POST` | `system:read` | Generate and stream sanitized diagnostics bundle zip with client telemetry overlay. |
| `/api/system/diagnostics-summary` | `GET` | `system:read` | Executive health status rollup, metric grids, and sanitized support markdown preview. |
| `/api/system/diagnostics/summary` | `GET` | `system:read` | Legacy alias for executive health status summary. |

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

### 9. Virtual Machines & Hypervisor

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/vms` | `GET` | `vms:read` | Inventory all virtual machines, runtime states, vCPU, RAM, and assigned IPs. |
| `/api/vms` | `POST` | `vms:manage` | Create a new virtual machine with disk image, ISO, UEFI/OVMF, vTPM, and allocations. |
| `/api/vms/{id}` | `PUT` | `vms:manage` | Update VM resources, UEFI/OVMF firmware, vTPM, video adapter, and USB passthrough. |
| `/api/vms/{id}/action` | `POST` | `vms:manage` | VM lifecycle control actions: `start`, `stop`, `pause`, `resume`, `force-stop`, `restart`. |
| `/api/vms/{id}` | `DELETE` | `vms:manage` | Delete a virtual machine and optionally remove associated virtual disk files. |
| `/api/vms/{id}/console` | `GET` | `vms:read` | Retrieve WebSocket VNC connection URL and credentials for Web Console. |
| `/api/vms/{id}/serial-ws` | `WS` | `vms:read` | Interactive bidirectional serial TTY terminal WebSocket stream. |
| `/api/vms/usb-devices` | `GET` | `vms:read` | Discover host physical USB devices available for direct guest passthrough. |
| `/api/vms/budget` | `GET` | `vms:read` | Dynamic elastic budget calculation (host reserve, safe RAM/vCPU ceilings). |
| `/api/vms/isos` | `GET` | `vms:read` | List local ISO images available in `/mnt/user/isos`. |
| `/api/vms/isos` | `POST` | `vms:manage` | Multipart streaming upload for custom ISO installation images. |
| `/api/vms/isos/catalog` | `GET` | `vms:read` | Browse curated official ISO catalog (Ubuntu, Debian, Alpine, Fedora, Windows). |
| `/api/vms/isos/download` | `POST` | `vms:manage` | Trigger background download of verified official distribution ISO image. |

---

### 10. Network, Virtual Switch & Mesh

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/network/combined-lan` | `GET` | `system:read` | Aggregate real-time throughput metrics across all physical NICs (`eth0`, `eth1`, `bond0`). |
| `/api/network/interfaces` | `GET` | `system:read` | Inventory physical and virtual network interfaces, link states, MTU, and IPs. |
| `/api/network/tailscale/status` | `GET` | `system:read` | Inspect Tailscale node status, peers, mesh IP, and exit node state. |
| `/api/network/tailscale/login` | `POST` | `system:admin` | Initiate 1-click Tailscale login flow with interactive auth URL and QR pairing. |
| `/api/network/wireguard/config` | `GET` | `system:read` | Generate mobile WireGuard client profile and scannable QR code. |
| `/api/network/vlans` | `GET` | `system:read` | List configured 802.1Q VLAN virtual interfaces. |
| `/api/network/vlans` | `POST` | `system:admin` | Create or update 802.1Q VLAN interface with canary rollback guard. |
| `/api/network/bonds` | `GET` | `system:read` | List bonded interfaces and LACP link aggregation groups. |
| `/api/network/bonds` | `POST` | `system:admin` | Configure network bonding (802.3ad LACP, active-backup, balance-xor). |

---

### 11. Enterprise Standards: Redfish & SNMP

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/redfish/v1/` | `GET` | Public | DMTF Redfish service root listing system and chassis endpoints. |
| `/redfish/v1/Chassis/1/Thermal` | `GET` | Public | Standard Redfish thermal endpoint with temperature sensors and fan tachometers. |
| `/redfish/v1/Systems/1` | `GET` | Public | Standard Redfish computer system model, CPU, memory, and power state. |
| `/redfish/v1/Storage/1` | `GET` | Public | Standard Redfish storage subsystem and drive telemetry. |
| `/api/snmp/status` | `GET` | `system:read` | Query SNMP v2c/v3 telemetry daemon state and active traps. |
| `/api/snmp/config` | `POST` | `system:admin` | Update SNMP community strings, user credentials, and trap receivers. |

---

### 12. UPS & Power Integrity Cockpit

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/ups` | `GET` | `system:read` | Query UPS status, battery %, load, runtime, and voltage (direct USB HID `/dev/hidraw*`, NUT, or APCUPSD). |
| `/api/system/ups/config` | `GET` | `system:read` | Retrieve persistent UPS configuration and tier recovery status from SQLite `history.db`. |
| `/api/system/ups/config` | `POST` | `system:admin`| Persist UPS connection settings across reboots with auto-discovery fallback on error. |
| `/api/system/ups/discover` | `GET` | `system:admin`| Auto-probe local USB ports and network gateway for available UPS daemons. |
| `/api/system/ups/mode` | `GET` | `system:read` | Query detected UPS mode, driver daemon type, and connection endpoint. |
| `/api/system/ups/mode` | `POST` | `system:admin`| Configure manual or auto UPS connection parameters (`nut_host`, `nut_port`, `nut_name`). |
| `/api/system/ups/policy` | `POST` | `system:admin`| Save safe shutdown policies: battery threshold % (5%–50%), runtime remaining minutes (2–30 min), and immediate shutdown toggle. |
| `/api/system/ups/drill` | `POST` | `system:admin`| Trigger interactive UPS drill: `self_test` (battery self-test) or `simulate_outage` (dry-run outage alert logging). |

---

### 13. System Updates & Self-Updater

| Endpoint | Method | Auth / Scope | Description |
| :--- | :---: | :---: | :--- |
| `/api/system/updates` | `GET` | `system:read` | Query available releases across `stable` (releases after a 7-day beta), `beta` (new releases) and `edge` (GitHub `main` branch commits) channels. |
| `/api/system/updates/apply` | `POST` | `system:manage` | Pull target Docker image and trigger seamless container recreation via Docker socket with health polling. |
| `/api/system/about` | `GET` | Public | System identity information including `version`, `commit_sha`, `commit_short`, `branch`, `channel`, and `build_timestamp`. |

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

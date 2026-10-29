# ZettNAS Toolkit REST API Reference

All routes are mounted at `/api` (with the versioned alias `/api/v1`). The daemon exposes a comprehensive RESTful interface, Server-Sent Events (SSE) live streaming, and interactive WebSocket endpoints for hardware orchestration, storage topology, multi-user identity, Docker stacks, and remote cloud storage.

---

## Versions, errors and deprecation

- **Use `/api/v1/…`.** It is the documented API (`/openapi.json`, `/docs` when enabled) for API tokens, Home Assistant and MCP clients. The same routes are also served under the bare `/api/…` for the web UI; that prefix is not documented. Requests with an API token to the bare `/api/…` get `Deprecation: true`, `Sunset: Wed, 30 Jun 2027` and a `Link` to the `/api/v1` route; after that date token clients must use `/api/v1`.
- **Errors** always have the shape `{"error": "<slug>", "detail": "<message>", "code": <status>}`; validation errors add `errors: [{field, message}]`. Branch on `error`, show `detail`.
- **500 errors** never carry internal error text. They add a `reference`; the full error is in the server log under that reference (include it when reporting a problem). A few failures that are meant for you, such as why a VM didn't start, keep their message and have their own `error` slug (e.g. `vm_start_failed`).

## Authentication & Authorization

Every operation that is not marked `public` needs one of these (they are the `bearerAuth` and
`cookieAuth` security schemes in `/openapi.json`):

1. **`Authorization: Bearer <token>`** — an API token (`zat_…`, made under Settings › API tokens,
   limited to the scopes you give it) or the session token that `POST /api/v1/auth/login` returns.
2. **The `zettnas_session` cookie** — the HttpOnly cookie the web UI gets at sign-in. Requests
   with the cookie that change something must come from the same site (otherwise 403
   `csrf_blocked`).

Long-lived tokens are never read from a URL, because URLs end up in logs and browser history. For
a live stream (SSE) or WebSocket a browser opens by URL, get a single-use, 60-second ticket from `POST
/api/v1/auth/ticket` and pass it as `?ticket=zst_…`.

Each operation lists the scopes it needs under **Access** below (and as `x-required-scopes` in
`/openapi.json`); having any one of them is enough. A token with too few scopes gets 403.

---

## Endpoint Catalog

Generated from `/openapi.json`, so it lists every documented operation with the access it really
needs. The same document, at `/openapi.json` (and `/docs` when enabled), has each operation's
request and response schemas.

<!-- BEGIN generated endpoints: python scripts/api_reference.py --update -->

621 operations. **Access** is what the session or token needs: `public` needs nothing, `signed in` any valid session or token, otherwise one of the listed scopes. ⏱ marks operations that can answer 429.

### AI Conversation History

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `DELETE` | `/api/v1/ai/conversations` | any of `shares:read`, `storage:read`, `system:read` | Deletes all conversations belonging to the authenticated user |
| `GET` | `/api/v1/ai/conversations` | any of `shares:read`, `storage:read`, `system:read` | Lists conversations for the authenticated user |
| `POST` | `/api/v1/ai/conversations` | any of `shares:read`, `storage:read`, `system:read` | Creates a new conversation thread |
| `DELETE` | `/api/v1/ai/conversations/{conv_id}` | any of `shares:read`, `storage:read`, `system:read` | Deletes a conversation thread and its message stream permanently |
| `GET` | `/api/v1/ai/conversations/{conv_id}` | any of `shares:read`, `storage:read`, `system:read` | Retrieves full conversation with ordered message stream |
| `PATCH` | `/api/v1/ai/conversations/{conv_id}` | any of `shares:read`, `storage:read`, `system:read` | Updates editable metadata on a conversation thread (title, pin, archive) |
| `POST` | `/api/v1/ai/conversations/{conv_id}/messages` | any of `shares:read`, `storage:read`, `system:read` | Appends an explicit message turn to a conversation thread |
| `DELETE` | `/api/v1/media/conversations` | any of `shares:read`, `storage:read`, `system:read` | Deletes all conversations belonging to the authenticated user |
| `GET` | `/api/v1/media/conversations` | any of `shares:read`, `storage:read`, `system:read` | Lists conversations for the authenticated user |
| `POST` | `/api/v1/media/conversations` | any of `shares:read`, `storage:read`, `system:read` | Creates a new conversation thread |
| `DELETE` | `/api/v1/media/conversations/{conv_id}` | any of `shares:read`, `storage:read`, `system:read` | Deletes a conversation thread and its message stream permanently |
| `GET` | `/api/v1/media/conversations/{conv_id}` | any of `shares:read`, `storage:read`, `system:read` | Retrieves full conversation with ordered message stream |
| `PATCH` | `/api/v1/media/conversations/{conv_id}` | any of `shares:read`, `storage:read`, `system:read` | Updates editable metadata on a conversation thread (title, pin, archive) |

### AI for apps

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/ai/apps` | `system:config` | The apps that can be set up, and the keys made for them (masked) |
| `POST` | `/api/v1/ai/apps/keys` | `system:config` | A key for one app, and that app's settings filled in |
| `DELETE` | `/api/v1/ai/apps/keys/{token_id}` | `system:config` | Delete App Key |
| `POST` | `/api/v1/ai/openai/chat/completions` | `ai:apps` | Openai Chat |
| `POST` | `/api/v1/ai/openai/embeddings` | `ai:apps` | Openai Embeddings |
| `GET` | `/api/v1/ai/openai/models` | `ai:apps` | Openai Models |

### AI pack

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/ai/pack` | `system:config` | The box, the recommended preset, and the pack's state (absent, warming, ready, stopped) |
| `POST` | `/api/v1/ai/pack/install` | `containers:manage` | Pack Install |
| `POST` | `/api/v1/ai/pack/use` | `system:config` | Chat through the pack; the answer says how to move the embeddings |

### ARGB Lighting

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/led` | any of `hardware:read`, `system:view` | Get Led |
| `POST` | `/api/v1/led` | `hardware:rgb` | Post Led |

### Authentication & Security

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/auth/audit` | `audit:read` | Get Security Audit Logs |
| `POST` | `/api/v1/auth/login` | public ⏱ | Login |
| `POST` | `/api/v1/auth/logout` | signed in | Logout |
| `GET` | `/api/v1/auth/me` | signed in | Get Current User Profile |
| `PUT` | `/api/v1/auth/me/preferences` | signed in | The signed-in person's own settings (B11, UX-23); only the keys sent change |
| `POST` | `/api/v1/auth/mfa/challenge` | public ⏱ | Mfa Challenge |
| `POST` | `/api/v1/auth/mfa/disable` | signed in ⏱ | Disable Mfa |
| `POST` | `/api/v1/auth/mfa/enable` | signed in ⏱ | Enable Mfa |
| `POST` | `/api/v1/auth/mfa/setup` | signed in | Setup Mfa |
| `GET` | `/api/v1/auth/mfa/status` | signed in | Get Mfa Status |
| `DELETE` | `/api/v1/auth/sessions` | signed in | Revoke All Other Sessions |
| `GET` | `/api/v1/auth/sessions` | signed in | Get My Active Sessions |
| `DELETE` | `/api/v1/auth/sessions/{session_id_hash}` | signed in | Revoke Specific Session |
| `POST` | `/api/v1/auth/ticket` | signed in | Generate a single-use, 60-second ticket for SSE or WebSocket connections |
| `GET` | `/api/v1/auth/users-list` | public | User tiles for the login screen, only when the admin turned them on (SEC-19) |
| `POST` | `/api/v1/confirmations` | signed in | Issues a single-use token for one destructive action (see backend/confirmations.py) |
| `GET` | `/api/v1/security` | any of `system:view`, `users:read`, `system:config` | Get Security |
| `POST` | `/api/v1/security` | any of `users:manage`, `system:config` ⏱ | Post Security |
| `GET` | `/api/v1/security/advisor` | any of `system:view`, `users:read` | Runs automated zero-wake security checks across identity, passwords, and sessions |
| `GET` | `/api/v1/users` | `users:read` | Get Users List |
| `POST` | `/api/v1/users` | `users:write` | Create New User |
| `POST` | `/api/v1/users/admin/disable` | any of `users:manage`, `users:write` | 1-click action to disable the default admin account |
| `DELETE` | `/api/v1/users/{user_id}` | `users:delete` | Delete User Endpoint |
| `GET` | `/api/v1/users/{user_id}` | signed in | Get User Detail |
| `PUT` | `/api/v1/users/{user_id}` | signed in | Update User Endpoint |
| `POST` | `/api/v1/users/{user_id}/password` | signed in ⏱ | Change User Password |

### Backup

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/backup/apps` | any of `backup:read`, `backup:manage`, `containers:read` | Lists saved app data & configuration archives, optionally filtered by app name |
| `DELETE` | `/api/v1/backup/apps/{backup_id}` | any of `containers:manage`, `backup:write`, `backup:manage` | Deletes an application backup archive from disk and registry |
| `GET` | `/api/v1/backup/apps/{backup_id}/download` | any of `backup:read`, `backup:manage` | Downloads an application backup archive (.tar.gz) |
| `POST` | `/api/v1/backup/apps/{backup_id}/restore` | any of `containers:manage`, `backup:write`, `backup:manage` | Restores application configuration and appdata from a backup archive |
| `GET` | `/api/v1/backup/history` | any of `backup:read`, `backup:manage`, `system:config` | Retrieves recent execution history for backup pipelines |
| `POST` | `/api/v1/backup/restore-snapshot` | any of `backup:write`, `backup:manage`, `system:config`, `storage:admin` | Restores or rolls back an atomic filesystem snapshot |
| `GET` | `/api/v1/backup/schedule` | any of `backup:read`, `backup:manage`, `system:config` | Lists all scheduled backup jobs |
| `POST` | `/api/v1/backup/schedule` | any of `backup:write`, `backup:manage`, `system:config` | Creates or updates a scheduled backup job |
| `DELETE` | `/api/v1/backup/schedule/{job_id}` | any of `backup:write`, `backup:manage`, `system:config` | Deletes a scheduled backup job |
| `POST` | `/api/v1/backup/schedule/{job_id}/migrate` | any of `backup:write`, `backup:manage`, `system:config` | Moves a copy job to an off-site (restic) backup: versioned and encrypted (REL-9) |
| `POST` | `/api/v1/backup/schedule/{job_id}/run` | any of `backup:write`, `backup:manage`, `system:config` | Starts a backup job in the background |
| `GET` | `/api/v1/backup/snapshots` | any of `backup:read`, `backup:manage`, `system:config`, `storage:read` | Lists filesystem snapshots for a storage pool |
| `POST` | `/api/v1/backup/snapshots` | any of `backup:write`, `backup:manage`, `system:config`, `storage:admin` | Creates an atomic filesystem snapshot on the storage platform |
| `DELETE` | `/api/v1/backup/snapshots/{pool_id}/{snapshot_name}` | any of `backup:write`, `backup:manage`, `system:config`, `storage:admin` | Deletes an atomic filesystem snapshot |
| `POST` | `/api/v1/docker/containers/{container_id}/backup` | any of `containers:manage`, `backup:write`, `backup:manage` | Takes an on-demand backup of an installed container app's data and synthesized compose config |
| `GET` | `/api/v1/system/backup` | `*` | Configuration backup as a plain zip (users, settings, shares, stacks, VM definitions) |
| `POST` | `/api/v1/system/backup` | `*` | Configuration backup, encrypted with the given passphrase (AES-256-GCM, scrypt) |
| `GET` | `/api/v1/system/client-preferences` | signed in | Returns persistent client UI preferences (themes, widgets, window layouts) from DATA_DIR |
| `POST` | `/api/v1/system/client-preferences` | `system:config` | Persists client UI preferences into DATA_DIR so they are preserved in backups and cross-device sync |
| `POST` | `/api/v1/system/restore` | `*` | Restores configuration from a zip archive |

### Calendar & Notes

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/calendar/events` | signed in | Returns the caller's notes/reminders combined with events from their synced feeds |
| `GET` | `/api/v1/calendar/export` | signed in | Exports the caller's notes and reminders as an RFC 5545 .ics calendar file |
| `GET` | `/api/v1/calendar/feeds` | signed in | Lists the caller's external calendar feeds and their sync status |
| `POST` | `/api/v1/calendar/feeds` | any of `system:config`, `shares:user_write` | Adds a new calendar provider feed (e.g |
| `DELETE` | `/api/v1/calendar/feeds/{feed_id}` | any of `system:config`, `shares:user_write` | Removes one of the caller's calendar feeds and cleans up its cached events |
| `POST` | `/api/v1/calendar/notes` | any of `system:config`, `shares:user_write` | Creates a new note, reminder, or task for a given date |
| `DELETE` | `/api/v1/calendar/notes/{note_id}` | any of `system:config`, `shares:user_write` | Deletes a user note or reminder |
| `PATCH` | `/api/v1/calendar/notes/{note_id}` | any of `system:config`, `shares:user_write` | Updates or toggles completed status of a note/reminder |
| `POST` | `/api/v1/calendar/sync` | any of `system:config`, `shares:user_write` | Syncs the caller's enabled calendar feeds and updates their cached events |

### Chassis Visualizer & Layout

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/chassis/bay_map` | any of `storage:admin`, `system:config` | Saves user-customized chassis profile, total bays, and drag-and-drop bay slot assignments |
| `GET` | `/api/v1/chassis/bridges` | any of `hardware:read`, `storage:read`, `system:view` | Returns detected hardware platform bridges (Zettlab, Aoostar, Ugreen, CWWK) |
| `GET` | `/api/v1/chassis/config` | any of `hardware:read`, `storage:read`, `system:view` | Returns dynamic chassis layout configuration, detected bays, populated disks, and motherboard M.2 NVMe slots |

### Docker App Catalog

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/docker/catalog` | any of `containers:read`, `containers:manage` | Get Docker Catalog |
| `GET` | `/api/v1/docker/catalog/logo` | any of `containers:read`, `containers:manage` | An app's logo, fetched once by ZettNAS so the browser doesn't ask a third party (SEC-38) |
| `POST` | `/api/v1/docker/catalog/sideload` | `containers:manage` | Sideloads an application from a URL (e.g |
| `GET` | `/api/v1/docker/catalog/sources` | any of `containers:read`, `containers:manage` | Get Docker Catalog Sources |
| `POST` | `/api/v1/docker/catalog/sources` | `containers:manage` | Post Docker Catalog Sources |
| `DELETE` | `/api/v1/docker/catalog/sources/{source_id}` | `containers:manage` | Delete Docker Catalog Source |
| `POST` | `/api/v1/docker/catalog/sources/{source_id}/sync` | `containers:manage` | Post Docker Catalog Source Sync |
| `POST` | `/api/v1/docker/catalog/sources/{source_id}/toggle` | `containers:manage` | Post Docker Catalog Source Toggle |
| `POST` | `/api/v1/docker/catalog/{app_id}/compose` | `containers:manage` | Post Docker Catalog Compose |
| `POST` | `/api/v1/docker/catalog/{app_id}/deploy` | `containers:manage` | Post Docker Catalog Deploy |
| `GET` | `/api/v1/docker/catalog/{app_id}/resolve` | any of `containers:read`, `containers:manage` | Get Docker Catalog Resolve |
| `GET` | `/api/v1/docker/check_container_name` | any of `containers:read`, `containers:manage` | Get Check Container Name |

### Docker Containers & Stacks

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/docker/check_port` | any of `containers:read`, `containers:manage`, `system:view` | Get Check Port |
| `GET` | `/api/v1/docker/containers` | any of `containers:read`, `containers:manage`, `system:view` | Get Docker Containers |
| `POST` | `/api/v1/docker/containers/bulk-action` | any of `containers:write`, `containers:manage` | Post Docker Bulk Action |
| `DELETE` | `/api/v1/docker/containers/{container_id}` | `containers:manage` | Delete Docker Container |
| `POST` | `/api/v1/docker/containers/{container_id}/action` | any of `containers:write`, `containers:manage` | Post Docker Container Action |
| `GET` | `/api/v1/docker/containers/{container_id}/compose` | any of `containers:read`, `containers:manage`, `system:view` | Get Docker Container Compose |
| `GET` | `/api/v1/docker/containers/{container_id}/details` | any of `containers:read`, `containers:manage`, `system:view` | Get Docker Container Details |
| `POST` | `/api/v1/docker/containers/{container_id}/exec` | `containers:exec` | Post Docker Container Exec |
| `GET` | `/api/v1/docker/containers/{container_id}/logs` | any of `containers:read`, `containers:manage` | Get Docker Container Logs |
| `GET` | `/api/v1/docker/containers/{container_id}/logs/stream` | any of `containers:read`, `containers:manage` | Streams multiplexed stdout/stderr container logs via Server-Sent Events (SSE) |
| `POST` | `/api/v1/docker/containers/{container_id}/ports` | `containers:manage` | Post Docker Container Ports |
| `POST` | `/api/v1/docker/containers/{container_id}/recreate` | `containers:manage` | Post Docker Container Recreate |
| `POST` | `/api/v1/docker/containers/{container_id}/resources` | `containers:manage` | Post Docker Container Resources |
| `POST` | `/api/v1/docker/containers/{container_id}/update-image` | `containers:manage` | Post Docker Container Update Image |
| `GET` | `/api/v1/docker/networks/topology` | any of `containers:read`, `containers:manage`, `system:view` | Docker networks with their attached containers and IPs, for the Network Map |
| `GET` | `/api/v1/docker/stacks` | any of `containers:read`, `containers:manage` | Get Docker Stacks |
| `GET` | `/api/v1/docker/stacks/{stack_name}` | any of `containers:read`, `containers:manage` | Get Docker Stack Details |
| `POST` | `/api/v1/docker/stacks/{stack_name}/action` | any of `containers:write`, `containers:manage` | Post Docker Stack Action |
| `POST` | `/api/v1/docker/stacks/{stack_name}/save` | `containers:manage` | Post Docker Stack Save |
| `GET` | `/api/v1/docker/system/df` | any of `containers:read`, `containers:manage`, `system:view` | Get System Df |
| `POST` | `/api/v1/docker/system/prune` | `containers:manage` | Post System Prune |
| `POST` | `/api/v1/docker/system/prune/jobs` | `containers:manage` | Starts the cleanup in the background; poll the job for progress |
| `GET` | `/api/v1/docker/system/prune/jobs/current` | `containers:manage` | Get Current Prune Job |
| `GET` | `/api/v1/docker/system/prune/jobs/{job_id}` | `containers:manage` | Get Prune Job Status |
| `POST` | `/api/v1/docker/system/prune/jobs/{job_id}/cancel` | `containers:manage` | Cancel Prune Job Route |
| `POST` | `/api/v1/docker/updates/apply-all` | `containers:manage` | Post Docker Updates Apply All |
| `POST` | `/api/v1/docker/updates/check` | any of `containers:read`, `system:view` | Post Docker Updates Check |
| `GET` | `/api/v1/docker/updates/policies` | any of `containers:read`, `system:view` | Get Docker Update Policies |
| `POST` | `/api/v1/docker/updates/policies` | `containers:manage` | Post Docker Update Policies |
| `GET` | `/api/v1/docker/updates/status` | any of `containers:read`, `system:view` | Get Docker Updates Status |

### Drive Health

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/drives/health` | any of `storage:read`, `system:view` | Every drive with its verdict, reason and what to do; worst first |
| `GET` | `/api/v1/drives/history` | any of `storage:read`, `system:view` | A drive's temperature and error counters over time, and its age and wear outlook, from the stored readings: a sleeping drive is not touch… |

### File System & Shares

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/browse` | signed in | A folder's entries |
| `GET` | `/api/v1/fs/activity` | `audit:read` | Who deleted, moved, renamed, restored or uploaded what, newest first (90 days are kept) |
| `POST` | `/api/v1/fs/archive/create` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Archive Create |
| `POST` | `/api/v1/fs/archive/extract` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` ⏱ | Fs Archive Extract |
| `POST` | `/api/v1/fs/checksum` | any of `shares:read`, `storage:read`, `system:view` | Fs Checksum |
| `POST` | `/api/v1/fs/conflict-check` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Conflict Check |
| `POST` | `/api/v1/fs/delete` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Delete |
| `GET` | `/api/v1/fs/download` | signed in | Fs Download |
| `GET` | `/api/v1/fs/download-zip` | signed in ⏱ | Streams a zip archive containing multiple selected files or folders without staging on disk |
| `DELETE` | `/api/v1/fs/favorites` | any of `shares:read`, `storage:read`, `system:view` | Fs Remove Favorite |
| `GET` | `/api/v1/fs/favorites` | any of `shares:read`, `storage:read`, `system:view` | The signed-in user's favorite folders; ones that are gone or no longer allowed are marked |
| `POST` | `/api/v1/fs/favorites` | any of `shares:read`, `storage:read`, `system:view` | Fs Add Favorite |
| `POST` | `/api/v1/fs/folder-size` | any of `shares:read`, `storage:read`, `system:view` | Fs Folder Size |
| `GET` | `/api/v1/fs/inbox` | any of `shares:user_write`, `storage:write`, `storage:admin` | Fs Inbox |
| `POST` | `/api/v1/fs/inbox` | any of `shares:user_write`, `storage:write`, `storage:admin` | Saves one shared file into the Inbox under a name that doesn't overwrite anything (M1) |
| `GET` | `/api/v1/fs/media/info` | any of `shares:read`, `storage:read`, `system:view` | Duration, resolution, codecs, frame rate and rotation of a video or audio file |
| `GET` | `/api/v1/fs/permissions` | any of `shares:read`, `storage:read`, `system:view` | Fs Get Permissions |
| `PUT` | `/api/v1/fs/permissions` | any of `shares:manage`, `storage:admin` | Fs Update Permissions |
| `GET` | `/api/v1/fs/preview` | any of `shares:read`, `storage:read`, `system:view` | Universal Quick Look preview generator |
| `GET` | `/api/v1/fs/preview/image` | any of `shares:read`, `storage:read`, `system:view` | Thumbnails and screen-sized previews as WebP: photos (including Apple HEIC/HEIF) and video frames, cached on disk (backend/services/thumb… |
| `POST` | `/api/v1/fs/rename` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Rename |
| `GET` | `/api/v1/fs/roots` | any of `shares:read`, `storage:read`, `system:view` | Authoritative platform-aware storage hierarchy for File Explorer |
| `GET` | `/api/v1/fs/search` | any of `shares:read`, `storage:read`, `system:view` | Streaming bounded filesystem search using os.scandir with path containment |
| `GET` | `/api/v1/fs/share-links` | any of `files:read`, `storage:read`, `storage:admin` | Lists active public share links created by the current user or all if admin |
| `POST` | `/api/v1/fs/share-links` | any of `files:write`, `shares:user_write`, `storage:admin` ⏱ | Generates a secure, temporary or password-protected public share link for a file or folder |
| `DELETE` | `/api/v1/fs/share-links/{token}` | any of `files:write`, `storage:admin` | Revokes and deletes an existing share link |
| `GET` | `/api/v1/fs/shared/{token}` | public ⏱ | Public access endpoint for shared files and folders (no session needed) |
| `POST` | `/api/v1/fs/shared/{token}` | public ⏱ | Same as the GET route, with the password in a form or JSON body instead of the URL (SEC-21) |
| `GET` | `/api/v1/fs/stream` | signed in | HTTP 206 Partial Content Range streaming for video and audio playback |
| `GET` | `/api/v1/fs/stream/compat` | any of `shares:read`, `storage:read`, `system:view` | The video converted to H.264/AAC in fragmented MP4 while it plays, from `start` seconds |
| `POST` | `/api/v1/fs/transfer` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Transfer |
| `POST` | `/api/v1/fs/transfer/async` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Transfer Async |
| `GET` | `/api/v1/fs/transfers` | any of `shares:read`, `storage:read`, `system:view` | Fs List Transfers |
| `DELETE` | `/api/v1/fs/transfers/completed` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Clear Completed Transfers |
| `GET` | `/api/v1/fs/transfers/stream` | signed in | Fs Transfers Stream |
| `POST` | `/api/v1/fs/transfers/{task_id}/cancel` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Cancel Transfer |
| `POST` | `/api/v1/fs/transfers/{task_id}/dismiss` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Forgets a transfer a restart interrupted, after clearing its unfinished files |
| `POST` | `/api/v1/fs/transfers/{task_id}/pause` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Pause Transfer |
| `POST` | `/api/v1/fs/transfers/{task_id}/resume` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Resume Transfer |
| `POST` | `/api/v1/fs/transfers/{task_id}/undo` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Undoes a transfer a restart interrupted: copies to the Recycle Bin, moved items back |
| `GET` | `/api/v1/fs/trash` | any of `shares:read`, `storage:read`, `system:view` | What the Recycle Bins hold, newest first; each person sees what they may open |
| `DELETE` | `/api/v1/fs/trash/empty` | any of `shares:manage`, `storage:admin` | Permanently deletes everything in every Recycle Bin |
| `POST` | `/api/v1/fs/trash/restore` | any of `shares:user_write`, `storage:write`, `storage:admin` | Restores an item where it was (or into target_path), never over an existing one |
| `POST` | `/api/v1/fs/upload` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Upload |
| `POST` | `/api/v1/fs/upload/chunk` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Upload Chunk |
| `POST` | `/api/v1/fs/upload/complete` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Upload Complete |
| `POST` | `/api/v1/fs/upload/init` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Fs Upload Init |
| `POST` | `/api/v1/mkdir` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Mkdir |
| `GET` | `/api/v1/share-links` | any of `files:read`, `storage:read`, `storage:admin` | Lists active public share links created by the current user or all if admin |
| `POST` | `/api/v1/share-links` | any of `files:write`, `shares:user_write`, `storage:admin` ⏱ | Generates a secure, temporary or password-protected public share link for a file or folder |
| `DELETE` | `/api/v1/share-links/{token}` | any of `files:write`, `storage:admin` | Revokes and deletes an existing share link |
| `GET` | `/api/v1/shared/{token}` | public ⏱ | Public access endpoint for shared files and folders (no session needed) |
| `POST` | `/api/v1/shared/{token}` | public ⏱ | Same as the GET route, with the password in a form or JSON body instead of the URL (SEC-21) |

### Files

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/fs/versions` | any of `shares:read`, `shares:user_write`, `storage:read`, `storage:write`, `storage:admin` | Get Versions |
| `GET` | `/api/v1/fs/versions/download` | any of `shares:read`, `shares:user_write`, `storage:read`, `storage:write`, `storage:admin` | Download Version |
| `POST` | `/api/v1/fs/versions/restore` | any of `shares:manage`, `shares:user_write`, `storage:write`, `storage:admin` | Restore Version |

### Immich

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/immich` | signed in | Get Status |
| `DELETE` | `/api/v1/immich/me` | signed in | Disconnect Me |
| `PUT` | `/api/v1/immich/me` | signed in | Connect Me |
| `PUT` | `/api/v1/immich/phone` | signed in | Marks this person's phone as backing up to Immich (Getting started, B8) |
| `GET` | `/api/v1/immich/thumbnail/{asset_id}` | any of `shares:read`, `system:read` | Get Thumbnail |
| `PUT` | `/api/v1/immich/url` | any of `system:config`, `ai:manage` | Put Url |

### Invites

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/invite/{token}` | public ⏱ | Public: whether an invite link is still valid, and for which role |
| `POST` | `/api/v1/invite/{token}/accept` | public ⏱ | Public: creates the account an invite allows, and the person's private folder |
| `GET` | `/api/v1/invites` | any of `users:read`, `users:write` | Get Invites |
| `POST` | `/api/v1/invites` | `users:write` | New Invite |
| `DELETE` | `/api/v1/invites/{invite_id}` | `users:write` | Revoke |

### Jobs

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/jobs` | signed in | Your running jobs and recent history; administrators see everyone's and system jobs |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | signed in | Cancel Job |

### LDAP

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/auth/ldap/settings` | any of `users:write`, `system:config` | Ldap Settings |
| `PUT` | `/api/v1/auth/ldap/settings` | any of `users:write`, `system:config` | Ldap Save Settings |
| `POST` | `/api/v1/auth/ldap/test` | any of `users:write`, `system:config` | Ldap Test |

### MCP

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/mcp` | signed in | Mcp No Stream |
| `POST` | `/api/v1/mcp` | signed in | Mcp Endpoint |

### Metrics

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/metrics` | `system:view` | Prometheus exposition format for ZettNAS telemetry |
| `GET` | `/api/v1/metrics/network-topology` | `system:view` | Network topology metrics and switch status |
| `GET` | `/api/v1/metrics/requests` | `system:view` | The busiest API routes: requests, errors and latency (ARCH-10) |

### Network & Switching

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/network/bond/{bond_name}` | any of `system:view`, `system:config` | Retrieve configuration, operational mode, active slave, and candidates for a bonding group |
| `POST` | `/api/v1/network/bond/{bond_name}` | `system:config` | Update bonding group mode (802.3ad / active-backup / balance-alb), slave member interfaces, and miimon |
| `GET` | `/api/v1/network/bridge/{br_name}` | any of `system:view`, `system:config` | Retrieve configuration, STP state, forward delay, and members for a virtual bridge |
| `POST` | `/api/v1/network/bridge/{br_name}` | `system:config` | Update virtual bridge parameters (STP enable/disable, forward delay, member interfaces) |
| `POST` | `/api/v1/network/docker/create` | `containers:manage` | Create a new Docker bridge or custom network |
| `DELETE` | `/api/v1/network/docker/{net_id_or_name}` | `containers:manage` | Delete a custom Docker network |
| `POST` | `/api/v1/network/host/apply` | `system:config` | Arm 60-second Canary watchdog, snapshot configuration, and stage/apply new host IP settings |
| `GET` | `/api/v1/network/host/config` | any of `system:view`, `system:config` | Retrieve host IP assignment mode, primary interface, netmask, gateway, and DNS servers |
| `POST` | `/api/v1/network/host/confirm` | `system:config` | Confirm and seal host network configuration, cancelling the 60s rollback watchdog |
| `POST` | `/api/v1/network/host/revert` | `system:config` | Manually abort Canary test and immediately restore previous host network configuration |
| `GET` | `/api/v1/network/mesh-vpn` | `system:view` | Retrieves Zero-Trust Mesh VPN telemetry and status for Tailscale and WireGuard |
| `POST` | `/api/v1/network/mesh-vpn/tailscale/deploy` | `system:config` | 1-Click turnkey provisioning of the official Tailscale Docker container |
| `POST` | `/api/v1/network/mesh-vpn/tailscale/down` | `system:config` | Disconnects host from the Zero-Trust Tailscale mesh network |
| `POST` | `/api/v1/network/mesh-vpn/tailscale/ping` | `system:view` | Performs real-time latency ping against a Tailscale mesh peer |
| `POST` | `/api/v1/network/mesh-vpn/tailscale/reauth` | `system:config` | Forces node re-authentication before node key expiration |
| `POST` | `/api/v1/network/mesh-vpn/tailscale/set-exit-node` | `system:config` | Enables or disables advertising this NAS as a Tailscale Exit Node |
| `POST` | `/api/v1/network/mesh-vpn/tailscale/set-routes` | `system:config` | Advertises or withdraws subnet routes on the Tailscale network |
| `POST` | `/api/v1/network/mesh-vpn/tailscale/set-serve` | `system:config` | Configures Tailscale Serve (HTTPS on Tailnet) and optional Public Funnel |
| `POST` | `/api/v1/network/mesh-vpn/tailscale/set-ssh` | `system:config` | Enables or disables Tailscale SSH |
| `GET` | `/api/v1/network/mesh-vpn/tailscale/taildrop/files` | `storage:read` | Lists files received via Taildrop |
| `POST` | `/api/v1/network/mesh-vpn/tailscale/taildrop/receive` | `storage:write` | Receives and ingests incoming files from the Taildrop file inbox |
| `POST` | `/api/v1/network/mesh-vpn/tailscale/up` | `system:config` | Connects host to the Zero-Trust Tailscale mesh network |
| `POST` | `/api/v1/network/mesh-vpn/wireguard/client-config` | `system:config` | Generates a WireGuard client configuration file with keypair |
| `GET` | `/api/v1/network/mesh-vpn/wireguard/subnet-routing` | `system:config` | Gets current kernel IP packet forwarding state |
| `POST` | `/api/v1/network/mesh-vpn/wireguard/subnet-routing` | `system:config` | Enables or disables kernel IP forwarding and NAT for WireGuard subnet routing |
| `GET` | `/api/v1/network/port/{iface_name}` | any of `system:view`, `system:config` | Retrieve configuration, live capabilities, and alias for a specific interface |
| `POST` | `/api/v1/network/port/{iface_name}` | `system:config` | Update interface configuration (alias, MTU, WOL, negotiation speed) |
| `GET` | `/api/v1/network/ports/listening` | any of `system:config`, `system:read` | Returns active listening TCP and UDP ports and mapped container services |
| `GET` | `/api/v1/network/remote-access` | `system:view` | Use from anywhere (COMP-01): tailnet state, sign-in link, and the addresses to open |
| `POST` | `/api/v1/network/remote-access/connect` | `system:config` | Joins Tailscale, or a Headscale server; answers with the sign-in link when one is needed |
| `POST` | `/api/v1/network/remote-access/disconnect` | `system:config` | Post Remote Access Disconnect |
| `POST` | `/api/v1/network/remote-access/publish` | `system:config` | HTTPS addresses in the tailnet for ZettNAS and Immich |
| `GET` | `/api/v1/network/topology` | any of `system:view`, `system:config` | Retrieve full host network topology, physical NICs, bridges, bonds, and Docker networks |
| `POST` | `/api/v1/network/vlan/create` | `system:config` | Create a new 802.1Q VLAN tagged sub-interface (e.g |
| `DELETE` | `/api/v1/network/vlan/{vlan_iface}` | `system:config` | Delete an existing 802.1Q VLAN tagged sub-interface |
| `GET` | `/api/v1/network/vlans` | any of `system:view`, `system:config` | list all active and configured 802.1Q VLAN sub-interfaces |

### Notifications & Alerts

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/notifications/config` | any of `system:view`, `system:config` | Retrieve current notification settings with sensitive credentials masked |
| `POST` | `/api/v1/notifications/config` | `system:config` | Save notification settings, preserving existing secrets when masked |
| `GET` | `/api/v1/notifications/frigate` | any of `system:view`, `system:config` | Frigate's detections as camera alerts (COMP-11): on or off, which objects and cameras |
| `PUT` | `/api/v1/notifications/frigate` | `system:config` | Put Frigate Events |
| `POST` | `/api/v1/notifications/frigate/test` | `system:config` | Whether Frigate answers at the saved address, its version and its cameras |
| `GET` | `/api/v1/notifications/notifications/me` | signed in | This person's own alerts: where they go and which kinds (Batch 6) |
| `PUT` | `/api/v1/notifications/notifications/me` | signed in | Put My Alerts |
| `POST` | `/api/v1/notifications/test` | `system:config` | Dispatch an immediate test alert across all configured channels |
| `POST` | `/api/v1/notifications/test-channel` | `system:config` | Test a specific notification channel with latency telemetry and detailed diagnostic feedback |

### Offsite backup

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/offsite` | any of `backup:read`, `backup:manage`, `system:config` | Overview |
| `GET` | `/api/v1/offsite/destinations` | any of `backup:manage`, `system:config` | Where a new backup could go: USB disks, other NASes mounted here, cloud remotes (FEAT-01) |
| `GET` | `/api/v1/offsite/lock-presets` | any of `backup:read`, `backup:manage`, `system:config` | Cloud services that can lock a copy, with the steps to set a bucket up (FEAT-03) |
| `PUT` | `/api/v1/offsite/repos` | any of `backup:manage`, `system:config` | Put Repo |
| `DELETE` | `/api/v1/offsite/repos/{repo_id}` | any of `backup:manage`, `system:config` | Delete Repo |
| `POST` | `/api/v1/offsite/repos/{repo_id}/backup` | any of `backup:manage`, `system:config` | Starts the backup as a job (REL-16); its progress and result show in Jobs |
| `POST` | `/api/v1/offsite/repos/{repo_id}/check` | any of `backup:manage`, `system:config` | Run Check |
| `POST` | `/api/v1/offsite/repos/{repo_id}/init` | any of `backup:manage`, `system:config` | Init Repo |
| `GET` | `/api/v1/offsite/repos/{repo_id}/key` | any of `backup:manage`, `system:config` | The repository key: without it nobody, including you, can read the backup |
| `GET` | `/api/v1/offsite/repos/{repo_id}/kit` | any of `backup:manage`, `system:config` | The full recovery kit (REL-17): key, location, cloud settings and restore commands |
| `POST` | `/api/v1/offsite/repos/{repo_id}/kit-saved` | any of `backup:manage`, `system:config` | Kit Saved |
| `POST` | `/api/v1/offsite/repos/{repo_id}/lock-check` | any of `backup:manage`, `system:config` | Reads the bucket's Object Lock settings from the provider; nothing is written there |
| `GET` | `/api/v1/offsite/repos/{repo_id}/snapshots` | any of `backup:read`, `backup:manage`, `system:config` | List Versions |
| `GET` | `/api/v1/offsite/repos/{repo_id}/snapshots/{snapshot_id}/browse` | any of `backup:read`, `backup:manage`, `system:config` | Browse |
| `POST` | `/api/v1/offsite/repos/{repo_id}/snapshots/{snapshot_id}/restore` | any of `backup:manage`, `system:config` | Starts the restore as a job (REL-16); never over the live files |

### Push notifications

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/push/devices` | signed in | Devices |
| `POST` | `/api/v1/push/subscribe` | signed in | Subscribe |
| `POST` | `/api/v1/push/test` | any of `system:config`, `users:read`, `system:view` | Test Push |
| `POST` | `/api/v1/push/unsubscribe` | signed in | Unsubscribe |
| `GET` | `/api/v1/push/vapid-public-key` | signed in | Vapid Public Key |

### Redfish

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/redfish` | signed in | Redfish Service Root (/redfish/v1/) |
| `GET` | `/redfish/` | signed in | Redfish Service Root (/redfish/v1/) |
| `GET` | `/redfish/Chassis` | signed in | Redfish Chassis Collection |
| `GET` | `/redfish/Chassis/` | signed in | Redfish Chassis Collection |
| `GET` | `/redfish/Chassis/1` | signed in | Redfish Chassis/1 Detail |
| `GET` | `/redfish/Chassis/1/` | signed in | Redfish Chassis/1 Detail |
| `GET` | `/redfish/Chassis/1/Thermal` | signed in | Redfish Chassis/1/Thermal: Fan RPMs and Temperature Sensors |
| `GET` | `/redfish/Chassis/1/Thermal/` | signed in | Redfish Chassis/1/Thermal: Fan RPMs and Temperature Sensors |
| `GET` | `/redfish/Storage` | signed in | Redfish Storage Collection |
| `GET` | `/redfish/Storage/` | signed in | Redfish Storage Collection |
| `GET` | `/redfish/Storage/1` | signed in | Redfish Storage/1 Detail: Drives & Volumes |
| `GET` | `/redfish/Storage/1/` | signed in | Redfish Storage/1 Detail: Drives & Volumes |
| `GET` | `/redfish/Storage/1/Drives/{drive_id}` | signed in | Redfish Storage/1/Drives/{drive_id}: Individual Drive Telemetry |
| `GET` | `/redfish/Systems` | signed in | Redfish Systems Collection |
| `GET` | `/redfish/Systems/` | signed in | Redfish Systems Collection |
| `GET` | `/redfish/Systems/1` | signed in | Redfish Systems/1 Detail: Compute & Memory Telemetry |
| `GET` | `/redfish/Systems/1/` | signed in | Redfish Systems/1 Detail: Compute & Memory Telemetry |
| `GET` | `/redfish/v1` | public | Redfish Service Root (/redfish/v1/) |
| `GET` | `/redfish/v1/` | public | Redfish Service Root (/redfish/v1/) |
| `GET` | `/redfish/v1/Chassis` | signed in | Redfish Chassis Collection |
| `GET` | `/redfish/v1/Chassis/` | signed in | Redfish Chassis Collection |
| `GET` | `/redfish/v1/Chassis/1` | signed in | Redfish Chassis/1 Detail |
| `GET` | `/redfish/v1/Chassis/1/` | signed in | Redfish Chassis/1 Detail |
| `GET` | `/redfish/v1/Chassis/1/Thermal` | signed in | Redfish Chassis/1/Thermal: Fan RPMs and Temperature Sensors |
| `GET` | `/redfish/v1/Chassis/1/Thermal/` | signed in | Redfish Chassis/1/Thermal: Fan RPMs and Temperature Sensors |
| `GET` | `/redfish/v1/Storage` | signed in | Redfish Storage Collection |
| `GET` | `/redfish/v1/Storage/` | signed in | Redfish Storage Collection |
| `GET` | `/redfish/v1/Storage/1` | signed in | Redfish Storage/1 Detail: Drives & Volumes |
| `GET` | `/redfish/v1/Storage/1/` | signed in | Redfish Storage/1 Detail: Drives & Volumes |
| `GET` | `/redfish/v1/Storage/1/Drives/{drive_id}` | signed in | Redfish Storage/1/Drives/{drive_id}: Individual Drive Telemetry |
| `GET` | `/redfish/v1/Systems` | signed in | Redfish Systems Collection |
| `GET` | `/redfish/v1/Systems/` | signed in | Redfish Systems Collection |
| `GET` | `/redfish/v1/Systems/1` | signed in | Redfish Systems/1 Detail: Compute & Memory Telemetry |
| `GET` | `/redfish/v1/Systems/1/` | signed in | Redfish Systems/1 Detail: Compute & Memory Telemetry |

### Remote Storage

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/remotes` | any of `storage:read`, `storage:admin` | Lists all configured cloud and network storage remotes |
| `POST` | `/api/v1/remotes` | `storage:admin` | Creates or updates a remote cloud storage backend |
| `POST` | `/api/v1/remotes/oauth/exchange` | any of `storage:admin`, `storage:write` | Receives redirected URL or code, forwards it to rclone's loopback listener, and returns JSON token |
| `POST` | `/api/v1/remotes/oauth/mobile-exchange` | signed in | Allows a mobile phone scanning the QR code to submit authorization code to the active session |
| `GET` | `/api/v1/remotes/oauth/mobile-page` | signed in | Serves a mobile-optimized authorization companion page when scanning the QR code |
| `POST` | `/api/v1/remotes/oauth/start` | any of `storage:admin`, `storage:write` | Initiates an OAuth authorization session via rclone authorize, capturing the cloud login URL |
| `GET` | `/api/v1/remotes/oauth/status/{session_id}` | any of `storage:admin`, `storage:write` | Get Oauth Session Status |
| `DELETE` | `/api/v1/remotes/oauth/{session_id}` | any of `storage:admin`, `storage:write` | Cancel Oauth Session |
| `GET` | `/api/v1/remotes/providers` | any of `storage:read`, `storage:admin` | Returns curated list of cloud and network storage providers |
| `POST` | `/api/v1/remotes/sync` | any of `backup:write`, `storage:write`, `storage:admin` | Triggers an asynchronous cloud sync/copy/move operation |
| `GET` | `/api/v1/remotes/sync/jobs` | any of `storage:read`, `storage:admin` | Lists recent and active cloud sync jobs |
| `GET` | `/api/v1/remotes/sync/jobs/{job_id}` | any of `storage:read`, `storage:admin` | Returns detailed real-time telemetry for a specific sync job |
| `POST` | `/api/v1/remotes/test` | any of `storage:admin`, `storage:write` | Tests connectivity and credentials of a remote configuration candidate before saving |
| `DELETE` | `/api/v1/remotes/{name}` | `storage:admin` | Deletes a remote cloud storage backend |
| `GET` | `/api/v1/remotes/{name}/files` | any of `storage:read`, `storage:admin` | Lists files and folders inside a remote storage location |
| `POST` | `/api/v1/remotes/{name}/mount` | any of `storage:admin`, `storage:write` | Mounts remote cloud storage into /mnt/remotes/{name} via FUSE |
| `POST` | `/api/v1/remotes/{name}/test` | any of `storage:admin`, `storage:write` | Tests connectivity and credentials of an existing configured remote |
| `POST` | `/api/v1/remotes/{name}/unmount` | any of `storage:admin`, `storage:write` | Unmounts /mnt/remotes/{name} |
| `GET` | `/api/v1/sync/pairs` | any of `backup:read`, `storage:read`, `storage:admin` | Two-way syncs between a folder here and a cloud folder (FEAT-06) |
| `PUT` | `/api/v1/sync/pairs` | any of `backup:write`, `storage:write`, `storage:admin` | Adds or changes a two-way sync; it does nothing until its dry run was seen and approved |
| `DELETE` | `/api/v1/sync/pairs/{pair_id}` | any of `backup:write`, `storage:write`, `storage:admin` | Delete Sync Pair |
| `POST` | `/api/v1/sync/pairs/{pair_id}/approve` | any of `backup:write`, `storage:write`, `storage:admin` | Approve Sync Pair |
| `POST` | `/api/v1/sync/pairs/{pair_id}/preview` | any of `backup:write`, `storage:write`, `storage:admin` | The dry run: what would be copied each way, deleted, and kept twice as a conflict |
| `POST` | `/api/v1/sync/pairs/{pair_id}/run` | any of `backup:write`, `storage:write`, `storage:admin` | Run Sync Pair |

### SFTP File Sharing

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/sftp/config` | any of `shares:manage`, `storage:admin` | Updates global SFTP configuration (port, authentication modes, chroot) |
| `GET` | `/api/v1/sftp/status` | any of `shares:manage`, `storage:read`, `system:view` | Returns operational status, port, sidecar state, and quick-connect info for SFTP |
| `POST` | `/api/v1/sftp/toggle` | any of `shares:manage`, `storage:admin` | Enables or disables the inbound SFTP service |
| `GET` | `/api/v1/sftp/users` | any of `shares:read`, `storage:admin` | Lists configured SFTP users, authorized shares, and access levels |
| `POST` | `/api/v1/sftp/users` | any of `shares:manage`, `storage:admin` | Creates a new dedicated SFTP user with designated share access |
| `DELETE` | `/api/v1/sftp/users/{username}` | any of `shares:manage`, `storage:admin` | Deletes an SFTP user and revokes their file transfer credentials |

### SNMP Monitoring

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/snmp/config` | any of `system:view`, `system:config` | Returns current SNMP configuration with masked credentials |
| `POST` | `/api/v1/snmp/config` | `system:config` | Updates SNMP daemon configuration |
| `GET` | `/api/v1/snmp/mib` | `system:view` | Returns downloadable SMIv2 ZETTLAB-ZETTNAS-MIB file |
| `GET` | `/api/v1/snmp/oids` | `system:view` | Evaluates live enterprise OIDs directly from in-memory state |
| `GET` | `/api/v1/snmp/status` | any of `system:view`, `storage:read` | Returns SNMP daemon running status and protocol capabilities |

### Samba File Sharing

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/samba/config` | any of `shares:manage`, `storage:admin` | Returns current smb.conf text |
| `POST` | `/api/v1/samba/reload` | `shares:manage` | Reloads Samba service configuration |
| `GET` | `/api/v1/samba/shares` | any of `shares:manage`, `storage:read` | Returns all configured Samba shares |
| `POST` | `/api/v1/samba/shares` | `shares:manage` | Creates or updates a Samba share |
| `DELETE` | `/api/v1/samba/shares/{name}` | `shares:manage` | Deletes a configured Samba share |
| `GET` | `/api/v1/samba/status` | any of `shares:manage`, `storage:read`, `system:view` | Returns current runtime status of Samba service and sidecar |

### Security

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/security/ip-blocks` | any of `system:view`, `audit:read` | List Ip Blocks |
| `POST` | `/api/v1/security/ip-blocks` | `system:config` | Add Ip Block |
| `DELETE` | `/api/v1/security/ip-blocks/{ip}` | `system:config` | Remove Ip Block |
| `GET` | `/api/v1/security/ransomware` | any of `system:view`, `audit:read` | Ransomware Status |
| `PUT` | `/api/v1/security/ransomware` | `system:config` | Ransomware Settings |
| `POST` | `/api/v1/security/ransomware/unfreeze` | `system:config` | Ransomware Unfreeze |
| `POST` | `/api/v1/security/rotate-secret-key` | `*` | Replaces the install's secret key and re-encrypts two-factor secrets and backup passphrases |

### Setup

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/setup/checklist` | signed in | Get Checklist |

### Single sign-on

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/oidc/apps/immich` | any of `users:write`, `system:config` | Turns on sign-in with ZettNAS's provider in a freshly installed Immich (M3) |
| `GET` | `/api/v1/auth/oidc/callback` | signed in | Sso Callback |
| `GET` | `/api/v1/auth/oidc/config` | signed in | Whether to show the single sign-on button, and its label (public) |
| `GET` | `/api/v1/auth/oidc/login` | signed in | Sso Login |
| `GET` | `/api/v1/auth/oidc/settings` | any of `users:write`, `system:config` | Sso Settings |
| `PUT` | `/api/v1/auth/oidc/settings` | any of `users:write`, `system:config` | Sso Save Settings |

### Smart Media & AI RAG Engine

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/ai/access` | any of `system:config`, `users:read` | Who may ask Zetty, per role (B8) |
| `PUT` | `/api/v1/ai/access` | `system:config` | Put Ai Access |
| `GET` | `/api/v1/ai/access/me` | signed in | Get My Ai Access |
| `GET` | `/api/v1/ai/actions/{action_id}` | signed in | Get Pending Ai Action |
| `POST` | `/api/v1/ai/actions/{action_id}/confirm` | any of `shares:read`, `storage:read`, `system:read` | Runs an action ZettAI proposed, after the user clicked Confirm (AI-01) |
| `POST` | `/api/v1/ai/ask` | any of `shares:read`, `storage:read`, `system:read` | Grounded Conversational RAG & Structured Recipe/Document Synthesis |
| `POST` | `/api/v1/ai/benchmark` | any of `system:config`, `storage:admin` | Executes a zero-disk synthetic embedding benchmark over 3 in-memory reference strings |
| `POST` | `/api/v1/ai/chat` | any of `shares:read`, `storage:read`, `system:read` ⏱ | Ask Zetty: answers about your files and your server, with web search and the server tools |
| `POST` | `/api/v1/ai/chat/stream` | any of `shares:read`, `storage:read`, `system:read` ⏱ | Streams real-time Server-Sent Events (SSE) tokens, tool activity traces, and thought chains from ZettAI |
| `GET` | `/api/v1/ai/chat/tools` | any of `system:read`, `shares:read`, `storage:read` | The server and web search tools Ask Zetty can use |
| `GET` | `/api/v1/ai/config` | any of `system:read`, `storage:read` | Get Rag Config |
| `POST` | `/api/v1/ai/config` | any of `system:config`, `storage:admin` | Update Rag Config |
| `PUT` | `/api/v1/ai/config` | any of `system:config`, `storage:admin` | Update Rag Config |
| `POST` | `/api/v1/ai/favorites` | any of `shares:read`, `storage:read`, `system:read` | Adds or removes a file path from ZettAI favorites |
| `POST` | `/api/v1/ai/folder/audit` | any of `shares:read`, `storage:read`, `system:read` | Executes hierarchical folder context aggregation (Mode A: targeted fact retrieval; Mode B: comprehensive folder audit with MMR diversific… |
| `GET` | `/api/v1/ai/folder/manifest` | any of `shares:read`, `storage:read`, `system:read` | Retrieves the recursive structure outline and topic inventory for a folder from NVMe SQLite WAL |
| `GET` | `/api/v1/ai/folders` | any of `system:config`, `ai:manage` | Returns configured watched/excluded RAG folders and discovered NAS shares with live disk standby state |
| `POST` | `/api/v1/ai/folders` | any of `system:config`, `ai:manage` | Adds, removes, or sets watched or excluded folders/shares for ZettAI RAG |
| `POST` | `/api/v1/ai/index` | any of `shares:user_write`, `storage:write`, `storage:admin`, `system:config` | Runs incremental, spindown-safe multi-modal indexing on the requested directory or watched folders |
| `POST` | `/api/v1/ai/index/control` | any of `system:config`, `ai:manage` | Pause, resume, stop, query, or flush the active RAG & Visual Search indexing sync job |
| `POST` | `/api/v1/ai/index/flush` | any of `system:config`, `ai:manage` | Flushes all indexed files, vector embeddings, chunks, and manifests from rag_index.db to start fresh |
| `POST` | `/api/v1/ai/index/forget` | any of `system:config`, `ai:manage` | Deletes what the index learned from a folder and stops learning it (AI-20) |
| `POST` | `/api/v1/ai/index/sync` | any of `shares:user_write`, `storage:write`, `storage:admin`, `system:config` | Runs incremental, spindown-safe multi-modal indexing on the requested directory or watched folders |
| `POST` | `/api/v1/ai/learning/relearn-failed` | any of `system:config`, `ai:manage` | Retries indexing failed files without waking sleeping drives |
| `GET` | `/api/v1/ai/learning/results` | any of `system:read`, `shares:read`, `storage:read` | Returns ZettAI 6-state learning status, succeeded/failed counts, and failed file list |
| `GET` | `/api/v1/ai/manifests` | any of `shares:read`, `storage:read`, `system:read` | Lists all indexed folder manifests and tree summaries across watched storage shares |
| `GET` | `/api/v1/ai/models/benchmark` | any of `system:read`, `ai:manage`, `system:config` | Last benchmark results, the recommended tiers and a running job (D2) |
| `POST` | `/api/v1/ai/models/benchmark` | any of `system:config`, `ai:manage` | Start Model Benchmark |
| `POST` | `/api/v1/ai/models/benchmark/apply` | any of `system:config`, `ai:manage` | Makes the recommended model of a tier Ask Zetty's chat model |
| `POST` | `/api/v1/ai/models/huggingface/pull` | any of `system:config`, `ai:manage` | Pulls/registers a release model from https://huggingface.co and flags hardware fit warnings |
| `GET` | `/api/v1/ai/models/huggingface/search` | any of `system:read`, `shares:read`, `storage:read` | Searches https://huggingface.co release models and evaluates hardware fit against NAS NPU/GPU/RAM |
| `POST` | `/api/v1/ai/models/install` | any of `system:config`, `ai:manage` | Downloads a model into Ollama in the background; poll the job for progress (AI-03) |
| `GET` | `/api/v1/ai/models/install/{job_id}` | any of `system:config`, `ai:manage` | Get Install Job |
| `POST` | `/api/v1/ai/models/install/{job_id}/cancel` | any of `system:config`, `ai:manage` | Cancel Install Job |
| `GET` | `/api/v1/ai/models/installed` | any of `system:read`, `ai:manage`, `system:config` | Models the Ollama runtime has installed, and copies of one model under another name (AI-16) |
| `GET` | `/api/v1/ai/models/recommendations` | any of `system:read`, `shares:read`, `storage:read` | Returns hardware-aware LLM & Multi-Modal model recommendations based on onboard NPU, GPU, and RAM |
| `DELETE` | `/api/v1/ai/models/remove` | any of `system:config`, `ai:manage` | Removes a model from the ZettAI catalog and local storage via DELETE /remove |
| `POST` | `/api/v1/ai/models/remove` | any of `system:config`, `ai:manage` | Removes a model from the ZettAI catalog and local storage |
| `POST` | `/api/v1/ai/models/select` | any of `system:config`, `ai:manage` | Selects and applies an LLM / multi-modal model for ZettAI, returning any hardware fit warnings |
| `DELETE` | `/api/v1/ai/models/{model_id}` | signed in | Removes a model from the ZettAI catalog and local storage |
| `GET` | `/api/v1/ai/photo-facets` | any of `shares:read`, `storage:read`, `system:read` | The photo filters: the years and places of the photos this person may see (AI-24) |
| `GET` | `/api/v1/ai/photo-vectors/status` | any of `system:read`, `storage:read` | How many photos can be found by meaning (B14) |
| `POST` | `/api/v1/ai/reindex` | any of `system:config`, `storage:admin` | Triggers background in-place re-embedding without waking sleeping hard drives |
| `GET` | `/api/v1/ai/reindex/status` | any of `system:read`, `storage:read` | Get Ai Reindex Status |
| `GET` | `/api/v1/ai/requests` | any of `system:config`, `audit:read` | The assistant's request log: who asked when, the model, web search, the outcome; no text |
| `GET` | `/api/v1/ai/search` | any of `shares:read`, `storage:read`, `system:read` | Zero-Disk-Touch Cross-Modal Visual & Document Search (GET) |
| `POST` | `/api/v1/ai/search` | any of `shares:read`, `storage:read`, `system:read` | Zero-Disk-Touch Cross-Modal Visual & Document Search (POST) |
| `GET` | `/api/v1/ai/status` | any of `system:read`, `shares:read`, `storage:read` | Get Media Status |
| `GET` | `/api/v1/ai/tags` | any of `shares:read`, `storage:read`, `system:read` | The document filters: each auto-tag with how many files this person may see carry it (B8) |
| `GET` | `/api/v1/ai/thumbnail/{file_id}` | any of `shares:read`, `storage:read`, `system:read` | Streams the NVMe-cached WebP micro-thumbnail from rag_index.db with zero array disk I/O |
| `GET` | `/api/v1/ai/vision/status` | any of `system:read`, `storage:read` | Photo captioning progress (AI-14) |
| `POST` | `/api/v1/media/ai/benchmark` | any of `system:config`, `storage:admin` | Executes a zero-disk synthetic embedding benchmark over 3 in-memory reference strings |
| `POST` | `/api/v1/media/ai/reindex` | any of `system:config`, `storage:admin` | Triggers background in-place re-embedding without waking sleeping hard drives |
| `GET` | `/api/v1/media/ai/reindex/status` | any of `system:read`, `storage:read` | Get Ai Reindex Status |
| `POST` | `/api/v1/media/ask` | any of `shares:read`, `storage:read`, `system:read` | Grounded Conversational RAG & Structured Recipe/Document Synthesis |
| `POST` | `/api/v1/media/chat` | any of `shares:read`, `storage:read`, `system:read` ⏱ | Ask Zetty: answers about your files and your server, with web search and the server tools |
| `POST` | `/api/v1/media/chat/stream` | any of `shares:read`, `storage:read`, `system:read` ⏱ | Streams real-time Server-Sent Events (SSE) tokens, tool activity traces, and thought chains from ZettAI |
| `GET` | `/api/v1/media/chat/tools` | any of `system:read`, `shares:read`, `storage:read` | The server and web search tools Ask Zetty can use |
| `GET` | `/api/v1/media/config` | any of `system:read`, `storage:read` | Get Rag Config |
| `PUT` | `/api/v1/media/config` | any of `system:config`, `storage:admin` | Update Rag Config |
| `GET` | `/api/v1/media/duplicates` | any of `shares:read`, `storage:read`, `system:read` | Files kept more than once, photos that look the same included, that this person may open (AI-35) |
| `POST` | `/api/v1/media/favorites` | any of `shares:read`, `storage:read`, `system:read` | Adds or removes a file path from ZettAI favorites |
| `POST` | `/api/v1/media/folder/audit` | any of `shares:read`, `storage:read`, `system:read` | Executes hierarchical folder context aggregation (Mode A: targeted fact retrieval; Mode B: comprehensive folder audit with MMR diversific… |
| `GET` | `/api/v1/media/folder/manifest` | any of `shares:read`, `storage:read`, `system:read` | Retrieves the recursive structure outline and topic inventory for a folder from NVMe SQLite WAL |
| `GET` | `/api/v1/media/folders` | any of `system:config`, `ai:manage` | Returns configured watched/excluded RAG folders and discovered NAS shares with live disk standby state |
| `POST` | `/api/v1/media/folders` | any of `system:config`, `ai:manage` | Adds, removes, or sets watched or excluded folders/shares for ZettAI RAG |
| `POST` | `/api/v1/media/index` | any of `shares:user_write`, `storage:write`, `storage:admin`, `system:config` | Runs incremental, spindown-safe multi-modal indexing on the requested directory or watched folders |
| `POST` | `/api/v1/media/index/control` | any of `system:config`, `ai:manage` | Pause, resume, stop, query, or flush the active RAG & Visual Search indexing sync job |
| `POST` | `/api/v1/media/index/flush` | any of `system:config`, `ai:manage` | Flushes all indexed files, vector embeddings, chunks, and manifests from rag_index.db to start fresh |
| `POST` | `/api/v1/media/learning/relearn-failed` | any of `system:config`, `ai:manage` | Retries indexing failed files without waking sleeping drives |
| `GET` | `/api/v1/media/learning/results` | any of `system:read`, `shares:read`, `storage:read` | Returns ZettAI 6-state learning status, succeeded/failed counts, and failed file list |
| `GET` | `/api/v1/media/manifests` | any of `shares:read`, `storage:read`, `system:read` | Lists all indexed folder manifests and tree summaries across watched storage shares |
| `POST` | `/api/v1/media/models/huggingface/pull` | any of `system:config`, `ai:manage` | Pulls/registers a release model from https://huggingface.co and flags hardware fit warnings |
| `GET` | `/api/v1/media/models/huggingface/search` | any of `system:read`, `shares:read`, `storage:read` | Searches https://huggingface.co release models and evaluates hardware fit against NAS NPU/GPU/RAM |
| `GET` | `/api/v1/media/models/recommendations` | any of `system:read`, `shares:read`, `storage:read` | Returns hardware-aware LLM & Multi-Modal model recommendations based on onboard NPU, GPU, and RAM |
| `DELETE` | `/api/v1/media/models/remove` | any of `system:config`, `ai:manage` | Removes a model from the ZettAI catalog and local storage via DELETE /remove |
| `POST` | `/api/v1/media/models/remove` | any of `system:config`, `ai:manage` | Removes a model from the ZettAI catalog and local storage |
| `POST` | `/api/v1/media/models/select` | any of `system:config`, `ai:manage` | Selects and applies an LLM / multi-modal model for ZettAI, returning any hardware fit warnings |
| `DELETE` | `/api/v1/media/models/{model_id}` | signed in | Removes a model from the ZettAI catalog and local storage |
| `POST` | `/api/v1/media/organize/apply` | any of `storage:write`, `storage:admin` | Applies media renames and folder restructuring (move, copy, or hardlink) |
| `POST` | `/api/v1/media/organize/preview` | any of `storage:read`, `storage:admin` | Analyzes source media files and calculates dry-run proposed Plex/Jellyfin renames |
| `POST` | `/api/v1/media/scan` | `system:config` | Trigger Media Scan |
| `GET` | `/api/v1/media/search` | any of `shares:read`, `storage:read`, `system:read` | Zero-Disk-Touch Cross-Modal Visual & Document Search (GET) |
| `POST` | `/api/v1/media/search` | any of `shares:read`, `storage:read`, `system:read` | Zero-Disk-Touch Cross-Modal Visual & Document Search (POST) |
| `GET` | `/api/v1/media/status` | any of `system:read`, `shares:read`, `storage:read` | Get Media Status |
| `GET` | `/api/v1/media/thumbnail/{file_id}` | any of `shares:read`, `storage:read`, `system:read` | Streams the NVMe-cached WebP micro-thumbnail from rag_index.db with zero array disk I/O |

### Snapshots

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/snapshots/schedules` | any of `backup:read`, `storage:read` | Get Schedules |
| `PUT` | `/api/v1/snapshots/schedules` | any of `backup:manage`, `storage:admin` | Put Schedule |
| `DELETE` | `/api/v1/snapshots/schedules/{share}` | any of `backup:manage`, `storage:admin` | Remove Schedule |
| `POST` | `/api/v1/snapshots/schedules/{share}/run` | any of `backup:manage`, `storage:admin` | Run Now |
| `GET` | `/api/v1/snapshots/{name}/browse` | any of `backup:read`, `storage:read` | Browse |
| `POST` | `/api/v1/snapshots/{name}/restore` | any of `backup:manage`, `storage:admin` | Restore |
| `POST` | `/api/v1/snapshots/{name}/rollback` | any of `backup:manage`, `storage:admin` | Puts the whole share back as it was in this snapshot; the current state is kept as a snapshot |

### Storage Replication

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/storage/replication/history` | `storage:read` | Get Replication History |
| `GET` | `/api/v1/storage/replication/jobs` | `storage:read` | List Replication Jobs |
| `POST` | `/api/v1/storage/replication/jobs` | `storage:admin` | Create Replication Job |
| `DELETE` | `/api/v1/storage/replication/jobs/{job_id}` | `storage:admin` | Delete Replication Job |
| `GET` | `/api/v1/storage/replication/jobs/{job_id}` | `storage:read` | Get Replication Job |
| `POST` | `/api/v1/storage/replication/jobs/{job_id}/run` | `storage:admin` | Run Replication Job |

### Storage Subsystem & PAL

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/storage/disks` | any of `storage:read`, `system:view` | Returns detected physical disks discovered via DiskDiscoveryHAL |
| `GET` | `/api/v1/storage/overview` | any of `storage:read`, `system:view` | Returns unified storage overview: pools, shares, platform info, and physical disk inventories |
| `GET` | `/api/v1/storage/platform` | any of `storage:read`, `shares:read`, `system:view` | Returns platform classification (Unraid, TrueNAS, Generic Linux), capabilities (observer mode vs active provisioner), and storage busy state |
| `GET` | `/api/v1/storage/pools` | any of `storage:read`, `system:view` | Returns hierarchical storage pool and array topology, including parity protection, data disks, SSD cache tiers, capacity gauges, and heal… |
| `POST` | `/api/v1/storage/pools` | `storage:admin` | Creates a new storage pool |
| `GET` | `/api/v1/storage/pools/discover` | any of `storage:admin`, `storage:read` | Discovers unimported or detachable external storage pools (e.g |
| `POST` | `/api/v1/storage/pools/import` | `storage:admin` | Imports an external storage pool into the platform |
| `DELETE` | `/api/v1/storage/pools/{pool_id}` | `storage:admin` | Destroys/unmounts a storage pool |
| `POST` | `/api/v1/storage/pools/{pool_id}/export` | `storage:admin` | Gracefully flushes dirty write cache, terminates active handles, and exports/unmounts a storage pool for safe physical detachment |
| `POST` | `/api/v1/storage/pools/{pool_id}/rename` | `storage:admin` | Renames an existing storage pool (OpenZFS or Btrfs) and creates an atomic backwards-compatibility symlink to preserve Docker container vo… |
| `GET` | `/api/v1/storage/pools/{pool_id}/snapshots` | any of `storage:read`, `storage:admin` | Lists filesystem subvolume snapshots for a storage pool |
| `POST` | `/api/v1/storage/pools/{pool_id}/snapshots` | `storage:admin` | Creates an atomic Btrfs subvolume snapshot |
| `POST` | `/api/v1/storage/pools/{pool_id}/snapshots/break-glass-delete` | `storage:admin` | Overrides Governance-mode WORM lock to delete a snapshot with mandatory audit logging |
| `POST` | `/api/v1/storage/pools/{pool_id}/snapshots/restore` | `storage:admin` | Restores or rolls back a Btrfs subvolume snapshot |
| `DELETE` | `/api/v1/storage/pools/{pool_id}/snapshots/{snapshot_name}` | `storage:admin` | Deletes a Btrfs subvolume snapshot |
| `GET` | `/api/v1/storage/schedule` | `storage:read` | Retrieves current automated SMART self-test and storage scrub schedule |
| `PUT` | `/api/v1/storage/schedule` | `storage:admin` | Updates automated SMART self-test and storage scrub schedule |
| `POST` | `/api/v1/storage/scrub` | `storage:admin` | Initiates or monitors non-destructive array parity check or filesystem scrub |
| `GET` | `/api/v1/storage/share-access` | `shares:manage` | Who can use which share in the file manager (SEC-10) |
| `PUT` | `/api/v1/storage/share-access` | `shares:manage` | Put Share Access |
| `GET` | `/api/v1/storage/shares` | any of `storage:read`, `shares:read`, `system:view` | Returns network shares (Samba, NFS, WebDAV) with comment, security level, cache tiering settings, and live disk usage statistics |
| `POST` | `/api/v1/storage/shares` | `shares:manage` | Creates a new network share |
| `DELETE` | `/api/v1/storage/shares/{name}` | `shares:manage` | Deletes a network share configuration |
| `GET` | `/api/v1/storage/shares/{name}/compression` | any of `storage:read`, `shares:manage` | What compression a share's data uses now, the ratio where the filesystem reports one, and what can be chosen (FEAT-15) |
| `PUT` | `/api/v1/storage/shares/{name}/compression` | any of `shares:manage`, `storage:admin` | Change a share's compression; it applies to data written from now on (FEAT-15) |
| `GET` | `/api/v1/storage/smart/failure-predictions` | any of `storage:read`, `system:view` | Scrutiny-style failure probability analytics and historical attribute velocity for all discovered storage drives |
| `GET` | `/api/v1/storage/smart/schedule` | any of `storage:read`, `system:view` | Returns current SMART test schedule, intervals, and last execution timestamps |
| `POST` | `/api/v1/storage/smart/schedule` | `storage:admin` | Configures automated Short and Extended SMART test schedules |
| `GET` | `/api/v1/storage/unraid-api/status` | any of `storage:read`, `system:view` | Array, disks, shares and parity check from the Unraid API (companion mode, D5) |

### System & Storage

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/buttons` | any of `hardware:read`, `system:view` | Get Buttons |
| `POST` | `/api/v1/buttons` | `system:config` | Post Buttons |
| `POST` | `/api/v1/copy/cancel` | any of `storage:write`, `shares:user_write`, `storage:admin` | Copy Cancel |
| `POST` | `/api/v1/copy/confirm` | any of `storage:write`, `shares:user_write`, `storage:admin` | Copy Confirm |
| `POST` | `/api/v1/copy/dismiss-ingest` | any of `storage:write`, `shares:user_write`, `storage:admin` | Dismiss Pending Ingest |
| `POST` | `/api/v1/copy/eject` | any of `storage:write`, `storage:admin` | Eject Media |
| `GET` | `/api/v1/copy/history` | any of `system:view`, `storage:read` | Get Copy History |
| `POST` | `/api/v1/copy/pause` | any of `storage:write`, `shares:user_write`, `storage:admin` | Pause Copy |
| `POST` | `/api/v1/copy/rescan` | any of `storage:write`, `shares:user_write`, `storage:admin` | Rescan Media |
| `POST` | `/api/v1/copy/resume` | any of `storage:write`, `shares:user_write`, `storage:admin` | Resume Copy |
| `POST` | `/api/v1/copy/start` | any of `storage:write`, `shares:user_write`, `storage:admin` | Start Copy |
| `POST` | `/api/v1/disk/locate` | any of `storage:write`, `storage:admin` | Disk Locate Endpoint |
| `POST` | `/api/v1/disk/smart_test` | `storage:admin` | Disk Smart Test |
| `GET` | `/api/v1/disk/smart_tests` | any of `storage:read`, `hardware:read`, `system:view` | Returns persistent historical self-test runs and latest diagnostic report |
| `GET` | `/api/v1/disk_detail` | any of `storage:read`, `system:view` | Disk Detail |
| `POST` | `/api/v1/disk_wake` | any of `storage:write`, `storage:admin` | Disk Wake |
| `DELETE` | `/api/v1/events/clear` | `system:config` | Clear Events |
| `GET` | `/api/v1/health` | public | Public health probe (no secrets) for Docker HEALTHCHECK, the updater and monitoring |
| `GET` | `/api/v1/layout` | signed in | Get Layout |
| `POST` | `/api/v1/layout` | any of `system:config`, `shares:user_write` | Post Layout |
| `POST` | `/api/v1/lcd/cycle` | any of `system:config`, `hardware:fans` | Post Lcd Cycle |
| `GET` | `/api/v1/lcd/page` | any of `hardware:read`, `system:view` | Get Lcd Page |
| `POST` | `/api/v1/lcd/page` | any of `system:config`, `hardware:fans` | Post Lcd Page |
| `GET` | `/api/v1/lcd/preview.png` | any of `hardware:read`, `system:view` | The LCD as the built-in (no-browser) renderer draws it, as a 640x172 PNG |
| `GET` | `/api/v1/screen` | any of `hardware:read`, `system:view` | Screen State |
| `POST` | `/api/v1/screen` | `system:config` | Post Screen State |
| `POST` | `/api/v1/state` | any of `system:config`, `shares:user_write` | Post State |
| `GET` | `/api/v1/system/about` | signed in | Returns high-level system information, current version, chassis twin, and runtime stats |
| `GET` | `/api/v1/system/disks` | any of `storage:read`, `system:view` | Compatibility endpoint returning physical disks discovered via HAL |
| `GET` | `/api/v1/system/health-signal` | `system:view` | The opt-in anonymous weekly report: whether it is on, and exactly what it sends |
| `PUT` | `/api/v1/system/health-signal` | `system:config` | Put Health Signal |
| `GET` | `/api/v1/system/identity` | signed in | The server's name and time zone (UX-17) |
| `PUT` | `/api/v1/system/identity` | `system:config` | Put Server Identity |
| `GET` | `/api/v1/system/network-topology` | any of `system:view`, `system:config` | Expose complete host networking topology, physical NIC carrier states, link negotiation speeds (10GbE / 2.5GbE / 1GbE / 100M), duplex, MT… |
| `POST` | `/api/v1/system/profile` | `system:config` | Set System Profile |
| `GET` | `/api/v1/system/protection` | `system:view` | The copies outside this NAS, for the Overview (FEAT-01) |
| `POST` | `/api/v1/system/reboot` | `system:power` | Trigger system reboot (requires system:power scope) |
| `GET` | `/api/v1/system/security-posture` | any of `system:view`, `system:config`, `users:read` | Evaluates real-time security posture across authentication, MFA, HTTPS, guest network shares, and API credential hygiene |
| `POST` | `/api/v1/system/security-posture/fix/{fix_id}` | `system:config` | Applies one Security Advisor fix (B11): tightens a setting an upgraded install kept |
| `POST` | `/api/v1/system/shutdown` | `system:power` | Trigger system poweroff (requires system:power scope) |
| `GET` | `/api/v1/system/status-summary` | `system:view` | What needs attention, for the Overview (UX-1) |
| `GET` | `/api/v1/system/updates` | `system:view` | Release/commit check, then a registry digest check (OPS-18) |
| `POST` | `/api/v1/system/updates/apply` | any of `system:power`, `system:manage` | Pulls the latest ZettNAS image and initiates a graceful self-update |
| `GET` | `/api/v1/system/updates/last-result` | any of `system:view`, `system:manage` | How the last in-app update or revert ended (OPS-7) |
| `GET` | `/api/v1/system/updates/previous` | any of `system:power`, `system:manage` | Versions this install can go back to: a pre-update snapshot whose image is still on the host |
| `POST` | `/api/v1/system/updates/revert` | any of `system:power`, `system:manage` | Goes back to the version before the last update and restores the data as it was then (OPS-01) |
| `GET` | `/api/v1/tokens` | any of `users:read`, `system:config` | List Tokens |
| `POST` | `/api/v1/tokens` | any of `users:write`, `system:config` | Create Token |
| `DELETE` | `/api/v1/tokens/{token_id}` | any of `users:write`, `system:config` | Delete Token |
| `GET` | `/api/v1/unraid` | any of `system:view`, `storage:read` | Get Unraid Telemetry |
| `POST` | `/api/v1/usb/backup` | any of `backup:manage`, `system:config` | Backs the NAS up to this USB disk now: every off-site backup that lives on it (FEAT-07) |
| `GET` | `/api/v1/usb/disks` | any of `storage:read`, `system:view` | USB disks mounted under /mnt/disks: space, the backups that go to each, camera media (FEAT-07) |
| `POST` | `/api/v1/usb/dismiss` | any of `storage:write`, `storage:admin`, `backup:manage` | Usb Dismiss |
| `POST` | `/api/v1/usb/import` | any of `storage:write`, `storage:admin` | Copies a USB disk's photos and videos (its DCIM folder, else the whole disk) into dated folders, verified file by file like the card read… |
| `PUT` | `/api/v1/usb/settings` | `system:config` | Usb Settings |

### System Diagnostics

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/system/diagnostics-bundle` | `system:config` | Generates server-only diagnostics bundle via GET |
| `POST` | `/api/v1/system/diagnostics-bundle` | `system:config` | Generates an in-memory zip archive containing complete sanitized system & client diagnostics: - system_summary.json (platform, kernel, ch… |
| `GET` | `/api/v1/system/diagnostics-summary` | any of `system:view`, `system:read`, `system:config` | Returns a fast diagnostic summary for in-browser inspection and support markdown generation |

### Telemetry & Stats

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/history` | any of `hardware:read`, `system:view` | Get History |
| `GET` | `/api/v1/lcd_status` | any of `hardware:read`, `system:view` | Get Lcd Status |
| `GET` | `/api/v1/stats` | signed in | Get Stats |
| `GET` | `/api/v1/stats/stream` | signed in ⏱ | Stats Stream |

### Thermal & Fan Control

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/fans` | any of `hardware:read`, `system:view` | Get Fans |
| `POST` | `/api/v1/fans` | `hardware:fans` | Post Fans |
| `GET` | `/api/v1/fans/calibrate/acoustic` | any of `hardware:read`, `system:view` | Returns the live progress, state, and stability results of the acoustic sweep |
| `POST` | `/api/v1/fans/calibrate/acoustic` | any of `hardware:fans`, `hardware:*`, `system:config` | Initiates an automated acoustic fan calibration sweep from 58 to 183 PWM at 5-second intervals to map RPM stability and chassis harmonic… |
| `POST` | `/api/v1/fans/calibrate/acoustic/stop` | any of `hardware:fans`, `hardware:*`, `system:config` | Aborts the acoustic calibration sweep and immediately restores normal fan curves |
| `GET` | `/api/v1/fans/presets` | any of `hardware:read`, `system:view` | Lists all saved custom fan curve presets |
| `POST` | `/api/v1/fans/presets` | `hardware:fans` | Saves or updates a custom named fan curve preset |
| `DELETE` | `/api/v1/fans/presets/{preset_name}` | `hardware:fans` | Deletes a custom named fan curve preset |
| `POST` | `/api/v1/fans/presets/{preset_name}/apply` | `hardware:fans` | Applies a custom named preset to the active fan curve |

### UPS & Power Integrity

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/ups` | any of `hardware:read`, `system:view` | Returns real-time UPS telemetry enriched with power flow metrics and voltage data |
| `GET` | `/api/v1/ups/config` | `system:view` | Returns persistent UPS configuration with secret passwords masked |
| `POST` | `/api/v1/ups/config` | `system:config` | Saves persistent UPS configuration and reloads power watchdog parameters |
| `POST` | `/api/v1/ups/discover` | `system:config` | Auto-discovers connected USB HID power devices and active LAN power daemons |
| `GET` | `/api/v1/ups/events` | any of `hardware:read`, `system:view` | Returns historical power events, outages, brownouts, and diagnostic logs from SQLite |
| `GET` | `/api/v1/ups/nut-server` | `system:view` | The NUT server for the family's PCs: on or off, port, monitor user, PCs watching (FEAT-11) |
| `PUT` | `/api/v1/ups/nut-server` | `system:config` | Put Nut Server |
| `GET` | `/api/v1/ups/nut-server/client` | `system:config` | The monitor password and the upsmon.conf line for a PC (admins only) |
| `POST` | `/api/v1/ups/self-test` | `system:config` | Issues 10-second battery self-test diagnostic command to the configured UPS |
| `POST` | `/api/v1/ups/simulate` | `system:config` | Triggers simulated power outage drill for desktop UI testing |
| `POST` | `/api/v1/ups/test-connection` | `system:config` | Validates connection to a UPS daemon without altering persistent configuration |

### Virtual Machines

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/vms` | any of `system:view`, `storage:read` | Lists configured virtual machines with live states and resource allocations |
| `POST` | `/api/v1/vms` | any of `vms:manage`, `system:config` | Provisions a new virtual machine with dynamic headroom validation and volume mappings |
| `GET` | `/api/v1/vms/backups` | any of `system:view`, `storage:read` | Lists all saved VM backup archives across all virtual machines |
| `DELETE` | `/api/v1/vms/backups/{backup_id}` | any of `vms:manage`, `system:config` | Deletes a VM backup archive from disk and updates registry |
| `POST` | `/api/v1/vms/backups/{backup_id}/restore` | any of `vms:manage`, `system:config` | Restores VM configuration and disk images from backup archive |
| `GET` | `/api/v1/vms/bridges` | any of `system:view`, `storage:read` | Lists available host network bridges |
| `GET` | `/api/v1/vms/catalog` | any of `system:view`, `storage:read` | Lists curated official distribution images with local cache detection |
| `GET` | `/api/v1/vms/catalog/tasks` | any of `system:view`, `storage:read` | Returns status and telemetry of active and recent ISO download tasks |
| `DELETE` | `/api/v1/vms/catalog/tasks/{task_id}` | any of `vms:manage`, `system:config` | Cancels an in-flight ISO download task or removes a finished/failed task record |
| `POST` | `/api/v1/vms/catalog/{catalog_id}/download` | any of `vms:manage`, `system:config` | Initiates a background download of a verified official distribution ISO |
| `GET` | `/api/v1/vms/iommu-groups` | any of `system:view`, `storage:read` | Scans Linux host sysfs /sys/kernel/iommu_groups to report IOMMU isolation groups and PCI devices |
| `DELETE` | `/api/v1/vms/isos` | any of `vms:manage`, `system:config` | Delete Iso Image |
| `GET` | `/api/v1/vms/isos` | any of `system:view`, `storage:read` | Lists available ISO and OS installation images |
| `POST` | `/api/v1/vms/isos/upload` | any of `vms:manage`, `system:config` | Streams uploaded ISO file directly into NAS storage (/mnt/user/isos) |
| `GET` | `/api/v1/vms/kvm/diagnose` | any of `system:view`, `storage:read` | Returns detailed multi-tier KVM diagnostic report including host hardware and cgroup analysis |
| `GET` | `/api/v1/vms/telemetry` | any of `system:view`, `storage:read` | Returns KVM hypervisor acceleration state, dynamic memory headroom budget, and CPU capacity |
| `GET` | `/api/v1/vms/usb-devices` | any of `system:view`, `storage:read` | Lists physical and virtual USB devices connected to the host |
| `DELETE` | `/api/v1/vms/{vm_id}` | any of `vms:manage`, `system:config` | Deletes a virtual machine definition and cleans up its virtual disk directory |
| `GET` | `/api/v1/vms/{vm_id}` | any of `system:view`, `storage:read` | Retrieves detailed virtual machine configuration, attachments, and runtime state |
| `PATCH` | `/api/v1/vms/{vm_id}` | any of `vms:manage`, `system:config` | Updates virtual machine configuration (RAM, vCPUs, name, description, ISO path, boot order, autostart) |
| `PUT` | `/api/v1/vms/{vm_id}` | any of `vms:manage`, `system:config` | Updates virtual machine configuration (RAM, vCPUs, name, description, ISO path, boot order, autostart) |
| `POST` | `/api/v1/vms/{vm_id}/action` | any of `vms:manage`, `system:config` | Executes lifecycle action on target VM: start, stop, restart, reboot, acpi_shutdown, pause, resume, force_off |
| `POST` | `/api/v1/vms/{vm_id}/backup` | any of `vms:manage`, `system:config` | Takes a full backup of VM configuration and virtual disks |
| `GET` | `/api/v1/vms/{vm_id}/backups` | any of `system:view`, `storage:read` | Lists saved backup archives for target VM |
| `GET` | `/api/v1/vms/{vm_id}/connection-info` | any of `system:view`, `storage:read` | Returns multi-protocol access credentials (SSH, VNC, Web Console) for a target VM |
| `POST` | `/api/v1/vms/{vm_id}/console/token` | any of `vms:write`, `vms:manage`, `system:config` | Issues single-use ephemeral ticket for noVNC / serial console WebSocket streaming |
| `POST` | `/api/v1/vms/{vm_id}/disk/resize` | any of `vms:manage`, `system:config` | Expands a virtual machine virtual disk (qcow2/raw) using qemu-img resize |
| `GET` | `/api/v1/vms/{vm_id}/error` | any of `system:view`, `storage:read` | Returns the last recorded QEMU error or startup failure log for a virtual machine |
| `POST` | `/api/v1/vms/{vm_id}/resize-disk` | any of `vms:manage`, `system:config` | Expands a virtual machine virtual disk (qcow2/raw) using qemu-img resize |
| `POST` | `/api/v1/vms/{vm_id}/restart` | any of `vms:manage`, `system:config` | Restarts the target virtual machine |
| `GET` | `/api/v1/vms/{vm_id}/screenshot` | any of `system:view`, `storage:read` | Captures and returns a live graphical screendump of the VM via QMP screendump |
| `GET` | `/api/v1/vms/{vm_id}/snapshots` | any of `system:view`, `storage:read` | Lists snapshots for target virtual machine with QCOW2 internal and saved metadata |
| `POST` | `/api/v1/vms/{vm_id}/snapshots` | any of `vms:manage`, `system:config` | Creates a live snapshot (savevm via QMP if running, qemu-img if stopped) |
| `DELETE` | `/api/v1/vms/{vm_id}/snapshots/{snapshot_name}` | any of `vms:manage`, `system:config` | Deletes a named snapshot |
| `POST` | `/api/v1/vms/{vm_id}/snapshots/{snapshot_name}/revert` | any of `vms:manage`, `system:config` | Reverts virtual machine state to a named snapshot |
| `POST` | `/api/v1/vms/{vm_id}/start` | any of `vms:manage`, `system:config` | Starts the target virtual machine |
| `GET` | `/api/v1/vms/{vm_id}/status` | any of `system:view`, `storage:read` | Queries live QMP monitor socket for hypervisor execution state and vCPU threads |
| `POST` | `/api/v1/vms/{vm_id}/stop` | any of `vms:manage`, `system:config` | Stops the target virtual machine |

### Wallpapers

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/wallpaper_url` | signed in | Get Wallpaper Url |
| `GET` | `/api/v1/wallpapers` | signed in | List Wallpapers |
| `GET` | `/api/v1/wallpapers/download/{filename}` | public | Download Wallpaper |
| `POST` | `/api/v1/wallpapers/rename` | any of `system:config`, `shares:user_write` | Rename Wallpaper |
| `POST` | `/api/v1/wallpapers/select` | any of `system:config`, `shares:user_write` | Select Wallpaper |
| `GET` | `/api/v1/wallpapers/thumb/{filename}` | signed in | Get Wallpaper Thumbnail |
| `POST` | `/api/v1/wallpapers/upload` | any of `system:config`, `shares:user_write` | Upload Wallpaper |
| `DELETE` | `/api/v1/wallpapers/{filename}` | any of `system:config`, `shares:user_write` | Delete Wallpaper |

### WebDAV Storage

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/webdav/config` | `*` | Updates WebDAV configuration and restarts the daemon if running |
| `POST` | `/api/v1/webdav/restart` | any of `shares:manage`, `storage:admin` | Restarts the WebDAV daemon |
| `GET` | `/api/v1/webdav/status` | any of `shares:manage`, `storage:read`, `system:view` | Returns WebDAV daemon operational status, port, URLs, and quick-connect commands |
| `POST` | `/api/v1/webdav/toggle` | any of `shares:manage`, `storage:admin` | Enables or disables the WebDAV service |

### backup

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/protection/jobs` | any of `backup:read`, `storage:read`, `system:view` | List Protection Jobs |
| `PUT` | `/api/v1/protection/scrub/{pool_id}` | `storage:admin` | Set Monthly Scrub |

### users

| Method | Path | Access | What it does |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/users/{user_id}/erase-data` | signed in | Erase User Data |
| `GET` | `/api/v1/users/{user_id}/export` | signed in | Export User Data |

<!-- END generated endpoints -->

---

## Response Formats & Error Handling

Responses are `application/json`. Every error has the same body (the `Error` schema in
`/openapi.json`):

```json
{"error": "not_found", "detail": "Share link not found or revoked", "code": 404}
```

Validation errors (422) add `errors: [{"field": "...", "message": "..."}]`; 500s add a `reference`.

* `400 Bad Request` — the request makes no sense for this resource (e.g. an out-of-range fan curve).
* `401 Unauthorized` — no session or token, or it has expired or been revoked.
* `403 Forbidden` — the token or role lacks the scope, the password must be changed first, the address is blocked, or a browser request came from another site.
* `404 Not Found` — nothing with that id or name.
* `409 Conflict` — a copy job, update or SMART test is already running, or the target is older than what runs.
* `413 Payload Too Large` — the body is over the limit for that route.
* `422 Unprocessable Entity` — the body, query or path failed validation; `errors` names each field.
* `423 Locked` — file writes are frozen by the ransomware guard.
* `429 Too Many Requests` — wait as long as `Retry-After` says. Operations marked ⏱ above can answer it.
* `500 Internal Server Error` — the details are in the server log under `reference`.

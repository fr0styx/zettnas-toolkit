# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.9.x (latest patch) | ✅ |
| < 1.9.2 | ❌ Upgrade to 1.9.2 or later: earlier versions have known critical issues (see below). |

Only the latest stable release (`:latest` / `:stable`) gets security fixes. The `:edge` channel follows `main` and may contain unreleased fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately through GitHub: **Security → Report a vulnerability** on
[fr0styx/zettnas-toolkit](https://github.com/fr0styx/zettnas-toolkit/security/advisories/new).
Include the version, how the container is deployed (Unraid template, Compose, `docker run`), and steps to reproduce.

What to expect:

- An acknowledgement within **3 days**.
- An assessment and a planned fix date within **10 days**.
- A fix released as a patch version, with a GitHub Security Advisory crediting you (unless you prefer not to be named).
- We ask that you give us **90 days**, or until a fix is released if sooner, before disclosing publicly.

## Scope

In scope: the ZettNAS Toolkit web app and API, the WebDAV/SFTP services it runs, the in-app updater, and the published container images.

Out of scope: vulnerabilities in the host OS, Docker itself, or third-party containers that ZettNAS manages; issues that need an already-compromised admin account; denial of service from the local network by volume alone.

## Hardening recommendations

- Change the initial `admin` password on first login (1.9.2 and later enforce this).
- Don't publish the web UI (port 8080) or WebDAV (port 8084) to the internet; use a VPN or a reverse proxy with its own authentication.
- Leave WebDAV off unless you need it. Give WebDAV users their own accounts.
- Mount the Docker socket only into ZettNAS, and never `chmod 666` it. ZettNAS reaches it through its allow-list proxy (see below).
- Keep the appdata folder private: it holds the session-signing key and password hashes.

## Ransomware guard and blocked addresses

**Ransomware guard** (Security → Ransomware guard, on by default). It watches changes
made through ZettNAS: the file manager, uploads and WebDAV. With **guard files** turned
on, it also places `!ZettNAS-guard-file.docx` in each share and checks it every 30
seconds, which catches attacks over SMB and NFS too. It reacts to:

- 150 renames or permanent deletes in 60 seconds from one user or address
  (moving files to the Recycle Bin doesn't count);
- 10 files renamed to known ransomware extensions, or ransom notes written, in 60
  seconds;
- a guard file that changed or disappeared.

It then freezes writes: the file manager and WebDAV answer 423, ZettNAS's own Samba
shares turn read-only, and the SFTP service stops. Next it snapshots pools where
ZettNAS manages snapshots (Btrfs and ZFS on generic Linux; on Unraid, snapshots are
Unraid's job), blocks the source address for 24 hours, and sends a critical alert to
every notification channel. Unraid's own SMB shares aren't changed: use guard files
for early warning there. An admin lifts the freeze under Security.

**Blocked addresses.** An address with 20 failed sign-ins (web or WebDAV) in 15
minutes is blocked for an hour. Blocked addresses get 403 from the web app and WebDAV
and are denied by ZettNAS's Samba. Loopback and the networks in `ZETTNAS_TRUSTED_IPS`
(comma-separated, for example `192.168.1.10,10.0.0.0/24`) are never blocked. If you
lock yourself out, run
`docker exec zettnas-toolkit python3 -m backend.services.ip_block --unblock <address>`.

## Privileges and root-equivalent roles

ZettNAS runs as root in its container with raw-disk and hardware access, because it
reads SMART data, drives the fans and LCD, mounts disks and runs VMs. Treat the web UI
like an SSH login to the host.

**Docker API proxy.** The app doesn't use the Docker socket directly. A separate
process (`backend/docker_proxy.py`) forwards only the Docker API calls the app needs
and refuses everything else (swarm, plugins, secrets, image build/load/import,
commit, export). Creating a container with host-level access (privileged, host PID or
IPC namespace, dangerous capabilities, raw block devices, or bind mounts of `/`,
`/etc`, `/boot`, `/dev` or the Docker socket) is allowed only from flows you confirm:
installing an app after its security review, recreating an existing container, and
the updater. Each one is logged to `data/docker-proxy-audit.log`. Set
`ZETTNAS_DOCKER_PROXY=off` to bypass the proxy.

The proxy narrows what a bug in the web app can do through Docker. It is not a
sandbox: the web process itself still runs as root.

**Root-equivalent permissions.** Anyone holding one of these can gain root on the
host, so give them only to people you'd give the root password:

| Permission | Built-in role | Why |
| ---------- | ------------- | --- |
| `*` | SuperAdmin | Everything below |
| `containers:*`, `containers:manage`, `containers:exec` | AppOperator | Can run a container with host mounts, or a shell in one |
| `vms:manage` | (custom) | Can pass disks and PCI/USB devices to a VM |
| `storage:admin` | StorageAdmin | Raw disk access: format, mount and wipe |
| `system:config` | (custom) | Network, services and updates |

StorageAdmin can also destroy data without gaining root. BackupOperator, ShareUser
and Auditor aren't root-equivalent.

## Past advisories

| Version fixed | Issue | Severity |
| ------------- | ----- | -------- |
| 1.9.2 | Disabled, deleted or revoked users' sessions became superadmin sessions (SEC-01) | Critical |
| 1.9.2 | Archive extraction could write files outside the destination via links (SEC-03) | High |
| 1.9.2 | Uploaded HTML/SVG files ran script in the app's origin (SEC-05) | High |
| 1.9.2 | Default password change was not enforced; no re-authentication to change a password (SEC-23, SEC-13) | High |
| 1.9.2 | The AI assistant could restart/stop containers and change fans without confirmation (AI-01) | Medium |

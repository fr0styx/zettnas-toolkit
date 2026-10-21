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
- Mount the Docker socket only into ZettNAS, and never `chmod 666` it.
- Keep the appdata folder private: it holds the session-signing key and password hashes.

## Past advisories

| Version fixed | Issue | Severity |
| ------------- | ----- | -------- |
| 1.9.2 | Disabled, deleted or revoked users' sessions became superadmin sessions (SEC-01) | Critical |
| 1.9.2 | Archive extraction could write files outside the destination via links (SEC-03) | High |
| 1.9.2 | Uploaded HTML/SVG files ran script in the app's origin (SEC-05) | High |
| 1.9.2 | Default password change was not enforced; no re-authentication to change a password (SEC-23, SEC-13) | High |
| 1.9.2 | The AI assistant could restart/stop containers and change fans without confirmation (AI-01) | Medium |

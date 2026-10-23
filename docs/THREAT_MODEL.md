# ZettNAS threat model

What ZettNAS protects, from whom, where the trust boundaries are, and which risks
remain. It describes the design as of the current main branch. Report gaps as in
[SECURITY.md](../SECURITY.md).

## What we protect

| Asset | Where it lives | Why it matters |
| ----- | -------------- | -------------- |
| Your files | Shares under the pool (`/mnt/user` on Unraid) | The reason the NAS exists |
| The host | ZettNAS runs as root with disk, device and Docker access | Taking over ZettNAS means taking over the server |
| Accounts and sessions | `data/users.db` (password hashes), session-signing key in `data/` | Lets someone act as you |
| AI index and chats | `data/rag_index.db`, `data/ai_conversations.db` | Contains excerpts of your files and what you asked |
| Secrets for integrations | Notification tokens, cloud remotes (rclone), API tokens | Reach other services in your name |

## Who we defend against

1. **Someone on the internet.** ZettNAS is not meant to be exposed directly. Remote
   access goes through Tailscale or a reverse proxy with its own sign-in.
2. **Someone on your network**, including a compromised PC or IoT device: password
   guessing, cross-site requests from a page you visit, ransomware on a PC that has
   your shares mapped.
3. **A signed-in user with fewer rights** trying to reach other users' folders or admin
   functions.
4. **Content you index or download**: documents and web pages with instructions aimed at
   Ask Zetty (prompt injection), malformed images and archives.
5. **A compromised update channel or third-party image.**

Out of scope: someone with physical access or root on the host, a compromised admin
account (it is root-equivalent by design, see below), and flaws in Docker, the kernel
or the apps you install.

## Trust boundaries and how each is defended

| Boundary | Defences |
| -------- | -------- |
| Browser → web app (port 8082) | Session cookie (HttpOnly, SameSite) or Bearer tokens; CSRF origin check on cookie writes; enforced Content-Security-Policy; must-change default password; login lockout and IP blocking (20 failures in 15 min); optional TOTP 2FA |
| Clients → WebDAV (8084) and SFTP | Only real ZettNAS accounts; per-user share access; same lockout and IP blocking |
| User → files | Every path is resolved inside the allowed roots (no `..` or symlink escape); non-admins reach only their home folder and shares they were given, at the level they were given |
| User → admin functions | Scoped permissions on every endpoint; root-equivalent permissions listed in SECURITY.md; destructive actions need confirmation |
| Web app → Docker | Allow-list proxy: no swarm, plugins, secrets, image build/import, commit or export; containers with host-level access only from confirmed flows, each logged |
| Web app → network (SSRF) | Outbound fetches (web search, previews, webhooks) only to public addresses; AI runtimes only on this machine or its Docker network, never the LAN router |
| Indexed content → Ask Zetty | File and web text is passed as quoted data, never as instructions; tools that change the system need your click on Confirm; web access only in chats where you turned it on; answers are limited to what your account may read |
| Update channel → host | The updater installs only images from this project's registry; images are signed (cosign) and scanned (Trivy) in CI, and promotion to Stable verifies the signature. The in-app updater itself does not verify signatures yet (planned); data is snapshotted before each in-app update and can be rolled back |
| Files → shares (ransomware) | Ransomware guard: mass renames or deletes, ransomware extensions, ransom notes or a changed guard file freeze writes, snapshot where supported, block the source and alert |

## What remains

- **ZettNAS is root on the host.** It needs raw disk, fan, LCD and VM access. A remote
  code execution bug in the web app is a host compromise. The Docker proxy narrows
  what a bug can do through Docker, but the web process is not yet separated from a
  privileged helper.
- **Admins are root-equivalent.** Anyone with container, VM, raw-storage or system
  configuration rights can gain root. Give those roles only to people you'd give the
  root password.
- **The local network is trusted for discovery.** SMB, NFS and WebDAV use passwords,
  but traffic on the LAN is only as private as your network unless you use SMB
  encryption or HTTPS through a reverse proxy.
- **Unraid's own shares are outside ZettNAS's control.** The ransomware guard can only
  freeze ZettNAS's own services there; use guard files for early warning and Unraid
  snapshots or backups for recovery.
- **Local AI models can still be misled.** Quoting and confirmation keep injected text
  from acting on its own, but a model can still give a wrong answer based on a planted
  document.

## Reviewing changes against this model

A change needs a second look when it adds an endpoint without a scope, reads a path
from a request without `resolve_within`, fetches a URL from user input, starts a
process or container, adds a Docker API call, or gives the AI a new tool. The test
suite checks several of these: every Docker call against the proxy allow-list, every
AI tool against the permission registry, and path traversal for the file APIs.

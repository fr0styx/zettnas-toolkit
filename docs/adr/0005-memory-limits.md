# ADR 0005: No default memory limit on the app

- **Status:** Accepted (PERF-31, chosen 28 Oct 2026)
- **Decides:** whether the ZettNAS container gets a memory limit by default

## Context

Indexing, thumbnails and AI work can make ZettNAS use a lot of memory for a while. A hard limit
protects the host, but a limit set too low gets the app killed in the middle of that work, and
the right number depends on the box and on what else runs on it.

## Decision

No default limit. Instead:

- `docs/INSTALLATION.md` recommends a limit per box size, for people who want one.
- An alert warns when the app's memory stays above `APP_MEMORY_WARN_MB` (1536 MB by default;
  virtual machines' QEMU processes don't count).

## Consequences

- Nothing breaks on upgrade, and a busy evening of indexing doesn't kill the app.
- A runaway is caught by the alert rather than by the kernel; the person decides what to do.

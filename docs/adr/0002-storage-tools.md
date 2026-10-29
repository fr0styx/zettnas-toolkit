# ADR 0002: How storage tools run

- **Status:** Accepted (decision D2 of the v2.0 plan, 27 Oct 2026)
- **Decides:** where `zfs`, `btrfs` and friends come from on each platform

## Context

Snapshots, scrubs and replication need the storage tools. On TrueNAS the middleware owns the
pools and expects to be asked; on generic Linux and on ZettOS nothing else owns them. Running
the host's own tools from the container (`nsenter` into the host namespaces) would match the
host exactly, but widens what the container may do on the host (against SEC-24).

## Decision

- **TrueNAS:** use its middleware API (`backend/services/truenas_api.py`); the host keeps
  owning snapshots and scrubs.
- **Generic Linux and ZettOS:** install the tools in the image, pinned to versions that match
  the host kernel's ZFS module where possible.
- No `nsenter` into the host.

## Consequences

- A host whose kernel ZFS module is far from the image's tools may refuse some commands.
- The container keeps its narrower host access.

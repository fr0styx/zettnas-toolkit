# ZettNAS Toolkit — Project Tracker: Containers & Virtual Machines Modernization

## Architecture Overview

ZettNAS Toolkit (**NAS WORKBENCH**) provides an enterprise-grade glassmorphic Web Desktop Operating System and hardware orchestration platform running across appliance hardware (ZettLab D4/D6/D8, Aoostar WTR Pro/R1) and generic homelab servers.

### Audited Subsystems & File Layout
- **Containers Subsystem**:
  - Frontend Control Plane:
    - `frontend/src/components/containers-manager.js` — Standalone Containers Management Desktop Window
    - `frontend/src/components/container-modal.js` — Tabbed Container Inspector & Compose Stack Editor
    - `frontend/src/components/docker-table.js` — Keyed DOM Container Reconciler Table
    - `frontend/src/components/management.js` — Mission Control Containers Widget
  - Backend API & Routers:
    - `backend/api/docker.py` — REST Endpoints for container lifecycle, stacks, logs, terminal, and recreation
  - Backend Hardware, Services & Telemetry:
    - `backend/hardware/docker_stats.py` — Docker socket communication, hardware badges, and metrics collection
    - `backend/services/compose_synthesizer.py` — Reverse-engineering of `docker-compose.yml` with secrets redaction
    - `backend/services/container_mutator.py` — Zero-downtime resource tuning, port binding updates, and atomic rollback
    - `backend/services/docker_stacks.py` — Compose stack parser and DAG topological sort (Kahn's algorithm)
    - `backend/services/docker_terminal.py` — WebSocket PTY interactive terminal streamer
    - `backend/services/docker_cleanup.py` — Docker prune and storage reclamation
    - `backend/services/stats_collector.py` — Real-time host telemetry collector & SSE broadcaster
- **Virtual Machines Subsystem**:
  - Frontend Control Plane:
    - `frontend/src/components/vm-manager.js` — Virtual Machines Manager Window & Web VNC/Serial Console
    - `frontend/src/components/vm-modal.js` — VM Configuration Modal & Elastic Headroom Calculator
    - `frontend/src/components/management.js` — Mission Control VM Fleet Widget
    - `frontend/src/vm-console-direct.css` — Dedicated Direct-Mode Console Window Styling
  - Backend API & Routers:
    - `backend/api/vms.py` — REST endpoints for VM lifecycle, QMP socket dispatch, ISO catalog, and USB passthrough
  - Backend Hardware & Services:
    - `backend/hardware/vms.py` — KVM capabilities detector and sysfs USB scanner
    - `backend/services/console_proxy.py` — WebSocket-to-TCP/UNIX socket streaming bridge (noVNC & Serial TTY)
    - `backend/services/backup_engine.py` — System Hyper-Backup archive generator

---

## Feature Inventory

| # | Feature | Scope / Subsystem | Status | Target Phase | Source / Specification |
|---|---------|-------------------|:------:|:------------:|------------------------|
| 1 | **R1 Containers Deep Audit** | Containers Subsystem | **COMPLETED** | M1 | `docs/CONTAINERS_AND_VMS_MODERNIZATION_BLUEPRINT.md` §1 |
| 2 | **R2 Virtual Machines Deep Audit** | Virtual Machines Subsystem | **COMPLETED** | M1 | `docs/CONTAINERS_AND_VMS_MODERNIZATION_BLUEPRINT.md` §2 |
| 3 | **R3 Competitive Benchmark Matrix** | 6-Platform Parity & Gaps | **COMPLETED** | M1 | `docs/CONTAINERS_AND_VMS_MODERNIZATION_BLUEPRINT.md` §3 |
| 4 | **R4 Performance & Reliability Blueprint** | DOM, SSE, VNC, Terminals, QMP | **COMPLETED** | M1 | `docs/CONTAINERS_AND_VMS_MODERNIZATION_BLUEPRINT.md` §4 |
| 5 | **Telemetry Clamp & Delta SSE Stream** | `docker_stats.py` & `stats_collector.py` | PLANNED | Phase 1 | Blueprint §1.4 & §4.2 |
| 6 | **Mission Control Schema Fix & Keyed VM Grid** | `management.js` & `vm-manager.js` | PLANNED | Phase 1 | Blueprint §2.3 & §5 |
| 7 | **Container Bulk Action Bar & Batch API** | `docker-table.js` & `api/docker.py` | PLANNED | Phase 2 | Blueprint §1.4 |
| 8 | **Real vTPM 2.0 via `swtpm` Daemon** | `backend/api/vms.py` | PLANNED | Phase 2 | Blueprint §2.3 |
| 9 | **Real IP Discovery (ARP / QGA)** | `backend/api/vms.py` | PLANNED | Phase 2 | Blueprint §2.3 |
| 10 | **Zero-Copy Binary xterm.js Terminal** | `container-modal.js` & `vm-manager.js` | PLANNED | Phase 3 | Blueprint §4.4 |
| 11 | **Server-Sent Events Chunked Log Streaming** | `api/docker.py` & `container-modal.js` | PLANNED | Phase 3 | Blueprint §1.4 |
| 12 | **Persistent Async QMP Engine** | `backend/services/vm_engine.py` | PLANNED | Phase 4 | Blueprint §2.3 & §4.5 |
| 13 | **QCOW2 Live Snapshots & Revert** | `backend/api/vms.py` & `vm-manager.js` | PLANNED | Phase 4 | Blueprint §2.3 |
| 14 | **Hyper-Backup VM Disk Integration** | `backend/services/backup_engine.py` | PLANNED | Phase 4 | Blueprint §2.3 |
| 15 | **DOM Virtualized Container Table** | `docker-table.js` & `containers-manager.js` | PLANNED | Phase 5 | Blueprint §4.1 |
| 16 | **Container Network Topology Visualizer** | `containers-manager.js` | PLANNED | Phase 5 | Blueprint §1.4 |
| 17 | **VFIO-PCI / Discrete GPU Passthrough** | `backend/api/vms.py` & `vm-manager.js` | PLANNED | Phase 5 | Blueprint §2.3 |

---

## Project Milestones

| Milestone | Objective | Scope & Key Deliverables | Status | Target Date |
| :---: | :--- | :--- | :---: | :---: |
| **M1** | **Technical Investigation & Audit** | Exhaustive code audit of Containers, VMs, Benchmarks, and Performance bottlenecks by 3 parallel Explorers. | **DONE** | 2026-10-19 |
| **M2** | **Blueprint Authoring & Synthesis** | Authoritative Master Modernization Blueprint (`docs/CONTAINERS_AND_VMS_MODERNIZATION_BLUEPRINT.md`) and updated `PROJECT.md`. | **COMPLETED** | 2026-10-19 |
| **M3** | **Verification & Quality Gate** | Remote host test execution (Ruff, Vitest, Pytest) and forensic integrity audit. | **IN_PROGRESS** | 2026-10-19 |
| **M4** | **Implementation Phase 1** | P0 Telemetry un-capping, SSE delta pipeline, Mission Control schema fix, and Keyed VM Grid. | PLANNED | Q4 2026 |
| **M5** | **Implementation Phase 2** | Bulk Actions, Real vTPM 2.0 `swtpm`, ARP IP discovery, and boot autostart. | PLANNED | Q4 2026 |
| **M6** | **Implementation Phase 3** | Zero-copy xterm.js WebGL terminal, live log streamer, and noVNC latency tuning. | PLANNED | Q1 2027 |
| **M7** | **Implementation Phase 4** | Persistent Async QMP Engine, QCOW2 snapshots, and Hyper-Backup integration. | PLANNED | Q1 2027 |
| **M8** | **Implementation Phase 5** | Container Network Visualizer, DOM virtualization, and VFIO-PCI GPU Passthrough. | PLANNED | Q2 2027 |

---

## Compliance with AGENTS.md Invariants

1. **§1.1 Universal Hardware (HAL & PAL)**: Storage and virtualization layers adapt dynamically between Unraid array shares, TrueNAS ZFS pools, and generic Linux Btrfs subvolumes without host OS assumptions.
2. **§1.2 Spindown-Safe Storage Invariant**: Storage metrics queries preserve sleeping HDD states using `smartctl -n standby`. ISO and virtual disk queries use cached WAL metadata.
3. **§1.3 Keyed DOM Reconciliation**: All grid and table updates strictly use keyed element reconciliation (`reconcileKeyedTable`) with mirrored dataset attributes, prohibiting unkeyed `innerHTML` DOM wipes.
4. **§1.4 Cryptographic Security & Secrets Redaction**: Argon2id password hashing, token masking (`zat_****`), and path confinement (`resolve_within`) on all VirtIO-FS host shares.
5. **§1.5 Strict Theme & Style Isolation**: Component styles are scoped under dedicated classes (`.cw-*`, `.vm-*`, `#vm-console-window`), protecting physical LCD `#screen` boundaries.
6. **§1.6 Host Power & Test Execution Isolation**: Test suites strictly mock power endpoints and never trigger real host reboots or shutdowns.

---

## Remote Verification Gates

All changes must pass remote verification on `root@10.40.30.249`:
- **Python Lint & Format**: `ssh root@10.40.30.249 "cd /mnt/user/appdata/zettnas-toolkit && npm run lint"`
- **Frontend Test Suite**: `ssh root@10.40.30.249 "cd /mnt/user/appdata/zettnas-toolkit && node ./node_modules/vitest/dist/cli.js run frontend/src/__tests__/vm_manager_and_budgeting.test.js"`
- **Backend Test Suite**: `ssh root@10.40.30.249 "docker exec -i zettnas-toolkit python3 -m pytest -q /app/tests/test_vms_api.py /app/tests/test_docker_updates.py"`

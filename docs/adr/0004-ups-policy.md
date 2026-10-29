# ADR 0004: What ZettNAS does when the power fails

- **Status:** Accepted (decision D10 of the v2.0 plan, 27 Oct 2026)
- **Decides:** who shuts down the host on battery, and what ZettNAS stops

## Context

ZettNAS reads the UPS through NUT. On Unraid and TrueNAS the host has its own shutdown logic and
its own idea of which disks and services to stop first; two components both shutting the host
down, in different orders, risk an unclean array.

## Decision

- On Unraid and TrueNAS, ZettNAS hands the shutdown to the host.
- ZettNAS stops only the stacks it manages (labelled `com.zettnas.managed`).
- ZettNAS never cuts outlet power without a verified host shutdown path.

## Consequences

- Containers the host or another tool manages are stopped by the host, in its own order.

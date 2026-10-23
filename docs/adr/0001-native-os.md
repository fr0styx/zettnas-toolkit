# ADR 0001: ZettNAS as an installable operating system

- **Status:** Proposed
- **Date:** 2026-10-23
- **Decides:** base image, update method, ZFS packaging, disk-ownership rules

## Context

Today ZettNAS runs as a container on a host OS that someone else maintains. That host
provides the kernel, ZFS, Docker, boot and updates. People who want a NAS without a host OS
to look after need ZettNAS to install directly on the hardware, like TrueNAS, Unraid or
OpenMediaVault.

An appliance OS has to:

1. update safely: a failed update must never leave the box unbootable;
2. never put data disks at risk by accident;
3. keep the current container product working, since that is how most people run ZettNAS;
4. be something a small team can maintain.

## Decision (proposed)

### Base: Debian stable, built as an image

- Debian stable (13 "trixie"), built reproducibly with `mkosi` from a pinned package
  snapshot (snapshot.debian.org) so every image can be rebuilt bit for bit.
- x86_64 with UEFI first. ARM64 comes later, once a reference board is chosen.
- The root filesystem is read-only (EROFS) and checked with dm-verity. Settings and app
  state live in a separate writable partition.
- The ZettNAS backend runs on the host as a systemd service. User apps keep running in
  Docker, so the existing app catalog and compose stacks work unchanged.

Why Debian: it has the longest support window of the community distros, it is the base the
current container image already uses, and it is the base TrueNAS SCALE uses. Ubuntu Core and
Fedora CoreOS were considered. Ubuntu Core ties updates to the Snap Store. CoreOS's ZFS
story depends on out-of-tree modules for every kernel.

### Updates: A/B slots with RAUC

- Two root slots (A and B). An update is written to the slot that is not running, then the
  next boot uses it.
- Boot counting: if the new slot fails its health check (backend answering, pools imported,
  web UI reachable) three times, the bootloader goes back to the previous slot on its own.
- Bundles are signed in CI, and the device checks the signature before it installs anything.
  This also closes the gap in the container updater, which today checks only the registry.
- Updates use the same channels as today: Stable after the soak, Beta right away.

| Option | Why not chosen (for now) |
|---|---|
| Mender | Built around a management server; the full feature set is commercial. |
| systemd-sysupdate | Simple and a good fit with dm-verity, but rollback and bundle tooling are less mature. Revisit in a year. |
| OSTree | Works, but adds a second layout model next to Docker's, and is weaker on Debian. |

### ZFS: OpenZFS built into the image

- OpenZFS is built with DKMS when the image is made, so the kernel and the ZFS module always
  ship and update together. Nothing compiles on the device.
- A ZFS release is always tested against its kernel in CI before an image is published.
  A kernel that OpenZFS does not support yet blocks the release rather than shipping without
  ZFS.
- Licensing: shipping a CDDL module next to a GPL kernel needs a legal review before the
  first public image. The plan follows the approach other Debian-based NAS systems use, but
  the review is a release gate, not an assumption.

### Disk-ownership rules

These are rules the installer and the storage code must both follow:

1. **The OS disk holds only the OS.** It is never offered as a pool member, and pool disks
   are never offered as an install target.
2. **The installer writes only to the disk the user picks**, confirmed by model and serial
   number, not by device name.
3. **Disks are identified by `/dev/disk/by-id`**, and pools are imported by GUID, so a change
   in device order never points ZettNAS at the wrong disk.
4. **A disk with anything on it is not touched without a typed confirmation.** That includes
   partitions, a pool label, a filesystem or RAID metadata. The confirmation screen says what
   was found.
5. **Updates never write outside the OS disk.** The update tool has no access to pool disks.
6. **Existing pools are imported read-only first** on a fresh install, and the user chooses
   whether to import them for writing.

### What stays the same

- The container image stays a first-class product with the same features and release
  channels.
- The backend talks to the OS through the existing platform layer (`get_storage_platform`),
  so a native platform is added next to the current ones, not instead of them.

## Consequences

- New CI work: image build, a ZFS and kernel test matrix, bundle signing, and a QEMU boot
  test that covers update, failed update and rollback.
- New support surface: hardware compatibility, boot problems, installer bugs. A published
  list of tested hardware is needed before the first image.
- The release process gains a second artifact, the OS image, which shares version numbers
  with the container image.

## Open questions

1. Secure Boot: sign with our own key (enrolled by the user) or go through shim? This
   decides how much of the boot chain is checked.
2. Backend on the host versus in a privileged container on the appliance. The proposal says
   host; a container would keep one runtime path but makes boot health checks harder.
3. Minimum hardware: RAM floor with ZFS and the local AI features enabled.
4. Whether ARM64 is in the first public release or follows later.

## Next steps

1. Build a QEMU-only proof of concept: mkosi image, RAUC A/B update and an automatic
   rollback after a forced failed boot.
2. Write the installer's disk-selection screen against the rules above, with tests that use
   loop devices.
3. Get the ZFS licensing review done.
4. Come back to this ADR with results from the proof of concept and mark it Accepted or
   changed.

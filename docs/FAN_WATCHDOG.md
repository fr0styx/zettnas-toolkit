# Fan watchdog

ZettNAS drives the chassis fans itself. If the app stops cleanly it hands them back (firmware
control where the hardware has it, a safe fixed speed where it doesn't). If it is killed outright
(out of memory, `docker kill`, a crash) it can't, and the fans would stay at their last speed.

The fan watchdog covers that. It is a second, small container from the same image that does one
thing: it watches a heartbeat the app writes every few seconds to the host's `/dev/shm` (memory,
so it never wakes a disk). When the beats stop for 30 seconds without a clean release, it puts the
fans in the same safe state the app uses on shutdown. It acts once per outage and starts watching
again when the app is back. On a machine without fan control it does nothing.

## Docker Compose

It is the `fan-watchdog` service in `docker-compose.yml`; `docker compose up -d` starts it next to
the app.

## Unraid

Add a second container from the template `unraid/zettnas-fan-watchdog.xml` (Docker → Add Container
→ the template), or by hand:

```bash
docker run -d --name zettnas-fan-watchdog --restart unless-stopped --no-healthcheck --network none \
  --cap-add SYS_RAWIO -v /sys:/host/sys:rw -v /dev:/host/dev:rw --device-cgroup-rule='c 1:1 rwm' \
  -e HOST_SYS=/host/sys -e HOST_DEV=/host/dev -e DATA_DIR=/tmp/zettnas-watchdog \
  --memory 128m ghcr.io/fr0styx/zettnas-toolkit:latest python3 -m backend.fan_watchdog
```

After a reboot or an array stop:

- **From the template:** Unraid stops template containers itself and starts again only those with
  **Autostart** on. Turn it on for the watchdog on the Docker page.
- **By hand:** `--restart unless-stopped` brings it back. A watchdog created from an image older
  than this fix carries Unraid's "managed" label, so Unraid stops it on purpose and it stays down:
  remove it and run the command above again. `docker inspect zettnas-fan-watchdog --format
  '{{index .Config.Labels "net.unraid.docker.managed"}}'` prints nothing when it is fine.

## Checking it

```bash
docker exec zettnas-fan-watchdog python3 -m backend.fan_watchdog --check
```

prints the fan controller it can reach and how old the app's last heartbeat is.

Settings (environment): `FAN_WATCHDOG_STALE_SECS` (30), `FAN_WATCHDOG_CHECK_SECS` (5),
`FAN_WATCHDOG_DRY_RUN=1` to log instead of acting, `FAN_WATCHDOG_HEARTBEAT` to move the heartbeat.

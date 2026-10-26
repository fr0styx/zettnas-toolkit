# Anonymous health report

An opt-in, once-a-week report that tells the project which versions, platforms and features
are in use, so fixes and testing go where people are. **It is off by default.** Turn it on in
Mission Control, under Software Updates: **Help improve ZettNAS**. The card shows the exact
report before you do.

## What is sent

One small JSON object a week, for example:

```json
{
  "schema": 1,
  "id": "3f9c0d2a6b1e4f7a8c5d9e0b1a2c3d4e",
  "version": "1.10.3",
  "platform": "unraid",
  "arch": "x86_64",
  "variant": "full",
  "drives": "5-8",
  "features": ["containers", "ups"]
}
```

| Field | Meaning |
|---|---|
| `id` | random, made when you turn the report on; not derived from the machine; forgotten when you turn it off |
| `version` | the ZettNAS version |
| `platform` | the storage platform: `unraid`, `truenas`, `proxmox`, `generic_linux`, … |
| `arch` | the processor type, e.g. `x86_64`, `aarch64` |
| `variant` | `full` or `core` image |
| `drives` | a range: `0`, `1-2`, `3-4`, `5-8`, `9-16`, `17+` |
| `features` | from a fixed list: `containers`, `backups`, `ups`, `lcd`, `leds`, `ai`, `vms`, `sso` |

Never sent: hostname, IP addresses (the receiver does not store them), user or share names,
file names or paths, disk models or serial numbers, logs, settings.

The receiver keeps one row per install per week, refuses any other field, deletes rows after
26 weeks, and publishes only totals for the last complete week at `/v1/stats`.

## The receiver (for maintainers)

`tools/health-signal-worker/` is a Cloudflare Worker with a D1 database. Cloudflare's free
plan covers it (100,000 requests and 100,000 database row writes a day; one report per
install per week). Deploying it needs a Cloudflare account:

```bash
cd tools/health-signal-worker
npx wrangler login
npx wrangler d1 create zettnas-health          # copy the database_id into wrangler.toml
npx wrangler d1 execute zettnas-health --remote --file schema.sql
npx wrangler deploy                            # prints the https://zettnas-health.<you>.workers.dev address
```

Then set `DEFAULT_ENDPOINT` in `backend/services/health_signal.py` to
`https://zettnas-health.<you>.workers.dev/v1/report` and release. Until then the switch says
it is not available. An install can also point at its own receiver with `HEALTH_SIGNAL_URL`.

Worker logs are off in `wrangler.toml`, so request metadata is not kept either.

# Compatibility with each Unraid and TrueNAS release

Kiboto reads Unraid's and TrueNAS's own state: on Unraid the emhttp files `var.ini`, `disks.ini` and
`shares.ini`; on TrueNAS the REST answers for pools, datasets, SMB and NFS shares, and snapshots. A
release that changes those can break Kiboto quietly, so each release line has a **recording** of what
a real box answered, and the tests run Kiboto's parsers over every recording on every commit.

## Recordings

They live in `tests/compat/<platform>/<version>/` and are made with:

```bash
python scripts/compat_capture.py unraid            # on the Unraid box, or with --emhttp <folder>
TRUENAS_API_KEY=... python scripts/compat_capture.py truenas --url https://truenas.local
```

Only the keys and fields Kiboto reads are kept, and nothing that says whose box it was: the host name
becomes `tower`, serial numbers stable fakes (`DISK-1A2B3C4D`), shares, pools and datasets `share_1`,
`pool_1`, `pool_1/ds_1`, comments go, and sizes, usage, temperatures and counters are replaced with
neutral numbers that keep their relations. Read a recording before committing it.

`tests/test_b9_compat_recordings.py` runs the Unraid parsers (array state, disk roles, pools, shares)
over each Unraid recording; `tests/test_b9_compat_capture.py` replays each TrueNAS recording through
Kiboto's TrueNAS client.

## New releases

Each night, **Nightly compatibility recordings** (`scripts/compat_trains.py`) reads Unraid's release
list and TrueNAS's release tags and lists the two newest lines of each with or without a recording.
It fails when Unraid's newest line has none. TrueNAS lines without one are listed: recording one needs
a TrueNAS box, and a recording from a contributor's box is welcome.

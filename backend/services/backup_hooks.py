"""Consistent app data in backups (REL-20).

A backup copies files as they are. A database that writes while its files are copied can leave a
copy that won't start. So before a backup reads its folders, every running database container
whose data lies in them writes a dump next to its own files (.zettnas-dump.*), finished and
renamed into place before the copy starts: the backup then always holds one consistent copy of
each database, besides the live files. PostgreSQL (pg_dumpall), MariaDB and MySQL
(--single-transaction), Redis and Valkey (SAVE) and MongoDB (mongodump) are recognised by their
image. A dump that fails is reported and the backup goes on.
"""

import json
import os
import re
from typing import Any

from backend.config import logger

DUMP_TIMEOUT = 3600

_PART = '> "$D/{name}.part" && mv "$D/{name}.part" "$D/{name}"'
DUMPS: list[tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"postgres|postgis|timescale|pgvecto", re.I),
        "postgres",
        'pg_dumpall -U "${POSTGRES_USER:-postgres}" ' + _PART.format(name=".zettnas-dump.sql"),
    ),
    (
        re.compile(r"mariadb|mysql|percona", re.I),
        "mysql",
        'B=$(command -v mariadb-dump || command -v mysqldump) && P="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}" '
        '&& "$B" --all-databases --single-transaction --routines -uroot ${P:+-p"$P"} '
        + _PART.format(name=".zettnas-dump.sql"),
    ),
    (re.compile(r"redis|valkey|keydb", re.I), "redis", "redis-cli SAVE >/dev/null"),
    (
        re.compile(r"mongo", re.I),
        "mongo",
        'mongodump --quiet --archive="$D/.zettnas-dump.archive.part" '
        '&& mv "$D/.zettnas-dump.archive.part" "$D/.zettnas-dump.archive"',
    ),
]


class HookError(RuntimeError):
    pass


def _inside(path: str, roots: list[str]) -> bool:
    p = os.path.realpath(path)
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots)


def targets(paths: list[str]) -> list[dict[str, Any]]:
    """Running database containers with data inside `paths`: where each writes its dump."""
    from backend.services import docker_client

    roots = [os.path.realpath(p) for p in paths if p]
    try:
        status, containers = docker_client.request("GET", "/containers/json")
    except docker_client.DockerUnavailable:
        return []
    if status != 200 or not isinstance(containers, list):
        return []
    found = []
    for c in containers:
        image = str(c.get("Image") or "")
        kind = next(((k, cmd) for pattern, k, cmd in DUMPS if pattern.search(image)), None)
        if not kind:
            continue
        mount = next(
            (
                m
                for m in c.get("Mounts") or []
                if m.get("Type") == "bind" and _inside(str(m.get("Source") or ""), roots)
            ),
            None,
        )
        if mount:
            name = str((c.get("Names") or ["/?"])[0]).lstrip("/")
            found.append(
                {"id": c.get("Id"), "name": name, "kind": kind[0], "cmd": kind[1], "dest": mount["Destination"]}
            )
    return found


def _demux(raw: bytes) -> str:
    """Docker's multiplexed exec output as text (8-byte frame headers removed)."""
    out, i = [], 0
    while i + 8 <= len(raw) and raw[i] in (0, 1, 2):
        size = int.from_bytes(raw[i + 4 : i + 8], "big")
        out.append(raw[i + 8 : i + 8 + size])
        i += 8 + size
    text = b"".join(out) if out else raw
    return text.decode("utf-8", errors="replace").strip()


def _exec(container_id: str, cmd: str, dest: str, timeout: int = DUMP_TIMEOUT) -> None:
    from backend.services import docker_client

    body = {"AttachStdout": True, "AttachStderr": True, "Tty": False, "Cmd": ["sh", "-c", cmd], "Env": [f"D={dest}"]}
    status, created = docker_client.request("POST", f"/containers/{container_id}/exec", body, timeout=15)
    if status not in (200, 201) or not isinstance(created, dict) or not created.get("Id"):
        raise HookError(f"could not start the dump ({status})")
    start = json.dumps({"Detach": False, "Tty": False}).encode()
    _status, raw = docker_client.raw_request("POST", f"/exec/{created['Id']}/start", start, timeout=timeout)
    _status, info = docker_client.request("GET", f"/exec/{created['Id']}/json")
    code = info.get("ExitCode") if isinstance(info, dict) else None
    if code != 0:
        lines = _demux(raw).splitlines()
        raise HookError((lines[-1] if lines else f"exit {code}")[:300])


def run_dumps(paths: list[str]) -> list[dict[str, Any]]:
    """Dumps every database whose data is in `paths`, before a backup reads them."""
    results = []
    for t in targets(paths):
        try:
            _exec(str(t["id"]), t["cmd"], t["dest"])
            results.append({"name": t["name"], "kind": t["kind"], "ok": True})
            logger.info(f"[Backup] {t['name']}: {t['kind']} dump written before the backup")
        except Exception as e:
            results.append({"name": t["name"], "kind": t["kind"], "ok": False, "error": str(e)[:300]})
            logger.warning(f"[Backup] {t['name']}: the {t['kind']} dump failed, its live files are copied: {e}")
    return results

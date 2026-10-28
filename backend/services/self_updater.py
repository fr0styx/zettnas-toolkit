"""
ZettNAS Toolkit - Self-Update Orchestrator Subsystem
Enables automated, zero-terminal in-app system updates for both
Stable (GitHub Releases) and Edge / Rolling (Latest main commits) channels.
Safely clones and mutates container configurations across Docker Engine socket.
"""

import argparse
import json
import logging
import os
import re
import socket
import sys
import time
from typing import Any, Optional

logger = logging.getLogger("zettnas.self_updater")


# The updater only creates containers it fully controls (its helper and the app
# itself), so its creates carry the Docker proxy's elevated header (SEC-09).
ELEVATED = {"X-ZettNAS-Elevated": "1"}


def _docker_request(method: str, path: str, body: dict | None = None, timeout: float = 30.0) -> tuple[int, Any]:
    """Helper for synchronous Docker Unix socket communication."""
    from backend.services.container_mutator import _docker_request as raw_req

    headers = ELEVATED if path.startswith("/containers/create") else None
    return raw_req(method, path, body=body, timeout=timeout, headers=headers)


HELPER_DATA_DIR = "/zettnas-data"
APP_DATA_DIR = "/app/data"


def _data_mount_source(container_name: str) -> str | None:
    """Host path mounted at /app/data in the target container, if any."""
    st, data = _docker_request("GET", f"/containers/{container_name}/json")
    if st != 200 or not isinstance(data, dict):
        return None
    for m in data.get("Mounts") or []:
        if m.get("Destination") == APP_DATA_DIR and m.get("Source"):
            return str(m["Source"])
    return None


def spawn_self_updater(
    target_image: str = "ghcr.io/fr0styx/zettnas-toolkit:latest",
    container_name: str = "zettnas-toolkit",
    delay_seconds: float = 2.5,
    restore_snapshot_id: str | None = None,
) -> bool:
    """
    Spawns an ephemeral detached helper container from target_image that will
    gracefully recreate the main container while preserving all mounts, networks,
    ports, devices, and runtime configurations.
    """
    try:
        # 1. Clean up any stale updater container
        _docker_request("POST", "/containers/zettnas-self-updater/stop?t=2")
        _docker_request("DELETE", "/containers/zettnas-self-updater?force=true")

        # 2. Define ephemeral updater command
        cmd = [
            "python3",
            "-m",
            "backend.services.self_updater",
            "--apply",
            "--target",
            container_name,
            "--image",
            target_image,
            "--delay",
            str(delay_seconds),
        ]

        binds = ["/var/run/docker.sock:/var/run/docker.sock"]
        data_src = _data_mount_source(container_name)
        if data_src:
            # The helper snapshots the data folder before the update and restores it on rollback (OPS-03).
            binds.append(f"{data_src}:{HELPER_DATA_DIR}")
            cmd.extend(["--data-dir", HELPER_DATA_DIR])
            if restore_snapshot_id:
                cmd.extend(
                    ["--restore-from", os.path.join(HELPER_DATA_DIR, "backups", "pre-update", restore_snapshot_id)]
                )
        elif restore_snapshot_id:
            logger.error("[SelfUpdater] Cannot revert: the data folder mount was not found.")
            return False

        create_body = {
            "Image": target_image,
            "Cmd": cmd,
            "HostConfig": {
                "Binds": binds,
                "AutoRemove": True,
            },
        }

        st, res = _docker_request("POST", "/containers/create?name=zettnas-self-updater", body=create_body)
        if st in (200, 201) and isinstance(res, dict):
            cid = res.get("Id")
            if cid:
                st_start, _ = _docker_request("POST", f"/containers/{cid}/start")
                if st_start in (200, 204):
                    logger.info(f"[SelfUpdater] Successfully launched ephemeral updater container ({cid[:12]})")
                    return True
        logger.warning(f"[SelfUpdater] Could not spawn ephemeral updater container: status={st}, res={res}")
        return False
    except Exception as exc:
        logger.error(f"[SelfUpdater] Error spawning updater container: {exc}")
        return False


def _rollback_container(
    target: str,
    rollback_name: str,
    failed_id: str | None = None,
    snapshot: str | None = None,
    data_dir: str | None = None,
):
    """Removes a failed new container (if any), restores the data snapshot and the previous container."""
    if failed_id:
        _docker_request("POST", f"/containers/{failed_id}/stop?t=5")
        _docker_request("DELETE", f"/containers/{failed_id}?force=true")
    if snapshot and data_dir:
        try:
            from backend.services.data_snapshot import restore_snapshot

            restore_snapshot(snapshot, data_dir)
        except Exception as e:
            logger.critical(f"[SelfUpdater Helper] Could not restore data snapshot {snapshot}: {e}")
    logger.warning(f"[SelfUpdater Helper] Restoring '{rollback_name}' back to '{target}'...")
    _docker_request("POST", f"/containers/{rollback_name}/rename?name={target}")
    st_start, _ = _docker_request("POST", f"/containers/{target}/start")
    if st_start in (200, 204):
        logger.info(
            f"[SelfUpdater Helper] Rollback successful. Container '{target}' restored to previous working version."
        )
    else:
        logger.critical(
            f"[SelfUpdater Helper] CRITICAL: Failed to restart rolled-back container '{target}' (status={st_start})!"
        )


# Container settings that normally come from the image. They are carried over only
# when the user overrode them (they differ from the old image), so the new image's
# own command, healthcheck, workdir etc. take effect (OPS-01).
_IMAGE_DEFAULT_KEYS = ("Cmd", "Entrypoint", "Healthcheck", "WorkingDir", "User", "ExposedPorts", "StopSignal", "Shell")
HEALTH_TIMEOUT_SECS = 300
STABLE_RUN_SECS = 20
APP_OK_DWELL_SECS = 60  # the new version must report "ok" this long before the old one is removed (OPS-6)
RESULT_FILE = "update_result.json"  # in the data folder: what the last update did (OPS-7)

_HEALTH_PROBE = (
    "import urllib.request, urllib.error, os, sys\n"
    "u = 'http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8082')\n"
    "try:\n    body = urllib.request.urlopen(u, timeout=4).read()\n"
    "except urllib.error.HTTPError as e:\n    body = e.read()\n"
    "except Exception:\n    body = b''\n"
    "sys.stdout.write(body.decode('utf-8', 'replace'))\n"
)


def _app_status(cid: str) -> str | None:
    """The app's own health status inside the container ("ok", "starting", "degraded", or "" when
    it doesn't answer yet); None when it can't be asked (no exec support)."""
    st, ex = _docker_request(
        "POST",
        f"/containers/{cid}/exec",
        body={"Cmd": ["python3", "-c", _HEALTH_PROBE], "AttachStdout": True, "AttachStderr": False, "Tty": True},
    )
    if st not in (200, 201) or not isinstance(ex, dict) or not ex.get("Id"):
        return None
    st, out = _docker_request("POST", f"/exec/{ex['Id']}/start", body={"Detach": False, "Tty": True}, timeout=20)
    if st != 200 or not isinstance(out, dict):
        return ""
    return str(out.get("status") or "")


ROLLBACK_REPO = "zettnas-toolkit-rollback"


def _container_build(inspect_data: dict[str, Any], version: str) -> str:
    """The build a container runs: version plus short commit from its BUILD_COMMIT."""
    env = (inspect_data.get("Config") or {}).get("Env") or []
    commit = next((e.split("=", 1)[1] for e in env if e.startswith("BUILD_COMMIT=")), "")[:7]
    base = version or "unknown"
    return f"{base}+{commit}" if commit else base


def _tag_name(build: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", build)[:120] or "previous"


def _protect_rollback_image(image_id: str, build: str, data_dir: str) -> None:
    """Tags the previous image so `docker image prune` can't remove a rollback target, and drops
    the tags whose snapshot is gone (OPS-5)."""
    from backend.services.data_snapshot import list_snapshots

    tag = _tag_name(build)
    _docker_request("POST", f"/images/{image_id}/tag?repo={ROLLBACK_REPO}&tag={tag}")
    keep = {_tag_name(str(s.get("from_build"))) for s in list_snapshots(data_dir) if s.get("from_build")} | {tag}
    st, images = _docker_request("GET", f"/images/json?filters={json.dumps({'reference': [ROLLBACK_REPO]})}")
    for img in images if st == 200 and isinstance(images, list) else []:
        for ref in img.get("RepoTags") or []:
            if ref.startswith(ROLLBACK_REPO + ":") and ref.split(":", 1)[1] not in keep:
                _docker_request("DELETE", f"/images/{ref}?noprune=1")


def write_update_result(data_dir: str | None, result: str, reason: str = "", **extra: Any) -> None:
    """Records how the update ended, for the app to report after it starts (OPS-7)."""
    if not data_dir:
        return
    try:
        from backend.fsutil import atomic_write_json

        atomic_write_json(
            os.path.join(data_dir, RESULT_FILE),
            {"result": result, "reason": reason, "at": time.time(), "reported": False, **extra},
        )
    except Exception as e:
        logger.error(f"[SelfUpdater Helper] Could not record the update result: {e}")


def _image_config(image_ref: str) -> dict[str, Any]:
    st, data = _docker_request("GET", f"/images/{image_ref}/json")
    if st == 200 and isinstance(data, dict):
        return dict(data.get("Config") or {})
    return {}


def _endpoint_settings(net: dict[str, Any], container_id: str) -> dict[str, Any]:
    ep: dict[str, Any] = {}
    aliases = [a for a in (net.get("Aliases") or []) if a and not container_id.startswith(a)]
    if aliases:
        ep["Aliases"] = aliases
    if net.get("IPAMConfig"):
        ep["IPAMConfig"] = net["IPAMConfig"]
    if net.get("Links"):
        ep["Links"] = net["Links"]
    if net.get("DriverOpts"):
        ep["DriverOpts"] = net["DriverOpts"]
    if net.get("MacAddress") and net.get("IPAMConfig"):
        ep["MacAddress"] = net["MacAddress"]
    return ep


# SEC-24: an update narrows the device rules of older installs to what the app opens
_DROP_RULES = {"c 1:* rwm"}  # /dev/port, /dev/kmem, /dev/kmsg: never used
_MISC_RULES = ["c 10:232 rwm", "c 10:238 rwm", "c 10:200 rwm", "c 10:196 rwm", "c 10:229 rwm"]


def narrow_device_rules(rules: list[str] | None) -> list[str] | None:
    """The container's device cgroup rules without the ones nothing uses (SEC-24)."""
    if not rules:
        return rules
    out: list[str] = []
    for r in rules:
        r = str(r).strip()
        if r in _DROP_RULES:
            continue
        for x in _MISC_RULES if r == "c 10:* rwm" else [r]:
            if x not in out:
                out.append(x)
    return out


def build_recreate_plan(
    inspect_data: dict[str, Any], old_image_cfg: dict[str, Any], image: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Returns (create body, extra networks to connect after create)."""
    config = dict(inspect_data.get("Config") or {})
    host_config = dict(inspect_data.get("HostConfig") or {})
    container_id = str(inspect_data.get("Id") or "")

    body: dict[str, Any] = {k: v for k, v in config.items() if k != "Image"}
    # Docker's default hostname is the container id; a new container gets its own.
    if body.get("Hostname") and container_id.startswith(str(body["Hostname"])):
        body.pop("Hostname")
    for key in _IMAGE_DEFAULT_KEYS:
        if key in body and body[key] == old_image_cfg.get(key):
            body.pop(key)

    # Only the variables the user added or changed; the new image supplies its own.
    image_env = set(old_image_cfg.get("Env") or [])
    body["Env"] = [e for e in (config.get("Env") or []) if e not in image_env]

    image_labels = old_image_cfg.get("Labels") or {}
    labels = {
        k: v
        for k, v in (config.get("Labels") or {}).items()
        # Unraid's labels belong to the container (its template made them): kept even when the old
        # image had the same one, since newer images don't carry net.unraid.docker.managed
        if (image_labels.get(k) != v or k.startswith("net.unraid.docker."))
        and not k.startswith("org.opencontainers.image.")
        and k not in ("com.docker.compose.image", "com.docker.compose.config-hash")
    }
    body["Labels"] = labels
    body["Image"] = image
    if host_config.get("DeviceCgroupRules"):
        host_config["DeviceCgroupRules"] = narrow_device_rules(host_config["DeviceCgroupRules"])
    body["HostConfig"] = host_config

    networks = dict((inspect_data.get("NetworkSettings") or {}).get("Networks") or {})
    mode = str(host_config.get("NetworkMode") or "")
    extra: dict[str, dict[str, Any]] = {}
    if networks and not mode.startswith("container:") and mode not in ("host", "none"):
        primary = mode if mode in networks else next(iter(networks))
        body["NetworkingConfig"] = {"EndpointsConfig": {primary: _endpoint_settings(networks[primary], container_id)}}
        for name, net in networks.items():
            if name != primary:
                extra[name] = _endpoint_settings(net, container_id)
    return body, extra


def _wait_until_healthy(cid: str) -> tuple[bool, str]:
    """Healthy once the app itself reports "ok" and keeps doing so for APP_OK_DWELL_SECS, without
    the container exiting (OPS-6). "starting" doesn't count. If the app can't be asked at all
    (no exec support), the image healthcheck or a steady run stands in, for the same dwell."""
    deadline = time.time() + HEALTH_TIMEOUT_SECS
    good_since: float | None = None
    while time.time() < deadline:
        st, data = _docker_request("GET", f"/containers/{cid}/json")
        state = (data.get("State") or {}) if st == 200 and isinstance(data, dict) else {}
        if not state.get("Running"):
            if state.get("Status") in ("exited", "dead"):
                return False, f"container exited (code {state.get('ExitCode')})"
            good_since = None
        else:
            health = (state.get("Health") or {}).get("Status")
            if health == "unhealthy":
                return False, "healthcheck reported unhealthy"
            app = _app_status(cid)
            if app == "degraded":
                return False, "the app reported a failed part (degraded)"
            if app is None:  # can't ask the app: the image healthcheck, or a steady run, decides
                good = health == "healthy" or not health
            else:
                good = app == "ok"
            if good:
                good_since = good_since or time.time()
                if time.time() - good_since >= APP_OK_DWELL_SECS:
                    return True, f"ok for {APP_OK_DWELL_SECS} s" if app is not None else "running"
            else:
                good_since = None
        time.sleep(3)
    return False, "timed out waiting for the app to report ok"


def apply_update_from_helper(
    target: str,
    image: str,
    delay: float = 2.5,
    data_dir: str | None = None,
    restore_from: str | None = None,
):
    """
    Executed inside the ephemeral helper container (started from the new image)
    to recreate the target container. The old container is kept, renamed, until
    the new one is healthy, and restored if anything fails (OPS-01/02/04).
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info(f"[SelfUpdater Helper] Initialized. Waiting {delay}s for caller HTTP completion...")
    time.sleep(max(1.0, delay))

    st, inspect_data = _docker_request("GET", f"/containers/{target}/json")
    if st != 200 or not isinstance(inspect_data, dict):
        logger.error(f"[SelfUpdater Helper] Target container '{target}' not found (status={st})")
        sys.exit(1)

    old_image_ref = str(inspect_data.get("Image") or (inspect_data.get("Config") or {}).get("Image") or "")
    old_image_cfg = _image_config(old_image_ref) if old_image_ref else {}
    create_body, extra_networks = build_recreate_plan(inspect_data, old_image_cfg, image)

    # Clean up any leftover rollback container from a previous run
    rollback_name = f"{target}-rollback"
    _docker_request("POST", f"/containers/{rollback_name}/stop?t=2")
    _docker_request("DELETE", f"/containers/{rollback_name}?force=true")

    logger.info(f"[SelfUpdater Helper] Gracefully stopping container '{target}'...")
    _docker_request("POST", f"/containers/{target}/stop?t=15")

    snapshot = None
    if data_dir and os.path.isdir(data_dir):
        try:
            from backend.services.data_snapshot import current_build, is_stable_tag, take_snapshot

            from_version = str((old_image_cfg.get("Labels") or {}).get("org.opencontainers.image.version") or "")
            from_tag = str((inspect_data.get("Config") or {}).get("Image") or "")
            from_build = _container_build(inspect_data, from_version)
            snapshot = take_snapshot(
                data_dir,
                label=f"from-{from_build}",
                extra={
                    "from_version": from_version,
                    "from_build": from_build,
                    "to_build": current_build(),
                    "from_image": old_image_ref,
                    "from_tag": from_tag,
                    "stable": is_stable_tag(from_tag),
                    "to_image": image,
                    "kind": "revert" if restore_from else "update",
                },
                protect=restore_from,
            )
        except Exception as e:
            logger.error(f"[SelfUpdater Helper] Could not snapshot the data folder ({e}); not updating.")
            _docker_request("POST", f"/containers/{target}/start")
            write_update_result(data_dir, "not_applied", f"could not snapshot the data folder: {e}", to_image=image)
            sys.exit(1)
    elif restore_from:
        logger.error("[SelfUpdater Helper] A revert needs the data folder; not reverting.")
        _docker_request("POST", f"/containers/{target}/start")
        sys.exit(1)

    if restore_from:
        # Revert: the previous version gets back the data exactly as it left it.
        try:
            from backend.services.data_snapshot import restore_snapshot

            restore_snapshot(restore_from, data_dir or "")
        except Exception as e:
            logger.error(f"[SelfUpdater Helper] Could not restore {restore_from} ({e}); not reverting.")
            from backend.services.data_snapshot import restore_snapshot as _undo

            if snapshot and data_dir:
                _undo(snapshot, data_dir)
            _docker_request("POST", f"/containers/{target}/start")
            write_update_result(data_dir, "not_applied", f"could not restore the earlier data: {e}", to_image=image)
            sys.exit(1)

    logger.info(f"[SelfUpdater Helper] Renaming '{target}' to '{rollback_name}' for rollback protection...")
    st_ren, res_ren = _docker_request("POST", f"/containers/{target}/rename?name={rollback_name}")
    if st_ren not in (200, 204):
        logger.error(f"[SelfUpdater Helper] Failed to rename container for rollback: status={st_ren}, res={res_ren}")
        _docker_request("POST", f"/containers/{target}/start")
        write_update_result(data_dir, "not_applied", "could not keep the current version aside", to_image=image)
        sys.exit(1)

    logger.info(f"[SelfUpdater Helper] Creating updated container '{target}' with image '{image}'...")
    st_create, res_create = _docker_request("POST", f"/containers/create?name={target}", body=create_body)
    if st_create not in (200, 201) or not isinstance(res_create, dict) or not res_create.get("Id"):
        logger.error(f"[SelfUpdater Helper] Failed to recreate container: status={st_create}, res={res_create}.")
        _rollback_container(target, rollback_name)
        write_update_result(data_dir, "rolled_back", "the new version's container could not be created", to_image=image)
        sys.exit(1)
    new_cid = res_create["Id"]

    for net_name, endpoint in extra_networks.items():
        st_net, res_net = _docker_request(
            "POST", f"/networks/{net_name}/connect", body={"Container": new_cid, "EndpointConfig": endpoint}
        )
        if st_net not in (200, 201, 204):
            logger.error(f"[SelfUpdater Helper] Could not connect network '{net_name}': status={st_net}, res={res_net}")
            _rollback_container(target, rollback_name, failed_id=new_cid, snapshot=snapshot, data_dir=data_dir)
            write_update_result(data_dir, "rolled_back", f"could not connect network {net_name}", to_image=image)
            sys.exit(1)

    logger.info(f"[SelfUpdater Helper] Starting updated container '{target}' ({new_cid[:12]})...")
    st_start, _ = _docker_request("POST", f"/containers/{new_cid}/start")
    if st_start not in (200, 204):
        logger.error(f"[SelfUpdater Helper] Failed to start updated container: status={st_start}.")
        _rollback_container(target, rollback_name, failed_id=new_cid, snapshot=snapshot, data_dir=data_dir)
        write_update_result(data_dir, "rolled_back", "the new version did not start", to_image=image)
        sys.exit(1)

    healthy, why = _wait_until_healthy(new_cid)
    if not healthy:
        logger.error(f"[SelfUpdater Helper] Updated container is not healthy ({why}). Rolling back...")
        _rollback_container(target, rollback_name, failed_id=new_cid, snapshot=snapshot, data_dir=data_dir)
        write_update_result(data_dir, "rolled_back", why, to_image=image)
        sys.exit(1)

    logger.info(f"[SelfUpdater Helper] '{target}' is {why}. Removing the rollback container...")
    _docker_request("DELETE", f"/containers/{rollback_name}?v=false")
    if snapshot and old_image_ref and data_dir:
        _protect_rollback_image(old_image_ref, _container_build(inspect_data, ""), data_dir)
    write_update_result(data_dir, "reverted" if restore_from else "updated", why, to_image=image)
    logger.info(f"[SelfUpdater Helper] OTA update complete for '{target}'.")


def main():
    parser = argparse.ArgumentParser(description="ZettNAS Ephemeral Self-Updater Helper")
    parser.add_argument("--apply", action="store_true", help="Execute container recreate sequence")
    parser.add_argument("--target", default="zettnas-toolkit", help="Target container name")
    parser.add_argument("--image", default="ghcr.io/fr0styx/zettnas-toolkit:latest", help="Target Docker image")
    parser.add_argument("--delay", type=float, default=2.5, help="Delay seconds before stopping caller")
    parser.add_argument("--data-dir", default=None, help="Target's data folder mounted into the helper")
    parser.add_argument("--restore-from", default=None, help="Snapshot to restore before starting (revert)")
    args = parser.parse_args()

    if args.apply:
        apply_update_from_helper(
            args.target, args.image, args.delay, data_dir=args.data_dir, restore_from=args.restore_from
        )
    else:
        print("Self-updater helper invoked without --apply. Exiting.")


if __name__ == "__main__":
    main()


def last_update_result(data_dir: str) -> dict[str, Any] | None:
    from backend.fsutil import read_json

    data = read_json(os.path.join(data_dir, RESULT_FILE), None)
    return data if isinstance(data, dict) and data.get("result") else None


def report_last_update_result(data_dir: str) -> dict[str, Any] | None:
    """Once after an update: an event for every result, and a notification when the update did
    not take (OPS-7). Returns the result that was reported, if any."""
    data = last_update_result(data_dir)
    if not data or data.get("reported"):
        return None
    from backend.fsutil import atomic_write_json
    from backend.state import add_event

    target = str(data.get("to_image") or "the new version")
    reason = str(data.get("reason") or "")
    if data["result"] in ("rolled_back", "not_applied"):
        title = "Update rolled back" if data["result"] == "rolled_back" else "Update not applied"
        message = f"{target}: {reason}. The previous version is running." if reason else f"{target}."
        add_event("error", title, message)
        try:
            from backend.services.notifications import send_notification

            send_notification(
                title, message, level="warning", event_type="system_update", dedup_key=f"update-{data.get('at')}"
            )
        except Exception as e:
            logger.warning(f"[SelfUpdater] Could not send the update notification: {e}")
    else:
        add_event("info", "Update complete" if data["result"] == "updated" else "Reverted", f"Now running {target}.")
    data["reported"] = True
    atomic_write_json(os.path.join(data_dir, RESULT_FILE), data)
    return data

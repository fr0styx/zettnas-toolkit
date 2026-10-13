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
import socket
import sys
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("zettnas.self_updater")


def _docker_request(method: str, path: str, body: Optional[dict] = None, timeout: float = 30.0) -> Tuple[int, Any]:
    """Helper for synchronous Docker Unix socket communication."""
    from backend.services.container_mutator import _docker_request as raw_req

    return raw_req(method, path, body=body, timeout=timeout)


def spawn_self_updater(
    target_image: str = "ghcr.io/fr0styx/zettnas-toolkit:latest",
    container_name: str = "zettnas-toolkit",
    delay_seconds: float = 2.5,
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

        create_body = {
            "Image": target_image,
            "Cmd": cmd,
            "HostConfig": {
                "Binds": ["/var/run/docker.sock:/var/run/docker.sock"],
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


def apply_update_from_helper(target: str, image: str, delay: float = 2.5):
    """
    Executed inside the ephemeral helper container to safely recreate the target container.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info(f"[SelfUpdater Helper] Initialized. Waiting {delay}s for caller HTTP completion...")
    time.sleep(max(1.0, delay))

    st, inspect_data = _docker_request("GET", f"/containers/{target}/json")
    if st != 200 or not isinstance(inspect_data, dict):
        logger.error(f"[SelfUpdater Helper] Target container '{target}' not found (status={st})")
        sys.exit(1)

    config = dict(inspect_data.get("Config") or {})
    host_config = dict(inspect_data.get("HostConfig") or {})

    logger.info(f"[SelfUpdater Helper] Gracefully stopping container '{target}'...")
    _docker_request("POST", f"/containers/{target}/stop?t=15")

    logger.info(f"[SelfUpdater Helper] Removing old container '{target}'...")
    _docker_request("DELETE", f"/containers/{target}?v=false")

    logger.info(f"[SelfUpdater Helper] Creating updated container '{target}' with image '{image}'...")
    create_body = dict(config)
    create_body["Image"] = image
    create_body["HostConfig"] = host_config

    st_create, res_create = _docker_request("POST", f"/containers/create?name={target}", body=create_body)
    if st_create not in (200, 201) or not isinstance(res_create, dict):
        logger.error(f"[SelfUpdater Helper] Failed to recreate container: status={st_create}, res={res_create}")
        sys.exit(1)

    new_cid = res_create.get("Id")
    logger.info(f"[SelfUpdater Helper] Starting newly recreated container '{target}' ({new_cid[:12]})...")
    st_start, _ = _docker_request("POST", f"/containers/{new_cid}/start")
    if st_start in (200, 204):
        logger.info(f"[SelfUpdater Helper] Container '{target}' successfully updated and started!")
    else:
        logger.error(f"[SelfUpdater Helper] Failed to start updated container: status={st_start}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="ZettNAS Ephemeral Self-Updater Helper")
    parser.add_argument("--apply", action="store_true", help="Execute container recreate sequence")
    parser.add_argument("--target", default="zettnas-toolkit", help="Target container name")
    parser.add_argument("--image", default="ghcr.io/fr0styx/zettnas-toolkit:latest", help="Target Docker image")
    parser.add_argument("--delay", type=float, default=2.5, help="Delay seconds before stopping caller")
    args = parser.parse_args()

    if args.apply:
        apply_update_from_helper(args.target, args.image, args.delay)
    else:
        print("Self-updater helper invoked without --apply. Exiting.")


if __name__ == "__main__":
    main()

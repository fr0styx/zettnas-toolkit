#!/usr/bin/env python3
"""Deploys each built-in App Catalog template for real and checks its web UI answers.

Usage (on a Docker host, from the repo root):
    python3 scripts/verify_catalog.py [app_id ...] [--keep-images] [--root /tmp/zt-verify]

Each app runs through ZettNAS's own deploy code (stream_deploy_catalog_app) under a temporary
name, "zt-verify-<id>", with every host port moved to a free one so nothing on the host is
disturbed. The check passes when the web UI answers with any status below 500 within the time
limit. Afterwards the container, its companions and network, its folders and any image the
run pulled are removed. Results go to stdout and <root>/catalog-verify.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import app_catalog  # noqa: E402
from backend.services.catalog_templates import CURATED_APP_CATALOG  # noqa: E402
from backend.services.container_mutator import _docker_request  # noqa: E402

WAIT_SECONDS = {
    "default": 180,
    "minecraft": 420,
    "firefly-iii": 300,
    "wikijs": 300,
    "miniflux": 240,
    "immich": 420,
    "open-webui": 420,
    "paperless-ngx": 300,
    "nextcloud": 300,
    "homeassistant": 300,
}


def free_port(start: int, taken: set[int]) -> int:
    p = start
    while True:
        if p not in taken:
            with socket.socket() as s:
                try:
                    s.bind(("0.0.0.0", p))
                    taken.add(p)
                    return p
                except OSError:
                    pass
        p += 1


def remap_ports(app: dict, taken: set[int]) -> tuple[dict, int]:
    """A copy of the template with every host port moved to a free one; returns (app, main port)."""
    app = json.loads(json.dumps(app))
    default = int(app["default_port"])
    main = free_port(47000, taken)
    ports = []
    for p_str in app.get("ports") or []:
        m = re.match(r"^(\d+):(\d+)(/\w+)?$", p_str)
        hp, cp, proto = int(m.group(1)), int(m.group(2)), m.group(3) or ""
        if hp == default or cp == default:
            ports.append(p_str)  # the deploy maps this one to the main port
        else:
            ports.append(f"{free_port(47000, taken)}:{cp}{proto}")
    if ports:
        app["ports"] = ports
    return app, main


def probe(url: str, seconds: int) -> tuple[int | None, str]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    end = time.time() + seconds
    last = ""
    while time.time() < end:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "zettnas-catalog-verify"})
            with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
                return r.status, ""
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return e.code, ""
            last = f"HTTP {e.code}"
        except Exception as e:  # not up yet
            last = str(e)[:120]
        time.sleep(3)
    return None, last


def probe_tcp(port: int, seconds: int) -> tuple[int | None, str]:
    end = time.time() + seconds
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5):
                return 0, ""
        except OSError as e:
            last = str(e)[:120]
        time.sleep(3)
    return None, last if "last" in locals() else "no answer"


def image_ids() -> set[str]:
    st, imgs = _docker_request("GET", "/images/json")
    return {i["Id"] for i in imgs} if st == 200 else set()


def cleanup(service: str, app: dict, root: str, keep_images: bool, before: set[str]) -> None:
    names = [service] + [f"{service}_{re.sub(r'[^a-zA-Z0-9_.-]+', '_', s)}" for s in (app.get("stack_services") or {})]
    for n in names:
        _docker_request("POST", f"/containers/{n}/stop?t=5")
        _docker_request("DELETE", f"/containers/{n}?v=true&force=true")
    _docker_request("DELETE", f"/networks/{service}_net")
    shutil.rmtree(os.path.join(root, service), ignore_errors=True)
    if not keep_images:
        for img in image_ids() - before:
            _docker_request("DELETE", f"/images/{img}?force=true")


def logs_tail(name: str) -> str:
    st, out = _docker_request("GET", f"/containers/{name}/logs?stdout=1&stderr=1&tail=15")
    return str(out)[-1200:] if st == 200 else ""


def verify(app: dict, root: str, keep_images: bool, taken: set[int]) -> dict:
    service = f"zt-verify-{app['id']}"
    test_app, port = remap_ports(app, taken)
    before = image_ids()
    started = time.time()
    result = {"id": app["id"], "image": app["image"], "ok": False}
    original = app_catalog.get_catalog_app
    app_catalog.get_catalog_app = lambda _id: dict(test_app, source_id="builtin")
    try:
        final = None
        for ev in app_catalog.stream_deploy_catalog_app(
            app["id"], host_port=port, storage_root=root, container_name=service
        ):
            if ev.get("done"):
                final = ev
        if not final or final.get("step") != "success":
            result["error"] = (final or {}).get("message", "no result")[:400]
            result["logs"] = logs_tail(service)
            return result
        result["credentials"] = bool(final.get("credentials"))
        url = final["webui_url"].replace("[HOST]", "127.0.0.1")
        wait = WAIT_SECONDS.get(app["id"], WAIT_SECONDS["default"])
        if app.get("probe") == "tcp":  # no web UI: the port has to accept connections
            url = f"tcp://127.0.0.1:{port}"
            status, err = probe_tcp(port, wait)
        else:
            status, err = probe(url, wait)
        result.update(status=status, url=url, seconds=round(time.time() - started))
        if status is None:
            result["error"] = err
            result["logs"] = logs_tail(service)
        else:
            result["ok"] = True
        return result
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"[:400]
        return result
    finally:
        app_catalog.get_catalog_app = original
        cleanup(service, app, root, keep_images, before)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--keep-images", action="store_true")
    ap.add_argument("--root", default="/tmp/zt-verify")
    args = ap.parse_args()
    os.makedirs(args.root, exist_ok=True)
    apps = [a for a in CURATED_APP_CATALOG if not args.ids or a["id"] in args.ids]
    taken: set[int] = set()
    results = []
    for app in apps:
        r = verify(app, args.root, args.keep_images, taken)
        results.append(r)
        mark = "OK  " if r["ok"] else "FAIL"
        print(
            f"{mark} {r['id']:<22} {r.get('status')!s:<5} {r.get('seconds', '')!s:>4}s  {r.get('error', '')}",
            flush=True,
        )
        with open(os.path.join(args.root, "catalog-verify.json"), "w") as fh:
            json.dump(results, fh, indent=1)
    bad = [r["id"] for r in results if not r["ok"]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed" + (f"; failed: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

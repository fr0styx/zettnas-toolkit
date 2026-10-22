"""Node.js stays on one patched version everywhere: the build stage, the shipped Playwright driver and CI."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# October 2026 security release: Brotli decoder out-of-bounds write (CVE-2026-111497) and others
MINIMUM = (26, 12, 1)


def _version(text):
    return tuple(int(x) for x in text.split("."))


def test_node_versions_agree_and_are_patched():
    nvmrc = (ROOT / ".nvmrc").read_text().strip()
    dockerfile = (ROOT / "Dockerfile").read_text()
    builder = re.search(
        r"FROM --platform=\$BUILDPLATFORM node:([0-9.]+)-alpine@sha256:[0-9a-f]{64} AS frontend-builder", dockerfile
    )
    runtime = re.search(
        r"COPY --from=node:([0-9.]+)-[a-z]+-slim@sha256:[0-9a-f]{64} /usr/local/bin/node \S+/playwright/driver/node",
        dockerfile,
    )
    assert builder and runtime, "Node images must be pinned by version and digest"
    assert builder.group(1) == runtime.group(1) == nvmrc
    assert _version(nvmrc) >= MINIMUM


def test_ci_uses_nvmrc():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "node-version: 24" not in ci
    assert ci.count('node-version-file: ".nvmrc"') == 2
    assert "PLAYWRIGHT_NODEJS_PATH" in ci

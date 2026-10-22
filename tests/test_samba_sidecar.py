"""The generic-Linux Samba sidecar (docker-compose.linux.yml)."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _service():
    return yaml.safe_load((ROOT / "docker-compose.linux.yml").read_text())["services"]["zettnas-samba"]


def test_sidecar_uses_a_maintained_pinned_image():
    image = _service()["image"]
    assert image.startswith("crazymax/samba:")
    assert re.fullmatch(r"crazymax/samba:\d+\.\d+\.\d+", image), "pin an exact Samba version"
    assert "image: dperson" not in (ROOT / "docker-compose.linux.yml").read_text()


def test_start_script_runs_zettnas_config_and_survives_restarts():
    svc = _service()
    assert svc["entrypoint"] == ["/bin/sh", "-c"]
    script = svc["command"][0]
    # compose would expand single $ itself; the shell's own variables must be written $$
    assert not re.search(r"(?<!\$)\$(?!\$)", script)
    assert '--configfile="$$CONF"' in script and "CONF=/etc/samba/zettnas/smb.conf" in script
    assert "Standby mode" in script  # Unraid/TrueNAS already serve SMB on 445
    assert "pdbedit -L" in script and "adduser" in script  # Unix accounts come back after a restart
    assert "/var/lib/samba/private" in " ".join(svc["volumes"])


def test_user_sync_gives_each_user_an_id():
    src = (ROOT / "backend" / "services" / "samba_engine.py").read_text()
    assert 'adduser -D -H -u 1000 "$1" 2>/dev/null || adduser -D -H "$1"' in src

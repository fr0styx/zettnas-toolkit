"""Unraid's /boot/config/network.cfg, read only: the host's own network settings (SET-16, D2).

Kiboto reads this file for the address, bonds and bridges Unraid has set up. It never writes it:
on Unraid the wiring is changed in Unraid's own settings (backend/hardware/net/host.py)."""

import os

from backend.config import logger
from backend.hardware.net import common


def _parse_unraid_network_cfg() -> dict[str, str]:
    """Parse key-values from Unraid /boot/config/network.cfg if present."""
    cfg: dict[str, str] = {}
    for c in common.UNRAID_NETWORK_CFG:
        if os.path.isfile(c):
            try:
                with open(c, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            cfg[k.strip()] = v.strip().strip('"').strip("'")
                return cfg
            except OSError:
                logger.debug("Could not read %s", c, exc_info=True)
    return cfg

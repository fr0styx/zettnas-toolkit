"""Who changes the host's network wiring (SET-16, decision D2).

Kiboto reads the host's network on every install. It changes the wiring (address, packet size,
link speed, Wake-on-LAN, bonds, bridges, VLANs) only on a host it manages: Kiboto's own OS images,
which are still to come. Everywhere else the host's own settings own the wiring, and a change made
from Kiboto never applied or did not survive a restart (network report, B2 to B4).

The page asks `capabilities()` and draws each setting as a row that becomes a field once the host
allows it. The write routes keep their shape and answer "not on this host" with where to change it.
A managed host subclasses `HostNetwork`, sets `managed = True`, implements `apply()` and is
returned by `current_host()` for its platform.
"""

from typing import Any

from backend.hardware.pal.base import PlatformType

SETTINGS = ("address", "mtu", "speed", "wake_on_lan", "bond", "bridge", "vlan")

# where the host's own network settings are, for the sentence the page shows
_WHERE = {
    PlatformType.UNRAID: "unraid",
    PlatformType.TRUENAS: "truenas",
    PlatformType.PROXMOX: "proxmox",
    PlatformType.UGOS: "ugos",
}
_WHERE_TEXT = {
    "unraid": "Unraid: Settings, Network Settings",
    "truenas": "TrueNAS: Network",
    "proxmox": "Proxmox: the node's System, Network",
    "ugos": "UGOS: Control Panel, Network",
    "system": "the host system's own network settings",
}


class NotOnThisHost(Exception):
    """A change to the wiring on a host whose own settings own it."""

    def __init__(self, setting: str, where: str):
        self.setting = setting
        self.where = where
        super().__init__(f"This is changed in {_WHERE_TEXT.get(where, _WHERE_TEXT['system'])}, not in Kiboto.")


class HostNetwork:
    """A host Kiboto does not manage: it reads the wiring and changes none of it."""

    managed = False

    def __init__(self, platform: PlatformType | str = PlatformType.UNKNOWN):
        self.platform = platform

    def where(self) -> str:
        return _WHERE.get(self.platform, "system")  # type: ignore[call-overload]

    def capabilities(self) -> dict[str, Any]:
        return {
            "managed": self.managed,
            "where": self.where(),
            "can_change": {name: self.managed for name in SETTINGS},
        }

    def apply(self, setting: str, target: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Changes one setting of one interface (or the address). A managed host overrides this."""
        raise NotOnThisHost(setting, self.where())


def current_host() -> HostNetwork:
    """The host Kiboto runs on. No platform is managed yet: Kiboto's own OS images will be."""
    from backend.hardware.pal.detect import StoragePlatformDetector

    return HostNetwork(StoragePlatformDetector.detect())

"""NREL-6: hosts that can\x27t take snapshots here say so, so nothing schedules snapshots that fail."""

import pytest

from backend.hardware.pal import fygoos, observer, proxmox, ugos, unraid, zettos


@pytest.mark.parametrize(
    "adapter",
    [
        unraid.UnraidStorageAdapter,
        zettos.ZettOSStorageAdapter,
        proxmox.ProxmoxStorageAdapter,
        ugos.UgosStorageAdapter,
        fygoos.FygoOSStorageAdapter,
        observer.GenericObserverStorageAdapter,
    ],
)
def test_observers_dont_claim_snapshots(adapter):
    a = adapter.__new__(adapter)  # no host to read; capabilities are fixed
    a.__dict__.setdefault("_emhttp_dir", "")
    assert a.get_capabilities().can_snapshot is False

"""B9: Kiboto's Unraid parsers over every recorded Unraid release (tests/compat/unraid/<version>/emhttp).

A recording is what a real box's emhttp state files looked like, scrubbed by scripts/compat_capture.py.
When an Unraid release changes those files, its recording makes this fail before users notice.
"""

import configparser
import dataclasses
import pathlib

import pytest

from backend import config as _config
from backend.hardware import unraid
from backend.hardware.pal import base as pal_base

ROOT = pathlib.Path(__file__).resolve().parent / "compat" / "unraid"
RECORDINGS = sorted(p for p in ROOT.glob("*/emhttp") if (p / "var.ini").is_file())


def _ini(path: pathlib.Path) -> configparser.RawConfigParser:
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    text = path.read_text(encoding="utf-8")
    cp.read_string(text if text.lstrip().startswith("[") else "[global]\n" + text)
    return cp


def _values(cp, section):
    return {k: v.strip('"') for k, v in cp.items(section)}


@pytest.fixture(params=RECORDINGS, ids=[p.parent.name for p in RECORDINGS])
def box(request, monkeypatch):
    folder = request.param
    monkeypatch.setattr(_config, "SETTINGS", dataclasses.replace(_config.SETTINGS, unraid_emhttp_dir=str(folder)))
    monkeypatch.setattr(unraid, "_find_emhttp_dir", lambda: str(folder))
    monkeypatch.setattr(pal_base, "_find_emhttp_dir", lambda: str(folder))
    return folder


def test_there_is_a_recording():
    assert RECORDINGS, "record one with scripts/compat_capture.py unraid"


def test_recordings_carry_nothing_personal():
    for folder in RECORDINGS:
        for f in folder.iterdir():
            text = f.read_text(encoding="utf-8")
            assert 'NAME="tower"' in text or f.name != "var.ini", f
            for line in text.splitlines():
                key, _, value = line.partition("=")
                if key == "id" and value.strip('"'):
                    assert value.strip('"').startswith("DISK-"), (f, line)
                if key in ("comment",):
                    assert value == '""', (f, line)


def test_the_array_state(box):
    var = _values(_ini(box / "var.ini"), "global")
    st = unraid.read_unraid_status(force=True)
    assert st, "nothing parsed"
    text = repr(st)
    assert var["mdState"] in text or var["mdState"].lower() in text.lower()


def test_every_disk_has_a_role(box):
    disks = _ini(box / "disks.ini")
    roles = unraid.get_unraid_disk_roles(force=True)
    with_device = [s for s in disks.sections() if _values(disks, s).get("device")]
    assert with_device
    named = {str(r.get("name") or k) for k, r in roles.items()} | set(roles)
    for section in with_device:
        device = _values(disks, section)["device"]
        assert section.strip('"') in named or device in roles or device in repr(roles), section


def test_pools_and_shares(box):
    from backend.hardware.pal.unraid import UnraidStorageAdapter

    adapter = UnraidStorageAdapter()
    pools = adapter.list_pools()
    assert pools, "no pools from the recording"
    shares = adapter.list_shares()
    recorded = {s.strip('"') for s in _ini(box / "shares.ini").sections()} if (box / "shares.ini").exists() else set()
    names = {getattr(s, "name", "") for s in shares}
    assert recorded <= names, recorded - names

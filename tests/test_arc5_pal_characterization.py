"""ARC-5: the storage abstraction keeps its API and behaviour while it is split up.

Records, from backend.hardware.pal_storage: every public name, each class's ancestors and
method signatures, every adapter's capabilities, and what the parsing helpers return for
sample inputs. tests/golden/pal_storage.json was recorded before the module became a
package; the facade must still provide all of it. Regenerate only for an intended change:

    ZETTNAS_UPDATE_GOLDEN=1 pytest tests/test_arc5_pal_characterization.py
"""

import enum
import inspect
import json
import os
import re
import types

import pytest

from backend.hardware import pal_storage as pal

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "pal_storage.json")
INI_SAMPLES = [
    '["disk1"]\nname="disk1"\ndevice="sdb"\nstatus="DISK_OK"\n["parity"]\nname="parity"\n',
    "# comment\n[global]\nworkgroup = WORKGROUP\n[media]\npath = /mnt/user/media\nread only = no\n",
    "",
]


def _helpers(tmp):
    """The parsing helpers on sample inputs (files under tmp; results hold no tmp paths)."""
    out = {}
    out["_whole_disk"] = [
        pal._whole_disk(n) for n in ("sdb1", "sdb", "nvme0n1p1", "nvme1n1", "mmcblk0p2", "vda3", "md1")
    ]
    inis = []
    for i, text in enumerate(INI_SAMPLES):
        path = os.path.join(tmp, f"s{i}.ini")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        inis.append(pal._parse_ini_sections(path))
    inis.append(pal._parse_ini_sections(os.path.join(tmp, "missing.ini")))
    out["_parse_ini_sections"] = inis
    root = os.path.join(tmp, "sys")
    for fsid, dev, profiles in (("aaaa", "sdb", ("raid1",)), ("bbbb", "sdc", ("single", "raid10"))):
        os.makedirs(os.path.join(root, "fs", "btrfs", fsid, "devices", dev))
        for prof in profiles:
            os.makedirs(os.path.join(root, "fs", "btrfs", fsid, "allocation", "data", prof))
    out["btrfs_data_profiles"] = [pal.btrfs_data_profiles(d, sys_roots=(root,)) for d in ("/dev/sdb", "sdc", "sdz", "")]
    out["btrfs_is_redundant"] = [
        pal.btrfs_is_redundant(p) for p in (["raid1"], ["single"], ["dup"], [], ["raid1", "single"])
    ]
    return out


def _signature(obj):
    try:
        sig = str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "?"
    return re.sub(r"backend\.hardware\.pal[\w.]*?\.(?=[A-Z])", "", sig)  # where a type lives may change


def _surface():
    out = {}
    for name in sorted(dir(pal)):
        if name.startswith("__"):
            continue
        obj = getattr(pal, name)
        if isinstance(obj, types.ModuleType) or getattr(obj, "__module__", "").startswith(
            ("typing", "abc", "enum", "pydantic")
        ):
            continue
        if inspect.isclass(obj) and obj.__module__.startswith("backend.hardware.pal"):
            if issubclass(obj, enum.Enum):
                out[name] = {"enum": {m.name: m.value for m in obj}}
                continue
            methods = {
                m: _signature(f)
                for m, f in sorted(vars(obj).items())
                if callable(f) or isinstance(f, (staticmethod, classmethod))
                if not (m.startswith("__") and m != "__init__")
            }
            fields = sorted(getattr(obj, "model_fields", {}) or {})
            out[name] = {
                "mro": [c.__name__ for c in obj.__mro__ if c.__module__.startswith("backend.")],
                "methods": methods,
                "fields": fields,
            }
        elif inspect.isfunction(obj) and obj.__module__.startswith("backend.hardware.pal"):
            out[name] = {"function": _signature(obj)}
    return out


def _behaviour(tmp):
    out = {"capabilities": {}, "helpers": _helpers(tmp)}
    for name in sorted(dir(pal)):
        cls = getattr(pal, name)
        if not (inspect.isclass(cls) and issubclass(cls, pal.StoragePlatformAdapter) and not inspect.isabstract(cls)):
            continue
        try:
            params = inspect.signature(cls).parameters
            adapter = cls(pool_path="/tmp/zn-pal-golden") if "pool_path" in params else cls()
            out["capabilities"][name] = adapter.get_capabilities().model_dump(mode="json")
        except Exception as e:  # recorded too: the split must not change it
            out["capabilities"][name] = f"raised {type(e).__name__}"
    return out


def test_pal_api_and_behaviour_match_the_recording(tmp_path):
    got = {"surface": _surface(), "behaviour": _behaviour(str(tmp_path))}
    got = json.loads(json.dumps(got, sort_keys=True))
    if os.environ.get("ZETTNAS_UPDATE_GOLDEN") == "1":
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump(got, fh, indent=1, sort_keys=True)
            fh.write("\n")
        pytest.skip("golden file written")
    with open(GOLDEN, encoding="utf-8") as fh:
        want = json.load(fh)
    missing = sorted(set(want["surface"]) - set(got["surface"]))
    assert not missing, f"names no longer provided by pal_storage: {missing}"
    changed = [n for n in want["surface"] if got["surface"][n] != want["surface"][n]]
    assert not changed, f"API changed: {changed[:5]}"
    assert got["behaviour"] == want["behaviour"]
    assert len(want["surface"]) >= 20 and len(want["behaviour"]["capabilities"]) >= 8

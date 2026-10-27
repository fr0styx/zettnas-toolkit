"""B10 / SEC-24 step 1: the app gets only the device rules it uses, on new and updated installs."""

import os

from backend.services.self_updater import build_recreate_plan, narrow_device_rules

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_an_update_narrows_the_rules_of_an_older_install():
    old = ["c 1:1 rwm", "c 1:* rwm", "c 226:* rwm", "c 10:232 rwm", "c 10:* rwm", "b 8:* rwm"]
    new = narrow_device_rules(old)
    assert "c 1:* rwm" not in new and "c 10:* rwm" not in new
    assert "c 1:1 rwm" in new  # the fans and button still need /dev/mem (moves to a helper later, D3)
    for r in ("c 10:232 rwm", "c 10:238 rwm", "c 10:200 rwm", "c 10:196 rwm", "c 10:229 rwm"):
        assert new.count(r) == 1, r  # VMs (kvm, vhost-net, tun, vfio) and FUSE keep working
    assert narrow_device_rules(None) is None and narrow_device_rules([]) == []


def test_the_recreate_plan_applies_it():
    inspect = {"Id": "abc", "Config": {"Env": []}, "HostConfig": {"DeviceCgroupRules": ["c 1:* rwm", "c 10:* rwm"]}}
    body, _ = build_recreate_plan(inspect, {}, "img:new")
    assert "c 1:* rwm" not in body["HostConfig"]["DeviceCgroupRules"]


def test_templates_ship_only_the_narrow_rules():
    for name in ("docker-compose.yml", "docker-compose.linux.yml", "unraid/zettnas-toolkit.xml"):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            text = f.read()
        assert "c 1:* rwm" not in text and "c 10:* rwm" not in text, name
        assert "c 10:200 rwm" in text and "c 10:196 rwm" in text, name

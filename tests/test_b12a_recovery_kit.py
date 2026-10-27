"""B12a (REL-17): a full recovery kit (key, location, cloud settings, restore commands) that must
be saved, and files restored from it with plain restic and nothing else from the NAS."""

import os
import re
import shutil
import subprocess

import pytest

from backend import config
from backend.services import offsite_backup as ob
from backend.services import status_summary


@pytest.fixture
def env(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    (storage / "family").mkdir(parents=True)
    (storage / "family" / "letter.txt").write_text("Dear Grandma")
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(storage)])
    monkeypatch.setattr(ob, "REPOS_FILE", str(tmp_path / "repos.json"))
    monkeypatch.setattr(ob, "KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    return storage


def _repo(storage, rid="usb", location=None):
    loc = location or str(storage / "usb-backup")
    ob.save_repo(rid, "USB disk", loc, [str(storage / "family")])
    os.makedirs(ob.KEY_DIR, exist_ok=True)
    with open(ob._key_file(rid), "w") as f:
        f.write("correct-horse-battery-staple\n")
    repos = ob._repos()
    repos[rid]["initialized"] = True
    ob._save(repos)
    return loc


def test_the_kit_holds_the_key_the_place_and_the_commands(env):
    loc = _repo(env)
    kit = ob.recovery_kit("usb")
    assert "Recovery key: correct-horse-battery-staple" in kit
    assert f"Backup location: {loc}" in kit
    assert f"restic -r '{loc}' restore latest --target ./restored" in kit
    assert "rclone.conf" not in kit  # a folder destination needs no cloud settings


def test_a_cloud_kit_carries_its_rclone_settings(env, tmp_path, monkeypatch):
    conf = tmp_path / "rclone.conf"
    conf.write_text("[mycloud]\ntype = b2\naccount = abc\nkey = secret\n\n[other]\ntype = s3\n")
    monkeypatch.setattr(ob, "RCLONE_CONFIG_FILE", str(conf))
    _repo(env, "cloud", "rclone:mycloud:zettnas")
    kit = ob.recovery_kit("cloud")
    assert "[mycloud]" in kit and "account = abc" in kit and "[other]" not in kit
    assert "export RCLONE_CONFIG=./rclone.conf" in kit


def test_until_the_kit_is_saved_the_overview_says_so(env, monkeypatch):
    _repo(env)
    assert [k["id"] for k in ob.kits_not_saved()] == ["usb"]
    monkeypatch.setattr(ob, "kits_not_saved", ob.kits_not_saved)
    assert "kit_not_saved" in [i["kind"] for i in status_summary.summary()["items"]]
    ob.mark_kit_saved("usb")
    assert ob.kits_not_saved() == []
    ob.save_repo("usb", "USB disk", ob.get_repo("usb")["location"], ob.get_repo("usb")["paths"])
    assert ob.get_repo("usb")["kit_saved_at"]  # editing the backup keeps it


def test_the_api_gives_the_kit_and_records_it_saved(env, client, auth_headers):
    _repo(env)
    res = client.get("/api/offsite/repos/usb/kit", headers=auth_headers)
    assert res.status_code == 200 and res.json()["filename"] == "zettnas-recovery-usb.txt"
    assert "correct-horse-battery-staple" in res.json()["text"]
    assert client.post("/api/offsite/repos/usb/kit-saved", headers=auth_headers).status_code == 200
    assert ob.kits_not_saved() == []


@pytest.mark.skipif(not shutil.which("restic"), reason="restic is not installed")
def test_plain_restic_restores_the_files_with_only_the_kit(env, tmp_path):
    loc = _repo(env)
    ob.init("usb")
    ob.backup("usb")
    kit = ob.recovery_kit("usb")
    # a second machine: nothing from the NAS but the kit text
    key = re.search(r"^Recovery key: (.+)$", kit, re.M).group(1)
    where = re.search(r"^Backup location: (.+)$", kit, re.M).group(1)
    target = tmp_path / "second-machine"
    clean_env = {"PATH": os.environ["PATH"], "RESTIC_PASSWORD": key, "HOME": str(tmp_path)}
    subprocess.run(
        ["restic", "-r", where, "restore", "latest", "--target", str(target)],
        env=clean_env,
        check=True,
        capture_output=True,
    )
    restored = list(target.rglob("letter.txt"))
    assert restored and restored[0].read_text() == "Dear Grandma"
    assert where == loc

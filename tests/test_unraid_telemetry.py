import dataclasses

from backend import config as _config
from backend.hardware.unraid import read_unraid_status


def test_unraid_not_available_fallback(monkeypatch):
    monkeypatch.setattr(
        _config, "SETTINGS", dataclasses.replace(_config.SETTINGS, unraid_emhttp_dir="/nonexistent_dir")
    )
    status = read_unraid_status(force=True)
    assert status["available"] is False
    assert status["state"] == "STANDALONE"
    assert status["is_healthy"] is True
    assert status["parity_check"]["active"] is False
    assert status["mover"]["active"] is False


def test_unraid_parse_healthy_array(tmp_path, monkeypatch):
    emhttp_dir = tmp_path / "emhttp"
    emhttp_dir.mkdir()
    var_ini = emhttp_dir / "var.ini"
    var_ini.write_text(
        """version="7.3.2"
NAME="Kiboto"
SYS_MODEL="D6U"
mdColor="green-on"
mdNumDisks="6"
mdNumDisabled="0"
mdNumInvalid="0"
mdNumMissing="0"
mdState="STARTED"
fsState="Started"
shareMoverActive="no"
mdResync="0"
"""
    )

    monkeypatch.setattr("backend.hardware.unraid._find_emhttp_dir", lambda: str(emhttp_dir))
    status = read_unraid_status(force=True)

    assert status["available"] is True
    assert status["version"] == "7.3.2"
    assert status["server_name"] == "Kiboto"
    assert status["model"] == "D6U"
    assert status["state"] == "STARTED"
    assert status["color"] == "green-on"
    assert status["is_healthy"] is True
    assert status["disks"]["total"] == 6
    assert status["disks"]["disabled"] == 0
    assert status["parity_check"]["active"] is False
    assert status["mover"]["active"] is False


def test_unraid_parse_parity_check_in_progress(tmp_path, monkeypatch):
    emhttp_dir = tmp_path / "emhttp"
    emhttp_dir.mkdir()
    var_ini = emhttp_dir / "var.ini"
    var_ini.write_text(
        """mdColor="green-blink"
mdState="STARTED"
mdResyncAction="check P"
mdResyncPos="5000000"
mdResyncSize="10000000"
mdResyncCorr="1"
sbSyncErrs="2"
mdResync="145820"
shareMoverActive="no"
"""
    )

    monkeypatch.setattr("backend.hardware.unraid._find_emhttp_dir", lambda: str(emhttp_dir))
    status = read_unraid_status(force=True)

    assert status["available"] is True
    assert status["parity_check"]["active"] is True
    assert status["parity_check"]["paused"] is False
    assert status["parity_check"]["action"] == "check P"
    assert status["parity_check"]["progress_pct"] == 50.0
    assert status["parity_check"]["errors"] == 2  # sbSyncErrs, not the correcting switch
    assert status["parity_check"]["correcting"] is True
    assert status["parity_check"]["speed"] == 145820


def test_unraid_parse_parity_check_idle_or_paused(tmp_path, monkeypatch):
    emhttp_dir = tmp_path / "emhttp"
    emhttp_dir.mkdir()
    var_ini = emhttp_dir / "var.ini"
    var_ini.write_text(
        """mdColor="green-on"
mdState="STARTED"
mdResyncAction="check P"
mdResyncPos="7401889556"
mdResyncSize="21485322188"
mdResyncCorr="1"
mdResync="0"
mdResyncDt="0"
shareMoverActive="no"
"""
    )

    monkeypatch.setattr("backend.hardware.unraid._find_emhttp_dir", lambda: str(emhttp_dir))
    status = read_unraid_status(force=True)

    assert status["available"] is True
    assert status["parity_check"]["active"] is False
    assert status["parity_check"]["paused"] is True
    assert status["parity_check"]["action"] == "check P"
    assert status["parity_check"]["speed"] == 0


def test_unraid_parse_mover_active(tmp_path, monkeypatch):
    emhttp_dir = tmp_path / "emhttp"
    emhttp_dir.mkdir()
    var_ini = emhttp_dir / "var.ini"
    var_ini.write_text(
        """mdState="STARTED"
shareMoverActive="yes"
"""
    )
    mover_ini = emhttp_dir / "mover.ini"
    mover_ini.write_text(
        """TotalFilesToSecondary=40
RemainFilesToSecondary=15
TotalFilesFromSecondary=10
RemainFilesFromSecondary=5
Action=Moving
"""
    )

    monkeypatch.setattr("backend.hardware.unraid._find_emhttp_dir", lambda: str(emhttp_dir))
    status = read_unraid_status(force=True)

    assert status["available"] is True
    assert status["mover"]["active"] is True
    assert status["mover"]["action"] == "Moving"
    assert status["mover"]["total_files"] == 50
    assert status["mover"]["remain_files"] == 20


def test_unraid_parse_disk_roles_and_parity(tmp_path, monkeypatch):
    from backend.hardware.unraid import get_unraid_disk_roles

    emhttp_dir = tmp_path / "emhttp"
    emhttp_dir.mkdir()
    var_ini = emhttp_dir / "var.ini"
    var_ini.write_text(
        """version="7.3.3"
NAME="Kiboto"
mdColor="green-on"
mdState="STARTED"
shareMoverActive="no"
"""
    )
    disks_ini = emhttp_dir / "disks.ini"
    disks_ini.write_text(
        """["parity"]
name="parity"
device="sdb"
id="WDC_WD140EDFZ"
type="Parity"
status="DISK_OK"

["parity2"]
name="parity2"
device="sdc"
id="WDC_WD140EDFZ_2"
type="Parity"
status="DISK_OK"

["disk1"]
name="disk1"
device="sda"
id="WDC_WD80EMAZ"
type="Data"
status="DISK_OK"

["cache"]
name="cache"
device="nvme0n1"
id="Samsung_980_PRO"
type="Cache"
status="DISK_OK"
"""
    )

    monkeypatch.setattr("backend.hardware.unraid._find_emhttp_dir", lambda: str(emhttp_dir))
    roles = get_unraid_disk_roles(force=True)

    assert "sdb" in roles
    assert roles["sdb"]["is_parity"] is True
    assert roles["sdb"]["parity_label"] == "P"
    assert roles["sdb"]["type"] == "Parity"

    assert "sdc" in roles
    assert roles["sdc"]["is_parity"] is True
    assert roles["sdc"]["parity_label"] == "P2"

    assert "sda" in roles
    assert roles["sda"]["is_parity"] is False
    assert roles["sda"]["type"] == "Data"

    assert "nvme0n1" in roles
    assert roles["nvme0n1"]["is_parity"] is False
    assert roles["nvme0n1"]["type"] == "Cache"

    # Verify parity_devices in read_unraid_status
    status = read_unraid_status(force=True)
    assert "sdb" in status["parity_devices"]
    assert "sdc" in status["parity_devices"]
    assert "sda" not in status["parity_devices"]


def test_a_correcting_check_without_errors_says_none(tmp_path, monkeypatch):
    """mdResyncCorr=1 is the "write corrections" switch: after a crash a correcting check had found
    nothing, and the Jobs centre said "1 errors found so far"."""
    emhttp_dir = tmp_path / "emhttp"
    emhttp_dir.mkdir()
    (emhttp_dir / "var.ini").write_text(
        """mdState="STARTED"
mdResyncAction="check P"
mdResyncPos="100"
mdResyncSize="1000"
mdResyncCorr="1"
sbSyncErrs="0"
mdResync="5000"
shareMoverActive="no"
"""
    )
    monkeypatch.setattr("backend.hardware.unraid._find_emhttp_dir", lambda: str(emhttp_dir))
    pc = read_unraid_status(force=True)["parity_check"]
    assert pc["errors"] == 0 and pc["correcting"] is True

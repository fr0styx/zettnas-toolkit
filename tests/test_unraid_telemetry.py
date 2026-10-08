from backend.hardware.unraid import read_unraid_status


def test_unraid_not_available_fallback(monkeypatch):
    monkeypatch.setenv("UNRAID_EMHTTP_DIR", "/nonexistent_dir")
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
NAME="ZettNAS"
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
    assert status["server_name"] == "ZettNAS"
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
mdResyncCorr="2"
shareMoverActive="no"
"""
    )

    monkeypatch.setattr("backend.hardware.unraid._find_emhttp_dir", lambda: str(emhttp_dir))
    status = read_unraid_status(force=True)

    assert status["available"] is True
    assert status["parity_check"]["active"] is True
    assert status["parity_check"]["action"] == "check P"
    assert status["parity_check"]["progress_pct"] == 50.0
    assert status["parity_check"]["errors"] == 2


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

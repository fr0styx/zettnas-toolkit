import os

from backend.hardware.host_telemetry import (
    clear_telemetry_cache,
    get_cpu_telemetry,
    get_dmi_telemetry,
    get_gpu_telemetry,
    get_npu_telemetry,
    get_os_telemetry,
)


def test_dmi_telemetry_discovery(tmp_path, monkeypatch):
    clear_telemetry_cache()
    sys_dir = tmp_path / "sys"
    dmi_dir = sys_dir / "class" / "dmi" / "id"
    dmi_dir.mkdir(parents=True)
    (dmi_dir / "sys_vendor").write_text("Zettlab\n")
    (dmi_dir / "board_name").write_text("WY120\n")
    (dmi_dir / "bios_version").write_text("WY120V016\n")
    (dmi_dir / "bios_date").write_text("05/09/2026\n")

    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_SYS", str(sys_dir))

    dmi = get_dmi_telemetry()
    assert dmi["vendor"] == "Zettlab"
    assert dmi["board"] == "WY120"
    assert dmi["bios_version"] == "WY120V016"
    assert dmi["bios_date"] == "05/09/2026"


def test_cpu_telemetry_parsing(tmp_path, monkeypatch):
    clear_telemetry_cache()
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir(parents=True)
    (proc_dir / "cpuinfo").write_text("processor : 0\nmodel name : Intel(R) Core(TM) Ultra 5 125H\n")
    (proc_dir / "loadavg").write_text("0.15 0.22 0.35 1/450 12345\n")

    sys_dir = tmp_path / "sys"
    cpu0_freq = sys_dir / "devices" / "system" / "cpu" / "cpu0" / "cpufreq"
    cpu0_freq.mkdir(parents=True)
    (cpu0_freq / "scaling_governor").write_text("performance\n")

    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_PROC", str(proc_dir))
    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_SYS", str(sys_dir))

    cpu = get_cpu_telemetry()
    assert "Ultra 5 125H" in cpu["model"]
    assert cpu["load_avg"] == [0.15, 0.22, 0.35]
    assert cpu["governor"] == "performance"
    assert cpu["cores"] >= 1


def test_os_telemetry_parsing(tmp_path, monkeypatch):
    clear_telemetry_cache()
    etc_dir = tmp_path / "etc"
    etc_dir.mkdir(parents=True)
    (etc_dir / "os-release").write_text('PRETTY_NAME="Unraid OS 7.3.2"\nNAME="Unraid OS"\n')

    proc_dir = tmp_path / "proc"
    proc_dir.mkdir(parents=True)
    (proc_dir / "uptime").write_text("90061.50 180000.00\n")

    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_ETC", str(etc_dir))
    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_PROC", str(proc_dir))

    res = get_os_telemetry()
    assert "Unraid" in res["distro"]
    assert "1d 1h" in res["uptime_str"]
    assert res["uptime_sec"] == 90061.5


def test_gpu_telemetry_intel_arc(tmp_path, monkeypatch):
    clear_telemetry_cache()

    dev_dir = tmp_path / "dev"
    dri_dir = dev_dir / "dri"
    dri_dir.mkdir(parents=True)
    (dri_dir / "renderD128").write_text("")

    sys_dir = tmp_path / "sys"
    card_dev = sys_dir / "class" / "drm" / "card0" / "device"
    card_dev.mkdir(parents=True)
    (card_dev / "vendor").write_text("0x8086\n")
    (card_dev / "device").write_text("0x7d55\n")
    driver_link = card_dev / "driver"
    try:
        os.symlink("/lib/modules/drivers/gpu/drm/i915", str(driver_link))
    except Exception:
        driver_link.write_text("i915")

    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_DEV", str(dev_dir))
    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_SYS", str(sys_dir))

    gpu = get_gpu_telemetry()
    assert gpu["present"] is True
    assert gpu["vendor"] == "Intel"
    assert "Arc Graphics" in gpu["model"]
    assert gpu["ready"] is True
    assert "AV1" in gpu["codecs"]
    assert "HEVC 10-bit" in gpu["codecs"]


def test_npu_telemetry_intel_ai_boost(tmp_path, monkeypatch):
    clear_telemetry_cache()

    dev_dir = tmp_path / "dev"
    accel_dir = dev_dir / "accel"
    accel_dir.mkdir(parents=True)
    (accel_dir / "accel0").write_text("")

    sys_dir = tmp_path / "sys"
    accel_sys_dev = sys_dir / "class" / "accel" / "accel0" / "device"
    accel_sys_dev.mkdir(parents=True)
    (accel_sys_dev / "vendor").write_text("0x8086\n")
    (accel_sys_dev / "device").write_text("0x7d1d\n")
    (accel_sys_dev / "npu_max_frequency_mhz").write_text("1400\n")
    (accel_sys_dev / "npu_current_frequency_mhz").write_text("0\n")
    (accel_sys_dev / "sched_mode").write_text("HW\n")
    driver_link = accel_sys_dev / "driver"
    try:
        os.symlink("/lib/modules/drivers/accel/intel_vpu", str(driver_link))
    except Exception:
        driver_link.write_text("intel_vpu")

    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_DEV", str(dev_dir))
    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_SYS", str(sys_dir))

    npu = get_npu_telemetry()
    assert npu["present"] is True
    assert npu["vendor"] == "Intel"
    assert "AI Boost" in npu["model"]
    assert npu["max_freq_mhz"] == 1400
    assert npu["sched_mode"] == "HW"
    assert "OpenVINO" in npu["frameworks"]
    assert npu["ready"] is True


def test_npu_telemetry_none(tmp_path, monkeypatch):
    clear_telemetry_cache()
    dev_dir = tmp_path / "empty_dev"
    dev_dir.mkdir(parents=True)
    sys_dir = tmp_path / "empty_sys"
    sys_dir.mkdir(parents=True)

    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_DEV", str(dev_dir))
    monkeypatch.setattr("backend.hardware.host_telemetry.HOST_SYS", str(sys_dir))

    npu = get_npu_telemetry()
    assert npu["present"] is False
    assert npu["vendor"] == "None"
    assert npu["frameworks"] == []

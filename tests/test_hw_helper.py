"""SEC-24 step 2: the hardware helper alone opens /dev/mem; Kiboto asks it; updates drop Kiboto's access."""

import json
import os
import threading

import pytest

from backend import hw_helper
from backend.hardware import hw_client
from backend.services import self_updater


@pytest.fixture
def fake_mem(tmp_path):
    """A sparse file standing in for /dev/mem, with the fans' and the button's registers set."""
    path = tmp_path / "mem"
    with open(path, "wb") as f:
        f.truncate(hw_helper.EC_BASE + hw_helper.PAGE)
        f.seek(hw_helper.EC_BASE)
        f.write(bytes([0x04, 0xB0, 0, 0x05, 0x14, 0, 0x02, 0x58, 0]))  # 1200, 1300, 600 rpm
        f.seek(hw_helper.GPIO_BASE + hw_helper.COPY_OFFSET)
        f.write((2).to_bytes(4, "little"))  # button bit 1 high: not pressed
    return str(path)


@pytest.fixture
def helper(tmp_path, fake_mem, monkeypatch):
    sock = str(tmp_path / "hw" / "hw.sock")
    server = hw_helper.serve(sock, fake_mem)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(hw_client, "SOCKET_PATH", sock)
    hw_client.forget()
    yield sock, fake_mem
    server.shutdown()
    server.server_close()
    hw_client.forget()


def test_the_helper_answers_its_four_requests_and_nothing_else(helper):
    sock, mem = helper
    assert oct(os.stat(sock).st_mode & 0o777) == "0o660"
    assert hw_client.call("ping") == {"ok": True}
    assert hw_client.call("fans") == {"rpm": [1200, 1300, 600]}
    assert hw_client.call("button") == {"value": 2}
    assert hw_client.call("pwm", channel=2, value=120) == {"ok": True}
    with open(mem, "rb") as f:
        f.seek(hw_helper.EC_BASE + hw_helper.EC_PWM[2])
        assert f.read(1)[0] == 120
    for bad, words in (
        ({"op": "pwm", "channel": 4, "value": 1}, "channel"),
        ({"op": "pwm", "channel": 1, "value": 999}, "value"),
        ({"op": "pwm", "channel": True, "value": 1}, "channel"),
        ({"op": "peek", "address": 0}, "unknown"),
    ):
        with pytest.raises(hw_client.HelperError, match=words):
            hw_client.call(**bad)


def test_nonsense_and_overlong_requests_are_refused(helper):
    import socket

    sock, _ = helper
    for payload, words in (
        (b"not json\n", b"not JSON"),
        (b"x" * 400 + b"\n", b"too long"),
        (b"[1]\n", b"not a request"),
    ):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(sock)
            s.sendall(payload)
            assert words in s.recv(256)


def test_kiboto_uses_the_helper_when_it_answers_and_not_otherwise(helper, monkeypatch, tmp_path):
    from backend.hardware.fans import ZettlabMmioFanController

    fans = ZettlabMmioFanController(dev_mem_path=str(tmp_path / "nothing-here"))
    assert hw_client.available() and fans.is_available()
    assert fans.read_fans() == [1200, 1300, 600]
    assert fans.write_pwm(1, 500) is True  # clamped to FAN_MAX_PWM before it is sent
    monkeypatch.setattr(hw_client, "SOCKET_PATH", str(tmp_path / "gone.sock"))
    hw_client.forget()
    assert not hw_client.available()
    with pytest.raises(hw_client.HelperError):
        hw_client.call("ping")


def test_the_helper_knows_the_registers_kiboto_documents():
    from backend.hardware.fans import FAN_MAX_PWM
    from backend.hardware.fans import ZettlabMmioFanController as F

    assert hw_helper.EC_BASE == F.PHYS_BASE_ADDR and hw_helper.FAN_MAX_PWM == FAN_MAX_PWM
    assert hw_helper.EC_RPM == (F.OFF_FAN1_RPM, F.OFF_FAN2_RPM, F.OFF_FAN3_RPM)
    assert hw_helper.EC_PWM == {1: F.OFF_FAN1_PWM, 2: F.OFF_FAN2_PWM, 3: F.OFF_FAN3_PWM}
    with open("backend/services/button_listener.py", encoding="utf-8") as fh:
        src = fh.read()
    assert f"MMIO_BASE = 0x{hw_helper.GPIO_BASE:X}" in src and f"COPY_OFFSET = 0x{hw_helper.COPY_OFFSET:X}" in src


def test_an_update_leaves_raw_access_out_while_the_helper_answers_and_puts_it_back_after(helper, tmp_path):
    hc = {
        "CapAdd": ["CAP_SYS_ADMIN", "CAP_SYS_RAWIO"],
        "DeviceCgroupRules": ["c 1:1 rwm", "c 226:* rwm"],
        "Devices": [{"PathOnHost": "/dev/mem"}, {"PathOnHost": "/dev/dri"}],
    }
    out = self_updater.raw_hardware_access(hc, keep=False)
    assert out["CapAdd"] == ["CAP_SYS_ADMIN"] and out["DeviceCgroupRules"] == ["c 226:* rwm"]
    assert out["Devices"] == [{"PathOnHost": "/dev/dri"}]
    back = self_updater.raw_hardware_access(out, keep=True)
    assert "SYS_RAWIO" in back["CapAdd"] and "c 1:1 rwm" in back["DeviceCgroupRules"]
    assert self_updater.raw_hardware_access({}, keep=False)["CapAdd"] is None

    sock, _ = helper
    data = tmp_path / "data"
    (data / "hw").mkdir(parents=True)
    os.symlink(sock, data / "hw" / "hw.sock")
    assert self_updater.raw_hardware_decision(str(data)) is None  # no helper settings: untouched
    (data / "hw_helper.json").write_text(json.dumps({"enabled": True}))
    assert self_updater.raw_hardware_decision(str(data)) is False
    assert json.loads((data / "hw_helper.json").read_text())["dropped"] is True
    (data / "hw_helper.json").write_text(json.dumps({"enabled": False, "dropped": True}))
    assert self_updater.raw_hardware_decision(str(data)) is True
    assert json.loads((data / "hw_helper.json").read_text())["dropped"] is False
    assert self_updater.raw_hardware_decision(None) is None
    (data / "hw_helper.json").write_text("{not json")
    assert self_updater.raw_hardware_decision(str(data)) is None

    inspect = {"Id": "abc", "Config": {"Image": "old", "Env": []}, "HostConfig": dict(hc)}
    body, _ = self_updater.build_recreate_plan(inspect, {}, "new", raw_hw=False)
    assert "CAP_SYS_RAWIO" not in (body["HostConfig"]["CapAdd"] or [])
    body, _ = self_updater.build_recreate_plan(inspect, {}, "new")
    assert "CAP_SYS_RAWIO" in body["HostConfig"]["CapAdd"]  # no helper: untouched


def test_the_helper_container_is_small_and_kept_while_kiboto_lacks_access(tmp_path, monkeypatch):
    from backend.services import hw_helper_container as hc

    calls = []
    state = {"exists": False, "running": False}

    def docker(method, path, body=None, headers=None):
        calls.append((method, path, body, headers))
        if method == "GET" and path.endswith("/json"):
            return (
                (200, {"State": {"Running": state["running"]}, "Config": {"Labels": {}}})
                if state["exists"]
                else (404, None)
            )
        if path.startswith("/containers/create"):
            state["exists"] = True
            return 201, {"Id": "x"}
        if path.endswith("/start"):
            state["running"] = True
        return 204, None

    me = {
        "Config": {"Image": "ghcr.io/x/kiboto:2.0"},
        "Mounts": [{"Destination": hc.DATA_DIR, "Type": "bind", "Source": "/mnt/user/appdata/kiboto"}],
    }
    monkeypatch.setattr(hc, "_docker", docker)
    monkeypatch.setattr(hc, "_self", lambda: me)
    monkeypatch.setattr(hc, "CONFIG_FILE", str(tmp_path / "hw_helper.json"))
    monkeypatch.setattr(hc, "applies", lambda: True)
    monkeypatch.setattr(hc.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(hw_client, "available", lambda force=False: state["running"])

    want = hc.desired(me)
    h = want["HostConfig"]
    assert (
        h["NetworkMode"] == "none" and h["ReadonlyRootfs"] and h["CapDrop"] == ["ALL"] and h["CapAdd"] == ["SYS_RAWIO"]
    )
    assert h["Binds"] == [f"/mnt/user/appdata/kiboto/hw:{hc.SOCKET_DIR_IN_HELPER}"]
    st = hc.save(True)
    create = next(c for c in calls if c[1].startswith("/containers/create"))
    assert create[3] == hc.ELEVATED and st["running"] and st["answering"]
    assert hc.ready()
    # the update left Kiboto without raw access; turning the helper off keeps it until one gives it back
    (tmp_path / "hw_helper.json").write_text(json.dumps({"enabled": True, "dropped": True}))
    st = hc.save(False)
    assert st["kept_until_update"] and state["exists"]
    (tmp_path / "hw_helper.json").write_text(json.dumps({"enabled": False, "dropped": False}))
    hc.ensure()
    assert any(c[0] == "DELETE" for c in calls)
    assert hc.host_data_dir({"Mounts": []}) == ""


@pytest.mark.real_confirmations
def test_turning_it_on_is_confirmed(client, auth_headers):
    assert client.put("/api/hardware/helper", json={"enabled": True}, headers=auth_headers).status_code == 428
    assert client.get("/api/hardware/helper", headers=auth_headers).status_code == 200

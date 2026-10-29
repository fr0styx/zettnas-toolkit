"""FEAT-11: a NUT server for the family's PCs. upsmon on a PC logs in as a secondary, polls
ups.status, and sees FSD when ZettNAS starts its own low-battery shutdown."""

import socket
import threading

import pytest

from backend.services import nut_server as ns

ON_MAINS = {
    "available": True,
    "status": "ONLINE CHARGING",
    "model": "Back-UPS 700",
    "on_battery": False,
    "battery_charge_pct": 88,
    "time_left_min": 42.5,
    "load_pct": 17,
    "line_volts": 230,
    "output_volts": 230,
    "battery_volts": 13.6,
    "power_watts": 60,
    "line_freq_hz": 50,
    "policy_threshold_batt": 20,
    "policy_threshold_runtime": 5,
}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(ns, "SETTINGS_FILE", str(tmp_path / "nut.json"))
    ns.clear_fsd()
    ns.save_settings(enabled=True, port=3493, user="monuser")
    yield ns.settings()
    ns.SERVER.stop()
    ns.clear_fsd()
    ns._LOGINS.clear()


def test_ups_vars():
    v = ns.ups_vars(ON_MAINS)
    assert v["ups.status"] == "OL CHRG" and v["battery.charge"] == "88" and v["battery.runtime"] == "2550"
    assert v["ups.load"] == "17" and v["input.voltage"] == "230" and v["battery.voltage"] == "13.6"
    low = ns.ups_vars({**ON_MAINS, "on_battery": True, "battery_charge_pct": 15}, fsd=True)
    assert low["ups.status"] == "FSD OB LB"
    short = ns.ups_vars({**ON_MAINS, "on_battery": True, "battery_charge_pct": 60, "time_left_min": 4})
    assert short["ups.status"] == "OB LB"
    assert (
        ns.ups_vars({**ON_MAINS, "on_battery": True, "battery_charge_pct": None, "time_left_min": None})["ups.status"]
        == "OB"
    )
    assert ns.ups_vars({"available": False}) == {}
    assert "battery.charge" not in ns.ups_vars({**ON_MAINS, "battery_charge_pct": "n/a"})


def test_home_networks_only():
    nets = list(ns.HOME_NETWORKS)
    assert ns.allowed("192.168.1.20", nets) and ns.allowed("::ffff:10.0.0.5", nets) and ns.allowed("fe80::1%eth0", nets)
    assert not ns.allowed("203.0.113.7", nets) and not ns.allowed("not-an-ip", nets)
    assert not ns.allowed("10.0.0.1", ["bad net"])


def test_settings_and_password(cfg):
    assert cfg["enabled"] and cfg["password"]  # a password is made on first save, sealed
    pub = ns.public()
    assert "password" not in pub and pub["has_password"] is True and pub["running"] is False
    shown = ns.public(show_password=True)
    assert shown["upsmon"] == f"MONITOR ups@NAS-ADDRESS:3493 1 monuser {shown['password']} secondary"
    old = cfg["password"]
    ns.save_settings(new_password=True)
    assert ns.settings()["password"] != old
    with pytest.raises(ValueError, match="port"):
        ns.save_settings(port=0)
    with pytest.raises(ValueError, match="user name"):
        ns.save_settings(user="no spaces")


def _session(cfg, status=ON_MAINS):
    return ns.Session(cfg, lambda: status)


def test_the_protocol(cfg):
    s = _session(cfg)
    password = ns._password(cfg)
    assert s.handle("VER")[0] == [ns.VERSION]
    assert s.handle("NETVER")[0] == ["1.3"]
    assert s.handle("HELP")[0][0].startswith("Commands:")
    assert s.handle("")[0] == []
    assert s.handle("STARTTLS")[0] == ["ERR FEATURE-NOT-CONFIGURED"]
    assert s.handle("LIST UPS")[0] == ["BEGIN LIST UPS", 'UPS ups "ZettNAS UPS"', "END LIST UPS"]
    listing = s.handle("LIST VAR ups")[0]
    assert listing[0] == "BEGIN LIST VAR ups" and 'VAR ups ups.status "OL CHRG"' in listing
    assert s.handle("LIST VAR other")[0] == ["ERR UNKNOWN-UPS"]
    assert s.handle("GET VAR ups battery.charge")[0] == ['VAR ups battery.charge "88"']
    assert s.handle("GET VAR ups nothing.here")[0] == ["ERR VAR-NOT-SUPPORTED"]
    assert s.handle("GET VAR other ups.status")[0] == ["ERR UNKNOWN-UPS"]
    assert s.handle("GET UPSDESC ups")[0] == ['UPSDESC ups "ZettNAS UPS"']
    assert s.handle("GET SOMETHING ups")[0] == ["ERR INVALID-ARGUMENT"]
    assert s.handle("LOGIN ups")[0] == ["ERR USERNAME-REQUIRED"]
    assert s.handle("USERNAME")[0] == ["ERR INVALID-ARGUMENT"]
    assert s.handle("USERNAME monuser")[0] == ["OK"]
    assert s.handle("LOGIN ups")[0] == ["ERR PASSWORD-REQUIRED"]
    assert s.handle("PASSWORD")[0] == ["ERR INVALID-ARGUMENT"]
    assert s.handle("PASSWORD wrong")[0] == ["OK"]
    assert s.handle("LOGIN ups")[0] == ["ERR ACCESS-DENIED"]
    s.handle(f"PASSWORD {password}")
    assert s.handle("LOGIN nope")[0] == ["ERR UNKNOWN-UPS"]
    assert s.handle("LOGIN ups")[0] == ["OK"] and ns.logins() == 1
    assert s.handle("GET NUMLOGINS ups")[0] == ["NUMLOGINS ups 1"]
    assert s.handle("LOGIN ups")[0] == ["ERR ALREADY-LOGGED-IN"]
    for cmd in ("FSD ups", "PRIMARY ups", "MASTER ups", "INSTCMD ups beeper.off", "SET VAR ups x 1"):
        assert s.handle(cmd)[0] == ["ERR ACCESS-DENIED"]
    assert s.handle("WHATEVER")[0] == ["ERR UNKNOWN-COMMAND"]
    assert s.handle("LOGOUT") == (["OK Goodbye"], True)
    s.close()
    assert ns.logins() == 0


def test_no_ups_reading_is_stale_data(cfg):
    s = _session(cfg, {"available": False})
    assert s.handle("GET VAR ups ups.status")[0] == ["ERR DATA-STALE"]
    assert s.handle("LIST VAR ups")[0] == ["ERR DATA-STALE"]


def _talk(port, *lines):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        f = c.makefile("rw", encoding="utf-8", newline="\n")
        out = []
        for line in lines:
            f.write(line + "\n")
            f.flush()
            out.append(f.readline().strip())
        return out


def test_a_pc_logs_in_and_polls_over_tcp(cfg):
    port = ns.SERVER.start({**cfg, "port": 0}, status=lambda: ON_MAINS, host="127.0.0.1")
    assert ns.SERVER.running() and port
    password = ns._password(cfg)
    got = _talk(port, "USERNAME monuser", f"PASSWORD {password}", "LOGIN ups", "GET VAR ups ups.status", "LOGOUT")
    assert got == ["OK", "OK", "OK", 'VAR ups ups.status "OL CHRG"', "OK Goodbye"]
    ns.SERVER.stop()
    assert not ns.SERVER.running()


def test_other_networks_are_turned_away(cfg):
    port = ns.SERVER.start({**cfg, "port": 0, "networks": ["10.0.0.0/8"]}, status=lambda: ON_MAINS, host="127.0.0.1")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        try:
            c.sendall(b"VER\n")
            answer = c.recv(100)
        except ConnectionError:
            answer = b""
        assert answer == b""  # closed without an answer


def test_forced_shutdown_waits_for_the_pcs(cfg):
    assert ns.forced_shutdown() == 0  # not serving: nothing to wait for
    ns.clear_fsd()
    port = ns.SERVER.start(
        {**cfg, "port": 0}, status=lambda: {**ON_MAINS, "on_battery": True, "battery_charge_pct": 10}, host="127.0.0.1"
    )
    password = ns._password(cfg)
    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    f = c.makefile("rw", encoding="utf-8", newline="\n")
    for line in ("USERNAME monuser", f"PASSWORD {password}", "LOGIN ups"):
        f.write(line + "\n")
        f.flush()
        f.readline()
    assert ns.logins() == 1

    def pc_sees_fsd_and_leaves():
        while True:
            f.write("GET VAR ups ups.status\n")
            f.flush()
            if "FSD" in f.readline():
                f.write("LOGOUT\n")
                f.flush()
                f.readline()
                return

    t = threading.Thread(target=pc_sees_fsd_and_leaves)
    t.start()
    assert ns.forced_shutdown(wait=10) == 0
    t.join(5)
    c.close()
    assert ns.public()["fsd"] is True


def test_forced_shutdown_gives_up_after_the_wait(cfg, monkeypatch):
    monkeypatch.setattr(ns.SERVER, "running", lambda: True)
    ns._LOGINS.add(1)
    ticks = iter([0.0, 0.0, 20.0])
    assert ns.forced_shutdown(wait=15, clock=lambda: next(ticks), sleep=lambda s: None) == 1


def test_apply_and_a_taken_port(cfg, monkeypatch):
    busy = socket.socket()
    busy.bind(("0.0.0.0", 0))
    busy.listen(1)
    taken = busy.getsockname()[1]
    try:
        ns.save_settings(port=taken)
        with pytest.raises(ValueError, match=f"Port {taken} is in use"):
            ns.apply()
        ns.start_if_enabled()  # logged, not raised
    finally:
        busy.close()
    ns.save_settings(enabled=False)
    assert ns.apply()["running"] is False


def test_api(client, auth_headers, cfg, monkeypatch):
    monkeypatch.setattr(ns, "apply", lambda: ns.public())
    res = client.get("/api/ups/nut-server", headers=auth_headers).json()
    assert res["enabled"] is True and "password" not in res
    res = client.put("/api/ups/nut-server", json={"port": 13493, "user": "family"}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["port"] == 13493
    assert client.put("/api/ups/nut-server", json={"user": "bad user"}, headers=auth_headers).status_code == 400
    shown = client.get("/api/ups/nut-server/client", headers=auth_headers).json()
    assert shown["upsmon"].startswith("MONITOR ups@NAS-ADDRESS:13493 1 family ")


def test_the_watchdog_raises_fsd_first(monkeypatch):
    from backend.services import ups_watchdog as wd

    order = []
    monkeypatch.setattr(wd, "nut_forced_shutdown", lambda: order.append("fsd"))
    monkeypatch.setattr(wd, "graceful_docker_teardown", lambda timeout_sec=30: order.append("apps") or {})
    monkeypatch.setattr(wd, "shutdown_owner", lambda: "unraid")
    monkeypatch.setattr(wd, "log_ups_event", lambda **kw: None)
    monkeypatch.setattr(wd.os, "sync", lambda: None)
    monkeypatch.setattr(wd, "_failsafe_engaged", False)
    wd.execute_atomic_failsafe_shutdown(10, 2, "battery low")
    assert order[:2] == ["fsd", "apps"]

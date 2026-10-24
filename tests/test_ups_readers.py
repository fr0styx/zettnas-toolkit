"""UPS readers: NUT and apcupsd over TCP, their command-line tools, USB HID and sysfs, discovery."""

import socket
import subprocess
import threading

import pytest

from backend.hardware import ups


class FakeServer:
    """A one-shot TCP server answering each received line from a script."""

    def __init__(self, respond):
        self.respond = respond
        self.received = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                self.respond(conn, self)

    def close(self):
        self.sock.close()


def nut_responder(ups_name="myups", vars_=None, list_ups=None, unknown_first=False):
    vars_ = vars_ or {}

    def respond(conn, srv):
        buf = b""
        first_var = True
        while True:
            try:
                chunk = conn.recv(1024)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode()
                srv.received.append(cmd)
                if cmd.startswith(("USERNAME", "PASSWORD")):
                    conn.sendall(b"OK\n")
                elif cmd == "LIST UPS":
                    names = list_ups or [ups_name]
                    body = "BEGIN LIST UPS\n" + "".join(f'UPS {n} "desc"\n' for n in names) + "END LIST UPS\n"
                    conn.sendall(body.encode())
                elif cmd.startswith("LIST VAR"):
                    name = cmd.split()[2]
                    if unknown_first and first_var:
                        first_var = False
                        conn.sendall(b"ERR UNKNOWN-UPS\n")
                        continue
                    body = f"BEGIN LIST VAR {name}\n" + "".join(f'VAR {name} {k} "{v}"\n' for k, v in vars_.items())
                    conn.sendall((body + f"END LIST VAR {name}\n").encode())
                elif cmd.startswith("INSTCMD"):
                    conn.sendall(b"OK\n")
                elif cmd == "LOGOUT":
                    conn.sendall(b"OK Goodbye\n")
                    return

    return respond


NUT_VARS = {
    "battery.charge": "87",
    "battery.runtime": "1800",
    "ups.load": "23",
    "input.voltage": "231.0",
    "output.voltage": "230.0",
    "output.voltage.nominal": "230",
    "output.current": "1.2",
    "battery.current": "0.4",
    "ups.realpower": "180",
    "ups.power": "210",
    "battery.voltage": "13.5",
    "ups.status": "OL CHRG",
    "ups.model": "Back-UPS 900",
    "ups.mfr": "APC",
    "ups.realpower.nominal": "540",
    "battery.temperature": "29",
    "input.frequency": "50.0",
}


class TestNutSocket:
    def test_reads_and_maps_the_variables(self):
        srv = FakeServer(nut_responder("myups", NUT_VARS))
        try:
            out = ups._query_nut_socket("127.0.0.1", srv.port, ups_name="myups", username="mon", password="pw")
        finally:
            srv.close()
        assert out["BCHARGE"] == "87" and out["TIMELEFT"] == "30.0" and out["LOADPCT"] == "23"
        assert out["LINEV"] == "231.0" and out["STATUS"] == "OL CHRG" and out["MODEL"] == "Back-UPS 900"
        assert out["NOMPOWER"] == "540" and out["ITEMP"] == "29" and out["LINEFREQ"] == "50.0"
        assert srv.received[:2] == ["USERNAME mon", "PASSWORD pw"]

    def test_discovers_the_ups_name(self):
        srv = FakeServer(nut_responder("found", {"battery.charge": "50"}))
        try:
            out = ups._query_nut_socket("127.0.0.1", srv.port)
        finally:
            srv.close()
        assert out == {"BCHARGE": "50", "UPSNAME": "found"}

    def test_recovers_from_a_wrong_name(self):
        srv = FakeServer(nut_responder("real", {"battery.charge": "70"}, unknown_first=True))
        try:
            out = ups._query_nut_socket("127.0.0.1", srv.port, ups_name="wrong")
        finally:
            srv.close()
        assert out["BCHARGE"] == "70"

    def test_unreachable(self):
        assert ups._query_nut_socket("127.0.0.1", 1, timeout=0.2) == {}


def test_apcupsd_nis_protocol():
    lines = ["STATUS   : ONLINE", "BCHARGE  : 100.0 Percent", "MODEL    : Smart-UPS 750"]

    def respond(conn, srv):
        size = int.from_bytes(conn.recv(2), "big")
        srv.received.append(conn.recv(size))
        for ln in lines:
            data = ln.encode()
            conn.sendall(len(data).to_bytes(2, "big") + data)
        conn.sendall(b"\x00\x00")

    srv = FakeServer(respond)
    try:
        out = ups._query_apcupsd_socket("127.0.0.1", srv.port)
    finally:
        srv.close()
    assert srv.received == [b"status"]
    assert out == {"STATUS": "ONLINE", "BCHARGE": "100.0 Percent", "MODEL": "Smart-UPS 750"}


class TestCommandLineTools:
    def fake_run(self, monkeypatch, stdout, code=0):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            if cmd[0].startswith("/"):
                raise FileNotFoundError(cmd[0])
            return subprocess.CompletedProcess(cmd, code, stdout, "")

        monkeypatch.setattr(ups.subprocess, "run", run)
        return calls

    def test_upsc(self, monkeypatch):
        text = "\n".join(f"{k}: {v}" for k, v in NUT_VARS.items()) + "\nbattery.runtime.low: x\n"
        calls = self.fake_run(monkeypatch, text)
        out = ups._query_nut_cli("myups")
        assert out["BCHARGE"] == "87" and out["MFR"] == "APC" and calls[-1] == ["upsc", "myups"]

    def test_apcaccess(self, monkeypatch):
        self.fake_run(monkeypatch, "STATUS : ONBATT\nTIMELEFT : 12.0 Minutes\n")
        assert ups._query_apcaccess_cli() == {"STATUS": "ONBATT", "TIMELEFT": "12.0 Minutes"}

    def test_not_installed(self, monkeypatch):
        self.fake_run(monkeypatch, "", code=1)
        assert ups._query_nut_cli() == {} and ups._query_apcaccess_cli() == {}


def test_host_nut_config(tmp_path):
    (tmp_path / "ups.conf").write_text("[default]\n[rackups]\n  driver = usbhid-ups\n")
    (tmp_path / "upsmon.conf").write_text("# monitor\nMONITOR rackups@192.168.5.2:3494 1 monuser secret primary\n")
    cfg = ups._detect_host_nut_config([str(tmp_path)])
    assert cfg == {
        "enabled": True,
        "mode": "nut_client",
        "host": "192.168.5.2",
        "port": 3494,
        "ups_name": "rackups",
        "username": "monuser",
        "password": "secret",
    }
    assert ups._detect_host_nut_config([str(tmp_path / "none")]) is None


def test_docker_gateway(tmp_path, monkeypatch):
    route = tmp_path / "route"
    # default route via 172.17.0.1 (hex little endian 010011AC)
    route.write_text("Iface\tDestination\tGateway\neth0\t00000000\t010011AC\n")
    monkeypatch.setattr(ups, "PROC_NET_ROUTE", str(route))
    assert ups._get_docker_gateway() == "172.17.0.1"
    route.write_text("Iface\tDestination\tGateway\neth0\t00000000\t0101A8C0\n")  # 192.168.1.1: LAN, not docker
    assert ups._get_docker_gateway() is None


def hid_descriptor():
    """A HID descriptor with RemainingCapacity, RunTimeToEmpty, Voltage, PercentLoad, Current, ACPresent,
    Discharging and Charging as feature reports 1..8."""
    out = bytearray()
    items = [
        (0x85, 0x66),
        (0x85, 0x68),
        (0x84, 0x30),
        (0x84, 0x24),
        (0x84, 0x58),
        (0x84, 0xD0),
        (0x84, 0xD2),
        (0x84, 0xD1),
    ]
    for rid, (page, usage) in enumerate(items, start=1):
        out += bytes([0x05, page])  # Usage Page
        out += bytes([0x85, rid])  # Report ID
        out += bytes([0x75, 16, 0x95, 1])  # Report Size 16, Count 1
        out += bytes([0x09, usage])  # Usage
        out += bytes([0xB1, 0x02])  # Feature
    out += bytes([0xFE, 0x00, 0x00, 0x00])  # a long item is skipped
    return bytes(out)


class FakeIoctl:
    def __init__(self, reports):
        self.reports = reports

    def ioctl(self, fd, req, buf):
        rid = buf[0]
        if rid not in self.reports:
            raise OSError("no report")
        data = self.reports[rid]
        buf[1 : 1 + len(data)] = data


class TestHid:
    def test_descriptor_mapping(self):
        mapping = ups._parse_hid_report_descriptor(hid_descriptor())
        assert mapping[(0x85, 0x66)] == (1, 16, 1) and mapping[(0x84, 0xD1)] == (8, 16, 1)

    def test_reads_the_reports(self, monkeypatch):
        reports = {
            1: bytes([88]),
            2: bytes([0, 0x08, 0x07]),
            3: bytes([0xE6, 0x00]),
            4: bytes([31]),
            5: bytes([0xD0, 0x07]),
            6: bytes([1]),
            7: bytes([0]),
            8: bytes([1]),
        }
        monkeypatch.setattr(ups, "fcntl", FakeIoctl(reports))
        out = ups._read_hid_reports(3, ups._parse_hid_report_descriptor(hid_descriptor()), "051d", "0002", "Back-UPS")
        assert out["BCHARGE"] == "88" and out["LINEV"] == "230" and out["LOADPCT"] == "31"
        assert out["OUTCURR"] == "2.0" and out["STATUS"] == "ONLINE CHRG" and out["MFR"].startswith("American Power")

    def test_on_battery(self, monkeypatch):
        monkeypatch.setattr(ups, "fcntl", FakeIoctl({6: bytes([0]), 7: bytes([1])}))
        out = ups._read_hid_reports(3, ups._parse_hid_report_descriptor(hid_descriptor()), "0000", "0000", "")
        assert out["STATUS"] == "OB" and out["MODEL"] == "USB HID UPS"


@pytest.fixture
def sysfs(tmp_path, monkeypatch):
    for name in ("PSY_ROOTS", "HIDRAW_ROOTS", "USB_DEVICE_ROOTS"):
        monkeypatch.setattr(ups, name, (str(tmp_path / name),))
    monkeypatch.setattr(ups, "DEV_ROOTS", (str(tmp_path / "dev"),))
    monkeypatch.setattr(ups, "_HID_UPS_CACHE", {})
    return tmp_path


def write(path, **files):
    path.mkdir(parents=True, exist_ok=True)
    for k, v in files.items():
        (path / k).write_text(v)


class TestDirectUsb:
    def test_power_supply_class(self, sysfs):
        write(
            sysfs / "PSY_ROOTS" / "ups0",
            type="UPS",
            capacity="64",
            status="Discharging",
            voltage_now="13500000",
            current_now="-1500000",
            power_now="20000000",
            time_to_empty_now="900",
            model_name="Eco 650",
            manufacturer="Eaton",
        )
        out = ups._query_direct_usb()
        assert out["BCHARGE"] == "64" and out["STATUS"] == "OB" and out["BATTV"] == "13.5"
        assert out["OUTCURR"] == "1.5" and out["REALPOWER"] == "20.0" and out["TIMELEFT"] == "15.0"
        assert out["PROTOCOL"] == "direct_usb_sysfs"

    def test_power_supply_online_flag(self, sysfs):
        write(sysfs / "PSY_ROOTS" / "battery0", capacity="99", online="1")
        assert ups._query_direct_usb()["STATUS"] == "ONLINE"

    def test_hidraw_device(self, sysfs, monkeypatch):
        node = sysfs / "HIDRAW_ROOTS" / "hidraw0" / "device"
        write(node, uevent="HID_ID=0003:0000051D:00000002\nHID_NAME=APC Back-UPS\n")
        (node / "report_descriptor").write_bytes(hid_descriptor())
        write(sysfs / "dev", hidraw0="")
        monkeypatch.setattr(ups, "fcntl", FakeIoctl({1: bytes([77]), 6: bytes([1])}))
        out = ups._query_direct_usb()
        assert out["BCHARGE"] == "77" and out["PROTOCOL"] == "direct_usb_hid"
        assert ups._HID_UPS_CACHE["vid"] == "051d"
        assert ups._cached_hid_ups()["BCHARGE"] == "77"  # the next poll skips the scan

    def test_hidraw_without_permission(self, sysfs, monkeypatch):
        node = sysfs / "HIDRAW_ROOTS" / "hidraw0" / "device"
        write(node, uevent="HID_ID=0003:00000764:00000501\nHID_NAME=CPS UPS\n")
        (node / "report_descriptor").write_bytes(hid_descriptor())
        write(sysfs / "dev", hidraw0="")
        monkeypatch.setattr(ups, "fcntl", FakeIoctl({}))

        def deny(path, flags):
            raise PermissionError(path)

        monkeypatch.setattr(ups.os, "open", deny)
        out = ups._query_direct_usb()
        assert out["STATUS"] == "PERMISSION_REQUIRED" and out["VENDOR_ID"] == "0764"

    def test_usb_device_without_a_driver(self, sysfs):
        write(
            sysfs / "USB_DEVICE_ROOTS" / "1-1",
            idVendor="0463",
            idProduct="ffff",
            product="Ellipse ECO",
            manufacturer="EATON",
        )
        write(sysfs / "USB_DEVICE_ROOTS" / "1-2", idVendor="046d", idProduct="c52b", product="Unifying Receiver")
        out = ups._query_direct_usb()
        assert out["STATUS"] == "ACTION_REQUIRED" and out["MODEL"] == "Ellipse ECO"

    def test_nothing_connected(self, sysfs):
        assert ups._query_direct_usb() == {}

    def test_discovery_lists_usb_ups(self, sysfs, monkeypatch):
        write(
            sysfs / "USB_DEVICE_ROOTS" / "1-1",
            idVendor="051d",
            idProduct="0002",
            product="Back-UPS",
            manufacturer="APC",
        )
        monkeypatch.setattr(ups, "_query_nut_socket", lambda *a, **k: {})
        monkeypatch.setattr(ups, "_query_apcupsd_socket", lambda *a, **k: {})
        monkeypatch.setattr(ups, "_get_docker_gateway", lambda: None)
        found = ups.discover_ups_sources()
        assert any(c.get("vendor_id") == "051d" or "Back-UPS" in str(c) for c in found)


class TestConnectionTest:
    def test_refuses_link_local(self):
        r = ups.test_ups_connection(host="169.254.169.254", port=3551)
        assert not r["success"] and "forbidden" in r["error"]

    def test_nut(self):
        srv = FakeServer(nut_responder("myups", {"battery.charge": "81", "ups.status": "OL"}))
        try:
            r = ups.test_ups_connection(host="127.0.0.1", port=srv.port, mode="nut", ups_name="myups")
        finally:
            srv.close()
        assert r["connected"] and r["battery_charge_pct"] == 81.0 and r["status"] == "OL"

    def test_usb(self, monkeypatch):
        monkeypatch.setattr(ups, "_query_direct_usb", lambda: {"BCHARGE": "55", "MODEL": "X"})
        assert ups.test_ups_connection(mode="usb")["battery_charge_pct"] == 55.0
        monkeypatch.setattr(ups, "_query_direct_usb", lambda: {"PERMISSION_ERROR": True, "ERROR": "denied"})
        assert ups.test_ups_connection(mode="usb")["error"] == "denied"
        monkeypatch.setattr(ups, "_query_direct_usb", lambda: {})
        assert not ups.test_ups_connection(mode="usb")["success"]

    def test_unreachable_apcupsd(self, monkeypatch):
        monkeypatch.setattr(ups, "_query_apcaccess_cli", lambda: {})
        monkeypatch.setattr(ups, "_get_docker_gateway", lambda: None)
        r = ups.test_ups_connection(host="127.0.0.1", port=1, mode="apcupsd")
        assert not r["success"] and "Unable to reach" in r["error"]


def test_self_test_over_nut(monkeypatch):
    srv = FakeServer(nut_responder("myups", {"battery.charge": "90"}))
    logged = []
    monkeypatch.setattr(
        ups,
        "load_ups_config",
        lambda: {
            "mode": "nut",
            "host": "127.0.0.1",
            "port": srv.port,
            "ups_name": "myups",
            "username": "u",
            "password": "p",
        },
    )
    monkeypatch.setattr(ups, "read_ups_status", lambda force=False: {"battery_charge_pct": 90, "status": "ONLINE"})
    monkeypatch.setattr(ups, "log_ups_event", lambda **kw: logged.append(kw))
    try:
        r = ups.run_ups_self_test()
    finally:
        srv.close()
    assert r["success"] and "accepted" in r["message"] and logged[0]["status"] == "PASSED"
    assert any(c.startswith("INSTCMD myups test.battery.start.quick") for c in srv.received)

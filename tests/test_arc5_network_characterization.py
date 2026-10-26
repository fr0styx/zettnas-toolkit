"""ARC-5: the network module keeps its names and behaviour while it is split up.

Records, from backend.hardware.network: every name it defines (with signatures) and, on a
fake host (a sysfs and proc tree, Unraid's network.cfg, resolv.conf, fake ip/ethtool/wg/
tailscale commands and a fake Docker API), what each function returns and which commands it
runs: interfaces and routes, host IP changes with their canary, port settings, VLANs, bonds,
bridges, the topology, traffic rates, Tailscale (natively and in a container), WireGuard, IP
forwarding and listening ports. tests/golden/network.json was recorded before the module
became a package; the facade must still provide all of it. Regenerate only for an intended
change:

    ZETTNAS_UPDATE_GOLDEN=1 pytest tests/test_arc5_network_characterization.py
"""

import inspect
import json
import os
import re
import subprocess
import sys
import threading
import types

import httpx
import pytest

from backend.hardware import network as net

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "network.json")
OWN = ("backend.hardware.network", "backend.hardware.net")


def _signature(obj):
    try:
        sig = str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "?"
    sig = re.sub(r" at 0x[0-9a-f]+", "", sig)
    return re.sub(r"backend\.hardware\.net(work)?(\.\w+)*?\.(?=[A-Z])", "", sig)  # where a type lives may change


def _surface():
    out = {}
    for name in sorted(vars(net)):
        if name.startswith("__"):
            continue
        obj = getattr(net, name)
        if isinstance(obj, types.ModuleType):
            continue
        mod = getattr(obj, "__module__", None) or ""
        if inspect.isclass(obj) and mod.startswith(OWN):
            out[name] = {"class": {m: _signature(f) for m, f in sorted(vars(obj).items()) if inspect.isfunction(f)}}
        elif inspect.isfunction(obj) and mod.startswith(OWN):
            out[name] = {"function": _signature(obj)}
        elif name.isupper() and isinstance(obj, (int, str, tuple, dict, list)):
            out[name] = {"value": json.loads(json.dumps(obj, default=str))}
    return out


# --- the fake host -----------------------------------------------------------------------------
IFACES = {
    "lo": {"operstate": "unknown", "address": "00:00:00:00:00:00", "mtu": "65536", "type": "772"},
    "eth0": {
        "operstate": "up",
        "address": "aa:bb:cc:00:00:01",
        "mtu": "1500",
        "speed": "1000",
        "duplex": "full",
        "carrier": "1",
        "master": "bond0",
        "device/uevent": "DRIVER=igc\nPCI_SLOT_NAME=0000:01:00.0\n",
    },
    "eth1": {
        "operstate": "up",
        "address": "aa:bb:cc:00:00:02",
        "mtu": "1500",
        "speed": "2500",
        "duplex": "full",
        "carrier": "1",
        "master": "bond0",
        "device/uevent": "DRIVER=igc\n",
    },
    "eth2": {
        "operstate": "down",
        "address": "aa:bb:cc:00:00:03",
        "mtu": "9000",
        "speed": "-1",
        "carrier": "0",
        "device/uevent": "DRIVER=r8169\n",
    },
    "bond0": {
        "operstate": "up",
        "address": "aa:bb:cc:00:00:01",
        "mtu": "1500",
        "speed": "3500",
        "carrier": "1",
        "master": "br0",
        "bonding/mode": "802.3ad 4",
        "bonding/slaves": "eth0 eth1",
        "bonding/miimon": "100",
        "bonding/active_slave": "",
        "bonding/xmit_hash_policy": "layer3+4 1",
        "bonding/lacp_rate": "fast 1",
        "bonding/ad_num_ports": "2",
        "uevent": "DEVTYPE=bond\nINTERFACE=bond0\n",
    },
    "br0": {
        "operstate": "up",
        "address": "aa:bb:cc:00:00:01",
        "mtu": "1500",
        "carrier": "1",
        "bridge/stp_state": "0",
        "bridge/forward_delay": "1500",
        "brif/bond0": "",
        "brif/vnet0": "",
        "uevent": "DEVTYPE=bridge\nINTERFACE=br0\n",
    },
    "br0.20": {
        "operstate": "up",
        "address": "aa:bb:cc:00:00:01",
        "mtu": "1500",
        "carrier": "1",
        "uevent": "DEVTYPE=vlan\nINTERFACE=br0.20\n",
    },
    "docker0": {
        "operstate": "down",
        "address": "02:42:00:00:00:01",
        "mtu": "1500",
        "carrier": "0",
        "bridge/stp_state": "0",
        "uevent": "DEVTYPE=bridge\n",
    },
    "vnet0": {"operstate": "up", "address": "fe:54:00:00:00:01", "mtu": "1500", "carrier": "1", "master": "br0"},
    "wg0": {"operstate": "unknown", "address": "", "mtu": "1420", "type": "65534"},
    "tailscale0": {"operstate": "unknown", "address": "", "mtu": "1280", "type": "65534"},
}
STATS = {
    "rx_bytes": 123456789,
    "tx_bytes": 987654321,
    "rx_packets": 1000,
    "tx_packets": 2000,
    "rx_errors": 1,
    "tx_errors": 0,
    "rx_dropped": 2,
    "tx_dropped": 0,
}
ROUTE = (
    "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
    "br0\t00000000\t0101A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
    "br0\t0001A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
    "docker0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"
)
VLAN_CONFIG = "VLAN Dev name | VLAN ID\nName-Type: VLAN_NAME_TYPE_RAW_PLUS_VID_NO_PAD\nbr0.20 | 20 | br0\n"
DEV = (
    "Inter-|   Receive                                                |  Transmit\n"
    " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
    "    lo: 1000 10 0 0 0 0 0 0 1000 10 0 0 0 0 0 0\n"
    "  eth0: 123456789 1000 1 2 0 0 0 0 987654321 2000 0 0 0 0 0 0\n"
    "   br0: 5000000 400 0 0 0 0 0 0 7000000 500 0 0 0 0 0 0\n"
)
FIB_TRIE = "Main:\n  +-- 0.0.0.0/0 3 0 5\n     |-- 192.168.1.0\n        /24 link UNICAST\n     |-- 192.168.1.10\n        /32 host LOCAL\n"
TCP = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    "   0: 00000000:1F92 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1\n"
    "   1: 0100007F:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 2\n"
    "   2: 0A01A8C0:C350 0B01A8C0:01BB 01 00000000:00000000 00:00000000 00000000     0        0 3\n"
)
TCP6 = (
    "  sl  local_address                         remote_address                        st\n"
    "   0: 00000000000000000000000000000000:01BD 00000000000000000000000000000000:0000 0A 0 0 0\n"
)
UDP = (
    "  sl  local_address rem_address   st\n"
    "   0: 00000000:CA6C 00000000:0000 07 0 0 0\n"
    "   1: 00000000:14E9 00000000:0000 07 0 0 0\n"
)
UNRAID_CFG = (
    '# Generated settings:\nIFNAME[0]="br0"\nBONDNAME[0]="bond0"\nBONDING_MODE[0]="4"\nBRNAME[0]="br0"\n'
    'BRSTP[0]="no"\nDESCRIPTION[0]="Main LAN"\nUSE_DHCP[0]="no"\nIPADDR[0]="192.168.1.10"\nNETMASK[0]="255.255.255.0"\n'
    'GATEWAY="192.168.1.1"\nDNS_SERVER1="192.168.1.1"\nDNS_SERVER2="1.1.1.1"\nDHCP_KEEPRESOLV="yes"\nMTU[0]="1500"\n'
    'DESCRIPTION[1]="Backup NIC"\nSYSNICS="2"\n'
)
RESOLV = "# resolv\nnameserver 192.168.1.1\nnameserver 9.9.9.9\nsearch lan\n"
ETHTOOL = (
    "Settings for eth0:\n\tSupported link modes:   10baseT/Full 100baseT/Full 1000baseT/Full\n"
    "\tSpeed: 1000Mb/s\n\tDuplex: Full\n\tAuto-negotiation: on\n\tSupports Wake-on: pumbg\n\tWake-on: g\n\tLink detected: yes\n"
)
TS_STATUS = {
    "BackendState": "Running",
    "Self": {
        "HostName": "nas",
        "DNSName": "nas.tail1234.ts.net.",
        "TailscaleIPs": ["100.64.0.1", "fd7a::1"],
        "Online": True,
        "OS": "linux",
        "ExitNodeOption": False,
        "PrimaryRoutes": ["192.168.1.0/24"],
    },
    "Peer": {
        "nodekey:1": {
            "HostName": "laptop",
            "DNSName": "laptop.tail1234.ts.net.",
            "TailscaleIPs": ["100.64.0.2"],
            "Online": True,
            "OS": "macOS",
            "ExitNode": False,
            "ExitNodeOption": True,
            "RxBytes": 1000,
            "TxBytes": 2000,
            "LastSeen": "2026-10-20T10:00:00Z",
            "Relay": "fra",
        },
        "nodekey:2": {
            "HostName": "phone",
            "DNSName": "phone.tail1234.ts.net.",
            "TailscaleIPs": ["100.64.0.3"],
            "Online": False,
            "OS": "iOS",
            "LastSeen": "2026-10-19T10:00:00Z",
        },
    },
    "CurrentTailnet": {"Name": "example.org", "MagicDNSSuffix": "tail1234.ts.net"},
    "MagicDNSSuffix": "tail1234.ts.net",
}
WG_DUMP = (
    "wg0\tPRIVKEY=\tSERVERPUB=\t51820\toff\n"
    "wg0\tPEERPUB1=\t(none)\t203.0.113.5:51820\t10.13.13.2/32\t1792000000\t1024\t2048\t25\n"
    "wg0\tPEERPUB2=\t(none)\t(none)\t10.13.13.3/32\t0\t0\t0\toff\n"
)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _build_host(root):
    sysnet = os.path.join(root, "sys", "class", "net")
    for iface, files in IFACES.items():
        d = os.path.join(sysnet, iface)
        os.makedirs(os.path.join(d, "statistics"), exist_ok=True)
        for k, v in STATS.items():
            _write(os.path.join(d, "statistics", k), f"{v}\n")
        for name, text in files.items():
            if name == "master":
                os.symlink(os.path.join("..", text), os.path.join(d, "master"))
            elif name.startswith("brif/"):
                os.makedirs(os.path.join(d, name), exist_ok=True)
            else:
                _write(os.path.join(d, name), f"{text}\n" if not text.endswith("\n") else text)
    proc = os.path.join(root, "proc")
    for name, text in (
        ("route", ROUTE),
        ("vlan/config", VLAN_CONFIG),
        ("dev", DEV),
        ("fib_trie", FIB_TRIE),
        ("tcp", TCP),
        ("tcp6", TCP6),
        ("udp", UDP),
        ("udp6", "  sl  local_address\n"),
    ):
        _write(os.path.join(proc, "net", name), text)
    _write(os.path.join(proc, "sys", "net", "ipv4", "ip_forward"), "1\n")
    _write(os.path.join(root, "boot", "network.cfg"), UNRAID_CFG)
    _write(os.path.join(root, "etc", "resolv.conf"), RESOLV)
    _write(os.path.join(root, "etc", "interfaces"), "auto br0\niface br0 inet static\n    address 192.168.1.10\n")
    os.makedirs(os.path.join(root, "taildrop"), exist_ok=True)
    _write(os.path.join(root, "taildrop", "holiday.jpg"), "jpeg")
    return sysnet, proc


class _Host:
    """Fake commands, Docker API and timers; every call is logged."""

    def __init__(self, root):
        self.root = root
        self.calls = []
        self.container = None  # None: no tailscale container; "running" / "exited"
        self.ts_status = json.dumps(TS_STATUS)

    def run(self, argv, *args, **kwargs):
        cmd = [str(a) for a in (argv if isinstance(argv, (list, tuple)) else [argv])]
        self.calls.append(["run", *cmd])
        line = " ".join(cmd)
        out, rc = "", 0
        if "status --json" in line:
            out = self.ts_status
        elif re.search(r"tailscale (ip|--version)", line):
            out = "100.64.0.1\n" if " ip" in line else "1.80.0\n"
        elif "tailscale ping" in line:
            out = "pong from laptop (100.64.0.2) via 203.0.113.5:41641 in 12ms\n"
        elif "serve status" in line or "funnel status" in line:
            out = "https://nas.tail1234.ts.net (tailnet only)\n|-- / proxy http://127.0.0.1:8082\n"
        elif "tailscale" in line:
            out = "Success.\n"
        elif "wg show interfaces" in line:
            out = "wg0\n"
        elif "wg show all dump" in line:
            out = WG_DUMP
        elif cmd[-1:] == ["genkey"] or line.endswith("wg genkey"):
            out = "cHJpdmF0ZWtleXByaXZhdGVrZXlwcml2YXRla2V5MDA=\n"
        elif "pubkey" in line:
            out = "cHVibGlja2V5cHVibGlja2V5cHVibGlja2V5MDAwMDA=\n"
        elif "ethtool" in line and "-s" not in cmd:
            out = ETHTOOL
        elif "sysctl" in line:
            out = "net.ipv4.ip_forward = 1\n"
        elif cmd[:2] == ["ip", "-j"] or "-j" in cmd:
            out = "[]"
        elif "vlan id 999" in line:
            rc, out = 2, "RTNETLINK answers: File exists\n"
        if kwargs.get("check") and rc:
            raise subprocess.CalledProcessError(rc, cmd, output=out, stderr=out)
        text = kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding")
        payload = out if text else out.encode()
        return subprocess.CompletedProcess(
            cmd,
            rc,
            stdout=payload if kwargs.get("capture_output") or kwargs.get("stdout") else payload,
            stderr="" if text else b"",
        )

    def docker(self, method, path, body=None, timeout=15.0, headers=None):
        self.calls.append(["docker", method, path] + ([json.dumps(body, sort_keys=True)] if body else []))
        if path == "/containers/tailscale/json":
            if self.container is None:
                return 404, {"message": "No such container: tailscale"}
            return 200, {
                "Id": "abcdef1234567890",
                "State": {"Running": self.container == "running", "Status": self.container},
            }
        if path.startswith("/images/"):
            return 200, {"Id": "sha256:img"}
        if path.startswith("/containers/create"):
            return 201, {"Id": "fedcba0987654321"}
        if path.endswith("/start") or "/stop" in path:
            return 204, None
        if path.startswith("/networks"):
            return (201, {"Id": "net123"}) if method == "POST" else (204, None)
        return 404, {"message": "not faked"}

    def http(self, request):
        """The Docker API over its socket (httpx)."""
        self.calls.append(
            ["http", request.method, request.url.path] + ([request.content.decode()] if request.content else [])
        )
        path = request.url.path
        if path == "/networks" and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "Name": "bridge",
                        "Id": "n1",
                        "Driver": "bridge",
                        "Scope": "local",
                        "IPAM": {"Config": [{"Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1"}]},
                        "Containers": {
                            "c1": {
                                "Name": "jellyfin",
                                "IPv4Address": "172.17.0.2/16",
                                "MacAddress": "02:42:ac:11:00:02",
                            }
                        },
                    },
                    {
                        "Name": "host",
                        "Id": "n2",
                        "Driver": "host",
                        "Scope": "local",
                        "IPAM": {"Config": []},
                        "Containers": {},
                    },
                    {
                        "Name": "zn-apps",
                        "Id": "n3",
                        "Driver": "bridge",
                        "Scope": "local",
                        "IPAM": {"Config": [{"Subnet": "172.30.0.0/16", "Gateway": "172.30.0.1"}]},
                        "Containers": {},
                    },
                ],
            )
        if path == "/containers/json":
            return httpx.Response(
                200,
                json=[
                    {
                        "Id": "c1",
                        "Names": ["/jellyfin"],
                        "State": "running",
                        "Ports": [{"PrivatePort": 8096, "PublicPort": 8096, "Type": "tcp"}],
                    }
                ],
            )
        if path == "/networks/create":
            return httpx.Response(201, json={"Id": "net123", "Warning": ""})
        if request.method == "DELETE" and path.startswith("/networks/"):
            return (
                httpx.Response(204)
                if path.endswith("zn-test")
                else httpx.Response(404, json={"message": "network not found"})
            )
        return httpx.Response(404, json={"message": "not faked"})

    def exec_in(self, cid, cmd):
        self.calls.append(["exec", cid, *[str(c) for c in cmd]])
        res = self.run(list(cmd), capture_output=True, text=True)
        return {
            "success": res.returncode == 0,
            "exit_code": res.returncode,
            "stdout": res.stdout,
            "stderr": "",
            "output": res.stdout,
        }


class _Timer:
    made = []

    def __init__(self, interval, fn, args=None, kwargs=None):
        self.interval, self.fn, self.args = interval, fn, args or []
        _Timer.made.append(self)
        self.daemon = True

    def start(self):
        pass

    def cancel(self):
        pass


def _norm(value, subs, key=""):
    """Paths under the fake root, times and generated ids become tags; the rest is kept."""
    if isinstance(value, dict):
        return {str(k): _norm(v, subs, str(k)) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_norm(v, subs, key) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)) and key.endswith("_age"):
        return "<age>"
    if isinstance(value, (int, float)) and key == "expires_in" and value:
        return "<seconds left>"
    if isinstance(value, (int, float)):
        return "<ts>" if re.fullmatch(r"1[6-9]\d{8}(\.\d+)?", str(value)) else value
    if not isinstance(value, str):
        return f"<{type(value).__name__}>"
    for real, tag in subs:
        value = value.replace(real, tag)
    value = re.sub(r"(?<!\d)1[6-9]\d{8}(\.\d+)?(?!\d)", "<ts>", value)
    if (key in ("canary_id", "id") and re.fullmatch(r"[0-9a-f-]{8,}", value)) or re.fullmatch(r"[0-9a-f]{16}", value):
        return "<id>"
    return value


def _scenario(host, root):
    log = []

    def call(label, fn, *args, **kwargs):
        start = len(host.calls)
        try:
            result = fn(*args, **kwargs)
        except Exception as e:  # recorded too: the split must not change it
            result = {"raised": type(e).__name__, "message": str(e)[:200]}
        log.append({"call": label, "result": result, "commands": host.calls[start:]})
        return result

    call("_hex_to_ip", lambda: [net._hex_to_ip(h) for h in ("0101A8C0", "00000000", "0A01A8C0", "zz")])
    call("_mask_to_cidr", lambda: [net._mask_to_cidr(m) for m in ("255.255.255.0", "255.255.0.0", "0.0.0.0", "bad")])
    call(
        "_format_speed",
        lambda: [net._format_speed(s, u) for s in (None, -1, 10, 100, 1000, 2500, 10000, 40000) for u in (True, False)],
    )
    call(
        "_validate_ipv4",
        lambda: [
            _try(net._validate_ipv4, v, "IP address") for v in ("192.168.1.10", "256.1.1.1", "", "a.b.c.d", "10.0.0.0")
        ],
    )
    call(
        "_validate_netmask",
        lambda: [_try(net._validate_netmask, v) for v in ("255.255.255.0", "255.0.255.0", "24", "255.255.255.255", "")],
    )
    call(
        "_read_file",
        lambda: [net._read_file(os.path.join(root, "sys/class/net/eth0/mtu")), net._read_file("/nonexistent", "dflt")],
    )
    call("_read_stat", net._read_stat, os.path.join(root, "sys/class/net/eth0"), "rx_bytes")
    call("_parse_routes", net._parse_routes)
    call("_get_dns_servers", net._get_dns_servers)
    call("load_network_config (none)", net.load_network_config)
    call("save_network_config", net.save_network_config, {"example": True})
    call("load_network_config", net.load_network_config)
    call("_parse_unraid_network_cfg", net._parse_unraid_network_cfg)
    call("_get_unraid_descriptions", net._get_unraid_descriptions)
    call("get_host_ip_config", net.get_host_ip_config)
    for bad in (
        {"mode": "static", "ip_address": "999.1.1.1"},
        {"mode": "static", "ip_address": "192.168.1.20", "netmask": "255.0.255.0"},
        {"mode": "weird"},
        {"mode": "dhcp", "interface": "br0;x"},
        {"mode": "static", "ip_address": "192.168.1.20", "dns1": "x"},
    ):
        call(f"apply_host_ip_config_canary {bad}", net.apply_host_ip_config_canary, bad, 30)
    applied = call(
        "apply_host_ip_config_canary static",
        net.apply_host_ip_config_canary,
        {
            "mode": "static",
            "ip_address": "192.168.1.20",
            "netmask": "255.255.255.0",
            "gateway": "192.168.1.1",
            "dns1": "1.1.1.1",
            "dns2": "9.9.9.9",
        },
        30,
    )
    call("canary status", lambda: net.get_canary_watchdog().get_status())
    call("network.cfg after apply", _read, os.path.join(root, "boot", "network.cfg"))
    cid = applied.get("canary_id") if isinstance(applied, dict) else None
    call("confirm wrong id", net.confirm_host_ip_config, "nope")
    call("confirm", net.confirm_host_ip_config, cid)
    call("revert after confirm", net.revert_host_ip_config, cid)
    applied = call("apply again (dhcp)", net.apply_host_ip_config_canary, {"mode": "dhcp"}, 30)
    cid = applied.get("canary_id") if isinstance(applied, dict) else None
    call("revert", net.revert_host_ip_config, cid)
    call("network.cfg after revert", _read, os.path.join(root, "boot", "network.cfg"))
    w = net.CanaryWatchdog()
    call("watchdog arm", w.arm, {"ip": "1"}, {"ip": "0"}, 5)
    call("watchdog timeout", lambda: (w._on_timeout(w.get_status().get("canary_id") or "x"), w.get_status())[1])
    call("_query_ethtool", net._query_ethtool, "eth0")
    for iface in ("eth0", "eth2", "bond0", "br0", "nope0"):
        call(f"get_port_config {iface}", net.get_port_config, iface)
    for updates in (
        {"mtu": 9000},
        {"mtu": 100},
        {"wol": True},
        {"autoneg": False, "speed": 1000, "duplex": "full"},
        {"description": "Uplink"},
        {},
    ):
        call(f"update_port_config eth2 {updates}", net.update_port_config, "eth2", updates)
    call("update_port_config missing", net.update_port_config, "nope0", {"mtu": 1500})
    call("create_docker_network", net.create_docker_network, "zn-test", "bridge", "172.30.0.0/16", "172.30.0.1")
    call("create_docker_network bad", net.create_docker_network, "bad name!", "weird")
    call("delete_docker_network", net.delete_docker_network, "zn-test")
    call("delete_docker_network missing", net.delete_docker_network, "nope")
    call("_parse_proc_net_vlan", net._parse_proc_net_vlan)
    call("get_vlans", net.get_vlans)
    for args in (
        ("eth2", 30, "Cameras"),
        ("eth2", 5000, ""),
        ("nope0", 30, ""),
        ("eth2", 999, ""),
        ("eth2;rm", 30, ""),
    ):
        call(f"create_vlan {args}", net.create_vlan, *args)
    for name in ("eth2.30", "br0.20", "eth0", "nope.1"):
        call(f"delete_vlan {name}", net.delete_vlan, name)
    call("get_bond_config bond0", net.get_bond_config, "bond0")
    call("get_bond_config missing", net.get_bond_config, "bond9")
    for updates in ({"mode": "active-backup"}, {"mode": "nonsense"}, {"miimon": 200}, {"slaves": ["eth0", "eth2"]}):
        call(f"update_bond_config {updates}", net.update_bond_config, "bond0", updates)
    call("get_bridge_config br0", net.get_bridge_config, "br0")
    call("get_bridge_config missing", net.get_bridge_config, "br9")
    for updates in ({"stp": True}, {"forward_delay": 4}, {"members": ["bond0", "eth2"]}, {"stp": "maybe"}):
        call(f"update_bridge_config {updates}", net.update_bridge_config, "br0", updates)
    call("_get_docker_topology", net._get_docker_topology)
    call("get_network_topology", net.get_network_topology)
    call("read_network_rates", lambda: _strip_rates(net.read_network_rates()))
    call("read_ip", net.read_ip)

    # Tailscale natively, then in a container
    for where in ("native", "container"):
        host.container = None if where == "native" else "running"
        call(f"{where} _find_tailscale_bin", net._find_tailscale_bin)
        call(f"{where} _get_tailscale_container_info", net._get_tailscale_container_info)
        call(f"{where} _run_tailscale_cmd", net._run_tailscale_cmd, ["status", "--json"])
        call(f"{where} detect_local_subnets", net.detect_local_subnets)
        call(f"{where} get_taildrop_dir", net.get_taildrop_dir)
        call(f"{where} get_taildrop_inbox_files", net.get_taildrop_inbox_files)
        call(f"{where} taildrop receive", net.execute_tailscale_taildrop_receive)
        call(f"{where} ping", net.execute_tailscale_ping, "laptop")
        call(f"{where} ping bad", net.execute_tailscale_ping, "laptop; reboot")
        call(f"{where} set routes", net.execute_tailscale_set_routes, "192.168.1.0/24", True)
        call(f"{where} set routes bad", net.execute_tailscale_set_routes, "not-a-route", True)
        call(f"{where} exit node", net.execute_tailscale_set_exit_node, True)
        call(f"{where} ssh", net.execute_tailscale_set_ssh, False)
        call(f"{where} serve", net.execute_tailscale_set_serve, True, False, 8082)
        call(f"{where} funnel", net.execute_tailscale_set_serve, True, True, 8082)
        call(f"{where} serve off", net.execute_tailscale_set_serve, False)
        call(f"{where} reauth", net.execute_tailscale_reauth)
        call(f"{where} mesh status", net.get_mesh_vpn_status)
        call(f"{where} up", net.execute_tailscale_up, "tskey-auth-example", "nas", True)
        call(f"{where} down", net.execute_tailscale_down)
    host.ts_status = json.dumps({"BackendState": "NeedsLogin", "AuthURL": "https://login.tailscale.com/a/abc"})
    call("mesh status needs login", net.get_mesh_vpn_status)
    host.container = None
    call(
        "deploy tailscale container",
        net.deploy_tailscale_container,
        "tskey-auth-example",
        "nas",
        True,
        os.path.join(root, "ts-state"),
    )
    host.container = "exited"
    call("deploy (exists, stopped)", net.deploy_tailscale_container, None, None, True, None)
    call("_get_wireguard_status", net._get_wireguard_status)
    call("generate_wireguard_keypair", net.generate_wireguard_keypair)
    call(
        "generate_wireguard_client_config",
        net.generate_wireguard_client_config,
        "phone",
        "10.13.13.5/32",
        "vpn.example.org:51820",
        "SERVERPUB=",
    )
    call("generate_wireguard_client_config bad", net.generate_wireguard_client_config, "bad name\n", "nonsense")
    call("get_ip_forwarding_status", net.get_ip_forwarding_status)
    call("set_ip_forwarding off", net.set_ip_forwarding, False)
    call("set_ip_forwarding on", net.set_ip_forwarding, True)
    call("toggle_wireguard_subnet_nat", net.toggle_wireguard_subnet_nat, True, "wg0", "br0")
    call("toggle_wireguard_subnet_nat bad", net.toggle_wireguard_subnet_nat, True, "wg0;x", "br0")
    call("get_active_listening_ports", net.get_active_listening_ports)
    call("timers", lambda: [[t.interval, getattr(t.fn, "__name__", "?")] for t in _Timer.made])
    return log


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _try(fn, *args):
    try:
        return ["ok", fn(*args)]
    except Exception as e:
        return [type(e).__name__, str(e)[:120]]


def _strip_rates(result):
    """Rates divide by the time between two samples: keep the shape and the byte counters."""
    text = json.dumps(result, sort_keys=True, default=str)
    text = re.sub(r'"([a-z_]*(rate|speed|per_sec|bps)[a-z_]*)": ("[^"]*"|[0-9.]+)', r'"\1": "<rate>"', text)
    return json.loads(text)


def _patch_everywhere(monkeypatch, name, value):
    """Patch a module global in the network module and, once split, wherever it is defined."""
    hit = False
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith(OWN) and mod is not None and name in vars(mod):
            monkeypatch.setattr(mod, name, value)
            hit = True
    assert hit, name


@pytest.fixture
def fake_host(tmp_path, monkeypatch):
    root = str(tmp_path)
    sysnet, proc = _build_host(root)
    host = _Host(root)
    docker_sock = os.path.join(root, "docker.sock")
    _write(docker_sock, "")
    for name, value in {
        "_find_sys_net_dir": lambda: sysnet,
        "_find_proc_net_path": lambda name: p if os.path.isfile(p := os.path.join(proc, "net", name)) else None,
        "UNRAID_NETWORK_CFG": (os.path.join(root, "boot", "network.cfg"),),
        "DNS_SOURCES": (os.path.join(root, "boot", "network.cfg"), os.path.join(root, "etc", "resolv.conf")),
        "HOST_IP_SOURCES": (os.path.join(root, "boot", "network.cfg"), os.path.join(root, "etc", "interfaces")),
        "IP_FORWARD_PATHS": (os.path.join(proc, "sys", "net", "ipv4", "ip_forward"),),
        "NETWORK_CONFIG_FILE": os.path.join(root, "network_config.json"),
        "HOST_PROC": proc,
        "HOST_SYS": os.path.join(root, "sys"),
        "_docker_sock_path": lambda: docker_sock,
        "docker_sock": lambda: docker_sock,
    }.items():
        _patch_everywhere(monkeypatch, name, value)
    monkeypatch.setattr(subprocess, "run", host.run)
    monkeypatch.setattr(httpx, "HTTPTransport", lambda uds=None, **kw: httpx.MockTransport(host.http))
    monkeypatch.setattr(threading, "Timer", _Timer)
    _Timer.made = []
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(
        "shutil.which", lambda b: f"/usr/bin/{b}" if b in ("tailscale", "wg", "ethtool", "ip", "iptables") else None
    )
    monkeypatch.setattr("backend.services.container_mutator._docker_request", host.docker)
    monkeypatch.setattr("backend.services.compose_synthesizer.execute_in_container", host.exec_in)
    monkeypatch.setattr(
        "backend.hardware.docker_stats.read_docker_containers",
        lambda *a, **k: [
            {"name": "jellyfin", "id": "0123456789abcdef", "ports": [{"host_port": 8096, "proto": "tcp"}]},
            {"name": "wireguard", "id": "fedcba9876543210", "ports": [{"host_port": 51820, "proto": "udp"}]},
        ],
    )
    monkeypatch.setattr("backend.config.DATA_DIR", os.path.join(root, "data"))
    monkeypatch.delenv("HOST_IP", raising=False)
    from backend.state import Z_STATE

    monkeypatch.setattr(Z_STATE, "discovered_host_ip", None, raising=False)
    monkeypatch.setattr(Z_STATE, "prev_net_ifaces", None)  # traffic rates start from the first sample
    monkeypatch.setattr(net.get_canary_watchdog(), "__dict__", dict(net.CanaryWatchdog().__dict__))
    return host, root


def test_network_api_and_behaviour_match_the_recording(fake_host):
    host, root = fake_host
    got = {"surface": _surface(), "behaviour": _scenario(host, root)}
    got = _norm(got, [(root, "<root>")])
    if os.environ.get("ZETTNAS_UPDATE_GOLDEN") == "1":
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump(got, fh, indent=1, sort_keys=True)
            fh.write("\n")
        pytest.skip("golden file written")
    with open(GOLDEN, encoding="utf-8") as fh:
        want = json.load(fh)
    missing = sorted(set(want["surface"]) - set(got["surface"]))
    assert not missing, f"names no longer provided by backend.hardware.network: {missing}"
    changed = [n for n in want["surface"] if got["surface"][n] != want["surface"][n]]
    assert not changed, f"API changed: {changed[:5]}"
    for w, g in zip(want["behaviour"], got["behaviour"], strict=True):
        assert g == w, w["call"]
    assert len(want["surface"]) >= 70 and len(want["behaviour"]) >= 120

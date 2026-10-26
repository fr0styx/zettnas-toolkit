"""Network helpers: host config files, ethtool/ip commands, Docker networks, VLANs, forwarding."""

import subprocess

import httpx
import pytest

from backend.hardware import network as net
from backend.state import Z_STATE


class Run:
    """Fake subprocess.run: answers by the first words of the command."""

    def __init__(self, answers=None, default=(1, "")):
        self.answers = answers or {}
        self.default = default
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        for prefix, answer in self.answers.items():
            if " ".join(cmd).startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                code, out = answer
                return subprocess.CompletedProcess(cmd, code, out, "")
        code, out = self.default
        return subprocess.CompletedProcess(cmd, code, out, "")


@pytest.fixture
def run(monkeypatch):
    fake = Run()
    monkeypatch.setattr(net.subprocess, "run", fake)
    return fake


@pytest.fixture
def unraid_cfg(tmp_path, monkeypatch):
    cfg = tmp_path / "network.cfg"
    cfg.write_text(
        '# generated\nUSE_DHCP[0]="no"\nIPADDR[0]="192.168.7.20"\nNETMASK[0]="255.255.255.0"\n'
        'DESCRIPTION[0]="Main LAN"\nDESCRIPTION[1]="Backup link"\nDNS_SERVER1="9.9.9.9"\n'
    )
    monkeypatch.setattr(net.common, "UNRAID_NETWORK_CFG", (str(cfg),))
    return cfg


class TestUnraidConfig:
    def test_parse(self, unraid_cfg):
        cfg = net._parse_unraid_network_cfg()
        assert cfg["IPADDR[0]"] == "192.168.7.20" and cfg["USE_DHCP[0]"] == "no"

    def test_write_keeps_order_and_comments(self, unraid_cfg):
        assert net._write_unraid_network_cfg({"IPADDR[0]": "192.168.7.30", "GATEWAY[0]": "192.168.7.1"})
        text = unraid_cfg.read_text()
        assert text.startswith("# generated\n") and 'IPADDR[0]="192.168.7.30"' in text
        assert text.rstrip().endswith('GATEWAY[0]="192.168.7.1"')

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(net.common, "UNRAID_NETWORK_CFG", (str(tmp_path / "nope.cfg"),))
        assert net._parse_unraid_network_cfg() == {}
        assert net._write_unraid_network_cfg({"A": "b"}) is False
        assert net._get_unraid_descriptions() == {}

    def test_descriptions(self, unraid_cfg):
        d = net._get_unraid_descriptions()
        assert d["0"] == d["eth0"] == d["br0"] == "Main LAN" and d["1"] == "Backup link"

    def test_revert_writes_the_old_settings(self, unraid_cfg, monkeypatch):
        monkeypatch.setattr(net.common, "load_network_config", lambda: {"host_ip_staged": {}})
        saved = []
        monkeypatch.setattr(net.common, "save_network_config", lambda cfg: saved.append(cfg))
        net._execute_revert(
            {
                "mode": "static",
                "ip_address": "192.168.7.25",
                "netmask": "255.255.255.0",
                "gateway": "192.168.7.1",
                "dns1": "1.1.1.1",
                "dns2": "",
            }
        )
        text = unraid_cfg.read_text()
        assert 'IPADDR[0]="192.168.7.25"' in text and 'DNS_SERVER1="1.1.1.1"' in text
        assert saved and "host_ip_staged" not in saved[0]
        net._execute_revert({"mode": "dhcp"})
        assert 'USE_DHCP[0]="yes"' in unraid_cfg.read_text()


class TestDns:
    def test_from_resolv_conf(self, tmp_path, monkeypatch):
        resolv = tmp_path / "resolv.conf"
        resolv.write_text(
            "nameserver 127.0.0.11\nnameserver 10.0.0.53\nnameserver 10.0.0.53\n# ExtServers: [host(192.168.1.1)]\n"
        )
        monkeypatch.setattr(net.common, "DNS_SOURCES", (str(tmp_path / "missing"), str(resolv)))
        assert net._get_dns_servers() == ["10.0.0.53", "192.168.1.1"]

    def test_from_unraid(self, unraid_cfg, monkeypatch):
        monkeypatch.setattr(net.common, "DNS_SOURCES", (str(unraid_cfg),))
        assert net._get_dns_servers() == ["9.9.9.9"]


class TestValidation:
    @pytest.mark.parametrize("bad", ["", "300.1.1.1", "127.0.0.1", "224.0.0.1", "0.0.0.0", "255.255.255.255"])
    def test_bad_ipv4(self, bad):
        with pytest.raises(ValueError):
            net._validate_ipv4(bad, "IP")

    def test_good_ipv4(self):
        assert net._validate_ipv4(" 192.168.1.10 ", "IP") == "192.168.1.10"

    @pytest.mark.parametrize(
        "val, want",
        [("", "255.255.255.0"), ("/24", "255.255.255.0"), ("16", "255.255.0.0"), ("255.255.252.0", "255.255.252.0")],
    )
    def test_netmask(self, val, want):
        assert net._validate_netmask(val) == want

    @pytest.mark.parametrize("bad", ["/40", "0", "255.0.255.0", "abc"])
    def test_bad_netmask(self, bad):
        with pytest.raises(ValueError):
            net._validate_netmask(bad)


class TestLinkSettings:
    def test_bad_interface_names_run_nothing(self, run):
        assert net._query_ethtool("eth0; rm -rf /") == ""
        assert net._apply_mtu("$(x)", 9000) is False
        assert net._apply_wol("a b", True) is False
        assert net._apply_negotiation("x|y", True) is False
        assert run.calls == []

    def test_ethtool_direct(self, run):
        run.answers["ethtool eth0"] = (0, "Settings for eth0:\n Speed: 1000Mb/s")
        assert "Speed" in net._query_ethtool("eth0")

    def test_ethtool_in_the_host_namespace(self, run, monkeypatch):
        run.answers["nsenter"] = (0, "Settings for eth0:")
        monkeypatch.setattr(net.os.path, "exists", lambda p: p == "/host/proc/1/ns/net")
        assert net._query_ethtool("eth0") == "Settings for eth0:"

    def test_ethtool_unavailable(self, run, monkeypatch):
        run.answers["ethtool"] = FileNotFoundError("ethtool")
        monkeypatch.setattr(net.os.path, "exists", lambda p: False)
        assert net._query_ethtool("eth0") == ""

    def test_mtu_via_ip(self, run):
        run.answers["ip link set dev eth0 mtu 9000"] = (0, "")
        assert net._apply_mtu("eth0", 9000)

    def test_mtu_via_sysfs(self, run, tmp_path, monkeypatch):
        (tmp_path / "class/net/eth0").mkdir(parents=True)
        (tmp_path / "class/net/eth0/mtu").write_text("1500")
        monkeypatch.setattr(net.common, "HOST_SYS", str(tmp_path))
        monkeypatch.setattr(net.os.path, "exists", lambda p: False)
        assert net._apply_mtu("eth0", 9000)
        assert (tmp_path / "class/net/eth0/mtu").read_text() == "9000"

    def test_mtu_nowhere(self, run, tmp_path, monkeypatch):
        monkeypatch.setattr(net.common, "HOST_SYS", str(tmp_path))
        monkeypatch.setattr(net.os.path, "exists", lambda p: False)
        monkeypatch.setattr(net.os.path, "isfile", lambda p: False)
        assert net._apply_mtu("eth0", 9000) is False

    @pytest.mark.parametrize("enabled, arg", [(True, "g"), (False, "d")])
    def test_wol(self, run, enabled, arg):
        run.answers[f"ethtool -s eth0 wol {arg}"] = (0, "")
        assert net._apply_wol("eth0", enabled)

    def test_wol_host_namespace(self, run, monkeypatch):
        run.answers["nsenter"] = (0, "")
        monkeypatch.setattr(net.os.path, "exists", lambda p: p == "/host/proc/1/ns/net")
        assert net._apply_wol("eth0", True)

    def test_negotiation(self, run):
        run.answers["ethtool -s eth0 autoneg on"] = (0, "")
        assert net._apply_negotiation("eth0", True)
        run.answers["ethtool -s eth0 speed 1000 duplex full autoneg off"] = (0, "")
        assert net._apply_negotiation("eth0", False, speed=1000)

    def test_negotiation_fails(self, run, monkeypatch):
        monkeypatch.setattr(net.os.path, "exists", lambda p: p == "/host/proc/1/ns/net")
        assert net._apply_negotiation("eth0", False, speed=100, duplex="half") is False
        assert run.calls[-1][0] == "nsenter"


@pytest.fixture
def docker(tmp_path, monkeypatch):
    """A fake Docker engine behind the socket."""
    sock = tmp_path / "docker.sock"
    sock.write_text("")
    monkeypatch.setattr(net.common, "_docker_sock_path", lambda: str(sock))
    state = {"networks": [], "containers": [], "fail": None}

    def handler(request):
        if state["fail"]:
            return httpx.Response(state["fail"][0], json={"message": state["fail"][1]})
        if request.url.path == "/networks" and request.method == "GET":
            return httpx.Response(200, json=state["networks"])
        if request.url.path == "/containers/json":
            return httpx.Response(200, json=state["containers"])
        if request.url.path == "/networks/create":
            return httpx.Response(201, json={"Id": "abcdef1234567890"})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    real = httpx.HTTPTransport
    monkeypatch.setattr(net.httpx, "HTTPTransport", lambda uds=None, **kw: httpx.MockTransport(handler))
    yield state
    monkeypatch.setattr(net.httpx, "HTTPTransport", real)


class TestDockerNetworks:
    def test_topology(self, docker):
        docker["networks"] = [
            {
                "Name": "bridge",
                "Id": "1111111111119999",
                "Driver": "bridge",
                "IPAM": {"Config": [{"Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1"}]},
            },
            {"Name": "apps", "Id": "2222222222229999", "Driver": "bridge", "IPAM": {"Config": []}},
            {"Name": "host", "Id": "3333", "Driver": "host"},
        ]
        docker["containers"] = [
            {
                "Names": ["/jellyfin"],
                "Id": "c0ffee1234567890",
                "State": "running",
                "Ports": [
                    {"PublicPort": 8096, "PrivatePort": 8096, "Type": "tcp"},
                    {"PrivatePort": 1900, "Type": "udp"},
                ],
                "NetworkSettings": {"Networks": {"apps": {"IPAddress": "172.20.0.2", "MacAddress": "02:42:ac"}}},
            }
        ]
        topo = {n["name"]: n for n in net._get_docker_topology()}
        assert topo["bridge"]["bridge_device"] == "docker0" and topo["bridge"]["subnet"] == "172.17.0.0/16"
        assert topo["apps"]["bridge_device"] == "br-222222222222" and topo["apps"]["is_custom"]
        assert topo["apps"]["containers"][0]["ports"] == ["8096:8096/tcp", "1900/udp"]
        assert topo["host"]["bridge_device"] == "" and not topo["host"]["is_custom"]

    def test_topology_without_docker(self, tmp_path, monkeypatch):
        monkeypatch.setattr(net.common, "_docker_sock_path", lambda: str(tmp_path / "none.sock"))
        assert net._get_docker_topology() == []

    def test_create(self, docker):
        r = net.create_docker_network("apps", subnet="172.30.0.0/16", gateway="172.30.0.1")
        assert r == {"status": "ok", "id": "abcdef123456", "message": "Network 'apps' created"}

    def test_create_rejects_bad_names(self, docker):
        assert net.create_docker_network("bad name")["status"] == "error"

    def test_create_reports_docker_errors(self, docker):
        docker["fail"] = (409, "network with name apps already exists")
        assert "already exists" in net.create_docker_network("apps")["message"]

    def test_delete(self, docker):
        assert net.delete_docker_network("apps")["status"] == "ok"
        assert "default" in net.delete_docker_network("bridge")["message"]
        docker["fail"] = (403, "network has active endpoints")
        assert "active endpoints" in net.delete_docker_network("apps")["message"]

    def test_without_socket(self, tmp_path, monkeypatch):
        monkeypatch.setattr(net.common, "_docker_sock_path", lambda: str(tmp_path / "none.sock"))
        assert net.create_docker_network("x")["message"] == "Docker socket not accessible"
        assert net.delete_docker_network("x")["message"] == "Docker socket not accessible"


class TestVlans:
    @pytest.fixture
    def sysnet(self, tmp_path, monkeypatch):
        root = tmp_path / "net"

        def iface(name, **files):
            d = root / name
            d.mkdir(parents=True)
            for k, v in files.items():
                (d / k).write_text(v)
            (d / "statistics").mkdir()
            (d / "statistics" / "rx_bytes").write_text("100")
            (d / "statistics" / "tx_bytes").write_text("50")
            return d

        iface("eth0", operstate="up", carrier="1", speed="1000", mtu="1500", address="AA:BB")
        iface("eth0.10", operstate="up", carrier="1", speed="1000", mtu="1500", address="AA:BB:10")
        iface("vlan20", operstate="down", carrier="0", speed="-1", mtu="1500", address="CC", uevent="DEVTYPE=vlan")
        (root / "vlan20" / "lower_eth1").mkdir()
        monkeypatch.setattr(net.common, "_find_sys_net_dir", lambda: str(root))
        monkeypatch.setattr(
            net.common, "_parse_routes", lambda: [{"iface": "eth0.10", "destination": "10.10.0.0", "cidr": 24}]
        )
        vlan_conf = tmp_path / "vlan_config"
        vlan_conf.write_text(
            "VLAN Dev name | VLAN ID\nName-Type: VLAN_NAME_TYPE_RAW_PLUS_VID_NO_PAD\nvlan20 | 20 | eth1\nbroken | x | eth9\n"
        )
        monkeypatch.setattr(net.common, "_find_proc_net_path", lambda name: str(vlan_conf))
        monkeypatch.setattr(
            net.common,
            "load_network_config",
            lambda: {
                "vlans": {"eth2.30": {"parent": "eth2", "vlan_id": 30, "alias": "IoT"}},
                "aliases": {"eth0.10": "Cameras"},
            },
        )
        return root

    def test_proc_vlan_config(self, sysnet):
        assert net._parse_proc_net_vlan() == {"vlan20": {"vlan_id": 20, "parent": "eth1"}}

    def test_discovers_vlans_and_keeps_saved_ones(self, sysnet):
        vlans = {v["name"]: v for v in net.get_vlans()}
        assert set(vlans) == {"eth0.10", "vlan20", "eth2.30"}
        assert vlans["eth0.10"]["vlan_id"] == 10 and vlans["eth0.10"]["parent"] == "eth0"
        assert vlans["eth0.10"]["alias"] == "Cameras" and vlans["eth0.10"]["ip_address"] == "10.10.0.0/24"
        assert vlans["vlan20"]["parent"] == "eth1" and not vlans["vlan20"]["is_up"]
        assert vlans["eth2.30"]["speed_human"] == "Disconnected" and vlans["eth2.30"]["alias"] == "IoT"

    @pytest.mark.parametrize("parent, vid", [("eth0;x", 10), ("eth0", 0), ("eth0", 5000), ("eth0", "ten")])
    def test_create_rejects_bad_input(self, parent, vid):
        assert net.create_vlan(parent, vid)["status"] == "error"


class TestHostIp:
    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.delenv("HOST_IP", raising=False)
        monkeypatch.setattr(Z_STATE, "discovered_host_ip", None, raising=False)

    def test_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("HOST_IP", "10.1.2.3")
        assert net.read_ip() == "10.1.2.3"

    def test_from_unraid(self, unraid_cfg, monkeypatch):
        monkeypatch.setattr(net.common, "HOST_IP_SOURCES", (str(unraid_cfg),))
        assert net.read_ip() == "192.168.7.20"
        assert net.read_ip() == "192.168.7.20"  # cached

    def test_from_interfaces_file(self, tmp_path, monkeypatch):
        f = tmp_path / "interfaces"
        f.write_text("iface eth0 inet static\n  address 10.20.30.40\n")
        monkeypatch.setattr(net.common, "HOST_IP_SOURCES", (str(f),))
        assert net.read_ip() == "10.20.30.40"

    def test_from_fib_trie(self, tmp_path, monkeypatch):
        fib = tmp_path / "fib_trie"
        fib.write_text(
            "Main:\n  +-- 0.0.0.0/0 3 0 5\n     |-- 127.0.0.1\n        /32 host LOCAL\n     |-- 192.168.50.9\n        /32 host LOCAL\n"
        )
        monkeypatch.setattr(net.common, "HOST_IP_SOURCES", ())
        monkeypatch.setattr(net.common, "_find_proc_net_path", lambda name: str(fib))
        assert net.read_ip() == "192.168.50.9"

    def test_unknown(self, monkeypatch):
        monkeypatch.setattr(net.common, "HOST_IP_SOURCES", ())
        monkeypatch.setattr(net.common, "_find_proc_net_path", lambda name: None)
        assert net.read_ip() == "?"


class TestForwarding:
    def test_read_and_write(self, tmp_path, monkeypatch):
        f = tmp_path / "ip_forward"
        f.write_text("0\n")
        monkeypatch.setattr(net.common, "IP_FORWARD_PATHS", (str(f),))
        assert net.get_ip_forwarding_status() is False
        assert net.set_ip_forwarding(True)
        assert net.get_ip_forwarding_status() is True

    def test_falls_back_to_sysctl(self, run, monkeypatch):
        monkeypatch.setattr(net.common, "IP_FORWARD_PATHS", ())
        assert net.get_ip_forwarding_status() is False
        assert net.set_ip_forwarding(False)
        assert run.calls[-1] == ["sysctl", "-w", "net.ipv4.ip_forward=0"]

    def test_wireguard_nat(self, run, monkeypatch):
        monkeypatch.setattr(net.common, "IP_FORWARD_PATHS", ())
        run.answers["iptables"] = (0, "")
        r = net.toggle_wireguard_subnet_nat(True, out_iface="br0")
        assert r["nat_rule"] and "enabled" in r["message"]
        run.answers["iptables"] = OSError("no iptables")
        assert net.toggle_wireguard_subnet_nat(False)["nat_rule"] is False


def test_a_tailscale_timeout_reports_what_it_printed(monkeypatch):
    """TimeoutExpired carries bytes even with text=True; the reply is still text (ARC-5 type fix)."""
    import subprocess

    from backend.hardware.net import tailscale

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 10, output=b"partial output", stderr=b"still waiting")

    monkeypatch.setattr(tailscale, "_get_tailscale_container_info", lambda: {"exists": False})
    monkeypatch.setattr(tailscale.subprocess, "run", slow)
    assert tailscale._run_tailscale_cmd(["status"]) == (1, "partial output\nstill waiting")

    def silent(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 10)

    monkeypatch.setattr(tailscale.subprocess, "run", silent)
    assert tailscale._run_tailscale_cmd(["status"]) == (1, "Command timed out")

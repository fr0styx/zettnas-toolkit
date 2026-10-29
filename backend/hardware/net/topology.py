"""The network map (interfaces, bonds, bridges, VLANs, Docker networks), traffic rates and the host's IP.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import re
import time
from typing import Any

import httpx

from backend.config import logger
from backend.hardware.net import canary, common

# get_network_topology has locals named listening_ports and vlans, hence the aliases
from backend.hardware.net import listening_ports as listening_mod
from backend.hardware.net import vlans as vlan_mod
from backend.ignored_errors import ignored
from backend.state import Z_STATE


def _get_docker_topology() -> list[dict[str, Any]]:
    """Query Docker daemon for active bridge networks and attached container IPs."""
    docker_networks: list[dict[str, Any]] = []
    docker_sock = common._docker_sock_path()
    if not os.path.exists(docker_sock):
        return docker_networks

    try:
        transport = httpx.HTTPTransport(uds=docker_sock)
        with httpx.Client(transport=transport, base_url="http://docker", timeout=2.5) as client:
            net_res = client.get("/networks")
            if net_res.status_code != 200:
                return docker_networks
            raw_networks = net_res.json()

            # Also fetch containers to have full port mapping and IP data
            cnt_res = client.get("/containers/json")
            containers = cnt_res.json() if cnt_res.status_code == 200 else []

            # Map containers by network ID or network name
            containers_by_net: dict[str, list[dict[str, Any]]] = {}
            for c in containers:
                c_name = (c.get("Names") or [""])[0].lstrip("/")
                ports = []
                for p in c.get("Ports") or []:
                    pub = p.get("PublicPort")
                    priv = p.get("PrivatePort")
                    ptype = p.get("Type", "tcp")
                    if pub:
                        ports.append(f"{pub}:{priv}/{ptype}")
                    elif priv:
                        ports.append(f"{priv}/{ptype}")

                net_settings = c.get("NetworkSettings", {}).get("Networks", {})
                for n_name, n_info in net_settings.items():
                    c_record = {
                        "name": c_name,
                        "id": (c.get("Id") or "")[:12],
                        "ipv4": n_info.get("IPAddress", ""),
                        "mac": n_info.get("MacAddress", ""),
                        "ports": ports,
                        "state": c.get("State", "running"),
                    }
                    containers_by_net.setdefault(n_name, []).append(c_record)

            for net in raw_networks:
                net_name = net.get("Name", "")
                net_id = (net.get("Id") or "")[:12]
                driver = net.get("Driver", "bridge")
                ipam_configs = (net.get("IPAM") or {}).get("Config") or []
                subnet = ipam_configs[0].get("Subnet", "") if ipam_configs else ""
                gateway = ipam_configs[0].get("Gateway", "") if ipam_configs else ""

                # Find bridge device name (br-<id> or docker0)
                bridge_dev = ""
                if driver == "bridge":
                    if net_name == "bridge":
                        bridge_dev = "docker0"
                    else:
                        bridge_dev = f"br-{net_id}"

                # Attached containers
                attached = containers_by_net.get(net_name, [])

                docker_networks.append(
                    {
                        "id": net_id,
                        "name": net_name,
                        "driver": driver,
                        "subnet": subnet,
                        "gateway": gateway,
                        "bridge_device": bridge_dev,
                        "containers": attached,
                        "container_count": len(attached),
                        "is_custom": net_name not in ("bridge", "host", "none"),
                    }
                )
    except Exception as e:
        logger.debug(f"Docker network topology query error: {e}")

    return docker_networks


def get_network_topology() -> dict[str, Any]:
    """
    Expose complete host networking topology, physical NIC carrier states,
    link negotiation speeds (10GbE / 2.5GbE / 1GbE / 100M), duplex, MTU,
    bonding, bridges, and Docker bridge IP mappings.
    """
    sys_net_dir = common._find_sys_net_dir()
    if not sys_net_dir:
        return {
            "status": "error",
            "message": "Sysfs net directory not found",
            "summary": {},
            "physical_interfaces": [],
            "bonds": [],
            "bridges": [],
            "docker_networks": [],
            "routes": [],
        }

    physical_interfaces: list[dict[str, Any]] = []
    bonds: list[dict[str, Any]] = []
    bridges: list[dict[str, Any]] = []
    all_ifaces = os.listdir(sys_net_dir)

    routes = common._parse_routes()
    dns_servers = common._get_dns_servers()
    saved_cfg = common.load_network_config()
    saved_aliases = saved_cfg.get("aliases", {})
    unraid_descs = common._get_unraid_descriptions()

    # Determine default gateway and primary interface
    non_shim_defaults = [r for r in routes if r.get("is_default") and not r.get("iface", "").startswith("shim-")]
    if non_shim_defaults:
        default_route = sorted(non_shim_defaults, key=lambda x: x.get("metric", 999))[0]
    else:
        default_route = next(
            (r for r in sorted(routes, key=lambda x: x.get("metric", 999)) if r.get("is_default")), None
        )
    default_gw = default_route.get("gateway") if default_route else ""
    primary_iface = default_route.get("iface") if default_route else ""

    for iface in sorted(all_ifaces):
        if iface in ("lo", "bonding_masters"):
            continue

        iface_dir = os.path.join(sys_net_dir, iface)
        if not os.path.exists(iface_dir):
            continue

        # Check symlink target to distinguish physical from virtual
        link_target = ""
        try:
            link_target = os.readlink(iface_dir)
        except OSError:
            pass

        is_pci_or_platform = (
            "devices/pci" in link_target or "devices/platform" in link_target
        ) and "devices/virtual" not in link_target
        is_virtual = "devices/virtual" in link_target or iface.startswith(
            ("veth", "br-", "docker", "shim-", "tunl", "wg", "tailscale", "tap", "tun")
        )

        operstate = common._read_file(os.path.join(iface_dir, "operstate"), "unknown").lower()
        carrier_str = common._read_file(os.path.join(iface_dir, "carrier"), "0")
        carrier = 1 if carrier_str == "1" else 0
        is_up = operstate == "up" and carrier == 1

        raw_speed = common._read_file(os.path.join(iface_dir, "speed"), "-1")
        try:
            speed_val = int(raw_speed) if raw_speed and raw_speed.lstrip("-").isdigit() else -1
            if speed_val < 0:
                speed_val = None
        except ValueError:
            speed_val = None

        duplex = common._read_file(os.path.join(iface_dir, "duplex"), "unknown").lower()
        mtu = int(common._read_file(os.path.join(iface_dir, "mtu"), "1500") or 1500)
        mac = common._read_file(os.path.join(iface_dir, "address"), "").lower()

        # Master interface (e.g. bond0 or br0)
        master = None
        master_link = os.path.join(iface_dir, "master")
        if os.path.exists(master_link):
            try:
                master = os.path.basename(os.readlink(master_link))
            except OSError:
                pass

        alias = saved_aliases.get(iface) or unraid_descs.get(iface) or ""

        # 1. Check for physical NICs
        if is_pci_or_platform or (not is_virtual and iface.startswith(("eth", "en", "wl"))):
            # Parse PCI uevent
            pci_slot = ""
            driver = ""
            pci_id = ""
            uevent_path = os.path.join(iface_dir, "device/uevent")
            if os.path.isfile(uevent_path):
                uevent_content = common._read_file(uevent_path)
                for line in uevent_content.splitlines():
                    if line.startswith("PCI_SLOT_NAME="):
                        pci_slot = line.split("=", 1)[1]
                    elif line.startswith("DRIVER="):
                        driver = line.split("=", 1)[1]
                    elif line.startswith("PCI_ID="):
                        pci_id = line.split("=", 1)[1]

            physical_interfaces.append(
                {
                    "name": iface,
                    "alias": alias,
                    "state": operstate,
                    "carrier": carrier,
                    "is_up": is_up,
                    "speed_mbps": speed_val if is_up else None,
                    "speed_human": common._format_speed(speed_val, is_up),
                    "duplex": duplex,
                    "mtu": mtu,
                    "mac": mac,
                    "master": master,
                    "pci_slot": pci_slot,
                    "driver": driver,
                    "pci_id": pci_id,
                    "rx_bytes": common._read_stat(iface_dir, "rx_bytes"),
                    "tx_bytes": common._read_stat(iface_dir, "tx_bytes"),
                    "rx_packets": common._read_stat(iface_dir, "rx_packets"),
                    "tx_packets": common._read_stat(iface_dir, "tx_packets"),
                    "rx_errors": common._read_stat(iface_dir, "rx_errors"),
                    "tx_errors": common._read_stat(iface_dir, "tx_errors"),
                    "rx_dropped": common._read_stat(iface_dir, "rx_dropped"),
                    "tx_dropped": common._read_stat(iface_dir, "tx_dropped"),
                }
            )

        # 2. Check for Bonding interfaces
        elif os.path.isdir(os.path.join(iface_dir, "bonding")):
            mode = common._read_file(os.path.join(iface_dir, "bonding/mode"), "")
            slaves = common._read_file(os.path.join(iface_dir, "bonding/slaves"), "").split()
            active_slave = common._read_file(os.path.join(iface_dir, "bonding/active_slave"), "")
            xmit_hash_policy = common._read_file(os.path.join(iface_dir, "bonding/xmit_hash_policy"), "")
            lacp_rate = common._read_file(os.path.join(iface_dir, "bonding/lacp_rate"), "")
            ad_num_ports = common._read_file(os.path.join(iface_dir, "bonding/ad_num_ports"), "")
            miimon_str = common._read_file(os.path.join(iface_dir, "bonding/miimon"), "100")
            try:
                miimon_val = int(miimon_str) if miimon_str.isdigit() else 100
            except ValueError:
                miimon_val = 100

            mode_parts = mode.split()
            if mode_parts and mode_parts[-1].isdigit():
                mode_code = mode_parts[-1]
            elif "802.3ad" in mode.lower():
                mode_code = "4"
            elif "balance-alb" in mode.lower():
                mode_code = "6"
            elif "balance-rr" in mode.lower():
                mode_code = "0"
            elif "balance-xor" in mode.lower():
                mode_code = "2"
            else:
                mode_code = "1"

            mode_info = common.BONDING_MODES.get(mode_code, common.BONDING_MODES["1"])

            bonds.append(
                {
                    "name": iface,
                    "alias": alias,
                    "mode": mode,
                    "mode_code": mode_code,
                    "mode_name": mode_info.get("name", "active-backup"),
                    "mode_title": mode_info.get("title", "Active-Backup"),
                    "slaves": slaves,
                    "active_slave": active_slave,
                    "xmit_hash_policy": xmit_hash_policy,
                    "lacp_rate": lacp_rate,
                    "ad_num_ports": ad_num_ports,
                    "miimon": miimon_val,
                    "carrier": carrier,
                    "is_up": is_up,
                    "speed_mbps": speed_val if is_up else None,
                    "speed_human": common._format_speed(speed_val, is_up),
                    "duplex": duplex,
                    "mtu": mtu,
                    "mac": mac,
                    "master": master,
                    "rx_bytes": common._read_stat(iface_dir, "rx_bytes"),
                    "tx_bytes": common._read_stat(iface_dir, "tx_bytes"),
                }
            )

        # 3. Check for Host Bridges (e.g. br0)
        elif os.path.isdir(os.path.join(iface_dir, "bridge")) and not iface.startswith(("br-", "docker0")):
            members = []
            brif_dir = os.path.join(iface_dir, "brif")
            if os.path.isdir(brif_dir):
                members = os.listdir(brif_dir)

            stp_raw = common._read_file(os.path.join(iface_dir, "bridge/stp_state"), "0").strip()
            stp_enabled = stp_raw in ("1", "yes", "true")
            fd_raw = common._read_file(os.path.join(iface_dir, "bridge/forward_delay"), "0").strip()
            try:
                fd_val = int(fd_raw)
                if fd_val > 100:
                    fd_val = fd_val // 100
            except ValueError:
                fd_val = 0

            # Match IP address from routes or state
            bridge_ip = ""
            for r in routes:
                if r.get("iface") == iface and r.get("destination") != "0.0.0.0":
                    bridge_ip = f"{r.get('destination')}/{r.get('cidr')}"
                    break

            bridges.append(
                {
                    "name": iface,
                    "alias": alias,
                    "interfaces": sorted(members),
                    "stp": stp_enabled,
                    "forward_delay": fd_val,
                    "carrier": carrier,
                    "is_up": is_up,
                    "mtu": mtu,
                    "mac": mac,
                    "ip_address": bridge_ip,
                    "rx_bytes": common._read_stat(iface_dir, "rx_bytes"),
                    "tx_bytes": common._read_stat(iface_dir, "tx_bytes"),
                }
            )

    # 4. VLAN Sub-Interfaces (802.1Q)
    vlans = vlan_mod.get_vlans()

    # Docker network inspection
    docker_networks = _get_docker_topology()
    total_containers = sum(len(n.get("containers") or []) for n in docker_networks)

    # Calculate max speed across active physical NICs
    active_speeds = [p["speed_mbps"] for p in physical_interfaces if p["is_up"] and p["speed_mbps"]]
    max_speed_mbps = max(active_speeds) if active_speeds else 0
    max_speed_str = common._format_speed(max_speed_mbps, is_up=bool(max_speed_mbps))

    primary_ip = read_ip()

    summary = {
        "primary_ip": primary_ip,
        "default_gateway": default_gw,
        "dns_servers": dns_servers,
        "primary_interface": primary_iface or ("br0" if bridges else "eth0"),
        "total_physical": len(physical_interfaces),
        "active_physical": sum(1 for p in physical_interfaces if p["is_up"]),
        "max_speed": max_speed_str,
        "vlan_count": len(vlans),
        "docker_networks_count": len(docker_networks),
        "docker_containers_count": total_containers,
        "canary": canary.get_canary_watchdog().get_status(),
    }

    listening_ports = []
    try:
        listening_ports = listening_mod.get_active_listening_ports()
    except Exception as e:
        logger.debug(f"[Network Diagnostics] Error reading listening ports: {e}")

    return {
        "status": "ok",
        "summary": summary,
        "physical_interfaces": physical_interfaces,
        "bonds": bonds,
        "bridges": bridges,
        "vlans": vlans,
        "docker_networks": docker_networks,
        "routes": routes,
        "listening_ports": listening_ports,
    }


def read_network_rates():
    now = time.time()
    dev_path = common._find_proc_net_path("dev")
    ifaces = {}
    if dev_path:
        try:
            with open(dev_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if ":" in line:
                        iface, data = line.split(":", 1)
                        iface = iface.strip()
                        fields = data.split()
                        if len(fields) >= 9:
                            ifaces[iface] = (int(fields[0]), int(fields[8]))
        except Exception as e:
            logger.debug(f"Silenced exception reading net/dev: {e}")

    def fmt_speed(b):
        if b >= 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024 * 1024):.1f} GB/s"
        elif b >= 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} MB/s"
        elif b >= 1024:
            return f"{b / 1024:.0f} KB/s"
        return f"{b:.0f} B/s"

    prev_ifaces = getattr(Z_STATE, "prev_net_ifaces", None)
    if not isinstance(prev_ifaces, dict):
        prev_ifaces = {}

    interfaces_info = {}
    total_physical_rx_rate = 0.0
    total_physical_tx_rate = 0.0
    total_physical_rx_bytes = 0
    total_physical_tx_bytes = 0

    bond_slaves = set()
    for b in [i for i in ifaces if i.startswith("bond")]:
        try:
            bonding_slaves_path = os.path.join(common.HOST_SYS, "class/net", b, "bonding/slaves")
            if os.path.exists(bonding_slaves_path):
                with open(bonding_slaves_path, encoding="utf-8") as bf:
                    bond_slaves.update(bf.read().split())
        except Exception:
            ignored("backend.hardware.network.read_network_rates")

    for iface_name, (cur_rx, cur_tx) in ifaces.items():
        if iface_name == "lo" or iface_name.startswith(("veth", "docker", "br-", "shim-", "tunl", "tailscale", "wg")):
            continue

        prev_data = prev_ifaces.get(iface_name)
        rx_rate = 0.0
        tx_rate = 0.0
        if prev_data:
            dt = max(0.1, now - prev_data["time"])
            if cur_rx >= prev_data["rx"] and cur_tx >= prev_data["tx"]:
                rx_rate = max(0.0, (cur_rx - prev_data["rx"]) / dt)
                tx_rate = max(0.0, (cur_tx - prev_data["tx"]) / dt)

        prev_ifaces[iface_name] = {"time": now, "rx": cur_rx, "tx": cur_tx}

        is_physical = iface_name.startswith(("eth", "en"))
        interfaces_info[iface_name] = {
            "rx": fmt_speed(rx_rate),
            "tx": fmt_speed(tx_rate),
            "rx_bytes": cur_rx,
            "tx_bytes": cur_tx,
            "rx_rate": round(rx_rate, 1),
            "tx_rate": round(tx_rate, 1),
            "is_physical": is_physical,
            "is_bond": iface_name.startswith("bond"),
            "is_bridge": iface_name.startswith("br"),
        }

        if iface_name.startswith("bond") or is_physical and iface_name not in bond_slaves:
            total_physical_rx_rate += rx_rate
            total_physical_tx_rate += tx_rate
            total_physical_rx_bytes += cur_rx
            total_physical_tx_bytes += cur_tx

    Z_STATE.prev_net_ifaces = prev_ifaces

    env_iface = os.environ.get("HOST_NET_IFACE", "").strip()
    if env_iface and env_iface in interfaces_info:
        target = interfaces_info[env_iface]
        combined_rx_rate = target["rx_rate"]
        combined_tx_rate = target["tx_rate"]
        combined_rx_bytes = target["rx_bytes"]
        combined_tx_bytes = target["tx_bytes"]
        chosen_iface = env_iface
    else:
        combined_rx_rate = total_physical_rx_rate
        combined_tx_rate = total_physical_tx_rate
        combined_rx_bytes = total_physical_rx_bytes
        combined_tx_bytes = total_physical_tx_bytes
        chosen_iface = "combined"

    Z_STATE.prev_net = {
        "time": now,
        "rx": combined_rx_bytes,
        "tx": combined_tx_bytes,
        "iface": chosen_iface,
    }

    return {
        "rx": fmt_speed(combined_rx_rate),
        "tx": fmt_speed(combined_tx_rate),
        "rx_bytes": combined_rx_bytes,
        "tx_bytes": combined_tx_bytes,
        "rx_rate": round(combined_rx_rate, 1),
        "tx_rate": round(combined_tx_rate, 1),
        "rx_bytes_sec": round(combined_rx_rate, 1),
        "tx_bytes_sec": round(combined_tx_rate, 1),
        "iface": chosen_iface,
        "interfaces": interfaces_info,
    }


def read_ip():
    env_ip = os.environ.get("HOST_IP", "").strip()
    if env_ip:
        return env_ip

    if getattr(Z_STATE, "discovered_host_ip", None):
        return Z_STATE.discovered_host_ip

    # 1. Check known network configs
    for p in common.HOST_IP_SOURCES:
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                ip_match = re.search(r'IPADDR(?:.*?)="?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"?', content)
                if not ip_match:
                    ip_match = re.search(r"address\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", content)

                if ip_match:
                    Z_STATE.discovered_host_ip = ip_match.group(1)
                    return Z_STATE.discovered_host_ip

                matches = re.findall(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", content)
                for ip in matches:
                    if not (ip.startswith("127.") or ip.startswith("172.") or ip.endswith(".255") or ip == "0.0.0.0"):
                        Z_STATE.discovered_host_ip = ip
                        return ip
            except Exception as e:
                logger.debug(f"Silenced exception: {e}")

    # 2. Check /proc/net/fib_trie for local host IPs
    fib_path = common._find_proc_net_path("fib_trie")
    if fib_path:
        try:
            with open(fib_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if "/32 host LOCAL" in line and i > 0:
                    prev_line = lines[i - 1].strip()
                    m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", prev_line)
                    if m:
                        candidate_ip = m.group(1)
                        if not (
                            candidate_ip.startswith("127.")
                            or candidate_ip.startswith("172.")
                            or candidate_ip.endswith(".255")
                            or candidate_ip == "0.0.0.0"
                        ):
                            Z_STATE.discovered_host_ip = candidate_ip
                            return candidate_ip
        except Exception:
            ignored("backend.hardware.network.read_ip")

    return "?"

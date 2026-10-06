import os
import re
import time

from backend.config import HOST_PROC, logger
from backend.state import Z_STATE


def read_network_rates():
    now = time.time()
    rx_bytes = 0
    tx_bytes = 0
    chosen_iface = "bond0"

    # Search candidate paths for net/dev. In Docker containers with host /proc mounted,
    # /host/proc/1/net/dev accesses the host root network namespace (since PID 1 is on host).
    candidate_paths = [
        os.path.join(HOST_PROC, "1/net/dev"),
        os.path.join(HOST_PROC, "net/dev"),
        "/proc/1/net/dev",
        "/proc/net/dev",
    ]
    dev_path = None
    for p in candidate_paths:
        if os.path.exists(p):
            dev_path = p
            break

    ifaces = {}
    if dev_path:
        try:
            with open(dev_path) as f:
                for line in f:
                    if ":" in line:
                        iface, data = line.split(":", 1)
                        iface = iface.strip()
                        fields = data.split()
                        if len(fields) >= 9:
                            ifaces[iface] = (int(fields[0]), int(fields[8]))
        except Exception as e:
            logger.debug(f"Silenced exception reading net/dev: {e}")

    # Interface selection hierarchy:
    # 1. Explicit override via environment variable
    env_iface = os.environ.get("HOST_NET_IFACE", "").strip()
    if env_iface and env_iface in ifaces:
        chosen_iface = env_iface
        rx_bytes, tx_bytes = ifaces[env_iface]
    # 2. Unraid bond0 or any bonded interface (prioritized)
    elif "bond0" in ifaces:
        chosen_iface = "bond0"
        rx_bytes, tx_bytes = ifaces["bond0"]
    else:
        bond_candidates = [i for i in ifaces if i.startswith("bond")]
        if bond_candidates:
            chosen_iface = bond_candidates[0]
            rx_bytes, tx_bytes = ifaces[chosen_iface]
        # 3. Primary bridge br0
        elif "br0" in ifaces:
            chosen_iface = "br0"
            rx_bytes, tx_bytes = ifaces["br0"]
        # 4. Primary physical eth0
        elif "eth0" in ifaces and (ifaces["eth0"][0] > 0 or ifaces["eth0"][1] > 0):
            chosen_iface = "eth0"
            rx_bytes, tx_bytes = ifaces["eth0"]
        else:
            # 5. First active physical interface or sum of physical
            active_phys = [i for i in ifaces if i.startswith(("eth", "en")) and (ifaces[i][0] > 0 or ifaces[i][1] > 0)]
            if active_phys:
                chosen_iface = active_phys[0]
                rx_bytes, tx_bytes = ifaces[chosen_iface]
            elif ifaces:
                # Sum all non-virtual interfaces
                chosen_iface = "all"
                for i, (r, t) in ifaces.items():
                    if i in ("lo",) or i.startswith(("veth", "br-", "docker", "shim-", "tunl")):
                        continue
                    rx_bytes += r
                    tx_bytes += t

    prev = getattr(Z_STATE, "prev_net", None)
    if not isinstance(prev, dict):
        prev = {"time": 0.0, "rx": 0, "tx": 0, "iface": chosen_iface}

    # Reset baseline if interface changed
    if prev.get("iface") != chosen_iface:
        prev = {"time": 0.0, "rx": rx_bytes, "tx": tx_bytes, "iface": chosen_iface}

    prev_time = prev.get("time", 0.0)
    dt = max(0.1, now - prev_time)
    rx_rate = 0.0
    tx_rate = 0.0

    if prev_time > 0 and rx_bytes >= prev.get("rx", 0) and tx_bytes >= prev.get("tx", 0):
        rx_rate = max(0.0, (rx_bytes - prev.get("rx", 0)) / dt)
        tx_rate = max(0.0, (tx_bytes - prev.get("tx", 0)) / dt)

    Z_STATE.prev_net = {"time": now, "rx": rx_bytes, "tx": tx_bytes, "iface": chosen_iface}

    def fmt_speed(b):
        if b >= 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024 * 1024):.1f} GB/s"
        elif b >= 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} MB/s"
        elif b >= 1024:
            return f"{b / 1024:.0f} KB/s"
        return f"{b:.0f} B/s"

    return {
        "rx": fmt_speed(rx_rate),
        "tx": fmt_speed(tx_rate),
        "rx_bytes": rx_bytes,
        "tx_bytes": tx_bytes,
        "rx_rate": round(rx_rate, 1),
        "tx_rate": round(tx_rate, 1),
        "iface": chosen_iface,
    }


def read_ip():
    env_ip = os.environ.get("HOST_IP", "").strip()
    if env_ip:
        return env_ip

    if getattr(Z_STATE, "discovered_host_ip", None):
        return Z_STATE.discovered_host_ip

    for p in ["/boot/config/network.cfg", "/host/etc/network/interfaces"]:
        if os.path.exists(p):
            try:
                with open(p) as f:
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

    return "?"

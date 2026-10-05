import os
import re
import time

from backend.config import HOST_PROC, logger
from backend.state import Z_STATE


def read_network_rates():
    now = time.time()
    rx_bytes = 0
    tx_bytes = 0
    try:
        with open(os.path.join(HOST_PROC, "net/dev")) as f:
            for line in f:
                if ":" in line:
                    iface, data = line.split(":", 1)
                    iface = iface.strip()
                    if iface in ("lo",) or iface.startswith(("veth", "br-", "docker")):
                        continue
                    fields = data.split()
                    if len(fields) >= 9:
                        rx_bytes += int(fields[0])
                        tx_bytes += int(fields[8])
    except Exception as e:
        logger.debug(f"Silenced exception: {e}")

    dt = max(0.1, now - Z_STATE.prev_net["time"])
    rx_rate = 0.0
    tx_rate = 0.0
    if Z_STATE.prev_net["time"] > 0:
        rx_rate = max(0.0, (rx_bytes - Z_STATE.prev_net["rx"]) / dt)
        tx_rate = max(0.0, (tx_bytes - Z_STATE.prev_net["tx"]) / dt)

    Z_STATE.prev_net = {"time": now, "rx": rx_bytes, "tx": tx_bytes}

    def fmt_speed(b):
        if b >= 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} MB/s"
        elif b >= 1024:
            return f"{b / 1024:.0f} KB/s"
        return f"{b:.0f} B/s"

    return {"rx": fmt_speed(rx_rate), "tx": fmt_speed(tx_rate)}


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

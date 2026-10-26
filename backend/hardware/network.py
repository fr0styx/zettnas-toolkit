"""Host networking.

The code lives in backend/hardware/net/ (one module per area, ARC-5); this module keeps every
name importers use. Modules there read each other's names as module.name: patch a name in the
module that defines it. tests/test_arc5_network_characterization.py pins the behaviour."""

import os  # noqa: F401  (tests patch os, subprocess and httpx through this module)
import subprocess  # noqa: F401

import httpx  # noqa: F401

from backend.config import logger
from backend.fsutil import atomic_write_json, read_json
from backend.hardware.net import (  # noqa: F401  (the areas, for patching a name where it is defined)
    bonds_bridges,
    canary,
    common,
    host_ip,
    listening_ports,
    mesh,
    ports,
    tailscale,
    tailscale_setup,
    topology,
    vlans,
    wireguard,
)
from backend.hardware.net.bonds_bridges import (
    get_bond_config,
    get_bridge_config,
    update_bond_config,
    update_bridge_config,
)
from backend.hardware.net.canary import (
    _CANARY_WATCHDOG,
    CanaryWatchdog,
    _execute_revert,
    _parse_unraid_network_cfg,
    _write_unraid_network_cfg,
    get_canary_watchdog,
)
from backend.hardware.net.common import (
    BONDING_MODES,
    DNS_SOURCES,
    HOST_IP_SOURCES,
    HOST_PROC,
    HOST_SYS,
    IP_FORWARD_PATHS,
    NETWORK_CONFIG_FILE,
    UNRAID_NETWORK_CFG,
    _docker_sock_path,
    _find_proc_net_path,
    _find_sys_net_dir,
    _format_speed,
    _get_dns_servers,
    _get_unraid_descriptions,
    _hex_to_ip,
    _mask_to_cidr,
    _parse_routes,
    _read_file,
    _read_stat,
    docker_sock,
    load_network_config,
    save_network_config,
)
from backend.hardware.net.host_ip import (
    _validate_ipv4,
    _validate_netmask,
    apply_host_ip_config_canary,
    confirm_host_ip_config,
    get_host_ip_config,
    revert_host_ip_config,
)
from backend.hardware.net.listening_ports import (
    get_active_listening_ports,
)
from backend.hardware.net.mesh import (
    get_mesh_vpn_status,
)
from backend.hardware.net.ports import (
    _apply_mtu,
    _apply_negotiation,
    _apply_wol,
    _query_ethtool,
    create_docker_network,
    delete_docker_network,
    get_port_config,
    update_port_config,
)
from backend.hardware.net.tailscale import (
    _find_tailscale_bin,
    _get_tailscale_container_info,
    _run_tailscale_cmd,
    detect_local_subnets,
    execute_tailscale_ping,
    execute_tailscale_reauth,
    execute_tailscale_set_exit_node,
    execute_tailscale_set_routes,
    execute_tailscale_set_serve,
    execute_tailscale_set_ssh,
    execute_tailscale_taildrop_receive,
    get_taildrop_dir,
    get_taildrop_inbox_files,
)
from backend.hardware.net.tailscale_setup import (
    deploy_tailscale_container,
    execute_tailscale_down,
    execute_tailscale_up,
)
from backend.hardware.net.topology import (
    _get_docker_topology,
    get_network_topology,
    read_ip,
    read_network_rates,
)
from backend.hardware.net.vlans import (
    _IFNAME,
    _ip_link_delete,
    _parse_proc_net_vlan,
    create_vlan,
    delete_vlan,
    get_vlans,
)
from backend.hardware.net.wireguard import (
    _get_wireguard_status,
    generate_wireguard_client_config,
    generate_wireguard_keypair,
    get_ip_forwarding_status,
    set_ip_forwarding,
    toggle_wireguard_subnet_nat,
)
from backend.state import Z_STATE

__all__ = [
    "BONDING_MODES",
    "CanaryWatchdog",
    "DNS_SOURCES",
    "HOST_IP_SOURCES",
    "HOST_PROC",
    "HOST_SYS",
    "IP_FORWARD_PATHS",
    "NETWORK_CONFIG_FILE",
    "UNRAID_NETWORK_CFG",
    "Z_STATE",
    "_CANARY_WATCHDOG",
    "_IFNAME",
    "_apply_mtu",
    "_apply_negotiation",
    "_apply_wol",
    "_docker_sock_path",
    "_execute_revert",
    "_find_proc_net_path",
    "_find_sys_net_dir",
    "_find_tailscale_bin",
    "_format_speed",
    "_get_dns_servers",
    "_get_docker_topology",
    "_get_tailscale_container_info",
    "_get_unraid_descriptions",
    "_get_wireguard_status",
    "_hex_to_ip",
    "_ip_link_delete",
    "_mask_to_cidr",
    "_parse_proc_net_vlan",
    "_parse_routes",
    "_parse_unraid_network_cfg",
    "_query_ethtool",
    "_read_file",
    "_read_stat",
    "_run_tailscale_cmd",
    "_validate_ipv4",
    "_validate_netmask",
    "_write_unraid_network_cfg",
    "apply_host_ip_config_canary",
    "atomic_write_json",
    "confirm_host_ip_config",
    "create_docker_network",
    "create_vlan",
    "delete_docker_network",
    "delete_vlan",
    "deploy_tailscale_container",
    "detect_local_subnets",
    "docker_sock",
    "execute_tailscale_down",
    "execute_tailscale_ping",
    "execute_tailscale_reauth",
    "execute_tailscale_set_exit_node",
    "execute_tailscale_set_routes",
    "execute_tailscale_set_serve",
    "execute_tailscale_set_ssh",
    "execute_tailscale_taildrop_receive",
    "execute_tailscale_up",
    "generate_wireguard_client_config",
    "generate_wireguard_keypair",
    "get_active_listening_ports",
    "get_bond_config",
    "get_bridge_config",
    "get_canary_watchdog",
    "get_host_ip_config",
    "get_ip_forwarding_status",
    "get_mesh_vpn_status",
    "get_network_topology",
    "get_port_config",
    "get_taildrop_dir",
    "get_taildrop_inbox_files",
    "get_vlans",
    "load_network_config",
    "logger",
    "read_ip",
    "read_json",
    "read_network_rates",
    "revert_host_ip_config",
    "save_network_config",
    "set_ip_forwarding",
    "toggle_wireguard_subnet_nat",
    "update_bond_config",
    "update_bridge_config",
    "update_port_config",
]

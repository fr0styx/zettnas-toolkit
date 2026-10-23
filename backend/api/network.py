"""
ZettNAS Toolkit - Network Management API Router
Provides REST endpoints for network topology, port tuning (MTU, WOL, speed/duplex),
friendly interface aliases, and Docker network management.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.hardware.network import (
    apply_host_ip_config_canary,
    confirm_host_ip_config,
    create_docker_network,
    create_vlan,
    delete_docker_network,
    delete_vlan,
    get_bond_config,
    get_bridge_config,
    get_host_ip_config,
    get_network_topology,
    get_port_config,
    get_vlans,
    revert_host_ip_config,
    update_bond_config,
    update_bridge_config,
    update_port_config,
)

router = APIRouter(tags=["Network & Switching"])


class HostIpConfigApplyRequest(BaseModel):
    mode: str = Field(default="static", description="Protocol mode: 'dhcp' or 'static'")
    interface: str | None = Field(default="br0", description="Target network interface (e.g. br0, eth0)")
    ip_address: str | None = Field(default=None, description="Static IPv4 address (e.g. 192.168.1.50)")
    netmask: str | None = Field(default="255.255.255.0", description="Subnet mask or CIDR prefix")
    gateway: str | None = Field(default=None, description="Default gateway IPv4 address")
    dns1: str | None = Field(default=None, description="Primary upstream DNS server")
    dns2: str | None = Field(default=None, description="Secondary upstream DNS server")
    timeout_sec: int | None = Field(default=60, ge=10, le=300, description="Canary rollback safety timeout in seconds")


class HostIpConfirmRequest(BaseModel):
    canary_id: str | None = Field(default=None, description="Canary test token ID to seal")


class HostIpRevertRequest(BaseModel):
    canary_id: str | None = Field(default=None, description="Canary test token ID to cancel and rollback")


class PortConfigUpdateRequest(BaseModel):
    alias: str | None = Field(default=None, description="User-friendly port description/name")
    mtu: int | None = Field(default=None, ge=68, le=9216, description="Interface MTU (68-9216)")
    wol_enabled: bool | None = Field(default=None, description="Wake-on-LAN magic packet enable")
    autoneg: bool | None = Field(default=True, description="Enable automatic link speed negotiation")
    speed: int | None = Field(default=None, description="Forced link speed in Mbps (e.g. 10000, 2500, 1000, 100)")
    duplex: str | None = Field(default="full", description="Duplex mode: 'full' or 'half'")


class DockerNetworkCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="Network name")
    driver: str = Field(default="bridge", description="Network driver: 'bridge', 'macvlan', 'ipvlan'")
    subnet: str | None = Field(default="", description="Subnet CIDR (e.g. 172.28.0.0/16)")
    gateway: str | None = Field(default="", description="Gateway IP address (e.g. 172.28.0.1)")


class BondConfigUpdateRequest(BaseModel):
    mode: str = Field(
        default="1",
        description="Bonding mode: '0' (balance-rr), '1' (active-backup), '2' (balance-xor), '4' (802.3ad), '6' (balance-alb)",
    )
    slaves: list[str] = Field(
        ...,
        min_length=1,
        description="list of slave member interfaces to enslave (e.g. ['eth0', 'eth1'])",
    )
    miimon: int | None = Field(
        default=100, ge=10, le=1000, description="MII link monitoring interval in milliseconds (10-1000)"
    )


class BridgeConfigUpdateRequest(BaseModel):
    stp: bool = Field(default=False, description="Enable Spanning Tree Protocol (STP) to prevent network loops")
    forward_delay: int | None = Field(default=0, ge=0, le=30, description="Bridge forward delay in seconds (0-30)")
    members: list[str] = Field(
        default_factory=list, description="list of member interfaces attached to the bridge (e.g. ['bond0'])"
    )


class VlanCreateRequest(BaseModel):
    parent: str = Field(..., description="Parent network interface name (e.g. eth0, br0, bond0)")
    vlan_id: int = Field(..., ge=1, le=4094, description="802.1Q VLAN Tag ID (1-4094)")
    alias: str | None = Field(default="", description="Friendly role/purpose alias for this VLAN")


@router.get("/network/topology", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def get_network_topology_endpoint():
    """Retrieve full host network topology, physical NICs, bridges, bonds, and Docker networks."""
    return await asyncio.to_thread(get_network_topology)


@router.get("/network/port/{iface_name}", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def get_port_config_endpoint(iface_name: str):
    """Retrieve configuration, live capabilities, and alias for a specific interface."""
    res = await asyncio.to_thread(get_port_config, iface_name)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res.get("message", "Interface not found"))
    return res


@router.post("/network/port/{iface_name}", dependencies=[Depends(require_scope("system:config"))])
async def update_port_config_endpoint(iface_name: str, req: PortConfigUpdateRequest):
    """Update interface configuration (alias, MTU, WOL, negotiation speed)."""
    updates = req.model_dump(exclude_unset=True)
    res = await asyncio.to_thread(update_port_config, iface_name, updates)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to update port configuration"))
    return res


@router.post("/network/docker/create", dependencies=[Depends(require_scope("containers:manage"))])
async def create_docker_network_endpoint(req: DockerNetworkCreateRequest):
    """Create a new Docker bridge or custom network."""
    res = await asyncio.to_thread(
        create_docker_network,
        name=req.name,
        driver=req.driver,
        subnet=req.subnet or "",
        gateway=req.gateway or "",
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to create Docker network"))
    return res


@router.delete("/network/docker/{net_id_or_name}", dependencies=[Depends(require_scope("containers:manage"))])
async def delete_docker_network_endpoint(net_id_or_name: str):
    """Delete a custom Docker network."""
    res = await asyncio.to_thread(delete_docker_network, net_id_or_name)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to delete Docker network"))
    return res


@router.get("/network/host/config", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def get_host_ip_config_endpoint():
    """Retrieve host IP assignment mode, primary interface, netmask, gateway, and DNS servers."""
    return await asyncio.to_thread(get_host_ip_config)


@router.post("/network/host/apply", dependencies=[Depends(require_scope("system:config"))])
async def apply_host_ip_config_endpoint(req: HostIpConfigApplyRequest):
    """
    Arm 60-second Canary watchdog, snapshot configuration, and stage/apply new host IP settings.
    Automatically reverts within 60s unless confirmed.
    """
    try:
        updates = req.model_dump(exclude_unset=True)
        timeout_sec = updates.pop("timeout_sec", 60)
        res = await asyncio.to_thread(apply_host_ip_config_canary, updates, timeout_sec=timeout_sec)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to apply host network configuration: {e}") from e


@router.post("/network/host/confirm", dependencies=[Depends(require_scope("system:config"))])
async def confirm_host_ip_config_endpoint(req: HostIpConfirmRequest | None = None):
    """Confirm and seal host network configuration, cancelling the 60s rollback watchdog."""
    canary_id = req.canary_id if req else None
    res = await asyncio.to_thread(confirm_host_ip_config, canary_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Confirmation failed"))
    return res


@router.post("/network/host/revert", dependencies=[Depends(require_scope("system:config"))])
async def revert_host_ip_config_endpoint(req: HostIpRevertRequest | None = None):
    """Manually abort Canary test and immediately restore previous host network configuration."""
    canary_id = req.canary_id if req else None
    res = await asyncio.to_thread(revert_host_ip_config, canary_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Reversion failed"))
    return res


@router.get("/network/bond/{bond_name}", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def get_bond_config_endpoint(bond_name: str):
    """Retrieve configuration, operational mode, active slave, and candidates for a bonding group."""
    res = await asyncio.to_thread(get_bond_config, bond_name)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res.get("message", "Bond interface not found"))
    return res


@router.post("/network/bond/{bond_name}", dependencies=[Depends(require_scope("system:config"))])
async def update_bond_config_endpoint(bond_name: str, req: BondConfigUpdateRequest):
    """Update bonding group mode (802.3ad / active-backup / balance-alb), slave member interfaces, and miimon."""
    updates = req.model_dump(exclude_unset=True)
    res = await asyncio.to_thread(update_bond_config, bond_name, updates)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to update bond configuration"))
    return res


@router.get("/network/bridge/{br_name}", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def get_bridge_config_endpoint(br_name: str):
    """Retrieve configuration, STP state, forward delay, and members for a virtual bridge."""
    res = await asyncio.to_thread(get_bridge_config, br_name)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res.get("message", "Bridge interface not found"))
    return res


@router.post("/network/bridge/{br_name}", dependencies=[Depends(require_scope("system:config"))])
async def update_bridge_config_endpoint(br_name: str, req: BridgeConfigUpdateRequest):
    """Update virtual bridge parameters (STP enable/disable, forward delay, member interfaces)."""
    updates = req.model_dump(exclude_unset=True)
    res = await asyncio.to_thread(update_bridge_config, br_name, updates)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to update bridge configuration"))
    return res


@router.get("/network/vlans", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def get_vlans_endpoint():
    """list all active and configured 802.1Q VLAN sub-interfaces."""
    return {"status": "ok", "vlans": await asyncio.to_thread(get_vlans)}


@router.post("/network/vlan/create", dependencies=[Depends(require_scope("system:config"))])
async def create_vlan_endpoint(req: VlanCreateRequest):
    """Create a new 802.1Q VLAN tagged sub-interface (e.g. eth0.10, br0.20)."""
    res = await asyncio.to_thread(
        create_vlan,
        parent=req.parent,
        vlan_id=req.vlan_id,
        alias=req.alias or "",
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to create VLAN sub-interface"))
    return res


@router.delete("/network/vlan/{vlan_iface}", dependencies=[Depends(require_scope("system:config"))])
async def delete_vlan_endpoint(vlan_iface: str):
    """Delete an existing 802.1Q VLAN tagged sub-interface."""
    res = await asyncio.to_thread(delete_vlan, vlan_iface)
    return res


class TailscaleUpRequest(BaseModel):
    auth_key: str | None = Field(default=None, description="Pre-authenticated Tailscale ephemeral or reusable auth key")
    hostname: str | None = Field(default=None, description="Custom node hostname on tailnet")
    accept_routes: bool = Field(default=True, description="Accept subnet routes from other nodes")


class TailscaleDeployRequest(BaseModel):
    auth_key: str | None = Field(default=None, description="Pre-authenticated Tailscale ephemeral or reusable auth key")
    hostname: str | None = Field(default=None, description="Custom node hostname on tailnet")
    accept_routes: bool = Field(default=True, description="Accept subnet routes from other nodes")
    state_dir: str | None = Field(default=None, description="Custom persistent state directory on host")


@router.get("/network/mesh-vpn", dependencies=[Depends(require_scope("system:view"))])
async def get_mesh_vpn_endpoint():
    """Retrieves Zero-Trust Mesh VPN telemetry and status for Tailscale and WireGuard."""
    from backend.hardware.network import get_mesh_vpn_status

    return await asyncio.to_thread(get_mesh_vpn_status)


@router.post("/network/mesh-vpn/tailscale/up", dependencies=[Depends(require_scope("system:config"))])
async def post_tailscale_up(req: TailscaleUpRequest):
    """Connects host to the Zero-Trust Tailscale mesh network."""
    from backend.hardware.network import execute_tailscale_up

    res = await asyncio.to_thread(
        execute_tailscale_up,
        auth_key=req.auth_key,
        hostname=req.hostname,
        accept_routes=req.accept_routes,
    )
    if res.get("status") == "error":
        detail = res.get("output") or res.get("message") or "Tailscale connection failed"
        raise HTTPException(status_code=400, detail=detail)
    return res


@router.post("/network/mesh-vpn/tailscale/down", dependencies=[Depends(require_scope("system:config"))])
async def post_tailscale_down():
    """Disconnects host from the Zero-Trust Tailscale mesh network."""
    from backend.hardware.network import execute_tailscale_down

    res = await asyncio.to_thread(execute_tailscale_down)
    if res.get("status") == "error":
        detail = res.get("output") or res.get("message") or "Tailscale disconnection failed"
        raise HTTPException(status_code=400, detail=detail)
    return res


@router.post("/network/mesh-vpn/tailscale/deploy", dependencies=[Depends(require_scope("system:config"))])
async def post_tailscale_deploy(req: TailscaleDeployRequest):
    """1-Click turnkey provisioning of the official Tailscale Docker container."""
    from backend.hardware.network import deploy_tailscale_container

    res = await asyncio.to_thread(
        deploy_tailscale_container,
        auth_key=req.auth_key,
        hostname=req.hostname,
        accept_routes=req.accept_routes,
        state_dir=req.state_dir,
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Tailscale deployment failed"))
    return res


class TailscaleSetRoutesRequest(BaseModel):
    routes: str = Field(default="", max_length=512)
    enabled: bool = Field(default=True)


class TailscaleSetExitNodeRequest(BaseModel):
    enabled: bool = Field(default=True)


class TailscaleSetSshRequest(BaseModel):
    enabled: bool = Field(default=True)


class TailscaleSetServeRequest(BaseModel):
    serve: bool = Field(default=True)
    funnel: bool = Field(default=False)
    port: int = Field(default=8082, ge=1, le=65535)


class TailscalePingRequest(BaseModel):
    peer: str = Field(..., max_length=128)


@router.post("/network/mesh-vpn/tailscale/set-routes", dependencies=[Depends(require_scope("system:config"))])
async def post_tailscale_set_routes(req: TailscaleSetRoutesRequest):
    """Advertises or withdraws subnet routes on the Tailscale network."""
    from backend.hardware.network import execute_tailscale_set_routes

    return await asyncio.to_thread(execute_tailscale_set_routes, routes=req.routes, enabled=req.enabled)


@router.post("/network/mesh-vpn/tailscale/set-exit-node", dependencies=[Depends(require_scope("system:config"))])
async def post_tailscale_set_exit_node(req: TailscaleSetExitNodeRequest):
    """Enables or disables advertising this NAS as a Tailscale Exit Node."""
    from backend.hardware.network import execute_tailscale_set_exit_node

    return await asyncio.to_thread(execute_tailscale_set_exit_node, enabled=req.enabled)


@router.post("/network/mesh-vpn/tailscale/set-ssh", dependencies=[Depends(require_scope("system:config"))])
async def post_tailscale_set_ssh(req: TailscaleSetSshRequest):
    """Enables or disables Tailscale SSH."""
    from backend.hardware.network import execute_tailscale_set_ssh

    return await asyncio.to_thread(execute_tailscale_set_ssh, enabled=req.enabled)


@router.post("/network/mesh-vpn/tailscale/set-serve", dependencies=[Depends(require_scope("system:config"))])
async def post_tailscale_set_serve(req: TailscaleSetServeRequest):
    """Configures Tailscale Serve (HTTPS on Tailnet) and optional Public Funnel."""
    from backend.hardware.network import execute_tailscale_set_serve

    return await asyncio.to_thread(execute_tailscale_set_serve, serve=req.serve, funnel=req.funnel, port=req.port)


@router.post("/network/mesh-vpn/tailscale/taildrop/receive", dependencies=[Depends(require_scope("storage:write"))])
async def post_tailscale_taildrop_receive():
    """Receives and ingests incoming files from the Taildrop file inbox."""
    from backend.hardware.network import execute_tailscale_taildrop_receive

    return await asyncio.to_thread(execute_tailscale_taildrop_receive)


@router.get("/network/mesh-vpn/tailscale/taildrop/files", dependencies=[Depends(require_scope("storage:read"))])
async def get_tailscale_taildrop_files():
    """Lists files received via Taildrop."""
    from backend.hardware.network import get_taildrop_inbox_files

    files = await asyncio.to_thread(get_taildrop_inbox_files)
    return {"files": files, "count": len(files)}


@router.post("/network/mesh-vpn/tailscale/ping", dependencies=[Depends(require_scope("system:view"))])
async def post_tailscale_ping(req: TailscalePingRequest):
    """Performs real-time latency ping against a Tailscale mesh peer."""
    from backend.hardware.network import execute_tailscale_ping

    return await asyncio.to_thread(execute_tailscale_ping, peer=req.peer)


@router.post("/network/mesh-vpn/tailscale/reauth", dependencies=[Depends(require_scope("system:config"))])
async def post_tailscale_reauth():
    """Forces node re-authentication before node key expiration."""
    from backend.hardware.network import execute_tailscale_reauth

    return await asyncio.to_thread(execute_tailscale_reauth)


class WireguardClientConfigRequest(BaseModel):
    client_name: str = Field(default="mobile-client", max_length=64)
    client_ip: str = Field(default="10.13.13.2/32")
    server_endpoint: str | None = Field(default="")
    server_pubkey: str | None = Field(default="")
    dns: str = Field(default="1.1.1.1")
    allowed_ips: str = Field(default="0.0.0.0/0, ::/0")
    keepalive: int = Field(default=25, ge=0, le=3600)


class WireguardSubnetRouteRequest(BaseModel):
    enable: bool = Field(default=True)
    iface: str = Field(default="wg0")
    out_iface: str = Field(default="eth0")


@router.post("/network/mesh-vpn/wireguard/client-config", dependencies=[Depends(require_scope("system:config"))])
async def post_wireguard_client_config(req: WireguardClientConfigRequest):
    """Generates a WireGuard client configuration file with keypair."""
    from backend.hardware.network import generate_wireguard_client_config

    return await asyncio.to_thread(
        generate_wireguard_client_config,
        client_name=req.client_name,
        client_ip=req.client_ip,
        server_endpoint=req.server_endpoint or "",
        server_pubkey=req.server_pubkey or "",
        dns=req.dns,
        allowed_ips=req.allowed_ips,
        keepalive=req.keepalive,
    )


@router.get("/network/mesh-vpn/wireguard/subnet-routing", dependencies=[Depends(require_scope("system:config"))])
async def get_wireguard_subnet_routing():
    """Gets current kernel IP packet forwarding state."""
    from backend.hardware.network import get_ip_forwarding_status

    status = await asyncio.to_thread(get_ip_forwarding_status)
    return {"ip_forwarding": status}


@router.post("/network/mesh-vpn/wireguard/subnet-routing", dependencies=[Depends(require_scope("system:config"))])
async def post_wireguard_subnet_routing(req: WireguardSubnetRouteRequest):
    """Enables or disables kernel IP forwarding and NAT for WireGuard subnet routing."""
    from backend.hardware.network import toggle_wireguard_subnet_nat

    res = await asyncio.to_thread(
        toggle_wireguard_subnet_nat,
        enable=req.enable,
        iface=req.iface,
        out_iface=req.out_iface,
    )
    return res


@router.get("/network/ports/listening", dependencies=[Depends(require_scope("system:config", "system:read"))])
async def get_listening_ports():
    """Returns active listening TCP and UDP ports and mapped container services."""
    from backend.hardware.network import get_active_listening_ports

    ports = await asyncio.to_thread(get_active_listening_ports)
    return {"ports": ports, "total": len(ports)}

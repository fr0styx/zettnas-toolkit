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
    delete_docker_network,
    get_host_ip_config,
    get_network_topology,
    get_port_config,
    revert_host_ip_config,
    update_port_config,
)

router = APIRouter(tags=["Network & Switching"])


class HostIpConfigApplyRequest(BaseModel):
    mode: str = Field(default="static", description="Protocol mode: 'dhcp' or 'static'")
    interface: Optional[str] = Field(default="br0", description="Target network interface (e.g. br0, eth0)")
    ip_address: Optional[str] = Field(default=None, description="Static IPv4 address (e.g. 10.40.30.249)")
    netmask: Optional[str] = Field(default="255.255.255.0", description="Subnet mask or CIDR prefix")
    gateway: Optional[str] = Field(default=None, description="Default gateway IPv4 address")
    dns1: Optional[str] = Field(default=None, description="Primary upstream DNS server")
    dns2: Optional[str] = Field(default=None, description="Secondary upstream DNS server")
    timeout_sec: Optional[int] = Field(
        default=60, ge=10, le=300, description="Canary rollback safety timeout in seconds"
    )


class HostIpConfirmRequest(BaseModel):
    canary_id: Optional[str] = Field(default=None, description="Canary test token ID to seal")


class HostIpRevertRequest(BaseModel):
    canary_id: Optional[str] = Field(default=None, description="Canary test token ID to cancel and rollback")


class PortConfigUpdateRequest(BaseModel):
    alias: Optional[str] = Field(default=None, description="User-friendly port description/name")
    mtu: Optional[int] = Field(default=None, ge=68, le=9216, description="Interface MTU (68-9216)")
    wol_enabled: Optional[bool] = Field(default=None, description="Wake-on-LAN magic packet enable")
    autoneg: Optional[bool] = Field(default=True, description="Enable automatic link speed negotiation")
    speed: Optional[int] = Field(default=None, description="Forced link speed in Mbps (e.g. 10000, 2500, 1000, 100)")
    duplex: Optional[str] = Field(default="full", description="Duplex mode: 'full' or 'half'")


class DockerNetworkCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="Network name")
    driver: str = Field(default="bridge", description="Network driver: 'bridge', 'macvlan', 'ipvlan'")
    subnet: Optional[str] = Field(default="", description="Subnet CIDR (e.g. 172.28.0.0/16)")
    gateway: Optional[str] = Field(default="", description="Gateway IP address (e.g. 172.28.0.1)")


@router.get("/network/topology")
async def get_network_topology_endpoint():
    """Retrieve full host network topology, physical NICs, bridges, bonds, and Docker networks."""
    return await asyncio.to_thread(get_network_topology)


@router.get("/network/port/{iface_name}")
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


@router.get("/network/host/config")
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
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to apply host network configuration: {e}")


@router.post("/network/host/confirm", dependencies=[Depends(require_scope("system:config"))])
async def confirm_host_ip_config_endpoint(req: Optional[HostIpConfirmRequest] = None):
    """Confirm and seal host network configuration, cancelling the 60s rollback watchdog."""
    canary_id = req.canary_id if req else None
    res = await asyncio.to_thread(confirm_host_ip_config, canary_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Confirmation failed"))
    return res


@router.post("/network/host/revert", dependencies=[Depends(require_scope("system:config"))])
async def revert_host_ip_config_endpoint(req: Optional[HostIpRevertRequest] = None):
    """Manually abort Canary test and immediately restore previous host network configuration."""
    canary_id = req.canary_id if req else None
    res = await asyncio.to_thread(revert_host_ip_config, canary_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Reversion failed"))
    return res

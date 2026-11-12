"""
Kiboto - Network Management API Router
Provides REST endpoints for network topology, port tuning (MTU, WOL, speed/duplex),
friendly interface aliases, and Docker network management.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.errors import ApiError
from backend.hardware.net.host import NotOnThisHost, current_host
from backend.hardware.network import (
    create_docker_network,
    delete_docker_network,
    get_bond_config,
    get_bridge_config,
    get_host_ip_config,
    get_network_topology,
    get_port_config,
    get_vlans,
    save_port_alias,
)

router = APIRouter(tags=["Network & Switching"])


def _change(setting: str, target: str, changes: dict) -> dict:
    """A change to the host's wiring: made only where Kiboto manages the host (SET-16, D2)."""
    try:
        return current_host().apply(setting, target, changes)
    except NotOnThisHost as e:
        raise ApiError(409, str(e), "not_on_this_host") from None


@router.get("/network/capabilities", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def get_network_capabilities():
    """What Kiboto may change on this host's network, and where the host's own settings are."""
    return await asyncio.to_thread(lambda: current_host().capabilities())


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
    """A port's nickname (always), or its packet size, speed or Wake-on-LAN (only on a host Kiboto manages; 409 not_on_this_host elsewhere)."""
    updates = req.model_dump(exclude_unset=True)
    alias = updates.pop("alias", None)
    res: dict = {"status": "ok"}
    if updates:  # packet size, speed, Wake-on-LAN: the host's wiring, refused whole where it is not Kiboto's
        res = await asyncio.to_thread(_change, "port", iface_name, updates)
    if alias is not None:  # the nickname is Kiboto's own label
        res["alias"] = await asyncio.to_thread(save_port_alias, iface_name, alias)
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
    """Change the host's address: only on a host Kiboto manages (409 not_on_this_host elsewhere)."""
    return await asyncio.to_thread(_change, "address", "", req.model_dump(exclude_unset=True))


@router.post("/network/host/confirm", dependencies=[Depends(require_scope("system:config"))])
async def confirm_host_ip_config_endpoint(req: HostIpConfirmRequest | None = None):
    """Keep a trial address: only on a host Kiboto manages (409 not_on_this_host elsewhere)."""
    return await asyncio.to_thread(_change, "address", "", {"confirm": req.canary_id if req else None})


@router.post("/network/host/revert", dependencies=[Depends(require_scope("system:config"))])
async def revert_host_ip_config_endpoint(req: HostIpRevertRequest | None = None):
    """Go back from a trial address: only on a host Kiboto manages (409 not_on_this_host elsewhere)."""
    return await asyncio.to_thread(_change, "address", "", {"revert": req.canary_id if req else None})


@router.get("/network/bond/{bond_name}", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def get_bond_config_endpoint(bond_name: str):
    """Retrieve configuration, operational mode, active slave, and candidates for a bonding group."""
    res = await asyncio.to_thread(get_bond_config, bond_name)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res.get("message", "Bond interface not found"))
    return res


@router.post("/network/bond/{bond_name}", dependencies=[Depends(require_scope("system:config"))])
async def update_bond_config_endpoint(bond_name: str, req: BondConfigUpdateRequest):
    """Change a bond: only on a host Kiboto manages (409 not_on_this_host elsewhere)."""
    return await asyncio.to_thread(_change, "bond", bond_name, req.model_dump(exclude_unset=True))


@router.get("/network/bridge/{br_name}", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def get_bridge_config_endpoint(br_name: str):
    """Retrieve configuration, STP state, forward delay, and members for a virtual bridge."""
    res = await asyncio.to_thread(get_bridge_config, br_name)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res.get("message", "Bridge interface not found"))
    return res


@router.post("/network/bridge/{br_name}", dependencies=[Depends(require_scope("system:config"))])
async def update_bridge_config_endpoint(br_name: str, req: BridgeConfigUpdateRequest):
    """Change a bridge: only on a host Kiboto manages (409 not_on_this_host elsewhere)."""
    return await asyncio.to_thread(_change, "bridge", br_name, req.model_dump(exclude_unset=True))


@router.get("/network/vlans", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def get_vlans_endpoint():
    """list all active and configured 802.1Q VLAN sub-interfaces."""
    return {"status": "ok", "vlans": await asyncio.to_thread(get_vlans)}


@router.post("/network/vlan/create", dependencies=[Depends(require_scope("system:config"))])
async def create_vlan_endpoint(req: VlanCreateRequest):
    """Add a VLAN: only on a host Kiboto manages (409 not_on_this_host elsewhere)."""
    return await asyncio.to_thread(_change, "vlan", req.parent, req.model_dump(exclude_unset=True))


@router.delete("/network/vlan/{vlan_iface}", dependencies=[Depends(require_scope("system:config"))])
async def delete_vlan_endpoint(vlan_iface: str):
    """Remove a VLAN: only on a host Kiboto manages (409 not_on_this_host elsewhere)."""
    return await asyncio.to_thread(_change, "vlan", vlan_iface, {"delete": True})


class RemoteAccessConnectRequest(BaseModel):
    login_server: str = Field(default="", max_length=255, description="A Headscale server; empty for Tailscale")
    auth_key: str = Field(default="", max_length=512, description="A pre-auth key, to sign in without a browser")


class RemoteAccessPublishRequest(BaseModel):
    app_port: int | None = Field(default=None, ge=1, le=65535, description="The port Kiboto is opened on here")


def _remote(fn, *args):
    from backend.services.remote_access import RemoteAccessError

    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except RemoteAccessError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


def _may_change(principal: AuthenticatedPrincipal) -> bool:
    return principal.has_scope("system:config")


@router.get("/network/remote-access", dependencies=[Depends(require_scope("system:view"))])
async def get_remote_access(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Use from anywhere (COMP-01): tailnet state, sign-in link, and the addresses to open.
    The sign-in link only for someone who may change settings: opened with another account, it
    joins the NAS to that account's network (SET-02)."""
    from backend.services import remote_access

    st = await asyncio.to_thread(remote_access.status)
    return st if _may_change(principal) else {**st, "auth_url": ""}


def _ask_before_installing_tailscale(request: Request, principal: AuthenticatedPrincipal) -> None:
    """Putting Tailscale on the NAS means a container on the host's network that may change its
    network settings: asked on the server, once, before it is created (SET-02)."""
    from backend.confirmations import confirm_or_raise
    from backend.hardware.net import tailscale

    if not tailscale.installed():
        confirm_or_raise(request, principal, "network.tailscale_install", "tailscale")


class NetbirdConnectRequest(BaseModel):
    setup_key: str = Field(..., max_length=128, description="A setup key from NetBird Cloud or your own NetBird server")
    management_url: str = Field(
        default="", max_length=255, description="Your own NetBird server; empty for NetBird Cloud"
    )


@router.get("/network/remote-access/netbird", dependencies=[Depends(require_scope("system:view"))])
async def get_netbird(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """NetBird's state (SET-16N); the address and devices only for someone who may change settings."""
    from backend.services import netbird

    s = await asyncio.to_thread(netbird.status)
    if _may_change(principal):
        return s
    return {"state": s.get("state")}


@router.post("/network/remote-access/netbird/connect", dependencies=[Depends(require_scope("system:config"))])
async def post_netbird_connect(
    req: NetbirdConnectRequest, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Joins NetBird with a setup key; asks first before its container is put on the host's network."""
    from backend.confirmations import confirm_or_raise
    from backend.services import netbird

    if not (await asyncio.to_thread(netbird.container))["exists"]:
        confirm_or_raise(request, principal, "network.netbird_install", "netbird")
    try:
        return await asyncio.to_thread(netbird.connect, req.setup_key, req.management_url)
    except netbird.NetbirdError as e:
        raise ApiError(400, str(e), "netbird_failed") from None


@router.post("/network/remote-access/netbird/disconnect", dependencies=[Depends(require_scope("system:config"))])
async def post_netbird_disconnect():
    """Leaves NetBird; the container and its sign-in stay for next time."""
    from backend.services import netbird

    return await asyncio.to_thread(netbird.disconnect)


@router.post("/network/remote-access/connect", dependencies=[Depends(require_scope("system:config"))])
async def post_remote_access_connect(
    req: RemoteAccessConnectRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Joins Tailscale, or a Headscale server; answers with the sign-in link when one is needed."""
    from backend.services import remote_access

    _ask_before_installing_tailscale(request, principal)

    return await asyncio.to_thread(_remote, remote_access.connect, req.login_server, req.auth_key)


@router.post("/network/remote-access/publish", dependencies=[Depends(require_scope("system:config"))])
async def post_remote_access_publish(req: RemoteAccessPublishRequest):
    """HTTPS addresses in the tailnet for Kiboto and Immich."""
    from backend.services import remote_access

    return await asyncio.to_thread(_remote, remote_access.publish, req.app_port)


@router.post("/network/remote-access/disconnect", dependencies=[Depends(require_scope("system:config"))])
async def post_remote_access_disconnect():
    from backend.services import remote_access

    return await asyncio.to_thread(remote_access.disconnect)


@router.get("/network/mesh-vpn", dependencies=[Depends(require_scope("system:view"))])
async def get_mesh_vpn_endpoint(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Retrieves Zero-Trust Mesh VPN telemetry and status for Tailscale and WireGuard. The sign-in
    link, the devices with the addresses they connect from and the names of received files only
    for someone who may change settings; others get the counts (SET-02)."""
    from backend.hardware.network import cached_mesh_vpn_status

    doc = await asyncio.to_thread(cached_mesh_vpn_status)
    if _may_change(principal) or not isinstance(doc, dict):
        return doc
    ts = doc.get("tailscale")
    if isinstance(ts, dict):
        doc = {**doc, "tailscale": {**ts, "auth_url": "", "peers": [], "taildrop_files": []}}
    return doc


class TailscaleSetRoutesRequest(BaseModel):
    routes: str = Field(default="", max_length=512)
    enabled: bool = Field(default=True)


class TailscaleSetExitNodeRequest(BaseModel):
    enabled: bool = Field(default=True)


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


@router.post("/network/mesh-vpn/tailscale/reauth", dependencies=[Depends(require_scope("system:config"))])
async def post_tailscale_reauth():
    """Forces node re-authentication before node key expiration."""
    from backend.hardware.network import execute_tailscale_reauth

    return await asyncio.to_thread(execute_tailscale_reauth)


@router.get("/network/ports/listening", dependencies=[Depends(require_scope("system:config", "system:read"))])
async def get_listening_ports():
    """Returns active listening TCP and UDP ports and mapped container services."""
    from backend.hardware.network import get_active_listening_ports

    ports = await asyncio.to_thread(get_active_listening_ports)
    return {"ports": ports, "total": len(ports)}


# Removed in SET-16 (decisions D3 and D5, and the old connect form the "Use from anywhere" card
# replaced): for one release these answer 410 with what replaced them, so a script that still
# calls them learns why instead of meeting a 404.
_GONE = {
    ("POST", "/network/mesh-vpn/tailscale/up"): "Use POST /api/network/remote-access/connect.",
    ("POST", "/network/mesh-vpn/tailscale/down"): "Use POST /api/network/remote-access/disconnect.",
    ("POST", "/network/mesh-vpn/tailscale/deploy"): "Use POST /api/network/remote-access/connect.",
    (
        "POST",
        "/network/mesh-vpn/tailscale/set-ssh",
    ): "Tailscale SSH was removed: it opened the Tailscale container, not the NAS.",
    ("POST", "/network/mesh-vpn/tailscale/set-serve"): "Use POST /api/network/remote-access/publish.",
    ("POST", "/network/mesh-vpn/tailscale/taildrop/receive"): "Taildrop was removed.",
    ("GET", "/network/mesh-vpn/tailscale/taildrop/files"): "Taildrop was removed.",
    ("POST", "/network/mesh-vpn/tailscale/ping"): "Ping was removed.",
    (
        "POST",
        "/network/mesh-vpn/wireguard/client-config",
    ): "WireGuard was removed: it never produced a working connection.",
    (
        "GET",
        "/network/mesh-vpn/wireguard/subnet-routing",
    ): "WireGuard was removed: it never produced a working connection.",
    (
        "POST",
        "/network/mesh-vpn/wireguard/subnet-routing",
    ): "WireGuard was removed: it never produced a working connection.",
}


def _gone_route(method: str, path: str, why: str) -> None:
    async def gone():
        raise ApiError(410, why, "removed")

    gone.__doc__ = f"Removed (SET-16). {why}"
    scope = "system:view" if method == "GET" else "system:config"
    router.add_api_route(
        path, gone, methods=[method], dependencies=[Depends(require_scope(scope))], include_in_schema=False
    )


for (_method, _path), _why in _GONE.items():
    _gone_route(_method, _path, _why)

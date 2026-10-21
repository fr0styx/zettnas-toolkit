"""Docker network topology for the Containers Network Map."""

from unittest.mock import patch

from backend.services.docker_network_topology import get_network_topology, summarize_topology

NETWORKS = [
    {
        "Name": "bridge",
        "Id": "a" * 64,
        "Driver": "bridge",
        "Scope": "local",
        "IPAM": {"Config": [{"Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1"}]},
    },
    {
        "Name": "immich_default",
        "Id": "b" * 64,
        "Driver": "bridge",
        "Scope": "local",
        "IPAM": {"Config": [{"Subnet": "172.20.0.0/16"}]},
    },
    {"Name": "host", "Id": "c" * 64, "Driver": "host", "Scope": "local", "IPAM": {"Config": []}},
    {"Name": "unused_net", "Id": "d" * 64, "Driver": "bridge", "Internal": True},
    {"Id": "no-name"},
]

CONTAINERS = [
    {
        "Id": "1" * 64,
        "Names": ["/immich_server"],
        "State": "running",
        "HostConfig": {"NetworkMode": "immich_default"},
        "Labels": {"com.docker.compose.project": "immich"},
        "NetworkSettings": {
            "Networks": {
                "immich_default": {"IPAddress": "172.20.0.5", "MacAddress": "02:42:ac:14:00:05"},
                "bridge": {"IPAddress": "172.17.0.9"},
            }
        },
        "Ports": [
            {"PrivatePort": 2283, "PublicPort": 2283, "Type": "tcp", "IP": "0.0.0.0"},
            {"PrivatePort": 2283, "PublicPort": 2283, "Type": "tcp", "IP": "::"},
        ],
    },
    {
        "Id": "2" * 64,
        "Names": ["/gluetun"],
        "State": "running",
        "HostConfig": {"NetworkMode": "bridge"},
        "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.17.0.2"}}},
    },
    {
        "Id": "3" * 64,
        "Names": ["/qbittorrent"],
        "State": "running",
        "HostConfig": {"NetworkMode": "container:" + "2" * 64},
        "NetworkSettings": {"Networks": {}},
    },
    {
        "Id": "4" * 64,
        "Names": ["/plex"],
        "State": "exited",
        "HostConfig": {"NetworkMode": "host"},
        "NetworkSettings": {"Networks": {"host": {}, "ghost_net": {"NetworkID": "e" * 64}}},
    },
    "garbage",
]


def test_networks_carry_driver_subnet_and_counts():
    topo = summarize_topology(NETWORKS, CONTAINERS)
    nets = {n["name"]: n for n in topo["networks"]}
    assert nets["bridge"]["subnet"] == "172.17.0.0/16" and nets["bridge"]["gateway"] == "172.17.0.1"
    assert nets["bridge"]["container_count"] == 2
    assert nets["immich_default"]["container_count"] == 1
    assert nets["unused_net"]["container_count"] == 0 and nets["unused_net"]["internal"] is True
    # attached to a network missing from /networks: still shown
    assert nets["ghost_net"]["id"] == "e" * 12
    # busiest first, unused last
    assert topo["networks"][0]["name"] == "bridge"
    assert topo["networks"][-1]["name"] == "unused_net"


def test_containers_have_networks_ips_and_deduped_ports():
    topo = summarize_topology(NETWORKS, CONTAINERS)
    by_name = {c["name"]: c for c in topo["containers"]}
    immich = by_name["immich_server"]
    assert immich["id"] == "1" * 12
    assert immich["compose_project"] == "immich"
    assert [(a["network"], a["ip"]) for a in immich["networks"]] == [
        ("bridge", "172.17.0.9"),
        ("immich_default", "172.20.0.5"),
    ]
    assert immich["ports"] == [{"private": 2283, "public": 2283, "type": "tcp"}]
    assert [c["name"] for c in topo["containers"]] == sorted(by_name, key=str.lower)


def test_shared_network_namespace_resolves_container_name():
    topo = summarize_topology(NETWORKS, CONTAINERS)
    qbit = next(c for c in topo["containers"] if c["name"] == "qbittorrent")
    assert qbit["networks"] == []
    assert qbit["shares_with"] == "gluetun"


def test_bad_input_is_tolerated():
    assert summarize_topology(None, {"not": "a list"}) == {"networks": [], "containers": []}


def test_get_network_topology_queries_docker():
    calls = []

    def fake(method, path, timeout=0):
        calls.append(path)
        return 200, NETWORKS if path == "/networks" else CONTAINERS

    topo = get_network_topology(fake)
    assert calls == ["/networks", "/containers/json?all=1"]
    assert len(topo["containers"]) == 4


def test_endpoint_returns_topology_and_503_when_docker_fails(client, auth_headers):
    with patch(
        "backend.services.docker_network_topology.get_network_topology", return_value={"networks": [], "containers": []}
    ):
        res = client.get("/api/docker/networks/topology", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"networks": [], "containers": []}

    with patch("backend.services.docker_network_topology.get_network_topology", side_effect=RuntimeError("no socket")):
        res = client.get("/api/docker/networks/topology", headers=auth_headers)
    assert res.status_code == 503

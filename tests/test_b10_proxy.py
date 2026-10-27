"""B10 / SEC-25: the Docker proxy's ways to the host are closed for create and file writes."""

import json

import pytest

from backend import docker_proxy as dp


def _create(hc):
    return dp.check_request(
        "POST", "/v1.45/containers/create", {}, json.dumps({"Image": "x", "HostConfig": hc}).encode()
    )


@pytest.mark.parametrize(
    "hc, reason",
    [
        ({"VolumesFrom": ["zettnas-toolkit"]}, "volumes-from"),
        ({"PidMode": "container:zettnas-toolkit"}, "PidMode=container:"),
        ({"NetworkMode": "container:abc"}, "NetworkMode=container:"),
        ({"CgroupnsMode": "host"}, "CgroupnsMode=host"),
        (
            {
                "Mounts": [
                    {
                        "Type": "volume",
                        "Target": "/x",
                        "VolumeOptions": {"DriverConfig": {"Options": {"type": "none", "o": "bind", "device": "/"}}},
                    }
                ]
            },
            "volume bind /",
        ),
        ({"SecurityOpt": ['seccomp={"defaultAction":"SCMP_ACT_ALLOW"}']}, "custom seccomp"),
    ],
)
def test_ways_to_the_host_need_confirmation(hc, reason):
    ok, msg, reasons = _create(hc)
    assert not ok and any(reason in r for r in reasons), (msg, reasons)


def test_ordinary_containers_pass():
    ok, _, reasons = _create(
        {"Binds": ["/mnt/user/photos:/photos"], "NetworkMode": "bridge", "SecurityOpt": ["seccomp=default"]}
    )
    assert ok and reasons == []


def test_writing_files_into_a_container_needs_confirmation():
    ok, msg, _ = dp.check_request("PUT", "/v1.45/containers/zettnas-toolkit/archive?path=/app", {}, b"")
    assert not ok and "confirmation" in msg
    ok, _, _ = dp.check_request("PUT", "/containers/abc/archive?path=/x", {dp.ELEVATED_HEADER: "1"}, b"")
    assert ok
    ok, _, _ = dp.check_request("HEAD", "/containers/abc/archive?path=/x", {}, None)
    assert ok  # reading a file's details stays allowed

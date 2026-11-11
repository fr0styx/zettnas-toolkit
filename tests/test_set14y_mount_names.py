"""SET-14: the details carry a volume's name, so the Edit form saves the volume and not Docker's folder for it."""

from unittest.mock import patch

from backend.services import compose_synthesizer

INSPECT = {
    "Id": "c1" * 6,
    "Name": "/jellyfin",
    "Config": {"Env": [], "Labels": {}, "Image": "x:latest"},
    "HostConfig": {"NetworkMode": "bridge"},
    "State": {"Running": True, "Status": "running"},
    "NetworkSettings": {},
    "Mounts": [
        {
            "Type": "volume",
            "Name": "jf-cache",
            "Source": "/var/lib/docker/volumes/jf-cache/_data",
            "Destination": "/cache",
            "Mode": "z",
            "RW": True,
        },
        {"Type": "bind", "Source": "/mnt/user/appdata/jellyfin", "Destination": "/config", "Mode": "rw", "RW": True},
    ],
}


def test_volume_name_is_sent():
    with patch.object(compose_synthesizer, "fetch_container_raw_inspect", return_value=INSPECT):
        out = compose_synthesizer.get_container_full_details("jellyfin")
    mounts = {m["destination"]: m for m in out["mounts"]}
    assert mounts["/cache"]["name"] == "jf-cache"
    assert mounts["/config"]["name"] == ""

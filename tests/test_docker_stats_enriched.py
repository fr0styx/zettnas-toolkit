import unittest
from unittest.mock import MagicMock, patch

from backend.hardware.docker_stats import (
    _classify_stack,
    _extract_appdata_path,
    _extract_hardware_badges,
    _parse_ports_and_webui,
    read_docker_containers,
)


class TestDockerStatsEnriched(unittest.TestCase):
    def test_parse_ports_and_webui_unraid_label(self):
        raw_ports = [
            {"PrivatePort": 8096, "PublicPort": 8888, "Type": "tcp", "IP": "0.0.0.0"},
            {"PrivatePort": 8096, "PublicPort": 8888, "Type": "tcp", "IP": "::"},
        ]
        labels = {"net.unraid.docker.webui": "http://[IP]:[PORT:8096]/"}
        parsed, primary_port, webui_url = _parse_ports_and_webui(raw_ports, labels)

        self.assertEqual(len(parsed), 1)  # Deduplicated IPv4/IPv6
        self.assertEqual(primary_port, 8888)
        self.assertEqual(webui_url, "http://[HOST]:8888/")

    def test_parse_ports_and_webui_well_known_port(self):
        raw_ports = [
            {"PrivatePort": 2283, "PublicPort": 2283, "Type": "tcp"},
        ]
        labels = {}
        parsed, primary_port, webui_url = _parse_ports_and_webui(raw_ports, labels)

        self.assertEqual(primary_port, 2283)
        self.assertEqual(webui_url, "http://[HOST]:2283/")

    def test_parse_ports_and_webui_https_port(self):
        raw_ports = [
            {"PrivatePort": 443, "PublicPort": 8443, "Type": "tcp"},
        ]
        labels = {}
        parsed, primary_port, webui_url = _parse_ports_and_webui(raw_ports, labels)

        self.assertEqual(primary_port, 8443)
        self.assertEqual(webui_url, "https://[HOST]:8443/")

    def test_parse_ports_and_webui_no_public_ports(self):
        raw_ports = [
            {"PrivatePort": 5432, "Type": "tcp"},
        ]
        labels = {}
        parsed, primary_port, webui_url = _parse_ports_and_webui(raw_ports, labels)

        self.assertIsNone(primary_port)
        self.assertIsNone(webui_url)

    def test_classify_stack(self):
        # Compose
        stack, srv, managed = _classify_stack(
            {"com.docker.compose.project": "arr", "com.docker.compose.service": "jellyfin"}
        )
        self.assertEqual(stack, "arr")
        self.assertEqual(srv, "jellyfin")
        self.assertEqual(managed, "compose")

        # Unraid Native
        stack, srv, managed = _classify_stack({"net.unraid.docker.managed": "dockerman"})
        self.assertIsNone(stack)
        self.assertEqual(managed, "unraid")

        # Standalone
        stack, srv, managed = _classify_stack({})
        self.assertIsNone(stack)
        self.assertEqual(managed, "standalone")

    def test_extract_hardware_badges(self):
        # DRI / GPU
        mounts = [{"Source": "/dev/dri", "Destination": "/dev/dri"}]
        badges = _extract_hardware_badges(mounts, [], [])
        self.assertTrue(any(b["id"] == "gpu" for b in badges))

        # NVIDIA CUDA
        badges_nv = _extract_hardware_badges([], [], ["NVIDIA_VISIBLE_DEVICES=all", "CUDA_VERSION=12.0"])
        self.assertTrue(any(b["id"] == "nvidia" for b in badges_nv))

        # AMD ROCm / KFD
        devices_kfd = [{"PathOnHost": "/dev/kfd"}]
        badges_rocm = _extract_hardware_badges([], devices_kfd, [])
        self.assertTrue(any(b["id"] == "rocm" for b in badges_rocm))

        # Coral TPU
        devices_tpu = [{"PathOnHost": "/dev/apex_0"}]
        badges_tpu = _extract_hardware_badges([], devices_tpu, [])
        self.assertTrue(any(b["id"] == "tpu" for b in badges_tpu))

        # Serial
        devices_serial = [{"PathOnHost": "/dev/ttyUSB0"}]
        badges_serial = _extract_hardware_badges([], devices_serial, [])
        self.assertTrue(any(b["id"] == "serial" for b in badges_serial))

    def test_extract_appdata_path(self):
        mounts = [
            {"Source": "/mnt/user/appdata/docker/jellyfin", "Destination": "/config"},
            {"Source": "/mnt/user/media", "Destination": "/media"},
        ]
        path = _extract_appdata_path(mounts)
        self.assertEqual(path, "/mnt/user/appdata/docker/jellyfin")

    @patch("backend.hardware.docker_stats.os.path.exists")
    def test_read_docker_containers_socket_missing(self, mock_exists):
        mock_exists.return_value = False
        res = read_docker_containers(force=True)
        self.assertEqual(res, [])


if __name__ == "__main__":
    unittest.main()

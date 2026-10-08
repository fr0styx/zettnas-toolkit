import struct
import unittest
from unittest.mock import MagicMock, patch

from backend.services.compose_synthesizer import (
    format_compose_yaml,
    get_container_compose_data,
    get_container_full_details,
    get_container_logs_chunk,
    is_secret_key,
    mask_secret_value,
    synthesize_compose_spec,
)


class TestComposeSynthesizer(unittest.TestCase):
    def test_secret_key_detection(self):
        self.assertTrue(is_secret_key("API_KEY"))
        self.assertTrue(is_secret_key("DATABASE_PASSWORD"))
        self.assertTrue(is_secret_key("JWT_SECRET_TOKEN"))
        self.assertTrue(is_secret_key("AWS_CREDENTIALS"))
        self.assertFalse(is_secret_key("PUID"))
        self.assertFalse(is_secret_key("TZ"))
        self.assertFalse(is_secret_key("APP_NAME"))

    def test_mask_secret_value(self):
        self.assertEqual(mask_secret_value("my_super_secret"), "••••••••")
        self.assertEqual(mask_secret_value(""), "")

    def test_synthesize_compose_spec(self):
        inspect_data = {
            "Name": "/jellyfin",
            "Config": {
                "Image": "lscr.io/linuxserver/jellyfin:latest",
                "Env": ["PUID=1000", "PGID=1000", "API_KEY=secret_val_123"],
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "unless-stopped"},
                "PortBindings": {
                    "8096/tcp": [{"HostPort": "8096"}],
                },
                "Devices": [{"PathOnHost": "/dev/dri", "PathInContainer": "/dev/dri"}],
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/mnt/user/appdata/docker/jellyfin",
                    "Destination": "/config",
                    "Mode": "rw",
                    "RW": True,
                }
            ],
        }

        # Unmasked spec
        srv, spec = synthesize_compose_spec(inspect_data, mask_secrets=False)
        self.assertEqual(srv, "jellyfin")
        self.assertEqual(spec["image"], "lscr.io/linuxserver/jellyfin:latest")
        self.assertEqual(spec["restart"], "unless-stopped")
        self.assertIn("8096:8096/tcp", spec["ports"])
        self.assertIn("/mnt/user/appdata/docker/jellyfin:/config:rw", spec["volumes"])
        self.assertIn("/dev/dri:/dev/dri", spec["devices"])
        self.assertIn("API_KEY=secret_val_123", spec["environment"])

        # Masked spec
        _, masked_spec = synthesize_compose_spec(inspect_data, mask_secrets=True)
        self.assertIn("API_KEY=••••••••", masked_spec["environment"])

    def test_format_compose_yaml(self):
        spec = {
            "image": "lscr.io/linuxserver/jellyfin:latest",
            "container_name": "jellyfin",
            "restart": "unless-stopped",
            "ports": ["8096:8096/tcp"],
            "volumes": ["/mnt/user/appdata/jellyfin:/config:rw"],
        }
        yaml_str = format_compose_yaml("jellyfin", spec)
        self.assertIn('version: "3.8"', yaml_str)
        self.assertIn("services:", yaml_str)
        self.assertIn("  jellyfin:", yaml_str)
        self.assertIn('    image: "lscr.io/linuxserver/jellyfin:latest"', yaml_str)
        self.assertIn('      - "8096:8096/tcp"', yaml_str)

    @patch("backend.services.compose_synthesizer.fetch_container_raw_inspect")
    def test_get_container_compose_data_fallback_synthesized(self, mock_inspect):
        mock_inspect.return_value = {
            "Id": "c123456789012345",
            "Name": "/standalone-app",
            "Config": {"Image": "my-app:1.0", "Env": []},
            "HostConfig": {"RestartPolicy": {"Name": "always"}},
            "Mounts": [],
        }
        data = get_container_compose_data("standalone-app")
        self.assertEqual(data["source"], "synthesized")
        self.assertEqual(data["name"], "standalone-app")
        self.assertIn("my-app:1.0", data["compose_yaml"])

    @patch("backend.services.compose_synthesizer.fetch_container_raw_inspect")
    def test_get_container_full_details(self, mock_inspect):
        mock_inspect.return_value = {
            "Id": "c123456789012345",
            "Name": "/my-service",
            "Config": {
                "Image": "redis:alpine",
                "Env": ["REDIS_PASSWORD=supersecret", "PORT=6379"],
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "always"},
                "NetworkMode": "bridge",
            },
            "State": {
                "Status": "running",
                "Running": True,
                "StartedAt": "2026-10-08T12:00:00Z",
            },
            "Mounts": [
                {
                    "Source": "/mnt/user/appdata/redis",
                    "Destination": "/data",
                    "Mode": "rw",
                    "RW": True,
                }
            ],
            "NetworkSettings": {
                "IPAddress": "172.17.0.4",
            },
        }
        details = get_container_full_details("my-service")
        self.assertEqual(details["overview"]["name"], "my-service")
        self.assertEqual(details["overview"]["state"], "running")
        self.assertEqual(details["overview"]["ip_address"], "172.17.0.4")
        self.assertEqual(len(details["mounts"]), 1)
        self.assertTrue(details["mounts"][0]["is_appdata"])
        self.assertEqual(len(details["env"]), 2)
        # Verify secret classification
        sec_env = next(e for e in details["env"] if e["key"] == "REDIS_PASSWORD")
        self.assertTrue(sec_env["is_secret"])
        self.assertEqual(sec_env["masked_value"], "••••••••")

    @patch("backend.services.compose_synthesizer.UnixHTTPConnection")
    @patch("backend.services.compose_synthesizer.os.path.exists")
    def test_get_container_logs_chunk(self, mock_exists, mock_conn_cls):
        mock_exists.return_value = True

        # Build mock 8-byte framed Docker payload
        # Stream 1 = stdout, Stream 2 = stderr
        msg1 = b"2026-10-08T12:00:01Z System ready\n"
        hdr1 = struct.pack(">BxxxI", 1, len(msg1))
        msg2 = b"2026-10-08T12:00:02Z Warning message\n"
        hdr2 = struct.pack(">BxxxI", 2, len(msg2))
        raw_payload = hdr1 + msg1 + hdr2 + msg2

        mock_res = MagicMock()
        mock_res.read.return_value = raw_payload
        mock_conn = MagicMock()
        mock_conn.getresponse.return_value = mock_res
        mock_conn_cls.return_value = mock_conn

        logs = get_container_logs_chunk("my-container", tail=100)
        self.assertEqual(logs["count"], 2)
        self.assertEqual(logs["lines"][0]["stream"], "stdout")
        self.assertEqual(logs["lines"][0]["msg"], "System ready")
        self.assertEqual(logs["lines"][1]["stream"], "stderr")
        self.assertEqual(logs["lines"][1]["msg"], "Warning message")


if __name__ == "__main__":
    unittest.main()

"""Container stats: one-shot requests, and a slow refresh while nobody is looking (PERF-6)."""

import json
from unittest.mock import patch

from backend.hardware import docker_stats as ds


class _Res:
    status = 200

    def __init__(self, body):
        self._b = json.dumps(body).encode()

    def read(self):
        return self._b


def _sample(total, system):
    return {
        "cpu_stats": {"cpu_usage": {"total_usage": total}, "system_cpu_usage": system, "online_cpus": 4},
        "precpu_stats": {},
        "memory_stats": {"usage": 100, "limit": 1000},
        "networks": {},
    }


def test_repeat_requests_are_one_shot_and_cpu_uses_the_last_sample():
    ds._PREV_CPU.clear()
    paths, bodies = [], [_sample(1_000, 100_000), _sample(3_000, 104_000)]

    class Conn:
        def __init__(self, *a, **k):
            pass

        def request(self, method, path):
            paths.append(path)

        def getresponse(self):
            return _Res(bodies.pop(0))

        def close(self):
            pass

    with (
        patch.object(ds, "UnixHTTPConnection", Conn),
        patch.object(ds.os.path, "exists", return_value=True),
        patch.object(ds, "_kernel_telemetry", return_value=None),  # dockerd answers (PERF-4 falls back to it)
    ):
        ds._fetch_container_telemetry("abc")
        second = ds._fetch_container_telemetry("abc")
    assert "one-shot" not in paths[0] and paths[1].endswith("&one-shot=true")
    assert second["cpu_pct"] == 200.0  # (2000 / 4000) x 4 CPUs


def test_refresh_is_slow_until_someone_looks(monkeypatch):
    monkeypatch.setattr(ds, "_VIEWERS", 0)
    monkeypatch.setattr(ds, "_LAST_DEMAND", 0.0)
    assert ds.container_poll_interval(now=10_000) == ds.IDLE_POLL_SECS
    ds.viewer_joined()
    assert ds.container_poll_interval() == ds.ACTIVE_POLL_SECS and ds._DEMAND_WAKE.is_set()
    ds.viewer_left()
    assert ds.container_poll_interval(now=ds._LAST_DEMAND + ds.DEMAND_WINDOW_SECS + 1) == ds.IDLE_POLL_SECS


def test_the_container_list_counts_as_demand(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ds, "_LAST_DEMAND", 0.0)
    with patch("backend.api.docker._resolve_read_docker_containers", return_value=lambda: []):
        assert client.get("/api/docker/containers", headers=auth_headers).status_code == 200
    assert ds.container_poll_interval() == ds.ACTIVE_POLL_SECS

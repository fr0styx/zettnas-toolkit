"""
Live-stats delta encoder for the SSE stream.

Browsers merge every SSE message into the stats they already hold
(``state.setStats`` in frontend/src/state.js), so a tick only needs the
keys whose values changed since the previous tick.

Containers get special handling because the full list is large
(~650 bytes per container) while only a few numbers move each tick:

- ``docker`` (the full list) is sent only when a container's structure
  changes: one is added, removed, reordered, renamed, started/stopped,
  re-imaged, gets new ports, and so on.
- Otherwise ``docker_tel`` carries just the changed live fields per
  container id, e.g. ``{"abc123": {"cpu_pct": 2.5, "mem_used": 1048576}}``.

A full tick (keyframe) is sent every ``KEYFRAME_SECS`` so a client can
never drift for long, and new subscribers always start from a full
snapshot (see ``StatsBroadcaster.subscribe``).
"""

import time
from typing import Any, Callable, Dict, List, Optional

from backend.fast_json import dumps as fast_dumps

DOCKER_TEL_FIELDS = ("cpu_pct", "mem_used", "mem_limit", "mem_pct", "net_rx", "net_tx", "status")
KEYFRAME_SECS = 300.0


def _docker_structure(docker: List[Dict[str, Any]]) -> str:
    return fast_dumps([{k: v for k, v in c.items() if k not in DOCKER_TEL_FIELDS} for c in docker])


def _docker_telemetry(docker: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for c in docker:
        cid = c.get("id")
        if cid:
            out[str(cid)] = {f: c.get(f) for f in DOCKER_TEL_FIELDS if f in c}
    return out


class StatsDeltaEncoder:
    """Turns each full stats tick into the smallest message clients can merge."""

    def __init__(self, keyframe_secs: float = KEYFRAME_SECS, clock: Callable[[], float] = time.monotonic):
        self._keyframe_secs = keyframe_secs
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self._last: Dict[str, str] = {}
        self._last_docker_structure: Optional[str] = None
        self._last_docker_tel: Dict[str, Dict[str, Any]] = {}
        self._last_keyframe: Optional[float] = None

    def encode(self, data: Dict[str, Any]) -> Dict[str, Any]:
        now = self._clock()
        keyframe = self._last_keyframe is None or (now - self._last_keyframe) >= self._keyframe_secs

        out: Dict[str, Any] = {}
        for key, value in data.items():
            if key == "docker":
                continue
            ser = fast_dumps(value)
            if keyframe or self._last.get(key) != ser:
                out[key] = value
                self._last[key] = ser

        docker = data.get("docker")
        if isinstance(docker, list):
            structure = _docker_structure(docker)
            tel = _docker_telemetry(docker)
            if keyframe or structure != self._last_docker_structure:
                out["docker"] = docker
                self._last_docker_structure = structure
            else:
                delta: Dict[str, Dict[str, Any]] = {}
                for cid, fields in tel.items():
                    prev = self._last_docker_tel.get(cid, {})
                    changed = {f: v for f, v in fields.items() if prev.get(f) != v}
                    if changed:
                        delta[cid] = changed
                if delta:
                    out["docker_tel"] = delta
            self._last_docker_tel = tel

        if keyframe:
            self._last_keyframe = now
        return out

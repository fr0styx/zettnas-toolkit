"""Request metrics (ARCH-10): how often each API route is called, how long it takes, and how
often it fails. Routes are counted by their template (/api/storage/shares/{name}), not the
raw path, so the number of series stays bounded."""

import threading
from bisect import bisect_left
from typing import Any

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count: dict[tuple[str, str, str], int] = {}
        self._hist: dict[tuple[str, str], list[int]] = {}
        self._sum: dict[tuple[str, str], float] = {}

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        status_class = f"{status // 100}xx"
        key = (method, route)
        with self._lock:
            self._count[(method, route, status_class)] = self._count.get((method, route, status_class), 0) + 1
            h = self._hist.setdefault(key, [0] * (len(BUCKETS) + 1))
            h[bisect_left(BUCKETS, seconds)] += 1
            self._sum[key] = self._sum.get(key, 0.0) + seconds

    def reset(self) -> None:
        with self._lock:
            self._count.clear()
            self._hist.clear()
            self._sum.clear()

    @staticmethod
    def _quantile(hist: list[int], q: float) -> float | None:
        total = sum(hist)
        if not total:
            return None
        need = q * total
        seen = 0
        for i, n in enumerate(hist):
            seen += n
            if seen >= need:
                return BUCKETS[i] if i < len(BUCKETS) else float("inf")
        return None

    def summary(self, top: int = 25) -> list[dict[str, Any]]:
        """Busiest routes first, with error counts and upper bounds of p50/p95 latency."""
        with self._lock:
            rows = []
            for (method, route), hist in self._hist.items():
                n = sum(hist)
                errors = sum(c for (m, r, s), c in self._count.items() if m == method and r == route and s == "5xx")
                client = sum(c for (m, r, s), c in self._count.items() if m == method and r == route and s == "4xx")
                rows.append(
                    {
                        "method": method,
                        "route": route,
                        "requests": n,
                        "server_errors": errors,
                        "client_errors": client,
                        "avg_ms": round(1000 * self._sum[(method, route)] / n, 1) if n else None,
                        "p50_ms_max": _ms(self._quantile(hist, 0.5)),
                        "p95_ms_max": _ms(self._quantile(hist, 0.95)),
                    }
                )
        rows.sort(key=lambda r: r["requests"], reverse=True)
        return rows[:top]

    def prometheus(self) -> str:
        """Counter and histogram in the Prometheus text format."""
        with self._lock:
            out = [
                "# HELP zettnas_http_requests_total API requests by route and status class",
                "# TYPE zettnas_http_requests_total counter",
            ]
            for (m, r, s), c in sorted(self._count.items()):
                out.append(f'zettnas_http_requests_total{{method="{m}",route="{_esc(r)}",status="{s}"}} {c}')
            out += [
                "# HELP zettnas_http_request_duration_seconds API request duration",
                "# TYPE zettnas_http_request_duration_seconds histogram",
            ]
            for (m, r), hist in sorted(self._hist.items()):
                labels = f'method="{m}",route="{_esc(r)}"'
                cum = 0
                for i, b in enumerate(BUCKETS):
                    cum += hist[i]
                    out.append(f'zettnas_http_request_duration_seconds_bucket{{{labels},le="{b}"}} {cum}')
                cum += hist[-1]
                out.append(f'zettnas_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {cum}')
                out.append(f"zettnas_http_request_duration_seconds_sum{{{labels}}} {self._sum[(m, r)]:.6f}")
                out.append(f"zettnas_http_request_duration_seconds_count{{{labels}}} {cum}")
        return "\n".join(out) + "\n"


def _ms(v: float | None) -> float | None:
    if v is None:
        return None
    return None if v == float("inf") else round(v * 1000, 1)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


REQUEST_METRICS = RequestMetrics()


_PREFIXES = ("/api/v1", "/api", "/redfish/v1", "/redfish", "")


def route_template(scope: Any) -> str:
    """/api/storage/shares/{name} for a request to /api/storage/shares/media.

    Included routers keep their own paths (/storage/shares/{name}); the prefix they were
    included under is found by matching the route against the end of the request path."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    if not path:
        return "unmatched"
    regex = getattr(route, "path_regex", None)
    full = str(scope.get("path") or "")
    for prefix in _PREFIXES:
        if full.startswith(prefix) and (regex is None or regex.match(full[len(prefix) :])):
            return prefix + str(path)
    return str(path)

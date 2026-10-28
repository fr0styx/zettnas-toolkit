"""The vector index at scale (AI-18), for the self-hosted runner and for anyone who wants to know.

Builds a temporary database of synthetic chunks the way the app stores them (each chunk's float
vector in a table, its int8 copy in a vec0 index), then times the app's search path: the
nearest 200 in the int8 index, their float vectors read back, and the exact cosine order of
those 200. Budgets:

  p95-100k   p95 search time at 100,000 chunks, ms     <= 150
  p95-1m     p95 search time at 1,000,000 chunks, ms   <= 1500
  recall     recall@10 of int8 search + float rescoring against exact float search on
             clustered unit vectors                    >= 0.95

The public log says PASS or FAIL per budget only; numbers go to --results/vector-<date>.json on
the machine (Actions logs are public, see docs/HARDWARE_RUNNER.md). Budgets can be tuned with
HW_BUDGET_<NAME> (e.g. HW_BUDGET_P95_1M=2000). --print shows the numbers instead (local runs).

    python scripts/vector_bench.py --chunks 100000 1000000
    python scripts/vector_bench.py --chunks 20000 --print            # a quick look
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3
import struct
import sys
import tempfile
import time

DIM = 768
K = 200  # the app asks the index for at least 200 neighbours (rag_engine_search)
BUDGETS = {
    "p95-100k": float(os.environ.get("HW_BUDGET_P95_100K", "150")),
    "p95-1m": float(os.environ.get("HW_BUDGET_P95_1M", "1500")),
    "recall": float(os.environ.get("HW_BUDGET_RECALL", "0.95")),
}
_MASKS: dict[int, tuple[int, int]] = {}  # byte size -> (bits kept, bits set)


def load_vec(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            from backend.services.rag_embeddings import load_sqlite_vec_extension

            return load_sqlite_vec_extension(conn)
        except Exception:
            return False


def random_vectors(n: int, dim: int = DIM) -> bytes:
    """n float32 vectors with values of random sign and size 0.5..1, made from random bits
    without a per-value loop (the timing does not depend on how vectors are spread)."""
    size = 4 * dim * n
    if size not in _MASKS:
        _MASKS.clear()
        # keep the sign and mantissa bits, set the exponent of 0.5: a float of size 0.5..1
        _MASKS[size] = (
            int.from_bytes(b"\xff\xff\x7f\x80" * dim * n, "little"),
            int.from_bytes(b"\x00\x00\x00\x3f" * dim * n, "little"),
        )
    keep, set_bits = _MASKS[size]
    bits = int.from_bytes(os.urandom(size), "little")
    return ((bits & keep) | set_bits).to_bytes(size, "little")


def unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def build(path: str, n: int, dim: int = DIM, batch: int = 5000, vectors=None) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    if not load_vec(conn):
        raise RuntimeError("sqlite-vec is not available")
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY, embedding_f32 BLOB NOT NULL)")
    conn.execute(f"CREATE VIRTUAL TABLE idx USING vec0(chunk_id INTEGER PRIMARY KEY, embedding int8[{dim}])")
    done = 0
    while done < n:
        m = min(batch, n - done)
        if vectors is not None:
            rows = [(done + i + 1, struct.pack(f"<{dim}f", *vectors[done + i])) for i in range(m)]
        else:
            blob = random_vectors(m, dim)
            step = 4 * dim
            rows = [(done + i + 1, blob[i * step : (i + 1) * step]) for i in range(m)]
        conn.executemany("INSERT INTO chunks VALUES (?, ?)", rows)
        conn.executemany("INSERT INTO idx(chunk_id, embedding) VALUES (?, vec_quantize_int8(?, 'unit'))", rows)
        done += m
    conn.commit()
    return conn


def _cos(a: tuple, b: tuple) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def search(conn: sqlite3.Connection, q: bytes, top: int = 10, k: int = K, dim: int = DIM) -> list[int]:
    """The app's path: int8 nearest k, then the float vectors of those k in exact cosine order."""
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT chunk_id FROM idx WHERE embedding MATCH vec_quantize_int8(?, 'unit') AND k = ?", (q, k)
        )
    ]
    if not ids:
        return []
    qv = struct.unpack(f"<{dim}f", q)
    rows = conn.execute(
        f"SELECT chunk_id, embedding_f32 FROM chunks WHERE chunk_id IN ({','.join('?' * len(ids))})", ids
    )
    scored = sorted(((_cos(qv, struct.unpack(f"<{dim}f", b)), cid) for cid, b in rows), reverse=True)
    return [cid for _s, cid in scored[:top]]


def p95_ms(conn: sqlite3.Connection, queries: int, dim: int = DIM) -> float:
    times = []
    for _ in range(queries):
        q = random_vectors(1, dim)
        t0 = time.perf_counter()
        search(conn, q, dim=dim)
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    return times[min(len(times) - 1, math.ceil(0.95 * len(times)) - 1)]


def recall_at_10(n: int = 8000, dim: int = DIM, clusters: int = 80, queries: int = 20, seed: int = 7) -> float:
    """int8 search + float rescoring against exact float search, on unit vectors in clusters (how
    real embeddings spread), as a share of the true top 10 found."""
    rnd = random.Random(seed)
    centers = [unit([rnd.gauss(0, 1) for _ in range(dim)]) for _ in range(clusters)]
    vecs = []
    for i in range(n):
        c = centers[i % clusters]
        vecs.append(unit([x + rnd.gauss(0, 0.05) for x in c]))
    with tempfile.TemporaryDirectory() as d:
        conn = build(os.path.join(d, "r.db"), n, dim, vectors=vecs)
        hit = total = 0
        for qi in range(queries):
            c = centers[(qi * 7) % clusters]
            qv = unit([x + rnd.gauss(0, 0.05) for x in c])
            exact = sorted(range(n), key=lambda j: -sum(a * b for a, b in zip(qv, vecs[j], strict=True)))[:10]
            got = search(conn, struct.pack(f"<{dim}f", *qv), dim=dim)
            hit += len({j + 1 for j in exact} & set(got))
            total += 10
        conn.close()
    return hit / total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", type=int, nargs="+", default=[100000, 1000000])
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--dim", type=int, default=DIM)
    ap.add_argument("--recall-chunks", type=int, default=8000)
    ap.add_argument("--results", default=os.environ.get("HW_RESULTS_DIR", "/results"))
    ap.add_argument(
        "--tmp",
        default=os.environ.get("HW_BENCH_TMP") or None,
        help="where the temporary databases go (1M chunks take about 4 GB; default: the system temp)",
    )
    ap.add_argument("--print", action="store_true", help="show the numbers (local runs; not in public logs)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when a budget fails")
    args = ap.parse_args()

    probe = sqlite3.connect(":memory:")
    if not load_vec(probe):
        print("SKIP vector-bench (sqlite-vec is not available)")
        return 0
    values: dict[str, float] = {}
    for n in args.chunks:
        name = {100000: "p95-100k", 1000000: "p95-1m"}.get(n, f"p95-{n}")
        if args.tmp:
            os.makedirs(args.tmp, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=args.tmp) as d:
            t0 = time.time()
            conn = build(os.path.join(d, "v.db"), n, args.dim)
            values[f"build-s-{n}"] = round(time.time() - t0, 1)
            values[name] = round(p95_ms(conn, args.queries, args.dim), 1)
            values[f"db-mb-{n}"] = round(os.path.getsize(os.path.join(d, "v.db")) / 1e6, 1)
            conn.close()
    values["recall"] = round(recall_at_10(args.recall_chunks, args.dim), 3)

    ok = {}
    for name, val in values.items():
        if name in BUDGETS:
            ok[name] = val >= BUDGETS[name] if name == "recall" else val <= BUDGETS[name]
    for name in ok:
        line = f"{'PASS' if ok[name] else 'FAIL'} {name}"
        print(f"{line}: {values[name]} (budget {BUDGETS[name]})" if args.print else line)
    if args.print:
        print(json.dumps(values))
    try:
        os.makedirs(args.results, exist_ok=True)
        with open(os.path.join(args.results, f"vector-{time.strftime('%Y-%m-%d')}.json"), "w") as f:
            json.dump({"values": values, "budgets": BUDGETS, "pass": ok}, f, indent=1)
    except OSError:
        pass  # no results folder (a local run)
    return 1 if args.strict and not all(ok.values()) else 0


if __name__ == "__main__":
    sys.exit(main())

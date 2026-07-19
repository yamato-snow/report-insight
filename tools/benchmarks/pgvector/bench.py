"""pgvector benchmark modeled on report-insight's report_chunks schema.

Scales: 150k rows (~1 year of reports) then 500k rows, toward the 1M-row
re-evaluation threshold of ADR-001. vector(1024), HNSW + cosine, metadata
filters for property / category / date range as in docs/04_db_design.md.
Results and caveats: see README.md in this directory.
"""

import datetime
import json
import sys
import time

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

DSN = "host=127.0.0.1 port=55432 user=postgres password=bench dbname=bench"
DIM = 1024
N_PROPERTIES = 500
N_CATEGORIES = 10
QUERY_N = 100
WARMUP_N = 10
RECALL_QUERIES = 20
TOP_K = 10

rng = np.random.default_rng(42)


def gen_vectors(n):
    v = rng.standard_normal((n, DIM), dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


def load_rows(conn, n_rows, start_count):
    base = datetime.date(2024, 1, 1)
    batch = 20_000
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        with cur.copy(
            "COPY report_chunks (property_id, category, reported_at, embedding) "
            "FROM STDIN WITH (FORMAT BINARY)"
        ) as copy:
            copy.set_types(["int4", "int4", "date", "vector"])
            done = 0
            while done < n_rows:
                m = min(batch, n_rows - done)
                vecs = gen_vectors(m)
                props = rng.integers(1, N_PROPERTIES + 1, m)
                cats = rng.integers(1, N_CATEGORIES + 1, m)
                days = rng.integers(0, 730, m)
                for i in range(m):
                    copy.write_row(
                        (
                            int(props[i]),
                            int(cats[i]),
                            base + datetime.timedelta(days=int(days[i])),
                            vecs[i],
                        )
                    )
                done += m
                print(f"  loaded {start_count + done:,}", file=sys.stderr, flush=True)
    return time.perf_counter() - t0


def build_index(conn):
    with conn.cursor() as cur:
        cur.execute("DROP INDEX IF EXISTS report_chunks_embedding_idx")
        cur.execute("SET maintenance_work_mem = '5GB'")
        cur.execute("SET max_parallel_maintenance_workers = 4")
        t0 = time.perf_counter()
        cur.execute(
            "CREATE INDEX report_chunks_embedding_idx ON report_chunks "
            "USING hnsw (embedding vector_cosine_ops)"
        )
        build_s = time.perf_counter() - t0
        cur.execute(
            "SELECT pg_size_pretty(pg_relation_size('report_chunks_embedding_idx')),"
            " pg_size_pretty(pg_table_size('report_chunks'))"
        )
        idx_size, tbl_size = cur.fetchone()
    return build_s, idx_size, tbl_size


def pct(lat, p):
    return float(np.percentile(np.array(lat) * 1000, p))


def run_latency(conn, sql, param_fn, n=QUERY_N):
    lat = []
    with conn.cursor() as cur:
        for i in range(n + WARMUP_N):
            params = param_fn()
            t0 = time.perf_counter()
            cur.execute(sql, params)
            cur.fetchall()
            dt = time.perf_counter() - t0
            if i >= WARMUP_N:
                lat.append(dt)
    return {
        "p50_ms": round(pct(lat, 50), 2),
        "p95_ms": round(pct(lat, 95), 2),
        "mean_ms": round(float(np.mean(lat) * 1000), 2),
    }


def run_recall(conn):
    """recall@10 of HNSW (default ef_search=40) vs exact scan."""
    hits = 0
    with conn.cursor() as cur:
        for _ in range(RECALL_QUERIES):
            q = gen_vectors(1)[0]
            cur.execute(
                "SELECT id FROM report_chunks ORDER BY embedding <=> %s LIMIT %s", (q, TOP_K)
            )
            approx = {r[0] for r in cur.fetchall()}
            cur.execute("BEGIN")
            cur.execute("SET LOCAL enable_indexscan = off")
            cur.execute(
                "SELECT id FROM report_chunks ORDER BY embedding <=> %s LIMIT %s", (q, TOP_K)
            )
            exact = {r[0] for r in cur.fetchall()}
            cur.execute("COMMIT")
            hits += len(approx & exact)
    return round(hits / (RECALL_QUERIES * TOP_K), 3)


def bench_scale(conn, label):
    res = {"scale": label}
    build_s, idx_size, tbl_size = build_index(conn)
    res["hnsw_build_s"] = round(build_s, 1)
    res["index_size"] = idx_size
    res["table_size"] = tbl_size

    def plain_params():
        q = gen_vectors(1)[0]
        return (q, q, TOP_K)

    res["knn"] = run_latency(
        conn,
        "SELECT id, 1 - (embedding <=> %s::vector) AS similarity "
        "FROM report_chunks ORDER BY embedding <=> %s::vector LIMIT %s",
        plain_params,
    )

    def filtered_params():
        q = gen_vectors(1)[0]
        return (q, int(rng.integers(1, N_PROPERTIES + 1)), "2025-01-01", q, TOP_K)

    res["knn_filtered"] = run_latency(
        conn,
        "SELECT id, 1 - (embedding <=> %s::vector) AS similarity "
        "FROM report_chunks "
        "WHERE property_id = %s AND reported_at >= %s "
        "ORDER BY embedding <=> %s::vector LIMIT %s",
        filtered_params,
    )

    return res


def main():
    results = []
    with psycopg.connect(DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS report_chunks")
            cur.execute(
                "CREATE TABLE report_chunks ("
                " id bigserial PRIMARY KEY,"
                " property_id int NOT NULL,"
                " category int NOT NULL,"
                " reported_at date NOT NULL,"
                " embedding vector(1024) NOT NULL)"
            )

        print("== loading 150k ==", file=sys.stderr, flush=True)
        t = load_rows(conn, 150_000, 0)
        print(f"load 150k: {t:.1f}s", file=sys.stderr, flush=True)
        results.append(bench_scale(conn, "150k"))
        print(json.dumps(results[-1], indent=2), file=sys.stderr, flush=True)

        print("== loading +350k ==", file=sys.stderr, flush=True)
        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS report_chunks_embedding_idx")
        t = load_rows(conn, 350_000, 150_000)
        print(f"load +350k: {t:.1f}s", file=sys.stderr, flush=True)
        with conn.cursor() as cur:
            cur.execute("VACUUM ANALYZE report_chunks")
        results.append(bench_scale(conn, "500k"))
        print(json.dumps(results[-1], indent=2), file=sys.stderr, flush=True)

    with open("bench_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
